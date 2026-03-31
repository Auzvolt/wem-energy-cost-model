"""BESS asset model for WEM co-optimisation.

Provides BessConfig, degraded_capacity(), and add_bess_constraints()
which extend a Pyomo ConcreteModel built by optimisation.model.build_model().
"""
from __future__ import annotations

import math

import pyomo.environ as pyo
from pydantic import BaseModel, Field


class BessConfig(BaseModel):
    """Configuration for a Battery Energy Storage System asset."""

    capacity_kwh: float = Field(gt=0, description="Usable energy capacity in kWh")
    power_kw: float = Field(gt=0, description="Maximum charge/discharge power in kW")
    efficiency_rt: float = Field(
        default=0.9,
        gt=0,
        le=1.0,
        description="Round-trip efficiency (0-1)",
    )
    soc_min_pct: float = Field(
        default=0.1,
        ge=0,
        lt=1.0,
        description="Minimum state-of-charge as fraction of capacity",
    )
    soc_max_pct: float = Field(
        default=0.9,
        gt=0,
        le=1.0,
        description="Maximum state-of-charge as fraction of capacity",
    )
    max_daily_cycles: int = Field(
        default=2,
        gt=0,
        description="Maximum full charge/discharge cycles per day",
    )
    degradation_pct_per_year: float = Field(
        default=2.0,
        ge=0,
        le=100,
        description="Annual capacity fade as a percentage of rated capacity",
    )


def degraded_capacity(config: BessConfig, year: int) -> float:
    """Return the effective capacity (kWh) after `year` years of degradation.

    Uses a compound annual fade model:
        capacity * (1 - degradation_pct_per_year / 100) ^ year

    Args:
        config: BESS configuration.
        year: Number of years since commissioning (0 = nameplate).

    Returns:
        Effective capacity in kWh.
    """
    if year < 0:
        raise ValueError(f"year must be >= 0, got {year}")
    annual_retention = 1.0 - config.degradation_pct_per_year / 100.0
    return config.capacity_kwh * (annual_retention**year)


def add_bess_constraints(
    model: pyo.ConcreteModel,
    config: BessConfig,
    interval_minutes: int = 5,
) -> None:
    """Add BESS physical constraints to an existing Pyomo ConcreteModel.

    The model is expected to have already been created by
    ``optimisation.model.build_model()`` and therefore already contains:
        - ``model.T``: RangeSet of interval indices
        - ``model.charge_kw``: Var indexed over T
        - ``model.discharge_kw``: Var indexed over T
        - ``model.soc_kwh``: Var indexed over T

    This function replaces / augments the placeholder constraints with
    physically correct ones and sets variable bounds.

    Args:
        model: An existing Pyomo ConcreteModel with T, charge_kw,
               discharge_kw, soc_kwh already defined.
        config: BESS asset parameters.
        interval_minutes: Length of each dispatch interval in minutes.
    """
    dt_h = interval_minutes / 60.0  # hours per interval
    eff_one_way = math.sqrt(config.efficiency_rt)
    soc_min = config.soc_min_pct * config.capacity_kwh
    soc_max = config.soc_max_pct * config.capacity_kwh

    intervals: list[int] = list(model.T)
    n = len(intervals)

    # ── Variable bounds ───────────────────────────────────────────────────────

    for t in intervals:
        model.charge_kw[t].setlb(0)
        model.charge_kw[t].setub(config.power_kw)
        model.discharge_kw[t].setlb(0)
        model.discharge_kw[t].setub(config.power_kw)
        model.soc_kwh[t].setlb(soc_min)
        model.soc_kwh[t].setub(soc_max)

    # ── Remove placeholder SOC balance if present ────────────────────────────
    if hasattr(model, "soc_balance"):
        model.del_component(model.soc_balance)

    # ── SOC balance constraint ────────────────────────────────────────────────
    # soc[t+1] = soc[t] + charge[t]*eff_one_way*dt - discharge[t]/eff_one_way*dt
    def _soc_balance_rule(m: pyo.ConcreteModel, idx: int) -> pyo.Expression:
        t = intervals[idx]
        t_next = intervals[idx + 1]
        return (
            m.soc_kwh[t_next]
            == m.soc_kwh[t]
            + m.charge_kw[t] * eff_one_way * dt_h
            - m.discharge_kw[t] / eff_one_way * dt_h
        )

    model.soc_balance = pyo.Constraint(
        range(n - 1),
        rule=_soc_balance_rule,
    )

    # ── Terminal constraint: end SoC ≥ minimum ────────────────────────────────
    last_t = intervals[-1]
    model.soc_terminal = pyo.Constraint(
        expr=model.soc_kwh[last_t] >= soc_min
    )

    # ── Simultaneous charge/discharge limit ───────────────────────────────────
    # charge + discharge <= power_kw (prevents simultaneous full power)
    def _charge_discharge_limit_rule(
        m: pyo.ConcreteModel, t: int
    ) -> pyo.Expression:
        return m.charge_kw[t] + m.discharge_kw[t] <= config.power_kw

    model.charge_discharge_limit = pyo.Constraint(
        model.T,
        rule=_charge_discharge_limit_rule,
    )
