import hashlib
from collections.abc import Iterable
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder

from app.deps import (
    get_app_settings,
    get_artifact_storage,
    get_enterprise_store,
    get_enterprise_user_context,
)
from packages.agents import AgentExecutionRequest
from packages.artifacts import ArtifactStorageError, LocalArtifactStorage
from packages.auth import (
    EnterpriseUserContext,
    PolicyDecision,
    PolicyEvaluationRequest,
    can_access_workspace,
    evaluate_access_policy,
    list_policy_actions,
)
from packages.business_intel import (
    build_business_intel_plan,
    build_evidence_gap_agent,
    build_red_team_agent,
    evaluate_business_qa,
    evaluate_report_release_gate,
    list_business_qa_rules,
    list_scenario_packs,
    score_competitors,
    score_project_readiness,
    validate_project_claims,
)
from packages.config import Settings
from packages.enterprise import EnterpriseStore, build_report_version_diff
from packages.governance import ModelPolicyReport, build_model_policy_report
from packages.rag import (
    decorate_evidence_gap_report_with_retrieval,
    fill_evidence_gaps,
    fill_evidence_gaps_online,
)
from packages.search import PerplexitySearchClient
from packages.schema.enterprise import (
    ArtifactCreateRequest,
    ArtifactCreateResult,
    ArtifactRecord,
    AuditLogRecord,
    BusinessIntelPlan,
    BusinessQAEvaluation,
    BusinessQARule,
    ClaimRecord,
    ClaimValidationReport,
    CompetitorRecord,
    CompetitorScoreReport,
    EnterpriseRunProjection,
    EvidenceGapFillResult,
    EvidenceGapReport,
    EvidenceQualityUpdateRequest,
    EvidenceQualityUpdateResult,
    EvidenceRecord,
    EvidenceReindexResult,
    EvidenceSearchHit,
    NotificationRecord,
    ProjectReadinessScore,
    ProjectRecord,
    QualityAgentMatrix,
    QualityAgentMatrixEntry,
    QualityAgentStatus,
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
from packages.tools import (
    FetchPageResult,
    WebSearchRequest,
    fetch_page,
    robots_check,
    web_search,
)

router = APIRouter()
EnterpriseStoreDep = Annotated[EnterpriseStore, Depends(get_enterprise_store)]
EnterpriseUserDep = Annotated[EnterpriseUserContext, Depends(get_enterprise_user_context)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
ArtifactStorageDep = Annotated[LocalArtifactStorage, Depends(get_artifact_storage)]


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


@router.get("/enterprise/policy/actions", response_model=dict[str, str])
def get_policy_actions() -> dict[str, str]:
    return list_policy_actions()


@router.post("/enterprise/policy/evaluate", response_model=PolicyDecision)
def evaluate_policy(
    request: PolicyEvaluationRequest,
    user: EnterpriseUserDep,
) -> PolicyDecision:
    return evaluate_access_policy(
        user,
        request.workspace_id,
        request.action,
        target_type=request.target_type,
        target_id=request.target_id,
    )


@router.get("/enterprise/model-policy", response_model=ModelPolicyReport)
def get_model_policy(settings: SettingsDep) -> ModelPolicyReport:
    return build_model_policy_report(settings)


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
    "/enterprise/projects/{project_id}/claim-validation",
    response_model=ClaimValidationReport,
)
def get_project_claim_validation(
    project_id: str,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
) -> ClaimValidationReport:
    _project_or_404(project_id, store, user, "project:read")
    return validate_project_claims(
        project_id=project_id,
        claims=store.list_claims(project_id=project_id),
        evidence=store.list_evidence(project_id=project_id),
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
async def get_project_evidence_gaps(
    project_id: str,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
    settings: SettingsDep,
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
    result = await build_evidence_gap_agent().execute(
        AgentExecutionRequest(
            run_id=f"enterprise:{project_id}:evidence_gap",
            agent_name="evidence_gap",
            context=_pydantic_ai_context(settings),
            payload={
                "project_id": project_id,
                "plan": plan.model_dump(mode="json"),
                "qa_evaluation": qa_evaluation.model_dump(mode="json"),
                "competitors": [item.model_dump(mode="json") for item in competitors],
                "evidence": [item.model_dump(mode="json") for item in evidence],
                "claims": [item.model_dump(mode="json") for item in claims],
            },
        )
    )
    if result.status != "ok":
        raise HTTPException(status_code=503, detail=result.error or "Evidence gap agent failed.")
    report = EvidenceGapReport.model_validate(result.payload)
    project = _project_or_404(project_id, store, user, "evidence:read")
    return decorate_evidence_gap_report_with_retrieval(
        report,
        store=store,
        workspace_id=project.workspace_id,
        project_id=project_id,
    )


@router.post(
    "/enterprise/projects/{project_id}/evidence-gaps/fill",
    response_model=EvidenceGapFillResult,
)
async def fill_project_evidence_gaps(
    project_id: str,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
    settings: SettingsDep,
) -> EvidenceGapFillResult:
    project = _project_or_404(project_id, store, user, "report:write")
    report = await get_project_evidence_gaps(project_id, store, user, settings)
    versions = store.list_report_versions(project_id=project_id)
    source_version = versions[0] if versions else None
    if settings.has_web_search_credentials:
        search_client = PerplexitySearchClient(settings)

        async def search_online(query: str, max_results: int):
            return await web_search(
                search_client,
                WebSearchRequest(query=query, max_results=max_results),
            )

        async def fetch_with_robots(url: str) -> FetchPageResult:
            robots = await robots_check(url)
            if not robots.allowed:
                return FetchPageResult(
                    url=url,
                    ok=False,
                    title="",
                    text="",
                    content_hash=hashlib.sha256(f"robots:{url}".encode()).hexdigest()[:16],
                    error=f"Blocked by robots.txt at {robots.robots_url}",
                )
            return await fetch_page(url)

        return await fill_evidence_gaps_online(
            report,
            store=store,
            workspace_id=project.workspace_id,
            project_id=project_id,
            source_report_version=source_version,
            search=search_online,
            fetch=fetch_with_robots,
        )
    return fill_evidence_gaps(
        report,
        store=store,
        workspace_id=project.workspace_id,
        project_id=project_id,
        source_report_version=source_version,
    )


@router.get("/enterprise/projects/{project_id}/red-team", response_model=RedTeamReport)
async def get_project_red_team(
    project_id: str,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
    settings: SettingsDep,
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
    report_versions = store.list_report_versions(project_id=project_id)
    result = await build_red_team_agent().execute(
        AgentExecutionRequest(
            run_id=f"enterprise:{project_id}:red_team",
            agent_name="red_team",
            context=_pydantic_ai_context(settings),
            payload={
                "project_id": project_id,
                "plan": plan.model_dump(mode="json"),
                "qa_evaluation": qa_evaluation.model_dump(mode="json"),
                "competitors": [item.model_dump(mode="json") for item in competitors],
                "evidence": [item.model_dump(mode="json") for item in evidence],
                "claims": [item.model_dump(mode="json") for item in claims],
                "report_versions": [item.model_dump(mode="json") for item in report_versions],
            },
        )
    )
    if result.status != "ok":
        raise HTTPException(status_code=503, detail=result.error or "Red-team agent failed.")
    return RedTeamReport.model_validate(result.payload)


@router.get(
    "/enterprise/projects/{project_id}/quality-matrix",
    response_model=QualityAgentMatrix,
)
async def get_project_quality_matrix(
    project_id: str,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
    settings: SettingsDep,
) -> QualityAgentMatrix:
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
    claim_validation = validate_project_claims(
        project_id=project_id,
        claims=claims,
        evidence=evidence,
    )
    evidence_gaps = await get_project_evidence_gaps(project_id, store, user, settings)
    red_team = await get_project_red_team(project_id, store, user, settings)

    entries = [
        QualityAgentMatrixEntry(
            agent_name="BusinessQA",
            framework="deterministic-rules",
            status=_matrix_status(qa_evaluation.blocker_count, qa_evaluation.warn_count),
            score=max(0, 100 - qa_evaluation.blocker_count * 35 - qa_evaluation.warn_count * 10),
            blocker_count=qa_evaluation.blocker_count,
            warn_count=qa_evaluation.warn_count,
            finding_count=qa_evaluation.finding_count,
            summary=f"{qa_evaluation.passed_rules}/{qa_evaluation.total_rules} rules passed.",
            evidence_ids=_unique_ids(
                evidence_id
                for finding in qa_evaluation.findings
                for evidence_id in finding.evidence_ids
            ),
            claim_ids=_unique_ids(
                claim_id for finding in qa_evaluation.findings for claim_id in finding.claim_ids
            ),
        ),
        QualityAgentMatrixEntry(
            agent_name="ClaimValidator",
            framework="deterministic-evidence-crosscheck",
            status=_matrix_status(claim_validation.blocker_count, claim_validation.warn_count),
            score=max(
                0,
                100
                - claim_validation.blocked_count * 35
                - claim_validation.unsupported_count * 25
                - claim_validation.weak_count * 10,
            ),
            blocker_count=claim_validation.blocker_count,
            warn_count=claim_validation.warn_count,
            finding_count=claim_validation.issue_count,
            summary=(
                f"{claim_validation.supported_count}/{claim_validation.total_claims} "
                "claims strongly supported."
            ),
            evidence_ids=_unique_ids(
                evidence_id
                for result in claim_validation.results
                for evidence_id in result.usable_evidence_ids
            ),
            claim_ids=[item.claim_id for item in claim_validation.results],
        ),
        QualityAgentMatrixEntry(
            agent_name="EvidenceGap",
            framework=evidence_gaps.framework,
            status=_matrix_status(evidence_gaps.critical_count, evidence_gaps.high_count),
            score=max(
                0,
                100 - evidence_gaps.critical_count * 35 - evidence_gaps.high_count * 15,
            ),
            blocker_count=evidence_gaps.critical_count,
            warn_count=evidence_gaps.high_count + evidence_gaps.medium_count,
            finding_count=evidence_gaps.gap_count,
            summary=f"{evidence_gaps.gap_count} evidence gaps detected.",
            evidence_ids=_unique_ids(
                evidence_id for gap in evidence_gaps.gaps for evidence_id in gap.evidence_ids
            ),
            claim_ids=_unique_ids(
                claim_id for gap in evidence_gaps.gaps for claim_id in gap.claim_ids
            ),
        ),
        QualityAgentMatrixEntry(
            agent_name="RedTeam",
            framework=red_team.framework,
            status=_matrix_status(
                sum(1 for finding in red_team.findings if finding.severity == "critical"),
                red_team.high_severity_count,
            ),
            score=max(0, 100 - red_team.high_severity_count * 20),
            blocker_count=sum(1 for finding in red_team.findings if finding.severity == "critical"),
            warn_count=red_team.high_severity_count,
            finding_count=red_team.finding_count,
            summary=f"{red_team.finding_count} red-team findings detected.",
            evidence_ids=_unique_ids(
                evidence_id for finding in red_team.findings for evidence_id in finding.evidence_ids
            ),
            claim_ids=_unique_ids(
                claim_id for finding in red_team.findings for claim_id in finding.claim_ids
            ),
        ),
    ]
    blocker_count = sum(item.blocker_count for item in entries)
    warn_count = sum(item.warn_count for item in entries)
    overall_score = round(sum(item.score for item in entries) / max(len(entries), 1))
    return QualityAgentMatrix(
        project_id=project_id,
        status=_matrix_status(blocker_count, warn_count),
        overall_score=overall_score,
        entries=entries,
    )


def _pydantic_ai_context(settings: Settings) -> dict[str, str]:
    if settings.pydantic_ai_model_backed_enabled and settings.pydantic_ai_model_name:
        return {
            "pydantic_ai_execution_mode": "model_backed",
            "pydantic_ai_model": settings.pydantic_ai_model_name,
        }
    return {}


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


@router.get("/enterprise/artifacts", response_model=list[ArtifactRecord])
def list_artifacts(
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
    workspace_id: str | None = None,
    project_id: str | None = None,
    evidence_id: str | None = None,
) -> list[ArtifactRecord]:
    scoped_workspace_id = _scoped_workspace_id(user, workspace_id, "artifact:read")
    if project_id is not None:
        project = _project_or_404(project_id, store, user, "artifact:read")
        scoped_workspace_id = project.workspace_id
    if evidence_id is not None:
        evidence = _evidence_or_404(evidence_id, store)
        _require_workspace_access(user, evidence.workspace_id, "artifact:read")
        scoped_workspace_id = evidence.workspace_id
        if project_id is not None and evidence.project_id != project_id:
            raise HTTPException(status_code=400, detail="Evidence does not belong to project")
    return store.list_artifacts(
        workspace_id=scoped_workspace_id,
        project_id=project_id,
        evidence_id=evidence_id,
    )


@router.post("/enterprise/artifacts", response_model=ArtifactCreateResult)
def create_artifact(
    request: ArtifactCreateRequest,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
    artifact_storage: ArtifactStorageDep,
) -> ArtifactCreateResult:
    _require_workspace_access(user, request.workspace_id, "artifact:write")
    project = _project_or_404(request.project_id, store, user, "artifact:write")
    if project.workspace_id != request.workspace_id:
        raise HTTPException(status_code=400, detail="Artifact workspace does not match project")
    if request.evidence_id is not None:
        evidence = _evidence_or_404(request.evidence_id, store)
        if (
            evidence.workspace_id != request.workspace_id
            or evidence.project_id != request.project_id
        ):
            raise HTTPException(status_code=400, detail="Artifact evidence scope mismatch")
    try:
        artifact = artifact_storage.store(request, actor_id=user.user_id)
    except ArtifactStorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ArtifactCreateResult(artifact=store.upsert_artifact(artifact))


@router.get("/enterprise/artifacts/{artifact_id}", response_model=ArtifactRecord)
def get_artifact(
    artifact_id: str,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
) -> ArtifactRecord:
    artifact = store.get_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    _require_workspace_access(user, artifact.workspace_id, "artifact:read")
    return artifact


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


def _matrix_status(blocker_count: int, warn_count: int) -> QualityAgentStatus:
    if blocker_count > 0:
        return "blocker"
    if warn_count > 0:
        return "warn"
    return "pass"


def _unique_ids(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
