"""Spoiler-safe queries over authored town geography and routines."""

from datetime import time

from pydantic import BaseModel, ConfigDict

from rumor_mill.engine.domain import Visibility
from rumor_mill.worlds.authoring import AuthoredRoutine, WorldDefinition


class PublicPresence(BaseModel):
    """Public explanation of one character's scheduled whereabouts."""

    model_config = ConfigDict(frozen=True)

    character_id: str
    character_name: str
    location_id: str
    location_name: str
    activity: str


class CharacterLocationState(BaseModel):
    """Authoritative authored whereabouts, kept distinct from residence and visibility."""

    model_config = ConfigDict(frozen=True)

    character_id: str
    home_location_id: str | None
    home_location_name: str | None
    current_location_id: str | None
    current_location_name: str | None
    publicly_present: bool


class TownState:
    """Query authored presence through visibility-appropriate state snapshots."""

    def __init__(self, world: WorldDefinition) -> None:
        self._world = world
        self._characters = {character.id: character for character in world.cast}
        self._locations = {location.id: location for location in world.locations}

    def public_presence(self, *, day: int, at: time) -> tuple[PublicPresence, ...]:
        presences = []
        for routine in self._active_routines(day=day, at=at):
            if routine.visibility is not Visibility.PUBLIC:
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

    def character_location_state(
        self, character_id: str, *, day: int, at: time
    ) -> CharacterLocationState:
        """Resolve current location from active routines, never from a character's home.

        Routine windows are half-open: the start time is active and the end time is not.
        A routine of any visibility is authoritative for the participating character's private
        context, while ``publicly_present`` is true only for an active public routine.
        """

        if character_id not in self._characters:
            raise KeyError(character_id)
        character = self._characters[character_id]
        active = tuple(
            routine
            for routine in self._active_routines(day=day, at=at)
            if routine.character_id == character_id
        )
        active_location_ids = {routine.location_id for routine in active}
        if len(active_location_ids) > 1:
            raise ValueError(f"character {character_id!r} has ambiguous current location")
        current_location_id = next(iter(active_location_ids), None)
        current_location = (
            self._locations[current_location_id] if current_location_id is not None else None
        )
        home_location = (
            self._locations[character.home_location_id]
            if character.home_location_id is not None
            else None
        )
        return CharacterLocationState(
            character_id=character.id,
            home_location_id=home_location.id if home_location is not None else None,
            home_location_name=home_location.name if home_location is not None else None,
            current_location_id=current_location.id if current_location is not None else None,
            current_location_name=current_location.name if current_location is not None else None,
            publicly_present=any(routine.visibility is Visibility.PUBLIC for routine in active),
        )

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

    def _active_routines(self, *, day: int, at: time) -> tuple[AuthoredRoutine, ...]:
        """Return the shared authoritative set of active half-open routine windows."""

        self._validate_day(day)
        return tuple(
            routine
            for routine in self._world.routines
            if day in routine.days and routine.start_time <= at < routine.end_time
        )

    @staticmethod
    def _validate_day(day: int) -> None:
        if not 1 <= day <= 14:
            raise ValueError("day must be between 1 and 14")
