"""Integration coverage for the stable simulation service API."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.orm import Session, sessionmaker

from rumor_mill.adapters.persistence import create_database_engine, create_session_factory
from rumor_mill.adapters.persistence.models import ArtifactModel, Base
from rumor_mill.config import Settings
from rumor_mill.main import create_app

ROOT = Path(__file__).parents[1]
VISITOR = UUID("00000000-0000-0000-0000-000000000111")
OTHER_VISITOR = UUID("00000000-0000-0000-0000-000000000222")


@pytest.fixture
def api(tmp_path: Path):  # type: ignore[no-untyped-def]
    url = f"sqlite:///{tmp_path / 'api.db'}"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    engine = create_database_engine(url)
    factory = create_session_factory(engine)
    settings = Settings(
        database_url=url,
        operator_api_key=SecretStr("operator-secret"),
        environment="test",
    )
    with TestClient(create_app(settings, factory)) as client:
        yield client, factory
    engine.dispose()


def world_payload() -> dict[str, object]:
    return cast(
        dict[str, object],
        json.loads((ROOT / "tests/fixtures/worlds/minimal.json").read_text()),
    )


def initialize(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/v1/worlds/lantern-market/runs",
        headers={"Authorization": "Bearer operator-secret"},
        json={"definition": world_payload(), "seed": 42, "clock_mode": "manual"},
    )
    assert response.status_code == 201
    return cast(dict[str, object], response.json())


def test_full_simulation_api_lifecycle(api) -> None:  # type: ignore[no-untyped-def]
    client, factory = api
    assert client.get("/api/v1/health").json() == {"status": "ok", "environment": "test"}
    run = initialize(client)
    run_id = run["id"]

    # Reusing a validated authored world creates another run rather than another world.
    second = initialize(client)
    assert second["world_id"] == run["world_id"]
    assert second["id"] != run_id

    state = client.get(f"/api/v1/runs/{run_id}")
    assert state.status_code == 200
    assert state.json()["seed"] == 42

    tick = client.post(
        f"/api/v1/runs/{run_id}/ticks",
        headers={"Authorization": "Bearer operator-secret"},
        json={"ticks": 2},
    )
    assert tick.status_code == 200
    assert tick.json()["ticks"] == 2

    town = client.get(f"/api/v1/runs/{run_id}/town").json()
    assert town["character_count"] == 2
    assert town["location_count"] == 2

    locations = client.get(f"/api/v1/runs/{run_id}/locations?offset=1&limit=1").json()
    assert locations["total"] == 2
    assert [item["id"] for item in locations["items"]] == ["archive"]
    characters = client.get(f"/api/v1/runs/{run_id}/characters?limit=1").json()
    assert characters["total"] == 2
    assert characters["items"][0]["location_id"] == "market"

    visitor_header = {"X-Visitor-ID": str(VISITOR)}
    created = client.post(
        f"/api/v1/runs/{run_id}/conversations",
        headers=visitor_header,
        json={"character_id": "ada"},
    )
    assert created.status_code == 201
    conversation_id = created.json()["id"]
    message = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=visitor_header,
        json={"content": "What did you see?"},
    )
    assert message.status_code == 200
    assert message.json()["messages"][0]["role"] == "visitor"
    fetched = client.get(f"/api/v1/conversations/{conversation_id}", headers=visitor_header).json()
    assert fetched["messages"][0]["content"] == "What did you see?"

    now = datetime.now(UTC)
    with factory() as database:
        database.add_all(
            [
                ArtifactModel(
                    id=uuid4(),
                    run_id=UUID(str(run_id)),
                    kind="story_card",
                    title="Morning",
                    body="The market wakes.",
                    generated_at=now,
                    source_ids=[str(uuid4())],
                    payload={"visibility": "public"},
                ),
                ArtifactModel(
                    id=uuid4(),
                    run_id=UUID(str(run_id)),
                    kind="story_card",
                    title="Secret",
                    body="Not for visitors.",
                    generated_at=now,
                    source_ids=[str(uuid4())],
                    payload={"visibility": "engine_only"},
                ),
            ]
        )
        database.commit()
    episodes = client.get(f"/api/v1/runs/{run_id}/episodes?limit=1").json()
    assert episodes["total"] == 1
    assert episodes["items"][0]["title"] == "Morning"

    schema = client.get("/openapi.json").json()
    assert "/api/v1/runs/{run_id}/ticks" in schema["paths"]
    assert schema["info"]["version"] == "1.0.0"


def test_daily_recap_is_public_only_cached_and_operator_editable(api) -> None:  # type: ignore[no-untyped-def]
    client, factory = api
    run_id = UUID(str(initialize(client)["id"]))
    assert client.get(f"/api/v1/runs/{run_id}/recaps/today").status_code == 404

    now = datetime.now(UTC)
    private_id = uuid4()
    with factory() as database:
        database.add_all(
            [
                ArtifactModel(
                    id=uuid4(),
                    run_id=run_id,
                    kind="story_card",
                    title="The skiff returned empty",
                    body="Its harbor lamp was still warm.",
                    generated_at=now,
                    source_ids=[str(uuid4())],
                    payload={
                        "visibility": "public",
                        "importance": 5,
                        "location_id": "market",
                        "character_id": "ada",
                        "active_thread": "Where is the keeper?",
                    },
                ),
                ArtifactModel(
                    id=private_id,
                    run_id=run_id,
                    kind="story_card",
                    title="Hidden motive",
                    body="This must never be recapped.",
                    generated_at=now,
                    source_ids=[str(uuid4())],
                    payload={"visibility": "engine_only", "importance": 5},
                ),
            ]
        )
        database.commit()

    operator = {"Authorization": "Bearer operator-secret"}
    generated = client.post(f"/api/v1/runs/{run_id}/recaps/daily", headers=operator, json={})
    assert generated.status_code == 200
    first = generated.json()
    assert first["recap"]["headline"] == "The skiff returned empty"
    assert "Hidden motive" not in generated.text

    cached = client.post(f"/api/v1/runs/{run_id}/recaps/daily", headers=operator, json={}).json()
    assert cached["id"] == first["id"]
    assert client.get(f"/api/v1/runs/{run_id}/recaps/today").json()["id"] == first["id"]

    forced = client.post(
        f"/api/v1/runs/{run_id}/recaps/daily", headers=operator, json={"force": True}
    ).json()
    assert forced["id"] != first["id"]
    edited = client.patch(
        f"/api/v1/recaps/{forced['id']}",
        headers=operator,
        json={"headline": "Edited dispatch", "dek": "Reviewed by the story operator."},
    )
    assert edited.status_code == 200
    assert edited.json()["edited"] is True
    assert edited.json()["recap"]["headline"] == "Edited dispatch"

    missing = client.patch(
        f"/api/v1/recaps/{uuid4()}",
        headers=operator,
        json={"headline": "No", "dek": "Missing"},
    )
    assert missing.status_code == 404
    wrong_kind = client.patch(
        f"/api/v1/recaps/{private_id}",
        headers=operator,
        json={"headline": "No", "dek": "Wrong kind"},
    )
    assert wrong_kind.status_code == 404


def test_authentication_validation_and_not_found_errors(api) -> None:  # type: ignore[no-untyped-def]
    client, _ = api
    payload = {"definition": world_payload()}
    path = "/api/v1/worlds/lantern-market/runs"
    assert client.post(path, json=payload).status_code == 401
    assert (
        client.post(path, headers={"Authorization": "Bearer wrong"}, json=payload).status_code
        == 401
    )
    mismatch = client.post(
        "/api/v1/worlds/wrong/runs",
        headers={"Authorization": "Bearer operator-secret"},
        json=payload,
    )
    assert mismatch.status_code == 422

    missing_id = uuid4()
    assert client.get(f"/api/v1/runs/{missing_id}").status_code == 404
    assert (
        client.post(
            f"/api/v1/runs/{missing_id}/ticks",
            headers={"Authorization": "Bearer operator-secret"},
            json={"ticks": 1},
        ).status_code
        == 404
    )

    run = initialize(client)
    run_id = run["id"]
    conversation_path = f"/api/v1/runs/{run_id}/conversations"
    assert client.post(conversation_path, json={"character_id": "ada"}).status_code == 401
    assert (
        client.post(
            conversation_path,
            headers={"X-Visitor-ID": "not-a-uuid"},
            json={"character_id": "ada"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            conversation_path,
            headers={"X-Visitor-ID": str(VISITOR)},
            json={"character_id": "unknown"},
        ).status_code
        == 404
    )

    missing_conversation = uuid4()
    assert (
        client.get(
            f"/api/v1/conversations/{missing_conversation}",
            headers={"X-Visitor-ID": str(VISITOR)},
        ).status_code
        == 404
    )
    created = client.post(
        conversation_path,
        headers={"X-Visitor-ID": str(VISITOR)},
        json={"character_id": "ada"},
    ).json()
    assert (
        client.get(
            f"/api/v1/conversations/{created['id']}",
            headers={"X-Visitor-ID": str(OTHER_VISITOR)},
        ).status_code
        == 403
    )


def test_operator_api_can_be_disabled(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'disabled.db'}"
    engine = create_database_engine(url)
    Base.metadata.create_all(engine)
    factory: sessionmaker[Session] = create_session_factory(engine)
    with TestClient(create_app(Settings(database_url=url), factory)) as client:
        response = client.post(
            "/api/v1/worlds/lantern-market/runs",
            json={"definition": world_payload()},
        )
    engine.dispose()
    assert response.status_code == 503
