"""Narrative continuity checks that require a complete authored world."""

from collections import defaultdict, deque
from datetime import time

from rumor_mill.engine.domain import Visibility
from rumor_mill.worlds.authoring import AuthoredRoutine, WorldDefinition, WorldValidationIssue


def validate_continuity(world: WorldDefinition) -> tuple[WorldValidationIssue, ...]:
    """Return every actionable continuity defect in stable authoring order."""

    issues: list[WorldValidationIssue] = []
    issues.extend(_schedule_issues(world))
    issues.extend(_clue_issues(world))
    issues.extend(_disclosure_issues(world))
    issues.extend(_reachability_issues(world))
    return tuple(issues)


def _schedule_issues(world: WorldDefinition) -> list[WorldValidationIssue]:
    issues: list[WorldValidationIssue] = []
    routes: dict[tuple[str, str], int] = {}
    for route in world.travel_routes:
        routes[route.from_location_id, route.to_location_id] = route.minutes
        if route.bidirectional:
            routes[route.to_location_id, route.from_location_id] = route.minutes
    by_character_day: dict[tuple[str, int], list[tuple[int, AuthoredRoutine]]] = defaultdict(list)
    for index, routine in enumerate(world.routines):
        for day in routine.days:
            by_character_day[routine.character_id, day].append((index, routine))
    for (character_id, day), entries in sorted(by_character_day.items()):
        entries.sort(key=lambda item: item[1].start_time)
        for (left_index, left), (right_index, right) in zip(entries, entries[1:], strict=False):
            del left_index
            end = _minute(left.end_time)
            start = _minute(right.start_time)
            if start < end:
                message = f"{character_id} has overlapping routines on day {day}"
            else:
                required = routes.get(
                    (left.location_id, right.location_id),
                    0 if left.location_id == right.location_id else None,
                )
                if required is None:
                    message = (
                        f"{character_id} has no travel route between consecutive routines "
                        f"on day {day}"
                    )
                elif start - end < required:
                    message = (
                        f"{character_id} has {start - end} travel minutes but requires "
                        f"{required} on day {day}"
                    )
                else:
                    continue
            issues.append(WorldValidationIssue(field=f"$.routines[{right_index}]", message=message))
    return issues


def _minute(value: time) -> int:
    return value.hour * 60 + value.minute


def _clue_issues(world: WorldDefinition) -> list[WorldValidationIssue]:
    placed = {clue_id for location in world.locations for clue_id in location.clue_ids}
    discovered = {clue_id for beat in world.beat_graph.beats for clue_id in beat.discovers_clue_ids}
    return [
        WorldValidationIssue(
            field=f"$.clues[{index}].id",
            message=f"orphan clue '{clue.id}' is neither placed nor discovered by a beat",
        )
        for index, clue in enumerate(world.clues)
        if clue.id not in placed | discovered
    ]


def _disclosure_issues(world: WorldDefinition) -> list[WorldValidationIssue]:
    issues: list[WorldValidationIssue] = []
    for index, secret in enumerate(world.secrets):
        if secret.visibility is not Visibility.ENGINE_ONLY:
            issues.append(
                WorldValidationIssue(
                    field=f"$.secrets[{index}].visibility",
                    message=f"disclosure leak: secret '{secret.id}' must be engine_only",
                )
            )
        if set(secret.known_by_ids) - set(secret.holder_ids):
            issues.append(
                WorldValidationIssue(
                    field=f"$.secrets[{index}].known_by_ids",
                    message="disclosure leak: known_by_ids must be included in holder_ids",
                )
            )
    clue_by_id = {clue.id: clue for clue in world.clues}
    for index, location in enumerate(world.locations):
        leaked = [
            clue_id
            for clue_id in location.clue_ids
            if clue_id in clue_by_id and clue_by_id[clue_id].visibility is Visibility.PUBLIC
        ]
        if leaked:
            issues.append(
                WorldValidationIssue(
                    field=f"$.locations[{index}].clue_ids",
                    message=f"disclosure leak: undiscovered clues are public: {', '.join(leaked)}",
                )
            )
    return issues


def _reachability_issues(world: WorldDefinition) -> list[WorldValidationIssue]:
    dependents: dict[str, list[str]] = defaultdict(list)
    for beat in world.beat_graph.beats:
        for dependency in beat.depends_on:
            dependents[dependency].append(beat.id)
    reachable = set(world.beat_graph.entry_beat_ids)
    queue = deque(world.beat_graph.entry_beat_ids)
    while queue:
        for beat_id in dependents[queue.popleft()]:
            if beat_id not in reachable:
                reachable.add(beat_id)
                queue.append(beat_id)
    return [
        WorldValidationIssue(
            field=f"$.beat_graph.beats[{index}].id",
            message=f"required beat '{beat.id}' is unreachable from an entry beat",
        )
        for index, beat in enumerate(world.beat_graph.beats)
        if beat.id not in reachable
    ]
