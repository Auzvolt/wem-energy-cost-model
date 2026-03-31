"""Tests for the extended DB schema (market_prices, interval_readings,
forward curves, assumption library)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models import (
    AssumptionItem,
    AssumptionSet,
    Base,
    ForwardCurve,
    ForwardCurvePoint,
    IntervalReading,
    MarketPrice,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def session() -> AsyncSession:  # type: ignore[override]
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


# ---------------------------------------------------------------------------
# MarketPrice
# ---------------------------------------------------------------------------


async def test_create_market_price(session: AsyncSession) -> None:
    now = datetime.now(UTC)
    mp = MarketPrice(
        interval_start=now,
        settlement_point="SW1",
        product="ENERGY",
        price_aud_mwh=85.50,
        source="aemo_api",
        ingested_at=now,
    )
    session.add(mp)
    await session.commit()
    await session.refresh(mp)
    assert mp.id is not None
    assert mp.price_aud_mwh == pytest.approx(85.50)
    assert mp.product == "ENERGY"


async def test_market_price_unique_constraint(session: AsyncSession) -> None:
    """Inserting a duplicate (interval_start, settlement_point, product) should raise."""
    from sqlalchemy.exc import IntegrityError

    now = datetime.now(UTC)
    mp1 = MarketPrice(
        interval_start=now,
        settlement_point="SW1",
        product="ENERGY",
        price_aud_mwh=80.0,
        source="aemo_api",
        ingested_at=now,
    )
    mp2 = MarketPrice(
        interval_start=now,
        settlement_point="SW1",
        product="ENERGY",
        price_aud_mwh=90.0,
        source="aemo_api",
        ingested_at=now,
    )
    session.add(mp1)
    await session.commit()
    session.add(mp2)
    with pytest.raises(IntegrityError):
        await session.commit()


# ---------------------------------------------------------------------------
# IntervalReading
# ---------------------------------------------------------------------------


async def test_create_interval_reading(session: AsyncSession) -> None:
    now = datetime.now(UTC)
    reading = IntervalReading(
        meter_id="NMI12345",
        interval_start=now,
        interval_minutes=30,
        kwh=12.5,
        quality_flag="A",
        imported_at=now,
    )
    session.add(reading)
    await session.commit()
    await session.refresh(reading)
    assert reading.id is not None
    assert reading.kwh == pytest.approx(12.5)
    assert reading.meter_id == "NMI12345"


# ---------------------------------------------------------------------------
# ForwardCurve + ForwardCurvePoint
# ---------------------------------------------------------------------------


async def test_forward_curve_with_points(session: AsyncSession) -> None:
    now = datetime.now(UTC)
    curve = ForwardCurve(
        name="FY2025 Base",
        product="ENERGY",
        version=1,
        created_at=now,
        created_by="analyst@example.com",
    )
    session.add(curve)
    await session.flush()

    point = ForwardCurvePoint(
        curve_id=curve.id,
        interval_start=now,
        settlement_point="SW1",
        price_aud_mwh=95.0,
    )
    session.add(point)
    await session.commit()

    await session.refresh(curve)
    assert len(curve.points) == 1
    assert curve.points[0].price_aud_mwh == pytest.approx(95.0)


async def test_forward_curve_version_unique(session: AsyncSession) -> None:
    """Same name/product/version should fail."""
    from sqlalchemy.exc import IntegrityError

    now = datetime.now(UTC)
    c1 = ForwardCurve(name="TestCurve", product="ENERGY", version=1, created_at=now)
    c2 = ForwardCurve(name="TestCurve", product="ENERGY", version=1, created_at=now)
    session.add(c1)
    await session.commit()
    session.add(c2)
    with pytest.raises(IntegrityError):
        await session.commit()


# ---------------------------------------------------------------------------
# AssumptionSet + AssumptionItem
# ---------------------------------------------------------------------------


async def test_assumption_set_with_items(session: AsyncSession) -> None:
    now = datetime.now(UTC)
    aset = AssumptionSet(
        name="WA Default 2025",
        description="Standard WA assumptions",
        created_at=now,
        created_by="admin",
    )
    session.add(aset)
    await session.flush()

    item = AssumptionItem(
        assumption_set_id=aset.id,
        category="bess",
        key="capex_aud_kwh",
        value="650",
        unit="AUD/kWh",
        version=1,
        changed_at=now,
        changed_by="admin",
    )
    session.add(item)
    await session.commit()

    await session.refresh(aset)
    assert len(aset.items) == 1
    assert aset.items[0].value == "650"
    assert aset.items[0].unit == "AUD/kWh"


async def test_assumption_item_audit(session: AsyncSession) -> None:
    """Version 2 of an assumption stores the previous value."""
    now = datetime.now(UTC)
    aset = AssumptionSet(name="Audit Test", created_at=now)
    session.add(aset)
    await session.flush()

    v1 = AssumptionItem(
        assumption_set_id=aset.id,
        category="solar",
        key="capex_aud_w",
        value="0.80",
        unit="AUD/W",
        version=1,
        changed_at=now,
    )
    session.add(v1)
    await session.commit()

    v2 = AssumptionItem(
        assumption_set_id=aset.id,
        category="solar",
        key="capex_aud_w",
        value="0.75",
        unit="AUD/W",
        version=2,
        changed_at=datetime.now(UTC),
        previous_value="0.80",
    )
    session.add(v2)
    await session.commit()

    await session.refresh(aset)
    versions = sorted(aset.items, key=lambda x: x.version)
    assert len(versions) == 2
    assert versions[1].previous_value == "0.80"
    assert versions[1].value == "0.75"
