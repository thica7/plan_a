import builtins
import sys
import types

from app.events import RunEvent
from packages.compliance import CompliancePolicy, redact_text
from packages.compliance.report import build_run_compliance_report
from packages.config import Settings
from packages.observability import (
    LangfuseAdapter,
    LangfuseConfig,
    build_decision_replay,
    build_otel_trace_export,
    build_run_event,
    evaluate_trace_observability,
    otel_span_id_for_span,
    sanitize_for_trace,
    trace_id_for_run,
    traceparent_for_span,
)
from packages.schema.api_dto import RunDetail
from packages.schema.enterprise import AuditLogRecord, ReportVersionRecord
from packages.schema.models import AnalysisPlan, RawSource, RunMetrics, TraceSpan


def test_trace_payload_sanitizes_nested_secrets() -> None:
    payload = {
        "ARK_API_KEY": "ark-secret",
        "headers": {"Authorization": "Bearer token"},
        "nested": [{"pplx_token": "pplx-secret", "visible": "safe"}],
    }

    sanitized = sanitize_for_trace(payload)

    assert sanitized["ARK_API_KEY"] == "[redacted]"
    assert sanitized["headers"]["Authorization"] == "[redacted]"
    assert sanitized["nested"][0]["pplx_token"] == "[redacted]"
    assert sanitized["nested"][0]["visible"] == "safe"


def test_build_run_event_applies_trace_sanitizer() -> None:
    event = build_run_event(
        event_id=1,
        run_id="run-1",
        event_type="node_started",
        agent="collector",
        subagent="pricing",
        message="started",
        payload={"api_key": "secret", "query": "pricing"},
    )

    assert event.swimlane == "pricing"
    assert event.trace_id == trace_id_for_run("run-1")
    assert event.payload == {"api_key": "[redacted]", "query": "pricing"}


def test_trace_payload_sanitizes_sensitive_text_values() -> None:
    sanitized = sanitize_for_trace(
        {
            "note": (
                "Contact alice@example.com with "
                "OPENROUTER_TEST_KEY_REDACTED."
            )
        }
    )

    assert sanitized["note"] == (
        "Contact [redacted:email] with [redacted:api_key]."
    )


def test_compliance_redactor_reports_counts_by_kind() -> None:
    result = redact_text(
        "Bearer abcdef1234567890 belongs to bob@example.com and +1 415 555 2671."
    )

    assert result.total_count == 3
    assert result.counts == {"bearer_token": 1, "email": 1, "phone": 1}
    assert "[redacted:bearer_token]" in result.text


def test_compliance_redactor_obeys_policy() -> None:
    result = redact_text(
        "Contact alice@example.com with OPENROUTER_TEST_KEY_REDACTED.",
        policy=CompliancePolicy(redact_emails=False, redact_api_keys=True),
    )

    assert "alice@example.com" in result.text
    assert "[redacted:api_key]" in result.text
    assert result.counts == {"api_key": 1}


def test_compliance_redactor_covers_groq_and_xai_provider_keys() -> None:
    result = redact_text(
        "Groq gsk_abcdef1234567890abcdef123456 and xAI xai-abcdef1234567890abcdef123456."
    )

    assert "gsk_abcdef" not in result.text
    assert "xai-abcdef" not in result.text
    assert result.text.count("[redacted:api_key]") == 2
    assert result.counts["api_key"] == 2


def test_otel_export_and_observability_report_require_trace_context() -> None:
    trace_id = trace_id_for_run("run-1")
    otel_span_id = otel_span_id_for_span("run-1", "span-1")
    span = TraceSpan(
        id="span-1",
        trace_id=trace_id,
        otel_span_id=otel_span_id,
        traceparent=traceparent_for_span(trace_id, otel_span_id),
        kind="llm",
        agent="planner",
        name="Plan",
        status="ok",
        duration_ms=12,
        metadata={"pii_redacted": True},
    )

    export = build_otel_trace_export("run-1", [span])
    report = evaluate_trace_observability("run-1", [span])

    assert export.trace_id == trace_id
    assert export.spans[0].span_id == otel_span_id
    assert export.spans[0].attributes["agent.name"] == "planner"
    assert report.status == "pass"
    assert report.otel_export_ready is True
    assert report.traceparent_coverage == 1.0


def test_observability_report_flags_missing_trace_context() -> None:
    span = TraceSpan(
        id="span-bad",
        kind="tool",
        agent="collector",
        name="Fetch",
        status="ok",
        duration_ms=1,
    )

    report = evaluate_trace_observability("run-1", [span])

    assert report.status == "fail"
    assert report.otel_export_ready is False
    assert {issue.field for issue in report.issues} >= {"trace_id", "otel_span_id"}


def test_decision_replay_maps_trace_into_audit_timeline() -> None:
    detail = RunDetail(
        id="run-1",
        topic="Decision replay run",
        status="completed",
        execution_mode="demo",
        created_at="2026-05-31T00:00:00Z",
        updated_at="2026-05-31T00:01:00Z",
        plan=AnalysisPlan(topic="Decision replay run", competitors=["A"], dimensions=["pricing"]),
        raw_sources=[
            RawSource(
                id="source-1",
                competitor="A",
                dimension="pricing",
                source_type="webpage_verified",
                title="A pricing",
                url="https://example.com/pricing",
                snippet="A publishes pricing.",
                content_hash="hash-1",
                confidence=0.9,
            )
        ],
        metrics=RunMetrics(total_spans=2, source_coverage_rate=1.0),
    )
    events = [
        RunEvent(
            id=1,
            run_id="run-1",
            type="node_started",
            agent="planner",
            message="Planner started",
        ),
        RunEvent(
            id=2,
            run_id="run-1",
            type="node_completed",
            agent="collector",
            message="Collector finished",
            payload={"source_ids": ["source-1"]},
        ),
        RunEvent(
            id=3,
            run_id="run-1",
            type="memory.recalled",
            agent="memory",
            message="Memory recalled",
            payload={"candidate_ids": ["memory-1"], "score": 86},
        ),
        RunEvent(
            id=4,
            run_id="run-1",
            type="memory.feedback_captured",
            agent="memory",
            message="HITL feedback captured",
            payload={
                "feedback_id": "feedback-1",
                "candidate_ids": ["memory-2"],
                "candidate_count": 1,
                "target_type": "dimension",
                "target_id": "feature",
                "decision": "modify_plan",
                "dimensions": ["feature"],
            },
        ),
        RunEvent(
            id=5,
            run_id="run-1",
            type="node_completed",
            agent="hitl",
            subagent="planner",
            message="HITL decision received: modify_plan",
            payload={
                "decision": "modify_plan",
                "stage": "planner",
                "dimensions": ["feature"],
                "note": "Prioritize enterprise workflow evidence.",
            },
        ),
        RunEvent(
            id=6,
            run_id="run-1",
            type="self_consistency.sampled",
            agent="quality",
            message="Consistency sampled",
            payload={
                "self_consistency_score": 88,
                "sample_count": 3,
                "minority_sample_count": 1,
                "minority_validation_samples": [
                    {
                        "claim_id": "claim-1",
                        "checker": "triangulation",
                        "vote": "fail",
                        "score": 45,
                        "threshold": 70,
                    }
                ],
                "claim_ids": ["claim-1"],
                "evidence_ids": ["source-1"],
            },
        ),
        RunEvent(
            id=7,
            run_id="run-1",
            type="run_completed",
            agent="writer",
            message="Run completed",
        ),
    ]

    replay = build_decision_replay(detail, events)

    assert replay.event_count >= 5
    assert {event.event_type for event in replay.events} >= {
        "agent.started",
        "rag.retrieved",
        "memory.recalled",
        "memory.feedback_captured",
        "hitl.reviewed",
        "self_consistency.sampled",
        "claim.validated",
        "benchmark.scored",
        "report.ready",
    }
    assert replay.replay_coverage_score >= 85
    assert replay.event_type_counts["memory.recalled"] >= 1
    assert replay.event_type_counts["memory.feedback_captured"] == 1
    assert replay.event_type_counts["hitl.reviewed"] == 1
    hitl_event = next(event for event in replay.events if event.event_type == "hitl.reviewed")
    assert hitl_event.payload["decision"] == "modify_plan"
    assert hitl_event.payload["stage"] == "planner"
    assert hitl_event.payload["dimensions"] == ["feature"]
    feedback_event = next(
        event for event in replay.events if event.event_type == "memory.feedback_captured"
    )
    assert feedback_event.payload["feedback_id"] == "feedback-1"
    assert feedback_event.payload["candidate_count"] == 1
    consistency_event = next(
        event for event in replay.events if event.event_type == "self_consistency.sampled"
    )
    assert consistency_event.payload["sample_count"] == 3
    assert consistency_event.payload["minority_sample_count"] == 1
    assert consistency_event.payload["minority_validation_samples"][0]["checker"] == "triangulation"
    assert any(event.evidence_ids == ["source-1"] for event in replay.events)


def test_decision_replay_prefers_real_claim_validation_events() -> None:
    detail = RunDetail(
        id="run-claim-validation",
        topic="Decision replay claim validation",
        status="completed",
        execution_mode="demo",
        created_at="2026-05-31T00:00:00Z",
        updated_at="2026-05-31T00:01:00Z",
        plan=AnalysisPlan(
            topic="Decision replay claim validation",
            competitors=["A"],
            dimensions=["pricing"],
        ),
        raw_sources=[
            RawSource(
                id="source-1",
                competitor="A",
                dimension="pricing",
                source_type="webpage_verified",
                title="A pricing",
                url="https://example.com/pricing",
                snippet="A publishes pricing.",
                content_hash="hash-1",
                confidence=0.9,
            )
        ],
        metrics=RunMetrics(claim_citation_rate=1.0, source_coverage_rate=1.0),
    )
    events = [
        RunEvent(
            id=1,
            run_id="run-claim-validation",
            type="claim.validated",
            agent="quality",
            message="Validated claims through release gate.",
            payload={
                "claim_ids": ["claim-1"],
                "evidence_ids": ["source-1"],
                "claim_count": 1,
                "source_count": 1,
                "release_gate": {"status": "blocked", "issue_count": 2},
                "validation_sample_count": 3,
                "validation_samples": [
                    {
                        "claim_id": "claim-1",
                        "checker": "text_support",
                        "vote": "pass",
                        "score": 88,
                        "threshold": 70,
                    }
                ],
            },
        )
    ]

    replay = build_decision_replay(detail, events)
    claim_events = [event for event in replay.events if event.event_type == "claim.validated"]

    assert len(claim_events) == 1
    assert claim_events[0].claim_ids == ["claim-1"]
    assert claim_events[0].evidence_ids == ["source-1"]
    assert claim_events[0].payload["claim_count"] == 1
    assert claim_events[0].payload["release_gate"] == {"status": "blocked", "issue_count": 2}
    assert claim_events[0].payload["validation_sample_count"] == 3
    assert claim_events[0].payload["validation_samples"][0]["checker"] == "text_support"


def test_decision_replay_maps_nested_blocker_qa_issue_to_blocked_event() -> None:
    detail = RunDetail(
        id="run-qa-blocker",
        topic="Decision replay QA blocker",
        status="completed_with_blockers",
        execution_mode="demo",
        created_at="2026-05-31T00:00:00Z",
        updated_at="2026-05-31T00:01:00Z",
        plan=AnalysisPlan(
            topic="Decision replay QA blocker",
            competitors=["A"],
            dimensions=["pricing"],
        ),
    )
    events = [
        RunEvent(
            id=1,
            run_id="run-qa-blocker",
            type="qa_issue",
            agent="qa",
            subagent="pricing",
            message="No evidence sources were collected for pricing.",
            payload={
                "phase": "collect",
                "issue": {
                    "id": "missing-pricing",
                    "severity": "blocker",
                    "detected_by": "coverage",
                    "target_agent": "collector",
                    "target_subagent": "pricing",
                    "field_path": "raw_sources[pricing]",
                    "problem": "No evidence sources were collected for pricing.",
                    "redo_scope": {
                        "kind": "collector",
                        "target_subagent": "pricing",
                        "rationale": "No sources collected for pricing.",
                    },
                    "self_found": False,
                },
            },
        )
    ]

    replay = build_decision_replay(detail, events)

    qa_event = next(event for event in replay.events if event.event_type == "qa.blocked")
    assert qa_event.payload["issue_id"] == "missing-pricing"
    assert qa_event.payload["severity"] == "blocker"
    assert qa_event.payload["phase"] == "collect"
    assert qa_event.payload["target_agent"] == "collector"
    assert qa_event.payload["redo_scope"]["kind"] == "collector"
    assert "No evidence sources" in qa_event.payload["problem"]


def test_decision_replay_includes_report_version_gap_fill_events() -> None:
    detail = RunDetail(
        id="run-gap-fill",
        topic="Decision replay gap fill",
        status="completed",
        execution_mode="demo",
        created_at="2026-05-31T00:00:00Z",
        updated_at="2026-05-31T00:01:00Z",
        plan=AnalysisPlan(
            topic="Decision replay gap fill",
            competitors=["A"],
            dimensions=["security"],
        ),
        raw_sources=[
            RawSource(
                id="source-1",
                competitor="A",
                dimension="security",
                source_type="webpage_verified",
                title="A security",
                url="https://example.com/security",
                snippet="A publishes security controls.",
                content_hash="hash-1",
                confidence=0.9,
            )
        ],
        metrics=RunMetrics(source_coverage_rate=1.0),
    )
    version = ReportVersionRecord(
        id="report-gap-fill-v2",
        workspace_id="workspace-1",
        project_id="project-1",
        run_id="run-gap-fill",
        parent_version_id="report-gap-fill-v1",
        version_number=2,
        topic_normalized="decision-replay-gap-fill",
        competitor_layer="L1",
        competitor_set_hash="competitor-set",
        report_md="# Report",
        evidence_ids=["evidence-gap-1"],
        quality_metadata={
            "rag_gap_fill": {
                "decision_events": [
                    {
                        "event_type": "rag.retrieved",
                        "agent": "rag_gap_fill",
                        "message": "Retrieved one candidate.",
                        "gap_ids": ["gap-security"],
                        "evidence_ids": ["evidence-gap-1"],
                        "payload": {
                            "gap_closure_rate": 1.0,
                            "retrieval_queries": ["A SOC 2 SSO trust center"],
                            "retrieval_contexts": [
                                {
                                    "gap_id": "gap-security",
                                    "query": "A SOC 2 SSO trust center",
                                    "chunk_ids": ["chunk-gap-1"],
                                    "dedupe_drop_count": 2,
                                }
                            ],
                            "chunk_ids": ["chunk-gap-1"],
                            "rerank_scores": {"chunk-gap-1": 0.92},
                            "retrieval_record_count": 1,
                            "updated_report_version_id": "report-gap-fill-v2",
                        },
                        "created_at": "2026-05-31T00:02:00Z",
                    },
                    {
                        "event_type": "report.ready",
                        "agent": "rag_gap_fill",
                        "message": "Draft report ready.",
                        "gap_ids": ["gap-security"],
                        "evidence_ids": ["evidence-gap-1"],
                        "payload": {
                            "source_report_version_id": "report-gap-fill-v1",
                            "updated_report_version_id": "report-gap-fill-v2",
                            "gap_fill_chain_closed": True,
                        },
                        "created_at": "2026-05-31T00:03:00Z",
                    },
                ],
                "release_gate_delta": {
                    "source_report_version_id": "report-gap-fill-v1",
                    "updated_report_version_id": "report-gap-fill-v2",
                    "source_status": "blocked",
                    "updated_status": "pass",
                    "release_gate_improved": True,
                    "release_gate_blocker_delta": 2,
                    "release_gate_warn_delta": 1,
                    "readiness_score_delta": 12,
                },
            }
        },
    )

    replay = build_decision_replay(detail, [], report_versions=[version])
    gap_events = [
        event for event in replay.events if event.id.startswith("run-gap-fill:report-version:")
    ]

    assert [event.event_type for event in gap_events] == ["rag.retrieved", "report.ready"]
    assert gap_events[0].evidence_ids == ["evidence-gap-1"]
    assert gap_events[0].payload["gap_ids"] == ["gap-security"]
    assert gap_events[0].payload["gap_closure_rate"] == 1.0
    assert gap_events[0].payload["retrieval_queries"] == ["A SOC 2 SSO trust center"]
    assert gap_events[0].payload["retrieval_contexts"][0]["chunk_ids"] == ["chunk-gap-1"]
    assert gap_events[0].payload["chunk_ids"] == ["chunk-gap-1"]
    assert gap_events[0].payload["rerank_scores"] == {"chunk-gap-1": 0.92}
    assert gap_events[0].payload["report_version_id"] == "report-gap-fill-v2"
    assert gap_events[1].payload["gap_ids"] == ["gap-security"]
    assert gap_events[1].payload["gap_fill_chain_closed"] is True
    assert gap_events[1].payload["release_gate_delta"]["release_gate_improved"] is True
    assert gap_events[1].payload["release_gate_blocker_delta"] == 2
    assert gap_events[1].payload["readiness_score_delta"] == 12
    assert replay.event_type_counts["rag.retrieved"] >= 1


def test_decision_replay_includes_manual_report_revision_version_event() -> None:
    detail = RunDetail(
        id="run-manual-revision",
        topic="Decision replay manual revision",
        status="completed",
        execution_mode="demo",
        created_at="2026-05-31T00:00:00Z",
        updated_at="2026-05-31T00:01:00Z",
        plan=AnalysisPlan(
            topic="Decision replay manual revision",
            competitors=["A"],
            dimensions=["pricing"],
        ),
        raw_sources=[],
        metrics=RunMetrics(),
    )
    version = ReportVersionRecord(
        id="report-manual-v2",
        workspace_id="workspace-1",
        project_id="project-1",
        run_id="run-manual-revision",
        parent_version_id="report-manual-v1",
        version_number=2,
        topic_normalized="decision-replay-manual-revision",
        competitor_layer="L1",
        competitor_set_hash="competitor-set",
        report_md="# Report\n\nManual correction.",
        claim_ids=["claim-1"],
        evidence_ids=["evidence-1"],
        quality_metadata={
            "manual_revision": {
                "edited_by": "analyst-1",
                "note": "Clarified recommendation before approval.",
                "source_report_version_id": "report-manual-v1",
            }
        },
    )

    replay = build_decision_replay(detail, [], report_versions=[version])
    version_event = next(
        event
        for event in replay.events
        if event.id == "run-manual-revision:report-version-ready:report-manual-v2"
    )

    assert version_event.event_type == "report.ready"
    assert version_event.agent == "report_version"
    assert version_event.evidence_ids == ["evidence-1"]
    assert version_event.claim_ids == ["claim-1"]
    assert version_event.payload["manual_revision"] is True
    assert version_event.payload["edited_by"] == "analyst-1"
    assert version_event.payload["manual_revision_note"] == (
        "Clarified recommendation before approval."
    )
    assert version_event.payload["source_report_version_id"] == "report-manual-v1"
    assert version_event.payload["parent_version_id"] == "report-manual-v1"


def test_decision_replay_includes_enterprise_audit_governance_events() -> None:
    detail = RunDetail(
        id="run-audit",
        workspace_id="workspace-1",
        project_id="project-1",
        topic="Decision replay audit",
        status="completed",
        execution_mode="demo",
        created_at="2026-05-31T00:00:00Z",
        updated_at="2026-05-31T00:01:00Z",
        plan=AnalysisPlan(
            topic="Decision replay audit",
            competitors=["A"],
            dimensions=["pricing"],
        ),
        raw_sources=[
            RawSource(
                id="source-1",
                competitor="A",
                dimension="pricing",
                source_type="webpage_verified",
                title="A pricing",
                url="https://example.com/pricing",
                snippet="A publishes pricing.",
                content_hash="hash-1",
                confidence=0.9,
            )
        ],
        metrics=RunMetrics(),
    )
    version = ReportVersionRecord(
        id="report-audit-v1",
        workspace_id="workspace-1",
        project_id="project-1",
        run_id="run-audit",
        version_number=1,
        topic_normalized="decision-replay-audit",
        competitor_layer="L1",
        competitor_set_hash="competitor-set",
        report_md="# Report",
        claim_ids=["claim-1"],
        evidence_ids=["evidence-1"],
    )
    audit_logs = [
        AuditLogRecord(
            id="audit-source-review",
            workspace_id="workspace-1",
            actor_type="system",
            actor_id="reviewer-1",
            action="source_registry.upserted",
            resource_type="source_registry",
            resource_id="source-registry-1",
            before={"policy_review_status": "pending"},
            after={
                "domain": "example.com",
                "source_type": "webpage_verified",
                "policy_review_status": "approved",
                "policy_review_reason": "Reviewer approved source use.",
                "last_seen_run_id": "run-audit",
            },
            created_at="2026-05-31T00:02:00Z",
        ),
        AuditLogRecord(
            id="audit-report-approval",
            workspace_id="workspace-1",
            actor_type="system",
            actor_id="approver-1",
            action="report_version.status_changed",
            resource_type="report_version",
            resource_id="report-audit-v1",
            before={"status": "in_review"},
            after={"status": "approved", "project_id": "project-1", "version_number": 1},
            created_at="2026-05-31T00:03:00Z",
        ),
        AuditLogRecord(
            id="audit-compliance-export",
            workspace_id="workspace-1",
            actor_type="system",
            actor_id="compliance",
            action="artifact.upserted",
            resource_type="artifact",
            resource_id="artifact-compliance",
            after={
                "run_id": "run-audit",
                "artifact_type": "report_export",
                "storage_backend": "local",
                "metadata": {"export_kind": "run_compliance_report"},
            },
            created_at="2026-05-31T00:04:00Z",
        ),
    ]

    replay = build_decision_replay(
        detail,
        [],
        audit_logs=audit_logs,
        report_versions=[version],
    )
    audit_events = {
        event.id: event for event in replay.events if event.id.startswith("run-audit:audit:")
    }

    assert set(audit_events) == {
        "run-audit:audit:audit-source-review",
        "run-audit:audit:audit-report-approval",
        "run-audit:audit:audit-compliance-export",
    }
    assert audit_events["run-audit:audit:audit-source-review"].event_type == "hitl.reviewed"
    assert audit_events["run-audit:audit:audit-source-review"].payload[
        "policy_review_status"
    ] == "approved"
    assert audit_events["run-audit:audit:audit-report-approval"].payload[
        "report_version_status"
    ] == "approved"
    assert audit_events["run-audit:audit:audit-compliance-export"].event_type == "report.ready"
    assert audit_events["run-audit:audit:audit-compliance-export"].payload[
        "export_kind"
    ] == "run_compliance_report"
    assert replay.event_type_counts["hitl.reviewed"] >= 2


def test_run_compliance_report_flags_policy_source_trace_and_pii() -> None:
    settings = Settings(
        demo_mode=True,
        ark_api_key=None,
        ark_model=None,
        ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
        llm_timeout_seconds=10,
        llm_temperature=0.2,
        enterprise_store_backend="memory",
        enterprise_database_url=None,
        compliance_blocked_domains=("blocked.example",),
        compliance_require_source_urls=True,
    )
    detail = RunDetail(
        id="run-1",
        topic="Compliance run",
        status="completed",
        execution_mode="demo",
        created_at="2026-05-31T00:00:00Z",
        updated_at="2026-05-31T00:00:00Z",
        plan=AnalysisPlan(topic="Compliance run", competitors=["A"], dimensions=["pricing"]),
        raw_sources=[
            RawSource(
                id="source-1",
                competitor="A",
                dimension="pricing",
                source_type="robots_blocked",
                title="Blocked",
                url="https://blocked.example/pricing",
                snippet="Contact alice@example.com for details.",
                content_hash="hash-1",
                confidence=0.7,
            )
        ],
        trace_spans=[
            TraceSpan(
                id="span-1",
                kind="llm",
                agent="writer",
                name="Write",
                status="ok",
                duration_ms=1,
            )
        ],
        metrics=RunMetrics(compliance_redaction_count=1),
        report_md="Report cites the blocked source.",
    )

    report = build_run_compliance_report(detail, settings=settings)

    assert report.status == "fail"
    assert report.blocker_count >= 3
    assert {finding.category for finding in report.findings} >= {
        "robots",
        "source",
        "trace",
        "pii",
    }


def test_langfuse_adapter_records_import_failure(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "langfuse", raising=False)
    real_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name == "langfuse":
            raise ImportError("missing langfuse")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)

    adapter = LangfuseAdapter(
        LangfuseConfig(public_key="pk-test", secret_key="sk-test-value", host=None)
    )

    assert adapter.configured is True
    assert adapter.enabled is False
    assert adapter.disabled_reason == "dependency_unavailable"
    assert adapter.error_count == 1
    assert "missing langfuse" in adapter.last_error
    assert adapter.health()["enabled"] is False


def test_langfuse_adapter_records_mirror_failure(monkeypatch) -> None:
    class FailingTrace:
        def span(self, **_kwargs) -> None:
            raise RuntimeError("mirror failed with Bearer abcdef1234567890")

    class FakeLangfuse:
        def __init__(self, **_kwargs) -> None:
            pass

        def trace(self, **_kwargs) -> FailingTrace:
            return FailingTrace()

    module = types.ModuleType("langfuse")
    module.Langfuse = FakeLangfuse
    monkeypatch.setitem(sys.modules, "langfuse", module)
    span = TraceSpan(
        id="span-1",
        kind="llm",
        agent="writer",
        name="Write",
        status="ok",
        duration_ms=1,
    )
    adapter = LangfuseAdapter(
        LangfuseConfig(public_key="pk-test", secret_key="sk-test-value", host=None)
    )

    mirrored = adapter.mirror_span("run-1", span)

    assert mirrored is False
    assert adapter.enabled is True
    assert adapter.error_count == 1
    assert adapter.last_error.startswith("mirror_failed:")
    assert "Bearer [redacted]" in adapter.last_error
    assert "abcdef1234567890" not in adapter.last_error
