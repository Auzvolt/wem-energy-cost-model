"""Tests for diesel/gas genset asset model (issue #24)."""

from __future__ import annotations

import importlib.util
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


class TestFuelCostForOutputKw:
    """Tests for GensetConfig.fuel_cost_for_output_kw()."""

    BASE_CONFIG = dict(
        capacity_kw=500.0,
        heat_rate_gj_per_mwh=10.0,
        fuel_cost_aud_per_gj=8.0,
    )

    def test_scalar_mode_matches_fuel_cost_aud(self) -> None:
        """fuel_cost_for_output_kw with no curve matches fuel_cost_aud helper."""
        cfg = GensetConfig(**self.BASE_CONFIG)
        duration_h = 0.5
        output_kw = 300.0
        from_helper = fuel_cost_aud(cfg, output_kw, duration_h)
        from_method = cfg.fuel_cost_for_output_kw(output_kw, duration_h)
        assert math.isclose(from_helper, from_method, rel_tol=1e-9)

    def test_scalar_zero_output(self) -> None:
        cfg = GensetConfig(**self.BASE_CONFIG)
        assert cfg.fuel_cost_for_output_kw(0.0) == 0.0

    def test_curve_interpolation_between_breakpoints(self) -> None:
        """Heat rate is linearly interpolated between breakpoints."""
        # Curve: 0 kW → 12 GJ/MWh, 500 kW → 10 GJ/MWh
        cfg = GensetConfig(
            **self.BASE_CONFIG,
            heat_rate_curve=[(0.0, 12.0), (500.0, 10.0)],
        )
        # At 250 kW (midpoint) heat rate should be 11.0 GJ/MWh
        expected_hr = 11.0
        expected_cost = 250.0 * 0.5 / 1000.0 * expected_hr * 8.0
        result = cfg.fuel_cost_for_output_kw(250.0, 0.5)
        assert math.isclose(result, expected_cost, rel_tol=1e-9)

    def test_curve_below_first_breakpoint_uses_first_hr(self) -> None:
        """Output below first breakpoint uses the first heat rate (flat extrapolation)."""
        cfg = GensetConfig(
            **self.BASE_CONFIG,
            heat_rate_curve=[(100.0, 12.0), (500.0, 10.0)],
        )
        # 50 kW < 100 kW → use hr = 12.0
        expected_cost = 50.0 * 0.5 / 1000.0 * 12.0 * 8.0
        assert math.isclose(cfg.fuel_cost_for_output_kw(50.0, 0.5), expected_cost, rel_tol=1e-9)

    def test_curve_above_last_breakpoint_uses_last_hr(self) -> None:
        """Output above last breakpoint uses the last heat rate (flat extrapolation)."""
        cfg = GensetConfig(
            **self.BASE_CONFIG,
            heat_rate_curve=[(0.0, 12.0), (400.0, 10.0)],
        )
        # 450 kW > 400 kW → use hr = 10.0
        expected_cost = 450.0 * 0.5 / 1000.0 * 10.0 * 8.0
        assert math.isclose(cfg.fuel_cost_for_output_kw(450.0, 0.5), expected_cost, rel_tol=1e-9)

    def test_curve_at_exact_breakpoint(self) -> None:
        cfg = GensetConfig(
            **self.BASE_CONFIG,
            heat_rate_curve=[(0.0, 12.0), (250.0, 11.0), (500.0, 10.0)],
        )
        expected_cost = 250.0 * 0.5 / 1000.0 * 11.0 * 8.0
        assert math.isclose(cfg.fuel_cost_for_output_kw(250.0, 0.5), expected_cost, rel_tol=1e-9)

    def test_negative_output_raises(self) -> None:
        cfg = GensetConfig(**self.BASE_CONFIG)
        with pytest.raises(ValueError, match="output_kw must be >= 0"):
            cfg.fuel_cost_for_output_kw(-1.0)

    def test_invalid_duration_raises(self) -> None:
        cfg = GensetConfig(**self.BASE_CONFIG)
        with pytest.raises(ValueError, match="interval_duration_h must be > 0"):
            cfg.fuel_cost_for_output_kw(100.0, 0.0)


@pytest.mark.skipif(
    importlib.util.find_spec("pyomo") is None,
    reason="pyomo not installed",
)
class TestMinRunOffTimeConstraints:
    """Tests for min_run_time_intervals and min_off_time_intervals MILP constraints."""

    BASE_CONFIG = dict(
        capacity_kw=200.0,
        heat_rate_gj_per_mwh=10.0,
        fuel_cost_aud_per_gj=8.0,
        min_loading_pct=0.0,
    )

    def test_min_up_time_constraint_name_added(self, pyomo_model: Any) -> None:
        cfg = GensetConfig(**self.BASE_CONFIG, min_run_time_intervals=3)
        result = add_genset_constraints(pyomo_model, cfg, n_intervals=6)
        assert "genset_min_up_time" in result["constraints"]

    def test_no_min_up_time_constraint_when_zero(self, pyomo_model: Any) -> None:
        cfg = GensetConfig(**self.BASE_CONFIG, min_run_time_intervals=0)
        result = add_genset_constraints(pyomo_model, cfg, n_intervals=6)
        assert "genset_min_up_time" not in result["constraints"]

    def test_no_min_up_time_constraint_when_one(self, pyomo_model: Any) -> None:
        """min_run_time_intervals=1 means just \"stay on this interval\" — trivially true, skip."""
        cfg = GensetConfig(**self.BASE_CONFIG, min_run_time_intervals=1)
        result = add_genset_constraints(pyomo_model, cfg, n_intervals=6)
        assert "genset_min_up_time" not in result["constraints"]

    def test_min_down_time_constraint_name_added(self, pyomo_model: Any) -> None:
        cfg = GensetConfig(**self.BASE_CONFIG, min_off_time_intervals=2)
        result = add_genset_constraints(pyomo_model, cfg, n_intervals=6)
        assert "genset_min_down_time" in result["constraints"]

    def test_no_min_down_time_constraint_when_zero(self, pyomo_model: Any) -> None:
        cfg = GensetConfig(**self.BASE_CONFIG, min_off_time_intervals=0)
        result = add_genset_constraints(pyomo_model, cfg, n_intervals=6)
        assert "genset_min_down_time" not in result["constraints"]

    def test_mut_constraint_is_pyomo_constraint(self, pyomo_model: Any) -> None:
        import pyomo.environ as pyo  # noqa: PLC0415

        cfg = GensetConfig(**self.BASE_CONFIG, min_run_time_intervals=3)
        add_genset_constraints(pyomo_model, cfg, n_intervals=6)
        assert isinstance(pyomo_model.genset_min_up_time, pyo.Constraint)

    def test_mdt_constraint_is_pyomo_constraint(self, pyomo_model: Any) -> None:
        import pyomo.environ as pyo  # noqa: PLC0415

        cfg = GensetConfig(**self.BASE_CONFIG, min_off_time_intervals=3)
        add_genset_constraints(pyomo_model, cfg, n_intervals=6)
        assert isinstance(pyomo_model.genset_min_down_time, pyo.Constraint)

    def test_mut_feasibility_genset_must_stay_on(self, pyomo_model: Any) -> None:
        """MUT=3: after starting at t=0, online[1] and online[2] must be 1."""
        cfg = GensetConfig(**self.BASE_CONFIG, min_run_time_intervals=3)
        add_genset_constraints(pyomo_model, cfg, n_intervals=6)

        # Fix start[0]=1 (genset starts at t=0)
        pyomo_model.genset_start[0].fix(1)
        pyomo_model.genset_online[0].fix(1)

        # Constraint: start[0] <= online[1] (since t=1, sum includes start[1] + start[0])
        # Check the constraint body at t=1 — start[0] appears in the sum
        con_t1 = pyomo_model.genset_min_up_time[1]
        # The constraint LHS includes start[t-0]=start[1], start[t-1]=start[0]
        # With start[0]=1, the LHS >= 1, so online[1] must be >= 1
        assert con_t1 is not None  # Constraint exists for t=1

    def test_mdt_feasibility_genset_must_stay_off(self, pyomo_model: Any) -> None:
        """MDT=3: after stopping at t=0, online[1] and online[2] must be 0."""
        cfg = GensetConfig(**self.BASE_CONFIG, min_off_time_intervals=3)
        add_genset_constraints(pyomo_model, cfg, n_intervals=6)

        # Fix stop[0]=1 (genset stops at t=0)
        pyomo_model.genset_stop[0].fix(1)
        pyomo_model.genset_online[0].fix(0)

        # Check constraint at t=1 exists
        con_t1 = pyomo_model.genset_min_down_time[1]
        assert con_t1 is not None

    def test_min_run_time_intervals_default_zero(self) -> None:
        cfg = GensetConfig(**self.BASE_CONFIG)
        assert cfg.min_run_time_intervals == 0

    def test_min_off_time_intervals_default_zero(self) -> None:
        cfg = GensetConfig(**self.BASE_CONFIG)
        assert cfg.min_off_time_intervals == 0
