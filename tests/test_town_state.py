"""Tests for spoiler-safe authored town-state queries."""

from datetime import time

import pytest

from rumor_mill.worlds import TownState, WorldDefinition


def world_with_routines() -> WorldDefinition:
    return WorldDefinition.model_validate(
        {
            "schema_version": 1,
            "metadata": {
                "id": "test-town",
                "title": "Test Town",
                "summary": "A small test town.",
                "author": "Tests",
                "content_rating": "Teen",
            },
            "cast": [
                {
                    "id": "ada",
                    "name": "Ada",
                    "description": "A courier.",
                    "home_location_id": "archive",
                },
                {"id": "bea", "name": "Bea", "description": "An archivist."},
            ],
            "locations": [
                {"id": "market", "name": "Market", "description": "Public square."},
                {"id": "archive", "name": "Archive", "description": "Records room."},
            ],
            "truth": [{"id": "opening", "statement": "The market opened."}],
            "beat_graph": {
                "entry_beat_ids": ["opening"],
                "beats": [
                    {
                        "id": "opening",
                        "title": "Opening",
                        "summary": "The market opens.",
                        "character_ids": ["ada"],
                        "location_id": "market",
                    }
                ],
            },
            "routines": [
                {
                    "id": "ada-round",
                    "character_id": "ada",
                    "location_id": "market",
                    "days": [1],
                    "start_time": "07:00",
                    "end_time": "09:00",
                    "activity": "Carrying a sealed archive parcel.",
                    "public_activity": "Making deliveries.",
                },
                {
                    "id": "bea-private",
                    "character_id": "bea",
                    "location_id": "archive",
                    "days": [1],
                    "start_time": "07:00",
                    "end_time": "09:00",
                    "activity": "Hiding a key.",
                    "visibility": "engine_only",
                },
            ],
            "travel_routes": [
                {
                    "id": "market-archive",
                    "from_location_id": "market",
                    "to_location_id": "archive",
                    "minutes": 3,
                }
            ],
        }
    )


def test_public_presence_explains_whereabouts_without_private_activity() -> None:
    state = TownState(world_with_routines())

    presence = state.public_presence(day=1, at=time(8))

    assert len(presence) == 1
    assert presence[0].character_name == "Ada"
    assert presence[0].activity == "Making deliveries."


def test_presence_respects_half_open_windows_and_location_filter() -> None:
    state = TownState(world_with_routines())

    assert state.public_presence_at("market", day=1, at=time(7))[0].character_id == "ada"
    assert state.public_presence(day=1, at=time(9)) == ()
    assert state.public_presence(day=2, at=time(8)) == ()


@pytest.mark.parametrize(
    ("at", "expected_location"),
    [
        (time(6, 59), None),
        (time(7), "market"),
        (time(8, 59), "market"),
        (time(9), None),
    ],
)
def test_character_location_uses_half_open_routines_not_home(
    at: time, expected_location: str | None
) -> None:
    location = TownState(world_with_routines()).character_location_state("ada", day=1, at=at)

    assert location.home_location_id == "archive"
    assert location.current_location_id == expected_location
    assert location.publicly_present is (expected_location is not None)


def test_private_routine_is_known_without_claiming_public_presence_or_home() -> None:
    location = TownState(world_with_routines()).character_location_state("bea", day=1, at=time(8))

    assert location.home_location_id is None
    assert location.current_location_id == "archive"
    assert location.publicly_present is False


def test_presence_rejects_unknown_locations_and_days() -> None:
    state = TownState(world_with_routines())

    with pytest.raises(ValueError, match="day must be between 1 and 14"):
        state.public_presence(day=0, at=time(8))
    with pytest.raises(KeyError, match="missing"):
        state.public_presence_at("missing", day=1, at=time(8))


def test_schedule_and_routes_constrain_scene_planning() -> None:
    state = TownState(world_with_routines())

    assert state.can_stage_scene(("ada",), location_id="market", day=1, at=time(8))
    assert not state.can_stage_scene(("ada", "bea"), location_id="market", day=1, at=time(8))
    assert state.travel_minutes("market", "archive") == 3
    assert state.travel_minutes("archive", "market") == 3
    assert state.travel_minutes("market", "market") is None

    with pytest.raises(KeyError, match="unknown participant"):
        state.can_stage_scene(("missing",), location_id="market", day=1, at=time(8))
    with pytest.raises(KeyError, match="missing"):
        state.can_stage_scene(("ada",), location_id="missing", day=1, at=time(8))
    with pytest.raises(KeyError, match="unknown location"):
        state.travel_minutes("missing", "market")
