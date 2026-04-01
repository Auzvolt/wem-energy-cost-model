"""Tests for app.ui.charts — dispatch profile, cashflow waterfall, sensitivity tornado."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import pytest

from app.financial.sensitivity import SensitivityResult, SensitivityRow
from app.ui.charts import (
    cashflow_waterfall_chart,
    dispatch_profile_chart,
    sensitivity_tornado_chart,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dispatch_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-15", periods=3, freq="1h"),
            "solar_mw": [1.0, 2.0, 1.5],
            "bess_charge_mw": [-0.5, -1.0, -0.5],
            "bess_discharge_mw": [0.3, 0.0, 0.5],
            "grid_import_mw": [0.2, 0.0, 0.1],
            "grid_export_mw": [0.0, 1.0, 0.5],
        }
    )


def _make_cashflow_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "stream": [
                "Energy Revenue",
                "FCESS Revenue",
                "Capacity Revenue",
                "Network Savings",
                "OpEx",
                "Net Cashflow",
            ],
            "value_aud": [100_000, 20_000, 10_000, 5_000, -30_000, 105_000],
        }
    )


def _make_sensitivity_result() -> SensitivityResult:
    return SensitivityResult(
        base_npv=500_000.0,
        rows=[
            SensitivityRow(
                parameter="capex_aud_kw",
                base_value=1_000.0,
                low_value=700.0,
                high_value=1_300.0,
                npv_low=620_000.0,
                npv_high=380_000.0,
            ),
            SensitivityRow(
                parameter="energy_price_aud_mwh",
                base_value=80.0,
                low_value=48.0,
                high_value=112.0,
                npv_low=350_000.0,
                npv_high=650_000.0,
            ),
        ],
    )


# ---------------------------------------------------------------------------
# dispatch_profile_chart
# ---------------------------------------------------------------------------


def test_dispatch_profile_chart_returns_figure() -> None:
    fig = dispatch_profile_chart(_make_dispatch_df())
    assert isinstance(fig, go.Figure)


def test_dispatch_profile_chart_has_traces() -> None:
    fig = dispatch_profile_chart(_make_dispatch_df())
    assert len(fig.data) > 0


def test_dispatch_profile_chart_title() -> None:
    fig = dispatch_profile_chart(_make_dispatch_df())
    assert fig.layout.title.text == "Dispatch Profile"


def test_dispatch_profile_chart_empty_returns_figure() -> None:
    fig = dispatch_profile_chart(pd.DataFrame())
    assert isinstance(fig, go.Figure)


def test_dispatch_profile_chart_empty_has_annotation() -> None:
    fig = dispatch_profile_chart(pd.DataFrame())
    assert any("No dispatch" in (a.text or "") for a in fig.layout.annotations)


# ---------------------------------------------------------------------------
# cashflow_waterfall_chart
# ---------------------------------------------------------------------------


def test_cashflow_waterfall_returns_figure() -> None:
    fig = cashflow_waterfall_chart(_make_cashflow_df())
    assert isinstance(fig, go.Figure)


def test_cashflow_waterfall_has_waterfall_trace() -> None:
    fig = cashflow_waterfall_chart(_make_cashflow_df())
    assert any(isinstance(t, go.Waterfall) for t in fig.data)


def test_cashflow_waterfall_title() -> None:
    fig = cashflow_waterfall_chart(_make_cashflow_df())
    assert "Waterfall" in (fig.layout.title.text or "")


def test_cashflow_waterfall_empty_returns_figure() -> None:
    fig = cashflow_waterfall_chart(pd.DataFrame())
    assert isinstance(fig, go.Figure)


def test_cashflow_waterfall_empty_has_annotation() -> None:
    fig = cashflow_waterfall_chart(pd.DataFrame())
    assert any("No cashflow" in (a.text or "") for a in fig.layout.annotations)


# ---------------------------------------------------------------------------
# sensitivity_tornado_chart
# ---------------------------------------------------------------------------


def test_sensitivity_tornado_returns_figure() -> None:
    fig = sensitivity_tornado_chart(_make_sensitivity_result())
    assert isinstance(fig, go.Figure)


def test_sensitivity_tornado_has_two_bar_traces() -> None:
    fig = sensitivity_tornado_chart(_make_sensitivity_result())
    bar_traces = [t for t in fig.data if isinstance(t, go.Bar)]
    assert len(bar_traces) == 2


def test_sensitivity_tornado_title() -> None:
    fig = sensitivity_tornado_chart(_make_sensitivity_result())
    assert "Tornado" in (fig.layout.title.text or "")


def test_sensitivity_tornado_empty_rows_returns_figure() -> None:
    fig = sensitivity_tornado_chart(SensitivityResult(base_npv=0.0, rows=[]))
    assert isinstance(fig, go.Figure)


def test_sensitivity_tornado_empty_has_annotation() -> None:
    fig = sensitivity_tornado_chart(SensitivityResult(base_npv=0.0, rows=[]))
    assert any("No sensitivity" in (a.text or "") for a in fig.layout.annotations)


def test_sensitivity_tornado_bar_lengths_reflect_deltas() -> None:
    """Low-scenario bars should be negative for high-capex (NPV penalty)."""
    result = _make_sensitivity_result()
    fig = sensitivity_tornado_chart(result)
    low_trace = next(t for t in fig.data if isinstance(t, go.Bar) and t.name == "Low scenario")
    # capex_aud_kw low NPV=620k > base 500k → positive delta
    assert low_trace.x[0] == pytest.approx(620_000.0 - 500_000.0)
