"""Monte Carlo uncertainty simulation for WEM energy cost modelling.

Provides:
- ScenarioResult: single scenario outcome
- MonteCarloResults: aggregated P10/P50/P90 statistics across all scenarios
- generate_price_traces: sample N price traces for all WEM products
- run_monte_carlo: run the full Monte Carlo simulation and return percentile stats
"""

from __future__ import annotations

import math

import numpy as np
import numpy_financial as npf
from pydantic import BaseModel, Field

from app.models.uncertainty import (
    ENERGY_PRICE_CAP,
    ENERGY_PRICE_FLOOR,
    UncertaintyConfig,
)

__all__ = [
    "ScenarioResult",
    "MonteCarloResults",
    "generate_price_traces",
    "run_monte_carlo",
]

# Project life for NPV/IRR calculations (years)
_PROJECT_LIFE_YEARS = 20
_DISCOUNT_RATE = 0.08


class ScenarioResult(BaseModel):
    """Result for a single Monte Carlo scenario.

    Attributes
    ----------
    capacity_mw:
        Asset capacity used in this scenario (MW).
    npv:
        Net Present Value over project life ($).
    annual_revenue:
        Annual revenue for this scenario ($/year).
    irr:
        Internal Rate of Return, or None if not achievable.
    """

    capacity_mw: float = Field(description="Asset capacity (MW)")
    npv: float = Field(description="Net Present Value ($)")
    annual_revenue: float = Field(description="Annual revenue ($/year)")
    irr: float | None = Field(default=None, description="IRR as decimal, or None")


class MonteCarloResults(BaseModel):
    """Aggregated results from a Monte Carlo simulation run.

    Attributes
    ----------
    n_scenarios:
        Number of scenarios simulated.
    p10_npv, p50_npv, p90_npv:
        10th, 50th, 90th percentile NPV ($).
    p10_revenue, p50_revenue, p90_revenue:
        10th, 50th, 90th percentile annual revenue ($/year).
    scenario_results:
        Full list of per-scenario results.
    """

    n_scenarios: int
    p10_npv: float
    p50_npv: float
    p90_npv: float
    p10_revenue: float
    p50_revenue: float
    p90_revenue: float
    scenario_results: list[ScenarioResult]


def generate_price_traces(
    uncertainty_config: UncertaintyConfig,
    n_intervals: int,
) -> list[dict[str, list[float]]]:
    """Generate N independent price traces for all configured WEM products.

    Each trace is a dictionary mapping a product code to a list of
    ``n_intervals`` price samples drawn from the product's distribution.

    Energy prices are clamped to the WEM floor/cap ([-1000, 1000] $/MWh).

    Parameters
    ----------
    uncertainty_config:
        Uncertainty configuration including distributions and seed.
    n_intervals:
        Number of dispatch intervals per trace (e.g. 8760 for hourly annual).

    Returns
    -------
    list[dict[str, list[float]]]
        List of ``n_scenarios`` scenario dicts, each mapping
        product code → price list of length ``n_intervals``.
    """
    rng = np.random.default_rng(uncertainty_config.seed)
    traces: list[dict[str, list[float]]] = []

    for _ in range(uncertainty_config.n_scenarios):
        scenario: dict[str, list[float]] = {}
        for product, dist in uncertainty_config.distributions.items():
            samples = dist.sample(n_intervals, rng)
            if product == "ENERGY":
                samples = np.clip(samples, ENERGY_PRICE_FLOOR, ENERGY_PRICE_CAP)
            scenario[product] = samples.tolist()
        traces.append(scenario)

    return traces


def _compute_npv(annual_revenue: float, capex_total: float) -> float:
    """Compute 20-year project NPV at 8% discount rate.

    Parameters
    ----------
    annual_revenue:
        Annual revenue ($/year), assumed constant over project life.
    capex_total:
        Up-front capital cost at t=0 ($).

    Returns
    -------
    float
        NPV in $.
    """
    cashflows = [-capex_total] + [annual_revenue] * _PROJECT_LIFE_YEARS
    return float(npf.npv(_DISCOUNT_RATE, cashflows))


def _compute_irr(annual_revenue: float, capex_total: float) -> float | None:
    """Compute project IRR, returning None if not achievable.

    Parameters
    ----------
    annual_revenue:
        Annual revenue ($/year), constant over project life.
    capex_total:
        Up-front capital cost at t=0 ($).

    Returns
    -------
    float | None
        IRR as a decimal fraction, or None if numpy_financial cannot converge.
    """
    cashflows = [-capex_total] + [annual_revenue] * _PROJECT_LIFE_YEARS
    result = npf.irr(cashflows)
    if result is None or math.isnan(result):
        return None
    return float(result)


def run_monte_carlo(
    base_revenue_per_mw: float,
    capacity_mw: float,
    capex_total: float,
    uncertainty_config: UncertaintyConfig,
    n_intervals: int = 8760,
) -> MonteCarloResults:
    """Run a Monte Carlo simulation and return percentile statistics.

    For each scenario, energy prices are sampled from the configured
    distribution, and the annual revenue is scaled by the ratio of the
    scenario mean price to the mean of the base distribution for ENERGY
    (normalised perturbation). If no ENERGY distribution is configured,
    the base revenue is used unchanged.

    NPV is computed over :attr:`_PROJECT_LIFE_YEARS` years at
    :attr:`_DISCOUNT_RATE` discount rate.

    Parameters
    ----------
    base_revenue_per_mw:
        Base-case annual revenue per MW of capacity ($/MW/year).
    capacity_mw:
        Asset capacity (MW).
    capex_total:
        Total capital expenditure at t=0 ($).
    uncertainty_config:
        Monte Carlo configuration (distributions, n_scenarios, seed).
    n_intervals:
        Intervals per scenario price trace (default 8760, hourly annual).

    Returns
    -------
    MonteCarloResults
        Aggregated percentile statistics and full scenario list.
    """
    traces = generate_price_traces(uncertainty_config, n_intervals)
    base_revenue = base_revenue_per_mw * capacity_mw

    # Determine base energy price mean for normalisation
    energy_dist = uncertainty_config.distributions.get("ENERGY")
    base_energy_mean: float = energy_dist.mean if energy_dist is not None else 0.0

    results: list[ScenarioResult] = []

    for trace in traces:
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
