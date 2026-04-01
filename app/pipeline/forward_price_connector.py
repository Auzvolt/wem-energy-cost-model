"""Forward price curve connector.

Generates and persists forward price curves for WEM market products.

Forward curves represent assumed future prices and are used in scenario-based
financial modelling and optimisation.  This module supports two construction
methods:

1. **Historical average** — computes percentile-based forward curves from
   historical market prices already stored in the ``market_prices`` table.
   Useful for base-case and sensitivity scenarios.

2. **Manual import** — accepts a list of ``ForwardPricePoint`` records and
   upserts them into the ``price_curves`` table.  Useful for broker-supplied
   curves or scenario overrides.

Example::

    from app.pipeline.forward_price_connector import (
        build_curve_from_history,
        upsert_forward_curve,
        ForwardPricePoint,
    )
    from datetime import date

    # Build a P50 curve from the last 365 days of market data
    points = build_curve_from_history(
        session=db_session,
        product=\"ENERGY\",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        horizon_years=3,
        curve_name=\"ENERGY_P50_2025\",
        percentile=50.0,
    )
    upsert_forward_curve(session=db_session, points=points)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.db.models import MarketPrice, PriceCurve

log = logging.getLogger(__name__)

__all__ = [
    "ForwardPricePoint",
    "ForwardCurveConfig",
    "build_curve_from_history",
    "upsert_forward_curve",
    "PERCENTILE_PRESETS",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Standard percentile presets used in WEM scenario analysis.
PERCENTILE_PRESETS: dict[str, float] = {
    "P10": 10.0,
    "P25": 25.0,
    "P50": 50.0,
    "P75": 75.0,
    "P90": 90.0,
}

_INTERVALS_PER_HOUR = 12  # 5-minute intervals


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ForwardPricePoint:
    """A single point on a forward price curve.

    Attributes:
        curve_name: Unique identifier for this curve (e.g. ``"ENERGY_P50_2025"``).
        product: WEM market product code (e.g. ``"ENERGY"``, ``"REGULATION_RAISE"``).
        interval_start: UTC datetime of the forward interval.
        price_aud_mwh: Forward price in AUD/MWh.
        scenario_id: Optional scenario ID to associate with this curve.
    """

    curve_name: str
    product: str
    interval_start: datetime
    price_aud_mwh: float
    scenario_id: int | None = None


class ForwardCurveConfig(BaseModel):
    """Configuration for building a forward curve from historical data.

    Attributes:
        curve_name: Name for the generated curve.
        product: WEM market product (e.g. ``"ENERGY"``).
        percentile: Price percentile to use (0–100).  50 = median (P50).
        horizon_years: Number of years into the future to project.
        interval_hours: Granularity of forward curve intervals (hours).
            Default 0.5 (30-minute half-hour intervals for WEM trading).
        escalation_pct_per_year: Annual price escalation applied on top of
            the historical base (percentage).  Default 0.0.
        scenario_id: Optional scenario ID for the generated curve.
    """

    curve_name: str = Field(min_length=1)
    product: str = Field(min_length=1)
    percentile: float = Field(default=50.0, ge=0.0, le=100.0)
    horizon_years: int = Field(default=3, ge=1, le=30)
    interval_hours: float = Field(default=0.5, gt=0.0)
    escalation_pct_per_year: float = Field(default=0.0, ge=0.0)
    scenario_id: int | None = Field(default=None)

    @field_validator("product")
    @classmethod
    def product_uppercase(cls, v: str) -> str:
        """Normalise product names to uppercase."""
        return v.strip().upper()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _percentile(values: list[float], pct: float) -> float:
    """Return the *pct*-th percentile of *values* (0-indexed, nearest-rank).

    Args:
        values: Non-empty list of numeric values.
        pct: Percentile (0–100).

    Returns:
        The percentile value.

    Raises:
        ValueError: If *values* is empty.
    """
    if not values:
        raise ValueError("Cannot compute percentile of an empty list.")
    sorted_vals = sorted(values)
    idx = max(0, min(len(sorted_vals) - 1, int(math.ceil(pct / 100.0 * len(sorted_vals))) - 1))
    return sorted_vals[idx]


def _hour_of_week(dt: datetime) -> int:
    """Return a 0-based hour-of-week index (0 = Mon 00:00, 167 = Sun 23:00)."""
    return dt.weekday() * 24 + dt.hour


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def build_curve_from_history(
    session: Session,
    product: str,
    start_date: date,
    end_date: date,
    curve_name: str,
    percentile: float = 50.0,
    horizon_years: int = 3,
    interval_hours: float = 0.5,
    escalation_pct_per_year: float = 0.0,
    scenario_id: int | None = None,
) -> list[ForwardPricePoint]:
    """Build a forward price curve from historical market prices.

    Queries the ``market_prices`` table for the given *product* over
    [*start_date*, *end_date*], computes the *percentile*-th price for each
    hour-of-week bucket, then projects it forward for *horizon_years* years
    with optional annual escalation.

    Args:
        session: SQLAlchemy session.
        product: WEM market product (e.g. ``"ENERGY"``).
        start_date: Start of historical data window (inclusive).
        end_date: End of historical data window (inclusive).
        curve_name: Name for the generated curve.
        percentile: Price percentile (0–100).  Default 50 (median).
        horizon_years: Number of years to project forward.
        interval_hours: Granularity of forward intervals in hours.
        escalation_pct_per_year: Annual escalation rate (%).
        scenario_id: Optional linked scenario ID.

    Returns:
        List of :class:`ForwardPricePoint` objects ready to upsert.
    """
    product = product.strip().upper()

    start_dt = datetime(start_date.year, start_date.month, start_date.day, tzinfo=UTC)
    end_dt = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=UTC)

    rows: list[Any] = (
        session.query(MarketPrice)
        .filter(
            MarketPrice.product == product,
            MarketPrice.interval_start >= start_dt,
            MarketPrice.interval_start <= end_dt,
        )
        .all()
    )

    if not rows:
        log.warning(
            "No historical market prices found for product=%s in [%s, %s].",
            product,
            start_date,
            end_date,
        )
        return []

    # Group prices by hour-of-week bucket
    bucket_prices: dict[int, list[float]] = {}
    for row in rows:
        # MarketPrice.price_aud_mwh may be Decimal; convert to float
        price = float(row.price_aud_mwh)
        ts: datetime = row.interval_start
        hof_week = _hour_of_week(ts)
        bucket_prices.setdefault(hof_week, []).append(price)

    # Compute percentile for each bucket
    bucket_p: dict[int, float] = {
        hof: _percentile(prices, percentile) for hof, prices in bucket_prices.items()
    }

    # Fallback: use overall median for missing buckets
    all_prices = [p for prices in bucket_prices.values() for p in prices]
    overall_fallback = _percentile(all_prices, percentile)

    # Project forward
    points: list[ForwardPricePoint] = []
    reference_dt = datetime(end_date.year, end_date.month, end_date.day, tzinfo=UTC) + timedelta(
        hours=interval_hours
    )
    horizon_end = reference_dt + timedelta(days=365 * horizon_years)

    current = reference_dt
    year_offset = 0.0
    while current < horizon_end:
        # Compute escalation factor for this interval
        year_offset = (current - reference_dt).total_seconds() / (365.25 * 86400)
        escalation_factor = (1 + escalation_pct_per_year / 100.0) ** year_offset

        hof = _hour_of_week(current)
        base_price = bucket_p.get(hof, overall_fallback)
        forward_price = base_price * escalation_factor

        points.append(
            ForwardPricePoint(
                curve_name=curve_name,
                product=product,
                interval_start=current,
                price_aud_mwh=forward_price,
                scenario_id=scenario_id,
            )
        )
        current += timedelta(hours=interval_hours)

    log.info(
        "Built forward curve '%s' for %s: %d points (P%.0f, +%.1f%%/yr, %d yr horizon).",
        curve_name,
        product,
        len(points),
        percentile,
        escalation_pct_per_year,
        horizon_years,
    )
    return points


def upsert_forward_curve(
    session: Session,
    points: list[ForwardPricePoint],
    *,
    batch_size: int = 500,
) -> int:
    """Upsert forward price curve points into the ``price_curves`` table.

    Matches on (``curve_name``, ``product``, ``interval_start``) and updates
    ``price_mwh`` if a record already exists, or inserts a new record.

    Args:
        session: SQLAlchemy session (caller is responsible for commit/rollback).
        points: List of :class:`ForwardPricePoint` objects to upsert.
        batch_size: Number of records to flush per batch (default 500).

    Returns:
        Total number of records upserted.
    """
    if not points:
        return 0

    upserted = 0
    for i, pt in enumerate(points):
        existing: PriceCurve | None = (
            session.query(PriceCurve)
            .filter_by(
                curve_name=pt.curve_name,
                product=pt.product,
                interval_start=pt.interval_start,
            )
            .first()
        )
        if existing is not None:
            existing.price_mwh = pt.price_aud_mwh  # type: ignore[assignment]
        else:
            record = PriceCurve(
                curve_name=pt.curve_name,
                product=pt.product,
                interval_start=pt.interval_start,
                price_mwh=pt.price_aud_mwh,
                scenario_id=pt.scenario_id,
            )
            session.add(record)

        upserted += 1
        if (i + 1) % batch_size == 0:
            session.flush()

    session.flush()
    log.info("Upserted %d forward curve points.", upserted)
    return upserted
