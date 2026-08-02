"""Repository contracts that keep the engine independent of SQLAlchemy."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import TracebackType
from typing import Any, Protocol, Self
from uuid import UUID

from rumor_mill.engine.domain import Event


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class WorldRecord:
    id: UUID
    slug: str
    schema_version: int
    definition: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RunRecord:
    id: UUID
    world_id: UUID
    status: RunStatus
    seed: int
    started_at: datetime
    ended_at: datetime | None = None


class WorldRepository(Protocol):
    def add(self, world: WorldRecord) -> None: ...

    def get_by_slug(self, slug: str) -> WorldRecord | None: ...


class RunRepository(Protocol):
    def add(self, run: RunRecord) -> None: ...

    def get(self, run_id: UUID) -> RunRecord | None: ...


class EventRepository(Protocol):
    def add(self, run_id: UUID, sequence: int, event: Event) -> None: ...

    def get(self, event_id: UUID) -> Event | None: ...


class UnitOfWork(Protocol):
    @property
    def worlds(self) -> WorldRepository: ...

    @property
    def runs(self) -> RunRepository: ...

    @property
    def events(self) -> EventRepository: ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def commit(self) -> None: ...

    def flush(self) -> None: ...

    def rollback(self) -> None: ...
