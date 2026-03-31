"""Tests for wholesale energy dispatch model (issue #19)."""

from __future__ import annotations

import pyomo.environ as pyo
import pytest

from app.optimisation.bess import BessConfig, add_bess_constraints
from app.optimisation.dispatch import WholesaleDispatchConfig, add_wholesale_dispatch

# ---------------------------------------------------------------------------
# Unit tests: WholesaleDispatchConfig validation
# ---------------------------------------------------------------------------


class TestWholesaleDispatchConfig:
    def test_valid_config(self) -> None:
        cfg = WholesaleDispatchConfig(max_export_kw=500.0, max_import_kw=500.0)
        assert cfg.max_export_kw == 500.0
        assert cfg.max_import_kw == 500.0

    def test_asymmetric_limits(self) -> None:
        cfg = WholesaleDispatchConfig(max_export_kw=250.0, max_import_kw=100.0)
        assert cfg.max_export_kw == 250.0
        assert cfg.max_import_kw == 100.0

    def test_zero_export_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be > 0"):
            WholesaleDispatchConfig(max_export_kw=0.0, max_import_kw=500.0)

    def test_negative_import_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be > 0"):
            WholesaleDispatchConfig(max_export_kw=500.0, max_import_kw=-10.0)


# ---------------------------------------------------------------------------
# Helper: build a minimal Pyomo model with BESS + wholesale dispatch
# ---------------------------------------------------------------------------


def _build_model(
    prices: dict[int, float],
    *,
    capacity_kwh: float = 1000.0,
    power_kw: float = 500.0,
    soc_max_pct: float = 0.9,
) -> pyo.ConcreteModel:
    """Build a ConcreteModel with BESS + wholesale dispatch for testing."""
    n = len(prices)
    interval_h = 5.0 / 60.0  # 5-minute intervals

    model = pyo.ConcreteModel()
    model.T = pyo.Set(initialize=range(n), ordered=True)
    model.interval_duration_h = pyo.Param(initialize=interval_h)

    bess_cfg = BessConfig(
        capacity_kwh=capacity_kwh,
        power_kw=power_kw,
        soc_min_pct=0.0,
        soc_max_pct=soc_max_pct,
        max_daily_cycles=100.0,  # unrestricted for tests
    )
    add_bess_constraints(model, bess_cfg, interval_h=interval_h)

    dispatch_cfg = WholesaleDispatchConfig(max_export_kw=power_kw, max_import_kw=power_kw)
    add_wholesale_dispatch(model, dispatch_cfg, prices)

    return model


# ---------------------------------------------------------------------------
# Integration tests: model structure
# ---------------------------------------------------------------------------


class TestWholesaleDispatchStructure:
    """Verify variables and constraints are attached correctly."""

    def test_export_import_vars_exist(self) -> None:
        prices = {0: 50.0, 1: 100.0, 2: 30.0}
        model = _build_model(prices)
        assert hasattr(model, "export_kw")
        assert hasattr(model, "import_kw")

    def test_net_position_constraint_exists(self) -> None:
        prices = {0: 50.0, 1: 100.0, 2: 30.0}
        model = _build_model(prices)
        assert hasattr(model, "dispatch_net_position")

    def test_objective_exists(self) -> None:
        prices = {0: 50.0, 1: 100.0, 2: 30.0}
        model = _build_model(prices)
        assert hasattr(model, "objective")

    def test_variable_count_matches_intervals(self) -> None:
        prices = {t: float(t * 10 + 10) for t in range(5)}
        model = _build_model(prices)
        assert len(list(model.export_kw)) == 5
        assert len(list(model.import_kw)) == 5

    def test_net_position_constraint_count(self) -> None:
        prices = {0: 50.0, 1: 100.0, 2: 30.0}
        model = _build_model(prices)
        assert len(list(model.dispatch_net_position)) == 3

    def test_export_bounds_respected(self) -> None:
        """export_kw upper bound should equal max_export_kw from config."""
        prices = {0: 100.0}
        power_kw = 300.0
        model = _build_model(prices, power_kw=power_kw)
        lb, ub = model.export_kw[0].bounds
        assert ub == power_kw

    def test_import_bounds_respected(self) -> None:
        """import_kw upper bound should equal max_import_kw from config."""
        prices = {0: 100.0}
        power_kw = 300.0
        model = _build_model(prices, power_kw=power_kw)
        lb, ub = model.import_kw[0].bounds
        assert ub == power_kw


# ---------------------------------------------------------------------------
# Integration tests: solver-based (skipped if no solver available)
# ---------------------------------------------------------------------------


class TestWholesaleDispatchSolve:
    """Solve small LP problems and verify economic behaviour."""

    @pytest.fixture
    def solver(self) -> pyo.SolverFactory:
        """Return HiGHS solver; skip test if unavailable."""
        slv = pyo.SolverFactory("highs")
        if not slv.available(exception_flag=False):
            pytest.skip("HiGHS solver not available")
        return slv

    def test_higher_price_drives_more_export(self, solver: pyo.SolverFactory) -> None:
        """At a high-price interval the BESS should export more than at a low-price interval."""
        prices = {0: 50.0, 1: 150.0, 2: 30.0}
        model = _build_model(prices, capacity_kwh=2000.0, power_kw=500.0, soc_max_pct=1.0)

        result = solver.solve(model)
        assert str(result.solver.termination_condition) == "optimal"

        export_0 = pyo.value(model.export_kw[0])
        export_1 = pyo.value(model.export_kw[1])
        assert export_1 >= export_0, (
            f"Expected more export at higher price: export[0]={export_0:.2f}, "
            f"export[1]={export_1:.2f}"
        )

    def test_net_position_constraint_satisfied(self, solver: pyo.SolverFactory) -> None:
        """Verify discharge - charge == export - import at each interval."""
        prices = {0: 80.0, 1: 120.0, 2: 60.0}
        model = _build_model(prices)
        solver.solve(model)

        for t in model.T:
            net_bess = pyo.value(model.discharge_kw[t]) - pyo.value(model.charge_kw[t])
            net_market = pyo.value(model.export_kw[t]) - pyo.value(model.import_kw[t])
            assert abs(net_bess - net_market) < 1e-6, (
                f"Net position constraint violated at t={t}: "
                f"bess_net={net_bess:.6f}, market_net={net_market:.6f}"
            )

    def test_objective_value_positive_when_exporting(
        self, solver: pyo.SolverFactory
    ) -> None:
        """With positive prices and available SoC, revenue should be positive."""
        prices = {0: 100.0, 1: 100.0}
        model = _build_model(prices, capacity_kwh=1000.0, power_kw=500.0, soc_max_pct=1.0)
        solver.solve(model)
        obj = pyo.value(model.objective)
        assert obj > 0, f"Expected positive revenue, got {obj}"
