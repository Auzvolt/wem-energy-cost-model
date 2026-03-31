"""AEMO WA data pipeline — wholesale energy price connector.

Fetches 5-minute wholesale energy trading interval prices from the
AEMO WA public data portal (data.wa.aemo.com.au) and upserts them
into the ``market_prices`` table.

Usage (CLI)::

    python -m pipeline.aemo_wholesale \\
        --start 2024-01-01 \\
        --end   2024-01-31 \\
        --settlement-point SW1

Environment variables:
    DATABASE_URL  – SQLAlchemy async URL (defaults to SQLite dev.db)
    AEMO_WA_BASE_URL – Override API base (default: https://data.wa.aemo.com.au)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import urllib.error
import urllib.request
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = "https://data.wa.aemo.com.au"
# AEMO WA public API path for trading interval prices
_TRADING_PRICE_PATH = (
    "/public/public-data/datafiles/trading-price/trading-price-{year}{month:02d}.csv"
)

# Seconds between retries on transient failures
_RETRY_DELAYS: tuple[float, ...] = (2.0, 5.0, 15.0)

# Maximum rows per upsert batch
_BATCH_SIZE = 5000

PRODUCT_ENERGY = "ENERGY"


# ---------------------------------------------------------------------------
# HTTP fetching (stdlib urllib, async via to_thread)
# ---------------------------------------------------------------------------


def _fetch_url_sync(url: str, timeout: float = 60.0) -> str:
    """Synchronous URL fetch using stdlib urllib. Returns response text."""
    req = urllib.request.Request(url, headers={"User-Agent": "wem-energy-cost-model/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.read().decode("utf-8")


async def _fetch_monthly_csv(
    base_url: str,
    year: int,
    month: int,
) -> str:
    """Download the monthly trading-price CSV. Retries on transient errors."""
    url = base_url.rstrip("/") + _TRADING_PRICE_PATH.format(year=year, month=month)
    last_exc: Exception | None = None
    delays = (*_RETRY_DELAYS, None)
    for attempt, delay in enumerate(delays, start=1):
        try:
            logger.debug("Fetching %s (attempt %d)", url, attempt)
            text_data = await asyncio.to_thread(_fetch_url_sync, url)
            return text_data
        except (urllib.error.URLError, OSError) as exc:
            last_exc = exc
            logger.warning("Attempt %d failed for %s: %s", attempt, url, exc)
            if delay is not None:
                await asyncio.sleep(float(delay))
    raise RuntimeError(f"Failed to fetch {url} after {len(delays)} attempts") from last_exc


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------


def _parse_trading_price_csv(
    csv_text: str,
    settlement_point: str,
) -> list[dict[str, Any]]:
    """Parse AEMO WA monthly trading price CSV into list of dicts.

    Expected columns (AEMO WA format)::
        Trading Date, Trading Interval, Trading Price ($/MWh), Settlement Point

    Returns a list of dicts with keys:
        interval_start  datetime (UTC-aware, converted from AWST +08:00)
        settlement_point str
        product          str  ("ENERGY")
        price_aud_mwh   float
        source           str
        ingested_at      datetime
    """
    import csv
    import io
    from zoneinfo import ZoneInfo

    awst = ZoneInfo("Australia/Perth")
    rows: list[dict[str, Any]] = []
    ingested_at = datetime.now(UTC)

    reader = csv.DictReader(io.StringIO(csv_text))
    for raw in reader:
        # Normalise column names (strip whitespace)
        row = {k.strip(): v.strip() for k, v in raw.items() if k is not None}

        # Filter by settlement point if specified
        sp = row.get("Settlement Point", row.get("settlement_point", ""))
        if settlement_point and sp.upper() != settlement_point.upper():
            continue

        date_str = row.get("Trading Date", row.get("trading_date", ""))
        interval_str = row.get("Trading Interval", row.get("trading_interval", ""))
        price_str = row.get("Trading Price ($/MWh)", row.get("trading_price", ""))

        if not date_str or not interval_str or not price_str:
            continue

        try:
            trading_date = date.fromisoformat(date_str)
            interval_num = int(interval_str)  # 1-based, 5-min each
            price = float(price_str)
        except (ValueError, TypeError):
            continue

        # Convert interval number to AWST datetime, then UTC
        offset_minutes = (interval_num - 1) * 5
        naive_dt = datetime(
            trading_date.year,
            trading_date.month,
            trading_date.day,
            offset_minutes // 60,
            offset_minutes % 60,
        )
        aware_dt = naive_dt.replace(tzinfo=awst).astimezone(UTC)

        rows.append(
            {
                "interval_start": aware_dt,
                "settlement_point": sp.upper() or settlement_point.upper(),
                "product": PRODUCT_ENERGY,
                "price_aud_mwh": price,
                "source": "aemo_api",
                "ingested_at": ingested_at,
            }
        )

    return rows


# ---------------------------------------------------------------------------
# Database upsert
# ---------------------------------------------------------------------------


async def _upsert_prices(session: AsyncSession, rows: list[dict[str, Any]]) -> int:
    """Bulk-upsert market price rows. Returns number of rows written."""
    if not rows:
        return 0

    # Detect dialect for correct upsert syntax
    bind = session.get_bind()
    dialect = bind.dialect.name if bind is not None else "sqlite"

    inserted = 0
    for i in range(0, len(rows), _BATCH_SIZE):
        batch = rows[i : i + _BATCH_SIZE]
        if dialect == "postgresql":
            stmt = text(
                """
                INSERT INTO market_prices
                    (interval_start, settlement_point, product,
                     price_aud_mwh, source, ingested_at)
                VALUES
                    (:interval_start, :settlement_point, :product,
                     :price_aud_mwh, :source, :ingested_at)
                ON CONFLICT (interval_start, settlement_point, product)
                DO UPDATE SET
                    price_aud_mwh = EXCLUDED.price_aud_mwh,
                    source        = EXCLUDED.source,
                    ingested_at   = EXCLUDED.ingested_at
                """
            )
        else:
            # SQLite — identical syntax but lowercase excluded
            stmt = text(
                """
                INSERT INTO market_prices
                    (interval_start, settlement_point, product,
                     price_aud_mwh, source, ingested_at)
                VALUES
                    (:interval_start, :settlement_point, :product,
                     :price_aud_mwh, :source, :ingested_at)
                ON CONFLICT (interval_start, settlement_point, product)
                DO UPDATE SET
                    price_aud_mwh = excluded.price_aud_mwh,
                    source        = excluded.source,
                    ingested_at   = excluded.ingested_at
                """
            )
        await session.execute(stmt, batch)
        inserted += len(batch)

    await session.commit()
    return inserted


# ---------------------------------------------------------------------------
# Incremental helper
# ---------------------------------------------------------------------------


async def _last_ingested_date(session: AsyncSession, settlement_point: str) -> date | None:
    """Return the most recent interval_start date in market_prices for this SP."""
    result = await session.execute(
        text(
            """
            SELECT MAX(interval_start) FROM market_prices
            WHERE settlement_point = :sp AND product = 'ENERGY'
            """
        ),
        {"sp": settlement_point.upper()},
    )
    row = result.scalar()
    if row is None:
        return None
    if isinstance(row, str):
        row = datetime.fromisoformat(row)
    return row.date() if isinstance(row, datetime) else None  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Main ingestion function (public API)
# ---------------------------------------------------------------------------


async def ingest_wholesale_prices(
    start: date,
    end: date,
    settlement_point: str = "SW1",
    base_url: str = DEFAULT_BASE_URL,
    incremental: bool = False,
) -> dict[str, int]:
    """Fetch and store AEMO WA wholesale energy prices for a date range.

    Args:
        start: First date to fetch (inclusive).
        end: Last date to fetch (inclusive).
        settlement_point: WEM settlement point code (e.g. "SW1").
        base_url: AEMO WA data portal base URL.
        incremental: If True, skip months already fully ingested.

    Returns:
        Dict with ``{"months_fetched": N, "rows_inserted": M}``.
    """
    async with AsyncSessionLocal() as session:
        if incremental:
            last = await _last_ingested_date(session, settlement_point)
            if last is not None and last >= end:
                logger.info("Already up to date (last: %s). Skipping.", last)
                return {"months_fetched": 0, "rows_inserted": 0}
            if last is not None:
                start = max(
                    start,
                    (last.replace(day=1) + timedelta(days=32)).replace(day=1),
                )
                logger.info("Incremental mode: starting from %s", start)

        # Build list of (year, month) tuples to fetch
        months: list[tuple[int, int]] = []
        cur = start.replace(day=1)
        while cur <= end:
            months.append((cur.year, cur.month))
            cur = (cur + timedelta(days=32)).replace(day=1)

        total_rows = 0
        for year, month in months:
            logger.info("Fetching %04d-%02d for %s…", year, month, settlement_point)
            try:
                csv_text = await _fetch_monthly_csv(base_url, year, month)
                rows = _parse_trading_price_csv(csv_text, settlement_point)
                # Trim to requested date range
                rows = [r for r in rows if start <= r["interval_start"].date() <= end]
                n = await _upsert_prices(session, rows)
                total_rows += n
                logger.info("  → %d rows upserted", n)
            except Exception as exc:
                logger.error("Failed for %04d-%02d: %s", year, month, exc)

        return {"months_fetched": len(months), "rows_inserted": total_rows}


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Ingest AEMO WA wholesale energy prices")
    p.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    p.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    p.add_argument("--settlement-point", default="SW1", help="WEM settlement point (default: SW1)")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL)
    p.add_argument("--incremental", action="store_true", help="Skip months already in DB")
    p.add_argument("--log-level", default="INFO")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    logging.basicConfig(level=args.log_level.upper())
    result = asyncio.run(
        ingest_wholesale_prices(
            start=date.fromisoformat(args.start),
            end=date.fromisoformat(args.end),
            settlement_point=args.settlement_point,
            base_url=args.base_url,
            incremental=args.incremental,
        )
    )
    print(result)
