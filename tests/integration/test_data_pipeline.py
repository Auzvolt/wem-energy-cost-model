"""Integration tests for the data pipeline.

These tests require a live database connection and are excluded from the
default unit-test run.  They are gated by the ``integration`` marker and
will be skipped automatically if ``DATABASE_URL`` is not set to a
PostgreSQL URI.

Run with::

    DATABASE_URL=postgresql+psycopg://... pytest -m integration tests/integration/
"""
from __future__ import annotations

import os

import pytest

_REQUIRES_POSTGRES = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="Integration tests require DATABASE_URL pointing to PostgreSQL",
)


@pytest.mark.integration
@_REQUIRES_POSTGRES
class TestDataPipelineImports:
    """Verify pipeline modules are importable in a real environment."""

    def test_pipeline_package_importable(self) -> None:
        """pipeline package must be importable without errors."""
        import pipeline  # noqa: F401

        assert pipeline is not None

    def test_db_package_importable(self) -> None:
        """db package must be importable without errors."""
        import db  # noqa: F401

        assert db is not None


@pytest.mark.integration
@_REQUIRES_POSTGRES
class TestDatabaseConnectivity:
    """Verify database connectivity in the integration environment."""

    async def test_db_engine_creates(self, db_url: str) -> None:
        """SQLAlchemy async engine should be creatable from DATABASE_URL."""
        pytest.importorskip("sqlalchemy")
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(db_url, echo=False)
        assert engine is not None
        await engine.dispose()

    async def test_db_ping(self, db_url: str) -> None:
        """Database should respond to a simple ping query."""
        pytest.importorskip("sqlalchemy")
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(db_url, echo=False)
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            row = result.scalar()
        await engine.dispose()
        assert row == 1
