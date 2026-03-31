"""Western Power tariff engine — TOU, block-tier, and demand charge calculations.

Supports billing-grade calculation of energy and demand charges for WA electricity tariffs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Tariff data models
# ---------------------------------------------------------------------------

_DAY_ABBREVS = {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}
_PYTHON_WEEKDAY = {
    "Mon": 0,
    "Tue": 1,
    "Wed": 2,
    "Thu": 3,
    "Fri": 4,
    "Sat": 5,
    "Sun": 6,
}


class TOUWindow(BaseModel):
    """A time-of-use window (named period within a day/week)."""

    name: str
    start_hour: int = Field(ge=0, le=23)
    end_hour: int = Field(ge=0, le=24)  # 24 = midnight-end
    days: list[str]  # e.g. ["Mon","Tue","Wed","Thu","Fri"]

    model_config = {"frozen": True}

    def applies_to(self, dt: datetime) -> bool:
        """Return True if this window applies to the given datetime."""
        weekday_abbrev = dt.strftime("%a")  # Mon, Tue, ...
        if weekday_abbrev not in self.days:
            return False
        hour = dt.hour
        # end_hour == 24 means up to (but not including) midnight
        if self.start_hour <= self.end_hour:
            return self.start_hour <= hour < self.end_hour
        # Wrap-around (e.g. 22..6)
        return hour >= self.start_hour or hour < self.end_hour


class TOURate(BaseModel):
    """Energy rate for a specific TOU window."""

    window: TOUWindow
    rate_kwh: float = Field(gt=0, description="Energy rate in $/kWh")

    model_config = {"frozen": True}


class BlockTier(BaseModel):
    """A block (step) tier for block tariff structures.

    threshold_kwh: Upper usage boundary for this tier (None = unlimited/final tier).
    rate_kwh: Rate in $/kWh for usage within this tier.
    """

    threshold_kwh: float | None = None  # None means no upper limit
    rate_kwh: float = Field(gt=0)

    model_config = {"frozen": True}


class DemandCharge(BaseModel):
    """Demand charge configuration."""

    rate_per_kva: float = Field(gt=0, description="$/kVA/month")
    window: TOUWindow | None = None  # None means all hours qualify

    model_config = {"frozen": True}

    def applies_to(self, dt: datetime) -> bool:
        if self.window is None:
            return True
        return self.window.applies_to(dt)


class TariffSchedule(BaseModel):
    """Complete tariff schedule.

    Precedence: TOU rates override block tiers. If both are present, TOU takes priority.
    DLF (distribution loss factor) and TLF (transmission loss factor) scale the energy read.
    """

    name: str
    tou_rates: list[TOURate] = Field(default_factory=list)
    block_tiers: list[BlockTier] = Field(default_factory=list)
    demand_charge: DemandCharge | None = None
    dlf: float = Field(default=1.0, gt=0, description="Distribution loss factor")
    tlf: float = Field(default=1.0, gt=0, description="Transmission loss factor")

    model_config = {"frozen": True}

    @property
    def combined_loss_factor(self) -> float:
        return self.dlf * self.tlf


# ---------------------------------------------------------------------------
# Classification helper
# ---------------------------------------------------------------------------


def classify_interval(dt: datetime, schedule: TariffSchedule) -> str:
    """Return the TOU window name that applies to `dt`, or 'off_peak' if none match.

    First match wins (order of tou_rates list determines priority).
    """
    for tou_rate in schedule.tou_rates:
        if tou_rate.window.applies_to(dt):
            return tou_rate.window.name
    return "off_peak"


# ---------------------------------------------------------------------------
# Energy charge calculation
# ---------------------------------------------------------------------------


def calculate_energy_charge(
    intervals_df: pd.DataFrame,
    schedule: TariffSchedule,
) -> float:
    """Calculate total energy charge for the billing period.

    Args:
        intervals_df: DataFrame with columns:
            - ``timestamp`` (datetime, timezone-aware or naive)
            - ``kwh`` (float) — energy in each interval
        schedule: Tariff schedule to apply.

    Returns:
        Total energy charge in $.

    Notes:
        - DLF/TLF are applied multiplicatively: metered kWh × DLF × TLF = billed kWh.
        - If TOU rates are defined, they take precedence over block tiers.
        - Block tiers are applied to total period consumption when no TOU rates exist.
    """
    df = intervals_df.copy()
    clf = schedule.combined_loss_factor
    df["billed_kwh"] = df["kwh"] * clf

    if schedule.tou_rates:
        # Build a lookup: window_name -> rate_kwh
        rate_lookup: dict[str, float] = {}
        for tou in schedule.tou_rates:
            rate_lookup[tou.window.name] = tou.rate_kwh

        df["window"] = df["timestamp"].apply(lambda ts: classify_interval(ts, schedule))
        # Apply TOU rate; off_peak gets rate 0 unless explicitly in TOU list
        # If "off_peak" is not in rate_lookup, charge 0 for those intervals
        df["charge"] = df.apply(
            lambda row: row["billed_kwh"] * rate_lookup.get(row["window"], 0.0),
            axis=1,
        )
        return float(df["charge"].sum())

    if schedule.block_tiers:
        # Apply block tiers to total consumption for the billing period
        total_kwh = float(df["billed_kwh"].sum())
        return _apply_block_tiers(total_kwh, schedule.block_tiers)

    return 0.0


def _apply_block_tiers(total_kwh: float, tiers: list[BlockTier]) -> float:
    """Apply block (step) tariff tiers to a total consumption figure."""
    charge = 0.0
    remaining = total_kwh
    for tier in tiers:
        if remaining <= 0:
            break
        if tier.threshold_kwh is None:
            # Final unlimited tier
            charge += remaining * tier.rate_kwh
            remaining = 0.0
        else:
            portion = min(remaining, tier.threshold_kwh)
            charge += portion * tier.rate_kwh
            remaining -= portion
    return charge


# ---------------------------------------------------------------------------
# Demand charge calculation
# ---------------------------------------------------------------------------


def calculate_demand_charge(
    intervals_df: pd.DataFrame,
    schedule: TariffSchedule,
) -> float:
    """Calculate demand charge for the billing period.

    Args:
        intervals_df: DataFrame with columns:
            - ``timestamp`` (datetime)
            - ``kva`` (float) — apparent power in each interval
        schedule: Tariff schedule.

    Returns:
        Total demand charge in $. Returns 0.0 if no demand charge configured.
    """
    if schedule.demand_charge is None:
        return 0.0

    df = intervals_df.copy()
    dc = schedule.demand_charge

    # Filter to demand window if specified
    if dc.window is not None:
        mask = df["timestamp"].apply(dc.applies_to)
        df = df[mask]

    if df.empty:
        return 0.0

    peak_kva = float(df["kva"].max())
    return peak_kva * dc.rate_per_kva


# ---------------------------------------------------------------------------
# Monthly bill summary
# ---------------------------------------------------------------------------


def calculate_monthly_bill(
    intervals_df: pd.DataFrame,
    schedule: TariffSchedule,
) -> dict[str, Any]:
    """Calculate a complete monthly bill summary.

    Args:
        intervals_df: DataFrame with columns:
            - ``timestamp`` (datetime)
            - ``kwh`` (float) — energy per interval
            - ``kva`` (float, optional) — apparent power (required for demand charge)

    Returns:
        Dict with keys:
            - ``energy_charge`` (float): total energy charge $
            - ``demand_charge`` (float): total demand charge $
            - ``total`` (float): sum of energy + demand
            - one key per TOU window name (float): energy charge breakdown
    """
    clf = schedule.combined_loss_factor
    df = intervals_df.copy()
    df["billed_kwh"] = df["kwh"] * clf

    result: dict[str, Any] = {}

    # Per-window breakdown
    window_charges: dict[str, float] = {}
    if schedule.tou_rates:
        rate_lookup = {t.window.name: t.rate_kwh for t in schedule.tou_rates}
        df["window"] = df["timestamp"].apply(lambda ts: classify_interval(ts, schedule))
        for window_name, rate in rate_lookup.items():
            window_df = df[df["window"] == window_name]
            window_charges[window_name] = float((window_df["billed_kwh"] * rate).sum())

    energy_charge = calculate_energy_charge(intervals_df, schedule)
    demand_charge = (
        calculate_demand_charge(intervals_df[["timestamp", "kva"]], schedule)
        if "kva" in intervals_df.columns and schedule.demand_charge is not None
        else 0.0
    )

    result["energy_charge"] = energy_charge
    result["demand_charge"] = demand_charge
    result["total"] = energy_charge + demand_charge
    result.update(window_charges)

    return result
