"""Pydantic models for the energy asset library — issue #9.

Three asset types are supported:
- GeneratorAsset   (thermal, gas peaker, OCGT/CCGT, coal, solar PV, wind)
- BatteryAsset     (BESS — LFP, NMC, flow batteries)
- DemandResponseAsset (industrial/commercial DR programs)

All models enforce physical consistency constraints via Pydantic validators.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, model_validator


class AssetType(str, Enum):  # noqa: UP042
    """Discriminator for asset sub-types."""

    GENERATOR = "generator"
    BATTERY = "battery"
    DEMAND_RESPONSE = "demand_response"


class BaseAsset(BaseModel):
    """Shared fields for all energy assets."""

    name: str = Field(..., min_length=1, description="Human-readable asset name")
    asset_type: AssetType  # set by subclass

    model_config = {"frozen": False, "use_enum_values": False}


class GeneratorAsset(BaseAsset):
    """Dispatchable or variable generation asset.

    Covers: OCGT, CCGT, coal, gas steam, solar PV, wind, hydro.
    For variable renewables set heat_rate_gj_mwh = 0 and fuel_cost_aud_gj = 0.
    """

    asset_type: AssetType = AssetType.GENERATOR

    technology: str = Field(..., description="Technology string (e.g. 'OCGT', 'solar_pv', 'wind')")
    capacity_kw: Annotated[float, Field(gt=0, description="Nameplate capacity in kW")]
    min_stable_load_kw: Annotated[
        float, Field(ge=0, description="Minimum dispatchable output in kW")
    ]
    heat_rate_gj_mwh: Annotated[
        float, Field(ge=0, description="Heat rate in GJ/MWh (0 for renewables)")
    ]
    fuel_cost_aud_gj: Annotated[float, Field(ge=0, description="Fuel cost in AUD/GJ")]
    variable_om_aud_mwh: Annotated[float, Field(ge=0, description="Variable O&M in AUD/MWh")]
    start_cost_aud: Annotated[float, Field(ge=0, description="Start-up cost in AUD per start")]

    @model_validator(mode="after")
    def min_load_le_capacity(self) -> GeneratorAsset:
        if self.min_stable_load_kw > self.capacity_kw:
            raise ValueError(
                f"min_stable_load_kw ({self.min_stable_load_kw}) must not exceed "
                f"capacity_kw ({self.capacity_kw})"
            )
        return self


class BatteryAsset(BaseAsset):
    """Battery energy storage system (BESS).

    Models LFP, NMC, and flow battery chemistries.
    SoC limits and round-trip efficiency are enforced at construction time.
    """

    asset_type: AssetType = AssetType.BATTERY

    capacity_kwh: Annotated[float, Field(gt=0, description="Usable energy capacity in kWh")]
    power_kw: Annotated[float, Field(gt=0, description="Maximum charge/discharge power in kW")]
    round_trip_efficiency: Annotated[
        float,
        Field(gt=0, le=1.0, description="Round-trip efficiency (0 < η ≤ 1.0)"),
    ]
    soc_min_pct: Annotated[
        float,
        Field(ge=0, lt=1.0, description="Minimum state-of-charge as fraction of capacity (0–1)"),
    ]
    soc_max_pct: Annotated[
        float,
        Field(gt=0, le=1.0, description="Maximum state-of-charge as fraction of capacity (0–1)"),
    ]
    cycle_cost_aud_kwh: Annotated[
        float,
        Field(ge=0, description="Degradation cost per full cycle in AUD/kWh throughput"),
    ]

    @model_validator(mode="after")
    def soc_bounds_valid(self) -> BatteryAsset:
        if self.soc_min_pct >= self.soc_max_pct:
            raise ValueError(
                f"soc_min_pct ({self.soc_min_pct}) must be strictly less than "
                f"soc_max_pct ({self.soc_max_pct})"
            )
        return self


class DemandResponseAsset(BaseAsset):
    """Demand-response program (industrial or commercial load curtailment).

    Represents an aggregated pool of flexible load capable of being dispatched
    as a pseudo-generator in the WEM optimisation.
    """

    asset_type: AssetType = AssetType.DEMAND_RESPONSE

    capacity_kw: Annotated[float, Field(gt=0, description="Available reduction capacity in kW")]
    response_time_min: Annotated[
        float,
        Field(ge=0, description="Time from dispatch signal to full curtailment, in minutes"),
    ]
    availability_hours_per_day: Annotated[
        float,
        Field(ge=0, le=24.0, description="Hours per day the resource is available for dispatch"),
    ]
    cost_aud_mwh: Annotated[
        float,
        Field(ge=0, description="Cost of activating demand response in AUD/MWh curtailed"),
    ]


# Union type for type-safe handling of all asset variants
AnyAsset = GeneratorAsset | BatteryAsset | DemandResponseAsset
