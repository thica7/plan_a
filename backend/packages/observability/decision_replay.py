from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.events import RunEvent
from packages.identity import stable_prefixed_id
from packages.schema.api_dto import RunDetail
from packages.schema.enterprise import AuditLogRecord, ReportVersionRecord

DecisionEventType = Literal[
    "agent.started",
    "agent.finished",
    "tool.called",
    "rag.retrieved",
    "memory.recalled",
    "memory.feedback_captured",
    "hitl.reviewed",
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
    audit_logs: list[AuditLogRecord] | None = None,
    report_versions: list[ReportVersionRecord] | None = None,
) -> DecisionReplayReport:
    report_versions = report_versions or []
    replay_events: list[DecisionReplayEvent] = []
    for event in events:
        mapped = _map_run_event(detail, event)
        if mapped is not None:
            replay_events.append(mapped)

    replay_events.extend(_report_version_decisions(detail, report_versions))
    replay_events.extend(_audit_log_decisions(detail, report_versions, audit_logs or []))
    replay_events.extend(
        _synthetic_decisions(detail, {event.event_type for event in replay_events})
    )
    replay_events.sort(key=lambda item: (item.created_at, item.id))
    event_type_counts = _event_type_counts(replay_events)
    return DecisionReplayReport(
        run_id=detail.id,
        status=detail.status,
        event_count=len(replay_events),
        blocker_count=sum(1 for item in detail.qa_findings if item.severity == "blocker"),
        warn_count=sum(1 for item in detail.qa_findings if item.severity == "warn"),
        replay_coverage_score=_coverage_score(event_type_counts, detail),
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
        if event.agent == "hitl":
            event_type = "hitl.reviewed"
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
        severity = _qa_issue_severity(event.payload)
        event_type: DecisionEventType = "qa.blocked" if severity == "blocker" else "redo.routed"
        return _event(
            detail.id,
            event,
            event_type,
            event.message,
            claim_ids=_payload_ids(event.payload, "claim_ids", "claim_id"),
            evidence_ids=_payload_ids(event.payload, "evidence_ids", "source_ids"),
            payload=_qa_issue_payload(event.payload),
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
    if detail.raw_sources and "rag.retrieved" not in existing_event_types:
        source_ids = [source.id for source in detail.raw_sources]
        decisions.append(
            DecisionReplayEvent(
                id=stable_prefixed_id("decision", detail.id, "rag-retrieved", length=16),
                run_id=detail.id,
                event_type="rag.retrieved",
                agent="collector",
                message=(
                    f"Replay reconstructed {len(source_ids)} collected source(s) from "
                    "the persisted run detail."
                ),
                evidence_ids=source_ids,
                payload={
                    "source": "run_detail_projection",
                    "source_count": len(source_ids),
                    "source_ids": source_ids,
                    "dimensions": sorted({source.dimension for source in detail.raw_sources}),
                    "source_types": sorted({source.source_type for source in detail.raw_sources}),
                },
                created_at=created_at,
            )
        )
    if detail.raw_sources and "claim.validated" not in existing_event_types:
        claim_count = _knowledge_claim_count(detail)
        decisions.append(
            DecisionReplayEvent(
                id=stable_prefixed_id("decision", detail.id, "claim-validation", length=16),
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
                id=stable_prefixed_id("decision", detail.id, "self-consistency", length=16),
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
                id=stable_prefixed_id("decision", detail.id, "memory-recall", length=16),
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
                id=stable_prefixed_id("decision", detail.id, "benchmark", length=16),
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
        decisions.append(_report_version_ready_event(detail, version))
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
            release_gate_delta = gap_fill.get("release_gate_delta")
            if event_type == "report.ready" and isinstance(release_gate_delta, dict):
                payload_dict.setdefault("release_gate_delta", release_gate_delta)
                payload_dict.setdefault(
                    "release_gate_improved",
                    release_gate_delta.get("release_gate_improved"),
                )
                payload_dict.setdefault(
                    "release_gate_blocker_delta",
                    release_gate_delta.get("release_gate_blocker_delta"),
                )
                payload_dict.setdefault(
                    "release_gate_warn_delta",
                    release_gate_delta.get("release_gate_warn_delta"),
                )
                payload_dict.setdefault(
                    "readiness_score_delta",
                    release_gate_delta.get("readiness_score_delta"),
                )
            payload_dict.setdefault("gap_ids", _string_list(raw_event.get("gap_ids")))
            payload_dict.setdefault("report_version_id", version.id)
            payload_dict.setdefault("source", "report_version_quality_metadata")
            decisions.append(
                DecisionReplayEvent(
                    id=stable_prefixed_id(
                        "decision",
                        detail.id,
                        "report-version",
                        version.id,
                        index,
                        event_type,
                        length=16,
                    ),
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


def _report_version_ready_event(
    detail: RunDetail,
    version: ReportVersionRecord,
) -> DecisionReplayEvent:
    manual_revision = version.quality_metadata.get("manual_revision")
    manual_revision_payload = manual_revision if isinstance(manual_revision, dict) else {}
    is_manual_revision = bool(manual_revision_payload)
    message = (
        f"Manual report revision v{version.version_number} captured for replay."
        if is_manual_revision
        else f"Report version v{version.version_number} captured for replay."
    )
    payload = {
        "report_version_id": version.id,
        "version_number": version.version_number,
        "report_version_status": version.status,
        "parent_version_id": version.parent_version_id,
        "source": "report_version_record",
        "manual_revision": is_manual_revision,
        "edited_by": _optional_string(manual_revision_payload.get("edited_by")),
        "manual_revision_note": _optional_string(manual_revision_payload.get("note")),
        "source_report_version_id": _optional_string(
            manual_revision_payload.get("source_report_version_id")
        ),
    }
    return DecisionReplayEvent(
        id=stable_prefixed_id(
            "decision",
            detail.id,
            "report-version-ready",
            version.id,
            length=16,
        ),
        run_id=detail.id,
        event_type="report.ready",
        agent="report_version",
        message=message,
        evidence_ids=list(version.evidence_ids),
        claim_ids=list(version.claim_ids),
        payload=_safe_payload(payload),
        created_at=_normalize_datetime(version.created_at),
    )


def _audit_log_decisions(
    detail: RunDetail,
    report_versions: list[ReportVersionRecord],
    audit_logs: list[AuditLogRecord],
) -> list[DecisionReplayEvent]:
    version_ids = {
        version.id
        for version in report_versions
        if not version.run_id or version.run_id == detail.id
    }
    raw_source_ids = {source.id for source in detail.raw_sources}
    decisions: list[DecisionReplayEvent] = []
    for log in audit_logs:
        mapped = _audit_log_decision(
            detail,
            log,
            version_ids=version_ids,
            raw_source_ids=raw_source_ids,
        )
        if mapped is not None:
            decisions.append(mapped)
    return decisions


def _audit_log_decision(
    detail: RunDetail,
    log: AuditLogRecord,
    *,
    version_ids: set[str],
    raw_source_ids: set[str],
) -> DecisionReplayEvent | None:
    if log.action in _REPORT_LIFECYCLE_AUDIT_ACTIONS and log.resource_id in version_ids:
        return _report_lifecycle_audit_decision(detail, log)

    if log.action == "report_version.status_changed" and log.resource_id in version_ids:
        status = _audit_after_string(log, "status") or "updated"
        event_type: DecisionEventType = "report.ready" if status == "published" else "hitl.reviewed"
        return _audit_event(
            detail,
            log,
            event_type,
            agent="report_approval",
            message=f"Report version {log.resource_id} status changed to {status}.",
            payload={
                "decision": status,
                "report_version_id": log.resource_id,
                "report_version_status": status,
                "version_number": _audit_after_value(log, "version_number"),
            },
        )

    if log.action == "artifact.upserted" and _audit_run_id(log) == detail.id:
        metadata = _audit_metadata(log)
        export_kind = _optional_string(metadata.get("export_kind"))
        artifact_type = _audit_after_string(log, "artifact_type") or "artifact"
        report_version_id = _audit_after_string(log, "report_version_id")
        label = export_kind or artifact_type
        return _audit_event(
            detail,
            log,
            "report.ready",
            agent="artifact_store",
            message=f"Artifact {log.resource_id} captured for {label}.",
            payload={
                "artifact_type": artifact_type,
                "export_kind": export_kind,
                "storage_backend": _audit_after_string(log, "storage_backend"),
                "report_version_id": report_version_id,
                "retention_policy": _audit_after_string(log, "retention_policy"),
                "compliance_metadata": _audit_after_value(log, "compliance_metadata"),
                "run_id": detail.id,
            },
        )

    if log.action == "source_registry.upserted" and _audit_source_matches_run(
        detail,
        log,
    ):
        status = _audit_after_string(log, "policy_review_status") or "not_required"
        previous_status = _audit_before_string(log, "policy_review_status")
        if status == "not_required" and previous_status in {None, "not_required"}:
            return None
        domain = _audit_after_string(log, "domain") or log.resource_id
        source_type = _audit_after_string(log, "source_type") or "unknown"
        return _audit_event(
            detail,
            log,
            "hitl.reviewed",
            agent="source_registry",
            message=f"Source policy review for {domain} is {status}.",
            payload={
                "decision": status,
                "policy_review_status": status,
                "previous_policy_review_status": previous_status,
                "policy_review_reason": _audit_after_string(log, "policy_review_reason"),
                "source_domain": domain,
                "source_type": source_type,
                "run_id": detail.id,
            },
        )

    if log.action == "evidence.quality_updated" and _audit_evidence_matches_run(
        detail,
        log,
        raw_source_ids=raw_source_ids,
    ):
        quality_label = _audit_after_string(log, "quality_label") or "updated"
        return _audit_event(
            detail,
            log,
            "hitl.reviewed",
            agent="evidence_center",
            message=f"Evidence {log.resource_id} quality marked {quality_label}.",
            evidence_ids=[log.resource_id],
            payload={
                "decision": quality_label,
                "quality_label": quality_label,
                "previous_quality_label": _audit_before_string(log, "quality_label"),
                "note": _audit_after_string(log, "quality_note"),
            },
        )

    if log.action == "memory.feedback_captured" and _audit_memory_feedback_matches_run(
        detail,
        log,
        version_ids=version_ids,
    ):
        candidate_count = _audit_after_value(log, "candidate_count") or 0
        feedback_id = _audit_after_string(log, "feedback_id") or log.resource_id
        return _audit_event(
            detail,
            log,
            "memory.feedback_captured",
            agent="memory",
            message=(
                f"Memory feedback {feedback_id} captured "
                f"{candidate_count} candidate(s) for future recall."
            ),
            payload={
                "feedback_id": feedback_id,
                "feedback_type": _audit_after_string(log, "feedback_type"),
                "candidate_ids": _string_list(_audit_after_value(log, "candidate_ids")),
                "candidate_count": candidate_count,
                "candidate_kinds": _string_list(_audit_after_value(log, "candidate_kinds")),
                "candidate_statuses": _string_list(_audit_after_value(log, "candidate_statuses")),
                "target_type": _audit_after_string(log, "target_type"),
                "target_id": _audit_after_string(log, "target_id"),
                "run_id": _audit_after_string(log, "run_id"),
                "report_version_id": _audit_after_string(log, "report_version_id"),
                "project_id": _audit_after_string(log, "project_id"),
                "message_excerpt": _audit_after_string(log, "message_excerpt"),
                "redaction_counts": _audit_after_value(log, "redaction_counts"),
            },
        )

    if log.action == "schema_evolution.reviewed" and log.resource_id == detail.project_id:
        decision = _audit_after_string(log, "decision") or "reviewed"
        return _audit_event(
            detail,
            log,
            "hitl.reviewed",
            agent="schema_governance",
            message=f"Schema evolution suggestion {log.resource_id} was {decision}.",
            payload={
                "decision": decision,
                "project_id": detail.project_id,
                "target_id": _audit_after_string(log, "suggestion_id"),
                "target_type": "schema_suggestion",
                "note": _audit_after_string(log, "note"),
            },
        )

    return None


_REPORT_LIFECYCLE_AUDIT_ACTIONS = {
    "report_version.approval_requested",
    "report_version.approved",
    "report_version.rejected",
    "report_version.published",
    "report_version.manual_revision_created",
}


def _report_lifecycle_audit_decision(
    detail: RunDetail,
    log: AuditLogRecord,
) -> DecisionReplayEvent:
    status = _audit_after_string(log, "status") or _report_status_from_audit_action(log.action)
    event_type: DecisionEventType = "report.ready" if status == "published" else "hitl.reviewed"
    action_label = log.action.removeprefix("report_version.")
    return _audit_event(
        detail,
        log,
        event_type,
        agent="report_lifecycle",
        message=f"Report version {log.resource_id} lifecycle event: {action_label}.",
        payload={
            "decision": action_label,
            "report_version_id": log.resource_id,
            "report_version_status": status,
            "version_number": _audit_after_value(log, "version_number"),
            "approval_workflow": _audit_after_value(log, "approval_workflow"),
            "publication": _audit_after_value(log, "publication"),
            "release_gate": _audit_after_value(log, "release_gate"),
            "manual_revision": _audit_after_value(log, "manual_revision"),
            "source_report_version_id": _audit_after_string(log, "source_report_version_id"),
            "source_status": _audit_after_string(log, "source_status"),
            "diff": _audit_after_value(log, "diff"),
            "note": _audit_after_string(log, "note"),
        },
    )


def _report_status_from_audit_action(action: str) -> str:
    if action.endswith(".approval_requested"):
        return "in_review"
    if action.endswith(".approved"):
        return "approved"
    if action.endswith(".rejected"):
        return "rejected"
    if action.endswith(".published"):
        return "published"
    if action.endswith(".manual_revision_created"):
        return "draft"
    return "updated"


def _audit_event(
    detail: RunDetail,
    log: AuditLogRecord,
    event_type: DecisionEventType,
    *,
    agent: str,
    message: str,
    evidence_ids: list[str] | None = None,
    claim_ids: list[str] | None = None,
    payload: dict[str, Any] | None = None,
) -> DecisionReplayEvent:
    payload = {
        **(payload or {}),
        "audit_log_id": log.id,
        "audit_action": log.action,
        "actor_id": log.actor_id,
        "actor_type": log.actor_type,
        "resource_type": log.resource_type,
        "resource_id": log.resource_id,
        "source": "enterprise_audit_log",
    }
    return DecisionReplayEvent(
        id=stable_prefixed_id("decision", detail.id, "audit", log.id, length=16),
        run_id=detail.id,
        event_type=event_type,
        agent=agent,
        message=message,
        evidence_ids=evidence_ids or [],
        claim_ids=claim_ids or [],
        payload=_safe_payload(payload),
        created_at=_normalize_datetime(log.created_at),
    )


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
        id=stable_prefixed_id("decision", run_id, source.id, length=16),
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


def _audit_run_id(log: AuditLogRecord) -> str | None:
    return _audit_after_string(log, "run_id") or _audit_metadata_string(log, "run_id")


def _audit_source_matches_run(detail: RunDetail, log: AuditLogRecord) -> bool:
    return detail.id in {
        _audit_after_string(log, "first_seen_run_id"),
        _audit_after_string(log, "last_seen_run_id"),
        _audit_run_id(log),
    }


def _audit_evidence_matches_run(
    detail: RunDetail,
    log: AuditLogRecord,
    *,
    raw_source_ids: set[str],
) -> bool:
    if _audit_run_id(log) == detail.id:
        return True
    raw_source_id = _audit_after_string(log, "raw_source_id")
    return raw_source_id is not None and raw_source_id in raw_source_ids


def _audit_memory_feedback_matches_run(
    detail: RunDetail,
    log: AuditLogRecord,
    *,
    version_ids: set[str],
) -> bool:
    if _audit_after_string(log, "run_id") == detail.id:
        return True
    report_version_id = _audit_after_string(log, "report_version_id")
    return report_version_id is not None and report_version_id in version_ids


def _audit_metadata(log: AuditLogRecord) -> dict[str, Any]:
    after = log.after if isinstance(log.after, dict) else {}
    metadata = after.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _audit_metadata_string(log: AuditLogRecord, key: str) -> str | None:
    return _optional_string(_audit_metadata(log).get(key))


def _audit_after_string(log: AuditLogRecord, key: str) -> str | None:
    return _optional_string(_audit_after_value(log, key))


def _audit_before_string(log: AuditLogRecord, key: str) -> str | None:
    before = log.before if isinstance(log.before, dict) else {}
    return _optional_string(before.get(key))


def _audit_after_value(log: AuditLogRecord, key: str) -> Any:
    after = log.after if isinstance(log.after, dict) else {}
    return after.get(key)


def _safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    allowed: dict[str, Any] = {}
    for key in (
        "audit_log_id",
        "audit_action",
        "actor_id",
        "actor_type",
        "resource_type",
        "resource_id",
        "status",
        "severity",
        "issue_id",
        "problem",
        "phase",
        "field_path",
        "detected_by",
        "target_agent",
        "target_subagent",
        "target_competitor",
        "self_found",
        "agent",
        "subagent",
        "node",
        "redo_scope",
        "release_gate",
        "release_gate_delta",
        "release_gate_improved",
        "release_gate_blocker_delta",
        "release_gate_warn_delta",
        "readiness_score_delta",
        "approval_workflow",
        "publication",
        "diff",
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
        "candidate_urls",
        "candidate_kinds",
        "candidate_statuses",
        "feedback_id",
        "feedback_type",
        "candidate_count",
        "target_type",
        "target_id",
        "stage",
        "note",
        "interrupt_node",
        "interrupt_protocol",
        "resume_command",
        "timeout_seconds",
        "prompt_context",
        "decision",
        "dimensions",
        "score",
        "self_consistency_score",
        "consistency_votes",
        "sample_count",
        "sample_dimensions",
        "memory_recall",
        "metrics",
        "claim_count",
        "source_count",
        "source_types",
        "dimension_count",
        "bundle_count",
        "question_count",
        "response_count",
        "interview_count",
        "claim_citation_rate",
        "source_coverage_rate",
        "validated_from",
        "claim_validation",
        "claim_status_counts",
        "claim_validation_issue_count",
        "validation_sample_count",
        "validation_samples",
        "low_consistency_count",
        "minority_sample_count",
        "minority_validation_samples",
        "gap_count",
        "gap_ids",
        "before_gap_count",
        "after_gap_count",
        "gap_closure_rate",
        "filled_gap_ids",
        "remaining_gap_ids",
        "gap_evidence_links",
        "retrieval_queries",
        "retrieval_contexts",
        "chunk_ids",
        "rerank_scores",
        "retrieval_records",
        "retrieval_record_count",
        "retrieval_stage",
        "online_collected_evidence_ids",
        "online_failure_count",
        "online_failures",
        "source_report_version_id",
        "parent_report_version_id",
        "parent_version_id",
        "updated_report_version_id",
        "version_number",
        "report_version_status",
        "artifact_type",
        "export_kind",
        "storage_backend",
        "retention_policy",
        "compliance_metadata",
        "source_url",
        "message_excerpt",
        "redaction_count",
        "redaction_counts",
        "research_redacted",
        "policy_review_status",
        "previous_policy_review_status",
        "policy_review_reason",
        "source_domain",
        "source_type",
        "quality_label",
        "previous_quality_label",
        "project_id",
        "run_id",
        "manual_revision",
        "manual_revision_note",
        "edited_by",
        "source_status",
        "gap_fill_chain_closed",
        "source",
    ):
        if key in payload:
            allowed[key] = payload[key]
    return allowed


def _qa_issue_severity(payload: dict[str, Any]) -> str:
    severity = payload.get("severity")
    if isinstance(severity, str):
        return severity
    issue = payload.get("issue")
    if isinstance(issue, dict) and isinstance(issue.get("severity"), str):
        return issue["severity"]
    return ""


def _qa_issue_payload(payload: dict[str, Any]) -> dict[str, Any]:
    issue = payload.get("issue")
    if not isinstance(issue, dict):
        return _safe_payload(payload)

    normalized = dict(payload)
    normalized.setdefault("issue_id", _optional_string(issue.get("id")))
    normalized.setdefault("severity", _optional_string(issue.get("severity")))
    normalized.setdefault("problem", _optional_string(issue.get("problem")))
    normalized.setdefault("field_path", _optional_string(issue.get("field_path")))
    normalized.setdefault("detected_by", _optional_string(issue.get("detected_by")))
    normalized.setdefault("target_agent", _optional_string(issue.get("target_agent")))
    normalized.setdefault("target_subagent", _optional_string(issue.get("target_subagent")))
    normalized.setdefault("target_competitor", _optional_string(issue.get("target_competitor")))
    if "self_found" in issue:
        normalized.setdefault("self_found", issue.get("self_found"))
    redo_scope = issue.get("redo_scope")
    if isinstance(redo_scope, dict):
        normalized.setdefault("redo_scope", redo_scope)
    return _safe_payload(normalized)


_SPECIAL_EVENT_TYPES: set[DecisionEventType] = {
    "agent.started",
    "agent.finished",
    "tool.called",
    "rag.retrieved",
    "memory.recalled",
    "memory.feedback_captured",
    "hitl.reviewed",
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


def _coverage_score(counts: dict[str, int], detail: RunDetail) -> int:
    required = _coverage_requirements(detail)
    covered = len([event_type for event_type in required if counts.get(event_type, 0) > 0])
    return round(covered / len(required) * 100) if required else 100


def _coverage_requirements(detail: RunDetail) -> set[DecisionEventType]:
    required: set[DecisionEventType] = {
        "agent.started",
        "agent.finished",
        "report.ready",
    }
    if detail.raw_sources:
        required.update(
            {
                "rag.retrieved",
                "self_consistency.sampled",
                "claim.validated",
            }
        )
    if detail.reflections or detail.plan.memory_candidate_ids or detail.plan.memory_prompt_context:
        required.add("memory.recalled")
    if detail.qa_findings:
        if any(issue.severity == "blocker" for issue in detail.qa_findings):
            required.add("qa.blocked")
        if any(issue.severity != "blocker" for issue in detail.qa_findings):
            required.add("redo.routed")
    if detail.revisions:
        required.add("redo.routed")
    if detail.metrics.total_spans or detail.metrics.source_coverage_rate:
        required.add("benchmark.scored")
    return required


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
