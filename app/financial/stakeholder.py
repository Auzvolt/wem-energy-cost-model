"""Stakeholder value decomposition for WEM energy projects.

Decomposes project value into developer, offtaker, and network perspectives.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy_financial as npf
import pandas as pd

from app.financial import metrics as fin_metrics

# Default WA network demand avoidance value (AUD/kW/year).
# Based on Western Power RT7 demand rate default seed value.
WA_DEFAULT_DEMAND_AVOIDANCE_AUD_KW_YEAR: float = 120.0

# Default equity discount rate for NPV calculation when not supplied.
DEFAULT_EQUITY_DISCOUNT_RATE: float = 0.10


@dataclass
class DeveloperValue:
    """Value from the developer's perspective."""

    equity_irr: float
    """Equity IRR as a decimal (e.g. 0.12 = 12%). NaN if not solvable."""

    equity_npv: float
    """Equity NPV in AUD at the default or provided discount rate."""

    project_irr: float
    """Project (unlevered) IRR as a decimal. NaN if not solvable."""


@dataclass
class OfftakerValue:
    """Value from the energy offtaker's perspective."""

    annual_bill_saving: float
    """Annual electricity bill saving in AUD/year."""

    hedge_value: float
    """Price risk hedge value in AUD (contracted volume × price volatility proxy)."""

    payback_years: float
    """Simple payback of the offtaker's cost contribution (capex / annual_bill_saving).
    Returns math.inf when annual_bill_saving is zero."""


@dataclass
class NetworkValue:
    """Value from the network (distribution/transmission) perspective."""

    avoided_network_cost: float
    """Annual avoided network cost in AUD/year."""

    peak_demand_reduction_kw: float
    """Peak demand reduction in kW."""


@dataclass
class StakeholderValueResult:
    """Combined stakeholder value decomposition."""

    developer: DeveloperValue
    offtaker: OfftakerValue
    network: NetworkValue


def _safe_irr(cashflows: list[float]) -> float:
    """Return IRR as a decimal or NaN if numpy_financial cannot converge."""
    try:
        result = fin_metrics.irr(cashflows)
        return result if result is not None else float("nan")
    except Exception:  # noqa: BLE001
        return float("nan")


def calculate_stakeholder_value(
    cashflow_df: pd.DataFrame,
    capex: float,
    annual_bill_saving: float,
    peak_demand_reduction_kw: float = 0.0,
    contracted_volume_mwh: float = 0.0,
    price_volatility_aud_per_mwh: float = 0.0,
    equity_discount_rate: float = DEFAULT_EQUITY_DISCOUNT_RATE,
    demand_avoidance_rate: float = WA_DEFAULT_DEMAND_AVOIDANCE_AUD_KW_YEAR,
    metrics: Any | None = None,
) -> StakeholderValueResult:
    """Decompose project value into developer, offtaker, and network perspectives.

    Args:
        cashflow_df: DataFrame with columns ``fcfe`` (free cashflow to equity)
            and ``fcff`` (free cashflow to firm), one row per period.
        capex: Total capital expenditure (AUD).
        annual_bill_saving: Offtaker annual electricity bill saving (AUD/year).
        peak_demand_reduction_kw: Peak demand reduction achieved (kW).
        contracted_volume_mwh: MWh contracted under PPA or other agreement.
        price_volatility_aud_per_mwh: Price volatility proxy (AUD/MWh) used to
            value the hedge. Use 0 if unknown.
        equity_discount_rate: Discount rate for equity NPV. Default 10 %.
        demand_avoidance_rate: Network demand avoidance value (AUD/kW/year).
        metrics: Optional pre-computed financial metrics object with an ``npv``
            attribute. If supplied, ``equity_npv`` is taken from it.

    Returns:
        :class:`StakeholderValueResult` decomposing value by stakeholder.

    Raises:
        KeyError: If ``cashflow_df`` is missing required columns.
    """
    for col in ("fcfe", "fcff"):
        if col not in cashflow_df.columns:
            raise KeyError(f"cashflow_df must contain a '{col}' column")

    fcfe = cashflow_df["fcfe"].tolist()
    fcff = cashflow_df["fcff"].tolist()

    equity_irr = _safe_irr(fcfe)
    project_irr = _safe_irr(fcff)

    if metrics is not None and hasattr(metrics, "npv"):
        equity_npv = float(metrics.npv)
    else:
        # Compute equity NPV at the supplied discount rate
        equity_npv = float(npf.npv(equity_discount_rate, fcfe))

    developer = DeveloperValue(
        equity_irr=equity_irr,
        equity_npv=equity_npv,
        project_irr=project_irr,
    )

    hedge_value = contracted_volume_mwh * price_volatility_aud_per_mwh
    payback = capex / annual_bill_saving if annual_bill_saving > 0 else math.inf
    offtaker = OfftakerValue(
        annual_bill_saving=annual_bill_saving,
        hedge_value=hedge_value,
        payback_years=payback,
    )

    avoided_network = peak_demand_reduction_kw * demand_avoidance_rate
    network = NetworkValue(
        avoided_network_cost=avoided_network,
        peak_demand_reduction_kw=peak_demand_reduction_kw,
    )

    return StakeholderValueResult(developer=developer, offtaker=offtaker, network=network)
