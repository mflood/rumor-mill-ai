"""Validate, deterministically smoke-simulate, and seed an authored world."""

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import Engine

from rumor_mill.adapters.persistence import (
    SqlAlchemyUnitOfWork,
    create_database_engine,
    create_session_factory,
)
from rumor_mill.adapters.persistence.models import Base
from rumor_mill.engine.ports import ClockMode, RunRecord, RunStatus, WorldRecord
from rumor_mill.worlds.authoring import WorldDefinition, load_world
from rumor_mill.worlds.continuity import validate_continuity

EPOCH = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class SeedResult:
    world_id: UUID
    run_id: UUID
    transcript: str


def deterministic_id(world_slug: str, seed: int, kind: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"rumor-mill:{world_slug}:{seed}:{kind}")


def smoke_transcript(world: WorldDefinition, seed: int, *, days: int = 14) -> str:
    """Produce a stable multi-day narrative review artifact without a model call."""

    ordered = sorted(
        world.beat_graph.beats,
        key=lambda beat: (beat.earliest_day, beat.latest_day, beat.id),
    )
    lines = [
        f"# {world.metadata.title} — deterministic smoke transcript",
        "",
        f"Seed: {seed}",
        "Provider: deterministic-fake (no paid model)",
        "",
    ]
    completed: set[str] = set()
    for day in range(1, days + 1):
        eligible = [
            beat
            for beat in ordered
            if beat.id not in completed
            and beat.earliest_day <= day <= beat.latest_day
            and set(beat.depends_on) <= completed
        ]
        lines.append(f"## Day {day}")
        if not eligible:
            lines.append("No required beat became eligible.")
        else:
            beat = eligible[seed % len(eligible)]
            completed.add(beat.id)
            cast = ", ".join(beat.character_ids)
            lines.append(f"[{beat.location_id}] {beat.title} ({cast})")
            lines.append(beat.summary)
        lines.append("")
    remaining = [beat.id for beat in ordered if beat.id not in completed]
    lines.extend(["## Review", f"Completed: {', '.join(sorted(completed)) or 'none'}"])
    lines.append(f"Unreached during smoke run: {', '.join(remaining) or 'none'}")
    return "\n".join(lines) + "\n"


def validate_and_seed(
    world_path: str | Path,
    database_url: str,
    *,
    seed: int = 0,
    transcript_path: str | Path | None = None,
    create_schema: bool = True,
) -> SeedResult:
    """Validate and atomically seed one reproducible run into an empty database."""

    world = load_world(world_path)
    issues = validate_continuity(world)
    if issues:
        detail = "\n".join(f"{issue.field}: {issue.message}" for issue in issues)
        raise ValueError(f"continuity validation failed:\n{detail}")
    engine = create_database_engine(database_url)
    try:
        return _seed_engine(
            world,
            engine,
            seed=seed,
            transcript_path=transcript_path,
            create_schema=create_schema,
        )
    finally:
        engine.dispose()


def _seed_engine(
    world: WorldDefinition,
    engine: Engine,
    *,
    seed: int,
    transcript_path: str | Path | None,
    create_schema: bool,
) -> SeedResult:
    if create_schema:
        Base.metadata.create_all(engine)
    world_id = deterministic_id(world.metadata.id, seed, "world")
    run_id = deterministic_id(world.metadata.id, seed, "run")
    started_at = EPOCH + timedelta(seconds=seed)
    world_record = WorldRecord(
        world_id,
        world.metadata.id,
        world.schema_version,
        world.model_dump(mode="json"),
        started_at,
    )
    run_record = RunRecord(
        run_id,
        world_id,
        RunStatus.RUNNING,
        seed,
        started_at,
        clock_mode=ClockMode.MANUAL,
    )
    factory = create_session_factory(engine)
    with SqlAlchemyUnitOfWork(factory) as unit_of_work:
        if unit_of_work.worlds.get_by_slug(world.metadata.id) is not None:
            raise ValueError(f"database is not empty for world '{world.metadata.id}'")
        unit_of_work.worlds.add(world_record)
        unit_of_work.flush()
        unit_of_work.runs.add(run_record)
        unit_of_work.commit()
    transcript = smoke_transcript(world, seed)
    if transcript_path is not None:
        destination = Path(transcript_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(transcript, encoding="utf-8")
    return SeedResult(world_id, run_id, transcript)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("world", type=Path)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--transcript", type=Path, required=True)
    args = parser.parse_args(argv)
    result = validate_and_seed(
        args.world,
        args.database_url,
        seed=args.seed,
        transcript_path=args.transcript,
    )
    print(json.dumps({"world_id": str(result.world_id), "run_id": str(result.run_id)}))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
