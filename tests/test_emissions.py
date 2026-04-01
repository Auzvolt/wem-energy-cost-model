"""Tests for app.financial.emissions module."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from app.financial.emissions import (
    SWIS_DEFAULT_EF_TCO2E_PER_MWH,
    EmissionsResult,
    calculate_emissions,
)


def _make_dispatch(grid_import_kwh: float) -> pd.DataFrame:
    """Build a single-row dispatch DataFrame with the given grid import (kWh)."""
    return pd.DataFrame({"grid_import_kwh": [grid_import_kwh]})


def _make_dispatch_annual(grid_import_kwh_per_interval: float, n: int = 1) -> pd.DataFrame:
    """Build a multi-row dispatch DataFrame totalling grid imports."""
    return pd.DataFrame({"grid_import_kwh": [grid_import_kwh_per_interval] * n})


class TestCalculateEmissions:
    """Unit tests for calculate_emissions."""

    def test_known_values(self) -> None:
        """1000 MWh baseline vs 200 MWh post-project → 552 tCO2e abatement."""
        baseline_kwh = 1_000_000.0  # 1000 MWh
        post_project_kwh = 200_000.0  # 200 MWh
        net_cost = 552_000.0  # chosen so abatement_cost = 1000 AUD/tCO2e

        result = calculate_emissions(
            dispatch_df=_make_dispatch(post_project_kwh),
            grid_import_kwh_baseline=baseline_kwh,
            net_project_cost=net_cost,
        )

        assert result.baseline_tco2e_year == pytest.approx(1_000.0 * SWIS_DEFAULT_EF_TCO2E_PER_MWH)
        assert result.project_tco2e_year == pytest.approx(200.0 * SWIS_DEFAULT_EF_TCO2E_PER_MWH)
        expected_abatement = (1_000.0 - 200.0) * SWIS_DEFAULT_EF_TCO2E_PER_MWH  # = 800 × 0.69 = 552
        assert result.abatement_tco2e_year == pytest.approx(expected_abatement)
        assert result.abatement_cost_aud_per_tco2e == pytest.approx(net_cost / expected_abatement)

    def test_custom_emissions_factor(self) -> None:
        """Custom EF and source string are used correctly."""
        custom_ef = 0.50
        custom_source = "Custom EF Source 2025"

        result = calculate_emissions(
            dispatch_df=_make_dispatch(100_000.0),
            grid_import_kwh_baseline=500_000.0,
            net_project_cost=1_000.0,
            avg_ef_tco2e_per_mwh=custom_ef,
            ef_source=custom_source,
        )

        # baseline = 500 MWh × 0.50 = 250 tCO2e
        assert result.baseline_tco2e_year == pytest.approx(250.0)
        # project = 100 MWh × 0.50 = 50 tCO2e
        assert result.project_tco2e_year == pytest.approx(50.0)
        assert result.abatement_tco2e_year == pytest.approx(200.0)
        assert result.emissions_factor_source == custom_source

    def test_zero_abatement_returns_inf(self) -> None:
        """When baseline equals post-project, abatement_cost is inf."""
        same_kwh = 500_000.0
        result = calculate_emissions(
            dispatch_df=_make_dispatch(same_kwh),
            grid_import_kwh_baseline=same_kwh,
            net_project_cost=1_000.0,
        )
        assert result.abatement_tco2e_year == pytest.approx(0.0)
        assert math.isinf(result.abatement_cost_aud_per_tco2e)

    def test_negative_abatement_returns_inf(self) -> None:
        """When post-project emissions exceed baseline, abatement_cost is inf."""
        result = calculate_emissions(
            dispatch_df=_make_dispatch(1_500_000.0),  # more than baseline
            grid_import_kwh_baseline=1_000_000.0,
            net_project_cost=1_000.0,
        )
        assert result.abatement_tco2e_year < 0
        assert math.isinf(result.abatement_cost_aud_per_tco2e)

    def test_ef_source_default(self) -> None:
        """Default ef_source is the CER NGA 2023 string."""
        result = calculate_emissions(
            dispatch_df=_make_dispatch(0.0),
            grid_import_kwh_baseline=100_000.0,
            net_project_cost=1_000.0,
        )
        assert "Clean Energy Regulator" in result.emissions_factor_source

    def test_missing_column_raises(self) -> None:
        """dispatch_df without grid_import_kwh raises KeyError."""
        with pytest.raises(KeyError, match="grid_import_kwh"):
            calculate_emissions(
                dispatch_df=pd.DataFrame({"other_col": [100.0]}),
                grid_import_kwh_baseline=100_000.0,
                net_project_cost=1_000.0,
            )

    def test_result_type(self) -> None:
        """calculate_emissions returns an EmissionsResult."""
        result = calculate_emissions(
            dispatch_df=_make_dispatch(100_000.0),
            grid_import_kwh_baseline=1_000_000.0,
            net_project_cost=100_000.0,
        )
        assert isinstance(result, EmissionsResult)

    def test_multi_interval_dispatch(self) -> None:
        """Dispatch DataFrame with multiple rows is summed correctly."""
        # 4 intervals × 50 MWh = 200 MWh total
        result = calculate_emissions(
            dispatch_df=_make_dispatch_annual(50_000.0, n=4),
            grid_import_kwh_baseline=1_000_000.0,
            net_project_cost=1_000.0,
        )
        assert result.project_tco2e_year == pytest.approx(200.0 * SWIS_DEFAULT_EF_TCO2E_PER_MWH)
