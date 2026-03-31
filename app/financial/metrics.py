"""Financial metrics: NPV, IRR, LCOE, payback calculations.

Uses numpy_financial (NOT numpy.irr/numpy.npv which are deprecated/removed).
"""
from __future__ import annotations

import numpy_financial as npf


def npv(discount_rate: float, cashflows: list[float]) -> float:
    """Net Present Value.

    cashflows[0] is the year-0 outflow (negative), cashflows[1..N] are inflows.
    Uses numpy_financial.npv which discounts from t=1 onwards and adds cashflows[0] at t=0.

    Args:
        discount_rate: Annual discount rate as a decimal (e.g. 0.08 for 8%).
        cashflows: List of cashflows starting at t=0.

    Returns:
        NPV in the same currency units as the cashflows.
    """
    return float(npf.npv(discount_rate, cashflows))


def irr(cashflows: list[float]) -> float | None:
    """Internal Rate of Return.

    Args:
        cashflows: List of cashflows starting at t=0. Must have at least one sign change.

    Returns:
        IRR as a decimal, or None if numpy_financial fails to converge.
    """
    result = npf.irr(cashflows)
    # numpy_financial returns nan if no solution found
    import math
    if result is None or math.isnan(result):
        return None
    return float(result)


def lcoe(
    total_capex: float,
    annual_opex: float,
    annual_energy_kwh: float,
    discount_rate: float,
    project_life_years: int,
) -> float:
    """Levelised Cost of Energy ($/kWh).

    LCOE = PV(all costs) / PV(all energy output)

    Args:
        total_capex: Total capital expenditure at t=0 ($).
        annual_opex: Annual operating cost ($/year), assumed constant.
        annual_energy_kwh: Annual energy produced (kWh/year), assumed constant.
        discount_rate: Annual discount rate as a decimal.
        project_life_years: Project lifetime in years.

    Returns:
        LCOE in $/kWh.

    Raises:
        ValueError: If annual_energy_kwh <= 0 or project_life_years <= 0.
    """
    if annual_energy_kwh <= 0:
        raise ValueError("annual_energy_kwh must be positive")
    if project_life_years <= 0:
        raise ValueError("project_life_years must be positive")
    if discount_rate == 0.0:
        pv_costs = total_capex + annual_opex * project_life_years
        pv_energy = annual_energy_kwh * project_life_years
    else:
        # Annuity factor: sum of 1/(1+r)^t for t=1..N
        annuity_factor = (1 - (1 + discount_rate) ** (-project_life_years)) / discount_rate
        pv_costs = total_capex + annual_opex * annuity_factor
        pv_energy = annual_energy_kwh * annuity_factor
    return pv_costs / pv_energy


def simple_payback(initial_investment: float, annual_net_cashflow: float) -> float:
    """Simple (undiscounted) payback period in years.

    Args:
        initial_investment: Upfront investment (positive $).
        annual_net_cashflow: Annual net benefit (positive = net inflow).

    Returns:
        Payback period in years.

    Raises:
        ValueError: If annual_net_cashflow <= 0.
    """
    if annual_net_cashflow <= 0:
        raise ValueError("annual_net_cashflow must be positive for payback to occur")
    return initial_investment / annual_net_cashflow


def discounted_payback(
    cashflows: list[float],
    discount_rate: float,
) -> float | None:
    """Discounted payback period in years.

    Finds the first point at which cumulative discounted cashflows become non-negative.
    Interpolates within the year where payback occurs.

    Args:
        cashflows: List of cashflows starting at t=0. cashflows[0] is typically negative.
        discount_rate: Annual discount rate as a decimal.

    Returns:
        Discounted payback period in years (may be fractional), or None if never paid back.
    """
    cumulative = 0.0
    for t, cf in enumerate(cashflows):
        prev_cumulative = cumulative
        discounted_cf = cf / ((1 + discount_rate) ** t)
        cumulative += discounted_cf
        if cumulative >= 0 and t > 0:
            # Interpolate: how far into year t did we cross zero?
            fraction = -prev_cumulative / discounted_cf
            return float(t - 1 + fraction)
        elif cumulative >= 0 and t == 0:
            # Already positive at t=0 (unusual but handle it)
            return 0.0
    return None


def equity_multiple(equity_invested: float, total_equity_distributions: float) -> float:
    """Equity multiple (total return multiple on equity invested).

    Args:
        equity_invested: Total equity capital invested (positive $).
        total_equity_distributions: Total cash returned to equity investors ($).

    Returns:
        Equity multiple (e.g. 2.0 = 2x return).

    Raises:
        ValueError: If equity_invested <= 0.
    """
    if equity_invested <= 0:
        raise ValueError("equity_invested must be positive")
    return total_equity_distributions / equity_invested
