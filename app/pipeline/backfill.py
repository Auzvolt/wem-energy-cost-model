"""Historical data backfill CLI for AEMO WA market data.

Usage::

    python -m app.pipeline.backfill \\
        --start 2024-01-01 \\
        --end   2024-03-31 \\
        --products energy,fcess,capacity \\
        [--dry-run]

Resume behaviour: a checkpoint file (``.backfill_checkpoint.json``) in the
current working directory tracks per-(date, product) completion.  On restart,
successfully completed pairs are skipped automatically.

Graceful shutdown: SIGINT writes the checkpoint then exits with code 130.
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_PRODUCTS: frozenset[str] = frozenset({"energy", "fcess", "capacity"})
CHECKPOINT_FILE = Path(".backfill_checkpoint.json")

# ---------------------------------------------------------------------------
# Checkpoint helpers
# ---------------------------------------------------------------------------


def _checkpoint_key(trading_date: date, product: str) -> str:
    return f"{trading_date.isoformat()}::{product}"


def _load_checkpoint(path: Path) -> dict[str, Any]:
    if path.exists():
        try:
            return json.loads(path.read_text())  # type: ignore[no-any-return]
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Could not load checkpoint file %s: %s", path, exc)
    return {}


def _save_checkpoint(path: Path, checkpoint: dict[str, Any]) -> None:
    try:
        path.write_text(json.dumps(checkpoint, indent=2))
    except OSError as exc:
        log.error("Failed to write checkpoint: %s", exc)


# ---------------------------------------------------------------------------
# Date range
# ---------------------------------------------------------------------------


def _date_range(start: date, end: date) -> list[date]:
    """Return list of dates from start to end inclusive."""
    days: list[date] = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


# ---------------------------------------------------------------------------
# Product fetch helpers
# ---------------------------------------------------------------------------


def _date_to_utc_range(trading_date: date) -> tuple[datetime, datetime]:
    """Return UTC-aware start/end datetimes spanning a full trading day."""
    from_dt = datetime(trading_date.year, trading_date.month, trading_date.day, tzinfo=UTC)
    to_dt = from_dt + timedelta(days=1)
    return from_dt, to_dt


def _fetch_energy(trading_date: date, dry_run: bool) -> int:
    """Fetch + upsert energy (wholesale) prices for one day.

    Returns the number of records upserted.
    """
    if dry_run:
        log.info("[DRY-RUN] Would fetch energy prices for %s", trading_date)
        return 0

    import asyncio

    from app.db.session import SessionLocal
    from app.pipeline.ingest import ingest_prices

    async def _run() -> int:
        from app.pipeline.wholesale_price_connector import WholesalePriceConnector

        async with WholesalePriceConnector() as connector:
            await connector.fetch_date_range(trading_date, trading_date)
        session = SessionLocal()
        try:
            return ingest_prices(session, trading_date, trading_date)
        finally:
            session.close()

    return asyncio.run(_run())


def _fetch_fcess(trading_date: date, dry_run: bool) -> int:
    """Fetch + upsert FCESS prices for one day."""
    if dry_run:
        log.info("[DRY-RUN] Would fetch FCESS prices for %s", trading_date)
        return 0

    from app.db.session import SessionLocal
    from app.pipeline.fcess_connector import fetch_all_fcess_products

    from_dt, to_dt = _date_to_utc_range(trading_date)
    session = SessionLocal()
    try:
        results = fetch_all_fcess_products(from_dt, to_dt, session)
        return sum(len(v) for v in results.values())
    finally:
        session.close()


def _fetch_capacity(trading_date: date, dry_run: bool) -> int:
    """Fetch + upsert capacity prices for one day."""
    if dry_run:
        log.info("[DRY-RUN] Would fetch capacity prices for %s", trading_date)
        return 0

    try:
        from app.pipeline.capacity_price_connector import fetch_capacity_prices
    except ImportError:
        log.warning(
            "capacity_price_connector not available; skipping capacity for %s",
            trading_date,
        )
        return 0

    records = fetch_capacity_prices(trading_date)
    return len(records) if records else 0


_PRODUCT_FETCHERS: dict[str, Any] = {
    "energy": _fetch_energy,
    "fcess": _fetch_fcess,
    "capacity": _fetch_capacity,
}

# ---------------------------------------------------------------------------
# Core backfill logic
# ---------------------------------------------------------------------------


def run_backfill(
    start: date,
    end: date,
    products: list[str],
    dry_run: bool = False,
    checkpoint_path: Path = CHECKPOINT_FILE,
) -> dict[str, Any]:
    """Run the backfill for the given date range and products.

    Returns the final checkpoint dict.
    """
    checkpoint = _load_checkpoint(checkpoint_path)

    # Register SIGINT handler to write checkpoint before exit.
    def _sigint_handler(signum: int, frame: object) -> None:  # noqa: ARG001
        log.info("SIGINT received — saving checkpoint and exiting.")
        _save_checkpoint(checkpoint_path, checkpoint)
        sys.exit(130)

    signal.signal(signal.SIGINT, _sigint_handler)

    dates = _date_range(start, end)
    total_combinations = len(dates) * len(products)
    log.info(
        "Backfill: %d days × %d products = %d combinations (dry_run=%s)",
        len(dates),
        len(products),
        total_combinations,
        dry_run,
    )

    for trading_date in dates:
        for product in products:
            key = _checkpoint_key(trading_date, product)

            # Skip already-completed entries.
            entry = checkpoint.get(key, {})
            if isinstance(entry, dict) and entry.get("status") == "ok":
                log.debug("SKIP  %s  %s (already completed)", trading_date, product)
                continue

            fetcher = _PRODUCT_FETCHERS[product]
            status_entry: dict[str, Any]
            try:
                records_fetched = fetcher(trading_date, dry_run)
                status_entry = {
                    "status": "ok",
                    "records_fetched": records_fetched,
                }
                log.info(
                    "OK    %s  %-10s  records=%d",
                    trading_date,
                    product,
                    records_fetched,
                )
            except Exception as exc:  # noqa: BLE001
                status_entry = {
                    "status": "error",
                    "records_fetched": 0,
                    "error_msg": str(exc),
                }
                log.error(
                    "ERROR %s  %-10s  %s",
                    trading_date,
                    product,
                    exc,
                )

            checkpoint[key] = status_entry
            # Persist after every step so interruptions lose at most one entry.
            if not dry_run:
                _save_checkpoint(checkpoint_path, checkpoint)

    log.info("Backfill complete.")
    return checkpoint


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill historical AEMO WA market data.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--start",
        required=True,
        metavar="YYYY-MM-DD",
        help="Start date (inclusive).",
    )
    parser.add_argument(
        "--end",
        required=True,
        metavar="YYYY-MM-DD",
        help="End date (inclusive).",
    )
    parser.add_argument(
        "--products",
        default="energy,fcess,capacity",
        metavar="PRODUCT,...",
        help=f"Comma-separated list of products. Valid: {', '.join(sorted(VALID_PRODUCTS))}.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be fetched without writing to DB.",
    )
    parser.add_argument(
        "--checkpoint",
        default=str(CHECKPOINT_FILE),
        metavar="FILE",
        help="Path to the checkpoint JSON file.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
    )

    args = _parse_args(argv)

    try:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
    except ValueError as exc:
        log.error("Invalid date: %s", exc)
        sys.exit(1)

    if start > end:
        log.error("--start must be <= --end")
        sys.exit(1)

    raw_products = [p.strip().lower() for p in args.products.split(",") if p.strip()]
    invalid = set(raw_products) - VALID_PRODUCTS
    if invalid:
        log.error("Unknown products: %s.  Valid: %s", invalid, VALID_PRODUCTS)
        sys.exit(1)

    run_backfill(
        start=start,
        end=end,
        products=raw_products,
        dry_run=args.dry_run,
        checkpoint_path=Path(args.checkpoint),
    )


if __name__ == "__main__":
    main()
