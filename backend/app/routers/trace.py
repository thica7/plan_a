from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_run_service
from app.events import RunEvent
from packages.orchestrator.service import RunService

router = APIRouter()


@router.get("/runs/{run_id}/trace", response_model=list[RunEvent])
async def get_trace(
    run_id: str,
    service: RunService = Depends(get_run_service),
) -> list[RunEvent]:
    events = service.get_trace(run_id)
    if events is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return events
