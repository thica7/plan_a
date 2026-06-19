from fastapi.testclient import TestClient
from starlette.requests import Request

from app.deps import get_enterprise_user_context
from app.main import create_app
from app.middleware import auth
from packages.config import Settings


def test_auth_middleware_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.setattr(auth, "AUTH_ENABLED", False)
    client = TestClient(create_app())

    response = client.get("/api/runtime")

    assert response.status_code == 200


def test_auth_middleware_requires_bearer_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setenv("AUTH_BEARER_TOKENS", "demo-token")
    client = TestClient(create_app())

    missing = client.get("/api/runtime")
    allowed = client.get("/api/runtime", headers={"Authorization": "Bearer demo-token"})
    rejected = client.get("/api/runtime", headers={"Authorization": "Bearer wrong-token"})
    health = client.get("/api/health")

    assert missing.status_code == 401
    assert missing.json()["detail"] == "Missing or invalid authorization header"
    assert allowed.status_code == 200
    assert rejected.status_code == 401
    assert rejected.json()["detail"] == "Invalid bearer token"
    assert health.status_code == 200


def test_auth_middleware_fails_closed_without_configured_tokens(monkeypatch) -> None:
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.delenv("AUTH_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("AUTH_BEARER_TOKENS", raising=False)
    monkeypatch.delenv("AUTH_TOKEN_SUBJECTS", raising=False)
    client = TestClient(create_app())

    response = client.get("/api/runtime", headers={"Authorization": "Bearer demo-token"})

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Authentication is enabled but no bearer tokens are configured"
    )


def test_authenticated_user_context_ignores_spoofable_headers(monkeypatch) -> None:
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    request = Request({"type": "http", "method": "GET", "path": "/api/runs", "headers": []})
    request.state.enterprise_user = {
        "user_id": "token-user",
        "role": "viewer",
        "workspace_id": "workspace-a",
    }
    settings = Settings(
        demo_mode=True,
        ark_api_key=None,
        ark_model=None,
        ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
        llm_timeout_seconds=10,
        llm_temperature=0.2,
    )

    user = get_enterprise_user_context(
        request,
        settings,
        x_user_id="spoofed-user",
        x_user_role="owner",
        x_workspace_id="workspace-b",
    )

    assert user.user_id == "token-user"
    assert user.role == "viewer"
    assert user.workspace_id == "workspace-a"
