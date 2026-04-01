"""PDF report export for scenario results — issue #43.

Generates a formatted PDF using ReportLab.  The report contains:

- Title page with scenario name and generation timestamp
- Financial summary table (NPV, IRR, LCOE, payback)
- Year-by-year cashflow table
- Dispatch profile table (when provided)
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# Colour palette (RGB 0–255 tuples, converted to 0–1 floats for ReportLab)
_DARK_BLUE = (0.122, 0.286, 0.490)  # #1F497D
_LIGHT_GREY = (0.933, 0.933, 0.933)  # #EEEEEE
_WHITE = (1.0, 1.0, 1.0)
_BLACK = (0.0, 0.0, 0.0)

_CASHFLOW_HEADERS = [
    ("year", "Year"),
    ("energy_revenue", "Energy Rev ($)"),
    ("fcess_revenue", "FCESS Rev ($)"),
    ("capacity_revenue", "Capacity Rev ($)"),
    ("total_revenue", "Total Rev ($)"),
    ("opex_total", "OPEX ($)"),
    ("ebitda", "EBITDA ($)"),
    ("fcfe", "FCFE ($)"),
    ("fcfe_discounted", "Disc. FCFE ($)"),
]

_DISPATCH_HEADERS = [
    ("interval", "Interval"),
    ("dispatch_kw", "Dispatch (kW)"),
    ("soc_pct", "SoC (%)"),
]


def _rl_colour(rgb: tuple[float, float, float]) -> Any:
    """Return a ReportLab Color from an (r, g, b) 0–1 tuple."""
    from reportlab.lib.colors import Color

    return Color(*rgb)


class PDFExporter:
    """Generates formatted PDF reports from simulation results."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def export(self, results: dict[str, Any], output_path: str) -> str:
        """Generate a PDF report and write it to *output_path*.

        Args:
            results: Dictionary that **must** contain:
                - ``"scenario_name"`` (str)
                - ``"cashflow"`` (pd.DataFrame | None)
                - ``"financial_summary"`` (dict with keys npv, irr, lcoe, payback_years)
                - ``"dispatch_profile"`` (pd.DataFrame | None)
            output_path: Destination file path (created / overwritten).

        Returns:
            Absolute path to the generated PDF file.
        """
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )

        abs_path = os.path.abspath(output_path)
        scenario_name: str = str(results.get("scenario_name", "Scenario"))
        generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

        doc = SimpleDocTemplate(
            abs_path,
            pagesize=A4,
            leftMargin=2 * cm,
            rightMargin=2 * cm,
            topMargin=2 * cm,
            bottomMargin=2 * cm,
        )

        styles = getSampleStyleSheet()
        story: list[Any] = []

        # ---- Title ----
        story.append(Paragraph(f"<b>Scenario Report: {scenario_name}</b>", styles["Title"]))
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph(f"Generated: {generated_at}", styles["Normal"]))
        story.append(Spacer(1, 0.6 * cm))

        # ---- Financial summary ----
        story.append(Paragraph("<b>Financial Summary</b>", styles["Heading2"]))
        story.append(Spacer(1, 0.2 * cm))
        story.append(self._summary_table(results, Table, TableStyle))
        story.append(Spacer(1, 0.6 * cm))

        # ---- Cashflow ----
        cashflow: pd.DataFrame | None = results.get("cashflow")
        if cashflow is not None and not cashflow.empty:
            story.append(Paragraph("<b>Year-by-Year Cashflow</b>", styles["Heading2"]))
            story.append(Spacer(1, 0.2 * cm))
            story.append(self._cashflow_table(cashflow, Table, TableStyle))
            story.append(Spacer(1, 0.6 * cm))

        # ---- Dispatch profile ----
        dispatch: pd.DataFrame | None = results.get("dispatch_profile")
        if dispatch is not None and not dispatch.empty:
            story.append(Paragraph("<b>Dispatch Profile</b>", styles["Heading2"]))
            story.append(Spacer(1, 0.2 * cm))
            story.append(self._dispatch_table(dispatch, Table, TableStyle))

        doc.build(story)
        logger.info("PDF report written to %s", abs_path)
        return abs_path

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _table_style(self, TableStyle: Any) -> Any:
        """Return a base TableStyle with header formatting."""
        header_bg = _rl_colour(_DARK_BLUE)
        alt_bg = _rl_colour(_LIGHT_GREY)
        return TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), header_bg),
                ("TEXTCOLOR", (0, 0), (-1, 0), _rl_colour(_WHITE)),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 9),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [_rl_colour(_WHITE), alt_bg]),
                ("FONTSIZE", (0, 1), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.5, _rl_colour((0.7, 0.7, 0.7))),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )

    def _fmt(self, value: Any) -> str:
        """Format a numeric value as a comma-separated string."""
        if isinstance(value, float):
            return f"{value:,.2f}"
        return str(value) if value is not None else "N/A"

    def _summary_table(
        self,
        results: dict[str, Any],
        Table: Any,
        TableStyle: Any,
    ) -> Any:
        summary: dict[str, Any] = results.get("financial_summary") or {}
        irr = summary.get("irr")
        data = [
            ["Metric", "Value"],
            ["NPV ($)", self._fmt(summary.get("npv"))],
            ["IRR", f"{irr:.1%}" if isinstance(irr, float) else "N/A"],
            ["LCOE ($/MWh)", self._fmt(summary.get("lcoe"))],
            ["Payback Period (years)", self._fmt(summary.get("payback_years"))],
        ]
        t = Table(data, colWidths=[9, 6])
        t.setStyle(self._table_style(TableStyle))
        return t

    def _cashflow_table(
        self,
        df: pd.DataFrame,
        Table: Any,
        TableStyle: Any,
    ) -> Any:
        present = [(col, label) for col, label in _CASHFLOW_HEADERS if col in df.columns]
        headers = [label for _, label in present]
        rows = [headers]
        for _, row in df.iterrows():
            rows.append([self._fmt(row.get(col)) for col, _ in present])
        col_width = 17.0 / max(len(headers), 1)
        t = Table(rows, colWidths=[col_width] * len(headers))
        t.setStyle(self._table_style(TableStyle))
        return t

    def _dispatch_table(
        self,
        df: pd.DataFrame,
        Table: Any,
        TableStyle: Any,
    ) -> Any:
        present = [(col, label) for col, label in _DISPATCH_HEADERS if col in df.columns]
        known = {c for c, _ in _DISPATCH_HEADERS}
        for col in df.columns:
            if col not in known:
                present.append((col, col))
        headers = [label for _, label in present]
        rows = [headers]
        for _, row in df.iterrows():
            rows.append([self._fmt(row.get(col)) for col, _ in present])
        col_width = 17.0 / max(len(headers), 1)
        t = Table(rows, colWidths=[col_width] * len(headers))
        t.setStyle(self._table_style(TableStyle))
        return t
