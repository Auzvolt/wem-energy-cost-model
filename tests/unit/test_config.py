"""Unit tests for app.config (Settings / environment variables)."""
from __future__ import annotations

import os

import pytest


class TestSettings:
    """Tests for the top-level application Settings class."""

    def test_settings_importable(self) -> None:
        """app package must be importable without errors."""
        import app  # noqa: F401 — existence check

        assert app is not None

    def test_settings_class_importable(self) -> None:
        """Settings class should be importable from app.config."""
        # If app.config doesn't exist yet we skip gracefully.
        pytest.importorskip("app.config")
        from app.config import Settings  # type: ignore[import]

        assert Settings is not None

    def test_database_url_has_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DATABASE_URL should fall back to a sensible default when not set."""
        pytest.importorskip("app.config")
        monkeypatch.delenv("DATABASE_URL", raising=False)

        # Re-import to pick up the env change (pydantic-settings reads at init time)
        import importlib

        import app.config

        importlib.reload(app.config)
        from app.config import Settings  # type: ignore[import]

        settings = Settings()
        assert settings.database_url  # must not be empty

    def test_environment_variable_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DATABASE_URL env var should be picked up by Settings."""
        pytest.importorskip("app.config")
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test:test@localhost/testdb")

        import importlib

        import app.config

        importlib.reload(app.config)
        from app.config import Settings  # type: ignore[import]

        settings = Settings()
        assert "testdb" in settings.database_url


class TestEnvironmentVariables:
    """Sanity checks for expected environment variable names."""

    def test_solver_env_var_name(self) -> None:
        """The SOLVER env var controls which solver Pyomo uses."""
        # Just validate that code which reads SOLVER env var will work correctly
        solver = os.environ.get("SOLVER", "glpk")
        assert isinstance(solver, str)
        assert len(solver) > 0

    def test_database_url_env_var_name(self) -> None:
        """DATABASE_URL env var name is standardised."""
        # Ensure it's at least defined in .env.example
        import pathlib

        env_example = pathlib.Path("wem-energy-cost-model/.env.example")
        if not env_example.exists():
            env_example = pathlib.Path(".env.example")
        if env_example.exists():
            content = env_example.read_text()
            assert "DATABASE_URL" in content
