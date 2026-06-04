from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.deps import get_app_settings, get_enterprise_store, get_run_journal
from app.main import create_app
from app.routers.metrics import get_metrics_enterprise_store
from packages.compliance import build_data_retention_report
from packages.config import Settings
from packages.enterprise import EnterpriseMemoryStore, build_enterprise_projection
from packages.memory import RunJournal
from packages.schema.api_dto import RunDetail
from packages.schema.models import AnalysisPlan, RawSource


def test_data_retention_report_counts_expired_and_expiring_records() -> None:
    store, context = _projected_store()
    now = datetime(2026, 6, 4, 12, 0, 0)
    evidence = store.list_evidence(project_id=context.project_id)[0]
    store.upsert_evidence(
        evidence.model_copy(update={"captured_at": now - timedelta(days=8)})
    )
    report = store.list_report_versions(project_id=context.project_id)[0]
    store.upsert_report_version(
        report.model_copy(update={"created_at": now - timedelta(days=4)})
    )

    result = build_data_retention_report(
        store=store,
        workspace_id=context.workspace_id,
        settings=_settings(
            retention_evidence_days=7,
            retention_report_version_days=5,
            retention_expiring_soon_days=2,
        ),
        as_of=now,
    )

    assert result.status == "fail"
    assert result.expired_count >= 1
    assert result.expiring_soon_count >= 1
    buckets = {bucket.resource_type: bucket for bucket in result.buckets}
    assert buckets["evidence"].expired_count == 1
    assert buckets["report_version"].expiring_soon_count == 1
    assert result.physical_delete_enabled is False
    assert any("report-only" in item for item in result.recommendations)


def test_retention_report_route_and_metrics_expose_status() -> None:
    store, context = _projected_store()
    evidence = store.list_evidence(project_id=context.project_id)[0]
    store.upsert_evidence(
        evidence.model_copy(update={"captured_at": datetime.utcnow() - timedelta(days=10)})
    )
    settings = _settings(retention_evidence_days=1)
    app = create_app()
    app.dependency_overrides[get_app_settings] = lambda: settings
    app.dependency_overrides[get_enterprise_store] = lambda: store
    app.dependency_overrides[get_metrics_enterprise_store] = lambda: store
    app.dependency_overrides[get_run_journal] = RunJournal.in_memory
    client = TestClient(app)

    report_response = client.get(f"/api/enterprise/workspaces/{context.workspace_id}/retention")
    metrics_response = client.get("/api/metrics")

    assert report_response.status_code == 200
    assert report_response.json()["status"] == "fail"
    assert report_response.json()["expired_count"] >= 1
    assert metrics_response.status_code == 200
    assert 'competiscope_retention_status{status="fail"} 1' in metrics_response.text
    assert "competiscope_retention_expired_records_total " in metrics_response.text


def test_data_retention_report_accepts_mixed_timezone_datetimes() -> None:
    store, context = _projected_store()
    now = datetime(2026, 6, 4, 12, 0, 0, tzinfo=UTC)
    evidence = store.list_evidence(project_id=context.project_id)[0]
    store.upsert_evidence(
        evidence.model_copy(update={"captured_at": datetime(2026, 5, 25, 12, 0, 0)})
    )
    report = store.list_report_versions(project_id=context.project_id)[0]
    store.upsert_report_version(
        report.model_copy(
            update={"created_at": datetime(2026, 6, 3, 12, 0, 0, tzinfo=UTC)}
        )
    )

    result = build_data_retention_report(
        store=store,
        workspace_id=context.workspace_id,
        settings=_settings(retention_evidence_days=7),
        as_of=now,
    )

    assert result.status == "fail"
    assert result.expired_count >= 1


def _projected_store() -> tuple[EnterpriseMemoryStore, object]:
    store = EnterpriseMemoryStore()
    detail = RunDetail(
        id="run-retention",
        topic="Retention policy run",
        status="completed",
        execution_mode="demo",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        plan=AnalysisPlan(
            topic="Retention policy run",
            competitors=["Acme"],
            dimensions=["pricing"],
        ),
        raw_sources=[
            RawSource(
                id="source-retention",
                competitor="Acme",
                dimension="pricing",
                source_type="webpage_verified",
                title="Acme pricing",
                url="https://example.com/pricing",
                snippet="Acme publishes pricing.",
                content_hash="hash-retention",
                confidence=0.9,
            )
        ],
        report_md="Acme publishes pricing. [source:source-retention]",
    )
    context = store.start_run(detail)
    projection = build_enterprise_projection(
        detail,
        workspace_id=context.workspace_id,
        project_id=context.project_id,
        competitor_id_map=context.competitor_id_map,
    )
    store.save_projection(projection)
    return store, context


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
