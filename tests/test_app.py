"""Application smoke tests."""

from fastapi.testclient import TestClient

from rumor_mill.main import app


def test_health_check() -> None:
    """The application boots and exposes its health endpoint."""
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "environment": "development"}
