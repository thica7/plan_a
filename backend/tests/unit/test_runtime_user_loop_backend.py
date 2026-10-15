"""Regression coverage for authenticated run boundaries and the manual report loop."""

import json
from datetime import datetime

import pytest
from app import deps
from app.main import create_app
from app.middleware import auth
from fastapi.testclient import TestClient
from packages.artifacts import LocalArtifactStorage
from packages.auth import EnterpriseUserContext
from packages.business_intel.manual_revision import validate_manual_revision
from packages.config import Settings
from packages.enterprise import EnterpriseMemoryStore
from packages.memory import PreferenceMemoryStore, RunJournal
from packages.orchestrator.service import RunRecord, RunService
from packages.runtime import RuntimeCommandService
from packages.schema.api_dto import RunDetail
from packages.schema.enterprise import EnterpriseRunProjection, ManualReportRevisionRequest
from packages.schema.models import AnalysisPlan
from packages.skills.registry import SkillRegistry
from test_research_gate_repair import _records


def _service(store=None, journal=None):
    return RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(),
        enterprise_store=store,
        journal=journal,
    )


def _detail(run_id="run-a", workspace="workspace-a"):
    now = datetime.utcnow()
    return RunDetail(
        id=run_id,
        workspace_id=workspace,
        topic="Phone",
        status="completed",
        execution_mode="demo",
        created_at=now,
        updated_at=now,
        plan=AnalysisPlan(topic="Phone", competitors=["Phone"], dimensions=["pricing"]),
    )


@pytest.fixture
def secured(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    subjects = {
        "a": {"user_id": "user-a", "role": "owner", "workspace_id": "workspace-a"},
        "b": {"user_id": "user-b", "role": "owner", "workspace_id": "workspace-b"},
        "viewer": {"user_id": "viewer", "role": "viewer", "workspace_id": "workspace-a"},
        "unscoped": {"user_id": "user-u", "role": "owner"},
        "nouser": {"role": "owner", "workspace_id": "workspace-a"},
    }
    monkeypatch.setenv("AUTH_TOKEN_SUBJECTS", json.dumps(subjects))
    store = EnterpriseMemoryStore()
    service = _service(store)
    for run_id, workspace in [("run-a", "workspace-a"), ("run-b", "workspace-b")]:
        service._runs[run_id] = RunRecord(detail=_detail(run_id, workspace))
    app = create_app()
    storage = LocalArtifactStorage(tmp_path / "artifacts")
    app.dependency_overrides[deps.get_run_service] = lambda: service
    app.dependency_overrides[deps.get_enterprise_store] = lambda: store
    app.dependency_overrides[deps.get_artifact_storage] = lambda: storage
    app.dependency_overrides[deps.get_app_settings] = lambda: Settings()
    return TestClient(app), service, store, storage


def _headers(token="a"):
    return {
        "Authorization": f"Bearer {token}",
        "X-Workspace-Id": "workspace-b",
        "X-User-Role": "owner",
        "X-User-Id": "forged",
    }


@pytest.mark.parametrize(
    "suffix",
    [
        "",
        "/kb",
        "/revisions",
        "/trace",
        "/trace/spans",
        "/trace/otel",
        "/trace/observability",
        "/compliance",
        "/decision-replay",
        "/trace/agent-messages",
        "/trace/tool-calls",
        "/stream",
    ],
)
def test_legacy_run_reads_refuse_other_workspace_before_consumption(secured, suffix):
    client, service, _, _ = secured
    service._runs["run-b"].detail.status = "running"
    service._runs["run-b"].detail.current_node = "qa_hitl"
    response = client.get("/api/runs/run-b" + suffix, headers=_headers())
    assert response.status_code == 403
    # Auth must precede get_run's HITL repair or SSE subscription.
    assert service._runs["run-b"].detail.status == "running"


def test_run_list_and_baseline_are_scoped(secured):
    client, _, _, _ = secured
    response = client.get("/api/runs", headers=_headers())
    assert [item["id"] for item in response.json()] == ["run-a"]
    response = client.get(
        "/api/runs/run-a/quality-comparison?baseline_run_id=run-b", headers=_headers()
    )
    assert response.status_code == 403
    assert client.get("/api/runs/absent", headers=_headers()).status_code == 404


@pytest.mark.parametrize("token", ["unscoped", "nouser"])
def test_authenticated_subject_cannot_fall_back_to_global_owner(secured, token):
    client, _, _, _ = secured
    assert client.get("/api/runs", headers=_headers(token)).status_code == 403


@pytest.mark.parametrize(
    "body",
    [
        "Phone costs $499 in US.",
        "Phone costs $499 including tax.",
        "Phone costs $499 for all users.",
        "Phone is priced at $499.",
    ],
)
def test_manual_changed_fact_is_pending_instead_of_lexically_supported(body):
    _, _, evidence, _, version = _records()
    version.report_md = body + " [source:evidence-1]"
    _, metadata = validate_manual_revision(version, [evidence])
    assert metadata["run_qa_blocker_count"] > 0
    assert metadata["manual_claim_validation"]["results"][0]["status"] != "supported"
    assert metadata["manual_semantic_review"]["status"] == "pending_review"


def test_manual_original_source_sentence_and_formatting_remain_valid():
    _, _, evidence, _, version = _records()
    version.report_md = "## Revised\n- **Phone** costs $499. [source:evidence-1]"
    _, metadata = validate_manual_revision(version, [evidence])
    assert metadata["run_qa_findings"] == []


def test_journal_restores_manual_version_claims_and_fresh_qa(tmp_path):
    journal_path = tmp_path / "journal.db"
    store = EnterpriseMemoryStore()
    project, competitor, evidence, claim, source = _records()
    store.upsert_project(project)
    store.competitors[competitor.id] = competitor
    projection = EnterpriseRunProjection(
        workspace_id=source.workspace_id,
        project_id=source.project_id,
        run_id=source.run_id,
        evidence_records=[evidence],
        claim_records=[claim],
        report_version=source,
    )
    store.save_projection(projection)
    service = _service(store, RunJournal(journal_path))
    detail = _detail(source.run_id, source.workspace_id)
    detail.project_id = source.project_id
    detail.enterprise_projection = projection
    detail.report_md = source.report_md
    service._runs[detail.id] = RunRecord(detail=detail)
    service._persist_run(detail.id)
    runtime = RuntimeCommandService(
        settings=Settings(),
        run_service=service,
        workflow_service=object(),
        enterprise_store=store,
        preference_memory=PreferenceMemoryStore.in_memory(),
    )
    revision, _ = runtime._create_manual_report_revision(
        source,
        ManualReportRevisionRequest(report_md="Phone costs $499 in US. [source:evidence-1]"),
        EnterpriseUserContext(user_id="editor", role="owner", workspace_id=source.workspace_id),
    )
    restored_store = EnterpriseMemoryStore()
    restored = _service(restored_store, RunJournal(journal_path))
    actual = restored_store.get_report_version(revision.id)
    assert actual is not None
    assert actual.model_dump(mode="json") == revision.model_dump(mode="json")
    assert restored_store.get_report_version(source.id) is not None
    assert actual.parent_version_id == source.id
    assert actual.quality_metadata["run_qa_blocker_count"] > 0
    assert all(restored_store.claim_records.get(cid) is not None for cid in actual.claim_ids)
    assert restored.get_run(source.run_id).report_md == revision.report_md
    assert restored_store.get_project(source.project_id).workspace_id == source.workspace_id


def _store_report(store, workspace="workspace-a"):
    project, competitor, evidence, claim, source = _records()
    project.workspace_id = workspace
    competitor.workspace_id = workspace
    evidence.workspace_id = workspace
    claim.workspace_id = workspace
    source.workspace_id = workspace
    store.upsert_project(project)
    store.competitors[competitor.id] = competitor
    store.save_projection(
        EnterpriseRunProjection(
            workspace_id=workspace,
            project_id=project.id,
            run_id=source.run_id,
            evidence_records=[evidence],
            claim_records=[claim],
            report_version=source,
        )
    )
    return source


@pytest.mark.parametrize("format", ["markdown", "html", "csv"])
def test_export_download_returns_actual_authorized_version_bytes(secured, format):
    import hashlib

    client, _, store, _ = secured
    source = _store_report(store)
    exported = client.post(
        f"/api/enterprise/report-versions/{source.id}/export?format={format}", headers=_headers()
    )
    assert exported.status_code == 200
    artifact = exported.json()["artifact"]
    response = client.get(
        f"/api/enterprise/artifacts/{artifact['id']}/download", headers=_headers()
    )
    assert response.status_code == 200
    assert hashlib.sha256(response.content).hexdigest() == artifact["content_hash"]
    assert len(response.content) == artifact["byte_size"]
    assert "attachment;" in response.headers["content-disposition"]
    assert "filename*=UTF-8" in response.headers["content-disposition"]
    if format == "markdown":
        assert response.content.decode() == source.report_md
    denied = client.get(
        f"/api/enterprise/artifacts/{artifact['id']}/download", headers=_headers("b")
    )
    assert denied.status_code == 403


def test_local_artifact_download_rejects_tampering_and_cross_workspace_uri(secured):
    from packages.schema.enterprise import ArtifactCreateRequest

    client, _, store, storage = secured
    source = _store_report(store)
    artifact = storage.store(
        ArtifactCreateRequest(
            workspace_id="workspace-a",
            project_id=source.project_id,
            filename="中文报告.md",
            content_text="中文内容",
        )
    )
    store.upsert_artifact(artifact)
    response = client.get(f"/api/enterprise/artifacts/{artifact.id}/download", headers=_headers())
    assert response.status_code == 200
    assert "%E4%B8%AD%E6%96%87" in response.headers["content-disposition"]
    for change in [
        {"uri": artifact.uri.replace("workspace-a/", "workspace-b/")},
        {"uri": "local:///etc/passwd"},
        {"uri": "local://../../outside.md"},
        {"storage_backend": "s3"},
        {"content_hash": "0" * 64},
        {"byte_size": 1},
        {"report_version_id": source.id, "run_id": "another-run"},
    ]:
        store.upsert_artifact(artifact.model_copy(update=change))
        denied = client.get(f"/api/enterprise/artifacts/{artifact.id}/download", headers=_headers())
        assert denied.status_code in {400, 409}, change
    foreign = storage.store(
        ArtifactCreateRequest(
            workspace_id="workspace-b",
            project_id="foreign-project",
            filename="foreign.txt",
            content_text="SECRET FOREIGN",
        )
    )
    store.upsert_artifact(artifact.model_copy(update={"uri": foreign.uri}))
    for endpoint in ["preview", "download"]:
        denied = client.get(
            f"/api/enterprise/artifacts/{artifact.id}/{endpoint}", headers=_headers()
        )
        assert denied.status_code in {400, 409}
        assert "SECRET FOREIGN" not in denied.text


@pytest.mark.parametrize("token,run", [("a", "run-b"), ("viewer", "run-a")])
def test_research_import_refused_without_side_effects(secured, token, run):
    client, service, _, _ = secured
    body = {
        "imported_by": "forged",
        "materials": [
            {
                "source_type": "manual_note",
                "competitor": "Phone",
                "dimension": "pricing",
                "text": "Phone costs $499.",
            }
        ],
    }
    response = client.post(f"/api/runs/{run}/user-research", json=body, headers=_headers(token))
    assert response.status_code == 403
    assert service._runs[run].detail.raw_sources == []


def test_same_scope_reads_and_auth_disabled_local_compatibility(secured, monkeypatch):
    client, _, _, _ = secured
    for path in [
        "/api/runs/run-a",
        "/api/runs/run-a/kb",
        "/api/runs/run-a/trace",
        "/api/runs/run-a/revisions",
    ]:
        assert client.get(path, headers=_headers("viewer")).status_code == 200
    monkeypatch.setattr(auth, "AUTH_ENABLED", False)
    assert client.get("/api/runs/run-b").status_code == 200
    assert len(client.get("/api/runs").json()) == 2


@pytest.mark.asyncio
async def test_approval_identity_is_always_authenticated_actor():
    from types import SimpleNamespace

    from packages.runtime import ApproveReportCommand, RejectReportCommand, RequestApprovalCommand
    from packages.schema.api_dto import ReportApprovalSignalRequest, ReportApprovalStartRequest

    store = EnterpriseMemoryStore()
    source = _store_report(store)
    captured = []

    class Workflows:
        async def start_report_approval(self, request):
            captured.append(request.requested_by)
            return SimpleNamespace(workflow_id="wf")

        async def approve_report(self, version_id, request):
            captured.append(request.approver_id)
            return SimpleNamespace(workflow_id="wf", decision="approved")

        async def reject_report(self, version_id, request):
            captured.append(request.approver_id)
            return SimpleNamespace(workflow_id="wf", decision="rejected")

    runtime = RuntimeCommandService(
        settings=Settings(),
        run_service=object(),
        workflow_service=Workflows(),
        enterprise_store=store,
        preference_memory=PreferenceMemoryStore.in_memory(),
    )
    actor = EnterpriseUserContext(user_id="real-user", role="owner", workspace_id="workspace-a")
    await runtime.request_approval(
        RequestApprovalCommand(
            request=ReportApprovalStartRequest(report_version_id=source.id, requested_by="forged")
        ),
        actor=actor,
    )
    request = ReportApprovalSignalRequest(approver_id="forged")
    for command, method in [
        (ApproveReportCommand, runtime.approve_report),
        (RejectReportCommand, runtime.reject_report),
    ]:
        await method(command(report_version_id=source.id, request=request), actor=actor)
    assert captured == ["real-user"] * 3


def test_eval_baseline_does_not_expose_foreign_run(secured):
    client, service, _, _ = secured
    service._runs["run-b"].detail.status = "running"
    service._runs["run-b"].detail.current_node = "qa_hitl"
    for endpoint in ["enterprise", "enterprise/release-contract"]:
        response = client.get(f"/api/evals/{endpoint}?baseline_run_id=run-b", headers=_headers())
        assert response.status_code == 403
    assert service._runs["run-b"].detail.status == "running"


def test_manual_runtime_does_not_reuse_old_green_and_can_revise_after_restart(tmp_path):
    journal_path = tmp_path / "again.db"
    store = EnterpriseMemoryStore()
    source = _store_report(store, "workspace-1")
    service = _service(store, RunJournal(journal_path))
    detail = _detail(source.run_id, source.workspace_id)
    detail.project_id = source.project_id
    detail.enterprise_projection = store.get_run_projection(source.run_id)
    service._runs[detail.id] = RunRecord(detail=detail)
    service._persist_run(detail.id)
    actor = EnterpriseUserContext(user_id="editor", role="owner", workspace_id=source.workspace_id)
    runtime = RuntimeCommandService(
        settings=Settings(),
        run_service=service,
        workflow_service=object(),
        enterprise_store=store,
        preference_memory=PreferenceMemoryStore.in_memory(),
    )
    first, _ = runtime._create_manual_report_revision(
        source,
        ManualReportRevisionRequest(
            report_md="Phone costs $499 including tax. [source:evidence-1]"
        ),
        actor,
    )
    assert first.quality_metadata["release_gate"]["allowed"] is False
    assert first.quality_metadata["manual_semantic_review"]["status"] == "pending_review"
    assert first.quality_metadata["manual_revision"]["validation_status"] == "blocked"
    restored_store = EnterpriseMemoryStore()
    restored = _service(restored_store, RunJournal(journal_path))
    runtime = RuntimeCommandService(
        settings=Settings(),
        run_service=restored,
        workflow_service=object(),
        enterprise_store=restored_store,
        preference_memory=PreferenceMemoryStore.in_memory(),
    )
    second, _ = runtime._create_manual_report_revision(
        restored_store.get_report_version(first.id),
        ManualReportRevisionRequest(report_md="## 修订\nPhone costs $499. [source:evidence-1]"),
        actor,
    )
    assert second.parent_version_id == first.id
    assert second.version_number == first.version_number + 1
    assert second.quality_metadata["run_qa_findings"] == []
    again = _service(EnterpriseMemoryStore(), RunJournal(journal_path))
    assert again.enterprise_store.get_report_version(second.id).report_md == second.report_md
    assert (
        again.enterprise_store.get_report_version(first.id).quality_metadata["run_qa_blocker_count"]
        > 0
    )
    from app.routers.enterprise import download_artifact, export_report_version

    storage = LocalArtifactStorage(tmp_path / "restart-exports")
    exported = export_report_version(
        second.id, again.enterprise_store, actor, storage, format="markdown"
    )
    downloaded = download_artifact(exported.artifact.id, again.enterprise_store, actor, storage)
    assert downloaded.body.decode() == second.report_md


def test_journal_restore_never_overwrites_existing_enterprise_versions(tmp_path):
    journal = RunJournal(tmp_path / "newer.db")
    store = EnterpriseMemoryStore()
    source = _store_report(store, "workspace-1")
    detail = _detail(source.run_id, source.workspace_id)
    detail.project_id = source.project_id
    detail.enterprise_projection = store.get_run_projection(source.run_id)
    journal.save_run(detail)
    newer = source.model_copy(
        update={
            "id": "newer",
            "version_number": 10,
            "report_md": "New durable version",
            "parent_version_id": source.id,
        }
    )
    store.upsert_report_version(newer)
    restored = _service(store, journal)
    assert restored.get_run(source.run_id).report_md == "New durable version"
    assert store.get_report_version("newer").version_number == 10


def test_old_embedded_projection_restores_without_inventing_new_qa(tmp_path):
    journal = RunJournal(tmp_path / "old.db")
    store = EnterpriseMemoryStore()
    source = _store_report(store, "workspace-1")
    source.quality_metadata["run_qa_findings"] = [
        {"severity": "blocker", "problem": "old honest gap"}
    ]
    store.upsert_report_version(source)
    detail = _detail(source.run_id, source.workspace_id)
    detail.project_id = source.project_id
    detail.enterprise_projection = store.get_run_projection(source.run_id)
    journal.save_run(detail)
    restored = _service(EnterpriseMemoryStore(), journal)
    actual = restored.enterprise_store.get_report_version(source.id)
    assert actual is not None
    assert actual.quality_metadata["run_qa_findings"] == source.quality_metadata["run_qa_findings"]


@pytest.mark.parametrize("mutation", ["", "source_hash", "body", "producer"])
def test_only_current_audited_claim_can_survive_format_only_revision(monkeypatch, mutation):
    from datetime import date

    from packages.enterprise.projection import build_enterprise_projection
    from packages.research.evidence.answer_guard import evaluate_answer_boundary
    from packages.research.evidence.answer_models import AnswerRequirement
    from packages.research.evidence.report_claims import (
        ReportClaim,
        ReportDimensionAudit,
        audit_report_claims,
    )
    from packages.research.evidence.snapshot import seal_snapshot
    from test_answer_guard_workflow import fixture_detail
    from test_stage_evidence_views import FixedTime

    monkeypatch.setattr("packages.research.evidence.views.datetime", FixedTime)
    detail = fixture_detail()
    store = EnterpriseMemoryStore()
    service = _service(store)
    record = RunRecord(detail)
    service._runs[detail.id] = record
    seal_snapshot(detail, phase="analysis", canonical_documents={})
    view, use = service._begin_evidence_use(
        record, agent="writer", competitor="Product A", dimension="pricing"
    )
    fact = next(item for item in view.facts if item.field == "price")
    requirement = AnswerRequirement(
        competitor="Product A",
        dimension="pricing",
        intent="recorded_price",
        as_of=date(2026, 10, 3),
    )
    boundary = evaluate_answer_boundary(view, requirement)
    claim = ReportClaim(
        id="reviewed",
        text="页面采集报价为 3999 CNY。",
        kind="fact",
        competitor="Product A",
        dimension="pricing",
        fact_ids=(fact.id,),
        source_ids=(fact.source_id,),
    )
    reviewed = audit_report_claims(
        [claim],
        [
            {
                "claim_id": claim.id,
                "verdict": "supported",
                "reason": "The recorded amount and currency match the source.",
            }
        ],
        view,
        [boundary],
    )
    assert reviewed[0].status == "supported"
    detail.report_answer_boundaries = [boundary]
    detail.report_dimension_audits = [
        ReportDimensionAudit(
            competitor="Product A",
            dimension="pricing",
            consumption_id=use.id,
            claims=tuple(reviewed),
        )
    ]
    detail.report_md = claim.text + f" [source:{fact.source_id}]"
    service._validate_evidence_use(record, use)
    service._record_evidence_artifact(
        record, kind="writer", payload=service._writer_evidence_artifact_payload(detail), uses=[use]
    )
    projection = build_enterprise_projection(
        detail, workspace_id=detail.workspace_id, project_id=detail.project_id
    )
    store.start_run(detail, workspace_id=detail.workspace_id, project_id=detail.project_id)
    store.save_projection(projection)
    source = projection.report_version
    if mutation == "source_hash":
        detail.raw_sources[0].content_hash = "changed"
    elif mutation == "body":
        source = source.model_copy(
            update={"report_md": source.report_md + "\nUnverified assertion."}
        )
    elif mutation == "producer":
        detail.evidence_artifact_dependencies = []
    verified = service.current_manual_claims(source, projection.evidence_records)
    assert bool(verified) is (not mutation)
    edited = source.model_copy(update={"id": "manual", "report_md": "## 排版\n" + source.report_md})
    _, metadata = validate_manual_revision(
        edited, projection.evidence_records, verified_claims=verified
    )
    assert (metadata["run_qa_blocker_count"] == 0) is (not mutation)


@pytest.mark.parametrize(
    "snippet,body",
    [
        ("Phone costs $499. This price is US-only and excludes tax.", "Phone costs $499."),
        ("Guests can edit. Only with document access on paid plans.", "Guests can edit."),
    ],
)
def test_manual_source_sentence_cannot_drop_conditions_in_other_sentence(snippet, body):
    _, _, evidence, _, version = _records()
    evidence.snippet = snippet
    version.report_md = body + " [source:evidence-1]"
    _, metadata = validate_manual_revision(version, [evidence])
    assert metadata["run_qa_blocker_count"] > 0
    assert metadata["manual_semantic_review"]["status"] == "pending_review"


@pytest.mark.parametrize(
    "snippet,body",
    [
        ("Phone supports is_admin.", "Phone supports isadmin."),
        ("Phone stores 8 MB.", "Phone stores 8 Mb."),
    ],
)
def test_manual_format_equivalence_does_not_change_identifiers_or_units(snippet, body):
    _, _, evidence, _, version = _records()
    evidence.snippet = snippet
    version.report_md = body + " [source:evidence-1]"
    _, metadata = validate_manual_revision(version, [evidence])
    assert metadata["run_qa_blocker_count"] > 0


def test_old_embedded_projection_with_uncited_sources_restores_reference_subset(tmp_path):
    journal = RunJournal(tmp_path / "uncited.db")
    store = EnterpriseMemoryStore()
    source = _store_report(store, "workspace-1")
    projection = store.get_run_projection(source.run_id)
    projection.evidence_records.append(
        projection.evidence_records[0].model_copy(update={"id": "uncited"})
    )
    projection.claim_records.append(
        projection.claim_records[0].model_copy(update={"id": "unpublished"})
    )
    detail = _detail(source.run_id, source.workspace_id)
    detail.project_id = source.project_id
    detail.enterprise_projection = projection
    journal.save_run(detail)
    restored = _service(EnterpriseMemoryStore(), journal)
    actual = restored.enterprise_store.get_report_version(source.id)
    assert actual is not None
    assert actual.evidence_ids == source.evidence_ids
    assert actual.claim_ids == source.claim_ids


def test_journal_rejects_mismatched_projection_without_partial_run_write(tmp_path):
    journal = RunJournal.in_memory()
    store = EnterpriseMemoryStore()
    source = _store_report(store, "workspace-a")
    projection = store.get_run_projection(source.run_id)
    detail = _detail(source.run_id, "workspace-b")
    detail.project_id = source.project_id
    with pytest.raises(ValueError, match="scope mismatch"):
        journal.save_run(detail, projections=[projection])
    assert journal.load_run(detail.id) is None


def test_run_list_honors_the_workspace_read_policy_before_repair(secured, monkeypatch):
    from packages.auth import rbac

    client, service, _, _ = secured
    service._runs["run-a"].detail.status = "running"
    service._runs["run-a"].detail.current_node = "qa_hitl"
    monkeypatch.setattr(rbac, "can_perform", lambda role, action: False)
    response = client.get("/api/runs", headers=_headers())
    assert response.status_code == 403
    assert service._runs["run-a"].detail.status == "running"


def test_project_and_release_eval_consumers_do_not_hydrate_foreign_runs(secured):
    client, service, store, _ = secured
    source = _store_report(store)
    service._runs['run-b'].detail.status = 'running'
    service._runs['run-b'].detail.current_node = 'qa_hitl'
    runtime = RuntimeCommandService(settings=Settings(), run_service=service,
        workflow_service=object(), enterprise_store=store,
        preference_memory=PreferenceMemoryStore.in_memory())
    runtime._evalops_release_contract_for_version(source)
    assert service._runs['run-b'].detail.status == 'running'
    response = client.get(f'/api/enterprise/projects/{source.project_id}/quality-matrix',
                          headers=_headers())
    assert response.status_code == 200
    assert service._runs['run-b'].detail.status == 'running'


@pytest.mark.parametrize("citation", ["", " [source:evidence-1]"])
def test_manual_fact_heading_requires_fresh_review_with_or_without_citation(citation):
    _, _, evidence, _, version = _records()
    version.report_md = (
        "## Phone costs $499 including tax." + citation
        + "\nPhone costs $499. [source:evidence-1]"
    )
    _, metadata = validate_manual_revision(version, [evidence])
    assert metadata["run_qa_blocker_count"] > 0
    assert metadata["manual_semantic_review"]["status"] == "pending_review"
    if citation:
        assert metadata["manual_semantic_review"]["pending_claim_ids"]
    else:
        assert metadata["unresolved_manual_claims"][0]["line_number"] == 1


@pytest.mark.parametrize("heading", [
    "## Executive Summary", "## 产品对比", "## Phone pricing", "### Evidence & limitations",
])
def test_manual_plain_section_heading_is_not_an_uncited_claim(heading):
    _, _, evidence, _, version = _records()
    version.report_md = heading + "\nPhone costs $499. [source:evidence-1]"
    claims, metadata = validate_manual_revision(version, [evidence])
    assert len(claims) == 1
    assert metadata["run_qa_findings"] == []


@pytest.mark.parametrize("assertion", ["Phone 免费且不限用户", "Phone can edit every document."])
@pytest.mark.parametrize("citation", ["", " [source:evidence-1]"])
@pytest.mark.parametrize("layout", ["heading", "table_header"])
def test_manual_unknown_heading_and_table_header_assertions_are_not_auto_checked(
    assertion, citation, layout,
):
    _, _, evidence, _, version = _records()
    if layout == "heading":
        changed = "## " + assertion + citation
    else:
        changed = "| " + assertion + citation + " |\n| --- |\n| Phone |"
    version.report_md = changed + "\nPhone costs $499. [source:evidence-1]"
    _, metadata = validate_manual_revision(version, [evidence])
    assert metadata["run_qa_blocker_count"] > 0
    assert metadata["manual_semantic_review"]["status"] == "pending_review"


@pytest.mark.parametrize("header", [
    "| 产品 | 操作 | 证据 | 价格 |", "| Phone |", "| Product | Operation | Evidence | Price |",
])
def test_manual_neutral_table_column_labels_remain_structural(header):
    _, _, evidence, _, version = _records()
    divider = "| " + " | ".join("---" for _ in header.strip("|").split("|")) + " |"
    version.report_md = header + "\n" + divider + "\nPhone costs $499. [source:evidence-1]"
    claims, metadata = validate_manual_revision(version, [evidence])
    assert len(claims) == 1
    assert metadata["run_qa_findings"] == []
