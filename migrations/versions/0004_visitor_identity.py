"""Add private anonymous visitor identities and character-scoped state.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "visitors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reset_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("expires_at >= created_at", name="valid_expiry"),
        sa.PrimaryKeyConstraint("id", name="pk_visitors"),
        sa.UniqueConstraint("token_hash", name="uq_visitors_token_hash"),
    )
    op.create_index("ix_visitors_expiry", "visitors", ["expires_at", "reset_at"])
    op.create_table(
        "visitor_character_states",
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
        sa.Column("character_id", sa.String(length=80), nullable=False),
        sa.Column("relationship_summary", sa.Text(), nullable=False),
        sa.Column("trust", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("memories", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("trust >= 0 AND trust <= 1", name="valid_trust"),
        sa.PrimaryKeyConstraint("id", name="pk_visitor_character_states"),
        sa.UniqueConstraint(
            "visitor_id", "run_id", "character_id", name="uq_visitor_character_states_visitor_id"
        ),
    )
    op.create_index(
        "ix_visitor_character_state_lookup",
        "visitor_character_states",
        ["visitor_id", "run_id", "character_id"],
    )
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column("visitor_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_conversations_visitor_id_visitors",
            "visitors",
            ["visitor_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_index("ix_conversations_visitor_started", ["visitor_id", "started_at"])


def downgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.drop_index("ix_conversations_visitor_started")
        batch.drop_constraint("fk_conversations_visitor_id_visitors", type_="foreignkey")
        batch.drop_column("visitor_id")
    op.drop_table("visitor_character_states")
    op.drop_table("visitors")
