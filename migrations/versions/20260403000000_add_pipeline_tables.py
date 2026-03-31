"""Add facilities and trading_intervals tables for AEMO pipeline.

Revision ID: 20260403000000
Revises: 20260401120000
Create Date: 2026-04-03 00:00:00

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260403000000"
down_revision = "20260401120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create facilities table
    op.create_table(
        "facilities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("facility_id", sa.String(50), nullable=False, unique=True),
        sa.Column("facility_name", sa.String(255), nullable=False),
        sa.Column("facility_type", sa.String(50), nullable=True),
        sa.Column("fuel_type", sa.String(50), nullable=True),
        sa.Column("capacity_mw", sa.Numeric(10, 4), nullable=True),
        sa.Column("region", sa.String(50), nullable=True, server_default="WEM"),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("source", sa.String(50), nullable=False, server_default="aemo_public"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    op.create_index("ix_facilities_facility_id", "facilities", ["facility_id"])
    op.create_index("ix_facilities_type", "facilities", ["facility_type"])

    # Create trading_intervals table
    op.create_table(
        "trading_intervals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "facility_id",
            sa.Integer(),
            sa.ForeignKey("facilities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("trading_date", sa.Date(), nullable=False),
        sa.Column("interval_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dispatch_mw", sa.Numeric(10, 4), nullable=True),
        sa.Column("metered_mw", sa.Numeric(10, 4), nullable=True),
        sa.Column("energy_mwh", sa.Numeric(12, 4), nullable=True),
        sa.Column("source", sa.String(50), nullable=False, server_default="aemo_public"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    op.create_index(
        "ix_trading_intervals_facility_interval",
        "trading_intervals",
        ["facility_id", "interval_start"],
    )
    op.create_index("ix_trading_intervals_date", "trading_intervals", ["trading_date"])
    op.create_unique_constraint(
        "uq_trading_intervals_facility_interval",
        "trading_intervals",
        ["facility_id", "interval_start"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_trading_intervals_facility_interval", "trading_intervals", type_="unique"
    )
    op.drop_index("ix_trading_intervals_date", "trading_intervals")
    op.drop_index("ix_trading_intervals_facility_interval", "trading_intervals")
    op.drop_table("trading_intervals")
    op.drop_index("ix_facilities_type", "facilities")
    op.drop_index("ix_facilities_facility_id", "facilities")
    op.drop_table("facilities")
