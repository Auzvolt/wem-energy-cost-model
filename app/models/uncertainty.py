"""Uncertainty and stochastic scenario configuration models.

Provides:
- Distribution: base class for price distribution specifications
- NormalDistribution: Gaussian price distribution sampler
- UniformDistribution: uniform price distribution sampler
- UncertaintyConfig: top-level Monte Carlo configuration model
"""

from __future__ import annotations

from typing import Annotated, Literal

import numpy as np
from pydantic import BaseModel, Field, field_validator, model_validator

__all__ = [
    "Distribution",
    "NormalDistribution",
    "UniformDistribution",
    "UncertaintyConfig",
    "WEM_PRODUCTS",
]

# Valid WEM product codes for price distributions
WEM_PRODUCTS: frozenset[str] = frozenset(
    {
        "ENERGY",
        "FCESS_REG_RAISE",
        "FCESS_REG_LOWER",
        "FCESS_CONT_RAISE",
        "FCESS_CONT_LOWER",
        "FCESS_ROCOF",
    }
)

# WEM energy price bounds (post-reform)
ENERGY_PRICE_FLOOR = -1000.0  # $/MWh
ENERGY_PRICE_CAP = 1000.0  # $/MWh


class Distribution(BaseModel):
    """Base class for a price distribution.

    Attributes
    ----------
    mean:
        Expected (mean) price value.
    std:
        Standard deviation of the price distribution.
    """

    mean: float = Field(description="Expected (mean) price ($/MWh)")
    std: float = Field(ge=0.0, description="Standard deviation ($/MWh)")

    def sample(self, n: int, rng: np.random.Generator) -> np.ndarray:
        """Draw n samples from this distribution using the provided RNG.

        Parameters
        ----------
        n:
            Number of samples to draw.
        rng:
            NumPy random generator for reproducibility.

        Returns
        -------
        np.ndarray
            Array of n sampled price values.
        """
        raise NotImplementedError


class NormalDistribution(Distribution):
    """Gaussian (Normal) price distribution.

    Samples are drawn from N(mean, std²).
    """

    type: Literal["normal"] = "normal"

    def sample(self, n: int, rng: np.random.Generator) -> np.ndarray:
        """Draw n samples from N(mean, std²)."""
        return rng.normal(loc=self.mean, scale=self.std, size=n)


class UniformDistribution(Distribution):
    """Uniform price distribution over [low, high].

    Attributes
    ----------
    low:
        Lower bound of the distribution.
    high:
        Upper bound of the distribution.
    """

    type: Literal["uniform"] = "uniform"
    low: float = Field(description="Lower bound ($/MWh)")
    high: float = Field(description="Upper bound ($/MWh)")

    @model_validator(mode="after")
    def _check_bounds(self) -> UniformDistribution:
        if self.low >= self.high:
            raise ValueError("low must be strictly less than high")
        return self

    def sample(self, n: int, rng: np.random.Generator) -> np.ndarray:
        """Draw n samples from U(low, high)."""
        return rng.uniform(low=self.low, high=self.high, size=n)


# Discriminated union for Distribution — used for deserialization
AnyDistribution = Annotated[
    NormalDistribution | UniformDistribution,
    Field(discriminator="type"),
]


class UncertaintyConfig(BaseModel):
    """Configuration for Monte Carlo uncertainty / scenario modelling.

    Attributes
    ----------
    n_scenarios:
        Number of Monte Carlo scenarios to simulate (10–1000).
    seed:
        Random seed for reproducible sampling.
    distributions:
        Mapping of WEM product code → price distribution specification.
        Valid keys: ENERGY, FCESS_REG_RAISE, FCESS_REG_LOWER,
        FCESS_CONT_RAISE, FCESS_CONT_LOWER, FCESS_ROCOF.

    Notes
    -----
    FCESS_ROCOF has been effectively \\$0/MW·s/hr since March 2024.
    If supplied, its mean must be zero.
    """

    n_scenarios: int = Field(
        default=100,
        ge=10,
        le=1000,
        description="Number of Monte Carlo scenarios (10–1000)",
    )
    seed: int = Field(default=42, description="Random seed for reproducibility")
    distributions: dict[str, AnyDistribution] = Field(
        default_factory=dict,
        description="Product code → price distribution",
    )

    @field_validator("distributions")
    @classmethod
    def _check_product_keys(
        cls, v: dict[str, AnyDistribution]
    ) -> dict[str, AnyDistribution]:
        unknown = set(v.keys()) - WEM_PRODUCTS
        if unknown:
            raise ValueError(f"Unknown product codes: {unknown!r}. Valid: {WEM_PRODUCTS!r}")
        # Enforce FCESS_ROCOF mean == 0
        if "FCESS_ROCOF" in v and v["FCESS_ROCOF"].mean != 0.0:
            raise ValueError(
                "FCESS_ROCOF mean must be 0.0 (effectively $0/MW·s/hr since March 2024)"
            )
        return v
