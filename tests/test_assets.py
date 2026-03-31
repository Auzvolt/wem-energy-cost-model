"""Tests for the energy asset library — issue #9.

Covers:
- Pydantic model validation (positive capacity, efficiency bounds, SoC ordering)
- Default assets: all 11+ load without error and have positive capacity
- Async CRUD repository: create, read, list, update, delete via in-memory SQLite
  (requires aiosqlite; skipped in sandboxed environments where it is unavailable)
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.assets.defaults import DEFAULT_ASSETS
from app.assets.models import AssetType, BatteryAsset, DemandResponseAsset, GeneratorAsset

# ---------------------------------------------------------------------------
# Model validation — GeneratorAsset
# ---------------------------------------------------------------------------


class TestGeneratorAssetValidation:
    def test_valid_generator(self) -> None:
        g = GeneratorAsset(
            name="Test OCGT",
            technology="OCGT",
            capacity_kw=100_000.0,
            min_stable_load_kw=30_000.0,
            heat_rate_gj_mwh=10.5,
            fuel_cost_aud_gj=9.50,
            variable_om_aud_mwh=7.50,
            start_cost_aud=8_000.0,
        )
        assert g.capacity_kw == 100_000.0
        assert g.asset_type == AssetType.GENERATOR

    def test_zero_capacity_raises(self) -> None:
        with pytest.raises(ValidationError, match="greater than 0"):
            GeneratorAsset(
                name="Bad",
                technology="OCGT",
                capacity_kw=0.0,
                min_stable_load_kw=0.0,
                heat_rate_gj_mwh=10.5,
                fuel_cost_aud_gj=9.50,
                variable_om_aud_mwh=7.50,
                start_cost_aud=0.0,
            )

    def test_negative_capacity_raises(self) -> None:
        with pytest.raises(ValidationError):
            GeneratorAsset(
                name="Bad",
                technology="OCGT",
                capacity_kw=-100.0,
                min_stable_load_kw=0.0,
                heat_rate_gj_mwh=10.5,
                fuel_cost_aud_gj=9.50,
                variable_om_aud_mwh=7.50,
                start_cost_aud=0.0,
            )

    def test_min_load_exceeds_capacity_raises(self) -> None:
        with pytest.raises(ValidationError, match="min_stable_load_kw"):
            GeneratorAsset(
                name="Bad",
                technology="OCGT",
                capacity_kw=100.0,
                min_stable_load_kw=200.0,
                heat_rate_gj_mwh=10.5,
                fuel_cost_aud_gj=9.50,
                variable_om_aud_mwh=7.50,
                start_cost_aud=0.0,
            )

    def test_renewable_zero_heat_rate_valid(self) -> None:
        g = GeneratorAsset(
            name="Solar",
            technology="solar_pv",
            capacity_kw=50_000.0,
            min_stable_load_kw=0.0,
            heat_rate_gj_mwh=0.0,
            fuel_cost_aud_gj=0.0,
            variable_om_aud_mwh=8.0,
            start_cost_aud=0.0,
        )
        assert g.heat_rate_gj_mwh == 0.0


# ---------------------------------------------------------------------------
# Model validation — BatteryAsset
# ---------------------------------------------------------------------------


class TestBatteryAssetValidation:
    def test_valid_battery(self) -> None:
        b = BatteryAsset(
            name="Test BESS",
            capacity_kwh=1000.0,
            power_kw=500.0,
            round_trip_efficiency=0.87,
            soc_min_pct=0.05,
            soc_max_pct=0.95,
            cycle_cost_aud_kwh=8.0,
        )
        assert b.asset_type == AssetType.BATTERY

    def test_zero_capacity_raises(self) -> None:
        with pytest.raises(ValidationError, match="greater than 0"):
            BatteryAsset(
                name="Bad",
                capacity_kwh=0.0,
                power_kw=500.0,
                round_trip_efficiency=0.87,
                soc_min_pct=0.05,
                soc_max_pct=0.95,
                cycle_cost_aud_kwh=8.0,
            )

    def test_zero_efficiency_raises(self) -> None:
        with pytest.raises(ValidationError, match="greater than 0"):
            BatteryAsset(
                name="Bad",
                capacity_kwh=1000.0,
                power_kw=500.0,
                round_trip_efficiency=0.0,
                soc_min_pct=0.05,
                soc_max_pct=0.95,
                cycle_cost_aud_kwh=8.0,
            )

    def test_efficiency_above_one_raises(self) -> None:
        with pytest.raises(ValidationError):
            BatteryAsset(
                name="Bad",
                capacity_kwh=1000.0,
                power_kw=500.0,
                round_trip_efficiency=1.01,
                soc_min_pct=0.05,
                soc_max_pct=0.95,
                cycle_cost_aud_kwh=8.0,
            )

    def test_soc_min_equals_max_raises(self) -> None:
        with pytest.raises(ValidationError, match="soc_min_pct"):
            BatteryAsset(
                name="Bad",
                capacity_kwh=1000.0,
                power_kw=500.0,
                round_trip_efficiency=0.87,
                soc_min_pct=0.50,
                soc_max_pct=0.50,
                cycle_cost_aud_kwh=8.0,
            )

    def test_soc_min_greater_than_max_raises(self) -> None:
        with pytest.raises(ValidationError, match="soc_min_pct"):
            BatteryAsset(
                name="Bad",
                capacity_kwh=1000.0,
                power_kw=500.0,
                round_trip_efficiency=0.87,
                soc_min_pct=0.80,
                soc_max_pct=0.20,
                cycle_cost_aud_kwh=8.0,
            )


# ---------------------------------------------------------------------------
# Model validation — DemandResponseAsset
# ---------------------------------------------------------------------------


class TestDemandResponseValidation:
    def test_valid_dr(self) -> None:
        dr = DemandResponseAsset(
            name="Test DR",
            capacity_kw=5000.0,
            response_time_min=15.0,
            availability_hours_per_day=8.0,
            cost_aud_mwh=150.0,
        )
        assert dr.asset_type == AssetType.DEMAND_RESPONSE

    def test_zero_capacity_raises(self) -> None:
        with pytest.raises(ValidationError, match="greater than 0"):
            DemandResponseAsset(
                name="Bad",
                capacity_kw=0.0,
                response_time_min=15.0,
                availability_hours_per_day=8.0,
                cost_aud_mwh=150.0,
            )

    def test_availability_exceeds_24h_raises(self) -> None:
        with pytest.raises(ValidationError):
            DemandResponseAsset(
                name="Bad",
                capacity_kw=1000.0,
                response_time_min=15.0,
                availability_hours_per_day=25.0,
                cost_aud_mwh=150.0,
            )


# ---------------------------------------------------------------------------
# Default assets
# ---------------------------------------------------------------------------


class TestDefaultAssets:
    def test_at_least_11_defaults(self) -> None:
        assert len(DEFAULT_ASSETS) >= 11

    def test_all_defaults_load_without_error(self) -> None:
        """All defaults must be valid Pydantic models (construction doesn't raise)."""
        for asset in DEFAULT_ASSETS:
            assert asset.name, f"Asset has empty name: {asset}"

    def test_all_generators_have_positive_capacity(self) -> None:
        generators = [a for a in DEFAULT_ASSETS if isinstance(a, GeneratorAsset)]
        assert len(generators) >= 4
        for g in generators:
            assert g.capacity_kw > 0, f"{g.name}: capacity must be > 0"

    def test_all_batteries_have_valid_efficiency(self) -> None:
        batteries = [a for a in DEFAULT_ASSETS if isinstance(a, BatteryAsset)]
        assert len(batteries) >= 3
        for b in batteries:
            assert 0 < b.round_trip_efficiency <= 1.0, f"{b.name}: invalid efficiency"
            assert b.soc_min_pct < b.soc_max_pct, f"{b.name}: SoC bounds invalid"

    def test_all_dr_assets_have_positive_capacity(self) -> None:
        dr_assets = [a for a in DEFAULT_ASSETS if isinstance(a, DemandResponseAsset)]
        assert len(dr_assets) >= 2
        for dr in dr_assets:
            assert dr.capacity_kw > 0, f"{dr.name}: capacity must be > 0"

    def test_asset_types_all_set(self) -> None:
        for asset in DEFAULT_ASSETS:
            assert asset.asset_type in {
                AssetType.GENERATOR,
                AssetType.BATTERY,
                AssetType.DEMAND_RESPONSE,
            }


# ---------------------------------------------------------------------------
# Async CRUD repository (requires aiosqlite)
# ---------------------------------------------------------------------------

_aiosqlite_available = False
try:
    import aiosqlite as _aiosqlite  # noqa: F401

    _aiosqlite_available = True
except ImportError:
    pass

_skip_async = pytest.mark.skipif(
    not _aiosqlite_available,
    reason="aiosqlite not installed",
)


if _aiosqlite_available:
    import pytest_asyncio
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.assets.repository import (
        create_asset,
        delete_asset,
        get_asset,
        list_assets,
        update_asset,
    )
    from app.db.models import Base

    @pytest_asyncio.fixture
    async def async_session() -> AsyncSession:  # type: ignore[misc]
        """In-memory async SQLite session with all ORM tables created."""
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            yield session
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()

    @pytest.mark.asyncio
    class TestAssetRepository:
        async def test_create_and_get(self, async_session: AsyncSession) -> None:
            battery = BatteryAsset(
                name="Repo Test BESS",
                capacity_kwh=500.0,
                power_kw=250.0,
                round_trip_efficiency=0.88,
                soc_min_pct=0.05,
                soc_max_pct=0.95,
                cycle_cost_aud_kwh=9.0,
            )
            asset_id = await create_asset(async_session, battery)
            assert isinstance(asset_id, uuid.UUID)

            retrieved = await get_asset(async_session, asset_id)
            assert retrieved is not None
            assert isinstance(retrieved, BatteryAsset)
            assert retrieved.name == "Repo Test BESS"
            assert retrieved.capacity_kwh == 500.0

        async def test_get_nonexistent_returns_none(self, async_session: AsyncSession) -> None:
            result = await get_asset(async_session, uuid.uuid4())
            assert result is None

        async def test_list_all(self, async_session: AsyncSession) -> None:
            gen = GeneratorAsset(
                name="List Test Gen",
                technology="OCGT",
                capacity_kw=50_000.0,
                min_stable_load_kw=10_000.0,
                heat_rate_gj_mwh=10.5,
                fuel_cost_aud_gj=9.5,
                variable_om_aud_mwh=7.5,
                start_cost_aud=8000.0,
            )
            dr = DemandResponseAsset(
                name="List Test DR",
                capacity_kw=1000.0,
                response_time_min=10.0,
                availability_hours_per_day=6.0,
                cost_aud_mwh=120.0,
            )
            await create_asset(async_session, gen)
            await create_asset(async_session, dr)

            all_assets = await list_assets(async_session)
            assert len(all_assets) == 2

        async def test_list_filtered_by_type(self, async_session: AsyncSession) -> None:
            gen = GeneratorAsset(
                name="Filter Gen",
                technology="wind",
                capacity_kw=50_000.0,
                min_stable_load_kw=0.0,
                heat_rate_gj_mwh=0.0,
                fuel_cost_aud_gj=0.0,
                variable_om_aud_mwh=12.0,
                start_cost_aud=0.0,
            )
            batt = BatteryAsset(
                name="Filter BESS",
                capacity_kwh=1000.0,
                power_kw=500.0,
                round_trip_efficiency=0.90,
                soc_min_pct=0.10,
                soc_max_pct=0.95,
                cycle_cost_aud_kwh=10.0,
            )
            await create_asset(async_session, gen)
            await create_asset(async_session, batt)

            generators = await list_assets(async_session, asset_type=AssetType.GENERATOR)
            assert len(generators) == 1
            assert generators[0].name == "Filter Gen"

            batteries = await list_assets(async_session, asset_type=AssetType.BATTERY)
            assert len(batteries) == 1
            assert batteries[0].name == "Filter BESS"

        async def test_update(self, async_session: AsyncSession) -> None:
            dr = DemandResponseAsset(
                name="Original DR",
                capacity_kw=2000.0,
                response_time_min=20.0,
                availability_hours_per_day=10.0,
                cost_aud_mwh=200.0,
            )
            asset_id = await create_asset(async_session, dr)

            updated_dr = DemandResponseAsset(
                name="Updated DR",
                capacity_kw=3000.0,
                response_time_min=15.0,
                availability_hours_per_day=12.0,
                cost_aud_mwh=180.0,
            )
            success = await update_asset(async_session, asset_id, updated_dr)
            assert success is True

            retrieved = await get_asset(async_session, asset_id)
            assert retrieved is not None
            assert isinstance(retrieved, DemandResponseAsset)
            assert retrieved.name == "Updated DR"
            assert retrieved.capacity_kw == 3000.0

        async def test_update_nonexistent_returns_false(self, async_session: AsyncSession) -> None:
            dr = DemandResponseAsset(
                name="Ghost",
                capacity_kw=1000.0,
                response_time_min=10.0,
                availability_hours_per_day=4.0,
                cost_aud_mwh=100.0,
            )
            result = await update_asset(async_session, uuid.uuid4(), dr)
            assert result is False

        async def test_delete(self, async_session: AsyncSession) -> None:
            batt = BatteryAsset(
                name="Delete Test BESS",
                capacity_kwh=200.0,
                power_kw=100.0,
                round_trip_efficiency=0.90,
                soc_min_pct=0.10,
                soc_max_pct=0.90,
                cycle_cost_aud_kwh=12.0,
            )
            asset_id = await create_asset(async_session, batt)

            deleted = await delete_asset(async_session, asset_id)
            assert deleted is True

            after = await get_asset(async_session, asset_id)
            assert after is None

        async def test_delete_nonexistent_returns_false(self, async_session: AsyncSession) -> None:
            result = await delete_asset(async_session, uuid.uuid4())
            assert result is False
