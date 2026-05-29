from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.deps import get_app_settings, get_run_journal
from app.main import create_app
from packages.config import Settings
from packages.memory import RunJournal


def _settings(**overrides: object) -> Settings:
    values = {
        "demo_mode": True,
        "ark_api_key": None,
        "ark_model": None,
        "ark_base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "llm_timeout_seconds": 10,
        "llm_temperature": 0.2,
        "enterprise_store_backend": "memory",
        "enterprise_database_url": None,
        "run_orchestration_backend": "temporal",
        "temporal_address": "127.0.0.1:1",
    }
    values.update(overrides)
    return Settings(**values)


def test_metrics_exposes_run_and_temporal_operational_gauges() -> None:
    db_path = Path("runs") / f"test-metrics-{uuid4().hex}.db"
    app = create_app()
    app.dependency_overrides[get_app_settings] = lambda: _settings()
    app.dependency_overrides[get_run_journal] = lambda: RunJournal(db_path)
    client = TestClient(app)

    try:
        response = client.get("/api/metrics")
    finally:
        db_path.unlink(missing_ok=True)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert "competiscope_api_up 1" in body
    assert 'competiscope_runs_total{status="completed"} 0' in body
    assert 'competiscope_run_orchestration_backend{backend="temporal"} 1' in body
    assert "competiscope_temporal_server_up 0" in body
    assert "competiscope_enterprise_store_configured 1" in body
