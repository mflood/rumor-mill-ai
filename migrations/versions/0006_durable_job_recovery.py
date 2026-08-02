"""Add durable job leases, retries, results, and dead-letter state.

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.drop_constraint("ck_jobs_valid_status", type_="check")
        batch.drop_index("ix_jobs_claim")
        batch.add_column(sa.Column("available_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
        batch.add_column(
            sa.Column("max_attempts", sa.Integer(), server_default="5", nullable=False)
        )
        batch.add_column(sa.Column("result", sa.JSON()))
        batch.add_column(sa.Column("completed_at", sa.DateTime(timezone=True)))
    op.execute("UPDATE jobs SET available_at = scheduled_at WHERE available_at IS NULL")
    with op.batch_alter_table("jobs") as batch:
        batch.alter_column("available_at", nullable=False)
        batch.create_check_constraint(
            "ck_jobs_valid_status", "status IN ('pending','running','completed','failed','dead')"
        )
        batch.create_check_constraint("ck_jobs_positive_max_attempts", "max_attempts > 0")
        batch.create_index(
            "ix_jobs_claim", ["status", "available_at", "lease_expires_at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.drop_index("ix_jobs_claim")
        batch.drop_constraint("ck_jobs_positive_max_attempts", type_="check")
        batch.drop_constraint("ck_jobs_valid_status", type_="check")
        batch.drop_column("completed_at")
        batch.drop_column("result")
        batch.drop_column("max_attempts")
        batch.drop_column("lease_expires_at")
        batch.drop_column("available_at")
        batch.create_check_constraint(
            "ck_jobs_valid_status", "status IN ('pending','running','completed','failed')"
        )
        batch.create_index("ix_jobs_claim", ["status", "scheduled_at", "locked_at"], unique=False)
