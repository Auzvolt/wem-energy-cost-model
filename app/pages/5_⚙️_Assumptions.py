"""Assumptions page — admin-only assumption library management."""

from __future__ import annotations

import streamlit as st

from app.ui.session import USER_ROLE

st.set_page_config(page_title="Assumptions", layout="wide")

role = st.session_state.get(USER_ROLE, "analyst")
if role != "admin":
    st.error("🔒 Access denied. This page requires admin privileges.")
    st.stop()

st.title("⚙️ Assumptions")
st.info("Assumption library management coming soon. Admins can edit tariff schedules, escalation rates, technical parameters, and price forecasts here.")
