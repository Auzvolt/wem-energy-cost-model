"""Unit tests for auto-sizing optimisation mode (issue #28).

Tests cover:
- CapexModel.capital_recovery_factor correctness
- CRF edge case: discount_rate == 0
- sweep_capacity returns correct number of results
- sweep_capacity NPV is maximised at highest capacity (linear model)
- add_auto_size_vars injects expected Pyomo variables
"""

from __future__ import annotations

import pyomo.environ as pyo
import pytest

from app.models.capex import CapexModel
from app.optimisation.auto_size import (
    AutoSizeConfig,
    SizeResult,
    add_auto_size_vars,
    sweep_capacity,
)

# ---------------------------------------------------------------------------
# CapexModel / CRF tests
# ---------------------------------------------------------------------------


class TestCapitalRecoveryFactor:
    """Tests for CapexModel.capital_recovery_factor."""

    def test_crf_standard_values(self) -> None:
        """CRF(r=0.10, n=20) ≈ 0.1175 (standard textbook value)."""
        model = CapexModel(capex_per_kw=1000.0, opex_per_kw_year=20.0, life_years=20)
        crf = model.capital_recovery_factor(discount_rate=0.10)
        assert abs(crf - 0.11746) < 0.0001, f"Expected ≈0.11746, got {crf:.6f}"

    def test_crf_zero_discount_rate(self) -> None:
        """CRF with discount_rate=0 should equal 1/life_years."""
        model = CapexModel(capex_per_kw=500.0, opex_per_kw_year=10.0, life_years=25)
        crf = model.capital_recovery_factor(discount_rate=0.0)
        expected = 1.0 / 25
        assert abs(crf - expected) < 1e-9, f"Expected {expected}, got {crf}"

    def test_crf_positive(self) -> None:
        """CRF must always be positive."""
        model = CapexModel(capex_per_kw=800.0, opex_per_kw_year=15.0, life_years=10)
        for rate in [0.0, 0.05, 0.08, 0.12, 0.20]:
            crf = model.capital_recovery_factor(discount_rate=rate)
            assert crf > 0, f"CRF should be positive for rate={rate}, got {crf}"

    def test_crf_higher_rate_means_higher_crf(self) -> None:
        """Higher discount rate should produce a higher CRF (more expensive capital)."""
        model = CapexModel(capex_per_kw=1000.0, opex_per_kw_year=0.0, life_years=15)
        crf_low = model.capital_recovery_factor(discount_rate=0.05)
        crf_high = model.capital_recovery_factor(discount_rate=0.15)
        assert crf_high > crf_low, "Higher discount rate must yield higher CRF"

    def test_crf_formula_manual(self) -> None:
        """Verify CRF against manual calculation."""
        r, n = 0.08, 10
        model = CapexModel(capex_per_kw=1000.0, opex_per_kw_year=0.0, life_years=n)
        expected = r * (1 + r) ** n / ((1 + r) ** n - 1)
        crf = model.capital_recovery_factor(discount_rate=r)
        assert abs(crf - expected) < 1e-10


# ---------------------------------------------------------------------------
# sweep_capacity tests
# ---------------------------------------------------------------------------


class TestSweepCapacity:
    """Tests for the parametric capacity sweep."""

    def _make_config(self, min_mw: float = 0.0, max_mw: float = 100.0) -> AutoSizeConfig:
        capex = CapexModel(capex_per_kw=500.0, opex_per_kw_year=10.0, life_years=20)
        return AutoSizeConfig(
            capex=capex,
            discount_rate=0.08,
            min_capacity_mw=min_mw,
            max_capacity_mw=max_mw,
        )

    def test_returns_correct_number_of_results(self) -> None:
        """sweep_capacity must return exactly `steps` SizeResult entries."""
        config = self._make_config()
        results = sweep_capacity(
            config=config,
            capex_model=config.capex,
            capacity_range=(0.0, 100.0),
            steps=10,
            revenue_per_mw_year=50_000.0,
        )
        assert len(results) == 10

    def test_single_step(self) -> None:
        """Single-step sweep returns one result at min capacity."""
        config = self._make_config(min_mw=5.0, max_mw=50.0)
        results = sweep_capacity(
            config=config,
            capex_model=config.capex,
            capacity_range=(5.0, 50.0),
            steps=1,
            revenue_per_mw_year=80_000.0,
        )
        assert len(results) == 1
        assert results[0].capacity_mw == pytest.approx(5.0)

    def test_all_results_are_size_result_instances(self) -> None:
        """Each element must be a SizeResult dataclass."""
        config = self._make_config()
        results = sweep_capacity(
            config=config,
            capex_model=config.capex,
            capacity_range=(0.0, 50.0),
            steps=5,
            revenue_per_mw_year=60_000.0,
        )
        assert all(isinstance(r, SizeResult) for r in results)

    def test_irr_and_lcoe_are_none(self) -> None:
        """IRR and LCOE fields are None (not yet implemented)."""
        config = self._make_config()
        results = sweep_capacity(
            config=config,
            capex_model=config.capex,
            capacity_range=(0.0, 50.0),
            steps=3,
            revenue_per_mw_year=70_000.0,
        )
        for r in results:
            assert r.irr is None
            assert r.lcoe is None

    def test_npv_maximised_at_max_capacity_high_revenue(self) -> None:
        """With high revenue, the best NPV should be at maximum capacity (linear model)."""
        config = self._make_config(min_mw=1.0, max_mw=100.0)
        results = sweep_capacity(
            config=config,
            capex_model=config.capex,
            capacity_range=(1.0, 100.0),
            steps=20,
            revenue_per_mw_year=200_000.0,  # Very high revenue => positive NPV slope
        )
        best = max(results, key=lambda r: r.npv)
        assert best.capacity_mw == pytest.approx(100.0, rel=1e-3)

    def test_npv_is_negative_at_zero_revenue(self) -> None:
        """With zero revenue, NPV must be <= 0 for all non-zero capacities."""
        config = self._make_config(min_mw=0.0, max_mw=100.0)
        results = sweep_capacity(
            config=config,
            capex_model=config.capex,
            capacity_range=(0.0, 100.0),
            steps=10,
            revenue_per_mw_year=0.0,
        )
        for r in results:
            if r.capacity_mw > 0:
                assert r.npv <= 0, f"NPV must be <= 0 at zero revenue, got {r.npv}"

    def test_invalid_steps_raises(self) -> None:
        """steps < 1 should raise ValueError."""
        config = self._make_config()
        with pytest.raises(ValueError, match="steps"):
            sweep_capacity(
                config=config,
                capex_model=config.capex,
                capacity_range=(0.0, 100.0),
                steps=0,
                revenue_per_mw_year=50_000.0,
            )

    def test_capacity_range_spans_correctly(self) -> None:
        """First and last sweep points match capacity_range bounds."""
        config = self._make_config()
        results = sweep_capacity(
            config=config,
            capex_model=config.capex,
            capacity_range=(10.0, 90.0),
            steps=5,
            revenue_per_mw_year=50_000.0,
        )
        assert results[0].capacity_mw == pytest.approx(10.0)
        assert results[-1].capacity_mw == pytest.approx(90.0)


# ---------------------------------------------------------------------------
# add_auto_size_vars tests
# ---------------------------------------------------------------------------


class TestAddAutoSizeVars:
    """Tests for the Pyomo variable injection function."""

    def _make_model(self) -> pyo.ConcreteModel:
        m = pyo.ConcreteModel()
        m.T = pyo.Set(initialize=[0, 1, 2])
        return m

    def test_capacity_mw_variable_added(self) -> None:
        """add_auto_size_vars must add capacity_mw to the model."""
        capex = CapexModel(capex_per_kw=800.0, opex_per_kw_year=12.0, life_years=15)
        config = AutoSizeConfig(capex=capex, min_capacity_mw=5.0, max_capacity_mw=200.0)
        model = self._make_model()
        add_auto_size_vars(model, config)
        assert hasattr(model, "capacity_mw")

    def test_capacity_mw_bounds(self) -> None:
        """capacity_mw bounds must match config min/max."""
        capex = CapexModel(capex_per_kw=800.0, opex_per_kw_year=12.0, life_years=15)
        config = AutoSizeConfig(capex=capex, min_capacity_mw=10.0, max_capacity_mw=500.0)
        model = self._make_model()
        add_auto_size_vars(model, config)
        lb, ub = pyo.value(model.capacity_mw.lb), pyo.value(model.capacity_mw.ub)
        assert lb == pytest.approx(10.0)
        assert ub == pytest.approx(500.0)

    def test_no_capacity_mwh_for_non_bess(self) -> None:
        """capacity_mwh must NOT be added when is_bess=False."""
        capex = CapexModel(capex_per_kw=800.0, opex_per_kw_year=12.0, life_years=15)
        config = AutoSizeConfig(capex=capex, is_bess=False)
        model = self._make_model()
        add_auto_size_vars(model, config)
        assert not hasattr(model, "capacity_mwh")

    def test_capacity_mwh_added_for_bess(self) -> None:
        """capacity_mwh must be added when is_bess=True."""
        capex = CapexModel(capex_per_kw=800.0, opex_per_kw_year=12.0, life_years=15)
        config = AutoSizeConfig(capex=capex, is_bess=True)
        model = self._make_model()
        add_auto_size_vars(model, config)
        assert hasattr(model, "capacity_mwh")
