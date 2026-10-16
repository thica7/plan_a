from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def client(monkeypatch, runtime, *, auth=False):
    from app.middleware import redis_rate_limit as module

    monkeypatch.setattr(module, "get_redis_runtime", lambda: runtime)
    monkeypatch.setattr(
        module,
        "redis_options",
        lambda: SimpleNamespace(
            rate_limit_enabled=True, rate_limit_requests=2, rate_limit_window_seconds=60
        ),
    )
    app = FastAPI()
    app.add_middleware(module.RedisRateLimitMiddleware)
    if auth:
        from app.middleware import auth as auth_module

        monkeypatch.setattr(auth_module, "AUTH_ENABLED", True)
        monkeypatch.setenv(
            "AUTH_TOKEN_SUBJECTS",
            '{"unit-token":{"user_id":"trusted","workspace_id":"scope-a","role":"owner"}}',
        )
        app.add_middleware(auth_module.AuthMiddleware)

    @app.post("/api/runs")
    def runs():
        return {"ok": True}

    @app.get("/api/runs")
    def list_runs():
        return []

    return TestClient(app)


def test_excess_requests_rejected_before_handler_with_retry_after(monkeypatch):
    calls = []

    class Runtime:
        async def check_rate_limit(self, scope, **kwargs):
            calls.append(scope)
            return SimpleNamespace(
                allowed=len(calls) < 3, retry_after_seconds=17, remaining=max(0, 2 - len(calls))
            )

    c = client(monkeypatch, Runtime())
    assert c.post("/api/runs").status_code == 200
    assert c.post("/api/runs").status_code == 200
    response = c.post("/api/runs")
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "17"
    assert c.get("/api/runs").status_code == 200
    assert len(calls) == 3


def test_backend_failure_does_not_silently_allow_paid_request(monkeypatch):
    from packages.infrastructure.redis_runtime import RedisBackendUnavailable

    class Runtime:
        async def check_rate_limit(self, *args, **kwargs):
            raise RedisBackendUnavailable("unit-only")

    response = client(monkeypatch, Runtime()).post("/api/runs")
    assert response.status_code == 503
    assert "unit-only" not in response.text


def test_rate_limit_scope_comes_from_verified_auth_not_user_headers(monkeypatch):
    calls = []

    class Runtime:
        async def check_rate_limit(self, scope, **kwargs):
            calls.append(scope)
            return SimpleNamespace(allowed=True, retry_after_seconds=0, remaining=1)

    c = client(monkeypatch, Runtime(), auth=True)
    assert c.post("/api/runs").status_code == 401
    assert (
        c.post(
            "/api/runs",
            headers={
                "Authorization": "Bearer unit-token",
                "X-Workspace-Id": "spoofed",
                "X-User-Id": "spoofed",
            },
        ).status_code
        == 200
    )
    assert len(calls) == 1
    assert "trusted" in calls[0] and "scope-a" in calls[0] and "spoofed" not in calls[0]


@pytest.mark.parametrize("path", ["/api/workflows/scheduled-scan", "/api/workflows/monitor"])
def test_scheduled_paid_entries_fail_closed_when_limiter_is_down(monkeypatch, path):
    from packages.infrastructure.redis_runtime import RedisBackendUnavailable

    class Runtime:
        async def check_rate_limit(self, *a, **k):
            raise RedisBackendUnavailable("unit-only")

    assert client(monkeypatch, Runtime()).post(path).status_code == 503
