"""PPA and offtake contract modelling.

Supports three contract types:
- fixed_price: buyer pays a fixed $/MWh for contracted volume
- floor_share: buyer gets floor price plus a share of upside above floor
- indexed: fixed price escalated by a CPI index factor
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, model_validator

PPAContractType = Literal["fixed_price", "floor_share", "indexed"]


class PPAContract(BaseModel):
    """Configuration for a PPA / offtake contract."""

    contract_type: PPAContractType
    price_per_mwh: float = Field(
        gt=0, description="Base price (fixed, floor, or indexed base) AUD/MWh"
    )
    share_pct: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Merchant upside share (floor_share only)"
    )
    cpi_index: float = Field(default=1.0, gt=0, description="CPI escalation factor")
    volume_shape: Literal["flat"] | list[float] = "flat"
    annual_cap_mwh: float | None = Field(default=None, ge=0)
    term_years: int = Field(default=1, gt=0)

    @model_validator(mode="after")
    def check_floor_share_pct(self) -> PPAContract:
        if self.contract_type == "floor_share" and self.share_pct == 0.0:
            # Allow zero share — means pure floor contract
            pass
        return self


@dataclass
class PPAResult:
    """Revenue breakdown from a PPA contract calculation."""

    contracted_mwh: float
    merchant_mwh: float
    contracted_revenue: float
    merchant_revenue: float
    total_revenue: float


def calculate_ppa_revenue(
    dispatch_df: pd.DataFrame,
    contract: PPAContract,
    mcp_col: str = "mcp_aud_mwh",
    dispatch_col: str = "dispatch_mwh",
) -> PPAResult:
    """Calculate contracted and merchant revenue for a given dispatch profile.

    Args:
        dispatch_df: DataFrame with dispatch volume and market clearing price per interval.
        contract: PPAContract configuration.
        mcp_col: Column name for market clearing price (AUD/MWh).
        dispatch_col: Column name for dispatch volume (MWh per interval).

    Returns:
        PPAResult with contracted/merchant MWh and revenue splits.
    """
    if dispatch_col not in dispatch_df.columns:
        raise ValueError(f"dispatch_df missing column '{dispatch_col}'")
    if mcp_col not in dispatch_df.columns:
        raise ValueError(f"dispatch_df missing column '{mcp_col}'")

    dispatch_mwh: pd.Series = dispatch_df[dispatch_col].astype(float)
    mcp: pd.Series = dispatch_df[mcp_col].astype(float)
    total_dispatch_mwh = float(dispatch_mwh.sum())

    # Apply volume cap if set
    if contract.annual_cap_mwh is not None:
        contracted_total = min(total_dispatch_mwh, contract.annual_cap_mwh)
    else:
        contracted_total = total_dispatch_mwh

    # Proportion of each interval that is contracted
    contracted_ratio = contracted_total / total_dispatch_mwh if total_dispatch_mwh > 0 else 1.0

    contracted_mwh_series: pd.Series = dispatch_mwh * contracted_ratio
    merchant_mwh_series: pd.Series = dispatch_mwh * (1.0 - contracted_ratio)

    # Calculate contracted revenue per contract type
    if contract.contract_type == "fixed_price":
        ppa_price = contract.price_per_mwh
        contracted_rev_series = contracted_mwh_series * ppa_price

    elif contract.contract_type == "indexed":
        ppa_price = contract.price_per_mwh * contract.cpi_index
        contracted_rev_series = contracted_mwh_series * ppa_price

    elif contract.contract_type == "floor_share":
        floor = contract.price_per_mwh
        # Revenue = contracted_vol × (floor + share × max(0, mcp - floor))
        upside = np.maximum(0.0, mcp - floor)
        effective_price = floor + contract.share_pct * upside
        contracted_rev_series = contracted_mwh_series * effective_price

    else:
        raise ValueError(f"Unknown contract_type: {contract.contract_type}")

    merchant_rev_series = merchant_mwh_series * mcp

    contracted_mwh = float(contracted_mwh_series.sum())
    merchant_mwh = float(merchant_mwh_series.sum())
    contracted_revenue = float(contracted_rev_series.sum())
    merchant_revenue = float(merchant_rev_series.sum())
    total_revenue = contracted_revenue + merchant_revenue

    return PPAResult(
        contracted_mwh=contracted_mwh,
        merchant_mwh=merchant_mwh,
        contracted_revenue=contracted_revenue,
        merchant_revenue=merchant_revenue,
        total_revenue=total_revenue,
    )
