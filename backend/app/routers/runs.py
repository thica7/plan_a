import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.deps import (
    get_app_settings,
    get_run_service,
    get_temporal_workflow_service,
)
from app.governance import ensure_model_policy_allows_execution_mode
from packages.business_intel import compare_run_quality
from packages.config import Settings
from packages.enterprise import WorkspaceQuotaExceededError
from packages.identity import new_ui_run_idempotency_key
from packages.orchestrator.service import RunService
from packages.schema.api_dto import (
    RunCreateRequest,
    RunDetail,
    RunQualityComparison,
    RunSummary,
    WorkflowStartResponse,
)
from packages.schema.survey import UserResearchImportRequest, UserResearchImportResult
from packages.workflows.service import (
    TemporalWorkflowService,
    decide_temporal_cutover,
)

router = APIRouter()
RunServiceDep = Annotated[RunService, Depends(get_run_service)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
TemporalWorkflowServiceDep = Annotated[
    TemporalWorkflowService,
    Depends(get_temporal_workflow_service),
]


@router.post(
    "/runs",
    response_model=RunDetail | WorkflowStartResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_run(
    request: RunCreateRequest,
    response: Response,
    settings: SettingsDep,
    workflow_service: TemporalWorkflowServiceDep,
    service: RunServiceDep,
) -> RunDetail | WorkflowStartResponse:
    request = _with_run_idempotency_key(request)
    ensure_model_policy_allows_execution_mode(request.execution_mode, settings)
    _ensure_workspace_quota(service, request.workspace_id)
    cutover = decide_temporal_cutover(settings, request)
    response.headers["X-Run-Orchestration-Route"] = cutover.route
    response.headers["X-Temporal-Traffic-Percent"] = str(cutover.target_percent)
    response.headers["X-Temporal-Cutover-Bucket"] = str(cutover.bucket)
    if cutover.route == "temporal":
        try:
            result = await workflow_service.start_competitive_intel(request)
        except Exception as exc:  # noqa: BLE001 - surface Temporal cutover failures clearly.
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Temporal workflow service is unavailable.",
            ) from exc
        try:
            await _ensure_temporal_run_visible(result, request, service)
        except WorkspaceQuotaExceededError as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=exc.decision.model_dump(mode="json"),
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - explain post-start visibility failures.
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Temporal workflow started but run visibility sync failed.",
            ) from exc
        response.status_code = status.HTTP_202_ACCEPTED
        return result

    try:
        detail = await service.create_run(request)
    except WorkspaceQuotaExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=exc.decision.model_dump(mode="json"),
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    asyncio.create_task(service.run_pipeline(detail.id))
    return detail


async def _ensure_temporal_run_visible(
    result: WorkflowStartResponse,
    request: RunCreateRequest,
    service: RunService,
) -> None:
    visible_request = request.model_copy(update={"idempotency_key": result.idempotency_key})
    detail = await service.ensure_run_visible(visible_request)
    if detail.id != result.run_id:
        raise RuntimeError(
            f"Temporal returned run_id={result.run_id}, but local visibility "
            f"created run_id={detail.id}."
        )


def _with_run_idempotency_key(request: RunCreateRequest) -> RunCreateRequest:
    if request.idempotency_key:
        return request
    return request.model_copy(update={"idempotency_key": new_ui_run_idempotency_key()})


def _ensure_workspace_quota(service: RunService, workspace_id: str) -> None:
    try:
        service.ensure_workspace_quota_allows_run(workspace_id)
    except WorkspaceQuotaExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=exc.decision.model_dump(mode="json"),
        ) from exc


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
