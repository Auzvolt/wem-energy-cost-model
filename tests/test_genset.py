"""Tests for diesel/gas genset asset model (issue #24)."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from app.optimisation.genset import GensetConfig, add_genset_constraints, fuel_cost_aud

# ---------------------------------------------------------------------------
# GensetConfig tests
# ---------------------------------------------------------------------------


class TestGensetConfig:
    def test_fields_stored(self) -> None:
        cfg = GensetConfig(
            capacity_kw=500.0,
            heat_rate_gj_per_mwh=10.5,
            fuel_cost_aud_per_gj=8.0,
        )
        assert cfg.capacity_kw == 500.0
        assert cfg.heat_rate_gj_per_mwh == 10.5
        assert cfg.fuel_cost_aud_per_gj == 8.0

    def test_defaults(self) -> None:
        cfg = GensetConfig(
            capacity_kw=100.0,
            heat_rate_gj_per_mwh=11.0,
            fuel_cost_aud_per_gj=9.0,
        )
        assert cfg.min_loading_pct == 0.30
        assert cfg.ramp_rate_kw_per_min is None
        assert cfg.start_cost_aud == 0.0
        assert cfg.stop_cost_aud == 0.0
        assert cfg.availability_factor == 1.0

    def test_capacity_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            GensetConfig(capacity_kw=0, heat_rate_gj_per_mwh=10, fuel_cost_aud_per_gj=8)

    def test_heat_rate_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            GensetConfig(capacity_kw=100, heat_rate_gj_per_mwh=0, fuel_cost_aud_per_gj=8)

    def test_fuel_cost_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            GensetConfig(capacity_kw=100, heat_rate_gj_per_mwh=10, fuel_cost_aud_per_gj=-1)

    def test_min_loading_must_be_less_than_1(self) -> None:
        with pytest.raises(ValidationError):
            GensetConfig(
                capacity_kw=100,
                heat_rate_gj_per_mwh=10,
                fuel_cost_aud_per_gj=8,
                min_loading_pct=1.0,
            )

    def test_availability_must_be_gt_zero(self) -> None:
        with pytest.raises(ValidationError):
            GensetConfig(
                capacity_kw=100,
                heat_rate_gj_per_mwh=10,
                fuel_cost_aud_per_gj=8,
                availability_factor=0.0,
            )

    # Derived properties

    def test_effective_capacity(self) -> None:
        cfg = GensetConfig(
            capacity_kw=1000.0,
            heat_rate_gj_per_mwh=10.0,
            fuel_cost_aud_per_gj=8.0,
            availability_factor=0.85,
        )
        assert math.isclose(cfg.effective_capacity_kw, 850.0)

    def test_min_dispatch_kw(self) -> None:
        cfg = GensetConfig(
            capacity_kw=500.0,
            heat_rate_gj_per_mwh=10.0,
            fuel_cost_aud_per_gj=8.0,
            min_loading_pct=0.25,
        )
        assert math.isclose(cfg.min_dispatch_kw, 125.0)

    def test_variable_cost_aud_per_kwh(self) -> None:
        # 10 GJ/MWh * 8 AUD/GJ / 1000 = 0.08 AUD/kWh
        cfg = GensetConfig(
            capacity_kw=500.0,
            heat_rate_gj_per_mwh=10.0,
            fuel_cost_aud_per_gj=8.0,
        )
        assert math.isclose(cfg.variable_cost_aud_per_kwh, 0.08)

    def test_variable_cost_with_high_heat_rate(self) -> None:
        cfg = GensetConfig(
            capacity_kw=100.0,
            heat_rate_gj_per_mwh=12.0,
            fuel_cost_aud_per_gj=10.0,
        )
        # 12 * 10 / 1000 = 0.12
        assert math.isclose(cfg.variable_cost_aud_per_kwh, 0.12)


# ---------------------------------------------------------------------------
# fuel_cost_aud tests
# ---------------------------------------------------------------------------


class TestFuelCostAud:
    def test_zero_dispatch(self) -> None:
        cfg = GensetConfig(capacity_kw=500, heat_rate_gj_per_mwh=10, fuel_cost_aud_per_gj=8)
        assert fuel_cost_aud(cfg, 0.0) == 0.0

    def test_half_hour_interval(self) -> None:
        cfg = GensetConfig(capacity_kw=500, heat_rate_gj_per_mwh=10, fuel_cost_aud_per_gj=8)
        # 500 kW * 0.5 h = 250 kWh = 0.25 MWh
        # 0.25 MWh * 10 GJ/MWh * 8 AUD/GJ = 20 AUD
        result = fuel_cost_aud(cfg, 500.0, interval_duration_h=0.5)
        assert math.isclose(result, 20.0)

    def test_one_hour_interval(self) -> None:
        cfg = GensetConfig(capacity_kw=500, heat_rate_gj_per_mwh=10, fuel_cost_aud_per_gj=8)
        # 500 kW * 1.0 h = 500 kWh = 0.5 MWh
        # 0.5 * 10 * 8 = 40 AUD
        result = fuel_cost_aud(cfg, 500.0, interval_duration_h=1.0)
        assert math.isclose(result, 40.0)

    def test_partial_load(self) -> None:
        cfg = GensetConfig(capacity_kw=1000, heat_rate_gj_per_mwh=11, fuel_cost_aud_per_gj=9)
        # 300 kW * 0.5 h = 0.15 MWh; 0.15 * 11 * 9 = 14.85
        result = fuel_cost_aud(cfg, 300.0, interval_duration_h=0.5)
        assert math.isclose(result, 14.85)

    def test_negative_dispatch_raises(self) -> None:
        cfg = GensetConfig(capacity_kw=500, heat_rate_gj_per_mwh=10, fuel_cost_aud_per_gj=8)
        with pytest.raises(ValueError, match="dispatch_kw"):
            fuel_cost_aud(cfg, -1.0)

    def test_zero_interval_raises(self) -> None:
        cfg = GensetConfig(capacity_kw=500, heat_rate_gj_per_mwh=10, fuel_cost_aud_per_gj=8)
        with pytest.raises(ValueError, match="interval_duration_h"):
            fuel_cost_aud(cfg, 100.0, interval_duration_h=0.0)

    def test_free_fuel(self) -> None:
        cfg = GensetConfig(capacity_kw=500, heat_rate_gj_per_mwh=10, fuel_cost_aud_per_gj=0)
        assert fuel_cost_aud(cfg, 500.0) == 0.0


# ---------------------------------------------------------------------------
# add_genset_constraints tests
# ---------------------------------------------------------------------------


class TestAddGensetConstraints:
    """These tests require pyomo. Skipped if pyomo not installed."""

    @pytest.fixture
    def pyomo_model(self) -> pyo.ConcreteModel:  # noqa: F821
        pyomo = pytest.importorskip("pyomo.environ")
        return pyomo.ConcreteModel()

    def test_variables_added(self, pyomo_model: Any) -> None:
        cfg = GensetConfig(capacity_kw=500, heat_rate_gj_per_mwh=10, fuel_cost_aud_per_gj=8)
        result = add_genset_constraints(pyomo_model, cfg, n_intervals=48)
        assert "genset_dispatch" in result["variables"]
        assert "genset_online" in result["variables"]
        assert "genset_start" in result["variables"]
        assert "genset_stop" in result["variables"]

    def test_constraints_added(self, pyomo_model: Any) -> None:
        cfg = GensetConfig(capacity_kw=500, heat_rate_gj_per_mwh=10, fuel_cost_aud_per_gj=8)
        result = add_genset_constraints(pyomo_model, cfg, n_intervals=48)
        assert "genset_min_load" in result["constraints"]
        assert "genset_max_cap" in result["constraints"]
        assert "genset_logical" in result["constraints"]

    def test_ramp_constraints_added_when_configured(self, pyomo_model: Any) -> None:
        cfg = GensetConfig(
            capacity_kw=500,
            heat_rate_gj_per_mwh=10,
            fuel_cost_aud_per_gj=8,
            ramp_rate_kw_per_min=10.0,
        )
        result = add_genset_constraints(pyomo_model, cfg, n_intervals=48)
        assert "genset_ramp_up" in result["constraints"]
        assert "genset_ramp_dn" in result["constraints"]

    def test_no_ramp_constraints_without_config(self, pyomo_model: Any) -> None:
        cfg = GensetConfig(capacity_kw=500, heat_rate_gj_per_mwh=10, fuel_cost_aud_per_gj=8)
        result = add_genset_constraints(pyomo_model, cfg, n_intervals=48)
        assert "genset_ramp_up" not in result["constraints"]
        assert "genset_ramp_dn" not in result["constraints"]

    def test_custom_prefix(self, pyomo_model: Any) -> None:
        cfg = GensetConfig(capacity_kw=500, heat_rate_gj_per_mwh=10, fuel_cost_aud_per_gj=8)
        result = add_genset_constraints(pyomo_model, cfg, n_intervals=10, name_prefix="gen1")
        assert all("gen1" in name for name in result["variables"])

    def test_invalid_n_intervals_raises(self, pyomo_model: Any) -> None:
        cfg = GensetConfig(capacity_kw=500, heat_rate_gj_per_mwh=10, fuel_cost_aud_per_gj=8)
        with pytest.raises(ValueError, match="n_intervals"):
            add_genset_constraints(pyomo_model, cfg, n_intervals=0)

    def test_pyomo_var_bounds(self, pyomo_model: Any) -> None:
        import pyomo.environ as pyo  # noqa: PLC0415

        cfg = GensetConfig(
            capacity_kw=200.0,
            heat_rate_gj_per_mwh=10,
            fuel_cost_aud_per_gj=8,
            availability_factor=0.9,
        )
        add_genset_constraints(pyomo_model, cfg, n_intervals=5)
        dispatch_var = pyomo_model.genset_dispatch
        for t in range(5):
            lb, ub = pyo.value(dispatch_var[t].lb), pyo.value(dispatch_var[t].ub)
            assert lb == 0.0
            assert math.isclose(ub, 180.0)  # 200 * 0.9


# Type stub for Any used in fixture return type hint
from typing import Any  # noqa: E402
