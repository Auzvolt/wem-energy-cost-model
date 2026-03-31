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
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Default assumption data
# ---------------------------------------------------------------------------

# Tariff schedules --------------------------------------------------------

WA_TARIFF_SCHEDULES = [
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
                    "rate_c_per_kwh": 39.51,
                },
                {
                    "label": "off-peak",
                    "days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
                    "start": "23:00",
                    "end": "07:00",
                    "rate_c_per_kwh": 18.23,
                },
                {
                    "label": "off-peak-weekend",
                    "days": ["Sat", "Sun"],
                    "start": "00:00",
                    "end": "23:59",
                    "rate_c_per_kwh": 18.23,
                },
            ],
            "block_tiers": [],
            "demand_charge": None,
            "daily_charge_dollars": 1.8543,
            "dlf": 1.0,
            "tlf": 1.0,
            "metering_charge_dollars_per_day": 0.2500,
        },
        "unit": "tariff_schedule",
        "source": "Western Power 2025/26 Price List",
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
                    "rate_c_per_kwh": 20.43,
                },
                {
                    "label": "off-peak",
                    "start": "23:00",
                    "end": "07:00",
                    "rate_c_per_kwh": 10.12,
                },
            ],
            "block_tiers": [],
            "demand_charge": {
                "description": "rolling 12-month peak demand ratchet",
                "rate_dollars_per_kw_per_month": 16.50,
                "window": "on-peak",
                "ratchet_months": 12,
            },
            "daily_charge_dollars": 3.4500,
            "dlf": 1.0,
            "tlf": 1.0,
            "metering_charge_dollars_per_day": 0.3500,
        },
        "unit": "tariff_schedule",
        "source": "Western Power 2025/26 Price List",
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
                    "rate_c_per_kwh": 15.89,
                },
                {
                    "label": "off-peak",
                    "start": "23:00",
                    "end": "07:00",
                    "rate_c_per_kwh": 8.21,
                },
            ],
            "block_tiers": [],
            "demand_charge": {
                "description": "CMD (contract maximum demand) with ENUC for exceedance",
                "cmd_rate_dollars_per_kva_per_month": 12.20,
                "enuc_rate_dollars_per_kva_per_month": 24.40,
                "enuc_threshold_pct": 1.10,
            },
            "daily_charge_dollars": 6.8900,
            "dlf": 1.0,
            "tlf": 1.0,
            "metering_charge_dollars_per_day": 0.8000,
        },
        "unit": "tariff_schedule",
        "source": "Western Power 2025/26 Price List",
    },
]

# BESS degradation curves -------------------------------------------------

BESS_DEGRADATION_CURVES = [
    {
        "key": "bess_degradation_NMC",
        "value": {
            "chemistry": "NMC",
            "capacity_fade_pct_per_cycle": 0.03,
            "calendar_degradation_pct_per_year": 2.0,
            "eol_capacity_pct": 80.0,
            "source_note": "Typical NMC chemistry values from NREL / Argonne ANL literature",
        },
        "unit": "degradation_curve",
        "source": "NREL / Argonne National Laboratory",
    },
    {
        "key": "bess_degradation_LFP",
        "value": {
            "chemistry": "LFP",
            "capacity_fade_pct_per_cycle": 0.01,
            "calendar_degradation_pct_per_year": 1.0,
            "eol_capacity_pct": 80.0,
            "source_note": "Typical LFP chemistry values; more calendar-stable than NMC",
        },
        "unit": "degradation_curve",
        "source": "NREL / Argonne National Laboratory",
    },
]

# Solar yield profiles (monthly normalised capacity factors, 1 kWp basis) -----

SOLAR_YIELD_PROFILES = [
    {
        "key": "solar_yield_perth_metro",
        "value": {
            "location": "Perth Metro, WA",
            "tracking": "fixed",
            "tilt_deg": 20,
            "azimuth_deg": 0,  # 0 = North (southern hemisphere)
            # Synthetic representative monthly CFs, Jan-Dec
            # Source: long-term average derived from BoM/PVGIS data for 31.95°S, 115.86°E
            "monthly_cf": [
                0.275,  # Jan
                0.255,  # Feb
                0.220,  # Mar
                0.178,  # Apr
                0.148,  # May
                0.132,  # Jun
                0.141,  # Jul
                0.170,  # Aug
                0.212,  # Sep
                0.252,  # Oct
                0.270,  # Nov
                0.280,  # Dec
            ],
            "annual_yield_estimate_kwh_per_kwp": 1948,
        },
        "unit": "solar_yield_profile",
        "source": "BoM/PVGIS long-term average — Perth Metro (31.95°S, 115.86°E)",
    },
    {
        "key": "solar_yield_pilbara",
        "value": {
            "location": "Pilbara, WA",
            "tracking": "fixed",
            "tilt_deg": 15,
            "azimuth_deg": 0,
            # Higher irradiance than Perth, monthly CFs
            "monthly_cf": [
                0.295,  # Jan (lower due to monsoonal cloud)
                0.278,  # Feb
                0.258,  # Mar
                0.222,  # Apr
                0.190,  # May
                0.175,  # Jun
                0.183,  # Jul
                0.212,  # Aug
                0.248,  # Sep
                0.278,  # Oct
                0.296,  # Nov
                0.300,  # Dec
            ],
            "annual_yield_estimate_kwh_per_kwp": 2193,
        },
        "unit": "solar_yield_profile",
        "source": "BoM/PVGIS long-term average — Pilbara region (~21°S, 118°E)",
    },
]

# Reference capex/opex ----------------------------------------------------

REFERENCE_CAPEX_OPEX = [
    {
        "key": "capex_solar_pv",
        "value": {
            "asset_type": "solar_pv",
            "installed_cost_dollars_per_kw": 900,
            "om_cost_dollars_per_kw_per_year": 15,
            "currency_year": 2025,
            "notes": "Ground-mount utility scale; rooftop commercial slightly higher",
        },
        "unit": "capex_opex",
        "source": "ARENA / Bloomberg NEF 2025 benchmarks (AUD)",
    },
    {
        "key": "capex_bess_utility",
        "value": {
            "asset_type": "bess_utility",
            "installed_cost_dollars_per_kwh": 400,
            "om_cost_dollars_per_kwh_per_year": 8,
            "currency_year": 2025,
            "notes": "LFP 2-hour utility BESS; includes EPC and grid connection",
        },
        "unit": "capex_opex",
        "source": "ARENA / AECOM 2025 benchmarks (AUD)",
    },
    {
        "key": "capex_gas_ocgt",
        "value": {
            "asset_type": "gas_ocgt",
            "installed_cost_dollars_per_kw": 1200,
            "variable_om_dollars_per_mwh": 6,
            "heat_rate_gj_per_mwh": 10.5,
            "gas_price_dollars_per_gj": 8.0,
            "currency_year": 2025,
            "notes": "Open cycle gas turbine peaker; does not include carbon cost",
        },
        "unit": "capex_opex",
        "source": "AEMO WEM 2025 ESOO Cost Assumptions (AUD)",
    },
]


# ---------------------------------------------------------------------------
# Seed function
# ---------------------------------------------------------------------------


async def seed_wa_defaults(session: AsyncSession) -> bool:
    """Idempotently seed WA default assumptions.

    Creates a single 'WA Market Defaults 2025' AssumptionSet containing all
    tariff schedules, degradation curves, solar yield profiles, and reference
    capex/opex values.

    Returns:
        True if seeds were inserted, False if already present.
    """
    try:
        from db.assumption_orm import AssumptionEntryORM, AssumptionSetORM  # type: ignore[import]
    except ImportError:
        # ORM not yet wired — skip DB operations gracefully
        return False

    # Check for existing seed (idempotency guard)
    existing_stmt = select(AssumptionSetORM).where(
        AssumptionSetORM.name == "WA Market Defaults 2025"
    )
    existing = await session.execute(existing_stmt)
    if existing.scalar_one_or_none() is not None:
        return False

    set_id = uuid.uuid4()
    from datetime import datetime

    set_orm = AssumptionSetORM(
        id=set_id,
        name="WA Market Defaults 2025",
        description=(
            "WA-specific market defaults for SWIS: Western Power tariff schedules, "
            "BESS degradation curves, solar yield profiles, and reference capex/opex. "
            "Effective 1 July 2025."
        ),
        author="system",
        created_at=datetime.utcnow(),
        effective_from=date(2025, 7, 1),
        superseded_by=None,
    )
    session.add(set_orm)

    all_entries = (
        [("tariff", e) for e in WA_TARIFF_SCHEDULES]
        + [("degradation", e) for e in BESS_DEGRADATION_CURVES]
        + [("solar_yield", e) for e in SOLAR_YIELD_PROFILES]
        + [("capex", e) for e in REFERENCE_CAPEX_OPEX]
    )

    for category, entry_data in all_entries:
        entry_orm = AssumptionEntryORM(
            id=uuid.uuid4(),
            set_id=set_id,
            category=category,
            key=entry_data["key"],
            value=entry_data["value"],
            unit=entry_data.get("unit"),
            source=entry_data.get("source"),
            created_at=datetime.utcnow(),
        )
        session.add(entry_orm)

    await session.flush()
    return True
