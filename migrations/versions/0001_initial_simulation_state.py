"""Create durable simulation state tables.

Revision ID: 0001
Revises: None
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id() -> sa.Column[object]:
    return sa.Column("id", sa.Uuid(), nullable=False)


def _created() -> sa.Column[object]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def _run_id() -> sa.Column[object]:
    return sa.Column(
        "run_id", sa.Uuid(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "worlds",
        _id(),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        _created(),
        sa.CheckConstraint("schema_version > 0", name="ck_worlds_positive_schema_version"),
        sa.PrimaryKeyConstraint("id", name="pk_worlds"),
        sa.UniqueConstraint("slug", name="uq_worlds_slug"),
    )
    op.create_table(
        "runs",
        _id(),
        sa.Column(
            "world_id",
            sa.Uuid(),
            sa.ForeignKey("worlds.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('pending','running','paused','completed','failed')",
            name="ck_runs_valid_status",
        ),
        sa.CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at", name="ck_runs_valid_times"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_runs"),
    )
    op.create_index("ix_runs_world_status", "runs", ["world_id", "status"])
    op.create_table(
        "events",
        _id(),
        _run_id(),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        _created(),
        sa.CheckConstraint("sequence >= 0", name="ck_events_nonnegative_sequence"),
        sa.PrimaryKeyConstraint("id", name="pk_events"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_events_run_id"),
    )
    op.create_index("ix_events_run_occurred", "events", ["run_id", "occurred_at"])
    op.create_table(
        "claims",
        _id(),
        _run_id(),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("visibility", sa.String(length=20), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        _created(),
        sa.PrimaryKeyConstraint("id", name="pk_claims"),
    )
    op.create_index("ix_claims_run_created", "claims", ["run_id", "created_at"])
    op.create_table(
        "beliefs",
        _id(),
        _run_id(),
        sa.Column("character_id", sa.Uuid(), nullable=False),
        sa.Column(
            "claim_id",
            sa.Uuid(),
            sa.ForeignKey("claims.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        _created(),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_beliefs_valid_confidence"
        ),
        sa.CheckConstraint("version > 0", name="ck_beliefs_positive_version"),
        sa.PrimaryKeyConstraint("id", name="pk_beliefs"),
        sa.UniqueConstraint(
            "run_id", "character_id", "claim_id", "version", name="uq_beliefs_run_id"
        ),
    )
    op.create_index("ix_beliefs_character_claim", "beliefs", ["run_id", "character_id", "claim_id"])
    op.create_table(
        "memories",
        _id(),
        _run_id(),
        sa.Column("character_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), sa.ForeignKey("events.id", ondelete="CASCADE")),
        sa.Column("claim_id", sa.Uuid(), sa.ForeignKey("claims.id", ondelete="CASCADE")),
        sa.Column("remembered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        _created(),
        sa.CheckConstraint(
            "(event_id IS NOT NULL AND claim_id IS NULL) OR "
            "(event_id IS NULL AND claim_id IS NOT NULL)",
            name="ck_memories_exactly_one_source",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_memories_valid_confidence"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_memories"),
    )
    op.create_index(
        "ix_memories_character_remembered",
        "memories",
        ["run_id", "character_id", "remembered_at"],
    )
    op.create_table(
        "scenes",
        _id(),
        _run_id(),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        _created(),
        sa.CheckConstraint("sequence >= 0", name="ck_scenes_nonnegative_sequence"),
        sa.CheckConstraint("ends_at >= starts_at", name="ck_scenes_valid_times"),
        sa.PrimaryKeyConstraint("id", name="pk_scenes"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_scenes_run_id"),
    )
    op.create_index("ix_scenes_run_starts", "scenes", ["run_id", "starts_at"])
    op.create_table(
        "conversations",
        _id(),
        _run_id(),
        sa.Column("scene_id", sa.Uuid(), sa.ForeignKey("scenes.id", ondelete="SET NULL")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("participant_ids", sa.JSON(), nullable=False),
        sa.Column("transcript", sa.JSON(), nullable=False),
        _created(),
        sa.CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at",
            name="ck_conversations_valid_times",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conversations"),
    )
    op.create_index("ix_conversations_run_started", "conversations", ["run_id", "started_at"])
    op.create_table(
        "jobs",
        _id(),
        _run_id(),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True)),
        sa.Column("locked_by", sa.String(length=200)),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text()),
        _created(),
        sa.CheckConstraint(
            "status IN ('pending','running','completed','failed')", name="ck_jobs_valid_status"
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_jobs_nonnegative_attempts"),
        sa.PrimaryKeyConstraint("id", name="pk_jobs"),
        sa.UniqueConstraint("idempotency_key", name="uq_jobs_idempotency_key"),
    )
    op.create_index("ix_jobs_claim", "jobs", ["status", "scheduled_at", "locked_at"])
    op.create_index("ix_jobs_run_created", "jobs", ["run_id", "created_at"])
    op.create_table(
        "artifacts",
        _id(),
        _run_id(),
        sa.Column("scene_id", sa.Uuid(), sa.ForeignKey("scenes.id", ondelete="SET NULL")),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_ids", sa.JSON(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        _created(),
        sa.PrimaryKeyConstraint("id", name="pk_artifacts"),
    )
    op.create_index("ix_artifacts_run_generated", "artifacts", ["run_id", "generated_at"])


def downgrade() -> None:
    for table_name in (
        "artifacts",
        "jobs",
        "conversations",
        "scenes",
        "memories",
        "beliefs",
        "claims",
        "events",
        "runs",
        "worlds",
    ):
        op.drop_table(table_name)
