"""Pydantic v2 row schemas for WEM pipeline ingest validation.

These models validate raw API/CSV row dicts before ORM records are created
and written to the database. Invalid rows are logged and skipped rather than
silently coerced.
"""

from __future__ import annotations

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
        import math

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
        import math

        if not math.isfinite(v):
            raise ValueError(f"price_aud_mwh must be finite, got {v}")
        return v
