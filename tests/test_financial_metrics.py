"""Tests for financial metrics module."""

from __future__ import annotations

import math

import pytest
from financial.metrics import (
    discounted_payback,
    equity_multiple,
    irr,
    lcoe,
    npv,
    simple_payback,
)


class TestNPV:
    def test_simple_npv_positive(self) -> None:
        # Invest 1000, receive 600 each year for 2 years at 10%
        # NPV = -1000 + 600/1.1 + 600/1.21 = -1000 + 545.45 + 495.87 ≈ 41.32
        cashflows = [-1000.0, 600.0, 600.0]
        result = npv(0.10, cashflows)
        assert math.isclose(result, 41.32, rel_tol=0.01)

    def test_simple_npv_negative(self) -> None:
        # Same but rate 20% — project not viable
        cashflows = [-1000.0, 600.0, 600.0]
        result = npv(0.20, cashflows)
        assert result < 0

    def test_zero_discount_rate(self) -> None:
        # At 0% discount, NPV = simple sum
        cashflows = [-1000.0, 400.0, 400.0, 400.0]
        result = npv(0.0, cashflows)
        assert math.isclose(result, 200.0, rel_tol=1e-6)

    def test_single_period(self) -> None:
        cashflows = [-100.0, 110.0]
        result = npv(0.10, cashflows)
        assert math.isclose(result, 0.0, abs_tol=1e-6)


class TestIRR:
    def test_irr_known_value(self) -> None:
        # -1000, +1100 => IRR = 10%
        cashflows = [-1000.0, 1100.0]
        result = irr(cashflows)
        assert result is not None
        assert math.isclose(result, 0.10, rel_tol=1e-4)

    def test_irr_multi_period(self) -> None:
        # Standard example: -100, 39, 59, 55, 20
        cashflows = [-100.0, 39.0, 59.0, 55.0, 20.0]
        result = irr(cashflows)
        assert result is not None
        assert 0.28 < result < 0.29  # ~28.7%

    def test_irr_no_sign_change_returns_none(self) -> None:
        # All positive — no sign change, no valid IRR
        cashflows = [100.0, 200.0, 300.0]
        result = irr(cashflows)
        # numpy_financial returns nan for this case
        assert result is None

    def test_irr_breaks_even_at_irr(self) -> None:
        cashflows = [-1000.0, 1100.0]
        r = irr(cashflows)
        assert r is not None
        computed_npv = npv(r, cashflows)
        assert math.isclose(computed_npv, 0.0, abs_tol=1e-3)


class TestLCOE:
    def test_zero_discount_rate(self) -> None:
        # At 0% discount: LCOE = (capex + opex*N) / (energy*N)
        result = lcoe(
            total_capex=1_000_000.0,
            annual_opex=50_000.0,
            annual_energy_kwh=500_000.0,
            discount_rate=0.0,
            project_life_years=20,
        )
        expected = (1_000_000 + 50_000 * 20) / (500_000 * 20)
        assert math.isclose(result, expected, rel_tol=1e-6)

    def test_positive_discount_rate(self) -> None:
        result = lcoe(
            total_capex=1_000_000.0,
            annual_opex=50_000.0,
            annual_energy_kwh=500_000.0,
            discount_rate=0.08,
            project_life_years=20,
        )
        # Should be between $0.05 and $0.50 per kWh for reasonable inputs
        assert 0.05 < result < 0.50

    def test_raises_on_zero_energy(self) -> None:
        with pytest.raises(ValueError, match="annual_energy_kwh"):
            lcoe(1_000_000.0, 50_000.0, 0.0, 0.08, 20)

    def test_raises_on_zero_years(self) -> None:
        with pytest.raises(ValueError, match="project_life_years"):
            lcoe(1_000_000.0, 50_000.0, 500_000.0, 0.08, 0)


class TestSimplePayback:
    def test_basic_payback(self) -> None:
        result = simple_payback(100_000.0, 25_000.0)
        assert math.isclose(result, 4.0, rel_tol=1e-6)

    def test_raises_on_non_positive_cashflow(self) -> None:
        with pytest.raises(ValueError):
            simple_payback(100_000.0, 0.0)

    def test_raises_on_negative_cashflow(self) -> None:
        with pytest.raises(ValueError):
            simple_payback(100_000.0, -5_000.0)

    def test_fractional_payback(self) -> None:
        result = simple_payback(10_000.0, 3_000.0)
        assert math.isclose(result, 10_000 / 3_000, rel_tol=1e-6)


class TestDiscountedPayback:
    def test_never_pays_back(self) -> None:
        # All outflows — never pays back
        cashflows = [-1000.0, -100.0, -100.0]
        result = discounted_payback(cashflows, 0.10)
        assert result is None

    def test_pays_back_year_2(self) -> None:
        # -1000, +600, +600 at 0% — pays back in year 2 (cumulative: -1000, -400, +200)
        result = discounted_payback([-1000.0, 600.0, 600.0], 0.0)
        assert result is not None
        assert 1.0 < result < 2.0

    def test_discounted_longer_than_simple(self) -> None:
        cashflows = [-1000.0, 400.0, 400.0, 400.0, 400.0]
        simple = simple_payback(1000.0, 400.0)
        discounted = discounted_payback(cashflows, 0.10)
        assert discounted is not None
        # Discounted payback is always >= simple payback
        assert discounted >= simple


class TestEquityMultiple:
    def test_two_x_return(self) -> None:
        result = equity_multiple(500_000.0, 1_000_000.0)
        assert math.isclose(result, 2.0, rel_tol=1e-6)

    def test_loss_scenario(self) -> None:
        result = equity_multiple(500_000.0, 250_000.0)
        assert math.isclose(result, 0.5, rel_tol=1e-6)

    def test_raises_on_zero_equity(self) -> None:
        with pytest.raises(ValueError):
            equity_multiple(0.0, 100_000.0)
