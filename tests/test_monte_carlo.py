"""Tests for Monte Carlo uncertainty modelling (issue #27)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.uncertainty import (
    NormalDistribution,
    UncertaintyConfig,
    UniformDistribution,
)
from app.simulation.monte_carlo import (
    MonteCarloResults,
    ScenarioResult,
    generate_price_traces,
    run_monte_carlo,
)

# ---------------------------------------------------------------------------
# UncertaintyConfig validation
# ---------------------------------------------------------------------------


class TestUncertaintyConfig:
    def test_default_values(self) -> None:
        cfg = UncertaintyConfig()
        assert cfg.n_scenarios == 100
        assert cfg.seed == 42
        assert cfg.distributions == {}

    def test_n_scenarios_lower_bound(self) -> None:
        with pytest.raises(ValidationError):
            UncertaintyConfig(n_scenarios=9)

    def test_n_scenarios_upper_bound(self) -> None:
        with pytest.raises(ValidationError):
            UncertaintyConfig(n_scenarios=1001)

    def test_n_scenarios_at_bounds(self) -> None:
        cfg10 = UncertaintyConfig(n_scenarios=10)
        cfg1000 = UncertaintyConfig(n_scenarios=1000)
        assert cfg10.n_scenarios == 10
        assert cfg1000.n_scenarios == 1000

    def test_unknown_product_raises(self) -> None:
        with pytest.raises(ValidationError, match="Unknown product codes"):
            UncertaintyConfig(
                distributions={"UNKNOWN_PRODUCT": NormalDistribution(mean=50.0, std=10.0)}
            )

    def test_fcess_rocof_nonzero_mean_raises(self) -> None:
        with pytest.raises(ValidationError, match="FCESS_ROCOF mean must be 0.0"):
            UncertaintyConfig(
                distributions={
                    "FCESS_ROCOF": NormalDistribution(mean=5.0, std=1.0)
                }
            )

    def test_fcess_rocof_zero_mean_valid(self) -> None:
        cfg = UncertaintyConfig(
            distributions={"FCESS_ROCOF": NormalDistribution(mean=0.0, std=0.5)}
        )
        assert cfg.distributions["FCESS_ROCOF"].mean == 0.0

    def test_valid_all_products(self) -> None:
        cfg = UncertaintyConfig(
            distributions={
                "ENERGY": NormalDistribution(mean=80.0, std=15.0),
                "FCESS_REG_RAISE": NormalDistribution(mean=10.0, std=2.0),
                "FCESS_REG_LOWER": NormalDistribution(mean=10.0, std=2.0),
                "FCESS_CONT_RAISE": NormalDistribution(mean=8.0, std=1.5),
                "FCESS_CONT_LOWER": NormalDistribution(mean=8.0, std=1.5),
                "FCESS_ROCOF": NormalDistribution(mean=0.0, std=0.0),
            }
        )
        assert len(cfg.distributions) == 6


class TestUniformDistribution:
    def test_low_must_be_less_than_high(self) -> None:
        with pytest.raises(ValidationError):
            UniformDistribution(mean=10.0, std=0.0, low=20.0, high=10.0)

    def test_equal_low_high_raises(self) -> None:
        with pytest.raises(ValidationError):
            UniformDistribution(mean=10.0, std=0.0, low=10.0, high=10.0)

    def test_valid_uniform(self) -> None:
        dist = UniformDistribution(mean=50.0, std=5.0, low=40.0, high=60.0)
        assert dist.low == 40.0
        assert dist.high == 60.0


# ---------------------------------------------------------------------------
# generate_price_traces
# ---------------------------------------------------------------------------


class TestGeneratePriceTraces:
    def _config(self, n: int = 10) -> UncertaintyConfig:
        return UncertaintyConfig(
            n_scenarios=n,
            seed=7,
            distributions={
                "ENERGY": NormalDistribution(mean=80.0, std=10.0),
                "FCESS_REG_RAISE": NormalDistribution(mean=12.0, std=2.0),
            },
        )

    def test_returns_correct_number_of_scenarios(self) -> None:
        cfg = self._config(n=15)
        traces = generate_price_traces(cfg, n_intervals=48)
        assert len(traces) == 15

    def test_returns_correct_n_intervals(self) -> None:
        cfg = self._config(n=10)
        traces = generate_price_traces(cfg, n_intervals=96)
        for trace in traces:
            for product, prices in trace.items():
                assert len(prices) == 96, f"{product} should have 96 intervals"

    def test_contains_configured_products(self) -> None:
        cfg = self._config(n=10)
        traces = generate_price_traces(cfg, n_intervals=24)
        for trace in traces:
            assert "ENERGY" in trace
            assert "FCESS_REG_RAISE" in trace

    def test_fixed_seed_reproducible(self) -> None:
        cfg = self._config(n=10)
        traces1 = generate_price_traces(cfg, n_intervals=24)
        traces2 = generate_price_traces(cfg, n_intervals=24)
        for t1, t2 in zip(traces1, traces2, strict=True):
            assert t1["ENERGY"] == t2["ENERGY"]
            assert t1["FCESS_REG_RAISE"] == t2["FCESS_REG_RAISE"]

    def test_energy_prices_clamped(self) -> None:
        """High std forces some samples outside ±1000; they must be clamped."""
        cfg = UncertaintyConfig(
            n_scenarios=50,
            seed=42,
            distributions={"ENERGY": NormalDistribution(mean=0.0, std=5000.0)},
        )
        traces = generate_price_traces(cfg, n_intervals=100)
        for trace in traces:
            for price in trace["ENERGY"]:
                assert -1000.0 <= price <= 1000.0, f"Price {price} outside WEM bounds"


# ---------------------------------------------------------------------------
# run_monte_carlo
# ---------------------------------------------------------------------------


class TestRunMonteCarlo:
    def _basic_config(self, n: int = 50) -> UncertaintyConfig:
        return UncertaintyConfig(
            n_scenarios=n,
            seed=0,
            distributions={"ENERGY": NormalDistribution(mean=80.0, std=5.0)},
        )

    def test_returns_correct_type(self) -> None:
        cfg = self._basic_config()
        results = run_monte_carlo(
            base_revenue_per_mw=50_000.0,
            capacity_mw=5.0,
            capex_total=3_000_000.0,
            uncertainty_config=cfg,
            n_intervals=100,
        )
        assert isinstance(results, MonteCarloResults)

    def test_n_scenarios_matches(self) -> None:
        cfg = self._basic_config(n=30)
        results = run_monte_carlo(50_000.0, 5.0, 3_000_000.0, cfg, n_intervals=50)
        assert results.n_scenarios == 30
        assert len(results.scenario_results) == 30

    def test_scenario_results_are_scenario_result_instances(self) -> None:
        cfg = self._basic_config(n=10)
        results = run_monte_carlo(50_000.0, 5.0, 3_000_000.0, cfg, n_intervals=50)
        for sr in results.scenario_results:
            assert isinstance(sr, ScenarioResult)

    def test_p10_lte_p50_lte_p90_npv(self) -> None:
        cfg = self._basic_config(n=100)
        results = run_monte_carlo(50_000.0, 10.0, 2_000_000.0, cfg, n_intervals=200)
        assert results.p10_npv <= results.p50_npv <= results.p90_npv

    def test_p10_lte_p50_lte_p90_revenue(self) -> None:
        cfg = self._basic_config(n=100)
        results = run_monte_carlo(50_000.0, 10.0, 2_000_000.0, cfg, n_intervals=200)
        assert results.p10_revenue <= results.p50_revenue <= results.p90_revenue

    def test_fixed_seed_reproducible(self) -> None:
        cfg = self._basic_config(n=20)
        r1 = run_monte_carlo(40_000.0, 5.0, 1_500_000.0, cfg, n_intervals=50)
        r2 = run_monte_carlo(40_000.0, 5.0, 1_500_000.0, cfg, n_intervals=50)
        assert r1.p50_npv == r2.p50_npv
        assert r1.p50_revenue == r2.p50_revenue

    def test_negative_npv_when_capex_very_high(self) -> None:
        cfg = self._basic_config(n=20)
        results = run_monte_carlo(
            base_revenue_per_mw=1.0,  # tiny revenue
            capacity_mw=1.0,
            capex_total=1_000_000_000.0,  # massive capex
            uncertainty_config=cfg,
            n_intervals=50,
        )
        assert results.p90_npv < 0.0

    def test_no_energy_dist_uses_base_revenue(self) -> None:
        """Without ENERGY distribution, revenue should equal base_revenue_per_mw * capacity_mw."""
        cfg = UncertaintyConfig(n_scenarios=10, seed=1, distributions={})
        base = 60_000.0
        cap = 2.0
        results = run_monte_carlo(base, cap, 500_000.0, cfg, n_intervals=50)
        expected_revenue = base * cap
        for sr in results.scenario_results:
            assert abs(sr.annual_revenue - expected_revenue) < 0.01

    def test_positive_irr_when_revenue_exceeds_capex(self) -> None:
        """With sufficient revenue, IRR should be computable (non-None)."""
        cfg = self._basic_config(n=10)
        results = run_monte_carlo(
            base_revenue_per_mw=500_000.0,  # very high revenue per MW
            capacity_mw=10.0,
            capex_total=1_000_000.0,  # low capex
            uncertainty_config=cfg,
            n_intervals=100,
        )
        # At least some scenarios should have a computable IRR
        irr_values = [sr.irr for sr in results.scenario_results if sr.irr is not None]
        assert len(irr_values) > 0
