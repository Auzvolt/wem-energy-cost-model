"""Dispatch profile comparison chart for GridCog benchmark scenarios (issue #80).

Generates stacked-area dispatch charts for the two GridCog benchmark scenarios
using synthetic 5-minute dispatch profiles derived from scenario parameters.
No external API calls or LP solver required — profiles are generated analytically.

Charts are saved as PNG to tests/validation/outputs/dispatch_profile_<scenario>.png.

Usage:
    python tests/validation/plot_dispatch_profiles.py
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # Non-interactive backend for CI
import matplotlib.pyplot as plt
import numpy as np

from tests.validation.gridcog_reference_cases import ALL_CASES, ReferenceCase

# Output directory
OUTPUT_DIR = Path(__file__).parent / "outputs"

# Time axis: 288 intervals of 5 minutes (one 24-hour day)
N_INTERVALS = 288
INTERVAL_H = 5 / 60  # 5 minutes in hours
HOURS = np.linspace(0, 24, N_INTERVALS, endpoint=False)


def _solar_profile(solar_kwp: float) -> np.ndarray:
    """Generate a synthetic clear-day solar generation profile (kW).

    Uses a sine curve peaking at solar noon (hour 12), non-zero between 6–18h.
    """
    if solar_kwp <= 0:
        return np.zeros(N_INTERVALS)
    profile = np.zeros(N_INTERVALS)
    for i, h in enumerate(HOURS):
        if 6.0 <= h <= 18.0:
            # Normalised angle: 0 at 6h, π at 18h
            angle = math.pi * (h - 6.0) / 12.0
            profile[i] = solar_kwp * math.sin(angle) * 0.85  # 85% peak capacity factor
    return profile


def _bess_profiles(
    bess_power_kw: float,
    bess_energy_kwh: float,
    solar_kwp: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Generate synthetic BESS charge (negative) and discharge (positive) profiles.

    Strategy:
    - With solar: charge during solar peak (10–14h), discharge in evening peak (17–20h)
    - Without solar: charge overnight off-peak (1–5h), discharge in morning peak (7.5–9.5h)

    Returns (charge_kw, discharge_kw) where charge values are negative.
    """
    charge = np.zeros(N_INTERVALS)
    discharge = np.zeros(N_INTERVALS)

    if solar_kwp > 0:
        charge_window = (10.0, 14.0)
        discharge_window = (17.0, 20.0)
    else:
        charge_window = (1.0, 5.0)
        discharge_window = (7.5, 9.5)

    # Scale power so energy fits within battery capacity
    charge_hours = charge_window[1] - charge_window[0]
    discharge_hours = discharge_window[1] - discharge_window[0]
    energy_limited_power = bess_energy_kwh / max(charge_hours, discharge_hours)
    power = min(bess_power_kw, energy_limited_power)

    for i, h in enumerate(HOURS):
        if charge_window[0] <= h < charge_window[1]:
            charge[i] = -power  # negative = charging
        if discharge_window[0] <= h < discharge_window[1]:
            discharge[i] = power

    return charge, discharge


def generate_dispatch_profile(case: ReferenceCase) -> dict[str, np.ndarray]:
    """Generate synthetic dispatch profile arrays for a reference case.

    Returns dict with keys: solar, bess_charge, bess_discharge, grid_import, grid_export.
    All values in kW (bess_charge is negative).
    """
    # Base load: sized relative to assets
    base_load_kw = case.solar_kwp * 0.6 if case.solar_kwp > 0 else case.bess_power_kw * 1.5

    solar = _solar_profile(case.solar_kwp)
    bess_charge, bess_discharge = _bess_profiles(
        case.bess_power_kw, case.bess_energy_kwh, case.solar_kwp
    )

    # Net injection = solar + bess_discharge + bess_charge (negative) - load
    net = solar + bess_discharge + bess_charge - base_load_kw
    grid_export = np.maximum(net, 0)
    grid_import = np.maximum(-net, 0)

    return {
        "solar": solar,
        "bess_charge": bess_charge,
        "bess_discharge": bess_discharge,
        "grid_import": grid_import,
        "grid_export": grid_export,
    }


def plot_dispatch_profile(case: ReferenceCase, output_path: Path) -> None:
    """Generate and save a stacked-area dispatch chart for a reference case."""
    profiles = generate_dispatch_profile(case)

    fig, ax = plt.subplots(figsize=(14, 6))

    # Positive layers: solar, BESS discharge, grid import
    ax.stackplot(
        HOURS,
        profiles["solar"] / 1000,
        profiles["bess_discharge"] / 1000,
        profiles["grid_import"] / 1000,
        labels=["Solar generation", "BESS discharge", "Grid import"],
        colors=["#f9c74f", "#43aa8b", "#577590"],
        alpha=0.8,
    )
    # Negative layer: BESS charge (already negative)
    ax.stackplot(
        HOURS,
        profiles["bess_charge"] / 1000,
        labels=["BESS charge"],
        colors=["#f3722c"],
        alpha=0.8,
    )
    # Grid export as dashed line
    ax.plot(
        HOURS,
        profiles["grid_export"] / 1000,
        color="#90be6d",
        linewidth=1.5,
        linestyle="--",
        label="Grid export",
    )

    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xlabel("Hour of day")
    ax.set_ylabel("Power (MW)")
    ax.set_title(f"Dispatch Profile — {case.name}")
    ax.set_xlim(0, 24)
    ax.set_xticks(range(0, 25, 2))
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=120, bbox_inches="tight")
    plt.close(fig)


def _scenario_slug(name: str) -> str:
    """Convert a scenario name to a filename-safe slug."""
    slug = re.sub(r"[^\w\s-]", "", name.lower())
    slug = re.sub(r"[\s]+", "_", slug)
    return slug.strip("_")


def main() -> None:
    """Generate dispatch profile charts for all GridCog reference cases."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for case in ALL_CASES:
        slug = _scenario_slug(case.name)
        output_path = OUTPUT_DIR / f"dispatch_profile_{slug}.png"
        plot_dispatch_profile(case, output_path)
        print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
