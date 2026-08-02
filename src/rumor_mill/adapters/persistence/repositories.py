"""SQLAlchemy implementations of engine repository ports."""

from datetime import UTC
from types import TracebackType
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from rumor_mill.adapters.persistence.models import EventModel, RunModel, WorldModel
from rumor_mill.engine.domain import Event
from rumor_mill.engine.ports import RunRecord, RunStatus, WorldRecord


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
            )
        )

    def get(self, run_id: UUID) -> RunRecord | None:
        model = self._session.get(RunModel, run_id)
        if model is None:
            return None
        return RunRecord(
            id=model.id,
            world_id=model.world_id,
            status=RunStatus(model.status),
            seed=model.seed,
            started_at=model.started_at.replace(tzinfo=UTC),
            ended_at=(None if model.ended_at is None else model.ended_at.replace(tzinfo=UTC)),
        )


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
