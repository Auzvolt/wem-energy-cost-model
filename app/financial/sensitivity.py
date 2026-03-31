"""Sensitivity analysis engine for WEM energy cost modelling.

Produces tornado-chart data by sweeping individual financial parameters
while holding all others at their base values.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel, Field


class SensitivityParam(BaseModel):
    """Definition of a single sensitivity parameter and its sweep range."""

    name: str = Field(description="Human-readable parameter name")
    base_value: float = Field(description="Base-case value")
    low_factor: float = Field(
        description=(
            "Multiplier applied to base_value to get the low scenario. "
            "For additive sweep (e.g. discount rate ±2pp) set "
            "additive_delta to override multiplicative behaviour."
        )
    )
    high_factor: float = Field(
        description="Multiplier applied to base_value to get the high scenario."
    )
    additive_delta: float | None = Field(
        default=None,
        description=(
            "If set, low_value = base_value - additive_delta and "
            "high_value = base_value + additive_delta, ignoring factors."
        ),
    )

    @property
    def low_value(self) -> float:
        """Return the low-scenario parameter value."""
        if self.additive_delta is not None:
            return self.base_value - self.additive_delta
        return self.base_value * self.low_factor

    @property
    def high_value(self) -> float:
        """Return the high-scenario parameter value."""
        if self.additive_delta is not None:
            return self.base_value + self.additive_delta
        return self.base_value * self.high_factor


@dataclass
class SensitivityRow:
    """Result row for a single parameter sweep."""

    parameter: str
    base_value: float
    low_value: float
    high_value: float
    npv_low: float
    npv_high: float

    @property
    def npv_delta(self) -> float:
        """NPV swing = high NPV minus low NPV."""
        return self.npv_high - self.npv_low


@dataclass
class SensitivityResult:
    """Aggregated sensitivity analysis result (tornado chart data)."""

    base_npv: float
    rows: list[SensitivityRow] = field(default_factory=list)


# Default parameters representing typical WEM project sensitivities
DEFAULT_SENSITIVITY_PARAMS: list[SensitivityParam] = [
    SensitivityParam(
        name="capex_aud_kw",
        base_value=1_000.0,
        low_factor=0.70,
        high_factor=1.30,
    ),
    SensitivityParam(
        name="energy_price_aud_mwh",
        base_value=80.0,
        low_factor=0.60,
        high_factor=1.40,
    ),
    SensitivityParam(
        name="fcess_price_aud_mw",
        base_value=5_000.0,
        low_factor=0.50,
        high_factor=1.50,
    ),
    SensitivityParam(
        name="discount_rate",
        base_value=0.08,
        low_factor=1.0,  # ignored when additive_delta is set
        high_factor=1.0,  # ignored when additive_delta is set
        additive_delta=0.02,
    ),
    SensitivityParam(
        name="capacity_factor",
        base_value=0.25,
        low_factor=0.80,
        high_factor=1.20,
    ),
]


def run_sensitivity(
    cashflow_fn: Callable[[SensitivityParam, float], float],
    base_npv: float,
    params: list[SensitivityParam] | None = None,
) -> SensitivityResult:
    """Run a one-at-a-time sensitivity analysis (tornado chart).

    For each parameter in ``params``, the analysis sweeps the parameter
    from its low to high scenario value (holding all others at base),
    calling ``cashflow_fn`` to obtain the resulting NPV at each end.

    Args:
        cashflow_fn: Callable ``(param, value) -> npv``.  The caller is
            responsible for re-running their model with the given
            parameter changed to ``value`` and returning the resulting NPV.
        base_npv: The base-case NPV (pre-computed by the caller).
        params: Parameters to sweep.  Defaults to
            ``DEFAULT_SENSITIVITY_PARAMS``.

    Returns:
        :class:`SensitivityResult` with rows sorted by
        ``abs(npv_delta)`` descending (largest swing first — widest bar
        at the top of the tornado chart).
    """
    if params is None:
        params = DEFAULT_SENSITIVITY_PARAMS

    rows: list[SensitivityRow] = []
    for p in params:
        npv_low = cashflow_fn(p, p.low_value)
        npv_high = cashflow_fn(p, p.high_value)
        rows.append(
            SensitivityRow(
                parameter=p.name,
                base_value=p.base_value,
                low_value=p.low_value,
                high_value=p.high_value,
                npv_low=npv_low,
                npv_high=npv_high,
            )
        )

    # Sort by absolute NPV swing — widest bar first (tornado convention)
    rows.sort(key=lambda r: abs(r.npv_delta), reverse=True)

    return SensitivityResult(base_npv=base_npv, rows=rows)
