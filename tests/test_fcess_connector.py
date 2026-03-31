"""Tests for the FCESS price connector.

Uses an in-memory SQLite database (via SQLAlchemy) and a mock HTTP client
so no network or real PostgreSQL instance is required.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base as AppBase
from app.pipeline.fcess_connector import (
    FCESS_PRODUCTS,
    FcessPrice,
    _row_to_record,
    fetch_all_fcess_products,
    fetch_fcess_prices,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def engine():
    """Ephemeral in-memory SQLite engine."""
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    AppBase.metadata.create_all(eng)
    FcessPrice.__table__.create(eng, checkfirst=True)
    yield eng
    eng.dispose()


@pytest.fixture()
def db(engine):
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.rollback()
    session.close()


def _mock_row(
    ts: str = "2025-07-01 00:00:00",
    price: float = 15.5,
) -> dict[str, Any]:
    return {"DISPATCH_INTERVAL_START": ts, "MARKET_CLEARING_PRICE": price}


def _make_http_client(rows: list[dict[str, Any]] | None = None):
    """Return a mock HTTP client that returns *rows* as a JSON payload."""
    rows = rows or []
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {"data": rows}
    client = MagicMock()
    client.get.return_value = response
    return client


# ---------------------------------------------------------------------------
# Unit: _row_to_record
# ---------------------------------------------------------------------------


class TestRowToRecord:
    def test_standard_fields_parsed(self):
        row = {
            "DISPATCH_INTERVAL_START": "2025-07-01 08:00:00",
            "MARKET_CLEARING_PRICE": 22.75,
        }
        rec = _row_to_record(row, "REG_RAISE", "https://example.com/api")
        assert rec is not None
        assert rec.product == "REG_RAISE"
        assert rec.price_aud_mwh == pytest.approx(22.75)
        # AWST (UTC+8) -> UTC: 08:00 AWST = 00:00 UTC
        assert rec.interval_start_utc == datetime(2025, 7, 1, 0, 0, 0, tzinfo=UTC)

    def test_alternative_field_names(self):
        row = {"INTERVAL_START": "2025-07-01 08:00:00", "CLEARING_PRICE": 5.0}
        rec = _row_to_record(row, "REG_LOWER", "https://x")
        assert rec is not None
        assert rec.price_aud_mwh == pytest.approx(5.0)

    def test_missing_timestamp_returns_none(self):
        row = {"MARKET_CLEARING_PRICE": 10.0}
        rec = _row_to_record(row, "CONT_RAISE", "https://x")
        assert rec is None

    def test_missing_price_returns_none(self):
        row = {"DISPATCH_INTERVAL_START": "2025-07-01 08:00:00"}
        rec = _row_to_record(row, "CONT_RAISE", "https://x")
        assert rec is None

    def test_bad_timestamp_returns_none(self):
        row = {"DISPATCH_INTERVAL_START": "not-a-date", "MARKET_CLEARING_PRICE": 1.0}
        rec = _row_to_record(row, "CONT_RAISE", "https://x")
        assert rec is None

    def test_iso_timestamp_format(self):
        row = {
            "INTERVAL_START": "2025-07-01T08:30:00",
            "MARKET_CLEARING_PRICE": 0.0,
        }
        rec = _row_to_record(row, "ROCOF", "https://x")
        assert rec is not None
        assert rec.interval_start_utc == datetime(2025, 7, 1, 0, 30, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Integration: fetch_fcess_prices
# ---------------------------------------------------------------------------


class TestFetchFcessPrices:
    def test_records_are_persisted(self, db):
        rows = [
            _mock_row("2025-07-01 08:00:00", 10.0),
            _mock_row("2025-07-01 08:05:00", 11.0),
        ]
        client = _make_http_client(rows)
        from_dt = datetime(2025, 7, 1, 0, 0, 0, tzinfo=UTC)
        to_dt = datetime(2025, 7, 2, 0, 0, 0, tzinfo=UTC)

        persisted = fetch_fcess_prices("REG_RAISE", from_dt, to_dt, db, http_client=client)
        db.commit()

        assert len(persisted) == 2
        stored = db.query(FcessPrice).filter_by(product="REG_RAISE").all()
        assert len(stored) == 2

    def test_duplicate_records_not_duplicated(self, db):
        rows = [_mock_row("2025-07-01 08:00:00", 10.0)]
        client = _make_http_client(rows)
        from_dt = datetime(2025, 7, 1, 0, 0, 0, tzinfo=UTC)
        to_dt = datetime(2025, 7, 2, 0, 0, 0, tzinfo=UTC)

        fetch_fcess_prices("REG_RAISE", from_dt, to_dt, db, http_client=client)
        db.commit()
        # Fetch again — same rows
        client2 = _make_http_client(rows)
        fetch_fcess_prices("REG_RAISE", from_dt, to_dt, db, http_client=client2)
        db.commit()

        stored = db.query(FcessPrice).filter_by(product="REG_RAISE").all()
        # Should still be only 1 record
        assert len(stored) == 1

    def test_invalid_product_raises(self, db):
        from_dt = datetime(2025, 7, 1, tzinfo=UTC)
        to_dt = datetime(2025, 7, 2, tzinfo=UTC)
        with pytest.raises(ValueError, match="Unknown FCESS product"):
            fetch_fcess_prices("INVALID_PROD", from_dt, to_dt, db)

    def test_incremental_fetch_advances_from_dt(self, db):
        """If records exist, from_dt advances past the latest stored record."""
        # Pre-load a record at 08:00 AWST (00:00 UTC)
        existing = FcessPrice(
            product="REG_RAISE",
            interval_start_utc=datetime(2025, 7, 1, 0, 0, 0, tzinfo=UTC),
            price_aud_mwh=5.0,
            source_url="https://x",
            fetched_at=datetime.now(UTC),
        )
        db.add(existing)
        db.commit()

        # API returns a record at 08:05 AWST (00:05 UTC) only
        rows = [_mock_row("2025-07-01 08:05:00", 20.0)]
        client = _make_http_client(rows)
        from_dt = datetime(2025, 7, 1, 0, 0, 0, tzinfo=UTC)  # Would be skipped
        to_dt = datetime(2025, 7, 2, 0, 0, 0, tzinfo=UTC)

        persisted = fetch_fcess_prices("REG_RAISE", from_dt, to_dt, db, http_client=client)
        db.commit()

        # Connector should not refetch the already-stored record
        assert len(persisted) == 1
        assert persisted[0].price_aud_mwh == pytest.approx(20.0)

    def test_http_error_is_handled_gracefully(self, db):
        """HTTP errors should be caught; no crash, empty result returned."""
        client = MagicMock()
        client.get.return_value = MagicMock(
            raise_for_status=MagicMock(side_effect=Exception("503")),
            json=MagicMock(return_value={}),
        )
        from_dt = datetime(2025, 7, 1, tzinfo=UTC)
        to_dt = datetime(2025, 7, 2, tzinfo=UTC)
        # Should not raise
        result = fetch_fcess_prices("REG_RAISE", from_dt, to_dt, db, http_client=client)
        assert result == []


# ---------------------------------------------------------------------------
# Integration: fetch_all_fcess_products
# ---------------------------------------------------------------------------


class TestFetchAllFcessProducts:
    def test_all_products_fetched(self, db):
        rows = [_mock_row("2025-07-01 08:00:00", 5.0)]
        client = _make_http_client(rows)
        from_dt = datetime(2025, 7, 1, tzinfo=UTC)
        to_dt = datetime(2025, 7, 2, tzinfo=UTC)

        results = fetch_all_fcess_products(from_dt, to_dt, db, http_client=client)
        db.commit()

        assert set(results.keys()) == set(FCESS_PRODUCTS.keys())
        for product, records in results.items():
            assert len(records) == 1, f"{product} should have 1 record"
