"""Continuity validation and reproducible world-seeding tests."""

import json
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from rumor_mill.adapters.persistence.models import Base, RunModel, WorldModel
from rumor_mill.worlds import WorldDefinition, load_world, validate_continuity
from rumor_mill.worlds.seeding import main, smoke_transcript, validate_and_seed

FIXTURE = Path(__file__).parent / "fixtures" / "worlds" / "minimal.json"
LIGHTHOUSE = Path(__file__).parents[1] / "docs" / "worlds" / "lighthouse" / "world.json"


def lighthouse_payload() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(LIGHTHOUSE.read_text(encoding="utf-8")))


def world_with(payload: dict[str, Any]) -> WorldDefinition:
    return WorldDefinition.model_validate(payload)


def test_complete_lighthouse_world_passes_continuity_validation() -> None:
    world = load_world(LIGHTHOUSE)

    assert world.metadata.id == "lighthouse"
    assert len(world.cast) == 7
    assert validate_continuity(world) == ()


def test_validator_catches_impossible_schedule_and_orphan_clue() -> None:
    payload = lighthouse_payload()
    payload["clues"].append(
        {"id": "orphan", "name": "Orphan", "description": "No placement or beat."}
    )
    payload["routines"].append(
        {
            "id": "mara-overlap",
            "character_id": "mara",
            "location_id": "widows-steps",
            "days": [1],
            "start_time": "08:00",
            "end_time": "09:00",
            "activity": "An impossible simultaneous search.",
        }
    )

    messages = [issue.message for issue in validate_continuity(world_with(payload))]

    assert any("overlapping routines" in message for message in messages)
    assert any("orphan clue 'orphan'" in message for message in messages)


def test_validator_catches_disclosure_leak_and_unreachable_beat() -> None:
    payload = lighthouse_payload()
    payload["secrets"][0]["visibility"] = "public"
    payload["secrets"][1]["known_by_ids"] = ["june", "mara"]
    payload["clues"][0]["visibility"] = "public"
    payload["beat_graph"]["beats"].append(
        {
            "id": "detached-ending",
            "title": "Detached Ending",
            "summary": "A required beat with no path from the entry.",
            "character_ids": ["mara"],
            "location_id": "northlight",
        }
    )

    messages = [issue.message for issue in validate_continuity(world_with(payload))]

    assert any("disclosure leak" in message for message in messages)
    assert any("known_by_ids" in message for message in messages)
    assert any("undiscovered clues are public" in message for message in messages)
    assert any("required beat 'detached-ending' is unreachable" in message for message in messages)


def test_loader_catches_broken_clue_reference(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["locations"][0]["clue_ids"] = ["missing-clue"]
    path = tmp_path / "broken.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown clue id 'missing-clue'"):
        load_world(path)


def test_seed_command_is_reproducible_and_writes_multiday_transcript(tmp_path: Path) -> None:
    first_db = tmp_path / "first.sqlite"
    second_db = tmp_path / "second.sqlite"
    transcript = tmp_path / "review.md"

    first = validate_and_seed(
        LIGHTHOUSE, f"sqlite:///{first_db}", seed=60, transcript_path=transcript
    )
    second = validate_and_seed(LIGHTHOUSE, f"sqlite:///{second_db}", seed=60)

    assert (first.world_id, first.run_id, first.transcript) == (
        second.world_id,
        second.run_id,
        second.transcript,
    )
    assert "## Day 14" in transcript.read_text(encoding="utf-8")
    with Session(create_engine(f"sqlite:///{first_db}")) as session:
        world = session.scalar(select(WorldModel))
        run = session.scalar(select(RunModel))
        assert world is not None and world.id == first.world_id
        assert run is not None and run.id == first.run_id and run.seed == 60


def test_seed_rejects_nonempty_world_database(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'world.sqlite'}"
    validate_and_seed(LIGHTHOUSE, database_url, seed=60)

    with pytest.raises(ValueError, match="database is not empty"):
        validate_and_seed(LIGHTHOUSE, database_url, seed=60)


def test_seed_rejects_continuity_errors_before_touching_database(tmp_path: Path) -> None:
    payload = lighthouse_payload()
    payload["clues"].append({"id": "orphan", "name": "Orphan", "description": "Never used."})
    world_path = tmp_path / "invalid.json"
    world_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="continuity validation failed"):
        validate_and_seed(world_path, f"sqlite:///{tmp_path / 'unused.sqlite'}")


def test_schedule_validator_catches_missing_and_insufficient_travel() -> None:
    payload = lighthouse_payload()
    payload["travel_routes"][0]["bidirectional"] = False
    payload["routines"].extend(
        [
            {
                "id": "june-council",
                "character_id": "june",
                "location_id": "council-rooms",
                "days": [1],
                "start_time": "14:02",
                "end_time": "15:00",
                "activity": "Delivering the dispatch log.",
            },
            {
                "id": "june-cottage",
                "character_id": "june",
                "location_id": "orin-cottage",
                "days": [1],
                "start_time": "16:00",
                "end_time": "17:00",
                "activity": "Asking Orin about the old signal route.",
            },
        ]
    )

    messages = [issue.message for issue in validate_continuity(world_with(payload))]

    assert any("2 travel minutes but requires 5" in message for message in messages)
    assert any("no travel route" in message for message in messages)


def test_seed_without_schema_creation_and_cli_entrypoint(tmp_path: Path, capsys: Any) -> None:
    database = tmp_path / "prepared.sqlite"
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    engine.dispose()
    result = validate_and_seed(
        LIGHTHOUSE,
        f"sqlite:///{database}",
        seed=61,
        create_schema=False,
    )
    assert result.run_id

    cli_database = tmp_path / "cli.sqlite"
    transcript = tmp_path / "cli.md"
    assert (
        main(
            [
                str(LIGHTHOUSE),
                "--database-url",
                f"sqlite:///{cli_database}",
                "--seed",
                "62",
                "--transcript",
                str(transcript),
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["world_id"] and transcript.exists()


def test_smoke_transcript_changes_deterministically_with_seed() -> None:
    world = load_world(LIGHTHOUSE)

    assert smoke_transcript(world, 7) == smoke_transcript(world, 7)
    assert "Provider: deterministic-fake" in smoke_transcript(world, 8)


def test_reachability_handles_converging_dependency_paths() -> None:
    payload = lighthouse_payload()
    payload["beat_graph"]["beats"].insert(
        1,
        {
            "id": "parallel-inquiry",
            "title": "Parallel Inquiry",
            "summary": "A second inquiry path converges on the edited records.",
            "character_ids": ["june"],
            "location_id": "harbor-dispatch",
            "depends_on": ["dark-headland"],
        },
    )
    payload["beat_graph"]["beats"][3]["depends_on"].append("parallel-inquiry")

    assert validate_continuity(world_with(payload)) == ()
