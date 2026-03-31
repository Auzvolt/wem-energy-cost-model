"""Unit tests for application configuration."""

from __future__ import annotations


def test_settings_defaults():
    """Settings reads expected keys and provides defaults."""
    from app.config import Settings

    s = Settings()
    assert s.database_url.startswith("postgresql://") or s.database_url.startswith("sqlite://")
    assert s.aemo_api_base_url.startswith("https://")
    assert isinstance(s.log_level, str)
    assert isinstance(s.aemo_api_key, str)


def test_settings_override_via_env(monkeypatch):
    """Settings picks up values from environment variables."""
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./override.db")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")

    from app.config import Settings

    s = Settings()
    assert s.database_url == "sqlite:///./override.db"
    assert s.log_level == "WARNING"


def test_settings_direct_kwargs():
    """Settings can be constructed directly with keyword arguments."""
    from app.config import Settings

    s = Settings(
        database_url="sqlite:///./direct.db",
        log_level="ERROR",
    )
    assert s.database_url == "sqlite:///./direct.db"
    assert s.log_level == "ERROR"


def test_settings_repr_hides_api_key():
    """Settings repr should not expose the API key value."""
    from app.config import Settings

    s = Settings(aemo_api_key="super-secret-value")
    r = repr(s)
    # api_key is intentionally excluded from __repr__
    assert "super-secret-value" not in r


def test_settings_api_key_kwarg():
    """API key passed as kwarg is stored on the instance."""
    from app.config import Settings

    s = Settings(aemo_api_key="my-key")
    assert s.aemo_api_key == "my-key"
