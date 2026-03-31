"""Unit tests for BESS asset model (optimisation.bess)."""
from __future__ import annotations

import pyomo.environ as pyo
import pytest
from pydantic import ValidationError

from optimisation.bess import BessConfig, add_bess_constraints, degraded_capacity
from optimisation.model import OptimisationConfig, build_model

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def small_config() -> OptimisationConfig:
    """OptimisationConfig with a short horizon for fast tests."""
    return OptimisationConfig(horizon_intervals=12, interval_minutes=30)


@pytest.fixture()
def bess_config() -> BessConfig:
    """Standard BESS config for tests."""
    return BessConfig(
        capacity_kwh=100.0,
        power_kw=50.0,
        efficiency_rt=0.90,
        soc_min_pct=0.1,
        soc_max_pct=0.9,
        degradation_pct_per_year=2.0,
    )


@pytest.fixture()
def model_with_bess(
    small_config: OptimisationConfig, bess_config: BessConfig
) -> pyo.ConcreteModel:
    """Build a Pyomo model and attach BESS constraints."""
    model = build_model(small_config)
    add_bess_constraints(model, bess_config, interval_minutes=small_config.interval_minutes)
    return model


# ── Tests: model structure ─────────────────────────────────────────────────────


class TestBessModelStructure:
    def test_soc_balance_constraint_count(
        self, model_with_bess: pyo.ConcreteModel, small_config: OptimisationConfig
    ) -> None:
        """SOC balance constraints should equal horizon_intervals - 1."""
        expected = small_config.horizon_intervals - 1
        actual = len(list(model_with_bess.soc_balance))
        assert actual == expected, (
            f"Expected {expected} SOC balance constraints, got {actual}"
        )

    def test_soc_bounds_are_set(
        self,
        model_with_bess: pyo.ConcreteModel,
        bess_config: BessConfig,
        small_config: OptimisationConfig,
    ) -> None:
        """SoC variables should have lb = soc_min and ub = soc_max."""
        soc_min = bess_config.soc_min_pct * bess_config.capacity_kwh
        soc_max = bess_config.soc_max_pct * bess_config.capacity_kwh
        for t in model_with_bess.T:
            assert model_with_bess.soc_kwh[t].lb == pytest.approx(soc_min)
            assert model_with_bess.soc_kwh[t].ub == pytest.approx(soc_max)

    def test_charge_bounds_are_set(
        self, model_with_bess: pyo.ConcreteModel, bess_config: BessConfig
    ) -> None:
        """Charge variables should have lb=0, ub=power_kw."""
        for t in model_with_bess.T:
            assert model_with_bess.charge_kw[t].lb == pytest.approx(0.0)
            assert model_with_bess.charge_kw[t].ub == pytest.approx(bess_config.power_kw)

    def test_discharge_bounds_are_set(
        self, model_with_bess: pyo.ConcreteModel, bess_config: BessConfig
    ) -> None:
        """Discharge variables should have lb=0, ub=power_kw."""
        for t in model_with_bess.T:
            assert model_with_bess.discharge_kw[t].lb == pytest.approx(0.0)
            assert model_with_bess.discharge_kw[t].ub == pytest.approx(bess_config.power_kw)

    def test_terminal_constraint_present(
        self, model_with_bess: pyo.ConcreteModel
    ) -> None:
        """Terminal SOC constraint should be present."""
        assert hasattr(model_with_bess, "soc_terminal")

    def test_charge_discharge_limit_present(
        self, model_with_bess: pyo.ConcreteModel, small_config: OptimisationConfig
    ) -> None:
        """Simultaneous charge/discharge limit should cover all intervals."""
        assert hasattr(model_with_bess, "charge_discharge_limit")
        assert len(list(model_with_bess.charge_discharge_limit)) == small_config.horizon_intervals


# ── Tests: degraded_capacity ───────────────────────────────────────────────────


class TestDegradedCapacity:
    def test_year_zero_returns_nameplate(self, bess_config: BessConfig) -> None:
        """Year 0 should return the nameplate capacity unchanged."""
        result = degraded_capacity(bess_config, year=0)
        assert result == pytest.approx(bess_config.capacity_kwh)

    def test_year_ten_compound_fade(self, bess_config: BessConfig) -> None:
        """Year 10 with 2%/yr should yield 100 * 0.98^10."""
        expected = bess_config.capacity_kwh * (0.98**10)
        result = degraded_capacity(bess_config, year=10)
        assert result == pytest.approx(expected, rel=1e-6)

    def test_year_one(self, bess_config: BessConfig) -> None:
        """Year 1 should reduce capacity by exactly degradation_pct_per_year."""
        expected = bess_config.capacity_kwh * (1 - bess_config.degradation_pct_per_year / 100)
        result = degraded_capacity(bess_config, year=1)
        assert result == pytest.approx(expected, rel=1e-9)

    def test_negative_year_raises(self, bess_config: BessConfig) -> None:
        """Negative year should raise ValueError."""
        with pytest.raises(ValueError, match="year must be >= 0"):
            degraded_capacity(bess_config, year=-1)


# ── Tests: BessConfig validation ──────────────────────────────────────────────


class TestBessConfig:
    def test_defaults(self) -> None:
        """Default config should have sensible values."""
        config = BessConfig(capacity_kwh=200.0, power_kw=100.0)
        assert config.efficiency_rt == pytest.approx(0.9)
        assert config.soc_min_pct == pytest.approx(0.1)
        assert config.soc_max_pct == pytest.approx(0.9)
        assert config.max_daily_cycles == 2
        assert config.degradation_pct_per_year == pytest.approx(2.0)

    def test_invalid_efficiency_raises(self) -> None:
        """Efficiency > 1 should raise validation error."""
        with pytest.raises(ValidationError):  # noqa: B017
            BessConfig(capacity_kwh=100.0, power_kw=50.0, efficiency_rt=1.1)

    def test_invalid_capacity_raises(self) -> None:
        """Zero or negative capacity should raise validation error."""
        with pytest.raises(ValidationError):
            BessConfig(capacity_kwh=0.0, power_kw=50.0)
