"""create fcess_prices table

Revision ID: 20260401000001
Revises:
Create Date: 2026-04-01 00:00:01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260401000001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fcess_prices",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("product", sa.String(32), nullable=False),
        sa.Column("interval_start_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price_aud_mwh", sa.Float, nullable=False),
        sa.Column("source_url", sa.String(512), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_fcess_prices_product", "fcess_prices", ["product"])
    op.create_index(
        "ix_fcess_prices_interval_start_utc",
        "fcess_prices",
        ["interval_start_utc"],
    )
    op.create_unique_constraint(
        "uq_fcess_product_interval",
        "fcess_prices",
        ["product", "interval_start_utc"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_fcess_product_interval", "fcess_prices", type_="unique")
    op.drop_index("ix_fcess_prices_interval_start_utc", "fcess_prices")
    op.drop_index("ix_fcess_prices_product", "fcess_prices")
    op.drop_table("fcess_prices")
