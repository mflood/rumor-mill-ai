"""Heroku process, worker, and smoke-check contracts."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Self
from uuid import UUID

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select

from rumor_mill.adapters.persistence import (
    SqlAlchemyUnitOfWork,
    create_database_engine,
    create_session_factory,
    seed_run,
)
from rumor_mill.adapters.persistence.models import RunModel, WorkerHeartbeatModel
from rumor_mill.config import Settings
from rumor_mill.deployment import smoke
from rumor_mill.engine.ports import RunRecord, RunStatus, WorldRecord
from rumor_mill.main import create_app
from rumor_mill.worker import SimulationWorker, main, worker_id

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
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json()["components"]["worker"] == "ok"
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
    def __init__(self, body: bytes, status: int = 200) -> None:
        self.body = body
        self.status = status

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


def test_deployment_smoke_checks_health_assets_and_public_pages() -> None:
    requested: list[str] = []

    def open_fake(url: str, *, timeout: int) -> FakeResponse:
        assert timeout == 15
        requested.append(url)
        if url.endswith(("/health/live", "/health/ready")):
            body = b'{"status":"ok"}'
        elif url.endswith("/lighthouse/feedback"):
            body = b"Share feedback on GitHub"
        elif "/lighthouse" in url:
            body = b'property="og:title"'
        else:
            body = b"asset"
        return FakeResponse(body)

    smoke("https://rumor.example/", opener=open_fake)
    assert requested == [
        "https://rumor.example/health/live",
        "https://rumor.example/health/ready",
        "https://rumor.example/static/lighthouse.css",
        "https://rumor.example/static/favicon.svg",
        "https://rumor.example/lighthouse",
        "https://rumor.example/lighthouse/today",
        "https://rumor.example/lighthouse/town",
        "https://rumor.example/lighthouse/archive",
        "https://rumor.example/lighthouse/feedback",
    ]


def test_deployment_smoke_rejects_unhealthy_responses() -> None:
    def response(status: int, body: bytes) -> object:
        return FakeResponse(body, status)

    for responses, message in (
        ([response(503, b"{}")], "/health/live returned HTTP 503"),
        ([response(200, b'{"status":"degraded"}')], "/health/live reported degraded"),
        (
            [
                response(200, b'{"status":"ok"}'),
                response(200, b'{"status":"ok"}'),
                response(200, b""),
            ],
            "/static/lighthouse.css static asset smoke check failed",
        ),
        (
            [
                response(200, b'{"status":"ok"}'),
                response(200, b'{"status":"ok"}'),
                response(200, b"css"),
                response(200, b"svg"),
                response(200, b"missing metadata"),
            ],
            "/lighthouse public-page smoke check failed",
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
