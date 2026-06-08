from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_run_service
from packages.orchestrator.service import RunService
from packages.schema.models import CompetitorKnowledge

router = APIRouter()
RunServiceDep = Annotated[RunService, Depends(get_run_service)]


@router.get("/runs/{run_id}/kb", response_model=dict[str, CompetitorKnowledge])
async def get_run_kb(
    run_id: str,
    service: RunServiceDep,
) -> dict[str, CompetitorKnowledge]:
    detail = service.get_run(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return detail.competitor_knowledge
