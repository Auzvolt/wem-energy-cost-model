"""Tests for app.optimisation.solar -- Solar PV asset model.

Covers:
  - SolarConfig validation
  - synthetic_generation_profile_kw()
  - ac_generation_kw()
  - add_solar_constraints() model structure and correctness
"""

from __future__ import annotations

import math
from typing import Any

import pytest
from pydantic import ValidationError

from app.optimisation.solar import (
    SolarConfig,
    ac_generation_kw,
    add_solar_constraints,
    synthetic_generation_profile_kw,
)

pyo = pytest.importorskip("pyomo.environ", reason="pyomo not installed")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_model(n_intervals: int = 4) -> Any:
    """Return a minimal ConcreteModel with a T set."""
    m = pyo.ConcreteModel(name="TestSolar")
    m.T = pyo.Set(initialize=range(n_intervals), ordered=True)
    return m


# ---------------------------------------------------------------------------
# SolarConfig validation
# ---------------------------------------------------------------------------


class TestSolarConfig:
    def test_defaults(self) -> None:
        cfg = SolarConfig(system_capacity_kwp=100.0)
        assert cfg.dc_ac_ratio == pytest.approx(1.2)
        assert cfg.efficiency_factor == pytest.approx(0.80)
        assert cfg.curtailment_cost_aud_per_kwh == pytest.approx(0.0)
        assert cfg.irradiance_w_per_m2 is None
        assert cfg.panel_area_m2 is None

    def test_zero_capacity_raises(self) -> None:
        with pytest.raises(ValidationError):
            SolarConfig(system_capacity_kwp=0.0)

    def test_negative_capacity_raises(self) -> None:
        with pytest.raises(ValidationError):
            SolarConfig(system_capacity_kwp=-10.0)

    def test_dc_ac_ratio_below_one_raises(self) -> None:
        with pytest.raises(ValidationError):
            SolarConfig(system_capacity_kwp=100.0, dc_ac_ratio=0.9)

    def test_efficiency_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            SolarConfig(system_capacity_kwp=100.0, efficiency_factor=0.0)

    def test_efficiency_above_one_raises(self) -> None:
        with pytest.raises(ValidationError):
            SolarConfig(system_capacity_kwp=100.0, efficiency_factor=1.1)

    def test_negative_curtailment_cost_raises(self) -> None:
        with pytest.raises(ValidationError):
            SolarConfig(system_capacity_kwp=100.0, curtailment_cost_aud_per_kwh=-0.01)

    def test_custom_values_accepted(self) -> None:
        cfg = SolarConfig(
            system_capacity_kwp=200.0,
            dc_ac_ratio=1.35,
            efficiency_factor=0.75,
            curtailment_cost_aud_per_kwh=0.05,
        )
        assert cfg.system_capacity_kwp == pytest.approx(200.0)
        assert cfg.dc_ac_ratio == pytest.approx(1.35)

    def test_dc_ac_ratio_exactly_one_allowed(self) -> None:
        cfg = SolarConfig(system_capacity_kwp=100.0, dc_ac_ratio=1.0)
        assert cfg.dc_ac_ratio == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# synthetic_generation_profile_kw()
# ---------------------------------------------------------------------------


class TestSyntheticProfile:
    def test_length(self) -> None:
        profile = synthetic_generation_profile_kw(
            n_intervals=48, interval_duration_h=0.5, system_capacity_kwp=100.0
        )
        assert len(profile) == 48

    def test_no_generation_at_night(self) -> None:
        # Interval 0 = 00:00, before 06:00 → zero
        profile = synthetic_generation_profile_kw(
            n_intervals=48, interval_duration_h=0.5, system_capacity_kwp=100.0
        )
        assert profile[0] == pytest.approx(0.0)   # 00:00
        assert profile[11] == pytest.approx(0.0)  # 05:30

    def test_generation_during_day(self) -> None:
        profile = synthetic_generation_profile_kw(
            n_intervals=48, interval_duration_h=0.5, system_capacity_kwp=100.0
        )
        # Interval 24 = 12:00 (solar noon) — should be near peak
        assert profile[24] > 0.0

    def test_peak_at_noon(self) -> None:
        # Use dc_ac_ratio=1.0 to avoid inverter clipping so the true sine peak is at noon
        profile = synthetic_generation_profile_kw(
            n_intervals=48, interval_duration_h=0.5, system_capacity_kwp=100.0, dc_ac_ratio=1.0
        )
        peak_idx = profile.index(max(profile))
        # Peak should be around interval 24 (12:00)
        assert 22 <= peak_idx <= 26

    def test_inverter_clipping(self) -> None:
        # dc_ac_ratio=1 means inverter ceiling == system_capacity_kwp
        profile_no_clip = synthetic_generation_profile_kw(
            n_intervals=48,
            interval_duration_h=0.5,
            system_capacity_kwp=100.0,
            efficiency_factor=1.0,
            dc_ac_ratio=1.0,
        )
        # dc_ac_ratio=2 → inverter ceiling = 50 kW
        profile_clipped = synthetic_generation_profile_kw(
            n_intervals=48,
            interval_duration_h=0.5,
            system_capacity_kwp=100.0,
            efficiency_factor=1.0,
            dc_ac_ratio=2.0,
        )
        assert max(profile_clipped) <= 50.0 + 1e-9
        assert max(profile_no_clip) > max(profile_clipped)

    def test_all_non_negative(self) -> None:
        profile = synthetic_generation_profile_kw(
            n_intervals=48, interval_duration_h=0.5, system_capacity_kwp=100.0
        )
        assert all(v >= 0.0 for v in profile)

    def test_efficiency_factor_scales_output(self) -> None:
        profile_80 = synthetic_generation_profile_kw(
            n_intervals=48,
            interval_duration_h=0.5,
            system_capacity_kwp=100.0,
            efficiency_factor=0.80,
        )
        profile_50 = synthetic_generation_profile_kw(
            n_intervals=48,
            interval_duration_h=0.5,
            system_capacity_kwp=100.0,
            efficiency_factor=0.50,
        )
        # 80% efficient should produce more than 50%
        assert max(profile_80) > max(profile_50)


# ---------------------------------------------------------------------------
# ac_generation_kw()
# ---------------------------------------------------------------------------


class TestAcGenerationKw:
    def test_synthetic_path(self) -> None:
        cfg = SolarConfig(system_capacity_kwp=100.0)
        profile = ac_generation_kw(cfg, n_intervals=48, interval_duration_h=0.5)
        assert len(profile) == 48
        assert all(v >= 0.0 for v in profile)

    def test_irradiance_path(self) -> None:
        irr = [500.0] * 4
        cfg = SolarConfig(
            system_capacity_kwp=100.0,
            irradiance_w_per_m2=irr,
            panel_area_m2=200.0,
        )
        profile = ac_generation_kw(cfg, n_intervals=4, interval_duration_h=0.5)
        assert len(profile) == 4
        # dc_kw = 500 * 200 / 1000 = 100 kW; inverter = 100/1.2 ≈ 83.33 kW; × 0.8 ≈ 66.67 kW
        expected = min(100.0, 100.0 / 1.2) * 0.80
        assert all(v == pytest.approx(expected, rel=1e-4) for v in profile)

    def test_irradiance_wrong_length_raises(self) -> None:
        cfg = SolarConfig(
            system_capacity_kwp=100.0,
            irradiance_w_per_m2=[500.0] * 3,
            panel_area_m2=200.0,
        )
        with pytest.raises(ValueError, match="length"):
            ac_generation_kw(cfg, n_intervals=4, interval_duration_h=0.5)

    def test_irradiance_without_area_raises(self) -> None:
        cfg = SolarConfig(
            system_capacity_kwp=100.0,
            irradiance_w_per_m2=[500.0] * 4,
        )
        with pytest.raises(ValueError, match="panel_area_m2"):
            ac_generation_kw(cfg, n_intervals=4, interval_duration_h=0.5)

    def test_zero_irradiance_gives_zero(self) -> None:
        cfg = SolarConfig(
            system_capacity_kwp=100.0,
            irradiance_w_per_m2=[0.0] * 4,
            panel_area_m2=200.0,
        )
        profile = ac_generation_kw(cfg, n_intervals=4, interval_duration_h=0.5)
        assert all(v == pytest.approx(0.0) for v in profile)


# ---------------------------------------------------------------------------
# add_solar_constraints()
# ---------------------------------------------------------------------------


class TestAddSolarConstraints:
    def _cfg(self, **kwargs: Any) -> SolarConfig:
        defaults: dict[str, Any] = {"system_capacity_kwp": 100.0}
        defaults.update(kwargs)
        return SolarConfig(**defaults)

    def test_components_created(self) -> None:
        m = _make_model(4)
        cfg = self._cfg()
        add_solar_constraints(m, cfg, n_intervals=4, interval_duration_h=0.5)
        assert hasattr(m, "solar_max_gen_kw")
        assert hasattr(m, "solar_gen_kw")
        assert hasattr(m, "solar_curtailed_kw")
        assert hasattr(m, "solar_gen_balance")
        assert hasattr(m, "solar_total_gen_kwh")
        assert hasattr(m, "solar_curtailment_cost_aud")

    def test_constraint_count(self) -> None:
        n = 6
        m = _make_model(n)
        cfg = self._cfg()
        add_solar_constraints(m, cfg, n_intervals=n, interval_duration_h=0.5)
        assert len(list(m.solar_gen_balance)) == n

    def test_gen_balance_holds_at_init(self) -> None:
        """At initialisation gen + curtailed == max_gen for each interval."""
        m = _make_model(4)
        cfg = self._cfg()
        add_solar_constraints(m, cfg, n_intervals=4, interval_duration_h=0.5)
        for t in range(4):
            lhs = pyo.value(m.solar_gen_kw[t]) + pyo.value(m.solar_curtailed_kw[t])
            rhs = pyo.value(m.solar_max_gen_kw[t])
            assert lhs == pytest.approx(rhs, abs=1e-9)

    def test_solar_gen_non_negative(self) -> None:
        m = _make_model(4)
        cfg = self._cfg()
        add_solar_constraints(m, cfg, n_intervals=4, interval_duration_h=0.5)
        for t in range(4):
            assert pyo.value(m.solar_gen_kw[t]) >= -1e-9

    def test_mismatched_n_intervals_raises(self) -> None:
        m = _make_model(4)
        cfg = self._cfg()
        with pytest.raises(ValueError, match="n_intervals"):
            add_solar_constraints(m, cfg, n_intervals=5, interval_duration_h=0.5)

    def test_empty_T_no_op(self) -> None:
        m = _make_model(0)
        cfg = self._cfg()
        add_solar_constraints(m, cfg, n_intervals=0, interval_duration_h=0.5)
        assert not hasattr(m, "solar_gen_kw")

    def test_total_gen_kwh_expression(self) -> None:
        """Total kWh = sum(gen_kw[t] * interval_h)."""
        m = _make_model(4)
        cfg = self._cfg()
        interval_h = 0.5
        add_solar_constraints(m, cfg, n_intervals=4, interval_duration_h=interval_h)
        expected = sum(
            pyo.value(m.solar_gen_kw[t]) * interval_h for t in range(4)
        )
        assert float(pyo.value(m.solar_total_gen_kwh)) == pytest.approx(expected, rel=1e-6)

    def test_curtailment_cost_zero_by_default(self) -> None:
        m = _make_model(4)
        cfg = self._cfg()  # curtailment_cost_aud_per_kwh=0
        add_solar_constraints(m, cfg, n_intervals=4, interval_duration_h=0.5)
        assert float(pyo.value(m.solar_curtailment_cost_aud)) == pytest.approx(0.0)

    def test_curtailment_cost_non_zero(self) -> None:
        """Force curtailment by manually setting gen_kw below max, check cost."""
        m = _make_model(4)
        cfg = self._cfg(curtailment_cost_aud_per_kwh=0.10)
        interval_h = 0.5
        add_solar_constraints(m, cfg, n_intervals=4, interval_duration_h=interval_h)
        # Manually curtail 10 kW at interval 2
        max_gen = pyo.value(m.solar_max_gen_kw[2])
        curtailed_kw = min(10.0, max_gen)
        m.solar_gen_kw[2].set_value(max_gen - curtailed_kw)
        m.solar_curtailed_kw[2].set_value(curtailed_kw)
        cost = float(pyo.value(m.solar_curtailment_cost_aud))
        assert cost == pytest.approx(curtailed_kw * interval_h * 0.10, rel=1e-6)

    def test_irradiance_profile_integration(self) -> None:
        """Irradiance-based profile feeds correctly into Pyomo model."""
        n = 4
        irr = [0.0, 300.0, 800.0, 0.0]
        cfg = SolarConfig(
            system_capacity_kwp=100.0,
            irradiance_w_per_m2=irr,
            panel_area_m2=200.0,
        )
        m = _make_model(n)
        add_solar_constraints(m, cfg, n_intervals=n, interval_duration_h=0.5)
        # Interval 0: irradiance=0 → max_gen=0
        assert pyo.value(m.solar_max_gen_kw[0]) == pytest.approx(0.0)
        # Interval 2: irradiance=800 W/m²; dc=800×200/1000=160kW; inverter=83.33kW; ×0.8=66.67kW
        expected_t2 = min(800.0 * 200.0 / 1000.0, 100.0 / 1.2) * 0.80
        assert pyo.value(m.solar_max_gen_kw[2]) == pytest.approx(expected_t2, rel=1e-4)


# ---------------------------------------------------------------------------
# DC/AC clipping verification (pure function)
# ---------------------------------------------------------------------------


class TestDcAcClipping:
    def test_clipping_reduces_peak(self) -> None:
        """Higher dc_ac_ratio should produce lower (or equal) peak AC output."""
        profile_1_0 = synthetic_generation_profile_kw(
            n_intervals=48,
            interval_duration_h=0.5,
            system_capacity_kwp=100.0,
            efficiency_factor=1.0,
            dc_ac_ratio=1.0,
        )
        profile_1_5 = synthetic_generation_profile_kw(
            n_intervals=48,
            interval_duration_h=0.5,
            system_capacity_kwp=100.0,
            efficiency_factor=1.0,
            dc_ac_ratio=1.5,
        )
        assert max(profile_1_0) >= max(profile_1_5)

    def test_no_clipping_peak_equals_capacity_times_efficiency(self) -> None:
        """With dc_ac_ratio=1 and noon irradiance, peak ≈ capacity × efficiency."""
        profile = synthetic_generation_profile_kw(
            n_intervals=48,
            interval_duration_h=0.5,
            system_capacity_kwp=100.0,
            efficiency_factor=1.0,
            dc_ac_ratio=1.0,
        )
        # Peak at interval 24 = 12:00 → sin(π/2)=1 → dc=100kW, inverter ceiling=100kW
        assert max(profile) == pytest.approx(100.0 * math.sin(math.pi / 2), rel=1e-4)
