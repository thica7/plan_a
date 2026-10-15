from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_enterprise_user_context, get_run_service, require_run_access
from packages.auth import EnterpriseUserContext
from packages.orchestrator.service import RunService
from packages.schema.models import CompetitorKnowledge

router = APIRouter()
RunServiceDep = Annotated[RunService, Depends(get_run_service)]
EnterpriseUserDep = Annotated[EnterpriseUserContext, Depends(get_enterprise_user_context)]


@router.get("/runs/{run_id}/kb", response_model=dict[str, CompetitorKnowledge])
async def get_run_kb(
    run_id: str,
    service: RunServiceDep,
    user: EnterpriseUserDep,
) -> dict[str, CompetitorKnowledge]:
    require_run_access(service, run_id, user, "report:read")
    detail = service.get_run(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return detail.competitor_knowledge
