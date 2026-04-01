"""Data pipeline health checks.

Each check returns a dict with keys:
  ok: bool     — True if healthy, False if alert needed
  check: str   — name of the check
  detail: str  — human-readable description of result or failure reason
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


def check_fetch_failure(result: dict[str, Any]) -> dict[str, Any]:
    """Check whether an ingest result indicates a fetch failure.

    Args:
        result: Dict returned by an ingest function.  Expected keys:
            error (str | None): set if an exception occurred.
            rows (int | None): number of rows inserted.

    Returns:
        Health check result dict.
    """
    error = result.get("error")
    rows = result.get("rows", 1)  # default 1 so missing key doesn't trigger

    if error:
        return {
            "ok": False,
            "check": "fetch_failure",
            "detail": f"Fetch error: {error}",
        }
    if rows == 0:
        return {
            "ok": False,
            "check": "fetch_failure",
            "detail": "Fetch returned empty response (0 rows).",
        }
    return {
        "ok": True,
        "check": "fetch_failure",
        "detail": f"Fetch succeeded ({rows} rows).",
    }


def check_data_gap(session: Any, product: str, threshold_hours: int = 25) -> dict[str, Any]:
    """Check whether market_prices data for *product* is stale.

    Queries the ``market_prices`` table for the latest ``timestamp`` value
    for the given product.  If the gap since now exceeds *threshold_hours*,
    the check fails.

    Args:
        session: SQLAlchemy session.
        product: Market product code to check (e.g. ``"ENERGY"``).
        threshold_hours: Maximum acceptable age of latest row in hours.

    Returns:
        Health check result dict.
    """
    from sqlalchemy import text  # noqa: PLC0415 — lazy import keeps module light

    row = session.execute(
        text(
            "SELECT MAX(timestamp) AS latest FROM market_prices WHERE product = :product"
        ),
        {"product": product},
    ).fetchone()

    now = datetime.now(tz=UTC)

    if row is None or row.latest is None:
        return {
            "ok": False,
            "check": "data_gap",
            "detail": f"No market_prices rows found for product '{product}'.",
        }

    latest: datetime = row.latest
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=UTC)

    gap = now - latest
    gap_hours = gap.total_seconds() / 3600

    if gap_hours > threshold_hours:
        return {
            "ok": False,
            "check": "data_gap",
            "detail": (
                f"Latest '{product}' data is {gap_hours:.1f} h old "
                f"(threshold: {threshold_hours} h)."
            ),
        }

    return {
        "ok": True,
        "check": "data_gap",
        "detail": f"Latest '{product}' data is {gap_hours:.1f} h old — within threshold.",
    }


def check_schema_change(
    expected_columns: list[str], actual_columns: list[str]
) -> dict[str, Any]:
    """Check whether the CSV response contains all expected columns.

    Args:
        expected_columns: Column names the pipeline expects.
        actual_columns: Column names found in the actual response.

    Returns:
        Health check result dict.  On failure, ``detail`` includes the missing
        columns for easy diagnosis.
    """
    expected_set = set(expected_columns)
    actual_set = set(actual_columns)
    missing = sorted(expected_set - actual_set)

    if missing:
        return {
            "ok": False,
            "check": "schema_change",
            "detail": f"Missing expected columns: {missing}",
        }

    return {
        "ok": True,
        "check": "schema_change",
        "detail": "All expected columns present.",
    }


def check_duplicate_run(rows_inserted: int) -> dict[str, Any]:
    """Check whether an ingest run inserted any new rows.

    A zero-row insert typically means the data was already present (duplicate
    run), which is a warning rather than a hard failure.

    Args:
        rows_inserted: Number of new rows written by the ingest function.

    Returns:
        Health check result dict.
    """
    if rows_inserted == 0:
        return {
            "ok": False,
            "check": "duplicate_run",
            "detail": "No new rows inserted — possible duplicate run.",
        }

    return {
        "ok": True,
        "check": "duplicate_run",
        "detail": f"{rows_inserted} new rows inserted.",
    }
