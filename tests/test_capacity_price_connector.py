"""Tests for the AEMO capacity price data connector (issue #13).

Uses an in-memory SQLite database and a mock HTTP client to test the full
fetch-parse-upsert pipeline without any external network calls.
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, CapacityPrice
from app.pipeline.capacity_price_connector import _parse_csv, fetch_capacity_prices
from app.pipeline.schemas import CapacityPriceRow

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_CSV = """CAPACITY_YEAR,FACILITY_ID,FACILITY_NAME,CAPACITY_CREDITS_MW,BRCP_MWYR
2023-24,ALINTA_WGP,Alinta WGP,150.5,151500.00
2023-24,SYNERGY_MR5A,Synergy MR5A,200.0,151500.00
2024-25,ALINTA_WGP,Alinta WGP,155.0,155000.00
"""

SAMPLE_CSV_ALT_HEADERS = """CAPACITY YEAR,FACILITY ID,FACILITY NAME,CAPACITY CREDITS MW,BRCP MW/YR
2023-24,ALINTA_WGP,Alinta WGP,150.5,151500.00
2024-25,SYNERGY_MR5A,Synergy MR5A,200.0,155000.00
"""

SOURCE_URL = "https://data.wa.aemo.com.au/public/public-data/dataFiles/capacity-credits/"


@pytest.fixture()
def engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)


@pytest.fixture()
def db_session(engine):
    with Session(engine) as session:
        yield session


def _mock_http(csv_text: str, status_code: int = 200) -> MagicMock:
    """Return a mock httpx.Client that responds with *csv_text*."""
    response = MagicMock()
    response.text = csv_text
    response.status_code = status_code
    response.raise_for_status = MagicMock()
    client = MagicMock()
    client.get.return_value = response
    client.close = MagicMock()
    return client


# ---------------------------------------------------------------------------
# URL / endpoint tests
# ---------------------------------------------------------------------------


def test_connector_builds_url_from_base(monkeypatch):
    """The connector appends the capacity-credits path to AEMO_API_BASE_URL."""
    monkeypatch.setattr(
        "app.pipeline.capacity_price_connector.AEMO_API_BASE_URL", "https://data.wa.aemo.com.au"
    )
    http = _mock_http(SAMPLE_CSV)

    with Session(create_engine("sqlite:///:memory:")) as tmp_db:
        Base.metadata.create_all(tmp_db.get_bind())
        fetch_capacity_prices(tmp_db, http_client=http)

    called_url = http.get.call_args[0][0]
    assert "capacity-credits" in called_url
    assert called_url.startswith("https://data.wa.aemo.com.au")


def test_connector_strips_trailing_slash_from_base(monkeypatch):
    """Trailing slash on AEMO_API_BASE_URL must not produce double slashes."""
    monkeypatch.setattr(
        "app.pipeline.capacity_price_connector.AEMO_API_BASE_URL",
        "https://data.wa.aemo.com.au/",
    )
    http = _mock_http(SAMPLE_CSV)

    with Session(create_engine("sqlite:///:memory:")) as tmp_db:
        Base.metadata.create_all(tmp_db.get_bind())
        fetch_capacity_prices(tmp_db, http_client=http)

    called_url = http.get.call_args[0][0]
    assert "//" not in called_url.split("://", 1)[1]


# ---------------------------------------------------------------------------
# CSV parse tests
# ---------------------------------------------------------------------------


def test_parse_csv_standard_headers():
    """Parse standard AEMO CSV headers into CapacityPriceRow objects."""
    rows = _parse_csv(SAMPLE_CSV, SOURCE_URL)
    assert len(rows) == 3
    years = {r.capacity_year for r in rows}
    assert years == {"2023-24", "2024-25"}


def test_parse_csv_alternative_headers():
    """Parse alternative header names (spaces instead of underscores)."""
    rows = _parse_csv(SAMPLE_CSV_ALT_HEADERS, SOURCE_URL)
    assert len(rows) == 2
    assert rows[0].facility_id == "ALINTA_WGP"


def test_parse_csv_sets_source_url():
    """Each parsed row must carry the source URL."""
    rows = _parse_csv(SAMPLE_CSV, SOURCE_URL)
    assert all(r.source_url == SOURCE_URL for r in rows)


def test_parse_csv_skips_missing_facility_id():
    """Rows without a facility_id are skipped."""
    bad_csv = "CAPACITY_YEAR,FACILITY_ID,CAPACITY_CREDITS_MW,BRCP_MWYR\n2023-24,,100.0,150000\n"
    rows = _parse_csv(bad_csv, SOURCE_URL)
    assert rows == []


def test_parse_csv_skips_missing_capacity_year():
    """Rows without a capacity_year are skipped."""
    bad_csv = "CAPACITY_YEAR,FACILITY_ID,CAPACITY_CREDITS_MW,BRCP_MWYR\n,FACILITY_X,100.0,150000\n"
    rows = _parse_csv(bad_csv, SOURCE_URL)
    assert rows == []


# ---------------------------------------------------------------------------
# Pydantic schema tests
# ---------------------------------------------------------------------------


def test_capacity_price_row_valid():
    """A complete, valid row validates without error."""
    row = CapacityPriceRow(
        capacity_year="2024-25",
        facility_id="ALINTA_WGP",
        facility_name="Alinta WGP",
        capacity_credits_mw=150.5,
        brcp_mwyr=155000.0,
        source_url=SOURCE_URL,
    )
    assert row.capacity_year == "2024-25"
    assert row.capacity_credits_mw == 150.5


def test_capacity_price_row_rejects_nan_credits():
    """NaN capacity_credits_mw must raise ValidationError."""
    with pytest.raises(ValidationError):
        CapacityPriceRow(
            capacity_year="2024-25",
            facility_id="F1",
            capacity_credits_mw=float("nan"),
            brcp_mwyr=155000.0,
            source_url=SOURCE_URL,
        )


def test_capacity_price_row_rejects_inf_brcp():
    """Inf brcp_mwyr must raise ValidationError."""
    with pytest.raises(ValidationError):
        CapacityPriceRow(
            capacity_year="2024-25",
            facility_id="F1",
            capacity_credits_mw=100.0,
            brcp_mwyr=math.inf,
            source_url=SOURCE_URL,
        )


# ---------------------------------------------------------------------------
# Persistence / upsert tests
# ---------------------------------------------------------------------------


def test_fetch_and_store_inserts_new_records(db_session):
    """fetch_capacity_prices inserts all rows from a fresh CSV."""
    http = _mock_http(SAMPLE_CSV)
    result = fetch_capacity_prices(db_session, http_client=http)
    db_session.commit()

    stored = db_session.query(CapacityPrice).all()
    assert len(stored) == 3
    assert len(result) == 3


def test_fetch_and_store_upserts_existing_record(db_session):
    """Re-fetching an existing record updates it rather than inserting a duplicate."""
    http1 = _mock_http(SAMPLE_CSV)
    fetch_capacity_prices(db_session, http_client=http1)
    db_session.commit()

    # Fetch again with updated BRCP
    updated_csv = SAMPLE_CSV.replace("151500.00", "160000.00")
    http2 = _mock_http(updated_csv)
    fetch_capacity_prices(db_session, http_client=http2)
    db_session.commit()

    stored = db_session.query(CapacityPrice).all()
    assert len(stored) == 3  # no duplicates
    # Updated records should have new BRCP
    alinta_2023 = (
        db_session.query(CapacityPrice)
        .filter_by(capacity_year="2023-24", facility_id="ALINTA_WGP")
        .first()
    )
    assert alinta_2023 is not None
    assert float(alinta_2023.brcp_mwyr) == pytest.approx(160000.0)


def test_since_year_filter(db_session):
    """since_year filters out rows from earlier capacity years."""
    http = _mock_http(SAMPLE_CSV)
    result = fetch_capacity_prices(db_session, since_year="2024-25", http_client=http)
    db_session.commit()

    stored = db_session.query(CapacityPrice).all()
    assert len(stored) == 1
    assert stored[0].capacity_year == "2024-25"
    assert len(result) == 1


def test_fetch_returns_empty_list_for_empty_csv(db_session):
    """An empty CSV (headers only) returns an empty list."""
    empty_csv = "CAPACITY_YEAR,FACILITY_ID,CAPACITY_CREDITS_MW,BRCP_MWYR\n"
    http = _mock_http(empty_csv)
    result = fetch_capacity_prices(db_session, http_client=http)
    assert result == []
