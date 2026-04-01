"""SQLAlchemy ORM models for the WEM Energy Cost Modelling Tool.

Table hierarchy:
  Project → Site → MeterReading
  Project → Scenario → PriceCurve
  TariffSchedule ← Site (FK)
  LossFactor ← Site (FK)
  MarketPrice (standalone, populated by AEMO data pipeline)
  CapacityPrice (standalone, populated by AEMO RCM pipeline)
"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""

    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class MarketProduct(enum.StrEnum):
    """WEM market products — energy + five FCESS."""

    energy = "energy"
    reg_raise = "reg_raise"
    reg_lower = "reg_lower"
    cont_raise = "cont_raise"
    cont_lower = "cont_lower"
    rocof = "rocof"


class DataQuality(enum.StrEnum):
    """Meter reading data quality flags."""

    actual = "actual"
    estimated = "estimated"
    substituted = "substituted"


class LossFactorType(enum.StrEnum):
    """Loss factor classification."""

    transmission = "transmission"
    distribution = "distribution"


class ScenarioStatus(enum.StrEnum):
    """Scenario lifecycle status."""

    draft = "draft"
    running = "running"
    complete = "complete"
    failed = "failed"


# ---------------------------------------------------------------------------
# Core project / engagement records
# ---------------------------------------------------------------------------


class Project(Base):
    """Top-level project / engagement record."""

    __tablename__ = "projects"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(String(1024))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    sites = relationship("Site", back_populates="project", cascade="all, delete-orphan")
    scenarios = relationship("Scenario", back_populates="project", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Project id={self.id} name={self.name!r}>"


# ---------------------------------------------------------------------------
# Tariff and loss factor configuration
# ---------------------------------------------------------------------------


class TariffSchedule(Base):
    """Western Power network tariff schedule with versioned rates.

    The tariff_config JSON field stores the full rate structure:
    - daily_admin_rate ($/day)
    - demand_rate_kw ($/kW/month)
    - on_peak_rate_cents_kwh (c/kWh)
    - off_peak_rate_cents_kwh (c/kWh)
    - enuc_rate_kw ($/kW, annualised)
    - metering_rate_day ($/day)
    - tou_windows: [{day_type, start_time, end_time, period}]
    """

    __tablename__ = "tariff_schedules"

    id = Column(Integer, primary_key=True)
    tariff_code = Column(String(20), nullable=False)
    tariff_name = Column(String(255), nullable=False)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date, nullable=True)
    network_operator = Column(String(100), nullable=False, default="Western Power")
    tariff_config = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    sites = relationship("Site", back_populates="tariff")

    def __repr__(self) -> str:
        return f"<TariffSchedule id={self.id} code={self.tariff_code!r} from={self.effective_from}>"


class LossFactor(Base):
    """Annual loss factors per connection point.

    Both Transmission Loss Factor (TLF) and Distribution Loss Factor (DLF)
    are stored together keyed by financial year and connection point.
    Annual revision applies from 1 July; reference node is Perth Southern Terminal.
    """

    __tablename__ = "loss_factors"

    id = Column(Integer, primary_key=True)
    financial_year = Column(String(10), nullable=False)  # e.g. '2025-26'
    connection_point_id = Column(String(50), nullable=False)
    connection_point_name = Column(String(255), nullable=True)
    tlf = Column(Numeric(6, 4), nullable=False)
    dlf = Column(Numeric(6, 4), nullable=False)
    factor_type: Mapped[LossFactorType] = mapped_column(
        Enum(LossFactorType, name="loss_factor_type_enum"),
        nullable=False,
        default=LossFactorType.transmission,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    sites = relationship("Site", back_populates="loss_factor")

    __table_args__ = (
        UniqueConstraint(
            "financial_year",
            "connection_point_id",
            "factor_type",
            name="uq_loss_factors_year_cp_type",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<LossFactor id={self.id} year={self.financial_year!r} "
            f"cp={self.connection_point_id!r} tlf={self.tlf} dlf={self.dlf}>"
        )


# ---------------------------------------------------------------------------
# Site (connection point)
# ---------------------------------------------------------------------------


class Site(Base):
    """A physical connection point / site within a project."""

    __tablename__ = "sites"

    id = Column(Integer, primary_key=True)
    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = Column(String(255), nullable=False)
    nmi = Column(String(20), nullable=True)  # National Metering Identifier
    connection_voltage_kv = Column(Numeric(6, 2), nullable=True)
    tariff_id = Column(
        Integer,
        ForeignKey("tariff_schedules.id", ondelete="SET NULL"),
        nullable=True,
    )
    loss_factor_id = Column(
        Integer,
        ForeignKey("loss_factors.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    project = relationship("Project", back_populates="sites")
    tariff = relationship("TariffSchedule", back_populates="sites")
    loss_factor = relationship("LossFactor", back_populates="sites")
    meter_readings = relationship(
        "MeterReading", back_populates="site", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Site id={self.id} name={self.name!r} nmi={self.nmi!r}>"


# ---------------------------------------------------------------------------
# Interval meter data
# ---------------------------------------------------------------------------


class MeterReading(Base):
    """Half-hourly or 5-minute interval meter reading for a site.

    Timestamps are stored as UTC. Convert to AWST (UTC+8) for TOU calculations;
    WA does not observe daylight saving time.
    """

    __tablename__ = "meter_readings"

    id = Column(Integer, primary_key=True)
    site_id = Column(
        Integer,
        ForeignKey("sites.id", ondelete="CASCADE"),
        nullable=False,
    )
    interval_start = Column(DateTime(timezone=True), nullable=False)
    interval_end = Column(DateTime(timezone=True), nullable=False)
    kwh_import = Column(Numeric(12, 4), nullable=False)
    kwh_export = Column(Numeric(12, 4), nullable=True)
    kw_demand = Column(Numeric(10, 3), nullable=True)
    data_quality: Mapped[DataQuality] = mapped_column(
        Enum(DataQuality, name="data_quality_enum"),
        nullable=False,
        default=DataQuality.actual,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    site = relationship("Site", back_populates="meter_readings")

    __table_args__ = (
        UniqueConstraint("site_id", "interval_start", name="uq_meter_readings_site_interval"),
        Index("ix_meter_readings_site_interval", "site_id", "interval_start"),
    )

    def __repr__(self) -> str:
        return (
            f"<MeterReading id={self.id} site_id={self.site_id} "
            f"start={self.interval_start} import={self.kwh_import} kWh>"
        )


# ---------------------------------------------------------------------------
# AEMO market price data
# ---------------------------------------------------------------------------


class MarketPrice(Base):
    """5-minute WEM Market Clearing Price for energy or a FCESS product.

    Post-reform (Oct 2023+):
    - Energy: price at Perth Southern Terminal (Reference Node)
    - FCESS: separate price per product per 5-min Dispatch Interval
    - Energy settlement uses 30-min Reference Trading Price (average of 6 x 5-min MCPs)
    - FCESS settlement uses the 5-min MCP directly
    """

    __tablename__ = "market_prices"

    id = Column(Integer, primary_key=True)
    trading_date = Column(Date, nullable=False)
    interval_start = Column(DateTime(timezone=True), nullable=False)
    interval_end = Column(DateTime(timezone=True), nullable=False)
    product: Mapped[MarketProduct] = mapped_column(
        Enum(MarketProduct, name="market_product_enum"),
        nullable=False,
    )
    price_mwh = Column(Numeric(10, 4), nullable=False)
    volume_mw = Column(Numeric(10, 4), nullable=True)
    source = Column(String(50), nullable=False, default="aemo_public")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "product",
            "interval_start",
            name="uq_market_prices_product_interval",
        ),
        Index("ix_market_prices_product_interval", "product", "interval_start"),
    )

    def __repr__(self) -> str:
        return (
            f"<MarketPrice id={self.id} product={self.product.value} "
            f"start={self.interval_start} price={self.price_mwh}>"
        )


# ---------------------------------------------------------------------------
# Reserve Capacity Mechanism data
# ---------------------------------------------------------------------------


class CapacityPrice(Base):
    """Reserve Capacity Mechanism — capacity credit assignments and prices.

    Capacity Year runs October to September (e.g., '2024-25').
    Facilities receive monthly payments based on FCCs × BRCP.
    """

    __tablename__ = "capacity_prices"

    id = Column(Integer, primary_key=True)
    capacity_year = Column(String(10), nullable=False)  # e.g. '2024-25'
    facility_id = Column(String(50), nullable=False)
    facility_name = Column(String(255), nullable=True)
    capacity_credits_mw = Column(Numeric(8, 3), nullable=False)
    monthly_payment = Column(Numeric(12, 2), nullable=True)  # AUD
    brcp_mwyr = Column(Numeric(10, 2), nullable=True)  # AUD/MW/year
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "capacity_year",
            "facility_id",
            name="uq_capacity_prices_year_facility",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<CapacityPrice id={self.id} year={self.capacity_year!r} "
            f"facility={self.facility_id!r} cc={self.capacity_credits_mw} MW>"
        )


# ---------------------------------------------------------------------------
# AEMO Facility and Trading Interval data
# ---------------------------------------------------------------------------


class Facility(Base):
    """AEMO WEM registered facility (generator or load).

    Facilities are the participants in the WEM balancing market.
    Data sourced from AEMO facility reference data.
    """

    __tablename__ = "facilities"

    id = Column(Integer, primary_key=True)
    facility_id = Column(String(50), nullable=False, unique=True)
    facility_name = Column(String(255), nullable=False)
    facility_type = Column(String(50), nullable=True)  # e.g., 'GENERATOR', 'LOAD'
    fuel_type = Column(String(50), nullable=True)  # e.g., 'COAL', 'GAS', 'SOLAR', 'WIND'
    capacity_mw = Column(Numeric(10, 4), nullable=True)
    region = Column(String(50), nullable=True, default="WEM")
    effective_from = Column(Date, nullable=True)
    effective_to = Column(Date, nullable=True)
    source = Column(String(50), nullable=False, default="aemo_public")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    trading_intervals = relationship(
        "TradingInterval", back_populates="facility", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_facilities_facility_id", "facility_id"),
        Index("ix_facilities_type", "facility_type"),
    )

    def __repr__(self) -> str:
        return (
            f"<Facility id={self.id} facility_id={self.facility_id!r} name={self.facility_name!r}>"
        )


class TradingInterval(Base):
    """5-minute trading interval data per facility from AEMO.

    Contains dispatch quantities, metered generation/consumption,
    and operational data per facility per interval.
    """

    __tablename__ = "trading_intervals"

    id = Column(Integer, primary_key=True)
    facility_id = Column(
        Integer,
        ForeignKey("facilities.id", ondelete="CASCADE"),
        nullable=False,
    )
    trading_date = Column(Date, nullable=False)
    interval_start = Column(DateTime(timezone=True), nullable=False)
    interval_end = Column(DateTime(timezone=True), nullable=False)
    dispatch_mw = Column(Numeric(10, 4), nullable=True)
    metered_mw = Column(Numeric(10, 4), nullable=True)
    energy_mwh = Column(Numeric(12, 4), nullable=True)
    source = Column(String(50), nullable=False, default="aemo_public")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    facility = relationship("Facility", back_populates="trading_intervals")

    __table_args__ = (
        UniqueConstraint(
            "facility_id",
            "interval_start",
            name="uq_trading_intervals_facility_interval",
        ),
        Index("ix_trading_intervals_facility_interval", "facility_id", "interval_start"),
        Index("ix_trading_intervals_date", "trading_date"),
    )

    def __repr__(self) -> str:
        return (
            f"<TradingInterval id={self.id} facility_id={self.facility_id} "
            f"start={self.interval_start} dispatch={self.dispatch_mw} MW>"
        )


# ---------------------------------------------------------------------------
# Scenarios and forward price curves
# ---------------------------------------------------------------------------


class Scenario(Base):
    """A modelling scenario within a project.

    The config JSON field stores scenario parameters:
    - price_curve_assumptions (reference to PriceCurves or custom overrides)
    - asset_parameters (capacity, efficiency, degradation, etc.)
    - site_references (list of site IDs in scope)
    - financial_parameters (discount_rate, project_life, capex, opex)
    - optimisation_config (horizon, interval, solver settings)
    """

    __tablename__ = "scenarios"

    id = Column(Integer, primary_key=True)
    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = Column(String(255), nullable=False)
    description = Column(String(1024), nullable=True)
    config = Column(JSON, nullable=False, default=dict)
    status: Mapped[ScenarioStatus] = mapped_column(
        Enum(ScenarioStatus, name="scenario_status_enum"),
        nullable=False,
        default=ScenarioStatus.draft,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    project = relationship("Project", back_populates="scenarios")
    price_curves = relationship(
        "PriceCurve", back_populates="scenario", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Scenario id={self.id} name={self.name!r} status={self.status.value}>"


class PriceCurve(Base):
    """Forward price curve entry for a given product and scenario.

    Used to store assumed future market prices for optimisation / financial modelling.
    Can be linked to a specific scenario or be a generic market assumption (scenario_id=NULL).
    """

    __tablename__ = "price_curves"

    id = Column(Integer, primary_key=True)
    curve_name = Column(String(255), nullable=False)
    product: Mapped[MarketProduct] = mapped_column(
        Enum(MarketProduct, name="market_product_enum"),
        nullable=False,
    )
    interval_start = Column(DateTime(timezone=True), nullable=False)
    price_mwh = Column(Numeric(10, 4), nullable=False)
    scenario_id = Column(
        Integer,
        ForeignKey("scenarios.id", ondelete="CASCADE"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    scenario = relationship("Scenario", back_populates="price_curves")

    __table_args__ = (Index("ix_price_curves_product_interval", "product", "interval_start"),)

    def __repr__(self) -> str:
        return (
            f"<PriceCurve id={self.id} curve={self.curve_name!r} "
            f"product={self.product.value} start={self.interval_start}>"
        )


class Asset(Base):
    """Registered energy asset (generator, battery, demand response).

    The ``config`` column stores the full Pydantic model as JSONB.
    """

    __tablename__ = "assets"

    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        nullable=False,
    )
    asset_type = Column(String(50), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    config = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<Asset id={self.id} type={self.asset_type!r} name={self.name!r}>"
