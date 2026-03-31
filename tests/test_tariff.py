"""Tests for the Western Power tariff engine."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from app.financial.tariff import (
    BlockTier,
    DemandCharge,
    TariffSchedule,
    TOURate,
    TOUWindow,
    calculate_demand_charge,
    calculate_energy_charge,
    calculate_monthly_bill,
    classify_interval,
)

# ---------------------------------------------------------------------------
# Helper fixtures
# ---------------------------------------------------------------------------

PEAK_WINDOW = TOUWindow(
    name="peak",
    start_hour=7,
    end_hour=23,
    days=["Mon", "Tue", "Wed", "Thu", "Fri"],
)

OFF_PEAK_WINDOW = TOUWindow(
    name="off_peak_shoulder",
    start_hour=0,
    end_hour=7,
    days=["Mon", "Tue", "Wed", "Thu", "Fri"],
)

WEEKEND_WINDOW = TOUWindow(
    name="off_peak_weekend",
    start_hour=0,
    end_hour=24,
    days=["Sat", "Sun"],
)

PEAK_RATE = TOURate(window=PEAK_WINDOW, rate_kwh=0.35)
OFF_PEAK_RATE = TOURate(window=OFF_PEAK_WINDOW, rate_kwh=0.15)
WEEKEND_RATE = TOURate(window=WEEKEND_WINDOW, rate_kwh=0.15)

SIMPLE_TOU_SCHEDULE = TariffSchedule(
    name="Simple TOU",
    tou_rates=[PEAK_RATE, OFF_PEAK_RATE, WEEKEND_RATE],
    dlf=1.05,
    tlf=1.02,
)

BLOCK_SCHEDULE = TariffSchedule(
    name="Block Tariff",
    block_tiers=[
        BlockTier(threshold_kwh=500.0, rate_kwh=0.20),
        BlockTier(threshold_kwh=1000.0, rate_kwh=0.25),
        BlockTier(threshold_kwh=None, rate_kwh=0.30),  # Unlimited final tier
    ],
)

DEMAND_WINDOW = TOUWindow(
    name="demand_peak",
    start_hour=7,
    end_hour=22,
    days=["Mon", "Tue", "Wed", "Thu", "Fri"],
)

DEMAND_SCHEDULE = TariffSchedule(
    name="Demand Tariff",
    tou_rates=[PEAK_RATE],
    demand_charge=DemandCharge(rate_per_kva=15.0, window=DEMAND_WINDOW),
)


def _make_weekday_intervals(
    date_str: str = "2024-01-15",
    hour_start: int = 0,
    hour_end: int = 24,
    kwh_per_interval: float = 1.0,
    kva_per_interval: float = 10.0,
    interval_minutes: int = 30,
) -> pd.DataFrame:
    """Generate synthetic interval data for a weekday (Monday 2024-01-15)."""
    timestamps = pd.date_range(
        start=f"{date_str} {hour_start:02d}:00",
        end=f"{date_str} {hour_end - 1:02d}:30",
        freq=f"{interval_minutes}min",
    )
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "kwh": kwh_per_interval,
            "kva": kva_per_interval,
        }
    )


def _make_weekend_intervals(
    date_str: str = "2024-01-13",  # Saturday
    kwh_per_interval: float = 1.0,
    kva_per_interval: float = 5.0,
    interval_minutes: int = 30,
) -> pd.DataFrame:
    """Generate synthetic interval data for a Saturday."""
    timestamps = pd.date_range(
        start=f"{date_str} 00:00",
        periods=48,
        freq=f"{interval_minutes}min",
    )
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "kwh": kwh_per_interval,
            "kva": kva_per_interval,
        }
    )


# ---------------------------------------------------------------------------
# TOUWindow.applies_to tests
# ---------------------------------------------------------------------------


class TestTOUWindow:
    def test_peak_window_applies_weekday_peak_hour(self) -> None:
        # Monday 12:00 — should be peak
        dt = datetime(2024, 1, 15, 12, 0)  # Monday
        assert PEAK_WINDOW.applies_to(dt) is True

    def test_peak_window_does_not_apply_weekend(self) -> None:
        dt = datetime(2024, 1, 13, 12, 0)  # Saturday
        assert PEAK_WINDOW.applies_to(dt) is False

    def test_peak_window_boundary_start(self) -> None:
        # 07:00 should be peak (start_hour=7 is inclusive)
        dt = datetime(2024, 1, 15, 7, 0)
        assert PEAK_WINDOW.applies_to(dt) is True

    def test_peak_window_boundary_end(self) -> None:
        # 23:00 should NOT be peak (end_hour=23 is exclusive)
        dt = datetime(2024, 1, 15, 23, 0)
        assert PEAK_WINDOW.applies_to(dt) is False

    def test_weekend_window_all_day(self) -> None:
        # Saturday midnight
        dt = datetime(2024, 1, 13, 0, 0)
        assert WEEKEND_WINDOW.applies_to(dt) is True

    def test_off_peak_shoulder_early_morning(self) -> None:
        dt = datetime(2024, 1, 15, 3, 0)
        assert OFF_PEAK_WINDOW.applies_to(dt) is True


# ---------------------------------------------------------------------------
# classify_interval tests
# ---------------------------------------------------------------------------


class TestClassifyInterval:
    def test_peak_classification(self) -> None:
        dt = datetime(2024, 1, 15, 10, 0)  # Monday 10:00
        result = classify_interval(dt, SIMPLE_TOU_SCHEDULE)
        assert result == "peak"

    def test_off_peak_shoulder_classification(self) -> None:
        dt = datetime(2024, 1, 15, 3, 0)  # Monday 03:00
        result = classify_interval(dt, SIMPLE_TOU_SCHEDULE)
        assert result == "off_peak_shoulder"

    def test_weekend_classification(self) -> None:
        dt = datetime(2024, 1, 13, 14, 0)  # Saturday 14:00
        result = classify_interval(dt, SIMPLE_TOU_SCHEDULE)
        assert result == "off_peak_weekend"

    def test_no_matching_window_returns_off_peak(self) -> None:
        # Empty schedule — all intervals are off_peak
        empty_schedule = TariffSchedule(name="empty")
        dt = datetime(2024, 1, 15, 12, 0)
        result = classify_interval(dt, empty_schedule)
        assert result == "off_peak"


# ---------------------------------------------------------------------------
# calculate_energy_charge — TOU tests
# ---------------------------------------------------------------------------


class TestCalculateEnergyChargeTOU:
    def test_pure_peak_day(self) -> None:
        """All peak intervals: DLF×TLF applied to metered kWh, then × rate."""
        # 1 kWh per interval × 32 intervals (07:00–23:00 at 30min) × rate × DLF × TLF
        df = _make_weekday_intervals(hour_start=7, hour_end=23, kwh_per_interval=1.0)
        charge = calculate_energy_charge(df, SIMPLE_TOU_SCHEDULE)
        # 16h × 2 intervals/h = 32 intervals × 1 kWh × 1.05 × 1.02 × 0.35
        expected = 32 * 1.0 * 1.05 * 1.02 * 0.35
        assert abs(charge - expected) < 0.01

    def test_dlf_tlf_applied(self) -> None:
        """Without DLF/TLF (=1.0), charge should be plain kWh × rate."""
        flat_schedule = TariffSchedule(
            name="Flat TOU",
            tou_rates=[TOURate(window=PEAK_WINDOW, rate_kwh=0.30)],
            dlf=1.0,
            tlf=1.0,
        )
        df = pd.DataFrame(
            {
                "timestamp": [datetime(2024, 1, 15, 12, 0)],  # Monday peak
                "kwh": [100.0],
                "kva": [50.0],
            }
        )
        charge = calculate_energy_charge(df, flat_schedule)
        assert abs(charge - 30.0) < 0.001  # 100 kWh × $0.30

    def test_weekend_off_peak_rate(self) -> None:
        df = _make_weekend_intervals(kwh_per_interval=1.0)
        charge = calculate_energy_charge(df, SIMPLE_TOU_SCHEDULE)
        # 48 intervals × 1 kWh × 1.05 × 1.02 × 0.15
        expected = 48 * 1.0 * 1.05 * 1.02 * 0.15
        assert abs(charge - expected) < 0.01

    def test_zero_energy(self) -> None:
        df = _make_weekday_intervals(kwh_per_interval=0.0)
        charge = calculate_energy_charge(df, SIMPLE_TOU_SCHEDULE)
        assert charge == 0.0


# ---------------------------------------------------------------------------
# calculate_energy_charge — block tier tests
# ---------------------------------------------------------------------------


class TestCalculateEnergyChargeBlock:
    def test_single_tier(self) -> None:
        """Usage below first threshold → only tier-1 rate applies."""
        df = pd.DataFrame(
            {
                "timestamp": [datetime(2024, 1, 15, 12, 0)] * 10,
                "kwh": [40.0] * 10,  # 400 kWh total — under 500 kWh threshold
                "kva": [20.0] * 10,
            }
        )
        charge = calculate_energy_charge(df, BLOCK_SCHEDULE)
        assert abs(charge - 400 * 0.20) < 0.001

    def test_crosses_first_threshold(self) -> None:
        """600 kWh: first 500 at 0.20, next 100 at 0.25."""
        df = pd.DataFrame(
            {
                "timestamp": [datetime(2024, 1, 15, 12, 0)] * 6,
                "kwh": [100.0] * 6,  # 600 kWh
                "kva": [20.0] * 6,
            }
        )
        charge = calculate_energy_charge(df, BLOCK_SCHEDULE)
        expected = 500 * 0.20 + 100 * 0.25
        assert abs(charge - expected) < 0.001

    def test_crosses_both_thresholds(self) -> None:
        """1800 kWh: 500@0.20 + 1000@0.25 + 300@0.30."""
        df = pd.DataFrame(
            {
                "timestamp": [datetime(2024, 1, 15, 12, 0)] * 18,
                "kwh": [100.0] * 18,  # 1800 kWh
                "kva": [20.0] * 18,
            }
        )
        charge = calculate_energy_charge(df, BLOCK_SCHEDULE)
        expected = 500 * 0.20 + 1000 * 0.25 + 300 * 0.30
        assert abs(charge - expected) < 0.001


# ---------------------------------------------------------------------------
# calculate_demand_charge tests
# ---------------------------------------------------------------------------


class TestCalculateDemandCharge:
    def test_no_demand_charge_configured(self) -> None:
        df = _make_weekday_intervals()
        charge = calculate_demand_charge(df, SIMPLE_TOU_SCHEDULE)
        assert charge == 0.0

    def test_peak_kva_in_demand_window(self) -> None:
        """Peak kVA during demand window × rate."""
        df = pd.DataFrame(
            {
                "timestamp": [
                    datetime(2024, 1, 15, 9, 0),  # Monday 09:00 — in demand window
                    datetime(2024, 1, 15, 14, 0),  # Monday 14:00 — in demand window (peak kVA)
                    datetime(2024, 1, 15, 23, 30),  # Monday 23:30 — outside demand window
                ],
                "kwh": [10.0, 10.0, 10.0],
                "kva": [100.0, 250.0, 500.0],  # 500 kVA at 23:30 is outside window
            }
        )
        charge = calculate_demand_charge(df, DEMAND_SCHEDULE)
        # Peak within window (07:00–22:00) = 250 kVA × $15/kVA
        assert abs(charge - 250.0 * 15.0) < 0.001

    def test_demand_charge_no_window_uses_all_hours(self) -> None:
        """DemandCharge with window=None includes all hours."""
        all_hours_demand = TariffSchedule(
            name="Demand All Hours",
            demand_charge=DemandCharge(rate_per_kva=10.0, window=None),
        )
        df = pd.DataFrame(
            {
                "timestamp": [datetime(2024, 1, 15, 3, 0)],  # Off-peak hour
                "kwh": [5.0],
                "kva": [200.0],
            }
        )
        charge = calculate_demand_charge(df, all_hours_demand)
        assert abs(charge - 200.0 * 10.0) < 0.001

    def test_empty_demand_window_returns_zero(self) -> None:
        """If no intervals fall in the demand window, charge = 0."""
        weekend_df = _make_weekend_intervals()
        charge = calculate_demand_charge(weekend_df, DEMAND_SCHEDULE)
        # demand window is weekdays only — weekend intervals excluded
        assert charge == 0.0


# ---------------------------------------------------------------------------
# calculate_monthly_bill tests
# ---------------------------------------------------------------------------


class TestCalculateMonthlyBill:
    def test_monthly_bill_keys(self) -> None:
        df = _make_weekday_intervals()
        bill = calculate_monthly_bill(df, SIMPLE_TOU_SCHEDULE)
        assert "energy_charge" in bill
        assert "demand_charge" in bill
        assert "total" in bill

    def test_total_equals_energy_plus_demand(self) -> None:
        df = _make_weekday_intervals()
        bill = calculate_monthly_bill(df, DEMAND_SCHEDULE)
        assert abs(bill["total"] - (bill["energy_charge"] + bill["demand_charge"])) < 0.001

    def test_tou_window_breakdown_in_bill(self) -> None:
        df = _make_weekday_intervals(hour_start=7, hour_end=23, kwh_per_interval=1.0)
        bill = calculate_monthly_bill(df, SIMPLE_TOU_SCHEDULE)
        # peak window charge should be present
        assert "peak" in bill
        assert bill["peak"] > 0

    def test_no_demand_charge_without_kva(self) -> None:
        """If kva column is absent, demand charge = 0."""
        df = pd.DataFrame(
            {
                "timestamp": [datetime(2024, 1, 15, 12, 0)],
                "kwh": [100.0],
            }
        )
        bill = calculate_monthly_bill(df, DEMAND_SCHEDULE)
        assert bill["demand_charge"] == 0.0

    def test_combined_loss_factor_applied(self) -> None:
        """Bill energy charge must reflect DLF × TLF scaling."""
        schedule_no_loss = TariffSchedule(
            name="No Loss",
            tou_rates=[TOURate(window=PEAK_WINDOW, rate_kwh=0.30)],
            dlf=1.0,
            tlf=1.0,
        )
        schedule_with_loss = TariffSchedule(
            name="With Loss",
            tou_rates=[TOURate(window=PEAK_WINDOW, rate_kwh=0.30)],
            dlf=1.05,
            tlf=1.02,
        )
        df = pd.DataFrame(
            {
                "timestamp": [datetime(2024, 1, 15, 12, 0)],
                "kwh": [100.0],
                "kva": [50.0],
            }
        )
        bill_no = calculate_monthly_bill(df, schedule_no_loss)
        bill_with = calculate_monthly_bill(df, schedule_with_loss)
        # With loss factor > 1, energy charge must be higher
        assert bill_with["energy_charge"] > bill_no["energy_charge"]
        ratio = bill_with["energy_charge"] / bill_no["energy_charge"]
        assert abs(ratio - 1.05 * 1.02) < 0.001
