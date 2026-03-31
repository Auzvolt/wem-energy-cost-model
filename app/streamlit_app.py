"""WEM Energy Cost Model — Streamlit application entry point.

Run with:
    streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import streamlit as st

from app.ui.auth import login, logout
from app.ui.nav import render_sidebar
from app.ui.session import USER_ROLE, USERNAME

st.set_page_config(
    page_title="WEM Energy Cost Model",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)


def main() -> None:
    """Main application controller."""
    # Authentication gate — must be authenticated to see anything
    if not st.session_state.get(USER_ROLE):
        authenticated = login()
        if not authenticated:
            st.stop()

    role = st.session_state.get(USER_ROLE, "analyst")
    username = st.session_state.get(USERNAME, "")

    # Sidebar: navigation + logout
    render_sidebar(role)
    with st.sidebar:
        st.divider()
        st.write(f"Logged in as **{username}**")
        if st.button("Logout"):
            logout()
            st.rerun()

    # Main content area
    st.title("⚡ WEM Energy Cost Model")
    st.markdown(
        """
        Welcome to the WEM Energy Cost Model for the WA Wholesale Energy Market (SWIS).

        Use the navigation sidebar to access:
        - **Data Status** — pipeline health and last ingest times
        - **Project Designer** — configure assets, scenarios and assumptions
        - **Results** — view optimisation outputs and dispatch schedules
        - **Reports** — export PDF/Excel summaries
        - **Assumptions** *(admin only)* — manage the assumption library
        """
    )


if __name__ == "__main__":
    main()
