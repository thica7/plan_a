from __future__ import annotations

import errno
import importlib.util
import json
import os
import socket
import subprocess
import sys
import sysconfig
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/workbench_runtime.py"


def load_runtime():
    assert SCRIPT.is_file(), "controlled workbench entry point is missing"
    spec = importlib.util.spec_from_file_location("workbench_runtime", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("action", ["init", "start", "status", "stop"])
def test_preview_from_foreign_cwd_without_dependencies_or_side_effects(tmp_path, action):
    assert SCRIPT.is_file(), "controlled workbench entry point is missing"
    workspace = tmp_path / "never-created"
    result = subprocess.run(
        [sys.executable, "-S", str(SCRIPT), action, "--workspace-dir", str(workspace)],
        cwd=tmp_path,
        env={"PATH": "", "PRIVATE_OWNER_DSN": "sentinel-owner"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "preview" in result.stdout
    assert "sentinel-owner" not in result.stdout + result.stderr
    assert not workspace.exists()
    assert list(tmp_path.iterdir()) == []


def test_environment_is_allowlisted_and_all_profile_data_is_isolated(tmp_path):
    runtime = load_runtime()
    manager = runtime.WorkbenchRuntime(ROOT, tmp_path / "profile")
    injected = {
        "PATH": "/bin",
        "HOME": "/trusted-home",
        "LANG": "en_US.UTF-8",
        "ENTERPRISE_DATABASE_URL": "owner-secret",
        "TASK_CENTER_DATABASE_URL": "owner-secret",
        "ARK_API_KEY": "model-secret",
        "OPENAI_API_KEY": "model-secret",
        "QDRANT_URL": "http://lan",
        "REDIS_URL": "redis://lan",
        "TEMPORAL_ADDRESS": "lan:7233",
        "AUTH_ENABLED": "true",
        "HTTP_PROXY": "http://proxy",
        "NODE_OPTIONS": "--require=/unsafe.js",
        "PYTHONPATH": "/unsafe",
        "VITE_SECRET": "browser-secret",
    }
    app = {
        "ENTERPRISE_DATABASE_URL": "restricted-app",
        "TASK_CENTER_DATABASE_URL": "restricted-app",
        "ENTERPRISE_STORE_BACKEND": "postgres",
        "TASK_CENTER_ENABLED": "true",
    }
    env = manager.child_environment(injected, app)
    assert env["ENTERPRISE_DATABASE_URL"] == "restricted-app"
    assert env["TASK_CENTER_DATABASE_URL"] == "restricted-app"
    assert env["TASK_CENTER_POOL_MAX_SIZE"] == env["ENTERPRISE_POOL_MAX_SIZE"] == "4"
    assert env["AUTH_ENABLED"] == "false"
    assert env["COMPETISCOPE_LOAD_ENV_FILES"] == "0"
    assert env["RUN_ORCHESTRATION_BACKEND"] == "langgraph"
    assert env["DEMO_MODE"] == env["EXECUTION_CONTROL_ENABLED"] == "true"
    assert env["EXECUTION_GLOBAL_RUNNING_LIMIT"] == "2"
    assert env["EXECUTION_WORKSPACE_RUNNING_LIMIT"] == "1"
    for key in (
        "GRAPH_CHECKPOINT_PATH",
        "EXECUTION_CONTROL_JOURNAL_PATH",
        "KB_DB_PATH",
        "KB_CACHE_PATH",
        "TRACE_DB_PATH",
        "PREFERENCE_MEMORY_PATH",
        "ARTIFACT_STORAGE_ROOT",
    ):
        assert Path(env[key]).is_relative_to(manager.workspace)
    for key in set(injected) - {"PATH", "HOME", "LANG", *app}:
        if key != "AUTH_ENABLED":
            assert key not in env
    assert not manager.workspace.exists()


def test_commands_carry_role_workspace_code_and_loopback_ports(tmp_path):
    runtime = load_runtime()
    manager = runtime.WorkbenchRuntime(ROOT, tmp_path, backend_port=8123, frontend_port=5123)
    for role in ("backend", "relay", "frontend"):
        command = manager.command(role)
        assert command[0] == sys.executable
        assert str(SCRIPT) in command
        assert str(tmp_path) in command
        assert command[command.index("--child-service") + 1] == role
        assert "8123" in command and "5123" in command


@pytest.mark.parametrize("ports", [(0, 5180), (8010, 65536), (8010, 8010)])
def test_invalid_ports_are_rejected_without_io(tmp_path, ports):
    runtime = load_runtime()
    with pytest.raises(ValueError, match="ports"):
        runtime.WorkbenchRuntime(
            ROOT, tmp_path / "no-io", backend_port=ports[0], frontend_port=ports[1]
        )
    assert not (tmp_path / "no-io").exists()


def test_port_conflict_does_not_kill_or_renumber(tmp_path, monkeypatch):
    runtime = load_runtime()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        manager = runtime.WorkbenchRuntime(ROOT, tmp_path, backend_port=listener.getsockname()[1])
        calls = []
        monkeypatch.setattr(runtime.os, "kill", lambda *args: calls.append(args))
        with pytest.raises(RuntimeError, match="port.*occupied"):
            manager.assert_ports_available()
        assert calls == []
        with socket.create_connection(listener.getsockname(), timeout=1):
            pass


def test_closed_listener_with_reusable_port_is_not_reported_as_occupied(tmp_path):
    runtime = load_runtime()
    with socket.socket() as listener, socket.socket() as frontend:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        frontend.bind(("127.0.0.1", 0))
        backend_port, frontend_port = listener.getsockname()[1], frontend.getsockname()[1]
        client = socket.create_connection(listener.getsockname(), timeout=1)
        connection, _ = listener.accept()
        connection.close()
        assert client.recv(1) == b""
        client.close()
    # This local fixture reproduces the measured false-busy bind condition;
    # it makes no claim about which kernel TCP state caused it.
    with socket.socket() as ordinary_probe:
        with pytest.raises(OSError) as busy:
            ordinary_probe.bind(("127.0.0.1", backend_port))
        assert busy.value.errno == errno.EADDRINUSE
    manager = runtime.WorkbenchRuntime(
        ROOT, tmp_path, backend_port=backend_port, frontend_port=frontend_port
    )
    manager.assert_ports_available()


def test_preflight_still_rejects_active_listener_that_uses_reuseaddr(tmp_path, monkeypatch):
    runtime = load_runtime()
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        manager = runtime.WorkbenchRuntime(ROOT, tmp_path, backend_port=port)
        original_config = manager.config.copy()
        signals = []
        monkeypatch.setattr(runtime.os, "kill", lambda *args: signals.append(args))
        with pytest.raises(RuntimeError, match="port.*occupied"):
            manager.assert_ports_available()
        assert signals == [] and manager.config == original_config
        with socket.create_connection(listener.getsockname(), timeout=1):
            pass


def test_ownership_requires_exact_command_created_and_workspace(tmp_path):
    runtime = load_runtime()
    manager = runtime.WorkbenchRuntime(ROOT, tmp_path)
    record = {"service": "relay", "pid": 1234, "created": "birth"}
    snapshot = {"created": "birth", "command": " ".join(manager.command("relay"))}
    assert manager.is_owned(record, snapshot)
    assert not manager.is_owned(record, {**snapshot, "created": "other"})
    assert not manager.is_owned(record, {**snapshot, "command": snapshot["command"] + " foreign"})
    assert not manager.is_owned(
        record, {**snapshot, "command": snapshot["command"].replace(str(tmp_path), "/foreign")}
    )


def test_macos_framework_exec_identity_accepts_only_current_interpreter(tmp_path, monkeypatch):
    runtime = load_runtime()
    manager = runtime.WorkbenchRuntime(ROOT, tmp_path)
    prefix = tmp_path / "Python.framework/Versions/3.11"
    executable = prefix / "Resources/Python.app/Contents/MacOS/Python"
    executable.parent.mkdir(parents=True)
    executable.touch()
    monkeypatch.setattr(runtime.sys, "platform", "darwin")
    monkeypatch.setattr(
        sysconfig, "get_config_var", lambda key: str(prefix) if key == "prefix" else "Python"
    )
    suffix = " ".join(manager.command("relay")[1:])
    record = {"service": "relay", "pid": 1234, "created": "birth"}
    assert manager.is_owned(record, {"created": "birth", "command": f"{executable} {suffix}"})
    assert not manager.is_owned(
        record, {"created": "birth", "command": f"/foreign/Python {suffix}"}
    )


@pytest.mark.parametrize("observation", [None, "reused", "wrong-command", "ps-error"])
def test_stop_never_signals_unverified_or_exited_pid(tmp_path, monkeypatch, observation):
    runtime = load_runtime()
    manager = runtime.WorkbenchRuntime(ROOT, tmp_path)
    manager.prepare_runtime()
    record = {"service": "backend", "pid": 1234, "created": "birth"}
    manager.write_registry([record], state="failed")

    def snapshot(_pid):
        if observation == "ps-error":
            raise RuntimeError("cannot inspect")
        if observation is None:
            return None
        return {"created": "reused" if observation == "reused" else "birth", "command": "foreign"}

    monkeypatch.setattr(runtime, "process_snapshot", snapshot)
    calls = []
    monkeypatch.setattr(runtime.os, "kill", lambda *args: calls.append(args))
    monkeypatch.setattr(
        manager, "postgres", lambda: pytest.fail("must not touch PG before process verification")
    )
    with pytest.raises(RuntimeError):
        manager.stop()
    assert calls == []
    assert manager.read_registry()["services"] == [record]


def test_registry_private_minimal_and_rejects_foreign_owner(tmp_path):
    runtime = load_runtime()
    manager = runtime.WorkbenchRuntime(ROOT, tmp_path)
    manager.prepare_runtime()
    manager.write_registry([], state="stopped")
    path = manager.registry_path
    assert path.stat().st_mode & 0o777 == 0o600
    payload = json.loads(path.read_text())
    assert set(payload) == {
        "version",
        "repo",
        "workspace",
        "uid",
        "config",
        "fingerprint",
        "state",
        "services",
    }
    assert "environment" not in path.read_text() and "dsn" not in path.read_text().lower()
    payload["repo"] = "/foreign"
    path.write_text(json.dumps(payload))
    with pytest.raises(RuntimeError, match="ownership"):
        manager.read_registry()


def test_new_invocation_canonicalizes_parent_alias_and_rejects_symbolic_workspace(
    tmp_path, monkeypatch
):
    runtime = load_runtime()
    actual = tmp_path / "actual"
    profile = actual / "profile"
    profile.mkdir(parents=True)
    alias = tmp_path / "alias"
    alias.symlink_to(actual, target_is_directory=True)
    manager = runtime.WorkbenchRuntime(ROOT, profile)
    manager.prepare_runtime()
    manager.write_registry([], state="stopped")
    second = runtime.WorkbenchRuntime(ROOT, alias / "profile")
    monkeypatch.setattr(
        second, "postgres", lambda: SimpleNamespace(status=lambda: {"running": False})
    )
    assert second.status()["state"] == "stopped"
    symbolic_profile = tmp_path / "symbolic-profile"
    symbolic_profile.symlink_to(profile, target_is_directory=True)
    with pytest.raises(RuntimeError, match="symbolic"):
        runtime.WorkbenchRuntime(ROOT, symbolic_profile).prepare_runtime()


def test_ready_probe_disables_proxy_and_only_reads_bounded_ready_body(tmp_path, monkeypatch):
    runtime = load_runtime()
    handlers = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, size):
            assert size == 65537
            return b'{"status":"ok"}'

    class Opener:
        def open(self, url, timeout):
            assert url == "http://127.0.0.1:8010/api/readyz"
            return Response()

    def build(handler):
        handlers.append(handler.proxies)
        return Opener()

    monkeypatch.setattr(runtime.urllib.request, "build_opener", build)
    assert runtime.WorkbenchRuntime(ROOT, tmp_path).probe_ready()
    assert handlers == [{}]


def lifecycle_fixture(tmp_path, monkeypatch):
    runtime = load_runtime()
    manager = runtime.WorkbenchRuntime(ROOT, tmp_path)
    events, live = [], {}

    class Postgres:
        running = False

        def status(self):
            return {"initialized": True, "running": self.running}

        def start(self):
            self.running = True
            events.append("pg-start")

        def stop(self):
            self.running = False
            events.append("pg-stop")
            return self.status()

        def app_environment(self):
            return {"TASK_CENTER_DATABASE_URL": "app-secret"}

    pg = Postgres()
    monkeypatch.setattr(manager, "postgres", lambda: pg)
    monkeypatch.setattr(manager, "check_dependencies", lambda: None)
    monkeypatch.setattr(manager, "assert_ports_available", lambda: events.append("ports"))
    monkeypatch.setattr(runtime, "process_snapshot", lambda pid: live.get(pid))

    def spawn(role, env):
        events.append(role)
        pid = 1000 + len(live)
        live[pid] = {"created": f"birth-{pid}", "command": " ".join(manager.command(role))}
        return {"service": role, "pid": pid, "created": f"birth-{pid}"}

    monkeypatch.setattr(manager, "spawn", spawn)
    monkeypatch.setattr(manager, "wait_ready", lambda record: events.append("ready"))
    monkeypatch.setattr(
        manager, "wait_relay", lambda record: events.append("relay-ready"), raising=False
    )
    monkeypatch.setattr(manager, "wait_frontend", lambda record: events.append("frontend-ready"))

    def stop_record(record, config=None):
        events.append("stop-" + record["service"])
        live.pop(record["pid"], None)

    monkeypatch.setattr(manager, "stop_record", stop_record)
    return runtime, manager, pg, events, live


def test_start_order_idempotence_and_stop_preserve_data(tmp_path, monkeypatch):
    _, manager, _, events, _ = lifecycle_fixture(tmp_path, monkeypatch)
    data = tmp_path / "retained.db"
    data.write_bytes(b"persistent rows")
    manager.start()
    assert events == [
        "ports",
        "pg-start",
        "backend",
        "ready",
        "relay",
        "relay-ready",
        "frontend",
        "frontend-ready",
    ]
    events.clear()
    manager.start()
    assert events == []
    manager.stop()
    assert events == ["stop-frontend", "stop-relay", "stop-backend", "pg-stop"]
    assert manager.read_registry()["state"] == "stopped"
    assert data.read_bytes() == b"persistent rows"


@pytest.mark.parametrize("preexisting_pg", [False, True])
def test_partial_start_failure_cleans_only_this_attempt(tmp_path, monkeypatch, preexisting_pg):
    _, manager, pg, events, live = lifecycle_fixture(tmp_path, monkeypatch)
    pg.running = preexisting_pg

    def not_ready(record):
        raise RuntimeError("API readiness failed")

    monkeypatch.setattr(manager, "wait_ready", not_ready)
    with pytest.raises(RuntimeError, match="readiness"):
        manager.start()
    assert "stop-backend" in events
    assert ("pg-stop" in events) is (not preexisting_pg)
    assert pg.running is preexisting_pg
    assert live == {}
    assert manager.read_registry()["state"] == "failed"


def test_changed_ports_require_stop_before_spawning(tmp_path, monkeypatch):
    runtime, manager, _, events, _ = lifecycle_fixture(tmp_path, monkeypatch)
    manager.start()
    other = runtime.WorkbenchRuntime(ROOT, tmp_path, backend_port=8129)
    monkeypatch.setattr(other, "postgres", lambda: pytest.fail("config conflict must be first"))
    events.clear()
    with pytest.raises(RuntimeError, match="stop"):
        other.start()
    assert events == []


def test_inactive_registry_can_restart_without_signalling_reused_pid(tmp_path, monkeypatch):
    _, manager, _, events, live = lifecycle_fixture(tmp_path, monkeypatch)
    manager.prepare_runtime()
    manager.write_registry([{"service": "backend", "pid": 4000, "created": "old"}], state="running")
    live[4000] = {"created": "new", "command": "external"}
    manager.start()
    assert "stop-backend" not in events
    assert live[4000]["command"] == "external"


def test_stop_timeout_preserves_registry_and_leaves_pg_running(tmp_path, monkeypatch):
    _, manager, pg, events, _ = lifecycle_fixture(tmp_path, monkeypatch)
    manager.start()
    before = manager.registry_path.read_bytes()

    def timeout(record, config=None):
        raise RuntimeError("shutdown timed out")

    monkeypatch.setattr(manager, "stop_record", timeout)
    with pytest.raises(RuntimeError, match="timed out"):
        manager.stop()
    assert pg.running
    assert "pg-stop" not in events
    assert manager.registry_path.read_bytes() == before


def test_cli_error_does_not_echo_dependency_secrets(tmp_path, monkeypatch, capsys):
    runtime = load_runtime()

    def unavailable(self):
        raise RuntimeError("postgresql://owner:sentinel-secret@db/private")

    monkeypatch.setattr(runtime.WorkbenchRuntime, "postgres", unavailable)
    assert runtime.main(["init", "--execute", "--workspace-dir", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert "sentinel-secret" not in captured.out + captured.err


def test_spawn_identity_failure_retains_unverified_record_and_preexisting_pg(tmp_path, monkeypatch):
    _, manager, pg, _, _ = lifecycle_fixture(tmp_path, monkeypatch)
    pg.running = True
    pending = {"service": "backend", "pid": 5000, "created": "unverified"}

    def spawn_failed(role, env):
        manager._pending_record = pending
        raise RuntimeError("process identity unavailable")

    monkeypatch.setattr(manager, "spawn", spawn_failed)
    monkeypatch.setattr(
        manager, "stop_record", lambda record: (_ for _ in ()).throw(RuntimeError("cannot verify"))
    )
    with pytest.raises(RuntimeError):
        manager.start()
    assert manager.read_registry()["services"] == [pending]
    assert pg.running


def test_retry_partial_stop_accepts_proven_successful_exit(tmp_path, monkeypatch):
    runtime = load_runtime()
    manager = runtime.WorkbenchRuntime(ROOT, tmp_path)
    manager.prepare_runtime()
    record = {"service": "frontend", "pid": 111, "created": "birth"}
    runtime.write_json(
        manager.runtime_dir / "frontend.exit.json",
        {
            "pid": 111,
            "created": "birth",
            "exit_code": 0,
            "shutdown_complete": True,
        },
    )
    monkeypatch.setattr(runtime, "process_snapshot", lambda pid: None)
    monkeypatch.setattr(
        runtime.os, "kill", lambda *args: pytest.fail("already exited; do not signal")
    )
    manager.stop_record(record)


def test_stop_accepts_only_same_birth_zombie_with_completed_shutdown(tmp_path, monkeypatch):
    runtime = load_runtime()
    manager = runtime.WorkbenchRuntime(ROOT, tmp_path)
    manager.prepare_runtime()
    record = {"service": "frontend", "pid": 111, "created": "birth"}
    runtime.write_json(
        manager.runtime_dir / "frontend.exit.json",
        {
            "pid": 111,
            "created": "birth",
            "exit_code": 0,
            "shutdown_complete": True,
        },
    )
    calls = 0

    def snapshot(pid):
        nonlocal calls
        calls += 1
        return (
            {"created": "birth", "command": " ".join(manager.command("frontend")), "state": "S"}
            if calls == 1
            else {"created": "birth", "command": "(Python)", "state": "Z"}
        )

    monkeypatch.setattr(runtime, "process_snapshot", snapshot)
    monkeypatch.setattr(runtime.os, "kill", lambda *args: None)
    manager.stop_record(record)


@pytest.mark.parametrize(
    "exited", [None, {"created": "birth", "command": "(Python)", "state": "Z"}]
)
def test_independent_stop_waits_through_observed_macos_exiting_argv_after_one_term(
    tmp_path,
    monkeypatch,
    exited,
):
    runtime = load_runtime()
    manager = runtime.WorkbenchRuntime(ROOT, tmp_path)
    manager.prepare_runtime()
    assert manager._children == {}, "fresh CLI has no Popen handle to reap the service"
    record = {"service": "frontend", "pid": 111, "created": "birth"}
    runtime.write_json(
        manager.runtime_dir / "frontend.exit.json",
        {
            "pid": 111,
            "created": "birth",
            "exit_code": 0,
            "shutdown_complete": True,
        },
    )
    observations = iter(
        [
            {"created": "birth", "command": " ".join(manager.command("frontend")), "state": "Ss"},
            {"created": "birth", "command": "(Python)", "state": "?Es"},
            {"created": "birth", "command": "(Python)", "state": "?Es"},
            exited,
        ]
    )
    monkeypatch.setattr(runtime, "process_snapshot", lambda pid: next(observations))
    signals, waits = [], []
    monkeypatch.setattr(runtime.os, "kill", lambda *args: signals.append(args))
    monkeypatch.setattr(runtime.time, "sleep", lambda duration: waits.append(duration))
    manager.stop_record(record)
    assert signals == [(111, runtime.signal.SIGTERM)]
    assert len(waits) == 2
    assert json.loads((manager.runtime_dir / "frontend.stop.json").read_text()) == record


def test_exiting_argv_before_first_term_still_fails_ownership_gate(tmp_path, monkeypatch):
    runtime = load_runtime()
    manager = runtime.WorkbenchRuntime(ROOT, tmp_path)
    manager.prepare_runtime()
    record = {"service": "relay", "pid": 111, "created": "birth"}
    runtime.write_json(
        manager.runtime_dir / "relay.exit.json",
        {
            "pid": 111,
            "created": "birth",
            "exit_code": 0,
            "shutdown_complete": True,
        },
    )
    monkeypatch.setattr(
        runtime,
        "process_snapshot",
        lambda pid: {
            "created": "birth",
            "command": "(Python)",
            "state": "?Es",
        },
    )
    monkeypatch.setattr(
        runtime.os, "kill", lambda *args: pytest.fail("identity gate must reject before signal")
    )
    with pytest.raises(RuntimeError, match="ownership"):
        manager.stop_record(record)


@pytest.mark.parametrize(
    "transition",
    [
        {"created": "birth", "command": "(Python)", "state": "?Es"},
        {"created": "birth", "command": "unrecognized", "state": "Ss"},
    ],
)
def test_post_term_transition_with_success_marker_is_not_success_while_still_live(
    tmp_path,
    monkeypatch,
    transition,
):
    runtime = load_runtime()
    manager = runtime.WorkbenchRuntime(ROOT, tmp_path)
    manager.prepare_runtime()
    manager.shutdown_timeout = 0.3
    record = {"service": "relay", "pid": 111, "created": "birth"}
    runtime.write_json(
        manager.runtime_dir / "relay.exit.json",
        {
            "pid": 111,
            "created": "birth",
            "exit_code": 0,
            "shutdown_complete": True,
        },
    )
    calls = 0

    def snapshot(pid):
        nonlocal calls
        calls += 1
        return (
            {"created": "birth", "command": " ".join(manager.command("relay")), "state": "Ss"}
            if calls == 1
            else transition
        )

    clock = iter(i / 10 for i in range(20))
    signals = []
    monkeypatch.setattr(runtime, "process_snapshot", snapshot)
    monkeypatch.setattr(runtime.os, "kill", lambda *args: signals.append(args))
    monkeypatch.setattr(runtime.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(runtime.time, "sleep", lambda duration: None)
    with pytest.raises(RuntimeError, match="timed out"):
        manager.stop_record(record)
    assert signals == [(111, runtime.signal.SIGTERM)]


@pytest.mark.parametrize("failure", ["reused", "ps-error", "bad-exit", "missing-exit"])
def test_post_term_reuse_uncertain_ps_and_unconfirmed_exit_remain_fail_closed(
    tmp_path,
    monkeypatch,
    failure,
):
    runtime = load_runtime()
    manager = runtime.WorkbenchRuntime(ROOT, tmp_path)
    manager.prepare_runtime()
    record = {"service": "relay", "pid": 111, "created": "birth"}
    if failure != "missing-exit":
        runtime.write_json(
            manager.runtime_dir / "relay.exit.json",
            {
                "pid": 111,
                "created": "birth",
                "exit_code": 1 if failure == "bad-exit" else 0,
                "shutdown_complete": True,
            },
        )
    calls = 0

    def snapshot(pid):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "created": "birth",
                "command": " ".join(manager.command("relay")),
                "state": "Ss",
            }
        if failure == "ps-error":
            raise RuntimeError("identity unavailable")
        return (
            {"created": "reused-birth", "command": "foreign", "state": "Ss"}
            if failure == "reused"
            else None
        )

    signals = []
    monkeypatch.setattr(runtime, "process_snapshot", snapshot)
    monkeypatch.setattr(runtime.os, "kill", lambda *args: signals.append(args))
    with pytest.raises(RuntimeError):
        manager.stop_record(record)
    assert signals == [(111, runtime.signal.SIGTERM)]


def test_relay_child_publishes_ready_after_initialization_and_preserves_early_stop(
    tmp_path, monkeypatch
):
    import asyncio

    import scripts

    runtime = load_runtime()
    manager = runtime.WorkbenchRuntime(ROOT, tmp_path)
    manager.prepare_runtime()
    monkeypatch.setattr(
        runtime, "process_snapshot", lambda pid: {"created": "birth", "command": "owned"}
    )
    handlers = {}
    monkeypatch.setattr(
        runtime.signal, "signal", lambda signum, handler: handlers.update({signum: handler})
    )

    async def serve(relay, stop, **kwargs):
        assert stop.is_set(), "early stop must be carried into the initialized relay"

    async def run(concurrency):
        handlers[runtime.signal.SIGTERM](runtime.signal.SIGTERM, None)
        await module.serve(None, asyncio.Event())

    module = SimpleNamespace(run=run, serve=serve)
    monkeypatch.setitem(sys.modules, "scripts.run_submission_relay", module)
    monkeypatch.setattr(scripts, "run_submission_relay", module, raising=False)
    assert runtime.run_child(manager, "relay") == 0
    assert json.loads((manager.runtime_dir / "relay.ready.json").read_text()) == {
        "pid": os.getpid(),
        "created": "birth",
    }


@pytest.mark.parametrize(
    "started,startup_failed,shutdown_failed,expected",
    [
        (True, False, False, 0),
        (False, False, False, 1),
        (True, False, True, 1),
        (True, True, False, 1),
    ],
)
def test_api_child_verifies_lifespan_and_handles_uvicorn_signal_redelivery(
    tmp_path,
    monkeypatch,
    started,
    startup_failed,
    shutdown_failed,
    expected,
):
    runtime = load_runtime()
    manager = runtime.WorkbenchRuntime(ROOT, tmp_path)
    monkeypatch.setattr(
        runtime, "process_snapshot", lambda pid: {"created": "birth", "command": "owned"}
    )
    manager.prepare_runtime()
    runtime.write_json(
        manager.runtime_dir / "backend.stop.json",
        {
            "service": "backend",
            "pid": os.getpid(),
            "created": "birth",
        },
    )
    handlers = {}
    monkeypatch.setattr(
        runtime.signal, "signal", lambda signum, handler: handlers.update({signum: handler})
    )

    class Server:
        def __init__(self, config):
            self.started = started
            self.lifespan = SimpleNamespace(
                startup_failed=startup_failed, shutdown_failed=shutdown_failed
            )

        def run(self):
            handlers[runtime.signal.SIGTERM](runtime.signal.SIGTERM, None)

    monkeypatch.setitem(
        sys.modules, "uvicorn", SimpleNamespace(Config=lambda *args, **kwargs: None, Server=Server)
    )
    assert runtime.run_child(manager, "backend") == expected
    result = json.loads((manager.runtime_dir / "backend.exit.json").read_text())
    assert result["exit_code"] == expected
    assert result["shutdown_complete"] is (expected == 0)
