"""FastAPI application entrypoint and stable simulation service API."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Generic, Literal, TypeVar
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from rumor_mill.adapters.persistence import (
    SqlAlchemyUnitOfWork,
    create_database_engine,
    create_session_factory,
)
from rumor_mill.adapters.persistence.models import ArtifactModel, ConversationModel
from rumor_mill.config import Settings, get_settings
from rumor_mill.engine.ports import ClockMode, RunRecord, RunStatus, WorldRecord
from rumor_mill.engine.recap import DailyRecap, RecapSource, build_daily_recap
from rumor_mill.engine.scheduling import SimulationScheduler
from rumor_mill.worlds.authoring import WorldDefinition

T = TypeVar("T")


class HealthResponse(BaseModel):
    """Health-check response schema."""

    status: Literal["ok"]
    environment: str


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Page(ApiModel, Generic[T]):
    items: list[T]
    offset: int
    limit: int
    total: int


class InitializeRunRequest(ApiModel):
    definition: WorldDefinition
    seed: int = 0
    clock_mode: ClockMode = ClockMode.WALL
    clock_rate: float = Field(default=1, gt=0)
    tick_seconds: int = Field(default=300, gt=0)
    max_catch_up_ticks: int = Field(default=12, gt=0)


class RunResponse(ApiModel):
    id: UUID
    world_id: UUID
    status: RunStatus
    seed: int
    clock_mode: ClockMode
    simulation_time: datetime
    started_at: datetime

    @classmethod
    def from_record(cls, run: RunRecord) -> "RunResponse":
        return cls(
            id=run.id,
            world_id=run.world_id,
            status=run.status,
            seed=run.seed,
            clock_mode=run.clock_mode,
            simulation_time=run.simulation_time or run.started_at,
            started_at=run.started_at,
        )


class TickRequest(ApiModel):
    ticks: int = Field(default=1, ge=1, le=100)


class TickResponse(ApiModel):
    previous_time: datetime
    simulation_time: datetime
    ticks: int
    jobs_enqueued: int
    catch_up_limited: bool


class TownStatusResponse(ApiModel):
    run_id: UUID
    simulation_time: datetime
    status: RunStatus
    character_count: int
    location_count: int


class LocationResponse(ApiModel):
    id: str
    name: str
    description: str
    parent_location_id: str | None


class CharacterResponse(ApiModel):
    id: str
    name: str
    description: str
    location_id: str | None


class StartConversationRequest(ApiModel):
    character_id: str = Field(min_length=1, max_length=80)


class ConversationMessage(ApiModel):
    role: Literal["visitor", "character"]
    content: str = Field(min_length=1, max_length=4_000)
    created_at: datetime


class AddMessageRequest(ApiModel):
    content: str = Field(min_length=1, max_length=4_000)


class ConversationResponse(ApiModel):
    id: UUID
    run_id: UUID
    character_id: str
    visitor_id: UUID
    started_at: datetime
    messages: list[ConversationMessage]


class EpisodeResponse(ApiModel):
    id: UUID
    kind: str
    title: str
    body: str
    generated_at: datetime


class GenerateRecapRequest(ApiModel):
    force: bool = False


class EditRecapRequest(ApiModel):
    headline: str = Field(min_length=1, max_length=200)
    dek: str = Field(min_length=1, max_length=500)


class DailyRecapResponse(ApiModel):
    id: UUID
    generated_at: datetime
    edited: bool
    recap: DailyRecap


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def create_app(
    settings: Settings | None = None,
    session_factory: sessionmaker[Session] | None = None,
) -> FastAPI:
    """Build and configure the application."""
    settings = settings or get_settings()
    if session_factory is None:
        engine = create_database_engine(settings.database_url)
        session_factory = create_session_factory(engine)
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description="Stable application-facing API for Rumor Mill simulations.",
    )
    web_root = Path(__file__).with_name("web")
    app.mount("/static", StaticFiles(directory=web_root / "static"), name="static")
    bearer = HTTPBearer(auto_error=False)

    def uow_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory)

    def session() -> Any:
        database = session_factory()
        try:
            yield database
        finally:
            database.close()

    def require_operator(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> None:
        expected = settings.operator_api_key
        if expected is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "operator API is disabled")
        if credentials is None or credentials.credentials != expected.get_secret_value():
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid operator credentials")

    def require_visitor(x_visitor_id: Annotated[str | None, Header()] = None) -> UUID:
        if x_visitor_id is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "X-Visitor-ID is required")
        try:
            return UUID(x_visitor_id)
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "X-Visitor-ID must be a UUID"
            ) from exc

    def load_run(run_id: UUID) -> tuple[RunRecord, WorldDefinition]:
        with uow_factory() as unit_of_work:
            run = unit_of_work.runs.get(run_id)
            if run is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "run not found")
            world = unit_of_work.worlds.get(run.world_id)
            if world is None:  # pragma: no cover - protected by the run FK
                raise HTTPException(status.HTTP_404_NOT_FOUND, "world not found")
            return run, WorldDefinition.model_validate(world.definition)

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", environment=settings.environment)

    @app.get("/lighthouse", response_class=HTMLResponse, include_in_schema=False)
    def lighthouse() -> HTMLResponse:
        """Render the public, server-first Lighthouse story shell."""
        return HTMLResponse((web_root / "lighthouse.html").read_text(encoding="utf-8"))

    @app.get("/lighthouse/today", response_class=HTMLResponse, include_in_schema=False)
    def lighthouse_today() -> HTMLResponse:
        """Render the latest spoiler-safe daily briefing without requiring JavaScript."""
        return HTMLResponse((web_root / "today.html").read_text(encoding="utf-8"))

    @app.get("/api/v1/health", response_model=HealthResponse, tags=["system"])
    def api_health(database: Annotated[Session, Depends(session)]) -> HealthResponse:
        database.execute(text("SELECT 1"))
        return HealthResponse(status="ok", environment=settings.environment)

    @app.post(
        "/api/v1/worlds/{slug}/runs",
        response_model=RunResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_operator)],
        tags=["runs"],
    )
    def initialize_run(slug: str, request: InitializeRunRequest) -> RunResponse:
        if slug != request.definition.metadata.id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "slug must match metadata.id")
        now = datetime.now(UTC)
        world = WorldRecord(uuid4(), slug, 1, request.definition.model_dump(mode="json"), now)
        run = RunRecord(
            uuid4(),
            world.id,
            RunStatus.RUNNING,
            request.seed,
            now,
            clock_mode=request.clock_mode,
            clock_rate=request.clock_rate,
            tick_seconds=request.tick_seconds,
            max_catch_up_ticks=request.max_catch_up_ticks,
        )
        try:
            with uow_factory() as unit_of_work:
                existing = unit_of_work.worlds.get_by_slug(slug)
                if existing is None:
                    unit_of_work.worlds.add(world)
                    unit_of_work.flush()
                else:
                    world = existing
                    run = RunRecord(
                        run.id,
                        world.id,
                        run.status,
                        run.seed,
                        run.started_at,
                        clock_mode=run.clock_mode,
                        clock_rate=run.clock_rate,
                        tick_seconds=run.tick_seconds,
                        max_catch_up_ticks=run.max_catch_up_ticks,
                    )
                unit_of_work.runs.add(run)
                unit_of_work.commit()
        except IntegrityError as exc:  # pragma: no cover - concurrent-create safeguard
            raise HTTPException(
                status.HTTP_409_CONFLICT, "world initialization conflicted"
            ) from exc
        return RunResponse.from_record(run)

    @app.get("/api/v1/runs/{run_id}", response_model=RunResponse, tags=["runs"])
    def get_run(run_id: UUID) -> RunResponse:
        run, _ = load_run(run_id)
        return RunResponse.from_record(run)

    @app.post(
        "/api/v1/runs/{run_id}/ticks",
        response_model=TickResponse,
        dependencies=[Depends(require_operator)],
        tags=["runs"],
    )
    def tick(run_id: UUID, request: TickRequest) -> TickResponse:
        try:
            result = SimulationScheduler(uow_factory).advance(run_id, manual_ticks=request.ticks)
        except LookupError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "run not found") from exc
        return TickResponse(
            previous_time=result.previous_time,
            simulation_time=result.simulation_time,
            ticks=result.ticks,
            jobs_enqueued=result.jobs_enqueued,
            catch_up_limited=result.catch_up_limited,
        )

    @app.get("/api/v1/runs/{run_id}/town", response_model=TownStatusResponse, tags=["town"])
    def town_status(run_id: UUID) -> TownStatusResponse:
        run, world = load_run(run_id)
        return TownStatusResponse(
            run_id=run.id,
            simulation_time=run.simulation_time or run.started_at,
            status=run.status,
            character_count=len(world.cast),
            location_count=len(world.locations),
        )

    @app.get(
        "/api/v1/runs/{run_id}/locations", response_model=Page[LocationResponse], tags=["town"]
    )
    def locations(
        run_id: UUID,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> Page[LocationResponse]:
        _, world = load_run(run_id)
        records = [
            LocationResponse(
                id=item.id,
                name=item.name,
                description=item.description,
                parent_location_id=item.parent_location_id,
            )
            for item in world.locations
        ]
        return Page(
            items=records[offset : offset + limit], offset=offset, limit=limit, total=len(records)
        )

    @app.get(
        "/api/v1/runs/{run_id}/characters",
        response_model=Page[CharacterResponse],
        tags=["town"],
    )
    def characters(
        run_id: UUID,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> Page[CharacterResponse]:
        _, world = load_run(run_id)
        records = [
            CharacterResponse(
                id=item.id,
                name=item.name,
                description=item.description,
                location_id=item.home_location_id,
            )
            for item in world.cast
        ]
        return Page(
            items=records[offset : offset + limit], offset=offset, limit=limit, total=len(records)
        )

    def conversation_response(model: ConversationModel, visitor_id: UUID) -> ConversationResponse:
        return ConversationResponse(
            id=model.id,
            run_id=model.run_id,
            character_id=model.participant_ids[0],
            visitor_id=visitor_id,
            started_at=_aware(model.started_at),
            messages=[ConversationMessage.model_validate(item) for item in model.transcript],
        )

    @app.post(
        "/api/v1/runs/{run_id}/conversations",
        response_model=ConversationResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["conversations"],
    )
    def start_conversation(
        run_id: UUID,
        request: StartConversationRequest,
        visitor_id: Annotated[UUID, Depends(require_visitor)],
        database: Annotated[Session, Depends(session)],
    ) -> ConversationResponse:
        _, world = load_run(run_id)
        if request.character_id not in {item.id for item in world.cast}:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "character not found")
        model = ConversationModel(
            run_id=run_id,
            started_at=datetime.now(UTC),
            participant_ids=[request.character_id, str(visitor_id)],
            transcript=[],
        )
        database.add(model)
        database.commit()
        database.refresh(model)
        return conversation_response(model, visitor_id)

    def owned_conversation(
        conversation_id: UUID, visitor_id: UUID, database: Session
    ) -> ConversationModel:
        model = database.get(ConversationModel, conversation_id)
        if model is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
        if len(model.participant_ids) < 2 or model.participant_ids[1] != str(visitor_id):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "conversation belongs to another visitor"
            )
        return model

    @app.get(
        "/api/v1/conversations/{conversation_id}",
        response_model=ConversationResponse,
        tags=["conversations"],
    )
    def get_conversation(
        conversation_id: UUID,
        visitor_id: Annotated[UUID, Depends(require_visitor)],
        database: Annotated[Session, Depends(session)],
    ) -> ConversationResponse:
        return conversation_response(
            owned_conversation(conversation_id, visitor_id, database), visitor_id
        )

    @app.post(
        "/api/v1/conversations/{conversation_id}/messages",
        response_model=ConversationResponse,
        tags=["conversations"],
    )
    def add_message(
        conversation_id: UUID,
        request: AddMessageRequest,
        visitor_id: Annotated[UUID, Depends(require_visitor)],
        database: Annotated[Session, Depends(session)],
    ) -> ConversationResponse:
        model = owned_conversation(conversation_id, visitor_id, database)
        transcript = list(model.transcript)
        transcript.append(
            ConversationMessage(
                role="visitor", content=request.content, created_at=datetime.now(UTC)
            ).model_dump(mode="json")
        )
        model.transcript = transcript
        database.commit()
        database.refresh(model)
        return conversation_response(model, visitor_id)

    @app.get(
        "/api/v1/runs/{run_id}/episodes",
        response_model=Page[EpisodeResponse],
        tags=["episodes"],
    )
    def episodes(
        run_id: UUID,
        database: Annotated[Session, Depends(session)],
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> Page[EpisodeResponse]:
        load_run(run_id)
        models = list(
            database.scalars(
                select(ArtifactModel)
                .where(ArtifactModel.run_id == run_id)
                .order_by(ArtifactModel.generated_at.desc(), ArtifactModel.id)
            )
        )
        records = [
            EpisodeResponse(
                id=item.id,
                kind=item.kind,
                title=item.title,
                body=item.body,
                generated_at=_aware(item.generated_at),
            )
            for item in models
            if item.payload.get("visibility", "public") == "public"
        ]
        return Page(
            items=records[offset : offset + limit], offset=offset, limit=limit, total=len(records)
        )

    def recap_response(model: ArtifactModel) -> DailyRecapResponse:
        return DailyRecapResponse(
            id=model.id,
            generated_at=_aware(model.generated_at),
            edited=bool(model.payload.get("edited", False)),
            recap=DailyRecap.model_validate(model.payload["recap"]),
        )

    def cached_recap(database: Session, run_id: UUID, story_date: str) -> ArtifactModel | None:
        candidates = database.scalars(
            select(ArtifactModel)
            .where(ArtifactModel.run_id == run_id, ArtifactModel.kind == "daily_recap")
            .order_by(ArtifactModel.generated_at.desc())
        )
        return next(
            (
                item
                for item in candidates
                if item.payload.get("recap", {}).get("story_date") == story_date
            ),
            None,
        )

    @app.get(
        "/api/v1/runs/{run_id}/recaps/today",
        response_model=DailyRecapResponse,
        tags=["episodes"],
    )
    def today_recap(
        run_id: UUID, database: Annotated[Session, Depends(session)]
    ) -> DailyRecapResponse:
        run, _ = load_run(run_id)
        story_date = (run.simulation_time or run.started_at).date().isoformat()
        model = cached_recap(database, run_id, story_date)
        if model is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "today's recap has not been generated")
        return recap_response(model)

    @app.post(
        "/api/v1/runs/{run_id}/recaps/daily",
        response_model=DailyRecapResponse,
        dependencies=[Depends(require_operator)],
        tags=["episodes"],
    )
    def generate_daily_recap(
        run_id: UUID,
        request: GenerateRecapRequest,
        database: Annotated[Session, Depends(session)],
    ) -> DailyRecapResponse:
        run, _ = load_run(run_id)
        story_date = (run.simulation_time or run.started_at).date()
        existing = cached_recap(database, run_id, story_date.isoformat())
        if existing is not None and not request.force:
            return recap_response(existing)

        models = list(
            database.scalars(
                select(ArtifactModel)
                .where(
                    ArtifactModel.run_id == run_id,
                    ArtifactModel.kind != "daily_recap",
                )
                .order_by(ArtifactModel.generated_at.desc())
            )
        )
        sources = [
            RecapSource(
                id=item.id,
                kind=item.kind,
                title=item.title,
                body=item.body,
                generated_at=_aware(item.generated_at),
                visibility=item.payload.get("visibility", "public"),
                importance=item.payload.get("importance", 1),
                location_id=item.payload.get("location_id"),
                character_id=item.payload.get("character_id"),
                active_thread=item.payload.get("active_thread"),
            )
            for item in models
            if _aware(item.generated_at).date() == story_date
        ]
        recap = build_daily_recap(story_date, sources)
        if existing is not None:
            database.delete(existing)
            database.flush()
        model = ArtifactModel(
            run_id=run_id,
            kind="daily_recap",
            title=recap.headline,
            body=recap.dek,
            generated_at=datetime.now(UTC),
            source_ids=[str(panel.source_id) for panel in recap.panels],
            payload=recap.artifact_payload(),
        )
        database.add(model)
        database.commit()
        database.refresh(model)
        return recap_response(model)

    @app.patch(
        "/api/v1/recaps/{recap_id}",
        response_model=DailyRecapResponse,
        dependencies=[Depends(require_operator)],
        tags=["episodes"],
    )
    def edit_daily_recap(
        recap_id: UUID,
        request: EditRecapRequest,
        database: Annotated[Session, Depends(session)],
    ) -> DailyRecapResponse:
        model = database.get(ArtifactModel, recap_id)
        if model is None or model.kind != "daily_recap":
            raise HTTPException(status.HTTP_404_NOT_FOUND, "recap not found")
        recap = DailyRecap.model_validate(model.payload["recap"]).model_copy(
            update={"headline": request.headline, "dek": request.dek}
        )
        model.title = recap.headline
        model.body = recap.dek
        model.payload = {**recap.artifact_payload(), "edited": True}
        database.commit()
        database.refresh(model)
        return recap_response(model)

    return app


app = create_app()
