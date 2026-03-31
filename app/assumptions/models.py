"""Assumption library Pydantic v2 models.

Provides type-safe representations of versioned assumption sets and entries,
covering tariffs, capex, degradation curves, and solar yield profiles.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class AssumptionCategory(StrEnum):
    TARIFF = "tariff"
    CAPEX = "capex"
    OPEX = "opex"
    DEGRADATION = "degradation"
    SOLAR_YIELD = "solar_yield"


# ---------------------------------------------------------------------------
# Core models
# ---------------------------------------------------------------------------


class AssumptionEntry(BaseModel):
    """A single key-value assumption entry within a set."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    set_id: uuid.UUID
    category: AssumptionCategory
    key: str
    value: Any  # JSONB — can be dict, list, float, str
    unit: str | None = None
    source: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"from_attributes": True}


class AssumptionSet(BaseModel):
    """A versioned snapshot of all assumptions, valid from `effective_from`."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    name: str
    description: str | None = None
    author: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    effective_from: date
    superseded_by: uuid.UUID | None = None
    entries: list[AssumptionEntry] = Field(default_factory=list)

    model_config = {"from_attributes": True}

    @property
    def is_active(self) -> bool:
        return self.superseded_by is None


# ---------------------------------------------------------------------------
# Typed wrappers for specific assumption categories
# ---------------------------------------------------------------------------


class TariffScheduleAssumption(BaseModel):
    """Parsed tariff schedule assumption entry value."""

    name: str
    tou_windows: list[dict[str, Any]] = Field(default_factory=list)
    block_tiers: list[dict[str, Any]] = Field(default_factory=list)
    demand_charge: dict[str, Any] | None = None
    dlf: float = 1.0
    tlf: float = 1.0
    daily_charge: float = 0.0  # $/day fixed charge


class CapexAssumption(BaseModel):
    """Capital expenditure assumption for an asset class."""

    asset_type: str  # "solar_pv", "bess", "ocgt", etc.
    cost_per_unit: float  # e.g. $/kW or $/kWh
    unit: str  # "$/kW", "$/kWh", "$/unit"
    installation_factor: float = 1.0  # multiplier for installed cost vs equipment cost
    contingency_pct: float = 0.0  # contingency as a fraction (e.g. 0.10 = 10%)
    currency_year: int = 2025


class DegradationCurve(BaseModel):
    """Battery degradation model parameters."""

    chemistry: str  # "NMC", "LFP", etc.
    capacity_fade_pct_per_cycle: float  # % of nameplate per full-equivalent cycle
    calendar_degradation_pct_per_year: float  # % of nameplate per year (calendar aging)
    eol_capacity_pct: float = 80.0  # end-of-life threshold (% nameplate)


class SolarYieldProfile(BaseModel):
    """Monthly normalised capacity factors for a location (1 kWp basis)."""

    location: str
    monthly_cf: list[float]  # 12 values, Jan-Dec, fraction of installed kWp
    tracking: str = "fixed"  # "fixed", "single_axis", "dual_axis"
    tilt_deg: float | None = None
    azimuth_deg: float | None = None  # 0=North (southern hemisphere convention)

    def annual_yield_kwh_per_kwp(self) -> float:
        """Approximate annual yield assuming 730h/month average."""
        return sum(cf * 730 for cf in self.monthly_cf)
