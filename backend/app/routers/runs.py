from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.deps import (
    get_enterprise_user_context,
    get_run_service,
    get_runtime_command_service,
)
from packages.auth import EnterpriseUserContext
from packages.business_intel import compare_run_quality
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
RunServiceDep = Annotated[RunService, Depends(get_run_service)]
RuntimeCommandServiceDep = Annotated[RuntimeCommandService, Depends(get_runtime_command_service)]
EnterpriseUserDep = Annotated[EnterpriseUserContext, Depends(get_enterprise_user_context)]


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
) -> RunDetail | WorkflowStartResponse:
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
) -> RunDetail:
    detail = service.get_run(run_id)
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
