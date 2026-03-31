"""Tests for app.optimisation.rcm -- Reserve Capacity Mechanism model.

Covers:
  - RcmConfig validation
  - annual_rcm_revenue() helper
  - add_rcm_constraints() model structure and correctness
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.optimisation.rcm import RcmConfig, add_rcm_constraints, annual_rcm_revenue

pyo = pytest.importorskip("pyomo.environ", reason="pyomo not installed")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_model(n_intervals: int = 4) -> Any:
    """Return a minimal ConcreteModel with a T set."""
    m = pyo.ConcreteModel(name="TestRCM")
    m.T = pyo.Set(initialize=range(n_intervals), ordered=True)
    return m


# ---------------------------------------------------------------------------
# RcmConfig validation
# ---------------------------------------------------------------------------


class TestRcmConfig:
    def test_default_obligation(self) -> None:
        cfg = RcmConfig(accredited_mw=10.0, capacity_price_aud_per_mw_year=200_000.0)
        assert cfg.availability_obligation_pct == pytest.approx(0.85)

    def test_custom_values(self) -> None:
        cfg = RcmConfig(
            accredited_mw=50.0,
            capacity_price_aud_per_mw_year=180_000.0,
            availability_obligation_pct=0.90,
        )
        assert cfg.accredited_mw == pytest.approx(50.0)
        assert cfg.capacity_price_aud_per_mw_year == pytest.approx(180_000.0)
        assert cfg.availability_obligation_pct == pytest.approx(0.90)

    def test_negative_accredited_mw_raises(self) -> None:
        with pytest.raises(ValidationError):
            RcmConfig(accredited_mw=-5.0, capacity_price_aud_per_mw_year=200_000.0)

    def test_zero_accredited_mw_raises(self) -> None:
        with pytest.raises(ValidationError):
            RcmConfig(accredited_mw=0.0, capacity_price_aud_per_mw_year=200_000.0)

    def test_negative_price_raises(self) -> None:
        with pytest.raises(ValidationError):
            RcmConfig(accredited_mw=10.0, capacity_price_aud_per_mw_year=-1.0)

    def test_obligation_above_one_raises(self) -> None:
        with pytest.raises(ValidationError):
            RcmConfig(
                accredited_mw=10.0,
                capacity_price_aud_per_mw_year=200_000.0,
                availability_obligation_pct=1.5,
            )

    def test_obligation_below_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            RcmConfig(
                accredited_mw=10.0,
                capacity_price_aud_per_mw_year=200_000.0,
                availability_obligation_pct=-0.1,
            )

    def test_zero_price_allowed(self) -> None:
        cfg = RcmConfig(accredited_mw=10.0, capacity_price_aud_per_mw_year=0.0)
        assert cfg.capacity_price_aud_per_mw_year == pytest.approx(0.0)

    def test_obligation_boundary_zero(self) -> None:
        cfg = RcmConfig(
            accredited_mw=10.0,
            capacity_price_aud_per_mw_year=200_000.0,
            availability_obligation_pct=0.0,
        )
        assert cfg.availability_obligation_pct == pytest.approx(0.0)

    def test_obligation_boundary_one(self) -> None:
        cfg = RcmConfig(
            accredited_mw=10.0,
            capacity_price_aud_per_mw_year=200_000.0,
            availability_obligation_pct=1.0,
        )
        assert cfg.availability_obligation_pct == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# annual_rcm_revenue()
# ---------------------------------------------------------------------------


class TestAnnualRcmRevenue:
    def test_basic_calculation(self) -> None:
        cfg = RcmConfig(accredited_mw=10.0, capacity_price_aud_per_mw_year=200_000.0)
        assert annual_rcm_revenue(cfg) == pytest.approx(2_000_000.0)

    def test_zero_price(self) -> None:
        cfg = RcmConfig(accredited_mw=5.0, capacity_price_aud_per_mw_year=0.0)
        assert annual_rcm_revenue(cfg) == pytest.approx(0.0)

    def test_fractional_mw(self) -> None:
        cfg = RcmConfig(accredited_mw=2.5, capacity_price_aud_per_mw_year=100_000.0)
        assert annual_rcm_revenue(cfg) == pytest.approx(250_000.0)


# ---------------------------------------------------------------------------
# add_rcm_constraints()
# ---------------------------------------------------------------------------


class TestAddRcmConstraints:
    def _default_cfg(self) -> RcmConfig:
        return RcmConfig(
            accredited_mw=10.0,
            capacity_price_aud_per_mw_year=200_000.0,
            availability_obligation_pct=0.85,
        )

    def test_variables_created(self) -> None:
        m = _make_model(4)
        cfg = self._default_cfg()
        add_rcm_constraints(m, cfg, interval_duration_h=0.5)
        assert hasattr(m, "rcm_available_mw")

    def test_constraint_created(self) -> None:
        m = _make_model(4)
        cfg = self._default_cfg()
        add_rcm_constraints(m, cfg, interval_duration_h=0.5)
        assert hasattr(m, "rcm_availability_con")

    def test_annual_revenue_param(self) -> None:
        m = _make_model(4)
        cfg = self._default_cfg()
        add_rcm_constraints(m, cfg, interval_duration_h=0.5)
        assert hasattr(m, "rcm_annual_revenue_aud")
        assert float(m.rcm_annual_revenue_aud) == pytest.approx(2_000_000.0)

    def test_variable_bounds(self) -> None:
        m = _make_model(4)
        cfg = self._default_cfg()
        add_rcm_constraints(m, cfg, interval_duration_h=0.5)
        for t in range(4):
            lb, ub = m.rcm_available_mw[t].bounds
            assert lb == pytest.approx(0.0)
            assert ub == pytest.approx(10.0)

    def test_availability_constraint_count(self) -> None:
        n = 6
        m = _make_model(n)
        cfg = self._default_cfg()
        add_rcm_constraints(m, cfg, interval_duration_h=0.5)
        # One constraint per interval
        assert len(list(m.rcm_availability_con)) == n

    def test_revenue_expressions_exist(self) -> None:
        m = _make_model(4)
        cfg = self._default_cfg()
        add_rcm_constraints(m, cfg, interval_duration_h=0.5)
        assert hasattr(m, "rcm_revenue_per_interval")
        assert hasattr(m, "rcm_total_revenue")

    def test_pro_rated_interval_revenue(self) -> None:
        """Interval revenue = annual_revenue / (8760 / interval_h)."""
        m = _make_model(4)
        cfg = self._default_cfg()
        interval_h = 0.5
        add_rcm_constraints(m, cfg, interval_duration_h=interval_h)
        intervals_per_year = 8760.0 / interval_h
        expected_per_interval = 2_000_000.0 / intervals_per_year
        assert float(pyo.value(m.rcm_revenue_per_interval)) == pytest.approx(
            expected_per_interval, rel=1e-6
        )

    def test_total_revenue_over_horizon(self) -> None:
        """Total revenue = interval_revenue × n_intervals."""
        n = 4
        m = _make_model(n)
        cfg = self._default_cfg()
        interval_h = 0.5
        add_rcm_constraints(m, cfg, interval_duration_h=interval_h)
        intervals_per_year = 8760.0 / interval_h
        expected_total = n * (2_000_000.0 / intervals_per_year)
        assert float(pyo.value(m.rcm_total_revenue)) == pytest.approx(expected_total, rel=1e-6)

    def test_empty_T_does_not_raise(self) -> None:
        """Empty T set should log a warning and return without error."""
        m = _make_model(0)
        cfg = self._default_cfg()
        add_rcm_constraints(m, cfg, interval_duration_h=0.5)
        # No variables or constraints should be added
        assert not hasattr(m, "rcm_available_mw")
