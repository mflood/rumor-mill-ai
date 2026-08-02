"""Add append-only operator audit entries.

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "operator_audit_entries",
        sa.Column("actor", sa.String(length=80), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("resource_kind", sa.String(length=40), nullable=False),
        sa.Column("resource_id", sa.String(length=80), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_operator_audit_entries")),
    )
    op.create_index(
        "ix_operator_audit_created",
        "operator_audit_entries",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_operator_audit_created", table_name="operator_audit_entries")
    op.drop_table("operator_audit_entries")
