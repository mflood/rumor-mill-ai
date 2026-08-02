"""Simulation clock and durable scheduling tests."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from rumor_mill.adapters.persistence import (
    SqlAlchemyUnitOfWork,
    create_database_engine,
    create_session_factory,
    seed_run,
)
from rumor_mill.adapters.persistence.models import JobModel
from rumor_mill.engine.ports import ClockMode, RunRecord, RunStatus, WorldRecord
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
