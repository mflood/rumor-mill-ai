"""Heroku worker entrypoint for durable simulation advancement."""

import logging
import os
import socket
from collections.abc import Callable
from datetime import UTC, datetime
from threading import Event

from sqlalchemy.orm import Session, sessionmaker

from rumor_mill.adapters.persistence import (
    SqlAlchemyUnitOfWork,
    create_database_engine,
    create_session_factory,
)
from rumor_mill.adapters.persistence.models import WorkerHeartbeatModel
from rumor_mill.config import Settings, get_settings
from rumor_mill.engine.jobs import DurableJobWorker
from rumor_mill.engine.lighthouse_pipeline import LighthouseWorkSource, lighthouse_handlers
from rumor_mill.engine.scheduling import SimulationScheduler
from rumor_mill.observability import configure_json_logging

logger = logging.getLogger(__name__)


class _WorkerClock:
    def __init__(self, now: Callable[[], datetime]) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now()


class SimulationWorker:
    """Poll active runs and durably advance their wall clocks."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        worker_id: str,
        poll_seconds: float = 5.0,
        run_batch_size: int = 100,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session_factory = session_factory
        self._worker_id = worker_id
        self._poll_seconds = poll_seconds
        self._run_batch_size = run_batch_size
        self._clock = clock

    def _unit_of_work(self) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(self._session_factory)

    def poll_once(self) -> int:
        """Heartbeat and advance one bounded batch of active simulations."""
        now = self._clock()
        with self._session_factory.begin() as database:
            heartbeat = database.get(WorkerHeartbeatModel, self._worker_id)
            if heartbeat is None:
                database.add(
                    WorkerHeartbeatModel(
                        worker_id=self._worker_id,
                        last_seen_at=now,
                        story_pipeline_ready=True,
                    )
                )
            else:
                heartbeat.last_seen_at = now
                heartbeat.story_pipeline_ready = True

        with self._unit_of_work() as unit_of_work:
            runs = unit_of_work.runs.list_active(limit=self._run_batch_size)

        scheduler = SimulationScheduler(
            self._unit_of_work,
            LighthouseWorkSource(self._unit_of_work),
            clock=_WorkerClock(self._clock),
        )
        advanced = 0
        for run in runs:
            try:
                result = scheduler.advance(run.id)
            except Exception:
                logger.exception("simulation_run_advance_failed", extra={"run_id": str(run.id)})
                continue
            if result.ticks:
                advanced += 1
                logger.info(
                    "simulation_run_advanced",
                    extra={
                        "run_id": str(run.id),
                        "ticks": result.ticks,
                        "jobs_enqueued": result.jobs_enqueued,
                        "catch_up_limited": result.catch_up_limited,
                    },
                )

        job_worker = DurableJobWorker(
            self._unit_of_work,
            lighthouse_handlers(),
            worker_id=self._worker_id,
            clock=self._clock,
        )
        completed = 0
        for _ in range(self._run_batch_size):
            job_result = job_worker.run_once()
            if job_result.job is None:
                break
            if job_result.completed:
                completed += 1
        if completed:
            with self._session_factory.begin() as database:
                heartbeat = database.get(WorkerHeartbeatModel, self._worker_id)
                assert heartbeat is not None
                heartbeat.last_story_job_completed_at = self._clock()
            logger.info("story_jobs_completed", extra={"jobs_completed": completed})
        return advanced

    def run_forever(self, stop: Event | None = None) -> None:
        """Poll until Heroku asks the dyno to terminate."""
        stop = stop or Event()
        logger.info("simulation_worker_started", extra={"worker_id": self._worker_id})
        while not stop.is_set():
            try:
                self.poll_once()
            except Exception:
                logger.exception("simulation_worker_poll_failed")
            stop.wait(self._poll_seconds)
        logger.info("simulation_worker_stopped", extra={"worker_id": self._worker_id})


def worker_id() -> str:
    """Return a stable identifier for one dyno lifetime."""
    return os.getenv("DYNO") or socket.gethostname()


def main(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    configure_json_logging()
    engine = create_database_engine(settings.database_url)
    factory = create_session_factory(engine)
    SimulationWorker(
        factory,
        worker_id=worker_id(),
        poll_seconds=settings.worker_poll_seconds,
        run_batch_size=settings.worker_run_batch_size,
    ).run_forever()


if __name__ == "__main__":  # pragma: no cover - exercised by the Heroku process
    main()
