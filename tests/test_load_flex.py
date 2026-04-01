"""Tests for app.optimisation.load_flex — load flexibility asset model."""

from __future__ import annotations

import pytest

from app.optimisation.load_flex import (
    LoadFlexConfig,
    LoadFlexResult,
    add_load_flex_constraints,
    extract_load_flex_results,
)

# ---------------------------------------------------------------------------
# LoadFlexConfig validation
# ---------------------------------------------------------------------------


class TestLoadFlexConfigValidation:
    def test_minimal_valid_config(self) -> None:
        cfg = LoadFlexConfig(baseline_kw=[100.0, 100.0])
        assert len(cfg.baseline_kw) == 2
        assert cfg.max_shift_pct == 0.25
        assert cfg.max_curtail_pct == 0.0
        assert cfg.curtail_value_per_kwh == 0.0
        assert cfg.shift_window == 0

    def test_custom_config(self) -> None:
        cfg = LoadFlexConfig(
            baseline_kw=[50.0, 60.0, 70.0],
            max_shift_pct=0.30,
            max_curtail_pct=0.20,
            curtail_value_per_kwh=0.05,
            shift_window=2,
        )
        assert cfg.max_shift_pct == 0.30
        assert cfg.max_curtail_pct == 0.20
        assert cfg.curtail_value_per_kwh == 0.05
        assert cfg.shift_window == 2

    def test_negative_baseline_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            LoadFlexConfig(baseline_kw=[100.0, -10.0])

    def test_shift_pct_above_one_rejected(self) -> None:
        with pytest.raises(ValueError):
            LoadFlexConfig(baseline_kw=[100.0], max_shift_pct=1.5)

    def test_curtail_pct_above_one_rejected(self) -> None:
        with pytest.raises(ValueError):
            LoadFlexConfig(baseline_kw=[100.0], max_curtail_pct=-0.1)

    def test_curtail_value_negative_rejected(self) -> None:
        with pytest.raises(ValueError):
            LoadFlexConfig(baseline_kw=[100.0], curtail_value_per_kwh=-1.0)

    def test_shift_window_negative_rejected(self) -> None:
        with pytest.raises(ValueError):
            LoadFlexConfig(baseline_kw=[100.0], shift_window=-1)

    def test_zero_baseline_allowed(self) -> None:
        cfg = LoadFlexConfig(baseline_kw=[0.0, 0.0, 50.0])
        assert cfg.baseline_kw[0] == 0.0

    def test_single_interval(self) -> None:
        cfg = LoadFlexConfig(baseline_kw=[200.0])
        assert len(cfg.baseline_kw) == 1


# ---------------------------------------------------------------------------
# LoadFlexResult
# ---------------------------------------------------------------------------


class TestLoadFlexResult:
    def test_basic_construction(self) -> None:
        result = LoadFlexResult(
            scheduled_kw=[100.0, 90.0, 110.0],
            curtailed_kw=[0.0, 10.0, 0.0],
            interval_h=0.5,
        )
        assert result.total_curtailed_kwh == pytest.approx(5.0)  # 10 * 0.5
        assert result.curtail_revenue == 0.0

    def test_curtail_revenue_set_by_caller(self) -> None:
        result = LoadFlexResult(
            scheduled_kw=[80.0],
            curtailed_kw=[20.0],
            interval_h=1.0,
        )
        result.curtail_revenue = 20.0 * 0.05  # curtail_value_per_kwh=0.05
        assert result.curtail_revenue == pytest.approx(1.0)

    def test_repr(self) -> None:
        result = LoadFlexResult(
            scheduled_kw=[100.0],
            curtailed_kw=[5.0],
            interval_h=0.5,
        )
        r = repr(result)
        assert "LoadFlexResult" in r
        assert "total_curtailed_kwh" in r


# ---------------------------------------------------------------------------
# Pyomo integration — add_load_flex_constraints
# ---------------------------------------------------------------------------


def _make_model(n: int) -> pyo.ConcreteModel:  # noqa: F821
    """Helper: create a bare Pyomo model with T = 0..n-1."""
    import pyomo.environ as pyo

    m = pyo.ConcreteModel()
    m.T = pyo.Set(initialize=list(range(n)), ordered=True)
    return m


class TestAddLoadFlexConstraints:
    def test_variables_added(self) -> None:
        import pyomo.environ as pyo

        m = _make_model(4)
        cfg = LoadFlexConfig(baseline_kw=[100.0] * 4)
        add_load_flex_constraints(m, cfg, interval_h=0.5)

        assert hasattr(m, "lf_scheduled_kw")
        assert hasattr(m, "lf_curtailed_kw")
        assert hasattr(m, "lf_shift_pos")
        assert hasattr(m, "lf_shift_neg")
        assert isinstance(m.lf_scheduled_kw, pyo.Var)

    def test_constraints_added(self) -> None:

        m = _make_model(4)
        cfg = LoadFlexConfig(baseline_kw=[100.0] * 4)
        add_load_flex_constraints(m, cfg, interval_h=0.5)

        assert hasattr(m, "lf_schedule_balance")
        assert hasattr(m, "lf_shift_pos_limit")
        assert hasattr(m, "lf_shift_neg_limit")
        assert hasattr(m, "lf_curtail_limit")
        assert hasattr(m, "lf_energy_balance")

    def test_mismatched_baseline_raises(self) -> None:
        m = _make_model(4)
        cfg = LoadFlexConfig(baseline_kw=[100.0] * 6)  # wrong length
        with pytest.raises(ValueError, match="model.T has 4"):
            add_load_flex_constraints(m, cfg, interval_h=0.5)

    def test_windowed_balance_constraint(self) -> None:
        m = _make_model(4)
        cfg = LoadFlexConfig(baseline_kw=[100.0] * 4, shift_window=2)
        add_load_flex_constraints(m, cfg, interval_h=0.5)
        assert hasattr(m, "lf_energy_balance")
        assert hasattr(m, "lf_window_starts")

    def test_objective_term_appended(self) -> None:

        m = _make_model(2)
        m.obj_terms = []
        cfg = LoadFlexConfig(
            baseline_kw=[100.0, 100.0],
            max_curtail_pct=0.20,
            curtail_value_per_kwh=0.10,
        )
        add_load_flex_constraints(m, cfg, interval_h=0.5)
        assert len(m.obj_terms) == 1

    def test_no_objective_term_when_zero_curtail_value(self) -> None:

        m = _make_model(2)
        m.obj_terms = []
        cfg = LoadFlexConfig(baseline_kw=[100.0, 100.0], curtail_value_per_kwh=0.0)
        add_load_flex_constraints(m, cfg, interval_h=0.5)
        assert len(m.obj_terms) == 0


# ---------------------------------------------------------------------------
# End-to-end solve test
# ---------------------------------------------------------------------------


class TestLoadFlexEndToEnd:
    """Solve a minimal LP and verify the output is physically consistent."""

    def _solve(
        self,
        baseline_kw: list[float],
        max_shift_pct: float = 0.30,
        max_curtail_pct: float = 0.20,
        curtail_value: float = 0.05,
        prices: list[float] | None = None,
    ) -> LoadFlexResult:
        import pyomo.environ as pyo

        n = len(baseline_kw)
        if prices is None:
            prices = [0.10] * n  # uniform price — no incentive to shift

        m = pyo.ConcreteModel()
        m.T = pyo.Set(initialize=list(range(n)), ordered=True)

        cfg = LoadFlexConfig(
            baseline_kw=baseline_kw,
            max_shift_pct=max_shift_pct,
            max_curtail_pct=max_curtail_pct,
            curtail_value_per_kwh=curtail_value,
        )

        interval_h = 0.5
        add_load_flex_constraints(m, cfg, interval_h=interval_h)

        # Minimise energy cost − curtailment revenue
        price_map = {t: prices[t] for t in range(n)}
        m.obj = pyo.Objective(
            expr=sum(
                m.lf_scheduled_kw[t] * price_map[t] * interval_h
                - m.lf_curtailed_kw[t] * curtail_value * interval_h
                for t in m.T
            ),
            sense=pyo.minimize,
        )

        solver = pyo.SolverFactory("glpk")
        if not solver.available():
            pytest.skip("glpk solver not available")
        result = solver.solve(m)
        assert str(result.solver.termination_condition) == "optimal"

        return extract_load_flex_results(m, cfg, interval_h=interval_h)

    def test_no_shift_uniform_price(self) -> None:
        """With uniform prices and zero curtail value no shifting should occur."""
        baseline = [100.0] * 6
        res = self._solve(baseline, curtail_value=0.0)
        for kw, base in zip(res.scheduled_kw, baseline, strict=True):
            assert kw == pytest.approx(base, abs=1e-4)

    def test_curtailment_reduces_cost(self) -> None:
        """Curtailment should be maximised when curtail_value > price."""
        baseline = [100.0] * 4
        # curtail_value 0.30 > price 0.10 → solver should curtail as much as allowed
        res = self._solve(
            baseline,
            max_curtail_pct=0.20,
            curtail_value=0.30,
            prices=[0.10] * 4,
        )
        # Should have curtailed the maximum (20% * 100 = 20 kW per interval)
        for c_kw in res.curtailed_kw:
            assert c_kw == pytest.approx(20.0, abs=1e-3)

    def test_scheduled_kw_nonnegative(self) -> None:
        """Scheduled load should never be negative."""
        baseline = [50.0, 50.0, 50.0, 50.0]
        res = self._solve(baseline, max_shift_pct=0.20)
        for kw in res.scheduled_kw:
            assert kw >= -1e-6

    def test_energy_balance_preserved(self) -> None:
        """Total delivered energy should match baseline minus curtailment."""
        import pyomo.environ as pyo

        baseline = [80.0, 80.0, 80.0, 80.0]
        n = len(baseline)
        interval_h = 0.5

        m = pyo.ConcreteModel()
        m.T = pyo.Set(initialize=list(range(n)), ordered=True)
        cfg = LoadFlexConfig(
            baseline_kw=baseline,
            max_shift_pct=0.25,
            max_curtail_pct=0.0,  # no curtailment — balance must be exact
        )
        add_load_flex_constraints(m, cfg, interval_h=interval_h)

        m.obj = pyo.Objective(
            expr=sum(m.lf_scheduled_kw[t] for t in m.T),
            sense=pyo.minimize,
        )

        solver = pyo.SolverFactory("glpk")
        if not solver.available():
            pytest.skip("glpk solver not available")
        solver.solve(m)

        res = extract_load_flex_results(m, cfg, interval_h=interval_h)
        total_scheduled = sum(res.scheduled_kw) * interval_h
        total_baseline = sum(baseline) * interval_h
        assert total_scheduled == pytest.approx(total_baseline, abs=1e-4)

    def test_result_curtail_revenue_correct(self) -> None:
        """Curtail revenue should equal total_curtailed_kwh * curtail_value_per_kwh."""
        baseline = [100.0] * 2
        curtail_value = 0.05
        res = self._solve(baseline, max_curtail_pct=0.10, curtail_value=curtail_value)
        expected_revenue = res.total_curtailed_kwh * curtail_value
        assert res.curtail_revenue == pytest.approx(expected_revenue, abs=1e-6)
