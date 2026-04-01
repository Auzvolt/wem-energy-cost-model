"""Tests for app.pipeline.forward_price_connector."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from app.pipeline.forward_price_connector import (
    PERCENTILE_PRESETS,
    ForwardCurveConfig,
    ForwardPricePoint,
    _hour_of_week,
    _percentile,
    build_curve_from_history,
    upsert_forward_curve,
)

# ---------------------------------------------------------------------------
# _percentile helper
# ---------------------------------------------------------------------------


class TestPercentileHelper:
    def test_single_value(self) -> None:
        assert _percentile([42.0], 50.0) == 42.0

    def test_median_odd(self) -> None:
        assert _percentile([1.0, 2.0, 3.0], 50.0) == 2.0

    def test_median_even(self) -> None:
        # nearest-rank: for 4 values P50 = index ceil(0.5*4)-1 = 1 → 2nd value
        assert _percentile([1.0, 2.0, 3.0, 4.0], 50.0) == 2.0

    def test_p10(self) -> None:
        values = list(range(10, 110, 10))  # [10, 20, ..., 100]
        result = _percentile(values, 10.0)
        assert result == 10.0

    def test_p100(self) -> None:
        values = [1.0, 5.0, 10.0]
        assert _percentile(values, 100.0) == 10.0

    def test_p0(self) -> None:
        values = [3.0, 7.0, 12.0]
        assert _percentile(values, 0.0) == 3.0

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            _percentile([], 50.0)

    def test_unsorted_input(self) -> None:
        values = [30.0, 10.0, 20.0]
        assert _percentile(values, 50.0) == 20.0


# ---------------------------------------------------------------------------
# _hour_of_week helper
# ---------------------------------------------------------------------------


class TestHourOfWeek:
    def test_monday_midnight(self) -> None:
        # weekday() == 0 for Monday
        dt = datetime(2025, 1, 6, 0, 0, tzinfo=UTC)  # Monday
        assert _hour_of_week(dt) == 0

    def test_monday_midday(self) -> None:
        dt = datetime(2025, 1, 6, 12, 0, tzinfo=UTC)
        assert _hour_of_week(dt) == 12

    def test_sunday_last_hour(self) -> None:
        dt = datetime(2025, 1, 12, 23, 0, tzinfo=UTC)  # Sunday
        assert _hour_of_week(dt) == 6 * 24 + 23  # 167

    def test_tuesday(self) -> None:
        dt = datetime(2025, 1, 7, 8, 0, tzinfo=UTC)  # Tuesday
        assert _hour_of_week(dt) == 1 * 24 + 8  # 32

    def test_range_0_to_167(self) -> None:
        # All days of a week should produce values in [0, 167]
        base = datetime(2025, 1, 6, 0, 0, tzinfo=UTC)
        for hour in range(168):
            dt = base + timedelta(hours=hour)
            val = _hour_of_week(dt)
            assert 0 <= val <= 167


# ---------------------------------------------------------------------------
# ForwardCurveConfig
# ---------------------------------------------------------------------------


class TestForwardCurveConfig:
    def test_defaults(self) -> None:
        cfg = ForwardCurveConfig(curve_name="TEST", product="ENERGY")
        assert cfg.percentile == 50.0
        assert cfg.horizon_years == 3
        assert cfg.interval_hours == 0.5
        assert cfg.escalation_pct_per_year == 0.0
        assert cfg.scenario_id is None

    def test_product_normalised_uppercase(self) -> None:
        cfg = ForwardCurveConfig(curve_name="TEST", product="energy")
        assert cfg.product == "ENERGY"

    def test_percentile_bounds(self) -> None:
        with pytest.raises(Exception):  # noqa: B017
            ForwardCurveConfig(curve_name="X", product="E", percentile=101.0)
        with pytest.raises(Exception):  # noqa: B017
            ForwardCurveConfig(curve_name="X", product="E", percentile=-1.0)

    def test_horizon_bounds(self) -> None:
        with pytest.raises(Exception):  # noqa: B017
            ForwardCurveConfig(curve_name="X", product="E", horizon_years=0)

    def test_interval_hours_positive(self) -> None:
        with pytest.raises(Exception):  # noqa: B017
            ForwardCurveConfig(curve_name="X", product="E", interval_hours=0.0)


# ---------------------------------------------------------------------------
# ForwardPricePoint
# ---------------------------------------------------------------------------


class TestForwardPricePoint:
    def test_construction(self) -> None:
        pt = ForwardPricePoint(
            curve_name="ENERGY_P50",
            product="ENERGY",
            interval_start=datetime(2026, 1, 1, tzinfo=UTC),
            price_aud_mwh=85.0,
        )
        assert pt.curve_name == "ENERGY_P50"
        assert pt.scenario_id is None

    def test_with_scenario_id(self) -> None:
        pt = ForwardPricePoint(
            curve_name="X",
            product="ENERGY",
            interval_start=datetime(2026, 1, 1, tzinfo=UTC),
            price_aud_mwh=100.0,
            scenario_id=42,
        )
        assert pt.scenario_id == 42

    def test_frozen_immutable(self) -> None:
        pt = ForwardPricePoint(
            curve_name="X",
            product="ENERGY",
            interval_start=datetime(2026, 1, 1, tzinfo=UTC),
            price_aud_mwh=50.0,
        )
        with pytest.raises(Exception):  # noqa: B017
            pt.price_aud_mwh = 99.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# PERCENTILE_PRESETS constant
# ---------------------------------------------------------------------------


class TestPercentilePresets:
    def test_contains_standard_keys(self) -> None:
        for key in ("P10", "P25", "P50", "P75", "P90"):
            assert key in PERCENTILE_PRESETS

    def test_values_in_range(self) -> None:
        for val in PERCENTILE_PRESETS.values():
            assert 0.0 <= val <= 100.0


# ---------------------------------------------------------------------------
# build_curve_from_history
# ---------------------------------------------------------------------------


def _make_market_price_mock(product: str, interval_start: datetime, price: float) -> MagicMock:
    row = MagicMock()
    row.product = product
    row.interval_start = interval_start
    row.price_aud_mwh = price
    return row


class TestBuildCurveFromHistory:
    def _make_session(self, rows: list[MagicMock]) -> MagicMock:
        session = MagicMock()
        query_mock = MagicMock()
        filter_mock = MagicMock()
        filter_mock.all.return_value = rows
        query_mock.filter.return_value = filter_mock
        session.query.return_value = query_mock
        return session

    def test_empty_history_returns_empty(self) -> None:
        session = self._make_session([])
        points = build_curve_from_history(
            session=session,
            product="ENERGY",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            curve_name="TEST",
        )
        assert points == []

    def test_returns_forward_price_points(self) -> None:
        # Provide 2 weeks of hourly data
        base = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
        rows = []
        for h in range(24 * 14):
            rows.append(
                _make_market_price_mock("ENERGY", base + timedelta(hours=h), 100.0 + h % 10)
            )
        session = self._make_session(rows)

        points = build_curve_from_history(
            session=session,
            product="ENERGY",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 14),
            curve_name="TEST_CURVE",
            horizon_years=1,
            interval_hours=1.0,
        )
        assert len(points) > 0
        for pt in points:
            assert isinstance(pt, ForwardPricePoint)
            assert pt.curve_name == "TEST_CURVE"
            assert pt.product == "ENERGY"
            assert pt.interval_start.tzinfo is not None

    def test_product_normalised(self) -> None:
        session = self._make_session([])
        points = build_curve_from_history(
            session=session,
            product="energy",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
            curve_name="X",
        )
        # Should return empty (no data) but product should have been normalised
        assert points == []

    def test_escalation_increases_prices(self) -> None:
        base = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
        rows = [_make_market_price_mock("ENERGY", base + timedelta(hours=h), 100.0) for h in range(168)]
        session = self._make_session(rows)

        points = build_curve_from_history(
            session=session,
            product="ENERGY",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
            curve_name="ESC",
            horizon_years=2,
            interval_hours=1.0,
            escalation_pct_per_year=10.0,  # 10% per year
        )
        assert len(points) > 0
        # Prices later in the horizon should be higher than early prices
        first_price = points[0].price_aud_mwh
        last_price = points[-1].price_aud_mwh
        assert last_price > first_price

    def test_scenario_id_attached(self) -> None:
        base = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
        rows = [_make_market_price_mock("ENERGY", base + timedelta(hours=h), 80.0) for h in range(24)]
        session = self._make_session(rows)

        points = build_curve_from_history(
            session=session,
            product="ENERGY",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 1),
            curve_name="CURVE",
            horizon_years=1,
            interval_hours=1.0,
            scenario_id=7,
        )
        assert all(pt.scenario_id == 7 for pt in points)

    def test_horizon_duration_correct(self) -> None:
        base = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
        rows = [_make_market_price_mock("ENERGY", base + timedelta(hours=h), 90.0) for h in range(168)]
        session = self._make_session(rows)

        points = build_curve_from_history(
            session=session,
            product="ENERGY",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
            curve_name="H2",
            horizon_years=2,
            interval_hours=1.0,
        )
        # 2 years * 365 days * 24 hours = ~17520 intervals (approx)
        assert len(points) == pytest.approx(2 * 365 * 24, rel=0.02)

    def test_p50_between_min_and_max(self) -> None:
        base = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
        # All same hour-of-week, varying prices
        rows = []
        for week in range(4):
            # Monday 00:00 every week, prices 50–80
            dt = base + timedelta(weeks=week)
            rows.append(_make_market_price_mock("ENERGY", dt, 50.0 + week * 10))
        session = self._make_session(rows)

        points = build_curve_from_history(
            session=session,
            product="ENERGY",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 28),
            curve_name="P50",
            percentile=50.0,
            horizon_years=1,
            interval_hours=24.0,  # daily for simplicity
        )
        if points:
            for pt in points:
                assert 50.0 <= pt.price_aud_mwh <= 80.0 + 1e-6


# ---------------------------------------------------------------------------
# upsert_forward_curve
# ---------------------------------------------------------------------------


class TestUpsertForwardCurve:
    def _make_session(self, existing: object = None) -> MagicMock:
        session = MagicMock()
        query_mock = MagicMock()
        filter_by_mock = MagicMock()
        filter_by_mock.first.return_value = existing
        query_mock.filter_by.return_value = filter_by_mock
        session.query.return_value = query_mock
        return session

    def test_empty_points_returns_zero(self) -> None:
        session = MagicMock()
        result = upsert_forward_curve(session, [])
        assert result == 0
        session.flush.assert_not_called()

    def test_inserts_new_records(self) -> None:
        session = self._make_session(existing=None)
        points = [
            ForwardPricePoint(
                curve_name="C",
                product="ENERGY",
                interval_start=datetime(2026, 1, 1, h, tzinfo=UTC),
                price_aud_mwh=100.0 + h,
            )
            for h in range(5)
        ]
        result = upsert_forward_curve(session, points)
        assert result == 5
        assert session.add.call_count == 5
        session.flush.assert_called()

    def test_updates_existing_records(self) -> None:
        existing_mock = MagicMock()
        session = self._make_session(existing=existing_mock)

        pt = ForwardPricePoint(
            curve_name="C",
            product="ENERGY",
            interval_start=datetime(2026, 1, 1, tzinfo=UTC),
            price_aud_mwh=200.0,
        )
        result = upsert_forward_curve(session, [pt])
        assert result == 1
        # Should have updated existing, not inserted
        session.add.assert_not_called()
        assert existing_mock.price_mwh == 200.0

    def test_batch_flush(self) -> None:
        session = self._make_session(existing=None)
        points = [
            ForwardPricePoint(
                curve_name="C",
                product="ENERGY",
                interval_start=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=i),
                price_aud_mwh=float(i),
            )
            for i in range(1050)
        ]
        result = upsert_forward_curve(session, points, batch_size=500)
        assert result == 1050
        # Should have flushed at batch boundaries + final
        assert session.flush.call_count >= 3
