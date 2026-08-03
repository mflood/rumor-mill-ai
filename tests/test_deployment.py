"""Heroku process, worker, and smoke-check contracts."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Self
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

from rumor_mill.adapters.persistence import (
    SqlAlchemyUnitOfWork,
    create_database_engine,
    create_session_factory,
    seed_run,
)
from rumor_mill.adapters.persistence.models import (
    ArtifactModel,
    JobModel,
    RunModel,
    SceneModel,
    WorkerHeartbeatModel,
    WorldModel,
)
from rumor_mill.adapters.providers import DeterministicFakeProvider
from rumor_mill.bootstrap import _bootstrap_session
from rumor_mill.config import Settings
from rumor_mill.deployment import smoke
from rumor_mill.engine.lighthouse_pipeline import LighthouseStoryHandler, RoutineTimeError
from rumor_mill.engine.ports import JobRecord, JobStatus, RunRecord, RunStatus, WorldRecord
from rumor_mill.main import create_app
from rumor_mill.observability import MetricsRegistry
from rumor_mill.worker import SimulationWorker, main, worker_id
from rumor_mill.worlds import load_world

ROOT = Path(__file__).parents[1]
START = datetime(2026, 8, 2, 12, tzinfo=UTC)


def test_heroku_manifests_declare_release_web_worker_and_uv_runtime() -> None:
    procfile = (ROOT / "Procfile").read_text()
    assert "release: alembic upgrade head" in procfile
    assert "web: uvicorn rumor_mill.main:app" in procfile
    assert "--port $PORT" in procfile
    assert "worker: python -m rumor_mill.worker" in procfile
    assert (ROOT / ".python-version").read_text().strip() == "3.13"
    manifest = json.loads((ROOT / "app.json").read_text())
    assert manifest["formation"] == {"web": {"quantity": 1}, "worker": {"quantity": 1}}
    assert manifest["addons"][0]["plan"].startswith("heroku-postgresql:")


def test_settings_accept_heroku_database_url(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("RUMOR_MILL_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgres://managed.example/rumor_mill")
    assert Settings(_env_file=None).database_url == "postgres://managed.example/rumor_mill"


def test_production_metrics_require_dedicated_bearer_credentials(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'metrics-auth.db'}"
    engine = create_database_engine(url)
    from rumor_mill.adapters.persistence.models import Base

    Base.metadata.create_all(engine)
    with TestClient(
        create_app(
            Settings(
                database_url=url,
                environment="production",
                metrics_api_key=SecretStr("metrics-secret"),
            ),
            create_session_factory(engine),
        )
    ) as client:
        for headers in ({}, {"Authorization": "Bearer wrong-secret"}):
            response = client.get("/metrics", headers=headers)
            assert response.status_code == 401
            assert "rumor_mill_" not in response.text

        authorized = client.get("/metrics", headers={"Authorization": "Bearer metrics-secret"})
        assert authorized.status_code == 200
        assert "rumor_mill_http_requests_total" in authorized.text

        health = client.get("/health/live")
        assert health.status_code == 200
        assert health.json() == {"status": "ok", "environment": "production"}
    engine.dispose()


def test_production_metrics_fail_closed_without_a_configured_key(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'metrics-disabled.db'}"
    engine = create_database_engine(url)
    from rumor_mill.adapters.persistence.models import Base

    Base.metadata.create_all(engine)
    with TestClient(
        create_app(
            Settings(database_url=url, environment="production"),
            create_session_factory(engine),
        )
    ) as client:
        response = client.get("/metrics")
        assert response.status_code == 503
        assert "rumor_mill_" not in response.text
    engine.dispose()


def test_worker_heartbeats_and_advances_persisted_runs(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'worker.db'}"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    engine = create_database_engine(url)
    factory = create_session_factory(engine)
    world = WorldRecord(UUID(int=1), "worker-world", 1, {}, START)
    run = RunRecord(
        UUID(int=2),
        world.id,
        RunStatus.RUNNING,
        7,
        START,
        tick_seconds=300,
        max_catch_up_ticks=3,
    )
    seed_run(SqlAlchemyUnitOfWork(factory), world, run)

    now = START + timedelta(minutes=30)
    worker = SimulationWorker(factory, worker_id="worker.1", clock=lambda: now)
    assert worker.poll_once() == 1
    assert worker.poll_once() == 0

    with factory() as database:
        stored = database.get(RunModel, run.id)
        heartbeat = database.scalar(select(WorkerHeartbeatModel))
        assert stored is not None
        assert stored.simulation_time.replace(tzinfo=UTC) == START + timedelta(minutes=15)
        assert heartbeat is not None
        assert heartbeat.worker_id == "worker.1"
        assert heartbeat.last_seen_at.replace(tzinfo=UTC) == now
    engine.dispose()


def test_production_readiness_requires_a_worker_heartbeat(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'readiness.db'}"
    engine = create_database_engine(url)
    from rumor_mill.adapters.persistence.models import Base

    Base.metadata.create_all(engine)
    client = TestClient(
        create_app(
            Settings(database_url=url, environment="production"),
            create_session_factory(engine),
        )
    )
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["components"]["worker"] == "degraded"
    with create_session_factory(engine).begin() as database:
        database.add(
            WorkerHeartbeatModel(
                worker_id="stale-worker",
                last_seen_at=datetime.now(UTC) - timedelta(hours=1),
            )
        )
    stale = client.get("/health/ready")
    assert stale.status_code == 503
    assert stale.json()["components"]["worker"] == "degraded"
    with create_session_factory(engine).begin() as database:
        heartbeat = database.get(WorkerHeartbeatModel, "stale-worker")
        assert heartbeat is not None
        heartbeat.last_seen_at = datetime.now(UTC)
        heartbeat.story_pipeline_ready = True
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json()["components"]["worker"] == "ok"
    assert ready.json()["components"]["story_pipeline"] == "ok"
    engine.dispose()


def test_story_pipeline_readiness_detects_non_progressing_clock(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'stalled-pipeline.db'}"
    engine = create_database_engine(url)
    from rumor_mill.adapters.persistence.models import Base

    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    definition = json.loads((ROOT / "docs/worlds/lighthouse/world.json").read_text())
    now = datetime.now(UTC)
    with factory.begin() as database:
        result = _bootstrap_session(database, definition)
        run = database.get(RunModel, result.run_id)
        assert run is not None
        run.started_at = now - timedelta(hours=1)
        database.add(
            WorkerHeartbeatModel(
                worker_id="worker.stalled",
                last_seen_at=now,
                story_pipeline_ready=True,
                last_clock_advanced_at=now - timedelta(hours=1),
            )
        )
    client = TestClient(
        create_app(
            Settings(
                database_url=url,
                environment="production",
                story_pipeline_stale_after_seconds=300,
            ),
            factory,
        )
    )

    stalled = client.get("/health/ready")
    assert stalled.status_code == 503
    assert stalled.json()["components"]["worker"] == "ok"
    assert stalled.json()["components"]["story_pipeline"] == "degraded"

    with factory.begin() as database:
        heartbeat = database.get(WorkerHeartbeatModel, "worker.stalled")
        assert heartbeat is not None
        heartbeat.last_clock_advanced_at = datetime.now(UTC)
    assert client.get("/health/ready").status_code == 200
    engine.dispose()


def test_production_shaped_bootstrap_advances_executes_and_publishes_once(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'autonomous-story.db'}"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    engine = create_database_engine(url)
    factory = create_session_factory(engine)
    definition = load_world(ROOT / "docs/worlds/lighthouse/world.json").model_dump(mode="json")
    assert definition["routines"][0]["start_time"] == "05:30:00"
    with factory.begin() as database:
        bootstrapped = _bootstrap_session(database, definition)
        run = database.get(RunModel, bootstrapped.run_id)
        assert run is not None
        started_at = run.started_at.replace(tzinfo=UTC)

    now = started_at + timedelta(minutes=10)
    worker = SimulationWorker(
        factory, worker_id="worker.story", run_batch_size=1, clock=lambda: now
    )
    assert worker.poll_once() == 1
    assert worker.poll_once() == 0

    with factory() as database:
        jobs = list(
            database.scalars(select(JobModel).where(JobModel.run_id == bootstrapped.run_id))
        )
        artifacts = list(
            database.scalars(
                select(ArtifactModel).where(ArtifactModel.run_id == bootstrapped.run_id)
            )
        )
        scenes = list(
            database.scalars(select(SceneModel).where(SceneModel.run_id == bootstrapped.run_id))
        )
        heartbeat = database.get(WorkerHeartbeatModel, "worker.story")
        assert len(jobs) == 1
        assert jobs[0].status == "completed"
        assert len(scenes) == 1
        assert len(artifacts) == 1
        assert artifacts[0].kind == "story_card"
        assert artifacts[0].title == "Dark Headland"
        assert heartbeat is not None and heartbeat.story_pipeline_ready
        assert heartbeat.last_clock_advanced_at is not None
        assert heartbeat.last_story_job_enqueued_at is not None
        assert heartbeat.last_story_job_completed_at is not None
        assert heartbeat.story_queue_depth == 0
    engine.dispose()


def test_worker_executes_authored_routine_output(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'autonomous-routine.db'}"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    engine = create_database_engine(url)
    factory = create_session_factory(engine)
    definition = load_world(ROOT / "docs/worlds/lighthouse/world.json").model_dump(mode="json")
    with factory.begin() as database:
        bootstrapped = _bootstrap_session(database, definition)
        run = database.get(RunModel, bootstrapped.run_id)
        assert run is not None
        run.max_catch_up_ticks = 100
        started_at = run.started_at.replace(tzinfo=UTC)

    worker = SimulationWorker(
        factory,
        worker_id="worker.routine",
        clock=lambda: started_at + timedelta(hours=5, minutes=35),
    )
    assert worker.poll_once() == 1
    with factory() as database:
        titles = set(
            database.scalars(
                select(ArtifactModel.title).where(ArtifactModel.run_id == bootstrapped.run_id)
            )
        )
        assert "Dark Headland" in titles
        assert "Dawn lighthouse work." in titles
    engine.dispose()


def test_worker_uses_provider_outside_completion_and_reports_job_metrics(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'provider-story.db'}"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    engine = create_database_engine(url)
    factory = create_session_factory(engine)
    definition = json.loads((ROOT / "docs/worlds/lighthouse/world.json").read_text())
    with factory.begin() as database:
        bootstrapped = _bootstrap_session(database, definition)
        run = database.get(RunModel, bootstrapped.run_id)
        assert run is not None
        started_at = run.started_at.replace(tzinfo=UTC)

    provider = DeterministicFakeProvider(
        {
            "off_screen_scene": {
                "title": "Generated at the headland",
                "duration_minutes": 5,
                "events": [{"summary": "The lamp remains dark."}],
                "presentation_hooks": [
                    {
                        "kind": "story_card",
                        "title": "Generated at the headland",
                        "body": "The scheduled beat reaches Greyhaven.",
                        "event_indexes": [0],
                    }
                ],
            }
        }
    )
    metrics = MetricsRegistry()
    worker = SimulationWorker(
        factory,
        worker_id="worker.provider",
        run_batch_size=1,
        job_batch_size=1,
        provider=provider,
        metrics=metrics,
        clock=lambda: started_at + timedelta(minutes=10),
    )

    assert worker.poll_once() == 1
    with factory() as database:
        job = database.scalar(select(JobModel).where(JobModel.run_id == bootstrapped.run_id))
        artifact = database.scalar(
            select(ArtifactModel).where(ArtifactModel.run_id == bootstrapped.run_id)
        )
        assert job is not None and job.status == "completed"
        assert artifact is not None and artifact.title == "Generated at the headland"
    rendered = metrics.render()
    assert 'rumor_mill_story_jobs_total{state="claimed"} 1' in rendered
    assert 'rumor_mill_story_jobs_total{state="completed"} 1' in rendered
    assert "The lamp remains dark" not in rendered
    engine.dispose()


def test_story_job_failure_leaves_pipeline_fresh_for_retry(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    url = f"sqlite:///{tmp_path / 'story-retry.db'}"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    engine = create_database_engine(url)
    factory = create_session_factory(engine)
    definition = json.loads((ROOT / "docs/worlds/lighthouse/world.json").read_text())
    with factory.begin() as database:
        bootstrapped = _bootstrap_session(database, definition)
        run = database.get(RunModel, bootstrapped.run_id)
        assert run is not None
        started_at = run.started_at.replace(tzinfo=UTC)

    def broken_handlers():  # type: ignore[no-untyped-def]
        def broken(job):  # type: ignore[no-untyped-def]
            del job
            raise RuntimeError("story provider unavailable")

        return {"lighthouse_story": broken}

    monkeypatch.setattr("rumor_mill.worker.lighthouse_handlers", broken_handlers)
    worker = SimulationWorker(
        factory,
        worker_id="worker.retry",
        clock=lambda: started_at + timedelta(minutes=10),
    )
    assert worker.poll_once() == 1
    with factory() as database:
        job = database.scalar(select(JobModel).where(JobModel.run_id == bootstrapped.run_id))
        heartbeat = database.get(WorkerHeartbeatModel, "worker.retry")
        assert job is not None and job.status == "failed"
        assert heartbeat is not None and heartbeat.story_pipeline_ready
        assert heartbeat.last_story_job_completed_at is None
    engine.dispose()


def test_story_mutation_rejects_a_deleted_run(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'deleted-run.db'}"
    engine = create_database_engine(url)
    from rumor_mill.adapters.persistence.models import Base

    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    missing_run_id = uuid4()
    job = JobRecord(
        id=uuid4(),
        run_id=missing_run_id,
        idempotency_key="deleted-run-story",
        kind="lighthouse_story",
        status=JobStatus.RUNNING,
        scheduled_at=START,
        payload={
            "story_kind": "beat",
            "id": "missing",
            "title": "Missing run",
            "summary": "This output cannot be committed.",
            "character_ids": [],
            "location_id": "northlight",
        },
    )
    mutation = LighthouseStoryHandler()(job)
    with (
        SqlAlchemyUnitOfWork(factory) as unit_of_work,
        pytest.raises(LookupError, match=str(missing_run_id)),
    ):
        mutation(unit_of_work)
    engine.dispose()


def test_story_handler_requires_provider_and_storage_together() -> None:
    provider = DeterministicFakeProvider({})
    with pytest.raises(ValueError, match="configured together"):
        LighthouseStoryHandler(provider)


def test_product_readiness_requires_valid_running_lighthouse_season(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'product-readiness.db'}"
    engine = create_database_engine(url)
    from rumor_mill.adapters.persistence.models import Base

    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    client = TestClient(create_app(Settings(database_url=url), factory))

    # Infrastructure remains ready even when the public product is not playable.
    assert client.get("/health/ready").status_code == 200
    missing = client.get("/health/product")
    assert missing.status_code == 503
    assert missing.json()["reason"] == "missing_world"

    definition = json.loads((ROOT / "docs/worlds/lighthouse/world.json").read_text())
    with factory.begin() as database:
        result = _bootstrap_session(database, definition)
    ready = client.get("/health/product")
    assert ready.status_code == 200
    assert ready.json()["playable_story_available"] is True
    assert "rumor_mill_playable_story_available 1" in client.get("/metrics").text

    with factory.begin() as database:
        run = database.get(RunModel, result.run_id)
        assert run is not None
        run.status = "paused"
    paused = client.get("/health/product")
    assert paused.status_code == 503
    assert paused.json()["reason"] == "no_running_season"
    engine.dispose()


@pytest.mark.parametrize("malformed", [True, False])
def test_product_readiness_rejects_invalid_lighthouse_world(
    tmp_path: Path, malformed: bool
) -> None:
    url = f"sqlite:///{tmp_path / f'invalid-{malformed}.db'}"
    engine = create_database_engine(url)
    from rumor_mill.adapters.persistence.models import Base

    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    definition = json.loads((ROOT / "docs/worlds/lighthouse/world.json").read_text())
    if malformed:
        definition = {"schema_version": 1}
    else:
        overlapping = dict(definition["routines"][0])
        overlapping["id"] = "overlapping-routine"
        definition["routines"].append(overlapping)
    with factory.begin() as database:
        database.add(WorldModel(slug="lighthouse", schema_version=1, definition=definition))

    response = TestClient(create_app(Settings(database_url=url), factory)).get("/health/product")
    assert response.status_code == 503
    assert response.json()["reason"] == "invalid_world"
    engine.dispose()


def test_worker_continues_after_run_and_poll_failures(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    url = f"sqlite:///{tmp_path / 'failures.db'}"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    engine = create_database_engine(url)
    factory = create_session_factory(engine)
    world = WorldRecord(UUID(int=11), "failure-world", 1, {}, START)
    run = RunRecord(UUID(int=12), world.id, RunStatus.RUNNING, 1, START)
    seed_run(SqlAlchemyUnitOfWork(factory), world, run)
    worker = SimulationWorker(factory, worker_id="worker.failure", clock=lambda: START)
    monkeypatch.setattr(
        "rumor_mill.worker.SimulationScheduler.advance",
        lambda self, run_id: (_ for _ in ()).throw(RuntimeError(str(run_id))),
    )
    assert worker.poll_once() == 0

    class StopAfterWait:
        stopped = False

        def is_set(self) -> bool:
            return self.stopped

        def wait(self, seconds: float) -> None:
            assert seconds == 5.0
            self.stopped = True

    monkeypatch.setattr(worker, "poll_once", lambda: (_ for _ in ()).throw(RuntimeError("db")))
    worker.run_forever(StopAfterWait())  # type: ignore[arg-type]
    engine.dispose()


def test_worker_logs_safe_actionable_routine_time_failure(  # type: ignore[no-untyped-def]
    tmp_path: Path, monkeypatch
) -> None:
    url = f"sqlite:///{tmp_path / 'routine-time-failure.db'}"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    engine = create_database_engine(url)
    factory = create_session_factory(engine)
    world = WorldRecord(UUID(int=11), "lighthouse", 1, {}, START)
    run = RunRecord(UUID(int=12), world.id, RunStatus.RUNNING, 1, START)
    seed_run(SqlAlchemyUnitOfWork(factory), world, run)
    worker = SimulationWorker(factory, worker_id="worker.routine-failure", clock=lambda: START)
    monkeypatch.setattr(
        "rumor_mill.worker.SimulationScheduler.advance",
        lambda self, run_id: (_ for _ in ()).throw(
            RoutineTimeError("routine start_time must be a valid ISO local time")
        ),
    )
    logged: dict[str, object] = {}
    monkeypatch.setattr(
        "rumor_mill.worker.logger.exception",
        lambda event, *, extra: logged.update(event=event, **extra),
    )

    assert worker.poll_once() == 0
    assert logged == {
        "event": "simulation_run_advance_failed",
        "run_id": str(run.id),
        "exception_type": "RoutineTimeError",
        "error_detail": "routine start_time must be a valid ISO local time",
    }
    engine.dispose()


def test_worker_entrypoint_configuration_and_identity(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DYNO", "worker.9")
    assert worker_id() == "worker.9"
    monkeypatch.delenv("DYNO")
    monkeypatch.setattr("rumor_mill.worker.socket.gethostname", lambda: "local-host")
    assert worker_id() == "local-host"

    configured: list[object] = []

    class FakeWorker:
        def __init__(self, factory, **kwargs) -> None:  # type: ignore[no-untyped-def]
            configured.append((factory, kwargs))

        def run_forever(self) -> None:
            configured.append("ran")

    sentinel_factory = object()
    settings = Settings(database_url="sqlite+pysqlite:///:memory:")
    monkeypatch.setattr(
        "rumor_mill.worker.configure_json_logging", lambda: configured.append("logs")
    )
    monkeypatch.setattr("rumor_mill.worker.create_database_engine", lambda url: url)
    monkeypatch.setattr("rumor_mill.worker.create_session_factory", lambda engine: sentinel_factory)
    monkeypatch.setattr("rumor_mill.worker.SimulationWorker", FakeWorker)
    monkeypatch.setattr("rumor_mill.worker.get_settings", lambda: settings)
    main(settings)
    main()
    assert configured.count("ran") == 2

    already_stopped = __import__("threading").Event()
    already_stopped.set()
    real_worker = SimulationWorker(  # factory is never touched because the event is already set
        sentinel_factory,  # type: ignore[arg-type]
        worker_id="stopped",
    )
    real_worker.run_forever(already_stopped)


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200, url: str = "") -> None:
        self.body = body
        self.status = status
        self.url = url

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback

    def read(self) -> bytes:
        return self.body

    def geturl(self) -> str:
        return self.url


def test_deployment_smoke_checks_health_assets_and_public_pages() -> None:
    requested: list[str] = []

    def open_fake(request: object, *, timeout: int) -> FakeResponse:
        assert timeout == 15
        url = request.full_url if hasattr(request, "full_url") else str(request)
        requested.append(url)
        if url.endswith("/health/ready"):
            body = b'{"status":"ok","components":{"story_pipeline":"ok"}}'
        elif url.endswith(("/health/live", "/health/product")):
            body = b'{"status":"ok"}'
        elif url.endswith("/lighthouse/feedback"):
            body = b"Share feedback on GitHub"
        elif url.endswith("/lighthouse/session"):
            return FakeResponse(
                b'property="og:title" data-primary-recommendation="true" '
                b'href="/lighthouse/runs/123/town/harbor"',
                url="https://rumor.example/lighthouse/today",
            )
        elif url.endswith("/lighthouse/runs/123/town/harbor"):
            body = b'data-playable-action="observe"'
        elif "/lighthouse" in url:
            body = b'property="og:title"'
        else:
            body = b"asset"
        return FakeResponse(body, url=url)

    smoke("https://rumor.example/", opener=open_fake)
    assert requested == [
        "https://rumor.example/health/live",
        "https://rumor.example/health/ready",
        "https://rumor.example/health/product",
        "https://rumor.example/static/lighthouse.css",
        "https://rumor.example/static/favicon.svg",
        "https://rumor.example/lighthouse",
        "https://rumor.example/lighthouse/feedback",
        "https://rumor.example/lighthouse/session",
        "https://rumor.example/lighthouse/runs/123/town/harbor",
    ]


def test_deployment_smoke_rejects_unhealthy_responses() -> None:
    def response(status: int, body: bytes) -> object:
        return FakeResponse(body, status)

    healthy_prefix = [
        response(200, b'{"status":"ok"}'),
        response(200, b'{"status":"ok","components":{"story_pipeline":"ok"}}'),
        response(200, b'{"status":"ok"}'),
        response(200, b"css"),
        response(200, b"svg"),
        response(200, b'property="og:title"'),
        response(200, b"Share feedback on GitHub"),
    ]
    ready = response(200, b'{"status":"ok","components":{"story_pipeline":"ok"}}')
    playable_today = (
        b'property="og:title" data-primary-recommendation="true" '
        b'href="/lighthouse/runs/123/town/harbor"'
    )
    for responses, message in (
        ([response(503, b"{}")], "/health/live returned HTTP 503"),
        ([response(200, b'{"status":"degraded"}')], "/health/live reported degraded"),
        (
            [response(200, b'{"status":"ok"}'), response(200, b'{"status":"ok"}')],
            "/health/ready did not verify autonomous story progression",
        ),
        (
            [
                response(200, b'{"status":"ok"}'),
                ready,
                response(200, b'{"status":"ok"}'),
                response(200, b""),
            ],
            "/static/lighthouse.css static asset smoke check failed",
        ),
        (
            [
                response(200, b'{"status":"ok"}'),
                ready,
                response(200, b'{"status":"ok"}'),
                response(200, b"css"),
                response(200, b"svg"),
                response(200, b"missing metadata"),
            ],
            "/lighthouse public-page smoke check failed",
        ),
        (
            [*healthy_prefix, FakeResponse(playable_today, url="https://rumor.example/lighthouse")],
            "visitor entry did not redirect to /lighthouse/today",
        ),
        (
            [
                *healthy_prefix,
                FakeResponse(b"missing metadata", url="https://rumor.example/lighthouse/today"),
            ],
            "/lighthouse/today playable-page smoke check failed",
        ),
        (
            [
                *healthy_prefix,
                FakeResponse(b'property="og:title"', url="https://rumor.example/lighthouse/today"),
            ],
            "/lighthouse/today exposed no primary playable recommendation",
        ),
        (
            [
                *healthy_prefix,
                FakeResponse(playable_today, url="https://rumor.example/lighthouse/today"),
                response(503, b""),
            ],
            "/lighthouse/runs/123/town/harbor playable destination smoke check failed",
        ),
        (
            [
                *healthy_prefix,
                FakeResponse(playable_today, url="https://rumor.example/lighthouse/today"),
                response(200, b"quiet but not actionable"),
            ],
            "/lighthouse/runs/123/town/harbor playable destination smoke check failed",
        ),
    ):
        iterator = iter(responses)

        def next_response(*args, items=iterator, **kwargs):  # type: ignore[no-untyped-def]
            del args, kwargs
            return next(items)

        try:
            smoke("https://rumor.example", opener=next_response)
        except RuntimeError as exc:
            assert str(exc) == message
        else:  # pragma: no cover - assertion guard
            raise AssertionError("smoke check unexpectedly passed")
