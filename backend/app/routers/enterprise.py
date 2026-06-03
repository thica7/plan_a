import csv
import hashlib
import html
import io
import re
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
    get_preference_memory,
)
from packages.agents import AgentExecutionRequest, AgentExecutionResult
from packages.artifacts import ArtifactStorage, ArtifactStorageError
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
    business_findings_to_redo_scopes,
    claim_validation_issues_to_redo_scopes,
    evaluate_business_qa,
    evaluate_report_release_gate,
    evidence_gaps_to_redo_scopes,
    list_business_qa_rules,
    list_scenario_packs,
    red_team_findings_to_redo_scopes,
    score_competitors,
    score_project_readiness,
    validate_project_claims,
)
from packages.compliance import (
    DataRetentionReport,
    build_data_retention_report,
    compliance_policy_from_settings,
)
from packages.config import Settings
from packages.enterprise import (
    EnterpriseStore,
    build_project_knowledge_graph_read_model,
    build_report_version_diff,
    capture_source_snapshot,
)
from packages.governance import (
    ModelPolicyReport,
    build_model_policy_report,
    build_model_route_decision,
    build_tool_registry_report,
)
from packages.memory import PreferenceMemoryStore
from packages.rag import (
    decorate_evidence_gap_report_with_retrieval,
    fill_evidence_gaps,
    fill_evidence_gaps_online,
    ingest_evidence_seed_corpus,
)
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
    EvidenceSeedIngestRequest,
    EvidenceSeedIngestResult,
    KnowledgeGraphReadModel,
    ManualReportRevisionRequest,
    MemoryCandidate,
    MemoryFeedbackIngestResult,
    MemoryRecallContext,
    MemoryStats,
    ModelRouteDecision,
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
    SchemaEvolutionReviewRecord,
    SchemaEvolutionReviewRequest,
    SchemaEvolutionReviewResult,
    SourceRegistryRecord,
    SourceSnapshotCreateRequest,
    SourceSnapshotResult,
    ToolRegistryReport,
    UserFeedbackCreateRequest,
    UserFeedbackRecord,
    WorkspaceMemberRecord,
    WorkspaceQuotaDecision,
    WorkspaceQuotaUpdateRequest,
    WorkspaceRecord,
    WorkspaceUsageSummary,
)
from packages.search import PerplexitySearchClient
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
ArtifactStorageDep = Annotated[ArtifactStorage, Depends(get_artifact_storage)]
PreferenceMemoryDep = Annotated[PreferenceMemoryStore, Depends(get_preference_memory)]


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


@router.get(
    "/enterprise/workspaces/{workspace_id}/retention",
    response_model=DataRetentionReport,
)
def get_workspace_retention_report(
    workspace_id: str,
    settings: SettingsDep,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
) -> DataRetentionReport:
    _require_workspace_access(user, workspace_id, "audit:read")
    return build_data_retention_report(
        store=store,
        workspace_id=workspace_id,
        settings=settings,
    )


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


@router.get("/enterprise/model-route", response_model=ModelRouteDecision)
def get_model_route_decision(
    settings: SettingsDep,
    user: EnterpriseUserDep,
) -> ModelRouteDecision:
    if user.workspace_id is not None:
        _require_workspace_access(user, user.workspace_id, "model:read")
    return build_model_route_decision(settings)


@router.get("/enterprise/tool-registry", response_model=ToolRegistryReport)
def get_tool_registry(
    settings: SettingsDep,
    user: EnterpriseUserDep,
) -> ToolRegistryReport:
    if user.workspace_id is not None:
        _require_workspace_access(user, user.workspace_id, "tool:read")
    return build_tool_registry_report(settings)


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


@router.get(
    "/enterprise/projects/{project_id}/kg-read-model",
    response_model=KnowledgeGraphReadModel,
)
def get_project_knowledge_graph_read_model(
    project_id: str,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
) -> KnowledgeGraphReadModel:
    _project_or_404(project_id, store, user, "kg:read")
    return build_project_knowledge_graph_read_model(store=store, project_id=project_id)


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


@router.post(
    "/enterprise/projects/{project_id}/memory/feedback",
    response_model=MemoryFeedbackIngestResult,
)
def ingest_project_memory_feedback(
    project_id: str,
    request: UserFeedbackCreateRequest,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
    settings: SettingsDep,
    memory: PreferenceMemoryDep,
) -> MemoryFeedbackIngestResult:
    project = _project_or_404(project_id, store, user, "memory:write")
    record = memory.add_feedback(
        UserFeedbackRecord(
            id="",
            workspace_id=project.workspace_id,
            project_id=project_id,
            user_id=user.user_id,
            feedback_type=request.feedback_type,
            target_type=request.target_type,
            target_id=request.target_id,
            run_id=request.run_id,
            report_version_id=request.report_version_id,
            message=request.message,
            tags=request.tags,
            metadata=request.metadata,
        ),
        policy=compliance_policy_from_settings(settings),
    )
    candidates = [
        memory.upsert_candidate(candidate)
        for candidate in memory.extract_candidates(
            record,
            auto_confirm=request.auto_confirm,
        )
    ]
    store.record_memory_feedback_audit(record, candidates, actor_id=user.user_id)
    recall = memory.recall(
        workspace_id=project.workspace_id,
        project_id=project_id,
        query=request.message,
        include_unconfirmed=True,
    )
    return MemoryFeedbackIngestResult(
        feedback=record,
        candidates=candidates,
        recall=recall,
    )


@router.get(
    "/enterprise/projects/{project_id}/memory/feedback",
    response_model=list[UserFeedbackRecord],
)
def list_project_memory_feedback(
    project_id: str,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
    memory: PreferenceMemoryDep,
    limit: int = 100,
) -> list[UserFeedbackRecord]:
    project = _project_or_404(project_id, store, user, "memory:read")
    return memory.list_feedback(
        workspace_id=project.workspace_id,
        project_id=project_id,
        limit=limit,
    )


@router.get(
    "/enterprise/projects/{project_id}/memory/recall",
    response_model=MemoryRecallContext,
)
def recall_project_memory(
    project_id: str,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
    memory: PreferenceMemoryDep,
    query: str = "",
    limit: int = 6,
    include_unconfirmed: bool = False,
) -> MemoryRecallContext:
    project = _project_or_404(project_id, store, user, "memory:read")
    return memory.recall(
        workspace_id=project.workspace_id,
        project_id=project_id,
        query=query,
        limit=limit,
        include_unconfirmed=include_unconfirmed,
    )


@router.patch(
    "/enterprise/projects/{project_id}/memory/candidates/{candidate_id}",
    response_model=MemoryCandidate,
)
def update_project_memory_candidate(
    project_id: str,
    candidate_id: str,
    status: str,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
    memory: PreferenceMemoryDep,
) -> MemoryCandidate:
    project = _project_or_404(project_id, store, user, "memory:review")
    candidate = memory.get_candidate(candidate_id)
    if candidate is None or candidate.project_id != project_id:
        raise HTTPException(status_code=404, detail="Memory candidate not found")
    if candidate.workspace_id != project.workspace_id:
        raise HTTPException(status_code=403, detail="Insufficient workspace permission")
    if status not in {"candidate", "confirmed", "rejected", "archived"}:
        raise HTTPException(status_code=400, detail="Invalid memory candidate status")
    updated = memory.update_candidate_status(candidate_id, status)
    if updated is None:
        raise HTTPException(status_code=404, detail="Memory candidate not found")
    return updated


@router.get(
    "/enterprise/projects/{project_id}/memory/stats",
    response_model=MemoryStats,
)
def get_project_memory_stats(
    project_id: str,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
    memory: PreferenceMemoryDep,
) -> MemoryStats:
    project = _project_or_404(project_id, store, user, "memory:read")
    return memory.stats(workspace_id=project.workspace_id, project_id=project_id)


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
    report = _with_pydantic_ai_execution_metadata(
        EvidenceGapReport.model_validate(result.payload),
        result,
    )
    project = _project_or_404(project_id, store, user, "evidence:read")
    return decorate_evidence_gap_report_with_retrieval(
        report,
        store=store,
        workspace_id=project.workspace_id,
        project_id=project_id,
    )


@router.post(
    "/enterprise/projects/{project_id}/schema-suggestions/{suggestion_id}/review",
    response_model=SchemaEvolutionReviewResult,
)
async def review_project_schema_suggestion(
    project_id: str,
    suggestion_id: str,
    request: SchemaEvolutionReviewRequest,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
    settings: SettingsDep,
) -> SchemaEvolutionReviewResult:
    project = _project_or_404(project_id, store, user, "schema:review")
    suggestion = request.suggestion
    if suggestion is not None and suggestion.id != suggestion_id:
        raise HTTPException(status_code=400, detail="Suggestion id mismatch")
    if suggestion is None:
        report = await get_project_evidence_gaps(project_id, store, user, settings)
        suggestion = next(
            (item for item in report.schema_suggestions if item.id == suggestion_id),
            None,
        )
    if suggestion is None:
        raise HTTPException(status_code=404, detail="Schema suggestion not found")

    review = SchemaEvolutionReviewRecord(
        suggestion_id=suggestion.id,
        decision=request.decision,
        dimension=suggestion.dimension,
        normalized_dimension=suggestion.normalized_dimension,
        reason=suggestion.reason,
        source_gap_ids=suggestion.source_gap_ids,
        proposed_skill=suggestion.proposed_skill,
        reviewed_by=user.user_id,
        note=request.note,
    )
    updated_project = store.upsert_project(
        _project_with_schema_review(project, review)
    )
    store.audit_schema_evolution_review(updated_project, review, actor_id=user.user_id)
    return SchemaEvolutionReviewResult(
        project_id=project_id,
        workspace_id=project.workspace_id,
        review=review,
        project=updated_project,
        accepted_schema_dimensions=_accepted_schema_dimensions(updated_project.metadata),
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

        result = await fill_evidence_gaps_online(
            report,
            store=store,
            workspace_id=project.workspace_id,
            project_id=project_id,
            source_report_version=source_version,
            search=search_online,
            fetch=fetch_with_robots,
        )
        return _with_gap_fill_release_gate_delta(result, project=project, store=store)
    result = fill_evidence_gaps(
        report,
        store=store,
        workspace_id=project.workspace_id,
        project_id=project_id,
        source_report_version=source_version,
    )
    return _with_gap_fill_release_gate_delta(result, project=project, store=store)


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
    return _with_pydantic_ai_execution_metadata(
        RedTeamReport.model_validate(result.payload),
        result,
    )


@router.get(
    "/enterprise/projects/{project_id}/quality-matrix",
    response_model=QualityAgentMatrix,
)
async def get_project_quality_matrix(
    project_id: str,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
    settings: SettingsDep,
    memory: PreferenceMemoryDep,
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
    project = _project_or_404(project_id, store, user, "memory:read")
    report_versions = store.list_report_versions(project_id=project_id)
    latest_release_gate = (
        evaluate_report_release_gate(
            project=project,
            report_version=report_versions[0],
            competitors=competitors,
            evidence=evidence,
            claims=claims,
            source_registry=store.list_source_registry(workspace_id=project.workspace_id),
        )
        if report_versions
        else None
    )
    latest_report_version = report_versions[0] if report_versions else None
    memory_stats = memory.stats(workspace_id=project.workspace_id, project_id=project_id)
    memory_status = (
        "warn"
        if memory_stats.candidate_count > 0 and memory_stats.confirmed_candidate_count == 0
        else "pass"
    )
    evidence_gap_runtime_warn_count = _pydantic_ai_runtime_warn_count(evidence_gaps)
    red_team_runtime_warn_count = _pydantic_ai_runtime_warn_count(red_team)

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
            suggested_redos=business_findings_to_redo_scopes(
                qa_evaluation.findings
            )[:3],
        ),
        QualityAgentMatrixEntry(
            agent_name="ClaimValidator",
            framework="deterministic-self-consistency",
            status=_matrix_status(claim_validation.blocker_count, claim_validation.warn_count),
            score=max(0, claim_validation.self_consistency_score),
            blocker_count=claim_validation.blocker_count,
            warn_count=claim_validation.warn_count,
            finding_count=claim_validation.issue_count,
            summary=(
                f"{claim_validation.supported_count}/{claim_validation.total_claims} "
                "claims strongly supported; "
                f"self-consistency {claim_validation.self_consistency_score}/100."
            ),
            evidence_ids=_unique_ids(
                evidence_id
                for result in claim_validation.results
                for evidence_id in result.usable_evidence_ids
            ),
            claim_ids=[item.claim_id for item in claim_validation.results],
            metadata={
                "sample_checkers": [
                    "text_support",
                    "evidence_quality",
                    "triangulation",
                ],
                "validation_sample_count": sum(
                    len(result.validation_samples) for result in claim_validation.results
                ),
                "low_consistency_claim_ids": [
                    result.claim_id
                    for result in claim_validation.results
                    if result.self_consistency_score < 55
                ],
                "sample_votes": [
                    {
                        "claim_id": result.claim_id,
                        "checker": sample.checker,
                        "vote": sample.vote,
                        "score": sample.score,
                        "threshold": sample.threshold,
                    }
                    for result in claim_validation.results
                    for sample in result.validation_samples
                ][:12],
            },
            suggested_redos=claim_validation_issues_to_redo_scopes(
                claim_validation.issues
            )[:3],
        ),
        QualityAgentMatrixEntry(
            agent_name="EvidenceGap",
            framework=evidence_gaps.framework,
            status=_matrix_status(
                evidence_gaps.critical_count,
                evidence_gaps.high_count + evidence_gap_runtime_warn_count,
            ),
            score=max(
                0,
                100
                - evidence_gaps.critical_count * 35
                - evidence_gaps.high_count * 15
                - _pydantic_ai_runtime_score_penalty(evidence_gaps),
            ),
            blocker_count=evidence_gaps.critical_count,
            warn_count=(
                evidence_gaps.high_count
                + evidence_gaps.medium_count
                + evidence_gap_runtime_warn_count
            ),
            finding_count=evidence_gaps.gap_count,
            summary=(
                f"{evidence_gaps.gap_count} evidence gaps detected."
                f"{_pydantic_ai_runtime_summary_suffix(evidence_gaps)}"
            ),
            evidence_ids=_unique_ids(
                evidence_id for gap in evidence_gaps.gaps for evidence_id in gap.evidence_ids
            ),
            claim_ids=_unique_ids(
                claim_id for gap in evidence_gaps.gaps for claim_id in gap.claim_ids
            ),
            suggested_redos=evidence_gaps_to_redo_scopes(evidence_gaps.gaps)[:3],
            metadata=_quality_agent_pydantic_ai_metadata(evidence_gaps),
        ),
        QualityAgentMatrixEntry(
            agent_name="RedTeam",
            framework=red_team.framework,
            status=_matrix_status(
                sum(1 for finding in red_team.findings if finding.severity == "critical"),
                red_team.high_severity_count + red_team_runtime_warn_count,
            ),
            score=max(
                0,
                100
                - red_team.high_severity_count * 20
                - _pydantic_ai_runtime_score_penalty(red_team),
            ),
            blocker_count=sum(1 for finding in red_team.findings if finding.severity == "critical"),
            warn_count=red_team.high_severity_count + red_team_runtime_warn_count,
            finding_count=red_team.finding_count,
            summary=(
                f"{red_team.finding_count} red-team findings detected."
                f"{_pydantic_ai_runtime_summary_suffix(red_team)}"
            ),
            evidence_ids=_unique_ids(
                evidence_id for finding in red_team.findings for evidence_id in finding.evidence_ids
            ),
            claim_ids=_unique_ids(
                claim_id for finding in red_team.findings for claim_id in finding.claim_ids
            ),
            suggested_redos=red_team_findings_to_redo_scopes(red_team.findings)[:3],
            metadata=_quality_agent_pydantic_ai_metadata(red_team),
        ),
        _benchmark_quality_matrix_entry(
            latest_report_version,
            latest_release_gate=latest_release_gate,
            evidence_count=len(evidence),
            claim_count=len(claims),
        ),
        (
            QualityAgentMatrixEntry(
                agent_name="ReleaseGate",
                framework="enterprise-release-gate",
                status=_matrix_status(
                    latest_release_gate.blocker_count,
                    latest_release_gate.warn_count,
                ),
                score=max(
                    0,
                    latest_release_gate.readiness.score
                    - latest_release_gate.blocker_count * 20
                    - latest_release_gate.warn_count * 5,
                ),
                blocker_count=latest_release_gate.blocker_count,
                warn_count=latest_release_gate.warn_count,
                finding_count=latest_release_gate.issue_count,
                summary=(
                    f"Latest report {latest_release_gate.report_version_id} "
                    f"is {latest_release_gate.status}; "
                    f"readiness {latest_release_gate.readiness.score}/100."
                ),
                evidence_ids=_unique_ids(
                    evidence_id
                    for issue in latest_release_gate.issues
                    for evidence_id in issue.evidence_ids
                ),
                claim_ids=_unique_ids(
                    claim_id
                    for issue in latest_release_gate.issues
                    for claim_id in issue.claim_ids
                ),
                suggested_redos=business_findings_to_redo_scopes(
                    latest_release_gate.issues
                )[:3],
            )
            if latest_release_gate is not None
            else QualityAgentMatrixEntry(
                agent_name="ReleaseGate",
                framework="enterprise-release-gate",
                status="warn",
                score=50,
                warn_count=1,
                finding_count=1,
                summary="No ReportVersion exists yet; release readiness cannot be evaluated.",
            )
        ),
        QualityAgentMatrixEntry(
            agent_name="MemoryAgent",
            framework="deterministic-preference-memory",
            status=memory_status,
            score=(
                80
                if memory_stats.candidate_count == 0
                else min(100, 82 + memory_stats.confirmed_candidate_count * 6)
            ),
            blocker_count=0,
            warn_count=1 if memory_status == "warn" else 0,
            finding_count=memory_stats.candidate_count,
            summary=(
                f"{memory_stats.feedback_count} feedback records, "
                f"{memory_stats.confirmed_candidate_count}/"
                f"{memory_stats.candidate_count} confirmed memory candidates."
            ),
        ),
    ]
    entries = _with_quality_peer_review_metadata(entries)
    blocker_count = sum(item.blocker_count for item in entries)
    warn_count = sum(item.warn_count for item in entries)
    overall_score = round(sum(item.score for item in entries) / max(len(entries), 1))
    return QualityAgentMatrix(
        project_id=project_id,
        status=_matrix_status(blocker_count, warn_count),
        overall_score=overall_score,
        entries=entries,
    )


def _benchmark_quality_matrix_entry(
    report_version: ReportVersionRecord | None,
    *,
    latest_release_gate: ReportReleaseGate | None,
    evidence_count: int,
    claim_count: int,
) -> QualityAgentMatrixEntry:
    if report_version is None:
        return QualityAgentMatrixEntry(
            agent_name="BenchmarkAgent",
            framework="deterministic-report-benchmark",
            status="blocker",
            score=0,
            blocker_count=1,
            finding_count=1,
            summary="No ReportVersion exists yet; report benchmark cannot score quality.",
            metadata={"benchmark_reason": "missing_report_version"},
        )
    report_md = report_version.report_md
    citation_count = len(_report_source_tokens(report_md))
    report_length_score = min(100, round(len(report_md.strip()) / 12))
    evidence_score = min(100, evidence_count * 25)
    claim_score = min(100, claim_count * 35)
    citation_score = min(100, citation_count * 20)
    release_score = latest_release_gate.readiness.score if latest_release_gate is not None else 50
    score = round(
        report_length_score * 0.25
        + evidence_score * 0.2
        + claim_score * 0.2
        + citation_score * 0.15
        + release_score * 0.2
    )
    blockers: list[str] = []
    warnings: list[str] = []
    if latest_release_gate is not None and latest_release_gate.blocker_count > 0:
        blockers.append("release_gate_blocked")
    if evidence_count == 0:
        blockers.append("missing_evidence")
    if claim_count == 0:
        warnings.append("missing_claims")
    if citation_count == 0:
        warnings.append("missing_source_tokens")
    if len(report_md.strip()) < 700:
        warnings.append("thin_report_body")
    if latest_release_gate is not None and latest_release_gate.warn_count > 0:
        warnings.append("release_gate_warnings")
    blocker_count = len(blockers)
    warn_count = len(warnings)
    return QualityAgentMatrixEntry(
        agent_name="BenchmarkAgent",
        framework="deterministic-report-benchmark",
        status=_matrix_status(blocker_count, warn_count),
        score=max(0, score - blocker_count * 25 - warn_count * 5),
        blocker_count=blocker_count,
        warn_count=warn_count,
        finding_count=blocker_count + warn_count,
        summary=(
            f"Report benchmark scored {score}/100 across length, citations, evidence, "
            f"claims, and release readiness."
        ),
        evidence_ids=list(report_version.evidence_ids),
        claim_ids=list(report_version.claim_ids),
        metadata={
            "report_version_id": report_version.id,
            "report_length_chars": len(report_md.strip()),
            "source_token_count": citation_count,
            "evidence_count": evidence_count,
            "claim_count": claim_count,
            "release_readiness_score": release_score,
            "benchmark_blockers": blockers,
            "benchmark_warnings": warnings,
            "component_scores": {
                "report_length_score": report_length_score,
                "evidence_score": evidence_score,
                "claim_score": claim_score,
                "citation_score": citation_score,
                "release_score": release_score,
            },
        },
    )


def _report_source_tokens(report_md: str) -> list[str]:
    return re.findall(r"\[source:([A-Za-z0-9_.:#-]+)\]", report_md)


def _with_quality_peer_review_metadata(
    entries: list[QualityAgentMatrixEntry],
) -> list[QualityAgentMatrixEntry]:
    available_agents = {entry.agent_name for entry in entries}
    review_targets = {
        "BusinessQA": ["EvidenceGap", "BenchmarkAgent", "ReleaseGate"],
        "ClaimValidator": ["BusinessQA", "BenchmarkAgent", "ReleaseGate"],
        "EvidenceGap": ["BusinessQA", "BenchmarkAgent", "ReleaseGate"],
        "RedTeam": [
            "BusinessQA",
            "ClaimValidator",
            "EvidenceGap",
            "BenchmarkAgent",
            "ReleaseGate",
        ],
        "BenchmarkAgent": ["ClaimValidator", "EvidenceGap", "RedTeam", "ReleaseGate"],
        "ReleaseGate": ["BenchmarkAgent"],
        "MemoryAgent": ["BusinessQA", "RedTeam"],
    }
    reviewed_by: dict[str, list[str]] = {agent: [] for agent in available_agents}
    for reviewer, targets in review_targets.items():
        if reviewer not in available_agents:
            continue
        for target in targets:
            if target in available_agents:
                reviewed_by.setdefault(target, []).append(reviewer)
    return [
        entry.model_copy(
            update={
                "metadata": {
                    **entry.metadata,
                    "peer_review_mode": "deterministic_cross_agent_matrix",
                    "peer_reviewed_by": sorted(reviewed_by.get(entry.agent_name, [])),
                    "review_targets": sorted(
                        target
                        for target in review_targets.get(entry.agent_name, [])
                        if target in available_agents
                    ),
                }
            }
        )
        for entry in entries
    ]


def _pydantic_ai_context(settings: Settings) -> dict[str, str]:
    if settings.pydantic_ai_model_backed_enabled and settings.pydantic_ai_model_name:
        return {
            "pydantic_ai_execution_mode": "model_backed",
            "pydantic_ai_model": settings.pydantic_ai_model_name,
        }
    return {}


def _with_pydantic_ai_execution_metadata(
    report: EvidenceGapReport | RedTeamReport,
    result: AgentExecutionResult,
) -> EvidenceGapReport | RedTeamReport:
    metadata = result.metadata
    return report.model_copy(
        update={
            "pydantic_ai_available": bool(
                metadata.get("pydantic_ai_available", report.pydantic_ai_available)
            ),
            "pydantic_ai_execution_mode": str(
                metadata.get("execution_mode", report.pydantic_ai_execution_mode)
            ),
            "pydantic_ai_model_backed_requested": bool(
                metadata.get(
                    "pydantic_ai_model_backed_requested",
                    report.pydantic_ai_model_backed_requested,
                )
            ),
            "pydantic_ai_model_backed_fallback": bool(
                metadata.get(
                    "pydantic_ai_model_backed_fallback",
                    report.pydantic_ai_model_backed_fallback,
                )
            ),
            "pydantic_ai_fallback_reason": _optional_str(
                metadata.get("pydantic_ai_model_backed_error")
                or metadata.get("pydantic_ai_test_model_error")
                or report.pydantic_ai_fallback_reason
            )
            or "",
            "pydantic_ai_runtime_agent_created": bool(
                metadata.get(
                    "pydantic_ai_runtime_agent_created",
                    report.pydantic_ai_runtime_agent_created,
                )
            ),
            "pydantic_ai_runtime_result_type": _optional_str(
                metadata.get(
                    "pydantic_ai_runtime_result_type",
                    report.pydantic_ai_runtime_result_type,
                )
            ),
            "pydantic_ai_model_name": _optional_str(
                metadata.get("pydantic_ai_model_name", report.pydantic_ai_model_name)
            ),
            "pydantic_ai_runtime_prompt_hash": _optional_str(
                metadata.get(
                    "runtime_prompt_hash",
                    report.pydantic_ai_runtime_prompt_hash,
                )
            ),
            "pydantic_ai_input_schema_hash": _optional_str(
                metadata.get("input_schema_hash", report.pydantic_ai_input_schema_hash)
            ),
            "pydantic_ai_output_schema_hash": _optional_str(
                metadata.get("output_schema_hash", report.pydantic_ai_output_schema_hash)
            ),
            "pydantic_ai_runtime_prompt_chars": _optional_int(
                metadata.get(
                    "runtime_prompt_chars",
                    report.pydantic_ai_runtime_prompt_chars,
                ),
                default=report.pydantic_ai_runtime_prompt_chars,
            ),
            "typed_contract_enforced": bool(
                metadata.get("typed_contract_enforced", report.typed_contract_enforced)
            ),
        }
    )


def _quality_agent_pydantic_ai_metadata(
    report: EvidenceGapReport | RedTeamReport,
) -> dict[str, object]:
    return {
        "framework": report.framework,
        "pydantic_ai_available": report.pydantic_ai_available,
        "pydantic_ai_execution_mode": report.pydantic_ai_execution_mode,
        "pydantic_ai_model_backed_requested": report.pydantic_ai_model_backed_requested,
        "pydantic_ai_model_backed_fallback": report.pydantic_ai_model_backed_fallback,
        "pydantic_ai_fallback_reason": report.pydantic_ai_fallback_reason,
        "pydantic_ai_runtime_agent_created": report.pydantic_ai_runtime_agent_created,
        "pydantic_ai_runtime_result_type": report.pydantic_ai_runtime_result_type,
        "pydantic_ai_model_name": report.pydantic_ai_model_name,
        "pydantic_ai_runtime_prompt_hash": report.pydantic_ai_runtime_prompt_hash,
        "pydantic_ai_input_schema_hash": report.pydantic_ai_input_schema_hash,
        "pydantic_ai_output_schema_hash": report.pydantic_ai_output_schema_hash,
        "pydantic_ai_runtime_prompt_chars": report.pydantic_ai_runtime_prompt_chars,
        "typed_contract_enforced": report.typed_contract_enforced,
    }


def _pydantic_ai_runtime_warn_count(report: EvidenceGapReport | RedTeamReport) -> int:
    if not report.pydantic_ai_model_backed_requested:
        return 0
    if report.pydantic_ai_model_backed_fallback:
        return 1
    if not report.pydantic_ai_runtime_agent_created:
        return 1
    return 0


def _pydantic_ai_runtime_score_penalty(report: EvidenceGapReport | RedTeamReport) -> int:
    return 12 if _pydantic_ai_runtime_warn_count(report) else 0


def _pydantic_ai_runtime_summary_suffix(report: EvidenceGapReport | RedTeamReport) -> str:
    if not report.pydantic_ai_model_backed_requested:
        return ""
    if report.pydantic_ai_model_backed_fallback:
        reason = report.pydantic_ai_fallback_reason or report.pydantic_ai_execution_mode
        return f" Pydantic-AI model-backed path fell back ({reason})."
    if not report.pydantic_ai_runtime_agent_created:
        return " Pydantic-AI model-backed path was requested but no runtime agent was created."
    return " Pydantic-AI model-backed path completed."


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_int(value: object, *, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _business_plan_for_project(
    project_id: str,
    store: EnterpriseStore,
    user: EnterpriseUserContext,
) -> BusinessIntelPlan:
    project = _project_or_404(project_id, store, user, "project:read")
    competitors = store.list_competitors(project_id=project_id)
    accepted_dimensions = _accepted_schema_dimensions(project.metadata)
    dimensions = sorted(
        {
            item.dimension
            for item in store.list_evidence(project_id=project_id)
        }
        | set(accepted_dimensions)
    )
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


@router.post(
    "/enterprise/projects/{project_id}/evidence/seed",
    response_model=EvidenceSeedIngestResult,
)
def ingest_project_evidence_seed(
    project_id: str,
    request: EvidenceSeedIngestRequest,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
) -> EvidenceSeedIngestResult:
    project = _project_or_404(project_id, store, user, "evidence:write")
    try:
        return ingest_evidence_seed_corpus(
            store=store,
            workspace_id=project.workspace_id,
            project_id=project_id,
            topic=request.topic or project.topic,
            competitors=request.competitors,
            dimensions=request.dimensions,
            run_id=request.run_id,
            limit=request.limit,
            competitor_id_map=_competitor_id_map_for_project(project_id, store),
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


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


@router.post("/enterprise/source-snapshots", response_model=SourceSnapshotResult)
def create_source_snapshot(
    request: SourceSnapshotCreateRequest,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
    artifact_storage: ArtifactStorageDep,
) -> SourceSnapshotResult:
    _require_workspace_access(user, request.workspace_id, "artifact:write")
    project = _project_or_404(request.project_id, store, user, "source:write")
    if project.workspace_id != request.workspace_id:
        raise HTTPException(status_code=400, detail="Snapshot workspace does not match project")
    if request.evidence_id is not None:
        evidence = _evidence_or_404(request.evidence_id, store)
        if (
            evidence.workspace_id != request.workspace_id
            or evidence.project_id != request.project_id
        ):
            raise HTTPException(status_code=400, detail="Snapshot evidence scope mismatch")
    try:
        return capture_source_snapshot(
            request,
            store=store,
            artifact_storage=artifact_storage,
            actor_id=user.user_id,
        )
    except ArtifactStorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
    action = "source:review" if record.policy_review_status != "not_required" else "source:write"
    _require_workspace_access(user, record.workspace_id, action)
    return store.upsert_source_registry(record, actor_id=user.user_id)


@router.patch(
    "/enterprise/evidence/{evidence_id}/quality",
    response_model=EvidenceQualityUpdateResult,
)
def update_evidence_quality(
    evidence_id: str,
    request: EvidenceQualityUpdateRequest,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
    settings: SettingsDep,
    memory: PreferenceMemoryDep,
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
    _capture_evidence_quality_memory(evidence, request, user, settings, memory)
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
    if version.status == "published":
        _enforce_report_publish_status(version, store)
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


@router.post(
    "/enterprise/report-versions/{version_id}/manual-revision",
    response_model=ReportVersionRecord,
)
def create_manual_report_revision(
    version_id: str,
    request: ManualReportRevisionRequest,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
    settings: SettingsDep,
    memory: PreferenceMemoryDep,
) -> ReportVersionRecord:
    source = _report_version_or_404(version_id, store, user, "report:write")
    next_version = store.next_report_version_number(
        project_id=source.project_id,
        topic_normalized=source.topic_normalized,
        competitor_layer=source.competitor_layer,
        competitor_set_hash=source.competitor_set_hash,
    )
    metadata = dict(source.quality_metadata)
    metadata["manual_revision"] = {
        "source_report_version_id": source.id,
        "edited_by": user.user_id,
        "note": request.note,
        "created_at": datetime.utcnow().isoformat(),
    }
    revision = source.model_copy(
        update={
            "id": _manual_report_revision_id(source, next_version, request.report_md),
            "parent_version_id": source.id,
            "version_number": next_version,
            "status": "draft",
            "report_md": request.report_md,
            "quality_metadata": metadata,
            "created_at": datetime.utcnow(),
            "published_at": None,
        }
    )
    updated = store.upsert_report_version(revision)
    _capture_manual_report_revision_memory(source, updated, request, user, settings, memory)
    return updated


@router.post("/enterprise/report-versions/{version_id}/export", response_model=ArtifactCreateResult)
def export_report_version(
    version_id: str,
    store: EnterpriseStoreDep,
    user: EnterpriseUserDep,
    artifact_storage: ArtifactStorageDep,
    format: str = "markdown",
) -> ArtifactCreateResult:
    version = _report_version_or_404(version_id, store, user, "report:read")
    _require_workspace_access(user, version.workspace_id, "artifact:write")
    project = _project_or_404(version.project_id, store, user, "artifact:write")
    if project.workspace_id != version.workspace_id:
        raise HTTPException(status_code=400, detail="Report workspace does not match project")
    body, filename, media_type = _report_export_payload(version, format)
    request = ArtifactCreateRequest(
        workspace_id=version.workspace_id,
        project_id=version.project_id,
        run_id=version.run_id,
        artifact_type="report_export",
        filename=filename,
        media_type=media_type,
        content_text=body,
        metadata={
            "report_version_id": version.id,
            "report_version_number": version.version_number,
            "report_status": version.status,
            "export_format": _normalize_report_export_format(format),
        },
    )
    try:
        artifact = artifact_storage.store(request, actor_id=user.user_id)
    except ArtifactStorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ArtifactCreateResult(artifact=store.upsert_artifact(artifact))


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
    if version.status not in {"approved", "published"}:
        raise HTTPException(
            status_code=409,
            detail={
                "status": "blocked",
                "reason": "report_approval_required",
                "message": (
                    "Report version must be approved before it can be published."
                ),
                "report_version_id": version.id,
                "current_status": version.status,
            },
        )
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


def _capture_evidence_quality_memory(
    evidence: EvidenceRecord,
    request: EvidenceQualityUpdateRequest,
    user: EnterpriseUserContext,
    settings: Settings,
    memory: PreferenceMemoryStore,
) -> None:
    note = request.note.strip()
    if request.quality_label == "accepted" and not note:
        return
    feedback_type = "rejection" if request.quality_label == "rejected" else "correction"
    message_parts = [
        (
            f"Evidence quality review marked {evidence.title} as "
            f"{request.quality_label}."
        ),
        (
            f"Treat {evidence.dimension} source quality issues as a quality gate "
            "before publish."
        ),
    ]
    if note:
        message_parts.append(note)
    feedback = memory.add_feedback(
        UserFeedbackRecord(
            id="",
            workspace_id=evidence.workspace_id,
            project_id=evidence.project_id,
            user_id=user.user_id,
            feedback_type=feedback_type,
            target_type="evidence",
            target_id=evidence.id,
            run_id=evidence.run_id,
            message=" ".join(message_parts),
            tags=[
                "evidence",
                "quality_gate",
                request.quality_label,
                evidence.dimension,
                evidence.source_type,
            ],
            metadata={
                "source": "evidence_quality_review",
                "quality_label": request.quality_label,
                "raw_source_id": evidence.raw_source_id,
                "source_type": evidence.source_type,
            },
        ),
        policy=compliance_policy_from_settings(settings),
    )
    for candidate in memory.extract_candidates(feedback):
        memory.upsert_candidate(candidate)


def _capture_manual_report_revision_memory(
    source: ReportVersionRecord,
    revision: ReportVersionRecord,
    request: ManualReportRevisionRequest,
    user: EnterpriseUserContext,
    settings: Settings,
    memory: PreferenceMemoryStore,
) -> None:
    note = request.note.strip()
    message_parts = [
        f"Manual report correction created draft v{revision.version_number}.",
        (
            "Treat reviewer edits as writing and QA policy feedback: keep recommendations "
            "source-backed, decision-ready, and explicit about evidence risk."
        ),
    ]
    if note:
        message_parts.append(note)
    feedback = memory.add_feedback(
        UserFeedbackRecord(
            id="",
            workspace_id=revision.workspace_id,
            project_id=revision.project_id,
            user_id=user.user_id,
            feedback_type="correction",
            target_type="report",
            target_id=revision.id,
            run_id=revision.run_id,
            report_version_id=revision.id,
            message=" ".join(message_parts),
            tags=[
                "manual_revision",
                "report",
                "correction",
                "writing",
                "quality_gate",
                revision.competitor_layer,
            ],
            metadata={
                "source": "manual_report_revision",
                "source_report_version_id": source.id,
                "updated_report_version_id": revision.id,
                "version_number": revision.version_number,
                "note": note,
            },
        ),
        policy=compliance_policy_from_settings(settings),
    )
    for candidate in memory.extract_candidates(feedback):
        memory.upsert_candidate(candidate)


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


def _competitor_id_map_for_project(
    project_id: str,
    store: EnterpriseStore,
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for competitor in store.list_competitors(project_id=project_id):
        keys = [competitor.name, competitor.normalized_name, *competitor.aliases]
        for key in keys:
            normalized = _slug_key(key)
            if normalized:
                mapping[normalized] = competitor.id
    return mapping


def _slug_key(value: str) -> str:
    return "-".join(re.findall(r"[a-z0-9]+", value.casefold()))


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


def _manual_report_revision_id(
    source: ReportVersionRecord,
    version_number: int,
    report_md: str,
) -> str:
    digest = hashlib.sha256(
        "|".join([source.id, str(version_number), report_md]).encode("utf-8")
    ).hexdigest()[:16]
    return f"report-version-manual-{digest}"


def _normalize_report_export_format(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"md", "markdown"}:
        return "markdown"
    if normalized in {"html", "web"}:
        return "html"
    if normalized in {"csv", "excel"}:
        return "csv"
    raise HTTPException(
        status_code=400,
        detail="Unsupported report export format. Use markdown, html, or csv.",
    )


def _report_export_payload(version: ReportVersionRecord, format: str) -> tuple[str, str, str]:
    normalized = _normalize_report_export_format(format)
    filename_base = f"report-v{version.version_number}-{version.id}"
    if normalized == "markdown":
        return version.report_md, f"{filename_base}.md", "text/markdown"
    if normalized == "html":
        title = html.escape(f"Report v{version.version_number} / {version.topic_normalized}")
        body = html.escape(version.report_md)
        return (
            (
                "<!doctype html>\n"
                '<html lang="en">\n'
                "<head>\n"
                '  <meta charset="utf-8" />\n'
                f"  <title>{title}</title>\n"
                "</head>\n"
                "<body>\n"
                f"  <main><h1>{title}</h1><pre>{body}</pre></main>\n"
                "</body>\n"
                "</html>\n"
            ),
            f"{filename_base}.html",
            "text/html",
        )
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["field", "value"])
    writer.writerow(["report_version_id", version.id])
    writer.writerow(["version_number", version.version_number])
    writer.writerow(["status", version.status])
    writer.writerow(["run_id", version.run_id or ""])
    writer.writerow(["competitor_layer", version.competitor_layer])
    writer.writerow(["topic_normalized", version.topic_normalized])
    writer.writerow([])
    writer.writerow(["line_number", "text"])
    for index, line in enumerate(version.report_md.splitlines(), start=1):
        writer.writerow([index, line])
    return output.getvalue(), f"{filename_base}.csv", "text/csv"


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
        source_registry=store.list_source_registry(workspace_id=project.workspace_id),
    )


def _project_with_schema_review(
    project: ProjectRecord,
    review: SchemaEvolutionReviewRecord,
) -> ProjectRecord:
    metadata = dict(project.metadata)
    reviews = _metadata_mapping(metadata.get("schema_evolution_reviews"))
    reviews[review.suggestion_id] = review.model_dump(mode="json")
    accepted = _metadata_mapping(metadata.get("accepted_schema_dimensions"))
    if review.decision == "accepted":
        accepted[review.normalized_dimension] = review.model_dump(mode="json")
    else:
        accepted.pop(review.normalized_dimension, None)
    metadata["schema_evolution_reviews"] = reviews
    metadata["accepted_schema_dimensions"] = accepted
    metadata["schema_evolution_last_review"] = review.model_dump(mode="json")
    return project.model_copy(
        update={
            "metadata": metadata,
            "updated_at": datetime.utcnow(),
        }
    )


def _accepted_schema_dimensions(
    metadata: dict[str, object],
) -> dict[str, SchemaEvolutionReviewRecord]:
    accepted = _metadata_mapping(metadata.get("accepted_schema_dimensions"))
    result: dict[str, SchemaEvolutionReviewRecord] = {}
    for dimension, raw_review in accepted.items():
        if isinstance(raw_review, dict):
            result[dimension] = SchemaEvolutionReviewRecord.model_validate(raw_review)
    return result


def _metadata_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _with_gap_fill_release_gate_delta(
    result: EvidenceGapFillResult,
    *,
    project: ProjectRecord,
    store: EnterpriseStore,
) -> EvidenceGapFillResult:
    source_gate = _release_gate_for_report_version_id(
        result.source_report_version_id,
        project=project,
        store=store,
    )
    updated_gate = _release_gate_for_report_version_id(
        result.updated_report_version_id,
        project=project,
        store=store,
    )
    if source_gate is None or updated_gate is None:
        return result.model_copy(
            update={
                "source_release_gate": source_gate,
                "updated_release_gate": updated_gate,
            }
        )
    blocker_delta = source_gate.blocker_count - updated_gate.blocker_count
    warn_delta = source_gate.warn_count - updated_gate.warn_count
    readiness_delta = updated_gate.readiness.score - source_gate.readiness.score
    not_worse = (
        updated_gate.blocker_count <= source_gate.blocker_count
        and updated_gate.warn_count <= source_gate.warn_count
    )
    enriched = result.model_copy(
        update={
            "source_release_gate": source_gate,
            "updated_release_gate": updated_gate,
            "release_gate_blocker_delta": blocker_delta,
            "release_gate_warn_delta": warn_delta,
            "readiness_score_delta": readiness_delta,
            "release_gate_improved": not_worse
            and (
                (updated_gate.allowed and not source_gate.allowed)
                or blocker_delta > 0
                or warn_delta > 0
                or readiness_delta > 0
            ),
        }
    )
    return _persist_gap_fill_release_gate_delta(enriched, store=store)


def _persist_gap_fill_release_gate_delta(
    result: EvidenceGapFillResult,
    *,
    store: EnterpriseStore,
) -> EvidenceGapFillResult:
    if result.updated_report_version_id is None:
        return result
    version = store.get_report_version(result.updated_report_version_id)
    if version is None:
        return result
    metadata = dict(version.quality_metadata)
    gap_fill = _metadata_mapping(metadata.get("rag_gap_fill"))
    gap_fill["release_gate_delta"] = {
        "source_report_version_id": result.source_report_version_id,
        "updated_report_version_id": result.updated_report_version_id,
        "source_allowed": result.source_release_gate.allowed
        if result.source_release_gate is not None
        else None,
        "updated_allowed": result.updated_release_gate.allowed
        if result.updated_release_gate is not None
        else None,
        "source_status": result.source_release_gate.status
        if result.source_release_gate is not None
        else None,
        "updated_status": result.updated_release_gate.status
        if result.updated_release_gate is not None
        else None,
        "source_blocker_count": result.source_release_gate.blocker_count
        if result.source_release_gate is not None
        else None,
        "updated_blocker_count": result.updated_release_gate.blocker_count
        if result.updated_release_gate is not None
        else None,
        "source_warn_count": result.source_release_gate.warn_count
        if result.source_release_gate is not None
        else None,
        "updated_warn_count": result.updated_release_gate.warn_count
        if result.updated_release_gate is not None
        else None,
        "release_gate_blocker_delta": result.release_gate_blocker_delta,
        "release_gate_warn_delta": result.release_gate_warn_delta,
        "readiness_score_delta": result.readiness_score_delta,
        "release_gate_improved": result.release_gate_improved,
        "generated_at": datetime.utcnow().isoformat(),
    }
    metadata["rag_gap_fill"] = gap_fill
    updated_version = store.upsert_report_version(
        version.model_copy(update={"quality_metadata": metadata})
    )
    return result.model_copy(update={"updated_report_version": updated_version})


def _release_gate_for_report_version_id(
    version_id: str | None,
    *,
    project: ProjectRecord,
    store: EnterpriseStore,
) -> ReportReleaseGate | None:
    if version_id is None:
        return None
    version = store.get_report_version(version_id)
    if version is None:
        return None
    return evaluate_report_release_gate(
        project=project,
        report_version=version,
        competitors=store.list_competitors(project_id=project.id),
        evidence=store.list_evidence(project_id=project.id),
        claims=store.list_claims(project_id=project.id),
        source_registry=store.list_source_registry(workspace_id=project.workspace_id),
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


def _enforce_report_publish_status(
    version: ReportVersionRecord,
    store: EnterpriseStore,
) -> None:
    current = store.get_report_version(version.id)
    current_status = current.status if current is not None else "missing"
    if current_status in {"approved", "published"}:
        return
    raise HTTPException(
        status_code=409,
        detail={
            "status": "blocked",
            "reason": "report_approval_required",
            "message": "Report version must be approved before it can be published.",
            "report_version_id": version.id,
            "current_status": current_status,
        },
    )


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
