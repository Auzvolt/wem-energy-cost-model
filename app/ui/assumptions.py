"""Streamlit UI stub for assumption set import/export.

Provides a page for admin users to:
- Import an assumption set from a JSON or Excel file
- Export the currently loaded assumption set as JSON or Excel

Wired into the main app navigation as the Assumptions page (admin-only).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import streamlit as st

from app.assumptions.io import (
    export_excel,
    export_json,
    import_excel,
    import_json,
)
from app.assumptions.models import AssumptionSet

if TYPE_CHECKING:
    pass


def render_assumptions_page(assumption_set: AssumptionSet | None = None) -> AssumptionSet | None:
    """Render the assumptions import/export Streamlit page.

    Parameters
    ----------
    assumption_set:
        The currently active assumption set, or ``None`` if none is loaded.

    Returns
    -------
    AssumptionSet | None
        The updated assumption set after import, or the original (possibly
        ``None``) if no import was performed.
    """
    st.header("⚙️ Assumption Library")

    # ------------------------------------------------------------------
    # Import section
    # ------------------------------------------------------------------
    st.subheader("Import assumptions")
    st.caption("Upload a JSON or Excel assumption file to load it into the session.")

    uploaded_file = st.file_uploader(
        "Choose a file",
        type=["json", "xlsx"],
        help="Accepted formats: JSON (.json) and Excel (.xlsx)",
    )

    if uploaded_file is not None:
        file_bytes = uploaded_file.read()
        filename = uploaded_file.name

        try:
            if filename.endswith(".xlsx"):
                imported = import_excel(file_bytes)
            else:
                # Treat as JSON (utf-8)
                imported = import_json(file_bytes.decode("utf-8"))

            st.success(
                f"✅ Imported assumption set: **{imported.name}** ({len(imported.entries)} entries)"
            )
            assumption_set = imported

        except ValueError as exc:
            st.error(f"❌ Import failed: {exc}")

    # ------------------------------------------------------------------
    # Export section
    # ------------------------------------------------------------------
    st.subheader("Export assumptions")

    if assumption_set is None:
        st.info(
            "No assumption set loaded. Import one above, or run a scenario to generate defaults."
        )
    else:
        st.caption(
            f"Currently loaded: **{assumption_set.name}** ({len(assumption_set.entries)} entries)"
        )

        col_json, col_excel = st.columns(2)

        with col_json:
            json_bytes = export_json(assumption_set).encode("utf-8")
            st.download_button(
                label="⬇️ Download as JSON",
                data=json_bytes,
                file_name=f"{assumption_set.name.replace(' ', '_')}.json",
                mime="application/json",
                help="Download assumption set as a JSON file",
            )

        with col_excel:
            excel_bytes = export_excel(assumption_set)
            st.download_button(
                label="⬇️ Download as Excel",
                data=excel_bytes,
                file_name=f"{assumption_set.name.replace(' ', '_')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                help="Download assumption set as an Excel workbook",
            )

    return assumption_set
