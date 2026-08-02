"""Versioned, data-only world-authoring contract and JSON loader."""

import json
from collections.abc import Iterable
from json import JSONDecodeError
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from rumor_mill.engine.domain import RelationshipKind, Visibility

Slug = Annotated[str, Field(pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$", max_length=80)]


class AuthoringModel(BaseModel):
    """Strict authoring value used to generate the versioned JSON Schema."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class WorldMetadata(AuthoringModel):
    id: Slug
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=2_000)
    author: str = Field(min_length=1, max_length=200)
    content_rating: str = Field(min_length=1, max_length=40)


class AuthoredCharacter(AuthoringModel):
    id: Slug
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=2_000)
    home_location_id: Slug | None = None


class AuthoredLocation(AuthoringModel):
    id: Slug
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=2_000)
    parent_location_id: Slug | None = None


class InitialRelationship(AuthoringModel):
    id: Slug
    source_character_id: Slug
    target_character_id: Slug
    kind: RelationshipKind
    visibility: Visibility = Visibility.PARTICIPANTS


class AuthoredTruth(AuthoringModel):
    id: Slug
    statement: str = Field(min_length=1, max_length=2_000)
    character_ids: tuple[Slug, ...] = ()
    location_ids: tuple[Slug, ...] = ()


class AuthoredSecret(AuthoringModel):
    id: Slug
    statement: str = Field(min_length=1, max_length=2_000)
    holder_ids: tuple[Slug, ...] = Field(min_length=1)
    known_by_ids: tuple[Slug, ...] = ()
    truth_id: Slug
    visibility: Visibility = Visibility.ENGINE_ONLY


class AuthoredBeat(AuthoringModel):
    id: Slug
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=2_000)
    character_ids: tuple[Slug, ...] = Field(min_length=1)
    location_id: Slug
    depends_on: tuple[Slug, ...] = ()
    reveals_secret_ids: tuple[Slug, ...] = ()
    establishes_truth_ids: tuple[Slug, ...] = ()


class BeatGraph(AuthoringModel):
    entry_beat_ids: tuple[Slug, ...] = Field(min_length=1)
    beats: tuple[AuthoredBeat, ...] = Field(min_length=1)


class WorldDefinition(AuthoringModel):
    """Complete v1 authored world, validated before runtime translation."""

    schema_version: Literal[1]
    metadata: WorldMetadata
    cast: tuple[AuthoredCharacter, ...] = Field(min_length=1)
    locations: tuple[AuthoredLocation, ...] = Field(min_length=1)
    initial_relationships: tuple[InitialRelationship, ...] = ()
    secrets: tuple[AuthoredSecret, ...] = ()
    truth: tuple[AuthoredTruth, ...] = Field(min_length=1)
    beat_graph: BeatGraph

    @model_validator(mode="after")
    def validate_world_references(self) -> Self:
        issues = _reference_issues(self)
        if issues:
            details = "; ".join(f"{issue.field}: {issue.message}" for issue in issues)
            raise ValueError(f"invalid world references: {details}")
        return self


class WorldValidationIssue(AuthoringModel):
    """One author-actionable validation failure."""

    field: str
    message: str


class WorldLoadError(ValueError):
    """Validation failure that always names the source file and field."""

    def __init__(self, source: Path, issues: Iterable[WorldValidationIssue]) -> None:
        self.source = source
        self.issues = tuple(issues)
        detail = "\n".join(f"{source}:{issue.field}: {issue.message}" for issue in self.issues)
        super().__init__(detail)


def load_world(path: str | Path) -> WorldDefinition:
    """Load and fully validate a versioned JSON world definition."""

    source = Path(path)
    try:
        raw_text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise WorldLoadError(source, (WorldValidationIssue(field="$", message=str(exc)),)) from exc

    try:
        payload: Any = json.loads(raw_text)
    except JSONDecodeError as exc:
        issue = WorldValidationIssue(
            field=f"line {exc.lineno}, column {exc.colno}",
            message=exc.msg,
        )
        raise WorldLoadError(source, (issue,)) from exc

    try:
        return WorldDefinition.model_validate(payload)
    except ValidationError as exc:
        issues = (
            WorldValidationIssue(field=_format_location(error["loc"]), message=error["msg"])
            for error in exc.errors(include_url=False)
        )
        raise WorldLoadError(source, issues) from exc


def _format_location(location: tuple[int | str, ...]) -> str:
    result = "$"
    for part in location:
        result += f"[{part}]" if isinstance(part, int) else f".{part}"
    return result


def _reference_issues(world: WorldDefinition) -> tuple[WorldValidationIssue, ...]:
    issues: list[WorldValidationIssue] = []
    character_ids = _collect_ids(world.cast, "$.cast", issues)
    location_ids = _collect_ids(world.locations, "$.locations", issues)
    _collect_ids(world.initial_relationships, "$.initial_relationships", issues)
    truth_ids = _collect_ids(world.truth, "$.truth", issues)
    secret_ids = _collect_ids(world.secrets, "$.secrets", issues)
    beat_ids = _collect_ids(world.beat_graph.beats, "$.beat_graph.beats", issues)

    for index, character in enumerate(world.cast):
        _check_optional_reference(
            character.home_location_id,
            location_ids,
            f"$.cast[{index}].home_location_id",
            "location",
            issues,
        )
    for index, location in enumerate(world.locations):
        _check_optional_reference(
            location.parent_location_id,
            location_ids,
            f"$.locations[{index}].parent_location_id",
            "location",
            issues,
        )
        if location.parent_location_id == location.id:
            issues.append(
                WorldValidationIssue(
                    field=f"$.locations[{index}].parent_location_id",
                    message="location cannot contain itself",
                )
            )
    for index, relationship in enumerate(world.initial_relationships):
        _check_reference(
            relationship.source_character_id,
            character_ids,
            f"$.initial_relationships[{index}].source_character_id",
            "character",
            issues,
        )
        _check_reference(
            relationship.target_character_id,
            character_ids,
            f"$.initial_relationships[{index}].target_character_id",
            "character",
            issues,
        )
        if relationship.source_character_id == relationship.target_character_id:
            issues.append(
                WorldValidationIssue(
                    field=f"$.initial_relationships[{index}].target_character_id",
                    message="relationship endpoints must be different",
                )
            )
    for index, truth in enumerate(world.truth):
        _check_references(
            truth.character_ids,
            character_ids,
            f"$.truth[{index}].character_ids",
            "character",
            issues,
        )
        _check_references(
            truth.location_ids,
            location_ids,
            f"$.truth[{index}].location_ids",
            "location",
            issues,
        )
    for index, secret in enumerate(world.secrets):
        _check_references(
            secret.holder_ids,
            character_ids,
            f"$.secrets[{index}].holder_ids",
            "character",
            issues,
        )
        _check_references(
            secret.known_by_ids,
            character_ids,
            f"$.secrets[{index}].known_by_ids",
            "character",
            issues,
        )
        _check_reference(
            secret.truth_id,
            truth_ids,
            f"$.secrets[{index}].truth_id",
            "truth",
            issues,
        )
    _check_references(
        world.beat_graph.entry_beat_ids,
        beat_ids,
        "$.beat_graph.entry_beat_ids",
        "beat",
        issues,
    )
    for index, beat in enumerate(world.beat_graph.beats):
        prefix = f"$.beat_graph.beats[{index}]"
        _check_references(
            beat.character_ids, character_ids, f"{prefix}.character_ids", "character", issues
        )
        _check_reference(
            beat.location_id, location_ids, f"{prefix}.location_id", "location", issues
        )
        _check_references(beat.depends_on, beat_ids, f"{prefix}.depends_on", "beat", issues)
        _check_references(
            beat.reveals_secret_ids,
            secret_ids,
            f"{prefix}.reveals_secret_ids",
            "secret",
            issues,
        )
        _check_references(
            beat.establishes_truth_ids,
            truth_ids,
            f"{prefix}.establishes_truth_ids",
            "truth",
            issues,
        )
    issues.extend(_beat_cycle_issues(world.beat_graph.beats))
    return tuple(issues)


def _collect_ids(
    records: Iterable[Any], field: str, issues: list[WorldValidationIssue]
) -> set[str]:
    seen: set[str] = set()
    for index, record in enumerate(records):
        if record.id in seen:
            issues.append(
                WorldValidationIssue(
                    field=f"{field}[{index}].id",
                    message=f"duplicate id '{record.id}'",
                )
            )
        seen.add(record.id)
    return seen


def _check_optional_reference(
    value: str | None,
    available: set[str],
    field: str,
    kind: str,
    issues: list[WorldValidationIssue],
) -> None:
    if value is not None:
        _check_reference(value, available, field, kind, issues)


def _check_references(
    values: Iterable[str],
    available: set[str],
    field: str,
    kind: str,
    issues: list[WorldValidationIssue],
) -> None:
    for index, value in enumerate(values):
        _check_reference(value, available, f"{field}[{index}]", kind, issues)


def _check_reference(
    value: str,
    available: set[str],
    field: str,
    kind: str,
    issues: list[WorldValidationIssue],
) -> None:
    if value not in available:
        issues.append(WorldValidationIssue(field=field, message=f"unknown {kind} id '{value}'"))


def _beat_cycle_issues(beats: tuple[AuthoredBeat, ...]) -> tuple[WorldValidationIssue, ...]:
    dependencies = {beat.id: beat.depends_on for beat in beats}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(beat_id: str) -> str | None:
        if beat_id in visiting:
            return beat_id
        if beat_id in visited:
            return None
        visiting.add(beat_id)
        for dependency in dependencies.get(beat_id, ()):
            cycle_at = visit(dependency)
            if cycle_at is not None:
                return cycle_at
        visiting.remove(beat_id)
        visited.add(beat_id)
        return None

    for index, beat in enumerate(beats):
        cycle_at = visit(beat.id)
        if cycle_at is not None:
            return (
                WorldValidationIssue(
                    field=f"$.beat_graph.beats[{index}].depends_on",
                    message=f"beat graph contains a cycle through '{cycle_at}'",
                ),
            )
    return ()
