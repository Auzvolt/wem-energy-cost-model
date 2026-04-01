"""Load flexibility (demand-side management) asset model.

Models a shiftable or curtailable load within the WEM co-optimisation engine.

Features
--------
- Shiftable loads: total consumption must be delivered within a window, but
  the instantaneous power can be moved across intervals to exploit price valleys.
- Curtailable loads: a fraction of load can be permanently shed in exchange for
  a curtailment value (e.g. demand-response payment or avoided cost).
- Pyomo constraint builder that injects load-flexibility variables and
  constraints into a ``ConcreteModel`` already prepared by the base engine.

Usage example::

    from app.optimisation.load_flex import LoadFlexConfig, add_load_flex_constraints

    cfg = LoadFlexConfig(
        baseline_kw=[50.0] * 48,
        max_shift_pct=0.30,
        max_curtail_pct=0.20,
        curtail_value_per_kwh=0.05,
    )
    add_load_flex_constraints(model, cfg, interval_h=0.5)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, model_validator

if TYPE_CHECKING:
    import pyomo.environ as pyo

logger = logging.getLogger(__name__)

__all__ = [
    "LoadFlexConfig",
    "LoadFlexResult",
    "add_load_flex_constraints",
    "extract_load_flex_results",
]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class LoadFlexConfig(BaseModel):
    """Configuration for a shiftable/curtailable load asset.

    Attributes:
        baseline_kw: Baseline load profile (kW per interval).  Must be
            non-negative.  Length determines the number of optimisation
            intervals if the model has not already set them.
        max_shift_pct: Maximum fraction of baseline load that can be shifted
            to another interval within the same day (0–1).  Default 0.25.
        max_curtail_pct: Maximum fraction of baseline load that can be
            permanently curtailed at each interval (0–1).  Default 0.0
            (no curtailment allowed).
        curtail_value_per_kwh: Revenue or avoided-cost value for curtailing
            1 kWh of load (AUD/kWh).  Used in the objective contribution.
            Default 0.0.
        shift_window: Number of consecutive intervals over which the shifted
            energy must be redelivered (0 = whole-day balancing, i.e. total
            delivered == total baseline over all intervals).  Default 0.
    """

    baseline_kw: list[float] = Field(..., min_length=1)
    max_shift_pct: float = Field(default=0.25, ge=0.0, le=1.0)
    max_curtail_pct: float = Field(default=0.0, ge=0.0, le=1.0)
    curtail_value_per_kwh: float = Field(default=0.0, ge=0.0)
    shift_window: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def baseline_non_negative(self) -> LoadFlexConfig:
        """Ensure all baseline load values are non-negative."""
        if any(v < 0 for v in self.baseline_kw):
            raise ValueError("All baseline_kw values must be non-negative.")
        return self


# ---------------------------------------------------------------------------
# Results dataclass
# ---------------------------------------------------------------------------


class LoadFlexResult:
    """Extracted results for a load-flexibility asset post-solve.

    Attributes:
        scheduled_kw: Optimised load profile after shifting/curtailment (kW).
        shifted_kw: Net shift applied at each interval (positive = load added,
            negative = load removed).  Derived as scheduled_kw - baseline_kw
            + curtailed_kw.
        curtailed_kw: Curtailed load at each interval (kW).
        total_curtailed_kwh: Total energy curtailed over the horizon (kWh).
        total_shifted_kwh: Total energy shifted (sum of positive deviations)
            over the horizon (kWh).
        curtail_revenue: Total curtailment revenue / avoided cost (AUD).
    """

    def __init__(
        self,
        scheduled_kw: list[float],
        curtailed_kw: list[float],
        interval_h: float,
    ) -> None:
        self.scheduled_kw = scheduled_kw
        self.curtailed_kw = curtailed_kw
        self.interval_h = interval_h

        self.total_curtailed_kwh = sum(curtailed_kw) * interval_h
        # Positive deviations from zero in shifted component
        self.total_shifted_kwh = sum(max(v, 0.0) for v in scheduled_kw) * interval_h
        self.curtail_revenue: float = 0.0  # set by caller with curtail_value_per_kwh

    def __repr__(self) -> str:
        return (
            f"LoadFlexResult(total_curtailed_kwh={self.total_curtailed_kwh:.2f}, "
            f"total_shifted_kwh={self.total_shifted_kwh:.2f}, "
            f"curtail_revenue={self.curtail_revenue:.2f})"
        )


# ---------------------------------------------------------------------------
# Pyomo constraint builder
# ---------------------------------------------------------------------------


def add_load_flex_constraints(
    model: pyo.ConcreteModel,
    config: LoadFlexConfig,
    *,
    interval_h: float = 5.0 / 60.0,
) -> None:
    """Add load-flexibility decision variables and constraints to a Pyomo model.

    Expects *model* to already have an ordered integer set ``model.T`` whose
    indices correspond positionally to ``config.baseline_kw``.

    Variables added (prefixed ``lf_``)::

        lf_scheduled_kw[t]  -- net load drawn in interval t (kW, >= 0)
        lf_curtailed_kw[t]  -- load curtailed in interval t (kW, >= 0)
        lf_shift_pos[t]     -- upward shift applied in interval t (kW, >= 0)
        lf_shift_neg[t]     -- downward shift applied in interval t (kW, >= 0)

    Constraints added::

        lf_schedule_balance[t]   -- scheduled = baseline − curtailed + shift_pos − shift_neg
        lf_shift_pos_limit[t]    -- shift_pos <= max_shift_pct * baseline
        lf_shift_neg_limit[t]    -- shift_neg <= max_shift_pct * baseline
        lf_curtail_limit[t]      -- curtailed <= max_curtail_pct * baseline
        lf_scheduled_nonneg[t]   -- scheduled_kw >= 0
        lf_energy_balance        -- total delivered == total baseline (whole-day or windowed)

    Objective contribution (added to ``model.obj_terms`` list if it exists)::

        curtailment revenue: sum_t curtailed_kw[t] * curtail_value_per_kwh * interval_h

    Args:
        model: Pyomo ConcreteModel with set T already populated.
        config: Load flexibility configuration.
        interval_h: Length of each dispatch interval in hours (default 5 min).

    Raises:
        ValueError: If len(config.baseline_kw) does not match len(model.T).
    """
    import pyomo.environ as pyo  # local import — optional dependency

    t_indices: list[int] = sorted(model.T)
    n = len(t_indices)
    if n != len(config.baseline_kw):
        raise ValueError(
            f"model.T has {n} elements but config.baseline_kw has "
            f"{len(config.baseline_kw)} elements."
        )

    baseline: dict[int, float] = {
        t: config.baseline_kw[i] for i, t in enumerate(t_indices)
    }

    # ------------------------------------------------------------------
    # Decision variables
    # ------------------------------------------------------------------
    model.lf_scheduled_kw = pyo.Var(model.T, domain=pyo.NonNegativeReals)
    model.lf_curtailed_kw = pyo.Var(model.T, domain=pyo.NonNegativeReals)
    model.lf_shift_pos = pyo.Var(model.T, domain=pyo.NonNegativeReals)
    model.lf_shift_neg = pyo.Var(model.T, domain=pyo.NonNegativeReals)

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------

    # scheduled = baseline − curtailed + shift_pos − shift_neg
    def _schedule_balance(m: Any, t: int) -> Any:
        return m.lf_scheduled_kw[t] == (
            baseline[t]
            - m.lf_curtailed_kw[t]
            + m.lf_shift_pos[t]
            - m.lf_shift_neg[t]
        )

    model.lf_schedule_balance = pyo.Constraint(model.T, rule=_schedule_balance)

    # shift limits
    def _shift_pos_limit(m: Any, t: int) -> Any:
        return m.lf_shift_pos[t] <= config.max_shift_pct * baseline[t]

    def _shift_neg_limit(m: Any, t: int) -> Any:
        return m.lf_shift_neg[t] <= config.max_shift_pct * baseline[t]

    model.lf_shift_pos_limit = pyo.Constraint(model.T, rule=_shift_pos_limit)
    model.lf_shift_neg_limit = pyo.Constraint(model.T, rule=_shift_neg_limit)

    # curtailment limit
    def _curtail_limit(m: Any, t: int) -> Any:
        return m.lf_curtailed_kw[t] <= config.max_curtail_pct * baseline[t]

    model.lf_curtail_limit = pyo.Constraint(model.T, rule=_curtail_limit)

    # energy balance over horizon or window
    if config.shift_window == 0:
        # Whole-day: total shifted energy sums to zero
        model.lf_energy_balance = pyo.Constraint(
            expr=sum(
                model.lf_shift_pos[t] - model.lf_shift_neg[t] for t in model.T
            )
            == 0.0
        )
    else:
        # Windowed: rolling sum of net shift over shift_window intervals == 0
        def _windowed_balance(m: Any, t: int) -> Any:
            window_end = min(t + config.shift_window - 1, t_indices[-1])
            window = [ti for ti in t_indices if t <= ti <= window_end]
            net = sum(m.lf_shift_pos[ti] - m.lf_shift_neg[ti] for ti in window)
            return net == 0.0

        # Only apply at window start indices to avoid redundancy
        window_starts = t_indices[:: config.shift_window]
        model.lf_window_starts = pyo.Set(initialize=window_starts)
        model.lf_energy_balance = pyo.Constraint(
            model.lf_window_starts, rule=_windowed_balance
        )

    # ------------------------------------------------------------------
    # Objective contribution
    # ------------------------------------------------------------------
    if config.curtail_value_per_kwh > 0:
        curtail_obj = sum(
            model.lf_curtailed_kw[t] * config.curtail_value_per_kwh * interval_h
            for t in model.T
        )
        # Append to obj_terms list if present (engine convention)
        if hasattr(model, "obj_terms"):
            model.obj_terms.append(curtail_obj)


# ---------------------------------------------------------------------------
# Result extraction
# ---------------------------------------------------------------------------


def extract_load_flex_results(
    model: pyo.ConcreteModel,
    config: LoadFlexConfig,
    *,
    interval_h: float = 5.0 / 60.0,
) -> LoadFlexResult:
    """Extract load-flexibility results from a solved Pyomo model.

    Args:
        model: Solved Pyomo ConcreteModel.
        config: Load flexibility configuration used to build the model.
        interval_h: Interval duration in hours.

    Returns:
        :class:`LoadFlexResult` with scheduled and curtailed profiles.
    """
    import pyomo.environ as pyo  # local import — optional dependency

    t_indices: list[int] = sorted(model.T)
    scheduled = [float(pyo.value(model.lf_scheduled_kw[t])) for t in t_indices]
    curtailed = [float(pyo.value(model.lf_curtailed_kw[t])) for t in t_indices]

    result = LoadFlexResult(scheduled, curtailed, interval_h)
    result.curtail_revenue = result.total_curtailed_kwh * config.curtail_value_per_kwh
    return result
