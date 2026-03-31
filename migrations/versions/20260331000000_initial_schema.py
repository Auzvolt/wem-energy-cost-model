"""Initial PostgreSQL schema for WEM Energy Cost Modelling Tool.

Creates all tables:
  - projects
  - tariff_schedules
  - loss_factors
  - sites
  - meter_readings
  - market_prices
  - capacity_prices
  - scenarios
  - price_curves

Revision ID: 20260331000000
Revises: (base)
Create Date: 2026-03-31 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260331000000"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enums
    market_product_enum = sa.Enum(
        "energy",
        "reg_raise",
        "reg_lower",
        "cont_raise",
        "cont_lower",
        "rocof",
        name="market_product_enum",
    )
    data_quality_enum = sa.Enum(
        "actual",
        "estimated",
        "substituted",
        name="data_quality_enum",
    )
    loss_factor_type_enum = sa.Enum(
        "transmission",
        "distribution",
        name="loss_factor_type_enum",
    )
    scenario_status_enum = sa.Enum(
        "draft",
        "running",
        "complete",
        "failed",
        name="scenario_status_enum",
    )
    market_product_enum.create(op.get_bind(), checkfirst=True)
    data_quality_enum.create(op.get_bind(), checkfirst=True)
    loss_factor_type_enum.create(op.get_bind(), checkfirst=True)
    scenario_status_enum.create(op.get_bind(), checkfirst=True)

    # projects
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String(1024), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_projects"),
    )

    # tariff_schedules
    op.create_table(
        "tariff_schedules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tariff_code", sa.String(20), nullable=False),
        sa.Column("tariff_name", sa.String(255), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("network_operator", sa.String(100), nullable=False),
        sa.Column("tariff_config", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tariff_schedules"),
    )

    # loss_factors
    op.create_table(
        "loss_factors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("financial_year", sa.String(10), nullable=False),
        sa.Column("connection_point_id", sa.String(50), nullable=False),
        sa.Column("connection_point_name", sa.String(255), nullable=True),
        sa.Column("tlf", sa.Numeric(6, 4), nullable=False),
        sa.Column("dlf", sa.Numeric(6, 4), nullable=False),
        sa.Column("factor_type", loss_factor_type_enum, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_loss_factors"),
        sa.UniqueConstraint(
            "financial_year",
            "connection_point_id",
            "factor_type",
            name="uq_loss_factors_year_cp_type",
        ),
    )

    # sites
    op.create_table(
        "sites",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("nmi", sa.String(20), nullable=True),
        sa.Column("connection_voltage_kv", sa.Numeric(6, 2), nullable=True),
        sa.Column("tariff_id", sa.Integer(), nullable=True),
        sa.Column("loss_factor_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_sites_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tariff_id"],
            ["tariff_schedules.id"],
            name="fk_sites_tariff_id_tariff_schedules",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["loss_factor_id"],
            ["loss_factors.id"],
            name="fk_sites_loss_factor_id_loss_factors",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sites"),
    )

    # meter_readings
    op.create_table(
        "meter_readings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("interval_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kwh_import", sa.Numeric(12, 4), nullable=False),
        sa.Column("kwh_export", sa.Numeric(12, 4), nullable=True),
        sa.Column("kw_demand", sa.Numeric(10, 3), nullable=True),
        sa.Column("data_quality", data_quality_enum, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["site_id"],
            ["sites.id"],
            name="fk_meter_readings_site_id_sites",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_meter_readings"),
        sa.UniqueConstraint(
            "site_id",
            "interval_start",
            name="uq_meter_readings_site_interval",
        ),
    )
    op.create_index(
        "ix_meter_readings_site_interval",
        "meter_readings",
        ["site_id", "interval_start"],
    )

    # market_prices
    op.create_table(
        "market_prices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("interval_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("product", market_product_enum, nullable=False),
        sa.Column("price_mwh", sa.Numeric(10, 4), nullable=False),
        sa.Column("volume_mw", sa.Numeric(10, 4), nullable=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_market_prices"),
        sa.UniqueConstraint(
            "product",
            "interval_start",
            name="uq_market_prices_product_interval",
        ),
    )
    op.create_index(
        "ix_market_prices_product_interval",
        "market_prices",
        ["product", "interval_start"],
    )

    # capacity_prices
    op.create_table(
        "capacity_prices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("capacity_year", sa.String(10), nullable=False),
        sa.Column("facility_id", sa.String(50), nullable=False),
        sa.Column("facility_name", sa.String(255), nullable=True),
        sa.Column("capacity_credits_mw", sa.Numeric(8, 3), nullable=False),
        sa.Column("monthly_payment", sa.Numeric(12, 2), nullable=True),
        sa.Column("brcp_mwyr", sa.Numeric(10, 2), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_capacity_prices"),
        sa.UniqueConstraint(
            "capacity_year",
            "facility_id",
            name="uq_capacity_prices_year_facility",
        ),
    )

    # scenarios
    op.create_table(
        "scenarios",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String(1024), nullable=True),
        sa.Column("config", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("status", scenario_status_enum, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_scenarios_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_scenarios"),
    )

    # price_curves
    op.create_table(
        "price_curves",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("curve_name", sa.String(255), nullable=False),
        sa.Column("product", market_product_enum, nullable=False),
        sa.Column("interval_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price_mwh", sa.Numeric(10, 4), nullable=False),
        sa.Column("scenario_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["scenario_id"],
            ["scenarios.id"],
            name="fk_price_curves_scenario_id_scenarios",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_price_curves"),
    )
    op.create_index(
        "ix_price_curves_product_interval",
        "price_curves",
        ["product", "interval_start"],
    )


def downgrade() -> None:
    op.drop_index("ix_price_curves_product_interval", table_name="price_curves")
    op.drop_table("price_curves")
    op.drop_table("scenarios")
    op.drop_table("capacity_prices")
    op.drop_index("ix_market_prices_product_interval", table_name="market_prices")
    op.drop_table("market_prices")
    op.drop_index("ix_meter_readings_site_interval", table_name="meter_readings")
    op.drop_table("meter_readings")
    op.drop_table("sites")
    op.drop_table("loss_factors")
    op.drop_table("tariff_schedules")
    op.drop_table("projects")

    for enum_name in (
        "market_product_enum",
        "data_quality_enum",
        "loss_factor_type_enum",
        "scenario_status_enum",
    ):
        sa.Enum(name=enum_name).drop(op.get_bind(), checkfirst=True)
