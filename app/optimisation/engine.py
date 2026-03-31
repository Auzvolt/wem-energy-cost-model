"""Pyomo co-optimisation engine scaffold for WEM Energy Cost Modelling Tool.

Provides:
- WEMModel: abstract base model that sets up time-indexed sets and the
  objective function framework
- ModelConfig: Pydantic-based solver and model configuration
- SolveResult: structured results dataclass
- build_trivial_model: helper for integration tests
"""

from __future__ import annotations

import contextlib
import enum
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pyomo.environ as pyo

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class ObjectiveSense(enum.StrEnum):
    """Optimisation direction."""

    minimise_cost = "minimise_cost"
    maximise_revenue = "maximise_revenue"


@dataclass
class SolverConfig:
    """Pyomo solver configuration.

    The default solver is CBC (open-source MILP/LP solver).
    Set solver_name='gurobi' and ensure GUROBI_HOME / licence are configured
    for commercial solver access.
    """

    solver_name: str = "cbc"
    timelimit_seconds: int = 300
    mip_gap: float = 0.005  # 0.5 % optimality gap
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelConfig:
    """Top-level model configuration."""

    interval_minutes: int = 5  # WEM post-reform dispatch interval
    objective_sense: ObjectiveSense = ObjectiveSense.maximise_revenue
    solver: SolverConfig = field(default_factory=SolverConfig)


# ---------------------------------------------------------------------------
# Solve result
# ---------------------------------------------------------------------------


@dataclass
class SolveResult:
    """Structured result from a model solve."""

    status: str  # 'optimal', 'feasible', 'infeasible', 'error'
    termination_condition: str
    objective_value: float | None
    solve_time_seconds: float | None
    variables: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_optimal(self) -> bool:
        return self.status == "optimal"


# ---------------------------------------------------------------------------
# Base model
# ---------------------------------------------------------------------------


class WEMModel:
    """Abstract base Pyomo co-optimisation model for WEM dispatch.

    Subclasses should:
    1. Call ``super().__init__(intervals, config)``
    2. Add asset-specific variables and constraints via ``add_variables()``
       and ``add_constraints()``
    3. Call ``build()`` before ``solve()``

    The base model sets up:
    - ``model.T``: ordered set of interval indices (0-based integers)
    - ``model.interval_duration_h``: hours per dispatch interval (Param)
    - ``model.objective``: Objective expression (initially 0, overridden by subclasses)
    """

    def __init__(
        self,
        intervals: list[datetime],
        config: ModelConfig | None = None,
    ) -> None:
        self.config = config or ModelConfig()
        self.intervals = intervals
        self._n = len(intervals)
        self.model = pyo.ConcreteModel(name="WEMDispatch")
        self._built = False
        self._objective_expr: pyo.Expression | float = 0.0

    # ------------------------------------------------------------------
    # Internal build helpers
    # ------------------------------------------------------------------

    def _build_sets(self) -> None:
        """Create the time-indexed set T."""
        self.model.T = pyo.Set(initialize=range(self._n), ordered=True)

    def _build_params(self) -> None:
        """Create shared parameters."""
        hours_per_interval = self.config.interval_minutes / 60.0
        self.model.interval_duration_h = pyo.Param(
            initialize=hours_per_interval,
            doc="Duration of each dispatch interval in hours",
        )

    def _build_objective(self) -> None:
        """Attach objective function."""
        sense = (
            pyo.maximize
            if self.config.objective_sense == ObjectiveSense.maximise_revenue
            else pyo.minimize
        )
        # The expression is accumulated by subclasses via add_objective_term().
        self.model.objective = pyo.Objective(
            expr=self._objective_expr,
            sense=sense,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_objective_term(self, expr: Any) -> None:
        """Accumulate a term into the objective expression.

        Must be called before ``build()``.
        """
        self._objective_expr = self._objective_expr + expr

    def add_variables(self) -> None:
        """Override in subclasses to add Pyomo Var/Param blocks."""

    def add_constraints(self) -> None:
        """Override in subclasses to add Pyomo Constraint blocks."""

    def build(self) -> pyo.ConcreteModel:
        """Build the complete Pyomo model.

        Call order: sets → params → variables → constraints → objective.
        Returns the underlying ``pyo.ConcreteModel``.
        """
        if self._built:
            raise RuntimeError("Model has already been built. Create a new instance.")
        self._build_sets()
        self._build_params()
        self.add_variables()
        self.add_constraints()
        self._build_objective()
        self._built = True
        logger.debug(
            "Model built: %d intervals, solver=%s", self._n, self.config.solver.solver_name
        )
        return self.model

    def solve(self) -> SolveResult:
        """Solve the model and return a structured SolveResult.

        Raises:
            RuntimeError: if the model has not been built yet.
        """
        if not self._built:
            raise RuntimeError("Call build() before solve().")

        solver_cfg = self.config.solver
        solver = pyo.SolverFactory(solver_cfg.solver_name)
        if not solver.available():
            raise RuntimeError(
                f"Solver '{solver_cfg.solver_name}' is not available. "
                "Install CBC via 'apt-get install coinor-cbc' or set solver_name='glpk'."
            )

        # Apply solver options
        if solver_cfg.timelimit_seconds:
            solver.options["seconds"] = solver_cfg.timelimit_seconds
        if solver_cfg.mip_gap:
            solver.options["ratio"] = solver_cfg.mip_gap
        for key, val in solver_cfg.options.items():
            solver.options[key] = val

        logger.info(
            "Solving with %s (timelimit=%ds, gap=%.3f)…",
            solver_cfg.solver_name,
            solver_cfg.timelimit_seconds,
            solver_cfg.mip_gap,
        )
        results = solver.solve(self.model, tee=False)
        tc = str(results.solver.termination_condition)
        status_map = {
            "optimal": "optimal",
            "feasible": "feasible",
        }
        status = status_map.get(tc, "infeasible" if "infeasible" in tc else "error")

        obj_val: float | None = None
        if status in ("optimal", "feasible"):
            with contextlib.suppress(Exception):
                obj_val = float(pyo.value(self.model.objective))

        solve_time: float | None = None
        with contextlib.suppress(Exception):
            solve_time = float(results.solver.time)

        logger.info("Solve complete: status=%s objective=%.4f", status, obj_val or 0.0)
        return SolveResult(
            status=status,
            termination_condition=tc,
            objective_value=obj_val,
            solve_time_seconds=solve_time,
        )

    def extract_variable(self, var: pyo.Var) -> dict[int, float]:
        """Extract values from an indexed Pyomo variable into a plain dict."""
        if not self._built:
            raise RuntimeError("Call build() and solve() before extracting variables.")
        return {int(idx): float(pyo.value(var[idx])) for idx in var}


# ---------------------------------------------------------------------------
# Trivial model helper (used in integration tests)
# ---------------------------------------------------------------------------


def build_trivial_model(
    n_intervals: int = 12,
    interval_minutes: int = 5,
    config: ModelConfig | None = None,
) -> WEMModel:
    """Build a trivial WEMModel that solves correctly with no added assets.

    The objective is set to a constant (0.0) so any solver that supports LP
    will return 'optimal' immediately.  Used to verify environment setup.
    """
    intervals = [
        datetime(2024, 1, 1, 0, i * interval_minutes)
        for i in range(n_intervals)
    ]
    cfg = config or ModelConfig(
        interval_minutes=interval_minutes,
        objective_sense=ObjectiveSense.maximise_revenue,
        solver=SolverConfig(solver_name="glpk"),  # GLPK is lightweight for tests
    )
    m = WEMModel(intervals=intervals, config=cfg)
    m.build()
    return m
