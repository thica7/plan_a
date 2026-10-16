from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.deps import get_app_settings, get_run_journal
from app.main import create_app
from packages.config import Settings
from packages.memory import RunJournal
from packages.schema.api_dto import HealthCheck


def client(monkeypatch):
    from app.routers import readiness

    monkeypatch.delenv("QDRANT_URL", raising=False)
    monkeypatch.setenv("KB_RETRIEVAL_MODE", "sparse")
    monkeypatch.setattr(
        readiness,
        "redis_options",
        lambda: SimpleNamespace(cache_enabled=False, rate_limit_enabled=False),
    )
    app = create_app()
    app.dependency_overrides[get_app_settings] = lambda: Settings(
        enterprise_store_backend="memory",
        run_orchestration_backend="langgraph",
        temporal_traffic_percent=0,
    )
    app.dependency_overrides[get_run_journal] = RunJournal.in_memory
    return TestClient(app)


def test_liveness_does_not_probe_dependencies(monkeypatch):
    from app.routers import readiness

    c = client(monkeypatch)
    monkeypatch.setattr(
        readiness,
        "probe_dependencies",
        lambda *a: (_ for _ in ()).throw(AssertionError("probe called")),
    )
    assert c.get("/api/livez").status_code == 200


def test_light_mode_does_not_require_temporal_or_llm_credentials(monkeypatch):
    from app.routers import readiness

    c = client(monkeypatch)
    monkeypatch.setattr(
        readiness,
        "_temporal_probe",
        lambda *a: (_ for _ in ()).throw(AssertionError("temporal called")),
    )
    r = c.get("/api/readyz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_required_database_failure_returns_http_503_without_connection_string(monkeypatch):
    from app.routers import readiness

    c = client(monkeypatch)
    monkeypatch.setattr(
        readiness,
        "_enterprise_store_check",
        lambda *a: HealthCheck(name="enterprise_store", status="error", detail="unreachable"),
    )
    response = c.get("/api/readyz")
    assert response.status_code == 503
    assert response.json()["status"] == "error"


def test_redis_cache_outage_is_degraded_but_enabled_limiter_outage_blocks_readiness(monkeypatch):
    from app.routers import readiness

    c = client(monkeypatch)

    async def unavailable():
        return False

    monkeypatch.setattr(readiness, "get_redis_runtime", lambda: SimpleNamespace(ping=unavailable))
    monkeypatch.setattr(
        readiness,
        "redis_options",
        lambda: SimpleNamespace(cache_enabled=True, rate_limit_enabled=False),
    )
    response = c.get("/api/readyz")
    assert response.status_code == 200 and response.json()["status"] == "warn"
    monkeypatch.setattr(
        readiness,
        "redis_options",
        lambda: SimpleNamespace(cache_enabled=True, rate_limit_enabled=True),
    )
    assert c.get("/api/readyz").status_code == 503


def test_monitor_endpoints_are_available_with_auth_enabled(monkeypatch):
    from app.middleware import auth

    c = client(monkeypatch)
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    assert c.get("/api/livez").status_code == 200
    assert c.get("/api/readyz").status_code == 200


def test_light_legacy_health_does_not_misclassify_disabled_temporal(monkeypatch):
    from app.routers.health import _temporal_cutover_check

    result = _temporal_cutover_check(
        Settings(run_orchestration_backend="langgraph", temporal_traffic_percent=0)
    )
    assert result.status == "ok"
