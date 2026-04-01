"""Monte Carlo uncertainty simulation for WEM energy cost modelling.

Supports two operating modes:

1. **SAA mode** (recommended, implements issue #27 AC):
   Pass an ``engine_factory`` callable.  For each sampled scenario the factory
   is called with the scenario's price trace as a ``dict[int, float]``
   (interval index → $/MWh), builds and solves the LP/MILP model, and returns
   a ``SolveResult``.  The ``objective_value`` of each solve is used as that
   scenario's annual revenue.

2. **Simple mode** (backward-compatible fallback):
   No ``engine_factory`` supplied.  Annual revenue is estimated by scaling
   ``base_revenue_per_mw × capacity_mw`` by the ratio of the scenario mean
   energy price to the base distribution mean.  No LP solve is performed.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
import numpy_financial as npf
from pydantic import BaseModel, Field

from app.models.uncertainty import (
    AnyDistribution,
    NormalDistribution,
    UncertaintyConfig,
    UniformDistribution,
)
from app.optimisation.engine import SolveResult

__all__ = [
    "ScenarioResult",
    "MonteCarloResults",
    "generate_price_traces",
    "run_monte_carlo",
]

# WEM energy price bounds ($/MWh)
ENERGY_PRICE_FLOOR: float = -1000.0
ENERGY_PRICE_CAP: float = 1000.0

_PROJECT_LIFE_YEARS: int = 20
_DISCOUNT_RATE: float = 0.08


class ScenarioResult(BaseModel):
    """Result for a single Monte Carlo scenario."""

    capacity_mw: float = Field(description="Asset capacity (MW)")
    npv: float = Field(description="Net present value ($)")
    annual_revenue: float = Field(description="Annual revenue ($)")
    irr: float | None = Field(default=None, description="Internal rate of return")


class MonteCarloResults(BaseModel):
    """Aggregated Monte Carlo simulation results."""

    n_scenarios: int = Field(description="Number of scenarios simulated")
    p10_npv: float = Field(description="P10 NPV ($)")
    p50_npv: float = Field(description="P50 (median) NPV ($)")
    p90_npv: float = Field(description="P90 NPV ($)")
    p10_revenue: float = Field(description="P10 annual revenue ($)")
    p50_revenue: float = Field(description="P50 (median) annual revenue ($)")
    p90_revenue: float = Field(description="P90 annual revenue ($)")
    scenario_results: list[ScenarioResult] = Field(
        default_factory=list,
        description="Full per-scenario result list",
    )


def _sample_distribution(dist: AnyDistribution, size: int, rng: np.random.Generator) -> np.ndarray:
    """Sample *size* values from *dist* using *rng*."""
    if isinstance(dist, NormalDistribution):
        return rng.normal(loc=dist.mean, scale=dist.std, size=size)
    if isinstance(dist, UniformDistribution):
        return rng.uniform(low=dist.low, high=dist.high, size=size)
    raise TypeError(f"Unknown distribution type: {type(dist)}")


def generate_price_traces(
    config: UncertaintyConfig,
    n_intervals: int = 8760,
) -> list[dict[str, np.ndarray]]:
    """Generate N independent price traces for each configured product.

    Parameters
    ----------
    config:
        Uncertainty configuration with distributions per WEM product code.
    n_intervals:
        Number of dispatch intervals per scenario (default 8760 = 1 year hourly).

    Returns
    -------
    list[dict[str, np.ndarray]]
        List of N scenario dicts, each mapping product code → price array.
        ENERGY prices are clamped to [ENERGY_PRICE_FLOOR, ENERGY_PRICE_CAP].
    """
    rng = np.random.default_rng(config.seed)
    traces: list[dict[str, np.ndarray]] = []
    for _ in range(config.n_scenarios):
        trace: dict[str, np.ndarray] = {}
        for product, dist in config.distributions.items():
            samples = _sample_distribution(dist, n_intervals, rng)
            if product == "ENERGY":
                samples = np.clip(samples, ENERGY_PRICE_FLOOR, ENERGY_PRICE_CAP)
            trace[product] = samples
        traces.append(trace)
    return traces


def _compute_npv(annual_revenue: float, capex_total: float) -> float:
    """Compute NPV over _PROJECT_LIFE_YEARS at _DISCOUNT_RATE.

    Parameters
    ----------
    annual_revenue:
        Constant annual revenue ($/year).
    capex_total:
        Up-front capital expenditure ($, negative cash flow at t=0).

    Returns
    -------
    float
        Net present value ($).
    """
    cash_flows = [-capex_total] + [annual_revenue] * _PROJECT_LIFE_YEARS
    return float(npf.npv(_DISCOUNT_RATE, cash_flows))


def _compute_irr(annual_revenue: float, capex_total: float) -> float | None:
    """Compute IRR over _PROJECT_LIFE_YEARS.

    Returns None if IRR cannot be computed (e.g. all-negative cash flows).
    """
    cash_flows = [-capex_total] + [annual_revenue] * _PROJECT_LIFE_YEARS
    try:
        result = npf.irr(cash_flows)
        if result is None or math.isnan(result):
            return None
        return float(result)
    except Exception:
        return None


def run_monte_carlo(
    base_revenue_per_mw: float,
    capacity_mw: float,
    capex_total: float,
    uncertainty_config: UncertaintyConfig,
    n_intervals: int = 8760,
    engine_factory: Callable[[dict[int, float]], SolveResult] | None = None,
) -> MonteCarloResults:
    """Run a Monte Carlo simulation and return percentile statistics.

    **SAA mode** (when ``engine_factory`` is provided):
    For each scenario the sampled ENERGY price trace is converted to a
    ``dict[int, float]`` and passed to ``engine_factory``.  The factory must
    build, solve, and return a ``SolveResult``; its ``objective_value`` is used
    as the annual revenue for that scenario.  This implements the
    Sample Average Approximation (SAA) method required by issue #27.

    **Simple mode** (``engine_factory=None``):
    Annual revenue is estimated by scaling ``base_revenue_per_mw × capacity_mw``
    by the ratio of the scenario mean ENERGY price to the base distribution mean.
    No LP solve is performed.  Useful for quick sensitivity analysis or tests
    where an LP solver is not available.

    Parameters
    ----------
    base_revenue_per_mw:
        Base-case annual revenue per MW of capacity ($/MW/year).
        Used in simple mode and to set ``capacity_mw`` in SAA mode results.
    capacity_mw:
        Asset capacity (MW).
    capex_total:
        Total capital expenditure at t=0 ($).
    uncertainty_config:
        Monte Carlo configuration (distributions, n_scenarios, seed).
    n_intervals:
        Intervals per scenario price trace (default 8760, hourly annual).
    engine_factory:
        Optional callable ``(prices: dict[int, float]) -> SolveResult`` that
        builds and solves the LP for a given price trace.  When provided,
        SAA mode is used and the engine is called once per scenario.

    Returns
    -------
    MonteCarloResults
        Aggregated percentile statistics and full scenario list.
    """
    traces = generate_price_traces(uncertainty_config, n_intervals)
    base_revenue = base_revenue_per_mw * capacity_mw

    # Determine base energy price mean for normalisation (simple mode)
    energy_dist = uncertainty_config.distributions.get("ENERGY")
    base_energy_mean: float = energy_dist.mean if energy_dist is not None else 0.0

    results: list[ScenarioResult] = []

    for trace in traces:
        if engine_factory is not None:
            # SAA mode: call LP engine with this scenario's price trace
            energy_prices = trace.get("ENERGY", np.zeros(n_intervals))
            price_dict: dict[int, float] = {i: float(p) for i, p in enumerate(energy_prices)}
            solve_result = engine_factory(price_dict)
            annual_revenue = float(solve_result.objective_value or 0.0)
        else:
            # Simple mode: revenue scaling by mean price ratio
            if "ENERGY" in trace and base_energy_mean != 0.0:
                scenario_energy_mean = float(np.mean(trace["ENERGY"]))
                revenue_scale = scenario_energy_mean / base_energy_mean
            else:
                revenue_scale = 1.0
            annual_revenue = base_revenue * revenue_scale

        npv_val = _compute_npv(annual_revenue, capex_total)
        irr_val = _compute_irr(annual_revenue, capex_total)

        results.append(
            ScenarioResult(
                capacity_mw=capacity_mw,
                npv=npv_val,
                annual_revenue=annual_revenue,
                irr=irr_val,
            )
        )

    npv_values = np.array([r.npv for r in results])
    rev_values = np.array([r.annual_revenue for r in results])

    return MonteCarloResults(
        n_scenarios=uncertainty_config.n_scenarios,
        p10_npv=float(np.percentile(npv_values, 10)),
        p50_npv=float(np.percentile(npv_values, 50)),
        p90_npv=float(np.percentile(npv_values, 90)),
        p10_revenue=float(np.percentile(rev_values, 10)),
        p50_revenue=float(np.percentile(rev_values, 50)),
        p90_revenue=float(np.percentile(rev_values, 90)),
        scenario_results=results,
    )
