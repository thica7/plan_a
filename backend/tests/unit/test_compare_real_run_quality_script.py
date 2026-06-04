from __future__ import annotations

import importlib.util
import json
import sqlite3
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
            "trace_spans": [{"id": "span-1"}],
            "metrics": {"llm_calls": 2},
        }
    )

    assert summary["run_id"] == "run-1"
    assert summary["raw_sources"] == 1
    assert summary["claims"] == 1
    assert summary["trace_spans"] == 1
    assert summary["source_types"] == {"webpage_verified": 1}
    assert summary["by_competitor"] == {"Cursor": 1}
    assert summary["fallback_report"] is False


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
