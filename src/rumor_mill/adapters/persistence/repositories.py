"""SQLAlchemy implementations of engine repository ports."""

from datetime import UTC, datetime
from types import TracebackType
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from rumor_mill.adapters.persistence.models import EventModel, JobModel, RunModel, WorldModel
from rumor_mill.engine.domain import Event
from rumor_mill.engine.ports import (
    ClockMode,
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

    def get_by_slug(self, slug: str) -> WorldRecord | None:
        model = self._session.scalar(select(WorldModel).where(WorldModel.slug == slug))
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


class SqlAlchemyUnitOfWork:
    """One explicit SQLAlchemy transaction behind the engine unit-of-work port."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session = session_factory()
        self.worlds = SqlAlchemyWorldRepository(self._session)
        self.runs = SqlAlchemyRunRepository(self._session)
        self.events = SqlAlchemyEventRepository(self._session)
        self.jobs = SqlAlchemyJobRepository(self._session)
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
