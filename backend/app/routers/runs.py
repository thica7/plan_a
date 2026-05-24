import asyncio

from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_run_service
from packages.orchestrator.service import RunService
from packages.schema.api_dto import RunCreateRequest, RunDetail, RunSummary

router = APIRouter()


@router.post("/runs", response_model=RunDetail, status_code=201)
async def create_run(
    request: RunCreateRequest,
    service: RunService = Depends(get_run_service),
) -> RunDetail:
    try:
        detail = await service.create_run(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    asyncio.create_task(service.run_pipeline(detail.id))
    return detail


@router.get("/runs", response_model=list[RunSummary])
async def list_runs(service: RunService = Depends(get_run_service)) -> list[RunSummary]:
    return service.list_runs()


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(
    run_id: str,
    service: RunService = Depends(get_run_service),
) -> RunDetail:
    detail = service.get_run(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return detail
