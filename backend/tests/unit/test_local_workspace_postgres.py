"""Persistent cluster ownership is checked before any process can be signalled."""

import importlib
import json
import os
import subprocess
from pathlib import Path

import pytest
from psycopg.conninfo import conninfo_to_dict


def module():
    assert importlib.util.find_spec("scripts.local_workspace_postgres") is not None, (
        "persistent workspace PostgreSQL implementation is missing"
    )
    return importlib.import_module("scripts.local_workspace_postgres")


def cluster(tmp_path):
    return module().PersistentWorkspacePostgres(tmp_path / "workspace", binary_dir=Path("/pg"))


def owned(cluster, *, initialized=True):
    cluster.root.mkdir(mode=0o700)
    cluster.postgres_dir.mkdir(mode=0o700)
    cluster.data_dir.mkdir(mode=0o700)
    marker = {
        "kind": "plan-a-persistent-postgres",
        "version": 1,
        "uid": os.getuid(),
        "root": str(cluster.root.resolve()),
        "initialized": initialized,
    }
    cluster.marker_path.write_text(json.dumps(marker))
    cluster.marker_path.chmod(0o600)
    (cluster.data_dir / "PG_VERSION").write_text("15\n")
    return marker


def process(cluster, *, pid=12456, created="Fri Oct 30 00:00:00 2026"):
    command = f"/pg/postgres -D {cluster.data_dir} -c listen_addresses="
    started = 1793318400
    (cluster.data_dir / "postmaster.pid").write_text(
        f"{pid}\n{cluster.data_dir}\n{started}\n5432\n{cluster.socket_dir}\n\n\nready\n"
    )
    cluster.process_path.write_text(
        json.dumps(
            {
                "pid": pid,
                "created": created,
                "command": command,
                "pgdata": str(cluster.data_dir),
                "started": started,
            }
        )
    )
    cluster.process_path.chmod(0o600)
    return subprocess.CompletedProcess([], 0, f"{created} {command}\n", "")


def test_constructor_has_no_filesystem_process_or_connection_side_effects(tmp_path, monkeypatch):
    mod = module()

    def forbidden(*args, **kwargs):
        pytest.fail("construction performed IO")

    monkeypatch.setattr(Path, "resolve", forbidden)
    monkeypatch.setattr(Path, "mkdir", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(mod.psycopg, "connect", forbidden)
    instance = mod.PersistentWorkspacePostgres(tmp_path / "absent", binary_dir=Path("/pg"))
    assert instance.root == tmp_path / "absent"


def test_missing_status_is_uninitialized_without_creating_directories(tmp_path):
    instance = cluster(tmp_path)
    assert instance.status() == {"state": "uninitialized", "initialized": False, "running": False}
    assert not instance.root.exists()
    assert instance.stop()["state"] == "uninitialized"


@pytest.mark.parametrize("target", ["root", "postgres_dir", "data_dir", "marker_path"])
def test_symlink_control_paths_are_rejected_without_running_commands(tmp_path, monkeypatch, target):
    instance = cluster(tmp_path)
    owned(instance)
    path = getattr(instance, target)
    destination = path.with_name(path.name + "-original")
    path.rename(destination)
    path.symlink_to(destination, target_is_directory=destination.is_dir())
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("process command ran"))
    with pytest.raises(module().WorkspacePostgresError, match="ownership|symbolic"):
        instance.stop()


@pytest.mark.parametrize("mutation", ["missing", "uid", "root", "permissions"])
def test_unowned_or_insecure_directory_is_rejected(tmp_path, monkeypatch, mutation):
    instance = cluster(tmp_path)
    marker = owned(instance)
    if mutation == "missing":
        instance.marker_path.unlink()
    elif mutation == "permissions":
        instance.postgres_dir.chmod(0o755)
    else:
        marker[mutation] = -1 if mutation == "uid" else "/foreign"
        instance.marker_path.write_text(json.dumps(marker))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("process command ran"))
    with pytest.raises(module().WorkspacePostgresError, match="ownership"):
        instance.initialise()


def test_repeated_completed_initialise_does_not_migrate_or_run_initdb(tmp_path, monkeypatch):
    instance = cluster(tmp_path)
    owned(instance)
    sentinel = instance.data_dir / "sentinel"
    sentinel.write_text("persist")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("process command ran"))
    assert instance.initialise()["state"] == "stopped"
    assert sentinel.read_text() == "persist"


@pytest.mark.parametrize("mismatch", ["pid", "created", "command", "pgdata", "started", "ps"])
def test_stop_refuses_ambiguous_or_reused_pid(tmp_path, monkeypatch, mismatch):
    instance = cluster(tmp_path)
    owned(instance)
    snapshot = process(instance)
    record = json.loads(instance.process_path.read_text())
    if mismatch == "ps":
        snapshot = subprocess.CompletedProcess([], 1, "", "inspection denied")
    else:
        record[mismatch] = {
            "pid": 789,
            "created": "old",
            "command": "other",
            "pgdata": "/x",
            "started": 4,
        }[mismatch]
        instance.process_path.write_text(json.dumps(record))
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        assert argv[0] == "/bin/ps", "unsafe PostgreSQL command before identity validation"
        return snapshot

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(module().WorkspacePostgresError, match="identity|verify|PID"):
        instance.stop()
    assert all(call[0] == "/bin/ps" for call in calls)
    assert instance.data_dir.exists()


def test_missing_pid_file_with_live_record_is_not_reported_stopped(tmp_path, monkeypatch):
    instance = cluster(tmp_path)
    owned(instance)
    snapshot = process(instance)
    (instance.data_dir / "postmaster.pid").unlink()
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: snapshot)
    with pytest.raises(module().WorkspacePostgresError, match="PID|identity"):
        instance.status()


def test_ps_failure_without_stderr_is_not_assumed_dead(tmp_path, monkeypatch):
    instance = cluster(tmp_path)
    owned(instance)
    process(instance)
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: subprocess.CompletedProcess([], 1, "", "")
    )
    monkeypatch.setattr(os, "kill", lambda *a: None)
    with pytest.raises(module().WorkspacePostgresError, match="verify|identity"):
        instance.stop()


def test_stopped_cluster_and_application_environment_are_secret_free(tmp_path):
    instance = cluster(tmp_path)
    owned(instance)
    assert instance.status() == {"state": "stopped", "initialized": True, "running": False}
    assert instance.stop()["state"] == "stopped"
    assert instance.data_dir.exists()
    environment = instance.app_environment()
    assert environment["ENTERPRISE_STORE_BACKEND"] == "postgres"
    assert environment["TASK_CENTER_ENABLED"] == "true"
    assert environment["ENTERPRISE_POOL_MAX_SIZE"] == "4"
    assert environment["TASK_CENTER_POOL_MAX_SIZE"] == "4"
    assert environment["ENTERPRISE_DATABASE_URL"] == environment["TASK_CENTER_DATABASE_URL"]
    config = conninfo_to_dict(environment["ENTERPRISE_DATABASE_URL"])
    assert config["user"] == "plan_a_workspace_app"
    assert config["dbname"] == "plan_a_workspace"
    assert config["host"].startswith("/")
    assert "password" not in config
    assert "owner" not in repr(environment)
    assert len(os.fsencode(config["host"] + "/.s.PGSQL.5432")) < 100


def test_long_unicode_workspace_uses_short_stable_socket(tmp_path):
    mod = module()
    root = tmp_path / ("中文路径" * 30)
    first = mod.PersistentWorkspacePostgres(root, binary_dir=Path("/pg"))
    second = mod.PersistentWorkspacePostgres(root, binary_dir=Path("/pg"))
    assert first.socket_dir == second.socket_dir
    assert len(os.fsencode(str(first.socket_dir / ".s.PGSQL.5432"))) < 100


def test_process_inspection_uses_utf8_for_macos_unicode_paths(tmp_path, monkeypatch):
    instance = cluster(tmp_path)
    owned(instance)
    snapshot = process(instance)

    def run(argv, **kwargs):
        assert "UTF-8" in kwargs["env"]["LC_ALL"], "ps escapes Unicode in C locale"
        return snapshot

    monkeypatch.setattr(subprocess, "run", run)
    assert instance.status()["running"] is True


def test_existing_symbolic_socket_directory_is_rejected_before_stop(tmp_path, monkeypatch):
    instance = cluster(tmp_path)
    owned(instance)
    destination = tmp_path / "foreign-socket"
    destination.mkdir()
    instance.socket_dir.symlink_to(destination, target_is_directory=True)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("process command ran"))
    try:
        with pytest.raises(module().WorkspacePostgresError, match="ownership|symbolic"):
            instance.stop()
    finally:
        instance.socket_dir.unlink()


def test_successful_stop_retires_record_before_historical_pid_reuse(tmp_path, monkeypatch):
    instance = cluster(tmp_path)
    owned(instance)
    for name in ("postgresql.conf", "pg_hba.conf", "pg_ident.conf", "business-data"):
        (instance.data_dir / name).write_text("preserved data")
    database_before = {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in instance.data_dir.iterdir()
    }
    old_pid, new_pid = 12456, 23456
    snapshots = {old_pid: process(instance, pid=old_pid)}
    state = {"phase": "running", "active_pid": old_pid}
    stopped_pids = []
    signal_calls = []

    def signal(pid, sig):
        signal_calls.append((pid, sig))
        assert sig == 0, "no signal may be sent to a reused PID"
        assert state["phase"] == "stopped"
        raise ProcessLookupError

    def run(argv, **kwargs):
        if argv[0] == "/bin/ps":
            pid = int(argv[3])
            if state["phase"] == "reused" and pid == old_pid:
                return subprocess.CompletedProcess([], 0, "Fri Oct 30 01:00:00 2026 /foreign", "")
            if state["phase"] == "stopped":
                return subprocess.CompletedProcess([], 1, "", "")
            return snapshots[pid]
        if argv[-1] == "--version":
            return subprocess.CompletedProcess([], 0, "postgres (PostgreSQL) 15.18", "")
        assert Path(argv[0]).name == "pg_ctl"
        if argv[-1] == "stop":
            stopped_pids.append(state["active_pid"])
            (instance.data_dir / "postmaster.pid").unlink()
            state["phase"] = "stopped"
        elif argv[-1] == "start":
            assert state["phase"] == "reused"
            snapshots[new_pid] = process(instance, pid=new_pid)
            instance.process_path.unlink()  # pg_ctl creates its PID file, not our registry.
            state.update(phase="running", active_pid=new_pid)
        else:
            pytest.fail("unexpected PostgreSQL command")
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(os, "kill", signal)
    assert instance.stop()["state"] == "stopped"
    assert not instance.process_path.exists(), (
        "confirmed normal stop must retire its process record"
    )
    assert not (instance.data_dir / "postmaster.pid").exists()
    state["phase"] = "reused"
    replacement = module().PersistentWorkspacePostgres(
        instance.root, binary_dir=instance.binary_dir
    )
    assert replacement.status()["state"] == "stopped"
    assert replacement.stop()["state"] == "stopped"
    socket_created = not replacement.socket_dir.exists()
    try:
        assert replacement.start()["state"] == "running"
        assert json.loads(replacement.process_path.read_text())["pid"] == new_pid
        assert replacement.stop()["state"] == "stopped"
        assert stopped_pids == [old_pid, new_pid]
        assert all(sig == 0 for _, sig in signal_calls)
        assert {
            name: (
                (instance.data_dir / name).read_bytes(),
                (instance.data_dir / name).stat().st_mtime_ns,
            )
            for name in database_before
        } == database_before
    finally:
        if socket_created and replacement.socket_dir.exists():
            (replacement.socket_dir / ".workspace-postgres-socket").unlink()
            replacement.socket_dir.rmdir()


@pytest.mark.parametrize("failure", ["pg_ctl_error", "pid_file_remains"])
def test_unsuccessful_stop_retains_own_process_record(tmp_path, monkeypatch, failure):
    instance = cluster(tmp_path)
    owned(instance)
    snapshot = process(instance)
    before = instance.process_path.read_bytes()

    def run(argv, **kwargs):
        if argv[0] == "/bin/ps":
            return snapshot
        assert Path(argv[0]).name == "pg_ctl" and argv[-1] == "stop"
        return subprocess.CompletedProcess([], 1 if failure == "pg_ctl_error" else 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(module().WorkspacePostgresError):
        instance.stop()
    assert instance.process_path.read_bytes() == before
    assert (instance.data_dir / "postmaster.pid").exists()
