"""Track autonomous story-pipeline progress.

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"


def upgrade() -> None:
    op.add_column(
        "worker_heartbeats",
        sa.Column("last_clock_advanced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "worker_heartbeats",
        sa.Column("last_story_job_enqueued_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "worker_heartbeats",
        sa.Column("story_queue_depth", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("worker_heartbeats", "story_queue_depth")
    op.drop_column("worker_heartbeats", "last_story_job_enqueued_at")
    op.drop_column("worker_heartbeats", "last_clock_advanced_at")
