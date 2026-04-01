"""Tests for app.pipeline.schemas Pydantic validation models and their
integration in the parse functions (fcess_connector, wholesale_price_connector).
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.pipeline.schemas import FcessPriceRow, WholesalePriceRow
from app.pipeline.wholesale_price_connector import parse_balancing_csv, parse_fcess_csv

_NOW = datetime(2024, 6, 1, 0, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# FcessPriceRow unit tests
# ---------------------------------------------------------------------------


def test_fcess_price_row_valid() -> None:
    row = FcessPriceRow(product="REG_RAISE", interval_start_utc=_NOW, price_aud_mwh=12.5)
    assert row.price_aud_mwh == 12.5
    assert row.product == "REG_RAISE"


def test_fcess_price_row_zero_price_ok() -> None:
    """Zero price is valid (market can clear at zero)."""
    row = FcessPriceRow(product="REG_LOWER", interval_start_utc=_NOW, price_aud_mwh=0.0)
    assert row.price_aud_mwh == 0.0


def test_fcess_price_row_missing_product() -> None:
    with pytest.raises(ValidationError):
        FcessPriceRow(product="", interval_start_utc=_NOW, price_aud_mwh=10.0)


def test_fcess_price_row_nan_price() -> None:
    with pytest.raises(ValidationError):
        FcessPriceRow(product="REG_RAISE", interval_start_utc=_NOW, price_aud_mwh=math.nan)


def test_fcess_price_row_inf_price() -> None:
    with pytest.raises(ValidationError):
        FcessPriceRow(product="REG_RAISE", interval_start_utc=_NOW, price_aud_mwh=math.inf)


def test_fcess_price_row_missing_timestamp() -> None:
    with pytest.raises(ValidationError):
        FcessPriceRow(product="REG_RAISE", interval_start_utc=None, price_aud_mwh=10.0)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# WholesalePriceRow unit tests
# ---------------------------------------------------------------------------


def test_wholesale_price_row_valid() -> None:
    row = WholesalePriceRow(
        interval_start_utc=_NOW,
        price_aud_mwh=55.0,
        product="ENERGY",
        source_url="https://example.com/data.csv",
    )
    assert row.product == "ENERGY"


def test_wholesale_price_row_nan_price() -> None:
    with pytest.raises(ValidationError):
        WholesalePriceRow(
            interval_start_utc=_NOW,
            price_aud_mwh=math.nan,
            product="ENERGY",
            source_url="https://example.com/data.csv",
        )


def test_wholesale_price_row_empty_source_url() -> None:
    with pytest.raises(ValidationError):
        WholesalePriceRow(
            interval_start_utc=_NOW,
            price_aud_mwh=55.0,
            product="ENERGY",
            source_url="",
        )


# ---------------------------------------------------------------------------
# Integration: parse_balancing_csv skips invalid rows
# ---------------------------------------------------------------------------

_VALID_BALANCING_CSV = """\
DISPATCH_INTERVAL_START,MARKET_CLEARING_PRICE
2024-06-01 00:00:00,55.0
2024-06-01 00:05:00,60.0
"""

_BAD_PRICE_BALANCING_CSV = """\
DISPATCH_INTERVAL_START,MARKET_CLEARING_PRICE
2024-06-01 00:00:00,not_a_number
2024-06-01 00:05:00,60.0
"""

_MISSING_TS_BALANCING_CSV = """\
DISPATCH_INTERVAL_START,MARKET_CLEARING_PRICE
,55.0
2024-06-01 00:05:00,60.0
"""


def test_parse_balancing_csv_valid_rows() -> None:
    records = parse_balancing_csv(_VALID_BALANCING_CSV, "https://example.com/b.csv")
    assert len(records) == 2
    assert records[0].price_aud_mwh == 55.0
    assert records[1].price_aud_mwh == 60.0


def test_parse_balancing_csv_bad_price_skipped() -> None:
    records = parse_balancing_csv(_BAD_PRICE_BALANCING_CSV, "https://example.com/b.csv")
    # Only the valid row (60.0) should be returned
    assert len(records) == 1
    assert records[0].price_aud_mwh == 60.0


# ---------------------------------------------------------------------------
# Integration: parse_fcess_csv skips invalid rows
# ---------------------------------------------------------------------------

_VALID_FCESS_CSV = """\
DISPATCH_INTERVAL_START,MARKET_CLEARING_PRICE
2024-06-01 00:00:00,1.5
2024-06-01 00:05:00,2.0
"""


def test_parse_fcess_csv_valid_rows() -> None:
    records = parse_fcess_csv(_VALID_FCESS_CSV, "REG_RAISE", "https://example.com/f.csv")
    assert len(records) == 2
    assert records[0].product == "REG_RAISE"


def test_parse_fcess_csv_empty_returns_empty() -> None:
    records = parse_fcess_csv("", "REG_RAISE", "https://example.com/f.csv")
    assert records == []
