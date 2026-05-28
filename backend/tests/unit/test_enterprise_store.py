import pytest
from fastapi.testclient import TestClient

from app.deps import get_enterprise_store
from app.main import create_app
from packages.config import Settings
from packages.enterprise import EnterpriseMemoryStore, build_enterprise_projection
from packages.orchestrator.service import RunService
from packages.schema.api_dto import RunCreateRequest, RunDetail
from packages.schema.models import (
    AnalysisPlan,
    CompetitorKnowledge,
    KnowledgeClaim,
    PricingModel,
    RawSource,
)
from packages.skills.registry import SkillRegistry


def _detail() -> RunDetail:
    return RunDetail(
        id="run-1",
        topic="AI coding assistant comparison",
        status="completed",
        execution_mode="demo",
        created_at="2026-05-28T00:00:00",
        updated_at="2026-05-28T00:05:00",
        plan=AnalysisPlan(
            topic="AI coding assistant comparison",
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


def _settings() -> Settings:
    return Settings(
        demo_mode=True,
        ark_api_key=None,
        ark_model=None,
        ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
        llm_timeout_seconds=10,
        llm_temperature=0.2,
    )


def test_enterprise_store_bootstraps_context_and_deduplicates_audit() -> None:
    store = EnterpriseMemoryStore()
    detail = _detail()

    first = store.start_run(detail)
    second = store.start_run(detail)

    assert first.project_id == second.project_id
    assert detail.id in {log.resource_id for log in store.list_audit_logs()}
    assert [log.action for log in store.list_audit_logs()].count("run.created") == 1
    assert store.list_projects()[0].competitor_set_hash
    assert first.competitor_id_map["Cursor"].startswith("competitor-")
    assert len(store.project_competitors) == 1


def test_enterprise_store_round_trips_projection() -> None:
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
    loaded = store.get_run_projection(detail.id)

    assert loaded is not None
    assert loaded.report_version.id == projection.report_version.id
    assert [item.id for item in loaded.evidence_records] == [
        item.id for item in projection.evidence_records
    ]
    assert [item.id for item in loaded.claim_records] == [
        item.id for item in projection.claim_records
    ]


@pytest.mark.asyncio
async def test_run_service_writes_enterprise_projection_on_completion() -> None:
    store = EnterpriseMemoryStore()
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=_settings(),
        enterprise_store=store,
    )
    created = await service.create_run(
        RunCreateRequest(
            topic="AI coding assistant comparison",
            competitors=["Cursor"],
            dimensions=["pricing"],
            execution_mode="demo",
        )
    )
    record = service._runs[created.id]
    detail = _detail()
    record.detail.raw_sources = detail.raw_sources
    record.detail.competitor_knowledge = detail.competitor_knowledge
    record.detail.report_md = detail.report_md
    record.detail.status = "running"

    await service._finalize_demo_pipeline(record)

    projection = store.get_run_projection(created.id)
    assert projection is not None
    assert projection.project_id == record.detail.project_id
    assert projection.evidence_records[0].competitor_id.startswith("competitor-")
    assert len(projection.evidence_records) == 1
    assert record.events[-1].payload["enterprise_projection"]["evidence_count"] == 1


def test_enterprise_router_exposes_projection() -> None:
    store = EnterpriseMemoryStore()
    detail = _detail()
    context = store.start_run(detail)
    store.save_projection(
        build_enterprise_projection(
            detail,
            workspace_id=context.workspace_id,
            project_id=context.project_id,
            competitor_id_map=context.competitor_id_map,
        )
    )
    app = create_app()
    app.dependency_overrides[get_enterprise_store] = lambda: store
    client = TestClient(app)

    response = client.get(f"/api/enterprise/runs/{detail.id}/projection")
    workspaces = client.get("/api/enterprise/workspaces")

    assert response.status_code == 200
    assert response.json()["report_version"]["id"].startswith("report-run-1")
    assert workspaces.status_code == 200
    assert workspaces.json()[0]["id"] == "default-workspace"
