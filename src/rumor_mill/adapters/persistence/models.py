"""Relational storage schema for all durable simulation state."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class IdMixin:
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)


class CreatedMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class WorldModel(IdMixin, CreatedMixin, Base):
    __tablename__ = "worlds"

    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    __table_args__ = (CheckConstraint("schema_version > 0", name="positive_schema_version"),)


class RunModel(IdMixin, Base):
    __tablename__ = "runs"

    world_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("worlds.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    clock_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="wall")
    simulation_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    wall_time_anchor: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    clock_rate: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False, default=1)
    tick_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    max_catch_up_ticks: Mapped[int] = mapped_column(Integer, nullable=False, default=12)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','running','paused','completed','failed')",
            name="valid_status",
        ),
        CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="valid_times"),
        CheckConstraint("clock_mode IN ('wall','paused','manual')", name="valid_clock_mode"),
        CheckConstraint("clock_rate > 0", name="positive_clock_rate"),
        CheckConstraint("tick_seconds > 0", name="positive_tick_seconds"),
        CheckConstraint("max_catch_up_ticks > 0", name="positive_max_catch_up_ticks"),
        Index("ix_runs_world_status", "world_id", "status"),
    )


class EventModel(IdMixin, CreatedMixin, Base):
    __tablename__ = "events"

    run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "sequence"),
        CheckConstraint("sequence >= 0", name="nonnegative_sequence"),
        Index("ix_events_run_occurred", "run_id", "occurred_at"),
    )


class ClaimModel(IdMixin, CreatedMixin, Base):
    __tablename__ = "claims"

    run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    visibility: Mapped[str] = mapped_column(String(20), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    __table_args__ = (Index("ix_claims_run_created", "run_id", "created_at"),)


class BeliefModel(IdMixin, CreatedMixin, Base):
    __tablename__ = "beliefs"

    run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    character_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    claim_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("claims.id", ondelete="CASCADE"), nullable=False
    )
    confidence: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "character_id", "claim_id", "version"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="valid_confidence"),
        CheckConstraint("version > 0", name="positive_version"),
        Index("ix_beliefs_character_claim", "run_id", "character_id", "claim_id"),
    )


class EvidenceModel(IdMixin, CreatedMixin, Base):
    __tablename__ = "evidence"

    run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    claim_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("claims.id", ondelete="CASCADE"), nullable=False
    )
    stance: Mapped[str] = mapped_column(String(20), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    __table_args__ = (
        CheckConstraint("stance IN ('supports','refutes','ambiguous')", name="valid_stance"),
        Index("ix_evidence_run_claim", "run_id", "claim_id"),
    )


class MemoryModel(IdMixin, CreatedMixin, Base):
    __tablename__ = "memories"

    run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    character_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    event_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("events.id", ondelete="CASCADE"))
    claim_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("claims.id", ondelete="CASCADE"))
    remembered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "(event_id IS NOT NULL AND claim_id IS NULL) OR "
            "(event_id IS NULL AND claim_id IS NOT NULL)",
            name="exactly_one_source",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="valid_confidence"),
        Index("ix_memories_character_remembered", "run_id", "character_id", "remembered_at"),
    )


class SceneModel(IdMixin, CreatedMixin, Base):
    __tablename__ = "scenes"

    run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "sequence"),
        CheckConstraint("sequence >= 0", name="nonnegative_sequence"),
        CheckConstraint("ends_at >= starts_at", name="valid_times"),
        Index("ix_scenes_run_starts", "run_id", "starts_at"),
    )


class VisitorModel(IdMixin, CreatedMixin, Base):
    __tablename__ = "visitors"

    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active_run_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        CheckConstraint("expires_at >= created_at", name="valid_expiry"),
        Index("ix_visitors_expiry", "expires_at", "reset_at"),
        Index("ix_visitors_active_run", "active_run_id"),
    )


class VisitorCharacterStateModel(IdMixin, CreatedMixin, Base):
    __tablename__ = "visitor_character_states"

    visitor_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("visitors.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    character_id: Mapped[str] = mapped_column(String(80), nullable=False)
    relationship_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    trust: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False, default=0)
    memories: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("visitor_id", "run_id", "character_id"),
        CheckConstraint("trust >= 0 AND trust <= 1", name="valid_trust"),
        Index("ix_visitor_character_state_lookup", "visitor_id", "run_id", "character_id"),
    )


class ConversationModel(IdMixin, CreatedMixin, Base):
    __tablename__ = "conversations"

    run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    scene_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("scenes.id", ondelete="SET NULL")
    )
    visitor_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("visitors.id", ondelete="CASCADE")
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    participant_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    transcript: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)

    __table_args__ = (
        CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="valid_times"),
        Index("ix_conversations_visitor_started", "visitor_id", "started_at"),
        Index("ix_conversations_run_started", "run_id", "started_at"),
    )


class JobModel(IdMixin, CreatedMixin, Base):
    __tablename__ = "jobs"

    run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(200))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5, server_default="5"
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','running','completed','failed','dead')", name="valid_status"
        ),
        CheckConstraint("attempts >= 0", name="nonnegative_attempts"),
        CheckConstraint("max_attempts > 0", name="positive_max_attempts"),
        Index("ix_jobs_claim", "status", "available_at", "lease_expires_at"),
        Index("ix_jobs_run_created", "run_id", "created_at"),
    )


class WorkerHeartbeatModel(Base):
    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OperatorAuditModel(IdMixin, CreatedMixin, Base):
    """Append-only record of privileged operational changes."""

    __tablename__ = "operator_audit_entries"

    actor: Mapped[str] = mapped_column(String(80), nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(80), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (Index("ix_operator_audit_created", "created_at"),)


class ArtifactModel(IdMixin, CreatedMixin, Base):
    __tablename__ = "artifacts"

    run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    scene_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("scenes.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    __table_args__ = (Index("ix_artifacts_run_generated", "run_id", "generated_at"),)


class NarrativeReportModel(IdMixin, CreatedMixin, Base):
    __tablename__ = "narrative_reports"

    run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    visitor_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("visitors.id", ondelete="CASCADE"), nullable=False
    )
    target_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    diagnostic_refs: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "target_kind IN ('message','recap_panel','episode')", name="valid_target_kind"
        ),
        CheckConstraint(
            "category IN ('confusing','unsafe','continuity','other')", name="valid_category"
        ),
        Index("ix_narrative_reports_run_created", "run_id", "created_at"),
    )
