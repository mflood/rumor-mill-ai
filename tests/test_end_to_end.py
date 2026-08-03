"""End-to-end coverage for a returning player's complete story lifecycle."""

import json
from datetime import datetime, time, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr

from rumor_mill.adapters.persistence import create_database_engine, create_session_factory
from rumor_mill.adapters.persistence.models import ArtifactModel, RunModel
from rumor_mill.adapters.providers import DeterministicFakeProvider
from rumor_mill.config import Settings
from rumor_mill.engine.conversation import CharacterConversationEngine
from rumor_mill.main import create_app

ROOT = Path(__file__).parents[1]
pytestmark = pytest.mark.e2e


def test_player_can_complete_story_lifecycle_and_return(tmp_path: Path) -> None:
    """Cross every player-facing layer with a persisted anonymous identity."""
    database_url = f"sqlite:///{tmp_path / 'player-journey.db'}"
    migration = Config(str(ROOT / "alembic.ini"))
    migration.set_main_option("script_location", str(ROOT / "migrations"))
    migration.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(migration, "head")

    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    provider = DeterministicFakeProvider(
        {
            "character_conversation": {
                "reply": "The archive bell rang twice after midnight.",
                "stance": "answer",
                "conversation_memory": {
                    "content": "The visitor asked Ada about the archive bell.",
                    "salience": 0.8,
                },
            }
        }
    )
    app = create_app(
        Settings(
            database_url=database_url,
            operator_api_key=SecretStr("e2e-operator"),
            environment="test",
            secure_visitor_cookie=False,
        ),
        factory,
        CharacterConversationEngine(provider),
    )
    operator = {"Authorization": "Bearer e2e-operator"}
    world = json.loads((ROOT / "tests/fixtures/worlds/minimal.json").read_text())

    try:
        with TestClient(app) as first_visit:
            seeded = first_visit.post(
                "/api/v1/worlds/lantern-market/runs",
                headers=operator,
                json={"definition": world, "seed": 71, "clock_mode": "manual"},
            )
            assert seeded.status_code == 201
            run_id = UUID(seeded.json()["id"])

            advanced = first_visit.post(
                f"/api/v1/runs/{run_id}/ticks",
                headers=operator,
                json={"ticks": 3},
            )
            assert advanced.json()["ticks"] == 3

            landing = first_visit.get("/lighthouse")
            assert landing.status_code == 200
            assert "Day 1" in landing.text
            assert "The story continues while you are away" in landing.text
            assert "Enter Greyhaven" in landing.text

            entered = first_visit.post("/lighthouse/session", follow_redirects=False)
            assert entered.status_code == 303
            assert entered.headers["location"] == "/lighthouse/today"
            visitor_cookie = first_visit.cookies["rm_visitor"]
            visitor = first_visit.get("/api/v1/visitors/me")
            assert visitor.status_code == 200
            visitor_id = visitor.json()["visitor_id"]

            today = first_visit.get("/lighthouse/today")
            assert today.status_code == 200
            assert f"/lighthouse/runs/{run_id}/town/market" in today.text
            assert f"/lighthouse/runs/{run_id}/people/ada" in today.text

            harbor = first_visit.get(f"/lighthouse/runs/{run_id}/town/market")
            assert harbor.status_code == 200
            canonical_town = first_visit.get("/lighthouse/town")
            assert canonical_town.status_code == 200
            assert "Walk" in canonical_town.text
            character = first_visit.get(f"/lighthouse/runs/{run_id}/people/ada")
            assert character.status_code == 200

            with TestClient(app, cookies={"rm_visitor": "not-a-valid-session"}) as invalid_visit:
                unavailable = invalid_visit.get("/lighthouse/today")
                assert unavailable.status_code == 200
                assert unavailable.history[0].status_code == 303
                assert "Enter Greyhaven" in unavailable.text

            opened = first_visit.post(
                f"/api/v1/runs/{run_id}/conversations", json={"character_id": "ada"}
            )
            conversation_id = opened.json()["id"]
            turn = first_visit.post(
                f"/api/v1/conversations/{conversation_id}/messages",
                json={
                    "content": "What happened after midnight?",
                    "client_message_id": str(uuid4()),
                },
            )
            assert turn.status_code == 200
            assert turn.json()["messages"][-1]["content"] == (
                "The archive bell rang twice after midnight."
            )
            retried = first_visit.post(
                f"/api/v1/conversations/{conversation_id}/messages",
                json={
                    "content": "What happened after midnight?",
                    "client_message_id": turn.json()["messages"][0]["id"],
                },
            )
            assert retried.status_code == 200
            assert sum(message["role"] == "visitor" for message in retried.json()["messages"]) == 1

            with factory() as database:
                database.add(
                    ArtifactModel(
                        run_id=run_id,
                        kind="story_card",
                        title="The bell after midnight",
                        body="Ada heard two notes carry down from the archive.",
                        generated_at=datetime.fromisoformat(advanced.json()["simulation_time"]),
                        source_ids=[str(uuid4())],
                        payload={
                            "visibility": "public",
                            "importance": 5,
                            "character_id": "ada",
                            "location_id": "archive",
                            "active_thread": "Who entered the archive?",
                        },
                    )
                )
                database.commit()

            published = first_visit.post(
                f"/api/v1/runs/{run_id}/recaps/daily", headers=operator, json={}
            )
            assert published.status_code == 200
            episode_id = published.json()["id"]
            assert published.json()["recap"]["headline"] == "The bell after midnight"

            with factory() as database:
                run_model = database.get(RunModel, run_id)
                assert run_model is not None
                run_model.simulation_time = datetime.combine(
                    run_model.started_at.date() + timedelta(days=1), time(hour=0, minute=3)
                )
                database.add(
                    ArtifactModel(
                        run_id=run_id,
                        kind="daily_recap",
                        title="Unpublished Day 2 draft",
                        body="This draft must not replace the latest public dispatch.",
                        generated_at=run_model.simulation_time,
                        source_ids=[],
                        payload={"visibility": "private", "recap": published.json()["recap"]},
                    )
                )
                database.commit()

        with TestClient(app, cookies={"rm_visitor": visitor_cookie}) as return_visit:
            identity = return_visit.get("/api/v1/visitors/me")
            assert identity.status_code == 200
            assert identity.json()["visitor_id"] == visitor_id

            conversation = return_visit.get(f"/api/v1/conversations/{conversation_id}")
            assert conversation.status_code == 200
            assert conversation.json()["messages"][0]["content"] == (
                "What happened after midnight?"
            )

            archive = return_visit.get(f"/lighthouse/runs/{run_id}/archive")
            assert archive.status_code == 200
            assert "The bell after midnight" in archive.text
            episode = return_visit.get(f"/lighthouse/runs/{run_id}/archive/{episode_id}")
            assert episode.status_code == 200
            assert "Ada heard two notes carry down from the archive." in episode.text

            canonical_archive = return_visit.get("/lighthouse/archive")
            assert canonical_archive.status_code == 200
            assert "The bell after midnight" in canonical_archive.text

            public_routes = (
                "/lighthouse",
                "/lighthouse/today",
                f"/lighthouse/runs/{run_id}/town",
                f"/lighthouse/runs/{run_id}/town/market",
                f"/lighthouse/runs/{run_id}/people",
                f"/lighthouse/runs/{run_id}/people/ada",
                f"/lighthouse/runs/{run_id}/archive",
            )
            for route in public_routes:
                page = return_visit.get(route)
                assert page.status_code == 200
                assert "Day 2" in page.text
                assert "00:03" in page.text

            today = return_visit.get("/lighthouse/today")
            assert "Latest published dispatch · Day 1" in today.text
    finally:
        engine.dispose()
