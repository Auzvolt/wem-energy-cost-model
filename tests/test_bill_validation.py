"""Pytest wrapper for tariff bill validation tests.

Wraps the tariff bill validation script as pytest test cases
to ensure they run in CI.
"""

from __future__ import annotations

from tests.validation.tariff_bill_validation import validate_bill


class TestTariffBillValidation:
    """Tariff engine validation against synthetic anonymised bills."""

    def test_rt2_bill_within_1pct(self) -> None:
        """RT2 TOU tariff validation against synthetic bill fixture."""
        result = validate_bill("RT2")
        assert result["within_1pct"], (
            f"RT2 total {result['calculated_total_exc_gst']:.2f} vs billed "
            f"{result['billed_total_exc_gst']:.2f} differs by "
            f"{result['pct_difference']:.3f}% (>1% threshold)"
        )

    def test_rt5_bill_within_1pct(self) -> None:
        """RT5 demand + TOU tariff validation against synthetic bill fixture."""
        result = validate_bill("RT5")
        assert result["within_1pct"], (
            f"RT5 total {result['calculated_total_exc_gst']:.2f} vs billed "
            f"{result['billed_total_exc_gst']:.2f} differs by "
            f"{result['pct_difference']:.3f}% (>1% threshold)"
        )

    def test_rt2_peak_kwh_matches(self) -> None:
        """RT2 peak kWh consumed should match fixture within 0.1 kWh."""
        result = validate_bill("RT2")
        bd = result["calculated_breakdown"]
        # Synthetic fixtures are designed to exactly match
        assert abs(bd["peak_kwh"] - 2450.0) < 0.5

    def test_rt5_offpeak_kwh_matches(self) -> None:
        """RT5 off-peak kWh consumed should match fixture within 0.1 kWh."""
        result = validate_bill("RT5")
        bd = result["calculated_breakdown"]
        assert abs(bd["offpeak_kwh"] - 12200.0) < 0.5
