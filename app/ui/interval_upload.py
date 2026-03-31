"""Streamlit upload widget for interval meter data."""

from __future__ import annotations

import streamlit as st


def render_upload_widget() -> tuple[str, bytes] | None:
    """Render a file uploader for interval meter data.

    Returns:
        tuple of (filename, file_bytes) if a file is uploaded, None otherwise.
    """
    uploaded_file = st.file_uploader(
        "Upload interval meter data",
        type=["csv", "txt"],
        help="Upload NEM12 or CSV format interval data",
    )

    if uploaded_file is None:
        return None

    file_bytes = uploaded_file.read()
    return (uploaded_file.name, file_bytes)
