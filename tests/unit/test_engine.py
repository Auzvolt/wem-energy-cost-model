"""Unit tests for the Pyomo co-optimisation engine scaffold (issue #18).

Tests verify:
- ModelConfig defaults are sane
- WEMModel builds without error
- SolveResult properties behave correctly
- extract_variable raises before build/solve
- build_trivial_model helper works end-to-end

Note: solver availability is skipped in CI — tests check model structure only.
"""

from __future__ import annotations

import pytest

from app.optimisation.engine import (
    ModelConfig,
    ObjectiveSense,
    SolverConfig,
    SolveResult,
    WEMModel,
    build_trivial_model,
)

try:
    import pyomo.environ as pyo  # noqa: F401
    PYOMO_AVAILABLE = True
except ImportError:
    PYOMO_AVAILABLE = False

pytestmark = pytest.mark.skipif(not PYOMO_AVAILABLE, reason="pyomo not installed")


class TestModelConfig:
    def test_defaults(self) -> None:
        cfg = ModelConfig()
        assert cfg.interval_minutes == 5
        assert cfg.objective_sense == ObjectiveSense.maximise_revenue
        assert cfg.solver.solver_name == "cbc"

    def test_custom_solver(self) -> None:
        cfg = ModelConfig(solver=SolverConfig(solver_name="glpk", timelimit_seconds=60))
        assert cfg.solver.solver_name == "glpk"
        assert cfg.solver.timelimit_seconds == 60


class TestWEMModelBuild:
    def _make_model(self, n: int = 6) -> WEMModel:
        from datetime import datetime
        intervals = [datetime(2024, 1, 1, 0, i * 5) for i in range(n)]
        cfg = ModelConfig(solver=SolverConfig(solver_name="glpk"))
        return WEMModel(intervals=intervals, config=cfg)

    def test_build_returns_concrete_model(self) -> None:
        import pyomo.environ as pyo
        m = self._make_model()
        concrete = m.build()
        assert isinstance(concrete, pyo.ConcreteModel)

    def test_set_T_has_correct_size(self) -> None:
        m = self._make_model(n=12)
        m.build()
        assert len(list(m.model.T)) == 12

    def test_interval_duration_param(self) -> None:
        import pyomo.environ as pyo
        m = self._make_model(n=6)
        m.build()
        assert abs(float(pyo.value(m.model.interval_duration_h)) - 5 / 60) < 1e-9

    def test_build_twice_raises(self) -> None:
        m = self._make_model()
        m.build()
        with pytest.raises(RuntimeError, match="already been built"):
            m.build()

    def test_solve_before_build_raises(self) -> None:
        m = self._make_model()
        with pytest.raises(RuntimeError, match="build()"):
            m.solve()

    def test_extract_before_build_raises(self) -> None:
        import pyomo.environ as pyo
        m = self._make_model()
        dummy_var = pyo.Var()
        with pytest.raises(RuntimeError, match="build()"):
            m.extract_variable(dummy_var)

    def test_objective_attached(self) -> None:
        import pyomo.environ as pyo
        m = self._make_model()
        m.build()
        assert hasattr(m.model, "objective")
        assert isinstance(m.model.objective, pyo.Objective)

    def test_add_objective_term_accumulates(self) -> None:
        import pyomo.environ as pyo
        m = self._make_model(n=4)
        # Add a constant term before build
        m.add_objective_term(100.0)
        m.build()
        # Objective expression should include the constant
        val = float(pyo.value(m.model.objective))
        assert abs(val - 100.0) < 1e-6


class TestSolveResult:
    def test_is_optimal_true(self) -> None:
        r = SolveResult(
            status="optimal",
            termination_condition="optimal",
            objective_value=42.0,
            solve_time_seconds=0.1,
        )
        assert r.is_optimal is True

    def test_is_optimal_false(self) -> None:
        r = SolveResult(
            status="infeasible",
            termination_condition="infeasibleOrUnbounded",
            objective_value=None,
            solve_time_seconds=0.0,
        )
        assert r.is_optimal is False


class TestBuildTrivialModel:
    def test_trivial_model_builds(self) -> None:
        m = build_trivial_model(n_intervals=6)
        assert m._built is True

    def test_trivial_model_interval_count(self) -> None:
        m = build_trivial_model(n_intervals=3)
        assert len(list(m.model.T)) == 3
