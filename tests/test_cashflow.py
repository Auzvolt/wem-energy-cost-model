"""Tests for the cashflow forecasting model."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from app.financial.cashflow import (
    AnnualCosts,
    AnnualRevenue,
    ProjectFinanceConfig,
    _level_annuity,
    build_cashflow,
)

# ---------------------------------------------------------------------------
# ProjectFinanceConfig validation
# ---------------------------------------------------------------------------


def test_config_rejects_discount_rate_above_1() -> None:
    with pytest.raises(ValueError):
        ProjectFinanceConfig(
            project_life_years=10,
            discount_rate=1.5,
            debt_fraction=0.0,
            debt_rate=0.0,
            debt_term_years=0,
        )


def test_config_rejects_discount_rate_zero() -> None:
    with pytest.raises(ValueError):
        ProjectFinanceConfig(
            project_life_years=10,
            discount_rate=0.0,
            debt_fraction=0.0,
            debt_rate=0.0,
            debt_term_years=0,
        )


def test_config_rejects_debt_term_gt_project_life() -> None:
    with pytest.raises(ValueError):
        ProjectFinanceConfig(
            project_life_years=10,
            discount_rate=0.08,
            debt_fraction=0.6,
            debt_rate=0.05,
            debt_term_years=15,  # > project_life_years
        )


def test_config_rejects_nonzero_debt_fraction_with_zero_term() -> None:
    with pytest.raises(ValueError):
        ProjectFinanceConfig(
            project_life_years=10,
            discount_rate=0.08,
            debt_fraction=0.6,
            debt_rate=0.05,
            debt_term_years=0,  # invalid — must be > 0 when debt_fraction > 0
        )


def test_config_valid_no_debt() -> None:
    cfg = ProjectFinanceConfig(
        project_life_years=20,
        discount_rate=0.08,
        debt_fraction=0.0,
        debt_rate=0.0,
        debt_term_years=0,
    )
    assert cfg.project_life_years == 20


# ---------------------------------------------------------------------------
# _level_annuity
# ---------------------------------------------------------------------------


def test_level_annuity_standard() -> None:
    """Verify 100k at 6% over 10 years equals known value ~$13,587."""
    pmt = _level_annuity(100_000.0, 0.06, 10)
    # Standard formula: 100000 * 0.06 * (1.06^10) / (1.06^10 - 1)
    expected = 100_000 * 0.06 * (1.06**10) / ((1.06**10) - 1)
    assert math.isclose(pmt, expected, rel_tol=1e-9)


def test_level_annuity_zero_principal() -> None:
    assert _level_annuity(0.0, 0.06, 10) == 0.0


def test_level_annuity_zero_rate() -> None:
    assert _level_annuity(100_000.0, 0.0, 10) == 0.0


# ---------------------------------------------------------------------------
# build_cashflow — basic structure
# ---------------------------------------------------------------------------


def make_config(years: int = 10, **kwargs) -> ProjectFinanceConfig:  # type: ignore[no-untyped-def]
    defaults = dict(
        project_life_years=years,
        discount_rate=0.08,
        debt_fraction=0.0,
        debt_rate=0.0,
        debt_term_years=0,
    )
    defaults.update(kwargs)
    return ProjectFinanceConfig(**defaults)


def test_build_cashflow_row_count() -> None:
    cfg = make_config(10)
    df = build_cashflow(AnnualRevenue(), AnnualCosts(), 1_000_000.0, cfg)
    assert len(df) == 10
    assert list(df["year"]) == list(range(1, 11))


def test_build_cashflow_1_year_ebitda() -> None:
    """Single-year: EBITDA = revenue - opex."""
    cfg = make_config(1)
    rev = AnnualRevenue(energy_revenue=100_000.0)
    costs = AnnualCosts(opex_fixed=30_000.0)
    df = build_cashflow(rev, costs, 0.0, cfg)
    assert len(df) == 1
    assert math.isclose(df.iloc[0]["ebitda"], 70_000.0)
    assert math.isclose(df.iloc[0]["fcff"], 70_000.0)
    assert math.isclose(df.iloc[0]["fcfe"], 70_000.0)


def test_build_cashflow_fcff_fcfe_relationship() -> None:
    """FCFE = FCFF - debt_service for every row."""
    cfg = make_config(
        10,
        debt_fraction=0.6,
        debt_rate=0.06,
        debt_term_years=7,
    )
    rev = AnnualRevenue(energy_revenue=200_000.0, network_savings=50_000.0)
    costs = AnnualCosts(opex_fixed=40_000.0, opex_variable=10_000.0)
    df = build_cashflow(rev, costs, 1_000_000.0, cfg)
    for _, row in df.iterrows():
        assert math.isclose(row["fcfe"], row["fcff"] - row["debt_service"], rel_tol=1e-9)


def test_build_cashflow_flat_no_escalation() -> None:
    """Without escalation all revenue/cost rows should be identical."""
    cfg = make_config(5)
    rev = AnnualRevenue(energy_revenue=100_000.0, fcess_revenue=20_000.0)
    costs = AnnualCosts(opex_fixed=25_000.0)
    df = build_cashflow(rev, costs, 0.0, cfg)
    # All energy_revenue values should be the same
    assert df["energy_revenue"].nunique() == 1
    assert df["opex_fixed"].nunique() == 1
    assert math.isclose(df.iloc[0]["energy_revenue"], 100_000.0)


def test_build_cashflow_energy_escalation() -> None:
    """5% energy escalation over 3 years: Year 1 = base, Year 3 = base * 1.05^2."""
    cfg = make_config(3, escalation_rates={"energy_revenue": 0.05})
    rev = AnnualRevenue(energy_revenue=100_000.0)
    df = build_cashflow(rev, AnnualCosts(), 0.0, cfg)
    assert math.isclose(df.iloc[0]["energy_revenue"], 100_000.0)
    assert math.isclose(df.iloc[1]["energy_revenue"], 105_000.0)
    assert math.isclose(df.iloc[2]["energy_revenue"], 110_250.0)


def test_build_cashflow_debt_service_zeros_after_term() -> None:
    """Debt service should be zero for years > debt_term_years."""
    cfg = make_config(
        10,
        debt_fraction=0.7,
        debt_rate=0.055,
        debt_term_years=5,
    )
    df = build_cashflow(AnnualRevenue(), AnnualCosts(), 500_000.0, cfg)
    # Years 1–5: non-zero debt service
    assert all(df.iloc[:5]["debt_service"] > 0)
    # Years 6–10: zero
    assert all(df.iloc[5:]["debt_service"] == 0.0)


def test_build_cashflow_debt_service_annuity_math() -> None:
    """Verify debt service matches the standard annuity formula directly."""
    principal = 600_000.0
    rate = 0.06
    term = 8
    cfg = make_config(10, debt_fraction=0.6, debt_rate=rate, debt_term_years=term)
    df = build_cashflow(AnnualRevenue(), AnnualCosts(), principal / 0.6, cfg)
    expected_pmt = principal * rate * (1 + rate) ** term / ((1 + rate) ** term - 1)
    for _, row in df.iloc[:term].iterrows():
        assert math.isclose(row["debt_service"], expected_pmt, rel_tol=1e-9)


def test_build_cashflow_discounted_fcfe() -> None:
    """fcfe_discounted for year N = fcfe / (1+r)^N."""
    cfg = make_config(5, discount_rate=0.10)
    rev = AnnualRevenue(energy_revenue=100_000.0)
    df = build_cashflow(rev, AnnualCosts(), 0.0, cfg)
    for _, row in df.iterrows():
        expected = row["fcfe"] / (1.10 ** row["year"])
        assert math.isclose(row["fcfe_discounted"], expected, rel_tol=1e-9)


def test_build_cashflow_returns_dataframe() -> None:
    cfg = make_config(5)
    df = build_cashflow(AnnualRevenue(), AnnualCosts(), 0.0, cfg)
    assert isinstance(df, pd.DataFrame)
    required_cols = {
        "year", "energy_revenue", "fcess_revenue", "capacity_revenue",
        "network_savings", "total_revenue", "opex_fixed", "opex_variable",
        "opex_total", "replacement_capex", "debt_service", "ebitda", "fcff",
        "fcfe", "fcfe_discounted",
    }
    assert required_cols.issubset(set(df.columns))
