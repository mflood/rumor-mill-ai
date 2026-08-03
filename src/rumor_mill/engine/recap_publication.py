"""Durable, target-date publication of canonical Lighthouse daily recaps."""

from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from rumor_mill.engine.ports import JobRecord, JobStatus, RunStatus, UnitOfWork
from rumor_mill.engine.recap import build_daily_recap

DAILY_RECAP_JOB = "lighthouse_daily_recap"


def recap_key(run_id: UUID, story_date: date) -> str:
    return f"run:{run_id}:daily-recap:{story_date.isoformat()}"


def recap_artifact_id(run_id: UUID, story_date: date) -> UUID:
    return uuid5(NAMESPACE_URL, f"rumor-mill:{recap_key(run_id, story_date)}")


def publish_daily_recap(
    unit_of_work: UnitOfWork,
    *,
    run_id: UUID,
    story_date: date,
    published_at: datetime,
    allow_quiet: bool = False,
) -> tuple[UUID, bool]:
    """Publish once inside the caller's transaction and return (artifact id, created)."""
    if unit_of_work.runs.get_for_update(run_id) is None:
        raise LookupError(f"run {run_id} does not exist")
    existing = unit_of_work.artifacts.get_daily_recap(run_id, story_date)
    if existing is not None:
        return existing[0], False
    sources = list(unit_of_work.artifacts.recap_sources(run_id, story_date))
    if not sources and not allow_quiet:
        raise ValueError("no_public_recap_sources")
    recap = build_daily_recap(story_date, sources)
    artifact_id = recap_artifact_id(run_id, story_date)
    unit_of_work.artifacts.add_daily_recap(
        run_id,
        artifact_id=artifact_id,
        story_date=story_date,
        published_at=published_at,
        recap=recap,
    )
    return artifact_id, True


class DailyRecapPlanner:
    """Discover missing closed story dates and enqueue a bounded oldest-first batch."""

    def __init__(self, unit_of_work_factory: Callable[[], UnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def enqueue_missing(self, run_id: UUID, *, now: datetime, limit: int) -> int:
        if limit < 1:
            return 0
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get_for_update(run_id)
            if run is None:
                raise LookupError(f"run {run_id} does not exist")
            world = unit_of_work.worlds.get(run.world_id)
            if world is None or world.slug != "lighthouse":
                return 0
            current_date = (run.simulation_time or run.started_at).date()
            final_date = (run.ended_at or run.simulation_time or run.started_at).date()
            published = unit_of_work.artifacts.published_recap_dates(run.id)
            eligible = [
                story_date
                for story_date in unit_of_work.artifacts.public_source_dates(run.id)
                if story_date not in published
                and (
                    story_date < current_date
                    or (run.status is RunStatus.COMPLETED and story_date <= final_date)
                )
            ][:limit]
            enqueued = 0
            for story_date in eligible:
                closure = datetime.combine(story_date + timedelta(days=1), time.min, tzinfo=UTC)
                enqueued += unit_of_work.jobs.add_once(
                    JobRecord(
                        id=uuid5(NAMESPACE_URL, f"rumor-mill:job:{recap_key(run.id, story_date)}"),
                        run_id=run.id,
                        idempotency_key=recap_key(run.id, story_date),
                        kind=DAILY_RECAP_JOB,
                        status=JobStatus.PENDING,
                        scheduled_at=closure,
                        available_at=now,
                        payload={"story_date": story_date.isoformat()},
                    )
                )
            unit_of_work.commit()
            return enqueued


class DailyRecapHandler:
    def __call__(self, job: JobRecord):  # type: ignore[no-untyped-def]
        story_date = date.fromisoformat(str(job.payload["story_date"]))

        def mutation(unit_of_work: UnitOfWork) -> dict[str, Any]:
            artifact_id, created = publish_daily_recap(
                unit_of_work,
                run_id=job.run_id,
                story_date=story_date,
                published_at=job.scheduled_at,
            )
            return {
                "artifact_id": str(artifact_id),
                "story_date": story_date.isoformat(),
                "created": created,
            }

        return mutation
