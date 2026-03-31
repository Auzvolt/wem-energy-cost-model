"""Database session factory."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import config

engine = create_engine(
    config.DATABASE_URL,
    pool_pre_ping=True,
    echo=config.LOG_LEVEL == "DEBUG",
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_session() -> Generator[Session, None, None]:
    """Yield a database session and ensure it is closed afterwards."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
