from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.events import RunEvent
from packages.schema.api_dto import RunDetail

DecisionEventType = Literal[
    "agent.started",
    "agent.finished",
    "tool.called",
    "rag.retrieved",
    "memory.recalled",
    "claim.validated",
    "qa.blocked",
    "redo.routed",
    "benchmark.scored",
    "report.ready",
]


class DecisionReplayEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    run_id: str
    event_type: DecisionEventType
    agent: str | None = None
    subagent: str | None = None
    message: str
    source_event_id: int | None = None
    related_span_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class DecisionReplayReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: str
    event_count: int = Field(ge=0)
    blocker_count: int = Field(default=0, ge=0)
    warn_count: int = Field(default=0, ge=0)
    events: list[DecisionReplayEvent] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


def build_decision_replay(
    detail: RunDetail,
    events: list[RunEvent],
) -> DecisionReplayReport:
    replay_events: list[DecisionReplayEvent] = []
    for event in events:
        mapped = _map_run_event(detail, event)
        if mapped is not None:
            replay_events.append(mapped)

    replay_events.extend(_synthetic_decisions(detail))
    replay_events.sort(key=lambda item: (item.created_at, item.id))
    return DecisionReplayReport(
        run_id=detail.id,
        status=detail.status,
        event_count=len(replay_events),
        blocker_count=sum(1 for item in detail.qa_findings if item.severity == "blocker"),
        warn_count=sum(1 for item in detail.qa_findings if item.severity == "warn"),
        events=replay_events,
    )


def _map_run_event(detail: RunDetail, event: RunEvent) -> DecisionReplayEvent | None:
    if event.type == "node_started":
        return _event(
            detail.id,
            event,
            "agent.started",
            event.message,
            payload=_safe_payload(event.payload),
        )
    if event.type == "node_completed":
        event_type: DecisionEventType = "agent.finished"
        if event.agent == "collector" or event.payload.get("retrieval_records"):
            event_type = "rag.retrieved"
        return _event(
            detail.id,
            event,
            event_type,
            event.message,
            evidence_ids=_payload_ids(event.payload, "evidence_ids", "source_ids"),
            payload=_safe_payload(event.payload),
        )
    if event.type == "qa_issue":
        severity = str(event.payload.get("severity") or "")
        event_type = "qa.blocked" if severity == "blocker" else "redo.routed"
        return _event(
            detail.id,
            event,
            event_type,
            event.message,
            claim_ids=_payload_ids(event.payload, "claim_ids", "claim_id"),
            evidence_ids=_payload_ids(event.payload, "evidence_ids", "source_ids"),
            payload=_safe_payload(event.payload),
        )
    if event.type in {"report_updated", "run_completed"}:
        return _event(
            detail.id,
            event,
            "report.ready",
            event.message,
            evidence_ids=[source.id for source in detail.raw_sources],
            payload=_safe_payload(event.payload),
        )
    if event.type == "revision_recorded":
        return _event(
            detail.id,
            event,
            "redo.routed",
            event.message,
            payload=_safe_payload(event.payload),
        )
    return None


def _synthetic_decisions(detail: RunDetail) -> list[DecisionReplayEvent]:
    created_at = _detail_updated_at(detail)
    decisions: list[DecisionReplayEvent] = []
    if detail.raw_sources:
        decisions.append(
            DecisionReplayEvent(
                id=f"{detail.id}:claim-validation",
                run_id=detail.id,
                event_type="claim.validated",
                agent="quality",
                message=(
                    f"Validated evidence support for {len(detail.raw_sources)} collected sources."
                ),
                evidence_ids=[source.id for source in detail.raw_sources],
                created_at=created_at,
            )
        )
    if detail.reflections:
        decisions.append(
            DecisionReplayEvent(
                id=f"{detail.id}:memory-recall",
                run_id=detail.id,
                event_type="memory.recalled",
                agent="memory",
                message="Run memory and reflection observations are available for future analysis.",
                payload={"reflection_count": len(detail.reflections)},
                created_at=created_at,
            )
        )
    if detail.metrics.total_spans or detail.metrics.source_coverage_rate:
        decisions.append(
            DecisionReplayEvent(
                id=f"{detail.id}:benchmark",
                run_id=detail.id,
                event_type="benchmark.scored",
                agent="observability",
                message="Run metrics were scored for quality, cost, and coverage review.",
                payload=detail.metrics.model_dump(mode="json"),
                created_at=created_at,
            )
        )
    return decisions


def _event(
    run_id: str,
    source: RunEvent,
    event_type: DecisionEventType,
    message: str,
    *,
    claim_ids: list[str] | None = None,
    evidence_ids: list[str] | None = None,
    payload: dict[str, Any] | None = None,
) -> DecisionReplayEvent:
    return DecisionReplayEvent(
        id=f"{run_id}:decision:{source.id}",
        run_id=run_id,
        event_type=event_type,
        agent=source.agent,
        subagent=source.subagent,
        message=message,
        source_event_id=source.id,
        evidence_ids=evidence_ids or [],
        claim_ids=claim_ids or [],
        payload=payload or {},
        created_at=_normalize_datetime(source.created_at),
    )


def _payload_ids(payload: dict[str, Any], *keys: str) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str):
            values = [value]
        elif isinstance(value, list):
            values = value
        else:
            values = []
        for item in values:
            if isinstance(item, str) and item not in seen:
                seen.add(item)
                ids.append(item)
    return ids


def _safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    allowed: dict[str, Any] = {}
    for key in (
        "status",
        "severity",
        "agent",
        "subagent",
        "node",
        "redo_scope",
        "release_gate",
        "enterprise_projection",
    ):
        if key in payload:
            allowed[key] = payload[key]
    return allowed


def _detail_updated_at(detail: RunDetail) -> datetime:
    if isinstance(detail.updated_at, datetime):
        return _normalize_datetime(detail.updated_at)
    return datetime.utcnow()


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.replace(tzinfo=None)
