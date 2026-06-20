import json
from pathlib import Path
from typing import get_args

from app.events import RunEvent, RunEventType

EXPECTED_EVENT_TYPES = {
    "run_created",
    "node_started",
    "node_completed",
    "interrupt",
    "qa_issue",
    "report_updated",
    "revision_recorded",
    "run_completed",
    "run_failed",
    "agent.started",
    "agent.finished",
    "tool.called",
    "rag.retrieved",
    "self_consistency.sampled",
    "memory.recalled",
    "memory.feedback_captured",
    "hitl.reviewed",
    "claim.validated",
    "qa.blocked",
    "redo.routed",
    "benchmark.scored",
    "report.ready",
    "runtime.command",
    "writer_preflight",
    "writer_segment_preflight",
    "writer_segment_validated",
    "writer_assembly_completed",
    "writer_assemble_repair_completed",
    "writer_quality_preflight",
    "writer_quality_preflight_repair",
    "writer_structured_repair_selected",
    "writer_structured_section_started",
    "writer_structured_section_completed",
    "writer_structured_section_failed",
    "writer_structured_report_validated",
    "writer_publication_contract_validated",
    "writer_publication_contract_repair_selected",
    "writer_publication_contract_repaired",
    "writer_recommendation_delta_checked",
    "writer_structured_repair_failed_preserved_previous",
    "writer_schema_first_failed_closed",
    "writer_markdown_fallback_used",
    "writer_unified_quality_result_recorded",
}


def test_backend_sse_event_type_contract() -> None:
    assert set(get_args(RunEventType)) == EXPECTED_EVENT_TYPES


def test_frontend_subscribes_to_backend_sse_event_types() -> None:
    base_dir = Path(__file__).resolve().parents[3]
    client_source = (base_dir / "frontend" / "src" / "api" / "client.ts").read_text(
        encoding="utf-8"
    )
    sse_types_source = (base_dir / "frontend" / "src" / "api" / "sse_types.ts").read_text(
        encoding="utf-8"
    )

    for event_type in EXPECTED_EVENT_TYPES:
        assert f'"{event_type}"' in client_source
        assert f'"{event_type}"' in sse_types_source


def test_generated_openapi_types_include_backend_sse_event_types() -> None:
    base_dir = Path(__file__).resolve().parents[3]
    openapi_types_source = (base_dir / "frontend" / "src" / "api" / "openapi.ts").read_text(
        encoding="utf-8"
    )

    for event_type in EXPECTED_EVENT_TYPES:
        assert f'"{event_type}"' in openapi_types_source


def test_openapi_run_event_enum_includes_backend_sse_event_types() -> None:
    base_dir = Path(__file__).resolve().parents[3]
    openapi = json.loads((base_dir / "frontend" / "openapi.json").read_text(encoding="utf-8"))

    event_enum = openapi["components"]["schemas"]["RunEvent"]["properties"]["type"]["enum"]

    assert set(event_enum) == EXPECTED_EVENT_TYPES


def test_run_event_to_sse_round_trips_payload() -> None:
    event = RunEvent(
        id=1,
        run_id="run-1",
        type="qa_issue",
        agent="qa",
        message="QA produced an issue.",
        payload={"issue": {"id": "missing-pricing"}},
    )

    sse = event.to_sse()
    data = json.loads(sse["data"])

    assert sse["id"] == "1"
    assert sse["event"] == "qa_issue"
    assert data["payload"]["issue"]["id"] == "missing-pricing"
