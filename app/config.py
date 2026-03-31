"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os


def _env(key: str, default: str = "") -> str:
    """Read an environment variable with an optional default."""
    return os.environ.get(key, default)


class Settings:
    """Application-wide settings resolved from environment variables.

    Values are read at instantiation time. To override, set the environment
    variable before constructing Settings (or pass kwargs directly).
    """

    def __init__(
        self,
        *,
        database_url: str | None = None,
        aemo_api_base_url: str | None = None,
        aemo_api_key: str | None = None,
        log_level: str | None = None,
    ) -> None:
        self.database_url: str = database_url or _env(
            "DATABASE_URL",
            "postgresql://user:password@localhost:5432/wem_energy",
        )
        self.aemo_api_base_url: str = aemo_api_base_url or _env(
            "AEMO_API_BASE_URL",
            "https://data.wa.aemo.com.au",
        )
        # AEMO APIM subscription key — leave blank for public-data-only access
        self.aemo_api_key: str = (
            aemo_api_key if aemo_api_key is not None else _env("AEMO_API_KEY", "")
        )
        self.log_level: str = log_level or _env("LOG_LEVEL", "INFO")

    def __repr__(self) -> str:
        return (
            f"Settings(database_url={self.database_url!r}, "
            f"aemo_api_base_url={self.aemo_api_base_url!r}, "
            f"log_level={self.log_level!r})"
        )


# Module-level singleton — import and use directly:
#   from app.config import settings
settings = Settings()

# Legacy attribute-style access for backwards compatibility with existing code
DATABASE_URL: str = settings.database_url
AEMO_API_BASE_URL: str = settings.aemo_api_base_url
AEMO_API_KEY: str = settings.aemo_api_key
LOG_LEVEL: str = settings.log_level
