"""Interactive Plotly chart functions for WEM scenario results.

Three chart types:
- Dispatch profile (stacked area)
- Annual cashflow waterfall
- Sensitivity tornado
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from app.financial.sensitivity import SensitivityResult

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
_COLOUR_SOLAR = "#F6C90E"
_COLOUR_BESS_CHARGE = "#2196F3"
_COLOUR_BESS_DISCHARGE = "#FF9800"
_COLOUR_GRID_IMPORT = "#F44336"
_COLOUR_GRID_EXPORT = "#4CAF50"
_COLOUR_POSITIVE = "#4CAF50"
_COLOUR_NEGATIVE = "#F44336"
_COLOUR_TOTAL = "#2196F3"


def _empty_figure(message: str) -> go.Figure:
    """Return a blank figure with a centred annotation."""
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
        showarrow=False,
        font={"size": 16, "color": "gray"},
    )
    fig.update_layout(
        xaxis={"visible": False},
        yaxis={"visible": False},
    )
    return fig


# ---------------------------------------------------------------------------
# Chart 1: Dispatch Profile
# ---------------------------------------------------------------------------


def dispatch_profile_chart(df: pd.DataFrame) -> go.Figure:
    """Stacked-area dispatch profile chart.

    Args:
        df: DataFrame with columns: ``timestamp``, ``solar_mw``,
            ``bess_charge_mw`` (negative = charging), ``bess_discharge_mw``,
            ``grid_import_mw``, ``grid_export_mw``.

    Returns:
        Plotly Figure. If *df* is empty returns a "No data" placeholder.
    """
    if df.empty:
        return _empty_figure("No dispatch data available")

    fig = go.Figure()

    traces: list[tuple[str, str, str]] = [
        ("solar_mw", "Solar", _COLOUR_SOLAR),
        ("bess_charge_mw", "BESS Charge", _COLOUR_BESS_CHARGE),
        ("bess_discharge_mw", "BESS Discharge", _COLOUR_BESS_DISCHARGE),
        ("grid_import_mw", "Grid Import", _COLOUR_GRID_IMPORT),
        ("grid_export_mw", "Grid Export", _COLOUR_GRID_EXPORT),
    ]

    for col, name, colour in traces:
        if col not in df.columns:
            continue
        fig.add_trace(
            go.Scatter(
                x=df["timestamp"],
                y=df[col],
                name=name,
                mode="lines",
                stackgroup="one",
                line={"color": colour},
                hovertemplate="%{y:.2f} MW<extra>" + name + "</extra>",
            )
        )

    fig.update_layout(
        title="Dispatch Profile",
        xaxis_title="Time",
        yaxis_title="MW",
        legend={"orientation": "h", "yanchor": "bottom", "y": -0.3},
        hovermode="x unified",
    )
    return fig


# ---------------------------------------------------------------------------
# Chart 2: Annual Cashflow Waterfall
# ---------------------------------------------------------------------------


def cashflow_waterfall_chart(df: pd.DataFrame) -> go.Figure:
    """Annual cashflow waterfall chart.

    Args:
        df: DataFrame with columns ``stream`` (str) and ``value_aud`` (float).
            The last row is treated as the total (measure = "total").

    Returns:
        Plotly Figure. If *df* is empty returns a "No data" placeholder.
    """
    if df.empty:
        return _empty_figure("No cashflow data available")

    n = len(df)
    measures = ["relative"] * (n - 1) + ["total"]

    increasing_colour = {"marker": {"color": _COLOUR_POSITIVE}}
    decreasing_colour = {"marker": {"color": _COLOUR_NEGATIVE}}
    totals_colour = {"marker": {"color": _COLOUR_TOTAL}}

    fig = go.Figure(
        go.Waterfall(
            name="Cashflow",
            orientation="v",
            measure=measures,
            x=df["stream"].tolist(),
            y=df["value_aud"].tolist(),
            textposition="outside",
            text=[f"${v:,.0f}" for v in df["value_aud"]],
            increasing=increasing_colour,
            decreasing=decreasing_colour,
            totals=totals_colour,
            connector={"line": {"color": "gray", "dash": "dot"}},
        )
    )

    fig.update_layout(
        title="Annual Cashflow Waterfall",
        yaxis_title="AUD",
        showlegend=False,
    )
    return fig


# ---------------------------------------------------------------------------
# Chart 3: Sensitivity Tornado
# ---------------------------------------------------------------------------


def sensitivity_tornado_chart(result: SensitivityResult) -> go.Figure:
    """Horizontal tornado chart for sensitivity analysis.

    Args:
        result: :class:`~app.financial.sensitivity.SensitivityResult` with
            ``base_npv`` and ``rows`` sorted by absolute NPV swing (widest first).

    Returns:
        Plotly Figure. If ``result.rows`` is empty returns a placeholder.
    """
    if not result.rows:
        return _empty_figure("No sensitivity data available")

    parameters = [r.parameter for r in result.rows]
    low_deltas = [r.npv_low - result.base_npv for r in result.rows]
    high_deltas = [r.npv_high - result.base_npv for r in result.rows]

    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            name="Low scenario",
            x=low_deltas,
            y=parameters,
            orientation="h",
            marker_color=_COLOUR_NEGATIVE,
            hovertemplate="%{x:,.0f} AUD<extra>Low</extra>",
        )
    )

    fig.add_trace(
        go.Bar(
            name="High scenario",
            x=high_deltas,
            y=parameters,
            orientation="h",
            marker_color=_COLOUR_POSITIVE,
            hovertemplate="%{x:,.0f} AUD<extra>High</extra>",
        )
    )

    fig.add_vline(x=0, line_width=1, line_dash="solid", line_color="black")

    fig.update_layout(
        title="Sensitivity Tornado Chart",
        xaxis_title="NPV Delta (AUD)",
        barmode="overlay",
        bargap=0.3,
        legend={"orientation": "h", "yanchor": "bottom", "y": -0.25},
    )
    return fig
