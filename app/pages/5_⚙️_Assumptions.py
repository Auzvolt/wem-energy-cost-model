"""Assumptions page — admin-only assumption library management."""

from __future__ import annotations

import streamlit as st

from app.ui.assumptions import render_assumptions_page
from app.ui.session import USER_ROLE

st.set_page_config(page_title="Assumptions", layout="wide")

role = st.session_state.get(USER_ROLE, "analyst")
if role != "admin":
    st.error("🔒 Access denied. This page requires admin privileges.")
    st.stop()

# Persist the loaded assumption set across reruns via session state
assumption_set = st.session_state.get("assumption_set", None)
updated = render_assumptions_page(assumption_set)
if updated is not assumption_set:
    st.session_state["assumption_set"] = updated
