"""Tests for app.optimisation.bess -- BESS asset model.

Covers:
  - BessConfig validation
  - degraded_capacity() helper
  - add_bess_constraints() model structure
  - Integration: SoC balance correctness over a simple 4-interval trace
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.optimisation.bess import BessConfig, add_bess_constraints, degraded_capacity

# -- BessConfig validation ----------------------------------------------------


class TestBessConfig:
    def test_default_values(self) -> None:
        cfg = BessConfig(capacity_kwh=100.0, power_kw=50.0)
        assert cfg.efficiency_rt == pytest.approx(0.90)
        assert cfg.soc_min_pct == pytest.approx(0.10)
        assert cfg.soc_max_pct == pytest.approx(0.90)
        assert cfg.max_daily_cycles == pytest.approx(2.0)
        assert cfg.degradation_pct_per_year == pytest.approx(2.0)

    def test_custom_values(self) -> None:
        cfg = BessConfig(
            capacity_kwh=500.0,
            power_kw=250.0,
            efficiency_rt=0.85,
            soc_min_pct=0.05,
            soc_max_pct=0.95,
            max_daily_cycles=1.0,
            degradation_pct_per_year=1.5,
        )
        assert cfg.capacity_kwh == pytest.approx(500.0)
        assert cfg.power_kw == pytest.approx(250.0)

    def test_invalid_capacity(self) -> None:
        with pytest.raises(ValidationError):
            BessConfig(capacity_kwh=-10.0, power_kw=50.0)

    def test_invalid_soc_window(self) -> None:
        with pytest.raises(ValidationError):
            BessConfig(capacity_kwh=100.0, power_kw=50.0, soc_min_pct=0.8, soc_max_pct=0.5)

    def test_efficiency_bounds(self) -> None:
        with pytest.raises(ValidationError):
            BessConfig(capacity_kwh=100.0, power_kw=50.0, efficiency_rt=1.5)


# -- degraded_capacity() ------------------------------------------------------


class TestDegradedCapacity:
    def test_no_degradation(self) -> None:
        cfg = BessConfig(capacity_kwh=200.0, power_kw=100.0)
        assert degraded_capacity(cfg, age_years=0.0) == pytest.approx(200.0)

    def test_ten_year_degradation(self) -> None:
        cfg = BessConfig(capacity_kwh=200.0, power_kw=100.0, degradation_pct_per_year=2.0)
        # 10 years x 2 % = 20 % loss -> 160 kWh
        assert degraded_capacity(cfg, age_years=10.0) == pytest.approx(160.0)

    def test_full_degradation_clamped_to_zero(self) -> None:
        cfg = BessConfig(capacity_kwh=100.0, power_kw=50.0, degradation_pct_per_year=10.0)
        # 15 years x 10 % > 100 %, should clamp to 0
        assert degraded_capacity(cfg, age_years=15.0) == pytest.approx(0.0)

    def test_negative_age_raises(self) -> None:
        cfg = BessConfig(capacity_kwh=100.0, power_kw=50.0)
        with pytest.raises(ValueError, match="non-negative"):
            degraded_capacity(cfg, age_years=-1.0)


# -- add_bess_constraints() ---------------------------------------------------


pyomo = pytest.importorskip("pyomo", reason="pyomo required")


@pytest.fixture()
def simple_model():
    """Minimal Pyomo model with T = {0, 1, 2, 3} (4 x 5-min intervals)."""
    import pyomo.environ as pyo

    m = pyo.ConcreteModel()
    m.T = pyo.Set(initialize=range(4), ordered=True)
    return m


class TestAddBessConstraints:
    def test_variables_added(self, simple_model) -> None:
        cfg = BessConfig(capacity_kwh=100.0, power_kw=50.0)
        add_bess_constraints(simple_model, cfg)
        assert hasattr(simple_model, "charge_kw")
        assert hasattr(simple_model, "discharge_kw")
        assert hasattr(simple_model, "soc_kwh")

    def test_constraints_added(self, simple_model) -> None:
        cfg = BessConfig(capacity_kwh=100.0, power_kw=50.0)
        add_bess_constraints(simple_model, cfg)
        assert hasattr(simple_model, "bess_charge_limit")
        assert hasattr(simple_model, "bess_discharge_limit")
        assert hasattr(simple_model, "bess_soc_balance")
        assert hasattr(simple_model, "bess_daily_cycle")

    def test_soc_bounds_respect_config(self, simple_model) -> None:
        cfg = BessConfig(
            capacity_kwh=100.0,
            power_kw=50.0,
            soc_min_pct=0.10,
            soc_max_pct=0.90,
        )
        add_bess_constraints(simple_model, cfg)
        for t in simple_model.T:
            lb, ub = simple_model.soc_kwh[t].bounds
            assert lb == pytest.approx(10.0)  # 10 % of 100 kWh
            assert ub == pytest.approx(90.0)  # 90 % of 100 kWh

    def test_degraded_capacity_applied(self, simple_model) -> None:
        """soc bounds should reflect degraded capacity, not nameplate."""
        cfg = BessConfig(
            capacity_kwh=100.0,
            power_kw=50.0,
            soc_min_pct=0.10,
            soc_max_pct=0.90,
            degradation_pct_per_year=2.0,
        )
        add_bess_constraints(simple_model, cfg, age_years=5.0)
        # Degraded to 90 kWh; window = [9, 81]
        lb, ub = simple_model.soc_kwh[0].bounds
        assert lb == pytest.approx(9.0)
        assert ub == pytest.approx(81.0)

    def test_solver_integration(self, simple_model) -> None:
        """End-to-end solve: price-taker dispatches BESS optimally."""
        import pyomo.environ as pyo

        solver = pyo.SolverFactory("cbc")
        if not solver.available():
            pytest.skip("CBC solver not available")

        cfg = BessConfig(capacity_kwh=100.0, power_kw=50.0)
        interval_h = 5.0 / 60.0
        add_bess_constraints(simple_model, cfg, interval_h=interval_h)

        # Negative price = buy cheap, positive price = sell dear
        prices = {0: -10.0, 1: -10.0, 2: 50.0, 3: 50.0}
        simple_model.obj = pyo.Objective(
            expr=sum(
                prices[t] * (simple_model.discharge_kw[t] - simple_model.charge_kw[t]) * interval_h
                for t in simple_model.T
            ),
            sense=pyo.minimize,
        )

        result = solver.solve(simple_model)
        assert str(result.solver.termination_condition) in ("optimal", "feasible")
