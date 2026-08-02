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


class ClockMode(StrEnum):
    WALL = "wall"
    PAUSED = "paused"
    MANUAL = "manual"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
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
    clock_mode: ClockMode = ClockMode.WALL
    simulation_time: datetime | None = None
    wall_time_anchor: datetime | None = None
    clock_rate: float = 1.0
    tick_seconds: int = 300
    max_catch_up_ticks: int = 12

    def __post_init__(self) -> None:
        if self.simulation_time is None:
            object.__setattr__(self, "simulation_time", self.started_at)
        if self.wall_time_anchor is None:
            object.__setattr__(self, "wall_time_anchor", self.started_at)


@dataclass(frozen=True, slots=True)
class JobRecord:
    id: UUID
    run_id: UUID
    idempotency_key: str
    kind: str
    status: JobStatus
    scheduled_at: datetime
    payload: dict[str, Any]


class WorldRepository(Protocol):
    def add(self, world: WorldRecord) -> None: ...

    def get_by_slug(self, slug: str) -> WorldRecord | None: ...


class RunRepository(Protocol):
    def add(self, run: RunRecord) -> None: ...

    def get(self, run_id: UUID) -> RunRecord | None: ...

    def get_for_update(self, run_id: UUID) -> RunRecord | None: ...

    def update_clock(
        self, run_id: UUID, *, simulation_time: datetime, wall_time_anchor: datetime
    ) -> None: ...


class JobRepository(Protocol):
    def add_once(self, job: JobRecord) -> bool: ...


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

    @property
    def jobs(self) -> JobRepository: ...

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
