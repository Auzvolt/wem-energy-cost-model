"""Reserve Capacity Mechanism (RCM) participation model.

Models WEM Reserve Capacity Mechanism obligations and revenue within the
Pyomo co-optimisation engine.

WEM RCM background
------------------
Facilities that hold Capacity Credits (CCs) must make their accredited capacity
available during Trading Intervals (TIs).  In return they receive an annual
capacity payment based on the Reserve Capacity Price (RCP).

This module provides:
- ``RcmConfig``             — Pydantic configuration for an RCM participant
- ``add_rcm_constraints``   — Adds RCM variables/constraints/revenue to a
                              ``pyo.ConcreteModel`` that already has a ``T``
                              set and an ``_objective_terms`` list attribute
- ``annual_rcm_revenue``    — Pure-Python helper returning annual RCM revenue
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class RcmConfig(BaseModel):
    """Configuration for a Reserve Capacity Mechanism participant.

    Attributes:
        accredited_mw: Accredited Capacity Credits (MW).  Must be positive.
        capacity_price_aud_per_mw_year: Reserve Capacity Price (AUD/MW/year).
            Must be non-negative.
        availability_obligation_pct: Fraction of accredited capacity that must
            be declared available each Trading Interval (0–1, default 0.85).
    """

    accredited_mw: float = Field(..., gt=0, description="Accredited capacity credits (MW)")
    capacity_price_aud_per_mw_year: float = Field(
        ...,
        ge=0,
        description="Reserve Capacity Price (AUD/MW/year)",
    )
    availability_obligation_pct: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Minimum available fraction each Trading Interval (0–1)",
    )

    @field_validator("accredited_mw")
    @classmethod
    def accredited_mw_positive(cls, v: float) -> float:
        """Redundant guard — gt=0 already enforces this; kept for clarity."""
        if v <= 0:
            raise ValueError("accredited_mw must be positive")
        return v


__all__ = [
    "RcmConfig",
    "add_rcm_constraints",
    "annual_rcm_revenue",
]


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def annual_rcm_revenue(config: RcmConfig) -> float:
    """Return annual Reserve Capacity revenue (AUD).

    Args:
        config: RCM participant configuration.

    Returns:
        Annual revenue in AUD = accredited_mw × capacity_price_aud_per_mw_year.
    """
    return config.accredited_mw * config.capacity_price_aud_per_mw_year


# ---------------------------------------------------------------------------
# Pyomo constraint builder
# ---------------------------------------------------------------------------


def add_rcm_constraints(
    model: Any,
    config: RcmConfig,
    interval_duration_h: float,
) -> None:
    """Add RCM variables, constraints, and revenue contribution to *model*.

    The model must already have:
    - ``model.T`` — an ordered Pyomo Set of integer interval indices.

    After this call the model gains:
    - ``model.rcm_available_mw``         — Var indexed over T
    - ``model.rcm_availability_con``     — Constraint: available ≥ obligation
    - ``model.rcm_annual_revenue_aud``   — Param (AUD/year)
    - ``model.rcm_revenue_per_interval`` — Expression (AUD per interval)
    - ``model.rcm_total_revenue``        — Expression (AUD over horizon T)

    The pro-rated interval revenue is::

        revenue_per_interval = annual_revenue / intervals_per_year
        intervals_per_year   = 8760 / interval_duration_h

    Args:
        model: A ``pyo.ConcreteModel`` with a ``T`` set already defined.
        config: RCM participant configuration.
        interval_duration_h: Duration of each dispatch interval in hours
            (e.g. 0.5 for 30-min intervals, 1/12 for 5-min intervals).
    """
    import pyomo.environ as pyo  # local import keeps module importable without pyomo

    n_intervals = len(model.T)
    if n_intervals == 0:
        logger.warning("add_rcm_constraints: model.T is empty — skipping")
        return

    # ------------------------------------------------------------------
    # Parameters
    # ------------------------------------------------------------------
    model.rcm_annual_revenue_aud = pyo.Param(
        initialize=annual_rcm_revenue(config),
        within=pyo.NonNegativeReals,
        doc="Annual RCM capacity revenue (AUD)",
    )

    # ------------------------------------------------------------------
    # Variables
    # ------------------------------------------------------------------
    model.rcm_available_mw = pyo.Var(
        model.T,
        within=pyo.NonNegativeReals,
        bounds=(0.0, config.accredited_mw),
        initialize=config.accredited_mw,
        doc="Available capacity declared each interval (MW)",
    )

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------
    obligation_mw = config.availability_obligation_pct * config.accredited_mw

    def _availability_rule(m: Any, t: int) -> Any:
        return m.rcm_available_mw[t] >= obligation_mw

    model.rcm_availability_con = pyo.Constraint(
        model.T,
        rule=_availability_rule,
        doc="Availability obligation: declared MW >= obligation_pct × accredited_mw",
    )

    # ------------------------------------------------------------------
    # Revenue expressions
    # ------------------------------------------------------------------
    intervals_per_year = 8760.0 / interval_duration_h

    model.rcm_revenue_per_interval = pyo.Expression(
        expr=model.rcm_annual_revenue_aud / intervals_per_year,
        doc="RCM revenue earned per dispatch interval (AUD)",
    )

    model.rcm_total_revenue = pyo.Expression(
        expr=sum(model.rcm_revenue_per_interval for _ in model.T),
        doc="Total RCM revenue over the optimisation horizon (AUD)",
    )

    logger.debug(
        "RCM constraints added: %d intervals, accredited_mw=%.1f, "
        "annual_revenue=%.2f AUD",
        n_intervals,
        config.accredited_mw,
        float(model.rcm_annual_revenue_aud),
    )
