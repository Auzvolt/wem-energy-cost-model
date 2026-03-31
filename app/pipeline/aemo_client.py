"""AEMO WA Open Data API client — placeholder implementation."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import requests

from app import config

logger = logging.getLogger(__name__)

# Default timeout for all API requests (seconds)
REQUEST_TIMEOUT = 30


class AEMOClient:
    """Client for the AEMO WA Open Data portal (data.wa.aemo.com.au).

    This is a scaffold — endpoint paths and response schemas will be
    filled in once the API mapping (Issues #1–#3) is complete.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.base_url = (base_url or config.AEMO_API_BASE_URL).rstrip("/")
        self.api_key = api_key or config.AEMO_API_KEY
        self._session = requests.Session()
        if self.api_key:
            self._session.headers["Authorization"] = f"Bearer {self.api_key}"

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Perform a GET request and return the parsed JSON body."""
        url = f"{self.base_url}/{path.lstrip('/')}"
        logger.debug("GET %s params=%s", url, params)
        response = self._session.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()

    def fetch_wholesale_prices(
        self,
        start: date,
        end: date,
    ) -> list[dict[str, Any]]:
        """Fetch 5-minute wholesale energy prices for the given date range.

        TODO: implement once endpoint mapping (Issue #2) is complete.
        """
        raise NotImplementedError("Wholesale price endpoint not yet mapped.")

    def fetch_fcess_prices(
        self,
        start: date,
        end: date,
        product: str,
    ) -> list[dict[str, Any]]:
        """Fetch FCESS product prices for the given date range and product.

        Args:
            product: One of 'reg_raise', 'reg_lower', 'cont_raise', 'cont_lower', 'rocof'.

        TODO: implement once endpoint mapping (Issue #3) is complete.
        """
        raise NotImplementedError("FCESS price endpoint not yet mapped.")

    def fetch_capacity_prices(
        self,
        start: date,
        end: date,
    ) -> list[dict[str, Any]]:
        """Fetch Reserve Capacity Mechanism prices for the given date range.

        TODO: implement once endpoint mapping (Issue #4) is complete.
        """
        raise NotImplementedError("Capacity price endpoint not yet mapped.")
