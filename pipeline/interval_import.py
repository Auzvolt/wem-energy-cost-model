"""Interval meter data import pipeline with NEM12 and CSV support."""

from __future__ import annotations

import io
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IntervalData


class IntervalImportConfig(BaseModel):
    """Configuration for interval data import."""

    nmi: str
    site_id: str
    source_format: Literal["nem12", "generic_csv"]
    interval_minutes: int = 30


def parse_nem12(file_bytes: bytes) -> pd.DataFrame:
    """Parse NEM12 format (200/300/400 records) into a DataFrame.

    NEM12 300 record format:
    - RecordIndicator (3)
    - NMI (10)
    - NMIConfiguration (?
    - RegisterID (10)
    - NMISuffix (2)
    - MDMDataStreamIdentifier (2)
    - MeterSerialNumber (12)
    - DirectionIndicator (1)
    - PreviousRegisterRead (12)
    - PreviousRegisterReadDateTime (12)
    - PreviousQualityMethod (3)
    - PreviousReasonCode (3)
    - PreviousReasonDescription (240)
    - CurrentRegisterRead (12)
    - CurrentRegisterReadDateTime (12)
    - CurrentQualityMethod (3)
    - CurrentReasonCode (3)
    - CurrentReasonDescription (240)
    - Quantity (12)
    - UOM (2)
    - NextScheduledReadDate (8)
    - ... (variable)

    For interval data, we focus on 300 records with interval readings.
    """
    lines = file_bytes.decode("utf-8", errors="ignore").splitlines()

    records = []
    current_nmi: str | None = None
    current_interval_length: int = 30  # Default to 30 min

    for line in lines:
        line = line.strip()
        if not line:
            continue

        record_type = line[:3]

        if record_type == "200":
            # NMI Data Details record
            # 200,NMI,NMIConfig,RegisterID,NMISuffix,MDMDataStream,
            # MeterSerial,Direction,PrevRead,PrevDateTime,PrevQuality,
            # PrevReason,PrevDesc,CurrRead,CurrDateTime,CurrQuality,
            # CurrReason,CurrDesc,Quantity,UOM,NextReadDate,...
            parts = line.split(",")
            if len(parts) >= 2:
                current_nmi = parts[1]
            # Interval length might be specified in NMI config
            if len(parts) >= 3 and parts[2]:
                # Try to extract interval from config like "E1", "E2" etc
                pass

        elif record_type == "300":
            # Interval Data record
            # 300,NMI,Date,Interval1,Interval2,...,IntervalN,QualityMethod,...
            parts = line.split(",")
            if len(parts) < 3:
                continue

            date_str = parts[2]

            # Parse date (YYYYMMDD format)
            try:
                base_date = datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=UTC)
            except ValueError:
                continue

            # Find where interval values end and quality method starts
            # NEM12 has up to 288 intervals (5-min) or 48 intervals (30-min) per day
            # After intervals, there's QualityMethod, ReasonCode, ReasonDescription, etc.

            # Count how many numeric values we have (interval readings)
            interval_values = []

            # Start from index 3 (after record type, NMI, date)
            i = 3
            while i < len(parts):
                val = parts[i].strip()
                # Stop when we hit non-numeric quality method codes
                # Quality method is typically 3 chars like "A", "S", "N"
                if val and len(val) <= 3 and not re.match(r"^\d+\.?\d*$", val):
                    # This is likely the quality method field
                    break
                if val:
                    try:
                        interval_values.append(float(val))
                    except ValueError:
                        break
                i += 1

            # Quality method is at position i
            quality_method = parts[i] if i < len(parts) else "A"

            # Calculate interval length based on number of readings
            num_intervals = len(interval_values)
            if num_intervals == 288:
                interval_mins = 5
            elif num_intervals == 96:
                interval_mins = 15
            elif num_intervals == 48:
                interval_mins = 30
            else:
                interval_mins = current_interval_length

            # Create datetime entries
            for idx, energy_val in enumerate(interval_values):
                interval_start = base_date + timedelta(minutes=idx * interval_mins)
                # Convert to AWST (UTC+8)
                awst_offset = timedelta(seconds=8 * 3600)
                interval_start_awst = interval_start.replace(tzinfo=UTC) + awst_offset

                records.append(
                    {
                        "interval_start": interval_start_awst,
                        "energy_kwh": energy_val,
                        "quality_flag": quality_method if quality_method else "A",
                        "nmi": current_nmi,
                    }
                )

        elif record_type == "400":
            # Interval Data with multiple quality methods per interval
            # Similar to 300 but with per-interval quality
            parts = line.split(",")
            if len(parts) < 3:
                continue

            date_str = parts[2]

            try:
                base_date = datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=UTC)
            except ValueError:
                continue

            # 400 record: 400,NMI,Date,Interval1,QM1,Interval2,QM2,...
            # Alternate between value and quality method
            i = 3
            idx = 0
            while i + 1 < len(parts):
                val_str = parts[i].strip()
                quality = parts[i + 1].strip() if i + 1 < len(parts) else "A"

                if not val_str:
                    i += 2
                    idx += 1
                    continue

                try:
                    energy_val = float(val_str)
                except ValueError:
                    i += 2
                    idx += 1
                    continue

                # Assume 30-min intervals for 400 records unless specified
                interval_mins = 30
                interval_start = base_date + timedelta(minutes=idx * interval_mins)
                awst_offset = timedelta(seconds=8 * 3600)
                interval_start_awst = interval_start.replace(tzinfo=UTC) + awst_offset

                records.append(
                    {
                        "interval_start": interval_start_awst,
                        "energy_kwh": energy_val,
                        "quality_flag": quality if quality else "A",
                    }
                )

                i += 2
                idx += 1

    df = pd.DataFrame(records)
    if df.empty:
        return pd.DataFrame(columns=["interval_start", "energy_kwh", "quality_flag"])

    return df


def parse_generic_csv(file_bytes: bytes, interval_minutes: int = 30) -> pd.DataFrame:
    """Parse generic CSV with auto-detected datetime and energy columns.

    Detects:
    - Datetime column: contains 'datetime', 'timestamp', 'time' (case-insensitive)
    - Value column: contains 'energy', 'kwh', 'kw', 'power' (case-insensitive)
    """
    df = pd.read_csv(io.BytesIO(file_bytes))

    if df.empty:
        return pd.DataFrame(columns=["interval_start", "energy_kwh", "quality_flag"])

    # Detect datetime column
    datetime_col = None
    for col in df.columns:
        col_lower = col.lower()
        if any(keyword in col_lower for keyword in ["datetime", "timestamp", "time"]):
            datetime_col = col
            break

    if datetime_col is None:
        # Try first column as fallback
        datetime_col = df.columns[0]

    # Detect value column
    value_col = None
    for col in df.columns:
        col_lower = col.lower()
        if any(keyword in col_lower for keyword in ["energy", "kwh", "kw", "power", "value"]):
            value_col = col
            break

    if value_col is None:
        # Try second column as fallback
        value_col = df.columns[1] if len(df.columns) > 1 else df.columns[0]

    # Parse datetime
    df[datetime_col] = pd.to_datetime(df[datetime_col], utc=True)

    # Ensure timezone is set (assume UTC if not specified)
    if df[datetime_col].dt.tz is None:
        df[datetime_col] = df[datetime_col].dt.tz_localize(UTC)

    # Convert to AWST (UTC+8)
    awst_offset = timedelta(seconds=8 * 3600)
    df[datetime_col] = df[datetime_col] + awst_offset

    # Create result dataframe
    result = pd.DataFrame(
        {
            "interval_start": df[datetime_col],
            "energy_kwh": pd.to_numeric(df[value_col], errors="coerce"),
            "quality_flag": "A",
        }
    )

    # Drop rows with invalid energy values
    result = result.dropna(subset=["energy_kwh"])

    return result


def resample_to_5min(df: pd.DataFrame, source_interval_minutes: int) -> pd.DataFrame:
    """Resample interval data to 5-minute intervals.

    Distributes energy evenly across the new intervals.
    For example, 30-min interval with 6 kWh becomes 6 x 5-min intervals with 1 kWh each.
    """
    if df.empty:
        return pd.DataFrame(columns=["interval_start", "energy_kwh", "quality_flag"])

    if source_interval_minutes <= 5:
        # Already 5-min or less, no resampling needed
        return df.copy()

    # Calculate how many 5-min intervals fit into source interval
    num_subintervals = source_interval_minutes // 5
    if num_subintervals < 1:
        num_subintervals = 1

    new_records = []
    for _, row in df.iterrows():
        base_time = row["interval_start"]
        energy_per_slot = row["energy_kwh"] / num_subintervals
        quality = row.get("quality_flag", "A")

        for i in range(num_subintervals):
            new_time = base_time + timedelta(minutes=i * 5)
            new_records.append(
                {
                    "interval_start": new_time,
                    "energy_kwh": energy_per_slot,
                    "quality_flag": quality,
                }
            )

    return pd.DataFrame(new_records)


def validate_intervals(df: pd.DataFrame) -> dict[str, Any]:
    """Validate interval data for gaps and outliers.

    Returns dict with:
    - gap_count: number of gaps detected
    - outlier_count: number of outliers detected
    - warnings: list of warning messages
    """
    if df.empty:
        return {"gap_count": 0, "outlier_count": 0, "warnings": []}

    warnings: list[str] = []
    gap_count = 0
    outlier_count = 0

    # Sort by time
    df_sorted = df.sort_values("interval_start").reset_index(drop=True)

    # Check for gaps (expecting 5-min intervals)
    expected_diff = timedelta(minutes=5)
    time_diffs = df_sorted["interval_start"].diff().dropna()

    for i, diff in enumerate(time_diffs, start=1):
        if diff > expected_diff * 1.5:  # Allow some tolerance
            gap_count += 1
            warnings.append(f"Gap detected at index {i}: {diff.total_seconds() / 60:.0f} min gap")

    # Check for outliers using IQR method
    energy_values = df_sorted["energy_kwh"]
    q1 = energy_values.quantile(0.25)
    q3 = energy_values.quantile(0.75)
    iqr = q3 - q1
    lower_bound = q1 - 3 * iqr  # Using 3*IQR for extreme outliers
    upper_bound = q3 + 3 * iqr

    outliers = energy_values[(energy_values < lower_bound) | (energy_values > upper_bound)]
    outlier_count = len(outliers)

    if outlier_count > 0:
        warnings.append(f"Detected {outlier_count} outliers (IQR method)")

    # Check for negative energy values
    negative_count = (energy_values < 0).sum()
    if negative_count > 0:
        warnings.append(f"Found {negative_count} negative energy values")

    return {
        "gap_count": gap_count,
        "outlier_count": outlier_count,
        "warnings": warnings,
    }


async def ingest_interval_data(
    config: IntervalImportConfig,
    file_bytes: bytes,
    session: AsyncSession,
) -> dict[str, Any]:
    """Orchestrate the full import pipeline: parse → resample → validate → upsert.

    Returns dict with:
    - rows_upserted: number of rows inserted/updated
    - validation: validation results dict
    """
    # Parse based on format
    if config.source_format == "nem12":
        df = parse_nem12(file_bytes)
    else:
        df = parse_generic_csv(file_bytes, config.interval_minutes)

    if df.empty:
        return {
            "rows_upserted": 0,
            "validation": {
                "gap_count": 0,
                "outlier_count": 0,
                "warnings": ["No data found in file"],
            },
        }

    # Resample to 5-min intervals
    df_resampled = resample_to_5min(df, config.interval_minutes)

    # Validate
    validation = validate_intervals(df_resampled)

    # Prepare records for upsert
    records = []
    for _, row in df_resampled.iterrows():
        records.append(
            {
                "site_id": config.site_id,
                "nmi": config.nmi,
                "interval_start": row["interval_start"],
                "energy_kwh": row["energy_kwh"],
                "quality_flag": row.get("quality_flag", "A"),
            }
        )

    # Bulk upsert using insert with on_conflict_do_update
    if records:
        # Use dialect-specific upsert
        stmt = sqlite_insert(IntervalData).values(records)
        stmt = stmt.on_conflict_do_update(
            index_elements=["site_id", "interval_start"],
            set_={
                "energy_kwh": stmt.excluded.energy_kwh,
                "quality_flag": stmt.excluded.quality_flag,
                "nmi": stmt.excluded.nmi,
            },
        )
        await session.execute(stmt)
        await session.flush()

    return {
        "rows_upserted": len(records),
        "validation": validation,
    }
