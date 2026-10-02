from __future__ import annotations

import copy
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.export_agent_eval import MAX_ACTIONS, export_agent_eval, task_group

BACKEND = Path(__file__).resolve().parents[2]
SCRIPT = BACKEND / "scripts" / "export_agent_eval.py"
FIXTURES = BACKEND / "tests" / "fixtures" / "agent_eval"
FAKE_KEY = "sk-" + "syntheticsecret" * 3


def _span(**updates):
    return {
        "id": "span-1",
        "kind": "llm",
        "agent": "writer",
        "name": "write_report",
        "status": "ok",
        "duration_ms": 10,
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "input_preview": "比较功能",
        "output_preview": "缺少来源，待复核",
        "full_input": "DO_NOT_EXPORT_FULL_PROMPT",
        "full_output": "DO_NOT_EXPORT_FULL_OUTPUT",
        "input_tokens_estimate": 900,
        "output_tokens_estimate": 100,
        "cost_estimate_usd": 0.0002,
        "metadata": {},
        **updates,
    }


def _run(run_id="run-1", **updates):
    return {
        "id": run_id,
        "workspace_id": "ws-a",
        "project_id": "project-a",
        "execution_mode": "real",
        "topic": "任务管理比较 v2",
        "status": "completed",
        "plan": {
            "topic": "任务管理比较 v2",
            "target_product": {"name": "Task Product", "official_url": "https://example.com"},
            "competitors": ["Candidate A"],
            "dimensions": ["feature", "pricing"],
            "research_depth": "quick",
            "decision_brief": {"decision_question": "团队应该选哪个方案？"},
        },
        "trace_spans": [_span()],
        "qa_findings": [],
        "report_md": "DO_NOT_EXPORT_REPORT",
        **updates,
    }


def _journal(path, runs, *, columns=None):
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE runs (id TEXT, workspace_id TEXT, project_id TEXT, detail_json TEXT)"
        )
        for record in runs:
            overrides = (columns or {}).get(record["id"], {})
            conn.execute(
                "INSERT INTO runs VALUES (?, ?, ?, ?)",
                (
                    overrides.get("id", record["id"]),
                    overrides.get("workspace_id", record["workspace_id"]),
                    overrides.get("project_id", record["project_id"]),
                    json.dumps(record),
                ),
            )
    return path


def _feedback(path, records, *, columns=None):
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE memory_feedback "
            "(id TEXT, workspace_id TEXT, project_id TEXT, record_json TEXT)"
        )
        for record in records:
            overrides = (columns or {}).get(record["id"], {})
            conn.execute(
                "INSERT INTO memory_feedback VALUES (?, ?, ?, ?)",
                (
                    record["id"],
                    overrides.get("workspace_id", record["workspace_id"]),
                    overrides.get("project_id", record["project_id"]),
                    json.dumps(record),
                ),
            )
    return path


def _feedback_record(feedback_id, **updates):
    return {
        "id": feedback_id,
        "workspace_id": "ws-a",
        "project_id": "project-a",
        "user_id": "private-user@example.com",
        "run_id": "run-1",
        "feedback_type": "approval",
        "target_type": "report",
        "message": "已接受结果",
        "metadata": {"source": "human", "secret": FAKE_KEY},
        **updates,
    }


def _cli(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)],
        cwd=BACKEND.parent,
        env={**os.environ, "COMPETISCOPE_LOAD_ENV_FILES": "0", "PYTHONPATH": str(BACKEND)},
        capture_output=True,
        text=True,
        check=False,
    )


def test_only_explicit_raw_real_and_workspace_consistent_runs_are_exported(tmp_path):
    missing_mode = _run("missing-mode")
    missing_mode.pop("execution_mode")
    records = [
        _run(),
        missing_mode,
        *[_run(mode, execution_mode=mode) for mode in ("demo", "simulated", "unknown", "auto")],
        _run("other-ws", workspace_id="ws-b"),
        _run("forged-ws", workspace_id="ws-b"),
        _run("record-demo", metadata={"is_demo": True}),
        _run("record-simulated", simulated=True),
        _run("fixture", fixture_only=True, synthetic=True),
        _run("record-provider-demo", provider="Demo"),
    ]
    journal = _journal(
        tmp_path / "runs.db",
        records,
        columns={"forged-ws": {"workspace_id": "ws-a"}},
    )

    result = export_agent_eval(journal, "ws-a")

    assert [task["run_id"] for task in result["tasks"]] == ["run-1"]
    assert result["dataset_kind"] == "journal_explicit_real"


def test_demo_spans_are_filtered_and_unknown_failures_and_cancellations_survive(tmp_path):
    spans = [
        _span(id="unknown-failure", status="error", metadata={"token_usage_source": "estimate"}),
        _span(id="cancelled", status="cancelled"),
        _span(id="demo-provider", provider="DemoLLM"),
        _span(id="demo-metadata", metadata={"llm_provider": "demo"}),
        _span(id="simulated", metadata={"simulated": True}),
        _span(id="mode-demo", execution_mode="demo"),
    ]
    journal = _journal(tmp_path / "runs.db", [_run(trace_spans=spans)])

    task = export_agent_eval(journal, "ws-a")["tasks"][0]

    assert [action["id"] for action in task["actions"]] == ["unknown-failure", "cancelled"]
    assert task["actions_filtered"] == 4


def test_feedback_requires_matching_raw_workspace_project_and_explicit_run(tmp_path):
    journal = _journal(tmp_path / "runs.db", [_run()])
    feedback = _feedback(
        tmp_path / "feedback.db",
        [
            _feedback_record("linked"),
            _feedback_record("system", metadata={"source": "system", "truth_label": True}),
            _feedback_record("project-wide", run_id=None, target_type="project"),
            _feedback_record("other-run", run_id="run-2"),
            _feedback_record("other-ws", workspace_id="ws-b"),
            _feedback_record("forged-ws", workspace_id="ws-b"),
            _feedback_record("other-project", project_id="project-b"),
            _feedback_record("forged-project", project_id="project-b"),
        ],
        columns={
            "forged-ws": {"workspace_id": "ws-a"},
            "forged-project": {"project_id": "project-a"},
        },
    )

    task = export_agent_eval(journal, "ws-a", feedback_db=feedback)["tasks"][0]

    assert {item["id"] for item in task["feedback"]} == {"linked", "system"}
    assert task["reward"] == {"correctness": None, "source": None}
    assert "private-user" not in json.dumps(task)


def test_every_external_string_is_redacted_before_bounding_and_metadata_is_allowlisted(tmp_path):
    boundary_key = "x" * 585 + " " + FAKE_KEY + " ops@example.com"
    error = "api_key=shortsecret Bearer tiny-token +86 13800138000 ops@example.com"
    plan = _run()["plan"]
    plan.update(
        {
            "topic": boundary_key,
            "target_product": {
                "name": error,
                "official_url": "https://example.com?api_key=shortsecret&contact=ops@example.com",
            },
            "competitors": [error],
            "dimensions": [error],
            "decision_brief": {"decision_question": boundary_key},
        }
    )
    record = _run(
        "run-ops@example.com",
        topic=boundary_key,
        plan=plan,
        status=error,
        trace_spans=[
            _span(
                id=error,
                agent=error,
                name=boundary_key,
                provider=error,
                model=error,
                input_preview=boundary_key,
                output_preview=error,
                metadata={"error": error, "secret": FAKE_KEY, "nested": {"prompt": "PRIVATE"}},
            )
        ],
    )
    feedback = _feedback(
        tmp_path / "feedback.db",
        [
            _feedback_record(
                "feedback-ops@example.com",
                run_id=record["id"],
                message=boundary_key,
            )
        ],
    )
    journal = _journal(tmp_path / "runs.db", [record])

    result = export_agent_eval(journal, "ws-a", feedback_db=feedback)
    serialized = json.dumps(result, ensure_ascii=False)
    task = result["tasks"][0]

    for private in (
        FAKE_KEY,
        "sk-synthe",
        "ops@example.com",
        "shortsecret",
        "tiny-token",
        "13800138000",
        "PRIVATE",
        "DO_NOT_EXPORT",
    ):
        assert private not in serialized
    assert len(task["scope"]["topic"]) <= 600
    assert len(task["actions"][0]["input_summary"]) <= 600
    assert "[redacted:" in serialized


def test_provider_usage_cache_and_budget_charges_have_separate_bases(tmp_path):
    metadata = {
        "token_usage_source": "provider",
        "prompt_tokens": 90,
        "completion_tokens": 10,
        "total_tokens": 100,
        "prompt_cache_hit_tokens": 70,
        "prompt_cache_miss_tokens": 20,
        "llm_request_attempts": 2,
        "llm_tokens_charged": 1100,
        "llm_cost_charged_usd": 0.002,
    }
    checkpoint = {"calls": 3, "repairs": 0, "tokens_charged": 2000, "cost_charged_usd": 0.003}
    journal = _journal(
        tmp_path / "runs.db",
        [
            _run(
                trace_spans=[_span(metadata=metadata), _span(id="missing-usage", status="error")],
                llm_budget_checkpoint=checkpoint,
            )
        ],
    )

    task = export_agent_eval(journal, "ws-a")["tasks"][0]
    real, missing = task["actions"]

    assert real["provider_usage"] == {
        key: metadata[key]
        for key in (
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "prompt_cache_hit_tokens",
            "prompt_cache_miss_tokens",
        )
    }
    assert real["usage_source"] == "provider"
    assert real["provider_usage_scope"] == "last_attempt_only"
    assert real["budget_charge"] == {
        "tokens": 1100,
        "cost_usd": 0.002,
        "basis": "conservative_budget",
    }
    assert real["cost_estimate_usd"] == 0.0002
    assert missing["usage_source"] == "estimate"
    assert all(value is None for value in missing["provider_usage"].values())
    assert missing["token_estimates"]["input_tokens_estimate"] == 900
    assert missing["budget_charge"]["tokens"] is None
    assert task["budget_checkpoint"]["tokens_charged"] == 2000
    assert task["budget_checkpoint"]["cost_charged_usd"] == 0.003
    assert "total_cost_usd" not in task


def test_estimated_or_invalid_numeric_fields_never_become_provider_usage(tmp_path):
    spans = [
        _span(metadata={"token_usage_source": "estimate", "prompt_tokens": 999}),
        _span(
            metadata={
                "token_usage_source": "provider",
                "prompt_tokens": True,
                "total_tokens": "100",
                "completion_tokens": -1,
                "llm_cost_charged_usd": float("nan"),
            }
        ),
    ]
    journal = _journal(tmp_path / "runs.db", [_run(trace_spans=spans)])

    actions = export_agent_eval(journal, "ws-a")["tasks"][0]["actions"]

    assert all(action["usage_source"] == "estimate" for action in actions)
    assert all(value is None for action in actions for value in action["provider_usage"].values())
    assert actions[1]["budget_charge"]["cost_usd"] is None


def test_oversized_integer_usage_is_rejected_without_crashing(tmp_path):
    journal = _journal(
        tmp_path / "runs.db",
        [
            _run(
                trace_spans=[
                    _span(
                        metadata={
                            "token_usage_source": "provider",
                            "prompt_tokens": 10**400,
                        }
                    )
                ]
            )
        ],
    )

    action = export_agent_eval(journal, "ws-a")["tasks"][0]["actions"][0]

    assert action["provider_usage"]["prompt_tokens"] is None


@pytest.mark.parametrize(
    "error",
    [
        '{"api_key": "shortsecret"}',
        "https://example.com?api_key%253Dshortsecret",
        "Authorization: Bearer shortsecret",
        "Authorization=Basic shortsecret",
    ],
)
def test_quoted_or_escaped_short_credentials_are_redacted(tmp_path, error):
    journal = _journal(tmp_path / "runs.db", [_run(trace_spans=[_span(output_preview=error)])])

    result = export_agent_eval(journal, "ws-a")

    assert "shortsecret" not in json.dumps(result)


def test_explicit_simulation_flags_with_alternate_names_are_filtered(tmp_path):
    journal = _journal(
        tmp_path / "runs.db",
        [
            _run(
                trace_spans=[
                    _span(metadata={"survey_simulated": True}),
                    _span(metadata={"demo_mode": "on"}),
                ]
            )
        ],
    )

    task = export_agent_eval(journal, "ws-a")["tasks"][0]

    assert task["actions"] == []
    assert task["actions_filtered"] == 2


def test_whitespace_in_explicit_demo_provider_and_flags_is_still_filtered(tmp_path):
    journal = _journal(
        tmp_path / "runs.db",
        [_run(trace_spans=[_span(provider=" DemoLLM "), _span(metadata={"is_demo": " TRUE "})])],
    )

    task = export_agent_eval(journal, "ws-a")["tasks"][0]

    assert task["actions"] == []


def test_completed_qa_pass_and_explicit_feedback_truth_do_not_infer_rewards(tmp_path):
    journal = _journal(
        tmp_path / "runs.db",
        [
            _run(
                metrics={"qa_pass": True},
                enterprise_projection={"approval_status": "approved"},
            )
        ],
    )
    feedback = _feedback(
        tmp_path / "feedback.db",
        [
            _feedback_record(
                "accepted",
                metadata={"source": "human", "truth_label": True},
            )
        ],
    )

    task = export_agent_eval(journal, "ws-a", feedback_db=feedback)["tasks"][0]

    assert task["reward"] == {"correctness": None, "source": None}
    assert task["result"]["status"] == "completed"


def test_same_task_group_survives_reruns_depth_and_discovery_changes(tmp_path):
    first = _run()
    rerun = copy.deepcopy(first)
    rerun.update({"id": "rerun-2027", "created_at": "2027-01-01", "status": "failed"})
    rerun["plan"]["research_depth"] = "deep"
    rerun["plan"]["competitors"] = ["Different Discovery"]
    rerun["plan"]["dimensions"] = ["security"]
    journal = _journal(tmp_path / "runs.db", [first, rerun])

    tasks = export_agent_eval(journal, "ws-a")["tasks"]

    assert tasks[0]["task_group_id"] == tasks[1]["task_group_id"]
    assert tasks[0]["split"] == tasks[1]["split"]
    assert task_group(first, "ws-a") == task_group(rerun, "ws-a")
    changed_version = copy.deepcopy(first)
    changed_version["plan"]["topic"] = changed_version["topic"] = "任务管理比较 v3"
    assert task_group(first, "ws-a") != task_group(changed_version, "ws-a")
    generic = _run()
    generic["plan"]["target_product"] = None
    changed_scope = copy.deepcopy(generic)
    changed_scope["plan"]["decision_brief"]["decision_question"] = "如何降低迁移成本？"
    assert task_group(generic, "ws-a") != task_group(changed_scope, "ws-a")
    assert task_group(first, "ws-a") != task_group(first, "ws-b")


def test_action_limit_has_exact_omission_count(tmp_path):
    spans = [_span(id=f"span-{index}") for index in range(MAX_ACTIONS + 3)]
    journal = _journal(tmp_path / "runs.db", [_run(trace_spans=spans)])

    task = export_agent_eval(journal, "ws-a")["tasks"][0]

    assert len(task["actions"]) == MAX_ACTIONS
    assert task["actions_omitted"] == 3


def test_fixtures_cover_each_split_and_are_clearly_synthetic_without_truth():
    fixture = json.loads((FIXTURES / "split_examples.json").read_text())

    assert fixture["dataset_kind"] == "synthetic_fixture"
    assert {task["split"] for task in fixture["tasks"]} == {"train", "validation", "holdout"}
    groups = {}
    for task in fixture["tasks"]:
        assert task["synthetic"] is True and task["fixture_only"] is True
        assert task["execution_mode"] == "synthetic"
        assert task["reward"] == {"correctness": None, "source": None}
        raw = {"topic": task["scope"]["topic"], "plan": task["scope"]}
        assert task_group(raw, fixture["workspace_id"]) == (task["task_group_id"], task["split"])
        groups.setdefault(task["task_group_id"], set()).add(task["split"])
    assert all(len(splits) == 1 for splits in groups.values())
    assert len(fixture["tasks"]) > len(groups)  # At least one rerun example.


def test_cli_reads_sources_without_mutating_and_writes_bounded_valid_json(tmp_path):
    journal = _journal(tmp_path / "runs.db", [_run()])
    feedback = _feedback(tmp_path / "feedback.db", [_feedback_record("linked")])
    original = {path: hashlib.sha256(path.read_bytes()).digest() for path in (journal, feedback)}
    output = tmp_path / "export.json"

    completed = _cli(
        "--journal", journal, "--workspace", "ws-a", "--feedback-db", feedback, "--output", output
    )

    assert completed.returncode == 0, completed.stderr
    assert len(json.loads(output.read_text())["tasks"]) == 1
    assert all(
        hashlib.sha256(path.read_bytes()).digest() == digest for path, digest in original.items()
    )
    assert FAKE_KEY not in completed.stdout + completed.stderr + output.read_text()
    assert "private-user" not in output.read_text()


@pytest.mark.parametrize("source", ["journal", "feedback-db"])
def test_cli_missing_source_fails_without_creating_database(tmp_path, source):
    journal = _journal(tmp_path / "runs.db", [_run()])
    missing = tmp_path / "missing.db"
    output = tmp_path / "export.json"
    args = [
        "--journal",
        missing if source == "journal" else journal,
        "--workspace",
        "ws-a",
        "--output",
        output,
    ]
    if source == "feedback-db":
        args += ["--feedback-db", missing]

    completed = _cli(*args)

    assert completed.returncode != 0
    assert "does not exist" in completed.stderr
    assert not missing.exists() and not output.exists()


@pytest.mark.parametrize("damage", ["sqlite", "schema", "json"])
def test_cli_damaged_source_fails_without_echoing_source_records(tmp_path, damage):
    journal = tmp_path / "runs.db"
    if damage == "sqlite":
        journal.write_text("not SQLite " + FAKE_KEY)
    elif damage == "schema":
        with sqlite3.connect(journal) as conn:
            conn.execute("CREATE TABLE unrelated (value TEXT)")
    else:
        _journal(journal, [_run()])
        with sqlite3.connect(journal) as conn:
            conn.execute("UPDATE runs SET detail_json = ?", ('{"invalid": ' + FAKE_KEY,))
    output = tmp_path / "export.json"

    completed = _cli("--journal", journal, "--workspace", "ws-a", "--output", output)

    assert completed.returncode != 0
    assert "export failed" in completed.stderr.lower()
    assert FAKE_KEY not in completed.stdout + completed.stderr
    assert not output.exists()


def test_cli_refuses_to_overwrite_source_database(tmp_path):
    journal = _journal(tmp_path / "runs.db", [_run()])
    original = journal.read_bytes()

    completed = _cli("--journal", journal, "--workspace", "ws-a", "--output", journal)

    assert completed.returncode != 0
    assert journal.read_bytes() == original
