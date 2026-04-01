"""Tests for AEMOClient and AsyncAEMOClient HTTP retry / rate-limit handling.

Uses httpx transports to mock responses without hitting real AEMO endpoints.

Retry rules (from implementation):
- Transport errors → retry up to 3 attempts (exponential backoff)
- HTTP 5xx → retry up to 3 attempts
- HTTP 429 → sleep Retry-After seconds, then retry up to 3 attempts
- HTTP 4xx (other than 429) → raise immediately, no retry
"""

from __future__ import annotations

import asyncio
from collections import deque
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from app.pipeline.aemo_client import AEMOClient, AsyncAEMOClient, _should_retry_exception

# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------


def _json_resp(status: int, body: Any = None, headers: dict | None = None) -> httpx.Response:
    import json

    content = json.dumps(body or {}).encode()
    return httpx.Response(
        status_code=status,
        content=content,
        headers={"content-type": "application/json", **(headers or {})},
        request=httpx.Request("GET", "https://test.aemo.example/data"),
    )


def _text_resp(status: int, text: str = "", headers: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        content=text.encode(),
        headers={"content-type": "text/plain", **(headers or {})},
        request=httpx.Request("GET", "https://test.aemo.example/data"),
    )


# ---------------------------------------------------------------------------
# Mock transports
# ---------------------------------------------------------------------------


class SequentialTransport(httpx.BaseTransport):
    """Return pre-defined responses in FIFO order."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses: deque[httpx.Response] = deque(responses)
        self.call_count = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.call_count += 1
        if not self._responses:
            raise AssertionError(f"Unexpected extra request (call #{self.call_count})")
        resp = self._responses.popleft()
        # Attach the real request so raise_for_status works
        resp = httpx.Response(
            status_code=resp.status_code,
            content=resp.content,
            headers=dict(resp.headers),
            request=request,
        )
        return resp


class AsyncSequentialTransport(httpx.AsyncBaseTransport):
    """Async version of SequentialTransport."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses: deque[httpx.Response] = deque(responses)
        self.call_count = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.call_count += 1
        if not self._responses:
            raise AssertionError(f"Unexpected extra async request (call #{self.call_count})")
        resp = self._responses.popleft()
        resp = httpx.Response(
            status_code=resp.status_code,
            content=resp.content,
            headers=dict(resp.headers),
            request=request,
        )
        return resp


def _sync_client(responses: list[httpx.Response]) -> tuple[AEMOClient, SequentialTransport]:
    transport = SequentialTransport(responses)
    client = AEMOClient.__new__(AEMOClient)
    client.base_url = "https://test.aemo.example"
    client.api_key = None  # type: ignore[assignment]
    client._client = httpx.Client(transport=transport)
    return client, transport


def _async_client(
    responses: list[httpx.Response],
) -> tuple[AsyncAEMOClient, AsyncSequentialTransport]:
    transport = AsyncSequentialTransport(responses)
    client = AsyncAEMOClient.__new__(AsyncAEMOClient)
    client.base_url = "https://test.aemo.example"
    client.api_key = None  # type: ignore[assignment]
    client._client = httpx.AsyncClient(transport=transport)
    return client, transport


def run(coro: Any) -> Any:
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# _should_retry_exception unit tests
# ---------------------------------------------------------------------------


def test_retry_predicate_transport_error() -> None:
    assert _should_retry_exception(httpx.TransportError("net")) is True


def test_retry_predicate_5xx() -> None:
    req = httpx.Request("GET", "https://example.com")
    resp = httpx.Response(503, request=req)
    exc = httpx.HTTPStatusError("503", request=req, response=resp)
    assert _should_retry_exception(exc) is True


def test_retry_predicate_429() -> None:
    req = httpx.Request("GET", "https://example.com")
    resp = httpx.Response(429, request=req)
    exc = httpx.HTTPStatusError("429", request=req, response=resp)
    assert _should_retry_exception(exc) is True


def test_retry_predicate_404_false() -> None:
    req = httpx.Request("GET", "https://example.com")
    resp = httpx.Response(404, request=req)
    exc = httpx.HTTPStatusError("404", request=req, response=resp)
    assert _should_retry_exception(exc) is False


def test_retry_predicate_400_false() -> None:
    req = httpx.Request("GET", "https://example.com")
    resp = httpx.Response(400, request=req)
    exc = httpx.HTTPStatusError("400", request=req, response=resp)
    assert _should_retry_exception(exc) is False


def test_retry_predicate_other_exception_false() -> None:
    assert _should_retry_exception(ValueError("other")) is False


# ---------------------------------------------------------------------------
# Sync AEMOClient tests
# ---------------------------------------------------------------------------


def test_sync_success_first_attempt() -> None:
    client, transport = _sync_client([_json_resp(200, {"ok": True})])
    result = client.get_json("https://test.aemo.example/data")
    assert result == {"ok": True}
    assert transport.call_count == 1


def test_sync_5xx_retries_then_succeeds() -> None:
    with patch("time.sleep"):
        client, transport = _sync_client(
            [
                _text_resp(503, "unavailable"),
                _text_resp(503, "unavailable"),
                _json_resp(200, {"data": "ok"}),
            ]
        )
        result = client.get_json("https://test.aemo.example/data")
    assert result == {"data": "ok"}
    assert transport.call_count == 3


def test_sync_5xx_exhausts_retries_raises() -> None:
    with patch("time.sleep"):
        client, transport = _sync_client(
            [
                _text_resp(503),
                _text_resp(503),
                _text_resp(503),
            ]
        )
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            client.get_json("https://test.aemo.example/data")
    assert exc_info.value.response.status_code == 503
    assert transport.call_count == 3


def test_sync_429_sleeps_retry_after_then_succeeds() -> None:
    sleep_calls: list[int] = []

    with patch("time.sleep", side_effect=sleep_calls.append):
        client, transport = _sync_client(
            [
                _json_resp(429, {}, headers={"Retry-After": "5"}),
                _json_resp(429, {}, headers={"Retry-After": "5"}),
                _json_resp(200, {"result": "data"}),
            ]
        )
        result = client.get_json("https://test.aemo.example/data")

    assert result == {"result": "data"}
    # time.sleep called for Retry-After (5s) plus tenacity backoff between retries
    assert sleep_calls.count(5) == 2  # two 429 responses, each triggers Retry-After=5 sleep
    assert transport.call_count == 3


def test_sync_404_raises_immediately_no_retry() -> None:
    client, transport = _sync_client([_json_resp(404, {"error": "not found"})])
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        client.get_json("https://test.aemo.example/missing")
    assert exc_info.value.response.status_code == 404
    # Only one request should have been made — no retry on 4xx
    assert transport.call_count == 1


def test_sync_400_raises_immediately_no_retry() -> None:
    client, transport = _sync_client([_json_resp(400)])
    with pytest.raises(httpx.HTTPStatusError):
        client.get_json("https://test.aemo.example/bad")
    assert transport.call_count == 1


def test_sync_transport_error_retries_then_succeeds() -> None:
    call_count = 0

    class FlakyTransport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise httpx.TransportError("network glitch")
            return httpx.Response(
                200,
                content=b'{"recovered": true}',
                headers={"content-type": "application/json"},
                request=request,
            )

    with patch("time.sleep"):
        client = AEMOClient.__new__(AEMOClient)
        client.base_url = "https://test.aemo.example"
        client.api_key = None  # type: ignore[assignment]
        client._client = httpx.Client(transport=FlakyTransport())
        result = client.get_json("https://test.aemo.example/data")

    assert result == {"recovered": True}
    assert call_count == 3


def test_sync_get_csv_returns_text() -> None:
    client, _ = _sync_client([_text_resp(200, "col1,col2\nval1,val2\n")])
    result = client.get_csv("https://test.aemo.example/data.csv")
    assert "col1" in result
    assert "val1" in result


# ---------------------------------------------------------------------------
# Async AsyncAEMOClient tests
# ---------------------------------------------------------------------------


def test_async_success_first_attempt() -> None:
    client, transport = _async_client([_json_resp(200, {"ok": True})])
    result = run(client.get_json("https://test.aemo.example/data"))
    assert result == {"ok": True}
    assert transport.call_count == 1
    run(client.aclose())


def test_async_503_retries_then_succeeds() -> None:
    async def _run() -> Any:
        async def fake_sleep(_: float) -> None:
            pass

        with patch("app.pipeline.aemo_client.asyncio.sleep", fake_sleep), patch("time.sleep"):
                client, transport = _async_client(
                    [
                        _text_resp(503),
                        _text_resp(503),
                        _json_resp(200, {"data": "ok"}),
                    ]
                )
                result = await client.get_json("https://test.aemo.example/data")
        await client.aclose()
        return result, transport.call_count

    result, count = run(_run())
    assert result == {"data": "ok"}
    assert count == 3


def test_async_429_honours_retry_after() -> None:
    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    async def _run() -> Any:
        with patch("app.pipeline.aemo_client.asyncio.sleep", fake_sleep), patch("time.sleep"):
                client, transport = _async_client(
                    [
                        _json_resp(429, {}, headers={"Retry-After": "7"}),
                        _json_resp(429, {}, headers={"Retry-After": "7"}),
                        _json_resp(200, {"result": "async_data"}),
                    ]
                )
                result = await client.get_json("https://test.aemo.example/data")
        await client.aclose()
        return result, transport.call_count

    result, count = run(_run())
    assert result == {"result": "async_data"}
    # async sleep called for Retry-After (7s); tenacity backoff uses time.sleep separately
    assert sleep_calls.count(7) == 2  # two 429 responses, each triggers Retry-After=7
    assert count == 3


def test_async_404_raises_immediately() -> None:
    client, transport = _async_client([_json_resp(404)])
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        run(client.get_json("https://test.aemo.example/missing"))
    assert exc_info.value.response.status_code == 404
    assert transport.call_count == 1
    run(client.aclose())


def test_async_transport_error_retries() -> None:
    call_count = 0

    class FlakyAsync(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise httpx.TransportError("async glitch")
            return httpx.Response(
                200,
                content=b'{"recovered": true}',
                headers={"content-type": "application/json"},
                request=request,
            )

    async def _run() -> Any:
        with patch("time.sleep"):
            client = AsyncAEMOClient.__new__(AsyncAEMOClient)
            client.base_url = "https://test.aemo.example"
            client.api_key = None  # type: ignore[assignment]
            client._client = httpx.AsyncClient(transport=FlakyAsync())
            result = await client.get_json("https://test.aemo.example/data")
            await client.aclose()
        return result

    result = run(_run())
    assert result == {"recovered": True}
    assert call_count == 3
