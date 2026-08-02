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
