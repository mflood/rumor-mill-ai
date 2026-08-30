"""Structured off-screen scene planning, generation, and transaction tests."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from pydantic import BaseModel, ValidationError
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from rumor_mill.adapters.persistence import (
    SqlAlchemyUnitOfWork,
    create_database_engine,
    create_session_factory,
    seed_run,
)
from rumor_mill.adapters.persistence.models import (
    ArtifactModel,
    ClaimModel,
    EventModel,
    MemoryModel,
    SceneModel,
)
from rumor_mill.adapters.providers import DeterministicFakeProvider
from rumor_mill.engine.domain import ArtifactKind, CharacterId, LocationId
from rumor_mill.engine.ports import GenerationResult, RunRecord, RunStatus, Usage, WorldRecord
from rumor_mill.engine.scene_generation import (
    ContextItem,
    PlotIntent,
    SceneGenerationService,
    ScenePlan,
    ScenePlanner,
    StructuredSceneOutput,
)

ROOT = Path(__file__).parents[1]
pytestmark = pytest.mark.integration
NOW = datetime(2026, 8, 2, 13, tzinfo=UTC)
DEFAULT_RUN_ID = UUID(int=2)


def uid(value: int) -> UUID:
    return UUID(int=value)


def character(value: int) -> CharacterId:
    return CharacterId(uid(value))


def location(value: int) -> LocationId:
    return LocationId(uid(value))


@pytest.fixture
def scene_database(
    tmp_path: Path,
) -> tuple[Engine, sessionmaker[Session], RunRecord]:
    url = f"sqlite:///{tmp_path / 'scenes.db'}"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    engine = create_database_engine(url)
    factory = create_session_factory(engine)
    world = WorldRecord(uid(1), "scene-world", 1, {}, NOW)
    run = RunRecord(uid(2), world.id, RunStatus.RUNNING, 42, NOW)
    seed_run(SqlAlchemyUnitOfWork(factory), world, run)
    return engine, factory, run


def plan(run_id: UUID = DEFAULT_RUN_ID) -> ScenePlan:
    return ScenePlan(
        run_id=run_id,
        scheduled_at=NOW,
        participant_ids=(character(10), character(11)),
        location_id=location(20),
        authored_location_id="northlight",
        goals=("Reveal the missing key",),
        constraints=("Do not reveal the culprit",),
        relevant_context=(ContextItem(content="A storm is approaching", salience=0.9),),
    )


def response(title: str = "The Key at Dusk") -> dict[str, Any]:
    return {
        "title": title,
        "duration_minutes": 8,
        "dialogue": [
            {"speaker_id": str(uid(10)), "text": "The key was here."},
        ],
        "actions": [
            {"actor_id": str(uid(11)), "description": "Searches the windowsill."},
            {"actor_id": None, "description": "Thunder rolls over the harbor."},
        ],
        "events": [
            {
                "summary": "Bea found salt where the key had been.",
                "participant_ids": [str(uid(10)), str(uid(11))],
                "visibility": "public",
            }
        ],
        "claims": [
            {
                "statement": "The thief arrived by sea.",
                "subject_ids": [str(uid(10))],
                "visibility": "participants",
            }
        ],
        "memories": [
            {
                "character_id": str(uid(10)),
                "content": "Salt lay beside the empty hook.",
                "confidence": 0.95,
                "source_event_index": 0,
            },
            {
                "character_id": str(uid(11)),
                "content": "Ada suspected someone came from the sea.",
                "confidence": 0.6,
                "source_claim_index": 0,
            },
        ],
        "relationship_changes": [
            {
                "source_character_id": str(uid(10)),
                "target_character_id": str(uid(11)),
                "trust_delta": 0.1,
                "reason": "They searched together.",
            }
        ],
        "presentation_hooks": [
            {
                "kind": "story_card",
                "title": "Salt on the Sill",
                "body": "A new clue appeared before the storm.",
                "event_indexes": [0],
                "claim_indexes": [0],
            }
        ],
    }


def test_planner_selects_cast_location_and_relevant_context() -> None:
    intent = PlotIntent(
        run_id=uid(2),
        scheduled_at=NOW,
        candidate_participant_ids=(character(10), character(11), character(12)),
        preferred_participant_ids=(character(11),),
        available_location_ids=(location(20), location(21)),
        preferred_location_id=location(21),
        goals=("Find the key",),
        constraints=("Keep the secret",),
        context=(
            ContextItem(content="global", salience=0.3),
            ContextItem(content="selected", character_ids=(character(11),), salience=0.8),
            ContextItem(content="place", location_id=location(21), salience=0.7),
            ContextItem(content="irrelevant", character_ids=(character(99),), salience=1),
        ),
    )

    result = ScenePlanner(max_participants=2, context_limit=2).plan(intent)

    assert result.participant_ids == (character(11), character(10))
    assert result.location_id == location(21)
    assert [item.content for item in result.relevant_context] == ["selected", "place"]


@pytest.mark.parametrize("kwargs", [{"max_participants": 0}, {"context_limit": -1}])
def test_planner_rejects_invalid_limits(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError, match="limits"):
        ScenePlanner(**kwargs)


def test_intent_validation_and_defaults() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        PlotIntent(
            run_id=uid(2),
            scheduled_at=NOW.replace(tzinfo=None),
            candidate_participant_ids=(character(10),),
            available_location_ids=(location(20),),
            goals=("goal",),
        )
    with pytest.raises(ValidationError, match="preferred participants"):
        PlotIntent(
            run_id=uid(2),
            scheduled_at=NOW,
            candidate_participant_ids=(character(10),),
            preferred_participant_ids=(character(99),),
            available_location_ids=(location(20),),
            goals=("goal",),
        )
    with pytest.raises(ValidationError, match="preferred location"):
        PlotIntent(
            run_id=uid(2),
            scheduled_at=NOW,
            candidate_participant_ids=(character(10),),
            available_location_ids=(location(20),),
            preferred_location_id=location(99),
            goals=("goal",),
        )
    intent = PlotIntent(
        run_id=uid(2),
        scheduled_at=NOW,
        candidate_participant_ids=(character(10),),
        available_location_ids=(location(20),),
        goals=("goal",),
    )
    result = ScenePlanner().plan(intent)
    assert result.participant_ids == (character(10),)
    assert result.location_id == location(20)


def test_output_rejects_bad_internal_references() -> None:
    invalid_memory = response()
    invalid_memory["memories"][0]["source_event_index"] = 3
    with pytest.raises(ValidationError, match="source_event_index"):
        StructuredSceneOutput.model_validate(invalid_memory)

    invalid_claim = response()
    invalid_claim["memories"][1]["source_claim_index"] = 3
    with pytest.raises(ValidationError, match="source_claim_index"):
        StructuredSceneOutput.model_validate(invalid_claim)

    invalid_event_hook = response()
    invalid_event_hook["presentation_hooks"][0]["event_indexes"] = [3]
    with pytest.raises(ValidationError, match="event index"):
        StructuredSceneOutput.model_validate(invalid_event_hook)

    invalid_claim_hook = response()
    invalid_claim_hook["presentation_hooks"][0]["claim_indexes"] = [3]
    with pytest.raises(ValidationError, match="claim index"):
        StructuredSceneOutput.model_validate(invalid_claim_hook)


def test_nested_output_contracts_reject_ambiguous_sources_and_self_relationship() -> None:
    missing_source = response()
    missing_source["memories"][0].pop("source_event_index")
    with pytest.raises(ValidationError, match="exactly one"):
        StructuredSceneOutput.model_validate(missing_source)

    self_relationship = response()
    self_relationship["relationship_changes"][0]["target_character_id"] = str(uid(10))
    with pytest.raises(ValidationError, match="distinct"):
        StructuredSceneOutput.model_validate(self_relationship)


def test_generation_commits_and_round_trips_every_consequence(
    scene_database: tuple[Engine, sessionmaker[Session], RunRecord],
) -> None:
    engine, factory, run = scene_database
    provider = DeterministicFakeProvider({"off_screen_scene": response()})
    service = SceneGenerationService(provider, lambda: SqlAlchemyUnitOfWork(factory))

    first = service.generate(plan(run.id))
    second = service.generate(plan(run.id))

    assert first.scene.title == "The Key at Dusk"
    assert len(first.events) == 1
    assert len(first.claims) == 1
    assert len(first.memories) == 2
    assert first.artifacts[0].kind is ArtifactKind.STORY_CARD
    assert first.artifacts[0].location_id == "northlight"
    assert first.generation["provider"] == "fake"
    assert first.generation["request_id"] == "fake:off_screen_scene"
    assert first.generation["output"]["relationship_changes"][0]["trust_delta"] == 0.1

    with SqlAlchemyUnitOfWork(factory) as unit_of_work:
        stored = unit_of_work.scenes.get(first.scene.id)
        assert stored == first
        assert unit_of_work.scenes.get(uid(999)) is None

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(SceneModel)) == 2
        assert session.scalar(select(func.count()).select_from(EventModel)) == 2
        assert session.scalar(select(func.count()).select_from(ClaimModel)) == 2
        assert session.scalar(select(func.count()).select_from(MemoryModel)) == 4
        assert session.scalar(select(func.count()).select_from(ArtifactModel)) == 2
        assert session.scalar(select(func.max(SceneModel.sequence))) == 1
        assert session.scalar(select(func.max(EventModel.sequence))) == 1
    assert second.scene.id != first.scene.id
    engine.dispose()


def test_invalid_provider_output_is_rejected_without_partial_mutation(
    scene_database: tuple[Engine, sessionmaker[Session], RunRecord],
) -> None:
    engine, factory, run = scene_database
    invalid = response()
    invalid["events"] = []
    service = SceneGenerationService(
        DeterministicFakeProvider({"off_screen_scene": invalid}),
        lambda: SqlAlchemyUnitOfWork(factory),
    )

    with pytest.raises(ValidationError):
        service.generate(plan(run.id))
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(SceneModel)) == 0
        assert session.scalar(select(func.count()).select_from(EventModel)) == 0
    engine.dispose()


def test_generated_characters_must_be_in_plan(
    scene_database: tuple[Engine, sessionmaker[Session], RunRecord],
) -> None:
    engine, factory, run = scene_database
    outside = response()
    outside["dialogue"][0]["speaker_id"] = str(uid(99))
    service = SceneGenerationService(
        DeterministicFakeProvider({"off_screen_scene": outside}),
        lambda: SqlAlchemyUnitOfWork(factory),
    )

    with pytest.raises(ValueError, match="outside the plan"):
        service.generate(plan(run.id))
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(SceneModel)) == 0
    engine.dispose()


def test_generation_rejects_missing_run(
    scene_database: tuple[Engine, sessionmaker[Session], RunRecord],
) -> None:
    engine, factory, _ = scene_database
    service = SceneGenerationService(
        DeterministicFakeProvider({"off_screen_scene": response()}),
        lambda: SqlAlchemyUnitOfWork(factory),
    )
    with pytest.raises(LookupError, match="does not exist"):
        service.generate(plan(uid(999)))
    engine.dispose()


def test_generation_rejects_unexpected_provider_model(
    scene_database: tuple[Engine, sessionmaker[Session], RunRecord],
) -> None:
    engine, factory, run = scene_database

    class OtherOutput(BaseModel):
        value: str

    class WrongProvider:
        def generate(self, request):  # type: ignore[no-untyped-def]
            del request
            return GenerationResult(
                data=OtherOutput(value="wrong"),
                usage=Usage(0, 0, 0),
                provider="wrong",
                model="wrong",
                request_id="wrong",
            )

        def stream(self, request):  # type: ignore[no-untyped-def]
            del request
            return iter(())

    service = SceneGenerationService(WrongProvider(), lambda: SqlAlchemyUnitOfWork(factory))
    with pytest.raises(TypeError, match="unexpected"):
        service.generate(plan(run.id))
    engine.dispose()
