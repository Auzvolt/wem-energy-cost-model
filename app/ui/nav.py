"""Sidebar navigation renderer."""

from __future__ import annotations

import streamlit as st

# Pages visible to each role
_ADMIN_PAGES = [
    ("📥 Data Status", "pages/1_📥_Data_Status"),
    ("📋 Project Designer", "pages/2_📋_Project_Designer"),
    ("📈 Results", "pages/3_📈_Results"),
    ("📊 Reports", "pages/4_📊_Reports"),
    ("⚙️ Assumptions", "pages/5_⚙️_Assumptions"),
]

_ANALYST_PAGES = [
    ("📥 Data Status", "pages/1_📥_Data_Status"),
    ("📋 Project Designer", "pages/2_📋_Project_Designer"),
    ("📈 Results", "pages/3_📈_Results"),
    ("📊 Reports", "pages/4_📊_Reports"),
    # Assumptions is admin-only
]


def render_sidebar(role: str) -> None:
    """Render the sidebar with role-appropriate navigation links.

    Parameters
    ----------
    role:
        User role string — ``"admin"`` or ``"analyst"``.
    """
    pages = _ADMIN_PAGES if role == "admin" else _ANALYST_PAGES

    with st.sidebar:
        st.markdown("## Navigation")
        for label, _ in pages:
            st.markdown(f"- {label}")
        st.divider()
        if role == "admin":
            st.caption("🔑 Admin access")
        else:
            st.caption("👤 Analyst access")
