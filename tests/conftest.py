"""Pytest configuration and shared fixtures for WEM energy cost modelling tests.

Fixtures here are available to all test modules automatically.
"""
from __future__ import annotations

import os

import pytest

# ── anyio / asyncio backend ───────────────────────────────────────────────────


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    """Use asyncio as the async backend for all tests."""
    return "asyncio"


# ── Database ───────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def db_url() -> str:
    """Return the database URL to use for tests.

    Prefers the ``DATABASE_URL`` environment variable so that integration
    tests can use a real PostgreSQL instance in CI.  Falls back to an
    in-process SQLite database for unit tests.
    """
    return os.environ.get(
        "DATABASE_URL",
        "sqlite+aiosqlite:///./test.db",
    )


# ── Markers ────────────────────────────────────────────────────────────────────


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers to avoid PytestUnknownMarkWarning."""
    config.addinivalue_line(
        "markers",
        "integration: mark test as requiring a live database / external services",
    )
    config.addinivalue_line(
        "markers",
        "slow: mark test as slow-running (skip with -m 'not slow')",
    )
