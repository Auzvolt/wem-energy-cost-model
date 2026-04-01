"""Reserve Capacity Mechanism (RCM) participation model.

Models WEM Reserve Capacity Mechanism obligations and revenue for assets
(primarily BESS) that hold Capacity Credits.

The RCM requires accredited assets to be available during trading intervals
at a minimum availability threshold. In return, they receive an annual
capacity payment proportional to their assigned Capacity Credits.

References
----------
- WEM Wholesale Electricity Market Procedure: Reserve Capacity Mechanism
- AEMO WA: Reserve Capacity Mechanism Rules
"""

from __future__ import annotations

from typing import Any

import pyomo.environ as pyo
from pydantic import BaseModel, Field

__all__ = ["CapacityConfig", "add_capacity_model"]


class CapacityConfig(BaseModel):
    """Configuration for Reserve Capacity Mechanism participation.

    Attributes
    ----------
    capacity_credits_mw:
        MW of Reserve Capacity Credits assigned to this asset.
        Zero means the asset does not participate in the RCM.
    accredited_capacity_mw:
        ICAP accreditation in MW. Must be >= capacity_credits_mw.
        Defaults to capacity_credits_mw if not set.
    capacity_price_per_mw_year:
        Annual capacity payment rate ($/MW/year). Current WEM reference
        price is approximately $236,000/MW/year.
    availability_threshold:
        Fraction of trading intervals in which the asset must be available
        to provide its credited capacity. Default 0.85 (85%).
    trading_intervals_per_year:
        Total number of trading intervals in a year. For 30-minute intervals
        (pre-reform SWIS): 17520. For 5-minute intervals (post-reform): 105120.
        Default 17520.
    """

    capacity_credits_mw: float = Field(
        default=0.0, ge=0.0, description="Reserve Capacity Credits (MW)"
    )
    accredited_capacity_mw: float | None = Field(
        default=None,
        ge=0.0,
        description="ICAP accreditation (MW). Defaults to capacity_credits_mw.",
    )
    capacity_price_per_mw_year: float = Field(
        default=236_000.0,
        ge=0.0,
        description="Annual capacity payment rate ($/MW/year)",
    )
    availability_threshold: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Minimum availability fraction (0–1)",
    )
    trading_intervals_per_year: int = Field(
        default=17520,
        ge=1,
        description="Total trading intervals per year (for revenue annualisation)",
    )

    def effective_accredited_mw(self) -> float:
        """Return effective accreditation, falling back to capacity_credits_mw."""
        if self.accredited_capacity_mw is not None:
            return self.accredited_capacity_mw
        return self.capacity_credits_mw


def add_capacity_model(
    model: Any,
    config: CapacityConfig,
) -> None:
    """Add Reserve Capacity Mechanism constraints and revenue to a Pyomo model.

    This function is a no-op if ``config.capacity_credits_mw == 0``.

    The model must already have:
    - ``model.T`` — a Pyomo Set of time interval indices
    - ``model.charge_kw[t]`` — charging power variable (kW)
    - ``model.discharge_kw[t]`` — discharging power variable (kW) with upper
      bound equal to the asset's rated power (used to derive power_kw)

    Parameters
    ----------
    model:
        Pyomo ConcreteModel to augment with RCM constraints and revenue.
    config:
        RCM participation configuration.
    """
    if config.capacity_credits_mw <= 0.0:
        return

    # ------------------------------------------------------------------
    # Derive asset rated power from the discharge variable upper bound.
    # Fall back to accredited capacity if no bound is available.
    # ------------------------------------------------------------------
    power_kw: float | None = None
    for t in model.T:
        ub = pyo.value(model.discharge_kw[t].ub)
        if ub is not None:
            power_kw = float(ub)
            break

    if power_kw is None:
        # Fall back: use accredited capacity
        power_kw = config.effective_accredited_mw() * 1000.0

    credits_kw = config.capacity_credits_mw * 1000.0  # MW → kW

    # ------------------------------------------------------------------
    # Availability obligation constraint
    #
    # The asset must be able to supply its credited capacity at each
    # trading interval (simplified: continuous obligation across all
    # intervals). The constraint ensures enough discharge headroom:
    #
    #   power_kw - charge_kw[t] >= credits_kw * availability_threshold
    #   ⟺  charge_kw[t] <= power_kw - credits_kw * availability_threshold
    #
    # This means while the asset is absorbing energy (charging), it must
    # still retain enough reserve headroom to honour its capacity obligation.
    # ------------------------------------------------------------------
    headroom_kw = credits_kw * config.availability_threshold
    max_allowed_charge_kw = power_kw - headroom_kw

    if max_allowed_charge_kw < 0.0:
        raise ValueError(
            f"Capacity credits ({config.capacity_credits_mw} MW) × "
            f"availability threshold ({config.availability_threshold}) "
            f"exceeds asset power rating ({power_kw / 1000:.3f} MW). "
            "Reduce credits or lower availability threshold."
        )

    def availability_rule(m: Any, t: int) -> Any:
        """Charge must leave enough headroom for capacity obligation."""
        return m.charge_kw[t] <= max_allowed_charge_kw

    model.rcm_availability = pyo.Constraint(model.T, rule=availability_rule)

    # ------------------------------------------------------------------
    # Annual capacity revenue term
    #
    # Revenue = credits_mw * price_per_mw_year
    # Annualised per interval = total_revenue / intervals_per_year
    # Total revenue across all model intervals = per_interval * n_intervals
    # ------------------------------------------------------------------
    n_intervals = len(list(model.T))
    revenue_per_interval = (
        config.capacity_credits_mw
        * config.capacity_price_per_mw_year
        / config.trading_intervals_per_year
    )
    total_rcm_revenue = revenue_per_interval * n_intervals

    # Add to or create the objective
    if hasattr(model, "objective"):
        existing_sense = model.objective.sense
        existing_expr = model.objective.expr
        model.del_component(model.objective)
        model.objective = pyo.Objective(
            expr=existing_expr + total_rcm_revenue,
            sense=existing_sense,
        )
    else:
        model.objective = pyo.Objective(expr=total_rcm_revenue, sense=pyo.maximize)
