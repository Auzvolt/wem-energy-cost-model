"""Pytest validation tests — GridCog benchmark (issue #44).

These tests assert that our NPV and IRR calculations are within the accepted
tolerance of GridCog reference outputs for two synthetic WEM project cases.

All cases use fully synthetic / anonymised data (no real NMI, names, or addresses).
"""

from __future__ import annotations

import pytest

from tests.validation.gridcog_benchmark import run_all_benchmarks, run_case
from tests.validation.gridcog_reference_cases import (
    ALL_CASES,
    CASE_A_BESS_KARRATHA,
    CASE_B_SOLAR_BESS_PERTH,
)


@pytest.mark.validation
class TestGridCogBenchmarkCaseA:
    """Case A — Small C&I BESS (Karratha), 10-year horizon."""

    def test_npv_within_tolerance(self) -> None:
        result = run_case(CASE_A_BESS_KARRATHA)
        assert result.npv_pass, (
            f"Case A NPV outside ±2% tolerance: "
            f"computed={result.computed_npv:.2f}, "
            f"gridcog={result.gridcog_npv:.2f}, "
            f"diff={result.npv_diff_pct:+.3f}%"
        )

    def test_irr_within_tolerance(self) -> None:
        result = run_case(CASE_A_BESS_KARRATHA)
        assert result.computed_irr is not None, "IRR did not converge for Case A"
        assert result.irr_pass, (
            f"Case A IRR outside ±10% relative tolerance: "
            f"computed={result.computed_irr * 100:.2f}%, "
            f"gridcog={result.gridcog_irr * 100:.1f}%, "
            f"diff={result.irr_diff_pct:+.2f}%"
        )

    def test_positive_npv(self) -> None:
        result = run_case(CASE_A_BESS_KARRATHA)
        assert result.computed_npv > 0, "Case A NPV should be positive for a viable BESS project"

    def test_revenue_streams_nonzero(self) -> None:
        result = run_case(CASE_A_BESS_KARRATHA)
        assert result.revenue_bill_savings > 0, "Bill savings should be positive"
        assert result.revenue_fcess > 0, "FCESS revenue should be positive"
        assert result.revenue_capacity > 0, "Capacity revenue should be positive"

    def test_no_solar_revenue(self) -> None:
        """Case A has no solar — PPA savings should be zero."""
        result = run_case(CASE_A_BESS_KARRATHA)
        assert result.revenue_ppa == 0.0, "Case A has no solar — PPA savings must be zero"


@pytest.mark.validation
class TestGridCogBenchmarkCaseB:
    """Case B — Solar + BESS (Perth Metro), 20-year horizon."""

    def test_npv_within_tolerance(self) -> None:
        result = run_case(CASE_B_SOLAR_BESS_PERTH)
        assert result.npv_pass, (
            f"Case B NPV outside ±2% tolerance: "
            f"computed={result.computed_npv:.2f}, "
            f"gridcog={result.gridcog_npv:.2f}, "
            f"diff={result.npv_diff_pct:+.3f}%"
        )

    def test_irr_within_tolerance(self) -> None:
        result = run_case(CASE_B_SOLAR_BESS_PERTH)
        assert result.computed_irr is not None, "IRR did not converge for Case B"
        assert result.irr_pass, (
            f"Case B IRR outside ±10% relative tolerance: "
            f"computed={result.computed_irr * 100:.2f}%, "
            f"gridcog={result.gridcog_irr * 100:.1f}%, "
            f"diff={result.irr_diff_pct:+.2f}%"
        )

    def test_positive_npv(self) -> None:
        result = run_case(CASE_B_SOLAR_BESS_PERTH)
        assert result.computed_npv > 0, (
            "Case B NPV should be positive for a viable solar+BESS project"
        )

    def test_solar_ppa_revenue_nonzero(self) -> None:
        """Case B has solar — PPA savings should be non-zero."""
        result = run_case(CASE_B_SOLAR_BESS_PERTH)
        assert result.revenue_ppa > 0, "Case B has solar — PPA savings must be non-zero"

    def test_case_b_npv_greater_than_case_a(self) -> None:
        """Case B (20yr, larger system) should have a higher NPV than Case A (10yr)."""
        result_a = run_case(CASE_A_BESS_KARRATHA)
        result_b = run_case(CASE_B_SOLAR_BESS_PERTH)
        assert result_b.computed_npv > result_a.computed_npv, (
            "Case B (solar+BESS, 20yr) should exceed Case A (BESS-only, 10yr) in NPV"
        )


@pytest.mark.validation
class TestGridCogBenchmarkSuite:
    """Integration tests for the full benchmark suite."""

    def test_all_cases_pass(self) -> None:
        results = run_all_benchmarks()
        failures = [r for r in results if not r.overall_pass]
        assert not failures, "The following benchmark cases failed:\n" + "\n".join(
            f"  {r.case_name}: {r.notes}" for r in failures
        )

    def test_all_cases_covered(self) -> None:
        results = run_all_benchmarks()
        assert len(results) == len(ALL_CASES), (
            f"Expected {len(ALL_CASES)} benchmark cases, got {len(results)}"
        )
