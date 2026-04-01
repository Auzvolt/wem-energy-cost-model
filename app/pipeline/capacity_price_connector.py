"""AEMO Reserve Capacity Mechanism (RCM) capacity price data connector.

Fetches capacity credit assignments and BRCP (Benchmark Reserve Capacity Price)
from the AEMO WA public data portal and persists them to the ``capacity_prices``
PostgreSQL table.

AEMO WA publishes capacity credit data at:
  /public/public-data/dataFiles/capacity-credits/

The CSV contains per-facility capacity credit allocations and BRCP for each
capacity year (October–September).

Environment variables:
  AEMO_API_BASE_URL — base URL for AEMO WA data portal
  AEMO_API_KEY      — optional API key header value
"""

from __future__ import annotations

import csv
import io
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.config import AEMO_API_BASE_URL, AEMO_API_KEY
from app.db.models import CapacityPrice
from app.pipeline.schemas import CapacityPriceRow

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# URL / endpoint constants
# ---------------------------------------------------------------------------

#: Path to the capacity credits CSV on the AEMO WA public portal.
_CAPACITY_CREDITS_PATH = "/public/public-data/dataFiles/capacity-credits/"

# ---------------------------------------------------------------------------
# CSV field name aliases (AEMO sometimes changes column names between releases)
# ---------------------------------------------------------------------------

_YEAR_FIELDS = ("CAPACITY_YEAR", "CAPACITY YEAR", "CAP_YEAR")
_FACILITY_ID_FIELDS = ("FACILITY_ID", "FACILITY ID", "FACILITYID")
_FACILITY_NAME_FIELDS = ("FACILITY_NAME", "FACILITY NAME", "FACILITYNAME")
_CREDITS_FIELDS = ("CAPACITY_CREDITS_MW", "CAPACITY CREDITS MW", "CAPACITY_CREDITS", "CC_MW")
_BRCP_FIELDS = ("BRCP_MWYR", "BRCP MW/YR", "BRCP", "BRCP_AUD_MWYR")


def _pick(row: dict[str, str], *candidates: str) -> str | None:
    """Return the first candidate key found in *row*, or None."""
    for key in candidates:
        val = row.get(key)
        if val is not None:
            return val
    return None


def _parse_csv(raw_csv: str, source_url: str) -> list[CapacityPriceRow]:
    """Parse a capacity credits CSV string into validated ``CapacityPriceRow`` objects.

    Invalid or incomplete rows are logged and skipped.

    Args:
        raw_csv: Raw CSV text from the AEMO portal.
        source_url: URL the CSV was fetched from (stored for audit).

    Returns:
        List of valid ``CapacityPriceRow`` instances.
    """
    records: list[CapacityPriceRow] = []
    reader = csv.DictReader(io.StringIO(raw_csv))

    for i, row in enumerate(reader):
        # Strip whitespace from keys/values
        row = {k.strip(): v.strip() for k, v in row.items() if k is not None}

        capacity_year = _pick(row, *_YEAR_FIELDS)
        facility_id = _pick(row, *_FACILITY_ID_FIELDS)
        facility_name = _pick(row, *_FACILITY_NAME_FIELDS) or ""
        credits_raw = _pick(row, *_CREDITS_FIELDS)
        brcp_raw = _pick(row, *_BRCP_FIELDS)

        if not capacity_year:
            log.debug("Row %d: missing capacity_year, skipping", i)
            continue
        if not facility_id:
            log.debug("Row %d: missing facility_id, skipping", i)
            continue

        try:
            capacity_credits_mw = float(credits_raw) if credits_raw else 0.0
        except ValueError:
            log.debug("Row %d: invalid capacity_credits_mw %r, skipping", i, credits_raw)
            continue

        try:
            brcp_mwyr = float(brcp_raw) if brcp_raw else 0.0
        except ValueError:
            log.debug("Row %d: invalid brcp_mwyr %r, skipping", i, brcp_raw)
            continue

        try:
            record = CapacityPriceRow(
                capacity_year=capacity_year,
                facility_id=facility_id,
                facility_name=facility_name,
                capacity_credits_mw=capacity_credits_mw,
                brcp_mwyr=brcp_mwyr,
                source_url=source_url,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Row %d: validation failed: %s", i, exc)
            continue

        records.append(record)

    return records


def fetch_capacity_prices(
    db: Session,
    *,
    since_year: str | None = None,
    http_client: Any | None = None,
) -> list[CapacityPrice]:
    """Fetch capacity credit data from AEMO WA and persist to ``capacity_prices``.

    Supports incremental fetch: if ``since_year`` is provided, only rows for
    that year and later are persisted.  If omitted, all available rows are
    fetched and upserted.

    Upsert key: ``(capacity_year, facility_id)``.  Existing records are updated
    in-place if the fetched BRCP or credit allocation has changed.

    Args:
        db: SQLAlchemy ``Session``.
        since_year: Optional capacity year string (e.g. ``'2023-24'``).  Only
            rows with ``capacity_year >= since_year`` (lexicographic) are kept.
        http_client: Optional pre-built ``httpx.Client``; created internally if
            not provided.

    Returns:
        List of newly inserted or updated ``CapacityPrice`` ORM records.
    """
    import contextlib

    _owns_client = http_client is None
    if http_client is None:
        try:
            import httpx

            headers: dict[str, str] = {}
            if AEMO_API_KEY:
                headers["Ocp-Apim-Subscription-Key"] = AEMO_API_KEY
            http_client = httpx.Client(headers=headers, timeout=30.0, follow_redirects=True)
        except ImportError as exc:
            raise RuntimeError("httpx is required for capacity price fetching") from exc

    source_url = f"{AEMO_API_BASE_URL.rstrip('/')}{_CAPACITY_CREDITS_PATH}"

    try:
        response = http_client.get(source_url)
        response.raise_for_status()
        raw_csv = response.text
    finally:
        if _owns_client:
            with contextlib.suppress(Exception):
                http_client.close()

    rows = _parse_csv(raw_csv, source_url)

    if since_year is not None:
        rows = [r for r in rows if r.capacity_year >= since_year]

    upserted: list[CapacityPrice] = []

    for row in rows:
        # Check for existing record
        existing = (
            db.query(CapacityPrice)
            .filter_by(capacity_year=row.capacity_year, facility_id=row.facility_id)
            .first()
        )
        if existing is not None:
            # Update in-place
            existing.facility_name = row.facility_name
            existing.capacity_credits_mw = row.capacity_credits_mw
            existing.brcp_mwyr = row.brcp_mwyr
            upserted.append(existing)
        else:
            record = CapacityPrice(
                capacity_year=row.capacity_year,
                facility_id=row.facility_id,
                facility_name=row.facility_name,
                capacity_credits_mw=row.capacity_credits_mw,
                brcp_mwyr=row.brcp_mwyr,
            )
            db.add(record)
            upserted.append(record)

    db.flush()
    log.info("Capacity prices: upserted %d records (since_year=%r)", len(upserted), since_year)
    return upserted
