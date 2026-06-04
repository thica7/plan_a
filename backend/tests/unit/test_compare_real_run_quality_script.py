from __future__ import annotations

import importlib.util
import json
import sqlite3
from argparse import Namespace
from pathlib import Path
from types import ModuleType


def _load_script() -> ModuleType:
    script_path = (
        Path(__file__).resolve().parents[2] / "scripts" / "compare_real_run_quality.py"
    )
    spec = importlib.util.spec_from_file_location("compare_real_run_quality", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_summarize_run_detail_payload_extracts_quality_shape() -> None:
    script = _load_script()
    summary = script.summarize_run_detail_payload(
        {
            "id": "run-1",
            "status": "completed",
            "current_node": "writer",
            "execution_mode": "real",
            "report_md": "# Report\n\nDecision-grade report body.",
            "raw_sources": [
                {
                    "id": "source-1",
                    "competitor": "Cursor",
                    "dimension": "pricing",
                    "source_type": "webpage_verified",
                    "title": "Cursor pricing",
                    "url": "https://cursor.com/pricing",
                }
            ],
            "knowledge_claims": [{"id": "claim-1"}],
            "qa_findings": [],
            "agent_messages": [
                {
                    "from_agent": "writer",
                    "to_agent": "qa",
                    "message_type": "report_ready",
                    "status": "consumed",
                    "payload": {"writer_mode": "real LLM call"},
                }
            ],
            "tool_call_messages": [{"id": "tool-1"}],
            "trace_spans": [{"id": "span-1"}],
            "metrics": {"llm_calls": 2},
        }
    )

    assert summary["run_id"] == "run-1"
    assert summary["raw_sources"] == 1
    assert summary["claims"] == 1
    assert summary["agent_messages"] == 1
    assert summary["tool_call_messages"] == 1
    assert summary["last_agent_messages"][0]["detail"] == "writer_mode=real LLM call"
    assert summary["trace_spans"] == 1
    assert summary["source_types"] == {"webpage_verified": 1}
    assert summary["by_competitor"] == {"Cursor": 1}
    assert summary["fallback_report"] is False


def test_agent_message_diagnostics_includes_writer_error_with_mode() -> None:
    script = _load_script()
    summary = script.summarize_run_detail_payload(
        {
            "id": "run-writer-error",
            "status": "completed_with_blockers",
            "execution_mode": "real",
            "report_md": "# Report",
            "raw_sources": [],
            "agent_messages": [
                {
                    "from_agent": "writer",
                    "to_agent": "qa",
                    "message_type": "report_ready",
                    "status": "consumed",
                    "payload": {
                        "writer_mode": "deterministic fallback after writer error",
                        "error": "writer LLM exceeded 30s",
                    },
                }
            ],
        }
    )

    assert summary["last_agent_messages"][0]["detail"] == (
        "writer_mode=deterministic fallback after writer error; "
        "error=writer LLM exceeded 30s"
    )


def test_old_run_summary_reads_sqlite_journal(tmp_path: Path) -> None:
    script = _load_script()
    db_path = tmp_path / "run_journal.db"
    payload = {
        "id": "old-run",
        "status": "completed",
        "execution_mode": "demo",
        "report_md": "Old report",
        "raw_sources": [],
    }
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("create table runs (id text primary key, detail_json text not null)")
        conn.execute(
            "insert into runs (id, detail_json) values (?, ?)",
            ("old-run", json.dumps(payload)),
        )
        conn.commit()
    finally:
        conn.close()

    summary = script.old_run_summary(db_path, "old-run")

    assert summary["run_id"] == "old-run"
    assert summary["status"] == "completed"
    assert summary["report_chars"] == len("Old report")


def test_build_summary_delta_marks_baseline_and_fallback_regression() -> None:
    script = _load_script()

    delta = script.build_summary_delta(
        {
            "report_chars": 100,
            "raw_sources": 2,
            "claims": 1,
            "qa_findings": 0,
            "trace_spans": 4,
            "fallback_report": False,
        },
        {
            "report_chars": 160,
            "raw_sources": 5,
            "claims": 3,
            "qa_findings": 1,
            "trace_spans": 9,
            "fallback_report": True,
        },
    )

    assert delta["baseline_available"] is True
    assert delta["report_chars"] == 60
    assert delta["raw_sources"] == 3
    assert delta["fallback_report_regressed"] is True


def test_build_summary_delta_tolerates_missing_baseline() -> None:
    script = _load_script()

    assert script.build_summary_delta({"error": "missing"}, {"report_chars": 10}) == {
        "baseline_available": False
    }


def test_render_compare_markdown_summarizes_quality_gate() -> None:
    script = _load_script()

    markdown = script.render_compare_markdown(
        {
            "old": {"run_id": "old-run"},
            "current": {
                "run_id": "current-run",
                "status": "failed",
                "current_node": "writer",
                "execution_mode": "real",
                "raw_sources": 5,
                "enterprise_evidence": 5,
                "claims": 3,
                "enterprise_claims": 3,
                "trace_spans": 12,
                "report_chars": 2400,
                "agent_messages": 2,
                "tool_call_messages": 4,
                "qa_issue_diagnostics": [
                    {
                        "id": "schema-missing-pricing-a",
                        "severity": "blocker",
                        "target_agent": "analyst",
                        "target_subagent": "pricing",
                        "target_competitor": "A",
                        "problem": "A has sources for pricing, but no structured claims.",
                    }
                ],
                "last_agent_messages": [
                    {
                        "from_agent": "writer",
                        "to_agent": "qa",
                        "message_type": "report_ready",
                        "status": "consumed",
                        "detail": "preserved previous report after writer error",
                    }
                ],
            },
            "delta": {
                "baseline_available": True,
                "report_chars": 1200,
                "raw_sources": 3,
                "claims": 2,
                "qa_findings": -1,
                "trace_spans": 8,
                "fallback_report_regressed": False,
            },
            "quality": {
                "target_score": 86,
                "baseline_score": 70,
                "delta_score": 16,
                "verdict": "pass",
                "regression_gate_status": "pass",
                "metrics": [
                    {
                        "name": "report_length_score",
                        "target_value": 1.0,
                        "baseline_value": 0.4,
                        "delta": 0.6,
                        "status": "improved",
                    }
                ],
                "recommendations": ["Keep source snapshots attached to gap-filled evidence."],
            },
        }
    )

    assert "# Real Run Quality Comparison" in markdown
    assert "- Current run: current-run" in markdown
    assert "- Current status: failed" in markdown
    assert "| Agent messages | 2 |" in markdown
    assert "preserved previous report after writer error" in markdown
    assert "| Delta score | +16 |" in markdown
    assert "| Raw sources | +3 |" in markdown
    assert "| report_length_score | 1 | 0.4 | +0.6 | improved |" in markdown
    assert "## QA Issue Diagnostics" in markdown
    assert "schema-missing-pricing-a" in markdown
    assert "Keep source snapshots attached" in markdown


def test_parse_args_disables_hitl_for_automated_comparison_by_default() -> None:
    script = _load_script()

    default_args = script.parse_args([])
    hitl_args = script.parse_args(["--hitl-enabled"])
    warn_redo_args = script.parse_args(["--auto-redo-warn-enabled"])

    assert default_args.hitl_enabled is False
    assert default_args.auto_redo_warn_enabled is False
    assert hitl_args.hitl_enabled is True
    assert warn_redo_args.auto_redo_warn_enabled is True


def test_pipeline_completion_gate_marks_incomplete_run_as_failed() -> None:
    script = _load_script()

    quality = script.apply_pipeline_completion_gate(
        {
            "verdict": "pass",
            "regression_gate_status": "pass",
            "regression_gate_passed": True,
            "regression_gate_reasons": ["existing quality reason"],
            "recommendations": ["existing recommendation"],
        },
        {
            "status": "interrupted",
            "current_node": "qa_hitl",
            "report_chars": 0,
            "pipeline_timed_out": True,
            "timeout_seconds": 45,
        },
    )
    markdown = script.render_compare_markdown(
        {
            "old": {"run_id": "old-run"},
            "current": {
                "run_id": "current-run",
                "status": "interrupted",
                "current_node": "qa_hitl",
                "execution_mode": "real",
                "report_chars": 0,
                "pipeline_timed_out": True,
                "timeout_seconds": 45,
            },
            "delta": {"baseline_available": False},
            "quality": quality,
            "comparison_error": "pipeline timeout after 45 seconds",
        }
    )

    assert quality["verdict"] == "fail"
    assert quality["regression_gate_status"] == "fail"
    assert quality["regression_gate_passed"] is False
    assert quality["pipeline_incomplete"] is True
    assert "current run pipeline timed out after 45 seconds" in quality[
        "regression_gate_reasons"
    ]
    assert (
        "current run did not complete: status=interrupted, current_node=qa_hitl"
        in quality["regression_gate_reasons"]
    )
    assert "current run did not produce report_md" in quality["regression_gate_reasons"]
    assert "- Pipeline incomplete: yes" in markdown
    assert "- Comparison error: pipeline timeout after 45 seconds" in markdown


def test_pipeline_completion_gate_accepts_terminal_completed_with_blockers() -> None:
    script = _load_script()

    quality = script.apply_pipeline_completion_gate(
        {
            "verdict": "fail",
            "regression_gate_status": "fail",
            "regression_gate_passed": False,
            "regression_gate_reasons": ["source quality regressed"],
            "recommendations": ["Improve source verification."],
        },
        {
            "status": "completed_with_blockers",
            "current_node": None,
            "report_chars": 2400,
        },
    )

    assert quality["pipeline_incomplete"] is False
    assert quality["regression_gate_reasons"] == ["source quality regressed"]


def test_timeout_payload_renders_failed_comparison_card(tmp_path: Path) -> None:
    script = _load_script()
    missing_db = tmp_path / "missing.db"

    payload = script.build_timeout_payload(
        Namespace(
            old_db=missing_db,
            old_run_id="old-run",
            execution_mode="real",
            timeout_seconds=12,
        )
    )
    markdown = script.render_compare_markdown(payload)

    assert payload["current"]["status"] == "timeout"
    assert payload["quality"]["regression_gate_status"] == "fail"
    assert "- Comparison error: timeout after 12 seconds" in markdown
    assert "real run comparison timed out after 12 seconds" in markdown
