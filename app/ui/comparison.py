"""Scenario comparison utilities: metrics table, delta computation, narrative summary."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class ScenarioMetrics:
    """Financial metrics snapshot for a single scenario."""

    name: str
    npv_aud: float
    irr_pct: float | None  # percent, e.g. 9.2 (not 0.092)
    lcoe_aud_kwh: float | None
    lcos_aud_kwh: float | None
    simple_payback_years: float | None
    equity_multiple: float | None


@dataclass
class ComparisonTable:
    """Side-by-side metrics table with deltas vs the base case."""

    base: ScenarioMetrics
    comparators: list[ScenarioMetrics] = field(default_factory=list)

    # Ordered display labels (and the corresponding ScenarioMetrics attribute)
    METRIC_ROWS: list[tuple[str, str, str]] = field(
        default_factory=lambda: [
            ("NPV", "npv_aud", "AUD"),
            ("IRR", "irr_pct", "%"),
            ("LCOE", "lcoe_aud_kwh", "$/kWh"),
            ("LCOS", "lcos_aud_kwh", "$/kWh"),
            ("Simple Payback", "simple_payback_years", "years"),
            ("Equity Multiple", "equity_multiple", "x"),
        ]
    )

    def to_dataframe(self) -> pd.DataFrame:
        """Build a tidy DataFrame with one row per metric.

        Columns:
            Metric, Unit, <base_name>, <comp1_name>, <comp1_delta>, <comp1_pct>, ...
        """
        rows: list[dict[str, object]] = []
        for label, attr, unit in self.METRIC_ROWS:
            row: dict[str, object] = {"Metric": label, "Unit": unit}
            base_val = getattr(self.base, attr)
            row[self.base.name] = base_val
            for comp in self.comparators:
                comp_val = getattr(comp, attr)
                row[comp.name] = comp_val
                if base_val is not None and comp_val is not None and base_val != 0:
                    delta = comp_val - base_val
                    pct = delta / abs(base_val) * 100.0
                    row[f"{comp.name} Δ"] = delta
                    row[f"{comp.name} Δ%"] = pct
                else:
                    row[f"{comp.name} Δ"] = None
                    row[f"{comp.name} Δ%"] = None
            rows.append(row)
        return pd.DataFrame(rows)

    @property
    def all_scenarios(self) -> list[ScenarioMetrics]:
        return [self.base] + self.comparators


# ---------------------------------------------------------------------------
# Narrative generation
# ---------------------------------------------------------------------------

_BETTER_HIGHER = {"npv_aud", "irr_pct", "equity_multiple"}  # higher = better
_BETTER_LOWER = {"lcoe_aud_kwh", "lcos_aud_kwh", "simple_payback_years"}  # lower = better

_METRIC_LABEL: dict[str, str] = {
    "npv_aud": "NPV",
    "irr_pct": "IRR",
    "lcoe_aud_kwh": "LCOE",
    "lcos_aud_kwh": "LCOS",
    "simple_payback_years": "Simple Payback",
    "equity_multiple": "Equity Multiple",
}

_METRIC_FORMAT: dict[str, str] = {
    "npv_aud": "${delta:+,.0f}",
    "irr_pct": "{delta:+.1f}pp",
    "lcoe_aud_kwh": "${delta:+.4f}/kWh",
    "lcos_aud_kwh": "${delta:+.4f}/kWh",
    "simple_payback_years": "{delta:+.1f} years",
    "equity_multiple": "{delta:+.2f}x",
}


def _is_improvement(attr: str, delta: float) -> bool:
    if attr in _BETTER_HIGHER:
        return delta > 0
    if attr in _BETTER_LOWER:
        return delta < 0
    return False


def generate_narrative(table: ComparisonTable) -> str:
    """Generate a plain-English summary of the top-3 metric changes per comparator.

    Uses string templates only — no LLM.
    """
    if not table.comparators:
        return "No comparator scenarios selected."

    paragraphs: list[str] = []
    metric_attrs = [attr for _, attr, _ in table.METRIC_ROWS]

    for comp in table.comparators:
        deltas: list[tuple[float, str]] = []
        for attr in metric_attrs:
            base_val = getattr(table.base, attr)
            comp_val = getattr(comp, attr)
            if base_val is not None and comp_val is not None:
                deltas.append((abs(comp_val - base_val), attr))

        # Sort by absolute delta descending, take top 3
        top3 = sorted(deltas, key=lambda x: x[0], reverse=True)[:3]

        lines: list[str] = [f"**{comp.name}** vs *{table.base.name}* (base case):"]
        for _, attr in top3:
            base_val = getattr(table.base, attr)
            comp_val = getattr(comp, attr)
            if base_val is None or comp_val is None:
                continue
            delta = comp_val - base_val
            pct = delta / abs(base_val) * 100.0 if base_val != 0 else 0.0
            fmt = _METRIC_FORMAT[attr]
            delta_str = fmt.format(delta=delta)
            direction = "improves" if _is_improvement(attr, delta) else "worsens"
            label = _METRIC_LABEL[attr]
            sign = "+" if pct >= 0 else ""
            lines.append(f"  - {label} {direction} by {delta_str} ({sign}{pct:.1f}%)")

        paragraphs.append("\n".join(lines))

    return "\n\n".join(paragraphs)
