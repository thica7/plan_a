import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.deps import get_artifact_storage, get_enterprise_store, get_preference_memory
from app.main import create_app
from app.routers.enterprise import _with_gap_fill_release_gate_delta
from packages.artifacts import LocalArtifactStorage
from packages.config import Settings
from packages.enterprise import (
    EnterpriseMemoryStore,
    WorkspaceQuotaExceededError,
    build_enterprise_projection,
    build_report_version_diff,
)
from packages.memory import PreferenceMemoryStore
from packages.orchestrator.service import RunService
from packages.schema.api_dto import RunCreateRequest, RunDetail
from packages.schema.enterprise import (
    ArtifactRecord,
    EvidenceGapFillResult,
    EvidenceGapReport,
    NotificationRecord,
    SchemaEvolutionSuggestion,
    UserFeedbackRecord,
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
    SkillOutputSpec,
    SkillSpec,
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
        report_md=_structured_demo_report(),
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


def _structured_demo_report(source_id: str = "pricing-1") -> str:
    citation = f"[source:{source_id}]"
    return f"""
# Cursor Direct Battlecard

## Executive Summary
Cursor publishes pricing and the claim is scoped to accepted pricing evidence. {citation}

## Source Quality & Coverage
The report uses verified webpage evidence and keeps broader enterprise claims out of scope.
{citation}

## Side-by-Side Decision Matrix
| Dimension | Cursor |
| --- | --- |
| Pricing | Cursor publishes pricing. {citation} |

## Battlecard
Use pricing transparency as the direct battlecard point, pending feature and procurement review.
{citation}

## Next Collection / Verification Plan
Collect feature, security, and procurement sources before publishing broader recommendations.
{citation}

## Evidence Appendix
- {source_id}: Cursor pricing evidence. {citation}
""".strip()


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


def test_enterprise_store_deduplicates_embedding_index_by_content_hash() -> None:
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
    canonical = projection.evidence_records[0]
    duplicate = canonical.model_copy(
        update={
            "id": "zz-duplicate-evidence",
            "raw_source_id": "duplicate-source",
            "canonical_url": "https://mirror.example/pricing",
            "metadata": {},
        }
    )

    stored_duplicate = store.upsert_evidence(duplicate)
    embeddings = store.list_evidence_embeddings(workspace_id=context.workspace_id)
    hits = store.search_evidence(
        workspace_id=context.workspace_id,
        project_id=context.project_id,
        query="Cursor pricing plan",
        limit=5,
    )
    reindexed = store.reindex_evidence_embeddings(workspace_id=context.workspace_id)

    assert stored_duplicate.metadata["embedding_duplicate_of"] == canonical.id
    assert stored_duplicate.metadata["embedding_indexed"] is False
    canonical_after_duplicate = store.evidence_records[canonical.id]
    assert canonical_after_duplicate.metadata["embedding_duplicate_ids"] == [
        "zz-duplicate-evidence"
    ]
    assert canonical_after_duplicate.metadata["embedding_duplicate_count"] == 1
    assert len(store.list_evidence(project_id=context.project_id)) == 2
    assert len(embeddings) == 1
    assert embeddings[0].evidence_id == canonical.id
    assert [hit.evidence.id for hit in hits] == [canonical.id]
    assert reindexed.indexed_count == 1
    assert reindexed.duplicate_count == 1
    assert (
        store.evidence_records["zz-duplicate-evidence"].metadata["embedding_duplicate_of"]
        == canonical.id
    )
    assert store.evidence_records[canonical.id].metadata["embedding_duplicate_count"] == 1


def test_schema_suggestion_review_persists_metadata_and_updates_plan_dimensions() -> None:
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
    suggestion = SchemaEvolutionSuggestion(
        id="schema-suggestion-enterprise-sso",
        dimension="enterprise_sso",
        normalized_dimension="enterprise_sso",
        reason="Reviewer wants enterprise SSO tracked as a first-class dimension.",
        source_gap_ids=["gap-enterprise-sso"],
        proposed_skill=SkillSpec(
            name="enterprise_sso",
            subagent_class="GenericCollector",
            description="Collect enterprise SSO evidence.",
            tools_allowlist=["web_search", "fetch_page"],
            query_templates=["{competitor} enterprise SSO official"],
            source_type="webpage",
            output=SkillOutputSpec(
                prefix="enterprise_sso",
                confidence_default=0.8,
                confidence_no_url=0.45,
                required_dimension="enterprise_sso",
            ),
        ),
    )
    app = create_app()
    app.dependency_overrides[get_enterprise_store] = lambda: store
    client = TestClient(app)

    response = client.post(
        f"/api/enterprise/projects/{context.project_id}/schema-suggestions/{suggestion.id}/review",
        headers={"X-User-Role": "reviewer"},
        json={
            "decision": "accepted",
            "note": "Track enterprise SSO in this project.",
            "suggestion": suggestion.model_dump(mode="json"),
        },
    )
    plan = client.get(f"/api/enterprise/projects/{context.project_id}/business-plan")
    gaps = client.get(f"/api/enterprise/projects/{context.project_id}/evidence-gaps")

    assert response.status_code == 200
    body = response.json()
    assert body["review"]["decision"] == "accepted"
    assert body["accepted_schema_dimensions"]["enterprise_sso"]["reviewed_by"] == "system-user"
    project = store.get_project(context.project_id)
    assert project is not None
    assert "enterprise_sso" in project.metadata["accepted_schema_dimensions"]
    assert plan.status_code == 200
    assert "enterprise_sso" in plan.json()["requested_dimensions"]
    assert gaps.status_code == 200
    assert any(gap["dimension"] == "enterprise_sso" for gap in gaps.json()["gaps"])
    assert any(
        log.action == "project.upserted"
        and log.resource_id == context.project_id
        and "accepted_schema_dimensions" in log.after.get("metadata", {})
        for log in store.list_audit_logs()
    )


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


def test_enterprise_store_audits_report_version_status_changes() -> None:
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

    store.upsert_report_version(projection.report_version.model_copy(update={"status": "approved"}))
    status_logs = [
        log
        for log in store.list_audit_logs()
        if log.action == "report_version.status_changed"
    ]

    assert len(status_logs) == 1
    assert status_logs[0].resource_id == projection.report_version.id
    assert status_logs[0].before == {"status": "draft"}
    assert status_logs[0].after["status"] == "approved"
    assert status_logs[0].after["project_id"] == projection.project_id


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
                f"{first_detail.report_md}\n"
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
    assert diff.unchanged_lines >= 1


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
    assert {event.type for event in record.events} >= {
        "claim.validated",
        "self_consistency.sampled",
        "benchmark.scored",
    }
    claim_event = next(event for event in record.events if event.type == "claim.validated")
    consistency_event = next(
        event for event in record.events if event.type == "self_consistency.sampled"
    )
    assert claim_event.payload["claim_validation"]["supported_count"] == 1
    assert claim_event.payload["claim_status_counts"]["supported"] == 1
    assert consistency_event.payload["self_consistency_score"] >= 70
    assert consistency_event.payload["consistency_votes"]["text_support"] >= 1
    assert consistency_event.payload["consistency_votes"]["supported_claims"] == 1
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
async def test_run_service_applies_confirmed_memory_to_plan() -> None:
    store = EnterpriseMemoryStore()
    memory = PreferenceMemoryStore.in_memory()
    feedback = memory.add_feedback(
        UserFeedbackRecord(
            id="",
            workspace_id="default-workspace",
            project_id="project-memory",
            user_id="analyst-1",
            feedback_type="preference",
            target_type="project",
            target_id="project-memory",
            message="Prefer persona evidence and concise battlecard tables in this project.",
            tags=[],
        )
    )
    for candidate in memory.extract_candidates(feedback, auto_confirm=True):
        memory.upsert_candidate(candidate)
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=_settings(),
        enterprise_store=store,
        preference_memory=memory,
    )

    created = await service.create_run(
        RunCreateRequest(
            topic="AI coding assistant comparison",
            competitors=["Cursor"],
            dimensions=["pricing"],
            execution_mode="demo",
            project_id="project-memory",
        )
    )

    assert "persona" in created.plan.dimensions
    assert created.plan.memory_candidate_ids
    assert created.plan.memory_recall_score >= 70
    assert any("battlecard" in item for item in created.plan.memory_prompt_context)
    report_md = service._demo_report(created)
    assert "## Memory Context" in report_md
    assert created.plan.memory_candidate_ids[0] in report_md
    assert "Confirmed MemoryAgent preferences" in report_md


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
    memory = PreferenceMemoryStore.in_memory()
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
    app.dependency_overrides[get_preference_memory] = lambda: memory
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
    memory_ingest = client.post(
        f"/api/enterprise/projects/{context.project_id}/memory/feedback",
        json={
            "feedback_type": "preference",
            "target_type": "report",
            "target_id": projection.report_version.id,
            "message": (
                "Prefer official pricing sources, concise battlecard tables, and explicit "
                "evidence gap risks."
            ),
            "tags": [],
        },
    )
    candidate_id = memory_ingest.json()["candidates"][0]["id"]
    memory_confirm = client.patch(
        f"/api/enterprise/projects/{context.project_id}/memory/candidates/{candidate_id}",
        params={"status": "confirmed"},
        headers={"X-User-Role": "reviewer"},
    )
    memory_recall = client.get(
        f"/api/enterprise/projects/{context.project_id}/memory/recall",
        params={"query": "pricing source risk"},
    )
    memory_feedback = client.get(
        f"/api/enterprise/projects/{context.project_id}/memory/feedback"
    )
    memory_stats = client.get(f"/api/enterprise/projects/{context.project_id}/memory/stats")
    readiness = client.get(f"/api/enterprise/projects/{context.project_id}/readiness-score")
    gaps = client.get(f"/api/enterprise/projects/{context.project_id}/evidence-gaps")
    red_team = client.get(f"/api/enterprise/projects/{context.project_id}/red-team")
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
    draft_publish = client.post(
        f"/api/enterprise/report-versions/{projection.report_version.id}/publish"
    )
    approval_upsert = client.post(
        "/api/enterprise/report-versions",
        json=projection.report_version.model_copy(update={"status": "approved"}).model_dump(
            mode="json"
        ),
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
    assert memory_ingest.status_code == 200
    assert memory_ingest.json()["feedback"]["id"].startswith("feedback-")
    assert memory_ingest.json()["candidates"]
    assert memory_confirm.status_code == 200
    assert memory_confirm.json()["status"] == "confirmed"
    assert memory_recall.status_code == 200
    assert memory_recall.json()["candidates"][0]["id"] == candidate_id
    assert memory_feedback.status_code == 200
    assert memory_feedback.json()[0]["target_id"] == projection.report_version.id
    assert memory_stats.status_code == 200
    assert memory_stats.json()["confirmed_candidate_count"] >= 1
    assert readiness.status_code == 200
    assert readiness.json()["risk_level"] in {"ready", "watch", "at_risk", "blocked"}
    assert gaps.status_code == 200
    assert "gap_count" in gaps.json()
    assert gaps.json()["framework"] == "pydantic-ai"
    assert gaps.json()["pydantic_ai_execution_mode"] == "deterministic_handler"
    assert gaps.json()["pydantic_ai_model_backed_requested"] is False
    assert gaps.json()["typed_contract_enforced"] is True
    assert red_team.status_code == 200
    assert red_team.json()["framework"] == "pydantic-ai"
    assert red_team.json()["pydantic_ai_execution_mode"] == "deterministic_handler"
    assert red_team.json()["pydantic_ai_model_backed_requested"] is False
    assert red_team.json()["typed_contract_enforced"] is True
    assert quality_matrix.status_code == 200
    assert {item["agent_name"] for item in quality_matrix.json()["entries"]} >= {
        "BusinessQA",
        "ClaimValidator",
        "EvidenceGap",
        "RedTeam",
        "ReleaseGate",
        "MemoryAgent",
    }
    claim_matrix = next(
        item for item in quality_matrix.json()["entries"] if item["agent_name"] == "ClaimValidator"
    )
    assert claim_matrix["framework"] == "deterministic-self-consistency"
    assert "self-consistency" in claim_matrix["summary"]
    memory_matrix = next(
        item for item in quality_matrix.json()["entries"] if item["agent_name"] == "MemoryAgent"
    )
    assert memory_matrix["framework"] == "deterministic-preference-memory"
    assert memory_matrix["score"] >= 80
    evidence_gap_matrix = next(
        item for item in quality_matrix.json()["entries"] if item["agent_name"] == "EvidenceGap"
    )
    assert evidence_gap_matrix["metadata"]["pydantic_ai_execution_mode"] == "deterministic_handler"
    assert evidence_gap_matrix["metadata"]["typed_contract_enforced"] is True
    red_team_matrix = next(
        item for item in quality_matrix.json()["entries"] if item["agent_name"] == "RedTeam"
    )
    assert red_team_matrix["metadata"]["pydantic_ai_execution_mode"] == "deterministic_handler"
    assert red_team_matrix["metadata"]["typed_contract_enforced"] is True
    release_matrix = next(
        item for item in quality_matrix.json()["entries"] if item["agent_name"] == "ReleaseGate"
    )
    assert release_matrix["framework"] == "enterprise-release-gate"
    assert release_matrix["status"] == "pass"
    assert projection.report_version.id in release_matrix["summary"]
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
    assert draft_publish.status_code == 409
    assert draft_publish.json()["detail"]["reason"] == "report_approval_required"
    assert approval_upsert.status_code == 200
    assert approval_upsert.json()["status"] == "approved"
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


def test_enterprise_router_blocks_direct_publish_status_without_approval() -> None:
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

    direct_publish = client.post(
        "/api/enterprise/report-versions",
        json=projection.report_version.model_copy(update={"status": "published"}).model_dump(
            mode="json"
        ),
    )
    approved = client.post(
        "/api/enterprise/report-versions",
        json=projection.report_version.model_copy(update={"status": "approved"}).model_dump(
            mode="json"
        ),
    )
    approved_publish = client.post(
        "/api/enterprise/report-versions",
        json=projection.report_version.model_copy(update={"status": "published"}).model_dump(
            mode="json"
        ),
    )

    assert direct_publish.status_code == 409
    assert direct_publish.json()["detail"]["reason"] == "report_approval_required"
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved_publish.status_code == 200
    assert approved_publish.json()["status"] == "published"


def test_gap_fill_result_carries_release_gate_improvement_delta() -> None:
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
    source_version = projection.report_version.model_copy(
        update={
            "id": "report-source-gapped",
            "version_number": 1,
            "evidence_ids": [],
            "claim_ids": [],
        }
    )
    store.upsert_report_version(source_version)
    project = store.get_project(context.project_id)
    assert project is not None
    result = EvidenceGapFillResult(
        project_id=context.project_id,
        workspace_id=context.workspace_id,
        source_report_version_id=source_version.id,
        updated_report_version_id=projection.report_version.id,
        gap_count=1,
        filled_gap_count=1,
        added_evidence_count=1,
        candidate_evidence_ids=projection.report_version.evidence_ids,
        filled_gap_ids=["gap-pricing"],
        remaining_gap_ids=[],
        report=EvidenceGapReport(
            project_id=context.project_id,
            scenario_id="l1_pricing_pack",
            gap_count=0,
        ),
        updated_report_version=projection.report_version,
    )

    enriched = _with_gap_fill_release_gate_delta(result, project=project, store=store)

    assert enriched.source_release_gate is not None
    assert enriched.updated_release_gate is not None
    assert enriched.source_release_gate.allowed is False
    assert enriched.updated_release_gate.allowed is True
    assert enriched.release_gate_improved is True
    assert enriched.release_gate_blocker_delta > 0
    assert enriched.readiness_score_delta >= 0


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
