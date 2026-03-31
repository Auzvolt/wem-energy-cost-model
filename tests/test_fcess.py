"""Tests for app.optimisation.fcess -- FCESS market participation model.

Covers:
  - FcessConfig validation
  - price_series() and max_mw() helpers
  - add_fcess_constraints() model structure and constraint feasibility
  - Revenue contribution to the objective
  - Co-optimisation headroom enforcement
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.optimisation.fcess import FCESS_PRODUCTS, FcessConfig, add_fcess_constraints

# ---------------------------------------------------------------------------
# FcessConfig validation
# ---------------------------------------------------------------------------


class TestFcessConfig:
    def test_default_products(self) -> None:
        cfg = FcessConfig()
        assert set(cfg.enabled_products) == set(FCESS_PRODUCTS)

    def test_subset_products(self) -> None:
        cfg = FcessConfig(enabled_products=["reg_raise", "reg_lower"])
        assert cfg.enabled_products == ["reg_raise", "reg_lower"]

    def test_unknown_product_raises(self) -> None:
        with pytest.raises(ValidationError, match="Unknown FCESS products"):
            FcessConfig(enabled_products=["bogus_product"])

    def test_max_mw_defaults_none(self) -> None:
        cfg = FcessConfig()
        for p in FCESS_PRODUCTS:
            assert cfg.max_mw(p) is None

    def test_max_mw_configured(self) -> None:
        cfg = FcessConfig(max_reg_raise_mw=10.0, max_cont_raise_mw=5.0)
        assert cfg.max_mw("reg_raise") == pytest.approx(10.0)
        assert cfg.max_mw("cont_raise") == pytest.approx(5.0)
        assert cfg.max_mw("reg_lower") is None

    def test_price_series_fallback(self) -> None:
        cfg = FcessConfig()
        series = cfg.price_series("reg_raise", n_intervals=6)
        assert series == [0.0] * 6

    def test_price_series_custom(self) -> None:
        prices = [10.0, 12.0, 11.0]
        cfg = FcessConfig(prices={"reg_raise": prices})
        assert cfg.price_series("reg_raise", n_intervals=3) == pytest.approx(prices)

    def test_negative_max_mw_raises(self) -> None:
        with pytest.raises(ValidationError):
            FcessConfig(max_reg_raise_mw=-1.0)


# ---------------------------------------------------------------------------
# add_fcess_constraints() — Pyomo model integration
# ---------------------------------------------------------------------------

pyomo = pytest.importorskip("pyomo.environ", reason="pyomo not installed")


def _make_bess_model(
    n: int = 6,
    power_kw: float = 100.0,
    *,
    add_dummy_objective: bool = True,
) -> Any:
    """Build a minimal Pyomo ConcreteModel with BESS-like charge/discharge vars."""
    import pyomo.environ as pyo

    m = pyo.ConcreteModel()
    m.T = pyo.Set(initialize=list(range(n)), ordered=True)

    m.discharge_kw = pyo.Var(m.T, domain=pyo.NonNegativeReals, bounds=(0, power_kw))
    m.charge_kw = pyo.Var(m.T, domain=pyo.NonNegativeReals, bounds=(0, power_kw))

    # Objective accumulation list (mirrors WEMModel.add_objective_term)
    m._obj_terms = []  # list[Any]

    def _add_term(expr: Any) -> None:
        m._obj_terms.append(expr)

    m.add_objective_term = _add_term

    if add_dummy_objective:
        m.base_obj = pyo.Objective(
            expr=sum(m.discharge_kw[t] for t in m.T),
            sense=pyo.maximize,
        )

    return m


class TestAddFcessConstraints:
    def test_variables_added_for_enabled_products(self) -> None:
        m = _make_bess_model()
        cfg = FcessConfig(enabled_products=["reg_raise", "reg_lower"])
        add_fcess_constraints(m, cfg, bess_power_kw=100.0)

        assert hasattr(m, "fcess_reg_raise")
        assert hasattr(m, "fcess_reg_lower")
        assert not hasattr(m, "fcess_cont_raise")

    def test_raise_headroom_constraint_added(self) -> None:
        m = _make_bess_model()
        cfg = FcessConfig(enabled_products=["reg_raise"])
        add_fcess_constraints(m, cfg, bess_power_kw=100.0)
        assert hasattr(m, "fcess_raise_headroom")

    def test_lower_headroom_constraint_added(self) -> None:
        m = _make_bess_model()
        cfg = FcessConfig(enabled_products=["reg_lower"])
        add_fcess_constraints(m, cfg, bess_power_kw=100.0)
        assert hasattr(m, "fcess_lower_headroom")

    def test_no_raise_constraint_if_no_raise_products(self) -> None:
        m = _make_bess_model()
        cfg = FcessConfig(enabled_products=["reg_lower"])
        add_fcess_constraints(m, cfg, bess_power_kw=100.0)
        assert not hasattr(m, "fcess_raise_headroom")

    def test_mw_cap_applied(self) -> None:
        """Variable upper bound should equal configured max_mw."""
        m = _make_bess_model()
        cfg = FcessConfig(enabled_products=["reg_raise"], max_reg_raise_mw=30.0)
        add_fcess_constraints(m, cfg, bess_power_kw=100.0)

        for t in m.T:
            _lb, ub = m.fcess_reg_raise[t].bounds
            assert ub == pytest.approx(30.0)

    def test_revenue_objective_term_added_when_prices_given(self) -> None:
        """Non-zero prices should result in an objective term being added."""
        m = _make_bess_model()
        prices = [5.0] * 6
        cfg = FcessConfig(enabled_products=["reg_raise"], prices={"reg_raise": prices})
        add_fcess_constraints(m, cfg, bess_power_kw=100.0)

        assert len(m._obj_terms) >= 1

    def test_no_objective_term_when_zero_prices(self) -> None:
        """Zero prices should not pollute the objective."""
        m = _make_bess_model()
        cfg = FcessConfig(enabled_products=["reg_raise"])  # no prices → all zeros
        add_fcess_constraints(m, cfg, bess_power_kw=100.0)
        assert len(m._obj_terms) == 0

    def test_headroom_constraint_feasibility(self) -> None:
        """Solving with all products enabled should be feasible.

        BESS at 80 kW discharge + 20 kW reg_raise = 100 kW (at the limit).
        """
        import pyomo.environ as pyo

        m = _make_bess_model(n=2, power_kw=100.0, add_dummy_objective=False)
        prices = [10.0, 10.0]
        cfg = FcessConfig(
            enabled_products=["reg_raise", "reg_lower"],
            prices={"reg_raise": prices, "reg_lower": prices},
        )
        add_fcess_constraints(m, cfg, bess_power_kw=100.0)

        for t in m.T:
            m.discharge_kw[t].fix(80.0)
            m.charge_kw[t].fix(10.0)
            m.fcess_reg_raise[t].fix(20.0)  # exact boundary
            m.fcess_reg_lower[t].fix(90.0)  # exact boundary

        all_terms = m._obj_terms
        if all_terms:
            m.Objective_fcess = pyo.Objective(expr=sum(all_terms), sense=pyo.maximize)

        solver = pyo.SolverFactory("glpk")
        if not solver.available():
            pytest.skip("GLPK solver not available")

        results = solver.solve(m)
        tc = str(results.solver.termination_condition)
        assert tc in ("optimal", "feasible", "locallyOptimal"), f"Unexpected termination: {tc}"

    def test_revenue_calculation_correctness(self) -> None:
        """Revenue should equal price * enabled MW summed across intervals."""
        import pyomo.environ as pyo

        n = 4
        power_kw = 200.0
        reg_raise_mw = 50.0
        prices = [8.0, 10.0, 12.0, 9.0]
        expected_revenue = sum(prices) * reg_raise_mw

        m = _make_bess_model(n=n, power_kw=power_kw, add_dummy_objective=False)
        cfg = FcessConfig(
            enabled_products=["reg_raise"],
            prices={"reg_raise": prices},
        )
        add_fcess_constraints(m, cfg, bess_power_kw=power_kw)

        for t in m.T:
            m.discharge_kw[t].fix(0.0)
            m.charge_kw[t].fix(0.0)
            m.fcess_reg_raise[t].fix(reg_raise_mw)

        obj_expr = sum(m._obj_terms)
        revenue = pyo.value(obj_expr)
        assert revenue == pytest.approx(expected_revenue)
