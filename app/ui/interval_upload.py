"""Streamlit upload widget interface for interval meter data.

This module provides a UI stub for the interval meter data upload.
The actual Streamlit widgets will be implemented in the Streamlit phase;
this module exposes the interface contract.
"""

from __future__ import annotations

from typing import Literal


def render_interval_upload() -> tuple[bytes | None, Literal["nem12", "csv"]]:
    """Render the interval meter upload widget.

    Returns
    -------
    tuple[bytes | None, Literal["nem12", "csv"]]
        ``(file_bytes, format)`` where ``file_bytes`` is the uploaded file
        content (or ``None`` if no file has been uploaded) and ``format``
        is the user-selected format.

    Notes
    -----
    The Streamlit implementation will call ``st.file_uploader`` here.
    This stub returns ``(None, "csv")`` to keep tests and imports working
    before the Streamlit phase wires up the widgets.
    """
    # Streamlit phase will replace this with:
    #   fmt = st.selectbox("Format", ["csv", "nem12"])
    #   uploaded = st.file_uploader("Upload interval data", type=["csv", "nem12"])
    #   return (uploaded.read() if uploaded else None, fmt)
    return None, "csv"
