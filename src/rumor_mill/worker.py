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
from rumor_mill.adapters.persistence.llm_tracing import SqlAlchemyLlmTraceStore
from rumor_mill.adapters.persistence.models import WorkerHeartbeatModel
from rumor_mill.adapters.providers import create_model_provider
from rumor_mill.config import Settings, get_settings
from rumor_mill.engine.jobs import DurableJobWorker
from rumor_mill.engine.lighthouse_pipeline import (
    LighthouseWorkSource,
    RoutineTimeError,
    lighthouse_handlers,
)
from rumor_mill.engine.ports import JobStatus, ModelProvider
from rumor_mill.engine.scheduling import SimulationScheduler
from rumor_mill.observability import MetricsRegistry, configure_json_logging, observed_job

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
        job_batch_size: int = 100,
        provider: ModelProvider | None = None,
        metrics: MetricsRegistry | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session_factory = session_factory
        self._worker_id = worker_id
        self._poll_seconds = poll_seconds
        self._run_batch_size = run_batch_size
        self._job_batch_size = job_batch_size
        self._provider = provider
        self._metrics = metrics or MetricsRegistry()
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
        jobs_enqueued = 0
        for run in runs:
            try:
                result = scheduler.advance(run.id)
            except Exception as exc:
                diagnostic = {
                    "run_id": str(run.id),
                    "exception_type": type(exc).__name__,
                }
                if isinstance(exc, RoutineTimeError):
                    diagnostic["error_detail"] = str(exc)
                logger.exception("simulation_run_advance_failed", extra=diagnostic)
                continue
            if result.ticks:
                advanced += 1
                jobs_enqueued += result.jobs_enqueued
                logger.info(
                    "simulation_run_advanced",
                    extra={
                        "run_id": str(run.id),
                        "ticks": result.ticks,
                        "jobs_enqueued": result.jobs_enqueued,
                        "catch_up_limited": result.catch_up_limited,
                    },
                )

        handlers = (
            lighthouse_handlers()
            if self._provider is None
            else lighthouse_handlers(self._provider, self._unit_of_work)
        )
        observed_handlers = {
            kind: observed_job(handler, self._metrics) for kind, handler in handlers.items()
        }
        job_worker = DurableJobWorker(
            self._unit_of_work,
            observed_handlers,
            worker_id=self._worker_id,
            clock=self._clock,
        )
        counts = {"claimed": 0, "completed": 0, "retried": 0, "dead": 0}
        for _ in range(self._job_batch_size):
            job_result = job_worker.run_once()
            if job_result.job is None:
                break
            counts["claimed"] += 1
            if job_result.completed:
                counts["completed"] += 1
            else:
                counts["dead"] += int(job_result.job.status is JobStatus.DEAD)
                counts["retried"] += int(job_result.job.status is JobStatus.FAILED)
        with self._unit_of_work() as unit_of_work:
            pending = len(unit_of_work.jobs.list(status=JobStatus.PENDING, limit=1_000))
        for state, value in (*counts.items(), ("pending", pending)):
            self._metrics.increment("story_jobs_total", value, state=state)
        self._metrics.set("story_jobs_pending", pending)
        if counts["claimed"] or pending:
            logger.info("story_jobs_polled", extra={**counts, "pending": pending})
        with self._session_factory.begin() as database:
            heartbeat = database.get(WorkerHeartbeatModel, self._worker_id)
            assert heartbeat is not None
            heartbeat.story_queue_depth = pending
            if advanced:
                heartbeat.last_clock_advanced_at = now
            if jobs_enqueued:
                heartbeat.last_story_job_enqueued_at = now
            if counts["completed"]:
                heartbeat.last_story_job_completed_at = self._clock()
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
    metrics = MetricsRegistry()
    engine = create_database_engine(settings.database_url)
    factory = create_session_factory(engine)
    provider = create_model_provider(
        settings,
        metrics=metrics,
        trace_store=(SqlAlchemyLlmTraceStore(factory) if settings.llm_trace_enabled else None),
        fake_responses={
            "off_screen_scene": {
                "title": "Greyhaven dispatch",
                "duration_minutes": 5,
                "events": [{"summary": "The scheduled story moment unfolds."}],
                "presentation_hooks": [
                    {
                        "kind": "story_card",
                        "title": "Greyhaven dispatch",
                        "body": "A new moment unfolds in Greyhaven.",
                        "event_indexes": [0],
                    }
                ],
            }
        },
    )
    SimulationWorker(
        factory,
        worker_id=worker_id(),
        poll_seconds=settings.worker_poll_seconds,
        run_batch_size=settings.worker_run_batch_size,
        job_batch_size=settings.worker_job_batch_size,
        provider=provider,
        metrics=metrics,
    ).run_forever()


if __name__ == "__main__":  # pragma: no cover - exercised by the Heroku process
    main()
