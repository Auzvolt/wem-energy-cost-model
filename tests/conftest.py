"""Shared pytest fixtures."""

from __future__ import annotations

import pytest


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
