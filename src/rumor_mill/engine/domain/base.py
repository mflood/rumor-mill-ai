"""Primitives shared by all domain contract layers."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, NewType, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

CharacterId = NewType("CharacterId", UUID)
LocationId = NewType("LocationId", UUID)
RelationshipId = NewType("RelationshipId", UUID)
SceneId = NewType("SceneId", UUID)
EventId = NewType("EventId", UUID)
ClaimId = NewType("ClaimId", UUID)
EvidenceId = NewType("EvidenceId", UUID)
BeliefId = NewType("BeliefId", UUID)
MemoryId = NewType("MemoryId", UUID)
PresentationArtifactId = NewType("PresentationArtifactId", UUID)

Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class Visibility(StrEnum):
    """Who is allowed to receive a record through application queries."""

    PUBLIC = "public"
    PARTICIPANTS = "participants"
    PRIVATE = "private"
    ENGINE_ONLY = "engine_only"


class LifecycleStatus(StrEnum):
    """Supported lifecycle states for versioned records."""

    ACTIVE = "active"
    RETRACTED = "retracted"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class ProvenanceKind(StrEnum):
    """How information entered the story system."""

    AUTHORED = "authored"
    OBSERVED = "observed"
    REPORTED = "reported"
    INFERRED = "inferred"
    GENERATED = "generated"
    DERIVED = "derived"


class ContractModel(BaseModel):
    """Strict, immutable base for values crossing domain boundaries."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Provenance(ContractModel):
    """Traceable origin for a domain assertion or artifact."""

    kind: ProvenanceKind
    source_id: UUID | None = None
    recorded_at: datetime
    detail: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def require_aware_timestamp(self) -> Self:
        _require_aware(self.recorded_at, "recorded_at")
        if self.kind is not ProvenanceKind.AUTHORED and self.source_id is None:
            raise ValueError("non-authored provenance requires source_id")
        return self


class Lifecycle(ContractModel):
    """Lifecycle metadata; records are replaced, never updated in place."""

    status: LifecycleStatus = LifecycleStatus.ACTIVE
    started_at: datetime
    ended_at: datetime | None = None
    supersedes_id: UUID | None = None
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_transition_metadata(self) -> Self:
        _require_aware(self.started_at, "started_at")
        if self.ended_at is not None:
            _require_aware(self.ended_at, "ended_at")
            if self.ended_at < self.started_at:
                raise ValueError("ended_at cannot be before started_at")

        if self.status is LifecycleStatus.ACTIVE and self.ended_at is not None:
            raise ValueError("active lifecycle cannot have ended_at")
        if self.status is not LifecycleStatus.ACTIVE and self.ended_at is None:
            raise ValueError("inactive lifecycle requires ended_at")
        if self.status is LifecycleStatus.SUPERSEDED and self.supersedes_id is None:
            raise ValueError("superseded lifecycle requires supersedes_id")
        return self


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
