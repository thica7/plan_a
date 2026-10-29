"""Executable acceptance contract for the isolated local concurrency verifier."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "backend/scripts/verify_local_concurrency.py"


def invoke(tmp_path, *arguments):
    env = {**os.environ, "COMPETISCOPE_LOAD_ENV_FILES": "0", "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        cwd=tmp_path, env=env, text=True, capture_output=True, timeout=180,
    )


def test_preview_is_default_and_does_not_touch_cwd_or_output(tmp_path):
    (tmp_path / ".env").write_text("THIS IS NOT VALID ENVIRONMENT CONFIGURATION\n")
    output = tmp_path / "must-not-exist.json"
    before = set(tmp_path.iterdir())
    result = invoke(tmp_path, "--output", str(output))
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value["mode"] == "preview" and value["requests"] == 64
    assert value["seed"] == 20261028
    assert value["execution_control_enabled"] is True
    assert value["external_services"] is False
    assert set(tmp_path.iterdir()) == before


@pytest.mark.parametrize("count", ["15", "257", "not-an-integer"])
def test_cli_rejects_unbounded_request_counts(tmp_path, count):
    result = invoke(tmp_path, "--requests", count)
    assert result.returncode == 2
    assert "--requests" in result.stderr
    assert list(tmp_path.iterdir()) == []


def test_cli_records_failure_and_returns_nonzero(tmp_path, monkeypatch, capsys):
    from scripts import local_concurrency_harness, verify_local_concurrency

    output = tmp_path / "failure.json"
    monkeypatch.setattr(local_concurrency_harness, "execute", lambda count: {
        "passed": False, "error": "synthetic acceptance failure",
    })
    assert verify_local_concurrency.main(["--execute", "--output", str(output)]) == 1
    assert json.loads(output.read_text())["passed"] is False
    assert json.loads(capsys.readouterr().out)["passed"] is False


def test_report_percentiles_interpolate_small_success_samples():
    from scripts.local_concurrency_harness import percentiles

    assert percentiles([100., 0.]) == {"p50": 50., "p95": 95.}


def test_execute_exercises_real_entries_and_records_cleanup(tmp_path):
    output = tmp_path / "acceptance.json"
    result = invoke(tmp_path, "--execute", "--requests", "16", "--output", str(output))
    assert result.returncode == 0, result.stderr + result.stdout
    value = json.loads(output.read_text())
    assert value["passed"] is True
    burst = value["burst"]
    assert burst["requests"] == burst["accepted"] + burst["rejected"] == 16
    assert burst["accepted"] > 0 and burst["rejected"] > 0 and burst["expired"] > 0
    assert burst["running_peak"] == burst["model_peak"] == 2
    assert burst["workspace_running_peak"] == 1
    assert burst["http_429"] == burst["retry_after_valid"] == burst["rejected"]
    assert burst["generation_calls"] and burst["rewrite_calls"] and burst["native_search_calls"]
    assert burst["completed"] + burst["expired"] == burst["accepted"]
    assert burst["fault_injection"]["holder_release_delay_seconds"] > .5
    assert burst["latency_samples"]["end_to_end"] == burst["accepted"]
    assert burst["latency_samples"]["completed_end_to_end"] == burst["completed"]
    assert burst["final"] == {"queued": 0, "running": 0, "model_active": 0}
    assert burst["process_exitcodes"] == [0, 0] and burst["pending_tasks"] == 0
    assert all(key in burst["latency_ms"] for key in ("create", "queue", "end_to_end"))
    assert value["cross_instance"]["get_and_list"] is True
    assert value["cross_instance"]["durable_sse_slow_cursor"] is True
    assert value["singleflight"]["scope"] == "single-process"
    assert value["singleflight"]["fetch_provider_calls"] == 1
    assert value["singleflight"]["embedding_provider_calls"] == 1
    recovery = value["recovery"]
    assert recovery["real_langgraph_checkpoint"] is True
    assert recovery["old_token_rejected"] is True
    assert recovery["generation_after"] > recovery["generation_before"]
    assert recovery["planner_completions_before"] == recovery["planner_completions_after"] == 1
    assert recovery["terminal_status"] in {"completed", "completed_with_blockers"}
    assert recovery["content_quality_asserted"] is False
    assert recovery["old_token_rejected_while_new_owner_active"] is True
    assert recovery["pending_tasks"] == value["singleflight"]["pending_tasks"] == 0
    assert value["regressions"]["passed"] is True
    assert value["cleanup"]["temporary_directory_removed"] is True
    assert value["cleanup"]["all_children_joined"] is True
    assert "Redis service/Lua/TTL/disconnect" in value["not_verified"]
