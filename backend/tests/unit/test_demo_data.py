from __future__ import annotations

import importlib.util
import io
import json
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def load_data():
    path = ROOT / "scripts/demo_data.py"
    assert path.exists(), "Missing safe demo backup/restore tool"
    spec = importlib.util.spec_from_file_location("demo_data", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_backup(data, directory: Path):
    directory.mkdir()
    for name in ("run-data", "artifact-data", "qdrant_data"):
        with tarfile.open(directory / f"{name}.tar.gz", "w:gz") as archive:
            member = tarfile.TarInfo("durable-marker.txt")
            member.size = 4
            archive.addfile(member, io.BytesIO(b"demo"))
    (directory / "postgres-competiscope.dump").write_bytes(b"database archive")
    data.write_manifest(directory, "plan-a-demo", ["competiscope"], ["backend", "postgres"])


def test_backup_plan_stops_writers_before_export_and_never_removes_volumes(tmp_path):
    data = load_data()
    plan = data.data_plan("backup", "plan-a-demo", tmp_path / "backup")
    assert plan["dry_run"] is True
    assert plan["steps"][0]["command"][-6:] == [
        "nginx",
        "backend",
        "temporal-worker",
        "temporal",
        "temporal-ui",
        "qdrant",
    ]
    commands = [step["command"] for step in plan["steps"]]
    assert any("pg_dump" in " ".join(command) for command in commands)
    assert not any("down" in command or "--volumes" in command for command in commands)
    assert "postgres-data" not in data.DATA_VOLUMES


def test_archives_read_source_volume_only_and_do_not_need_network(tmp_path):
    data = load_data()
    command = data.volume_command("plan-a-demo", "run-data", tmp_path, restore=False)
    assert "none" == command[command.index("--network") + 1]
    assert "plan-a-demo_run-data:/source:ro" in command
    assert "alpine:3.21.3" in command
    restore = data.volume_command("plan-a-drill-1", "run-data", tmp_path, restore=True)
    assert "plan-a-drill-1_run-data:/target" in restore
    assert f"type=bind,source={tmp_path.resolve()},target=/backup,readonly" in restore


@pytest.mark.parametrize(
    "action,project,target,allow_stop",
    [
        ("backup", "plan-a-demo", None, False),
        ("restore", "plan-a-demo", "plan-a-demo", True),
        ("restore", "plan-a-demo", "another-project", True),
        ("fault", "plan-a-demo", None, True),
    ],
)
def test_execute_rejects_implicit_stopping_or_nonisolated_targets(
    action, project, target, allow_stop
):
    data = load_data()
    with pytest.raises(ValueError):
        data.validate_execution(action, project, target, allow_stop)


def test_ownership_rejects_another_checkout_even_with_same_project():
    data = load_data()
    labels = {
        "com.docker.compose.project": "plan-a-drill-1",
        "com.docker.compose.service": "backend",
        "com.docker.compose.project.working_dir": "/another/checkout",
        "com.docker.compose.project.config_files": str(ROOT / "docker-compose.yml"),
    }
    with pytest.raises(RuntimeError, match="ownership"):
        data.validate_ownership(labels, "plan-a-drill-1")
    labels["com.docker.compose.project.working_dir"] = str(ROOT)
    data.validate_ownership(labels, "plan-a-drill-1")


def test_backup_manifest_verifies_digests_before_restore(tmp_path):
    data = load_data()
    directory = tmp_path / "backup"
    make_backup(data, directory)
    assert data.verify_backup(directory)["project"] == "plan-a-demo"
    (directory / "postgres-competiscope.dump").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        data.verify_backup(directory)


def test_restore_rejects_tar_traversal_even_with_matching_digest(tmp_path):
    data = load_data()
    directory = tmp_path / "backup"
    make_backup(data, directory)
    with tarfile.open(directory / "run-data.tar.gz", "w:gz") as archive:
        member = tarfile.TarInfo("../../outside")
        member.size = 4
        archive.addfile(member, io.BytesIO(b"evil"))
    data.write_manifest(directory, "plan-a-demo", ["competiscope"], ["backend"])
    with pytest.raises(ValueError, match="archive"):
        data.verify_backup(directory)


def test_restore_rejects_manifest_path_injection(tmp_path):
    data = load_data()
    directory = tmp_path / "backup"
    make_backup(data, directory)
    path = directory / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["files"]["../../secret"] = "digest"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="manifest"):
        data.verify_backup(directory)


def test_data_default_dry_run_never_calls_docker_or_creates_directory(
    monkeypatch, tmp_path, capsys
):
    data = load_data()
    monkeypatch.setattr(
        data.subprocess, "run", lambda *args, **kwargs: pytest.fail("Docker called")
    )
    target = tmp_path / "backup"
    assert data.main(["backup", "--project", "plan-a-demo", "--directory", str(target)]) == 0
    assert not target.exists()
    assert json.loads(capsys.readouterr().out)["dry_run"] is True


def test_fault_plan_checks_persisted_run_and_marker():
    data = load_data()
    plan = data.data_plan("fault", "plan-a-drill-1", Path("/tmp/unused"), run_id="run-demo")
    text = json.dumps(plan)
    assert "run_journal.db" in text
    assert "restart" in text
    assert "marker" in text
    with pytest.raises(ValueError, match="run-id"):
        data.data_plan("fault", "plan-a-drill-1", Path("/tmp/unused"))


def test_fault_acceptance_rejects_lost_events_or_changed_waiting_state():
    data = load_data()
    before = {
        "id": "demo",
        "status": "waiting_hitl",
        "execution_mode": "demo",
        "events": 3,
        "last_event": 3,
    }
    data.validate_fault_result(before, dict(before), "marker", "marker")
    with pytest.raises(RuntimeError, match="persist"):
        data.validate_fault_result(before, {**before, "events": 2}, "marker", "marker")
    with pytest.raises(RuntimeError, match="waiting"):
        data.validate_fault_result(before, {**before, "status": "running"}, "marker", "marker")
    with pytest.raises(RuntimeError, match="marker"):
        data.validate_fault_result(before, dict(before), "marker", "lost")


def test_restore_refuses_existing_project_before_creating_any_volume(monkeypatch, tmp_path):
    data = load_data()
    make_backup(data, tmp_path / "backup")
    monkeypatch.setattr(data, "project_inventory", lambda project: [{"service": "backend"}])
    calls = []
    monkeypatch.setattr(data, "run_command", lambda command, **kwargs: calls.append(command))
    with pytest.raises(RuntimeError, match="empty"):
        data.execute_restore("plan-a-drill-1", tmp_path / "backup")
    assert calls == []


def test_restore_postgres_uses_compose_credentials_without_publishing_host_ports():
    data = load_data()
    command = data.isolated_postgres_command("plan-a-drill-1")
    assert command[:2] == ["docker", "compose"]
    assert "--no-deps" in command
    assert "--service-ports" not in command
    assert "POSTGRES_HOST_AUTH_METHOD=trust" not in command
    assert "--publish" not in command


def test_fault_preserves_interrupted_and_completed_with_blockers_states():
    data = load_data()
    for status in ("interrupted", "completed_with_blockers"):
        before = {
            "id": "demo",
            "status": status,
            "execution_mode": "demo",
            "events": 3,
            "last_event": 3,
        }
        with pytest.raises(RuntimeError):
            data.validate_fault_result(before, {**before, "status": "running"}, "marker", "marker")


def test_fault_rejects_rewritten_event_history():
    data = load_data()
    before = {
        "id": "demo",
        "status": "running",
        "execution_mode": "demo",
        "events": 3,
        "last_event": 3,
        "history_hash": "old",
    }
    with pytest.raises(RuntimeError, match="persist"):
        data.validate_fault_result(
            before, {**before, "history_hash": "changed"}, "marker", "marker"
        )


def test_postgres_backup_also_covers_an_application_using_the_postgres_database():
    data = load_data()
    assert "datname <>" not in " ".join(data.DATABASE_LIST)
    assert "-d template1" in " ".join(data.DATABASE_RESTORE)


def test_sqlite_probe_reopens_durable_run_and_hashes_only_existing_events(tmp_path):
    import sqlite3
    import subprocess
    import sys

    data = load_data()
    path = tmp_path / "run_journal.db"
    with sqlite3.connect(path) as connection:
        connection.execute("create table runs (id text, status text, execution_mode text)")
        connection.execute("create table events (run_id text, event_id integer, event_json text)")
        connection.execute("insert into runs values ('demo', 'interrupted', 'demo')")
        connection.execute("insert into events values ('demo', 1, '{\"event\":\"old\"}')")
    code = data.RUN_PROBE.replace("/app/runs/run_journal.db", str(path))
    before = json.loads(
        subprocess.run([sys.executable, "-c", code, "demo"], capture_output=True, check=True).stdout
    )
    with sqlite3.connect(path) as connection:
        connection.execute("insert into events values ('demo', 2, '{\"event\":\"new\"}')")
    after = json.loads(
        subprocess.run(
            [sys.executable, "-c", code, "demo", "1"], capture_output=True, check=True
        ).stdout
    )
    assert before["events"] == 1
    assert after["events"] == 2
    assert before["history_hash"] == after["history_hash"]
    data.validate_fault_result(before, after, "marker", "marker")


def test_failed_backup_restarts_only_previously_running_writers(monkeypatch, tmp_path):
    import subprocess

    data = load_data()
    monkeypatch.setattr(
        data,
        "project_inventory",
        lambda project: [
            {"service": "backend", "running": True},
            {"service": "postgres", "running": True},
            {"service": "temporal-worker", "running": False},
        ],
    )
    monkeypatch.setattr(data, "assert_source_volumes", lambda project: None)
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        if data.DATABASE_LIST[2] in command:
            return b"competiscope\npostgres\n"
        if data.DATABASE_DUMP[2] in command:
            raise subprocess.CalledProcessError(1, command, stderr=b"private server detail")
        return b""

    monkeypatch.setattr(data, "run_command", run)
    with pytest.raises(subprocess.CalledProcessError):
        data.execute_backup("plan-a-demo", tmp_path / "backup")
    assert commands[-1][-2:] == ["start", "backend"]
    assert not (tmp_path / "backup" / "manifest.json").exists()


def test_restore_executes_only_fresh_target_and_leaves_application_stopped(monkeypatch, tmp_path):
    data = load_data()
    make_backup(data, tmp_path / "backup")
    monkeypatch.setattr(data, "project_inventory", lambda project: [])
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return b""

    monkeypatch.setattr(data, "run_command", run)
    result = data.execute_restore("plan-a-drill-1", tmp_path / "backup")
    assert result["verified"] is True
    assert commands[-1] == ["docker", "rm", "plan-a-drill-1-restore-postgres"]
    assert not any("plan-a-demo" in str(command) for command in commands)
    assert not any("backend" in command or "temporal-worker" in command for command in commands)
    assert not any("volume" in command and "rm" in command for command in commands)


def test_backup_bind_mount_accepts_colons_without_volume_syntax_ambiguity(tmp_path):
    data = load_data()
    directory = tmp_path / "drive:folder"
    command = data.volume_command("plan-a-demo", "run-data", directory, restore=False)
    assert f"type=bind,source={directory.resolve()},target=/backup" in command
    assert "--mount" in command


def test_data_compose_file_is_explicit_even_with_inherited_compose_file(monkeypatch):
    data = load_data()
    monkeypatch.setenv("COMPOSE_FILE", "/foreign/docker-compose.yml")
    command = data.compose("plan-a-demo")
    assert command[command.index("-f") + 1] == str(ROOT / "docker-compose.yml")
