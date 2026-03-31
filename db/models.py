"""SQLAlchemy 2.0 ORM models for the WEM energy cost modelling tool."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Facility(Base):
    """AEMO WA registered facility."""

    __tablename__ = "facilities"

    facility_code: Mapped[str] = mapped_column(String(64), primary_key=True)
    facility_name: Mapped[str] = mapped_column(String(256))
    participant_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    technology_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    capacity_mw: Mapped[float | None] = mapped_column(Float, nullable=True)
    registered_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    intervals: Mapped[list[Interval]] = relationship(
        "Interval", back_populates="facility"
    )


class Interval(Base):
    """5-minute trading interval data for a facility."""

    __tablename__ = "intervals"
    __table_args__ = (
        UniqueConstraint("interval_start", "facility_code", name="uq_interval"),
        Index("ix_intervals_interval_start", "interval_start"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    interval_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    facility_code: Mapped[str] = mapped_column(
        String(64), ForeignKey("facilities.facility_code")
    )
    actual_mw: Mapped[float] = mapped_column(Float)
    trading_price_aud_mwh: Mapped[float | None] = mapped_column(Float, nullable=True)

    facility: Mapped[Facility] = relationship("Facility", back_populates="intervals")


class PriceInterval(Base):
    """30-minute settlement price interval."""

    __tablename__ = "price_intervals"
    __table_args__ = (
        UniqueConstraint("interval_start", "region", name="uq_price_interval"),
        Index("ix_price_intervals_interval_start", "interval_start"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    interval_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    region: Mapped[str] = mapped_column(String(32))
    rrp_aud_mwh: Mapped[float] = mapped_column(Float)
    total_demand_mw: Mapped[float | None] = mapped_column(Float, nullable=True)


class Asset(Base):
    """User-configured energy asset for a project."""

    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=_uuid,
        server_default=text(
            "(lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2)))"
            " || '-4' || substr(lower(hex(randomblob(2))),2)"
            " || '-' || substr('89ab',abs(random()) % 4 + 1, 1)"
            " || substr(lower(hex(randomblob(2))),2)"
            " || '-' || lower(hex(randomblob(6))))"
        ),
    )
    name: Mapped[str] = mapped_column(String(256))
    # solar | bess | genset | ev_fleet | load_flex
    asset_type: Mapped[str] = mapped_column(String(32))
    capacity_kw: Mapped[float] = mapped_column(Float)
    config: Mapped[dict] = mapped_column(JSON, default=dict)  # type: ignore[type-arg]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    scenario_results: Mapped[list[ScenarioResult]] = relationship(
        "ScenarioResult", back_populates="asset"
    )


class Scenario(Base):
    """Optimisation scenario configuration."""

    __tablename__ = "scenarios"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    params: Mapped[dict] = mapped_column(JSON, default=dict)  # type: ignore[type-arg]

    results: Mapped[list[ScenarioResult]] = relationship(
        "ScenarioResult", back_populates="scenario"
    )


class ScenarioResult(Base):
    """Per-interval dispatch and revenue result for a scenario."""

    __tablename__ = "scenario_results"
    __table_args__ = (
        Index(
            "ix_scenario_results_scenario_interval",
            "scenario_id",
            "interval_start",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    scenario_id: Mapped[str] = mapped_column(String(36), ForeignKey("scenarios.id"))
    interval_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    asset_id: Mapped[str] = mapped_column(String(36), ForeignKey("assets.id"))
    dispatch_kw: Mapped[float] = mapped_column(Float)
    revenue_aud: Mapped[float] = mapped_column(Float)

    scenario: Mapped[Scenario] = relationship("Scenario", back_populates="results")
    asset: Mapped[Asset] = relationship("Asset", back_populates="scenario_results")
