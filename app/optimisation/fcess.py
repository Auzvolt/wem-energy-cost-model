"""FCESS (Frequency Control and System Security Services) market participation model.

Provides Pydantic configuration and Pyomo constraint builder for BESS
co-optimisation across all five WEM FCESS products within the WEM model.

FCESS products:
    - reg_raise  : Regulation raise (fast frequency response up)
    - reg_lower  : Regulation lower (fast frequency response down)
    - cont_raise : Contingency raise (post-contingency frequency recovery up)
    - cont_lower : Contingency lower (post-contingency frequency recovery down)
    - rocof      : Rate-of-change-of-frequency (inertia-like synthetic response)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, model_validator

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

FCESS_PRODUCTS: tuple[str, ...] = (
    "reg_raise",
    "reg_lower",
    "cont_raise",
    "cont_lower",
    "rocof",
)


class FcessConfig(BaseModel):
    """Configuration for FCESS market participation.

    Attributes:
        enabled_products: Set of FCESS product names to enable in the model.
            Defaults to all five products.
        prices: Mapping of product name → list of prices ($/MW) per interval.
            Must have the same length as the number of dispatch intervals.
            If a product is enabled but has no price list, prices default to 0.
        max_reg_raise_mw: Maximum MW enablement for regulation raise (default: uncapped).
        max_reg_lower_mw: Maximum MW enablement for regulation lower (default: uncapped).
        max_cont_raise_mw: Maximum MW enablement for contingency raise (default: uncapped).
        max_cont_lower_mw: Maximum MW enablement for contingency lower (default: uncapped).
        max_rocof_mw: Maximum MW enablement for RoCoF product (default: uncapped).
    """

    enabled_products: list[str] = Field(
        default_factory=lambda: list(FCESS_PRODUCTS),
        description=(
            "FCESS products to enable "
            "(subset of reg_raise, reg_lower, cont_raise, cont_lower, rocof)"
        ),
    )
    prices: dict[str, list[float]] = Field(
        default_factory=dict,
        description="Availability prices per product per interval ($/MW). Missing products default to 0.",
    )
    max_reg_raise_mw: float | None = Field(default=None, ge=0, description="MW cap for reg_raise")
    max_reg_lower_mw: float | None = Field(default=None, ge=0, description="MW cap for reg_lower")
    max_cont_raise_mw: float | None = Field(default=None, ge=0, description="MW cap for cont_raise")
    max_cont_lower_mw: float | None = Field(default=None, ge=0, description="MW cap for cont_lower")
    max_rocof_mw: float | None = Field(default=None, ge=0, description="MW cap for rocof")

    @model_validator(mode="after")
    def validate_products(self) -> FcessConfig:
        """Ensure enabled_products only contains known product names."""
        unknown = set(self.enabled_products) - set(FCESS_PRODUCTS)
        if unknown:
            raise ValueError(f"Unknown FCESS products: {unknown}. Must be one of {FCESS_PRODUCTS}")
        return self

    def price_series(self, product: str, n_intervals: int) -> list[float]:
        """Return per-interval price list for the given product.

        Falls back to a list of zeros if prices are not provided for the product.
        """
        if product in self.prices and self.prices[product]:
            return self.prices[product]
        return [0.0] * n_intervals

    def max_mw(self, product: str) -> float | None:
        """Return the configured MW cap for a product, or None (uncapped)."""
        return {
            "reg_raise": self.max_reg_raise_mw,
            "reg_lower": self.max_reg_lower_mw,
            "cont_raise": self.max_cont_raise_mw,
            "cont_lower": self.max_cont_lower_mw,
            "rocof": self.max_rocof_mw,
        }.get(product)


__all__ = ["FcessConfig", "FCESS_PRODUCTS", "add_fcess_constraints"]


def add_fcess_constraints(
    model: Any,
    config: FcessConfig,
    *,
    bess_power_kw: float,
) -> None:
    """Add FCESS decision variables and constraints to an existing Pyomo model.

    Expects ``model`` to already have:
    - ``model.T``: ordered integer index set of dispatch intervals
    - ``model.discharge_kw[t]``: BESS discharge power variable (from bess.py)
    - ``model.charge_kw[t]``: BESS charge power variable (from bess.py)
    - ``model.add_objective_term(expr)``: method to accumulate revenue

    Variables added (one Var per enabled product):
        fcess_<product>[t]  -- MW enabled for that FCESS product at interval t (>= 0)

    Constraints added:
        fcess_raise_headroom[t]  -- discharge_kw + sum(raise products)[t] <= bess_power_kw
        fcess_lower_headroom[t]  -- charge_kw + sum(lower products)[t] <= bess_power_kw
        fcess_<product>_cap[t]   -- per-product MW cap (if configured)

    Objective contribution:
        For each enabled product p: sum_t( price[p][t] * fcess_p[t] ) added as revenue.

    Args:
        model: Pyomo ConcreteModel with BESS variables already added.
        config: FCESS participation configuration.
        bess_power_kw: Nameplate charge/discharge power of the BESS (kW).
            Used to enforce headroom constraints (kW == MW * 1000 is handled
            by keeping units consistent — assume kW throughout).
    """
    import pyomo.environ as pyo  # local import — optional dependency

    T = list(model.T)
    n = len(T)
    enabled = config.enabled_products

    # -------------------------------------------------------------------------
    # Decision variables: one Var per enabled product
    # -------------------------------------------------------------------------
    fcess_vars: dict[str, Any] = {}
    for product in enabled:
        cap_kw = config.max_mw(product)
        if cap_kw is not None:
            var = pyo.Var(
                model.T,
                domain=pyo.NonNegativeReals,
                bounds=(0.0, cap_kw),
                initialize=0.0,
            )
        else:
            var = pyo.Var(model.T, domain=pyo.NonNegativeReals, initialize=0.0)
        setattr(model, f"fcess_{product}", var)
        fcess_vars[product] = var

    # -------------------------------------------------------------------------
    # Co-optimisation headroom constraints
    # -------------------------------------------------------------------------
    raise_products = [p for p in ("reg_raise", "cont_raise", "rocof") if p in enabled]
    lower_products = [p for p in ("reg_lower", "cont_lower") if p in enabled]

    if raise_products:

        def raise_headroom_rule(m: Any, t: int) -> Any:
            raise_sum = sum(fcess_vars[p][t] for p in raise_products)
            return m.discharge_kw[t] + raise_sum <= bess_power_kw

        model.fcess_raise_headroom = pyo.Constraint(model.T, rule=raise_headroom_rule)

    if lower_products:

        def lower_headroom_rule(m: Any, t: int) -> Any:
            lower_sum = sum(fcess_vars[p][t] for p in lower_products)
            return m.charge_kw[t] + lower_sum <= bess_power_kw

        model.fcess_lower_headroom = pyo.Constraint(model.T, rule=lower_headroom_rule)

    # -------------------------------------------------------------------------
    # Objective: FCESS availability revenue
    # -------------------------------------------------------------------------
    for product in enabled:
        prices = config.price_series(product, n)
        if not prices or all(p == 0.0 for p in prices):
            continue  # skip zero-value products to keep model sparse

        price_param_name = f"fcess_{product}_price"
        price_param = pyo.Param(
            model.T,
            initialize={t: prices[i] for i, t in enumerate(T)},
            within=pyo.Reals,
        )
        setattr(model, price_param_name, price_param)

        revenue_expr = sum(getattr(model, price_param_name)[t] * fcess_vars[product][t] for t in T)
        model.add_objective_term(revenue_expr)
        logger.debug("FCESS %s revenue term added (%d intervals)", product, n)

    logger.debug(
        "FCESS constraints added: enabled=%s, bess_power_kw=%.1f",
        enabled,
        bess_power_kw,
    )
