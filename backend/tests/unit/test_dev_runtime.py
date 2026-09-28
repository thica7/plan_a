from __future__ import annotations

import importlib.util
import socket
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def load_script(name: str = "dev_runtime"):
    path = ROOT / "scripts" / f"{name}.py"
    assert path.exists(), f"Missing project runtime entry: {path.name}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_custom_ports_reach_backend_vite_and_proxy(tmp_path: Path):
    runtime = load_script()
    (tmp_path / ".env").write_text("BACKEND_PORT=8101\nFRONTEND_PORT=5101\n")
    config = runtime.resolve_config(tmp_path, {"BACKEND_PORT": "8102"}, frontend_port=5102)
    commands = runtime.service_commands(tmp_path, config, "python", "node")

    assert config["backend_port"] == 8102
    assert config["frontend_port"] == 5102
    assert commands["backend"][-2:] == ["--app-dir", str(tmp_path / "backend")]
    assert commands["backend"][commands["backend"].index("--port") + 1] == "8102"
    assert commands["frontend"][-3:] == ["--port", "5102", "--strictPort"]
    assert (
        runtime.service_environment(tmp_path, config, {})["VITE_API_TARGET"]
        == "http://127.0.0.1:8102"
    )


def test_status_uses_recorded_ports_even_after_env_changes(tmp_path: Path):
    runtime = load_script()
    runtime.write_registry(
        tmp_path,
        {
            "root": str(tmp_path),
            "config": {"backend_port": 8103, "frontend_port": 5103},
            "services": [],
        },
    )
    (tmp_path / ".env").write_text("BACKEND_PORT=9999\nFRONTEND_PORT=9998\n")

    assert runtime.status_config(tmp_path, {})["backend_port"] == 8103
    assert runtime.status_config(tmp_path, {})["frontend_port"] == 5103


def test_recorded_status_survives_invalid_new_port_configuration(tmp_path: Path):
    runtime = load_script()
    config = runtime.resolve_config(tmp_path, {"BACKEND_PORT": "8103", "FRONTEND_PORT": "5103"})
    runtime.write_registry(tmp_path, {"root": str(tmp_path), "config": config, "services": []})
    (tmp_path / ".env").write_text("BACKEND_PORT=invalid\n")
    assert runtime.status_config(tmp_path, {})["backend_port"] == 8103


@pytest.mark.parametrize(
    "env", [{"BACKEND_PORT": "0"}, {"FRONTEND_PORT": "65536"}, {"FRONTEND_PORT": "8000"}]
)
def test_invalid_or_duplicate_ports_fail_before_start(tmp_path: Path, env):
    runtime = load_script()
    with pytest.raises(ValueError, match="port"):
        runtime.resolve_config(tmp_path, env)


def test_pid_ownership_requires_birth_command_and_current_project(tmp_path: Path):
    runtime = load_script()
    command = f"python {tmp_path}/backend/scripts/run_temporal_worker.py"
    record = {"name": "temporal-worker", "pid": 4242, "created": "start-1", "command": command}

    assert runtime.is_owned(record, {"created": "start-1", "command": command}, tmp_path)
    assert not runtime.is_owned(record, {"created": "start-2", "command": command}, tmp_path)
    foreign = "python /another-project/backend/scripts/run_temporal_worker.py"
    assert not runtime.is_owned(record, {"created": "start-1", "command": foreign}, tmp_path)
    forged = {**record, "command": foreign}
    assert not runtime.is_owned(forged, {"created": "start-1", "command": foreign}, tmp_path)


def test_pid_ownership_rejects_path_prefix_lookalikes(tmp_path: Path):
    runtime = load_script()
    command = f"python {tmp_path}/backend/scripts/run_temporal_worker.py.another-project"
    record = {"name": "temporal-worker", "pid": 4242, "created": "start-1", "command": command}
    assert not runtime.is_owned(record, {"created": "start-1", "command": command}, tmp_path)


def test_occupied_port_reports_listener_owner(tmp_path: Path, monkeypatch):
    runtime = load_script()
    monkeypatch.setattr(
        runtime, "port_owners", lambda port: ["pid=4242 external-server"], raising=False
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        with pytest.raises(RuntimeError, match="pid=4242 external-server"):
            runtime.assert_ports_available(
                {"backend_port": listener.getsockname()[1], "frontend_port": 5173}
            )


def test_stop_never_signals_unverified_recorded_pid(tmp_path: Path, monkeypatch):
    runtime = load_script()
    foreign = "python /another-project/backend/scripts/run_temporal_worker.py"
    runtime.write_registry(
        tmp_path,
        {
            "root": str(tmp_path),
            "config": {},
            "services": [
                {"name": "temporal-worker", "pid": 4242, "created": "start-1", "command": foreign},
            ],
        },
    )
    monkeypatch.setattr(
        runtime, "process_snapshot", lambda pid: {"created": "start-1", "command": foreign}
    )
    stopped = []
    monkeypatch.setattr(runtime, "terminate_process", lambda pid: stopped.append(pid))

    with pytest.raises(RuntimeError, match="ownership"):
        runtime.stop_services(tmp_path, force=True)
    assert stopped == []


def test_occupied_port_is_reported_without_stopping_listener(tmp_path: Path):
    runtime = load_script()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        with pytest.raises(RuntimeError, match=str(port)):
            runtime.assert_ports_available({"backend_port": port, "frontend_port": 5173})
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            pass


def test_active_run_guard_fails_closed_when_backend_cannot_be_read(monkeypatch):
    runtime = load_script()

    def unavailable(_url):
        raise OSError("unavailable")

    monkeypatch.setattr(runtime, "fetch_json", unavailable)
    with pytest.raises(RuntimeError, match="--force"):
        runtime.assert_no_active_runs({"api_target": "http://127.0.0.1:8000"}, 6)


def test_active_run_guard_respects_timestamps_with_negative_timezone(monkeypatch):
    runtime = load_script()
    recent = datetime.now(timezone(timedelta(hours=-8))).isoformat()
    monkeypatch.setattr(runtime, "fetch_json", lambda _url: [{
        "id": "active-1", "status": "running", "updated_at": recent,
    }])
    with pytest.raises(RuntimeError, match="active-1"):
        runtime.assert_no_active_runs({"api_target": "http://127.0.0.1:8000"}, 6)


def test_registry_from_other_repository_is_rejected(tmp_path: Path):
    runtime = load_script()
    runtime.write_registry(tmp_path, {"root": "/another-project", "config": {}, "services": []})
    with pytest.raises(RuntimeError, match="repository"):
        runtime.read_registry(tmp_path)


def test_stop_terminates_only_our_registered_test_process(tmp_path: Path):
    runtime = load_script()
    worker = tmp_path / "backend/scripts/run_temporal_worker.py"
    worker.parent.mkdir(parents=True)
    worker.write_text("import time\ntime.sleep(30)\n")
    process = subprocess.Popen([sys.executable, str(worker)])
    try:
        snapshot = runtime.process_snapshot(process.pid)
        assert snapshot is not None
        runtime.write_registry(
            tmp_path,
            {
                "root": str(tmp_path),
                "config": {},
                "services": [
                    {"name": "temporal-worker", "pid": process.pid, **snapshot},
                ],
            },
        )
        runtime.stop_services(tmp_path, force=True)
        assert process.wait(timeout=5) is not None
        assert runtime.read_registry(tmp_path)["services"] == []
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)


def test_compose_endpoint_output_uses_resolved_host_ports():
    deploy = load_script("docker_deploy")
    config = {
        "services": {
            "nginx": {"ports": [{"target": 80, "published": "9080", "host_ip": "0.0.0.0"}]},
            "temporal-ui": {
                "ports": [{"target": 8080, "published": "9233", "host_ip": "127.0.0.1"}]
            },
            "qdrant": {"ports": [{"target": 6333, "published": "9333", "host_ip": "127.0.0.1"}]},
        }
    }
    assert deploy.compose_urls(config) == {
        "App": "http://127.0.0.1:9080",
        "API": "http://127.0.0.1:9080/api",
        "Temporal UI": "http://127.0.0.1:9233",
        "Qdrant": "http://127.0.0.1:9333",
    }
