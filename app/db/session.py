"""Database session factory."""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import config


def _get_database_url() -> str:
    """Resolve DATABASE_URL from env via config, with Streamlit secrets fallback.

    Resolution order:
    1. ``config.DATABASE_URL`` (populated from ``DATABASE_URL`` env var)
    2. ``st.secrets["DATABASE_URL"]`` when running inside Streamlit Cloud
       and the env var is not set / is the placeholder default.
    """
    # Coerce to str — config.DATABASE_URL may be a Pydantic AnyUrl type.
    url: str = str(config.DATABASE_URL)
    # The config default is the placeholder; try Streamlit secrets instead.
    if url == "postgresql://user:password@localhost:5432/wem_energy":
        try:
            import streamlit as st  # noqa: PLC0415

            url = str(st.secrets["DATABASE_URL"])
        except Exception:  # noqa: BLE001 — missing key, import error, or not in ST
            pass
    return url


engine = create_engine(
    _get_database_url(),
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
