"""Solar PV asset model.

Models a grid-connected solar PV system within the WEM co-optimisation engine.

Features
--------
- Generation profile from an irradiance time series (W/m²) or a pre-computed
  AC generation profile (kW per interval).
- DC/AC conversion with inverter clipping (DC:AC ratio).
- Curtailment variable with an optional curtailment cost (AUD/kWh).
- Pyomo constraint builder that injects the solar variables and constraints
  into a ``ConcreteModel`` already prepared by the base engine.

Synthetic WA profile
--------------------
If no irradiance data is supplied a simple synthetic profile is generated using
a clear-sky model: a scaled half-sine over the daylight window (6 h to 18 h
local time) with peak at solar noon, normalised to ``system_capacity_kwp``.

Usage example::

    from app.optimisation.solar import SolarConfig, add_solar_constraints

    cfg = SolarConfig(system_capacity_kwp=100.0, dc_ac_ratio=1.2)
    add_solar_constraints(model, cfg, n_intervals=48, interval_duration_h=0.5)
"""

from __future__ import annotations

import logging
import math
from typing import Any

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

__all__ = [
    "SolarConfig",
    "synthetic_generation_profile_kw",
    "ac_generation_kw",
    "add_solar_constraints",
]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class SolarConfig(BaseModel):
    """Configuration for a solar PV asset.

    Attributes:
        system_capacity_kwp: DC nameplate capacity (kWp).  Must be positive.
        dc_ac_ratio: Ratio of DC capacity to AC inverter capacity (≥ 1.0).
            Values > 1 cause clipping at the inverter ceiling.  Typical WA
            utility-scale value is 1.2–1.35.
        efficiency_factor: System efficiency factor (0–1) capturing losses from
            temperature, soiling, wiring, etc.  Default 0.80.
        curtailment_cost_aud_per_kwh: Opportunity cost applied to curtailed
            generation (AUD/kWh).  Default 0.0 (no explicit cost).
        irradiance_w_per_m2: Optional per-interval irradiance series (W/m²).
            Length must equal the number of dispatch intervals.  If ``None``
            a synthetic WA clear-sky profile is generated.
        panel_area_m2: Panel area (m²) used to convert irradiance to DC power.
            Required when ``irradiance_w_per_m2`` is supplied.
    """

    system_capacity_kwp: float = Field(..., gt=0, description="DC nameplate capacity (kWp)")
    dc_ac_ratio: float = Field(
        default=1.2,
        ge=1.0,
        description="DC:AC ratio — inverter AC capacity = system_capacity_kwp / dc_ac_ratio",
    )
    efficiency_factor: float = Field(
        default=0.80,
        gt=0.0,
        le=1.0,
        description="Overall system efficiency (0–1)",
    )
    curtailment_cost_aud_per_kwh: float = Field(
        default=0.0,
        ge=0.0,
        description="Curtailment opportunity cost (AUD/kWh)",
    )
    irradiance_w_per_m2: list[float] | None = Field(
        default=None,
        description="Per-interval irradiance series (W/m²).  None → synthetic profile.",
    )
    panel_area_m2: float | None = Field(
        default=None,
        gt=0,
        description="Panel area (m²) — required when irradiance_w_per_m2 is provided",
    )

    @field_validator("dc_ac_ratio")
    @classmethod
    def dc_ac_ratio_at_least_one(cls, v: float) -> float:
        if v < 1.0:
            raise ValueError("dc_ac_ratio must be ≥ 1.0")
        return v


# ---------------------------------------------------------------------------
# Generation profile helpers
# ---------------------------------------------------------------------------


def synthetic_generation_profile_kw(
    n_intervals: int,
    interval_duration_h: float,
    system_capacity_kwp: float,
    efficiency_factor: float = 0.80,
    dc_ac_ratio: float = 1.2,
) -> list[float]:
    """Generate a synthetic WA clear-sky AC generation profile.

    Uses a half-sine daylight model centred on solar noon (12:00 local time),
    active between 06:00 and 18:00.  DC output is clipped at the AC inverter
    ceiling before applying system efficiency.

    Args:
        n_intervals: Total number of dispatch intervals over the horizon.
        interval_duration_h: Duration of each interval in hours.
        system_capacity_kwp: DC nameplate capacity (kWp).
        efficiency_factor: System efficiency factor (0–1).
        dc_ac_ratio: DC:AC ratio for inverter clipping.

    Returns:
        List of length *n_intervals* with AC generation (kW) for each interval.
    """
    inverter_capacity_kw = system_capacity_kwp / dc_ac_ratio
    profile: list[float] = []

    for i in range(n_intervals):
        hour_of_day = (i * interval_duration_h) % 24.0
        if hour_of_day < 6.0 or hour_of_day >= 18.0:
            profile.append(0.0)
        else:
            angle = math.pi * (hour_of_day - 6.0) / 12.0
            dc_kw = system_capacity_kwp * math.sin(angle)
            ac_kw = min(dc_kw, inverter_capacity_kw) * efficiency_factor
            profile.append(max(ac_kw, 0.0))

    return profile


def ac_generation_kw(
    config: SolarConfig,
    n_intervals: int,
    interval_duration_h: float,
) -> list[float]:
    """Return AC generation (kW) for each interval given *config*.

    If ``config.irradiance_w_per_m2`` is provided the profile is computed from
    irradiance; otherwise a synthetic WA profile is generated.

    Args:
        config: SolarConfig instance.
        n_intervals: Number of intervals (must match irradiance series length
            when irradiance data is provided).
        interval_duration_h: Interval duration in hours.

    Returns:
        List of AC generation values (kW), length == *n_intervals*.

    Raises:
        ValueError: If irradiance series length != n_intervals, or panel_area_m2
            is missing when irradiance data is supplied.
    """
    if config.irradiance_w_per_m2 is not None:
        irr = config.irradiance_w_per_m2
        if len(irr) != n_intervals:
            raise ValueError(
                f"irradiance_w_per_m2 length ({len(irr)}) must equal n_intervals ({n_intervals})"
            )
        if config.panel_area_m2 is None:
            raise ValueError("panel_area_m2 is required when irradiance_w_per_m2 is provided")
        inverter_capacity_kw = config.system_capacity_kwp / config.dc_ac_ratio
        profile = []
        for irr_val in irr:
            dc_kw = irr_val * config.panel_area_m2 / 1000.0
            ac_kw = min(dc_kw, inverter_capacity_kw) * config.efficiency_factor
            profile.append(max(ac_kw, 0.0))
        return profile

    return synthetic_generation_profile_kw(
        n_intervals=n_intervals,
        interval_duration_h=interval_duration_h,
        system_capacity_kwp=config.system_capacity_kwp,
        efficiency_factor=config.efficiency_factor,
        dc_ac_ratio=config.dc_ac_ratio,
    )


# ---------------------------------------------------------------------------
# Pyomo constraint builder
# ---------------------------------------------------------------------------


def add_solar_constraints(
    model: Any,
    config: SolarConfig,
    n_intervals: int,
    interval_duration_h: float,
) -> None:
    """Add solar PV variables and constraints to *model*.

    The model must already have:
    - ``model.T`` — an ordered Pyomo Set of integer interval indices.

    After this call the model gains:

    **Parameters**
    - ``model.solar_max_gen_kw``          — Param indexed over T (kW ceiling)

    **Variables**
    - ``model.solar_gen_kw``              — Var indexed over T (dispatched kW)
    - ``model.solar_curtailed_kw``        — Var indexed over T (curtailed kW)

    **Constraints**
    - ``model.solar_gen_balance``         — gen + curtailed == max_gen each t

    **Expressions**
    - ``model.solar_total_gen_kwh``       — total energy dispatched (kWh)
    - ``model.solar_curtailment_cost_aud`` — total curtailment cost (AUD)

    Args:
        model: ``pyo.ConcreteModel`` with ``T`` set defined.
        config: Solar PV configuration.
        n_intervals: Number of intervals (must equal len(model.T)).
        interval_duration_h: Interval duration in hours.
    """
    import pyomo.environ as pyo

    if len(model.T) == 0:
        logger.warning("add_solar_constraints: model.T is empty — skipping")
        return

    if len(model.T) != n_intervals:
        raise ValueError(f"model.T length ({len(model.T)}) != n_intervals ({n_intervals})")

    gen_profile = ac_generation_kw(config, n_intervals, interval_duration_h)

    model.solar_max_gen_kw = pyo.Param(
        model.T,
        initialize={t: gen_profile[t] for t in range(n_intervals)},
        within=pyo.NonNegativeReals,
        doc="Maximum AC generation available each interval (kW)",
    )

    model.solar_gen_kw = pyo.Var(
        model.T,
        within=pyo.NonNegativeReals,
        initialize={t: gen_profile[t] for t in range(n_intervals)},
        doc="Dispatched AC solar generation (kW)",
    )

    model.solar_curtailed_kw = pyo.Var(
        model.T,
        within=pyo.NonNegativeReals,
        initialize=0.0,
        doc="Curtailed AC solar generation (kW)",
    )

    def _gen_balance_rule(m: Any, t: int) -> Any:
        return m.solar_gen_kw[t] + m.solar_curtailed_kw[t] == m.solar_max_gen_kw[t]

    model.solar_gen_balance = pyo.Constraint(
        model.T,
        rule=_gen_balance_rule,
        doc="Generation balance: dispatched + curtailed == max available",
    )

    model.solar_total_gen_kwh = pyo.Expression(
        expr=sum(model.solar_gen_kw[t] * interval_duration_h for t in model.T),
        doc="Total solar energy dispatched over horizon (kWh)",
    )

    model.solar_curtailment_cost_aud = pyo.Expression(
        expr=sum(
            model.solar_curtailed_kw[t] * interval_duration_h * config.curtailment_cost_aud_per_kwh
            for t in model.T
        ),
        doc="Total curtailment cost over horizon (AUD)",
    )

    logger.debug(
        "Solar PV constraints added: %d intervals, capacity=%.1f kWp, peak_gen=%.1f kW",
        n_intervals,
        config.system_capacity_kwp,
        max(gen_profile) if gen_profile else 0.0,
    )
