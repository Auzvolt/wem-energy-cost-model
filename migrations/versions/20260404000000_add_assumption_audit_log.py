"""Add assumption_audit_log table.

Revision ID: 20260404000000
Revises: 20260403000000
Create Date: 2026-04-04 00:00:00

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260404000000"
down_revision = "20260403000000"
branch_labels = None
depends_on = None

AUDIT_OPERATION_ENUM = postgresql.ENUM(
    "create",
    "update",
    "delete",
    name="audit_operation",
)


def upgrade() -> None:
    AUDIT_OPERATION_ENUM.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "assumption_audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("entry_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("set_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation", AUDIT_OPERATION_ENUM, nullable=False),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("old_value", postgresql.JSONB, nullable=True),
        sa.Column("new_value", postgresql.JSONB, nullable=True),
    )

    # FK to assumption_sets (nullable FK not enforced for deleted sets)
    op.create_foreign_key(
        "fk_audit_log_set_id",
        "assumption_audit_log",
        "assumption_sets",
        ["set_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.create_index("ix_audit_log_set_id", "assumption_audit_log", ["set_id"])
    op.create_index("ix_audit_log_entry_id", "assumption_audit_log", ["entry_id"])
    op.create_index("ix_audit_log_changed_at", "assumption_audit_log", ["changed_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_changed_at", "assumption_audit_log")
    op.drop_index("ix_audit_log_entry_id", "assumption_audit_log")
    op.drop_index("ix_audit_log_set_id", "assumption_audit_log")
    op.drop_constraint("fk_audit_log_set_id", "assumption_audit_log", type_="foreignkey")
    op.drop_table("assumption_audit_log")
    AUDIT_OPERATION_ENUM.drop(op.get_bind(), checkfirst=True)
