"""Persist the active story selected by each visitor.

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("visitors") as batch:
        batch.add_column(sa.Column("active_run_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_visitors_active_run_id_runs",
            "runs",
            ["active_run_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_visitors_active_run", ["active_run_id"])


def downgrade() -> None:
    with op.batch_alter_table("visitors") as batch:
        batch.drop_index("ix_visitors_active_run")
        batch.drop_constraint("fk_visitors_active_run_id_runs", type_="foreignkey")
        batch.drop_column("active_run_id")
