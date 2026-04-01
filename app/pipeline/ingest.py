"""AEMO WA data pipeline ingestion functions.

Fetches and stores facility reference data, trading intervals, and market prices
from the AEMO WA public data portal.
"""

from __future__ import annotations

import logging
from contextlib import suppress
from datetime import UTC, date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import httpx
import pandas as pd

from app.db.models import Facility, MarketPrice, TradingInterval
from app.pipeline.aemo_client import AEMOClient, AsyncAEMOClient
from app.pipeline.wholesale_price_connector import (
    WholesalePriceConnector,
    balancing_summary_url,
    parse_balancing_csv,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# AWST = UTC+8
_AWST = timezone(timedelta(hours=8))

_BASE_URL = "https://data.wa.aemo.com.au/public/public-data/dataFiles"


def _date_range(start: date, end: date) -> list[date]:
    """Generate a list of dates from start to end (inclusive)."""
    dates = []
    current = start
    while current <= end:
        dates.append(current)
        current += timedelta(days=1)
    return dates


def _parse_awst_to_utc(raw: object) -> datetime | None:
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

    logger.debug("Could not parse timestamp: %r", s)
    return None


def ingest_facilities(session: Session) -> int:
    """Fetch and store facility reference data from AEMO.

    Args:
        session: SQLAlchemy database session.

    Returns:
        Number of facilities inserted/updated.
    """
    client = AEMOClient()
    url = f"{_BASE_URL}/facility-reference/facility-reference.csv"

    try:
        csv_text = client.get_csv(url)
    except httpx.HTTPError as exc:
        logger.warning("Failed to fetch facilities: %s", exc)
        return 0
    finally:
        client.close()

    if not csv_text.strip():
        logger.info("No facility data returned")
        return 0

    try:
        df = pd.read_csv(pd.io.common.StringIO(csv_text), skipinitialspace=True)
    except Exception as exc:
        logger.warning("Failed to parse facility CSV: %s", exc)
        return 0

    df.columns = [c.strip().upper() for c in df.columns]

    # Map expected columns
    id_col = next((c for c in df.columns if "FACILITY" in c and "ID" in c), None) or "FACILITY_ID"
    name_col = next((c for c in df.columns if "NAME" in c), None) or "FACILITY_NAME"
    type_col = next((c for c in df.columns if "TYPE" in c), None) or "FACILITY_TYPE"
    fuel_col = next((c for c in df.columns if "FUEL" in c), None) or "FUEL_TYPE"

    count = 0
    for _, row in df.iterrows():
        facility_id = str(row.get(id_col, "")).strip()
        if not facility_id:
            continue

        facility_name = str(row.get(name_col, "")).strip() or facility_id
        facility_type = str(row.get(type_col, "")).strip() or None
        fuel_type = str(row.get(fuel_col, "")).strip() or None

        # Check if facility exists
        existing = session.query(Facility).filter_by(facility_id=facility_id).first()
        if existing:
            existing.facility_name = facility_name  # type: ignore[assignment]
            existing.facility_type = facility_type  # type: ignore[assignment]
            existing.fuel_type = fuel_type  # type: ignore[assignment]
            existing.updated_at = datetime.now(UTC)  # type: ignore[assignment]
        else:
            facility = Facility(
                facility_id=facility_id,
                facility_name=facility_name,
                facility_type=facility_type,
                fuel_type=fuel_type,
            )
            session.add(facility)
        count += 1

    session.commit()
    logger.info("Ingested %d facilities", count)
    return count


def ingest_intervals(session: Session, start: date, end: date) -> int:
    """Fetch and store trading interval data for a date range.

    Args:
        session: SQLAlchemy database session.
        start: Start date (inclusive).
        end: End date (inclusive).

    Returns:
        Number of trading intervals inserted.
    """
    client = AEMOClient()
    total_inserted = 0

    dates = _date_range(start, end)

    for trading_date in dates:
        date_str = trading_date.strftime("%Y%m%d")
        url = f"{_BASE_URL}/dispatch-intervals/DispatchIntervals_{date_str}.csv"

        try:
            csv_text = client.get_csv(url)
        except httpx.HTTPError as exc:
            logger.debug("No dispatch intervals for %s: %s", trading_date, exc)
            continue

        if not csv_text.strip():
            continue

        try:
            df = pd.read_csv(pd.io.common.StringIO(csv_text), skipinitialspace=True)
        except Exception as exc:
            logger.warning("Failed to parse dispatch CSV for %s: %s", trading_date, exc)
            continue

        df.columns = [c.strip().upper() for c in df.columns]

        # Find columns
        facility_col = next((c for c in df.columns if "FACILITY" in c), None)
        ts_col = next((c for c in df.columns if "INTERVAL" in c or "TIME" in c), None)
        dispatch_col = next((c for c in df.columns if "DISPATCH" in c or "MW" in c), None)

        if not facility_col or not ts_col:
            logger.debug("Missing required columns in dispatch CSV for %s", trading_date)
            continue

        for _, row in df.iterrows():
            facility_id_str = str(row.get(facility_col, "")).strip()
            if not facility_id_str:
                continue

            # Get facility from DB
            facility = session.query(Facility).filter_by(facility_id=facility_id_str).first()
            if not facility:
                # Create facility if not exists
                facility = Facility(
                    facility_id=facility_id_str,
                    facility_name=facility_id_str,
                )
                session.add(facility)
                session.flush()

            ts = _parse_awst_to_utc(row.get(ts_col))
            if not ts:
                continue

            interval_end = ts + timedelta(minutes=5)

            dispatch_mw = None
            if dispatch_col:
                with suppress(ValueError, TypeError):
                    dispatch_mw = float(row[dispatch_col])

            # Check for existing
            existing = (
                session.query(TradingInterval)
                .filter_by(facility_id=facility.id, interval_start=ts)
                .first()
            )
            if existing:
                continue

            interval = TradingInterval(
                facility_id=facility.id,
                trading_date=trading_date,
                interval_start=ts,
                interval_end=interval_end,
                dispatch_mw=dispatch_mw,
            )
            session.add(interval)
            total_inserted += 1

        session.commit()

    client.close()
    logger.info("Ingested %d trading intervals", total_inserted)
    return total_inserted


def ingest_prices(session: Session, start: date, end: date) -> int:
    """Fetch and store market prices for a date range.

    Args:
        session: SQLAlchemy database session.
        start: Start date (inclusive).
        end: End date (inclusive).

    Returns:
        Number of price records inserted.
    """
    from app.db.models import MarketProduct

    client = AEMOClient()
    total_inserted = 0

    dates = _date_range(start, end)

    for trading_date in dates:
        # Energy prices
        url = balancing_summary_url(trading_date)
        try:
            csv_text = client.get_csv(url)
            records = parse_balancing_csv(csv_text, source_url=url)
        except httpx.HTTPError:
            records = []

        for record in records:
            interval_end = record.interval_start_utc + timedelta(minutes=5)

            # Check for existing
            existing = (
                session.query(MarketPrice)
                .filter_by(
                    product=MarketProduct.energy,
                    interval_start=record.interval_start_utc,
                )
                .first()
            )
            if existing:
                continue

            price = MarketPrice(
                trading_date=trading_date,
                interval_start=record.interval_start_utc,
                interval_end=interval_end,
                product=MarketProduct.energy,
                price_mwh=record.price_aud_mwh,
                source="aemo_public",
            )
            session.add(price)
            total_inserted += 1

        session.commit()

    client.close()
    logger.info("Ingested %d price records", total_inserted)
    return total_inserted


async def ingest_all_products(session: Session, start: date, end: date) -> dict[str, int]:
    """Fetch and store all market products (energy + FCESS) for a date range.

    Args:
        session: SQLAlchemy database session.
        start: Start date (inclusive).
        end: End date (inclusive).

    Returns:
        Dictionary with counts per product.
    """
    from app.db.models import MarketProduct

    async with AsyncAEMOClient() as client:
        connector = WholesalePriceConnector(client)
        records = await connector.fetch_date_range(start, end, include_fcess=True)

    counts: dict[str, int] = {}
    product_map = {
        "ENERGY": MarketProduct.energy,
        "REGULATION_RAISE": MarketProduct.reg_raise,
        "REGULATION_LOWER": MarketProduct.reg_lower,
        "CONTINGENCY_RESERVE_RAISE": MarketProduct.cont_raise,
        "CONTINGENCY_RESERVE_LOWER": MarketProduct.cont_lower,
        "ROCOF_CONTROL_SERVICE": MarketProduct.rocof,
    }

    for record in records:
        product_enum = product_map.get(record.product)
        if not product_enum:
            continue

        interval_end = record.interval_start_utc + timedelta(minutes=5)

        # Check for existing
        existing = (
            session.query(MarketPrice)
            .filter_by(product=product_enum, interval_start=record.interval_start_utc)
            .first()
        )
        if existing:
            continue

        price = MarketPrice(
            trading_date=record.interval_start_utc.date(),
            interval_start=record.interval_start_utc,
            interval_end=interval_end,
            product=product_enum,
            price_mwh=record.price_aud_mwh,
            source="aemo_public",
        )
        session.add(price)
        counts[record.product] = counts.get(record.product, 0) + 1

    session.commit()
    logger.info("Ingested prices: %s", counts)
    return counts
