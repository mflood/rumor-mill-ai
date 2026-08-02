"""Tests for the versioned data-only world format."""

import json
from pathlib import Path
from typing import Any

import pytest

from rumor_mill.worlds import WorldDefinition, WorldLoadError, load_world

FIXTURE = Path(__file__).parent / "fixtures" / "worlds" / "minimal.json"


def fixture_payload() -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return payload


def write_world(tmp_path: Path, payload: Any) -> Path:
    path = tmp_path / "world.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_minimal_fixture_loads_and_round_trips() -> None:
    world = load_world(FIXTURE)

    assert world.schema_version == 1
    assert world.metadata.id == "lantern-market"
    assert [character.id for character in world.cast] == ["ada", "bea"]
    assert world.beat_graph.beats[1].depends_on == ("hidden-key",)
    assert WorldDefinition.model_validate_json(world.model_dump_json()) == world


def test_generated_schema_is_strict_and_versioned() -> None:
    schema = WorldDefinition.model_json_schema()

    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"]["const"] == 1
    assert {"metadata", "cast", "locations", "truth", "beat_graph"} <= set(schema["required"])


def test_loader_reports_file_and_nested_field_for_schema_error(tmp_path: Path) -> None:
    payload = fixture_payload()
    del payload["cast"][0]["name"]
    path = write_world(tmp_path, payload)

    with pytest.raises(WorldLoadError) as error:
        load_world(path)

    assert error.value.source == path
    assert error.value.issues[0].field == "$.cast[0].name"
    assert f"{path}:$.cast[0].name: Field required" in str(error.value)


def test_loader_rejects_unsupported_version(tmp_path: Path) -> None:
    payload = fixture_payload()
    payload["schema_version"] = 2
    path = write_world(tmp_path, payload)

    with pytest.raises(WorldLoadError, match=r"\$\.schema_version: Input should be 1"):
        load_world(path)


def test_loader_reports_malformed_json_location(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text('{"schema_version": 1,', encoding="utf-8")

    with pytest.raises(WorldLoadError) as error:
        load_world(path)

    assert error.value.issues[0].field == "line 1, column 22"
    assert "Expecting property name enclosed in double quotes" in str(error.value)


def test_loader_reports_unreadable_source(tmp_path: Path) -> None:
    path = tmp_path / "missing.json"

    with pytest.raises(WorldLoadError) as error:
        load_world(path)

    assert error.value.issues[0].field == "$"
    assert str(path) in str(error.value)


def test_loader_reports_all_cross_reference_failures(tmp_path: Path) -> None:
    payload = fixture_payload()
    payload["cast"][0]["home_location_id"] = "missing-home"
    payload["locations"][1]["parent_location_id"] = "missing-parent"
    payload["initial_relationships"][0]["source_character_id"] = "missing-source"
    payload["initial_relationships"][0]["target_character_id"] = "missing-target"
    payload["truth"][0]["character_ids"] = ["missing-truth-character"]
    payload["truth"][0]["location_ids"] = ["missing-truth-location"]
    payload["secrets"][0]["holder_ids"] = ["missing-holder"]
    payload["secrets"][0]["known_by_ids"] = ["missing-knower"]
    payload["secrets"][0]["truth_id"] = "missing-truth"
    payload["beat_graph"]["entry_beat_ids"] = ["missing-entry"]
    beat = payload["beat_graph"]["beats"][0]
    beat["character_ids"] = ["missing-beat-character"]
    beat["location_id"] = "missing-beat-location"
    beat["depends_on"] = ["missing-dependency"]
    beat["reveals_secret_ids"] = ["missing-secret"]
    beat["establishes_truth_ids"] = ["missing-beat-truth"]
    path = write_world(tmp_path, payload)

    with pytest.raises(WorldLoadError) as error:
        load_world(path)

    message = str(error.value)
    assert "$.cast[0].home_location_id: unknown location id 'missing-home'" in message
    assert "$.initial_relationships[0].source_character_id" in message
    assert "$.truth[0].character_ids[0]" in message
    assert "$.secrets[0].holder_ids[0]" in message
    assert "$.beat_graph.entry_beat_ids[0]" in message
    assert "$.beat_graph.beats[0].reveals_secret_ids[0]" in message


def test_loader_rejects_duplicate_ids_and_self_references(tmp_path: Path) -> None:
    payload = fixture_payload()
    payload["cast"][1]["id"] = "ada"
    payload["locations"][1]["id"] = "market"
    payload["locations"][1]["parent_location_id"] = "market"
    relationship = payload["initial_relationships"][0]
    relationship["target_character_id"] = relationship["source_character_id"]
    payload["beat_graph"]["beats"][1]["id"] = "hidden-key"
    path = write_world(tmp_path, payload)

    with pytest.raises(WorldLoadError) as error:
        load_world(path)

    message = str(error.value)
    assert "$.cast[1].id: duplicate id 'ada'" in message
    assert "$.locations[1].id: duplicate id 'market'" in message
    assert "location cannot contain itself" in message
    assert "relationship endpoints must be different" in message
    assert "$.beat_graph.beats[1].id: duplicate id 'hidden-key'" in message


def test_loader_rejects_beat_graph_cycle(tmp_path: Path) -> None:
    payload = fixture_payload()
    payload["beat_graph"]["beats"][0]["depends_on"] = ["quiet-question"]
    path = write_world(tmp_path, payload)

    with pytest.raises(WorldLoadError, match="beat graph contains a cycle"):
        load_world(path)


def test_loader_accepts_string_path(tmp_path: Path) -> None:
    path = write_world(tmp_path, fixture_payload())

    assert load_world(str(path)).metadata.id == "lantern-market"


def test_loader_accepts_locations_routines_and_travel_routes(tmp_path: Path) -> None:
    payload = fixture_payload()
    payload["locations"][0].update(
        {
            "purpose": "The public center of trade and encounter.",
            "atmosphere": "Warm lantern light under a rain-dark roof.",
            "access_rules": ["Open from 06:00 to 20:00."],
            "clue_ids": ["market-ledger"],
            "presentation_copy": "Lanterns glow above the morning stalls.",
        }
    )
    payload["routines"] = [
        {
            "id": "ada-morning-round",
            "character_id": "ada",
            "location_id": "market",
            "days": [1, 2, 3],
            "start_time": "07:00",
            "end_time": "09:00",
            "activity": "Delivering private archive parcels.",
            "public_activity": "Making the morning delivery round.",
        }
    ]
    payload["travel_routes"] = [
        {
            "id": "market-archive-stairs",
            "from_location_id": "market",
            "to_location_id": "archive",
            "minutes": 3,
            "access_rules": ["Archive key required after 17:00."],
        }
    ]

    world = load_world(write_world(tmp_path, payload))

    assert world.locations[0].clue_ids == ("market-ledger",)
    assert world.routines[0].start_time.isoformat() == "07:00:00"
    assert world.travel_routes[0].minutes == 3


def test_loader_rejects_invalid_routine_and_route_references(tmp_path: Path) -> None:
    payload = fixture_payload()
    payload["routines"] = [
        {
            "id": "lost-round",
            "character_id": "missing-character",
            "location_id": "missing-location",
            "days": [1],
            "start_time": "08:00",
            "end_time": "09:00",
            "activity": "Impossible round.",
        }
    ]
    payload["travel_routes"] = [
        {
            "id": "nowhere",
            "from_location_id": "market",
            "to_location_id": "market",
            "minutes": 1,
        }
    ]

    with pytest.raises(WorldLoadError) as error:
        load_world(write_world(tmp_path, payload))

    message = str(error.value)
    assert "unknown character id 'missing-character'" in message
    assert "unknown location id 'missing-location'" in message
    assert "travel route endpoints must be different" in message


@pytest.mark.parametrize(
    ("days", "start", "end", "expected"),
    [
        ([1], "09:00", "08:00", "start_time must be before end_time"),
        ([1, 1], "08:00", "09:00", "days must not contain duplicates"),
    ],
)
def test_loader_rejects_invalid_routine_windows(
    tmp_path: Path, days: list[int], start: str, end: str, expected: str
) -> None:
    payload = fixture_payload()
    payload["routines"] = [
        {
            "id": "invalid-round",
            "character_id": "ada",
            "location_id": "market",
            "days": days,
            "start_time": start,
            "end_time": end,
            "activity": "Invalid round.",
        }
    ]

    with pytest.raises(WorldLoadError, match=expected):
        load_world(write_world(tmp_path, payload))
