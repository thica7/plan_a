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
    if service.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if request.decision == "redo" and not service.has_pending_interrupt(run_id):
        raise HTTPException(status_code=409, detail="Manual scoped redo must use POST /runs/{run_id}/redo")
    detail = await service.resume(run_id, request)
    if detail is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return detail


@router.post("/runs/{run_id}/redo", response_model=RunDetail)
async def start_manual_redo(
    run_id: str,
    service: RunService = Depends(get_run_service),
) -> RunDetail:
    detail = service.get_run(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if service.has_pending_interrupt(run_id):
        raise HTTPException(status_code=409, detail="Resolve the active HITL interrupt before manual redo.")
    if not service.can_start_redo(run_id):
        raise HTTPException(status_code=409, detail="No eligible QA findings or redo limit reached.")
    asyncio.create_task(service.run_scoped_redo(run_id))
    return detail
