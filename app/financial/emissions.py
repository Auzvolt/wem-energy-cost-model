"""Scope 2 GHG emissions calculator for WEM energy projects.

Calculates baseline and post-project Scope 2 emissions using the SWIS
average emissions factor, and derives abatement cost.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

# Default SWIS average emissions factor (tCO2e/MWh), Clean Energy Regulator NGA 2023
SWIS_DEFAULT_EF_TCO2E_PER_MWH: float = 0.69


@dataclass
class EmissionsResult:
    """Results of a Scope 2 emissions calculation."""

    baseline_tco2e_year: float
    """Annual baseline emissions before the project (tCO2e/year)."""

    project_tco2e_year: float
    """Annual post-project Scope 2 emissions (tCO2e/year)."""

    abatement_tco2e_year: float
    """Annual emissions abatement (baseline minus project, tCO2e/year).
    Negative values indicate an emissions increase."""

    abatement_cost_aud_per_tco2e: float
    """Cost of abatement (net_project_cost / abatement_tco2e_year).
    Returns math.inf when abatement is zero or negative."""

    emissions_factor_source: str
    """Citation for the emissions factor used."""


def calculate_emissions(
    dispatch_df: pd.DataFrame,
    grid_import_kwh_baseline: float,
    net_project_cost: float,
    avg_ef_tco2e_per_mwh: float = SWIS_DEFAULT_EF_TCO2E_PER_MWH,
    ef_source: str = "Clean Energy Regulator NGA 2023",
) -> EmissionsResult:
    """Calculate Scope 2 emissions abatement for a WEM energy project.

    Args:
        dispatch_df: DataFrame with at least a ``grid_import_kwh`` column
            containing per-interval post-project grid imports in kWh.
        grid_import_kwh_baseline: Total annual grid import (kWh) in the
            baseline (no-project) scenario.
        net_project_cost: Net present cost of the project (AUD), used to
            compute the levelised abatement cost.
        avg_ef_tco2e_per_mwh: Average grid emissions factor (tCO2e/MWh).
            Defaults to the SWIS CER NGA 2023 value.
        ef_source: Citation string for the emissions factor.

    Returns:
        :class:`EmissionsResult` with all emissions and cost metrics.

    Raises:
        KeyError: If ``dispatch_df`` does not contain a ``grid_import_kwh``
            column.
    """
    if "grid_import_kwh" not in dispatch_df.columns:
        raise KeyError("dispatch_df must contain a 'grid_import_kwh' column")

    # Convert kWh → MWh before applying factor
    baseline_tco2e = (grid_import_kwh_baseline / 1_000.0) * avg_ef_tco2e_per_mwh
    project_tco2e = (float(dispatch_df["grid_import_kwh"].sum()) / 1_000.0) * avg_ef_tco2e_per_mwh
    abatement = baseline_tco2e - project_tco2e

    abatement_cost = net_project_cost / abatement if abatement > 0 else math.inf

    return EmissionsResult(
        baseline_tco2e_year=baseline_tco2e,
        project_tco2e_year=project_tco2e,
        abatement_tco2e_year=abatement,
        abatement_cost_aud_per_tco2e=abatement_cost,
        emissions_factor_source=ef_source,
    )
