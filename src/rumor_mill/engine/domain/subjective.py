"""Character knowledge contracts, separate from canonical truth."""

from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from rumor_mill.engine.domain.base import (
    BeliefId,
    CharacterId,
    ClaimId,
    Confidence,
    ContractModel,
    EventId,
    EvidenceId,
    Lifecycle,
    MemoryId,
    Provenance,
    Visibility,
    _require_aware,
)


class EvidenceStance(StrEnum):
    SUPPORTS = "supports"
    REFUTES = "refutes"
    AMBIGUOUS = "ambiguous"


class Claim(ContractModel):
    """A proposition that may or may not agree with canon."""

    schema_version: Literal[1] = 1
    id: ClaimId
    statement: str = Field(min_length=1, max_length=2_000)
    subject_ids: tuple[CharacterId, ...] = ()
    provenance: Provenance
    visibility: Visibility
    lifecycle: Lifecycle


class Evidence(ContractModel):
    """A character-readable reason to accept or reject a claim."""

    schema_version: Literal[1] = 1
    id: EvidenceId
    claim_id: ClaimId
    stance: EvidenceStance
    strength: Confidence
    source_event_id: EventId | None = None
    source_memory_id: MemoryId | None = None
    provenance: Provenance
    visibility: Visibility
    lifecycle: Lifecycle

    @model_validator(mode="after")
    def require_one_source(self) -> Self:
        sources = (self.source_event_id, self.source_memory_id)
        if sum(source is not None for source in sources) != 1:
            raise ValueError("evidence requires exactly one event or memory source")
        return self


class Belief(ContractModel):
    """A character's current confidence in a claim, not a mutation of canon."""

    schema_version: Literal[1] = 1
    id: BeliefId
    character_id: CharacterId
    claim_id: ClaimId
    confidence: Confidence
    evidence_ids: tuple[EvidenceId, ...] = ()
    formed_at: datetime
    updated_at: datetime
    provenance: Provenance
    visibility: Visibility = Visibility.PRIVATE
    lifecycle: Lifecycle

    @model_validator(mode="after")
    def validate_belief_timestamps(self) -> Self:
        _require_aware(self.formed_at, "formed_at")
        _require_aware(self.updated_at, "updated_at")
        if self.updated_at < self.formed_at:
            raise ValueError("updated_at cannot be before formed_at")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("evidence_ids must be unique")
        return self


class Memory(ContractModel):
    """What a character experienced or was told, with explicit sourcing."""

    schema_version: Literal[1] = 1
    id: MemoryId
    character_id: CharacterId
    content: str = Field(min_length=1, max_length=4_000)
    source_event_id: EventId | None = None
    source_claim_id: ClaimId | None = None
    experienced_at: datetime
    remembered_at: datetime
    confidence: Confidence
    salience: Confidence = 0.5
    plot_importance: Confidence = 0.0
    provenance: Provenance
    visibility: Visibility = Visibility.PRIVATE
    lifecycle: Lifecycle

    @model_validator(mode="after")
    def validate_memory(self) -> Self:
        _require_aware(self.experienced_at, "experienced_at")
        _require_aware(self.remembered_at, "remembered_at")
        if self.remembered_at < self.experienced_at:
            raise ValueError("remembered_at cannot be before experienced_at")
        if (self.source_event_id is None) == (self.source_claim_id is None):
            raise ValueError("memory requires exactly one event or claim source")
        return self
