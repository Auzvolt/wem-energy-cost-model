"""Application configuration — loads environment variables from .env."""

import os

from dotenv import load_dotenv

load_dotenv()


def get(key: str, default: str | None = None) -> str | None:
    """Retrieve a configuration value from the environment."""
    return os.environ.get(key, default)


def require(key: str) -> str:
    """Retrieve a required configuration value; raise if missing."""
    value = os.environ.get(key)
    if not value:
        raise RuntimeError(f"Required environment variable '{key}' is not set.")
    return value


# Common config values
DATABASE_URL: str = get("DATABASE_URL", "postgresql://user:password@localhost:5432/wem_energy") or ""
AEMO_API_BASE_URL: str = get("AEMO_API_BASE_URL", "https://data.wa.aemo.com.au") or ""
AEMO_API_KEY: str | None = get("AEMO_API_KEY")
LOG_LEVEL: str = get("LOG_LEVEL", "INFO") or "INFO"
