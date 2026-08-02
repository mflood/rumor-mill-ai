"""SQLAlchemy implementations of engine repository ports."""

from datetime import UTC, datetime
from types import TracebackType
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from rumor_mill.adapters.persistence.models import (
    ArtifactModel,
    BeliefModel,
    ClaimModel,
    EventModel,
    EvidenceModel,
    JobModel,
    MemoryModel,
    RunModel,
    SceneModel,
    WorldModel,
)
from rumor_mill.engine.domain import (
    Belief,
    Claim,
    Event,
    Evidence,
    Memory,
    PresentationArtifact,
    Scene,
)
from rumor_mill.engine.ports import (
    ClockMode,
    GeneratedSceneRecord,
    JobRecord,
    RunRecord,
    RunStatus,
    WorldRecord,
)


class SqlAlchemyWorldRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, world: WorldRecord) -> None:
        self._session.add(
            WorldModel(
                id=world.id,
                slug=world.slug,
                schema_version=world.schema_version,
                definition=world.definition,
                created_at=world.created_at,
            )
        )

    def get(self, world_id: UUID) -> WorldRecord | None:
        return self._record(self._session.get(WorldModel, world_id))

    def get_by_slug(self, slug: str) -> WorldRecord | None:
        model = self._session.scalar(select(WorldModel).where(WorldModel.slug == slug))
        return self._record(model)

    @staticmethod
    def _record(model: WorldModel | None) -> WorldRecord | None:
        if model is None:
            return None
        return WorldRecord(
            id=model.id,
            slug=model.slug,
            schema_version=model.schema_version,
            definition=model.definition,
            created_at=model.created_at.replace(tzinfo=UTC),
        )


class SqlAlchemyRunRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, run: RunRecord) -> None:
        self._session.add(
            RunModel(
                id=run.id,
                world_id=run.world_id,
                status=run.status.value,
                seed=run.seed,
                started_at=run.started_at,
                ended_at=run.ended_at,
                clock_mode=run.clock_mode.value,
                simulation_time=run.simulation_time or run.started_at,
                wall_time_anchor=run.wall_time_anchor or run.started_at,
                clock_rate=run.clock_rate,
                tick_seconds=run.tick_seconds,
                max_catch_up_ticks=run.max_catch_up_ticks,
            )
        )

    def get(self, run_id: UUID) -> RunRecord | None:
        model = self._session.get(RunModel, run_id)
        return self._record(model)

    def get_for_update(self, run_id: UUID) -> RunRecord | None:
        model = self._session.scalar(
            select(RunModel).where(RunModel.id == run_id).with_for_update()
        )
        return self._record(model)

    def update_clock(
        self, run_id: UUID, *, simulation_time: datetime, wall_time_anchor: datetime
    ) -> None:
        self._session.execute(
            update(RunModel)
            .where(RunModel.id == run_id)
            .values(simulation_time=simulation_time, wall_time_anchor=wall_time_anchor)
        )

    @staticmethod
    def _record(model: RunModel | None) -> RunRecord | None:
        if model is None:
            return None
        return RunRecord(
            id=model.id,
            world_id=model.world_id,
            status=RunStatus(model.status),
            seed=model.seed,
            started_at=model.started_at.replace(tzinfo=UTC),
            ended_at=(None if model.ended_at is None else model.ended_at.replace(tzinfo=UTC)),
            clock_mode=ClockMode(model.clock_mode),
            simulation_time=model.simulation_time.replace(tzinfo=UTC),
            wall_time_anchor=model.wall_time_anchor.replace(tzinfo=UTC),
            clock_rate=float(model.clock_rate),
            tick_seconds=model.tick_seconds,
            max_catch_up_ticks=model.max_catch_up_ticks,
        )


class SqlAlchemyJobRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_once(self, job: JobRecord) -> bool:
        exists = self._session.scalar(
            select(JobModel.id).where(JobModel.idempotency_key == job.idempotency_key)
        )
        if exists is not None:
            return False
        self._session.add(
            JobModel(
                id=job.id,
                run_id=job.run_id,
                idempotency_key=job.idempotency_key,
                kind=job.kind,
                status=job.status.value,
                scheduled_at=job.scheduled_at,
                payload=job.payload,
            )
        )
        return True


class SqlAlchemyEventRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, run_id: UUID, sequence: int, event: Event) -> None:
        self._session.add(
            EventModel(
                id=event.id,
                run_id=run_id,
                sequence=sequence,
                occurred_at=event.occurred_at,
                summary=event.summary,
                payload=event.model_dump(mode="json"),
            )
        )

    def get(self, event_id: UUID) -> Event | None:
        model = self._session.get(EventModel, event_id)
        return None if model is None else Event.model_validate(model.payload)


class SqlAlchemySceneRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_generated(self, run_id: UUID, record: GeneratedSceneRecord) -> None:
        scene_sequence = self._next_sequence(SceneModel, run_id)
        event_sequence = self._next_sequence(EventModel, run_id)
        self._session.add(
            SceneModel(
                id=record.scene.id,
                run_id=run_id,
                sequence=scene_sequence,
                title=record.scene.title,
                starts_at=record.scene.starts_at,
                ends_at=record.scene.ends_at,
                payload={
                    "scene": record.scene.model_dump(mode="json"),
                    "generation": record.generation,
                },
            )
        )
        self._session.add_all(
            EventModel(
                id=event.id,
                run_id=run_id,
                sequence=event_sequence + offset,
                occurred_at=event.occurred_at,
                summary=event.summary,
                payload=event.model_dump(mode="json"),
            )
            for offset, event in enumerate(record.events)
        )
        self._session.add_all(
            ClaimModel(
                id=claim.id,
                run_id=run_id,
                statement=claim.statement,
                visibility=claim.visibility.value,
                payload=claim.model_dump(mode="json"),
            )
            for claim in record.claims
        )
        self._session.add_all(
            MemoryModel(
                id=memory.id,
                run_id=run_id,
                character_id=memory.character_id,
                event_id=memory.source_event_id,
                claim_id=memory.source_claim_id,
                remembered_at=memory.remembered_at,
                content=memory.content,
                confidence=memory.confidence,
                payload=memory.model_dump(mode="json"),
            )
            for memory in record.memories
        )
        self._session.add_all(
            ArtifactModel(
                id=artifact.id,
                run_id=run_id,
                scene_id=record.scene.id,
                kind=artifact.kind.value,
                title=artifact.title,
                body=artifact.body,
                generated_at=artifact.generated_at,
                source_ids=[
                    str(source_id)
                    for source_id in (
                        artifact.source_scene_ids
                        + artifact.source_event_ids
                        + artifact.source_claim_ids
                    )
                ],
                payload=artifact.model_dump(mode="json"),
            )
            for artifact in record.artifacts
        )

    def get(self, scene_id: UUID) -> GeneratedSceneRecord | None:
        model = self._session.get(SceneModel, scene_id)
        if model is None:
            return None
        scene = Scene.model_validate(model.payload["scene"])
        events = tuple(
            Event.model_validate(item.payload)
            for item in self._session.scalars(
                select(EventModel)
                .where(EventModel.run_id == model.run_id)
                .where(EventModel.id.in_(scene.event_ids))
                .order_by(EventModel.sequence)
            )
        )
        claims = tuple(
            Claim.model_validate(item.payload)
            for item in self._session.scalars(
                select(ClaimModel).where(ClaimModel.run_id == model.run_id)
            )
            if item.payload.get("provenance", {}).get("source_id") == str(scene_id)
        )
        memories = tuple(
            Memory.model_validate(item.payload)
            for item in self._session.scalars(
                select(MemoryModel).where(MemoryModel.run_id == model.run_id)
            )
            if item.payload.get("provenance", {}).get("source_id") == str(scene_id)
        )
        artifacts = tuple(
            PresentationArtifact.model_validate(item.payload)
            for item in self._session.scalars(
                select(ArtifactModel).where(ArtifactModel.scene_id == scene_id)
            )
        )
        return GeneratedSceneRecord(
            scene=scene,
            events=events,
            claims=claims,
            memories=memories,
            artifacts=artifacts,
            generation=model.payload["generation"],
        )

    def _next_sequence(self, model: type[SceneModel] | type[EventModel], run_id: UUID) -> int:
        current = self._session.scalar(
            select(func.max(model.sequence)).where(model.run_id == run_id)
        )
        return 0 if current is None else current + 1


class SqlAlchemyMemoryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, run_id: UUID, memory: Memory) -> None:
        self._session.add(
            MemoryModel(
                id=memory.id,
                run_id=run_id,
                character_id=memory.character_id,
                event_id=memory.source_event_id,
                claim_id=memory.source_claim_id,
                remembered_at=memory.remembered_at,
                content=memory.content,
                confidence=memory.confidence,
                payload=memory.model_dump(mode="json"),
            )
        )

    def find_by_source(
        self,
        run_id: UUID,
        character_id: UUID,
        *,
        event_id: UUID | None = None,
        claim_id: UUID | None = None,
    ) -> Memory | None:
        if (event_id is None) == (claim_id is None):
            raise ValueError("exactly one memory source is required")
        query = select(MemoryModel).where(
            MemoryModel.run_id == run_id,
            MemoryModel.character_id == character_id,
        )
        query = query.where(
            MemoryModel.event_id == event_id
            if event_id is not None
            else MemoryModel.claim_id == claim_id
        )
        model = self._session.scalar(query.order_by(MemoryModel.remembered_at).limit(1))
        return None if model is None else Memory.model_validate(model.payload)

    def list_for_character(self, run_id: UUID, character_id: UUID) -> tuple[Memory, ...]:
        return tuple(
            Memory.model_validate(model.payload)
            for model in self._session.scalars(
                select(MemoryModel)
                .where(
                    MemoryModel.run_id == run_id,
                    MemoryModel.character_id == character_id,
                )
                .order_by(MemoryModel.remembered_at.desc(), MemoryModel.id)
            )
        )


class SqlAlchemyBeliefRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_evidence(self, run_id: UUID, evidence: Evidence) -> None:
        self._session.add(
            EvidenceModel(
                id=evidence.id,
                run_id=run_id,
                claim_id=evidence.claim_id,
                stance=evidence.stance.value,
                payload=evidence.model_dump(mode="json"),
            )
        )

    def add_version(self, run_id: UUID, belief: Belief) -> None:
        current_version = self._session.scalar(
            select(func.max(BeliefModel.version)).where(
                BeliefModel.run_id == run_id,
                BeliefModel.character_id == belief.character_id,
                BeliefModel.claim_id == belief.claim_id,
            )
        )
        self._session.add(
            BeliefModel(
                id=belief.id,
                run_id=run_id,
                character_id=belief.character_id,
                claim_id=belief.claim_id,
                confidence=belief.confidence,
                version=1 if current_version is None else current_version + 1,
                payload=belief.model_dump(mode="json"),
            )
        )

    def get_current(self, run_id: UUID, character_id: UUID, claim_id: UUID) -> Belief | None:
        model = self._session.scalar(
            select(BeliefModel)
            .where(
                BeliefModel.run_id == run_id,
                BeliefModel.character_id == character_id,
                BeliefModel.claim_id == claim_id,
            )
            .order_by(BeliefModel.version.desc())
            .limit(1)
        )
        return None if model is None else Belief.model_validate(model.payload)

    def list_evidence(self, run_id: UUID, belief: Belief) -> tuple[Evidence, ...]:
        if not belief.evidence_ids:
            return ()
        models = self._session.scalars(
            select(EvidenceModel).where(
                EvidenceModel.run_id == run_id, EvidenceModel.id.in_(belief.evidence_ids)
            )
        )
        by_id = {model.id: Evidence.model_validate(model.payload) for model in models}
        return tuple(by_id[evidence_id] for evidence_id in belief.evidence_ids)


class SqlAlchemyUnitOfWork:
    """One explicit SQLAlchemy transaction behind the engine unit-of-work port."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session = session_factory()
        self.worlds = SqlAlchemyWorldRepository(self._session)
        self.runs = SqlAlchemyRunRepository(self._session)
        self.events = SqlAlchemyEventRepository(self._session)
        self.jobs = SqlAlchemyJobRepository(self._session)
        self.scenes = SqlAlchemySceneRepository(self._session)
        self.memories = SqlAlchemyMemoryRepository(self._session)
        self.beliefs = SqlAlchemyBeliefRepository(self._session)
        self._finished = False

    def __enter__(self) -> "SqlAlchemyUnitOfWork":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if not self._finished:
            self.rollback()
        self._session.close()

    def commit(self) -> None:
        self._session.commit()
        self._finished = True

    def flush(self) -> None:
        self._session.flush()

    def rollback(self) -> None:
        self._session.rollback()
        self._finished = True
