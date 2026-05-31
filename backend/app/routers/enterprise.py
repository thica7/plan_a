from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder

from app.deps import get_enterprise_store, get_enterprise_user_context
from packages.auth import EnterpriseUserContext, can_access_workspace
from packages.business_intel import (
    analyze_evidence_gaps,
    analyze_red_team,
    build_business_intel_plan,
    evaluate_business_qa,
    evaluate_report_release_gate,
    list_business_qa_rules,
    list_scenario_packs,
    score_competitors,
    score_project_readiness,
)
from packages.enterprise import EnterpriseStore, build_report_version_diff
from packages.schema.enterprise import (
    AuditLogRecord,
    BusinessIntelPlan,
    BusinessQAEvaluation,
    BusinessQARule,
    ClaimRecord,
    CompetitorRecord,
    CompetitorScoreReport,
    EnterpriseRunProjection,
    EvidenceGapReport,
    EvidenceQualityUpdateRequest,
    EvidenceQualityUpdateResult,
    EvidenceRecord,
    EvidenceReindexResult,
    EvidenceSearchHit,
    NotificationRecord,
    ProjectReadinessScore,
    ProjectRecord,
    RedTeamReport,
    ReportReleaseGate,
    ReportVersionDiff,
    ReportVersionRecord,
    ScenarioPack,
    SourceRegistryRecord,
    WorkspaceMemberRecord,
    WorkspaceQuotaDecision,
    WorkspaceQuotaUpdateRequest,
    WorkspaceRecord,
    WorkspaceUsageSummary,
)

router = APIRouter()
EnterpriseStoreDep = Annotated[EnterpriseStore, Depends(get_enterprise_store)]
EnterpriseUserDep = Annotated[EnterpriseUserContext, Depends(get_enterprise_user_context)]


@router.get("/enterprise/workspaces", response_model=list[WorkspaceRecord])
def list_workspaces(
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
) -> list[WorkspaceRecord]:
    workspaces = store.list_workspaces()
    if user.workspace_id is not None:
        _require_workspace_access(user, user.workspace_id, "workspace:read")
        workspaces = [item for item in workspaces if item.id == user.workspace_id]
    return workspaces


@router.get("/enterprise/workspace-members", response_model=list[WorkspaceMemberRecord])
def list_workspace_members(
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
    workspace_id: str | None = None,
) -> list[WorkspaceMemberRecord]:
    scoped_workspace_id = _scoped_workspace_id(user, workspace_id, "workspace:read")
    return store.list_workspace_members(workspace_id=scoped_workspace_id)


@router.post("/enterprise/workspace-members", response_model=WorkspaceMemberRecord)
def upsert_workspace_member(
    member: WorkspaceMemberRecord,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
) -> WorkspaceMemberRecord:
    _require_workspace_access(user, member.workspace_id, "workspace:write")
    return store.upsert_workspace_member(member)


@router.get(
    "/enterprise/workspaces/{workspace_id}/usage",
    response_model=WorkspaceUsageSummary,
)
def get_workspace_usage(
    workspace_id: str,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
) -> WorkspaceUsageSummary:
    _require_workspace_access(user, workspace_id, "workspace:read")
    return store.get_workspace_usage(workspace_id)


@router.get(
    "/enterprise/workspaces/{workspace_id}/quota-decision",
    response_model=WorkspaceQuotaDecision,
)
def get_workspace_quota_decision(
    workspace_id: str,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
) -> WorkspaceQuotaDecision:
    _require_workspace_access(user, workspace_id, "workspace:read")
    return store.check_workspace_quota(workspace_id)


@router.patch("/enterprise/workspaces/{workspace_id}/quota", response_model=WorkspaceRecord)
def update_workspace_quota(
    workspace_id: str,
    request: WorkspaceQuotaUpdateRequest,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
) -> WorkspaceRecord:
    _require_workspace_access(user, workspace_id, "workspace:write")
    workspace = store.update_workspace_quota(
        workspace_id,
        request,
        actor_id=user.user_id,
    )
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


@router.get("/enterprise/notifications", response_model=list[NotificationRecord])
def list_notifications(
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
    workspace_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[NotificationRecord]:
    scoped_workspace_id = _scoped_workspace_id(user, workspace_id, "notification:read")
    return store.list_notifications(
        workspace_id=scoped_workspace_id,
        status=status,
        limit=limit,
    )


@router.post("/enterprise/notifications", response_model=NotificationRecord)
def upsert_notification(
    notification: NotificationRecord,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
) -> NotificationRecord:
    _require_workspace_access(user, notification.workspace_id, "notification:write")
    if notification.project_id is not None:
        project = store.get_project(notification.project_id)
        if project is not None and project.workspace_id != notification.workspace_id:
            raise HTTPException(
                status_code=400,
                detail="Notification workspace does not match project",
            )
    return store.upsert_notification(notification)


@router.get("/enterprise/scenario-packs", response_model=list[ScenarioPack])
def get_scenario_packs() -> list[ScenarioPack]:
    return list_scenario_packs()


@router.get("/enterprise/qa-rules", response_model=list[BusinessQARule])
def get_qa_rules(
    layer: str | None = None,
) -> list[BusinessQARule]:
    return list_business_qa_rules(layer=layer)


@router.get("/enterprise/projects", response_model=list[ProjectRecord])
def list_projects(
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
    workspace_id: str | None = None,
) -> list[ProjectRecord]:
    scoped_workspace_id = _scoped_workspace_id(user, workspace_id, "project:read")
    return store.list_projects(workspace_id=scoped_workspace_id)


@router.post("/enterprise/projects", response_model=ProjectRecord)
def upsert_project(
    project: ProjectRecord,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
) -> ProjectRecord:
    _require_workspace_access(user, project.workspace_id, "project:write")
    return store.upsert_project(project)


@router.get("/enterprise/projects/{project_id}", response_model=ProjectRecord)
def get_project(
    project_id: str,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
) -> ProjectRecord:
    return _project_or_404(project_id, store, user, "project:read")


@router.get("/enterprise/projects/{project_id}/business-plan", response_model=BusinessIntelPlan)
def get_project_business_plan(
    project_id: str,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
) -> BusinessIntelPlan:
    return _business_plan_for_project(project_id, store, user)


@router.get("/enterprise/projects/{project_id}/qa-evaluation", response_model=BusinessQAEvaluation)
def get_project_qa_evaluation(
    project_id: str,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
) -> BusinessQAEvaluation:
    plan = _business_plan_for_project(project_id, store, user)
    return evaluate_business_qa(
        project_id=project_id,
        plan=plan,
        competitors=store.list_competitors(project_id=project_id),
        evidence=store.list_evidence(project_id=project_id),
        claims=store.list_claims(project_id=project_id),
    )


@router.get(
    "/enterprise/projects/{project_id}/readiness-score",
    response_model=ProjectReadinessScore,
)
def get_project_readiness_score(
    project_id: str,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
) -> ProjectReadinessScore:
    plan = _business_plan_for_project(project_id, store, user)
    competitors = store.list_competitors(project_id=project_id)
    evidence = store.list_evidence(project_id=project_id)
    claims = store.list_claims(project_id=project_id)
    qa_evaluation = evaluate_business_qa(
        project_id=project_id,
        plan=plan,
        competitors=competitors,
        evidence=evidence,
        claims=claims,
    )
    return score_project_readiness(
        project_id=project_id,
        plan=plan,
        qa_evaluation=qa_evaluation,
        competitors=competitors,
        evidence=evidence,
        claims=claims,
    )


@router.get(
    "/enterprise/projects/{project_id}/competitor-scores",
    response_model=CompetitorScoreReport,
)
def get_project_competitor_scores(
    project_id: str,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
) -> CompetitorScoreReport:
    plan = _business_plan_for_project(project_id, store, user)
    return score_competitors(
        project_id=project_id,
        plan=plan,
        competitors=store.list_competitors(project_id=project_id),
        evidence=store.list_evidence(project_id=project_id),
        claims=store.list_claims(project_id=project_id),
    )


@router.get("/enterprise/projects/{project_id}/evidence-gaps", response_model=EvidenceGapReport)
def get_project_evidence_gaps(
    project_id: str,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
) -> EvidenceGapReport:
    plan = _business_plan_for_project(project_id, store, user)
    competitors = store.list_competitors(project_id=project_id)
    evidence = store.list_evidence(project_id=project_id)
    claims = store.list_claims(project_id=project_id)
    qa_evaluation = evaluate_business_qa(
        project_id=project_id,
        plan=plan,
        competitors=competitors,
        evidence=evidence,
        claims=claims,
    )
    return analyze_evidence_gaps(
        project_id=project_id,
        plan=plan,
        qa_evaluation=qa_evaluation,
        competitors=competitors,
        evidence=evidence,
        claims=claims,
    )


@router.get("/enterprise/projects/{project_id}/red-team", response_model=RedTeamReport)
def get_project_red_team(
    project_id: str,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
) -> RedTeamReport:
    plan = _business_plan_for_project(project_id, store, user)
    competitors = store.list_competitors(project_id=project_id)
    evidence = store.list_evidence(project_id=project_id)
    claims = store.list_claims(project_id=project_id)
    qa_evaluation = evaluate_business_qa(
        project_id=project_id,
        plan=plan,
        competitors=competitors,
        evidence=evidence,
        claims=claims,
    )
    return analyze_red_team(
        project_id=project_id,
        plan=plan,
        qa_evaluation=qa_evaluation,
        competitors=competitors,
        evidence=evidence,
        claims=claims,
        report_versions=store.list_report_versions(project_id=project_id),
    )


def _business_plan_for_project(
    project_id: str,
    store: EnterpriseStore,
    user: EnterpriseUserContext,
) -> BusinessIntelPlan:
    project = _project_or_404(project_id, store, user, "project:read")
    competitors = store.list_competitors(project_id=project_id)
    dimensions = sorted({item.dimension for item in store.list_evidence(project_id=project_id)})
    if not dimensions:
        dimensions = ["pricing", "feature", "persona"]
    return build_business_intel_plan(
        topic=project.topic,
        competitors=[item.name for item in competitors],
        dimensions=dimensions,
        requested_layer=project.competitor_layer if project.competitor_layer != "unknown" else None,
        requested_scenario_id=project.scenario_id,
    )


@router.get("/enterprise/competitors", response_model=list[CompetitorRecord])
def list_competitors(
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
    workspace_id: str | None = None,
    project_id: str | None = None,
) -> list[CompetitorRecord]:
    if project_id is not None:
        _project_or_404(project_id, store, user, "competitor:read")
    else:
        workspace_id = _scoped_workspace_id(user, workspace_id, "competitor:read")
    return store.list_competitors(workspace_id=workspace_id, project_id=project_id)


@router.get("/enterprise/projects/{project_id}/evidence", response_model=list[EvidenceRecord])
def list_project_evidence(
    project_id: str,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
) -> list[EvidenceRecord]:
    _project_or_404(project_id, store, user, "evidence:read")
    return store.list_evidence(project_id=project_id)


@router.post("/enterprise/evidence", response_model=EvidenceRecord)
def upsert_evidence(
    evidence: EvidenceRecord,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
) -> EvidenceRecord:
    _require_workspace_access(user, evidence.workspace_id, "evidence:write")
    project = store.get_project(evidence.project_id)
    if project is not None and project.workspace_id != evidence.workspace_id:
        raise HTTPException(status_code=400, detail="Evidence workspace does not match project")
    return store.upsert_evidence(evidence)


@router.get("/enterprise/evidence/search", response_model=list[EvidenceSearchHit])
def search_evidence(
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
    workspace_id: str,
    query: str,
    project_id: str | None = None,
    limit: int = 10,
) -> list[EvidenceSearchHit]:
    _require_workspace_access(user, workspace_id, "evidence:read")
    if project_id is not None:
        _project_or_404(project_id, store, user, "evidence:read")
    return store.search_evidence(
        workspace_id=workspace_id,
        query=query,
        project_id=project_id,
        limit=limit,
    )


@router.post("/enterprise/evidence/reindex", response_model=EvidenceReindexResult)
def reindex_evidence_embeddings(
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
    workspace_id: str | None = None,
    project_id: str | None = None,
) -> EvidenceReindexResult:
    workspace_id = _scoped_workspace_id(user, workspace_id, "evidence:write")
    if project_id is not None:
        _project_or_404(project_id, store, user, "evidence:write")
    return store.reindex_evidence_embeddings(workspace_id=workspace_id, project_id=project_id)


@router.get("/enterprise/source-registry", response_model=list[SourceRegistryRecord])
def list_source_registry(
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
    workspace_id: str | None = None,
) -> list[SourceRegistryRecord]:
    return store.list_source_registry(
        workspace_id=_scoped_workspace_id(user, workspace_id, "source:read")
    )


@router.post("/enterprise/source-registry", response_model=SourceRegistryRecord)
def upsert_source_registry(
    record: SourceRegistryRecord,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
) -> SourceRegistryRecord:
    _require_workspace_access(user, record.workspace_id, "source:write")
    return store.upsert_source_registry(record)


@router.patch(
    "/enterprise/evidence/{evidence_id}/quality",
    response_model=EvidenceQualityUpdateResult,
)
def update_evidence_quality(
    evidence_id: str,
    request: EvidenceQualityUpdateRequest,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
) -> EvidenceQualityUpdateResult:
    existing = _evidence_or_404(evidence_id, store)
    _require_workspace_access(user, existing.workspace_id, "evidence:review")
    evidence = store.update_evidence_quality(
        evidence_id,
        request.quality_label,
        actor_id=user.user_id,
        note=request.note,
    )
    if evidence is None:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return EvidenceQualityUpdateResult(evidence=evidence)


@router.get("/enterprise/projects/{project_id}/claims", response_model=list[ClaimRecord])
def list_project_claims(
    project_id: str,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
) -> list[ClaimRecord]:
    _project_or_404(project_id, store, user, "project:read")
    return store.list_claims(project_id=project_id)


@router.get(
    "/enterprise/projects/{project_id}/report-versions",
    response_model=list[ReportVersionRecord],
)
def list_project_report_versions(
    project_id: str,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
) -> list[ReportVersionRecord]:
    _project_or_404(project_id, store, user, "report:read")
    return store.list_report_versions(project_id=project_id)


@router.post("/enterprise/report-versions", response_model=ReportVersionRecord)
def upsert_report_version(
    version: ReportVersionRecord,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
) -> ReportVersionRecord:
    _require_workspace_access(user, version.workspace_id, "report:write")
    if version.status in {"approved", "published"}:
        _enforce_report_release_gate(version, store, user)
    return store.upsert_report_version(version)


@router.get("/enterprise/report-versions/{version_id}", response_model=ReportVersionRecord)
def get_report_version(
    version_id: str,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
) -> ReportVersionRecord:
    version = store.get_report_version(version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Report version not found")
    _require_workspace_access(user, version.workspace_id, "report:read")
    return version


@router.get("/enterprise/report-versions/{version_id}/diff", response_model=ReportVersionDiff)
def get_report_version_diff(
    version_id: str,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
    base_version_id: str | None = None,
) -> ReportVersionDiff:
    target_version = store.get_report_version(version_id)
    if target_version is None:
        raise HTTPException(status_code=404, detail="Report version not found")
    _require_workspace_access(user, target_version.workspace_id, "report:read")
    if base_version_id:
        base_version = store.get_report_version(base_version_id)
        if base_version is None:
            raise HTTPException(status_code=404, detail="Base report version not found")
        _require_workspace_access(user, base_version.workspace_id, "report:read")
    else:
        base_version = store.get_previous_report_version(target_version)
    return build_report_version_diff(target_version, base_version=base_version)


@router.get(
    "/enterprise/report-versions/{version_id}/release-gate",
    response_model=ReportReleaseGate,
)
def get_report_release_gate(
    version_id: str,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
) -> ReportReleaseGate:
    version = _report_version_or_404(version_id, store, user, "report:read")
    return _report_release_gate_for_version(version, store, user, "report:read")


@router.post(
    "/enterprise/report-versions/{version_id}/publish",
    response_model=ReportVersionRecord,
)
def publish_report_version(
    version_id: str,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
) -> ReportVersionRecord:
    version = _report_version_or_404(version_id, store, user, "report:write")
    _enforce_report_release_gate(version, store, user)
    updated = version.model_copy(update={"status": "published", "published_at": datetime.utcnow()})
    return store.upsert_report_version(updated)


@router.get("/enterprise/runs/{run_id}/projection", response_model=EnterpriseRunProjection)
def get_run_projection(
    run_id: str,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
) -> EnterpriseRunProjection:
    projection = store.get_run_projection(run_id)
    if projection is None:
        raise HTTPException(status_code=404, detail="Enterprise projection not found")
    _require_workspace_access(user, projection.workspace_id, "project:read")
    return projection


@router.get("/enterprise/audit-logs", response_model=list[AuditLogRecord])
def list_audit_logs(
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
    workspace_id: str | None = None,
) -> list[AuditLogRecord]:
    scoped_workspace_id = _scoped_workspace_id(user, workspace_id, "audit:read")
    return store.list_audit_logs(workspace_id=scoped_workspace_id)


def _project_or_404(
    project_id: str,
    store: EnterpriseStore,
    user: EnterpriseUserContext,
    action: str,
) -> ProjectRecord:
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    _require_workspace_access(user, project.workspace_id, action)
    return project


def _evidence_or_404(evidence_id: str, store: EnterpriseStore) -> EvidenceRecord:
    for evidence in store.list_evidence():
        if evidence.id == evidence_id:
            return evidence
    raise HTTPException(status_code=404, detail="Evidence not found")


def _report_version_or_404(
    version_id: str,
    store: EnterpriseStore,
    user: EnterpriseUserContext,
    action: str,
) -> ReportVersionRecord:
    version = store.get_report_version(version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Report version not found")
    _require_workspace_access(user, version.workspace_id, action)
    return version


def _report_release_gate_for_version(
    version: ReportVersionRecord,
    store: EnterpriseStore,
    user: EnterpriseUserContext,
    action: str,
) -> ReportReleaseGate:
    project = _project_or_404(version.project_id, store, user, action)
    if project.workspace_id != version.workspace_id:
        raise HTTPException(status_code=400, detail="Report workspace does not match project")
    return evaluate_report_release_gate(
        project=project,
        report_version=version,
        competitors=store.list_competitors(project_id=project.id),
        evidence=store.list_evidence(project_id=project.id),
        claims=store.list_claims(project_id=project.id),
    )


def _enforce_report_release_gate(
    version: ReportVersionRecord,
    store: EnterpriseStore,
    user: EnterpriseUserContext,
) -> None:
    gate = _report_release_gate_for_version(version, store, user, "report:write")
    if gate.allowed:
        return
    raise HTTPException(status_code=409, detail=jsonable_encoder(gate))


def _scoped_workspace_id(
    user: EnterpriseUserContext,
    workspace_id: str | None,
    action: str,
) -> str | None:
    if workspace_id is not None:
        _require_workspace_access(user, workspace_id, action)
        return workspace_id
    if user.workspace_id is not None:
        _require_workspace_access(user, user.workspace_id, action)
        return user.workspace_id
    return None


def _require_workspace_access(
    user: EnterpriseUserContext,
    workspace_id: str,
    action: str,
) -> None:
    if not can_access_workspace(user, workspace_id, action):
        raise HTTPException(status_code=403, detail="Insufficient workspace permission")
