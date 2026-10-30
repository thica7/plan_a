#!/usr/bin/env python3
"""Private persistent loopback workbench. Every action defaults to preview."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import signal
import socket
import stat
import subprocess
import sys
import sysconfig
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROLES = ("backend", "relay", "frontend")


class WorkbenchError(RuntimeError):
    """An intentionally non-secret diagnostic safe for CLI output."""


def process_snapshot(pid: int) -> dict | None:
    """Fail closed; UTF-8 and UTC keep Chinese argv and birth markers stable on macOS."""
    try:
        result = subprocess.run(
            [
                "/bin/ps",
                "-ww",
                "-p",
                str(pid),
                "-o",
                "lstart=",
                "-o",
                "stat=",
                "-o",
                "args=",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
            check=False,
            env={
                "PATH": os.defpath,
                "LC_ALL": "en_US.UTF-8" if sys.platform == "darwin" else "C.UTF-8",
                "TZ": "UTC",
            },
        )
        if (
            result.returncode == 1
            and not result.stdout.strip()
            and not result.stderr.strip()
        ):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return None
        parts = result.stdout.strip().split(None, 6)
        if result.returncode or result.stderr.strip() or len(parts) != 7:
            raise ValueError
        return {"created": " ".join(parts[:5]), "state": parts[5], "command": parts[6]}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise WorkbenchError(
            "process identity could not be verified; no signal sent"
        ) from None


def check_path(path: Path, *, directory: bool = False) -> None:
    info = path.lstat()
    valid_kind = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if not valid_kind or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise WorkbenchError("workbench ownership or private permissions mismatch")


def write_json(path: Path, payload: dict) -> None:
    if path.exists() or path.is_symlink():
        check_path(path)
    descriptor, temporary = tempfile.mkstemp(prefix=".workbench-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class WorkbenchRuntime:
    def __init__(
        self,
        repo: Path,
        workspace: Path,
        *,
        backend_port: int = 8010,
        frontend_port: int = 5180,
    ):
        if (
            not (1 <= backend_port <= 65535 and 1 <= frontend_port <= 65535)
            or backend_port == frontend_port
        ):
            raise ValueError(
                "backend/frontend ports must be distinct integers in 1..65535"
            )
        self.repo = repo.resolve()
        self._workspace_input = workspace.absolute()
        self.workspace = workspace.resolve()
        self.config = {"backend_port": backend_port, "frontend_port": frontend_port}
        self.runtime_dir = self.workspace / "runtime"
        self.registry_path = self.runtime_dir / "services.json"
        self.shutdown_timeout = 30.0
        self.startup_timeout = 30.0
        self._children: dict[int, subprocess.Popen] = {}
        self._pending_record: dict | None = None

    def fingerprint(self, config: dict | None = None) -> str:
        value = {
            "repo": str(self.repo),
            "workspace": str(self.workspace),
            "config": config or self.config,
            "version": 1,
        }
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    def prepare_runtime(self) -> None:
        if self._workspace_input.is_symlink():
            raise WorkbenchError("symbolic workspace ownership is not allowed")
        # Canonical paths are used in argv and records, including macOS /var aliases.
        self.workspace = self.workspace.resolve()
        self.repo = self.repo.resolve()
        self.runtime_dir = self.workspace / "runtime"
        self.registry_path = self.runtime_dir / "services.json"
        if not self.workspace.exists():
            raise WorkbenchError(
                "workspace must be explicitly initialized before start"
            )
        if self.runtime_dir.exists() or self.runtime_dir.is_symlink():
            check_path(self.runtime_dir, directory=True)
        else:
            self.runtime_dir.mkdir(mode=0o700)
        marker = self.runtime_dir / "owner.json"
        identity = {
            "kind": "persistent-workbench-runtime",
            "repo": str(self.repo),
            "workspace": str(self.workspace),
            "uid": os.getuid(),
            "version": 1,
        }
        if marker.exists() or marker.is_symlink():
            check_path(marker)
            if json.loads(marker.read_text(encoding="utf-8")) != identity:
                raise WorkbenchError("workbench runtime ownership mismatch")
        else:
            if any(self.runtime_dir.iterdir()):
                raise WorkbenchError(
                    "unmarked runtime directory ownership cannot be adopted"
                )
            write_json(marker, identity)

    @contextmanager
    def operation(self):
        self.prepare_runtime()
        path = self.runtime_dir / ".operation.lock"
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "r+") as lock:
            check_path(path)
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            yield

    def read_registry(self) -> dict | None:
        if self._workspace_input.is_symlink():
            raise WorkbenchError("symbolic workspace ownership is not allowed")
        if not self.registry_path.exists() and not self.registry_path.is_symlink():
            return None
        check_path(self.runtime_dir, directory=True)
        check_path(self.registry_path)
        try:
            value = json.loads(self.registry_path.read_text(encoding="utf-8"))
            config = value["config"]
            valid_ports = (
                set(config) == {"backend_port", "frontend_port"}
                and all(
                    type(port) is int and 1 <= port <= 65535 for port in config.values()
                )
                and config["backend_port"] != config["frontend_port"]
            )
            if not valid_ports or any(
                value.get(key) != expected
                for key, expected in {
                    "version": 1,
                    "repo": str(self.repo),
                    "workspace": str(self.workspace),
                    "uid": os.getuid(),
                    "fingerprint": self.fingerprint(config),
                }.items()
            ):
                raise ValueError
            if value["state"] not in {"starting", "running", "stopped", "failed"}:
                raise ValueError
            services = value["services"]
            if not isinstance(services, list) or len(services) > 3:
                raise ValueError
            if len({record["service"] for record in services}) != len(services):
                raise ValueError
            for record in services:
                if (
                    set(record) != {"service", "pid", "created"}
                    or record["service"] not in ROLES
                    or type(record["pid"]) is not int
                    or record["pid"] <= 0
                    or not isinstance(record["created"], str)
                    or not record["created"]
                ):
                    raise ValueError
            return value
        except (ValueError, KeyError, TypeError):
            raise WorkbenchError(
                "workbench registry ownership or schema mismatch"
            ) from None

    def write_registry(
        self, services: list[dict], *, state: str, config: dict | None = None
    ) -> None:
        config = config or self.config
        write_json(
            self.registry_path,
            {
                "version": 1,
                "repo": str(self.repo),
                "workspace": str(self.workspace),
                "uid": os.getuid(),
                "config": config,
                "fingerprint": self.fingerprint(config),
                "state": state,
                "services": services,
            },
        )

    def command(self, role: str, config: dict | None = None) -> list[str]:
        config = config or self.config
        if role not in ROLES:
            raise WorkbenchError("unknown workbench service role")
        return [
            sys.executable,
            str(self.repo / "scripts/workbench_runtime.py"),
            "start",
            "--execute",
            "--workspace-dir",
            str(self.workspace),
            "--backend-port",
            str(config["backend_port"]),
            "--frontend-port",
            str(config["frontend_port"]),
            "--child-service",
            role,
        ]

    def is_owned(
        self, record: dict, snapshot: dict | None, config: dict | None = None
    ) -> bool:
        if (
            not snapshot
            or snapshot.get("created") != record.get("created")
            or record.get("service") not in ROLES
        ):
            return False
        interpreters = {sys.executable, str(Path(sys.executable).resolve())}
        if sys.platform == "darwin" and sysconfig.get_config_var("PYTHONFRAMEWORK"):
            # Homebrew Framework Python execs this real binary after its venv
            # launcher. Derive it from this interpreter, never from registry input.
            framework = (
                Path(sysconfig.get_config_var("prefix"))
                / "Resources/Python.app/Contents/MacOS/Python"
            )
            if framework.is_file():
                interpreters.add(str(framework.resolve()))
        suffix = " ".join(self.command(record["service"], config)[1:])
        return any(
            snapshot.get("command") == f"{interpreter} {suffix}"
            for interpreter in interpreters
        )

    def postgres(self):
        if self._workspace_input.is_symlink():
            raise WorkbenchError("symbolic workspace ownership is not allowed")
        candidates = [
            Path(found).parent
            for name in ("pg_ctl", "pg_config")
            if (found := shutil.which(name))
        ]
        candidates += [
            Path("/opt/homebrew/bin"),
            Path("/usr/local/opt/postgresql@15/bin"),
            Path("/usr/local/bin"),
        ]
        binary_dir = next(
            (
                candidate
                for candidate in candidates
                if all(
                    (candidate / name).is_file()
                    for name in ("initdb", "pg_ctl", "postgres", "pg_config")
                )
            ),
            None,
        )
        if binary_dir is None:
            raise WorkbenchError(
                "native PostgreSQL 15 tools and pgvector are required; install dependencies first"
            )
        sys.path.insert(0, str(self.repo / "backend"))
        from scripts.local_workspace_postgres import PersistentWorkspacePostgres

        return PersistentWorkspacePostgres(self.workspace, binary_dir=binary_dir)

    def check_dependencies(self) -> None:
        if (
            not shutil.which("node")
            or not (self.repo / "frontend/node_modules/vite/bin/vite.js").is_file()
        ):
            raise WorkbenchError(
                "PATH node and installed frontend Vite dependencies are required"
            )
        import importlib.util

        if importlib.util.find_spec("uvicorn") is None:
            raise WorkbenchError(
                "current Python interpreter requires backend dependencies including uvicorn"
            )

    def child_environment(self, environ: dict, app: dict) -> dict[str, str]:
        env = {
            name: environ[name]
            for name in (
                "PATH",
                "HOME",
                "LANG",
                "LC_ALL",
                "LC_CTYPE",
                "TMPDIR",
                "SYSTEMROOT",
            )
            if name in environ
        }
        env.update(app)
        env.update(
            {
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONUNBUFFERED": "1",
                "COMPETISCOPE_LOAD_ENV_FILES": "0",
                "DEMO_MODE": "true",
                "RUN_ORCHESTRATION_BACKEND": "langgraph",
                "AUTH_ENABLED": "false",
                "TASK_CENTER_ENABLED": "true",
                "ENTERPRISE_STORE_BACKEND": "postgres",
                "TASK_CENTER_POOL_MIN_SIZE": "1",
                "TASK_CENTER_POOL_MAX_SIZE": "4",
                "ENTERPRISE_POOL_MAX_SIZE": "4",
                "EXECUTION_CONTROL_ENABLED": "true",
                "EXECUTION_GLOBAL_RUNNING_LIMIT": "2",
                "EXECUTION_WORKSPACE_RUNNING_LIMIT": "1",
                "EXECUTION_CONTROL_JOURNAL_PATH": str(
                    self.workspace / "run_journal.db"
                ),
                "GRAPH_CHECKPOINT_PATH": str(self.workspace / "graph_checkpoints.db"),
                "KB_DB_PATH": str(self.workspace / "knowledge.db"),
                "KB_CACHE_PATH": str(self.workspace / "kb_cache.db"),
                "TRACE_DB_PATH": str(self.workspace / "traces.db"),
                "PREFERENCE_MEMORY_PATH": str(self.workspace / "preference_memory.db"),
                "ARTIFACT_STORAGE_BACKEND": "local",
                "ARTIFACT_STORAGE_ROOT": str(self.workspace / "artifacts"),
                "KB_RETRIEVAL_MODE": "sparse",
                "KB_EMBEDDING_PROVIDER": "hash",
                "KB_RERANKER_PROVIDER": "none",
                "BACKEND_PORT": str(self.config["backend_port"]),
                "FRONTEND_PORT": str(self.config["frontend_port"]),
                "VITE_API_TARGET": f"http://127.0.0.1:{self.config['backend_port']}",
                "COMPETISCOPE_VITE_CACHE_DIR": str(self.workspace / "vite-cache"),
            }
        )
        return env

    def assert_ports_available(self) -> None:
        for port in self.config.values():
            with socket.socket() as probe:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    probe.bind(("127.0.0.1", port))
                except OSError:
                    raise WorkbenchError(
                        f"loopback port {port} occupied; stop its owner or choose explicit ports"
                    ) from None

    def probe_ready(self) -> bool:
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(
                f"http://127.0.0.1:{self.config['backend_port']}/api/readyz", timeout=2
            ) as response:
                body = response.read(65537)
                return (
                    len(body) <= 65536
                    and response.status == 200
                    and json.loads(body).get("status") == "ok"
                )
        except (OSError, ValueError, urllib.error.URLError):
            return False

    def spawn(self, role: str, env: dict) -> dict:
        path = self.runtime_dir / f"{role}.log"
        if path.exists() or path.is_symlink():
            check_path(path)
        descriptor = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(descriptor, "ab") as log:
            child = subprocess.Popen(
                self.command(role),
                cwd=self.repo,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        self._children[child.pid] = child
        # Keep a non-secret fail-closed record even if ps becomes unavailable
        # between Popen and the first verified ownership snapshot.
        self._pending_record = {
            "service": role,
            "pid": child.pid,
            "created": "unverified",
        }
        snapshot = process_snapshot(child.pid)
        if snapshot is None:
            raise WorkbenchError(
                f"{role} exited before process ownership could be recorded"
            )
        record = {"service": role, "pid": child.pid, "created": snapshot["created"]}
        self._pending_record = record
        if not self.is_owned(record, snapshot):
            raise WorkbenchError(f"{role} process ownership mismatch; no signal sent")
        self._pending_record = None
        return record

    def require_live(self, record: dict) -> None:
        child = self._children.get(record["pid"])
        if child is not None and child.poll() is not None:
            raise WorkbenchError(
                f"{record['service']} exited during startup; inspect its private log"
            )
        if not self.is_owned(record, process_snapshot(record["pid"])):
            raise WorkbenchError(
                f"{record['service']} ownership or liveness check failed"
            )

    def wait_ready(self, record: dict) -> None:
        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            self.require_live(record)
            if self.probe_ready():
                return
            time.sleep(0.1)
        raise WorkbenchError("API readiness timed out; inspect its private log")

    def wait_frontend(self, record: dict) -> None:
        deadline = time.monotonic() + self.startup_timeout
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        while time.monotonic() < deadline:
            self.require_live(record)
            try:
                with opener.open(
                    f"http://127.0.0.1:{self.config['frontend_port']}/", timeout=2
                ) as response:
                    if response.status == 200:
                        return
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(0.1)
        raise WorkbenchError("frontend readiness timed out; inspect its private log")

    def wait_relay(self, record: dict) -> None:
        deadline = time.monotonic() + self.startup_timeout
        path = self.runtime_dir / "relay.ready.json"
        while time.monotonic() < deadline:
            self.require_live(record)
            if path.exists() or path.is_symlink():
                check_path(path)
                if json.loads(path.read_text(encoding="utf-8")) == {
                    "pid": record["pid"],
                    "created": record["created"],
                }:
                    return
            time.sleep(0.1)
        raise WorkbenchError("relay readiness timed out; inspect its private log")

    @staticmethod
    def has_exited(record: dict, snapshot: dict | None) -> bool:
        return snapshot is None or (
            snapshot.get("created") == record["created"]
            and snapshot.get("state", "").startswith("Z")
        )

    def exit_result(self, record: dict) -> dict | None:
        path = self.runtime_dir / f"{record['service']}.exit.json"
        if not path.exists() and not path.is_symlink():
            return None
        check_path(path)
        result = json.loads(path.read_text(encoding="utf-8"))
        if (
            result.get("pid") == record["pid"]
            and result.get("created") == record["created"]
        ):
            return result
        return None

    def stop_record(self, record: dict, config: dict | None = None) -> None:
        snapshot = process_snapshot(record["pid"])
        if self.has_exited(record, snapshot):
            result = self.exit_result(record)
            if (
                result
                and result.get("exit_code") == 0
                and result.get("shutdown_complete") is True
            ):
                return
        if not self.is_owned(record, snapshot, config):
            raise WorkbenchError(
                "process ownership unavailable; no signal sent; registry retained"
            )
        write_json(self.runtime_dir / f"{record['service']}.stop.json", record)
        os.kill(record["pid"], signal.SIGTERM)
        deadline = time.monotonic() + self.shutdown_timeout
        while time.monotonic() < deadline:
            child = self._children.get(record["pid"])
            if child is not None:
                child.poll()  # Reap our child, rather than mistaking its zombie for a live service.
            snapshot = process_snapshot(record["pid"])
            if self.has_exited(record, snapshot):
                result = self.exit_result(record)
                if (
                    result
                    and result.get("exit_code") == 0
                    and result.get("shutdown_complete") is True
                ):
                    return
                raise WorkbenchError(
                    "service exited without confirmed graceful shutdown; registry retained"
                )
            # macOS ps can stop reporting our argv while showing the same birth in
            # an exiting state (?Es). After our one verified TERM, wait for
            # actual exit plus the matching shutdown result; never signal again.
            if snapshot.get("created") != record["created"]:
                raise WorkbenchError(
                    "process identity changed while stopping; registry retained"
                )
            time.sleep(0.1)
        raise WorkbenchError(
            "service shutdown timed out; no force kill; registry retained"
        )

    def start(self) -> dict:
        with self.operation():
            registry = self.read_registry()
            if (
                registry
                and registry["state"] != "stopped"
                and registry["config"] != self.config
            ):
                raise WorkbenchError(
                    "port configuration changed; stop this workspace first"
                )
            active = []
            for record in (registry or {}).get("services", []):
                snapshot = process_snapshot(record["pid"])
                if self.is_owned(record, snapshot, registry["config"]):
                    active.append(record)
                elif snapshot and snapshot["created"] == record["created"]:
                    raise WorkbenchError(
                        "process command ownership mismatch; stop and inspect workspace"
                    )
                # Missing/recycled PIDs are inactive records; never signal them.
            if active:
                if (
                    len(active) == 3
                    and {record["service"] for record in active} == set(ROLES)
                    and self.postgres().status()["running"]
                ):
                    return {
                        "state": "running",
                        "config": self.config,
                        "services": active,
                    }
                raise WorkbenchError(
                    "partial workbench already running; stop it before start"
                )
            self.check_dependencies()
            self.assert_ports_available()
            postgres = self.postgres()
            previous = postgres.status()
            if not previous["initialized"]:
                raise WorkbenchError(
                    "workspace must be explicitly initialized before start"
                )
            records = []
            pg_started = False
            self.write_registry(records, state="starting")
            try:
                postgres.start()
                pg_started = not previous["running"]
                env = self.child_environment(
                    dict(os.environ), postgres.app_environment()
                )
                for role in ROLES:
                    record = self.spawn(role, env)
                    records.append(record)
                    self.write_registry(records, state="starting")
                    if role == "backend":
                        self.wait_ready(record)
                    elif role == "relay":
                        self.wait_relay(record)
                    elif role == "frontend":
                        self.wait_frontend(record)
                for record in records:
                    self.require_live(record)
                self.write_registry(records, state="running")
                return {"state": "running", "config": self.config, "services": records}
            except BaseException:
                failed = False
                if self._pending_record is not None:
                    records.append(self._pending_record)
                    self._pending_record = None
                for record in reversed(records):
                    try:
                        child = self._children.get(record["pid"])
                        if child is not None and child.poll() is not None:
                            # A failed startup is still a failure, but an already
                            # reaped child needs no signal or graceful-stop claim.
                            continue
                        self.stop_record(record)
                    except (
                        OSError,
                        ValueError,
                        RuntimeError,
                        subprocess.SubprocessError,
                    ):
                        failed = True
                if pg_started and not failed:
                    postgres.stop()
                self.write_registry(records if failed else [], state="failed")
                if failed:
                    raise WorkbenchError(
                        "start failed and cleanup could not confirm shutdown; "
                        "records and data retained"
                    ) from None
                raise

    def stop(self) -> dict:
        if not self.runtime_dir.exists() and not self.runtime_dir.is_symlink():
            return {
                "state": "stopped",
                "postgres": self.postgres().stop(),
                "services": [],
            }
        with self.operation():
            registry = self.read_registry()
            records = (registry or {}).get("services", [])
            config = (registry or {}).get("config", self.config)
            # Verify every target before stopping any service or PostgreSQL.
            for record in records:
                snapshot = process_snapshot(record["pid"])
                result = (
                    self.exit_result(record)
                    if self.has_exited(record, snapshot)
                    else None
                )
                already_joined = (
                    result
                    and result.get("exit_code") == 0
                    and result.get("shutdown_complete") is True
                )
                if not already_joined and not self.is_owned(record, snapshot, config):
                    raise WorkbenchError(
                        "process ownership unavailable; no signal sent; registry retained"
                    )
            for role in reversed(ROLES):
                for record in records:
                    if record["service"] == role:
                        self.stop_record(record, config)
            postgres = self.postgres().stop()
            self.write_registry([], state="stopped", config=config)
            return {"state": "stopped", "postgres": postgres, "services": []}

    def status(self) -> dict:
        registry = self.read_registry()
        config = (registry or {}).get("config", self.config)
        services = []
        for record in (registry or {}).get("services", []):
            snapshot = process_snapshot(record["pid"])
            state = (
                "running"
                if self.is_owned(record, snapshot, config)
                else "exited"
                if self.has_exited(record, snapshot)
                else "ownership-mismatch"
            )
            result = (
                self.exit_result(record) if self.has_exited(record, snapshot) else None
            )
            services.append(
                {
                    **record,
                    "state": state,
                    "exit_code": result.get("exit_code") if result else None,
                }
            )
        postgres = self.postgres().status()
        state = (
            "running"
            if len(services) == 3
            and all(service["state"] == "running" for service in services)
            and postgres["running"]
            else "stopped"
            if not services and not postgres["running"]
            else "degraded"
        )
        return {
            "state": state,
            "config": config,
            "postgres": postgres,
            "services": services,
        }


def run_child(manager: WorkbenchRuntime, role: str) -> int:
    """Own one service; publish its actual exit outcome for verified graceful stop."""
    manager.prepare_runtime()
    snapshot = process_snapshot(os.getpid())
    if snapshot is None:
        raise WorkbenchError("child process identity unavailable")
    sys.path.insert(0, str(manager.repo / "backend"))
    code = 1
    try:
        if role == "backend":
            import uvicorn

            stopping = False

            def receive_redelivered_signal(_signum, _frame):
                nonlocal stopping
                stopping = True

            # Uvicorn restores these handlers and re-delivers signals *after*
            # lifespan shutdown. Let it return so the outcome can be recorded.
            signal.signal(signal.SIGTERM, receive_redelivered_signal)
            signal.signal(signal.SIGINT, receive_redelivered_signal)
            server = uvicorn.Server(
                uvicorn.Config(
                    "app.main:app",
                    host="127.0.0.1",
                    port=manager.config["backend_port"],
                    timeout_graceful_shutdown=25,
                )
            )
            server.run()
            code = (
                0
                if (
                    stopping
                    and server.started
                    and not server.lifespan.startup_failed
                    and not server.lifespan.shutdown_failed
                )
                else 1
            )
        elif role == "relay":
            stopping = False

            def receive_early_stop(_signum, _frame):
                nonlocal stopping
                stopping = True

            signal.signal(signal.SIGTERM, receive_early_stop)
            signal.signal(signal.SIGINT, receive_early_stop)
            import asyncio

            from scripts import run_submission_relay

            original_serve = run_submission_relay.serve

            async def serve_ready(relay, stop, **kwargs):
                write_json(
                    manager.runtime_dir / "relay.ready.json",
                    {
                        "pid": os.getpid(),
                        "created": snapshot["created"],
                    },
                )
                if stopping:
                    stop.set()
                await original_serve(relay, stop, **kwargs)

            run_submission_relay.serve = serve_ready
            asyncio.run(run_submission_relay.run(2))
            code = 0
        else:
            stopping = False
            child = None

            def stop_child(_signum, _frame):
                nonlocal stopping
                stopping = True
                if child is not None and child.poll() is None:
                    child.terminate()

            signal.signal(signal.SIGTERM, stop_child)
            signal.signal(signal.SIGINT, stop_child)
            node = shutil.which("node")
            if node is None:
                raise WorkbenchError("PATH node is required")
            child = subprocess.Popen(
                [
                    node,
                    str(manager.repo / "frontend/node_modules/vite/bin/vite.js"),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(manager.config["frontend_port"]),
                    "--strictPort",
                ],
                cwd=manager.repo / "frontend",
                stdin=subprocess.DEVNULL,
            )
            if stopping:
                child.terminate()
            result = child.wait()
            code = (
                0
                if stopping and result in (0, -signal.SIGTERM, 128 + signal.SIGTERM)
                else result or 1
            )
    except (Exception, SystemExit):  # noqa: BLE001 - service boundary must record a secret-free failure.
        print(f"{role} service failed; private log retained", file=sys.stderr)
        code = 1
    finally:
        request = manager.runtime_dir / f"{role}.stop.json"
        requested = False
        if request.exists() and not request.is_symlink():
            check_path(request)
            requested = json.loads(request.read_text(encoding="utf-8")) == {
                "service": role,
                "pid": os.getpid(),
                "created": snapshot["created"],
            }
        write_json(
            manager.runtime_dir / f"{role}.exit.json",
            {
                "pid": os.getpid(),
                "created": snapshot["created"],
                "exit_code": code,
                "shutdown_complete": code == 0 and requested,
            },
        )
    return code


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "start", "status", "stop"))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--workspace-dir", type=Path, default=ROOT / "runs/local-workspace"
    )
    parser.add_argument("--backend-port", type=int, default=8010)
    parser.add_argument("--frontend-port", type=int, default=5180)
    parser.add_argument("--child-service", choices=ROLES, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        workspace = (
            args.workspace_dir
            if args.workspace_dir.is_absolute()
            else ROOT / args.workspace_dir
        )
        manager = WorkbenchRuntime(
            ROOT,
            workspace,
            backend_port=args.backend_port,
            frontend_port=args.frontend_port,
        )
        if not args.execute:
            print(
                json.dumps(
                    {
                        "mode": "preview",
                        "action": args.action,
                        "workspace": str(workspace),
                        "config": manager.config,
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        if args.child_service:
            return run_child(manager, args.child_service)
        if args.action == "init":
            result = manager.postgres().initialise()
        else:
            result = getattr(manager, args.action)()
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except WorkbenchError as error:
        print(f"workbench: {error}", file=sys.stderr)
    except Exception:  # noqa: BLE001 - CLI boundary must never echo injected DSNs or credentials.
        print(
            "workbench: configuration or dependency operation failed; "
            "owned records and data retained",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
