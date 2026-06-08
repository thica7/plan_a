from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_run_service
from packages.orchestrator.service import RunService
from packages.schema.models import RevisionRecord

router = APIRouter()
RunServiceDep = Annotated[RunService, Depends(get_run_service)]


@router.get("/runs/{run_id}/revisions", response_model=list[RevisionRecord])
async def get_run_revisions(
    run_id: str,
    service: RunServiceDep,
) -> list[RevisionRecord]:
    detail = service.get_run(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return detail.revisions
