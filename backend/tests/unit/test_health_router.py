from pathlib import Path
from uuid import uuid4

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
    }
    values.update(overrides)
    return Settings(**values)


def _client(db_path: Path, settings: Settings) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_app_settings] = lambda: settings
    app.dependency_overrides[get_run_journal] = lambda: RunJournal(db_path)
    return TestClient(app)


def _db_path() -> Path:
    return Path("runs") / f"test-health-{uuid4().hex}.db"


def test_health_reports_foundation_checks() -> None:
    db_path = _db_path()
    client = _client(db_path, _settings())

    try:
        response = client.get("/api/health")
    finally:
        db_path.unlink(missing_ok=True)

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
    }
    enterprise = [check for check in body["checks"] if check["name"] == "enterprise_store"][0]
    assert enterprise["status"] == "ok"
    assert enterprise["detail"] == "backend=memory"


def test_health_marks_misconfigured_postgres_enterprise_store_as_error() -> None:
    db_path = _db_path()
    client = _client(db_path, _settings(enterprise_store_backend="postgres"))

    try:
        response = client.get("/api/health")
    finally:
        db_path.unlink(missing_ok=True)

    assert response.status_code == 200
    body = response.json()
    enterprise = [check for check in body["checks"] if check["name"] == "enterprise_store"][0]
    assert body["status"] == "error"
    assert enterprise["status"] == "error"
    assert "ENTERPRISE_DATABASE_URL" in enterprise["detail"]


def test_llm_smoke_uses_real_client_without_exposing_key(
    monkeypatch,
) -> None:
    async def fake_complete_text(self, *, system: str, user: str) -> str:  # noqa: ANN001
        return "ok"

    monkeypatch.setattr("app.routers.health.DoubaoClient.complete_text", fake_complete_text)
    db_path = _db_path()
    client = _client(db_path, _settings(ark_api_key="secret", ark_model="model"))

    try:
        response = client.post("/api/smoke/llm", json={"prompt": "ping"})
    finally:
        db_path.unlink(missing_ok=True)

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["details"]["model"] == "model"
    assert "secret" not in response.text


def test_search_smoke_returns_perplexity_results(monkeypatch) -> None:
    async def fake_search(self, query: str, max_results: int):  # noqa: ANN001, ANN202
        return [SearchResult(title="A result", url="https://example.com/a", snippet="snippet")]

    monkeypatch.setattr("app.routers.health.PerplexitySearchClient.search", fake_search)
    db_path = _db_path()
    client = _client(db_path, _settings(pplx_api_key="pplx-secret"))

    try:
        response = client.post("/api/smoke/search", json={"query": "test", "max_results": 1})
    finally:
        db_path.unlink(missing_ok=True)

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
    db_path = _db_path()
    client = _client(db_path, _settings())

    try:
        response = client.post("/api/smoke/fetch", json={"url": "https://example.com"})
    finally:
        db_path.unlink(missing_ok=True)

    assert response.status_code == 200
    body = response.json()
    assert body["component"] == "fetch"
    assert body["ok"] is True
