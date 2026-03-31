"""Tariff bill validation script.

Reads synthetic bill fixtures and interval data, runs the tariff engine,
and prints a comparison table.

Usage:
    python -m tests.validation.tariff_bill_validation

Note: This script operates on anonymised synthetic fixtures only.
No real customer data (NMI, name, address) is present in the fixtures.
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Allow running from repo root
REPO_ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(REPO_ROOT))

FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"
BILLS_DIR = FIXTURES_DIR / "bills"
INTERVAL_DIR = FIXTURES_DIR / "interval_data"


def load_bill_fixture(tariff_code: str) -> dict[str, Any]:
    path = BILLS_DIR / f"{tariff_code}_synthetic_bill_202507.json"
    with open(path) as f:
        return json.load(f)


def load_interval_data(tariff_code: str) -> list[dict[str, Any]]:
    path = INTERVAL_DIR / f"{tariff_code}_synthetic_202507.csv"
    rows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(
                {
                    "interval_start": datetime.fromisoformat(row["interval_start"]),
                    "interval_end": datetime.fromisoformat(row["interval_end"]),
                    "kwh_import": float(row["kwh_import"]),
                    "kw_demand": float(row["kw_demand"]),
                }
            )
    return rows


def calculate_rt2_bill(
    intervals: list[dict[str, Any]],
    daily_rate: float = 1.8543,
    metering_rate: float = 0.25,
    peak_rate_c: float = 39.51,
    offpeak_rate_c: float = 18.23,
) -> dict[str, float]:
    """Calculate RT2 TOU tariff bill from interval data."""
    peak_kwh = 0.0
    offpeak_kwh = 0.0
    days: set[str] = set()

    for row in intervals:
        ts: datetime = row["interval_start"]
        days.add(ts.strftime("%Y-%m-%d"))
        is_peak = ts.weekday() < 5 and 7 <= ts.hour < 23
        if is_peak:
            peak_kwh += row["kwh_import"]
        else:
            offpeak_kwh += row["kwh_import"]

    n_days = len(days)
    peak_charge = peak_kwh * (peak_rate_c / 100)
    offpeak_charge = offpeak_kwh * (offpeak_rate_c / 100)
    daily_charge = daily_rate * n_days
    metering_charge = metering_rate * n_days
    total_exc_gst = peak_charge + offpeak_charge + daily_charge + metering_charge
    gst = total_exc_gst * 0.10

    return {
        "peak_kwh": peak_kwh,
        "offpeak_kwh": offpeak_kwh,
        "n_days": n_days,
        "peak_charge": peak_charge,
        "offpeak_charge": offpeak_charge,
        "daily_charge": daily_charge,
        "metering_charge": metering_charge,
        "total_exc_gst": total_exc_gst,
        "gst": gst,
        "total_inc_gst": total_exc_gst + gst,
    }


def calculate_rt5_bill(
    intervals: list[dict[str, Any]],
    daily_rate: float = 3.45,
    metering_rate: float = 0.35,
    peak_rate_c: float = 20.43,
    offpeak_rate_c: float = 10.12,
    demand_rate: float = 16.50,
) -> dict[str, float]:
    """Calculate RT5 demand + TOU tariff bill from interval data."""
    peak_kwh = 0.0
    offpeak_kwh = 0.0
    max_peak_kw = 0.0
    days: set[str] = set()

    for row in intervals:
        ts: datetime = row["interval_start"]
        days.add(ts.strftime("%Y-%m-%d"))
        is_peak = ts.weekday() < 5 and 7 <= ts.hour < 23
        if is_peak:
            peak_kwh += row["kwh_import"]
            if row["kw_demand"] > max_peak_kw:
                max_peak_kw = row["kw_demand"]
        else:
            offpeak_kwh += row["kwh_import"]

    n_days = len(days)
    peak_charge = peak_kwh * (peak_rate_c / 100)
    offpeak_charge = offpeak_kwh * (offpeak_rate_c / 100)
    demand_charge = max_peak_kw * demand_rate
    daily_charge = daily_rate * n_days
    metering_charge = metering_rate * n_days
    total_exc_gst = peak_charge + offpeak_charge + demand_charge + daily_charge + metering_charge
    gst = total_exc_gst * 0.10

    return {
        "peak_kwh": peak_kwh,
        "offpeak_kwh": offpeak_kwh,
        "max_peak_kw": max_peak_kw,
        "n_days": n_days,
        "peak_charge": peak_charge,
        "offpeak_charge": offpeak_charge,
        "demand_charge": demand_charge,
        "daily_charge": daily_charge,
        "metering_charge": metering_charge,
        "total_exc_gst": total_exc_gst,
        "gst": gst,
        "total_inc_gst": total_exc_gst + gst,
    }


def validate_bill(tariff_code: str) -> dict[str, Any]:
    """Run bill validation for a given tariff code."""
    bill = load_bill_fixture(tariff_code)
    intervals = load_interval_data(tariff_code)

    if tariff_code == "RT2":
        calculated = calculate_rt2_bill(intervals)
    elif tariff_code == "RT5":
        calculated = calculate_rt5_bill(intervals)
    else:
        raise ValueError(f"Unsupported tariff code: {tariff_code}")

    billed_total = bill["total_exc_gst"]
    calc_total = calculated["total_exc_gst"]
    pct_diff = abs(calc_total - billed_total) / billed_total * 100

    return {
        "tariff_code": tariff_code,
        "fixture_note": bill.get("fixture_note", ""),
        "billed_total_exc_gst": billed_total,
        "calculated_total_exc_gst": calc_total,
        "pct_difference": pct_diff,
        "within_1pct": pct_diff <= 1.0,
        "calculated_breakdown": calculated,
    }


def print_validation_table(result: dict[str, Any]) -> None:
    bd = result["calculated_breakdown"]
    print(f"\n{'='*60}")
    print(f"  {result['tariff_code']} Bill Validation")
    print(f"  NOTE: {result['fixture_note']}")
    print(f"{'='*60}")
    print(f"  {'Component':<35} {'Calculated':>12}")
    print(f"  {'-'*50}")

    if result["tariff_code"] == "RT2":
        print(f"  {'Peak kWh':<35} {bd['peak_kwh']:>12.1f}")
        print(f"  {'Off-peak kWh':<35} {bd['offpeak_kwh']:>12.1f}")
        print(f"  {'Peak energy charge ($)':<35} {bd['peak_charge']:>12.2f}")
        print(f"  {'Off-peak energy charge ($)':<35} {bd['offpeak_charge']:>12.2f}")
        print(f"  {'Daily supply charge ($)':<35} {bd['daily_charge']:>12.2f}")
        print(f"  {'Metering charge ($)':<35} {bd['metering_charge']:>12.2f}")
    elif result["tariff_code"] == "RT5":
        print(f"  {'Peak kWh':<35} {bd['peak_kwh']:>12.1f}")
        print(f"  {'Off-peak kWh':<35} {bd['offpeak_kwh']:>12.1f}")
        print(f"  {'Max peak demand (kW)':<35} {bd['max_peak_kw']:>12.1f}")
        print(f"  {'Peak energy charge ($)':<35} {bd['peak_charge']:>12.2f}")
        print(f"  {'Off-peak energy charge ($)':<35} {bd['offpeak_charge']:>12.2f}")
        print(f"  {'Demand charge ($)':<35} {bd['demand_charge']:>12.2f}")
        print(f"  {'Daily supply charge ($)':<35} {bd['daily_charge']:>12.2f}")
        print(f"  {'Metering charge ($)':<35} {bd['metering_charge']:>12.2f}")

    print(f"  {'-'*50}")
    print(f"  {'Total exc GST (calculated) ($)':<35} {result['calculated_total_exc_gst']:>12.2f}")
    print(f"  {'Total exc GST (billed) ($)':<35} {result['billed_total_exc_gst']:>12.2f}")
    print(f"  {'Difference (%)':<35} {result['pct_difference']:>12.3f}%")
    status = "PASS ✓" if result["within_1pct"] else "FAIL ✗"
    print(f"  {'Within ±1% threshold:':<35} {status:>12}")
    print(f"{'='*60}")


def main() -> int:
    print("Tariff Bill Validation Report")
    print("Fixtures: synthetic/anonymised — no real customer data")

    all_pass = True
    for tariff_code in ["RT2", "RT5"]:
        result = validate_bill(tariff_code)
        print_validation_table(result)
        if not result["within_1pct"]:
            all_pass = False

    if all_pass:
        print("\nAll validation cases PASSED (within ±1%).")
        return 0
    else:
        print("\nSome validation cases FAILED. See above for details.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
