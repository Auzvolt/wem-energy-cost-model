"""Streamlit application entry point."""

import streamlit as st

st.set_page_config(
    page_title="WEM Energy Cost Modelling Tool",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("⚡ WEM Energy Cost Modelling Tool")
st.markdown(
    """
    Welcome to the WEM Energy Cost Modelling Tool — an in-house platform for modelling
    energy costs in the Western Australian Wholesale Electricity Market (SWIS).

    **Status:** 🚧 Under active development

    ### Modules
    - 📊 **Data Pipeline** — AEMO WA market data ingestion
    - ⚙️ **Optimisation Engine** — Pyomo LP/MILP co-optimisation
    - 📐 **Assumption Library** — Versioned tariffs, asset parameters, yield profiles
    - 💰 **Financial Model** — NPV, IRR, LCOE, cashflow forecasting
    - 📄 **Reports** — PDF and Excel export
    """
)

st.info("Use the sidebar to navigate between modules once they are available.")
