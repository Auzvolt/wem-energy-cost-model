"""Tests for assumption library models and repository logic."""
from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.assumptions.models import (
    AssumptionCategory,
    AssumptionEntry,
    AssumptionSet,
    CapexAssumption,
    DegradationCurve,
    SolarYieldProfile,
    TariffScheduleAssumption,
)


# ---------------------------------------------------------------------------
# AssumptionSet model tests
# ---------------------------------------------------------------------------

class TestAssumptionSet:
    def test_is_active_when_not_superseded(self) -> None:
        assumption_set = AssumptionSet(
            name="FY2025",
            effective_from=date(2025, 1, 1),
        )
        assert assumption_set.is_active is True

    def test_is_inactive_when_superseded(self) -> None:
        import uuid
        assumption_set = AssumptionSet(
            name="FY2024",
            effective_from=date(2024, 1, 1),
            superseded_by=uuid.uuid4(),
        )
        assert assumption_set.is_active is False

    def test_default_entries_is_empty_list(self) -> None:
        assumption_set = AssumptionSet(
            name="Base",
            effective_from=date(2025, 6, 1),
        )
        assert assumption_set.entries == []

    def test_entry_serialisation_roundtrip(self) -> None:
        assumption_set = AssumptionSet(
            name="Base",
            effective_from=date(2025, 6, 1),
        )
        data = assumption_set.model_dump()
        restored = AssumptionSet.model_validate(data)
        assert restored.name == "Base"
        assert restored.effective_from == date(2025, 6, 1)


# ---------------------------------------------------------------------------
# AssumptionEntry model tests
# ---------------------------------------------------------------------------

class TestAssumptionEntry:
    def test_create_entry_with_dict_value(self) -> None:
        import uuid
        set_id = uuid.uuid4()
        entry = AssumptionEntry(
            set_id=set_id,
            category=AssumptionCategory.TARIFF,
            key="wem_a2_tariff",
            value={"peak_rate": 0.28, "offpeak_rate": 0.12},
            unit="$/kWh",
        )
        assert entry.key == "wem_a2_tariff"
        assert entry.value["peak_rate"] == 0.28
        assert entry.unit == "$/kWh"

    def test_create_entry_with_numeric_value(self) -> None:
        import uuid
        entry = AssumptionEntry(
            set_id=uuid.uuid4(),
            category=AssumptionCategory.CAPEX,
            key="solar_installed_cost",
            value=1200.0,
            unit="$/kW",
        )
        assert entry.category == AssumptionCategory.CAPEX
        assert entry.value == 1200.0

    def test_entry_id_auto_generated(self) -> None:
        import uuid
        entry = AssumptionEntry(
            set_id=uuid.uuid4(),
            category=AssumptionCategory.OPEX,
            key="maintenance_rate",
            value=15.0,
        )
        assert isinstance(entry.id, uuid.UUID)


# ---------------------------------------------------------------------------
# Typed assumption wrapper tests
# ---------------------------------------------------------------------------

class TestTariffScheduleAssumption:
    def test_default_empty_tou_windows(self) -> None:
        tariff = TariffScheduleAssumption(name="Synergy A2")
        assert tariff.tou_windows == []
        assert tariff.daily_charge == 0.0
        assert tariff.dlf == 1.0

    def test_tou_window_with_demand_charge(self) -> None:
        tariff = TariffScheduleAssumption(
            name="C&I tariff",
            tou_windows=[
                {"label": "peak", "start": "07:00", "end": "23:00", "rate": 0.30},
                {"label": "offpeak", "start": "23:00", "end": "07:00", "rate": 0.10},
            ],
            demand_charge={"rate": 12.50, "unit": "$/kW/month"},
            daily_charge=1.20,
        )
        assert len(tariff.tou_windows) == 2
        assert tariff.demand_charge["rate"] == 12.50
        assert tariff.daily_charge == 1.20


class TestCapexAssumption:
    def test_solar_capex(self) -> None:
        capex = CapexAssumption(
            asset_type="solar_pv",
            cost_per_unit=1100.0,
            unit="$/kW",
            installation_factor=1.15,
        )
        assert capex.asset_type == "solar_pv"
        assert capex.contingency_pct == 0.0  # default

    def test_effective_cost_calculation(self) -> None:
        capex = CapexAssumption(
            asset_type="bess",
            cost_per_unit=500.0,
            unit="$/kWh",
            installation_factor=1.2,
            contingency_pct=0.10,
        )
        effective = capex.cost_per_unit * capex.installation_factor * (1 + capex.contingency_pct)
        assert effective == pytest.approx(660.0, rel=1e-5)


class TestDegradationCurve:
    def test_lfp_defaults(self) -> None:
        curve = DegradationCurve(
            chemistry="LFP",
            capacity_fade_pct_per_cycle=0.003,
            calendar_degradation_pct_per_year=1.5,
        )
        assert curve.eol_capacity_pct == 80.0

    def test_custom_eol(self) -> None:
        curve = DegradationCurve(
            chemistry="NMC",
            capacity_fade_pct_per_cycle=0.005,
            calendar_degradation_pct_per_year=2.0,
            eol_capacity_pct=75.0,
        )
        assert curve.eol_capacity_pct == 75.0


class TestSolarYieldProfile:
    def _perth_profile(self) -> SolarYieldProfile:
        # Synthetic monthly CFs for Perth-like climate (high summer, lower winter)
        return SolarYieldProfile(
            location="Perth, WA",
            monthly_cf=[0.28, 0.26, 0.22, 0.18, 0.15, 0.13, 0.14, 0.17, 0.21, 0.25, 0.27, 0.29],
        )

    def test_twelve_months_required(self) -> None:
        profile = self._perth_profile()
        assert len(profile.monthly_cf) == 12

    def test_annual_yield_approximation(self) -> None:
        profile = self._perth_profile()
        # Must be positive and plausible (1200–2000 kWh/kWp/yr for Perth)
        yield_kwh = profile.annual_yield_kwh_per_kwp()
        assert 1200 < yield_kwh < 2200

    def test_default_tracking_is_fixed(self) -> None:
        profile = self._perth_profile()
        assert profile.tracking == "fixed"
