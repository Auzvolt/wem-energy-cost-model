"""EV Fleet Smart Charging and V2G (Vehicle-to-Grid) model.

Provides Pydantic configuration, helper utilities, and a Pyomo constraint
builder for fleet-level EV charging optimisation within the WEM dispatch model.

Fleet model assumptions
-----------------------
- All vehicles share a common AC power point (aggregate fleet charger).
- Each vehicle has an arrival time, a departure time, and an initial SoC.
- The optimiser must ensure every vehicle reaches its target SoC before
  departure (hard constraint).
- Optional V2G: when ``enable_v2g=True`` the fleet can discharge back to
  the grid subject to the same power limit.
- SoC trajectory is tracked per dispatch interval for the *fleet aggregate*
  (sum of individual vehicle SoC values).

The constraint builder follows the same interface as ``add_bess_constraints``
in ``app.optimisation.bess``:

    add_ev_fleet_constraints(model, config, *, interval_h=5/60)

The calling engine is responsible for attaching the ``model.T`` set before
invoking this function.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, ValidationError, ValidationInfo, field_validator

if TYPE_CHECKING:
    import pyomo.environ as pyo

logger = logging.getLogger(__name__)

__all__ = [
    "EVConfig",
    "EVFleetConfig",
    "ValidationError",
    "add_ev_fleet_constraints",
]


# ---------------------------------------------------------------------------
# Pydantic configuration schemas
# ---------------------------------------------------------------------------


class EVConfig(BaseModel):
    """Configuration for a single EV in the fleet.

    Interval indices are zero-based integers matching the engine's ``model.T``
    set (i.e. the same ordering as the ``intervals`` list passed to
    ``WEMModel.__init__``).
    """

    vehicle_id: str = Field(..., description="Unique vehicle identifier")
    battery_kwh: float = Field(..., gt=0, description="Usable battery capacity (kWh)")
    max_charge_kw: float = Field(
        ..., gt=0, description="Maximum AC charging power per vehicle (kW)"
    )
    arrival_interval: int = Field(
        ...,
        ge=0,
        description="Interval index at which the vehicle arrives and begins charging",
    )
    departure_interval: int = Field(
        ...,
        ge=0,
        description="Interval index after which the vehicle must have reached target SoC",
    )
    soc_on_arrival_kwh: float = Field(
        ..., ge=0, description="State of charge when the vehicle arrives (kWh)"
    )
    soc_target_kwh: float = Field(
        ..., ge=0, description="Required state of charge on departure (kWh)"
    )

    @field_validator("soc_target_kwh")
    @classmethod
    def target_within_capacity(cls, v: float, info: ValidationInfo) -> float:
        """Ensure SoC target does not exceed battery capacity."""
        cap = (info.data or {}).get("battery_kwh")
        if cap is not None and v > cap:
            raise ValueError(f"soc_target_kwh ({v}) exceeds battery_kwh ({cap})")
        return v

    @field_validator("soc_on_arrival_kwh")
    @classmethod
    def arrival_soc_within_capacity(cls, v: float, info: ValidationInfo) -> float:
        """Ensure arrival SoC does not exceed battery capacity."""
        cap = (info.data or {}).get("battery_kwh")
        if cap is not None and v > cap:
            raise ValueError(f"soc_on_arrival_kwh ({v}) exceeds battery_kwh ({cap})")
        return v

    @field_validator("departure_interval")
    @classmethod
    def departure_after_arrival(cls, v: int, info: ValidationInfo) -> int:
        """Ensure departure is strictly after arrival."""
        arrival = (info.data or {}).get("arrival_interval")
        if arrival is not None and v <= arrival:
            raise ValueError("departure_interval must be strictly greater than arrival_interval")
        return v


class EVFleetConfig(BaseModel):
    """Fleet-level EV charging configuration.

    The fleet shares a single aggregated grid connection point with a combined
    power limit across all simultaneously connected vehicles.
    """

    vehicles: list[EVConfig] = Field(..., min_length=1, description="List of EV configurations")
    fleet_max_charge_kw: float = Field(
        ..., gt=0, description="Maximum aggregate AC import power for the fleet (kW)"
    )
    fleet_max_discharge_kw: float = Field(
        default=0.0,
        ge=0,
        description="Maximum aggregate V2G export power for the fleet (kW). 0 disables V2G.",
    )
    efficiency_rt: float = Field(
        default=0.92,
        ge=0.0,
        le=1.0,
        description="Round-trip charge/discharge efficiency (0-1)",
    )
    enable_v2g: bool = Field(
        default=False,
        description="Enable Vehicle-to-Grid (V2G) discharge capability",
    )

    @field_validator("fleet_max_discharge_kw")
    @classmethod
    def v2g_power_requires_flag(cls, v: float, info: ValidationInfo) -> float:
        """Warn if fleet_max_discharge_kw is set without enable_v2g."""
        enable = (info.data or {}).get("enable_v2g", False)
        if v > 0 and not enable:
            logger.warning(
                "fleet_max_discharge_kw=%.1f set but enable_v2g=False; "
                "discharge will not be allowed by constraints",
                v,
            )
        return v


# ---------------------------------------------------------------------------
# Constraint builder
# ---------------------------------------------------------------------------


def add_ev_fleet_constraints(
    model: pyo.ConcreteModel,
    config: EVFleetConfig,
    *,
    interval_h: float = 5.0 / 60.0,
) -> None:
    """Add EV fleet smart charging variables and constraints to a Pyomo model.

    Expects *model* to already have an ordered integer set ``model.T``.

    Variables added
    ---------------
    ``ev_charge_kw[t]``
        Aggregate fleet charging power at interval *t* (kW, >= 0).
    ``ev_discharge_kw[t]``
        Aggregate fleet V2G discharge power at interval *t* (kW, >= 0).
        Only non-zero when ``config.enable_v2g=True``.
    ``ev_soc_kwh[v, t]``
        Per-vehicle SoC at end of interval *t* (kWh).  Defined only for
        intervals where the vehicle is present (arrival <= t <= departure).
    ``ev_vehicle_charge_kw[v, t]``
        Per-vehicle charge allocation (kW) at interval *t*.

    Constraints added
    -----------------
    ``ev_fleet_charge_limit[t]``
        Aggregate charge power <= ``fleet_max_charge_kw``.
    ``ev_fleet_discharge_limit[t]``
        Aggregate discharge power <= ``fleet_max_discharge_kw`` (or 0 if V2G
        disabled).
    ``ev_fleet_aggregate[t]``
        Aggregate charge equals sum of per-vehicle allocations.
    ``ev_soc_balance[v, t]``
        Per-vehicle SoC continuity (charge proportionally allocated).
    ``ev_departure_soc[v]``
        Mandatory SoC target at departure for each vehicle.
    ``ev_vehicle_charge_limit[v, t]``
        Per-vehicle share of charge power <= ``max_charge_kw``.

    Args:
        model: Pyomo ``ConcreteModel`` with set ``T`` already populated.
        config: EV fleet configuration.
        interval_h: Duration of each dispatch interval in hours (default 5 min).
    """
    import pyomo.environ as pyo  # local import -- optional dependency

    T = sorted(model.T)
    n_vehicles = len(config.vehicles)
    eta_one_way = config.efficiency_rt**0.5  # split round-trip symmetrically

    # Vehicle indices (0-based, matching config.vehicles list order)
    V = list(range(n_vehicles))
    veh = config.vehicles

    # ------------------------------------------------------------------
    # Fleet-level aggregate decision variables
    # ------------------------------------------------------------------

    model.ev_charge_kw = pyo.Var(model.T, domain=pyo.NonNegativeReals, initialize=0.0)
    model.ev_discharge_kw = pyo.Var(model.T, domain=pyo.NonNegativeReals, initialize=0.0)

    # ------------------------------------------------------------------
    # Per-vehicle SoC variables (indexed by vehicle index x T)
    # ------------------------------------------------------------------

    # Determine presence set: (v, t) where arrival_interval <= t <= departure_interval
    presence = set()
    for v_idx, v_cfg in enumerate(veh):
        for t in T:
            if v_cfg.arrival_interval <= t <= v_cfg.departure_interval:
                presence.add((v_idx, t))

    model.ev_vehicle_set = pyo.Set(initialize=V)
    model.ev_presence_set = pyo.Set(
        initialize=sorted(presence),
        within=model.ev_vehicle_set * model.T,
        dimen=2,
    )

    def _soc_bounds(m: pyo.ConcreteModel, v_idx: int, t: int) -> tuple[float, float]:
        return (0.0, veh[v_idx].battery_kwh)

    model.ev_soc_kwh = pyo.Var(
        model.ev_presence_set,
        domain=pyo.NonNegativeReals,
        bounds=_soc_bounds,
        initialize=lambda m, v_idx, t: veh[v_idx].soc_on_arrival_kwh,
    )

    # Per-vehicle charge allocation variables (kW per vehicle per interval)
    model.ev_vehicle_charge_kw = pyo.Var(
        model.ev_presence_set,
        domain=pyo.NonNegativeReals,
        initialize=0.0,
    )

    # ------------------------------------------------------------------
    # Fleet power limits
    # ------------------------------------------------------------------

    model.ev_fleet_charge_limit = pyo.Constraint(
        model.T,
        rule=lambda m, t: m.ev_charge_kw[t] <= config.fleet_max_charge_kw,
    )

    max_discharge = config.fleet_max_discharge_kw if config.enable_v2g else 0.0
    model.ev_fleet_discharge_limit = pyo.Constraint(
        model.T,
        rule=lambda m, t: m.ev_discharge_kw[t] <= max_discharge,
    )

    # ------------------------------------------------------------------
    # Fleet aggregate = sum of per-vehicle charges
    # ------------------------------------------------------------------

    def _fleet_aggregate_rule(m: pyo.ConcreteModel, t: int) -> pyo.Expression:
        """Sum per-vehicle charge allocation must equal fleet aggregate."""
        vehicle_charges = [
            m.ev_vehicle_charge_kw[v_idx, t] for v_idx in V if (v_idx, t) in presence
        ]
        if not vehicle_charges:
            return m.ev_charge_kw[t] == 0.0
        return m.ev_charge_kw[t] == sum(vehicle_charges)

    model.ev_fleet_aggregate = pyo.Constraint(model.T, rule=_fleet_aggregate_rule)

    # ------------------------------------------------------------------
    # Per-vehicle power limit
    # ------------------------------------------------------------------

    model.ev_vehicle_charge_limit = pyo.Constraint(
        model.ev_presence_set,
        rule=lambda m, v_idx, t: m.ev_vehicle_charge_kw[v_idx, t] <= veh[v_idx].max_charge_kw,
    )

    # ------------------------------------------------------------------
    # Per-vehicle SoC balance
    # ------------------------------------------------------------------

    def _soc_balance_rule(m: pyo.ConcreteModel, v_idx: int, t: int) -> pyo.Expression:
        v_cfg = veh[v_idx]
        if t == v_cfg.arrival_interval:
            soc_prev = v_cfg.soc_on_arrival_kwh
        else:
            soc_prev = m.ev_soc_kwh[v_idx, t - 1]

        return (
            m.ev_soc_kwh[v_idx, t]
            == soc_prev + m.ev_vehicle_charge_kw[v_idx, t] * eta_one_way * interval_h
        )

    model.ev_soc_balance = pyo.Constraint(model.ev_presence_set, rule=_soc_balance_rule)

    # ------------------------------------------------------------------
    # Departure SoC requirement (hard constraint)
    # ------------------------------------------------------------------

    def _departure_soc_rule(m: pyo.ConcreteModel, v_idx: int) -> pyo.Expression:
        v_cfg = veh[v_idx]
        return m.ev_soc_kwh[v_idx, v_cfg.departure_interval] >= v_cfg.soc_target_kwh

    model.ev_departure_soc = pyo.Constraint(model.ev_vehicle_set, rule=_departure_soc_rule)

    logger.debug(
        "EV fleet constraints added: %d vehicles, fleet_max_charge=%.1f kW, "
        "v2g=%s (max_discharge=%.1f kW), intervals=%d",
        n_vehicles,
        config.fleet_max_charge_kw,
        config.enable_v2g,
        max_discharge,
        len(T),
    )
