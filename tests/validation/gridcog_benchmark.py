"""GridCog benchmark runner.

Computes NPV and IRR for each reference case using the project's financial
metrics module and compares against the GridCog reference values.

Run standalone::

    python -m tests.validation.gridcog_benchmark

Or called from pytest via tests/test_gridcog_benchmark.py.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.financial.metrics import irr, npv
from tests.validation.gridcog_reference_cases import ALL_CASES, ReferenceCase


@dataclass
class BenchmarkResult:
    """Result for a single reference case."""

    case_name: str
    gridcog_npv: float
    computed_npv: float
    npv_diff_pct: float
    npv_pass: bool

    gridcog_irr: float
    computed_irr: float | None
    irr_diff_pct: float | None
    irr_pass: bool

    revenue_bill_savings: float
    revenue_fcess: float
    revenue_capacity: float
    revenue_ppa: float
    revenue_total_annual: float

    notes: list[str]

    @property
    def overall_pass(self) -> bool:
        return self.npv_pass and self.irr_pass


def run_case(case: ReferenceCase) -> BenchmarkResult:
    """Run financial benchmark for a single reference case."""
    cashflows = case.annual_cashflows

    # Compute NPV using project's financial metrics module
    computed_npv = npv(case.discount_rate, cashflows)
    npv_diff_pct = (computed_npv - case.gridcog_npv) / abs(case.gridcog_npv) * 100.0
    npv_pass = abs(npv_diff_pct) <= case.npv_tolerance * 100.0

    # Compute IRR
    computed_irr = irr(cashflows)
    if computed_irr is not None:
        irr_diff_pct = (computed_irr - case.gridcog_irr) / abs(case.gridcog_irr) * 100.0
        # IRR tolerance: ±10% relative (i.e. if GridCog IRR=12%, accept 10.8%–13.2%)
        irr_pass = abs(irr_diff_pct) <= 10.0
    else:
        irr_diff_pct = None
        irr_pass = False

    notes: list[str] = []
    if not npv_pass:
        notes.append(
            f"NPV FAIL: diff={npv_diff_pct:+.2f}% exceeds ±{case.npv_tolerance * 100:.0f}% tolerance"
        )
    if not irr_pass:
        if irr_diff_pct is not None:
            notes.append(f"IRR FAIL: diff={irr_diff_pct:+.2f}% exceeds ±10% tolerance")
        else:
            notes.append("IRR FAIL: could not converge")

    return BenchmarkResult(
        case_name=case.name,
        gridcog_npv=case.gridcog_npv,
        computed_npv=computed_npv,
        npv_diff_pct=npv_diff_pct,
        npv_pass=npv_pass,
        gridcog_irr=case.gridcog_irr,
        computed_irr=computed_irr,
        irr_diff_pct=irr_diff_pct,
        irr_pass=irr_pass,
        revenue_bill_savings=case.revenue.bill_savings_annual,
        revenue_fcess=case.revenue.fcess_revenue_annual,
        revenue_capacity=case.revenue.capacity_revenue_annual,
        revenue_ppa=case.revenue.ppa_savings_annual,
        revenue_total_annual=case.revenue.total_annual,
        notes=notes,
    )


def run_all_benchmarks() -> list[BenchmarkResult]:
    """Run all reference cases and return results."""
    return [run_case(c) for c in ALL_CASES]


def print_report(results: list[BenchmarkResult]) -> None:
    """Print a human-readable summary of benchmark results to stdout."""
    print("\n" + "=" * 70)
    print("  GridCog Benchmark Report")
    print("=" * 70)
    for r in results:
        status = "✅ PASS" if r.overall_pass else "❌ FAIL"
        print(f"\n{status}  {r.case_name}")
        print(
            f"  NPV:  GridCog=${r.gridcog_npv:>12,.0f}  Computed=${r.computed_npv:>12,.2f}  Diff={r.npv_diff_pct:+.3f}%"
        )
        irr_str = f"{r.computed_irr * 100:.2f}%" if r.computed_irr is not None else "n/a"
        print(f"  IRR:  GridCog={r.gridcog_irr * 100:.1f}%         Computed={irr_str}")
        print("  Revenue breakdown (annual):")
        print(f"    Bill savings:  ${r.revenue_bill_savings:>10,.0f}")
        print(f"    FCESS:         ${r.revenue_fcess:>10,.0f}")
        print(f"    Capacity:      ${r.revenue_capacity:>10,.0f}")
        print(f"    PPA/solar:     ${r.revenue_ppa:>10,.0f}")
        print(f"    TOTAL:         ${r.revenue_total_annual:>10,.0f}")
        if r.notes:
            for note in r.notes:
                print(f"  ⚠  {note}")

    all_pass = all(r.overall_pass for r in results)
    print("\n" + "=" * 70)
    print(f"  Overall: {'✅ ALL PASS' if all_pass else '❌ FAILURES DETECTED'}")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    results = run_all_benchmarks()
    print_report(results)
    if not all(r.overall_pass for r in results):
        raise SystemExit(1)
