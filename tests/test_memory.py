"""Character memory formation and retrieval tests."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from rumor_mill.adapters.persistence import (
    SqlAlchemyUnitOfWork,
    create_database_engine,
    create_session_factory,
)
from rumor_mill.adapters.persistence.models import Base
from rumor_mill.engine.domain import CharacterId
from rumor_mill.engine.memory import (
    MemoryFormation,
    MemoryQuery,
    MemoryService,
    MemorySourceKind,
)

NOW = datetime(2026, 8, 2, 12, tzinfo=UTC)
RUN_ID = UUID(int=1)
ADA = CharacterId(UUID(int=2))


@pytest.fixture
def memory_service(tmp_path: Path) -> Iterator[MemoryService]:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'memory.db'}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    yield MemoryService(lambda: SqlAlchemyUnitOfWork(factory))
    engine.dispose()


def formation(
    source: int,
    content: str,
    *,
    kind: MemorySourceKind = MemorySourceKind.WITNESSED_EVENT,
    when: datetime = NOW,
    salience: float = 0.5,
    plot_importance: float = 0.0,
) -> MemoryFormation:
    return MemoryFormation(
        character_id=ADA,
        content=content,
        source_kind=kind,
        source_id=UUID(int=source),
        experienced_at=when,
        confidence=0.8,
        salience=salience,
        plot_importance=plot_importance,
    )


def test_forms_only_explicitly_sourced_memories_and_suppresses_duplicates(
    memory_service: MemoryService,
) -> None:
    witnessed = memory_service.form(RUN_ID, formation(10, "Ada saw the lighthouse go dark."))
    repeated = memory_service.form(RUN_ID, formation(10, "A conflicting duplicate."))
    reported = memory_service.form(
        RUN_ID,
        formation(
            11,
            "Bea said the keeper left early.",
            kind=MemorySourceKind.COMMUNICATED_CLAIM,
        ),
    )

    assert repeated == witnessed
    assert witnessed.source_event_id == UUID(int=10)
    assert witnessed.source_claim_id is None
    assert witnessed.provenance.kind.value == "observed"
    assert reported.source_claim_id == UUID(int=11)
    assert reported.source_event_id is None
    assert reported.provenance.kind.value == "reported"


def test_retrieval_ranks_five_factors_forgets_and_honors_budget(
    memory_service: MemoryService,
) -> None:
    relevant = memory_service.form(
        RUN_ID,
        formation(20, "The brass lighthouse key was hidden in the boathouse.", salience=1.0),
    )
    important = memory_service.form(
        RUN_ID,
        formation(21, "A storm damaged the harbor bell.", plot_importance=1.0),
    )
    memory_service.form(
        RUN_ID,
        formation(
            22,
            "An old gull landed on the roof.",
            when=NOW - timedelta(days=365),
            salience=0.1,
        ),
    )
    query = MemoryQuery(
        text="Where is the lighthouse key?",
        now=NOW,
        token_budget=100,
        relationship=0.8,
        recency_half_life_days=30,
    )

    retrieved = memory_service.retrieve(RUN_ID, ADA, query)

    assert [item.memory.id for item in retrieved] == [relevant.id, important.id]
    assert retrieved[0].score > retrieved[1].score
    assert memory_service.summarize(retrieved).splitlines()[0].startswith("- [event:")
    assert str(relevant.source_event_id) in memory_service.summarize(retrieved)

    exact_budget = retrieved[0].token_cost
    budgeted = memory_service.retrieve(
        RUN_ID,
        ADA,
        MemoryQuery(text=query.text, now=NOW, token_budget=exact_budget, relationship=0.8),
    )
    assert len(budgeted) == 1
    assert budgeted[0].memory.id == relevant.id


def test_empty_query_and_zero_budget_are_deterministic(memory_service: MemoryService) -> None:
    memory_service.form(RUN_ID, formation(30, "Short"))
    query = MemoryQuery(text="", now=NOW, token_budget=0)
    assert memory_service.retrieve(RUN_ID, ADA, query) == ()
    assert memory_service.summarize(()) == ""


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"content": "  "}, "content"),
        ({"confidence": -0.1}, "confidence"),
        ({"salience": 1.1}, "salience"),
        ({"plot_importance": 2.0}, "plot_importance"),
        ({"experienced_at": datetime(2026, 8, 2)}, "timezone"),
    ],
)
def test_rejects_invalid_formations(
    memory_service: MemoryService, changes: dict[str, object], message: str
) -> None:
    values = {
        "character_id": ADA,
        "content": "Valid memory",
        "source_kind": MemorySourceKind.WITNESSED_EVENT,
        "source_id": UUID(int=40),
        "experienced_at": NOW,
        "confidence": 0.5,
        "salience": 0.5,
        "plot_importance": 0.5,
    }
    values.update(changes)
    with pytest.raises(ValueError, match=message):
        memory_service.form(RUN_ID, MemoryFormation(**values))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"now": datetime(2026, 8, 2)}, "timezone"),
        ({"token_budget": -1}, "token_budget"),
        ({"relationship": 1.1}, "relationship"),
        ({"recency_half_life_days": 0}, "half_life"),
        ({"forget_below": -0.1}, "forget_below"),
    ],
)
def test_rejects_invalid_queries(changes: dict[str, object], message: str) -> None:
    values = {"text": "key", "now": NOW, "token_budget": 10}
    values.update(changes)
    with pytest.raises(ValueError, match=message):
        MemoryQuery(**values)  # type: ignore[arg-type]


def test_repository_requires_exactly_one_source(memory_service: MemoryService) -> None:
    with (
        memory_service._unit_of_work_factory() as unit_of_work,
        pytest.raises(ValueError, match="exactly one"),
    ):
        unit_of_work.memories.find_by_source(RUN_ID, ADA)
