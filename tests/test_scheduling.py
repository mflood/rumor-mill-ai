"""Simulation clock and durable scheduling tests."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, update

from rumor_mill.adapters.persistence import (
    SqlAlchemyUnitOfWork,
    create_database_engine,
    create_session_factory,
    seed_run,
)
from rumor_mill.adapters.persistence.models import JobModel, WorldModel
from rumor_mill.engine.jobs import DurableJobWorker
from rumor_mill.engine.lighthouse_pipeline import LighthouseWorkSource, RoutineTimeError
from rumor_mill.engine.ports import (
    ClockMode,
    JobRecord,
    JobStatus,
    ProviderTimeoutError,
    RunRecord,
    RunStatus,
    WorldRecord,
)
from rumor_mill.engine.scheduling import ScheduledWork, SimulationScheduler, SystemClock

ROOT = Path(__file__).parents[1]
pytestmark = pytest.mark.integration
START = datetime(2026, 8, 2, 12, tzinfo=UTC)


class FixedClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


class WorkPlan:
    def due_work(
        self, run: RunRecord, *, after: datetime, through: datetime
    ) -> tuple[ScheduledWork, ...]:
        del run
        return (
            ScheduledWork("beat:intro", "beat", after + timedelta(minutes=5), {"beat": "intro"}),
            ScheduledWork("scene:harbor", "autonomous_scene", through, {"place": "harbor"}),
        )


def uid(value: int) -> UUID:
    return UUID(int=value)


@pytest.fixture
def scheduler_database(tmp_path: Path):  # type: ignore[no-untyped-def]
    url = f"sqlite:///{tmp_path / 'scheduler.db'}"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    engine = create_database_engine(url)
    factory = create_session_factory(engine)
    yield factory
    engine.dispose()


def seed(factory, *, mode: ClockMode = ClockMode.WALL, max_ticks: int = 12) -> RunRecord:  # type: ignore[no-untyped-def]
    world = WorldRecord(uid(1), "clock-world", 1, {}, START)
    run = RunRecord(
        uid(2),
        uid(1),
        RunStatus.RUNNING,
        42,
        START,
        clock_mode=mode,
        tick_seconds=300,
        max_catch_up_ticks=max_ticks,
    )
    seed_run(SqlAlchemyUnitOfWork(factory), world, run)
    return run


def test_wall_clock_advances_and_enqueues_each_work_item_once(scheduler_database) -> None:  # type: ignore[no-untyped-def]
    factory = scheduler_database
    run = seed(factory)
    clock = FixedClock(START + timedelta(minutes=10))
    scheduler = SimulationScheduler(lambda: SqlAlchemyUnitOfWork(factory), WorkPlan(), clock)

    first = scheduler.advance(run.id)
    clock.value = START + timedelta(minutes=20)
    second = scheduler.advance(run.id)

    assert first.ticks == 2
    assert first.jobs_enqueued == 2
    assert first.simulation_time == START + timedelta(minutes=10)
    assert not first.catch_up_limited
    assert second.ticks == 2
    assert second.jobs_enqueued == 0
    with factory() as session:
        jobs = session.scalars(select(JobModel).order_by(JobModel.kind)).all()
        assert [job.kind for job in jobs] == ["autonomous_scene", "beat"]
        assert all(job.idempotency_key.startswith(f"run:{run.id}:") for job in jobs)


def test_paused_clock_only_moves_with_manual_ticks(scheduler_database) -> None:  # type: ignore[no-untyped-def]
    factory = scheduler_database
    run = seed(factory, mode=ClockMode.PAUSED)
    scheduler = SimulationScheduler(
        lambda: SqlAlchemyUnitOfWork(factory), clock=FixedClock(START + timedelta(days=1))
    )

    assert scheduler.advance(run.id).ticks == 0
    result = scheduler.advance(run.id, manual_ticks=3)
    assert result.ticks == 3
    assert result.simulation_time == START + timedelta(minutes=15)


def test_catch_up_is_bounded_and_accelerated(scheduler_database) -> None:  # type: ignore[no-untyped-def]
    factory = scheduler_database
    world = WorldRecord(uid(1), "fast-world", 1, {}, START)
    run = RunRecord(
        uid(2),
        uid(1),
        RunStatus.RUNNING,
        1,
        START,
        clock_rate=2,
        tick_seconds=300,
        max_catch_up_ticks=2,
    )
    seed_run(SqlAlchemyUnitOfWork(factory), world, run)
    scheduler = SimulationScheduler(
        lambda: SqlAlchemyUnitOfWork(factory), clock=FixedClock(START + timedelta(minutes=30))
    )

    result = scheduler.advance(run.id)
    assert result.ticks == 2
    assert result.catch_up_limited


def test_scheduler_rejects_invalid_inputs_and_work(scheduler_database) -> None:  # type: ignore[no-untyped-def]
    factory = scheduler_database
    run = seed(factory)
    scheduler = SimulationScheduler(lambda: SqlAlchemyUnitOfWork(factory), clock=FixedClock(START))
    with pytest.raises(ValueError, match="negative"):
        scheduler.advance(run.id, manual_ticks=-1)
    with pytest.raises(LookupError):
        scheduler.advance(uid(99))

    naive = SimulationScheduler(
        lambda: SqlAlchemyUnitOfWork(factory), clock=FixedClock(START.replace(tzinfo=None))
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        naive.advance(run.id)

    class BadPlan:
        def due_work(self, run, *, after, through):  # type: ignore[no-untyped-def]
            del run, after
            return (ScheduledWork("late", "beat", through + timedelta(seconds=1), {}),)

    bad = SimulationScheduler(
        lambda: SqlAlchemyUnitOfWork(factory), BadPlan(), FixedClock(START + timedelta(minutes=5))
    )
    with pytest.raises(ValueError, match="outside"):
        bad.advance(run.id)


def test_clock_configuration_and_system_clock() -> None:
    assert SystemClock().now().tzinfo is UTC
    invalid = RunRecord(uid(2), uid(1), RunStatus.RUNNING, 1, START, tick_seconds=0)
    with pytest.raises(ValueError, match="positive"):
        SimulationScheduler._ticks_due(invalid, START, START, 0)

    wall = RunRecord(uid(3), uid(1), RunStatus.RUNNING, 1, START)
    assert SimulationScheduler._ticks_due(wall, START - timedelta(minutes=5), START, 0) == (
        0,
        False,
    )


def test_lighthouse_work_respects_dependencies_windows_and_persisted_completion(
    scheduler_database: Any,
) -> None:
    factory = scheduler_database
    definition = {
        "beat_graph": {
            "entry_beat_ids": ["entry"],
            "beats": [
                {
                    "id": "entry",
                    "title": "Entry",
                    "summary": "The story begins.",
                    "character_ids": [],
                    "location_id": "harbor",
                    "earliest_day": 1,
                    "latest_day": 1,
                },
                {
                    "id": "dependent",
                    "title": "Dependent",
                    "summary": "The story continues.",
                    "character_ids": [],
                    "location_id": "harbor",
                    "depends_on": ["entry"],
                    "earliest_day": 1,
                    "latest_day": 1,
                },
            ],
        },
        "routines": [
            {
                "id": "harbor-watch",
                "character_id": "keeper",
                "location_id": "harbor",
                "days": [1],
                "start_time": "00:10",
                "end_time": "01:00",
                "activity": "Watching the harbor.",
                "public_activity": "Harbor watch.",
            }
        ],
    }
    world = WorldRecord(uid(1), "lighthouse", 1, definition, START)
    run = RunRecord(
        uid(2), uid(1), RunStatus.RUNNING, 42, START, tick_seconds=300, max_catch_up_ticks=500
    )
    seed_run(SqlAlchemyUnitOfWork(factory), world, run)
    clock = FixedClock(START + timedelta(minutes=10))
    scheduler = SimulationScheduler(
        lambda: SqlAlchemyUnitOfWork(factory),
        LighthouseWorkSource(lambda: SqlAlchemyUnitOfWork(factory)),
        clock,
    )

    first = scheduler.advance(run.id)
    assert first.jobs_enqueued == 2
    with factory.begin() as session:
        entry = session.scalar(
            select(JobModel).where(JobModel.idempotency_key == f"run:{run.id}:beat:entry")
        )
        assert entry is not None
        entry.status = JobStatus.COMPLETED.value
        entry.completed_at = clock.value
    with SqlAlchemyUnitOfWork(factory) as unit_of_work:
        assert unit_of_work.jobs.completed_keys(run.id) == frozenset({f"run:{run.id}:beat:entry"})

    clock.value = START + timedelta(minutes=15)
    second = scheduler.advance(run.id)
    assert second.jobs_enqueued == 1
    with factory() as session:
        jobs = list(session.scalars(select(JobModel).order_by(JobModel.scheduled_at)))
        assert [job.idempotency_key.rsplit(":", 1)[-1] for job in jobs] == [
            "entry",
            "1",
            "dependent",
        ]
        assert jobs[-1].scheduled_at.replace(tzinfo=UTC) == clock.value

    # Stable keys suppress repeated work even when a later catch-up interval covers the window.
    clock.value = START + timedelta(hours=23)
    assert scheduler.advance(run.id).jobs_enqueued == 0


def test_lighthouse_does_not_enqueue_a_dependency_after_its_latest_day(
    scheduler_database: Any,
) -> None:
    factory = scheduler_database
    definition = {
        "beat_graph": {
            "entry_beat_ids": ["late"],
            "beats": [
                {
                    "id": "late",
                    "title": "Late",
                    "summary": "Too late.",
                    "character_ids": [],
                    "location_id": "harbor",
                    "earliest_day": 1,
                    "latest_day": 1,
                }
            ],
        },
        "routines": [],
    }
    world = WorldRecord(uid(1), "lighthouse", 1, definition, START)
    run = RunRecord(uid(2), uid(1), RunStatus.RUNNING, 42, START)
    seed_run(SqlAlchemyUnitOfWork(factory), world, run)
    source = LighthouseWorkSource(lambda: SqlAlchemyUnitOfWork(factory))

    assert tuple(source.due_work(run, after=START, through=START + timedelta(minutes=1))) == ()

    assert (
        tuple(
            source.due_work(
                run,
                after=START + timedelta(days=1),
                through=START + timedelta(days=1, minutes=5),
            )
        )
        == ()
    )


@pytest.mark.parametrize(
    ("serialized_time", "expected"),
    [
        ("05:30", timedelta(hours=5, minutes=30)),
        ("05:30:00", timedelta(hours=5, minutes=30)),
        ("05:30:04.250000", timedelta(hours=5, minutes=30, seconds=4, milliseconds=250)),
    ],
)
def test_lighthouse_accepts_iso_local_routine_times(
    scheduler_database: Any, serialized_time: str, expected: timedelta
) -> None:
    factory = scheduler_database
    definition = {
        "beat_graph": {"entry_beat_ids": [], "beats": []},
        "routines": [
            {
                "id": "watch",
                "character_id": "keeper",
                "location_id": "harbor",
                "days": [1],
                "start_time": serialized_time,
                "public_activity": "Harbor watch.",
            }
        ],
    }
    run = RunRecord(uid(2), uid(1), RunStatus.RUNNING, 42, START)
    seed_run(
        SqlAlchemyUnitOfWork(factory),
        WorldRecord(uid(1), "lighthouse", 1, definition, START),
        run,
    )

    work = tuple(
        LighthouseWorkSource(lambda: SqlAlchemyUnitOfWork(factory)).due_work(
            run, after=START, through=START + timedelta(hours=6)
        )
    )

    assert len(work) == 1
    assert work[0].scheduled_at == START + expected


@pytest.mark.parametrize("invalid_time", ["not-a-time", "05:30:00Z", 530, None])
def test_lighthouse_rejects_invalid_routine_times_with_bounded_diagnostic(
    scheduler_database: Any, invalid_time: object
) -> None:
    factory = scheduler_database
    definition = {
        "beat_graph": {"entry_beat_ids": [], "beats": []},
        "routines": [{"id": "secret-routine", "days": [1], "start_time": invalid_time}],
    }
    run = RunRecord(uid(2), uid(1), RunStatus.RUNNING, 42, START)
    seed_run(
        SqlAlchemyUnitOfWork(factory),
        WorldRecord(uid(1), "lighthouse", 1, definition, START),
        run,
    )

    with pytest.raises(RoutineTimeError, match="routine start_time") as error:
        tuple(
            LighthouseWorkSource(lambda: SqlAlchemyUnitOfWork(factory)).due_work(
                run, after=START, through=START + timedelta(hours=6)
            )
        )
    assert "secret-routine" not in str(error.value)


@pytest.mark.postgres
def test_postgres_concurrent_lighthouse_polls_enqueue_each_item_once() -> None:
    database_url = os.environ.get("RUMOR_MILL_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("RUMOR_MILL_TEST_DATABASE_URL is not configured")
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    world_id, run_id = uuid4(), uuid4()
    definition = {
        "beat_graph": {
            "entry_beat_ids": ["entry"],
            "beats": [
                {
                    "id": "entry",
                    "title": "Entry",
                    "summary": "The story begins.",
                    "character_ids": [],
                    "location_id": "harbor",
                    "earliest_day": 1,
                    "latest_day": 1,
                }
            ],
        },
        "routines": [],
    }
    run = RunRecord(run_id, world_id, RunStatus.RUNNING, 42, START)
    seed_run(
        SqlAlchemyUnitOfWork(factory),
        WorldRecord(world_id, f"lighthouse-{world_id}", 1, definition, START),
        run,
    )
    # The production source intentionally selects only the packaged Lighthouse slug.
    with factory.begin() as session:
        world = session.get(WorldModel, world_id)
        assert world is not None
        world.slug = "lighthouse"

    def poll() -> int:
        scheduler = SimulationScheduler(
            lambda: SqlAlchemyUnitOfWork(factory),
            LighthouseWorkSource(lambda: SqlAlchemyUnitOfWork(factory)),
            FixedClock(START + timedelta(minutes=10)),
        )
        return scheduler.advance(run_id).jobs_enqueued

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sum(pool.map(lambda _: poll(), range(2))) == 1
        with factory() as session:
            assert (
                len(list(session.scalars(select(JobModel).where(JobModel.run_id == run_id)))) == 1
            )
    finally:
        engine.dispose()
        command.downgrade(config, "base")


def add_job(factory, run: RunRecord, *, max_attempts: int = 3, kind: str = "test") -> UUID:  # type: ignore[no-untyped-def]
    job_id = uuid4()
    with SqlAlchemyUnitOfWork(factory) as unit_of_work:
        unit_of_work.jobs.add_once(
            JobRecord(
                job_id,
                run.id,
                f"test:{job_id}",
                kind,
                JobStatus.PENDING,
                START,
                {},
                max_attempts=max_attempts,
            )
        )
        unit_of_work.commit()
    return job_id


def test_worker_dead_letters_unknown_job_kinds_without_raising(scheduler_database) -> None:  # type: ignore[no-untyped-def]
    factory = scheduler_database
    run = seed(factory)
    job_id = add_job(factory, run, max_attempts=1, kind="unregistered")

    result = DurableJobWorker(
        lambda: SqlAlchemyUnitOfWork(factory),
        {},
        worker_id="worker-unknown",
        clock=lambda: START,
    ).run_once()

    assert result.job is not None and result.job.id == job_id
    assert result.job.status is JobStatus.DEAD
    assert result.job.error == "unknown_job_kind"
    assert DurableJobWorker._safe_error(ProviderTimeoutError("private prompt")) == (
        "provider_timeout"
    )


def test_worker_claims_completes_and_never_runs_job_twice(scheduler_database) -> None:  # type: ignore[no-untyped-def]
    factory = scheduler_database
    run = seed(factory)
    job_id = add_job(factory, run)
    prepared: list[UUID] = []
    applied: list[UUID] = []

    def handler(job: JobRecord):  # type: ignore[no-untyped-def]
        prepared.append(job.id)

        def mutation(unit_of_work):  # type: ignore[no-untyped-def]
            del unit_of_work
            applied.append(job.id)
            return {"scene_id": "accepted"}

        return mutation

    worker = DurableJobWorker(
        lambda: SqlAlchemyUnitOfWork(factory),
        {"test": handler},
        worker_id="worker-1",
        clock=lambda: START,
    )
    assert worker.run_once().completed
    assert worker.run_once().job is None
    with SqlAlchemyUnitOfWork(factory) as unit_of_work:
        job = unit_of_work.jobs.get(job_id)
        assert job is not None
        assert job.status is JobStatus.COMPLETED
        assert job.attempts == 1
        assert job.result == {"scene_id": "accepted"}
    assert prepared == [job_id]
    assert applied == [job_id]


def test_worker_reclaims_expired_lease_and_backs_off_failures(scheduler_database) -> None:  # type: ignore[no-untyped-def]
    factory = scheduler_database
    run = seed(factory)
    job_id = add_job(factory, run, max_attempts=2)
    with SqlAlchemyUnitOfWork(factory) as unit_of_work:
        claimed = unit_of_work.jobs.claim_due(
            worker_id="crashed", now=START, lease_until=START + timedelta(seconds=10)
        )
        unit_of_work.commit()
    assert claimed is not None

    now = START + timedelta(seconds=11)

    def broken(job: JobRecord):  # type: ignore[no-untyped-def]
        del job
        raise RuntimeError("provider unavailable")

    worker = DurableJobWorker(
        lambda: SqlAlchemyUnitOfWork(factory),
        {"test": broken},
        worker_id="recovery",
        base_backoff=timedelta(seconds=30),
        clock=lambda: now,
    )
    result = worker.run_once()
    assert result.job is not None
    assert result.job.id == job_id
    assert result.job.status is JobStatus.DEAD
    assert result.job.error == "RuntimeError: provider unavailable"


def test_failed_job_can_be_inspected_and_safely_retried(scheduler_database) -> None:  # type: ignore[no-untyped-def]
    factory = scheduler_database
    run = seed(factory)
    job_id = add_job(factory, run, max_attempts=1)
    with SqlAlchemyUnitOfWork(factory) as unit_of_work:
        unit_of_work.jobs.claim_due(
            worker_id="worker", now=START, lease_until=START + timedelta(minutes=1)
        )
        dead = unit_of_work.jobs.fail(
            job_id,
            worker_id="worker",
            now=START,
            retry_at=START + timedelta(minutes=1),
            error="invalid output",
        )
        unit_of_work.commit()
    assert dead.status is JobStatus.DEAD

    with SqlAlchemyUnitOfWork(factory) as unit_of_work:
        assert unit_of_work.jobs.list(status=JobStatus.DEAD) == (dead,)
        retried = unit_of_work.jobs.retry(job_id, now=START + timedelta(minutes=2))
        unit_of_work.commit()
    assert retried.status is JobStatus.PENDING
    assert retried.attempts == 0
    assert retried.error is None


def test_mutation_and_completion_roll_back_together(scheduler_database) -> None:  # type: ignore[no-untyped-def]
    factory = scheduler_database
    run = seed(factory)
    add_job(factory, run)

    def handler(job: JobRecord):  # type: ignore[no-untyped-def]
        def mutation(unit_of_work):  # type: ignore[no-untyped-def]
            unit_of_work.runs.update_clock(
                job.run_id,
                simulation_time=START + timedelta(days=1),
                wall_time_anchor=START + timedelta(days=1),
            )
            raise RuntimeError("partial generation rejected")

        return mutation

    worker = DurableJobWorker(
        lambda: SqlAlchemyUnitOfWork(factory),
        {"test": handler},
        worker_id="worker",
        clock=lambda: START,
    )
    result = worker.run_once()
    assert result.job is not None and result.job.status is JobStatus.FAILED
    with SqlAlchemyUnitOfWork(factory) as unit_of_work:
        stored_run = unit_of_work.runs.get(run.id)
        assert stored_run is not None
        assert stored_run.simulation_time == START


def test_worker_detects_completion_or_lost_lease_during_preparation(scheduler_database) -> None:  # type: ignore[no-untyped-def]
    factory = scheduler_database
    run = seed(factory)
    completed_id = add_job(factory, run)

    def completed_elsewhere(job: JobRecord):  # type: ignore[no-untyped-def]
        with SqlAlchemyUnitOfWork(factory) as unit_of_work:
            assert unit_of_work.jobs.complete(
                job.id, worker_id="worker", completed_at=START, result={"other": True}
            )
            unit_of_work.commit()
        return lambda unit_of_work: pytest.fail("completed mutation must not run")

    worker = DurableJobWorker(
        lambda: SqlAlchemyUnitOfWork(factory),
        {"test": completed_elsewhere},
        worker_id="worker",
        clock=lambda: START,
    )
    result = worker.run_once()
    assert result.completed and result.job is not None and result.job.id == completed_id

    lost_id = add_job(factory, run)

    def lease_stolen(job: JobRecord):  # type: ignore[no-untyped-def]
        with factory() as session:
            session.execute(
                update(JobModel).where(JobModel.id == job.id).values(locked_by="other-worker")
            )
            session.commit()
        return lambda unit_of_work: {}

    lost_worker = DurableJobWorker(
        lambda: SqlAlchemyUnitOfWork(factory),
        {"test": lease_stolen},
        worker_id="worker",
        clock=lambda: START,
    )
    lost = lost_worker.run_once()
    assert lost.job is not None and lost.job.id == lost_id
    assert not lost.completed


def test_job_repository_rejects_unsafe_recovery_operations(scheduler_database) -> None:  # type: ignore[no-untyped-def]
    factory = scheduler_database
    run = seed(factory)
    job_id = add_job(factory, run)
    missing_id = uuid4()
    with SqlAlchemyUnitOfWork(factory) as unit_of_work:
        assert unit_of_work.jobs.get(missing_id) is None
        assert unit_of_work.jobs.list() == (unit_of_work.jobs.get(job_id),)
        with pytest.raises(ValueError, match="failed or dead"):
            unit_of_work.jobs.retry(job_id, now=START)
        with pytest.raises(LookupError, match="does not exist"):
            unit_of_work.jobs.retry(missing_id, now=START)
        with pytest.raises(ValueError, match="leased"):
            unit_of_work.jobs.fail(
                job_id,
                worker_id="nobody",
                now=START,
                retry_at=START,
                error="no lease",
            )
