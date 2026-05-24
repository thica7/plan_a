from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_run_service
from packages.orchestrator.service import RunService
from packages.schema.models import RevisionRecord

router = APIRouter()


@router.get("/runs/{run_id}/revisions", response_model=list[RevisionRecord])
async def get_run_revisions(
    run_id: str,
    service: RunService = Depends(get_run_service),
) -> list[RevisionRecord]:
    detail = service.get_run(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return detail.revisions
