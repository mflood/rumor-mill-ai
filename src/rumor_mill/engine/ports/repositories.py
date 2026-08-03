"""Repository contracts that keep the engine independent of SQLAlchemy."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from types import TracebackType
from typing import Any, Protocol, Self
from uuid import UUID

from rumor_mill.engine.domain import (
    Belief,
    Claim,
    Event,
    Evidence,
    Memory,
    PresentationArtifact,
    Scene,
)
from rumor_mill.engine.recap import DailyRecap, RecapSource


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
    DEAD = "dead"


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
    attempts: int = 0
    max_attempts: int = 5
    available_at: datetime | None = None
    lease_expires_at: datetime | None = None
    locked_by: str | None = None
    completed_at: datetime | None = None
    error: str | None = None
    result: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class GeneratedSceneRecord:
    """A fully validated scene bundle persisted as one transaction."""

    scene: Scene
    events: tuple[Event, ...]
    claims: tuple[Claim, ...]
    memories: tuple[Memory, ...]
    artifacts: tuple[PresentationArtifact, ...]
    generation: dict[str, Any]


class WorldRepository(Protocol):
    def add(self, world: WorldRecord) -> None: ...

    def get(self, world_id: UUID) -> WorldRecord | None: ...

    def get_by_slug(self, slug: str) -> WorldRecord | None: ...


class RunRepository(Protocol):
    def add(self, run: RunRecord) -> None: ...

    def get(self, run_id: UUID) -> RunRecord | None: ...

    def get_for_update(self, run_id: UUID) -> RunRecord | None: ...

    def list_active(self, *, limit: int = 100) -> tuple[RunRecord, ...]: ...

    def list_recap_candidates(self, *, limit: int = 100) -> tuple[RunRecord, ...]: ...

    def update_clock(
        self, run_id: UUID, *, simulation_time: datetime, wall_time_anchor: datetime
    ) -> None: ...


class JobRepository(Protocol):
    def add_once(self, job: JobRecord) -> bool: ...

    def get(self, job_id: UUID) -> JobRecord | None: ...

    def list(
        self, *, status: JobStatus | None = None, limit: int = 100
    ) -> tuple[JobRecord, ...]: ...

    def completed_keys(self, run_id: UUID, *, kind: str | None = None) -> frozenset[str]: ...

    def claim_due(
        self, *, worker_id: str, now: datetime, lease_until: datetime
    ) -> JobRecord | None: ...

    def complete(
        self, job_id: UUID, *, worker_id: str, completed_at: datetime, result: dict[str, Any]
    ) -> bool: ...

    def fail(
        self, job_id: UUID, *, worker_id: str, now: datetime, retry_at: datetime, error: str
    ) -> JobRecord: ...

    def retry(self, job_id: UUID, *, now: datetime) -> JobRecord: ...


class EventRepository(Protocol):
    def add(self, run_id: UUID, sequence: int, event: Event) -> None: ...

    def get(self, event_id: UUID) -> Event | None: ...


class SceneRepository(Protocol):
    def add_generated(self, run_id: UUID, record: GeneratedSceneRecord) -> None: ...

    def get(self, scene_id: UUID) -> GeneratedSceneRecord | None: ...


class MemoryRepository(Protocol):
    def add(self, run_id: UUID, memory: Memory) -> None: ...

    def find_by_source(
        self,
        run_id: UUID,
        character_id: UUID,
        *,
        event_id: UUID | None = None,
        claim_id: UUID | None = None,
    ) -> Memory | None: ...

    def list_for_character(self, run_id: UUID, character_id: UUID) -> tuple[Memory, ...]: ...


class BeliefRepository(Protocol):
    def add_evidence(self, run_id: UUID, evidence: Evidence) -> None: ...

    def add_version(self, run_id: UUID, belief: Belief) -> None: ...

    def get_current(self, run_id: UUID, character_id: UUID, claim_id: UUID) -> Belief | None: ...

    def list_evidence(self, run_id: UUID, belief: Belief) -> tuple[Evidence, ...]: ...


class ArtifactRepository(Protocol):
    def public_source_dates(self, run_id: UUID) -> tuple[date, ...]: ...

    def recap_sources(self, run_id: UUID, story_date: date) -> tuple[RecapSource, ...]: ...

    def published_recap_dates(self, run_id: UUID) -> frozenset[date]: ...

    def get_daily_recap(self, run_id: UUID, story_date: date) -> tuple[UUID, DailyRecap] | None: ...

    def add_daily_recap(
        self,
        run_id: UUID,
        *,
        artifact_id: UUID,
        story_date: date,
        published_at: datetime,
        recap: DailyRecap,
    ) -> None: ...


class UnitOfWork(Protocol):
    @property
    def worlds(self) -> WorldRepository: ...

    @property
    def runs(self) -> RunRepository: ...

    @property
    def events(self) -> EventRepository: ...

    @property
    def jobs(self) -> JobRepository: ...

    @property
    def scenes(self) -> SceneRepository: ...

    @property
    def memories(self) -> MemoryRepository: ...

    @property
    def beliefs(self) -> BeliefRepository: ...

    @property
    def artifacts(self) -> ArtifactRepository: ...

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
