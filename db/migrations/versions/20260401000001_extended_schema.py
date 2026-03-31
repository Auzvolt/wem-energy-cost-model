"""Add full market data schema: market_prices, interval_readings, forward curves, assumption library.

Revision ID: 20260401000001
Revises: 20260401000000
Create Date: 2026-04-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260401000001"
down_revision: str | None = "20260401000000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # market_prices ─ 5-min prices for energy, FCESS, capacity
    op.create_table(
        "market_prices",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("interval_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settlement_point", sa.String(32), nullable=False),
        sa.Column("product", sa.String(32), nullable=False),
        sa.Column("price_aud_mwh", sa.Float(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default="aemo_api"),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "interval_start", "settlement_point", "product", name="uq_market_price"
        ),
    )
    op.create_index("ix_market_prices_interval_start", "market_prices", ["interval_start"])
    op.create_index(
        "ix_market_prices_product_interval", "market_prices", ["product", "interval_start"]
    )

    # interval_readings ─ customer NEM12-style meter data
    op.create_table(
        "interval_readings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("meter_id", sa.String(64), nullable=False),
        sa.Column("interval_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("kwh", sa.Float(), nullable=False),
        sa.Column("quality_flag", sa.String(4), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("meter_id", "interval_start", name="uq_reading"),
    )
    op.create_index(
        "ix_interval_readings_meter_interval",
        "interval_readings",
        ["meter_id", "interval_start"],
    )

    # forward_curves ─ header
    op.create_table(
        "forward_curves",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("product", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "product", "version", name="uq_forward_curve"),
    )

    # forward_curve_points ─ rows
    op.create_table(
        "forward_curve_points",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("curve_id", sa.String(36), nullable=False),
        sa.Column("interval_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settlement_point", sa.String(32), nullable=False),
        sa.Column("price_aud_mwh", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["curve_id"], ["forward_curves.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "curve_id", "interval_start", "settlement_point", name="uq_curve_point"
        ),
    )
    op.create_index("ix_fcp_curve_interval", "forward_curve_points", ["curve_id", "interval_start"])

    # assumption_sets
    op.create_table(
        "assumption_sets",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.String(1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # assumption_items
    op.create_table(
        "assumption_items",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("assumption_set_id", sa.String(36), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("value", sa.String(1024), nullable=False),
        sa.Column("unit", sa.String(32), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("changed_by", sa.String(128), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("previous_value", sa.String(1024), nullable=True),
        sa.ForeignKeyConstraint(["assumption_set_id"], ["assumption_sets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "assumption_set_id", "category", "key", "version", name="uq_assumption_item"
        ),
    )
    op.create_index(
        "ix_assumption_items_set_cat_key",
        "assumption_items",
        ["assumption_set_id", "category", "key"],
    )


def downgrade() -> None:
    op.drop_index("ix_assumption_items_set_cat_key", table_name="assumption_items")
    op.drop_table("assumption_items")
    op.drop_table("assumption_sets")
    op.drop_index("ix_fcp_curve_interval", table_name="forward_curve_points")
    op.drop_table("forward_curve_points")
    op.drop_table("forward_curves")
    op.drop_index("ix_interval_readings_meter_interval", table_name="interval_readings")
    op.drop_table("interval_readings")
    op.drop_index("ix_market_prices_product_interval", table_name="market_prices")
    op.drop_index("ix_market_prices_interval_start", table_name="market_prices")
    op.drop_table("market_prices")
