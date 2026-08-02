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


class BeliefRule(StrEnum):
    DIRECT_OBSERVATION = "direct_observation"
    TESTIMONY = "testimony"
    DENIAL = "denial"
    CORRECTION = "correction"


class BeliefState(StrEnum):
    SETTLED = "settled"
    UNRESOLVED_CONTRADICTION = "unresolved_contradiction"


class BeliefUpdate(ContractModel):
    """An inspectable explanation of one immutable belief transition."""

    rule: BeliefRule
    evidence_id: EvidenceId
    previous_confidence: Confidence
    new_confidence: Confidence
    effective_strength: Confidence
    occurred_at: datetime
    explanation: str = Field(min_length=1, max_length=1_000)

    @model_validator(mode="after")
    def require_aware_timestamp(self) -> Self:
        _require_aware(self.occurred_at, "occurred_at")
        return self


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
    source_character_id: CharacterId | None = None
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
    supporting_evidence_ids: tuple[EvidenceId, ...] = ()
    conflicting_evidence_ids: tuple[EvidenceId, ...] = ()
    state: BeliefState = BeliefState.SETTLED
    update_history: tuple[BeliefUpdate, ...] = ()
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
        if self.evidence_ids and not (
            self.supporting_evidence_ids or self.conflicting_evidence_ids
        ):
            object.__setattr__(self, "supporting_evidence_ids", self.evidence_ids)
        classified = self.supporting_evidence_ids + self.conflicting_evidence_ids
        if len(set(classified)) != len(classified):
            raise ValueError("supporting and conflicting evidence must be unique")
        if set(classified) != set(self.evidence_ids):
            raise ValueError("all evidence must be classified as supporting or conflicting")
        if self.state is BeliefState.UNRESOLVED_CONTRADICTION and not (
            self.supporting_evidence_ids and self.conflicting_evidence_ids
        ):
            raise ValueError("unresolved contradiction requires evidence on both sides")
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
