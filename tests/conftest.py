"""Shared pytest fixtures for the WEM energy cost model test suite."""

from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.db.models import Base


@pytest.fixture
def test_settings():
    """Return a fresh Settings instance with test defaults."""
    from app.config import Settings

    return Settings(
        database_url="sqlite:///./test.db",
        aemo_api_base_url="https://data.wa.aemo.com.au",
        aemo_api_key="",
        log_level="DEBUG",
    )


@pytest.fixture
def db_session():
    """Yield a synchronous SQLAlchemy session backed by an in-memory SQLite database.

    Creates all ORM tables at fixture setup and drops them at teardown.
    Uses the SQLite-compatible workaround for UUID primary keys.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    # Enable SQLite UUID handling
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):  # type: ignore[misc]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)

    with Session(engine) as session:
        yield session

    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def sample_interval_df() -> pd.DataFrame:
    """Return a small 5-minute interval DataFrame for testing.

    Columns: timestamp (datetime), nmi (str), channel (str), kwh (float).
    Contains 12 rows (1 hour of 5-min data).
    """
    timestamps = pd.date_range("2025-07-01 08:00", periods=12, freq="5min")
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "nmi": ["6305000000"] * 12,
            "channel": ["E1"] * 12,
            "kwh": [0.5, 0.6, 0.55, 0.7, 0.8, 0.75, 0.9, 0.85, 0.8, 0.7, 0.6, 0.5],
        }
    )


@pytest.fixture
def mock_aemo_response() -> dict[str, str]:
    """Return stub CSV content keyed by AEMO product name.

    These match the shape of real AEMO WA API responses (but are synthetic data).
    """
    return {
        "WHOLESALE_PRICE": (
            "TRADING_DAY,TRADING_INTERVAL,CLEARING_PRICE,REFERENCE_PRICE\n"
            "2025-07-01,1,85.50,82.00\n"
            "2025-07-01,2,87.20,82.00\n"
            "2025-07-01,3,90.10,82.00\n"
        ),
        "FCESS_RAISE": (
            "TRADING_DAY,PERIOD,PRICE,CLEARING_PRICE\n"
            "2025-07-01,1,12.50,12.50\n"
            "2025-07-01,2,13.00,13.00\n"
        ),
    }
