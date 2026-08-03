"""Production work plan and durable handlers for the packaged Lighthouse season."""

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, time, timedelta
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from rumor_mill.engine.domain import (
    ArtifactKind,
    CharacterId,
    Event,
    EventId,
    Lifecycle,
    LocationId,
    PresentationArtifact,
    PresentationArtifactId,
    Provenance,
    ProvenanceKind,
    Scene,
    SceneId,
)
from rumor_mill.engine.ports import (
    GeneratedSceneRecord,
    JobRecord,
    ModelProvider,
    RunRecord,
    UnitOfWork,
)
from rumor_mill.engine.scene_generation import SceneGenerationService, ScenePlan
from rumor_mill.engine.scheduling import ScheduledWork

LIGHTHOUSE_STORY_JOB = "lighthouse_story"


class RoutineTimeError(ValueError):
    """A bounded, payload-free diagnostic for an invalid persisted routine time."""


def _routine_offset(value: object) -> timedelta:
    if not isinstance(value, str):
        raise RoutineTimeError("routine start_time must be an ISO local time string")
    try:
        parsed = time.fromisoformat(value)
    except ValueError as exc:
        raise RoutineTimeError("routine start_time must be a valid ISO local time") from exc
    if parsed.tzinfo is not None:
        raise RoutineTimeError("routine start_time must not include a UTC offset")
    return timedelta(
        hours=parsed.hour,
        minutes=parsed.minute,
        seconds=parsed.second,
        microseconds=parsed.microsecond,
    )


def _stable_id(run_id: UUID, kind: str, authored_id: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"rumor-mill:{run_id}:{kind}:{authored_id}")


class LighthouseWorkSource:
    """Translate authored Lighthouse beats and routines into deterministic durable jobs."""

    def __init__(self, unit_of_work_factory: Callable[[], UnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def due_work(
        self, run: RunRecord, *, after: datetime, through: datetime
    ) -> Iterable[ScheduledWork]:
        with self._unit_of_work_factory() as unit_of_work:
            world = unit_of_work.worlds.get(run.world_id)
            completed_keys = unit_of_work.jobs.completed_keys(run.id, kind=LIGHTHOUSE_STORY_JOB)
        if world is None or world.slug != "lighthouse":
            return ()

        definition = world.definition
        work: list[ScheduledWork] = []
        completed_beats = {
            key.rsplit(":", 1)[-1]
            for key in completed_keys
            if key.startswith(f"run:{run.id}:beat:")
        }
        beats = definition.get("beat_graph", {}).get("beats", [])
        for beat in beats:
            beat_id = str(beat["id"])
            if beat_id in completed_beats:
                continue
            prerequisites = {str(item) for item in beat.get("depends_on", [])}
            if not prerequisites <= completed_beats:
                continue
            earliest = run.started_at + timedelta(days=int(beat["earliest_day"]) - 1, minutes=5)
            latest = run.started_at + timedelta(days=int(beat["latest_day"]))
            # A prerequisite may complete after this beat's earliest instant. In that case,
            # enqueue it on the first subsequent simulation tick that remains in its window.
            scheduled_at = max(earliest, through if earliest <= after else earliest)
            if after < scheduled_at <= through and scheduled_at <= latest:
                work.append(
                    ScheduledWork(
                        key=f"beat:{beat_id}",
                        kind=LIGHTHOUSE_STORY_JOB,
                        scheduled_at=scheduled_at,
                        payload={"story_kind": "beat", **beat},
                    )
                )

        for routine in definition.get("routines", []):
            offset = _routine_offset(routine.get("start_time"))
            for day in routine["days"]:
                scheduled_at = run.started_at + timedelta(days=int(day) - 1) + offset
                if after < scheduled_at <= through:
                    work.append(
                        ScheduledWork(
                            key=f"routine:{routine['id']}:day:{day}",
                            kind=LIGHTHOUSE_STORY_JOB,
                            scheduled_at=scheduled_at,
                            payload={"story_kind": "routine", "day": day, **routine},
                        )
                    )
        return sorted(work, key=lambda item: (item.scheduled_at, item.key))


class LighthouseStoryHandler:
    """Prepare deterministic authored output, then commit it with job completion."""

    def __init__(
        self,
        provider: ModelProvider | None = None,
        unit_of_work_factory: Callable[[], UnitOfWork] | None = None,
    ) -> None:
        if (provider is None) != (unit_of_work_factory is None):
            raise ValueError("provider and unit_of_work_factory must be configured together")
        self._generator = (
            None
            if provider is None or unit_of_work_factory is None
            else SceneGenerationService(provider, unit_of_work_factory)
        )

    def __call__(self, job: JobRecord):  # type: ignore[no-untyped-def]
        payload = job.payload
        story_kind = str(payload["story_kind"])
        authored_id = str(payload["id"])
        scene_id = SceneId(_stable_id(job.run_id, "scene", job.idempotency_key))
        event_id = EventId(_stable_id(job.run_id, "event", job.idempotency_key))
        artifact_id = PresentationArtifactId(
            _stable_id(job.run_id, "artifact", job.idempotency_key)
        )
        provenance = Provenance(
            kind=ProvenanceKind.AUTHORED,
            recorded_at=job.scheduled_at,
            detail=f"Lighthouse {story_kind} {authored_id}",
        )
        lifecycle = Lifecycle(started_at=job.scheduled_at)
        if story_kind == "beat":
            title = str(payload["title"])
            summary = str(payload["summary"])
            participant_ids = tuple(
                CharacterId(_stable_id(job.run_id, "character", str(item)))
                for item in payload.get("character_ids", [])
            )
            location = str(payload["location_id"])
            location_id = LocationId(_stable_id(job.run_id, "location", location))
            body = summary
        else:
            title = str(payload["public_activity"])
            summary = f"{title} continues in Greyhaven."
            participant_ids = (
                CharacterId(_stable_id(job.run_id, "character", str(payload["character_id"]))),
            )
            location_id = LocationId(
                _stable_id(job.run_id, "location", str(payload["location_id"]))
            )
            body = summary

        if self._generator is not None:
            record = self._generator.prepare(
                ScenePlan(
                    run_id=job.run_id,
                    scheduled_at=job.scheduled_at,
                    participant_ids=participant_ids,
                    location_id=location_id,
                    goals=(summary,),
                    constraints=(
                        "Respect authored Lighthouse canon and reveal no hidden story text.",
                        f"Produce a {story_kind} scene titled {title}.",
                    ),
                )
            )
        else:
            record = self._authored_record(
                job,
                story_kind=story_kind,
                authored_id=authored_id,
                title=title,
                summary=summary,
                body=body,
                participant_ids=participant_ids,
                location_id=location_id,
                scene_id=scene_id,
                event_id=event_id,
                artifact_id=artifact_id,
                provenance=provenance,
                lifecycle=lifecycle,
            )

        def mutation(unit_of_work: UnitOfWork) -> dict[str, Any]:
            if unit_of_work.runs.get_for_update(job.run_id) is None:
                raise LookupError(f"run {job.run_id} does not exist")
            unit_of_work.scenes.add_generated(job.run_id, record)
            return {
                "scene_id": str(record.scene.id),
                "artifact_ids": [str(item.id) for item in record.artifacts],
            }

        return mutation

    @staticmethod
    def _authored_record(
        job: JobRecord,
        *,
        story_kind: str,
        authored_id: str,
        title: str,
        summary: str,
        body: str,
        participant_ids: tuple[CharacterId, ...],
        location_id: LocationId,
        scene_id: SceneId,
        event_id: EventId,
        artifact_id: PresentationArtifactId,
        provenance: Provenance,
        lifecycle: Lifecycle,
    ) -> GeneratedSceneRecord:
        event = Event(
            id=event_id,
            occurred_at=job.scheduled_at,
            summary=summary,
            participant_ids=participant_ids,
            location_id=location_id,
            provenance=provenance,
            lifecycle=lifecycle,
        )
        scene = Scene(
            id=scene_id,
            title=title,
            event_ids=(event_id,),
            starts_at=job.scheduled_at,
            ends_at=job.scheduled_at + timedelta(minutes=5),
            location_id=location_id,
            provenance=provenance,
            lifecycle=lifecycle,
        )
        artifact = PresentationArtifact(
            id=artifact_id,
            kind=ArtifactKind.STORY_CARD,
            title=title,
            body=body,
            source_scene_ids=(scene_id,),
            source_event_ids=(event_id,),
            generated_at=job.scheduled_at,
            provenance=provenance,
            lifecycle=lifecycle,
        )
        return GeneratedSceneRecord(
            scene=scene,
            events=(event,),
            claims=(),
            memories=(),
            artifacts=(artifact,),
            generation={
                "source": "authored_lighthouse_pipeline",
                "job_id": str(job.id),
                "story_kind": story_kind,
                "authored_id": authored_id,
            },
        )


def lighthouse_handlers(
    provider: ModelProvider | None = None,
    unit_of_work_factory: Callable[[], UnitOfWork] | None = None,
) -> Mapping[str, LighthouseStoryHandler]:
    return {LIGHTHOUSE_STORY_JOB: LighthouseStoryHandler(provider, unit_of_work_factory)}
