import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.deps import (
    get_app_settings,
    get_enterprise_store,
    get_run_service,
    get_temporal_workflow_service,
)
from packages.config import Settings
from packages.enterprise import EnterpriseStore, WorkspaceQuotaExceededError
from packages.orchestrator.service import RunService
from packages.schema.api_dto import RunCreateRequest, RunDetail, RunSummary, WorkflowStartResponse
from packages.workflows.service import TemporalWorkflowService

router = APIRouter()
RunServiceDep = Annotated[RunService, Depends(get_run_service)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
TemporalWorkflowServiceDep = Annotated[
    TemporalWorkflowService,
    Depends(get_temporal_workflow_service),
]
EnterpriseStoreDep = Annotated[EnterpriseStore, Depends(get_enterprise_store)]


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
    store: EnterpriseStoreDep,
) -> RunDetail | WorkflowStartResponse:
    _ensure_workspace_quota(store, request.workspace_id)
    if settings.run_orchestration_backend == "temporal":
        try:
            result = await workflow_service.start_competitive_intel(request)
        except Exception as exc:  # noqa: BLE001 - surface Temporal cutover failures clearly.
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Temporal workflow service is unavailable.",
            ) from exc
        response.status_code = status.HTTP_202_ACCEPTED
        return result

    service = get_run_service()
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


def _ensure_workspace_quota(store: EnterpriseStore, workspace_id: str) -> None:
    decision = store.check_workspace_quota(workspace_id)
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=decision.model_dump(mode="json"),
        )


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
