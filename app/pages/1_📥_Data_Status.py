"""Data pipeline status page — shows last ingest times and pipeline health."""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Data Status", layout="wide")
st.title("📥 Data Status")
st.info("Pipeline health dashboard coming soon. This page will show last ingest times, data gaps, and trigger manual refreshes.")

st.subheader("Data Sources")
st.markdown("""
| Source | Type | Frequency | Status |
|--------|------|-----------|--------|
| AEMO WA — Trading Prices | 5-min wholesale prices | 30 min | 🟡 Pending |
| AEMO WA — FCESS | Frequency services | 30 min | 🟡 Pending |
| AEMO WA — Facilities | Generator registry | Daily | 🟡 Pending |
| Interval Meter | NEM12 interval data | On demand | 🟡 Pending |
""")
