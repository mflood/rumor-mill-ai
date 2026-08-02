"""Track whether a worker has composed the autonomous story pipeline.

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"


def upgrade() -> None:
    op.add_column(
        "worker_heartbeats",
        sa.Column(
            "story_pipeline_ready",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "worker_heartbeats",
        sa.Column("last_story_job_completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("worker_heartbeats", "last_story_job_completed_at")
    op.drop_column("worker_heartbeats", "story_pipeline_ready")
