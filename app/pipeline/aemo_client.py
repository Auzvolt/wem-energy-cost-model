"""AEMO WA Open Data API client.

Provides both synchronous (AEMOClient) and async (AsyncAEMOClient) interfaces
for fetching CSV data from the AEMO WA public data portal (data.wa.aemo.com.au).

Public data requires no authentication.
APIM REST endpoints require an Ocp-Apim-Subscription-Key header.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import httpx

from app import config

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30.0


class AEMOClient:
    """Synchronous client for the AEMO WA Open Data portal.

    Public data (CSV files) requires no authentication.
    APIM REST endpoints require a subscription key in the Authorization header.

    Data URL patterns (post-reform, October 2023+):
    - Wholesale/balancing prices: /public/public-data/dataFiles/balancing-summary/
    - FCESS prices:               /public/public-data/dataFiles/fcess-prices/{product}/
    - Capacity credits:           /public/public-data/dataFiles/capacity-credits/

    File naming convention: {category}_{YYYYMMDD}.csv
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.base_url = (base_url or config.AEMO_API_BASE_URL).rstrip("/")
        self.api_key = api_key or config.AEMO_API_KEY
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Ocp-Apim-Subscription-Key"] = self.api_key
        self._client = httpx.Client(
            headers=headers,
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
        )

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        """Perform a GET request and return the parsed JSON body."""
        logger.debug("GET JSON %s params=%s", url, params)
        response = self._client.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def get_csv(self, url: str, params: dict[str, Any] | None = None) -> str:
        """Perform a GET request and return the raw CSV text."""
        logger.debug("GET CSV %s params=%s", url, params)
        response = self._client.get(url, params=params)
        response.raise_for_status()
        result: str = response.text
        return result

    # ------------------------------------------------------------------
    # Legacy private aliases (keep for backwards compat)
    # ------------------------------------------------------------------
    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self.get_json(path, params)

    def _get_csv(self, path: str, params: dict[str, Any] | None = None) -> str:
        return self.get_csv(path, params)

    # ------------------------------------------------------------------
    # Placeholder high-level methods (implemented by connectors in #11-#13)
    # ------------------------------------------------------------------

    def fetch_wholesale_prices(self, start: date, end: date) -> list[dict[str, Any]]:
        """Fetch 5-min wholesale energy prices. Implemented by WholesalePriceConnector (#11)."""
        raise NotImplementedError(
            "Use WholesalePriceConnector from app.pipeline.wholesale_price_connector"
        )

    def fetch_fcess_prices(self, start: date, end: date, product: str) -> list[dict[str, Any]]:
        """Fetch FCESS product prices. Implemented by WholesalePriceConnector (#11)."""
        raise NotImplementedError(
            "Use WholesalePriceConnector from app.pipeline.wholesale_price_connector"
        )

    def fetch_capacity_prices(self, start: date, end: date) -> list[dict[str, Any]]:
        """Fetch Reserve Capacity prices. Placeholder for #13."""
        raise NotImplementedError("Capacity price endpoint not yet implemented.")

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> AEMOClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


class AsyncAEMOClient:
    """Async client for the AEMO WA Open Data portal.

    Prefer this for use in async contexts (FastAPI, async data pipelines).
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.base_url = (base_url or config.AEMO_API_BASE_URL).rstrip("/")
        self.api_key = api_key or config.AEMO_API_KEY
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Ocp-Apim-Subscription-Key"] = self.api_key
        self._client = httpx.AsyncClient(
            headers=headers,
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
        )

    async def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        """Perform an async GET request and return parsed JSON."""
        logger.debug("ASYNC GET JSON %s params=%s", url, params)
        response = await self._client.get(url, params=params)
        response.raise_for_status()
        return response.json()

    async def get_csv(self, url: str, params: dict[str, Any] | None = None) -> str:
        """Perform an async GET request and return raw CSV text."""
        logger.debug("ASYNC GET CSV %s params=%s", url, params)
        response = await self._client.get(url, params=params)
        response.raise_for_status()
        result: str = response.text
        return result

    async def aclose(self) -> None:
        """Close the underlying async HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> AsyncAEMOClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()
