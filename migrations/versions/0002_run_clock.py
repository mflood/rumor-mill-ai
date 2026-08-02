"""Add durable simulation clock state to runs.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.add_column(
            sa.Column("clock_mode", sa.String(length=20), server_default="wall", nullable=False)
        )
        batch.add_column(sa.Column("simulation_time", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("wall_time_anchor", sa.DateTime(timezone=True)))
        batch.add_column(
            sa.Column("clock_rate", sa.Numeric(10, 4), server_default="1", nullable=False)
        )
        batch.add_column(
            sa.Column("tick_seconds", sa.Integer(), server_default="300", nullable=False)
        )
        batch.add_column(
            sa.Column("max_catch_up_ticks", sa.Integer(), server_default="12", nullable=False)
        )

    op.execute("UPDATE runs SET simulation_time = started_at, wall_time_anchor = started_at")

    with op.batch_alter_table("runs") as batch:
        batch.alter_column("simulation_time", nullable=False)
        batch.alter_column("wall_time_anchor", nullable=False)
        batch.create_check_constraint(
            "ck_runs_valid_clock_mode", "clock_mode IN ('wall','paused','manual')"
        )
        batch.create_check_constraint("ck_runs_positive_clock_rate", "clock_rate > 0")
        batch.create_check_constraint("ck_runs_positive_tick_seconds", "tick_seconds > 0")
        batch.create_check_constraint(
            "ck_runs_positive_max_catch_up_ticks", "max_catch_up_ticks > 0"
        )


def downgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.drop_constraint("ck_runs_positive_max_catch_up_ticks", type_="check")
        batch.drop_constraint("ck_runs_positive_tick_seconds", type_="check")
        batch.drop_constraint("ck_runs_positive_clock_rate", type_="check")
        batch.drop_constraint("ck_runs_valid_clock_mode", type_="check")
        batch.drop_column("max_catch_up_ticks")
        batch.drop_column("tick_seconds")
        batch.drop_column("clock_rate")
        batch.drop_column("wall_time_anchor")
        batch.drop_column("simulation_time")
        batch.drop_column("clock_mode")
