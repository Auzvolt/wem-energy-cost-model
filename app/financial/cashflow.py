"""Cashflow forecasting model for energy asset financial analysis.

Builds annual cashflow projections from revenue streams, costs, and
project finance configuration. Designed to be solver-agnostic — inputs
come from either the optimisation engine or manual assumptions.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Configuration models
# ---------------------------------------------------------------------------


class ProjectFinanceConfig(BaseModel):
    """Financial parameters for a project cashflow model.

    Attributes:
        project_life_years: Economic life of the project in years.
        discount_rate: Nominal annual discount rate (0 < r < 1), e.g. 0.08.
        debt_fraction: Fraction of initial capex funded by debt (0–1).
        debt_rate: Annual interest rate on debt (0–1), e.g. 0.06.
        debt_term_years: Loan amortisation period in years (≤ project_life_years).
        escalation_rates: Per-stream annual nominal escalation rate.
            Keys match revenue/cost stream names, e.g.:
            ``{"energy_revenue": 0.03, "opex_fixed": 0.025}``.
            Streams not listed default to 0% escalation.
        tax_rate: Corporate tax rate (0–1). Defaults to 0 (pre-tax model).
    """

    project_life_years: int = Field(..., ge=1, le=50)
    discount_rate: float = Field(..., gt=0.0, lt=1.0)
    debt_fraction: float = Field(0.0, ge=0.0, le=1.0)
    debt_rate: float = Field(0.0, ge=0.0, lt=1.0)
    debt_term_years: int = Field(0, ge=0)
    escalation_rates: dict[str, float] = Field(default_factory=dict)
    tax_rate: float = Field(0.0, ge=0.0, lt=1.0)

    @field_validator("discount_rate")
    @classmethod
    def discount_rate_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("discount_rate must be > 0")
        return v

    @model_validator(mode="after")
    def debt_term_le_project_life(self) -> ProjectFinanceConfig:
        if self.debt_fraction > 0 and self.debt_term_years > self.project_life_years:
            raise ValueError(
                "debt_term_years must be <= project_life_years when debt_fraction > 0"
            )
        if self.debt_fraction > 0 and self.debt_term_years == 0:
            raise ValueError("debt_term_years must be > 0 when debt_fraction > 0")
        return self


# ---------------------------------------------------------------------------
# Input dataclasses
# ---------------------------------------------------------------------------


@dataclass
class AnnualRevenue:
    """Base-year annual revenue streams (Year 1 nominal, $/year).

    Escalation is applied per-stream using ``ProjectFinanceConfig.escalation_rates``.
    """

    energy_revenue: float = 0.0
    fcess_revenue: float = 0.0
    capacity_revenue: float = 0.0
    network_savings: float = 0.0

    def total(self) -> float:
        return (
            self.energy_revenue
            + self.fcess_revenue
            + self.capacity_revenue
            + self.network_savings
        )


@dataclass
class AnnualCosts:
    """Base-year annual cost streams (Year 1 nominal, $/year).

    Note: ``debt_service`` is typically computed internally from capex and finance
    config, but can be overridden here for refinancing scenarios.
    """

    opex_fixed: float = 0.0
    opex_variable: float = 0.0
    replacement_capex: float = 0.0

    def opex_total(self) -> float:
        return self.opex_fixed + self.opex_variable


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _level_annuity(principal: float, rate: float, periods: int) -> float:
    """Compute the constant annual payment for a level annuity (loan).

    Uses the standard annuity formula::

        PMT = P * r * (1+r)^n / ((1+r)^n - 1)

    Returns 0 if principal or rate is 0, or periods is 0.
    """
    if principal <= 0 or rate <= 0 or periods <= 0:
        return 0.0
    pv_factor = (1 + rate) ** periods
    return principal * rate * pv_factor / (pv_factor - 1)


def _escalate(base_value: float, rate: float, year: int) -> float:
    """Apply annual escalation: ``base * (1 + rate)^(year - 1)``.

    Year 1 returns the base value unchanged.
    """
    return base_value * ((1 + rate) ** (year - 1))


def _get_rate(stream: str, config: ProjectFinanceConfig) -> float:
    return config.escalation_rates.get(stream, 0.0)


# ---------------------------------------------------------------------------
# Core cashflow builder
# ---------------------------------------------------------------------------


def build_cashflow(
    annual_revenue: AnnualRevenue,
    annual_costs: AnnualCosts,
    initial_capex: float,
    config: ProjectFinanceConfig,
) -> pd.DataFrame:
    """Build a year-by-year cashflow projection.

    Parameters
    ----------
    annual_revenue:
        Base-year (Year 1 nominal) revenue by stream.
    annual_costs:
        Base-year (Year 1 nominal) operating costs by stream.
    initial_capex:
        Total project capital expenditure ($).
    config:
        Project finance parameters including escalation, debt structure,
        discount rate, and project life.

    Returns
    -------
    pd.DataFrame
        One row per year with columns:
        ``year, energy_revenue, fcess_revenue, capacity_revenue,
        network_savings, total_revenue, opex_fixed, opex_variable,
        opex_total, replacement_capex, debt_service, ebitda, fcff, fcfe,
        fcfe_discounted``.
    """
    debt_principal = initial_capex * config.debt_fraction
    annual_debt_service = _level_annuity(
        debt_principal,
        config.debt_rate,
        config.debt_term_years,
    )

    rows: list[dict[str, float]] = []

    for year in range(1, config.project_life_years + 1):
        # Revenue streams — each escalated independently
        energy_rev = _escalate(
            annual_revenue.energy_revenue,
            _get_rate("energy_revenue", config),
            year,
        )
        fcess_rev = _escalate(
            annual_revenue.fcess_revenue,
            _get_rate("fcess_revenue", config),
            year,
        )
        capacity_rev = _escalate(
            annual_revenue.capacity_revenue,
            _get_rate("capacity_revenue", config),
            year,
        )
        network_sav = _escalate(
            annual_revenue.network_savings,
            _get_rate("network_savings", config),
            year,
        )
        total_rev = energy_rev + fcess_rev + capacity_rev + network_sav

        # Cost streams
        opex_fixed = _escalate(annual_costs.opex_fixed, _get_rate("opex_fixed", config), year)
        opex_var = _escalate(annual_costs.opex_variable, _get_rate("opex_variable", config), year)
        opex_total = opex_fixed + opex_var
        repl_capex = _escalate(
            annual_costs.replacement_capex,
            _get_rate("replacement_capex", config),
            year,
        )

        # Debt service: zero after debt term
        debt_svc = annual_debt_service if year <= config.debt_term_years else 0.0

        # P&L aggregates
        ebitda = total_rev - opex_total
        fcff = ebitda - repl_capex  # Free Cash Flow to Firm (pre-financing)
        fcfe = fcff - debt_svc       # Free Cash Flow to Equity (post-financing)

        # Discounted equity cashflow (Year 1 discounted at t=1)
        fcfe_disc = fcfe / ((1 + config.discount_rate) ** year)

        rows.append(
            {
                "year": float(year),
                "energy_revenue": energy_rev,
                "fcess_revenue": fcess_rev,
                "capacity_revenue": capacity_rev,
                "network_savings": network_sav,
                "total_revenue": total_rev,
                "opex_fixed": opex_fixed,
                "opex_variable": opex_var,
                "opex_total": opex_total,
                "replacement_capex": repl_capex,
                "debt_service": debt_svc,
                "ebitda": ebitda,
                "fcff": fcff,
                "fcfe": fcfe,
                "fcfe_discounted": fcfe_disc,
            }
        )

    df = pd.DataFrame(rows)
    df["year"] = df["year"].astype(int)
    return df
