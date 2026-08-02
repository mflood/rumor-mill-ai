"""Per-character belief, evidence, contradiction, and trace tests."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from rumor_mill.adapters.persistence import (
    SqlAlchemyUnitOfWork,
    create_database_engine,
    create_session_factory,
)
from rumor_mill.adapters.persistence.models import Base
from rumor_mill.engine.beliefs import BeliefService, EvidenceInput
from rumor_mill.engine.domain import (
    Belief,
    BeliefRule,
    BeliefState,
    CharacterId,
    ClaimId,
    EventId,
    EvidenceStance,
    MemoryId,
)

NOW = datetime(2026, 8, 2, 12, tzinfo=UTC)
RUN_ID = UUID(int=1)
CLAIM = ClaimId(UUID(int=2))
ADA = CharacterId(UUID(int=3))
BEA = CharacterId(UUID(int=4))


@pytest.fixture
def belief_service(tmp_path: Path) -> Iterator[BeliefService]:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'beliefs.db'}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    yield BeliefService(lambda: SqlAlchemyUnitOfWork(factory))
    engine.dispose()


def test_two_characters_can_hold_incompatible_beliefs_about_one_event(
    belief_service: BeliefService,
) -> None:
    ada = belief_service.consider(
        RUN_ID,
        ADA,
        CLAIM,
        EvidenceInput(
            rule=BeliefRule.DIRECT_OBSERVATION,
            stance=EvidenceStance.SUPPORTS,
            strength=0.9,
            source_event_id=EventId(UUID(int=10)),
            occurred_at=NOW,
        ),
    )
    bea = belief_service.consider(
        RUN_ID,
        BEA,
        CLAIM,
        EvidenceInput(
            rule=BeliefRule.DIRECT_OBSERVATION,
            stance=EvidenceStance.REFUTES,
            strength=0.9,
            source_event_id=EventId(UUID(int=11)),
            occurred_at=NOW,
        ),
    )

    assert ada.confidence == 0.95
    assert bea.confidence == 0.05
    assert ada.claim_id == bea.claim_id
    assert ada.character_id != bea.character_id


def test_testimony_denial_correction_and_contradiction_are_traced(
    belief_service: BeliefService,
) -> None:
    testimony = belief_service.consider(
        RUN_ID,
        ADA,
        CLAIM,
        EvidenceInput(
            rule=BeliefRule.TESTIMONY,
            stance=EvidenceStance.SUPPORTS,
            strength=0.8,
            source_memory_id=MemoryId(UUID(int=20)),
            source_character_id=BEA,
            source_reliability=0.5,
            occurred_at=NOW,
        ),
    )
    denied = belief_service.consider(
        RUN_ID,
        ADA,
        CLAIM,
        EvidenceInput(
            rule=BeliefRule.DENIAL,
            stance=EvidenceStance.REFUTES,
            strength=0.75,
            source_memory_id=MemoryId(UUID(int=21)),
            source_character_id=BEA,
            source_reliability=0.8,
            occurred_at=NOW + timedelta(minutes=1),
        ),
    )
    corrected = belief_service.consider(
        RUN_ID,
        ADA,
        CLAIM,
        EvidenceInput(
            rule=BeliefRule.CORRECTION,
            stance=EvidenceStance.SUPPORTS,
            strength=1.0,
            source_memory_id=MemoryId(UUID(int=22)),
            source_character_id=BEA,
            source_reliability=0.8,
            occurred_at=NOW + timedelta(minutes=2),
        ),
    )

    assert testimony.confidence == 0.7
    assert denied.state is BeliefState.UNRESOLVED_CONTRADICTION
    assert corrected.confidence > denied.confidence
    assert len(corrected.supporting_evidence_ids) == 2
    assert len(corrected.conflicting_evidence_ids) == 1
    assert [update.rule for update in corrected.update_history] == [
        BeliefRule.TESTIMONY,
        BeliefRule.DENIAL,
        BeliefRule.CORRECTION,
    ]
    assert "remain unresolved" in corrected.update_history[-1].explanation
    with belief_service._unit_of_work_factory() as unit_of_work:
        evidence = unit_of_work.beliefs.list_evidence(RUN_ID, corrected)
    assert [item.id for item in evidence] == list(corrected.evidence_ids)
    assert evidence[0].source_character_id == BEA

    empty = corrected.model_copy(
        update={
            "evidence_ids": (),
            "supporting_evidence_ids": (),
            "conflicting_evidence_ids": (),
            "state": BeliefState.SETTLED,
        }
    )
    with belief_service._unit_of_work_factory() as unit_of_work:
        assert unit_of_work.beliefs.list_evidence(RUN_ID, empty) == ()


def test_ambiguous_evidence_preserves_confidence(belief_service: BeliefService) -> None:
    belief = belief_service.consider(
        RUN_ID,
        ADA,
        CLAIM,
        EvidenceInput(
            rule=BeliefRule.DIRECT_OBSERVATION,
            stance=EvidenceStance.AMBIGUOUS,
            strength=0.7,
            source_event_id=EventId(UUID(int=23)),
            occurred_at=NOW,
        ),
    )
    assert belief.confidence == 0.5


@pytest.mark.parametrize(
    ("values", "message"),
    [
        (
            {
                "rule": BeliefRule.TESTIMONY,
                "stance": EvidenceStance.SUPPORTS,
                "strength": 0.5,
                "source_memory_id": MemoryId(UUID(int=29)),
                "source_event_id": EventId(UUID(int=30)),
                "source_character_id": BEA,
                "occurred_at": NOW,
            },
            "exactly one",
        ),
        (
            {
                "rule": BeliefRule.DIRECT_OBSERVATION,
                "stance": EvidenceStance.SUPPORTS,
                "strength": 1.1,
                "source_event_id": EventId(UUID(int=30)),
                "occurred_at": NOW,
            },
            "strength must be between",
        ),
        (
            {
                "rule": BeliefRule.DIRECT_OBSERVATION,
                "stance": EvidenceStance.SUPPORTS,
                "strength": 0.5,
                "source_memory_id": MemoryId(UUID(int=30)),
                "occurred_at": NOW,
            },
            "direct observation requires an event",
        ),
        (
            {
                "rule": BeliefRule.TESTIMONY,
                "stance": EvidenceStance.SUPPORTS,
                "strength": 0.5,
                "source_event_id": EventId(UUID(int=30)),
                "occurred_at": NOW,
            },
            "requires a memory and character",
        ),
        (
            {
                "rule": BeliefRule.DENIAL,
                "stance": EvidenceStance.SUPPORTS,
                "strength": 0.5,
                "source_memory_id": MemoryId(UUID(int=31)),
                "source_character_id": BEA,
                "occurred_at": NOW,
            },
            "denial must refute",
        ),
    ],
)
def test_rejects_invalid_rule_sources(values: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        EvidenceInput(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {"supporting_evidence_ids": (UUID(int=1), UUID(int=1))},
            "must be unique",
        ),
        (
            {"supporting_evidence_ids": (), "conflicting_evidence_ids": (UUID(int=2),)},
            "all evidence must be classified",
        ),
        (
            {
                "evidence_ids": (),
                "supporting_evidence_ids": (),
                "state": BeliefState.UNRESOLVED_CONTRADICTION,
            },
            "requires evidence on both sides",
        ),
    ],
)
def test_belief_rejects_invalid_evidence_classification(
    belief_service: BeliefService, changes: dict[str, object], message: str
) -> None:
    valid = belief_service.consider(
        RUN_ID,
        ADA,
        CLAIM,
        EvidenceInput(
            rule=BeliefRule.DIRECT_OBSERVATION,
            stance=EvidenceStance.SUPPORTS,
            strength=0.5,
            source_event_id=EventId(UUID(int=40)),
            occurred_at=NOW,
        ),
    ).model_dump()
    valid.update(changes)
    with pytest.raises(ValidationError, match=message):
        Belief.model_validate(valid)
