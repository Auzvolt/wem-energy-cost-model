"""Tests for interval meter data import pipeline (issue #15)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.pipeline.interval_import import (
    IngestResult,
    ValidationResult,
    ingest_interval_data,
    parse_generic_csv,
    parse_nem12,
    resample_to_5min,
    upsert_interval_data,
    validate_intervals,
)
from app.pipeline.schemas import IntervalDataRow

AWST = timezone(timedelta(hours=8))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row(
    start: datetime,
    energy: float,
    site_id: str = "SITE001",
    source: str = "csv",
) -> IntervalDataRow:
    return IntervalDataRow(
        site_id=site_id,
        interval_start=start,
        interval_end=start + timedelta(minutes=5),
        energy_kwh=energy,
        source=source,
    )


def _make_rows(
    n: int,
    start: datetime | None = None,
    energy: float = 1.0,
    interval_minutes: int = 5,
) -> list[IntervalDataRow]:
    if start is None:
        start = datetime(2024, 1, 1, 0, 0, tzinfo=AWST)
    return [
        IntervalDataRow(
            site_id="SITE001",
            interval_start=start + timedelta(minutes=i * interval_minutes),
            interval_end=start + timedelta(minutes=(i + 1) * interval_minutes),
            energy_kwh=energy,
            source="csv",
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# parse_nem12
# ---------------------------------------------------------------------------


class TestParseNem12:
    NEM12_SAMPLE = (
        "100,NEM12,202401010000,AGLNDE001,NEMMCO\n"
        "200,NEM1201234,E1E2,E1,NGLNDE001,A01234,kWh,30,\n"
        "300,20240101,1.5,1.5,1.5,1.5,1.5,1.5,1.5,1.5,"
        "1.5,1.5,1.5,1.5,1.5,1.5,1.5,1.5,1.5,1.5,1.5,1.5,"
        "1.5,1.5,1.5,1.5,1.5,1.5,1.5,1.5,1.5,1.5,1.5,1.5,"
        "1.5,1.5,1.5,1.5,1.5,1.5,1.5,1.5,1.5,1.5,1.5,1.5,"
        "1.5,1.5,1.5,A,0,20240102000000\n"
        "900"
    )

    def test_returns_rows(self) -> None:
        rows = parse_nem12(self.NEM12_SAMPLE)
        assert len(rows) > 0

    def test_source_is_nem12(self) -> None:
        rows = parse_nem12(self.NEM12_SAMPLE)
        assert all(r.source == "nem12" for r in rows)

    def test_energy_kwh_correct(self) -> None:
        rows = parse_nem12(self.NEM12_SAMPLE)
        # Each 300 record value is 1.5 kWh per 30-min interval
        assert all(r.energy_kwh == 1.5 for r in rows)

    def test_nmi_set_as_site_id(self) -> None:
        rows = parse_nem12(self.NEM12_SAMPLE)
        assert all(r.site_id == "NEM1201234" for r in rows)

    def test_bad_date_skipped(self) -> None:
        bad = self.NEM12_SAMPLE.replace("20240101,", "BADDATE,", 1)
        rows = parse_nem12(bad)
        # Should not crash; rows from bad date are skipped
        assert isinstance(rows, list)

    def test_empty_input(self) -> None:
        assert parse_nem12("") == []


# ---------------------------------------------------------------------------
# parse_generic_csv
# ---------------------------------------------------------------------------


class TestParseGenericCsv:
    CSV_SAMPLE = (
        "interval_start,energy_kwh\n"
        "2024-01-01T00:00:00+08:00,1.2\n"
        "2024-01-01T00:30:00+08:00,1.4\n"
        "2024-01-01T01:00:00+08:00,0.9\n"
    )

    CSV_WITH_POWER = "interval_start,energy_kwh,power_kw\n2024-01-01T00:00:00+08:00,1.2,2.4\n"

    CSV_WITH_SITE = "interval_start,energy_kwh,site_id\n2024-01-01T00:00:00+08:00,1.2,MYSITE\n"

    def test_parse_basic(self) -> None:
        rows = parse_generic_csv(self.CSV_SAMPLE)
        assert len(rows) == 3

    def test_energy_values(self) -> None:
        rows = parse_generic_csv(self.CSV_SAMPLE)
        assert [r.energy_kwh for r in rows] == [1.2, 1.4, 0.9]

    def test_default_interval_end_30min(self) -> None:
        rows = parse_generic_csv(self.CSV_SAMPLE)
        gap = (rows[0].interval_end - rows[0].interval_start).total_seconds() / 60
        assert gap == 30

    def test_power_kw_parsed(self) -> None:
        rows = parse_generic_csv(self.CSV_WITH_POWER)
        assert rows[0].power_kw == 2.4

    def test_site_id_parsed(self) -> None:
        rows = parse_generic_csv(self.CSV_WITH_SITE)
        assert rows[0].site_id == "MYSITE"

    def test_missing_energy_skipped(self) -> None:
        bad_csv = "interval_start,energy_kwh\n2024-01-01T00:00:00+08:00,\n"
        rows = parse_generic_csv(bad_csv)
        assert rows == []

    def test_bad_start_skipped(self) -> None:
        bad_csv = "interval_start,energy_kwh\nNOTADATE,1.0\n"
        rows = parse_generic_csv(bad_csv)
        assert rows == []

    def test_empty_csv(self) -> None:
        rows = parse_generic_csv("interval_start,energy_kwh\n")
        assert rows == []


# ---------------------------------------------------------------------------
# resample_to_5min
# ---------------------------------------------------------------------------


class TestResampleTo5Min:
    def test_5min_data_unchanged(self) -> None:
        rows = _make_rows(12, interval_minutes=5)
        result = resample_to_5min(rows)
        assert len(result) == 12

    def test_30min_upsampled(self) -> None:
        rows = _make_rows(48, interval_minutes=30, energy=3.0)
        result = resample_to_5min(rows)
        assert len(result) == 48 * 6

    def test_energy_conserved(self) -> None:
        rows = _make_rows(48, interval_minutes=30, energy=3.0)
        result = resample_to_5min(rows)
        original_total = sum(r.energy_kwh for r in rows)
        resampled_total = sum(r.energy_kwh for r in result)
        assert abs(original_total - resampled_total) < 1e-6

    def test_empty_input(self) -> None:
        assert resample_to_5min([]) == []

    def test_5min_intervals_preserved(self) -> None:
        rows = _make_rows(6, interval_minutes=30, energy=1.0)
        result = resample_to_5min(rows)
        for i in range(len(result) - 1):
            gap = (result[i + 1].interval_start - result[i].interval_start).total_seconds() / 60
            assert gap == 5


# ---------------------------------------------------------------------------
# validate_intervals
# ---------------------------------------------------------------------------


class TestValidateIntervals:
    def test_valid_contiguous(self) -> None:
        rows = _make_rows(288)
        result = validate_intervals(rows)
        assert result.valid
        assert result.gap_intervals == []
        assert result.outlier_indices == []

    def test_gap_detected(self) -> None:
        start = datetime(2024, 1, 1, 0, 0, tzinfo=AWST)
        rows = _make_rows(10, start=start)
        # Introduce gap by skipping rows 5-9 (50-min gap)
        rows_with_gap = rows[:5] + _make_rows(5, start=start + timedelta(hours=1))
        result = validate_intervals(rows_with_gap)
        assert len(result.gap_intervals) >= 1

    def test_outlier_detected(self) -> None:
        rows = _make_rows(100, energy=1.0)
        # Insert a huge outlier in the middle
        rows[50] = _row(rows[50].interval_start, energy=1000.0)
        result = validate_intervals(rows)
        assert len(result.outlier_indices) >= 1

    def test_empty_input(self) -> None:
        result = validate_intervals([])
        assert result.valid

    def test_single_row(self) -> None:
        start = datetime(2024, 1, 1, 0, 0, tzinfo=AWST)
        result = validate_intervals([_row(start, 1.0)])
        assert result.valid


# ---------------------------------------------------------------------------
# upsert_interval_data
# ---------------------------------------------------------------------------


class TestUpsertIntervalData:
    def test_insert_new_rows(self, db_session) -> None:
        rows = _make_rows(10)
        count = upsert_interval_data(db_session, "SITE001", rows)
        assert count == 10

    def test_upsert_idempotent(self, db_session) -> None:
        rows = _make_rows(5)
        upsert_interval_data(db_session, "SITE001", rows)
        count = upsert_interval_data(db_session, "SITE001", rows)
        assert count == 5

    def test_update_energy_on_upsert(self, db_session) -> None:
        rows = _make_rows(3, energy=1.0)
        upsert_interval_data(db_session, "SITE001", rows)
        updated = _make_rows(3, energy=2.0)
        upsert_interval_data(db_session, "SITE001", updated)
        from app.db.models import IntervalData

        records = db_session.query(IntervalData).filter_by(site_id="SITE001").all()
        assert all(float(r.energy_kwh) == 2.0 for r in records)

    def test_empty_rows(self, db_session) -> None:
        count = upsert_interval_data(db_session, "SITE001", [])
        assert count == 0


# ---------------------------------------------------------------------------
# ingest_interval_data (integration)
# ---------------------------------------------------------------------------


class TestIngestIntervalData:
    CSV_SAMPLE = (
        "interval_start,energy_kwh\n2024-01-01T00:00:00+08:00,1.2\n2024-01-01T00:30:00+08:00,1.4\n"
    )

    def test_csv_ingest(self, db_session) -> None:
        result = ingest_interval_data(db_session, "SITE001", self.CSV_SAMPLE, fmt="csv")
        assert isinstance(result, IngestResult)
        assert result.rows_ingested > 0

    def test_returns_validation(self, db_session) -> None:
        result = ingest_interval_data(db_session, "SITE001", self.CSV_SAMPLE, fmt="csv")
        assert isinstance(result.validation, ValidationResult)
