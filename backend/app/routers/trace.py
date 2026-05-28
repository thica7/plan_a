from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_run_service
from app.events import RunEvent
from packages.orchestrator.service import RunService
from packages.schema.models import AgentMessage, ToolCallMessage, TraceSpan

router = APIRouter()
RunServiceDep = Annotated[RunService, Depends(get_run_service)]


@router.get("/runs/{run_id}/trace", response_model=list[RunEvent])
async def get_trace(
    run_id: str,
    service: RunServiceDep,
) -> list[RunEvent]:
    events = service.get_trace(run_id)
    if events is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return events


@router.get("/runs/{run_id}/trace/spans", response_model=list[TraceSpan])
async def get_trace_spans(
    run_id: str,
    service: RunServiceDep,
) -> list[TraceSpan]:
    spans = service.get_trace_spans(run_id)
    if spans is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return spans


@router.get("/runs/{run_id}/trace/agent-messages", response_model=list[AgentMessage])
async def get_agent_messages(
    run_id: str,
    service: RunServiceDep,
) -> list[AgentMessage]:
    messages = service.get_agent_messages(run_id)
    if messages is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return messages


@router.get("/runs/{run_id}/trace/tool-calls", response_model=list[ToolCallMessage])
async def get_tool_call_messages(
    run_id: str,
    service: RunServiceDep,
) -> list[ToolCallMessage]:
    messages = service.get_tool_call_messages(run_id)
    if messages is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return messages
