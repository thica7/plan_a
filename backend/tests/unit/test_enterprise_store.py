import pytest
from fastapi.testclient import TestClient

from app.deps import get_enterprise_store
from app.main import create_app
from packages.config import Settings
from packages.enterprise import (
    EnterpriseMemoryStore,
    build_enterprise_projection,
    build_report_version_diff,
)
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
    assert store.get_project(first.project_id) is not None
    assert [item.name for item in store.list_competitors(project_id=first.project_id)] == ["Cursor"]


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
    actions = {log.action for log in store.list_audit_logs()}
    assert actions >= {
        "run.created",
        "project.upserted",
        "competitor.upserted",
        "project_competitor.linked",
        "evidence.upserted",
        "claim.upserted",
        "report_version.upserted",
        "run.projected",
    }


def test_enterprise_store_tracks_evidence_lifecycle_across_runs() -> None:
    store = EnterpriseMemoryStore()
    first_detail = _detail()
    first_context = store.start_run(first_detail)
    first_projection = build_enterprise_projection(
        first_detail,
        workspace_id=first_context.workspace_id,
        project_id=first_context.project_id,
        competitor_id_map=first_context.competitor_id_map,
    )
    store.save_projection(first_projection)

    second_detail = _detail().model_copy(deep=True, update={"id": "run-2"})
    second_context = store.start_run(second_detail)
    second_projection = build_enterprise_projection(
        second_detail,
        workspace_id=second_context.workspace_id,
        project_id=second_context.project_id,
        version_number=2,
        competitor_id_map=second_context.competitor_id_map,
    )
    store.save_projection(second_projection)
    store.save_projection(second_projection)

    [evidence] = store.list_evidence(project_id=first_context.project_id)
    assert evidence.first_seen_run_id == "run-1"
    assert evidence.last_seen_run_id == "run-2"
    assert evidence.seen_count == 2
    assert evidence.run_id == "run-1"


def test_enterprise_store_registers_sources_from_evidence_lifecycle() -> None:
    store = EnterpriseMemoryStore()
    first_detail = _detail()
    first_context = store.start_run(first_detail)
    first_projection = build_enterprise_projection(
        first_detail,
        workspace_id=first_context.workspace_id,
        project_id=first_context.project_id,
        competitor_id_map=first_context.competitor_id_map,
    )
    store.save_projection(first_projection)

    second_detail = _detail().model_copy(deep=True, update={"id": "run-2"})
    second_context = store.start_run(second_detail)
    second_projection = build_enterprise_projection(
        second_detail,
        workspace_id=second_context.workspace_id,
        project_id=second_context.project_id,
        version_number=2,
        competitor_id_map=second_context.competitor_id_map,
    )
    store.save_projection(second_projection)
    store.save_projection(second_projection)

    [source] = store.list_source_registry(workspace_id=first_context.workspace_id)
    assert source.domain == "cursor.sh"
    assert source.source_type == "webpage_verified"
    assert source.trust_level == "verified"
    assert source.homepage_url is not None
    assert str(source.homepage_url) == "https://cursor.sh/"
    assert source.first_seen_run_id == "run-1"
    assert source.last_seen_run_id == "run-2"
    assert source.seen_count == 2
    assert any(log.action == "source_registry.upserted" for log in store.list_audit_logs())


def test_enterprise_store_indexes_and_searches_evidence_embeddings() -> None:
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

    embeddings = store.list_evidence_embeddings(workspace_id=context.workspace_id)
    hits = store.search_evidence(
        workspace_id=context.workspace_id,
        project_id=context.project_id,
        query="Cursor pricing plan",
        limit=3,
    )
    reindexed = store.reindex_evidence_embeddings(workspace_id=context.workspace_id)

    assert len(embeddings) == 1
    assert embeddings[0].evidence_id == projection.evidence_records[0].id
    assert reindexed.indexed_count == 1
    assert [hit.evidence.id for hit in hits] == [projection.evidence_records[0].id]
    assert hits[0].embedding_model == "hashing-384"


def test_enterprise_store_updates_evidence_quality_with_audit() -> None:
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

    updated = store.update_evidence_quality(
        projection.evidence_records[0].id,
        "rejected",
        note="Outdated pricing page.",
    )

    assert updated is not None
    assert updated.quality_label == "rejected"
    assert updated.metadata["quality_note"] == "Outdated pricing page."
    assert any(log.action == "evidence.quality_updated" for log in store.list_audit_logs())


def test_enterprise_store_increments_report_version_by_group() -> None:
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
    next_version = store.next_report_version_number(
        project_id=projection.project_id,
        topic_normalized=projection.report_version.topic_normalized,
        competitor_layer=projection.report_version.competitor_layer,
        competitor_set_hash=projection.report_version.competitor_set_hash,
    )

    assert next_version == 2


def test_report_version_diff_uses_previous_version() -> None:
    store = EnterpriseMemoryStore()
    first_detail = _detail()
    first_context = store.start_run(first_detail)
    first_projection = build_enterprise_projection(
        first_detail,
        workspace_id=first_context.workspace_id,
        project_id=first_context.project_id,
        competitor_id_map=first_context.competitor_id_map,
    )
    store.save_projection(first_projection)

    second_detail = _detail().model_copy(
        deep=True,
        update={
            "id": "run-2",
            "report_md": (
                "Cursor publishes pricing. [source:pricing-1]\n"
                "Cursor has a public paid plan. [source:pricing-1]"
            ),
        },
    )
    second_context = store.start_run(second_detail)
    second_projection = build_enterprise_projection(
        second_detail,
        workspace_id=second_context.workspace_id,
        project_id=second_context.project_id,
        version_number=store.next_report_version_number(
            project_id=second_context.project_id,
            topic_normalized=first_projection.report_version.topic_normalized,
            competitor_layer=first_projection.report_version.competitor_layer,
            competitor_set_hash=first_projection.report_version.competitor_set_hash,
        ),
        competitor_id_map=second_context.competitor_id_map,
    )
    store.save_projection(second_projection)

    previous = store.get_previous_report_version(second_projection.report_version)
    diff = build_report_version_diff(second_projection.report_version, base_version=previous)

    assert previous is not None
    assert previous.id == first_projection.report_version.id
    assert diff.target_version.version_number == 2
    assert diff.added_lines == 1
    assert diff.unchanged_lines == 1


@pytest.mark.asyncio
async def test_run_service_reuses_explicit_idempotency_key() -> None:
    store = EnterpriseMemoryStore()
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=_settings(),
        enterprise_store=store,
    )
    request = RunCreateRequest(
        topic="AI coding assistant comparison",
        competitors=["Cursor"],
        dimensions=["pricing"],
        execution_mode="demo",
        idempotency_key="temporal-request-001",
    )

    first = await service.create_run(request)
    second = await service.create_run(request)

    assert first.id == second.id
    assert first.idempotency_key == "temporal-request-001"
    assert [log.action for log in store.list_audit_logs()].count("run.created") == 1


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


@pytest.mark.asyncio
async def test_writer_node_persists_enterprise_report_version_draft() -> None:
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
    record.detail.status = "running"

    await service._demo_writer_step(record)

    projection = store.get_run_projection(created.id)
    assert projection is not None
    assert projection.report_version.report_md == record.detail.report_md
    assert projection.report_version.version_number == 1
    assert record.events[-1].payload["enterprise_projection"]["report_version_id"] == (
        projection.report_version.id
    )


@pytest.mark.asyncio
async def test_run_service_attaches_business_intel_plan_to_project() -> None:
    store = EnterpriseMemoryStore()
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=_settings(),
        enterprise_store=store,
    )

    created = await service.create_run(
        RunCreateRequest(
            topic="Cursor vs Copilot pricing battlecard",
            competitors=["Cursor", "Copilot"],
            dimensions=["pricing"],
            competitor_layer="L1",
            scenario_id="l1_pricing_pack",
            execution_mode="demo",
        )
    )

    assert created.plan.competitor_layer == "L1"
    assert created.plan.scenario_id == "l1_pricing_pack"
    assert "pricing_currentness" in created.plan.qa_rule_ids
    project = store.get_project(created.project_id or "")
    assert project is not None
    assert project.competitor_layer == "L1"
    assert project.scenario_id == "l1_pricing_pack"
    assert {item.layer for item in store.list_competitors(project_id=project.id)} == {"L1"}


@pytest.mark.asyncio
async def test_run_service_increments_enterprise_report_versions() -> None:
    store = EnterpriseMemoryStore()
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=_settings(),
        enterprise_store=store,
    )

    async def run_once() -> str:
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
        return created.id

    first_run_id = await run_once()
    second_run_id = await run_once()

    first_projection = store.get_run_projection(first_run_id)
    second_projection = store.get_run_projection(second_run_id)
    assert first_projection is not None
    assert second_projection is not None
    assert first_projection.report_version.version_number == 1
    assert second_projection.report_version.version_number == 2


def test_enterprise_router_exposes_projection() -> None:
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
    app = create_app()
    app.dependency_overrides[get_enterprise_store] = lambda: store
    client = TestClient(app)

    response = client.get(f"/api/enterprise/runs/{detail.id}/projection")
    workspaces = client.get("/api/enterprise/workspaces")
    project = client.get(f"/api/enterprise/projects/{context.project_id}")
    business_plan = client.get(f"/api/enterprise/projects/{context.project_id}/business-plan")
    qa_evaluation = client.get(f"/api/enterprise/projects/{context.project_id}/qa-evaluation")
    readiness = client.get(f"/api/enterprise/projects/{context.project_id}/readiness-score")
    gaps = client.get(f"/api/enterprise/projects/{context.project_id}/evidence-gaps")
    competitors = client.get(f"/api/enterprise/competitors?project_id={context.project_id}")
    source_registry = client.get(
        f"/api/enterprise/source-registry?workspace_id={context.workspace_id}"
    )
    source_upsert = client.post(
        "/api/enterprise/source-registry",
        json=store.list_source_registry()[0].model_dump(mode="json"),
    )
    project_upsert = client.post(
        "/api/enterprise/projects",
        json=store.get_project(context.project_id).model_dump(mode="json"),
    )
    evidence_upsert = client.post(
        "/api/enterprise/evidence",
        json=projection.evidence_records[0].model_dump(mode="json"),
    )
    evidence_search = client.get(
        "/api/enterprise/evidence/search",
        params={
            "workspace_id": context.workspace_id,
            "project_id": context.project_id,
            "query": "Cursor pricing",
        },
    )
    evidence_reindex = client.post(
        "/api/enterprise/evidence/reindex",
        params={"workspace_id": context.workspace_id},
    )
    quality = client.patch(
        f"/api/enterprise/evidence/{projection.evidence_records[0].id}/quality",
        json={"quality_label": "stale", "note": "Needs review."},
    )
    report_upsert = client.post(
        "/api/enterprise/report-versions",
        json=projection.report_version.model_dump(mode="json"),
    )
    version = client.get(f"/api/enterprise/report-versions/{projection.report_version.id}")
    diff = client.get(f"/api/enterprise/report-versions/{projection.report_version.id}/diff")

    assert response.status_code == 200
    assert response.json()["report_version"]["id"].startswith("report-run-1")
    assert workspaces.status_code == 200
    assert workspaces.json()[0]["id"] == "default-workspace"
    assert project.status_code == 200
    assert project.json()["id"] == context.project_id
    assert business_plan.status_code == 200
    assert business_plan.json()["scenario_pack"]["id"]
    assert qa_evaluation.status_code == 200
    assert "finding_count" in qa_evaluation.json()
    assert readiness.status_code == 200
    assert readiness.json()["risk_level"] in {"ready", "watch", "at_risk", "blocked"}
    assert gaps.status_code == 200
    assert "gap_count" in gaps.json()
    assert competitors.status_code == 200
    assert [item["name"] for item in competitors.json()] == ["Cursor"]
    assert source_registry.status_code == 200
    assert source_registry.json()[0]["domain"] == "cursor.sh"
    assert source_upsert.status_code == 200
    assert source_upsert.json()["source_type"] == "webpage_verified"
    assert project_upsert.status_code == 200
    assert project_upsert.json()["id"] == context.project_id
    assert evidence_upsert.status_code == 200
    assert evidence_upsert.json()["id"] == projection.evidence_records[0].id
    assert evidence_search.status_code == 200
    assert evidence_search.json()[0]["evidence"]["id"] == projection.evidence_records[0].id
    assert evidence_reindex.status_code == 200
    assert evidence_reindex.json()["indexed_count"] == 1
    assert quality.status_code == 200
    assert quality.json()["evidence"]["quality_label"] == "stale"
    assert report_upsert.status_code == 200
    assert report_upsert.json()["id"] == projection.report_version.id
    assert version.status_code == 200
    assert version.json()["id"] == projection.report_version.id
    assert diff.status_code == 200
    assert diff.json()["base_version"] is None
    assert diff.json()["added_lines"] >= 1


def test_enterprise_router_returns_404_for_missing_project() -> None:
    store = EnterpriseMemoryStore()
    app = create_app()
    app.dependency_overrides[get_enterprise_store] = lambda: store
    client = TestClient(app)

    response = client.get("/api/enterprise/projects/missing")

    assert response.status_code == 404
