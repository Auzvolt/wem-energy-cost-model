"""Tests for WholesalePriceConnector and helpers."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
import pytest

from app.pipeline.wholesale_price_connector import (
    FCESS_PRODUCTS,
    WholesalePriceConnector,
    WholesalePriceRecord,
    balancing_summary_url,
    fcess_price_url,
    parse_balancing_csv,
    parse_fcess_csv,
)

# ---------------------------------------------------------------------------
# URL builder tests
# ---------------------------------------------------------------------------


def test_balancing_summary_url_format() -> None:
    url = balancing_summary_url(date(2024, 3, 15))
    assert "BalancingSummary_20240315.csv" in url
    assert url.startswith("https://data.wa.aemo.com.au")


def test_fcess_price_url_format() -> None:
    url = fcess_price_url(date(2024, 3, 15), "REGULATION_RAISE")
    assert "regulation-raise" in url
    assert "20240315" in url
    assert url.startswith("https://data.wa.aemo.com.au")


def test_fcess_products_count() -> None:
    assert len(FCESS_PRODUCTS) == 5


# ---------------------------------------------------------------------------
# CSV parser tests
# ---------------------------------------------------------------------------


_BALANCING_CSV = """\
DISPATCH_INTERVAL_START,MARKET_CLEARING_PRICE,QUANTITY
2024-03-15 00:00:00,85.50,100
2024-03-15 00:05:00,87.00,100
2024-03-15 00:10:00,82.25,100
"""


def test_parse_balancing_csv_returns_records() -> None:
    records = parse_balancing_csv(_BALANCING_CSV, source_url="http://test/balancing.csv")
    assert len(records) == 3


def test_parse_balancing_csv_price_values() -> None:
    records = parse_balancing_csv(_BALANCING_CSV, source_url="http://test/balancing.csv")
    prices = [r.price_aud_mwh for r in records]
    assert prices == pytest.approx([85.50, 87.00, 82.25])


def test_parse_balancing_csv_product_is_energy() -> None:
    records = parse_balancing_csv(_BALANCING_CSV, source_url="http://test/balancing.csv")
    assert all(r.product == "ENERGY" for r in records)


def test_parse_balancing_csv_timestamps_utc() -> None:
    records = parse_balancing_csv(_BALANCING_CSV, source_url="http://test/balancing.csv")
    # AWST is UTC+8, so 00:00 AWST → 16:00 previous day UTC
    first_ts = records[0].interval_start_utc
    assert first_ts.tzinfo == UTC
    assert first_ts.hour == 16  # 00:00 AWST = 16:00 UTC
    assert first_ts.day == 14   # previous UTC day


def test_parse_balancing_csv_empty() -> None:
    records = parse_balancing_csv("", source_url="http://test/empty.csv")
    assert records == []


def test_parse_balancing_csv_missing_price_column() -> None:
    csv = "INTERVAL_START,QUANTITY\n2024-03-15 00:00:00,100\n"
    records = parse_balancing_csv(csv, source_url="http://test/noprice.csv")
    assert records == []


_FCESS_CSV = """\
DISPATCH_INTERVAL_START,MARKET_CLEARING_PRICE
2024-03-15 00:00:00,12.50
2024-03-15 00:05:00,11.00
"""


def test_parse_fcess_csv_returns_records() -> None:
    records = parse_fcess_csv(
        _FCESS_CSV,
        product="REGULATION_RAISE",
        source_url="http://test/fcess.csv",
    )
    assert len(records) == 2


def test_parse_fcess_csv_product_name() -> None:
    records = parse_fcess_csv(
        _FCESS_CSV,
        product="CONTINGENCY_RESERVE_RAISE",
        source_url="http://test/fcess.csv",
    )
    assert all(r.product == "CONTINGENCY_RESERVE_RAISE" for r in records)


def test_parse_fcess_csv_empty() -> None:
    records = parse_fcess_csv("", product="REGULATION_LOWER", source_url="http://test/empty.csv")
    assert records == []


# ---------------------------------------------------------------------------
# Connector integration tests (mocked HTTP)
# ---------------------------------------------------------------------------


class _FakeAsyncClient:
    """Minimal async HTTP client stub."""

    def __init__(self, csv_map: dict[str, str]) -> None:
        self._map = csv_map

    async def get_csv(self, url: str, params: object = None) -> str:
        if url in self._map:
            return self._map[url]
        from httpx import HTTPStatusError, Request, Response
        req = Request("GET", url)
        resp = Response(404, request=req)
        raise HTTPStatusError(f"Not found: {url}", request=req, response=resp)

    async def aclose(self) -> None:
        pass


@pytest.mark.asyncio
async def test_connector_fetch_date_range_energy_only() -> None:
    energy_url = balancing_summary_url(date(2024, 3, 15))
    fake_client = _FakeAsyncClient({energy_url: _BALANCING_CSV})
    connector = WholesalePriceConnector(client=fake_client)  # type: ignore[arg-type]

    records = await connector.fetch_date_range(
        start=date(2024, 3, 15),
        end=date(2024, 3, 15),
        include_fcess=False,
    )
    assert len(records) == 3
    assert all(r.product == "ENERGY" for r in records)


@pytest.mark.asyncio
async def test_connector_fetch_date_range_with_fcess() -> None:
    energy_url = balancing_summary_url(date(2024, 3, 15))
    fcess_url = fcess_price_url(date(2024, 3, 15), "REGULATION_RAISE")
    fake_client = _FakeAsyncClient(
        {
            energy_url: _BALANCING_CSV,
            fcess_url: _FCESS_CSV,
        }
    )
    connector = WholesalePriceConnector(client=fake_client)  # type: ignore[arg-type]

    records = await connector.fetch_date_range(
        start=date(2024, 3, 15),
        end=date(2024, 3, 15),
        include_fcess=True,
    )
    # 3 energy + 2 reg_raise + 0 for others (404 => empty)
    energy = [r for r in records if r.product == "ENERGY"]
    reg_raise = [r for r in records if r.product == "REGULATION_RAISE"]
    assert len(energy) == 3
    assert len(reg_raise) == 2


@pytest.mark.asyncio
async def test_connector_404_returns_empty_not_error() -> None:
    """Connector should silently skip 404 responses (no data for that date)."""
    fake_client = _FakeAsyncClient({})
    connector = WholesalePriceConnector(client=fake_client)  # type: ignore[arg-type]

    records = await connector.fetch_date_range(
        start=date(2024, 3, 15),
        end=date(2024, 3, 15),
        include_fcess=False,
    )
    assert records == []


@pytest.mark.asyncio
async def test_connector_incremental_no_new_data() -> None:
    """If last_fetched_date is yesterday, no data to fetch."""
    from datetime import date as date_cls


    today = date_cls.today()
    yesterday = today - __import__("datetime").timedelta(days=1)

    fake_client = _FakeAsyncClient({})
    connector = WholesalePriceConnector(client=fake_client)  # type: ignore[arg-type]

    records = await connector.fetch_incremental(
        last_fetched_date=yesterday, include_fcess=False
    )
    assert records == []


def test_to_dataframe_with_records() -> None:
    r = WholesalePriceRecord(
        interval_start_utc=datetime(2024, 3, 15, 0, 0, tzinfo=UTC),
        price_aud_mwh=85.5,
        product="ENERGY",
        source_url="http://test/balancing.csv",
    )
    df = WholesalePriceConnector.to_dataframe([r])
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 1
    assert df["product"].iloc[0] == "ENERGY"
    assert df["price_aud_mwh"].iloc[0] == pytest.approx(85.5)


def test_to_dataframe_empty() -> None:
    df = WholesalePriceConnector.to_dataframe([])
    assert isinstance(df, pd.DataFrame)
    assert df.empty
