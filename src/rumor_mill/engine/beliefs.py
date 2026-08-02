"""Deterministic, explainable updates to per-character beliefs."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from rumor_mill.engine.domain import (
    Belief,
    BeliefId,
    BeliefRule,
    BeliefState,
    BeliefUpdate,
    CharacterId,
    ClaimId,
    EventId,
    Evidence,
    EvidenceId,
    EvidenceStance,
    Lifecycle,
    MemoryId,
    Provenance,
    ProvenanceKind,
    Visibility,
)
from rumor_mill.engine.domain.base import _require_aware
from rumor_mill.engine.ports import UnitOfWork


@dataclass(frozen=True, slots=True)
class EvidenceInput:
    rule: BeliefRule
    stance: EvidenceStance
    strength: float
    occurred_at: datetime
    source_event_id: EventId | None = None
    source_memory_id: MemoryId | None = None
    source_character_id: CharacterId | None = None
    source_reliability: float = 1.0

    def __post_init__(self) -> None:
        _require_aware(self.occurred_at, "occurred_at")
        if (self.source_event_id is None) == (self.source_memory_id is None):
            raise ValueError("evidence requires exactly one event or memory source")
        for name, value in (
            ("strength", self.strength),
            ("source_reliability", self.source_reliability),
        ):
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.rule is BeliefRule.DIRECT_OBSERVATION and self.source_event_id is None:
            raise ValueError("direct observation requires an event source")
        if self.rule in (
            BeliefRule.TESTIMONY,
            BeliefRule.DENIAL,
            BeliefRule.CORRECTION,
        ) and (self.source_memory_id is None or self.source_character_id is None):
            raise ValueError(f"{self.rule.value} requires a memory and character source")
        if self.rule is BeliefRule.DENIAL and self.stance is not EvidenceStance.REFUTES:
            raise ValueError("denial must refute the claim")


class BeliefService:
    """Maintains independent, append-only beliefs without consulting canonical truth."""

    def __init__(self, unit_of_work_factory: Callable[[], UnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def consider(
        self,
        run_id: UUID,
        character_id: CharacterId,
        claim_id: ClaimId,
        item: EvidenceInput,
    ) -> Belief:
        with self._unit_of_work_factory() as unit_of_work:
            current = unit_of_work.beliefs.get_current(run_id, character_id, claim_id)
            prior = 0.5 if current is None else current.confidence
            evidence = self._make_evidence(claim_id, item)
            effective = self._effective_strength(item)
            confidence = self._updated_confidence(prior, item.stance, effective)
            supporting = () if current is None else current.supporting_evidence_ids
            conflicting = () if current is None else current.conflicting_evidence_ids
            if item.stance is EvidenceStance.SUPPORTS:
                supporting += (evidence.id,)
            else:
                conflicting += (evidence.id,)
            state = (
                BeliefState.UNRESOLVED_CONTRADICTION
                if supporting and conflicting
                else BeliefState.SETTLED
            )
            history = (() if current is None else current.update_history) + (
                BeliefUpdate(
                    rule=item.rule,
                    evidence_id=evidence.id,
                    previous_confidence=prior,
                    new_confidence=confidence,
                    effective_strength=effective,
                    occurred_at=item.occurred_at,
                    explanation=self._explain(item, prior, confidence, state),
                ),
            )
            belief = Belief(
                id=BeliefId(uuid4()),
                character_id=character_id,
                claim_id=claim_id,
                confidence=confidence,
                evidence_ids=supporting + conflicting,
                supporting_evidence_ids=supporting,
                conflicting_evidence_ids=conflicting,
                state=state,
                update_history=history,
                formed_at=item.occurred_at if current is None else current.formed_at,
                updated_at=item.occurred_at,
                provenance=Provenance(
                    kind=ProvenanceKind.DERIVED,
                    source_id=evidence.id,
                    recorded_at=item.occurred_at,
                    detail=item.rule.value,
                ),
                visibility=Visibility.PRIVATE,
                lifecycle=Lifecycle(started_at=item.occurred_at),
            )
            unit_of_work.beliefs.add_evidence(run_id, evidence)
            unit_of_work.beliefs.add_version(run_id, belief)
            unit_of_work.commit()
            return belief

    @staticmethod
    def _effective_strength(item: EvidenceInput) -> float:
        reliability = 1.0 if item.rule is BeliefRule.DIRECT_OBSERVATION else item.source_reliability
        if item.rule is BeliefRule.CORRECTION:
            reliability = min(1.0, reliability + 0.15)
        return round(item.strength * reliability, 6)

    @staticmethod
    def _updated_confidence(prior: float, stance: EvidenceStance, strength: float) -> float:
        if stance is EvidenceStance.AMBIGUOUS:
            return prior
        target = 1.0 if stance is EvidenceStance.SUPPORTS else 0.0
        return round(prior + (target - prior) * strength, 6)

    @staticmethod
    def _make_evidence(claim_id: ClaimId, item: EvidenceInput) -> Evidence:
        source_id = item.source_event_id or item.source_memory_id
        assert source_id is not None
        return Evidence(
            id=EvidenceId(uuid4()),
            claim_id=claim_id,
            stance=item.stance,
            strength=item.strength,
            source_event_id=item.source_event_id,
            source_memory_id=item.source_memory_id,
            source_character_id=item.source_character_id,
            provenance=Provenance(
                kind=(
                    ProvenanceKind.OBSERVED
                    if item.rule is BeliefRule.DIRECT_OBSERVATION
                    else ProvenanceKind.REPORTED
                ),
                source_id=source_id,
                recorded_at=item.occurred_at,
                detail=item.rule.value,
            ),
            visibility=Visibility.PRIVATE,
            lifecycle=Lifecycle(started_at=item.occurred_at),
        )

    @staticmethod
    def _explain(item: EvidenceInput, prior: float, confidence: float, state: BeliefState) -> str:
        source = item.source_event_id or item.source_memory_id
        result = (
            f"{item.rule.value} from {source} {item.stance.value} the claim; "
            f"confidence changed from {prior:.3f} to {confidence:.3f}."
        )
        if state is BeliefState.UNRESOLVED_CONTRADICTION:
            result += " Supporting and conflicting evidence remain unresolved."
        return result
