"""Tests for app.ui.comparison — ScenarioMetrics, ComparisonTable, generate_narrative."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from app.ui.comparison import ComparisonTable, ScenarioMetrics, generate_narrative

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BASE = ScenarioMetrics(
    name="Base Case",
    npv_aud=500_000.0,
    irr_pct=9.2,
    lcoe_aud_kwh=0.0821,
    lcos_aud_kwh=0.1140,
    simple_payback_years=8.4,
    equity_multiple=2.1,
)

HIGH_SOLAR = ScenarioMetrics(
    name="High Solar",
    npv_aud=612_000.0,
    irr_pct=11.4,
    lcoe_aud_kwh=0.0743,
    lcos_aud_kwh=0.1020,
    simple_payback_years=7.1,
    equity_multiple=2.5,
)

CONSERVATIVE = ScenarioMetrics(
    name="Conservative Prices",
    npv_aud=378_000.0,
    irr_pct=7.6,
    lcoe_aud_kwh=0.0912,
    lcos_aud_kwh=0.1260,
    simple_payback_years=10.2,
    equity_multiple=1.7,
)


# ---------------------------------------------------------------------------
# ScenarioMetrics
# ---------------------------------------------------------------------------


class TestScenarioMetrics:
    def test_fields_stored(self) -> None:
        assert BASE.name == "Base Case"
        assert BASE.npv_aud == 500_000.0
        assert BASE.irr_pct == 9.2
        assert BASE.lcoe_aud_kwh == pytest.approx(0.0821)
        assert BASE.lcos_aud_kwh == pytest.approx(0.1140)
        assert BASE.simple_payback_years == pytest.approx(8.4)
        assert BASE.equity_multiple == pytest.approx(2.1)

    def test_nullable_fields(self) -> None:
        s = ScenarioMetrics(
            name="Minimal",
            npv_aud=0.0,
            irr_pct=None,
            lcoe_aud_kwh=None,
            lcos_aud_kwh=None,
            simple_payback_years=None,
            equity_multiple=None,
        )
        assert s.irr_pct is None
        assert s.lcoe_aud_kwh is None


# ---------------------------------------------------------------------------
# ComparisonTable.to_dataframe
# ---------------------------------------------------------------------------


class TestComparisonTableDataframe:
    def setup_method(self) -> None:
        self.table = ComparisonTable(base=BASE, comparators=[HIGH_SOLAR, CONSERVATIVE])
        self.df = self.table.to_dataframe()

    def test_returns_dataframe(self) -> None:
        assert isinstance(self.df, pd.DataFrame)

    def test_six_metric_rows(self) -> None:
        assert len(self.df) == 6

    def test_metric_column_values(self) -> None:
        metrics = self.df["Metric"].tolist()
        assert "NPV" in metrics
        assert "IRR" in metrics
        assert "LCOE" in metrics
        assert "LCOS" in metrics
        assert "Simple Payback" in metrics
        assert "Equity Multiple" in metrics

    def test_base_case_column_present(self) -> None:
        assert "Base Case" in self.df.columns

    def test_comparator_columns_present(self) -> None:
        assert "High Solar" in self.df.columns
        assert "Conservative Prices" in self.df.columns

    def test_delta_columns_present(self) -> None:
        assert "High Solar Δ" in self.df.columns
        assert "High Solar Δ%" in self.df.columns
        assert "Conservative Prices Δ" in self.df.columns
        assert "Conservative Prices Δ%" in self.df.columns

    def test_npv_base_value(self) -> None:
        row = self.df[self.df["Metric"] == "NPV"].iloc[0]
        assert row["Base Case"] == pytest.approx(500_000.0)

    def test_npv_delta_high_solar(self) -> None:
        row = self.df[self.df["Metric"] == "NPV"].iloc[0]
        expected_delta = 612_000.0 - 500_000.0
        assert row["High Solar Δ"] == pytest.approx(expected_delta)

    def test_npv_delta_pct_high_solar(self) -> None:
        row = self.df[self.df["Metric"] == "NPV"].iloc[0]
        expected_pct = (112_000.0 / 500_000.0) * 100.0
        assert row["High Solar Δ%"] == pytest.approx(expected_pct)

    def test_conservative_negative_delta(self) -> None:
        row = self.df[self.df["Metric"] == "NPV"].iloc[0]
        assert row["Conservative Prices Δ"] == pytest.approx(378_000.0 - 500_000.0)
        assert row["Conservative Prices Δ%"] < 0

    def test_unit_column_present(self) -> None:
        assert "Unit" in self.df.columns
        row = self.df[self.df["Metric"] == "NPV"].iloc[0]
        assert row["Unit"] == "AUD"

    def test_empty_comparators_no_delta_cols(self) -> None:
        table = ComparisonTable(base=BASE, comparators=[])
        df = table.to_dataframe()
        assert len(df) == 6
        assert "Base Case" in df.columns
        delta_cols = [c for c in df.columns if "Δ" in c]
        assert delta_cols == []

    def test_null_fields_produce_none_deltas(self) -> None:
        s = ScenarioMetrics(
            name="No IRR",
            npv_aud=400_000.0,
            irr_pct=None,
            lcoe_aud_kwh=None,
            lcos_aud_kwh=None,
            simple_payback_years=None,
            equity_multiple=None,
        )
        table = ComparisonTable(base=BASE, comparators=[s])
        df = table.to_dataframe()
        irr_row = df[df["Metric"] == "IRR"].iloc[0]
        assert irr_row["No IRR Δ"] is None or (
            isinstance(irr_row["No IRR Δ"], float) and math.isnan(irr_row["No IRR Δ"])
        )
        assert irr_row["No IRR Δ%"] is None or (
            isinstance(irr_row["No IRR Δ%"], float) and math.isnan(irr_row["No IRR Δ%"])
        )


# ---------------------------------------------------------------------------
# ComparisonTable.all_scenarios
# ---------------------------------------------------------------------------


class TestAllScenarios:
    def test_all_scenarios_includes_base(self) -> None:
        table = ComparisonTable(base=BASE, comparators=[HIGH_SOLAR])
        all_s = table.all_scenarios
        assert all_s[0] is BASE

    def test_all_scenarios_length(self) -> None:
        table = ComparisonTable(base=BASE, comparators=[HIGH_SOLAR, CONSERVATIVE])
        assert len(table.all_scenarios) == 3

    def test_all_scenarios_order(self) -> None:
        table = ComparisonTable(base=BASE, comparators=[HIGH_SOLAR, CONSERVATIVE])
        names = [s.name for s in table.all_scenarios]
        assert names == ["Base Case", "High Solar", "Conservative Prices"]


# ---------------------------------------------------------------------------
# generate_narrative
# ---------------------------------------------------------------------------


class TestGenerateNarrative:
    def test_no_comparators_returns_placeholder(self) -> None:
        table = ComparisonTable(base=BASE, comparators=[])
        result = generate_narrative(table)
        assert "No comparator" in result

    def test_returns_string(self) -> None:
        table = ComparisonTable(base=BASE, comparators=[HIGH_SOLAR])
        assert isinstance(generate_narrative(table), str)

    def test_contains_comparator_name(self) -> None:
        table = ComparisonTable(base=BASE, comparators=[HIGH_SOLAR])
        narrative = generate_narrative(table)
        assert "High Solar" in narrative

    def test_contains_base_name(self) -> None:
        table = ComparisonTable(base=BASE, comparators=[HIGH_SOLAR])
        narrative = generate_narrative(table)
        assert "Base Case" in narrative

    def test_two_comparators_two_paragraphs(self) -> None:
        table = ComparisonTable(base=BASE, comparators=[HIGH_SOLAR, CONSERVATIVE])
        narrative = generate_narrative(table)
        # Each comparator gets its own paragraph separated by double newline
        assert "High Solar" in narrative
        assert "Conservative Prices" in narrative
        assert "\n\n" in narrative

    def test_improvement_direction_for_npv_increase(self) -> None:
        table = ComparisonTable(base=BASE, comparators=[HIGH_SOLAR])
        narrative = generate_narrative(table)
        # NPV is higher → should say "improves"
        assert "improves" in narrative

    def test_worsening_direction_for_npv_decrease(self) -> None:
        table = ComparisonTable(base=BASE, comparators=[CONSERVATIVE])
        narrative = generate_narrative(table)
        # NPV drops → should say "worsens"
        assert "worsens" in narrative

    def test_at_most_three_bullet_points_per_comparator(self) -> None:
        table = ComparisonTable(base=BASE, comparators=[HIGH_SOLAR])
        narrative = generate_narrative(table)
        # Bullet points begin with "  - "
        bullets = [line for line in narrative.splitlines() if line.startswith("  - ")]
        assert len(bullets) <= 3

    def test_all_null_metrics_handled_gracefully(self) -> None:
        s = ScenarioMetrics(
            name="All Null",
            npv_aud=BASE.npv_aud,  # same as base so delta=0
            irr_pct=None,
            lcoe_aud_kwh=None,
            lcos_aud_kwh=None,
            simple_payback_years=None,
            equity_multiple=None,
        )
        table = ComparisonTable(base=BASE, comparators=[s])
        result = generate_narrative(table)
        assert isinstance(result, str)
