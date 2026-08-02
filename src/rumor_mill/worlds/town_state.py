"""Spoiler-safe queries over authored town geography and routines."""

from datetime import time

from pydantic import BaseModel, ConfigDict

from rumor_mill.engine.domain import Visibility
from rumor_mill.worlds.authoring import WorldDefinition


class PublicPresence(BaseModel):
    """Public explanation of one character's scheduled whereabouts."""

    model_config = ConfigDict(frozen=True)

    character_id: str
    character_name: str
    location_id: str
    location_name: str
    activity: str


class TownState:
    """Query authored presence without exposing private or engine-only routines."""

    def __init__(self, world: WorldDefinition) -> None:
        self._world = world
        self._characters = {character.id: character for character in world.cast}
        self._locations = {location.id: location for location in world.locations}

    def public_presence(self, *, day: int, at: time) -> tuple[PublicPresence, ...]:
        self._validate_day(day)

        presences = []
        for routine in self._world.routines:
            if routine.visibility is not Visibility.PUBLIC:
                continue
            if day not in routine.days or not routine.start_time <= at < routine.end_time:
                continue
            character = self._characters[routine.character_id]
            location = self._locations[routine.location_id]
            presences.append(
                PublicPresence(
                    character_id=character.id,
                    character_name=character.name,
                    location_id=location.id,
                    location_name=location.name,
                    activity=routine.public_activity or routine.activity,
                )
            )
        return tuple(sorted(presences, key=lambda item: (item.location_name, item.character_name)))

    def public_presence_at(
        self, location_id: str, *, day: int, at: time
    ) -> tuple[PublicPresence, ...]:
        if location_id not in self._locations:
            raise KeyError(location_id)
        return tuple(
            item for item in self.public_presence(day=day, at=at) if item.location_id == location_id
        )

    def can_stage_scene(
        self, participant_ids: tuple[str, ...], *, location_id: str, day: int, at: time
    ) -> bool:
        """Return whether every participant is authored at the location at that time."""

        self._validate_day(day)
        if location_id not in self._locations:
            raise KeyError(location_id)
        if any(character_id not in self._characters for character_id in participant_ids):
            raise KeyError("unknown participant")
        scheduled = {
            routine.character_id
            for routine in self._world.routines
            if routine.location_id == location_id
            and day in routine.days
            and routine.start_time <= at < routine.end_time
        }
        return set(participant_ids) <= scheduled

    def travel_minutes(self, from_location_id: str, to_location_id: str) -> int | None:
        """Return a direct authored travel time, respecting one-way routes."""

        if from_location_id not in self._locations or to_location_id not in self._locations:
            raise KeyError("unknown location")
        for route in self._world.travel_routes:
            if (
                route.from_location_id == from_location_id
                and route.to_location_id == to_location_id
            ):
                return route.minutes
            if (
                route.bidirectional
                and route.from_location_id == to_location_id
                and route.to_location_id == from_location_id
            ):
                return route.minutes
        return None

    @staticmethod
    def _validate_day(day: int) -> None:
        if not 1 <= day <= 14:
            raise ValueError("day must be between 1 and 14")
