from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.deps import get_temporal_workflow_service
from packages.schema.api_dto import RunCreateRequest, WorkflowStartResponse
from packages.workflows.service import TemporalWorkflowService

router = APIRouter()
TemporalWorkflowServiceDep = Annotated[
    TemporalWorkflowService,
    Depends(get_temporal_workflow_service),
]


@router.post(
    "/workflows/competitive-intel",
    response_model=WorkflowStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_competitive_intel_workflow(
    request: RunCreateRequest,
    service: TemporalWorkflowServiceDep,
) -> WorkflowStartResponse:
    try:
        return await service.start_competitive_intel(request)
    except Exception as exc:  # noqa: BLE001 - surface Temporal availability as HTTP 503.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Temporal workflow service is unavailable.",
        ) from exc
