from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_app_settings, get_run_service
from app.events import RunEvent
from packages.compliance import RunComplianceReport, build_run_compliance_report
from packages.config import Settings
from packages.observability import (
    DecisionReplayReport,
    OtelTraceExport,
    TraceObservabilityReport,
    build_decision_replay,
    build_otel_trace_export,
    evaluate_trace_observability,
)
from packages.orchestrator.service import RunService
from packages.schema.models import AgentMessage, ToolCallMessage, TraceSpan

router = APIRouter()
RunServiceDep = Annotated[RunService, Depends(get_run_service)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]


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


@router.get("/runs/{run_id}/trace/otel", response_model=OtelTraceExport)
async def get_trace_otel_export(
    run_id: str,
    service: RunServiceDep,
) -> OtelTraceExport:
    spans = service.get_trace_spans(run_id)
    if spans is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return build_otel_trace_export(run_id, spans)


@router.get("/runs/{run_id}/trace/observability", response_model=TraceObservabilityReport)
async def get_trace_observability_report(
    run_id: str,
    service: RunServiceDep,
) -> TraceObservabilityReport:
    spans = service.get_trace_spans(run_id)
    if spans is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return evaluate_trace_observability(run_id, spans)


@router.get("/runs/{run_id}/compliance", response_model=RunComplianceReport)
async def get_run_compliance_report(
    run_id: str,
    service: RunServiceDep,
    settings: SettingsDep,
) -> RunComplianceReport:
    detail = service.get_run(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return build_run_compliance_report(detail, settings=settings)


@router.get("/runs/{run_id}/decision-replay", response_model=DecisionReplayReport)
async def get_decision_replay(
    run_id: str,
    service: RunServiceDep,
) -> DecisionReplayReport:
    detail = service.get_run(run_id)
    events = service.get_trace(run_id)
    if detail is None or events is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return build_decision_replay(detail, events)


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
