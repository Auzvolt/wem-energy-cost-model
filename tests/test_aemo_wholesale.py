"""Tests for the AEMO WA wholesale price connector.

All HTTP calls are mocked — no network access required.
"""

from __future__ import annotations

import urllib.error
from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from db.models import Base
from pipeline.aemo_wholesale import (
    _parse_trading_price_csv,
    _upsert_prices,
    ingest_wholesale_prices,
)

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

# ---------------------------------------------------------------------------
# Sample CSV in AEMO WA trading-price format
# ---------------------------------------------------------------------------

SAMPLE_CSV = """\
Trading Date,Trading Interval,Settlement Point,Trading Price ($/MWh)
2024-01-15,1,SW1,75.50
2024-01-15,2,SW1,78.00
2024-01-15,3,SW1,72.30
2024-01-15,1,NW1,80.00
2024-01-15,96,SW1,65.00
"""

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
# Unit tests: CSV parsing
# ---------------------------------------------------------------------------


def test_parse_csv_filters_settlement_point() -> None:
    rows = _parse_trading_price_csv(SAMPLE_CSV, "SW1")
    # Should only include SW1 rows (4 rows)
    assert all(r["settlement_point"] == "SW1" for r in rows)
    assert len(rows) == 4


def test_parse_csv_interval_1_is_midnight() -> None:
    rows = _parse_trading_price_csv(SAMPLE_CSV, "SW1")
    midnight_row = next(r for r in rows if r["price_aud_mwh"] == pytest.approx(75.50))
    # Interval 1 → offset 0 min → midnight AWST = 16:00 UTC prev day
    assert midnight_row["interval_start"].hour == 16
    assert midnight_row["interval_start"].tzinfo is not None


def test_parse_csv_interval_96_is_23h55() -> None:
    rows = _parse_trading_price_csv(SAMPLE_CSV, "SW1")
    last_row = next(r for r in rows if r["price_aud_mwh"] == pytest.approx(65.00))
    # Interval 96 → offset (95)*5 = 475 min = 7h55 AWST = 23:55 UTC prev day
    assert last_row["interval_start"].minute == 55


def test_parse_csv_price_values() -> None:
    rows = _parse_trading_price_csv(SAMPLE_CSV, "SW1")
    prices = {r["price_aud_mwh"] for r in rows}
    assert 75.50 in prices
    assert 78.00 in prices
    assert 72.30 in prices


def test_parse_csv_product_is_energy() -> None:
    rows = _parse_trading_price_csv(SAMPLE_CSV, "SW1")
    assert all(r["product"] == "ENERGY" for r in rows)


def test_parse_csv_no_filter_returns_all_points() -> None:
    rows = _parse_trading_price_csv(SAMPLE_CSV, "")
    # 5 rows total (4 SW1 + 1 NW1)
    assert len(rows) == 5


def test_parse_csv_empty_returns_empty() -> None:
    rows = _parse_trading_price_csv(
        "Trading Date,Trading Interval,Settlement Point,Trading Price ($/MWh)\n", "SW1"
    )
    assert rows == []


# ---------------------------------------------------------------------------
# Unit tests: database upsert
# ---------------------------------------------------------------------------


async def test_upsert_prices_inserts_rows(session: AsyncSession) -> None:
    from sqlalchemy import text

    rows = _parse_trading_price_csv(SAMPLE_CSV, "SW1")
    n = await _upsert_prices(session, rows)
    assert n == 4
    result = await session.execute(text("SELECT COUNT(*) FROM market_prices"))
    assert result.scalar() == 4


async def test_upsert_prices_idempotent(session: AsyncSession) -> None:
    from sqlalchemy import text

    rows = _parse_trading_price_csv(SAMPLE_CSV, "SW1")
    await _upsert_prices(session, rows)
    # Upsert again — should overwrite, not duplicate
    n = await _upsert_prices(session, rows)
    assert n == 4
    result = await session.execute(text("SELECT COUNT(*) FROM market_prices"))
    assert result.scalar() == 4


async def test_upsert_empty_rows(session: AsyncSession) -> None:
    n = await _upsert_prices(session, [])
    assert n == 0


# ---------------------------------------------------------------------------
# Integration test: ingest_wholesale_prices with mocked HTTP
# ---------------------------------------------------------------------------


async def test_ingest_wholesale_prices_mocked() -> None:
    """End-to-end: mock urllib response → parse → upsert."""
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)

    # Mock _fetch_url_sync to return our sample CSV
    def mock_fetch_url_sync(url: str, timeout: float = 60.0) -> str:  # noqa: ARG001
        return SAMPLE_CSV

    with (
        patch("pipeline.aemo_wholesale.AsyncSessionLocal", factory),
        patch("pipeline.aemo_wholesale._fetch_url_sync", side_effect=mock_fetch_url_sync),
    ):
        result = await ingest_wholesale_prices(
            start=date(2024, 1, 1),
            end=date(2024, 1, 31),
            settlement_point="SW1",
        )

    assert result["months_fetched"] == 1
    assert result["rows_inserted"] == 4  # 4 SW1 rows in SAMPLE_CSV

    async with factory() as s:
        from sqlalchemy import text

        r = await s.execute(text("SELECT COUNT(*) FROM market_prices WHERE product='ENERGY'"))
        assert r.scalar() == 4

    await engine.dispose()


async def test_ingest_handles_http_error_gracefully() -> None:
    """HTTP failures should be logged but not crash — result shows 0 rows."""
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)

    def mock_fetch_fail(url: str, timeout: float = 60.0) -> str:  # noqa: ARG001
        raise urllib.error.URLError("connection refused")

    with (
        patch("pipeline.aemo_wholesale.AsyncSessionLocal", factory),
        patch("pipeline.aemo_wholesale._fetch_url_sync", side_effect=mock_fetch_fail),
        patch("pipeline.aemo_wholesale._RETRY_DELAYS", ()),  # no retries
    ):
        result = await ingest_wholesale_prices(
            start=date(2024, 1, 1),
            end=date(2024, 1, 31),
            settlement_point="SW1",
        )

    assert result["rows_inserted"] == 0
    await engine.dispose()
