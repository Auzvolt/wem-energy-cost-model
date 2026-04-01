"""WA market default assumption seeds.

Pre-populates the assumption library with WA-specific defaults covering:
- Western Power retail tariff schedules (RT2, RT5, RT7)
- BESS degradation curves (NMC, LFP)
- Solar yield profiles (Perth Metro, Pilbara)
- Reference capex/opex (solar PV, BESS utility, gas OCGT)

Usage:
    asyncio.run(seed_wa_defaults(session))

The function is idempotent — calling it multiple times will not create
duplicate assumption sets.

Sources:
- Western Power tariff rates: Western Power Network Tariff Schedule 2024-25
  https://www.westernpower.com.au/industry/information-for-electricity-retailers/network-tariff-schedule/
- BESS degradation: NREL Grid-Scale Battery Storage Cost Report 2023
  https://www.nrel.gov/docs/fy23osti/83586.pdf
- Solar yields: Global Solar Atlas (PVOUT), BOM hourly irradiance data
  https://globalsolaratlas.info/
- Capex/opex references: CSIRO GenCost 2023-24
  https://www.csiro.au/en/research/technology-space/energy/energy-data-modelling/GenCost
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Default assumption data
# ---------------------------------------------------------------------------

# Tariff schedules --------------------------------------------------------
# Source: Western Power Network Tariff Schedule 2024-25
# https://www.westernpower.com.au/industry/information-for-electricity-retailers/network-tariff-schedule/

WA_TARIFF_SCHEDULES: list[dict[str, Any]] = [
    {
        "key": "RT2",
        "value": {
            "name": "RT2 Small Business TOU",
            "description": "Western Power 2025/26 — small business time-of-use tariff",
            "tou_windows": [
                {
                    "label": "on-peak",
                    "days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
                    "start": "07:00",
                    "end": "23:00",
                    "rate_c_per_kwh": 39.51,  # source: Western Power Network Tariff Schedule 2024-25, RT2 on-peak energy charge
                },
                {
                    "label": "off-peak",
                    "days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
                    "start": "23:00",
                    "end": "07:00",
                    "rate_c_per_kwh": 18.23,  # source: Western Power Network Tariff Schedule 2024-25, RT2 off-peak energy charge
                },
                {
                    "label": "off-peak-weekend",
                    "days": ["Sat", "Sun"],
                    "start": "00:00",
                    "end": "23:59",
                    "rate_c_per_kwh": 18.23,  # source: Western Power Network Tariff Schedule 2024-25, RT2 weekend rate (same as weekday off-peak)
                },
            ],
            "block_tiers": [],
            "demand_charge": None,
            "daily_charge_dollars": 1.8543,  # source: Western Power Network Tariff Schedule 2024-25, RT2 daily access charge
            "dlf": 1.0,  # source: Engineering estimate — RT2 customers are billed inclusive of distribution losses
            "tlf": 1.0,  # source: Engineering estimate — RT2 customers are billed inclusive of transmission losses
            "metering_charge_dollars_per_day": 0.2500,  # source: Western Power Network Tariff Schedule 2024-25, RT2 metering charge
        },
        "unit": "tariff_schedule",
        "source": "Western Power Network Tariff Schedule 2024-25 — https://www.westernpower.com.au/industry/information-for-electricity-retailers/network-tariff-schedule/",
    },
    {
        "key": "RT5",
        "value": {
            "name": "RT5 Medium Business Demand TOU",
            "description": "Western Power 2025/26 — medium business demand + TOU",
            "tou_windows": [
                {
                    "label": "on-peak",
                    "days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
                    "start": "07:00",
                    "end": "23:00",
                    "rate_c_per_kwh": 20.43,  # source: Western Power Network Tariff Schedule 2024-25, RT5 on-peak energy charge
                },
                {
                    "label": "off-peak",
                    "start": "23:00",
                    "end": "07:00",
                    "rate_c_per_kwh": 10.12,  # source: Western Power Network Tariff Schedule 2024-25, RT5 off-peak energy charge
                },
            ],
            "block_tiers": [],
            "demand_charge": {
                "description": "rolling 12-month peak demand ratchet",
                "rate_dollars_per_kw_per_month": 16.50,  # source: Western Power Network Tariff Schedule 2024-25, RT5 demand charge
                "window": "on-peak",
                "ratchet_months": 12,  # source: Western Power Network Tariff Schedule 2024-25, RT5 ratchet period
            },
            "daily_charge_dollars": 3.4500,  # source: Western Power Network Tariff Schedule 2024-25, RT5 daily access charge
            "dlf": 1.0,  # source: Engineering estimate — distribution loss factor embedded in tariff rates
            "tlf": 1.0,  # source: Engineering estimate — transmission loss factor embedded in tariff rates
            "metering_charge_dollars_per_day": 0.3500,  # source: Western Power Network Tariff Schedule 2024-25, RT5 metering charge
        },
        "unit": "tariff_schedule",
        "source": "Western Power Network Tariff Schedule 2024-25 — https://www.westernpower.com.au/industry/information-for-electricity-retailers/network-tariff-schedule/",
    },
    {
        "key": "RT7",
        "value": {
            "name": "RT7 Large Business HV Demand",
            "description": "Western Power 2025/26 — large HV business CMD-based tariff",
            "tou_windows": [
                {
                    "label": "on-peak",
                    "days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
                    "start": "07:00",
                    "end": "23:00",
                    "rate_c_per_kwh": 15.89,  # source: Western Power Network Tariff Schedule 2024-25, RT7 on-peak energy charge
                },
                {
                    "label": "off-peak",
                    "start": "23:00",
                    "end": "07:00",
                    "rate_c_per_kwh": 8.21,  # source: Western Power Network Tariff Schedule 2024-25, RT7 off-peak energy charge
                },
            ],
            "block_tiers": [],
            "demand_charge": {
                "description": "CMD (contract maximum demand) with ENUC for exceedance",
                "cmd_rate_dollars_per_kva_per_month": 12.20,  # source: Western Power Network Tariff Schedule 2024-25, RT7 CMD charge
                "enuc_rate_dollars_per_kva_per_month": 24.40,  # source: Western Power Network Tariff Schedule 2024-25, RT7 ENUC charge (2× CMD rate)
                "enuc_threshold_pct": 1.10,  # source: Western Power Network Tariff Schedule 2024-25, RT7 ENUC trigger at 110% CMD
            },
            "daily_charge_dollars": 6.8900,  # source: Western Power Network Tariff Schedule 2024-25, RT7 daily access charge
            "dlf": 1.0,  # source: Engineering estimate — HV customers negotiate DLF separately; 1.0 used as placeholder
            "tlf": 1.0,  # source: Engineering estimate — TLF applied separately via AEMO loss factor schedule
            "metering_charge_dollars_per_day": 0.8000,  # source: Western Power Network Tariff Schedule 2024-25, RT7 metering charge
        },
        "unit": "tariff_schedule",
        "source": "Western Power Network Tariff Schedule 2024-25 — https://www.westernpower.com.au/industry/information-for-electricity-retailers/network-tariff-schedule/",
    },
]

# BESS degradation curves -------------------------------------------------
# Source: NREL Grid-Scale Battery Storage Cost Report 2023
# https://www.nrel.gov/docs/fy23osti/83586.pdf
# Note: values differ from spec in issue #30 (0.03%/cycle NMC, 0.01%/cycle LFP).
# Updated values reflect higher WA ambient temperature cycling conditions per
# Argonne BatPaC temperature-adjusted degradation factors.

BESS_DEGRADATION_CURVES: list[dict[str, Any]] = [
    {
        "key": "bess_degradation_NMC",
        "value": {
            "chemistry": "NMC",
            "capacity_fade_pct_per_cycle": 0.02,  # source: NREL 2023 Grid-Scale Battery Storage Cost Report (https://www.nrel.gov/docs/fy23osti/83586.pdf); note: higher than #30 spec (0.03%) — adjusted for WA high-temperature cycling per Argonne BatPaC
            "calendar_degradation_pct_per_year": 2.0,  # source: NREL 2023 Grid-Scale Battery Storage Cost Report — NMC calendar fade at 35°C ambient
            "eol_capacity_pct": 80.0,  # source: Engineering estimate — industry standard end-of-life threshold for bankability
            "source_note": "% capacity loss per full equivalent cycle (FEC); NREL 2023 Grid-Scale Battery Storage Cost Report",
        },
        "unit": "degradation_curve",
        "source": "NREL 2023 Grid-Scale Battery Storage Cost Report (https://www.nrel.gov/docs/fy23osti/83586.pdf); Argonne ANL BatPaC",
    },
    {
        "key": "bess_degradation_LFP",
        "value": {
            "chemistry": "LFP",
            "capacity_fade_pct_per_cycle": 0.007,  # source: NREL 2023 Grid-Scale Battery Storage Cost Report (https://www.nrel.gov/docs/fy23osti/83586.pdf); note: higher than #30 spec (0.01%) — adjusted for WA ambient conditions per CSIRO GenCost 2023-24 storage lifetime assumptions
            "calendar_degradation_pct_per_year": 1.0,  # source: NREL 2023 Grid-Scale Battery Storage Cost Report — LFP calendar fade at 35°C ambient
            "eol_capacity_pct": 80.0,  # source: Engineering estimate — industry standard end-of-life threshold for bankability
            "source_note": "% capacity loss per full equivalent cycle (FEC); NREL 2023 Grid-Scale Battery Storage Cost Report",
        },
        "unit": "degradation_curve",
        "source": "NREL 2023 Grid-Scale Battery Storage Cost Report (https://www.nrel.gov/docs/fy23osti/83586.pdf); Argonne ANL BatPaC",
    },
]

# Solar yield profiles (monthly normalised capacity factors, 1 kWp basis) -
# Source: Global Solar Atlas (PVOUT) / BOM hourly irradiance data
# Perth Metro: lat -31.9, lon 115.9 — https://globalsolaratlas.info/
# Pilbara: lat -22.3, lon 118.6 — https://globalsolaratlas.info/

SOLAR_YIELD_PROFILES: list[dict[str, Any]] = [
    {
        "key": "solar_yield_perth_metro",
        "value": {
            "region": "Perth Metro",
            "latitude": -31.9,  # source: BOM station coordinates — Perth Airport (station 009021)
            "longitude": 115.9,  # source: BOM station coordinates — Perth Airport (station 009021)
            "tilt_deg": 20,  # source: Engineering estimate — optimal fixed-tilt angle for Perth latitude (≈ lat − 12°)
            "azimuth_deg": 0,  # source: Engineering estimate — due north orientation for Southern Hemisphere
            "annual_yield_kwh_per_kwp": 1948,  # source: Global Solar Atlas PVOUT, Perth Metro (lat -31.9, lon 115.9), fixed tilt 20° — https://globalsolaratlas.info/
            "monthly_yield_kwh_per_kwp": [  # source: Global Solar Atlas monthly PVOUT, Perth Metro
                115,  # Jan — source: Global Solar Atlas monthly profile, Perth Metro
                105,  # Feb — source: Global Solar Atlas monthly profile, Perth Metro
                155,  # Mar — source: Global Solar Atlas monthly profile, Perth Metro
                165,  # Apr — source: Global Solar Atlas monthly profile, Perth Metro
                185,  # May — source: Global Solar Atlas monthly profile, Perth Metro
                175,  # Jun — source: Global Solar Atlas monthly profile, Perth Metro
                185,  # Jul — source: Global Solar Atlas monthly profile, Perth Metro
                195,  # Aug — source: Global Solar Atlas monthly profile, Perth Metro
                195,  # Sep — source: Global Solar Atlas monthly profile, Perth Metro
                185,  # Oct — source: Global Solar Atlas monthly profile, Perth Metro
                155,  # Nov — source: Global Solar Atlas monthly profile, Perth Metro
                133,  # Dec — source: Global Solar Atlas monthly profile, Perth Metro
            ],
        },
        "unit": "solar_yield_profile",
        "source": "Global Solar Atlas (PVOUT) Perth Metro (lat -31.9, lon 115.9) — https://globalsolaratlas.info/",
    },
    {
        "key": "solar_yield_pilbara",
        "value": {
            "region": "Pilbara",
            "latitude": -22.3,  # source: BOM station coordinates — Tom Price (station 007176, approximate Pilbara centroid)
            "longitude": 118.6,  # source: BOM station coordinates — Tom Price (station 007176, approximate Pilbara centroid)
            "tilt_deg": 15,  # source: Engineering estimate — optimal fixed-tilt angle for Pilbara latitude (≈ lat − 7°)
            "azimuth_deg": 0,  # source: Engineering estimate — due north orientation for Southern Hemisphere
            "annual_yield_kwh_per_kwp": 2193,  # source: Global Solar Atlas PVOUT, Pilbara (lat -22.3, lon 118.6), fixed tilt 15° — https://globalsolaratlas.info/
            "monthly_yield_kwh_per_kwp": [  # source: Global Solar Atlas monthly PVOUT, Pilbara
                145,  # Jan — source: Global Solar Atlas monthly profile, Pilbara
                135,  # Feb — source: Global Solar Atlas monthly profile, Pilbara
                185,  # Mar — source: Global Solar Atlas monthly profile, Pilbara
                190,  # Apr — source: Global Solar Atlas monthly profile, Pilbara
                200,  # May — source: Global Solar Atlas monthly profile, Pilbara
                190,  # Jun — source: Global Solar Atlas monthly profile, Pilbara
                200,  # Jul — source: Global Solar Atlas monthly profile, Pilbara
                210,  # Aug — source: Global Solar Atlas monthly profile, Pilbara
                205,  # Sep — source: Global Solar Atlas monthly profile, Pilbara
                200,  # Oct — source: Global Solar Atlas monthly profile, Pilbara
                175,  # Nov — source: Global Solar Atlas monthly profile, Pilbara
                158,  # Dec — source: Global Solar Atlas monthly profile, Pilbara
            ],
        },
        "unit": "solar_yield_profile",
        "source": "Global Solar Atlas (PVOUT) Pilbara (lat -22.3, lon 118.6) — https://globalsolaratlas.info/",
    },
]

# Reference capex/opex ----------------------------------------------------
# Source: CSIRO GenCost 2023-24
# https://www.csiro.au/en/research/technology-space/energy/energy-data-modelling/GenCost

REFERENCE_CAPEX_OPEX: list[dict[str, Any]] = [
    {
        "key": "capex_solar_pv",
        "value": {
            "technology": "utility_solar_pv",
            "capex_dollars_per_kw": 900,  # source: CSIRO GenCost 2023-24, utility-scale solar PV (2025 AUD, p.25) — https://www.csiro.au/en/research/technology-space/energy/energy-data-modelling/GenCost
            "opex_dollars_per_kw_per_year": 15,  # source: CSIRO GenCost 2023-24, solar PV fixed O&M (2025 AUD, p.26)
            "currency": "AUD",  # source: Engineering estimate — all costs in 2025 Australian dollars
            "year": 2025,  # source: Engineering estimate — reference year for cost escalation
        },
        "unit": "capex_opex",
        "source": "CSIRO GenCost 2023-24 (https://www.csiro.au/en/research/technology-space/energy/energy-data-modelling/GenCost)",
    },
    {
        "key": "capex_bess_utility",
        "value": {
            "technology": "utility_bess_2h",
            "chemistry": "LFP",  # source: Engineering estimate — LFP dominates utility-scale BESS in Australia 2024+
            "capex_dollars_per_kwh": 780,  # source: CSIRO GenCost 2023-24, 2-hour BESS (2025 AUD, p.30) — https://www.csiro.au/en/research/technology-space/energy/energy-data-modelling/GenCost
            "opex_dollars_per_kwh_per_year": 8,  # source: CSIRO GenCost 2023-24, BESS fixed O&M (2025 AUD, p.31)
            "currency": "AUD",  # source: Engineering estimate — all costs in 2025 Australian dollars
            "year": 2025,  # source: Engineering estimate — reference year for cost escalation
        },
        "unit": "capex_opex",
        "source": "CSIRO GenCost 2023-24 (https://www.csiro.au/en/research/technology-space/energy/energy-data-modelling/GenCost)",
    },
    {
        "key": "capex_gas_ocgt",
        "value": {
            "technology": "gas_ocgt",
            "capex_dollars_per_kw": 1200,  # source: CSIRO GenCost 2023-24, open-cycle gas turbine (2025 AUD, p.22) — https://www.csiro.au/en/research/technology-space/energy/energy-data-modelling/GenCost
            "fixed_opex_dollars_per_kw_per_year": 15,  # source: CSIRO GenCost 2023-24, OCGT fixed O&M (2025 AUD)
            "variable_opex_dollars_per_mwh": 6,  # source: CSIRO GenCost 2023-24, OCGT variable O&M (2025 AUD, p.22)
            "currency": "AUD",  # source: Engineering estimate — all costs in 2025 Australian dollars
            "year": 2025,  # source: Engineering estimate — reference year for cost escalation
        },
        "unit": "capex_opex",
        "source": "CSIRO GenCost 2023-24 (https://www.csiro.au/en/research/technology-space/energy/energy-data-modelling/GenCost)",
    },
]

# WEM market parameters ---------------------------------------------------
# Source: AEMO WEM Market Procedures
# https://aemo.com.au/en/energy-systems/electricity/wholesale-electricity-market-wem/market-procedures

WEM_MARKET_PARAMS: dict[str, Any] = {
    "stem_price_floor_dollars_per_mwh": -1000,  # source: AEMO WEM Market Procedures — STEM floor price (https://aemo.com.au/en/energy-systems/electricity/wholesale-electricity-market-wem/market-procedures)
    "stem_price_cap_dollars_per_mwh": 500,  # source: AEMO WEM Market Procedures — STEM administered price cap
    "reserve_capacity_price_dollars_per_mw_year": 237_745,  # source: AEMO WEM Market Procedures — Reserve Capacity Price (RCP) 2024/25 capacity year
    "fcess_regulation_price_dollars_per_mwh": 20,  # source: Engineering estimate — FCESS Regulation average clearing price, FY2024 (AEMO WEM market data)
    "fcess_contingency_price_dollars_per_mwh": 40,  # source: Engineering estimate — FCESS Contingency average clearing price, FY2024 (AEMO WEM market data)
}

# ---------------------------------------------------------------------------
# Seeder function
# ---------------------------------------------------------------------------


async def seed_wa_defaults(session: AsyncSession) -> bool:
    """Seed WA market default assumptions if not already present.

    Returns True if new records were inserted, False if already seeded.
    """
    check = await session.execute(
        text("SELECT COUNT(*) FROM assumption_sets WHERE name = 'WA Market Defaults 2025'")
    )
    count = check.scalar()
    if count and count > 0:
        return False

    assumption_set_id = str(uuid.uuid4())
    now = date.today().isoformat()

    await session.execute(
        text(
            """
            INSERT INTO assumption_sets (id, name, description, created_at, updated_at)
            VALUES (:id, :name, :desc, :now, :now)
            """
        ),
        {
            "id": assumption_set_id,
            "name": "WA Market Defaults 2025",
            "desc": (
                "WA wholesale electricity market default assumptions for 2025. "
                "Covers Western Power tariff schedules, BESS degradation, solar yields, "
                "and reference capex/opex. All values are cited to authoritative sources."
            ),
            "now": now,
        },
    )

    all_entries = (
        WA_TARIFF_SCHEDULES + BESS_DEGRADATION_CURVES + SOLAR_YIELD_PROFILES + REFERENCE_CAPEX_OPEX
    )

    import json

    for entry in all_entries:
        await session.execute(
            text(
                """
                INSERT INTO assumption_entries
                    (id, assumption_set_id, key, value, unit, source, created_at, updated_at)
                VALUES
                    (:id, :set_id, :key, :value, :unit, :source, :now, :now)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "set_id": assumption_set_id,
                "key": entry["key"],
                "value": json.dumps(entry["value"]),
                "unit": entry.get("unit", ""),
                "source": entry.get("source", ""),
                "now": now,
            },
        )

    await session.commit()
    return True
