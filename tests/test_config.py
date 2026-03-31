"""Tests for app/config.py."""

import os

import pytest


def test_config_loads_defaults() -> None:
    """Config should return defaults when env vars are not set."""
    from app import config

    # DATABASE_URL has a hardcoded default
    assert config.DATABASE_URL is not None
    assert "postgresql" in config.DATABASE_URL


def test_config_get_returns_none_for_missing() -> None:
    """config.get() should return None for unknown keys."""
    from app import config

    assert config.get("NONEXISTENT_KEY_XYZ") is None


def test_config_get_returns_default() -> None:
    """config.get() should return the supplied default."""
    from app import config

    assert config.get("NONEXISTENT_KEY_XYZ", "fallback") == "fallback"


def test_config_require_raises_for_missing() -> None:
    """config.require() should raise RuntimeError for missing keys."""
    from app import config

    with pytest.raises(RuntimeError, match="NONEXISTENT_KEY_XYZ"):
        config.require("NONEXISTENT_KEY_XYZ")


def test_config_require_returns_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """config.require() should return the env var value when set."""
    monkeypatch.setenv("TEST_SECRET_KEY", "my-secret")
    from app import config

    assert config.require("TEST_SECRET_KEY") == "my-secret"
