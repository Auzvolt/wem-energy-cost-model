"""Initial schema: facilities, intervals, price_intervals, assets, scenarios, scenario_results.

Revision ID: 20260401000000
Revises:
Create Date: 2026-04-01 00:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260401000000"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # facilities
    op.create_table(
        "facilities",
        sa.Column("facility_code", sa.String(64), primary_key=True),
        sa.Column("facility_name", sa.String(256), nullable=False),
        sa.Column("participant_id", sa.String(64), nullable=True),
        sa.Column("technology_type", sa.String(64), nullable=True),
        sa.Column("capacity_mw", sa.Float(), nullable=True),
        sa.Column("registered_from", sa.DateTime(timezone=True), nullable=True),
    )

    # intervals
    op.create_table(
        "intervals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("interval_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "facility_code",
            sa.String(64),
            sa.ForeignKey("facilities.facility_code"),
            nullable=False,
        ),
        sa.Column("actual_mw", sa.Float(), nullable=False),
        sa.Column("trading_price_aud_mwh", sa.Float(), nullable=True),
        sa.UniqueConstraint("interval_start", "facility_code", name="uq_interval"),
    )
    op.create_index("ix_intervals_interval_start", "intervals", ["interval_start"])

    # price_intervals
    op.create_table(
        "price_intervals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("interval_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("region", sa.String(32), nullable=False),
        sa.Column("rrp_aud_mwh", sa.Float(), nullable=False),
        sa.Column("total_demand_mw", sa.Float(), nullable=True),
        sa.UniqueConstraint("interval_start", "region", name="uq_price_interval"),
    )
    op.create_index(
        "ix_price_intervals_interval_start", "price_intervals", ["interval_start"]
    )

    # assets
    op.create_table(
        "assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("asset_type", sa.String(32), nullable=False),
        sa.Column("capacity_kw", sa.Float(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    # scenarios
    op.create_table(
        "scenarios",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("params", sa.JSON(), nullable=False, server_default="{}"),
    )

    # scenario_results
    op.create_table(
        "scenario_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "scenario_id",
            sa.String(36),
            sa.ForeignKey("scenarios.id"),
            nullable=False,
        ),
        sa.Column("interval_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "asset_id", sa.String(36), sa.ForeignKey("assets.id"), nullable=False
        ),
        sa.Column("dispatch_kw", sa.Float(), nullable=False),
        sa.Column("revenue_aud", sa.Float(), nullable=False),
    )
    op.create_index(
        "ix_scenario_results_scenario_interval",
        "scenario_results",
        ["scenario_id", "interval_start"],
    )


def downgrade() -> None:
    op.drop_index("ix_scenario_results_scenario_interval", "scenario_results")
    op.drop_table("scenario_results")
    op.drop_table("scenarios")
    op.drop_table("assets")
    op.drop_index("ix_price_intervals_interval_start", "price_intervals")
    op.drop_table("price_intervals")
    op.drop_index("ix_intervals_interval_start", "intervals")
    op.drop_table("intervals")
    op.drop_table("facilities")
