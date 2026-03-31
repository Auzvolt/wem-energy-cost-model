"""Add assumption_sets and assumption_entries tables.

Revision ID: 20260401120000
Revises: 20260401000001
Create Date: 2026-04-01 12:00:00

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260401120000"
down_revision = "20260401000001"
branch_labels = None
depends_on = None

ASSUMPTION_CATEGORY_ENUM = postgresql.ENUM(
    "tariff",
    "capex",
    "opex",
    "degradation",
    "solar_yield",
    name="assumption_category",
)


def upgrade() -> None:
    # Create the PostgreSQL ENUM type.
    ASSUMPTION_CATEGORY_ENUM.create(op.get_bind(), checkfirst=True)

    # Create assumption_sets table.
    op.create_table(
        "assumption_sets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("author", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("effective_from", sa.Date, nullable=False),
        sa.Column("superseded_by", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # Self-referential FK: superseded_by → assumption_sets.id
    op.create_foreign_key(
        "fk_assumption_sets_superseded_by",
        "assumption_sets",
        "assumption_sets",
        ["superseded_by"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index("ix_assumption_sets_effective_from", "assumption_sets", ["effective_from"])

    # Create assumption_entries table.
    op.create_table(
        "assumption_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("set_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "category",
            ASSUMPTION_CATEGORY_ENUM,
            nullable=False,
        ),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("value", postgresql.JSONB, nullable=False),
        sa.Column("unit", sa.String(64), nullable=True),
        sa.Column("source", sa.String(512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    op.create_foreign_key(
        "fk_assumption_entries_set_id",
        "assumption_entries",
        "assumption_sets",
        ["set_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.create_index("ix_assumption_entries_set_id", "assumption_entries", ["set_id"])
    op.create_index(
        "ix_assumption_entries_category_key",
        "assumption_entries",
        ["set_id", "category", "key"],
    )


def downgrade() -> None:
    op.drop_index("ix_assumption_entries_category_key", "assumption_entries")
    op.drop_index("ix_assumption_entries_set_id", "assumption_entries")
    op.drop_constraint("fk_assumption_entries_set_id", "assumption_entries", type_="foreignkey")
    op.drop_table("assumption_entries")

    op.drop_index("ix_assumption_sets_effective_from", "assumption_sets")
    op.drop_constraint("fk_assumption_sets_superseded_by", "assumption_sets", type_="foreignkey")
    op.drop_table("assumption_sets")

    ASSUMPTION_CATEGORY_ENUM.drop(op.get_bind(), checkfirst=True)
