"""Async scheduler for the AEMO data pipeline.

Runs ingestion tasks on a configurable schedule using PIPELINE_REFRESH_MINUTES
environment variable.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, timedelta
from typing import TYPE_CHECKING

from app.pipeline.ingest import ingest_all_products, ingest_facilities, ingest_intervals

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Default refresh interval in minutes
DEFAULT_REFRESH_MINUTES = 60


def get_refresh_interval() -> int:
    """Get the pipeline refresh interval from environment variable.

    Returns:
        Refresh interval in minutes (default: 60).
    """
    env_value = os.environ.get("PIPELINE_REFRESH_MINUTES", "")
    try:
        interval = int(env_value)
        if interval < 1:
            logger.warning("Invalid PIPELINE_REFRESH_MINUTES value: %s, using default", env_value)
            return DEFAULT_REFRESH_MINUTES
        return interval
    except ValueError:
        if env_value:
            logger.warning("Invalid PIPELINE_REFRESH_MINUTES value: %s, using default", env_value)
        return DEFAULT_REFRESH_MINUTES


async def run_ingestion_cycle(session_factory: type[Session] | None = None) -> dict[str, int]:
    """Run a single ingestion cycle.

    Fetches facilities, recent trading intervals, and market prices.

    Args:
        session_factory: Optional callable that returns a database session.

    Returns:
        Dictionary with ingestion counts.
    """
    results: dict[str, int] = {}

    # Create a session if factory provided
    if session_factory is None:
        # Try to import from app.db.session if available
        try:
            from app.db.session import SessionLocal

            session = SessionLocal()
        except ImportError:
            logger.error("No session factory available")
            return results
    else:
        session = session_factory()

    try:
        # Ingest facilities (reference data)
        facility_count = ingest_facilities(session)
        results["facilities"] = facility_count

        # Calculate date range for recent data (last 2 days)
        end_date = date.today() - timedelta(days=1)
        start_date = end_date - timedelta(days=1)

        # Ingest trading intervals
        interval_count = ingest_intervals(session, start_date, end_date)
        results["trading_intervals"] = interval_count

        # Ingest market prices
        price_counts = await ingest_all_products(session, start_date, end_date)
        results["prices"] = sum(price_counts.values())

        logger.info("Ingestion cycle complete: %s", results)

    except Exception as exc:
        logger.exception("Error during ingestion cycle: %s", exc)
        session.rollback()
    finally:
        session.close()

    return results


async def run_scheduler(
    session_factory: type[Session] | None = None,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Run the pipeline scheduler loop.

    Continuously runs ingestion cycles at the configured interval.

    Args:
        session_factory: Optional callable that returns a database session.
        stop_event: Optional asyncio.Event to signal stopping.
    """
    refresh_minutes = get_refresh_interval()
    refresh_seconds = refresh_minutes * 60

    logger.info("Starting AEMO pipeline scheduler (refresh interval: %d minutes)", refresh_minutes)

    while stop_event is None or not stop_event.is_set():
        try:
            results = await run_ingestion_cycle(session_factory)
            logger.info("Ingestion results: %s", results)
        except Exception as exc:
            logger.exception("Error in ingestion cycle: %s", exc)

        # Wait for next cycle or until stopped
        if stop_event:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=refresh_seconds)
                break
            except TimeoutError:
                continue
        else:
            await asyncio.sleep(refresh_seconds)

    logger.info("AEMO pipeline scheduler stopped")


if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Run the scheduler
    asyncio.run(run_scheduler())
