"""Safety contract and a repeatable real socket/process/database acceptance run."""

import importlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def acceptance_module():
    assert importlib.util.find_spec("scripts.verify_task_center") is not None, (
        "the safe acceptance CLI must exist"
    )
    return importlib.import_module("scripts.verify_task_center")


def test_preview_has_no_settings_database_process_or_temporary_side_effects(monkeypatch, capsys):
    module = acceptance_module()
    import tempfile

    import psycopg

    import packages.config

    def forbidden(*args, **kwargs):
        pytest.fail("preview performed an execution side effect")

    monkeypatch.setattr(packages.config, "get_settings", forbidden)
    monkeypatch.setattr(psycopg, "connect", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(tempfile, "mkdtemp", forbidden)
    monkeypatch.setattr(os, "getenv", forbidden)
    assert module.main([]) == 0
    assert "preview" in capsys.readouterr().out.lower()


@pytest.mark.parametrize(
    "arguments",
    [
        ["--port", "8000"],
        ["--database-url", "postgresql://localhost/postgres"],
        ["--data-dir", "/tmp"],
        ["--output-dir", "/tmp"],
        ["--child", "api"],
    ],
)
def test_public_cli_rejects_external_targets(arguments):
    with pytest.raises(SystemExit) as caught:
        acceptance_module().main(arguments)
    assert caught.value.code == 2


def test_preview_direct_from_foreign_working_directory(tmp_path):
    acceptance_module()
    filename = Path(__file__).resolve().parents[2] / "scripts" / "verify_task_center.py"
    result = subprocess.run(
        [sys.executable, str(filename)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"},
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "preview" in result.stdout.lower()
    assert list(tmp_path.iterdir()) == []


def test_internal_child_rejects_unowned_directory_without_reading_settings(tmp_path, monkeypatch):
    module = importlib.import_module("scripts.task_center_acceptance")
    import packages.config

    monkeypatch.setattr(packages.config, "get_settings", lambda: pytest.fail("read settings"))
    filename = tmp_path / "acceptance.json"
    filename.write_text(json.dumps({"root": str(tmp_path), "token": "forged"}))
    with pytest.raises(RuntimeError, match="unowned"):
        module.child_config(str(filename), "forged")


@pytest.mark.parametrize(
    "dsn",
    [
        "host=localhost port=5432 dbname=postgres user=task_center_app",
        "host=/private/tmp/other/socket dbname=postgres user=task_center_app",
        "host=/private/tmp/task-center-pg-test/socket dbname=other user=task_center_app",
        "host=/private/tmp/task-center-pg-test/socket dbname=postgres user=task_center_owner",
        "host=/private/tmp/task-center-pg-test/socket dbname=postgres "
        "user=task_center_app hostaddr=127.0.0.1",
    ],
)
def test_internal_child_rejects_foreign_database_targets(dsn):
    module = importlib.import_module("scripts.task_center_acceptance")
    assert hasattr(module, "validate_child_dsn"), "child target validation must exist"
    with pytest.raises(RuntimeError, match="database"):
        module.validate_child_dsn(Path("/private/tmp/task-center-pg-test"), dsn)


def test_startup_failure_is_nonzero_evidence_and_still_cleans_up(tmp_path, monkeypatch):
    module = importlib.import_module("scripts.task_center_acceptance")
    from scripts.local_postgres import OwnedPostgres

    monkeypatch.setattr(module, "ARTIFACTS", tmp_path)

    def unavailable(self):
        raise RuntimeError("owned PostgreSQL unavailable")

    monkeypatch.setattr(OwnedPostgres, "start", unavailable)
    outcome = module.execute()
    assert outcome["status"] == "failed"
    evidence = Path(outcome["result"]).parent
    assert (evidence / "first-failure.json").exists()
    assert json.loads((evidence / "result.json").read_text())["cleanup"]["postgres_stopped"]


def test_cleanup_failure_still_attempts_every_owned_child_and_closes_logs(tmp_path):
    module = importlib.import_module("scripts.task_center_acceptance")
    children = module.OwnedChildren({}, tmp_path)
    children.children = [("one", 1), ("two", 2)]
    attempted = []

    def failing_stop(child):
        attempted.append(child)
        raise RuntimeError("identity cannot be proven")

    children.stop = failing_stop
    log = (tmp_path / "child.log").open("w")
    children.logs.append(log)
    with pytest.raises(RuntimeError):
        children.close()
    assert attempted == [2, 1]
    assert log.closed


class ChildExit:
    def __init__(self, pid, returncode=None, *, on_term=0, hang=False):
        self.pid, self.returncode = pid, returncode
        self.on_term, self.hang = on_term, hang

    def poll(self):
        return self.returncode

    def terminate(self):
        if not self.hang:
            self.returncode = self.on_term

    def kill(self):
        self.returncode = -9

    def wait(self, timeout):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("owned child", timeout)
        return self.returncode


@pytest.mark.parametrize("role,code", [("receiver", -9), ("receiver", 0), ("relay-2", 73)])
def test_unexpected_child_exit_is_rejected_and_audited(tmp_path, role, code):
    module = importlib.import_module("scripts.task_center_acceptance")
    children = module.OwnedChildren({}, tmp_path)
    children.children = [(role, ChildExit(101, code))]
    with pytest.raises(RuntimeError, match="child"):
        children.close()
    record = children.exit_records[101]
    assert record["returncode"] == code
    assert not record["accepted"] and not record["controller_stop_requested"]
    assert not record["forced_kill"]


def test_expected_sender_exception_is_exactly_one_pid_and_graph_zero_is_normal(tmp_path):
    module = importlib.import_module("scripts.task_center_acceptance")
    children = module.OwnedChildren({}, tmp_path)
    children.expected_sender_pid = 101
    children.children = [("relay-1", ChildExit(101, 73)), ("graph", ChildExit(102, 0))]
    children.close()
    assert children.exit_records[101]["expected_reason"] == "durable_acceptance_before_ack"
    assert all(row["accepted"] for row in children.exit_records.values())
    children.children.append(("relay-2", ChildExit(103, 73)))
    with pytest.raises(RuntimeError, match="child"):
        children.close()
    assert not children.exit_records[103]["accepted"]


@pytest.mark.parametrize("code", [0, -15])
def test_parent_requested_term_accepts_only_normal_lifecycle_exit(tmp_path, monkeypatch, code):
    module = importlib.import_module("scripts.task_center_acceptance")
    children = module.OwnedChildren({"token": "owned-capability"}, tmp_path)
    children.children = [("api", ChildExit(101, on_term=code))]
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: type(
            "Result", (), {"stdout": f"{module.__file__} owned-capability", "returncode": 0}
        )(),
    )
    children.close()
    assert children.exit_records[101]["accepted"]
    assert children.exit_records[101]["controller_stop_requested"]
    assert children.exit_records[101]["returncode"] == code


def test_parent_forced_kill_fails_even_when_cleanup_joins_child(tmp_path, monkeypatch):
    module = importlib.import_module("scripts.task_center_acceptance")
    children = module.OwnedChildren({"token": "owned-capability"}, tmp_path)
    children.children = [("receiver", ChildExit(101, hang=True))]
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: type(
            "Result", (), {"stdout": f"{module.__file__} owned-capability", "returncode": 0}
        )(),
    )
    with pytest.raises(RuntimeError, match="child"):
        children.close()
    assert children.exit_records[101]["forced_kill"]
    assert not children.exit_records[101]["accepted"]


def test_real_receiver_unexpected_exit_fails_cli_and_preserves_cleanup():
    program = """
from scripts import task_center_acceptance as acceptance, verify_task_center
original_start = acceptance.OwnedChildren.start
def start(self, role, listener=None):
    if role == 'graph':
        receiver = next(child for name, child in self.children if name == 'receiver')
        assert receiver.poll() is None
        receiver.kill()
        assert receiver.wait(timeout=5) == -9
    return original_start(self, role, listener)
acceptance.OwnedChildren.start = start
raise SystemExit(verify_task_center.main(['--execute']))
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        env={**os.environ, "COMPETISCOPE_LOAD_ENV_FILES": "0"},
        timeout=180,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    outcome = json.loads(result.stdout.splitlines()[-1])
    report = json.loads(Path(outcome["result"]).read_text())
    assert report["status"] == "failed" and all(report["cleanup"].values())
    exits = report["processes"]["exit_results"]
    receiver = next(row for row in exits if row["role"] == "receiver")
    assert receiver["returncode"] == -9 and not receiver["accepted"]
    assert not receiver["controller_stop_requested"] and not receiver["forced_kill"]
    assert (Path(outcome["result"]).parent / "first-failure.json").exists()
    assert not report["processes"]["exit_validation_passed"]


def test_real_socket_database_and_process_acceptance():
    acceptance_module()
    filename = Path(__file__).resolve().parents[2] / "scripts" / "verify_task_center.py"
    result = subprocess.run(
        [sys.executable, str(filename), "--execute"],
        capture_output=True,
        text=True,
        env={**os.environ, "COMPETISCOPE_LOAD_ENV_FILES": "0"},
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads(result.stdout.splitlines()[-1])
    report = json.loads(Path(evidence["result"]).read_text())
    assert report["status"] == "passed"
    assert report["seed"] == 4242
    assert all(report["cleanup"].values()), report["cleanup"]
    assert set(report["scenarios"]) >= {
        "one_remaining",
        "same_key",
        "payload_conflict",
        "sql_rollback",
        "cancel_races",
        "sender_crash",
        "retry_budget",
        "tenant_auth",
        "old_http",
        "pool_saturation",
        "connection_loss",
        "database_stop",
        "demo_graph",
        "sql_integrity",
        "explain",
    }
    assert [row["concurrency"] for row in report["metrics"]["idle"]] == [10, 50, 100]
    assert [row["concurrency"] for row in report["metrics"]["saturated"]] == [10, 50, 100]
    assert len(report["processes"]["api"]) == len(report["processes"]["relay"]) == 2
    assert report["processes"]["exit_validation_passed"]
    exits = report["processes"]["exit_results"]
    expected_sender = report["scenarios"]["sender_crash"]["confirmed_expected_sender_pid"]
    assert len(exits) == 6 and all(row["accepted"] for row in exits)
    assert [row["pid"] for row in exits if row["returncode"] == 73] == [expected_sender]
    assert all(not row["forced_kill"] for row in exits)
    assert report["scenarios"]["sender_crash"]["sends"] == 2
    assert report["scenarios"]["demo_graph"]["checkpoints"] > 0
