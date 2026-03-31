"""Pyomo optimisation scaffold for BESS co-optimisation in the WA wholesale market.

Provides the model skeleton (sets, decision variables, constraints, objective)
for a battery energy storage system (BESS) dispatch optimisation over a
rolling time horizon.

Solvers are resolved via the SOLVER environment variable (default: "glpk").
To use HiGHS: set SOLVER=highs and ensure highspy is installed.
"""
from __future__ import annotations

import logging
import os

import pyomo.environ as pyo
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class OptimisationConfig(BaseModel):
    """Configuration for the optimisation model.

    Attributes:
        horizon_intervals: Number of dispatch intervals in the rolling horizon.
        interval_minutes: Duration of each interval in minutes (e.g. 5 or 30).
        solver: Pyomo solver name. Read from SOLVER env var, default "glpk".
    """

    horizon_intervals: int = Field(default=288, gt=0)  # 24h × 12 × 5-min intervals
    interval_minutes: int = Field(default=5, gt=0)
    solver: str = Field(
        default_factory=lambda: os.environ.get("SOLVER", "glpk")
    )

    @property
    def horizon_hours(self) -> float:
        return self.horizon_intervals * self.interval_minutes / 60.0


# ---------------------------------------------------------------------------
# Model builder
# ---------------------------------------------------------------------------

def build_model(config: OptimisationConfig) -> pyo.ConcreteModel:
    """Build a Pyomo ConcreteModel scaffold for BESS dispatch optimisation.

    The model contains:
    - Set T: time intervals [0, horizon_intervals)
    - Decision variables: charge_kw, discharge_kw, soc_kwh (all ≥ 0)
    - Placeholder SOC balance constraint
    - Placeholder objective (minimise 0 — to be replaced by cost function)

    Args:
        config: Optimisation configuration.

    Returns:
        A Pyomo ConcreteModel ready for parameter population and solving.
    """
    m = pyo.ConcreteModel(name="BESS_CoOptimisation")

    # ------------------------------------------------------------------
    # Index sets
    # ------------------------------------------------------------------
    m.T = pyo.RangeSet(0, config.horizon_intervals - 1)

    # ------------------------------------------------------------------
    # Decision variables
    # ------------------------------------------------------------------
    # Charging power [kW] at each interval
    m.charge_kw = pyo.Var(m.T, within=pyo.NonNegativeReals, initialize=0.0)

    # Discharging power [kW] at each interval
    m.discharge_kw = pyo.Var(m.T, within=pyo.NonNegativeReals, initialize=0.0)

    # State of charge [kWh] at the end of each interval
    m.soc_kwh = pyo.Var(m.T, within=pyo.NonNegativeReals, initialize=0.0)

    # ------------------------------------------------------------------
    # Placeholder objective — to be replaced by actual cost function
    # ------------------------------------------------------------------
    m.obj = pyo.Objective(expr=0, sense=pyo.minimize)

    # ------------------------------------------------------------------
    # Placeholder constraints — SOC balance will be populated per-scenario
    # ------------------------------------------------------------------
    def _soc_balance_rule(model: pyo.ConcreteModel, t: int) -> object:
        """SOC balance: soc[t] = soc[t-1] + charge[t] - discharge[t] (placeholder)."""
        return pyo.Constraint.Skip

    m.soc_balance = pyo.Constraint(m.T, rule=_soc_balance_rule)

    logger.debug(
        "Built BESS model: %d intervals × %d min = %.1fh horizon",
        config.horizon_intervals,
        config.interval_minutes,
        config.horizon_hours,
    )
    return m


# ---------------------------------------------------------------------------
# Solver
# ---------------------------------------------------------------------------

def solve_model(
    model: pyo.ConcreteModel,
    config: OptimisationConfig,
) -> dict[str, object]:
    """Solve the Pyomo model and return a status dict.

    Args:
        model: A ConcreteModel built by build_model().
        config: Optimisation configuration (used to select solver).

    Returns:
        Dict with keys:
        - ``status`` (str): Solver status string ("ok", "warning", "error",
          "aborted", "solver_not_found")
        - ``termination_condition`` (str): Termination condition string
        - ``objective`` (float | None): Objective value if solve succeeded
    """
    try:
        solver = pyo.SolverFactory(config.solver)
        if not solver.available():
            logger.warning("Solver '%s' is not available", config.solver)
            return {
                "status": "solver_not_found",
                "termination_condition": "not_available",
                "objective": None,
            }
        results = solver.solve(model, tee=False)
    except Exception as exc:  # noqa: BLE001
        logger.error("Solver error: %s", exc)
        return {
            "status": "error",
            "termination_condition": str(exc),
            "objective": None,
        }

    status = str(results.solver.status)
    termination = str(results.solver.termination_condition)

    objective: float | None = None
    try:
        objective = float(pyo.value(model.obj))
    except Exception:  # noqa: BLE001
        pass

    logger.info(
        "Solve complete: status=%s termination=%s objective=%s",
        status, termination, objective,
    )
    return {
        "status": status,
        "termination_condition": termination,
        "objective": objective,
    }
