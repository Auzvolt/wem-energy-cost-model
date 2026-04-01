"""Interval meter data import pipeline.

Supports NEM12 and generic 5-minute / 30-minute CSV uploads.
Data is validated, resampled to 5-minute resolution if needed, and upserted
into the ``interval_data`` table.
"""

from __future__ import annotations

import contextlib
import csv
import io
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy.orm import Session

from app.db.models import IntervalData
from app.pipeline.schemas import IntervalDataRow

logger = logging.getLogger(__name__)

INTERVAL_MINUTES = 5
AWST = timezone(timedelta(hours=8))

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    valid: bool
    gap_intervals: list[tuple[datetime, datetime]] = field(default_factory=list)
    outlier_indices: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class IngestResult:
    rows_ingested: int
    validation: ValidationResult


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def parse_nem12(file_content: str) -> list[IntervalDataRow]:
    """Parse a NEM12 file and return a flat list of 5-minute interval rows.

    NEM12 record types used:
    - 100: header (ignored)
    - 200: NMI data details — sets the NMI and interval length
    - 300: interval data — one row per day
    - 900: end of file
    """
    rows: list[IntervalDataRow] = []
    nmi: str = "unknown"
    interval_minutes: int = 30  # default, overridden by 200 record

    for line in file_content.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(",")
        record_type = parts[0]

        if record_type == "200":
            # 200,NMI,NMIConfig,RegSuffix,MDMDataStreamID,MeterSerial,UOM,IntLen,...
            if len(parts) > 1:
                nmi = parts[1].strip() or nmi
            if len(parts) > 8:
                try:
                    interval_minutes = int(parts[8].strip())
                except (ValueError, IndexError):
                    interval_minutes = 30

        elif record_type == "300":
            # 300,YYYYMMDD,val1,val2,...,valN,Quality,ReasonCode,...
            if len(parts) < 3:
                continue
            try:
                date_str = parts[1].strip()
                date = datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=AWST)
            except ValueError:
                logger.warning("NEM12 300 record: bad date %r", parts[1])
                continue

            intervals_per_day = 1440 // interval_minutes
            values_end = 2 + intervals_per_day
            interval_values = parts[2:values_end]

            for i, raw_val in enumerate(interval_values):
                raw_val = raw_val.strip()
                if not raw_val:
                    continue
                try:
                    energy_kwh = float(raw_val)
                except ValueError:
                    continue

                start = date + timedelta(minutes=i * interval_minutes)
                end = start + timedelta(minutes=interval_minutes)
                rows.append(
                    IntervalDataRow(
                        site_id=nmi,
                        interval_start=start,
                        interval_end=end,
                        energy_kwh=energy_kwh,
                        power_kw=energy_kwh / (interval_minutes / 60) if interval_minutes else None,
                        source="nem12",
                    )
                )

    return rows


def parse_generic_csv(file_content: str) -> list[IntervalDataRow]:
    """Parse a generic CSV file with interval meter data.

    Required columns: ``interval_start``, ``energy_kwh``
    Optional columns: ``interval_end``, ``power_kw``, ``site_id``

    ``interval_start`` must be ISO 8601.  If ``interval_end`` is absent a
    30-minute interval length is assumed for determining ``interval_end``.
    """
    reader = csv.DictReader(io.StringIO(file_content))
    rows: list[IntervalDataRow] = []

    for lineno, record in enumerate(reader, start=2):
        start_raw = record.get("interval_start", "").strip()
        energy_raw = record.get("energy_kwh", "").strip()
        if not start_raw or not energy_raw:
            logger.warning("CSV line %d: missing required field, skipping", lineno)
            continue

        try:
            interval_start = datetime.fromisoformat(start_raw)
            if interval_start.tzinfo is None:
                interval_start = interval_start.replace(tzinfo=AWST)
        except ValueError:
            logger.warning("CSV line %d: bad interval_start %r", lineno, start_raw)
            continue

        try:
            energy_kwh = float(energy_raw)
        except ValueError:
            logger.warning("CSV line %d: bad energy_kwh %r", lineno, energy_raw)
            continue

        end_raw = record.get("interval_end", "").strip()
        if end_raw:
            try:
                interval_end = datetime.fromisoformat(end_raw)
                if interval_end.tzinfo is None:
                    interval_end = interval_end.replace(tzinfo=AWST)
            except ValueError:
                interval_end = interval_start + timedelta(minutes=30)
        else:
            interval_end = interval_start + timedelta(minutes=30)

        power_raw = record.get("power_kw", "").strip()
        power_kw: float | None = None
        if power_raw:
            with contextlib.suppress(ValueError):
                power_kw = float(power_raw)

        site_id = record.get("site_id", "default").strip() or "default"

        rows.append(
            IntervalDataRow(
                site_id=site_id,
                interval_start=interval_start,
                interval_end=interval_end,
                energy_kwh=energy_kwh,
                power_kw=power_kw,
                source="csv",
            )
        )

    return rows


# ---------------------------------------------------------------------------
# Resampling
# ---------------------------------------------------------------------------


def resample_to_5min(rows: list[IntervalDataRow]) -> list[IntervalDataRow]:
    """Resample interval rows to 5-minute resolution via linear interpolation.

    If rows are already at 5-minute resolution they are returned unchanged.
    """
    if not rows:
        return []

    # Detect interval length from first gap
    if len(rows) > 1:
        gap = (rows[1].interval_start - rows[0].interval_start).total_seconds() / 60
    else:
        gap = (rows[0].interval_end - rows[0].interval_start).total_seconds() / 60

    if gap <= INTERVAL_MINUTES:
        return rows  # already 5-min or finer

    factor = int(gap / INTERVAL_MINUTES)
    resampled: list[IntervalDataRow] = []

    for row in rows:
        energy_per_5min = row.energy_kwh / factor
        power = row.power_kw / factor if row.power_kw is not None else None
        for j in range(factor):
            start = row.interval_start + timedelta(minutes=j * INTERVAL_MINUTES)
            end = start + timedelta(minutes=INTERVAL_MINUTES)
            resampled.append(
                IntervalDataRow(
                    site_id=row.site_id,
                    interval_start=start,
                    interval_end=end,
                    energy_kwh=energy_per_5min,
                    power_kw=power,
                    source=row.source,
                )
            )

    return resampled


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_intervals(rows: list[IntervalDataRow]) -> ValidationResult:
    """Validate interval rows for gaps and outliers.

    Gap: any adjacent pair of rows where the gap exceeds 30 minutes.
    Outlier: energy_kwh > 3× rolling mean of a 12-interval (1-hour) window.
    """
    result = ValidationResult(valid=True)
    if not rows:
        return result

    # Sort by start time
    sorted_rows = sorted(rows, key=lambda r: r.interval_start)

    # Gap detection
    for i in range(len(sorted_rows) - 1):
        expected_end = sorted_rows[i].interval_end
        actual_start = sorted_rows[i + 1].interval_start
        gap_minutes = (actual_start - expected_end).total_seconds() / 60
        if gap_minutes > 30:
            result.gap_intervals.append((expected_end, actual_start))

    # Outlier flagging (rolling mean over 12-interval window)
    window = 12
    for i, row in enumerate(sorted_rows):
        start_idx = max(0, i - window)
        end_idx = min(len(sorted_rows), i + window + 1)
        window_values = [r.energy_kwh for r in sorted_rows[start_idx:end_idx]]
        if not window_values:
            continue
        rolling_mean = sum(window_values) / len(window_values)
        if rolling_mean > 0 and row.energy_kwh > 3 * rolling_mean:
            result.outlier_indices.append(i)

    if result.gap_intervals:
        result.errors.append(f"{len(result.gap_intervals)} gap(s) detected in interval data")
    if result.outlier_indices:
        result.errors.append(f"{len(result.outlier_indices)} outlier interval(s) detected")

    result.valid = not result.errors
    return result


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------


def upsert_interval_data(
    session: Session,
    site_id: str,
    rows: list[IntervalDataRow],
) -> int:
    """Upsert interval rows for a given site.  Returns the number of rows upserted."""
    if not rows:
        return 0

    upserted = 0
    for row in rows:
        existing = (
            session.query(IntervalData)
            .filter_by(site_id=site_id, interval_start=row.interval_start)
            .first()
        )
        if existing is not None:
            existing.interval_end = row.interval_end  # type: ignore[assignment]
            existing.energy_kwh = row.energy_kwh  # type: ignore[assignment]
            existing.power_kw = row.power_kw  # type: ignore[assignment]
            existing.source = row.source  # type: ignore[assignment]
        else:
            record = IntervalData(
                site_id=site_id,
                interval_start=row.interval_start,
                interval_end=row.interval_end,
                energy_kwh=row.energy_kwh,
                power_kw=row.power_kw,
                source=row.source,
            )
            session.add(record)
        upserted += 1

    session.flush()
    return upserted


# ---------------------------------------------------------------------------
# Top-level ingest
# ---------------------------------------------------------------------------


def ingest_interval_data(
    session: Session,
    site_id: str,
    file_content: str,
    fmt: Literal["nem12", "csv"] = "csv",
) -> IngestResult:
    """Parse, validate, resample, and upsert interval meter data.

    Parameters
    ----------
    session:
        Active SQLAlchemy session.
    site_id:
        Identifier for the site / NMI this data belongs to.
    file_content:
        Raw file text (UTF-8).
    fmt:
        ``'nem12'`` for NEM12 format, ``'csv'`` for generic CSV.

    Returns
    -------
    IngestResult
        Row count and validation details.
    """
    if fmt == "nem12":
        rows = parse_nem12(file_content)
        # Override site_id from caller (NMI comes from file but caller wins)
        rows = [r.model_copy(update={"site_id": site_id}) for r in rows]
    else:
        rows = parse_generic_csv(file_content)
        rows = [r.model_copy(update={"site_id": site_id}) for r in rows]

    rows = resample_to_5min(rows)
    validation = validate_intervals(rows)
    count = upsert_interval_data(session, site_id, rows)
    return IngestResult(rows_ingested=count, validation=validation)
