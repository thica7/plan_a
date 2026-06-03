from app.events import RunEvent
from packages.compliance import CompliancePolicy, redact_text
from packages.compliance.report import build_run_compliance_report
from packages.config import Settings
from packages.observability import (
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
from packages.schema.enterprise import ReportVersionRecord
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
            type="self_consistency.sampled",
            agent="quality",
            message="Consistency sampled",
            payload={
                "self_consistency_score": 88,
                "claim_ids": ["claim-1"],
                "evidence_ids": ["source-1"],
            },
        ),
        RunEvent(
            id=5,
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
        "self_consistency.sampled",
        "claim.validated",
        "benchmark.scored",
        "report.ready",
    }
    assert replay.replay_coverage_score >= 85
    assert replay.event_type_counts["memory.recalled"] >= 1
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
                        "evidence_ids": ["evidence-gap-1"],
                        "payload": {
                            "gap_closure_rate": 1.0,
                            "retrieval_record_count": 1,
                            "updated_report_version_id": "report-gap-fill-v2",
                        },
                        "created_at": "2026-05-31T00:02:00Z",
                    },
                    {
                        "event_type": "report.ready",
                        "agent": "rag_gap_fill",
                        "message": "Draft report ready.",
                        "evidence_ids": ["evidence-gap-1"],
                        "payload": {
                            "source_report_version_id": "report-gap-fill-v1",
                            "updated_report_version_id": "report-gap-fill-v2",
                            "gap_fill_chain_closed": True,
                        },
                        "created_at": "2026-05-31T00:03:00Z",
                    },
                ]
            }
        },
    )

    replay = build_decision_replay(detail, [], report_versions=[version])
    gap_events = [
        event for event in replay.events if event.id.startswith("run-gap-fill:report-version:")
    ]

    assert [event.event_type for event in gap_events] == ["rag.retrieved", "report.ready"]
    assert gap_events[0].evidence_ids == ["evidence-gap-1"]
    assert gap_events[0].payload["gap_closure_rate"] == 1.0
    assert gap_events[0].payload["report_version_id"] == "report-gap-fill-v2"
    assert gap_events[1].payload["gap_fill_chain_closed"] is True
    assert replay.event_type_counts["rag.retrieved"] >= 1


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
