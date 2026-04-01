"""Diesel / gas genset (generator set) asset model.

Models a reciprocating internal-combustion generator within the WEM
co-optimisation engine.

Features
--------
- Pydantic ``GensetConfig`` capturing nameplate capacity, heat rate,
  fuel cost, minimum loading, ramp limits, and start/stop costs.
- ``fuel_cost_aud`` helper that converts a dispatch MW value to an AUD
  fuel cost for a given interval duration.
- Pyomo constraint builder ``add_genset_constraints`` that injects the
  genset dispatch variable and operating constraints into a
  ``ConcreteModel`` prepared by the base engine.

Usage example::

    from app.optimisation.genset import GensetConfig, add_genset_constraints

    cfg = GensetConfig(
        capacity_kw=500.0,
        heat_rate_gj_per_mwh=10.5,
        fuel_cost_aud_per_gj=8.0,
    )
    add_genset_constraints(model, cfg, n_intervals=48, interval_duration_h=0.5)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, model_validator

if TYPE_CHECKING:
    import pyomo.environ as pyo

logger = logging.getLogger(__name__)

__all__ = [
    "GensetConfig",
    "fuel_cost_aud",
    "add_genset_constraints",
]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class GensetConfig(BaseModel):
    """Configuration parameters for a diesel/gas genset asset.

    Attributes:
        capacity_kw: Nameplate generating capacity (kW).  Must be positive.
        heat_rate_gj_per_mwh: Gross heat rate at full load (GJ/MWh).
            Typical reciprocating diesel: 10–12 GJ/MWh.
        fuel_cost_aud_per_gj: Delivered fuel cost (AUD/GJ).
        min_loading_pct: Minimum stable generation as a fraction of nameplate
            (0–1).  Below this level the genset is considered off.  Default 0.3
            (30 % of capacity).
        ramp_rate_kw_per_min: Maximum ramp rate (kW/min) for both up and down
            ramps.  Set to ``None`` to disable ramp constraints.
        start_cost_aud: Fixed cost incurred when the genset transitions from
            off → on (AUD).  Default 0.
        stop_cost_aud: Fixed cost incurred when the genset transitions from
            on → off (AUD).  Default 0.
        availability_factor: Fraction of time the genset is available for
            dispatch (0–1).  Effective capacity = capacity_kw *
            availability_factor.  Default 1.0.
    """

    capacity_kw: float = Field(..., gt=0, description="Nameplate generating capacity (kW)")
    heat_rate_gj_per_mwh: float = Field(
        ...,
        gt=0,
        description="Gross heat rate at full load (GJ/MWh)",
    )
    fuel_cost_aud_per_gj: float = Field(
        ...,
        ge=0,
        description="Delivered fuel cost (AUD/GJ)",
    )
    min_loading_pct: float = Field(
        default=0.30,
        ge=0.0,
        le=1.0,
        description="Minimum stable loading fraction (0–1)",
    )
    ramp_rate_kw_per_min: float | None = Field(
        default=None,
        gt=0,
        description="Max ramp rate (kW/min).  None disables ramp constraints.",
    )
    start_cost_aud: float = Field(
        default=0.0,
        ge=0,
        description="Fixed start cost (AUD)",
    )
    stop_cost_aud: float = Field(
        default=0.0,
        ge=0,
        description="Fixed stop cost (AUD)",
    )
    availability_factor: float = Field(
        default=1.0,
        gt=0.0,
        le=1.0,
        description="Availability factor (0–1)",
    )

    @model_validator(mode="after")
    def _validate_min_loading(self) -> GensetConfig:
        if self.min_loading_pct >= 1.0:
            raise ValueError("min_loading_pct must be < 1.0 (cannot require full load at minimum)")
        return self

    # ------------------------------------------------------------------
    # Derived properties
    # ------------------------------------------------------------------

    @property
    def effective_capacity_kw(self) -> float:
        """Nameplate capacity derated by availability factor (kW)."""
        return self.capacity_kw * self.availability_factor

    @property
    def min_dispatch_kw(self) -> float:
        """Minimum dispatch power when online (kW)."""
        return self.effective_capacity_kw * self.min_loading_pct

    @property
    def variable_cost_aud_per_kwh(self) -> float:
        """Variable fuel cost at full load (AUD/kWh).

        = heat_rate (GJ/MWh) * fuel_cost (AUD/GJ) / 1000 (kWh per MWh)
        """
        return self.heat_rate_gj_per_mwh * self.fuel_cost_aud_per_gj / 1_000.0


# ---------------------------------------------------------------------------
# Financial helpers
# ---------------------------------------------------------------------------


def fuel_cost_aud(
    config: GensetConfig,
    dispatch_kw: float,
    interval_duration_h: float = 0.5,
) -> float:
    """Calculate the fuel cost for a single dispatch interval.

    Uses the constant heat-rate approximation::

        fuel_cost = dispatch_kW * interval_h * heat_rate_GJ/MWh * fuel_cost_AUD/GJ
                    / 1000  (convert kW → MW)

    Args:
        config: Genset configuration.
        dispatch_kw: Dispatch level for the interval (kW).  Must be >= 0.
        interval_duration_h: Duration of the interval in hours.  Default 0.5 h
            (WEM 30-minute pre-reform interval).

    Returns:
        Fuel cost in AUD for the interval.

    Raises:
        ValueError: If dispatch_kw < 0 or interval_duration_h <= 0.
    """
    if dispatch_kw < 0:
        raise ValueError(f"dispatch_kw must be >= 0, got {dispatch_kw}")
    if interval_duration_h <= 0:
        raise ValueError(f"interval_duration_h must be > 0, got {interval_duration_h}")
    dispatch_mwh = dispatch_kw * interval_duration_h / 1_000.0
    return dispatch_mwh * config.heat_rate_gj_per_mwh * config.fuel_cost_aud_per_gj


# ---------------------------------------------------------------------------
# Pyomo constraint builder
# ---------------------------------------------------------------------------


def add_genset_constraints(
    model: pyo.ConcreteModel,
    config: GensetConfig,
    n_intervals: int,
    interval_duration_h: float = 0.5,
    name_prefix: str = "genset",
) -> dict[str, Any]:
    """Inject genset dispatch variables and constraints into a Pyomo model.

    Variables added
    ~~~~~~~~~~~~~~~
    ``{name_prefix}_dispatch[t]`` : Non-negative real — generation output (kW)
        per interval *t*.  Bounded ``[0, effective_capacity_kw]``.

    ``{name_prefix}_online[t]`` : Binary — 1 if the genset is online in
        interval *t*, 0 if offline.

    ``{name_prefix}_start[t]`` : Binary — 1 if the genset starts up in
        interval *t*.

    ``{name_prefix}_stop[t]`` : Binary — 1 if the genset shuts down in
        interval *t*.

    Constraints added
    ~~~~~~~~~~~~~~~~~
    - Minimum loading: dispatch ≥ min_dispatch_kw * online
    - Maximum capacity: dispatch ≤ effective_capacity_kw * online
    - Ramp up / ramp down limits (if ``ramp_rate_kw_per_min`` is set)
    - Logical start/stop: start[t] - stop[t] = online[t] - online[t-1]

    Returns:
        Dict with keys ``variables`` and ``constraints`` listing added
        Pyomo component names for introspection.

    Args:
        model: Pyomo ``ConcreteModel`` to augment.
        config: Genset configuration.
        n_intervals: Number of dispatch intervals.
        interval_duration_h: Duration of each interval in hours.
        name_prefix: Prefix for all added Pyomo components.

    Raises:
        ImportError: If ``pyomo`` is not installed.
        ValueError: If n_intervals < 1.
    """
    try:
        import pyomo.environ as pyo  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError("pyomo is required to use add_genset_constraints") from exc

    if n_intervals < 1:
        raise ValueError(f"n_intervals must be >= 1, got {n_intervals}")

    T = range(n_intervals)
    cap = config.effective_capacity_kw
    min_load = config.min_dispatch_kw
    ramp_max = (
        config.ramp_rate_kw_per_min * interval_duration_h * 60.0
        if config.ramp_rate_kw_per_min is not None
        else None
    )

    dispatch_name = f"{name_prefix}_dispatch"
    online_name = f"{name_prefix}_online"
    start_name = f"{name_prefix}_start"
    stop_name = f"{name_prefix}_stop"

    # ------------------------------------------------------------------
    # Variables
    # ------------------------------------------------------------------
    setattr(
        model,
        dispatch_name,
        pyo.Var(T, domain=pyo.NonNegativeReals, bounds=(0.0, cap)),
    )
    setattr(model, online_name, pyo.Var(T, domain=pyo.Binary))
    setattr(model, start_name, pyo.Var(T, domain=pyo.Binary))
    setattr(model, stop_name, pyo.Var(T, domain=pyo.Binary))

    dispatch = getattr(model, dispatch_name)
    online = getattr(model, online_name)
    start = getattr(model, start_name)
    stop = getattr(model, stop_name)

    constraint_names: list[str] = []
    variable_names = [dispatch_name, online_name, start_name, stop_name]

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------

    # Minimum loading
    min_load_name = f"{name_prefix}_min_load"
    setattr(
        model,
        min_load_name,
        pyo.Constraint(T, rule=lambda m, t: dispatch[t] >= min_load * online[t]),
    )
    constraint_names.append(min_load_name)

    # Maximum capacity
    max_cap_name = f"{name_prefix}_max_cap"
    setattr(
        model,
        max_cap_name,
        pyo.Constraint(T, rule=lambda m, t: dispatch[t] <= cap * online[t]),
    )
    constraint_names.append(max_cap_name)

    # Logical start/stop: start[t] - stop[t] = online[t] - online[t-1]
    # At t=0 assume genset was offline (online[-1] = 0)
    def _start_stop_rule(m: pyo.ConcreteModel, t: int) -> Any:
        prev_online = online[t - 1] if t > 0 else 0
        return start[t] - stop[t] == online[t] - prev_online

    logical_name = f"{name_prefix}_logical"
    setattr(model, logical_name, pyo.Constraint(T, rule=_start_stop_rule))
    constraint_names.append(logical_name)

    # Ramp rate constraints (optional)
    if ramp_max is not None:
        ramp_up_name = f"{name_prefix}_ramp_up"
        ramp_dn_name = f"{name_prefix}_ramp_dn"

        setattr(
            model,
            ramp_up_name,
            pyo.Constraint(
                range(1, n_intervals),
                rule=lambda m, t: dispatch[t] - dispatch[t - 1] <= ramp_max,
            ),
        )
        setattr(
            model,
            ramp_dn_name,
            pyo.Constraint(
                range(1, n_intervals),
                rule=lambda m, t: dispatch[t - 1] - dispatch[t] <= ramp_max,
            ),
        )
        constraint_names.extend([ramp_up_name, ramp_dn_name])

    logger.info(
        "Added genset constraints: %d variables, %d constraint groups (prefix=%s, cap=%.1f kW)",
        len(variable_names),
        len(constraint_names),
        name_prefix,
        cap,
    )

    return {
        "variables": variable_names,
        "constraints": constraint_names,
    }
