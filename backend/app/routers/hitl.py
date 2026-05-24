import asyncio

from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_run_service
from packages.orchestrator.service import RunService
from packages.schema.api_dto import HitlResumeRequest, RunDetail

router = APIRouter()


@router.post("/runs/{run_id}/resume", response_model=RunDetail)
async def resume_run(
    run_id: str,
    request: HitlResumeRequest,
    service: RunService = Depends(get_run_service),
) -> RunDetail:
    should_start_redo = (
        request.decision == "redo"
        and service.can_start_redo(run_id)
        and not service.has_pending_interrupt(run_id)
    )
    detail = await service.resume(run_id, request)
    if detail is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if should_start_redo:
        asyncio.create_task(service.run_scoped_redo(run_id))
    return detail
