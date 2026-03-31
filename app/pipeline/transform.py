"""Data transformation utilities for the AEMO pipeline.

Provides functions for timestamp normalisation, resampling, gap detection,
and deduplication of time-series data.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from pandas import DataFrame

logger = logging.getLogger(__name__)


def normalise_timestamps(df: DataFrame, col: str) -> DataFrame:
    """Normalise timestamps in a DataFrame column to UTC.

    Args:
        df: Input DataFrame.
        col: Column name containing timestamps.

    Returns:
        DataFrame with normalised timestamps in the specified column.
    """
    if col not in df.columns:
        logger.warning("Column %s not found in DataFrame", col)
        return df

    df = df.copy()

    # Convert to datetime if not already
    if not pd.api.types.is_datetime64_any_dtype(df[col]):
        df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)
    else:
        # Ensure UTC timezone
        if df[col].dt.tz is None:
            df[col] = df[col].dt.tz_localize("UTC")
        else:
            df[col] = df[col].dt.tz_convert("UTC")

    return df


def resample_to_5min(df: DataFrame) -> DataFrame:
    """Resample a DataFrame to 5-minute intervals.

    Assumes the DataFrame has a datetime index or an 'interval_start' column.
    Numeric columns are averaged during resampling.

    Args:
        df: Input DataFrame with time-series data.

    Returns:
        Resampled DataFrame with 5-minute intervals.
    """
    df = df.copy()

    # Ensure we have a datetime index
    if "interval_start" in df.columns:
        df = df.set_index("interval_start")

    if not isinstance(df.index, pd.DatetimeIndex):
        logger.warning("DataFrame does not have a DatetimeIndex")
        return df

    # Select only numeric columns for resampling
    numeric_cols = df.select_dtypes(include=["number"]).columns

    if len(numeric_cols) == 0:
        logger.warning("No numeric columns to resample")
        return df

    resampled = df[numeric_cols].resample("5min").mean()

    # Forward fill any NaN values (up to a reasonable limit)
    resampled = resampled.ffill(limit=2)

    return resampled.reset_index()


def detect_gaps(df: DataFrame, col: str, freq: str = "5min") -> DataFrame:
    """Detect gaps in a time-series DataFrame.

    Args:
        df: Input DataFrame.
        col: Column name containing timestamps.
        freq: Expected frequency (default: "5min").

    Returns:
        DataFrame with columns: gap_start, gap_end, gap_duration.
    """
    if col not in df.columns:
        logger.warning("Column %s not found in DataFrame", col)
        return pd.DataFrame(columns=["gap_start", "gap_end", "gap_duration"])

    df = df.copy()
    df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)
    df = df.dropna(subset=[col]).sort_values(col)

    if len(df) < 2:
        return pd.DataFrame(columns=["gap_start", "gap_end", "gap_duration"])

    timestamps = df[col].values
    gaps = []

    expected_delta = pd.Timedelta(freq)

    for i in range(len(timestamps) - 1):
        current = pd.Timestamp(timestamps[i])
        next_ts = pd.Timestamp(timestamps[i + 1])
        delta = next_ts - current

        if delta > expected_delta * 1.5:  # Allow 50% tolerance
            gaps.append(
                {
                    "gap_start": current,
                    "gap_end": next_ts,
                    "gap_duration": delta,
                }
            )

    return pd.DataFrame(gaps)


def deduplicate(df: DataFrame, subset: list[str] | None = None) -> DataFrame:
    """Remove duplicate rows from a DataFrame.

    Args:
        df: Input DataFrame.
        subset: Optional list of column names to consider for deduplication.
                If None, all columns are used.

    Returns:
        DataFrame with duplicates removed, keeping the first occurrence.
    """
    if df.empty:
        return df

    before_count = len(df)
    df_deduped = df.drop_duplicates(subset=subset, keep="first")
    after_count = len(df_deduped)

    removed = before_count - after_count
    if removed > 0:
        logger.info("Removed %d duplicate rows", removed)

    return df_deduped.reset_index(drop=True)
