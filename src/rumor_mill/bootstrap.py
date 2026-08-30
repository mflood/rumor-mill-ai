"""Idempotently bootstrap the packaged Lighthouse production season."""

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from rumor_mill.adapters.persistence import create_database_engine, create_session_factory
from rumor_mill.adapters.persistence.models import ArtifactModel, RunModel, WorldModel
from rumor_mill.lighthouse_opening import opening_recap_artifact
from rumor_mill.worlds.authoring import load_world
from rumor_mill.worlds.continuity import validate_continuity

LIGHTHOUSE_PATH = Path(__file__).parents[2] / "docs" / "worlds" / "lighthouse" / "world.json"


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    world_id: UUID
    run_id: UUID
    created_world: bool
    created_run: bool
    definition_updated: bool


def bootstrap_lighthouse(database_url: str, world_path: Path = LIGHTHOUSE_PATH) -> BootstrapResult:
    """Validate Lighthouse, then select or create exactly one playable season."""
    definition = load_world(world_path)
    issues = validate_continuity(definition)
    if issues:
        detail = "\n".join(f"{issue.field}: {issue.message}" for issue in issues)
        raise ValueError(f"continuity validation failed:\n{detail}")

    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    try:
        with factory.begin() as database:
            return _bootstrap_session(database, definition.model_dump(mode="json"))
    finally:
        engine.dispose()


def _bootstrap_session(database: Session, definition: dict[str, object]) -> BootstrapResult:
    slug = "lighthouse"
    world = database.scalar(select(WorldModel).where(WorldModel.slug == slug).with_for_update())
    created_world = world is None
    definition_updated = False
    if world is None:
        world = WorldModel(id=uuid4(), slug=slug, schema_version=1, definition=definition)
        database.add(world)
        database.flush()
    elif world.definition != definition:
        # Keep the stored world in sync with the packaged, continuity-validated JSON on every
        # deploy. Beats and routines are read fresh each tick, so this can apply mid-season.
        world.definition = definition
        definition_updated = True
        database.flush()

    run = database.scalar(
        select(RunModel)
        .where(RunModel.world_id == world.id, RunModel.status == "running")
        .order_by(RunModel.started_at.desc())
        .limit(1)
        .with_for_update()
    )
    created_run = run is None
    if run is None:
        now = datetime.now(UTC)
        run = RunModel(
            id=uuid4(),
            world_id=world.id,
            status="running",
            seed=0,
            started_at=now,
            clock_mode="wall",
            simulation_time=now,
            wall_time_anchor=now,
            clock_rate=1,
            tick_seconds=300,
            max_catch_up_ticks=12,
        )
        database.add(run)
        database.flush()
    opening_exists = database.scalar(
        select(ArtifactModel.id).where(
            ArtifactModel.run_id == run.id,
            ArtifactModel.kind == "daily_recap",
            ArtifactModel.story_date == run.started_at.date(),
        )
    )
    if opening_exists is None:
        database.add(opening_recap_artifact(run.id, run.started_at))
        database.flush()
    return BootstrapResult(world.id, run.id, created_world, created_run, definition_updated)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--world", type=Path, default=LIGHTHOUSE_PATH)
    args = parser.parse_args(argv)
    result = bootstrap_lighthouse(args.database_url, args.world)
    print(
        json.dumps(
            {
                "world_id": str(result.world_id),
                "run_id": str(result.run_id),
                "created_world": result.created_world,
                "created_run": result.created_run,
                "definition_updated": result.definition_updated,
            }
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
