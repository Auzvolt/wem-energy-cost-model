"""Reports page — PDF and Excel export of scenario results (issue #43)."""

from __future__ import annotations

import tempfile
from typing import Any

import pandas as pd
import streamlit as st

from app.exports.excel_export import ExcelExporter
from app.exports.pdf_export import PDFExporter

st.set_page_config(page_title="Reports", layout="wide")
st.title("📊 Reports")

# ---------------------------------------------------------------------------
# Session-state helper — load results from prior pages if available
# ---------------------------------------------------------------------------

_DEMO_CASHFLOW = pd.DataFrame(
    [
        {
            "year": y,
            "energy_revenue": 120_000.0 * y,
            "fcess_revenue": 12_000.0,
            "capacity_revenue": 25_000.0,
            "network_savings": 6_000.0,
            "total_revenue": 163_000.0 * y,
            "opex_fixed": 35_000.0,
            "opex_variable": 6_500.0,
            "opex_total": 41_500.0,
            "replacement_capex": 0.0,
            "debt_service": 18_000.0,
            "ebitda": 121_500.0 * y,
            "fcff": 121_500.0 * y,
            "fcfe": 103_500.0 * y,
            "fcfe_discounted": 103_500.0 * y / (1.08**y),
        }
        for y in range(1, 11)
    ]
)

_DEMO_RESULTS: dict[str, Any] = {
    "scenario_name": "Demo Scenario",
    "cashflow": _DEMO_CASHFLOW,
    "financial_summary": {
        "npv": 342_800.0,
        "irr": 0.158,
        "lcoe": 82.40,
        "payback_years": 5.7,
    },
    "dispatch_profile": None,
}


def _get_results() -> dict[str, Any]:
    """Return results from session state, falling back to demo data."""
    raw: Any = st.session_state.get("export_results", _DEMO_RESULTS)
    return raw if isinstance(raw, dict) else _DEMO_RESULTS


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

results = _get_results()
scenario_name: str = str(results.get("scenario_name", "Scenario"))

st.subheader(f"Scenario: {scenario_name}")

cashflow: pd.DataFrame | None = results.get("cashflow")
if cashflow is not None and not cashflow.empty:
    with st.expander("📋 Cashflow Preview", expanded=False):
        st.dataframe(cashflow, use_container_width=True)

summary: dict[str, Any] = results.get("financial_summary") or {}
if summary:
    cols = st.columns(4)
    npv = summary.get("npv")
    irr = summary.get("irr")
    lcoe = summary.get("lcoe")
    payback = summary.get("payback_years")
    cols[0].metric("NPV", f"${npv:,.0f}" if isinstance(npv, float) else "N/A")
    cols[1].metric("IRR", f"{irr:.1%}" if isinstance(irr, float) else "N/A")
    cols[2].metric("LCOE", f"${lcoe:.2f}/MWh" if isinstance(lcoe, float) else "N/A")
    cols[3].metric("Payback", f"{payback:.1f} yrs" if isinstance(payback, float) else "N/A")

st.divider()
st.subheader("Download Reports")

col_excel, col_pdf = st.columns(2)

# ---- Excel download ----
with col_excel:
    st.markdown("#### 📗 Excel Workbook")
    st.caption("Multi-sheet workbook: Summary, Cashflow, Dispatch")
    if st.button("Generate Excel", key="gen_excel", use_container_width=True):
        with st.spinner("Generating Excel workbook…"):
            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                tmp_path = tmp.name
            ExcelExporter().export(results, tmp_path)
            with open(tmp_path, "rb") as f:
                excel_bytes = f.read()
        st.download_button(
            label="⬇️ Download .xlsx",
            data=excel_bytes,
            file_name=f"{scenario_name.replace(' ', '_')}_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

# ---- PDF download ----
with col_pdf:
    st.markdown("#### 📕 PDF Report")
    st.caption("Formatted report: summary, cashflow, dispatch tables")
    if st.button("Generate PDF", key="gen_pdf", use_container_width=True):
        with st.spinner("Generating PDF report…"):
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp_path = tmp.name
            PDFExporter().export(results, tmp_path)
            with open(tmp_path, "rb") as f:
                pdf_bytes = f.read()
        st.download_button(
            label="⬇️ Download .pdf",
            data=pdf_bytes,
            file_name=f"{scenario_name.replace(' ', '_')}_report.pdf",
            mime="application/pdf",
            use_container_width=True,
        )

st.divider()
st.caption(
    "💡 Results are populated automatically when you run a scenario from the Results page. "
    "Demo data is shown when no scenario has been run in this session."
)
