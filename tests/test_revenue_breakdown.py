"""Tests for revenue stream breakdown comparison (issue #81)."""

from __future__ import annotations

import pytest

from tests.validation.gridcog_reference_cases import ALL_CASES, ReferenceCase
from tests.validation.revenue_breakdown import (
    TOLERANCE,
    RevenueBreakdownResult,
    StreamResult,
    compare_revenue_streams,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_case(name_fragment: str) -> ReferenceCase:
    """Return the first ReferenceCase whose name contains *name_fragment*."""
    for case in ALL_CASES:
        if name_fragment.lower() in case.name.lower():
            return case
    raise KeyError(f"No case found matching {name_fragment!r}")


# ---------------------------------------------------------------------------
# StreamResult unit tests
# ---------------------------------------------------------------------------


class TestStreamResult:
    def test_relative_error_zero_reference(self) -> None:
        sr = StreamResult(
            stream="test", modelled_aud=0.0, reference_aud=0.0, tolerance=0.05, passed=True
        )
        assert sr.relative_error == 0.0

    def test_relative_error_nonzero(self) -> None:
        sr = StreamResult(
            stream="test", modelled_aud=105.0, reference_aud=100.0, tolerance=0.05, passed=True
        )
        assert sr.relative_error == pytest.approx(0.05)

    def test_relative_error_negative(self) -> None:
        sr = StreamResult(
            stream="test", modelled_aud=95.0, reference_aud=100.0, tolerance=0.05, passed=True
        )
        assert sr.relative_error == pytest.approx(-0.05)


# ---------------------------------------------------------------------------
# RevenueBreakdownResult unit tests
# ---------------------------------------------------------------------------


class TestRevenueBreakdownResult:
    def test_all_pass_true_when_all_streams_pass(self) -> None:
        result = RevenueBreakdownResult(
            scenario_name="test",
            bill_savings_aud=100.0,
            fcess_aud=50.0,
            capacity_aud=20.0,
            ppa_savings_aud=0.0,
            total_aud=170.0,
            streams=[
                StreamResult("bill_savings", 100.0, 100.0, 0.05, passed=True),
                StreamResult("fcess", 50.0, 50.0, 0.05, passed=True),
            ],
        )
        assert result.all_pass is True

    def test_all_pass_false_when_any_stream_fails(self) -> None:
        result = RevenueBreakdownResult(
            scenario_name="test",
            bill_savings_aud=100.0,
            fcess_aud=50.0,
            capacity_aud=20.0,
            ppa_savings_aud=0.0,
            total_aud=170.0,
            streams=[
                StreamResult("bill_savings", 100.0, 100.0, 0.05, passed=True),
                StreamResult("fcess", 70.0, 50.0, 0.05, passed=False),
            ],
        )
        assert result.all_pass is False

    def test_streams_pass_dict(self) -> None:
        result = RevenueBreakdownResult(
            scenario_name="test",
            bill_savings_aud=0.0,
            fcess_aud=0.0,
            capacity_aud=0.0,
            ppa_savings_aud=0.0,
            total_aud=0.0,
            streams=[
                StreamResult("bill_savings", 100.0, 100.0, 0.05, passed=True),
                StreamResult("fcess", 50.0, 50.0, 0.05, passed=True),
            ],
        )
        assert result.streams_pass == {"bill_savings": True, "fcess": True}


# ---------------------------------------------------------------------------
# compare_revenue_streams — Case A (BESS only, no solar)
# ---------------------------------------------------------------------------


class TestCaseA:
    @pytest.fixture
    def result(self) -> RevenueBreakdownResult:
        return compare_revenue_streams(_get_case("Karratha"))

    def test_result_is_breakdown_result(self, result: RevenueBreakdownResult) -> None:
        assert isinstance(result, RevenueBreakdownResult)

    def test_scenario_name(self, result: RevenueBreakdownResult) -> None:
        assert "karratha" in result.scenario_name.lower()

    def test_has_four_streams(self, result: RevenueBreakdownResult) -> None:
        assert len(result.streams) == 4

    def test_bill_savings_value(self, result: RevenueBreakdownResult) -> None:
        assert result.bill_savings_aud == pytest.approx(26_800.0)

    def test_fcess_value(self, result: RevenueBreakdownResult) -> None:
        assert result.fcess_aud == pytest.approx(14_500.0)

    def test_capacity_value(self, result: RevenueBreakdownResult) -> None:
        assert result.capacity_aud == pytest.approx(6_600.0)

    def test_ppa_is_zero(self, result: RevenueBreakdownResult) -> None:
        assert result.ppa_savings_aud == pytest.approx(0.0)

    def test_total_annual_revenue(self, result: RevenueBreakdownResult) -> None:
        expected = 26_800.0 + 14_500.0 + 6_600.0 + 0.0
        assert result.total_aud == pytest.approx(expected)

    def test_bill_savings_passes(self, result: RevenueBreakdownResult) -> None:
        assert result.streams_pass["bill_savings"] is True

    def test_fcess_passes(self, result: RevenueBreakdownResult) -> None:
        assert result.streams_pass["fcess"] is True

    def test_capacity_passes(self, result: RevenueBreakdownResult) -> None:
        assert result.streams_pass["capacity"] is True

    def test_ppa_passes(self, result: RevenueBreakdownResult) -> None:
        assert result.streams_pass["ppa_savings"] is True

    def test_all_pass(self, result: RevenueBreakdownResult) -> None:
        assert result.all_pass is True


# ---------------------------------------------------------------------------
# compare_revenue_streams — Case B (Solar + BESS)
# ---------------------------------------------------------------------------


class TestCaseB:
    @pytest.fixture
    def result(self) -> RevenueBreakdownResult:
        return compare_revenue_streams(_get_case("Perth"))

    def test_result_is_breakdown_result(self, result: RevenueBreakdownResult) -> None:
        assert isinstance(result, RevenueBreakdownResult)

    def test_scenario_name(self, result: RevenueBreakdownResult) -> None:
        assert "perth" in result.scenario_name.lower()

    def test_has_four_streams(self, result: RevenueBreakdownResult) -> None:
        assert len(result.streams) == 4

    def test_bill_savings_value(self, result: RevenueBreakdownResult) -> None:
        assert result.bill_savings_aud == pytest.approx(12_000.0)

    def test_fcess_value(self, result: RevenueBreakdownResult) -> None:
        assert result.fcess_aud == pytest.approx(8_200.0)

    def test_capacity_value(self, result: RevenueBreakdownResult) -> None:
        assert result.capacity_aud == pytest.approx(4_400.0)

    def test_ppa_value(self, result: RevenueBreakdownResult) -> None:
        assert result.ppa_savings_aud == pytest.approx(32_000.0)

    def test_total_annual_revenue(self, result: RevenueBreakdownResult) -> None:
        expected = 12_000.0 + 8_200.0 + 4_400.0 + 32_000.0
        assert result.total_aud == pytest.approx(expected)

    def test_bill_savings_passes(self, result: RevenueBreakdownResult) -> None:
        assert result.streams_pass["bill_savings"] is True

    def test_fcess_passes(self, result: RevenueBreakdownResult) -> None:
        assert result.streams_pass["fcess"] is True

    def test_capacity_passes(self, result: RevenueBreakdownResult) -> None:
        assert result.streams_pass["capacity"] is True

    def test_ppa_passes(self, result: RevenueBreakdownResult) -> None:
        assert result.streams_pass["ppa_savings"] is True

    def test_all_pass(self, result: RevenueBreakdownResult) -> None:
        assert result.all_pass is True


# ---------------------------------------------------------------------------
# Tolerance constant
# ---------------------------------------------------------------------------


class TestTolerance:
    def test_tolerance_is_five_percent(self) -> None:
        assert pytest.approx(0.05) == TOLERANCE
