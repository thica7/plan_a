from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from app.deps import get_enterprise_user_context, get_run_service, require_run_access
from packages.auth import EnterpriseUserContext
from packages.orchestrator.service import RunService

router = APIRouter()
RunServiceDep = Annotated[RunService, Depends(get_run_service)]
EnterpriseUserDep = Annotated[EnterpriseUserContext, Depends(get_enterprise_user_context)]


@router.get("/runs/{run_id}/stream")
async def stream_run(
    run_id: str,
    request: Request,
    service: RunServiceDep,
    user: EnterpriseUserDep,
    last_event_id: Annotated[int, Header(alias="Last-Event-ID", ge=0)] = 0,
) -> EventSourceResponse:
    require_run_access(service, run_id, user, "report:read")
    if not service.run_exists(run_id):
        raise HTTPException(status_code=404, detail="Run not found")

    async def event_generator():
        async for event in service.stream_events(run_id, after_event_id=last_event_id):
            if await request.is_disconnected():
                break
            yield event.to_sse()

    return EventSourceResponse(event_generator())
