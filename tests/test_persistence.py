"""Migration, repository, constraint, and transaction tests."""

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, MetaData, Table, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from rumor_mill.adapters.persistence import (
    SqlAlchemyUnitOfWork,
    create_database_engine,
    create_session_factory,
    seed_run,
)
from rumor_mill.adapters.persistence.database import (
    DEFAULT_MIGRATION_DATABASE_URL,
    resolve_migration_database_url,
)
from rumor_mill.adapters.persistence.llm_tracing import SqlAlchemyLlmTraceStore
from rumor_mill.adapters.persistence.models import Base, LlmTraceMessageModel, WorldModel
from rumor_mill.engine.domain import Event, Lifecycle, Provenance, ProvenanceKind
from rumor_mill.engine.ports import RunRecord, RunStatus, WorldRecord

ROOT = Path(__file__).parents[1]
pytestmark = pytest.mark.integration
NOW = datetime(2026, 8, 2, 12, tzinfo=UTC)
TABLES = {
    "worlds",
    "runs",
    "events",
    "claims",
    "beliefs",
    "evidence",
    "memories",
    "scenes",
    "conversations",
    "visitors",
    "visitor_character_states",
    "jobs",
    "artifacts",
    "narrative_reports",
    "feedback_submissions",
    "worker_heartbeats",
    "operator_audit_entries",
    "llm_trace_messages",
}


def uid(value: int) -> Any:
    return UUID(int=value)


def alembic_config(database_url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def migrate(database_url: str, revision: str = "head") -> None:
    command.upgrade(alembic_config(database_url), revision)


@pytest.fixture
def sqlite_database(
    tmp_path: Path,
) -> Iterator[tuple[str, Engine, sessionmaker[Session]]]:
    database_url = f"sqlite:///{tmp_path / 'persistence.db'}"
    migrate(database_url)
    engine = create_database_engine(database_url)
    yield database_url, engine, create_session_factory(engine)
    engine.dispose()


def world_record(identifier: int = 1, slug: str = "lantern-market") -> WorldRecord:
    fixture = ROOT / "tests" / "fixtures" / "worlds" / "minimal.json"
    return WorldRecord(
        id=uid(identifier),
        slug=slug,
        schema_version=1,
        definition=json.loads(fixture.read_text(encoding="utf-8")),
        created_at=NOW,
    )


def run_record(identifier: int = 2, world_id: UUID | None = None) -> RunRecord:
    return RunRecord(
        id=uid(identifier),
        world_id=uid(1) if world_id is None else world_id,
        status=RunStatus.PENDING,
        seed=42,
        started_at=NOW,
    )


def event_record(identifier: int = 3) -> Event:
    return Event(
        id=uid(identifier),
        occurred_at=NOW,
        summary="Ada saw Bea conceal the key.",
        participant_ids=(uid(4), uid(5)),
        provenance=Provenance(kind=ProvenanceKind.AUTHORED, recorded_at=NOW),
        lifecycle=Lifecycle(started_at=NOW),
    )


def test_migration_upgrade_indexes_and_downgrade(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'migration.db'}"
    config = alembic_config(database_url)

    command.upgrade(config, "head")
    engine = create_database_engine(database_url)
    inspector = inspect(engine)

    assert set(inspector.get_table_names()) >= TABLES | {"alembic_version"}
    assert {index["name"] for index in inspector.get_indexes("jobs")} >= {
        "ix_jobs_claim",
        "ix_jobs_run_created",
    }
    assert {index["name"] for index in inspector.get_indexes("beliefs")} >= {
        "ix_beliefs_character_claim"
    }

    engine.dispose()
    command.downgrade(config, "base")
    engine = create_database_engine(database_url)
    assert not (set(inspect(engine).get_table_names()) & TABLES)
    engine.dispose()


def test_recap_identity_migration_preserves_legacy_duplicates(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'legacy-recaps.db'}"
    config = alembic_config(database_url)
    command.upgrade(config, "0012")
    engine = create_database_engine(database_url)
    metadata = MetaData()
    worlds = Table("worlds", metadata, autoload_with=engine)
    runs = Table("runs", metadata, autoload_with=engine)
    artifacts = Table("artifacts", metadata, autoload_with=engine)
    world_id = uid(901).hex
    run_id = uid(902).hex
    payload = {
        "visibility": "public",
        "recap": {
            "story_date": "2026-08-02",
            "headline": "Legacy recap",
            "dek": "A prior published dispatch.",
            "panels": [],
            "active_threads": [],
            "suggested_location_ids": [],
            "suggested_character_ids": [],
            "state": "quiet_day",
        },
    }
    with engine.begin() as database:
        database.execute(
            worlds.insert().values(
                id=world_id,
                slug="legacy-lighthouse",
                schema_version=1,
                definition={},
            )
        )
        database.execute(
            runs.insert().values(
                id=run_id,
                world_id=world_id,
                status="running",
                seed=7,
                started_at=NOW,
                ended_at=None,
                clock_mode="wall",
                simulation_time=NOW,
                wall_time_anchor=NOW,
                clock_rate=1,
                tick_seconds=300,
                max_catch_up_ticks=12,
            )
        )
        for index in range(2):
            database.execute(
                artifacts.insert().values(
                    id=uid(910 + index).hex,
                    run_id=run_id,
                    scene_id=None,
                    kind="daily_recap",
                    title=f"Legacy recap {index}",
                    body="Previously published.",
                    generated_at=NOW.replace(minute=index),
                    source_ids=[],
                    payload=payload,
                )
            )
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_database_engine(database_url)
    migrated = Table("artifacts", MetaData(), autoload_with=engine)
    with engine.connect() as database:
        rows = list(
            database.execute(
                select(migrated.c.story_date, migrated.c.payload)
                .where(migrated.c.run_id == run_id)
                .order_by(migrated.c.generated_at)
            )
        )
    assert rows[0].story_date.isoformat() == "2026-08-02"
    assert rows[0].payload["canonical"] is True
    assert rows[1].story_date is None
    assert rows[1].payload["canonical"] is False
    engine.dispose()


def test_explicit_migration_url_is_isolated_from_application_environment() -> None:
    test_url = "sqlite+pysqlite:///:memory:"
    explicit_url = "postgresql://explicit-application-database"
    managed_url = "postgres://heroku-managed-database"

    assert resolve_migration_database_url(test_url, explicit_url, managed_url) == test_url
    assert (
        resolve_migration_database_url(DEFAULT_MIGRATION_DATABASE_URL, explicit_url, managed_url)
        == "postgresql+psycopg://explicit-application-database"
    )
    assert (
        resolve_migration_database_url(DEFAULT_MIGRATION_DATABASE_URL, None, managed_url)
        == "postgresql+psycopg://heroku-managed-database"
    )
    assert resolve_migration_database_url(DEFAULT_MIGRATION_DATABASE_URL, None, None) == (
        DEFAULT_MIGRATION_DATABASE_URL
    )


def test_database_engine_normalizes_postgres_driver() -> None:
    for scheme in ("postgres", "postgresql", "postgresql+psycopg"):
        engine = create_database_engine(f"{scheme}://user:password@localhost/example")
        assert engine.url.drivername == "postgresql+psycopg"
        engine.dispose()


def test_seed_and_repository_round_trip(
    sqlite_database: tuple[str, Engine, sessionmaker[Session]],
) -> None:
    _, _, factory = sqlite_database
    world = world_record()
    run = run_record()

    seed_run(SqlAlchemyUnitOfWork(factory), world, run)

    event = event_record()
    with SqlAlchemyUnitOfWork(factory) as unit_of_work:
        unit_of_work.events.add(run.id, 0, event)
        unit_of_work.commit()

    with SqlAlchemyUnitOfWork(factory) as unit_of_work:
        assert unit_of_work.worlds.get_by_slug(world.slug) == world
        assert unit_of_work.runs.get(run.id) == run
        assert unit_of_work.events.get(event.id) == event
        assert unit_of_work.worlds.get_by_slug("missing") is None
        assert unit_of_work.runs.get(uid(99)) is None
        assert unit_of_work.events.get(uid(99)) is None


def test_seed_rejects_mismatched_world() -> None:
    class UnexpectedUnitOfWork:
        def __enter__(self) -> "UnexpectedUnitOfWork":
            raise AssertionError("unit of work should not open")

    with pytest.raises(ValueError, match="run.world_id must match world.id"):
        seed_run(UnexpectedUnitOfWork(), world_record(), run_record(world_id=uid(99)))  # type: ignore[arg-type]


def test_uncommitted_and_explicit_transactions_roll_back(
    sqlite_database: tuple[str, Engine, sessionmaker[Session]],
) -> None:
    _, _, factory = sqlite_database

    with SqlAlchemyUnitOfWork(factory) as unit_of_work:
        unit_of_work.worlds.add(world_record())

    with SqlAlchemyUnitOfWork(factory) as unit_of_work:
        assert unit_of_work.worlds.get_by_slug("lantern-market") is None
        unit_of_work.worlds.add(world_record(2, "second-world"))
        unit_of_work.rollback()

    with SqlAlchemyUnitOfWork(factory) as unit_of_work:
        assert unit_of_work.worlds.get_by_slug("second-world") is None


def test_exception_rolls_back_transaction(
    sqlite_database: tuple[str, Engine, sessionmaker[Session]],
) -> None:
    _, _, factory = sqlite_database

    with (
        pytest.raises(RuntimeError, match="abort"),
        SqlAlchemyUnitOfWork(factory) as unit_of_work,
    ):
        unit_of_work.worlds.add(world_record())
        raise RuntimeError("abort")

    with SqlAlchemyUnitOfWork(factory) as unit_of_work:
        assert unit_of_work.worlds.get_by_slug("lantern-market") is None


def test_unique_and_check_constraints(
    sqlite_database: tuple[str, Engine, sessionmaker[Session]],
) -> None:
    _, _, factory = sqlite_database
    with factory() as session:
        session.add(
            WorldModel(
                id=uid(1),
                slug="invalid-version",
                schema_version=0,
                definition={},
                created_at=NOW,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        first = world_record()
        session.add(
            WorldModel(
                id=first.id,
                slug=first.slug,
                schema_version=first.schema_version,
                definition=first.definition,
                created_at=first.created_at,
            )
        )
        session.commit()
        session.add(
            WorldModel(
                id=uid(2),
                slug=first.slug,
                schema_version=1,
                definition={},
                created_at=NOW,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_model_metadata_represents_every_state_family() -> None:
    assert set(Base.metadata.tables) == TABLES


def test_llm_trace_store_persists_outbound_and_inbound_rows_independently(
    sqlite_database: tuple[str, Engine, sessionmaker[Session]],
) -> None:
    _, _, factory = sqlite_database
    store = SqlAlchemyLlmTraceStore(factory)
    call_id = uid(800)

    store.record_outbound(
        call_id=call_id,
        provider="openai",
        model="gpt-test",
        purpose="character_conversation",
        messages=[
            {"role": "developer", "content": "private prompt"},
            {"role": "user", "content": "hello"},
        ],
    )
    with factory() as database:
        outbound = database.scalars(
            select(LlmTraceMessageModel).where(LlmTraceMessageModel.call_id == call_id)
        ).all()
        assert [row.payload["content"] for row in outbound] == ["private prompt", "hello"]

    store.record_inbound(
        call_id=call_id,
        sequence=0,
        provider="openai",
        model="gpt-test",
        purpose="character_conversation",
        item_type="error",
        payload={"error_code": "provider_error"},
        duration_ms=17,
    )
    with factory() as database:
        rows = database.scalars(
            select(LlmTraceMessageModel)
            .where(LlmTraceMessageModel.call_id == call_id)
            .order_by(LlmTraceMessageModel.direction, LlmTraceMessageModel.sequence)
        ).all()
        assert len(rows) == 3
        inbound = next(row for row in rows if row.direction == "inbound")
        assert inbound.item_type == "error"
        assert inbound.duration_ms == 17


def test_llm_trace_store_failure_does_not_break_model_calls() -> None:
    class BrokenSession:
        def __enter__(self) -> "BrokenSession":
            raise RuntimeError("database unavailable")

        def __exit__(self, *args: object) -> None:
            return None

    store = SqlAlchemyLlmTraceStore(lambda: BrokenSession())  # type: ignore[arg-type]

    with patch("rumor_mill.adapters.persistence.llm_tracing.logger.exception") as logged:
        store.record_inbound(
            call_id=uid(801),
            sequence=0,
            provider="openai",
            model="gpt-test",
            purpose="test",
            item_type="response",
            payload={"id": "response-1"},
        )

    logged.assert_called_once_with("llm_trace_write_failed")


@pytest.mark.postgres
def test_postgres_migrations_constraints_and_transaction() -> None:
    database_url = os.environ.get("RUMOR_MILL_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("RUMOR_MILL_TEST_DATABASE_URL is not configured")

    config = alembic_config(database_url)
    command.upgrade(config, "head")
    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    seed_run(SqlAlchemyUnitOfWork(factory), world_record(), run_record())

    with factory() as session:
        assert session.scalar(select(WorldModel.slug)) == "lantern-market"

    engine.dispose()
    command.downgrade(config, "base")
