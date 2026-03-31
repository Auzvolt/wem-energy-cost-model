"""Tests for application configuration."""

from __future__ import annotations


def test_settings_defaults(test_settings):
    """Settings loads with expected default values."""
    assert test_settings.aemo_api_base_url == "https://data.wa.aemo.com.au"
    assert test_settings.log_level == "DEBUG"
    assert test_settings.database_url == "sqlite:///./test.db"


def test_settings_api_key_defaults_empty(test_settings):
    """API key defaults to empty string (public data access)."""
    assert test_settings.aemo_api_key == ""


def test_settings_can_override():
    """Settings values can be overridden at construction time."""
    from app.config import Settings

    s = Settings(
        database_url="postgresql://localhost/test",
        aemo_api_base_url="https://custom.example.com",
        log_level="WARNING",
    )
    assert s.database_url == "postgresql://localhost/test"
    assert s.aemo_api_base_url == "https://custom.example.com"
    assert s.log_level == "WARNING"
