"""Add interval_data table for imported interval meter data.

Revision ID: 20260402000000
Revises: 20260401000000
Create Date: 2026-04-02 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260402000000"
down_revision: str | None = "20260401000000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interval_data",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("site_id", sa.String(64), nullable=False),
        sa.Column("nmi", sa.String(32), nullable=True),
        sa.Column("interval_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("energy_kwh", sa.Float, nullable=False),
        sa.Column("quality_flag", sa.String(8), nullable=False, server_default="A"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("site_id", "interval_start", name="uq_interval_data_site_time"),
    )
    op.create_index("ix_interval_data_start", "interval_data", ["interval_start"])


def downgrade() -> None:
    op.drop_index("ix_interval_data_start", table_name="interval_data")
    op.drop_table("interval_data")
