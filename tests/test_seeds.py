"""Tests for WA default assumption seeds."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.assumptions.seeds import (
    BESS_DEGRADATION_CURVES,
    REFERENCE_CAPEX_OPEX,
    SOLAR_YIELD_PROFILES,
    WA_TARIFF_SCHEDULES,
    seed_wa_defaults,
)


class TestSeedDataStructure:
    """Validate seed data structures are correct before DB interaction."""

    def test_three_tariff_schedules(self) -> None:
        assert len(WA_TARIFF_SCHEDULES) == 3
        keys = {t["key"] for t in WA_TARIFF_SCHEDULES}
        assert keys == {"RT2", "RT5", "RT7"}

    def test_all_tariffs_have_tou_windows(self) -> None:
        for tariff in WA_TARIFF_SCHEDULES:
            val = tariff["value"]
            assert isinstance(val["tou_windows"], list)
            assert len(val["tou_windows"]) > 0, f"{tariff['key']} has no TOU windows"

    def test_rt2_has_no_demand_charge(self) -> None:
        rt2 = next(t for t in WA_TARIFF_SCHEDULES if t["key"] == "RT2")
        assert rt2["value"]["demand_charge"] is None

    def test_rt5_has_demand_charge(self) -> None:
        rt5 = next(t for t in WA_TARIFF_SCHEDULES if t["key"] == "RT5")
        assert rt5["value"]["demand_charge"] is not None
        assert "rate_dollars_per_kw_per_month" in rt5["value"]["demand_charge"]

    def test_rt7_has_cmd_demand_charge(self) -> None:
        rt7 = next(t for t in WA_TARIFF_SCHEDULES if t["key"] == "RT7")
        dc = rt7["value"]["demand_charge"]
        assert dc is not None
        assert "cmd_rate_dollars_per_kva_per_month" in dc
        assert "enuc_rate_dollars_per_kva_per_month" in dc

    def test_two_bess_chemistries(self) -> None:
        chemistries = {c["value"]["chemistry"] for c in BESS_DEGRADATION_CURVES}
        assert chemistries == {"NMC", "LFP"}

    def test_lfp_lower_fade_than_nmc(self) -> None:
        nmc = next(c for c in BESS_DEGRADATION_CURVES if c["value"]["chemistry"] == "NMC")
        lfp = next(c for c in BESS_DEGRADATION_CURVES if c["value"]["chemistry"] == "LFP")
        assert (
            lfp["value"]["capacity_fade_pct_per_cycle"]
            < nmc["value"]["capacity_fade_pct_per_cycle"]
        )

    def test_two_solar_profiles(self) -> None:
        assert len(SOLAR_YIELD_PROFILES) == 2
        locations = {p["value"]["location"] for p in SOLAR_YIELD_PROFILES}
        assert any("Perth" in loc for loc in locations)
        assert any("Pilbara" in loc for loc in locations)

    def test_solar_profiles_have_12_monthly_values(self) -> None:
        for profile in SOLAR_YIELD_PROFILES:
            cfs = profile["value"]["monthly_cf"]
            assert len(cfs) == 12, f"{profile['key']} has {len(cfs)} monthly CFs, expected 12"

    def test_pilbara_higher_yield_than_perth(self) -> None:
        perth = next(p for p in SOLAR_YIELD_PROFILES if "Perth" in p["value"]["location"])
        pilbara = next(p for p in SOLAR_YIELD_PROFILES if "Pilbara" in p["value"]["location"])
        assert (
            pilbara["value"]["annual_yield_estimate_kwh_per_kwp"]
            > perth["value"]["annual_yield_estimate_kwh_per_kwp"]
        )

    def test_three_capex_opex_assets(self) -> None:
        asset_types = {c["value"]["asset_type"] for c in REFERENCE_CAPEX_OPEX}
        assert asset_types == {"solar_pv", "bess_utility", "gas_ocgt"}

    def test_capex_bess_has_chemistry_and_ref(self) -> None:
        bess = next(c for c in REFERENCE_CAPEX_OPEX if c["key"] == "capex_bess_utility")
        assert bess["value"]["chemistry"] == "LFP"
        assert bess["value"]["degradation_curve_ref"] == "bess_degradation_LFP"
        assert bess["value"]["installed_cost_dollars_per_kwh"] == 780

    def test_capex_values_are_positive(self) -> None:
        for item in REFERENCE_CAPEX_OPEX:
            val = item["value"]
            asset = val["asset_type"]
            if asset == "solar_pv":
                assert val["installed_cost_dollars_per_kw"] > 0
            elif asset == "bess_utility":
                assert val["installed_cost_dollars_per_kwh"] > 0
            elif asset == "gas_ocgt":
                assert val["installed_cost_dollars_per_kw"] > 0


class TestSeedWaDefaultsIdempotency:
    """Test idempotency logic without real DB."""

    @pytest.mark.asyncio
    async def test_skips_if_already_seeded(self) -> None:
        """If scalar() returns a positive count, seed returns False immediately."""

        mock_result = MagicMock()
        mock_result.scalar.return_value = 1  # existing row found → count > 0

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        mock_text = MagicMock(return_value=MagicMock())
        with patch("app.assumptions.seeds.text", mock_text):
            result = await seed_wa_defaults(mock_session)

        assert result is False
        # Only the existence check execute() should have been called
        assert mock_session.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_inserts_when_no_existing_set(self) -> None:
        """If no existing set (count == 0), seed inserts all records and returns True."""

        mock_result = MagicMock()
        mock_result.scalar.return_value = 0  # no existing row

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.flush = AsyncMock()

        mock_text = MagicMock(return_value=MagicMock())
        with patch("app.assumptions.seeds.text", mock_text):
            result = await seed_wa_defaults(mock_session)

        assert result is True

        # execute() is called:
        #   1 × existence check
        #   1 × INSERT INTO assumption_sets
        #   N × INSERT INTO assumption_entries (one per entry in all_entries)
        expected_entry_count = (
            len(WA_TARIFF_SCHEDULES)
            + len(BESS_DEGRADATION_CURVES)
            + len(SOLAR_YIELD_PROFILES)
            + len(REFERENCE_CAPEX_OPEX)
        )
        expected_execute_calls = 1 + 1 + expected_entry_count
        assert mock_session.execute.call_count == expected_execute_calls
