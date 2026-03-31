"""Tests for SQLAlchemy ORM models using in-memory SQLite."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models import (
    Asset,
    Base,
    Facility,
    Interval,
    PriceInterval,
    Scenario,
    ScenarioResult,
)

TEST_DATABASE_URL = "sqlite+aiosqlite://"


@pytest_asyncio.fixture
async def session() -> AsyncSession:  # type: ignore[misc]
    """Create an in-memory SQLite async session with all tables."""
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as sess:
        yield sess
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_facility(session: AsyncSession) -> None:
    facility = Facility(
        facility_code="ALINTA_WGP",
        facility_name="Alinta WGP Power Station",
        technology_type="Gas",
        capacity_mw=120.0,
    )
    session.add(facility)
    await session.flush()

    result = await session.get(Facility, "ALINTA_WGP")
    assert result is not None
    assert result.facility_name == "Alinta WGP Power Station"
    assert result.capacity_mw == 120.0


@pytest.mark.asyncio
async def test_create_interval_with_facility(session: AsyncSession) -> None:
    facility = Facility(
        facility_code="TEST_FAC",
        facility_name="Test Facility",
    )
    session.add(facility)
    await session.flush()

    ts = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
    interval = Interval(
        interval_start=ts,
        facility_code="TEST_FAC",
        actual_mw=50.0,
        trading_price_aud_mwh=85.50,
    )
    session.add(interval)
    await session.flush()

    result = await session.get(Interval, interval.id)
    assert result is not None
    assert result.actual_mw == 50.0
    assert result.facility_code == "TEST_FAC"


@pytest.mark.asyncio
async def test_create_price_interval(session: AsyncSession) -> None:
    ts = datetime(2024, 1, 1, 0, 30, 0, tzinfo=UTC)
    pi = PriceInterval(
        interval_start=ts,
        region="SW1",
        rrp_aud_mwh=92.10,
        total_demand_mw=1800.0,
    )
    session.add(pi)
    await session.flush()

    result = await session.get(PriceInterval, pi.id)
    assert result is not None
    assert result.rrp_aud_mwh == 92.10
    assert result.region == "SW1"


@pytest.mark.asyncio
async def test_create_asset(session: AsyncSession) -> None:
    asset = Asset(
        id=str(uuid.uuid4()),
        name="Rooftop Solar 100kW",
        asset_type="solar",
        capacity_kw=100.0,
        config={"tilt": 20, "azimuth": 0},
        created_at=datetime.now(tz=UTC),
    )
    session.add(asset)
    await session.flush()

    result = await session.get(Asset, asset.id)
    assert result is not None
    assert result.asset_type == "solar"
    assert result.config["tilt"] == 20


@pytest.mark.asyncio
async def test_scenario_and_results(session: AsyncSession) -> None:
    asset = Asset(
        id=str(uuid.uuid4()),
        name="BESS 200kWh",
        asset_type="bess",
        capacity_kw=100.0,
        config={},
        created_at=datetime.now(tz=UTC),
    )
    scenario = Scenario(
        id=str(uuid.uuid4()),
        name="Base Case 2025",
        created_at=datetime.now(tz=UTC),
        params={"discount_rate": 0.07},
    )
    session.add_all([asset, scenario])
    await session.flush()

    ts = datetime(2024, 6, 1, 0, 0, 0, tzinfo=UTC)
    sr = ScenarioResult(
        id=str(uuid.uuid4()),
        scenario_id=scenario.id,
        interval_start=ts,
        asset_id=asset.id,
        dispatch_kw=75.0,
        revenue_aud=6.38,
    )
    session.add(sr)
    await session.flush()

    fetched = await session.get(ScenarioResult, sr.id)
    assert fetched is not None
    assert fetched.dispatch_kw == 75.0
    assert fetched.scenario_id == scenario.id
    assert fetched.asset_id == asset.id
