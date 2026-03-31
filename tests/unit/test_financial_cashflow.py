"""Unit tests for the cashflow forecasting model."""

from __future__ import annotations

import pandas as pd
import pytest
from pydantic import ValidationError

from app.financial.cashflow import AnnualCosts, AnnualRevenue, ProjectFinanceConfig, build_cashflow


@pytest.fixture
def base_config() -> ProjectFinanceConfig:
    return ProjectFinanceConfig(
        project_life_years=10,
        discount_rate=0.08,
        debt_fraction=0.60,
        debt_rate=0.055,
        debt_term_years=10,
        capex_replacement_schedule={},
        escalation_rates={},
    )


@pytest.fixture
def base_revenue() -> AnnualRevenue:
    return AnnualRevenue(
        energy_revenue=200_000.0,
        fcess_revenue=50_000.0,
        capacity_revenue=30_000.0,
        network_savings=20_000.0,
    )


@pytest.fixture
def base_costs() -> AnnualCosts:
    return AnnualCosts(
        opex_fixed=40_000.0,
        opex_variable=10_000.0,
    )


class TestBuildCashflow:
    def test_returns_dataframe(self, base_config, base_revenue, base_costs):
        """build_cashflow returns a pandas DataFrame."""
        df = build_cashflow(base_revenue, base_costs, 1_000_000.0, base_config)
        assert isinstance(df, pd.DataFrame)

    def test_row_count(self, base_config, base_revenue, base_costs):
        """Returns one row per project year."""
        df = build_cashflow(base_revenue, base_costs, 1_000_000.0, base_config)
        assert len(df) == base_config.project_life_years

    def test_year_column(self, base_config, base_revenue, base_costs):
        """Year column runs from 1 to project_life_years."""
        df = build_cashflow(base_revenue, base_costs, 1_000_000.0, base_config)
        assert list(df["year"]) == list(range(1, base_config.project_life_years + 1))

    def test_required_columns(self, base_config, base_revenue, base_costs):
        """All expected financial columns are present."""
        df = build_cashflow(base_revenue, base_costs, 1_000_000.0, base_config)
        required_cols = {
            "year",
            "total_revenue",
            "opex_total",
            "ebitda",
            "fcff",
            "fcfe",
            "fcfe_discounted",
            "debt_service",
        }
        assert required_cols.issubset(set(df.columns))

    def test_ebitda_positive(self, base_config, base_revenue, base_costs):
        """EBITDA is positive when revenue exceeds opex."""
        df = build_cashflow(base_revenue, base_costs, 1_000_000.0, base_config)
        assert (df["ebitda"] > 0).all()

    def test_no_debt_service_after_term(self, base_config, base_revenue, base_costs):
        """Debt service should be zero after debt term ends."""
        short_debt_config = ProjectFinanceConfig(
            project_life_years=15,
            discount_rate=0.08,
            debt_fraction=0.60,
            debt_rate=0.055,
            debt_term_years=10,
            capex_replacement_schedule={},
            escalation_rates={},
        )
        df2 = build_cashflow(base_revenue, base_costs, 1_000_000.0, short_debt_config)
        after_term = df2[df2["year"] > 10]["debt_service"]
        assert (after_term == 0.0).all()

    def test_invalid_debt_fraction(self):
        """ValidationError raised if debt_fraction > 1."""
        with pytest.raises(ValidationError):
            ProjectFinanceConfig(
                project_life_years=10,
                discount_rate=0.08,
                debt_fraction=1.5,
                debt_rate=0.055,
                debt_term_years=10,
                capex_replacement_schedule={},
                escalation_rates={},
            )
