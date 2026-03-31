"""Tests for interval meter data import pipeline."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models import Base
from pipeline.interval_import import (
    IntervalImportConfig,
    ingest_interval_data,
    parse_generic_csv,
    parse_nem12,
    resample_to_5min,
    validate_intervals,
)

TEST_DATABASE_URL = "sqlite+aiosqlite://"


@pytest_asyncio.fixture
async def session() -> AsyncSession:  # type: ignore[misc]
    """Create an in-memory SQLite async session with all tables."""
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as sess:
        yield sess
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


class TestParseNem12:
    """Tests for NEM12 parser."""

    def test_parse_nem12_300_record(self) -> None:
        """Test parsing NEM12 300 record format."""
        # Create synthetic NEM12 content
        lines = [
            "200,NEM1201234,E1Q1,01,kWh,30,20240101",
            "300,NEM1201234,20240101,1.5,2.5,3.5,4.5,5.5,6.5,7.5,8.5,9.5,10.5,11.5,12.5,13.5,14.5,15.5,16.5,17.5,18.5,19.5,20.5,21.5,22.5,23.5,24.5,25.5,26.5,27.5,28.5,29.5,30.5,31.5,32.5,33.5,34.5,35.5,36.5,37.5,38.5,39.5,40.5,41.5,42.5,43.5,44.5,45.5,46.5,47.5,48.5,A,,,",
            "900",
        ]
        content = "\n".join(lines).encode("utf-8")

        df = parse_nem12(content)

        assert len(df) == 48  # 48 x 30-min intervals
        assert "interval_start" in df.columns
        assert "energy_kwh" in df.columns
        assert "quality_flag" in df.columns

        # Check first value
        assert df.iloc[0]["energy_kwh"] == 1.5
        assert df.iloc[0]["quality_flag"] == "A"

    def test_parse_nem12_empty(self) -> None:
        """Test parsing empty NEM12 content."""
        df = parse_nem12(b"")
        assert df.empty
        assert list(df.columns) == ["interval_start", "energy_kwh", "quality_flag"]

    def test_parse_nem12_400_record(self) -> None:
        """Test parsing NEM12 400 record format with per-interval quality."""
        lines = [
            "200,NEM1201234,E1Q1,01,kWh,30,20240101",
            "400,NEM1201234,20240101,1.5,A,2.5,A,3.5,S",
            "900",
        ]
        content = "\n".join(lines).encode("utf-8")

        df = parse_nem12(content)

        assert len(df) == 3
        assert df.iloc[0]["energy_kwh"] == 1.5
        assert df.iloc[0]["quality_flag"] == "A"
        assert df.iloc[2]["quality_flag"] == "S"


class TestParseGenericCsv:
    """Tests for generic CSV parser."""

    def test_parse_csv_datetime_energy_columns(self) -> None:
        """Test CSV with datetime and energy columns."""
        content = b"datetime,energy_kwh\n2024-01-01 00:00:00,1.5\n2024-01-01 00:30:00,2.5\n2024-01-01 01:00:00,3.5"

        df = parse_generic_csv(content, interval_minutes=30)

        assert len(df) == 3
        assert "interval_start" in df.columns
        assert "energy_kwh" in df.columns
        assert df.iloc[0]["energy_kwh"] == 1.5

    def test_parse_csv_timestamp_column(self) -> None:
        """Test CSV with timestamp column name."""
        content = b"timestamp,power\n2024-01-01 00:00:00,10.0\n2024-01-01 00:30:00,20.0"

        df = parse_generic_csv(content)

        assert len(df) == 2
        assert df.iloc[0]["energy_kwh"] == 10.0

    def test_parse_csv_empty(self) -> None:
        """Test parsing empty CSV."""
        content = b"datetime,energy"
        df = parse_generic_csv(content)
        assert df.empty

    def test_parse_csv_with_timezone(self) -> None:
        """Test CSV with timezone-aware datetimes."""
        content = b"datetime,value\n2024-01-01T00:00:00Z,5.0\n2024-01-01T01:00:00Z,10.0"

        df = parse_generic_csv(content)

        assert len(df) == 2
        # Should be converted to AWST (UTC+8)
        assert df.iloc[0]["interval_start"].utcoffset().total_seconds() == 8 * 3600


class TestResampleTo5min:
    """Tests for 5-minute resampling."""

    def test_resample_30min_to_5min(self) -> None:
        """Test resampling 30-min data to 5-min intervals."""
        base_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
        df = pd.DataFrame(
            {
                "interval_start": [base_time, base_time + timedelta(minutes=30)],
                "energy_kwh": [6.0, 12.0],
                "quality_flag": ["A", "A"],
            }
        )

        result = resample_to_5min(df, source_interval_minutes=30)

        # 2 x 30-min intervals -> 12 x 5-min intervals
        assert len(result) == 12
        # Each 30-min interval becomes 6 x 5-min intervals
        # 6 kWh / 6 = 1 kWh per 5-min slot
        assert result.iloc[0]["energy_kwh"] == 1.0
        assert result.iloc[6]["energy_kwh"] == 2.0  # 12 kWh / 6

    def test_resample_15min_to_5min(self) -> None:
        """Test resampling 15-min data to 5-min intervals."""
        base_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
        df = pd.DataFrame(
            {
                "interval_start": [base_time],
                "energy_kwh": [3.0],
                "quality_flag": ["A"],
            }
        )

        result = resample_to_5min(df, source_interval_minutes=15)

        assert len(result) == 3  # 15 min / 5 min = 3 intervals
        assert result.iloc[0]["energy_kwh"] == 1.0  # 3 kWh / 3

    def test_resample_already_5min(self) -> None:
        """Test that 5-min data is not changed."""
        base_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
        df = pd.DataFrame(
            {
                "interval_start": [base_time, base_time + timedelta(minutes=5)],
                "energy_kwh": [1.0, 2.0],
                "quality_flag": ["A", "A"],
            }
        )

        result = resample_to_5min(df, source_interval_minutes=5)

        assert len(result) == 2
        assert result.iloc[0]["energy_kwh"] == 1.0
        assert result.iloc[1]["energy_kwh"] == 2.0

    def test_resample_empty(self) -> None:
        """Test resampling empty dataframe."""
        df = pd.DataFrame(columns=["interval_start", "energy_kwh", "quality_flag"])
        result = resample_to_5min(df, source_interval_minutes=30)
        assert result.empty


class TestValidateIntervals:
    """Tests for interval validation."""

    def test_validate_no_gaps_no_outliers(self) -> None:
        """Test validation of clean data."""
        base_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
        df = pd.DataFrame(
            {
                "interval_start": [base_time + timedelta(minutes=5 * i) for i in range(10)],
                "energy_kwh": [1.0] * 10,
                "quality_flag": ["A"] * 10,
            }
        )

        result = validate_intervals(df)

        assert result["gap_count"] == 0
        assert result["outlier_count"] == 0
        assert len(result["warnings"]) == 0

    def test_validate_with_gap(self) -> None:
        """Test detection of gaps in data."""
        base_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
        df = pd.DataFrame(
            {
                "interval_start": [
                    base_time,
                    base_time + timedelta(minutes=5),
                    base_time + timedelta(minutes=20),  # 15-min gap
                    base_time + timedelta(minutes=25),
                ],
                "energy_kwh": [1.0, 2.0, 3.0, 4.0],
                "quality_flag": ["A"] * 4,
            }
        )

        result = validate_intervals(df)

        assert result["gap_count"] == 1
        assert len(result["warnings"]) == 1
        assert "Gap detected" in result["warnings"][0]

    def test_validate_with_outliers(self) -> None:
        """Test detection of outliers using IQR method."""
        base_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
        # Create data with one extreme outlier
        energy_values = [1.0] * 20
        energy_values[10] = 100.0  # Extreme outlier

        df = pd.DataFrame(
            {
                "interval_start": [base_time + timedelta(minutes=5 * i) for i in range(20)],
                "energy_kwh": energy_values,
                "quality_flag": ["A"] * 20,
            }
        )

        result = validate_intervals(df)

        assert result["outlier_count"] >= 1
        assert any("outlier" in w.lower() for w in result["warnings"])

    def test_validate_negative_values(self) -> None:
        """Test detection of negative energy values."""
        base_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
        df = pd.DataFrame(
            {
                "interval_start": [base_time + timedelta(minutes=5 * i) for i in range(5)],
                "energy_kwh": [1.0, -2.0, 3.0, 4.0, 5.0],
                "quality_flag": ["A"] * 5,
            }
        )

        result = validate_intervals(df)

        assert any("negative" in w.lower() for w in result["warnings"])

    def test_validate_empty(self) -> None:
        """Test validation of empty dataframe."""
        df = pd.DataFrame(columns=["interval_start", "energy_kwh", "quality_flag"])
        result = validate_intervals(df)
        assert result["gap_count"] == 0
        assert result["outlier_count"] == 0
        assert result["warnings"] == []


class TestIngestIntervalData:
    """Tests for full ingest pipeline."""

    @pytest.mark.asyncio
    async def test_ingest_nem12(self, session: AsyncSession) -> None:
        """Test full ingest of NEM12 data."""
        lines = [
            "200,NEM1201234,E1Q1,01,kWh,30,20240101",
            "300,NEM1201234,20240101,1.5,2.5,3.5,4.5,5.5,6.5,7.5,8.5,9.5,10.5,11.5,12.5,13.5,14.5,15.5,16.5,17.5,18.5,19.5,20.5,21.5,22.5,23.5,24.5,25.5,26.5,27.5,28.5,29.5,30.5,31.5,32.5,33.5,34.5,35.5,36.5,37.5,38.5,39.5,40.5,41.5,42.5,43.5,44.5,45.5,46.5,47.5,48.5,A,,,",
        ]
        content = "\n".join(lines).encode("utf-8")

        config = IntervalImportConfig(
            nmi="NEM1201234",
            site_id="SITE001",
            source_format="nem12",
            interval_minutes=30,
        )

        result = await ingest_interval_data(config, content, session)

        assert result["rows_upserted"] == 48 * 6  # 48 x 30-min -> 288 x 5-min
        assert "validation" in result
        assert isinstance(result["validation"]["gap_count"], int)

    @pytest.mark.asyncio
    async def test_ingest_csv(self, session: AsyncSession) -> None:
        """Test full ingest of CSV data."""
        content = b"datetime,energy_kwh\n2024-01-01 00:00:00,6.0\n2024-01-01 00:30:00,12.0"

        config = IntervalImportConfig(
            nmi="NMI123",
            site_id="SITE002",
            source_format="generic_csv",
            interval_minutes=30,
        )

        result = await ingest_interval_data(config, content, session)

        # 2 x 30-min intervals -> 12 x 5-min intervals
        assert result["rows_upserted"] == 12
        assert "validation" in result

    @pytest.mark.asyncio
    async def test_ingest_empty(self, session: AsyncSession) -> None:
        """Test ingest of empty file."""
        content = b"datetime,energy"

        config = IntervalImportConfig(
            nmi="NMI123",
            site_id="SITE003",
            source_format="generic_csv",
            interval_minutes=30,
        )

        result = await ingest_interval_data(config, content, session)

        assert result["rows_upserted"] == 0
        assert "No data found" in result["validation"]["warnings"][0]

    @pytest.mark.asyncio
    async def test_ingest_upsert_existing(self, session: AsyncSession) -> None:
        """Test that upsert updates existing records."""
        content = b"datetime,energy_kwh\n2024-01-01 00:00:00,6.0"

        config = IntervalImportConfig(
            nmi="NMI123",
            site_id="SITE004",
            source_format="generic_csv",
            interval_minutes=30,
        )

        # First ingest
        result1 = await ingest_interval_data(config, content, session)
        assert result1["rows_upserted"] == 6  # 30-min -> 6 x 5-min

        # Second ingest with same data (should upsert)
        result2 = await ingest_interval_data(config, content, session)
        assert result2["rows_upserted"] == 6
