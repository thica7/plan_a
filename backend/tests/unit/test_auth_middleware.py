from fastapi.testclient import TestClient

from app.main import create_app
from app.middleware import auth


def test_auth_middleware_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.setattr(auth, "AUTH_ENABLED", False)
    client = TestClient(create_app())

    response = client.get("/api/runtime")

    assert response.status_code == 200


def test_auth_middleware_requires_bearer_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    client = TestClient(create_app())

    missing = client.get("/api/runtime")
    allowed = client.get("/api/runtime", headers={"Authorization": "Bearer demo-token"})
    health = client.get("/api/health")

    assert missing.status_code == 401
    assert missing.json()["detail"] == "Missing or invalid authorization header"
    assert allowed.status_code == 200
    assert health.status_code == 200
