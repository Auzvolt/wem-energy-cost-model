"""Auto-sizing optimisation module.

Adds capacity as a continuous decision variable to the Pyomo model and
provides a parametric sweep for Pareto-frontier analysis.

Provides:
- AutoSizeConfig: Pydantic config for auto-sizing mode
- SizeResult: Result dataclass for a single capacity point
- add_auto_size_vars: Inject capacity variables into an existing Pyomo model
- sweep_capacity: Parametric sweep returning a list of SizeResult
"""

from __future__ import annotations

from dataclasses import dataclass

import pyomo.environ as pyo
from pydantic import BaseModel, Field

from app.models.capex import CapexModel

__all__ = [
    "AutoSizeConfig",
    "SizeResult",
    "add_auto_size_vars",
    "sweep_capacity",
]


class AutoSizeConfig(BaseModel):
    """Configuration for auto-sizing optimisation mode.

    Attributes
    ----------
    capex:
        Capital expenditure model used for NPV and annualisation calculations.
    discount_rate:
        Annual discount rate as a decimal fraction. Default 8 %.
    min_capacity_mw:
        Lower bound on the capacity decision variable (MW). Default 0.
    max_capacity_mw:
        Upper bound on the capacity decision variable (MW). Default 1000.
    is_bess:
        When True, also add a ``capacity_mwh`` variable for BESS duration sizing.
    """

    capex: CapexModel
    discount_rate: float = Field(default=0.08, ge=0.0, description="Annual discount rate")
    min_capacity_mw: float = Field(default=0.0, ge=0.0, description="Min capacity (MW)")
    max_capacity_mw: float = Field(default=1000.0, gt=0.0, description="Max capacity (MW)")
    is_bess: bool = Field(default=False, description="Also size MWh for BESS assets")


@dataclass
class SizeResult:
    """Result for a single point in the capacity sweep.

    Attributes
    ----------
    capacity_mw:
        Installed capacity evaluated at this sweep point (MW).
    npv:
        Net present value of cash flows at this capacity (currency units).
    irr:
        Internal rate of return. None when not computed.
    lcoe:
        Levelised cost of energy. None when not computed.
    """

    capacity_mw: float
    npv: float
    irr: float | None
    lcoe: float | None


def add_auto_size_vars(model: pyo.ConcreteModel, config: AutoSizeConfig) -> None:
    """Add capacity decision variables to an existing Pyomo ConcreteModel.

    Variables added:
    - ``model.capacity_mw``: continuous, non-negative, bounded by
      [config.min_capacity_mw, config.max_capacity_mw].
    - ``model.capacity_mwh``: continuous, non-negative (only when
      ``config.is_bess=True``).

    Parameters
    ----------
    model:
        Pyomo ConcreteModel to extend. Must already be initialised.
    config:
        Auto-sizing configuration specifying bounds and BESS flag.
    """
    model.capacity_mw = pyo.Var(
        domain=pyo.NonNegativeReals,
        bounds=(config.min_capacity_mw, config.max_capacity_mw),
        initialize=config.min_capacity_mw,
    )
    if config.is_bess:
        model.capacity_mwh = pyo.Var(
            domain=pyo.NonNegativeReals,
            initialize=0.0,
        )


def sweep_capacity(
    config: AutoSizeConfig,
    capex_model: CapexModel,
    capacity_range: tuple[float, float],
    steps: int,
    revenue_per_mw_year: float,
) -> list[SizeResult]:
    """Parametric capacity sweep returning NPV for each capacity point.

    The NPV is computed analytically (no Pyomo solve required):

        NPV = revenue_per_mw_year * capacity_mw
              * sum(1 / (1 + r)^t  for t in 1..life_years)
              - capex_per_kw * 1000 * capacity_mw

    IRR and LCOE are not computed and are returned as None.

    Parameters
    ----------
    config:
        Auto-sizing configuration (used for discount_rate).
    capex_model:
        Capital expenditure parameters (capex_per_kw, life_years).
    capacity_range:
        ``(min_mw, max_mw)`` sweep bounds.
    steps:
        Number of evenly-spaced capacity points (including endpoints).
    revenue_per_mw_year:
        Annual revenue generated per MW of installed capacity ($/MW/year).

    Returns
    -------
    list[SizeResult]
        One entry per sweep step, in ascending capacity order.
    """
    if steps < 1:
        raise ValueError("steps must be >= 1")

    min_mw, max_mw = capacity_range
    r = config.discount_rate
    n = capex_model.life_years

    # Present-value annuity factor: sum(1/(1+r)^t for t=1..n)
    pv_factor = float(n) if r == 0.0 else (1.0 - (1.0 + r) ** (-n)) / r

    results: list[SizeResult] = []
    for i in range(steps):
        capacity_mw = min_mw if steps == 1 else min_mw + (max_mw - min_mw) * i / (steps - 1)

        revenue_pv = revenue_per_mw_year * capacity_mw * pv_factor
        capex_total = capex_model.capex_per_kw * 1000.0 * capacity_mw
        npv = revenue_pv - capex_total

        results.append(SizeResult(capacity_mw=capacity_mw, npv=npv, irr=None, lcoe=None))

    return results
