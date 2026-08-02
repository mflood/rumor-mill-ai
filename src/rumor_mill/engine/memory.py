"""Deterministic character memory formation, forgetting, and retrieval."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import ceil, exp
from uuid import UUID, uuid4

from rumor_mill.engine.domain import (
    CharacterId,
    ClaimId,
    EventId,
    Lifecycle,
    Memory,
    MemoryId,
    Provenance,
    ProvenanceKind,
)
from rumor_mill.engine.domain.base import _require_aware
from rumor_mill.engine.ports import UnitOfWork


class MemorySourceKind(StrEnum):
    WITNESSED_EVENT = "witnessed_event"
    COMMUNICATED_CLAIM = "communicated_claim"


@dataclass(frozen=True, slots=True)
class MemoryFormation:
    character_id: CharacterId
    content: str
    source_kind: MemorySourceKind
    source_id: UUID
    experienced_at: datetime
    confidence: float = 1.0
    salience: float = 0.5
    plot_importance: float = 0.0


@dataclass(frozen=True, slots=True)
class MemoryQuery:
    text: str
    now: datetime
    token_budget: int
    relationship: float = 0.0
    recency_half_life_days: float = 30.0
    forget_below: float = 0.05

    def __post_init__(self) -> None:
        _require_aware(self.now, "now")
        if self.token_budget < 0:
            raise ValueError("token_budget cannot be negative")
        if not 0 <= self.relationship <= 1:
            raise ValueError("relationship must be between 0 and 1")
        if self.recency_half_life_days <= 0:
            raise ValueError("recency_half_life_days must be positive")
        if not 0 <= self.forget_below <= 1:
            raise ValueError("forget_below must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class RetrievedMemory:
    memory: Memory
    score: float
    token_cost: int
    source_kind: str
    source_id: UUID


class MemoryService:
    """Forms only sourced memories and retrieves them within a context budget."""

    def __init__(self, unit_of_work_factory: Callable[[], UnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def form(self, run_id: UUID, formation: MemoryFormation) -> Memory:
        _require_aware(formation.experienced_at, "experienced_at")
        if not formation.content.strip():
            raise ValueError("memory content cannot be empty")
        for name, value in (
            ("confidence", formation.confidence),
            ("salience", formation.salience),
            ("plot_importance", formation.plot_importance),
        ):
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
        event_id = (
            EventId(formation.source_id)
            if formation.source_kind is MemorySourceKind.WITNESSED_EVENT
            else None
        )
        claim_id = (
            ClaimId(formation.source_id)
            if formation.source_kind is MemorySourceKind.COMMUNICATED_CLAIM
            else None
        )
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.memories.find_by_source(
                run_id,
                formation.character_id,
                event_id=event_id,
                claim_id=claim_id,
            )
            if existing is not None:
                return existing
            memory = Memory(
                id=MemoryId(uuid4()),
                character_id=formation.character_id,
                content=formation.content.strip(),
                source_event_id=event_id,
                source_claim_id=claim_id,
                experienced_at=formation.experienced_at,
                remembered_at=formation.experienced_at,
                confidence=formation.confidence,
                salience=formation.salience,
                plot_importance=formation.plot_importance,
                provenance=Provenance(
                    kind=(
                        ProvenanceKind.OBSERVED
                        if formation.source_kind is MemorySourceKind.WITNESSED_EVENT
                        else ProvenanceKind.REPORTED
                    ),
                    source_id=formation.source_id,
                    recorded_at=formation.experienced_at,
                    detail=formation.source_kind.value,
                ),
                lifecycle=Lifecycle(started_at=formation.experienced_at),
            )
            unit_of_work.memories.add(run_id, memory)
            unit_of_work.commit()
            return memory

    def retrieve(
        self, run_id: UUID, character_id: CharacterId, query: MemoryQuery
    ) -> tuple[RetrievedMemory, ...]:
        with self._unit_of_work_factory() as unit_of_work:
            memories = unit_of_work.memories.list_for_character(run_id, character_id)
        terms = _terms(query.text)
        ranked: list[RetrievedMemory] = []
        for memory in memories:
            age_days = max(0.0, (query.now - memory.remembered_at).total_seconds() / 86_400)
            recency = exp(-0.6931471805599453 * age_days / query.recency_half_life_days)
            if recency * memory.salience < query.forget_below:
                continue
            memory_terms = _terms(memory.content)
            relevance = len(terms & memory_terms) / len(terms) if terms else 0.0
            score = (
                0.35 * relevance
                + 0.25 * recency
                + 0.15 * memory.salience
                + 0.10 * query.relationship
                + 0.15 * memory.plot_importance
            )
            source_kind = "event" if memory.source_event_id is not None else "claim"
            source_id = memory.source_event_id or memory.source_claim_id
            assert source_id is not None
            ranked.append(
                RetrievedMemory(
                    memory=memory,
                    score=score,
                    token_cost=max(1, ceil(len(memory.content) / 4)),
                    source_kind=source_kind,
                    source_id=source_id,
                )
            )
        ranked.sort(
            key=lambda item: (
                -item.score,
                -item.memory.remembered_at.timestamp(),
                str(item.memory.id),
            )
        )
        selected: list[RetrievedMemory] = []
        remaining = query.token_budget
        for item in ranked:
            if item.token_cost <= remaining:
                selected.append(item)
                remaining -= item.token_cost
        return tuple(selected)

    def summarize(self, retrieved: tuple[RetrievedMemory, ...]) -> str:
        """Return a compact inspectable summary without erasing event/claim sourcing."""
        return "\n".join(
            f"- [{item.source_kind}:{item.source_id}] {item.memory.content}" for item in retrieved
        )


def _terms(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.casefold()))
