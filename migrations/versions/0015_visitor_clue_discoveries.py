"""Add visitor clue discoveries.

Revision ID: 0015
Revises: 0014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "visitor_clue_discoveries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "visitor_id",
            sa.Uuid(),
            sa.ForeignKey("visitors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id", sa.Uuid(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("clue_id", sa.String(length=80), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "visitor_id", "run_id", "clue_id", name="uq_visitor_clue_discoveries_visitor_id"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_visitor_clue_discoveries"),
    )
    op.create_index(
        "ix_visitor_clue_discovery_lookup", "visitor_clue_discoveries", ["visitor_id", "run_id"]
    )


def downgrade() -> None:
    op.drop_table("visitor_clue_discoveries")
