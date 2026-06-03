from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.deps import get_app_settings, get_artifact_storage, get_enterprise_store
from app.main import create_app
from packages.artifacts import LocalArtifactStorage
from packages.config import Settings
from packages.enterprise import (
    EnterpriseMemoryStore,
    build_enterprise_projection,
    build_project_knowledge_graph_read_model,
    capture_source_snapshot,
)
from packages.governance import build_model_route_decision, build_tool_registry_report
from packages.schema.api_dto import RunDetail
from packages.schema.enterprise import SourceSnapshotCreateRequest
from packages.schema.models import (
    AnalysisPlan,
    CompetitorKnowledge,
    KnowledgeClaim,
    PricingModel,
    RawSource,
)


def test_source_snapshot_assets_external_s3_pointer_and_source_registry() -> None:
    store, context = _projected_store()
    evidence = store.list_evidence(project_id=context.project_id)[0]
    result = capture_source_snapshot(
        SourceSnapshotCreateRequest(
            workspace_id=context.workspace_id,
            project_id=context.project_id,
            evidence_id=evidence.id,
            run_id="run-1",
            snapshot_kind="webpage",
            filename="Cursor pricing snapshot.html",
            media_type="text/html",
            external_uri="s3://competiscope/snapshots/cursor-pricing.html",
            source_url="https://cursor.sh/pricing",
            source_type="webpage_verified",
            robots_status="allowed",
        ),
        store=store,
        artifact_storage=LocalArtifactStorage(Path("backend/.test-artifacts/h10")),
        actor_id="analyst-1",
    )

    assert result.artifact.storage_backend == "s3"
    assert result.artifact.evidence_id == evidence.id
    assert result.source.domain == "cursor.sh"
    assert result.snapshot_quality_score >= 80
    assert result.artifact.metadata["snapshot_quality_score"] == result.snapshot_quality_score
    assert result.artifact.metadata["snapshot_warnings"] == result.warnings
    assert result.artifact.metadata["source_registry_id"] == result.source.id
    assert result.artifact.metadata["source_domain"] == "cursor.sh"
    assert store.get_artifact(result.artifact.id) == result.artifact
    assert any(item.id == result.source.id for item in store.list_source_registry())


def test_manual_survey_snapshot_creates_research_evidence(tmp_path: Path) -> None:
    store, context = _projected_store()
    competitor_id = context.competitor_id_map["Cursor"]
    result = capture_source_snapshot(
        SourceSnapshotCreateRequest(
            workspace_id=context.workspace_id,
            project_id=context.project_id,
            run_id="run-1",
            snapshot_kind="survey",
            filename="enterprise-buyer-survey.md",
            media_type="text/markdown",
            content_text=(
                "Enterprise buyer survey: Cursor adoption depends on onboarding, "
                "security review, and workflow fit. Contact buyer@example.com "
                "with OPENROUTER_TEST_KEY_REDACTED."
            ),
            display_name="Enterprise buyer survey",
            trust_level="verified",
            metadata={
                "competitor_id": competitor_id,
                "dimension": "persona",
                "summary": (
                    "Enterprise buyers evaluate workflow fit and onboarding risk. "
                    "Follow up at analyst@example.com."
                ),
                "quotes": [
                    {
                        "speaker": "buyer@example.com",
                        "text": "Workflow fit improved after onboarding review.",
                    }
                ],
            },
        ),
        store=store,
        artifact_storage=LocalArtifactStorage(tmp_path),
        actor_id="analyst-1",
    )

    evidence = next(
        item for item in store.list_evidence(project_id=context.project_id)
        if item.id == result.evidence_id
    )

    assert result.evidence_id == evidence.id
    assert result.artifact.evidence_id == evidence.id
    assert result.source.source_type == "survey_response"
    assert result.artifact.metadata["source_type"] == "survey_response"
    assert evidence.source_type == "survey_response"
    assert evidence.competitor_id == competitor_id
    assert evidence.dimension == "persona"
    assert evidence.metadata["manual_research_ingest"] is True
    assert evidence.metadata["artifact_id"] == result.artifact.id
    assert "workflow fit" in evidence.snippet
    assert "buyer@example.com" not in evidence.snippet
    assert "sk-or-v1-redacted" not in evidence.snippet
    assert "[redacted:email]" in evidence.snippet
    assert "[redacted:api_key]" in evidence.snippet
    assert result.artifact.metadata["redaction_applied"] is True
    assert result.artifact.metadata["redaction_count"] >= 3
    assert result.artifact.metadata["redaction_counts"]["email"] >= 2
    assert result.artifact.metadata["redaction_counts"]["api_key"] == 1
    assert evidence.metadata["redaction_applied"] is True
    artifact_path = Path(str(result.artifact.metadata["storage_root"])) / Path(
        result.artifact.uri.removeprefix("local://")
    )
    artifact_text = artifact_path.read_text(encoding="utf-8")
    assert "buyer@example.com" not in artifact_text
    assert "sk-or-v1-redacted" not in artifact_text
    assert "[redacted:email]" in artifact_text
    assert "[redacted:api_key]" in artifact_text
    assert result.snapshot_quality_score >= 80
    assert result.warnings == []


def test_knowledge_graph_read_model_links_sources_claims_and_reports() -> None:
    store, context = _projected_store()

    graph = build_project_knowledge_graph_read_model(store=store, project_id=context.project_id)

    assert graph.workspace_id == context.workspace_id
    assert graph.node_count >= 5
    assert {"project", "competitor", "evidence", "claim", "source", "report"} <= {
        node.node_type for node in graph.nodes
    }
    assert {"tracks_competitor", "supported_by", "sourced_from", "contains_claim"} <= {
        edge.relation for edge in graph.edges
    }


def test_tool_registry_and_model_router_explain_enterprise_policy() -> None:
    settings = _settings(
        backup_llm_api_key="backup-key",
        backup_llm_model="deepseek/deepseek-v4-pro",
        compliance_redaction_enabled=True,
        compliance_require_trace_context=True,
    )

    tools = build_tool_registry_report(settings)
    route = build_model_route_decision(settings)
    tool_names = {entry.name for entry in tools.entries}

    assert tools.total_count >= 9
    assert {
        "source_snapshot",
        "memory_recall",
        "claim_validator",
        "self_consistency_sampler",
    } <= tool_names
    assert tools.side_effect_tool_count >= 3
    assert route.status == "fallback"
    assert route.selected is not None
    assert route.selected.provider_kind == "backup"


def test_model_router_blocks_real_routes_without_redaction() -> None:
    route = build_model_route_decision(
        _settings(
            ark_api_key="primary-key",
            ark_model="primary-model",
            compliance_redaction_enabled=False,
        )
    )

    assert route.status == "blocked"
    assert "redaction" in route.blocked_reasons[0]


def test_h10_enterprise_routes_are_callable() -> None:
    store, context = _projected_store()
    app = create_app()
    app.dependency_overrides[get_enterprise_store] = lambda: store
    app.dependency_overrides[get_artifact_storage] = lambda: LocalArtifactStorage(
        Path("backend/.test-artifacts/h10-route")
    )
    app.dependency_overrides[get_app_settings] = lambda: _settings(
        backup_llm_api_key="backup-key",
        backup_llm_model="deepseek/deepseek-v4-pro",
    )
    client = TestClient(app)

    assert client.get("/api/enterprise/tool-registry").status_code == 200
    route_response = client.get("/api/enterprise/model-route")
    graph_response = client.get(
        f"/api/enterprise/projects/{context.project_id}/kg-read-model"
    )
    report_version_id = store.list_report_versions(project_id=context.project_id)[0].id
    export_response = client.post(
        f"/api/enterprise/report-versions/{report_version_id}/export?format=csv"
    )
    snapshot_response = client.post(
        "/api/enterprise/source-snapshots",
        json={
            "workspace_id": context.workspace_id,
            "project_id": context.project_id,
            "evidence_id": store.list_evidence(project_id=context.project_id)[0].id,
            "run_id": "run-1",
            "filename": "pricing.html",
            "media_type": "text/html",
            "external_uri": "oss://competiscope/snapshots/pricing.html",
            "source_url": "https://cursor.sh/pricing",
            "robots_status": "allowed",
        },
    )

    assert route_response.status_code == 200
    assert route_response.json()["selected"]["provider_kind"] == "backup"
    assert graph_response.status_code == 200
    assert graph_response.json()["node_count"] >= 5
    assert export_response.status_code == 200
    export_artifact = export_response.json()["artifact"]
    assert export_artifact["artifact_type"] == "report_export"
    assert export_artifact["media_type"] == "text/csv"
    assert export_artifact["metadata"]["report_version_id"] == report_version_id
    assert store.get_artifact(export_artifact["id"]) is not None
    assert snapshot_response.status_code == 200
    assert snapshot_response.json()["artifact"]["storage_backend"] == "oss"
    assert snapshot_response.json()["artifact"]["metadata"]["snapshot_quality_score"] >= 80


def _projected_store() -> tuple[EnterpriseMemoryStore, object]:
    store = EnterpriseMemoryStore()
    detail = _detail()
    context = store.start_run(detail)
    projection = build_enterprise_projection(
        detail,
        workspace_id=context.workspace_id,
        project_id=context.project_id,
        competitor_id_map=context.competitor_id_map,
    )
    store.save_projection(projection)
    return store, context


def _detail() -> RunDetail:
    created_at = datetime.utcnow().replace(microsecond=0)
    updated_at = created_at + timedelta(minutes=3)
    return RunDetail(
        id="run-1",
        topic="AI coding assistant enterprise readiness",
        status="completed",
        execution_mode="demo",
        created_at=created_at,
        updated_at=updated_at,
        plan=AnalysisPlan(
            topic="AI coding assistant enterprise readiness",
            competitors=["Cursor"],
            dimensions=["pricing"],
            homepage_hints={"Cursor": "https://cursor.sh"},
        ),
        report_md="Cursor publishes pricing. [source:pricing-1]",
        raw_sources=[
            RawSource(
                id="pricing-1",
                competitor="Cursor",
                dimension="pricing",
                source_type="webpage_verified",
                title="Cursor pricing",
                url="https://cursor.sh/pricing",
                snippet="Cursor publishes pricing.",
                content_hash="hash-1",
                confidence=0.9,
            )
        ],
        competitor_knowledge={
            "Cursor": CompetitorKnowledge(
                competitor="Cursor",
                pricing_model=PricingModel(
                    notes=[
                        KnowledgeClaim(
                            claim="Cursor publishes pricing.",
                            source_ids=["pricing-1"],
                            confidence=0.9,
                        )
                    ]
                ),
            )
        },
    )


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
