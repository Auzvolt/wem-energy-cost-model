"""Add interval_data table for 5-minute meter interval import.

Revision ID: 20260402000000
Revises: 20260403000000
Create Date: 2026-04-02 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260402000000"
down_revision = "20260403000000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "interval_data",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("site_id", sa.String(length=100), nullable=False),
        sa.Column("interval_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("energy_kwh", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("power_kw", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "site_id", "interval_start", name="uq_interval_data_site_start"
        ),
    )
    op.create_index(
        "ix_interval_data_site_start",
        "interval_data",
        ["site_id", "interval_start"],
        unique=False,
    )
    op.create_index(
        op.f("ix_interval_data_site_id"),
        "interval_data",
        ["site_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_interval_data_site_id"), table_name="interval_data")
    op.drop_index("ix_interval_data_site_start", table_name="interval_data")
    op.drop_table("interval_data")
