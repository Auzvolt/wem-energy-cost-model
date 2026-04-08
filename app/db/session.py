"""Database session factory."""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import config

_PLACEHOLDER_URL = "postgresql://user:password@localhost:5432/wem_energy"


def _get_database_url() -> str:
    """Resolve DATABASE_URL with priority: env var → Streamlit secrets → placeholder.

    Resolution order:
    1. ``DATABASE_URL`` environment variable (if set and not the placeholder default).
    2. ``st.secrets["DATABASE_URL"]`` when running inside Streamlit Cloud and the
       env var is absent or is the placeholder.
    3. Fall back to the placeholder (will fail at connection time with a clear error).
    """
    url: str = str(config.DATABASE_URL)

    if url == _PLACEHOLDER_URL:
        # Env var was not set — try Streamlit secrets.
        try:
            import streamlit as st  # noqa: PLC0415

            secret = str(st.secrets["DATABASE_URL"])
            if secret:
                url = secret
        except Exception:  # noqa: BLE001 — missing key, import error, or not in ST
            pass

    return url


def _ensure_ssl(url: str) -> str:
    """Append ``?sslmode=require`` when connecting to a remote host.

    Supabase (and most managed PostgreSQL services) require SSL. We add the
    parameter automatically for any non-localhost URL that does not already
    specify an sslmode query parameter.
    """
    if "sslmode=" in url:
        return url  # already configured — leave untouched

    # Only add SSL for non-local hosts.
    local_hosts = ("localhost", "127.0.0.1", "::1")
    if any(f"@{h}" in url or f"@{h}:" in url for h in local_hosts):
        return url

    separator = "&" if "?" in url else "?"
    return f"{url}{separator}sslmode=require"


def _build_engine_url() -> str:
    url = _get_database_url()
    return _ensure_ssl(url)


engine = create_engine(
    _build_engine_url(),
    pool_pre_ping=True,
    echo=config.LOG_LEVEL == "DEBUG",
)

# SQLAlchemy 2.x-compatible: pass engine as first positional argument, not via bind=
SessionLocal = sessionmaker(engine, autocommit=False, autoflush=False)


def get_session() -> Iterator[Session]:
    """Yield a database session and ensure it is closed afterwards."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
