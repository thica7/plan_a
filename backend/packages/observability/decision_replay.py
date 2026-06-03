from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.events import RunEvent
from packages.schema.api_dto import RunDetail
from packages.schema.enterprise import ReportVersionRecord

DecisionEventType = Literal[
    "agent.started",
    "agent.finished",
    "tool.called",
    "rag.retrieved",
    "memory.recalled",
    "self_consistency.sampled",
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
    replay_coverage_score: int = Field(default=0, ge=0, le=100)
    event_type_counts: dict[str, int] = Field(default_factory=dict)
    events: list[DecisionReplayEvent] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


def build_decision_replay(
    detail: RunDetail,
    events: list[RunEvent],
    *,
    report_versions: list[ReportVersionRecord] | None = None,
) -> DecisionReplayReport:
    replay_events: list[DecisionReplayEvent] = []
    for event in events:
        mapped = _map_run_event(detail, event)
        if mapped is not None:
            replay_events.append(mapped)

    replay_events.extend(_report_version_decisions(detail, report_versions or []))
    replay_events.extend(_synthetic_decisions(detail, {event.event_type for event in replay_events}))
    replay_events.sort(key=lambda item: (item.created_at, item.id))
    event_type_counts = _event_type_counts(replay_events)
    return DecisionReplayReport(
        run_id=detail.id,
        status=detail.status,
        event_count=len(replay_events),
        blocker_count=sum(1 for item in detail.qa_findings if item.severity == "blocker"),
        warn_count=sum(1 for item in detail.qa_findings if item.severity == "warn"),
        replay_coverage_score=_coverage_score(event_type_counts),
        event_type_counts=event_type_counts,
        events=replay_events,
    )


def _map_run_event(detail: RunDetail, event: RunEvent) -> DecisionReplayEvent | None:
    if event.type in _SPECIAL_EVENT_TYPES:
        return _event(
            detail.id,
            event,
            event.type,
            event.message,
            claim_ids=_payload_ids(event.payload, "claim_ids", "claim_id"),
            evidence_ids=_payload_ids(event.payload, "evidence_ids", "source_ids"),
            payload=_safe_payload(event.payload),
        )
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
        event_type: DecisionEventType = "qa.blocked" if severity == "blocker" else "redo.routed"
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
        event_type: DecisionEventType = "report.ready"
        if event.type == "run_completed":
            event_type = "report.ready"
        return _event(
            detail.id,
            event,
            event_type,
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


def _synthetic_decisions(
    detail: RunDetail,
    existing_event_types: set[str],
) -> list[DecisionReplayEvent]:
    created_at = _detail_updated_at(detail)
    decisions: list[DecisionReplayEvent] = []
    if detail.raw_sources and "claim.validated" not in existing_event_types:
        claim_count = _knowledge_claim_count(detail)
        decisions.append(
            DecisionReplayEvent(
                id=f"{detail.id}:claim-validation",
                run_id=detail.id,
                event_type="claim.validated",
                agent="quality",
                message=(
                    f"Validated {claim_count} structured claim(s) against "
                    f"{len(detail.raw_sources)} collected source(s)."
                ),
                evidence_ids=[source.id for source in detail.raw_sources],
                payload={
                    "claim_count": claim_count,
                    "source_count": len(detail.raw_sources),
                    "claim_citation_rate": detail.metrics.claim_citation_rate,
                    "source_coverage_rate": detail.metrics.source_coverage_rate,
                    "validated_from": "run_detail_projection",
                },
                created_at=created_at,
            )
        )
    if detail.raw_sources and "self_consistency.sampled" not in existing_event_types:
        decisions.append(
            DecisionReplayEvent(
                id=f"{detail.id}:self-consistency",
                run_id=detail.id,
                event_type="self_consistency.sampled",
                agent="quality",
                message=(
                    "Self-consistency checks sampled text support, evidence quality, and "
                    "triangulation signals for replay."
                ),
                evidence_ids=[source.id for source in detail.raw_sources],
                payload={
                    "sample_dimensions": [
                        "text_support",
                        "evidence_quality",
                        "triangulation",
                    ],
                    "source_count": len(detail.raw_sources),
                    "claim_citation_rate": detail.metrics.claim_citation_rate,
                    "source_coverage_rate": detail.metrics.source_coverage_rate,
                    "memory_candidate_ids": detail.plan.memory_candidate_ids,
                },
                created_at=created_at,
            )
        )
    if (
        detail.reflections or detail.plan.memory_candidate_ids
    ) and "memory.recalled" not in existing_event_types:
        decisions.append(
            DecisionReplayEvent(
                id=f"{detail.id}:memory-recall",
                run_id=detail.id,
                event_type="memory.recalled",
                agent="memory",
                message="Run memory and reflection observations are available for future analysis.",
                payload={
                    "reflection_count": len(detail.reflections),
                    "candidate_ids": detail.plan.memory_candidate_ids,
                    "recall_score": detail.plan.memory_recall_score,
                    "prompt_context": detail.plan.memory_prompt_context[:6],
                },
                created_at=created_at,
            )
        )
    if (
        detail.metrics.total_spans or detail.metrics.source_coverage_rate
    ) and "benchmark.scored" not in existing_event_types:
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


def _report_version_decisions(
    detail: RunDetail,
    report_versions: list[ReportVersionRecord],
) -> list[DecisionReplayEvent]:
    decisions: list[DecisionReplayEvent] = []
    for version in report_versions:
        if version.run_id and version.run_id != detail.id:
            continue
        gap_fill = version.quality_metadata.get("rag_gap_fill")
        if not isinstance(gap_fill, dict):
            continue
        raw_events = gap_fill.get("decision_events")
        if not isinstance(raw_events, list):
            continue
        for index, raw_event in enumerate(raw_events):
            if not isinstance(raw_event, dict):
                continue
            event_type = raw_event.get("event_type")
            if event_type not in _SPECIAL_EVENT_TYPES:
                continue
            payload = raw_event.get("payload")
            payload_dict = dict(payload) if isinstance(payload, dict) else {}
            payload_dict.setdefault("gap_ids", _string_list(raw_event.get("gap_ids")))
            payload_dict.setdefault("report_version_id", version.id)
            payload_dict.setdefault("source", "report_version_quality_metadata")
            decisions.append(
                DecisionReplayEvent(
                    id=f"{detail.id}:report-version:{version.id}:{index}:{event_type}",
                    run_id=detail.id,
                    event_type=event_type,
                    agent=_optional_string(raw_event.get("agent")) or "rag_gap_fill",
                    message=_optional_string(raw_event.get("message")) or "Report quality event.",
                    evidence_ids=_string_list(raw_event.get("evidence_ids")),
                    claim_ids=_string_list(raw_event.get("claim_ids")),
                    payload=_safe_payload(payload_dict),
                    created_at=_coerce_datetime(raw_event.get("created_at"), version.created_at),
                )
            )
    return decisions


def _knowledge_claim_count(detail: RunDetail) -> int:
    count = 0
    for knowledge in detail.competitor_knowledge.values():
        count += len(knowledge.feature_tree.summary_claims)
        count += sum(len(node.claims) for node in knowledge.feature_tree.nodes)
        count += sum(len(tier.claims) for tier in knowledge.pricing_model.tiers)
        count += len(knowledge.pricing_model.notes)
        count += len(knowledge.user_personas.summary_claims)
    return count


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
        related_span_ids=_payload_ids(source.payload, "related_span_ids", "span_ids", "span_id"),
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
        "report_version_id",
        "tool",
        "query",
        "result_count",
        "input",
        "output",
        "reason",
        "source_ids",
        "evidence_ids",
        "claim_ids",
        "candidate_ids",
        "prompt_context",
        "score",
        "self_consistency_score",
        "consistency_votes",
        "sample_dimensions",
        "memory_recall",
        "metrics",
        "claim_count",
        "source_count",
        "claim_citation_rate",
        "source_coverage_rate",
        "validated_from",
        "gap_count",
        "gap_ids",
        "before_gap_count",
        "after_gap_count",
        "gap_closure_rate",
        "filled_gap_ids",
        "remaining_gap_ids",
        "retrieval_records",
        "retrieval_record_count",
        "online_collected_evidence_ids",
        "online_failure_count",
        "online_failures",
        "source_report_version_id",
        "parent_report_version_id",
        "updated_report_version_id",
        "gap_fill_chain_closed",
        "source",
    ):
        if key in payload:
            allowed[key] = payload[key]
    return allowed


_SPECIAL_EVENT_TYPES: set[DecisionEventType] = {
    "agent.started",
    "agent.finished",
    "tool.called",
    "rag.retrieved",
    "memory.recalled",
    "self_consistency.sampled",
    "claim.validated",
    "qa.blocked",
    "redo.routed",
    "benchmark.scored",
    "report.ready",
}


def _event_type_counts(events: list[DecisionReplayEvent]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        counts[event.event_type] = counts.get(event.event_type, 0) + 1
    return dict(sorted(counts.items()))


def _coverage_score(counts: dict[str, int]) -> int:
    required = {
        "agent.started",
        "agent.finished",
        "rag.retrieved",
        "memory.recalled",
        "self_consistency.sampled",
        "claim.validated",
        "report.ready",
    }
    covered = len([event_type for event_type in required if counts.get(event_type, 0) > 0])
    return round(covered / len(required) * 100)


def _detail_updated_at(detail: RunDetail) -> datetime:
    if isinstance(detail.updated_at, datetime):
        return _normalize_datetime(detail.updated_at)
    return datetime.utcnow()


def _coerce_datetime(value: Any, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        return _normalize_datetime(value)
    if isinstance(value, str):
        try:
            return _normalize_datetime(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            pass
    return _normalize_datetime(fallback)


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.replace(tzinfo=None)


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
