"""Add privacy-safe player narrative reports.

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "narrative_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "run_id", sa.Uuid(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "visitor_id",
            sa.Uuid(),
            sa.ForeignKey("visitors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_kind", sa.String(length=20), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("diagnostic_refs", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "target_kind IN ('message','recap_panel','episode')",
            name="ck_narrative_reports_valid_target_kind",
        ),
        sa.CheckConstraint(
            "category IN ('confusing','unsafe','continuity','other')",
            name="ck_narrative_reports_valid_category",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_narrative_reports"),
    )
    op.create_index(
        "ix_narrative_reports_run_created", "narrative_reports", ["run_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("narrative_reports")
