"""BESS (Battery Energy Storage System) asset model.

Provides Pydantic configuration, capacity degradation helper, and Pyomo
constraint builder for BESS co-optimisation within the WEM model.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, FieldValidationInfo, ValidationError, field_validator

if TYPE_CHECKING:
    import pyomo.environ as pyo

logger = logging.getLogger(__name__)


class BessConfig(BaseModel):
    """Configuration parameters for a BESS asset."""

    capacity_kwh: float = Field(..., gt=0, description="Nameplate energy capacity (kWh)")
    power_kw: float = Field(..., gt=0, description="Nameplate charge/discharge power (kW)")
    efficiency_rt: float = Field(
        default=0.90,
        ge=0.0,
        le=1.0,
        description="Round-trip efficiency (0–1)",
    )
    soc_min_pct: float = Field(
        default=0.10,
        ge=0.0,
        le=1.0,
        description="Minimum state of charge as fraction of nameplate capacity",
    )
    soc_max_pct: float = Field(
        default=0.90,
        ge=0.0,
        le=1.0,
        description="Maximum state of charge as fraction of nameplate capacity",
    )
    max_daily_cycles: float = Field(
        default=2.0,
        gt=0,
        description="Maximum full charge/discharge cycles per day",
    )
    degradation_pct_per_year: float = Field(
        default=2.0,
        ge=0.0,
        description="Annual capacity degradation percentage (e.g. 2.0 means 2 % per year)",
    )

    @field_validator("soc_max_pct")
    @classmethod
    def soc_window_valid(cls, v: float, info: FieldValidationInfo) -> float:
        """Ensure soc_max > soc_min."""
        soc_min: float = (info.data or {}).get("soc_min_pct", 0.0)
        if v <= soc_min:
            raise ValueError("soc_max_pct must be greater than soc_min_pct")
        return v


__all__ = ["BessConfig", "ValidationError", "add_bess_constraints", "degraded_capacity"]


def degraded_capacity(config: BessConfig, age_years: float) -> float:
    """Return the usable energy capacity (kWh) accounting for calendar ageing.

    Applies a linear degradation model::

        capacity(age) = nameplate * (1 - degradation_rate * age)

    Result is clamped to zero so capacity never goes negative.

    Args:
        config: BESS configuration.
        age_years: Asset age in years (>= 0).

    Returns:
        Degraded usable capacity in kWh.
    """
    if age_years < 0:
        raise ValueError(f"age_years must be non-negative, got {age_years}")
    degradation_factor = 1.0 - (config.degradation_pct_per_year / 100.0) * age_years
    return max(0.0, config.capacity_kwh * degradation_factor)


def add_bess_constraints(
    model: pyo.ConcreteModel,
    config: BessConfig,
    *,
    interval_h: float = 5.0 / 60.0,
    age_years: float = 0.0,
) -> None:
    """Add BESS decision variables and constraints to an existing Pyomo model.

    Expects *model* to already have a set ``model.T`` (ordered integer indices).

    Variables added:
        charge_kw[t]    -- charging power (>= 0)
        discharge_kw[t] -- discharging power (>= 0)
        soc_kwh[t]      -- state of charge at end of interval t (kWh)

    Constraints added:
        bess_charge_limit[t]    -- charge_kw <= power_kw
        bess_discharge_limit[t] -- discharge_kw <= power_kw
        bess_soc_balance[t]     -- SoC continuity (charge in, discharge out)
        bess_daily_cycle        -- total energy throughput <= max_daily_cycles

    Args:
        model: Pyomo ConcreteModel with set T already populated.
        config: BESS configuration.
        interval_h: Length of each dispatch interval in hours (default 5 min).
        age_years: Asset age for capacity degradation calculation.
    """
    import pyomo.environ as pyo  # local import -- optional dependency

    cap = degraded_capacity(config, age_years)
    eta_one_way = config.efficiency_rt**0.5  # split round-trip efficiency symmetrically
    soc_min_kwh = config.soc_min_pct * cap
    soc_max_kwh = config.soc_max_pct * cap

    T = list(model.T)
    first_t = T[0]
    soc_init = (soc_min_kwh + soc_max_kwh) / 2.0

    # -- Decision variables ---------------------------------------------------
    model.charge_kw = pyo.Var(model.T, domain=pyo.NonNegativeReals, initialize=0.0)
    model.discharge_kw = pyo.Var(model.T, domain=pyo.NonNegativeReals, initialize=0.0)
    model.soc_kwh = pyo.Var(
        model.T,
        domain=pyo.NonNegativeReals,
        bounds=(soc_min_kwh, soc_max_kwh),
        initialize=soc_init,
    )

    # -- Power limits ---------------------------------------------------------
    model.bess_charge_limit = pyo.Constraint(
        model.T,
        rule=lambda m, t: m.charge_kw[t] <= config.power_kw,
    )
    model.bess_discharge_limit = pyo.Constraint(
        model.T,
        rule=lambda m, t: m.discharge_kw[t] <= config.power_kw,
    )

    # -- SoC balance ----------------------------------------------------------
    def soc_balance_rule(m: pyo.ConcreteModel, t: int) -> pyo.Expression:
        soc_prev = soc_init if t == first_t else m.soc_kwh[t - 1]
        return (
            m.soc_kwh[t]
            == soc_prev
            + m.charge_kw[t] * eta_one_way * interval_h
            - m.discharge_kw[t] / eta_one_way * interval_h
        )

    model.bess_soc_balance = pyo.Constraint(model.T, rule=soc_balance_rule)

    # -- Daily throughput cycle limit ----------------------------------------
    max_throughput_kwh = config.max_daily_cycles * cap
    model.bess_daily_cycle = pyo.Constraint(
        expr=pyo.summation(model.discharge_kw) * interval_h <= max_throughput_kwh
    )

    logger.debug(
        "BESS constraints added: capacity=%.1f kWh (degraded from %.1f), "
        "power=%.1f kW, SoC window=[%.1f, %.1f] kWh",
        cap,
        config.capacity_kwh,
        config.power_kw,
        soc_min_kwh,
        soc_max_kwh,
    )
