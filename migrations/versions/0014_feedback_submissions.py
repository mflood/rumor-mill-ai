"""Add player feedback submissions.

Revision ID: 0014
Revises: 0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feedback_submissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("page_path", sa.String(length=200)),
        sa.Column(
            "visitor_id",
            sa.Uuid(),
            sa.ForeignKey("visitors.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("length(content) > 0", name="ck_feedback_submissions_nonempty_content"),
        sa.PrimaryKeyConstraint("id", name="pk_feedback_submissions"),
    )
    op.create_index("ix_feedback_submissions_created", "feedback_submissions", ["created_at"])


def downgrade() -> None:
    op.drop_table("feedback_submissions")
