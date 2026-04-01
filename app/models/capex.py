"""Capital expenditure model for asset sizing calculations.

Provides:
- CapexModel: Pydantic model capturing capex, opex, and asset life parameters
- capital_recovery_factor: CRF utility for annualising capital costs
"""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["CapexModel"]


class CapexModel(BaseModel):
    """Capital expenditure parameters for an energy asset.

    Attributes
    ----------
    capex_per_kw:
        Capital cost per kilowatt of installed capacity ($/kW).
    opex_per_kw_year:
        Annual operating expenditure per kilowatt ($/kW/year).
    life_years:
        Asset economic life in years used for annualisation.
    """

    capex_per_kw: float = Field(gt=0, description="Capital cost ($/kW)")
    opex_per_kw_year: float = Field(ge=0, description="Annual opex ($/kW/year)")
    life_years: int = Field(gt=0, description="Asset economic life (years)")

    def capital_recovery_factor(self, discount_rate: float) -> float:
        """Compute the capital recovery factor (CRF).

        CRF converts a present-value capital cost into an equivalent annual
        payment stream over the asset life.

        Formula (discount_rate > 0):
            CRF = r * (1 + r)^n / ((1 + r)^n - 1)

        For discount_rate == 0:
            CRF = 1 / life_years  (equal annual payments, no time value)

        Parameters
        ----------
        discount_rate:
            Annual discount rate as a decimal fraction (e.g. 0.08 = 8%).

        Returns
        -------
        float
            Capital recovery factor (dimensionless).
        """
        n = self.life_years
        r = discount_rate
        if r == 0.0:
            return 1.0 / n
        factor = (1.0 + r) ** n
        return r * factor / (factor - 1.0)
