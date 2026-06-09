from fastapi.testclient import TestClient

from app.deps import get_app_settings, get_run_journal
from app.main import create_app
from packages.config import Settings
from packages.memory import RunJournal
from packages.search import SearchResult
from packages.tools.fetch_page import FetchPageResult


def _settings(**overrides: object) -> Settings:
    values = {
        "demo_mode": True,
        "ark_api_key": None,
        "ark_model": None,
        "ark_base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "llm_timeout_seconds": 10,
        "llm_temperature": 0.2,
        "pplx_api_key": None,
        "pplx_base_url": "https://api.perplexity.ai",
        "web_search_provider": "perplexity",
        "enterprise_store_backend": "memory",
        "enterprise_database_url": None,
    }
    values.update(overrides)
    return Settings(**values)


def _client(settings: Settings) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_app_settings] = lambda: settings
    app.dependency_overrides[get_run_journal] = RunJournal.in_memory
    return TestClient(app)


class _FakeSocket:
    def __enter__(self) -> "_FakeSocket":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_health_reports_foundation_checks(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.routers.health.socket.create_connection",
        lambda *args, **kwargs: _FakeSocket(),  # noqa: ARG005
    )
    client = _client(_settings())

    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "competiscope-v2-api"
    assert body["status"] == "warn"
    assert {check["name"] for check in body["checks"]} >= {
        "config",
        "llm_credentials",
        "web_search_credentials",
        "skills",
        "sqlite",
        "enterprise_store",
        "auth_policy",
        "temporal_cutover",
        "temporal_server",
    }
    enterprise = [check for check in body["checks"] if check["name"] == "enterprise_store"][0]
    auth_policy = [check for check in body["checks"] if check["name"] == "auth_policy"][0]
    temporal_cutover = [
        check for check in body["checks"] if check["name"] == "temporal_cutover"
    ][0]
    temporal_server = [
        check for check in body["checks"] if check["name"] == "temporal_server"
    ][0]
    assert enterprise["status"] == "ok"
    assert enterprise["detail"] == "backend=memory"
    assert auth_policy["status"] == "ok"
    assert auth_policy["detail"] == "engine=internal"
    assert temporal_cutover["status"] == "ok"
    assert "target_percent=100" in temporal_cutover["detail"]
    assert temporal_server["status"] == "ok"


def test_runtime_reports_hitl_and_pydantic_ai_readiness() -> None:
    client = _client(
        _settings(
            hitl_enabled=True,
            pydantic_ai_model_backed_enabled=True,
            pydantic_ai_model_name="openai:gpt-4o-mini",
        )
    )

    response = client.get("/api/runtime")

    assert response.status_code == 200
    body = response.json()
    assert body["hitl_enabled"] is True
    assert body["hitl_demo_ready"] is True
    assert body["hitl_review_checkpoints"] == ["planner_hitl", "qa_hitl"]
    assert "enabled" in body["hitl_ready_reason"]
    assert body["pydantic_ai_model_backed_enabled"] is True
    assert body["pydantic_ai_model_name"] == "openai:gpt-4o-mini"
    assert isinstance(body["pydantic_ai_available"], bool)
    assert body["pydantic_ai_model_backed_ready"] is body["pydantic_ai_available"]
    assert "Pydantic-AI" in body["pydantic_ai_model_backed_reason"]
    assert body["telemetry"]["local_trace"]["enabled"] is True
    assert body["telemetry"]["local_trace"]["baseline"] is True
    assert body["telemetry"]["decision_replay"]["enabled"] is True
    assert body["telemetry"]["audit"]["enabled"] is True
    assert body["telemetry"]["langfuse"]["enabled"] is False
    assert body["telemetry"]["langfuse"]["disabled_reason"] == "not_configured"
    assert "hitl_lifecycle_event" in body["telemetry"]["event_types"]


def test_health_marks_incomplete_temporal_cutover_as_error() -> None:
    client = _client(_settings(run_orchestration_backend="langgraph"))

    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    temporal_cutover = [
        check for check in body["checks"] if check["name"] == "temporal_cutover"
    ][0]
    assert body["status"] == "error"
    assert temporal_cutover["status"] == "error"
    assert "RUN_ORCHESTRATION_BACKEND must be temporal" in temporal_cutover["detail"]


def test_health_marks_external_policy_engine_without_url_as_error() -> None:
    client = _client(_settings(auth_policy_engine="opa", auth_policy_url=None))

    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    auth_policy = [check for check in body["checks"] if check["name"] == "auth_policy"][0]
    assert body["status"] == "error"
    assert auth_policy["status"] == "error"
    assert "AUTH_POLICY_URL is required" in auth_policy["detail"]


def test_health_marks_misconfigured_postgres_enterprise_store_as_error() -> None:
    client = _client(
        _settings(enterprise_store_backend="postgres", enterprise_database_url=None),
    )

    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    enterprise = [check for check in body["checks"] if check["name"] == "enterprise_store"][0]
    assert body["status"] == "error"
    assert enterprise["status"] == "error"
    assert "ENTERPRISE_DATABASE_URL" in enterprise["detail"]


def test_health_pings_configured_postgres_enterprise_store(monkeypatch) -> None:
    class FakePostgresStore:
        def __init__(self, database_url: str, *, auto_migrate: bool) -> None:
            assert database_url == "postgresql://user:pass@db:5432/app"
            assert auto_migrate is False

        def ping(self) -> str:
            return "backend=postgres database=app"

    monkeypatch.setattr("app.routers.health.EnterprisePostgresStore", FakePostgresStore)
    client = _client(
        _settings(
            enterprise_store_backend="postgres",
            enterprise_database_url="postgresql://user:pass@db:5432/app",
        ),
    )

    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    enterprise = [check for check in body["checks"] if check["name"] == "enterprise_store"][0]
    assert enterprise["status"] == "ok"
    assert enterprise["detail"] == "backend=postgres database=app"


def test_health_marks_unreachable_postgres_enterprise_store_as_error(monkeypatch) -> None:
    class FakePostgresStore:
        def __init__(self, database_url: str, *, auto_migrate: bool) -> None:
            pass

        def ping(self) -> str:
            raise RuntimeError("contains-secret-password")

    monkeypatch.setattr("app.routers.health.EnterprisePostgresStore", FakePostgresStore)
    client = _client(
        _settings(
            enterprise_store_backend="postgres",
            enterprise_database_url="postgresql://user:secret@db:5432/app",
        ),
    )

    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    enterprise = [check for check in body["checks"] if check["name"] == "enterprise_store"][0]
    assert body["status"] == "error"
    assert enterprise["status"] == "error"
    assert enterprise["detail"] == "backend=postgres unreachable"
    assert "secret" not in response.text


def test_llm_smoke_uses_real_client_without_exposing_key(
    monkeypatch,
) -> None:
    async def fake_complete_text(self, *, system: str, user: str) -> str:  # noqa: ANN001
        return "ok"

    monkeypatch.setattr("app.routers.health.DoubaoClient.complete_text", fake_complete_text)
    client = _client(_settings(ark_api_key="secret", ark_model="model"))

    response = client.post("/api/smoke/llm", json={"prompt": "ping"})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["details"]["model"] == "model"
    assert "secret" not in response.text


def test_search_smoke_returns_perplexity_results(monkeypatch) -> None:
    async def fake_search(self, query: str, max_results: int):  # noqa: ANN001, ANN202
        return [SearchResult(title="A result", url="https://example.com/a", snippet="snippet")]

    monkeypatch.setattr("app.routers.health.PerplexitySearchClient.search", fake_search)
    client = _client(_settings(pplx_api_key="pplx-secret"))

    response = client.post("/api/smoke/search", json={"query": "test", "max_results": 1})

    assert response.status_code == 200
    body = response.json()
    assert body["component"] == "search"
    assert body["details"]["result_count"] == 1
    assert "pplx-secret" not in response.text


def test_fetch_smoke_returns_fetch_result(monkeypatch) -> None:
    async def fake_fetch_page(url: str):  # noqa: ANN202
        return FetchPageResult(
            url=url,
            ok=True,
            title="Example",
            text="Hello",
            content_hash="abc",
            status_code=200,
        )

    monkeypatch.setattr("app.routers.health.fetch_page", fake_fetch_page)
    client = _client(_settings())

    response = client.post("/api/smoke/fetch", json={"url": "https://example.com"})

    assert response.status_code == 200
    body = response.json()
    assert body["component"] == "fetch"
    assert body["ok"] is True
