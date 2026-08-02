"""Production work plan and durable handlers for the packaged Lighthouse season."""

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timedelta
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
from rumor_mill.engine.ports import GeneratedSceneRecord, JobRecord, RunRecord, UnitOfWork
from rumor_mill.engine.scheduling import ScheduledWork

LIGHTHOUSE_STORY_JOB = "lighthouse_story"


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
        if world is None or world.slug != "lighthouse":
            return ()

        definition = world.definition
        work: list[ScheduledWork] = []
        beats = definition.get("beat_graph", {}).get("beats", [])
        for beat in beats:
            day = int(beat["earliest_day"])
            scheduled_at = run.started_at + timedelta(days=day - 1, minutes=5)
            if after < scheduled_at <= through:
                work.append(
                    ScheduledWork(
                        key=f"beat:{beat['id']}",
                        kind=LIGHTHOUSE_STORY_JOB,
                        scheduled_at=scheduled_at,
                        payload={"story_kind": "beat", **beat},
                    )
                )

        for routine in definition.get("routines", []):
            hour, minute = (int(part) for part in routine["start_time"].split(":"))
            offset = timedelta(hours=hour, minutes=minute)
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
        record = GeneratedSceneRecord(
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

        def mutation(unit_of_work: UnitOfWork) -> dict[str, Any]:
            if unit_of_work.runs.get_for_update(job.run_id) is None:
                raise LookupError(f"run {job.run_id} does not exist")
            unit_of_work.scenes.add_generated(job.run_id, record)
            return {"scene_id": str(scene_id), "artifact_id": str(artifact_id)}

        return mutation


def lighthouse_handlers() -> Mapping[str, LighthouseStoryHandler]:
    return {LIGHTHOUSE_STORY_JOB: LighthouseStoryHandler()}
