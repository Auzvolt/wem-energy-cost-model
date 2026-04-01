"""AEMO data pipeline scheduler with health checks and alerting.

Runs ``ingest_all_products()`` on a configurable cron schedule and performs
health checks after each ingestion cycle.  Alert channel is configurable via
environment variables.

Configuration env vars
----------------------
PIPELINE_SCHEDULE_CRON  Cron expression for ingestion schedule.
                        Default: ``0 22 * * *`` (06:00 AWST = 22:00 UTC).
PIPELINE_REFRESH_MINUTES  Legacy: minutes between cycles (used when running
                          in polling/loop mode via ``run_scheduler()``).
                          Default: 60.

Usage
-----
Run as a standalone module::

    python -m app.pipeline.scheduler

"""

from __future__ import annotations

import logging
import os
import threading
from datetime import date, timedelta
from typing import Any

from app.db.session import SessionLocal
from app.pipeline.alerts import AlertChannel, get_alert_channel, send_alert
from app.pipeline.health import (
    check_data_gap,
    check_duplicate_run,
    check_fetch_failure,
)
from app.pipeline.ingest import (
    ingest_facilities,
    ingest_intervals,
    ingest_prices,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

_DEFAULT_CRON = "0 22 * * *"
_DEFAULT_REFRESH_MINUTES = 60

PRODUCTS = ["ENERGY", "FCESS_REG_RAISE", "FCESS_REG_LOWER", "CAPACITY"]


def _get_refresh_minutes() -> int:
    """Return polling interval in minutes from env (legacy loop mode)."""
    raw = os.environ.get("PIPELINE_REFRESH_MINUTES", str(_DEFAULT_REFRESH_MINUTES))
    try:
        minutes = int(raw)
        if minutes < 1:
            raise ValueError("must be >= 1")
        return minutes
    except ValueError:
        logger.warning(
            "Invalid PIPELINE_REFRESH_MINUTES=%r — using default %d.",
            raw,
            _DEFAULT_REFRESH_MINUTES,
        )
        return _DEFAULT_REFRESH_MINUTES


def get_pipeline_cron() -> str:
    """Return the configured cron expression (default: daily at 22:00 UTC)."""
    return os.environ.get("PIPELINE_SCHEDULE_CRON", _DEFAULT_CRON).strip()


# ---------------------------------------------------------------------------
# Core ingestion cycle
# ---------------------------------------------------------------------------


def run_ingestion_cycle(session_factory: Any = None) -> dict[str, Any]:
    """Run one full ingestion cycle and return counts.

    Args:
        session_factory: Callable returning a new DB session.  Defaults to
            ``SessionLocal`` from ``app.db.session``.

    Returns:
        Dict with keys ``facilities``, ``trading_intervals``, ``prices``.
    """
    factory = session_factory or SessionLocal
    today = date.today()
    start = today - timedelta(days=2)
    end = today - timedelta(days=1)

    result: dict[str, Any] = {"facilities": 0, "trading_intervals": 0, "prices": 0}

    session = factory()
    try:
        result["facilities"] = ingest_facilities(session)
        result["trading_intervals"] = ingest_intervals(session, start, end)
        result["prices"] = ingest_prices(session, start, end)
        session.commit()
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        result["error"] = str(exc)
        logger.exception("Ingestion cycle failed: %s", exc)
    finally:
        session.close()

    return result


# ---------------------------------------------------------------------------
# Health check + alerting pass
# ---------------------------------------------------------------------------


def run_health_checks(
    ingest_result: dict[str, Any],
    session_factory: Any = None,
    channel: AlertChannel | None = None,
) -> list[dict[str, Any]]:
    """Run all health checks after an ingestion cycle and fire alerts on failure.

    Args:
        ingest_result: Dict returned by ``run_ingestion_cycle()``.
        session_factory: Callable returning a DB session for data-gap checks.
        channel: Override alert channel.

    Returns:
        List of health check result dicts.
    """
    resolved_channel = channel if channel is not None else get_alert_channel()
    checks: list[dict[str, Any]] = []

    # 1. Fetch failure check
    fetch_check = check_fetch_failure(ingest_result)
    checks.append(fetch_check)
    if not fetch_check["ok"]:
        send_alert(fetch_check["check"], fetch_check["detail"], resolved_channel)

    # 2. Duplicate run check (use prices count as proxy)
    rows_inserted = ingest_result.get("prices", 0)
    dup_check = check_duplicate_run(rows_inserted)
    checks.append(dup_check)
    if not dup_check["ok"]:
        send_alert(dup_check["check"], dup_check["detail"], resolved_channel)

    # 3. Data-gap check per product (requires DB session)
    if session_factory is not None or ingest_result.get("error") is None:
        factory = session_factory or SessionLocal
        session = factory()
        try:
            for product in PRODUCTS:
                gap_check = check_data_gap(session, product)
                checks.append(gap_check)
                if not gap_check["ok"]:
                    send_alert(
                        gap_check["check"],
                        gap_check["detail"],
                        resolved_channel,
                    )
        finally:
            session.close()

    return checks


# ---------------------------------------------------------------------------
# Scheduler loop (legacy polling mode)
# ---------------------------------------------------------------------------


def run_scheduler(
    stop_event: threading.Event | None = None,
    session_factory: Any = None,
) -> None:
    """Run ingestion cycles in a blocking loop until *stop_event* is set.

    Args:
        stop_event: A ``threading.Event`` that, when set, stops the loop.
        session_factory: Optional override for DB session factory.
    """
    refresh_minutes = _get_refresh_minutes()
    logger.info(
        "Pipeline scheduler starting — interval: %d min, cron: %s",
        refresh_minutes,
        get_pipeline_cron(),
    )

    if stop_event is None:
        stop_event = threading.Event()

    while not stop_event.is_set():
        logger.info("Starting ingestion cycle…")
        result = run_ingestion_cycle(session_factory=session_factory)
        logger.info("Ingestion cycle complete: %s", result)
        run_health_checks(result, session_factory=session_factory)
        stop_event.wait(timeout=refresh_minutes * 60)

    logger.info("Pipeline scheduler stopped.")


# ---------------------------------------------------------------------------
# Module entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_scheduler()
