"""Unit tests for the sensitivity analysis engine (financial.sensitivity)."""

from __future__ import annotations

import pytest
from financial.sensitivity import (
    DEFAULT_SENSITIVITY_PARAMS,
    SensitivityParam,
    SensitivityResult,
    SensitivityRow,
    run_sensitivity,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _simple_cashflow_fn(param: SensitivityParam, value: float) -> float:
    """Mock cashflow_fn that returns NPV = value * 1000 for any param."""
    return value * 1_000.0


# ── Tests: SensitivityParam ───────────────────────────────────────────────────


class TestSensitivityParam:
    def test_multiplicative_low(self) -> None:
        p = SensitivityParam(name="capex", base_value=1000.0, low_factor=0.7, high_factor=1.3)
        assert p.low_value == pytest.approx(700.0)

    def test_multiplicative_high(self) -> None:
        p = SensitivityParam(name="capex", base_value=1000.0, low_factor=0.7, high_factor=1.3)
        assert p.high_value == pytest.approx(1300.0)

    def test_additive_low(self) -> None:
        p = SensitivityParam(
            name="discount_rate",
            base_value=0.08,
            low_factor=1.0,
            high_factor=1.0,
            additive_delta=0.02,
        )
        assert p.low_value == pytest.approx(0.06)

    def test_additive_high(self) -> None:
        p = SensitivityParam(
            name="discount_rate",
            base_value=0.08,
            low_factor=1.0,
            high_factor=1.0,
            additive_delta=0.02,
        )
        assert p.high_value == pytest.approx(0.10)


# ── Tests: SensitivityRow ─────────────────────────────────────────────────────


class TestSensitivityRow:
    def test_npv_delta_positive(self) -> None:
        row = SensitivityRow(
            parameter="price",
            base_value=100.0,
            low_value=60.0,
            high_value=140.0,
            npv_low=-500_000.0,
            npv_high=1_000_000.0,
        )
        assert row.npv_delta == pytest.approx(1_500_000.0)

    def test_npv_delta_negative(self) -> None:
        """Cost parameter: high cost → lower NPV → negative delta."""
        row = SensitivityRow(
            parameter="capex",
            base_value=1000.0,
            low_value=700.0,
            high_value=1300.0,
            npv_low=800_000.0,
            npv_high=200_000.0,
        )
        assert row.npv_delta == pytest.approx(-600_000.0)


# ── Tests: run_sensitivity ────────────────────────────────────────────────────


class TestRunSensitivity:
    def _make_params(self) -> list[SensitivityParam]:
        return [
            SensitivityParam(name="price", base_value=100.0, low_factor=0.6, high_factor=1.4),
            SensitivityParam(name="capex", base_value=500.0, low_factor=0.8, high_factor=1.2),
        ]

    def test_rows_count_equals_params(self) -> None:
        params = self._make_params()
        result = run_sensitivity(_simple_cashflow_fn, base_npv=1_000_000.0, params=params)
        assert len(result.rows) == len(params)

    def test_base_npv_stored(self) -> None:
        result = run_sensitivity(_simple_cashflow_fn, base_npv=42_000.0, params=self._make_params())
        assert result.base_npv == pytest.approx(42_000.0)

    def test_rows_sorted_by_abs_npv_delta_descending(self) -> None:
        """Row with the largest |npv_delta| should appear first."""
        params = self._make_params()
        result = run_sensitivity(_simple_cashflow_fn, base_npv=0.0, params=params)
        deltas = [abs(r.npv_delta) for r in result.rows]
        assert deltas == sorted(deltas, reverse=True)

    def test_npv_values_computed_correctly(self) -> None:
        """npv_low and npv_high should be cashflow_fn evaluated at low/high values."""
        params = [SensitivityParam(name="price", base_value=100.0, low_factor=0.6, high_factor=1.4)]
        result = run_sensitivity(_simple_cashflow_fn, base_npv=100_000.0, params=params)
        row = result.rows[0]
        assert row.npv_low == pytest.approx(60.0 * 1_000.0)
        assert row.npv_high == pytest.approx(140.0 * 1_000.0)
        assert row.npv_delta == pytest.approx(140.0 * 1_000.0 - 60.0 * 1_000.0)

    def test_default_params_used_when_none_provided(self) -> None:
        """When params=None, default params should be used."""
        result = run_sensitivity(_simple_cashflow_fn, base_npv=0.0, params=None)
        assert len(result.rows) == len(DEFAULT_SENSITIVITY_PARAMS)

    def test_result_type(self) -> None:
        result = run_sensitivity(_simple_cashflow_fn, base_npv=0.0, params=self._make_params())
        assert isinstance(result, SensitivityResult)
        for row in result.rows:
            assert isinstance(row, SensitivityRow)

    def test_additive_param_in_run(self) -> None:
        """Additive delta params should compute correct low/high values."""
        params = [
            SensitivityParam(
                name="discount_rate",
                base_value=0.08,
                low_factor=1.0,
                high_factor=1.0,
                additive_delta=0.02,
            )
        ]

        def _dr_cashflow_fn(param: SensitivityParam, value: float) -> float:
            # NPV is inverse in discount rate: lower rate → higher NPV
            return 1_000_000.0 / (1 + value)

        result = run_sensitivity(_dr_cashflow_fn, base_npv=0.0, params=params)
        row = result.rows[0]
        # low discount rate (0.06) → higher NPV
        assert row.npv_low > row.npv_high
        assert row.npv_delta < 0  # NPV falls when rate rises
