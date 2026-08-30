"""Application smoke tests."""

from pathlib import Path

from fastapi.testclient import TestClient

from rumor_mill.adapters.persistence import create_database_engine, create_session_factory
from rumor_mill.adapters.persistence.models import Base, VisitorModel
from rumor_mill.config import Settings
from rumor_mill.main import app, create_app


def test_health_check() -> None:
    """The application boots and exposes its health endpoint."""
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "environment": "development"}


def test_lighthouse_shell_is_server_rendered_and_semantic() -> None:
    """The public experience works as a useful document without JavaScript."""
    with TestClient(app) as client:
        response = client.get("/lighthouse")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert '<main id="story"' in response.text
    assert 'aria-label="Story navigation unavailable while between seasons"' in response.text
    assert 'href="#story">Skip to the story</a>' in response.text
    assert "Between seasons" in response.text
    assert "No story is progressing" in response.text
    assert "Day 1" not in response.text
    assert "Night" not in response.text
    assert "The story continues while you are away" not in response.text
    assert "Enter Greyhaven" not in response.text
    assert response.text.count('aria-disabled="true"') == 3
    assert response.text.count('href="/lighthouse/help">How to play</a>') == 1
    assert "prior visitor data is safe" in response.text
    assert "no visitor record or cookie will be created" in response.text


def test_lighthouse_entry_failure_disables_the_inert_entry_action() -> None:
    with TestClient(app) as client:
        response = client.get("/lighthouse?unavailable=true")

    assert response.status_code == 200
    assert "Between seasons" in response.text
    assert "Enter Greyhaven" not in response.text


def test_failed_lighthouse_entry_persists_no_visitor_or_cookie(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'empty-entry.db'}"
    engine = create_database_engine(database_url)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    empty_app = create_app(Settings(database_url=database_url), factory)

    with TestClient(empty_app) as client:
        response = client.post("/lighthouse/session", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/lighthouse"
    assert "rm_visitor" not in response.cookies
    assert "set-cookie" not in response.headers
    with factory() as database:
        assert database.query(VisitorModel).count() == 0
    engine.dispose()


def test_lighthouse_help_is_semantic_session_free_and_honest_between_seasons(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'empty-help.db'}"
    engine = create_database_engine(database_url)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    empty_app = create_app(Settings(database_url=database_url), factory)

    with TestClient(empty_app) as client:
        response = client.get("/lighthouse/help")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "set-cookie" not in response.headers
    assert '<a class="skip-link" href="#help">' in response.text
    assert '<nav aria-label="Help navigation">' in response.text
    assert response.text.count("<h1>") == 1
    assert "<h1>How to play The Lighthouse</h1>" in response.text
    assert "No season:" in response.text
    assert "no story is progressing" in response.text
    assert "Core story routes appear when Greyhaven is available" in response.text
    assert "<script" not in response.text
    with factory() as database:
        assert database.query(VisitorModel).count() == 0
    engine.dispose()


def test_today_page_uses_the_consistent_unavailable_state_without_a_selected_story() -> None:
    with TestClient(app) as client:
        response = client.get("/lighthouse/today")

    assert response.status_code == 200
    assert '<main id="story"' in response.text
    assert "Between seasons" in response.text


def test_town_uses_the_consistent_unavailable_state_without_a_selected_story() -> None:
    with TestClient(app) as client:
        response = client.get("/lighthouse/town")

    assert response.status_code == 200
    assert "Between seasons" in response.text
    assert response.history[0].status_code == 303


def test_archive_uses_the_consistent_unavailable_state_without_a_selected_story() -> None:
    with TestClient(app) as client:
        response = client.get("/lighthouse/archive")

    assert response.status_code == 200
    assert "No published story yet" in response.text
    assert response.history == []


def test_lighthouse_visual_system_includes_accessibility_states() -> None:
    """The design system exposes focus, small-screen, and reduced-motion rules."""
    with TestClient(app) as client:
        response = client.get("/static/lighthouse.css")

    assert response.status_code == 200
    assert ":focus-visible" in response.text
    assert "@media (max-width: 360px)" in response.text
    assert "@media (prefers-reduced-motion: reduce)" in response.text
    assert "@media (forced-colors: active)" in response.text
    assert all(
        component in response.text
        for component in (".story-panel", ".portrait", ".town-card", ".dialogue")
    )


def test_public_launch_metadata_assets_and_feedback_route() -> None:
    with TestClient(app) as client:
        for path in ("/lighthouse", "/lighthouse/today", "/lighthouse/town", "/lighthouse/archive"):
            response = client.get(path)
            assert response.status_code in {200, 503}
            assert 'property="og:title"' in response.text
            assert 'property="og:image"' in response.text
            assert 'name="twitter:card"' in response.text
            assert 'rel="icon" href="/static/favicon.svg"' in response.text

        favicon = client.get("/static/favicon.svg")
        feedback = client.get("/lighthouse/feedback")

    assert favicon.status_code == 200
    assert favicon.headers["content-type"].startswith("image/svg+xml")
    assert feedback.status_code == 200
    assert "Send feedback" in feedback.text
    assert "SECURITY.md" in feedback.text
