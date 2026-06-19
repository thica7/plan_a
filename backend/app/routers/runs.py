import math
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.deps import (
    get_app_settings,
    get_create_run_rate_limiter,
    get_enterprise_user_context,
    get_run_service,
    get_runtime_command_service,
)
from app.rate_limit import RateLimitDecision, SlidingWindowRateLimiter
from packages.auth import EnterpriseUserContext
from packages.business_intel import compare_run_quality
from packages.config import Settings
from packages.orchestrator.service import RunService
from packages.runtime import CreateRunCommand, RuntimeCommandError, RuntimeCommandService
from packages.schema.api_dto import (
    RunCreateRequest,
    RunDetail,
    RunQualityComparison,
    RunSummary,
    WorkflowStartResponse,
)
from packages.schema.survey import UserResearchImportRequest, UserResearchImportResult

router = APIRouter()
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
RunServiceDep = Annotated[RunService, Depends(get_run_service)]
RuntimeCommandServiceDep = Annotated[RuntimeCommandService, Depends(get_runtime_command_service)]
EnterpriseUserDep = Annotated[EnterpriseUserContext, Depends(get_enterprise_user_context)]
CreateRunRateLimiterDep = Annotated[
    SlidingWindowRateLimiter,
    Depends(get_create_run_rate_limiter),
]


@router.post(
    "/runs",
    response_model=RunDetail | WorkflowStartResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_run(
    request: RunCreateRequest,
    response: Response,
    runtime: RuntimeCommandServiceDep,
    user: EnterpriseUserDep,
    settings: SettingsDep,
    rate_limiter: CreateRunRateLimiterDep,
) -> RunDetail | WorkflowStartResponse:
    rate_limit = _enforce_create_run_rate_limit(request, settings, rate_limiter)
    response.headers["X-Create-Run-RateLimit-Remaining"] = str(rate_limit.remaining)
    try:
        result = await runtime.create_run(CreateRunCommand(request=request), actor=user)
    except RuntimeCommandError as exc:
        _raise_runtime_command_error(exc)
    response.headers["X-Run-Orchestration-Route"] = result.route
    if "temporal_target_percent" in result.metadata:
        response.headers["X-Temporal-Traffic-Percent"] = str(
            result.metadata["temporal_target_percent"]
        )
    if "temporal_cutover_bucket" in result.metadata:
        response.headers["X-Temporal-Cutover-Bucket"] = str(
            result.metadata["temporal_cutover_bucket"]
        )
    runtime_policy = result.metadata.get("runtime_policy_decision")
    if isinstance(runtime_policy, dict):
        response.headers["X-Runtime-Policy-Status"] = str(runtime_policy.get("status", ""))
        response.headers["X-Runtime-Policy-Reason"] = str(
            runtime_policy.get("audit_reason", "")
        )[:240]
    response.headers["X-Runtime-Command-Id"] = result.command_id
    response.headers["X-Runtime-Audit-Correlation-Id"] = result.audit_correlation_id
    if result.route == "temporal":
        response.status_code = status.HTTP_202_ACCEPTED
    return result.payload


@router.get("/runs", response_model=list[RunSummary])
async def list_runs(service: RunServiceDep) -> list[RunSummary]:
    return service.list_runs()


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(
    run_id: str,
    service: RunServiceDep,
    include_trace_payloads: bool = Query(default=False),
) -> RunDetail:
    detail = service.get_run(run_id, include_trace_payloads=include_trace_payloads)
    if detail is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return detail


@router.post("/runs/{run_id}/user-research", response_model=UserResearchImportResult)
async def import_user_research_materials(
    run_id: str,
    request: UserResearchImportRequest,
    service: RunServiceDep,
) -> UserResearchImportResult:
    result = service.import_user_research_materials(run_id, request)
    if result is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return result


@router.get("/runs/{run_id}/quality-comparison", response_model=RunQualityComparison)
async def get_run_quality_comparison(
    run_id: str,
    service: RunServiceDep,
    baseline_run_id: str | None = Query(default=None),
) -> RunQualityComparison:
    detail = service.get_run(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Run not found")
    baseline = None
    if baseline_run_id:
        baseline = service.get_run(baseline_run_id)
        if baseline is None:
            raise HTTPException(status_code=404, detail="Baseline run not found")
    return compare_run_quality(detail, baseline=baseline)


def _raise_runtime_command_error(error: RuntimeCommandError) -> None:
    raise HTTPException(status_code=error.status_code, detail=error.detail)


def _enforce_create_run_rate_limit(
    request: RunCreateRequest,
    settings: Settings,
    rate_limiter: SlidingWindowRateLimiter,
) -> RateLimitDecision:
    decision = rate_limiter.allow(
        f"workspace:{request.workspace_id}",
        limit=settings.create_run_rate_limit_per_window,
        window_seconds=settings.create_run_rate_limit_window_seconds,
        unique_id=request.idempotency_key,
    )
    if decision.allowed:
        return decision
    retry_after = max(1, math.ceil(decision.retry_after_seconds))
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "reason": "Create run rate limit exceeded.",
            "workspace_id": request.workspace_id,
            "limit": settings.create_run_rate_limit_per_window,
            "window_seconds": settings.create_run_rate_limit_window_seconds,
            "retry_after_seconds": retry_after,
        },
        headers={"Retry-After": str(retry_after)},
    )
