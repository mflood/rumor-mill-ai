"""Contract tests for canon, subjective state, and presentation schemas."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from rumor_mill.engine.domain import (
    ArtifactKind,
    Belief,
    Character,
    Claim,
    Event,
    Evidence,
    EvidenceStance,
    Lifecycle,
    LifecycleStatus,
    Location,
    Memory,
    PresentationArtifact,
    Provenance,
    ProvenanceKind,
    Relationship,
    RelationshipKind,
    Scene,
    Visibility,
)

NOW = datetime(2026, 8, 2, 12, tzinfo=UTC)


def uid(value: int) -> Any:
    return UUID(int=value)


def active_lifecycle() -> Lifecycle:
    return Lifecycle(started_at=NOW)


def authored_provenance() -> Provenance:
    return Provenance(kind=ProvenanceKind.AUTHORED, recorded_at=NOW)


def generated_provenance(source_id: int) -> Provenance:
    return Provenance(
        kind=ProvenanceKind.GENERATED,
        source_id=uid(source_id),
        recorded_at=NOW,
    )


@pytest.fixture
def representative_contracts() -> dict[str, Any]:
    location = Location(
        id=uid(1),
        name="Lantern Market",
        description="A covered market where everybody overhears something.",
        lifecycle=active_lifecycle(),
    )
    ada = Character(
        id=uid(2),
        name="Ada",
        description="An observant courier.",
        home_location_id=location.id,
        lifecycle=active_lifecycle(),
    )
    bea = Character(
        id=uid(3),
        name="Bea",
        description="The market's guarded archivist.",
        lifecycle=active_lifecycle(),
    )
    relationship = Relationship(
        id=uid(4),
        source_character_id=ada.id,
        target_character_id=bea.id,
        kind=RelationshipKind.FRIEND,
        began_at=NOW,
        lifecycle=active_lifecycle(),
    )
    event = Event(
        id=uid(5),
        occurred_at=NOW,
        summary="Ada saw Bea hide a brass key beneath the west stall.",
        participant_ids=(ada.id, bea.id),
        location_id=location.id,
        provenance=authored_provenance(),
        visibility=Visibility.ENGINE_ONLY,
        lifecycle=active_lifecycle(),
    )
    scene = Scene(
        id=uid(6),
        title="The Hidden Key",
        event_ids=(event.id,),
        starts_at=NOW,
        ends_at=NOW + timedelta(minutes=5),
        location_id=location.id,
        provenance=generated_provenance(5),
        lifecycle=active_lifecycle(),
    )
    memory = Memory(
        id=uid(7),
        character_id=ada.id,
        content="Bea hid a brass key under the west stall.",
        source_event_id=event.id,
        experienced_at=NOW,
        remembered_at=NOW + timedelta(minutes=1),
        confidence=0.95,
        provenance=Provenance(
            kind=ProvenanceKind.OBSERVED,
            source_id=event.id,
            recorded_at=NOW + timedelta(minutes=1),
        ),
        lifecycle=active_lifecycle(),
    )
    claim = Claim(
        id=uid(8),
        statement="Bea controls access to the old observatory.",
        subject_ids=(bea.id,),
        provenance=Provenance(
            kind=ProvenanceKind.INFERRED,
            source_id=memory.id,
            recorded_at=NOW + timedelta(minutes=2),
        ),
        visibility=Visibility.PRIVATE,
        lifecycle=active_lifecycle(),
    )
    evidence = Evidence(
        id=uid(9),
        claim_id=claim.id,
        stance=EvidenceStance.SUPPORTS,
        strength=0.7,
        source_memory_id=memory.id,
        provenance=Provenance(
            kind=ProvenanceKind.DERIVED,
            source_id=memory.id,
            recorded_at=NOW + timedelta(minutes=2),
        ),
        visibility=Visibility.PRIVATE,
        lifecycle=active_lifecycle(),
    )
    belief = Belief(
        id=uid(10),
        character_id=ada.id,
        claim_id=claim.id,
        confidence=0.7,
        evidence_ids=(evidence.id,),
        formed_at=NOW + timedelta(minutes=2),
        updated_at=NOW + timedelta(minutes=2),
        provenance=generated_provenance(9),
        lifecycle=active_lifecycle(),
    )
    artifact = PresentationArtifact(
        id=uid(11),
        kind=ArtifactKind.SCENE_PAGE,
        title=scene.title,
        body="Ada watched Bea glance around before hiding the key.",
        source_scene_ids=(scene.id,),
        source_event_ids=(event.id,),
        generated_at=NOW + timedelta(minutes=3),
        provenance=generated_provenance(6),
        lifecycle=active_lifecycle(),
    )
    return {
        "location": location,
        "ada": ada,
        "bea": bea,
        "relationship": relationship,
        "event": event,
        "scene": scene,
        "memory": memory,
        "claim": claim,
        "evidence": evidence,
        "belief": belief,
        "artifact": artifact,
    }


@pytest.mark.parametrize(
    "contract_name",
    [
        "location",
        "ada",
        "relationship",
        "event",
        "scene",
        "memory",
        "claim",
        "evidence",
        "belief",
        "artifact",
    ],
)
def test_representative_contracts_round_trip_json(
    representative_contracts: dict[str, Any], contract_name: str
) -> None:
    contract = representative_contracts[contract_name]

    restored = type(contract).model_validate_json(contract.model_dump_json())

    assert restored == contract
    assert restored.schema_version == 1


def test_schema_version_is_required_to_be_supported() -> None:
    with pytest.raises(ValidationError, match="Input should be 1"):
        Character.model_validate(
            {
                "schema_version": 2,
                "id": uid(1),
                "name": "Ada",
                "description": "Courier",
                "lifecycle": active_lifecycle(),
            }
        )


def test_contracts_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Location.model_validate(
            {
                "id": uid(1),
                "name": "Market",
                "description": "Busy",
                "lifecycle": active_lifecycle(),
                "tenant_id": "not-part-of-the-mvp",
            }
        )


def test_canon_is_immutable_through_all_contract_references(
    representative_contracts: dict[str, Any],
) -> None:
    event = representative_contracts["event"]
    memory = representative_contracts["memory"]
    artifact = representative_contracts["artifact"]

    with pytest.raises(ValidationError, match="Instance is frozen"):
        event.summary = "A belief tried to rewrite history."

    assert memory.source_event_id == event.id
    assert not hasattr(memory, "event")
    assert event.id in artifact.source_event_ids
    assert not hasattr(artifact, "events")


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (
            lambda: Provenance(
                kind=ProvenanceKind.OBSERVED,
                recorded_at=NOW,
            ),
            "non-authored provenance requires source_id",
        ),
        (
            lambda: Lifecycle(
                status=LifecycleStatus.RETRACTED,
                started_at=NOW,
            ),
            "inactive lifecycle requires ended_at",
        ),
        (
            lambda: Lifecycle(
                status=LifecycleStatus.SUPERSEDED,
                started_at=NOW,
                ended_at=NOW,
            ),
            "superseded lifecycle requires supersedes_id",
        ),
        (
            lambda: Lifecycle(
                started_at=NOW,
                ended_at=NOW + timedelta(minutes=1),
            ),
            "active lifecycle cannot have ended_at",
        ),
        (
            lambda: Lifecycle(
                status=LifecycleStatus.ARCHIVED,
                started_at=NOW,
                ended_at=NOW - timedelta(minutes=1),
            ),
            "ended_at cannot be before started_at",
        ),
        (
            lambda: Relationship(
                id=uid(1),
                source_character_id=uid(2),
                target_character_id=uid(2),
                kind=RelationshipKind.RIVAL,
                began_at=NOW,
                lifecycle=active_lifecycle(),
            ),
            "relationship endpoints must be different",
        ),
        (
            lambda: Event(
                id=uid(1),
                occurred_at=NOW,
                summary="Two copies of the same witness.",
                participant_ids=(uid(2), uid(2)),
                provenance=authored_provenance(),
                lifecycle=active_lifecycle(),
            ),
            "participant_ids must be unique",
        ),
        (
            lambda: Scene(
                id=uid(1),
                title="Backwards",
                event_ids=(uid(2),),
                starts_at=NOW,
                ends_at=NOW - timedelta(minutes=1),
                provenance=authored_provenance(),
                lifecycle=active_lifecycle(),
            ),
            "ends_at cannot be before starts_at",
        ),
        (
            lambda: Scene(
                id=uid(1),
                title="Repeated Event",
                event_ids=(uid(2), uid(2)),
                starts_at=NOW,
                ends_at=NOW,
                provenance=authored_provenance(),
                lifecycle=active_lifecycle(),
            ),
            "event_ids must be unique",
        ),
        (
            lambda: Evidence(
                id=uid(1),
                claim_id=uid(2),
                stance=EvidenceStance.AMBIGUOUS,
                strength=0.5,
                provenance=authored_provenance(),
                visibility=Visibility.PRIVATE,
                lifecycle=active_lifecycle(),
            ),
            "evidence requires exactly one",
        ),
        (
            lambda: Belief(
                id=uid(1),
                character_id=uid(2),
                claim_id=uid(3),
                confidence=0.5,
                formed_at=NOW,
                updated_at=NOW - timedelta(minutes=1),
                provenance=authored_provenance(),
                lifecycle=active_lifecycle(),
            ),
            "updated_at cannot be before formed_at",
        ),
        (
            lambda: Belief(
                id=uid(1),
                character_id=uid(2),
                claim_id=uid(3),
                confidence=0.5,
                evidence_ids=(uid(4), uid(4)),
                formed_at=NOW,
                updated_at=NOW,
                provenance=authored_provenance(),
                lifecycle=active_lifecycle(),
            ),
            "evidence_ids must be unique",
        ),
        (
            lambda: Memory(
                id=uid(1),
                character_id=uid(2),
                content="A memory from the future.",
                source_event_id=uid(3),
                experienced_at=NOW,
                remembered_at=NOW - timedelta(minutes=1),
                confidence=0.5,
                provenance=authored_provenance(),
                lifecycle=active_lifecycle(),
            ),
            "remembered_at cannot be before experienced_at",
        ),
        (
            lambda: Memory(
                id=uid(1),
                character_id=uid(2),
                content="A memory with competing sources.",
                source_event_id=uid(3),
                source_claim_id=uid(4),
                experienced_at=NOW,
                remembered_at=NOW,
                confidence=0.5,
                provenance=authored_provenance(),
                lifecycle=active_lifecycle(),
            ),
            "memory requires exactly one",
        ),
        (
            lambda: PresentationArtifact(
                id=uid(1),
                kind=ArtifactKind.STORY_CARD,
                title="Untethered",
                body="This has no domain source.",
                generated_at=NOW,
                provenance=authored_provenance(),
                lifecycle=active_lifecycle(),
            ),
            "requires at least one source",
        ),
        (
            lambda: PresentationArtifact(
                id=uid(1),
                kind=ArtifactKind.STORY_CARD,
                title="Repeated Source",
                body="The same source appears twice.",
                source_event_ids=(uid(2), uid(2)),
                generated_at=NOW,
                provenance=authored_provenance(),
                lifecycle=active_lifecycle(),
            ),
            "presentation source IDs must be unique",
        ),
    ],
)
def test_invalid_domain_states_are_rejected(factory: Any, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        factory()


def test_naive_timestamps_are_rejected() -> None:
    with pytest.raises(ValidationError, match="must include a timezone"):
        Lifecycle(started_at=datetime(2026, 8, 2, 12))


def test_confidence_is_bounded(representative_contracts: dict[str, Any]) -> None:
    belief = representative_contracts["belief"]

    with pytest.raises(ValidationError, match="less than or equal to 1"):
        Belief.model_validate({**belief.model_dump(), "confidence": 1.1})


def test_json_schema_forbids_extra_properties() -> None:
    schema = Event.model_json_schema()

    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"]["const"] == 1
