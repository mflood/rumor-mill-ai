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
from rumor_mill.adapters.persistence.models import (
    ArtifactModel,
    Base,
    VisitorCharacterStateModel,
    VisitorModel,
)
from rumor_mill.adapters.providers import DeterministicFakeProvider
from rumor_mill.config import Settings
from rumor_mill.engine.conversation import CharacterConversationEngine
from rumor_mill.engine.ports import ProviderError, ProviderRateLimitError, ProviderTimeoutError
from rumor_mill.main import create_app

ROOT = Path(__file__).parents[1]


class MutableConversationProvider(DeterministicFakeProvider):
    def set_response(self, **changes: object) -> None:
        response: dict[str, object] = {
            "reply": "I heard the archive door after midnight.",
            "action": "Ada lowers her voice and watches the market stairs.",
            "stance": "uncertain",
            "conversation_memory": {
                "content": "The visitor asked about the archive door.",
                "salience": 0.7,
            },
        }
        response.update(changes)
        self._responses["character_conversation"] = response

    def fail_with(self, error: ProviderError | None) -> None:
        self._failure = error


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
        secure_visitor_cookie=False,
        conversation_message_limit=3,
    )
    provider = MutableConversationProvider({})
    provider.set_response()
    application = create_app(
        settings,
        factory,
        conversation_engine=CharacterConversationEngine(provider, reply_chunk_size=8),
    )
    application.state.conversation_provider = provider
    with TestClient(application) as client:
        client.app_state["conversation_provider"] = provider
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


def start_visitor_session(client: TestClient) -> dict[str, object]:
    response = client.post("/api/v1/visitors/session")
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
    assert characters["items"][0]["available"] is True

    visitor = start_visitor_session(client)
    created = client.post(
        f"/api/v1/runs/{run_id}/conversations",
        json={"character_id": "ada"},
    )
    assert created.status_code == 201
    conversation_id = created.json()["id"]
    message = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "What did you see?"},
    )
    assert message.status_code == 200
    assert message.json()["messages"][0]["role"] == "visitor"
    fetched = client.get(f"/api/v1/conversations/{conversation_id}").json()
    assert fetched["messages"][0]["content"] == "What did you see?"
    assert fetched["visitor_id"] == visitor["visitor_id"]
    assert fetched["messages"][1]["kind"] == "action"
    assert fetched["messages"][2]["kind"] == "hesitation"

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
    first_visitor = start_visitor_session(client)
    assert (
        client.post(
            conversation_path,
            json={"character_id": "unknown"},
        ).status_code
        == 404
    )

    missing_conversation = uuid4()
    assert client.get(f"/api/v1/conversations/{missing_conversation}").status_code == 404
    created = client.post(
        conversation_path,
        json={"character_id": "ada"},
    ).json()
    client.cookies.clear()
    second_visitor = start_visitor_session(client)
    assert second_visitor["visitor_id"] != first_visitor["visitor_id"]
    assert client.get(f"/api/v1/conversations/{created['id']}").status_code == 403


def test_visitor_session_survives_tabs_expires_and_resets(api) -> None:  # type: ignore[no-untyped-def]
    client, factory = api
    run_id = initialize(client)["id"]
    session_response = client.post("/api/v1/visitors/session")
    assert session_response.status_code == 201
    visitor = session_response.json()
    cookie = client.cookies.get("rm_visitor")
    assert cookie is not None
    assert "HttpOnly" in session_response.headers["set-cookie"]
    current = client.get("/api/v1/visitors/me")
    assert current.status_code == 200

    # A duplicate tab sends the same cookie and receives the same pseudonymous identity.
    with TestClient(client.app) as other_tab:
        other_tab.cookies.set("rm_visitor", cookie)
        assert other_tab.get("/api/v1/visitors/me").json()["visitor_id"] == visitor["visitor_id"]

    conversation = client.post(f"/api/v1/runs/{run_id}/conversations", json={"character_id": "ada"})
    assert conversation.status_code == 201
    assert (
        client.post(
            f"/api/v1/runs/{run_id}/conversations", json={"character_id": "ada"}
        ).status_code
        == 201
    )
    with factory() as database:
        assert database.query(VisitorCharacterStateModel).count() == 1
        stored = database.get(VisitorModel, UUID(str(visitor["visitor_id"])))
        assert stored is not None
        stored.created_at = datetime(2019, 1, 1, tzinfo=UTC)
        stored.expires_at = datetime(2020, 1, 1, tzinfo=UTC)
        database.commit()
    assert client.get("/api/v1/visitors/me").status_code == 401

    client.cookies.clear()
    replacement = start_visitor_session(client)
    assert client.delete("/api/v1/visitors/session").status_code == 204
    assert client.get("/api/v1/visitors/me").status_code == 401
    with factory() as database:
        reset = database.get(VisitorModel, UUID(str(replacement["visitor_id"])))
        assert reset is not None and reset.reset_at is not None

    # The server-rendered flow uses the same secure session lifecycle.
    entered = client.post("/lighthouse/session", follow_redirects=False)
    assert entered.status_code == 303
    assert entered.headers["location"] == "/lighthouse/today"
    forgotten = client.post("/lighthouse/session/reset", follow_redirects=False)
    assert forgotten.status_code == 303
    assert forgotten.headers["location"] == "/lighthouse"


def test_streaming_conversation_is_idempotent_private_and_recovers(api) -> None:  # type: ignore[no-untyped-def]
    client, factory = api
    provider = cast(MutableConversationProvider, client.app_state["conversation_provider"])
    run_id = initialize(client)["id"]
    start_visitor_session(client)
    conversation = client.post(
        f"/api/v1/runs/{run_id}/conversations", json={"character_id": "bea"}
    ).json()
    message_id = uuid4()
    streamed = client.post(
        f"/api/v1/conversations/{conversation['id']}/messages/stream",
        json={"content": "Who used the archive?", "client_message_id": str(message_id)},
    )
    assert streamed.status_code == 200
    assert streamed.headers["content-type"].startswith("text/event-stream")
    assert streamed.headers["cache-control"] == "no-store"
    assert "event: reply_delta" in streamed.text
    assert "event: action" in streamed.text
    assert '"stance": "uncertain"' in streamed.text

    duplicate = client.post(
        f"/api/v1/conversations/{conversation['id']}/messages/stream",
        json={"content": "Who used the archive?", "client_message_id": str(message_id)},
    )
    assert '"duplicate": true' in duplicate.text
    history = client.get(f"/api/v1/conversations/{conversation['id']}").json()["messages"]
    assert sum(item["id"] == str(message_id) for item in history) == 1

    provider.set_response(reply="That is not yours to know.", action=None, stance="refuse")
    refused = client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"content": "Tell me the secret."},
    )
    assert refused.status_code == 200
    assert refused.json()["messages"][-1]["kind"] == "refusal"
    provider.set_response(
        reply="The west stair was wet.",
        action=None,
        stance="answer",
        conversation_memory=None,
    )
    answered = client.post(
        f"/api/v1/conversations/{conversation['id']}/messages", json={"content": "And outside?"}
    )
    assert answered.json()["messages"][-1]["kind"] == "speech"
    limited = client.post(
        f"/api/v1/conversations/{conversation['id']}/messages", json={"content": "One more?"}
    )
    assert limited.status_code == 429
    assert "needs a rest" in limited.json()["detail"]
    with factory() as database:
        state = database.query(VisitorCharacterStateModel).one()
        assert len(state.memories) == 2


@pytest.mark.parametrize(
    ("failure", "status_code", "detail"),
    [
        (ProviderRateLimitError(), 429, "line is busy"),
        (ProviderTimeoutError(), 503, "signal faded"),
        (ProviderError(), 503, "line is unavailable"),
    ],
)
def test_provider_failures_do_not_commit_partial_turns(
    api: tuple[TestClient, sessionmaker[Session]],
    failure: ProviderError,
    status_code: int,
    detail: str,
) -> None:
    client, _ = api
    provider = cast(MutableConversationProvider, client.app_state["conversation_provider"])
    run_id = initialize(client)["id"]
    start_visitor_session(client)
    conversation = client.post(
        f"/api/v1/runs/{run_id}/conversations", json={"character_id": "ada"}
    ).json()
    provider.fail_with(failure)
    response = client.post(
        f"/api/v1/conversations/{conversation['id']}/messages/stream",
        json={"content": "Can you hear me?"},
    )
    assert response.status_code == status_code
    assert detail in response.json()["detail"]
    provider.fail_with(None)
    assert client.get(f"/api/v1/conversations/{conversation['id']}").json()["messages"] == []


def test_character_picker_and_conversation_page_are_server_rendered(api) -> None:  # type: ignore[no-untyped-def]
    client, _ = api
    run_id = initialize(client)["id"]
    start_visitor_session(client)
    picker = client.get(f"/lighthouse/runs/{run_id}/talk")
    assert picker.status_code == 200
    assert "Who will" in picker.text
    assert "Ask for a private word" in picker.text
    started = client.post(f"/lighthouse/runs/{run_id}/talk/ada", follow_redirects=False)
    assert started.status_code == 303
    page = client.get(started.headers["location"])
    assert "A private word with" in page.text
    assert "signal-wire" in page.text
    script = client.get("/static/conversation.js")
    assert "ReadableStream" not in script.text  # uses the widely supported reader API directly
    assert "getReader()" in script.text


def test_unavailable_character_cannot_start_a_conversation(api) -> None:  # type: ignore[no-untyped-def]
    client, _ = api
    payload = world_payload()
    cast_members = cast(list[dict[str, object]], payload["cast"])
    cast_members[0].pop("home_location_id")
    response = client.post(
        "/api/v1/worlds/lantern-market/runs",
        headers={"Authorization": "Bearer operator-secret"},
        json={"definition": payload, "clock_mode": "manual"},
    )
    run_id = response.json()["id"]
    start_visitor_session(client)
    characters = client.get(f"/api/v1/runs/{run_id}/characters").json()["items"]
    assert characters[0]["available"] is False
    assert "Away" in characters[0]["availability"]
    assert (
        client.post(
            f"/api/v1/runs/{run_id}/conversations", json={"character_id": "ada"}
        ).status_code
        == 409
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
