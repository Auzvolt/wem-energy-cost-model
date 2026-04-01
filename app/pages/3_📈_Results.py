"""Results page — dispatch visualisation and scenario comparison."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.financial.sensitivity import SensitivityResult, SensitivityRow
from app.ui.charts import (
    cashflow_waterfall_chart,
    dispatch_profile_chart,
    sensitivity_tornado_chart,
)
from app.ui.comparison import ComparisonTable, ScenarioMetrics, generate_narrative

st.set_page_config(page_title="Results", layout="wide")
st.title("📈 Results")

# ---------------------------------------------------------------------------
# Demo / stub data
# (Replace with live DB queries once scenario runner is wired up)
# ---------------------------------------------------------------------------

_DEMO_SCENARIOS: list[ScenarioMetrics] = [
    ScenarioMetrics(
        name="Base Case",
        npv_aud=500_000.0,
        irr_pct=9.2,
        lcoe_aud_kwh=0.0821,
        lcos_aud_kwh=0.1140,
        simple_payback_years=8.4,
        equity_multiple=2.1,
    ),
    ScenarioMetrics(
        name="High Solar",
        npv_aud=612_000.0,
        irr_pct=11.4,
        lcoe_aud_kwh=0.0743,
        lcos_aud_kwh=0.1020,
        simple_payback_years=7.1,
        equity_multiple=2.5,
    ),
    ScenarioMetrics(
        name="Conservative Prices",
        npv_aud=378_000.0,
        irr_pct=7.6,
        lcoe_aud_kwh=0.0912,
        lcos_aud_kwh=0.1260,
        simple_payback_years=10.2,
        equity_multiple=1.7,
    ),
]

_DISPATCH_DEMO = pd.DataFrame(
    {
        "timestamp": pd.date_range("2024-01-15", periods=24, freq="1h"),
        "solar_mw": [
            0,
            0,
            0,
            0,
            0,
            0,
            0.5,
            1.2,
            2.1,
            2.8,
            3.2,
            3.5,
            3.3,
            3.0,
            2.5,
            1.8,
            0.9,
            0.2,
            0,
            0,
            0,
            0,
            0,
            0,
        ],
        "bess_charge_mw": [
            0,
            0,
            0,
            0,
            0,
            0,
            -0.2,
            -0.5,
            -0.8,
            -1.0,
            -1.2,
            -1.0,
            -0.8,
            -0.5,
            -0.3,
            -0.2,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        ],
        "bess_discharge_mw": [
            0.5,
            0.5,
            0.3,
            0.3,
            0.2,
            0.2,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0.5,
            0.8,
            1.0,
            1.2,
            1.0,
            0.8,
            0.6,
            0.5,
        ],
        "grid_import_mw": [
            0.8,
            0.8,
            0.7,
            0.7,
            0.6,
            0.6,
            0.5,
            0.3,
            0.1,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0.3,
            0.5,
            0.7,
            0.8,
            0.9,
            1.0,
            1.0,
            0.9,
        ],
        "grid_export_mw": [
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0.3,
            0.8,
            1.0,
            1.5,
            1.5,
            1.5,
            1.2,
            0.8,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        ],
    }
)

_CASHFLOW_DEMO = pd.DataFrame(
    {
        "stream": [
            "Energy Revenue",
            "FCESS Revenue",
            "Capacity Revenue",
            "Network Savings",
            "OpEx",
            "Debt Service",
            "Net Cashflow",
        ],
        "value_aud": [180_000, 45_000, 30_000, 15_000, -40_000, -55_000, 175_000],
    }
)

_SENSITIVITY_DEMO = SensitivityResult(
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
        SensitivityRow(
            parameter="discount_rate",
            base_value=0.08,
            low_value=0.06,
            high_value=0.10,
            npv_low=560_000.0,
            npv_high=445_000.0,
        ),
    ],
)

# ---------------------------------------------------------------------------
# Tab layout
# ---------------------------------------------------------------------------

tab_comparison, tab_dispatch, tab_cashflow, tab_sensitivity = st.tabs(
    ["📊 Scenario Comparison", "⚡ Dispatch Profile", "💰 Cashflow", "🌀 Sensitivity"]
)

# ---------------------------------------------------------------------------
# Tab 1 — Scenario Comparison
# ---------------------------------------------------------------------------
with tab_comparison:
    st.subheader("Scenario Comparison")
    st.info(
        "Select 2–6 completed scenarios to compare. "
        "The first selected scenario is the **base case**.",
        icon="ℹ️",
    )

    scenario_names = [s.name for s in _DEMO_SCENARIOS]

    if len(scenario_names) < 2:
        st.warning("⚠️ At least 2 completed scenarios are required for comparison.")
    else:
        base_name = st.radio(
            "Base case scenario",
            options=scenario_names,
            horizontal=True,
            key="base_case",
        )
        comparator_options = [n for n in scenario_names if n != base_name]
        selected_comparators = st.multiselect(
            "Comparator scenarios",
            options=comparator_options,
            default=comparator_options[:1],
            key="comparators",
        )

        if not selected_comparators:
            st.warning("Select at least one comparator scenario.")
        else:
            # Build ComparisonTable from demo data
            lookup = {s.name: s for s in _DEMO_SCENARIOS}
            table = ComparisonTable(
                base=lookup[base_name],
                comparators=[lookup[n] for n in selected_comparators if n in lookup],
            )
            df = table.to_dataframe()

            # Colour-code delta columns: green = improvement, red = worse
            delta_cols = [c for c in df.columns if c.endswith(" Δ%")]

            def _highlight_delta(val: object) -> str:
                if not isinstance(val, (int, float)):
                    return ""
                return "color: green" if float(val) > 0 else "color: red" if float(val) < 0 else ""

            styled = df.style.applymap(_highlight_delta, subset=delta_cols)
            st.dataframe(styled, use_container_width=True, hide_index=True)

            # Narrative summary
            st.subheader("Summary Narrative")
            narrative = generate_narrative(table)
            st.markdown(narrative)

# ---------------------------------------------------------------------------
# Tab 2 — Dispatch Profile
# ---------------------------------------------------------------------------
with tab_dispatch:
    st.subheader("Dispatch Profile")
    fig_dispatch = dispatch_profile_chart(_DISPATCH_DEMO)
    st.plotly_chart(fig_dispatch, use_container_width=True)
    buf_dispatch = fig_dispatch.to_image(format="png")
    st.download_button("⬇ Download Dispatch PNG", buf_dispatch, "dispatch_profile.png", "image/png")

# ---------------------------------------------------------------------------
# Tab 3 — Cashflow Waterfall
# ---------------------------------------------------------------------------
with tab_cashflow:
    st.subheader("Annual Cashflow Waterfall")
    fig_cashflow = cashflow_waterfall_chart(_CASHFLOW_DEMO)
    st.plotly_chart(fig_cashflow, use_container_width=True)
    buf_cashflow = fig_cashflow.to_image(format="png")
    st.download_button(
        "⬇ Download Cashflow PNG", buf_cashflow, "cashflow_waterfall.png", "image/png"
    )

# ---------------------------------------------------------------------------
# Tab 4 — Sensitivity Tornado
# ---------------------------------------------------------------------------
with tab_sensitivity:
    st.subheader("Sensitivity Analysis")
    fig_tornado = sensitivity_tornado_chart(_SENSITIVITY_DEMO)
    st.plotly_chart(fig_tornado, use_container_width=True)
    buf_tornado = fig_tornado.to_image(format="png")
    st.download_button(
        "⬇ Download Tornado PNG", buf_tornado, "sensitivity_tornado.png", "image/png"
    )
