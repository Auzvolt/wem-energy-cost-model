"""Pydantic v2 row schemas for WEM pipeline ingest validation.

These models validate raw API/CSV row dicts before ORM records are created
and written to the database. Invalid rows are logged and skipped rather than
silently coerced.
"""

from __future__ import annotations

import math
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class FcessPriceRow(BaseModel):
    """Validated row for a FCESS price record."""

    product: str = Field(min_length=1)
    interval_start_utc: datetime
    price_aud_mwh: float

    @field_validator("price_aud_mwh")
    @classmethod
    def price_finite(cls, v: float) -> float:
        """Reject NaN / Inf prices."""
        if not math.isfinite(v):
            raise ValueError(f"price_aud_mwh must be finite, got {v}")
        return v


class WholesalePriceRow(BaseModel):
    """Validated row for an energy or FCESS wholesale market-clearing price."""

    interval_start_utc: datetime
    price_aud_mwh: float
    product: str = Field(min_length=1)
    source_url: str = Field(min_length=1)

    @field_validator("price_aud_mwh")
    @classmethod
    def price_finite(cls, v: float) -> float:
        """Reject NaN / Inf prices."""
        if not math.isfinite(v):
            raise ValueError(f"price_aud_mwh must be finite, got {v}")
        return v


class CapacityPriceRow(BaseModel):
    """Validated row for a Reserve Capacity Mechanism price record.

    Represents a single facility's capacity credit assignment and BRCP
    for a given capacity year.
    """

    capacity_year: str = Field(min_length=1)  # e.g. '2024-25'
    facility_id: str = Field(min_length=1)
    facility_name: str = ""
    capacity_credits_mw: float
    brcp_mwyr: float
    source_url: str = Field(min_length=1)

    @field_validator("capacity_credits_mw", "brcp_mwyr")
    @classmethod
    def value_finite(cls, v: float) -> float:
        """Reject NaN / Inf numeric fields."""
        if not math.isfinite(v):
            raise ValueError(f"value must be finite, got {v}")
        return v
