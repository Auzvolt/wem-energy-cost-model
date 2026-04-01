"""Tests for Reserve Capacity Mechanism (RCM) Pyomo model (issue #95).

Covers:
- CapacityConfig validation: edge cases (zero credits, accredited_mw < credits_mw,
  negative values, threshold bounds, effective_accredited_mw fallback)
- add_capacity_model: no-op when credits=0, availability constraint added,
  availability constraint correct headroom value, objective augmented,
  objective created from scratch, ValueError when credits exceed power rating
"""

from __future__ import annotations

import pyomo.environ as pyo
import pytest
from pydantic import ValidationError

from app.optimisation.capacity import CapacityConfig, add_capacity_model

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bess_model(
    n_intervals: int = 12,
    power_kw: float = 1000.0,
) -> pyo.ConcreteModel:
    """Build a minimal Pyomo BESS model with charge_kw, discharge_kw, and T."""
    m = pyo.ConcreteModel()
    m.T = pyo.Set(initialize=list(range(n_intervals)))
    m.charge_kw = pyo.Var(m.T, domain=pyo.NonNegativeReals, bounds=(0.0, power_kw))
    m.discharge_kw = pyo.Var(m.T, domain=pyo.NonNegativeReals, bounds=(0.0, power_kw))
    return m


def _make_bess_model_with_objective(
    n_intervals: int = 12,
    power_kw: float = 1000.0,
    dispatch_revenue: float = 5000.0,
) -> pyo.ConcreteModel:
    """Minimal BESS model with an existing maximise objective."""
    m = _make_bess_model(n_intervals, power_kw)
    # Simple dispatch revenue objective
    m.objective = pyo.Objective(
        expr=sum(m.discharge_kw[t] * dispatch_revenue for t in m.T),
        sense=pyo.maximize,
    )
    return m


# ---------------------------------------------------------------------------
# CapacityConfig validation
# ---------------------------------------------------------------------------


class TestCapacityConfigValidation:
    def test_defaults(self) -> None:
        cfg = CapacityConfig()
        assert cfg.capacity_credits_mw == 0.0
        assert cfg.accredited_capacity_mw is None
        assert cfg.capacity_price_per_mw_year == 236_000.0
        assert cfg.availability_threshold == 0.85
        assert cfg.trading_intervals_per_year == 17_520

    def test_zero_credits_is_valid(self) -> None:
        cfg = CapacityConfig(capacity_credits_mw=0.0)
        assert cfg.capacity_credits_mw == 0.0

    def test_negative_credits_raises(self) -> None:
        with pytest.raises(ValidationError):
            CapacityConfig(capacity_credits_mw=-1.0)

    def test_negative_accredited_mw_raises(self) -> None:
        with pytest.raises(ValidationError):
            CapacityConfig(capacity_credits_mw=10.0, accredited_capacity_mw=-5.0)

    def test_negative_price_raises(self) -> None:
        with pytest.raises(ValidationError):
            CapacityConfig(capacity_price_per_mw_year=-100.0)

    def test_availability_threshold_above_one_raises(self) -> None:
        with pytest.raises(ValidationError):
            CapacityConfig(availability_threshold=1.01)

    def test_availability_threshold_below_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            CapacityConfig(availability_threshold=-0.01)

    def test_availability_threshold_at_bounds_valid(self) -> None:
        cfg0 = CapacityConfig(availability_threshold=0.0)
        cfg1 = CapacityConfig(availability_threshold=1.0)
        assert cfg0.availability_threshold == 0.0
        assert cfg1.availability_threshold == 1.0

    def test_trading_intervals_per_year_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            CapacityConfig(trading_intervals_per_year=0)

    def test_effective_accredited_mw_falls_back_to_credits(self) -> None:
        cfg = CapacityConfig(capacity_credits_mw=5.0)
        assert cfg.effective_accredited_mw() == 5.0

    def test_effective_accredited_mw_uses_explicit_value(self) -> None:
        cfg = CapacityConfig(capacity_credits_mw=5.0, accredited_capacity_mw=7.0)
        assert cfg.effective_accredited_mw() == 7.0

    def test_accredited_mw_less_than_credits_is_accepted_by_pydantic(self) -> None:
        """Pydantic does not enforce accredited >= credits; business logic handles it."""
        # Should not raise ValidationError — that check is Pyomo-side
        cfg = CapacityConfig(capacity_credits_mw=10.0, accredited_capacity_mw=5.0)
        assert cfg.accredited_capacity_mw == 5.0


# ---------------------------------------------------------------------------
# add_capacity_model: no-op when credits = 0
# ---------------------------------------------------------------------------


class TestAddCapacityModelNoop:
    def test_noop_when_credits_zero(self) -> None:
        m = _make_bess_model()
        cfg = CapacityConfig(capacity_credits_mw=0.0)
        add_capacity_model(m, cfg)
        assert not hasattr(m, "rcm_availability"), "Should not add constraints for 0 credits"
        assert not hasattr(m, "objective"), "Should not add objective for 0 credits"

    def test_noop_does_not_modify_existing_objective(self) -> None:
        m = _make_bess_model_with_objective()
        original_expr = m.objective.expr
        cfg = CapacityConfig(capacity_credits_mw=0.0)
        add_capacity_model(m, cfg)
        # Objective should be unchanged
        assert m.objective.expr is original_expr


# ---------------------------------------------------------------------------
# add_capacity_model: constraint generation
# ---------------------------------------------------------------------------


class TestAddCapacityModelConstraints:
    def test_rcm_availability_constraint_added(self) -> None:
        m = _make_bess_model(n_intervals=12, power_kw=1000.0)
        cfg = CapacityConfig(capacity_credits_mw=0.5, availability_threshold=0.85)
        add_capacity_model(m, cfg)
        assert hasattr(m, "rcm_availability"), "rcm_availability constraint must be present"

    def test_rcm_availability_constraint_covers_all_intervals(self) -> None:
        n = 24
        m = _make_bess_model(n_intervals=n, power_kw=1000.0)
        cfg = CapacityConfig(capacity_credits_mw=0.5)
        add_capacity_model(m, cfg)
        constraint_indices = list(m.rcm_availability.keys())
        assert len(constraint_indices) == n

    def test_availability_headroom_is_correct(self) -> None:
        """charge_kw upper bound (from constraint) should equal power - credits*threshold."""
        power_kw = 2000.0
        credits_mw = 1.0  # 1000 kW
        threshold = 0.8
        m = _make_bess_model(n_intervals=6, power_kw=power_kw)
        cfg = CapacityConfig(capacity_credits_mw=credits_mw, availability_threshold=threshold)
        add_capacity_model(m, cfg)

        expected_max_charge = power_kw - (credits_mw * 1000.0 * threshold)
        # The constraint is: charge_kw[t] <= expected_max_charge
        # Check constraint upper bound for interval 0
        con = m.rcm_availability[0]
        # Constraint body is charge_kw[0], upper bound is expected_max_charge

        upper = pyo.value(con.upper)
        assert abs(upper - expected_max_charge) < 1e-6

    def test_credits_exceed_power_raises_value_error(self) -> None:
        """Credits * threshold > power_kw should raise ValueError."""
        power_kw = 500.0  # 0.5 MW
        m = _make_bess_model(n_intervals=6, power_kw=power_kw)
        cfg = CapacityConfig(
            capacity_credits_mw=1.0,  # 1 MW credits > 0.5 MW asset
            availability_threshold=1.0,
        )
        with pytest.raises(ValueError, match="exceeds asset power rating"):
            add_capacity_model(m, cfg)


# ---------------------------------------------------------------------------
# add_capacity_model: objective augmentation
# ---------------------------------------------------------------------------


class TestAddCapacityModelObjective:
    def test_objective_created_when_absent(self) -> None:
        m = _make_bess_model(n_intervals=12, power_kw=1000.0)
        cfg = CapacityConfig(capacity_credits_mw=1.0)
        add_capacity_model(m, cfg)
        assert hasattr(m, "objective"), "Objective must be created"
        assert m.objective.sense == pyo.maximize

    def test_objective_value_correct_when_created_from_scratch(self) -> None:
        """RCM revenue = credits_mw * price * (n_intervals / intervals_per_year)."""
        n_intervals = 17520  # 1 full year at 30-min resolution
        power_kw = 2000.0
        credits_mw = 1.0
        price = 236_000.0
        m = _make_bess_model(n_intervals=n_intervals, power_kw=power_kw)
        cfg = CapacityConfig(
            capacity_credits_mw=credits_mw,
            capacity_price_per_mw_year=price,
            trading_intervals_per_year=n_intervals,
        )
        add_capacity_model(m, cfg)
        # Fix all variables to 0 and evaluate objective
        for t in m.T:
            m.charge_kw[t].fix(0.0)
            m.discharge_kw[t].fix(0.0)
        obj_val = pyo.value(m.objective)
        expected = credits_mw * price  # 1 year at full credits
        assert abs(obj_val - expected) < 1.0  # within $1

    def test_objective_augmented_when_present(self) -> None:
        """RCM revenue should be ADDED to existing objective, not replace it."""
        n_intervals = 12
        power_kw = 1000.0
        m = _make_bess_model_with_objective(n_intervals=n_intervals, power_kw=power_kw)
        # Fix dispatch to a known value to isolate RCM contribution
        dispatch_val = 100.0
        for t in m.T:
            m.discharge_kw[t].fix(dispatch_val)
            m.charge_kw[t].fix(0.0)

        # dispatch_revenue_per_interval = 5000.0 (matches _make_bess_model_with_objective default)
        pre_rcm_obj = pyo.value(m.objective)  # = dispatch_val * revenue_per_interval * n

        credits_mw = 0.5
        price = 100_000.0
        intervals_per_year = 17520
        cfg = CapacityConfig(
            capacity_credits_mw=credits_mw,
            capacity_price_per_mw_year=price,
            trading_intervals_per_year=intervals_per_year,
        )
        add_capacity_model(m, cfg)

        post_rcm_obj = pyo.value(m.objective)
        rcm_contribution = credits_mw * price * n_intervals / intervals_per_year
        assert abs(post_rcm_obj - (pre_rcm_obj + rcm_contribution)) < 1e-3

    def test_objective_sense_preserved_when_augmented(self) -> None:
        m = _make_bess_model_with_objective()
        original_sense = m.objective.sense
        cfg = CapacityConfig(capacity_credits_mw=0.5)
        add_capacity_model(m, cfg)
        assert m.objective.sense == original_sense
