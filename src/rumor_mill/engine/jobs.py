"""Durable background-job claiming, execution, and recovery."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from rumor_mill.engine.ports import JobRecord, UnitOfWork


class PreparedMutation(Protocol):
    """A validated mutation applied only inside the completion transaction."""

    def __call__(self, unit_of_work: UnitOfWork) -> dict[str, Any]: ...


class JobHandler(Protocol):
    """Prepare expensive work without mutating durable story state."""

    def __call__(self, job: JobRecord) -> PreparedMutation: ...


@dataclass(frozen=True, slots=True)
class WorkerResult:
    job: JobRecord | None
    completed: bool = False


class LeaseLostError(RuntimeError):
    pass


class DurableJobWorker:
    def __init__(
        self,
        unit_of_work_factory: Callable[[], UnitOfWork],
        handlers: Mapping[str, JobHandler],
        *,
        worker_id: str,
        lease_duration: timedelta = timedelta(minutes=5),
        base_backoff: timedelta = timedelta(seconds=30),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._handlers = handlers
        self._worker_id = worker_id
        self._lease_duration = lease_duration
        self._base_backoff = base_backoff
        self._clock = clock

    def run_once(self) -> WorkerResult:
        now = self._clock()
        with self._unit_of_work_factory() as unit_of_work:
            job = unit_of_work.jobs.claim_due(
                worker_id=self._worker_id, now=now, lease_until=now + self._lease_duration
            )
            unit_of_work.commit()
        if job is None:
            return WorkerResult(None)

        try:
            handler = self._handlers[job.kind]
            mutation = handler(job)
            with self._unit_of_work_factory() as unit_of_work:
                current = unit_of_work.jobs.get(job.id)
                if current is not None and current.status.value == "completed":
                    return WorkerResult(current, completed=True)
                result = mutation(unit_of_work)
                if not unit_of_work.jobs.complete(
                    job.id, worker_id=self._worker_id, completed_at=self._clock(), result=result
                ):
                    raise LeaseLostError("job lease was lost before completion")
                unit_of_work.commit()
            return WorkerResult(job, completed=True)
        except LeaseLostError:
            with self._unit_of_work_factory() as unit_of_work:
                return WorkerResult(unit_of_work.jobs.get(job.id))
        except Exception as exc:
            failed_at = self._clock()
            delay = self._base_backoff * (2 ** max(0, job.attempts - 1))
            with self._unit_of_work_factory() as unit_of_work:
                failed = unit_of_work.jobs.fail(
                    job.id,
                    worker_id=self._worker_id,
                    now=failed_at,
                    retry_at=failed_at + delay,
                    error=f"{type(exc).__name__}: {exc}"[:4000],
                )
                unit_of_work.commit()
            return WorkerResult(failed)
