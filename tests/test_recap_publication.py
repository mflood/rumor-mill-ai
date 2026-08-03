"""Autonomous recap rollover, backfill, and canonical identity regressions."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session, sessionmaker

from rumor_mill.adapters.persistence import (
    Base,
    SqlAlchemyUnitOfWork,
    create_database_engine,
    create_session_factory,
    seed_run,
)
from rumor_mill.adapters.persistence.models import ArtifactModel, JobModel, WorkerHeartbeatModel
from rumor_mill.engine.ports import ClockMode, RunRecord, RunStatus, WorldRecord
from rumor_mill.engine.recap import DailyRecap, build_daily_recap
from rumor_mill.engine.recap_publication import (
    DAILY_RECAP_JOB,
    DailyRecapPlanner,
    publish_daily_recap,
)
from rumor_mill.worker import SimulationWorker

START = datetime(2026, 8, 2, 23, 55, tzinfo=UTC)


def store_source(
    factory: sessionmaker[Session],
    run_id: UUID,
    *,
    generated_at: datetime,
    title: str,
    visibility: str = "public",
) -> UUID:
    artifact_id = uuid4()
    with factory.begin() as database:
        database.add(
            ArtifactModel(
                id=artifact_id,
                run_id=run_id,
                kind="story_card",
                title=title,
                body=f"Public body for {title}.",
                generated_at=generated_at,
                source_ids=[str(uuid4())],
                payload={"visibility": visibility, "importance": 5},
            )
        )
    return artifact_id


def recap_dates(factory, run_id: UUID) -> list[date]:  # type: ignore[no-untyped-def]
    with factory() as database:
        recaps = list(
            database.scalars(
                select(ArtifactModel).where(
                    ArtifactModel.run_id == run_id,
                    ArtifactModel.kind == "daily_recap",
                )
            )
        )
    return sorted(DailyRecap.model_validate(item.payload["recap"]).story_date for item in recaps)


def make_run(tmp_path: Path, run: RunRecord):  # type: ignore[no-untyped-def]
    engine = create_database_engine(f"sqlite:///{tmp_path / f'{run.id}.db'}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    world = WorldRecord(run.world_id, "lighthouse", 1, {}, START)
    seed_run(SqlAlchemyUnitOfWork(factory), world, run)
    return engine, factory


def test_simulation_midnight_publishes_closed_day_once_after_restart(tmp_path: Path) -> None:
    run = RunRecord(
        UUID(int=112),
        UUID(int=1),
        RunStatus.RUNNING,
        7,
        START,
        clock_mode=ClockMode.WALL,
        simulation_time=START,
        wall_time_anchor=START,
        tick_seconds=300,
        max_catch_up_ticks=2,
    )
    engine, factory = make_run(tmp_path, run)
    assert ["run_id", "kind", "story_date"] in [
        item["column_names"] for item in inspect(engine).get_unique_constraints("artifacts")
    ]
    source_id = store_source(
        factory,
        run.id,
        generated_at=START + timedelta(minutes=3),
        title="Grounded in Darkness",
    )
    now = START + timedelta(minutes=10)

    worker = SimulationWorker(factory, worker_id="worker.rollover", clock=lambda: now)
    assert worker.poll_once() == 1
    assert recap_dates(factory, run.id) == [START.date()]

    with factory() as database:
        recap = database.scalar(select(ArtifactModel).where(ArtifactModel.kind == "daily_recap"))
        job = database.scalar(select(JobModel).where(JobModel.kind == DAILY_RECAP_JOB))
        heartbeat = database.get(WorkerHeartbeatModel, "worker.rollover")
        assert recap is not None and recap.story_date == START.date()
        assert recap.source_ids == [str(source_id)]
        assert job is not None and job.status == "completed"
        assert job.idempotency_key == f"run:{run.id}:daily-recap:{START.date()}"
        assert heartbeat is not None
        assert heartbeat.last_recap_job_enqueued_at is not None
        assert heartbeat.last_recap_job_completed_at is not None
        assert heartbeat.recap_queue_depth == 0

    restarted = SimulationWorker(factory, worker_id="worker.restarted", clock=lambda: now)
    assert restarted.poll_once() == 0
    assert recap_dates(factory, run.id) == [START.date()]
    with factory() as database:
        jobs = list(database.scalars(select(JobModel).where(JobModel.kind == DAILY_RECAP_JOB)))
        assert len(jobs) == 1
    engine.dispose()


def test_multi_day_backfill_is_bounded_oldest_first_and_public_only(tmp_path: Path) -> None:
    run = RunRecord(
        UUID(int=113),
        UUID(int=2),
        RunStatus.RUNNING,
        7,
        START,
        clock_mode=ClockMode.MANUAL,
        simulation_time=START + timedelta(days=3),
        wall_time_anchor=START,
    )
    engine, factory = make_run(tmp_path, run)
    for offset, title in enumerate(("Day one", "Day two", "Day three")):
        store_source(
            factory,
            run.id,
            generated_at=START + timedelta(days=offset),
            title=title,
        )
    store_source(
        factory,
        run.id,
        generated_at=START,
        title="Private Day one",
        visibility="engine_only",
    )
    now = START + timedelta(days=3)
    worker = SimulationWorker(
        factory,
        worker_id="worker.backfill",
        recap_batch_size=2,
        job_batch_size=1,
        clock=lambda: now,
    )

    assert worker.poll_once() == 0
    assert recap_dates(factory, run.id) == [START.date()]
    assert worker.poll_once() == 0
    assert recap_dates(factory, run.id) == [START.date(), (START + timedelta(days=1)).date()]
    assert worker.poll_once() == 0
    assert recap_dates(factory, run.id) == [
        START.date(),
        (START + timedelta(days=1)).date(),
        (START + timedelta(days=2)).date(),
    ]
    with factory() as database:
        recaps = list(
            database.scalars(
                select(ArtifactModel)
                .where(ArtifactModel.kind == "daily_recap")
                .order_by(ArtifactModel.story_date)
            )
        )
        assert [item.title for item in recaps] == ["Day one", "Day two", "Day three"]
        assert all("Private" not in item.body for item in recaps)
        jobs = list(database.scalars(select(JobModel).where(JobModel.kind == DAILY_RECAP_JOB)))
        assert len(jobs) == 3
    engine.dispose()


def test_completed_run_closes_and_publishes_its_final_story_date(tmp_path: Path) -> None:
    run = RunRecord(
        UUID(int=114),
        UUID(int=3),
        RunStatus.COMPLETED,
        7,
        START,
        ended_at=START + timedelta(hours=1),
        clock_mode=ClockMode.MANUAL,
        simulation_time=START + timedelta(hours=1),
        wall_time_anchor=START,
    )
    engine, factory = make_run(tmp_path, run)
    store_source(factory, run.id, generated_at=START, title="Final light")
    worker = SimulationWorker(factory, worker_id="worker.final", clock=lambda: START)

    assert worker.poll_once() == 0
    assert recap_dates(factory, run.id) == [START.date()]
    engine.dispose()


def test_publication_service_validation_idempotency_and_legacy_lookup(tmp_path: Path) -> None:
    run = RunRecord(
        UUID(int=115),
        UUID(int=4),
        RunStatus.RUNNING,
        7,
        START,
        clock_mode=ClockMode.MANUAL,
        simulation_time=START + timedelta(days=1),
        wall_time_anchor=START,
    )
    engine, factory = make_run(tmp_path, run)
    planner = DailyRecapPlanner(lambda: SqlAlchemyUnitOfWork(factory))
    assert planner.enqueue_missing(run.id, now=START, limit=0) == 0
    with pytest.raises(LookupError, match=str(UUID(int=999))):
        planner.enqueue_missing(UUID(int=999), now=START, limit=1)
    other_world = WorldRecord(UUID(int=401), "other-world", 1, {}, START)
    other_run = RunRecord(UUID(int=402), other_world.id, RunStatus.RUNNING, 9, START)
    seed_run(SqlAlchemyUnitOfWork(factory), other_world, other_run)
    assert planner.enqueue_missing(other_run.id, now=START, limit=1) == 0
    with (
        SqlAlchemyUnitOfWork(factory) as unit_of_work,
        pytest.raises(LookupError, match=str(UUID(int=998))),
    ):
        publish_daily_recap(
            unit_of_work,
            run_id=UUID(int=998),
            story_date=START.date(),
            published_at=START,
        )
    with (
        SqlAlchemyUnitOfWork(factory) as unit_of_work,
        pytest.raises(ValueError, match="no_public_recap_sources"),
    ):
        publish_daily_recap(
            unit_of_work,
            run_id=run.id,
            story_date=START.date(),
            published_at=START,
        )

    store_source(factory, run.id, generated_at=START, title="Canonical source")
    with SqlAlchemyUnitOfWork(factory) as unit_of_work:
        artifact_id, created = publish_daily_recap(
            unit_of_work,
            run_id=run.id,
            story_date=START.date(),
            published_at=START + timedelta(days=1),
        )
        unit_of_work.commit()
    with SqlAlchemyUnitOfWork(factory) as unit_of_work:
        repeated_id, created_again = publish_daily_recap(
            unit_of_work,
            run_id=run.id,
            story_date=START.date(),
            published_at=START + timedelta(days=1),
        )
        assert (repeated_id, created_again) == (artifact_id, False)

    legacy_date = START.date() - timedelta(days=1)
    legacy_recap = build_daily_recap(legacy_date, [])
    with factory.begin() as database:
        database.add(
            ArtifactModel(
                run_id=run.id,
                kind="daily_recap",
                title=legacy_recap.headline,
                body=legacy_recap.dek,
                generated_at=START - timedelta(days=1),
                story_date=None,
                source_ids=[],
                payload=legacy_recap.artifact_payload(),
            )
        )
    with SqlAlchemyUnitOfWork(factory) as unit_of_work:
        legacy = unit_of_work.artifacts.get_daily_recap(run.id, legacy_date)
        assert legacy is not None and legacy[1].story_date == legacy_date
    engine.dispose()


def test_worker_bounds_recap_discovery_across_runs_and_records_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = RunRecord(
        UUID(int=116),
        UUID(int=5),
        RunStatus.RUNNING,
        7,
        START,
        clock_mode=ClockMode.MANUAL,
        simulation_time=START + timedelta(days=1),
        wall_time_anchor=START,
    )
    engine, factory = make_run(tmp_path, run)
    second = RunRecord(
        UUID(int=117),
        run.world_id,
        RunStatus.RUNNING,
        8,
        START,
        clock_mode=ClockMode.MANUAL,
        simulation_time=START + timedelta(days=1),
        wall_time_anchor=START,
    )
    with SqlAlchemyUnitOfWork(factory) as unit_of_work:
        unit_of_work.runs.add(second)
        unit_of_work.commit()
    store_source(factory, run.id, generated_at=START, title="Invalid source")
    store_source(factory, second.id, generated_at=START, title="Deferred source")
    with factory.begin() as database:
        invalid = database.scalar(select(ArtifactModel).where(ArtifactModel.run_id == run.id))
        assert invalid is not None
        invalid.payload = {**invalid.payload, "importance": 99}

    worker = SimulationWorker(
        factory,
        worker_id="worker.failed-recap",
        recap_batch_size=1,
        clock=lambda: START + timedelta(days=1),
    )
    assert worker.poll_once() == 0
    with factory() as database:
        jobs = list(database.scalars(select(JobModel).where(JobModel.kind == DAILY_RECAP_JOB)))
        heartbeat = database.get(WorkerHeartbeatModel, "worker.failed-recap")
        assert len(jobs) == 1 and jobs[0].status == "failed"
        assert heartbeat is not None and heartbeat.last_recap_job_failed_at is not None

    monkeypatch.setattr(
        DailyRecapPlanner,
        "enqueue_missing",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("planner unavailable")),
    )
    assert worker.poll_once() == 0
    engine.dispose()
