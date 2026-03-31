"""Default WEM energy asset library — issue #9.

Provides a catalogue of representative WEM assets calibrated to Western Australian
conditions. Values sourced from AEMO ESOO 2024, NREL ATB 2024, and WA government
renewable energy publications.

Contains:
- 5 generators (coal, CCGT, OCGT, solar PV utility, onshore wind)
- 3 BESS variants (LFP short-duration, LFP long-duration, NMC utility)
- 3 demand-response programs (industrial, commercial, aggregated residential)
"""

from __future__ import annotations

from app.assets.models import AnyAsset, BatteryAsset, DemandResponseAsset, GeneratorAsset

DEFAULT_ASSETS: list[AnyAsset] = [
    # ------------------------------------------------------------------
    # Generators
    # ------------------------------------------------------------------
    GeneratorAsset(
        name="Coal Baseload (Collie/Muja proxy)",
        technology="coal_steam",
        capacity_kw=200_000.0,
        min_stable_load_kw=100_000.0,
        heat_rate_gj_mwh=10.2,
        fuel_cost_aud_gj=2.80,
        variable_om_aud_mwh=6.50,
        start_cost_aud=80_000.0,
    ),
    GeneratorAsset(
        name="CCGT Midmerit",
        technology="CCGT",
        capacity_kw=450_000.0,
        min_stable_load_kw=135_000.0,
        heat_rate_gj_mwh=7.1,
        fuel_cost_aud_gj=8.50,
        variable_om_aud_mwh=5.00,
        start_cost_aud=25_000.0,
    ),
    GeneratorAsset(
        name="OCGT Gas Peaker",
        technology="OCGT",
        capacity_kw=160_000.0,
        min_stable_load_kw=32_000.0,
        heat_rate_gj_mwh=11.4,
        fuel_cost_aud_gj=9.50,
        variable_om_aud_mwh=8.50,
        start_cost_aud=12_000.0,
    ),
    GeneratorAsset(
        name="Utility-Scale Solar PV",
        technology="solar_pv",
        # 150 MWac
        capacity_kw=150_000.0,
        min_stable_load_kw=0.0,
        heat_rate_gj_mwh=0.0,
        fuel_cost_aud_gj=0.0,
        variable_om_aud_mwh=5.00,
        start_cost_aud=0.0,
    ),
    GeneratorAsset(
        name="Onshore Wind",
        technology="wind",
        capacity_kw=200_000.0,
        min_stable_load_kw=0.0,
        heat_rate_gj_mwh=0.0,
        fuel_cost_aud_gj=0.0,
        variable_om_aud_mwh=9.50,
        start_cost_aud=0.0,
    ),
    # ------------------------------------------------------------------
    # BESS
    # ------------------------------------------------------------------
    BatteryAsset(
        name="LFP Short-Duration BESS (2h)",
        capacity_kwh=200_000.0,
        power_kw=100_000.0,
        # LFP: ~92–94% RTE at cell level; 90% system-level (including inverter)
        round_trip_efficiency=0.90,
        soc_min_pct=0.05,
        soc_max_pct=0.95,
        # Cycle cost: LFP ~3000–6000 full cycles to 80% EoL, capex ~$350/kWh installed
        # => AUD 350 / 4000 cycles ≈ AUD 0.088/kWh; round to 0.09
        cycle_cost_aud_kwh=0.09,
    ),
    BatteryAsset(
        name="LFP Long-Duration BESS (4h)",
        capacity_kwh=400_000.0,
        power_kw=100_000.0,
        round_trip_efficiency=0.90,
        soc_min_pct=0.05,
        soc_max_pct=0.95,
        cycle_cost_aud_kwh=0.09,
    ),
    BatteryAsset(
        name="NMC Utility BESS (1h)",
        capacity_kwh=100_000.0,
        power_kw=100_000.0,
        # NMC: ~89–91% system-level RTE
        round_trip_efficiency=0.89,
        soc_min_pct=0.10,
        soc_max_pct=0.90,
        # NMC ~1500–2000 full cycles to 80% EoL, capex ~$450/kWh => 450/1750 ≈ 0.26
        cycle_cost_aud_kwh=0.26,
    ),
    # ------------------------------------------------------------------
    # Demand Response
    # ------------------------------------------------------------------
    DemandResponseAsset(
        name="Industrial DR — Mining Load Curtailment",
        capacity_kw=50_000.0,
        response_time_min=15.0,
        availability_hours_per_day=8.0,
        cost_aud_mwh=120.0,
    ),
    DemandResponseAsset(
        name="Commercial DR — HVAC Load Shifting",
        capacity_kw=10_000.0,
        response_time_min=5.0,
        availability_hours_per_day=12.0,
        cost_aud_mwh=90.0,
    ),
    DemandResponseAsset(
        name="Aggregated Residential VPP",
        capacity_kw=15_000.0,
        response_time_min=2.0,
        availability_hours_per_day=6.0,
        cost_aud_mwh=60.0,
    ),
]
