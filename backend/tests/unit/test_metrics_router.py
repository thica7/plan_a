from fastapi.testclient import TestClient

from app.deps import get_app_settings, get_run_journal
from app.main import create_app
from app.routers.metrics import get_metrics_enterprise_store
from packages.config import Settings
from packages.enterprise import EnterpriseMemoryStore
from packages.memory import RunJournal
from packages.schema.api_dto import RunDetail
from packages.schema.enterprise import NotificationRecord
from packages.schema.models import AnalysisPlan, RunMetrics, TraceSpan


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
    enterprise_store = EnterpriseMemoryStore()
    enterprise_store.upsert_notification(
        NotificationRecord(
            id="notification-release-gate-blocked",
            workspace_id="workspace-1",
            project_id="project-1",
            notification_type="release_gate_blocked",
            severity="warning",
            title="Release gate blocked",
            resource_type="run",
            resource_id="run-1",
        )
    )
    app = create_app()
    app.dependency_overrides[get_app_settings] = lambda: _settings()
    app.dependency_overrides[get_run_journal] = RunJournal.in_memory
    app.dependency_overrides[get_metrics_enterprise_store] = lambda: enterprise_store
    client = TestClient(app)

    response = client.get("/api/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert "competiscope_api_up 1" in body
    assert 'competiscope_runs_total{status="completed"} 0' in body
    assert 'competiscope_run_orchestration_backend{backend="temporal"} 1' in body
    assert "competiscope_temporal_traffic_percent_target 100" in body
    assert "competiscope_temporal_cutover_ready 1" in body
    assert "competiscope_temporal_server_up 0" in body
    assert "competiscope_enterprise_store_configured 1" in body
    assert 'competiscope_auth_policy_engine{engine="internal"} 1' in body
    assert 'competiscope_auth_policy_engine{engine="opa"} 0' in body
    assert 'competiscope_auth_policy_engine{engine="cerbos"} 0' in body
    assert "competiscope_auth_policy_external_configured 0" in body
    assert "competiscope_trace_spans_total 0" in body
    assert "competiscope_trace_context_coverage_ratio 0.000000" in body
    assert "competiscope_llm_calls_total 0" in body
    assert 'competiscope_token_estimate_total{kind="total"} 0' in body
    assert "competiscope_pydantic_ai_available " in body
    assert "competiscope_langfuse_configured 0" in body
    assert "competiscope_langfuse_enabled 0" in body
    assert "competiscope_langfuse_errors_total 0" in body
    assert 'competiscope_langfuse_disabled{reason="not_configured"} 1' in body
    assert "competiscope_langfuse_mirror_errors_total 0" in body
    assert "competiscope_pydantic_ai_model_backed_enabled 0" in body
    assert 'competiscope_model_route_status{status="selected"} 0' in body
    assert 'competiscope_model_route_status{status="fallback"} 1' in body
    assert 'competiscope_model_route_status{status="blocked"} 0' in body
    assert 'competiscope_model_route_selected{provider_kind="demo"} 1' in body
    assert "competiscope_model_route_blocked_reasons_total 0" in body
    assert "competiscope_compliance_redaction_enabled 1" in body
    assert "competiscope_compliance_redactions_total 0" in body
    assert "competiscope_compliance_require_trace_context 1" in body
    assert "competiscope_compliance_require_source_urls 0" in body
    assert (
        'competiscope_notifications_total{type="release_gate_blocked",status="queued"} 1'
        in body
    )
    assert "competiscope_release_gate_blocked_notifications_total 1" in body
    assert (
        'competiscope_temporal_workflow_registered_total{workflow="CompetitiveIntelWorkflow"} 1'
        in body
    )


def test_metrics_counts_persisted_langfuse_mirror_errors() -> None:
    journal = RunJournal.in_memory()
    journal.save_run(
        RunDetail(
            id="run-langfuse-error",
            topic="Langfuse mirror error run",
            status="completed",
            execution_mode="demo",
            created_at="2026-06-04T00:00:00Z",
            updated_at="2026-06-04T00:01:00Z",
            plan=AnalysisPlan(
                topic="Langfuse mirror error run",
                competitors=["A"],
                dimensions=["pricing"],
            ),
            trace_spans=[
                TraceSpan(
                    id="span-1",
                    kind="llm",
                    agent="writer",
                    name="Write",
                    status="ok",
                    duration_ms=1,
                    metadata={"langfuse_mirror_status": "error"},
                )
            ],
            metrics=RunMetrics(total_spans=1),
        )
    )
    app = create_app()
    app.dependency_overrides[get_app_settings] = lambda: _settings()
    app.dependency_overrides[get_run_journal] = lambda: journal
    app.dependency_overrides[get_metrics_enterprise_store] = lambda: None
    client = TestClient(app)

    response = client.get("/api/metrics")

    assert response.status_code == 200
    assert "competiscope_langfuse_mirror_errors_total 1" in response.text


def test_metrics_exposes_blocked_model_route_status() -> None:
    app = create_app()
    app.dependency_overrides[get_app_settings] = lambda: _settings(
        ark_api_key="primary-key",
        ark_model="primary-model",
        compliance_redaction_enabled=False,
    )
    app.dependency_overrides[get_run_journal] = RunJournal.in_memory
    app.dependency_overrides[get_metrics_enterprise_store] = lambda: None
    client = TestClient(app)

    response = client.get("/api/metrics")

    assert response.status_code == 200
    assert 'competiscope_model_route_status{status="blocked"} 1' in response.text
    assert 'competiscope_model_route_selected{provider_kind="none"} 1' in response.text
    assert "competiscope_model_route_blocked_reasons_total 1" in response.text
