"""Results page — optimisation outputs and dispatch visualisation."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.financial.sensitivity import SensitivityResult, SensitivityRow
from app.ui.charts import (
    cashflow_waterfall_chart,
    dispatch_profile_chart,
    sensitivity_tornado_chart,
)

st.set_page_config(page_title="Results", layout="wide")
st.title("📈 Results")

st.info(
    "Showing synthetic demo data. Connect a solved scenario to populate live results.",
    icon="ℹ️",
)

# ---------------------------------------------------------------------------
# Dispatch Profile
# ---------------------------------------------------------------------------
st.subheader("Dispatch Profile")

_dispatch_demo = pd.DataFrame(
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

fig_dispatch = dispatch_profile_chart(_dispatch_demo)
st.plotly_chart(fig_dispatch, use_container_width=True)
buf_dispatch = fig_dispatch.to_image(format="png")
st.download_button("⬇ Download Dispatch PNG", buf_dispatch, "dispatch_profile.png", "image/png")

# ---------------------------------------------------------------------------
# Annual Cashflow Waterfall
# ---------------------------------------------------------------------------
st.subheader("Annual Cashflow Waterfall")

_cashflow_demo = pd.DataFrame(
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

fig_cashflow = cashflow_waterfall_chart(_cashflow_demo)
st.plotly_chart(fig_cashflow, use_container_width=True)
buf_cashflow = fig_cashflow.to_image(format="png")
st.download_button("⬇ Download Cashflow PNG", buf_cashflow, "cashflow_waterfall.png", "image/png")

# ---------------------------------------------------------------------------
# Sensitivity Tornado
# ---------------------------------------------------------------------------
st.subheader("Sensitivity Analysis")

_demo_result = SensitivityResult(
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

fig_tornado = sensitivity_tornado_chart(_demo_result)
st.plotly_chart(fig_tornado, use_container_width=True)
buf_tornado = fig_tornado.to_image(format="png")
st.download_button("⬇ Download Tornado PNG", buf_tornado, "sensitivity_tornado.png", "image/png")
