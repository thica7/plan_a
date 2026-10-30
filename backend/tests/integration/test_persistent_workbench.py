"""Safe preview plus real persistent CLI, PostgreSQL, Relay and demo graph acceptance."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/verify_persistent_workbench.py"


def acceptance_module():
    assert SCRIPT.is_file(), "persistent workbench acceptance CLI must exist"
    spec = importlib.util.spec_from_file_location("persistent_workbench_acceptance", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_preview_never_reads_settings_environment_database_or_creates_resources(
    monkeypatch, capsys
):
    module = acceptance_module()
    import tempfile

    import psycopg

    import packages.config

    def forbidden(*args, **kwargs):
        pytest.fail("preview performed an execution side effect")

    for owner, attribute in (
        (packages.config, "get_settings"),
        (psycopg, "connect"),
        (subprocess, "Popen"),
        (tempfile, "mkdtemp"),
        (os, "getenv"),
        (Path, "mkdir"),
    ):
        monkeypatch.setattr(owner, attribute, forbidden)
    assert module.main([]) == 0
    assert "preview" in capsys.readouterr().out.lower()


@pytest.mark.parametrize(
    "args",
    [
        ["--database-url", "postgresql://localhost/postgres"],
        ["--data-dir", "/tmp"],
        ["--workspace-dir", "/tmp"],
        ["--port", "8010"],
        ["--output-dir", "/tmp"],
    ],
)
def test_public_cli_rejects_external_targets(args):
    with pytest.raises(SystemExit) as caught:
        acceptance_module().main(args)
    assert caught.value.code == 2


def test_preview_works_directly_from_foreign_cwd_without_dependencies(tmp_path):
    acceptance_module()
    result = subprocess.run(
        [sys.executable, "-S", str(SCRIPT)],
        cwd=tmp_path,
        env={"PATH": "", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "preview" in result.stdout
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "marker",
    [
        None,
        {"exit_code": 1, "shutdown_complete": True},
        {"exit_code": 0, "shutdown_complete": False},
    ],
)
def test_exit_proof_rejects_absence_abnormal_exit_and_incomplete_shutdown(marker):
    module = acceptance_module()
    record = {"service": "relay", "pid": 101, "created": "UTC birth"}
    with pytest.raises(RuntimeError, match="exit"):
        module.validate_exit(record, None, marker)


def test_exit_proof_requires_matching_birth_pid_and_actual_exit():
    module = acceptance_module()
    record = {"service": "relay", "pid": 101, "created": "UTC birth"}
    marker = {"pid": 101, "created": "UTC birth", "exit_code": 0, "shutdown_complete": True}
    assert module.validate_exit(record, None, marker)["accepted"]
    for change in ({"pid": 102}, {"created": "reused"}):
        with pytest.raises(RuntimeError, match="exit"):
            module.validate_exit(record, None, {**marker, **change})
    with pytest.raises(RuntimeError, match="exit"):
        module.validate_exit(record, {"created": "UTC birth", "state": "S"}, marker)


def test_cleanup_attempts_all_owned_roles_after_one_stop_failure(tmp_path, monkeypatch):
    module = acceptance_module()
    session = module.Acceptance(tmp_path, tmp_path / "profile", 8123, 5123)
    attempted = []
    records = [
        {"service": role, "pid": index, "created": "birth"}
        for index, role in enumerate(("backend", "relay", "frontend"), 101)
    ]
    monkeypatch.setattr(session, "records", lambda: records)

    def stop(record):
        attempted.append(record["service"])
        raise RuntimeError("identity unavailable")

    monkeypatch.setattr(session, "stop_role", stop)
    monkeypatch.setattr(session, "cli", lambda *_args: (_ for _ in ()).throw(RuntimeError("stop")))
    assert session.cleanup()["all_stopped"] is False
    assert set(attempted) == {"backend", "relay", "frontend"}


def test_real_persistent_workbench_via_independent_cli_processes():
    acceptance_module()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--execute"],
        env={**os.environ, "COMPETISCOPE_LOAD_ENV_FILES": "0", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    outcome = json.loads(result.stdout.splitlines()[-1])
    report = json.loads(Path(outcome["result"]).read_text())
    assert report["status"] == "passed"
    assert report["cleanup"]["all_stopped"] and report["cleanup"]["temporary_removed"]
    assert report["browser"] == "root_pending"
    assert set(report["scenarios"]) == {
        "demo_graph",
        "api_relay_restart",
        "full_restart",
        "same_key_20",
        "last_quota",
        "pending_resume",
        "cancel_once",
        "database_unavailable",
    }
    baseline = report["scenarios"]["demo_graph"]
    assert baseline["submission"]["run_id"] == baseline["submission"]["expected_run_id"]
    assert baseline["report_sha256"] and baseline["event_count"] > 0
    assert baseline["checkpoint_count"] > 0 and baseline["reserves"] == 1
    assert len(report["cli_commands"]) >= 9
    assert all(row["returncode"] == 0 for row in report["cli_commands"])
    assert len({row["pid"] for row in report["cli_commands"]}) == len(report["cli_commands"])
    assert all(row["accepted"] for row in report["exits"])
    recovery = report["scenarios"]["database_unavailable"]
    assert recovery.get("original_request_replayed") is True
    assert recovery["outage_orphan_submissions"] == 0
    assert recovery["outage_extra_reserves"] == 0
    assert recovery["replay_count"] == 2
    recovered = recovery["original_request"]
    assert recovered["submission"]["run_id"] == recovered["submission"]["expected_run_id"]
    assert recovered["reserves"] == 1 and recovered["report_sha256"]
    assert report["scenarios"]["full_restart"]["fault_request_unchanged"] is True


def test_recovery_waits_for_both_pools_but_never_accepts_500_or_wrong_result(tmp_path, monkeypatch):
    module = acceptance_module()
    session = module.Acceptance(tmp_path, tmp_path / "profile", 8123, 5123)
    responses = iter([(503, {}), (503, {}), (202, {"id": "original"})])
    monkeypatch.setattr(session, "http", lambda *_args: next(responses))
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    assert session.wait_http("POST", "/task-submissions", {}, expected=202) == {"id": "original"}
    monkeypatch.setattr(session, "http", lambda *_args: (500, {}))
    with pytest.raises(RuntimeError, match="500"):
        session.wait_http("POST", "/task-submissions", {}, expected=202)


@pytest.mark.parametrize("where", ["startup", "cleanup"])
def test_failed_execution_retains_first_failure_and_diagnostics_without_secret(
    tmp_path, monkeypatch, where
):
    module = acceptance_module()
    monkeypatch.setattr(module, "ARTIFACTS", tmp_path / "evidence")
    original = module.tempfile.mkdtemp
    monkeypatch.setattr(
        module.tempfile,
        "mkdtemp",
        lambda prefix, dir=None: original(prefix=prefix, dir=dir or tmp_path),
    )

    def perform(_self):
        if where == "startup":
            raise RuntimeError("postgresql://owner:secret@private/database")

    monkeypatch.setattr(module.Acceptance, "perform", perform)
    monkeypatch.setattr(
        module.Acceptance,
        "cleanup",
        lambda _self: {
            "all_stopped": where == "startup",
            "temporary_removed": False,
            "errors": ["unproven"] if where == "cleanup" else [],
        },
    )
    outcome = module.execute()
    assert outcome["status"] == "failed"
    path = Path(outcome["result"])
    first_failure = path.parent / "first-failure.json"
    assert first_failure.is_file()
    assert "secret" not in first_failure.read_text()
    report = json.loads(path.read_text())
    assert not report["cleanup"]["temporary_removed"]
    assert Path(report["profile"]).parent.is_dir()


def test_real_enterprise_migration_preserves_rows_and_blocked_status_with_restricted_app():
    import shutil
    import tempfile
    from datetime import UTC, datetime

    import psycopg

    from packages.enterprise.postgres import EnterprisePostgresStore
    from packages.schema.api_dto import RunDetail
    from packages.schema.models import AnalysisPlan
    from packages.task_center.errors import TaskCenterStorageError

    module = acceptance_module()
    root = Path(tempfile.mkdtemp(prefix="persistent-status-test-")).resolve()
    session = module.Acceptance(root, root / "profile", 49111, 49112)
    postgres = session.manager.postgres()
    app = owner = None
    try:
        postgres.initialise()
        postgres.start()
        now = datetime.now(UTC)
        normal = RunDetail(
            id="normal-state-fixture",
            idempotency_key="normal-state-fixture",
            topic="状态兼容fixture",
            status="completed",
            execution_mode="demo",
            created_at=now,
            updated_at=now,
            plan=AnalysisPlan(
                topic="状态兼容fixture", competitors=["Cursor"], dimensions=["pricing"]
            ),
        )
        app = EnterprisePostgresStore(
            postgres.app_environment()["ENTERPRISE_DATABASE_URL"], auto_migrate=False
        )
        app.start_run(normal)
        original = session.sql("SELECT id,status,detail_json FROM runs WHERE id=%s", (normal.id,))
        # A real existing five-state schema, with a real existing business row.
        with psycopg.connect(postgres._conninfo(owner=True)) as connection:
            connection.execute("ALTER TABLE runs DROP CONSTRAINT runs_status_check")
            connection.execute(
                "ALTER TABLE runs ADD CONSTRAINT runs_status_check CHECK "
                "(status IN ('queued','running','interrupted','completed','failed'))"
            )
        owner = EnterprisePostgresStore(postgres._conninfo(owner=True), auto_migrate=False)
        owner.migrate()
        blocked = normal.model_copy(
            deep=True,
            update={
                "id": "blocked-state-fixture",
                "idempotency_key": "blocked-state-fixture",
                "status": "completed_with_blockers",
            },
        )
        app.start_run(blocked)
        assert session.sql(
            "SELECT status,detail_json->>'status' AS detail_status FROM runs WHERE id=%s",
            (blocked.id,),
        ) == [
            {"status": "completed_with_blockers", "detail_status": "completed_with_blockers"},
        ]
        owner.migrate()
        assert (
            session.sql("SELECT id,status,detail_json FROM runs WHERE id=%s", (normal.id,))
            == original
        )
        assert session.sql("SELECT status FROM runs WHERE id=%s", (blocked.id,)) == [
            {"status": "completed_with_blockers"}
        ]
        invalid = normal.model_copy(
            deep=True,
            update={
                "id": "invalid-state-fixture",
                "idempotency_key": "invalid-state-fixture",
                "status": "invalid-status",
            },
        )
        with pytest.raises(TaskCenterStorageError) as error:
            app.start_run(invalid)
        assert error.value.sqlstate == "23514"
        assert not session.sql("SELECT id FROM runs WHERE id=%s", (invalid.id,))
    finally:
        for store in (app, owner):
            if store is not None:
                store.close()
        before = session.pg_before_stop()
        postgres.stop()
        session.prove_pg_stopped(before)
        shutil.rmtree(root)
        if postgres.socket_dir.exists():
            postgres._check_socket()
            (postgres.socket_dir / ".workspace-postgres-socket").unlink()
            postgres.socket_dir.rmdir()


def test_recovery_evidence_preserves_each_same_path_replay_window(tmp_path, monkeypatch):
    module = acceptance_module()
    session = module.Acceptance(tmp_path, tmp_path / "profile", 8123, 5123)
    replies = iter([(503, {}), (202, {"id": "one"}), (202, {"id": "two"})])
    monkeypatch.setattr(session, "http", lambda *_args: next(replies))
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    session.wait_http("POST", "/task-submissions", {"request": "baseline"}, 202)
    session.wait_http("POST", "/task-submissions", {"request": "original-failure"}, 202)
    windows = [json.loads(path.read_text()) for path in sorted(tmp_path.glob("recovery-*.json"))]
    assert [window["statuses"] for window in windows] == [[503, 202], [202]]


def test_cached_exit_proof_is_bound_to_process_not_latest_role_marker(tmp_path, monkeypatch):
    module = acceptance_module()
    session = module.Acceptance(tmp_path, tmp_path / "profile", 8123, 5123)
    old = {"service": "relay", "pid": 101, "created": "old birth"}
    marker = {"pid": 101, "created": "old birth", "exit_code": 0, "shutdown_complete": True}
    monkeypatch.setattr(session.runtime, "process_snapshot", lambda _pid: None)
    monkeypatch.setattr(session.manager, "exit_result", lambda _record: marker)
    session.prove_exits([old])
    monkeypatch.setattr(session.manager, "exit_result", lambda _record: None)
    session.prove_exits([old])
    assert session.exits[0]["pid"] == old["pid"]
    new = {"service": "relay", "pid": 102, "created": "new birth"}
    with pytest.raises(RuntimeError, match="exit"):
        session.prove_exits([new])


def test_cleanup_cannot_forget_unproven_process_when_registry_becomes_empty(tmp_path, monkeypatch):
    from types import SimpleNamespace

    module = acceptance_module()
    session = module.Acceptance(tmp_path, tmp_path / "profile", 8123, 5123)
    record = {"service": "relay", "pid": 101, "created": "birth"}
    registrations = iter([[record], []])
    monkeypatch.setattr(session, "records", lambda: next(registrations))
    monkeypatch.setattr(session, "cli", lambda *_args: {})
    monkeypatch.setattr(
        session, "stop_role", lambda _record: (_ for _ in ()).throw(RuntimeError("unproven"))
    )
    monkeypatch.setattr(session.runtime, "process_snapshot", lambda _pid: None)
    monkeypatch.setattr(session.manager, "exit_result", lambda _record: None)
    monkeypatch.setattr(
        session.manager,
        "postgres",
        lambda: SimpleNamespace(status=lambda: {"running": False}, stop=lambda: {}),
    )
    assert session.cleanup()["all_stopped"] is False
    assert session.cleanup()["all_stopped"] is False


def test_real_resume_registry_write_failure_stops_all_known_processes_before_pg(monkeypatch):
    import shutil
    import socket
    import tempfile

    module = acceptance_module()
    module.ARTIFACTS.mkdir(parents=True, exist_ok=True)
    evidence = Path(tempfile.mkdtemp(prefix="impl-task4-fix2-native-", dir=module.ARTIFACTS))
    temporary = Path(tempfile.mkdtemp(prefix="persistent-workbench-fix2-spawn-")).resolve()
    with socket.socket() as backend, socket.socket() as frontend:
        backend.bind(("127.0.0.1", 0))
        frontend.bind(("127.0.0.1", 0))
        ports = backend.getsockname()[1], frontend.getsockname()[1]
    session = module.Acceptance(evidence, temporary / "profile", *ports)
    spawned = []
    original_spawn = session.manager.spawn
    original_write = session.manager.write_registry
    completed = False
    observed = {}

    def capture_spawn(*args, **kwargs):
        record = original_spawn(*args, **kwargs)
        spawned.append(record)
        return record

    def fail_write(*args, **kwargs):
        raise OSError("injected single registry write failure")

    try:
        session.cli("init")
        session.cli("start")
        session.pause_relay()
        monkeypatch.setattr(session.manager, "spawn", capture_spawn)
        monkeypatch.setattr(session.manager, "write_registry", fail_write)
        with pytest.raises(OSError, match="injected single registry"):
            session.resume_relay()
        monkeypatch.setattr(session.manager, "write_registry", original_write)
        record = spawned[-1]
        session.manager.wait_relay(record)
        observed["spawned_record"] = record
        observed["registry_omits_spawned"] = record not in session.records()
        observed["spawn_remembered_before_registry"] = record in session.known_records.values()

        original_stop_role = session.stop_role

        def observe_stop(target):
            already_proven = session.record_key(target) in session.exit_proofs
            original_stop_role(target)
            if target == record and not already_proven:
                observed["pg_running_when_new_relay_exit_proven"] = (
                    session.manager.postgres().status()["running"]
                )

        monkeypatch.setattr(session, "stop_role", observe_stop)
        module.save(
            evidence / "first-failure.json",
            {"message": "injected single registry write failure", "spawned_record": record},
        )
        observed["first_cleanup"] = session.cleanup()
        observed["new_exit_marker"] = session.manager.exit_result(record)
        observed["new_stop_requested"] = any(
            record["pid"] == row["pid"]
            for attempt in session.stop_attempts
            for row in attempt["records"]
        )
        observed["repeat_cleanup"] = session.cleanup()
        observed["postgres_stopped"] = not session.manager.postgres().status()["running"]
        observed["normal_exit_proofs"] = session.exits
        module.save(evidence / "result.json", observed)
        assert observed["first_cleanup"]["all_stopped"]
        assert observed["repeat_cleanup"] == observed["first_cleanup"]
        assert observed["spawn_remembered_before_registry"]
        assert observed["pg_running_when_new_relay_exit_proven"]
        assert observed["new_stop_requested"]
        assert observed["new_exit_marker"]["exit_code"] == 0
        assert observed["new_exit_marker"]["shutdown_complete"]
        assert observed["postgres_stopped"]
        completed = True
    finally:
        monkeypatch.setattr(session.manager, "write_registry", original_write)
        # A red injection retains diagnostics. It never converts an abnormal exit
        # into a passing normal-stop proof, but joins our direct child safely.
        for record in spawned:
            try:
                snapshot = session.runtime.process_snapshot(record["pid"])
                if session.manager.is_owned(record, snapshot):
                    session.stop_role(record)
            finally:
                child = session.manager._children.get(record["pid"])
                if child is not None:
                    child.wait(timeout=10)
        if not completed:
            session.cleanup()
        if completed:
            postgres = session.manager.postgres()
            shutil.rmtree(temporary)
            if postgres.socket_dir.exists():
                postgres._check_socket()
                (postgres.socket_dir / ".workspace-postgres-socket").unlink()
                postgres.socket_dir.rmdir()


@pytest.mark.parametrize("actually_exited", [True, False])
def test_abnormal_exit_keeps_failure_but_only_live_or_unknown_child_retains_pg(
    tmp_path, monkeypatch, actually_exited
):
    from types import SimpleNamespace

    module = acceptance_module()
    session = module.Acceptance(tmp_path, tmp_path / "profile", 8123, 5123)
    record = {"service": "relay", "pid": 101, "created": "birth"}
    registrations = iter([[record], []])
    state = {"running": True, "stops": 0}

    def stop_pg():
        state["stops"] += 1
        state["running"] = False

    monkeypatch.setattr(session, "records", lambda: next(registrations))
    monkeypatch.setattr(session, "cli", lambda *_args: (_ for _ in ()).throw(RuntimeError("stop")))
    monkeypatch.setattr(
        session, "stop_role", lambda _record: (_ for _ in ()).throw(RuntimeError("exit 1"))
    )
    monkeypatch.setattr(session, "pg_before_stop", lambda: None)
    monkeypatch.setattr(session, "prove_pg_stopped", lambda _before: None)
    monkeypatch.setattr(
        session.runtime,
        "process_snapshot",
        lambda _pid: None if actually_exited else {"created": "unknown", "state": "S"},
    )
    monkeypatch.setattr(
        session.manager,
        "postgres",
        lambda: SimpleNamespace(status=lambda: {"running": state["running"]}, stop=stop_pg),
    )
    first = session.cleanup()
    assert first["all_stopped"] is False
    assert state["stops"] == int(actually_exited)
    assert state["running"] is not actually_exited
    assert session.cleanup()["all_stopped"] is False
