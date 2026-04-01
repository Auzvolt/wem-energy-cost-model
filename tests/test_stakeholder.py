"""Tests for app.financial.stakeholder module."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from app.financial.stakeholder import (
    DEFAULT_EQUITY_DISCOUNT_RATE,
    WA_DEFAULT_DEMAND_AVOIDANCE_AUD_KW_YEAR,
    DeveloperValue,
    NetworkValue,
    OfftakerValue,
    StakeholderValueResult,
    calculate_stakeholder_value,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cashflow_df(fcfe: list[float], fcff: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"fcfe": fcfe, "fcff": fcff})


def _simple_cashflows(
    capex: float = 100_000.0,
    annual_cashflow: float = 20_000.0,
    years: int = 10,
) -> pd.DataFrame:
    """Return a simple constant-cashflow DataFrame for tests."""
    fcfe = [-capex] + [annual_cashflow] * years
    fcff = [-capex] + [annual_cashflow * 1.2] * years  # slightly higher for unlevered
    return _cashflow_df(fcfe, fcff)


# ---------------------------------------------------------------------------
# Developer value tests
# ---------------------------------------------------------------------------


class TestDeveloperValue:
    def test_irr_computed(self) -> None:
        """equity_irr and project_irr are finite for standard cashflows."""
        result = calculate_stakeholder_value(
            cashflow_df=_simple_cashflows(),
            capex=100_000.0,
            annual_bill_saving=10_000.0,
        )
        assert math.isfinite(result.developer.equity_irr)
        assert math.isfinite(result.developer.project_irr)

    def test_equity_npv_default(self) -> None:
        """equity_npv is computed from fcfe at the default discount rate."""
        cf = _simple_cashflows(capex=100_000.0, annual_cashflow=20_000.0, years=10)
        result = calculate_stakeholder_value(
            cashflow_df=cf,
            capex=100_000.0,
            annual_bill_saving=10_000.0,
            equity_discount_rate=DEFAULT_EQUITY_DISCOUNT_RATE,
        )
        # NPV should be positive given high annual cashflows
        assert result.developer.equity_npv > 0

    def test_equity_npv_from_metrics(self) -> None:
        """When metrics.npv is supplied, equity_npv is taken from it."""

        class FakeMetrics:
            npv = 42_000.0

        result = calculate_stakeholder_value(
            cashflow_df=_simple_cashflows(),
            capex=100_000.0,
            annual_bill_saving=10_000.0,
            metrics=FakeMetrics(),
        )
        assert result.developer.equity_npv == pytest.approx(42_000.0)

    def test_irr_nan_for_non_solvable(self) -> None:
        """All-positive cashflows (no initial investment) produce NaN IRR."""
        all_positive = _cashflow_df(fcfe=[100.0] * 5, fcff=[100.0] * 5)
        result = calculate_stakeholder_value(
            cashflow_df=all_positive,
            capex=0.0,
            annual_bill_saving=0.0,
        )
        assert math.isnan(result.developer.equity_irr)

    def test_return_type(self) -> None:
        result = calculate_stakeholder_value(
            cashflow_df=_simple_cashflows(),
            capex=100_000.0,
            annual_bill_saving=10_000.0,
        )
        assert isinstance(result, StakeholderValueResult)
        assert isinstance(result.developer, DeveloperValue)


# ---------------------------------------------------------------------------
# Offtaker value tests
# ---------------------------------------------------------------------------


class TestOfftakerValue:
    def test_annual_bill_saving(self) -> None:
        result = calculate_stakeholder_value(
            cashflow_df=_simple_cashflows(),
            capex=100_000.0,
            annual_bill_saving=25_000.0,
        )
        assert result.offtaker.annual_bill_saving == pytest.approx(25_000.0)

    def test_payback_simple(self) -> None:
        result = calculate_stakeholder_value(
            cashflow_df=_simple_cashflows(),
            capex=100_000.0,
            annual_bill_saving=25_000.0,
        )
        # 100_000 / 25_000 = 4.0 years
        assert result.offtaker.payback_years == pytest.approx(4.0)

    def test_zero_saving_inf_payback(self) -> None:
        result = calculate_stakeholder_value(
            cashflow_df=_simple_cashflows(),
            capex=100_000.0,
            annual_bill_saving=0.0,
        )
        assert math.isinf(result.offtaker.payback_years)

    def test_hedge_value(self) -> None:
        result = calculate_stakeholder_value(
            cashflow_df=_simple_cashflows(),
            capex=100_000.0,
            annual_bill_saving=10_000.0,
            contracted_volume_mwh=500.0,
            price_volatility_aud_per_mwh=20.0,
        )
        # 500 MWh × 20 AUD/MWh = 10_000 AUD
        assert result.offtaker.hedge_value == pytest.approx(10_000.0)

    def test_zero_hedge_when_no_contract(self) -> None:
        result = calculate_stakeholder_value(
            cashflow_df=_simple_cashflows(),
            capex=100_000.0,
            annual_bill_saving=10_000.0,
        )
        assert result.offtaker.hedge_value == pytest.approx(0.0)

    def test_return_type(self) -> None:
        result = calculate_stakeholder_value(
            cashflow_df=_simple_cashflows(),
            capex=100_000.0,
            annual_bill_saving=10_000.0,
        )
        assert isinstance(result.offtaker, OfftakerValue)


# ---------------------------------------------------------------------------
# Network value tests
# ---------------------------------------------------------------------------


class TestNetworkValue:
    def test_avoided_network_cost(self) -> None:
        result = calculate_stakeholder_value(
            cashflow_df=_simple_cashflows(),
            capex=100_000.0,
            annual_bill_saving=10_000.0,
            peak_demand_reduction_kw=100.0,
        )
        # 100 kW × 120 AUD/kW/yr = 12_000 AUD/yr
        assert result.network.avoided_network_cost == pytest.approx(
            100.0 * WA_DEFAULT_DEMAND_AVOIDANCE_AUD_KW_YEAR
        )
        assert result.network.peak_demand_reduction_kw == pytest.approx(100.0)

    def test_custom_demand_avoidance_rate(self) -> None:
        result = calculate_stakeholder_value(
            cashflow_df=_simple_cashflows(),
            capex=100_000.0,
            annual_bill_saving=10_000.0,
            peak_demand_reduction_kw=50.0,
            demand_avoidance_rate=200.0,
        )
        assert result.network.avoided_network_cost == pytest.approx(50.0 * 200.0)

    def test_zero_demand_reduction(self) -> None:
        result = calculate_stakeholder_value(
            cashflow_df=_simple_cashflows(),
            capex=100_000.0,
            annual_bill_saving=10_000.0,
        )
        assert result.network.avoided_network_cost == pytest.approx(0.0)
        assert result.network.peak_demand_reduction_kw == pytest.approx(0.0)

    def test_return_type(self) -> None:
        result = calculate_stakeholder_value(
            cashflow_df=_simple_cashflows(),
            capex=100_000.0,
            annual_bill_saving=10_000.0,
        )
        assert isinstance(result.network, NetworkValue)


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_missing_fcfe_raises(self) -> None:
        with pytest.raises(KeyError, match="fcfe"):
            calculate_stakeholder_value(
                cashflow_df=pd.DataFrame({"fcff": [1.0, 2.0]}),
                capex=100_000.0,
                annual_bill_saving=10_000.0,
            )

    def test_missing_fcff_raises(self) -> None:
        with pytest.raises(KeyError, match="fcff"):
            calculate_stakeholder_value(
                cashflow_df=pd.DataFrame({"fcfe": [1.0, 2.0]}),
                capex=100_000.0,
                annual_bill_saving=10_000.0,
            )
