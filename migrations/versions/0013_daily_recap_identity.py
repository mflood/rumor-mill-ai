"""Give daily recaps a canonical per-run story-date identity.

Revision ID: 0013
Revises: 0012
"""

from datetime import date

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"


def upgrade() -> None:
    with op.batch_alter_table("artifacts") as batch:
        batch.add_column(sa.Column("story_date", sa.Date(), nullable=True))

    artifacts = sa.table(
        "artifacts",
        sa.column("id", sa.Uuid()),
        sa.column("run_id", sa.Uuid()),
        sa.column("kind", sa.String()),
        sa.column("generated_at", sa.DateTime(timezone=True)),
        sa.column("story_date", sa.Date()),
        sa.column("payload", sa.JSON()),
    )
    connection = op.get_bind()
    seen: set[tuple[object, date]] = set()
    for artifact_id, run_id, payload in connection.execute(
        sa.select(artifacts.c.id, artifacts.c.run_id, artifacts.c.payload)
        .where(artifacts.c.kind == "daily_recap")
        .order_by(artifacts.c.generated_at, artifacts.c.id)
    ):
        raw = (payload or {}).get("recap", {}).get("story_date")
        if isinstance(raw, str):
            try:
                parsed = date.fromisoformat(raw)
            except ValueError:
                continue
            identity = (run_id, parsed)
            canonical = identity not in seen
            seen.add(identity)
            updated_payload = dict(payload or {})
            updated_payload["canonical"] = canonical
            connection.execute(
                artifacts.update()
                .where(artifacts.c.id == artifact_id)
                .values(
                    story_date=parsed if canonical else None,
                    payload=updated_payload,
                )
            )

    with op.batch_alter_table("artifacts") as batch:
        batch.create_unique_constraint(
            "uq_artifacts_run_id_kind_story_date",
            ["run_id", "kind", "story_date"],
        )
        batch.create_index("ix_artifacts_run_story_date", ["run_id", "story_date"])

    op.add_column(
        "worker_heartbeats",
        sa.Column("last_recap_job_enqueued_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "worker_heartbeats",
        sa.Column("last_recap_job_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "worker_heartbeats",
        sa.Column("last_recap_job_failed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "worker_heartbeats",
        sa.Column("recap_queue_depth", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("worker_heartbeats", "recap_queue_depth")
    op.drop_column("worker_heartbeats", "last_recap_job_failed_at")
    op.drop_column("worker_heartbeats", "last_recap_job_completed_at")
    op.drop_column("worker_heartbeats", "last_recap_job_enqueued_at")
    with op.batch_alter_table("artifacts") as batch:
        batch.drop_index("ix_artifacts_run_story_date")
        batch.drop_constraint("uq_artifacts_run_id_kind_story_date", type_="unique")
        batch.drop_column("story_date")
