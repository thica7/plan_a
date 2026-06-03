from datetime import datetime

from fastapi.testclient import TestClient

from app.deps import (
    get_app_settings,
    get_artifact_storage,
    get_enterprise_store,
    get_run_service,
)
from app.main import create_app
from packages.artifacts import LocalArtifactStorage
from packages.config import Settings
from packages.enterprise import EnterpriseMemoryStore
from packages.schema.api_dto import RunDetail
from packages.schema.models import AnalysisPlan, RunMetrics


def test_run_compliance_export_creates_report_artifact(tmp_path) -> None:
    detail = RunDetail(
        id="run-compliance-export",
        workspace_id="workspace-export",
        topic="Compliance export run",
        status="completed",
        execution_mode="demo",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        plan=AnalysisPlan(
            topic="Compliance export run",
            competitors=["Acme"],
            dimensions=["pricing"],
        ),
        metrics=RunMetrics(compliance_redaction_count=1),
    )
    store = EnterpriseMemoryStore()
    context = store.start_run(detail, workspace_id=detail.workspace_id)
    app = create_app()
    app.dependency_overrides[get_run_service] = lambda: _FakeRunService(detail)
    app.dependency_overrides[get_enterprise_store] = lambda: store
    app.dependency_overrides[get_artifact_storage] = lambda: LocalArtifactStorage(tmp_path)
    app.dependency_overrides[get_app_settings] = lambda: _settings()
    client = TestClient(app)

    response = client.post(f"/api/runs/{detail.id}/compliance/export")

    assert response.status_code == 200
    artifact = response.json()["artifact"]
    assert artifact["workspace_id"] == detail.workspace_id
    assert artifact["project_id"] == context.project_id
    assert artifact["artifact_type"] == "report_export"
    assert artifact["media_type"] == "application/json"
    assert artifact["metadata"]["export_kind"] == "run_compliance_report"
    assert artifact["metadata"]["run_id"] == detail.id
    assert store.get_artifact(artifact["id"]) is not None


class _FakeRunService:
    def __init__(self, detail: RunDetail) -> None:
        self._detail = detail

    def get_run(self, run_id: str) -> RunDetail | None:
        return self._detail if run_id == self._detail.id else None


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
    }
    values.update(overrides)
    return Settings(**values)
