"""Unit tests for financial metrics: NPV, IRR, LCOE, payback, equity multiple."""

from __future__ import annotations

import math

import pytest

from app.financial.metrics import (
    discounted_payback,
    equity_multiple,
    irr,
    lcoe,
    npv,
    simple_payback,
)


class TestNPV:
    def test_simple_positive(self):
        """Simple 1-year project: invest 100, receive 120 — positive NPV at 10%."""
        result = npv(0.10, [-100.0, 120.0])
        assert result == pytest.approx(9.09, rel=0.01)

    def test_zero_discount_rate(self):
        """Zero discount rate — NPV equals sum of cashflows."""
        result = npv(0.0, [-100.0, 50.0, 60.0])
        assert result == pytest.approx(10.0, abs=0.01)

    def test_negative_npv(self):
        """High discount rate produces negative NPV."""
        result = npv(0.5, [-100.0, 110.0])
        assert result < 0


class TestIRR:
    def test_simple_project(self):
        """Invest 100, receive 110 in year 1 — IRR should be 10%."""
        result = irr([-100.0, 110.0])
        assert result is not None
        assert result == pytest.approx(0.10, rel=0.01)

    def test_multi_year(self):
        """Multi-year project IRR > 0."""
        result = irr([-1000.0, 300.0, 400.0, 500.0])
        assert result is not None
        assert result > 0

    def test_no_sign_change_returns_none_or_nan(self):
        """All positive cashflows — IRR may return None or a degenerate result."""
        result = irr([100.0, 100.0, 100.0])
        # Either None or NaN or a very large number; not a meaningful IRR
        if result is not None:
            assert math.isnan(result) or result > 1e6


class TestLCOE:
    def test_basic_lcoe_range(self):
        """LCOE of a typical 1 MW project at 10% over 20y is in 0.05–0.80 $/kWh range."""
        result = lcoe(
            total_capex=1_000_000.0,
            annual_opex=20_000.0,
            annual_energy_kwh=200_000.0,
            discount_rate=0.07,
            project_life_years=20,
        )
        # Rough range for a mid-sized project
        assert 0.05 < result < 1.0

    def test_zero_discount_rate(self):
        """Zero discount rate uses simple averaging."""
        result = lcoe(
            total_capex=1_000_000.0,
            annual_opex=0.0,
            annual_energy_kwh=100_000.0,
            discount_rate=0.0,
            project_life_years=10,
        )
        # 1_000_000 / (100_000 * 10) = 1.0 $/kWh
        assert result == pytest.approx(1.0, rel=0.001)

    def test_lcoe_decreases_with_more_energy(self):
        """Higher annual energy reduces LCOE proportionally."""
        base = lcoe(1_000_000.0, 20_000.0, 200_000.0, 0.07, 20)
        double_energy = lcoe(1_000_000.0, 20_000.0, 400_000.0, 0.07, 20)
        assert double_energy < base

    def test_invalid_energy(self):
        """Raises ValueError if annual_energy_kwh <= 0."""
        with pytest.raises(ValueError, match="annual_energy_kwh"):
            lcoe(1_000_000.0, 20_000.0, 0.0, 0.07, 20)

    def test_invalid_life(self):
        """Raises ValueError if project_life_years <= 0."""
        with pytest.raises(ValueError, match="project_life_years"):
            lcoe(1_000_000.0, 20_000.0, 200_000.0, 0.07, 0)


class TestSimplePayback:
    def test_basic(self):
        """Basic payback: invest 100k, earn 25k/yr — 4 years."""
        result = simple_payback(100_000.0, 25_000.0)
        assert result == pytest.approx(4.0, rel=0.001)

    def test_invalid_cashflow(self):
        """Raises ValueError if annual_net_cashflow <= 0."""
        with pytest.raises(ValueError):
            simple_payback(100_000.0, 0.0)


class TestDiscountedPayback:
    def test_achieves_payback(self):
        """Project pays back after several years."""
        cashflows = [-100.0] + [30.0] * 10
        result = discounted_payback(cashflows, 0.10)
        assert result is not None
        assert 3 < result < 10

    def test_never_pays_back(self):
        """Returns None if the project never pays back at high discount rate."""
        cashflows = [-1000.0] + [50.0] * 5  # insufficient cashflows
        result = discounted_payback(cashflows, 0.20)
        assert result is None


class TestEquityMultiple:
    def test_basic(self):
        """Invest 100k equity, receive 250k total — multiple is 2.5x."""
        result = equity_multiple(100_000.0, 250_000.0)
        assert result == pytest.approx(2.5, rel=0.001)

    def test_invalid_equity(self):
        """Raises ValueError if equity_invested <= 0."""
        with pytest.raises(ValueError):
            equity_multiple(0.0, 100_000.0)
