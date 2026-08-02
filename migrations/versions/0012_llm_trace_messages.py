"""Add opt-in durable LLM request and response traces.

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"


def upgrade() -> None:
    op.create_table(
        "llm_trace_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("purpose", sa.String(length=120), nullable=False),
        sa.Column("item_type", sa.String(length=40), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "direction IN ('outbound','inbound')",
            name=op.f("ck_llm_trace_messages_valid_direction"),
        ),
        sa.CheckConstraint(
            "sequence >= 0", name=op.f("ck_llm_trace_messages_nonnegative_sequence")
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name=op.f("ck_llm_trace_messages_nonnegative_duration"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_trace_messages")),
        sa.UniqueConstraint(
            "call_id", "direction", "sequence", name=op.f("uq_llm_trace_messages_call_id")
        ),
    )
    op.create_index("ix_llm_trace_call_created", "llm_trace_messages", ["call_id", "created_at"])
    op.create_index("ix_llm_trace_purpose_created", "llm_trace_messages", ["purpose", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_llm_trace_purpose_created", table_name="llm_trace_messages")
    op.drop_index("ix_llm_trace_call_created", table_name="llm_trace_messages")
    op.drop_table("llm_trace_messages")
