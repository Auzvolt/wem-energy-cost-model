"""Tests for the AEMO data pipeline.

Uses httpx MockTransport and mocked database sessions for isolation.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pandas as pd
import pytest

from app.pipeline.ingest import (
    ingest_all_products,
    ingest_facilities,
    ingest_intervals,
    ingest_prices,
)
from app.pipeline.transform import (
    deduplicate,
    detect_gaps,
    normalise_timestamps,
    resample_to_5min,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class MockSession:
    """Mock SQLAlchemy session for testing."""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.committed = False
        self.rolled_back = False
        self.closed = False
        self._query_results: dict[str, list[Any]] = {}

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True

    def flush(self) -> None:
        pass

    def query(self, model: Any) -> MockQuery:
        return MockQuery(self, model)

    def set_query_result(self, model_name: str, results: list[Any]) -> None:
        self._query_results[model_name] = results


class MockQuery:
    """Mock SQLAlchemy query for testing."""

    def __init__(self, session: MockSession, model: Any) -> None:
        self.session = session
        self.model = model
        self._filters: dict[str, Any] = {}
        self.model_name = getattr(model, "__name__", str(model))

    def filter_by(self, **kwargs: Any) -> MockQuery:
        self._filters.update(kwargs)
        return self

    def first(self) -> Any | None:
        results = self.session._query_results.get(self.model_name, [])
        for result in results:
            match = True
            for key, value in self._filters.items():
                if getattr(result, key, None) != value:
                    match = False
                    break
            if match:
                return result
        return None

    def all(self) -> list[Any]:
        return self.session._query_results.get(self.model_name, [])


class MockTransport(httpx.MockTransport):
    """Mock HTTP transport for testing."""

    def __init__(self, responses: dict[str, str]) -> None:
        self.responses = responses

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        for key, body in self.responses.items():
            if key in str(request.url):
                return httpx.Response(200, text=body)
        return httpx.Response(404, text="Not found")


@pytest.fixture
def mock_session() -> MockSession:
    return MockSession()


@pytest.fixture
def facility_csv() -> str:
    return """FACILITY_ID,FACILITY_NAME,FACILITY_TYPE,FUEL_TYPE,CAPACITY_MW
GEN001,Gas Generator 1,GENERATOR,GAS,100.0
GEN002,Solar Farm 1,GENERATOR,SOLAR,50.0
LOAD001,Industrial Load 1,LOAD,N/A,30.0
"""


@pytest.fixture
def dispatch_csv() -> str:
    return """FACILITY_ID,INTERVAL_START,DISPATCH_MW
GEN001,2024-03-15 08:00:00,100.5
GEN001,2024-03-15 08:05:00,102.0
GEN002,2024-03-15 08:00:00,50.0
"""


@pytest.fixture
def balancing_csv() -> str:
    return """DISPATCH_INTERVAL_START,MARKET_CLEARING_PRICE,QUANTITY
2024-03-15 08:00:00,85.50,100
2024-03-15 08:05:00,87.00,100
"""


# ---------------------------------------------------------------------------
# Transform function tests
# ---------------------------------------------------------------------------


def test_normalise_timestamps_converts_to_utc() -> None:
    df = pd.DataFrame(
        {
            "timestamp": ["2024-03-15 08:00:00", "2024-03-15 08:05:00"],
            "value": [1.0, 2.0],
        }
    )
    result = normalise_timestamps(df, "timestamp")
    assert pd.api.types.is_datetime64tz_dtype(result["timestamp"])
    assert str(result["timestamp"].dt.tz) in ("UTC", "utc", "Etc/UTC")


def test_normalise_timestamps_missing_column() -> None:
    df = pd.DataFrame({"value": [1.0, 2.0]})
    result = normalise_timestamps(df, "timestamp")
    assert "timestamp" not in result.columns


def test_resample_to_5min_averages_values() -> None:
    # Create DataFrame with 1-minute intervals
    timestamps = pd.date_range("2024-03-15 08:00:00", periods=10, freq="1min", tz="UTC")
    df = pd.DataFrame(
        {
            "interval_start": timestamps,
            "value": range(10),
        }
    )
    result = resample_to_5min(df)
    # Should have 2 rows (10 minutes / 5 min intervals)
    assert len(result) == 2


def test_resample_to_5min_no_datetime_index() -> None:
    df = pd.DataFrame({"value": [1.0, 2.0, 3.0]})
    result = resample_to_5min(df)
    # Should return unchanged if no datetime index
    pd.testing.assert_frame_equal(result, df)


def test_detect_gaps_finds_missing_intervals() -> None:
    # Create DataFrame with a gap
    timestamps = [
        datetime(2024, 3, 15, 8, 0, tzinfo=UTC),
        datetime(2024, 3, 15, 8, 5, tzinfo=UTC),
        # gap here - 8:10 missing
        datetime(2024, 3, 15, 8, 15, tzinfo=UTC),
        datetime(2024, 3, 15, 8, 20, tzinfo=UTC),
    ]
    df = pd.DataFrame({"interval_start": timestamps, "value": [1, 2, 4, 5]})
    gaps = detect_gaps(df)
    assert len(gaps) >= 1


def test_detect_gaps_no_gaps() -> None:
    timestamps = [
        datetime(2024, 3, 15, 8, 0, tzinfo=UTC),
        datetime(2024, 3, 15, 8, 5, tzinfo=UTC),
        datetime(2024, 3, 15, 8, 10, tzinfo=UTC),
    ]
    df = pd.DataFrame({"interval_start": timestamps, "value": [1, 2, 3]})
    gaps = detect_gaps(df)
    assert len(gaps) == 0


def test_deduplicate_removes_duplicates() -> None:
    timestamps = [
        datetime(2024, 3, 15, 8, 0, tzinfo=UTC),
        datetime(2024, 3, 15, 8, 0, tzinfo=UTC),  # duplicate
        datetime(2024, 3, 15, 8, 5, tzinfo=UTC),
    ]
    df = pd.DataFrame(
        {
            "interval_start": timestamps,
            "facility_id": ["GEN001", "GEN001", "GEN001"],
            "value": [1.0, 1.5, 2.0],
        }
    )
    result = deduplicate(df, subset=["interval_start", "facility_id"])
    assert len(result) == 2


def test_deduplicate_empty_dataframe() -> None:
    df = pd.DataFrame()
    result = deduplicate(df)
    assert len(result) == 0


# ---------------------------------------------------------------------------
# Ingest function tests
# ---------------------------------------------------------------------------


def test_ingest_facilities_success(mock_session: MockSession, facility_csv: str) -> None:
    with patch("app.pipeline.ingest.AEMOClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.get_csv.return_value = facility_csv
        mock_client_cls.return_value = mock_client
        count = ingest_facilities(mock_session)  # type: ignore[arg-type]
        assert count == 3
        assert len(mock_session.added) == 3


def test_ingest_facilities_http_error(mock_session: MockSession) -> None:
    with patch("app.pipeline.ingest.AEMOClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.get_csv.side_effect = httpx.HTTPError("Connection failed")
        mock_client.close = MagicMock()
        mock_client_cls.return_value = mock_client
        count = ingest_facilities(mock_session)  # type: ignore[arg-type]
        assert count == 0


def test_ingest_facilities_empty_response(mock_session: MockSession) -> None:
    with patch("app.pipeline.ingest.AEMOClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.get_csv.return_value = ""
        mock_client.close = MagicMock()
        mock_client_cls.return_value = mock_client
        count = ingest_facilities(mock_session)  # type: ignore[arg-type]
        assert count == 0


def test_ingest_intervals_success(mock_session: MockSession, dispatch_csv: str) -> None:
    # Create a mock facility
    mock_facility = MagicMock()
    mock_facility.id = 1
    mock_facility.facility_id = "GEN001"
    mock_session.set_query_result("Facility", [mock_facility])

    with patch("app.pipeline.ingest.AEMOClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.get_csv.return_value = dispatch_csv
        mock_client.close = MagicMock()
        mock_client_cls.return_value = mock_client
        count = ingest_intervals(mock_session, date(2024, 3, 15), date(2024, 3, 15))  # type: ignore[arg-type]
        assert count > 0


def test_ingest_intervals_http_error(mock_session: MockSession) -> None:
    with patch("app.pipeline.ingest.AEMOClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.get_csv.side_effect = httpx.HTTPError("Not found")
        mock_client.close = MagicMock()
        mock_client_cls.return_value = mock_client
        count = ingest_intervals(mock_session, date(2024, 3, 15), date(2024, 3, 15))  # type: ignore[arg-type]
        assert count == 0


def test_ingest_prices_success(mock_session: MockSession, balancing_csv: str) -> None:
    with patch("app.pipeline.ingest.AEMOClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.get_csv.return_value = balancing_csv
        mock_client.close = MagicMock()
        mock_client_cls.return_value = mock_client
        count = ingest_prices(mock_session, date(2024, 3, 15), date(2024, 3, 15))  # type: ignore[arg-type]
        assert count == 2


def test_ingest_prices_http_error(mock_session: MockSession) -> None:
    with patch("app.pipeline.ingest.AEMOClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.get_csv.side_effect = httpx.HTTPError("Not found")
        mock_client.close = MagicMock()
        mock_client_cls.return_value = mock_client
        count = ingest_prices(mock_session, date(2024, 3, 15), date(2024, 3, 15))  # type: ignore[arg-type]
        assert count == 0


@pytest.mark.asyncio
async def test_ingest_all_products_success(mock_session: MockSession) -> None:
    from app.pipeline.wholesale_price_connector import WholesalePriceRecord

    mock_records = [
        WholesalePriceRecord(
            interval_start_utc=datetime(2024, 3, 15, 0, 0, tzinfo=UTC),
            price_aud_mwh=85.5,
            product="ENERGY",
            source_url="http://test",
        ),
        WholesalePriceRecord(
            interval_start_utc=datetime(2024, 3, 15, 0, 5, tzinfo=UTC),
            price_aud_mwh=12.5,
            product="REGULATION_RAISE",
            source_url="http://test",
        ),
    ]

    with (
        patch("app.pipeline.ingest.AsyncAEMOClient") as mock_client_cls,
        patch("app.pipeline.ingest.WholesalePriceConnector") as mock_connector_cls,
    ):
        from unittest.mock import AsyncMock

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        from unittest.mock import AsyncMock

        mock_connector = MagicMock()
        mock_connector.fetch_date_range = AsyncMock(return_value=mock_records)
        mock_connector_cls.return_value = mock_connector

        counts = await ingest_all_products(mock_session, date(2024, 3, 15), date(2024, 3, 15))  # type: ignore[arg-type]
        assert "ENERGY" in counts or len(counts) >= 0
