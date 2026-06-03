import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.deps import get_artifact_storage, get_enterprise_store
from app.main import create_app
from packages.artifacts import LocalArtifactStorage
from packages.config import Settings
from packages.enterprise import (
    EnterpriseMemoryStore,
    WorkspaceQuotaExceededError,
    build_enterprise_projection,
    build_report_version_diff,
)
from packages.orchestrator.service import RunService
from packages.schema.api_dto import RunCreateRequest, RunDetail
from packages.schema.enterprise import (
    ArtifactRecord,
    NotificationRecord,
    WorkspaceMemberRecord,
    WorkspaceQuotaUpdateRequest,
)
from packages.schema.models import (
    AnalysisPlan,
    CompetitorKnowledge,
    KnowledgeClaim,
    PricingModel,
    RawSource,
    RunMetrics,
)
from packages.skills.registry import SkillRegistry


def _detail() -> RunDetail:
    created_at = datetime.utcnow().replace(microsecond=0)
    updated_at = created_at + timedelta(minutes=5)
    return RunDetail(
        id="run-1",
        topic="AI coding assistant comparison",
        status="completed",
        execution_mode="demo",
        created_at=created_at,
        updated_at=updated_at,
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
    assert store.get_workspace_member(first.workspace_id, "system-user").role == "owner"


def test_enterprise_store_upserts_workspace_members() -> None:
    store = EnterpriseMemoryStore()

    member = store.upsert_workspace_member(
        WorkspaceMemberRecord(
            workspace_id="workspace-a",
            user_id="analyst-1",
            role="analyst",
        )
    )

    assert member.role == "analyst"
    assert store.get_workspace_member("workspace-a", "analyst-1") == member
    assert [item.user_id for item in store.list_workspace_members("workspace-a")] == [
        "analyst-1",
        "system-user",
    ]


def test_enterprise_store_round_trips_notifications_with_audit() -> None:
    store = EnterpriseMemoryStore()

    notification = store.upsert_notification(
        NotificationRecord(
            id="notification-1",
            workspace_id="workspace-a",
            notification_type="scheduled_scan_summary",
            severity="success",
            status="sent",
            title="Scheduled scan finished",
            body="1 project scanned.",
            resource_type="scheduled_scan",
            resource_id="weekly",
        )
    )

    assert notification.status == "sent"
    assert store.list_notifications("workspace-a") == [notification]
    assert store.list_notifications("workspace-a", status="sent") == [notification]
    assert store.list_notifications("workspace-b") == []
    assert any(log.action == "notification.upserted" for log in store.list_audit_logs())


def test_enterprise_store_tracks_workspace_usage_and_quota_decision() -> None:
    store = EnterpriseMemoryStore()
    detail = _detail().model_copy(
        update={
            "status": "completed",
            "metrics": RunMetrics(
                input_tokens_estimate=700,
                output_tokens_estimate=400,
                cost_estimate_usd=0.25,
            ),
        }
    )

    context = store.start_run(detail, workspace_id="workspace-a")
    usage = store.get_workspace_usage(context.workspace_id)
    updated = store.update_workspace_quota(
        context.workspace_id,
        WorkspaceQuotaUpdateRequest(
            monthly_run_quota=1,
            monthly_token_quota=1_000,
            monthly_cost_quota_usd=0.2,
            quota_enforcement="block",
        ),
    )
    decision = store.check_workspace_quota(context.workspace_id)

    assert usage.run_count == 1
    assert usage.total_tokens_estimate == 1100
    assert usage.status == "ok"
    assert updated is not None
    assert updated.monthly_cost_quota_usd == 0.2
    assert decision.status == "exceeded"
    assert decision.allowed is False
    assert any(log.action == "workspace.quota_updated" for log in store.list_audit_logs())


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
    assert loaded.report_version.quality_metadata["memory_observations"][0]["kind"] == (
        "analysis_plan"
    )
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


def test_enterprise_store_round_trips_artifacts_with_audit() -> None:
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
    evidence = projection.evidence_records[0]

    artifact = store.upsert_artifact(
        ArtifactRecord(
            id="artifact-1",
            workspace_id=context.workspace_id,
            project_id=context.project_id,
            evidence_id=evidence.id,
            run_id=detail.id,
            artifact_type="web_snapshot",
            filename="pricing.html",
            media_type="text/html",
            storage_backend="local",
            uri="local://default-workspace/artifact-1/pricing.html",
            byte_size=128,
            content_hash="hash-artifact",
            created_by="analyst-1",
        )
    )

    assert store.get_artifact(artifact.id) == artifact
    assert store.list_artifacts(project_id=context.project_id) == [artifact]
    assert store.list_artifacts(evidence_id=evidence.id) == [artifact]
    assert any(log.action == "artifact.upserted" for log in store.list_audit_logs())


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
    assert record.events[-1].payload["enterprise_projection"]["release_gate"]["allowed"] is True
    assert not [
        item
        for item in store.list_notifications(created.workspace_id)
        if item.notification_type == "release_gate_blocked"
    ]


@pytest.mark.asyncio
async def test_run_service_records_release_gate_notification_for_weak_report() -> None:
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
    record.detail.report_md = "Weak report without evidence."
    record.detail.status = "running"

    await service._finalize_demo_pipeline(record)

    projection = store.get_run_projection(created.id)
    notifications = [
        item
        for item in store.list_notifications(created.workspace_id)
        if item.notification_type == "release_gate_blocked"
    ]
    assert projection is not None
    assert projection.report_version.status == "draft"
    assert record.detail.status == "completed_with_blockers"
    assert record.events[-1].payload["enterprise_projection"]["release_gate"]["allowed"] is False
    assert record.events[-1].payload["enterprise_projection"]["release_gate"]["status"] == "blocked"
    assert "Release gate blocked" in record.events[-1].message
    assert notifications
    assert notifications[0].resource_id == projection.report_version.id
    assert notifications[0].metadata["issue_count"] >= 1


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
async def test_run_service_blocks_when_workspace_quota_is_exhausted() -> None:
    store = EnterpriseMemoryStore()
    store.update_workspace_quota(
        "default-workspace",
        WorkspaceQuotaUpdateRequest(monthly_run_quota=0, quota_enforcement="block"),
    )
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=_settings(),
        enterprise_store=store,
    )

    with pytest.raises(WorkspaceQuotaExceededError) as exc_info:
        await service.create_run(
            RunCreateRequest(
                topic="AI coding assistant comparison",
                competitors=["Cursor"],
                dimensions=["pricing"],
                execution_mode="demo",
            )
        )

    assert exc_info.value.decision.allowed is False
    assert exc_info.value.decision.status == "exceeded"


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
    artifact_root = Path("backend/.test-artifacts/router")
    shutil.rmtree(artifact_root, ignore_errors=True)
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
    app.dependency_overrides[get_artifact_storage] = lambda: LocalArtifactStorage(artifact_root)
    client = TestClient(app)

    response = client.get(f"/api/enterprise/runs/{detail.id}/projection")
    workspaces = client.get("/api/enterprise/workspaces")
    usage = client.get(f"/api/enterprise/workspaces/{context.workspace_id}/usage")
    quota_update = client.patch(
        f"/api/enterprise/workspaces/{context.workspace_id}/quota",
        json={"monthly_run_quota": 1, "quota_enforcement": "monitor"},
    )
    quota_decision = client.get(
        f"/api/enterprise/workspaces/{context.workspace_id}/quota-decision"
    )
    notification_upsert = client.post(
        "/api/enterprise/notifications",
        json=NotificationRecord(
            id="notification-route-1",
            workspace_id=context.workspace_id,
            notification_type="scheduled_scan_summary",
            severity="success",
            status="sent",
            title="Scheduled scan finished",
        ).model_dump(mode="json"),
    )
    notifications = client.get(
        f"/api/enterprise/notifications?workspace_id={context.workspace_id}"
    )
    policy_actions = client.get("/api/enterprise/policy/actions")
    policy_decision = client.post(
        "/api/enterprise/policy/evaluate",
        json={
            "workspace_id": context.workspace_id,
            "action": "project:read",
            "target_type": "project",
            "target_id": context.project_id,
        },
    )
    model_policy = client.get("/api/enterprise/model-policy")
    project = client.get(f"/api/enterprise/projects/{context.project_id}")
    business_plan = client.get(f"/api/enterprise/projects/{context.project_id}/business-plan")
    qa_evaluation = client.get(f"/api/enterprise/projects/{context.project_id}/qa-evaluation")
    claim_validation = client.get(
        f"/api/enterprise/projects/{context.project_id}/claim-validation"
    )
    readiness = client.get(f"/api/enterprise/projects/{context.project_id}/readiness-score")
    gaps = client.get(f"/api/enterprise/projects/{context.project_id}/evidence-gaps")
    quality_matrix = client.get(f"/api/enterprise/projects/{context.project_id}/quality-matrix")
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
    artifact_create = client.post(
        "/api/enterprise/artifacts",
        json={
            "workspace_id": context.workspace_id,
            "project_id": context.project_id,
            "evidence_id": projection.evidence_records[0].id,
            "run_id": detail.id,
            "artifact_type": "web_snapshot",
            "filename": "cursor-pricing.html",
            "media_type": "text/html",
            "external_uri": "https://storage.example.test/cursor-pricing.html",
            "source_url": "https://cursor.sh/pricing",
        },
    )
    artifacts = client.get(
        "/api/enterprise/artifacts",
        params={
            "workspace_id": context.workspace_id,
            "project_id": context.project_id,
        },
    )
    release_gate = client.get(
        f"/api/enterprise/report-versions/{projection.report_version.id}/release-gate"
    )
    publish = client.post(
        f"/api/enterprise/report-versions/{projection.report_version.id}/publish"
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
    assert usage.status_code == 200
    assert usage.json()["run_count"] == 1
    assert quota_update.status_code == 200
    assert quota_update.json()["monthly_run_quota"] == 1
    assert quota_decision.status_code == 200
    assert quota_decision.json()["status"] == "exceeded"
    assert quota_decision.json()["allowed"] is True
    assert notification_upsert.status_code == 200
    assert notification_upsert.json()["id"] == "notification-route-1"
    assert notifications.status_code == 200
    assert notifications.json()[0]["notification_type"] == "scheduled_scan_summary"
    assert policy_actions.status_code == 200
    assert policy_actions.json()["project:write"] == "analyst"
    assert policy_decision.status_code == 200
    assert policy_decision.json()["allowed"] is True
    assert policy_decision.json()["engine"] == "internal-opa-compatible"
    assert model_policy.status_code == 200
    assert model_policy.json()["policy_version"] == "2026-05-phase5-model-policy"
    assert project.status_code == 200
    assert project.json()["id"] == context.project_id
    assert business_plan.status_code == 200
    assert business_plan.json()["scenario_pack"]["id"]
    assert qa_evaluation.status_code == 200
    assert "finding_count" in qa_evaluation.json()
    assert claim_validation.status_code == 200
    assert claim_validation.json()["supported_count"] == 1
    assert claim_validation.json()["self_consistency_score"] >= 70
    assert claim_validation.json()["results"][0]["self_consistency_score"] >= 70
    assert readiness.status_code == 200
    assert readiness.json()["risk_level"] in {"ready", "watch", "at_risk", "blocked"}
    assert gaps.status_code == 200
    assert "gap_count" in gaps.json()
    assert quality_matrix.status_code == 200
    assert {item["agent_name"] for item in quality_matrix.json()["entries"]} >= {
        "BusinessQA",
        "ClaimValidator",
        "EvidenceGap",
        "RedTeam",
    }
    claim_matrix = next(
        item for item in quality_matrix.json()["entries"] if item["agent_name"] == "ClaimValidator"
    )
    assert claim_matrix["framework"] == "deterministic-self-consistency"
    assert "self-consistency" in claim_matrix["summary"]
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
    assert artifact_create.status_code == 200
    artifact_id = artifact_create.json()["artifact"]["id"]
    assert artifact_create.json()["artifact"]["evidence_id"] == projection.evidence_records[0].id
    artifact = client.get(f"/api/enterprise/artifacts/{artifact_id}")
    assert artifacts.status_code == 200
    assert artifacts.json()[0]["id"] == artifact_id
    assert artifact.status_code == 200
    assert artifact.json()["storage_backend"] == "external"
    assert artifact.json()["uri"] == "https://storage.example.test/cursor-pricing.html"
    assert release_gate.status_code == 200
    assert release_gate.json()["allowed"] is True
    assert publish.status_code == 200
    assert publish.json()["status"] == "published"
    assert quality.status_code == 200
    assert quality.json()["evidence"]["quality_label"] == "stale"
    assert report_upsert.status_code == 200
    assert report_upsert.json()["id"] == projection.report_version.id
    assert version.status_code == 200
    assert version.json()["id"] == projection.report_version.id
    assert diff.status_code == 200
    assert diff.json()["base_version"] is None
    assert diff.json()["added_lines"] >= 1
    shutil.rmtree(artifact_root, ignore_errors=True)


def test_enterprise_router_blocks_report_approval_status_when_gate_fails() -> None:
    store = EnterpriseMemoryStore()
    detail = _detail()
    context = store.start_run(detail)
    projection = build_enterprise_projection(
        detail,
        workspace_id=context.workspace_id,
        project_id=context.project_id,
        competitor_id_map=context.competitor_id_map,
    )
    projection.report_version = projection.report_version.model_copy(update={"claim_ids": []})
    store.save_projection(projection)
    app = create_app()
    app.dependency_overrides[get_enterprise_store] = lambda: store
    client = TestClient(app)

    response = client.post(
        "/api/enterprise/report-versions",
        json=projection.report_version.model_copy(update={"status": "approved"}).model_dump(
            mode="json"
        ),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["status"] == "blocked"
    assert response.json()["detail"]["allowed"] is False


def test_enterprise_router_enforces_rbac_workspace_scope() -> None:
    store = EnterpriseMemoryStore()
    detail_a = _detail().model_copy(deep=True, update={"id": "run-a"})
    context_a = store.start_run(detail_a, workspace_id="workspace-a")
    projection_a = build_enterprise_projection(
        detail_a,
        workspace_id=context_a.workspace_id,
        project_id=context_a.project_id,
        competitor_id_map=context_a.competitor_id_map,
    )
    store.save_projection(projection_a)
    detail_b = _detail().model_copy(deep=True, update={"id": "run-b"})
    context_b = store.start_run(detail_b, workspace_id="workspace-b")
    projection_b = build_enterprise_projection(
        detail_b,
        workspace_id=context_b.workspace_id,
        project_id=context_b.project_id,
        competitor_id_map=context_b.competitor_id_map,
    )
    store.save_projection(projection_b)
    app = create_app()
    app.dependency_overrides[get_enterprise_store] = lambda: store
    client = TestClient(app)
    viewer_headers = {
        "X-User-Id": "viewer-a",
        "X-User-Role": "viewer",
        "X-Workspace-Id": "workspace-a",
    }
    reviewer_headers = {
        "X-User-Id": "reviewer-a",
        "X-User-Role": "reviewer",
        "X-Workspace-Id": "workspace-a",
    }

    scoped_projects = client.get("/api/enterprise/projects", headers=viewer_headers)
    cross_project = client.get(
        f"/api/enterprise/projects/{context_b.project_id}",
        headers=viewer_headers,
    )
    forbidden_write = client.post(
        "/api/enterprise/projects",
        json=store.get_project(context_a.project_id).model_dump(mode="json"),
        headers=viewer_headers,
    )
    quality = client.patch(
        f"/api/enterprise/evidence/{projection_a.evidence_records[0].id}/quality",
        json={"quality_label": "accepted", "note": "Reviewed."},
        headers=reviewer_headers,
    )

    assert scoped_projects.status_code == 200
    assert [item["workspace_id"] for item in scoped_projects.json()] == ["workspace-a"]
    assert cross_project.status_code == 403
    assert forbidden_write.status_code == 403
    assert quality.status_code == 200
    assert quality.json()["evidence"]["quality_label"] == "accepted"


def test_enterprise_router_returns_404_for_missing_project() -> None:
    store = EnterpriseMemoryStore()
    app = create_app()
    app.dependency_overrides[get_enterprise_store] = lambda: store
    client = TestClient(app)

    response = client.get("/api/enterprise/projects/missing")

    assert response.status_code == 404
