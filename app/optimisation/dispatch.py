"""Wholesale energy dispatch model.

Adds export/import quantity variables and net-position constraints that link
BESS charge/discharge to the WEM wholesale market, and accumulates a
price-taker revenue term into the model objective.
"""

from __future__ import annotations

from typing import Any

import pyomo.environ as pyo
from pydantic import BaseModel, field_validator

__all__ = ["WholesaleDispatchConfig", "add_wholesale_dispatch"]


class WholesaleDispatchConfig(BaseModel):
    """Configuration for wholesale energy market dispatch participation."""

    max_export_kw: float
    """Maximum export (sell) capacity in kW."""

    max_import_kw: float
    """Maximum import (buy) capacity in kW."""

    @field_validator("max_export_kw", "max_import_kw")
    @classmethod
    def must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("max_export_kw and max_import_kw must be > 0")
        return v


def add_wholesale_dispatch(
    model: pyo.ConcreteModel,
    config: WholesaleDispatchConfig,
    prices: dict[int, float],
) -> None:
    """Add wholesale dispatch variables, constraints, and objective term to *model*.

    Expects *model* to already have:
    - ``model.T``: ordered set of interval indices
    - ``model.interval_duration_h``: Pyomo Param, hours per interval
    - ``model.charge_kw``, ``model.discharge_kw``: BESS power variables (from
      :func:`~app.optimisation.bess.add_bess_constraints`)

    Variables added
    ---------------
    ``model.export_kw[t]``
        Energy exported to the market at interval *t* (kW), ∈ [0, max_export_kw].
    ``model.import_kw[t]``
        Energy imported from the market at interval *t* (kW), ∈ [0, max_import_kw].

    Constraints added
    -----------------
    ``model.dispatch_net_position``
        Enforces ``discharge_kw[t] − charge_kw[t] == export_kw[t] − import_kw[t]``.

    Objective contribution
    ----------------------
    Revenue = Σ_t (export_kw[t] − import_kw[t]) × price[t] × interval_h / 1000
    (converts kW·h to MWh, price in $/MWh → revenue in $).

    Parameters
    ----------
    model:
        Pyomo ``ConcreteModel`` already containing BESS variables and ``model.T``.
    config:
        Wholesale dispatch configuration (export/import limits).
    prices:
        Mapping of interval index → market price ($/MWh).
    """
    interval_h: float = pyo.value(model.interval_duration_h)

    # ------------------------------------------------------------------
    # Decision variables
    # ------------------------------------------------------------------
    model.export_kw = pyo.Var(
        model.T,
        domain=pyo.NonNegativeReals,
        bounds=(0.0, config.max_export_kw),
        initialize=0.0,
    )
    model.import_kw = pyo.Var(
        model.T,
        domain=pyo.NonNegativeReals,
        bounds=(0.0, config.max_import_kw),
        initialize=0.0,
    )

    # ------------------------------------------------------------------
    # Net-position constraint
    # discharge_kw[t] - charge_kw[t] == export_kw[t] - import_kw[t]
    # ------------------------------------------------------------------
    def net_position_rule(m: Any, t: int) -> Any:
        return m.discharge_kw[t] - m.charge_kw[t] == m.export_kw[t] - m.import_kw[t]

    model.dispatch_net_position = pyo.Constraint(model.T, rule=net_position_rule)

    # ------------------------------------------------------------------
    # Objective: price-taker revenue
    # sum_t (export_kw[t] - import_kw[t]) * price[t] * interval_h / 1000
    # ------------------------------------------------------------------
    revenue_expr = sum(
        (model.export_kw[t] - model.import_kw[t]) * prices.get(t, 0.0) * interval_h / 1000.0
        for t in model.T
    )

    # If the engine's add_objective_term hook is available use it; otherwise
    # create or extend model.objective directly so this module works standalone.
    if hasattr(model, "_dispatch_revenue_expr"):
        # Already added — should not happen in normal usage.
        return

    model._dispatch_revenue_expr = revenue_expr  # type: ignore[attr-defined]

    if hasattr(model, "objective"):
        # Extend an existing Objective (e.g. BESS degradation cost added earlier).
        existing_sense = model.objective.sense
        existing_expr = model.objective.expr
        model.del_component(model.objective)
        model.objective = pyo.Objective(
            expr=existing_expr + revenue_expr,
            sense=existing_sense,
        )
    else:
        # Standalone: maximise revenue.
        model.objective = pyo.Objective(expr=revenue_expr, sense=pyo.maximize)
