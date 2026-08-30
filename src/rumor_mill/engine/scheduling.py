"""Deterministic simulation clock and durable work scheduler."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from rumor_mill.engine.ports import (
    ClockMode,
    JobRecord,
    JobStatus,
    RunRecord,
    RunStatus,
    UnitOfWork,
)


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class ScheduledWork:
    """A beat or autonomous scene due during a simulation-time interval."""

    key: str
    kind: str
    scheduled_at: datetime
    payload: dict[str, Any]


class WorkSource(Protocol):
    def due_work(
        self, run: RunRecord, *, after: datetime, through: datetime
    ) -> Iterable[ScheduledWork]: ...

    def exhausted(self, run: RunRecord, *, at: datetime) -> bool:
        """Return True once no further work can ever become due for this run."""
        ...


class NoScheduledWork:
    def due_work(
        self, run: RunRecord, *, after: datetime, through: datetime
    ) -> Iterable[ScheduledWork]:
        del run, after, through
        return ()

    def exhausted(self, run: RunRecord, *, at: datetime) -> bool:
        del run, at
        return False


@dataclass(frozen=True, slots=True)
class AdvanceResult:
    previous_time: datetime
    simulation_time: datetime
    ticks: int
    jobs_enqueued: int
    catch_up_limited: bool


class SimulationScheduler:
    def __init__(
        self,
        unit_of_work_factory: Callable[[], UnitOfWork],
        work_source: WorkSource | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._work_source = work_source or NoScheduledWork()
        self._clock = clock or SystemClock()

    def advance(self, run_id: UUID, *, manual_ticks: int = 0) -> AdvanceResult:
        if manual_ticks < 0:
            raise ValueError("manual_ticks cannot be negative")
        now = self._clock.now()
        if now.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")

        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get_for_update(run_id)
            if run is None:
                raise LookupError(f"run {run_id} does not exist")
            previous = run.simulation_time or run.started_at
            anchor = run.wall_time_anchor or run.started_at
            ticks, limited = self._ticks_due(run, now, anchor, manual_ticks)
            target = previous + timedelta(seconds=ticks * run.tick_seconds)

            enqueued = 0
            if ticks:
                for work in self._work_source.due_work(run, after=previous, through=target):
                    if not previous < work.scheduled_at <= target:
                        raise ValueError("scheduled work lies outside the advanced interval")
                    job = JobRecord(
                        id=uuid4(),
                        run_id=run.id,
                        idempotency_key=f"run:{run.id}:{work.key}",
                        kind=work.kind,
                        status=JobStatus.PENDING,
                        scheduled_at=work.scheduled_at,
                        payload=work.payload,
                    )
                    enqueued += unit_of_work.jobs.add_once(job)

                consumed = timedelta(seconds=ticks * run.tick_seconds / run.clock_rate)
                unit_of_work.runs.update_clock(
                    run.id, simulation_time=target, wall_time_anchor=anchor + consumed
                )

            if run.status is RunStatus.RUNNING and self._work_source.exhausted(run, at=target):
                unit_of_work.runs.mark_completed(run.id, ended_at=target)
            unit_of_work.commit()
            return AdvanceResult(previous, target, ticks, enqueued, limited)

    @staticmethod
    def _ticks_due(
        run: RunRecord, now: datetime, anchor: datetime, manual_ticks: int
    ) -> tuple[int, bool]:
        if run.tick_seconds <= 0 or run.clock_rate <= 0 or run.max_catch_up_ticks <= 0:
            raise ValueError("clock configuration values must be positive")
        if manual_ticks:
            return manual_ticks, False
        if run.clock_mode is not ClockMode.WALL:
            return 0, False
        elapsed = max(0.0, (now - anchor).total_seconds())
        due = int(elapsed * run.clock_rate // run.tick_seconds)
        return min(due, run.max_catch_up_ticks), due > run.max_catch_up_ticks
