from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from app.deps import get_run_service
from packages.orchestrator.service import RunService

router = APIRouter()
RunServiceDep = Annotated[RunService, Depends(get_run_service)]


@router.get("/runs/{run_id}/stream")
async def stream_run(
    run_id: str,
    request: Request,
    service: RunServiceDep,
) -> EventSourceResponse:
    if not service.run_exists(run_id):
        raise HTTPException(status_code=404, detail="Run not found")

    async def event_generator():
        async for event in service.stream_events(run_id):
            if await request.is_disconnected():
                break
            yield event.to_sse()

    return EventSourceResponse(event_generator())
