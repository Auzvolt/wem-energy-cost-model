"""Tests for the Pyomo optimisation scaffold."""
from __future__ import annotations

import pytest

import pyomo.environ as pyo

from optimisation.model import OptimisationConfig, build_model, solve_model


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def small_config() -> OptimisationConfig:
    """A small 12-interval (1h) horizon for fast tests."""
    return OptimisationConfig(horizon_intervals=12, interval_minutes=5)


@pytest.fixture()
def small_model(small_config: OptimisationConfig) -> pyo.ConcreteModel:
    return build_model(small_config)


# ---------------------------------------------------------------------------
# build_model tests
# ---------------------------------------------------------------------------

class TestBuildModel:
    def test_returns_concrete_model(self, small_model: pyo.ConcreteModel) -> None:
        assert isinstance(small_model, pyo.ConcreteModel)

    def test_set_T_correct_length(
        self, small_model: pyo.ConcreteModel, small_config: OptimisationConfig
    ) -> None:
        assert len(list(small_model.T)) == small_config.horizon_intervals

    def test_set_T_correct_range(self, small_model: pyo.ConcreteModel) -> None:
        t_list = list(small_model.T)
        assert t_list[0] == 0
        assert t_list[-1] == 11  # 12 intervals: 0..11

    def test_charge_kw_var_exists(self, small_model: pyo.ConcreteModel) -> None:
        assert hasattr(small_model, "charge_kw")
        assert isinstance(small_model.charge_kw, pyo.Var)

    def test_discharge_kw_var_exists(self, small_model: pyo.ConcreteModel) -> None:
        assert hasattr(small_model, "discharge_kw")
        assert isinstance(small_model.discharge_kw, pyo.Var)

    def test_soc_kwh_var_exists(self, small_model: pyo.ConcreteModel) -> None:
        assert hasattr(small_model, "soc_kwh")
        assert isinstance(small_model.soc_kwh, pyo.Var)

    def test_vars_indexed_over_T(self, small_model: pyo.ConcreteModel) -> None:
        """Each decision variable must be indexed over T."""
        for t in small_model.T:
            assert small_model.charge_kw[t] is not None
            assert small_model.discharge_kw[t] is not None
            assert small_model.soc_kwh[t] is not None

    def test_all_vars_non_negative(self, small_model: pyo.ConcreteModel) -> None:
        """Variables must be declared within NonNegativeReals."""
        for t in small_model.T:
            assert small_model.charge_kw[t].lb == 0 or small_model.charge_kw[t].lb is None
            assert small_model.discharge_kw[t].lb == 0 or small_model.discharge_kw[t].lb is None
            assert small_model.soc_kwh[t].lb == 0 or small_model.soc_kwh[t].lb is None

    def test_objective_exists(self, small_model: pyo.ConcreteModel) -> None:
        assert hasattr(small_model, "obj")
        assert isinstance(small_model.obj, pyo.Objective)

    def test_soc_balance_constraint_exists(self, small_model: pyo.ConcreteModel) -> None:
        assert hasattr(small_model, "soc_balance")

    def test_horizon_intervals_288_default(self) -> None:
        config = OptimisationConfig()
        assert config.horizon_intervals == 288

    def test_horizon_hours_calculation(self, small_config: OptimisationConfig) -> None:
        # 12 intervals × 5 min = 60 min = 1.0 hour
        assert small_config.horizon_hours == 1.0


# ---------------------------------------------------------------------------
# OptimisationConfig tests
# ---------------------------------------------------------------------------

class TestOptimisationConfig:
    def test_default_solver_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SOLVER", "highs")
        config = OptimisationConfig()
        assert config.solver == "highs"

    def test_default_solver_glpk_when_no_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SOLVER", raising=False)
        config = OptimisationConfig()
        assert config.solver == "glpk"

    def test_explicit_solver_override(self) -> None:
        config = OptimisationConfig(solver="cplex")
        assert config.solver == "cplex"

    def test_invalid_horizon_raises(self) -> None:
        with pytest.raises(Exception):
            OptimisationConfig(horizon_intervals=0)


# ---------------------------------------------------------------------------
# solve_model tests
# ---------------------------------------------------------------------------

class TestSolveModel:
    def test_solve_placeholder_model_returns_dict(
        self, small_model: pyo.ConcreteModel, small_config: OptimisationConfig
    ) -> None:
        """solve_model must always return a dict with required keys."""
        result = solve_model(small_model, small_config)
        assert "status" in result
        assert "termination_condition" in result
        assert "objective" in result

    def test_unavailable_solver_returns_not_found(
        self, small_model: pyo.ConcreteModel
    ) -> None:
        """A solver that doesn't exist should return solver_not_found status."""
        config = OptimisationConfig(solver="nonexistent_solver_xyz_123", horizon_intervals=12)
        result = solve_model(small_model, config)
        assert result["status"] == "solver_not_found"

    def test_solve_with_available_solver(
        self, small_model: pyo.ConcreteModel, small_config: OptimisationConfig
    ) -> None:
        """If glpk or highs is available, the trivial model (obj=0) should solve."""
        # Try glpk first, then highs — skip if neither available
        for solver_name in ("glpk", "highs"):
            config = OptimisationConfig(
                horizon_intervals=small_config.horizon_intervals,
                solver=solver_name,
            )
            solver = pyo.SolverFactory(solver_name)
            if solver.available():
                result = solve_model(small_model, config)
                assert result["status"] in ("ok", "warning")
                assert result["objective"] is not None
                assert float(result["objective"]) == pytest.approx(0.0, abs=1e-6)  # type: ignore[arg-type]
                return
        pytest.skip("No supported solver (glpk, highs) available in this environment")
