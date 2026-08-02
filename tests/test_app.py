"""Application smoke tests."""

from fastapi.testclient import TestClient

from rumor_mill.main import app


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
    assert '<nav aria-label="Primary navigation">' in response.text
    assert 'href="#story">Skip to the story</a>' in response.text
    assert "The story continues while you are away" in response.text
    assert ">Enter Greyhaven" in response.text


def test_today_page_is_a_server_rendered_one_minute_briefing() -> None:
    with TestClient(app) as client:
        response = client.get("/lighthouse/today")

    assert response.status_code == 200
    assert '<main id="today"' in response.text
    assert "Threads to follow" in response.text
    assert "Since your last visit" in response.text
    assert "A dispatch could not be prepared" in response.text
    assert "Explore the harbor" in response.text


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
