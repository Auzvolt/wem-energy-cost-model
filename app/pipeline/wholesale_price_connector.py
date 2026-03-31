"""WEM wholesale price data connector.

Fetches 5-minute Market Clearing Prices from the AEMO WA public data portal
(data.wa.aemo.com.au) for both energy and FCESS products.

Post-reform (Oct 2023+):
  - Energy: 5-min dispatch interval MCPs
  - FCESS: 5-min MCPs for 5 products (Reg Raise/Lower, CR Raise/Lower, RCS)
  - Data published as CSV files under:
    https://data.wa.aemo.com.au/public/public-data/dataFiles/

All timestamps in AEMO CSV files are in AWST (UTC+8).
Stored in the database as UTC.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone

import httpx
import pandas as pd

from app.pipeline.aemo_client import AsyncAEMOClient

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://data.wa.aemo.com.au/public/public-data/dataFiles"

BALANCING_SUMMARY_PATH = "balancing-summary"

# Five FCESS products (post-reform naming)
FCESS_PRODUCTS: tuple[str, ...] = (
    "REGULATION_RAISE",
    "REGULATION_LOWER",
    "CONTINGENCY_RESERVE_RAISE",
    "CONTINGENCY_RESERVE_LOWER",
    "ROCOF_CONTROL_SERVICE",
)

# AWST = UTC+8
_AWST = timezone(timedelta(hours=8))


# ---------------------------------------------------------------------------
# Data record
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WholesalePriceRecord:
    """A single 5-minute wholesale price observation."""

    interval_start_utc: datetime
    price_aud_mwh: float
    product: str  # "ENERGY" or one of FCESS_PRODUCTS
    source_url: str


# ---------------------------------------------------------------------------
# URL builders
# ---------------------------------------------------------------------------


def balancing_summary_url(trading_date: date) -> str:
    """Build the URL for the energy balancing summary CSV."""
    date_str = trading_date.strftime("%Y%m%d")
    return f"{_BASE_URL}/{BALANCING_SUMMARY_PATH}/BalancingSummary_{date_str}.csv"


def fcess_price_url(trading_date: date, product: str) -> str:
    """Build the URL for a FCESS product price CSV."""
    date_str = trading_date.strftime("%Y%m%d")
    product_slug = product.lower().replace("_", "-")
    return f"{_BASE_URL}/fcess-prices/{product_slug}/FCESSPrice_{product}_{date_str}.csv"


# ---------------------------------------------------------------------------
# CSV parsers
# ---------------------------------------------------------------------------


def _find_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """Return the first candidate column name found in df.columns."""
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _parse_awst_timestamp(raw: object) -> datetime | None:
    """Parse an AWST timestamp string and return UTC datetime."""
    if raw is None:
        return None
    if isinstance(raw, float) and pd.isna(raw):
        return None

    s = str(raw).strip()
    if not s:
        return None

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%Y-%m-%d",
    ):
        try:
            dt_awst = datetime.strptime(s, fmt).replace(tzinfo=_AWST)
            return dt_awst.astimezone(UTC)
        except ValueError:
            continue

    log.debug("Could not parse timestamp: %r", s)
    return None


def parse_balancing_csv(csv_text: str, source_url: str) -> list[WholesalePriceRecord]:
    """Parse a balancing summary CSV into WholesalePriceRecord objects.

    Expected post-reform columns (names may vary):
      DISPATCH_INTERVAL_START, MARKET_CLEARING_PRICE, ...
    """
    if not csv_text.strip():
        return []

    try:
        df = pd.read_csv(pd.io.common.StringIO(csv_text), skipinitialspace=True)
    except Exception as exc:
        log.warning("Failed to parse balancing CSV %s: %s", source_url, exc)
        return []

    df.columns = [c.strip().upper() for c in df.columns]

    price_col = _find_column(df, ["MARKET_CLEARING_PRICE", "MCP", "BALANCING_PRICE", "PRICE"])
    ts_col = _find_column(
        df,
        [
            "DISPATCH_INTERVAL_START",
            "INTERVAL_START",
            "TRADING_INTERVAL_START",
            "TRADING_DATE",
        ],
    )

    if price_col is None:
        cols = list(df.columns)
        log.warning("No price column in balancing CSV %s. Cols: %s", source_url, cols)
        return []

    records: list[WholesalePriceRecord] = []
    for _, row in df.iterrows():
        try:
            price = float(row[price_col])
        except (ValueError, TypeError):
            continue

        ts = _parse_awst_timestamp(row.get(ts_col) if ts_col else None)
        if ts is None:
            continue

        records.append(
            WholesalePriceRecord(
                interval_start_utc=ts,
                price_aud_mwh=price,
                product="ENERGY",
                source_url=source_url,
            )
        )

    return records


def parse_fcess_csv(
    csv_text: str,
    product: str,
    source_url: str,
) -> list[WholesalePriceRecord]:
    """Parse a FCESS product price CSV into WholesalePriceRecord objects."""
    if not csv_text.strip():
        return []

    try:
        df = pd.read_csv(pd.io.common.StringIO(csv_text), skipinitialspace=True)
    except Exception as exc:
        log.warning("Failed to parse FCESS CSV %s: %s", source_url, exc)
        return []

    df.columns = [c.strip().upper() for c in df.columns]

    price_col = _find_column(df, ["MARKET_CLEARING_PRICE", "MCP", "CLEARING_PRICE", "PRICE"])
    ts_col = _find_column(
        df,
        ["DISPATCH_INTERVAL_START", "INTERVAL_START", "TRADING_DATE"],
    )

    if price_col is None:
        log.warning("No price column in FCESS CSV %s. Columns: %s", source_url, list(df.columns))
        return []

    records: list[WholesalePriceRecord] = []
    for _, row in df.iterrows():
        try:
            price = float(row[price_col])
        except (ValueError, TypeError):
            continue

        ts = _parse_awst_timestamp(row.get(ts_col) if ts_col else None)
        if ts is None:
            continue

        records.append(
            WholesalePriceRecord(
                interval_start_utc=ts,
                price_aud_mwh=price,
                product=product,
                source_url=source_url,
            )
        )

    return records


# ---------------------------------------------------------------------------
# Main connector
# ---------------------------------------------------------------------------


class WholesalePriceConnector:
    """Fetches WEM wholesale price data from the AEMO public data portal.

    Supports full date-range fetches and incremental (new-only) fetches.

    Example::

        async with AsyncAEMOClient() as client:
            connector = WholesalePriceConnector(client)
            records = await connector.fetch_date_range(
                start=date(2024, 1, 1),
                end=date(2024, 1, 7),
                include_fcess=True,
            )
            df = connector.to_dataframe(records)
    """

    def __init__(self, client: AsyncAEMOClient | None = None) -> None:
        self._client = client or AsyncAEMOClient()
        self._owns_client = client is None

    async def fetch_date_range(
        self,
        start: date,
        end: date,
        include_fcess: bool = True,
    ) -> list[WholesalePriceRecord]:
        """Fetch energy (and optionally FCESS) prices for a date range.

        Args:
            start: First trading date (inclusive).
            end: Last trading date (inclusive).
            include_fcess: If True, also fetches all 5 FCESS product prices.

        Returns:
            Flat list of WholesalePriceRecord objects.
        """
        all_records: list[WholesalePriceRecord] = []
        dates = _date_range(start, end)
        log.info(
            "Fetching %d days of WEM prices (%s to %s, fcess=%s)",
            len(dates),
            start,
            end,
            include_fcess,
        )

        for trading_date in dates:
            records = await self._fetch_energy_prices(trading_date)
            all_records.extend(records)

            if include_fcess:
                for product in FCESS_PRODUCTS:
                    fcess = await self._fetch_fcess_prices(trading_date, product)
                    all_records.extend(fcess)

        log.info("Fetched %d price records total", len(all_records))
        return all_records

    async def fetch_incremental(
        self,
        last_fetched_date: date | None = None,
        include_fcess: bool = True,
    ) -> list[WholesalePriceRecord]:
        """Fetch only data newer than last_fetched_date.

        AEMO typically publishes data 1 business day after trading.
        If last_fetched_date is None, fetches the last 7 days.

        Args:
            last_fetched_date: Most recent date already stored in the DB.
                               Pass None to fetch the last 7 days.
            include_fcess: Whether to include FCESS prices.

        Returns:
            List of new WholesalePriceRecord objects (may be empty).
        """
        today = date.today()
        available_through = today - timedelta(days=1)  # data available next day

        if last_fetched_date is None:
            start = today - timedelta(days=7)
        else:
            start = last_fetched_date + timedelta(days=1)

        if start > available_through:
            log.info("No new WEM price data to fetch (last_fetched=%s)", last_fetched_date)
            return []

        return await self.fetch_date_range(start, available_through, include_fcess)

    async def close(self) -> None:
        """Close the underlying HTTP client if owned by this connector."""
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> WholesalePriceConnector:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_energy_prices(self, trading_date: date) -> list[WholesalePriceRecord]:
        url = balancing_summary_url(trading_date)
        try:
            csv_text = await self._client.get_csv(url)
            return parse_balancing_csv(csv_text, url)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                log.debug("No energy data for %s (404)", trading_date)
            else:
                log.warning("HTTP error fetching energy prices for %s: %s", trading_date, exc)
        except Exception as exc:
            log.warning("Unexpected error fetching energy prices for %s: %s", trading_date, exc)
        return []

    async def _fetch_fcess_prices(
        self, trading_date: date, product: str
    ) -> list[WholesalePriceRecord]:
        url = fcess_price_url(trading_date, product)
        try:
            csv_text = await self._client.get_csv(url)
            return parse_fcess_csv(csv_text, product, url)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                log.debug("No FCESS data for %s %s (404)", product, trading_date)
            else:
                log.warning("HTTP error fetching FCESS %s for %s: %s", product, trading_date, exc)
        except Exception as exc:
            log.warning("Unexpected error fetching FCESS %s for %s: %s", product, trading_date, exc)
        return []

    @staticmethod
    def to_dataframe(records: list[WholesalePriceRecord]) -> pd.DataFrame:
        """Convert records to a pandas DataFrame.

        Columns: interval_start_utc, product, price_aud_mwh, source_url
        """
        if not records:
            return pd.DataFrame(
                columns=["interval_start_utc", "product", "price_aud_mwh", "source_url"]
            )
        return pd.DataFrame(
            [
                {
                    "interval_start_utc": r.interval_start_utc,
                    "product": r.product,
                    "price_aud_mwh": r.price_aud_mwh,
                    "source_url": r.source_url,
                }
                for r in records
            ]
        )


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _date_range(start: date, end: date) -> list[date]:
    """Return list of dates from start to end inclusive."""
    dates: list[date] = []
    current = start
    while current <= end:
        dates.append(current)
        current += timedelta(days=1)
    return dates
