#!/usr/bin/env python3
"""Local development services with repository-scoped PID ownership."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def env_values(root: Path, environ: dict) -> dict:
    values = {}
    path = root / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("\"'")
    values.update(environ)
    return values


def bind_url(value: str) -> str:
    host, _, port = value.rpartition(":")
    if not port:
        port, host = value, "127.0.0.1"
    elif not host or host in {"0.0.0.0", "[::]", "::"}:
        host = "127.0.0.1"
    return f"http://{host}:{port}"


def resolve_config(
    root: Path, environ: dict, backend_port=None, frontend_port=None, qdrant_port=None
) -> dict:
    values = env_values(root, environ)
    backend = int(
        backend_port if backend_port is not None else values.get("BACKEND_PORT", 8000)
    )
    frontend = int(
        frontend_port
        if frontend_port is not None
        else values.get("FRONTEND_PORT", 5173)
    )
    if not 1 <= backend <= 65535 or not 1 <= frontend <= 65535 or backend == frontend:
        raise ValueError("backend/frontend ports must be distinct integers in 1..65535")
    qdrant_url = values.get("QDRANT_URL") or bind_url(
        values.get("QDRANT_BIND", "127.0.0.1:6333")
    )
    if qdrant_port is not None:
        if not 1 <= qdrant_port <= 65535:
            raise ValueError("qdrant port must be in 1..65535")
        qdrant_url = f"http://127.0.0.1:{qdrant_port}"
    kb_path = Path(values.get("KB_DB_PATH") or "runs/knowledge.db")
    return {
        "backend_port": backend,
        "frontend_port": frontend,
        "api_target": f"http://127.0.0.1:{backend}",
        "qdrant_url": qdrant_url.rstrip("/"),
        "kb_db_path": str(kb_path if kb_path.is_absolute() else root / kb_path),
        "temporal_ui_url": bind_url(values.get("TEMPORAL_UI_BIND", "127.0.0.1:8233")),
    }


def registry_path(root: Path) -> Path:
    return root / "logs/runtime/services.json"


def write_registry(root: Path, registry: dict) -> None:
    path = registry_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    temporary.replace(path)


def read_registry(root: Path) -> dict:
    path = registry_path(root)
    if not path.exists():
        return {"root": str(root), "config": {}, "services": []}
    registry = json.loads(path.read_text(encoding="utf-8"))
    if registry.get("root") != str(root):
        raise RuntimeError(
            "PID registry belongs to another repository; refusing to use it"
        )
    if not isinstance(registry.get("services"), list):
        raise TypeError("Invalid PID registry; refusing to use it")
    for record in registry["services"]:
        if (
            not isinstance(record, dict)
            or record.get("name") not in {"backend", "frontend", "temporal-worker"}
            or not isinstance(record.get("pid"), int)
            or record["pid"] <= 0
            or not isinstance(record.get("created"), str)
            or not record["created"]
        ):
            raise ValueError("Invalid PID ownership record; refusing to use it")
    return registry


def status_config(root: Path, environ: dict) -> dict:
    return read_registry(root).get("config") or resolve_config(root, environ)


def service_commands(root: Path, config: dict, python: str, node: str) -> dict:
    return {
        "backend": [
            python,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(config["backend_port"]),
            "--app-dir",
            str(root / "backend"),
        ],
        "temporal-worker": [
            python,
            str(root / "backend/scripts/run_temporal_worker.py"),
        ],
        "frontend": [
            node,
            str(root / "frontend/node_modules/vite/bin/vite.js"),
            "--host",
            "127.0.0.1",
            "--port",
            str(config["frontend_port"]),
            "--strictPort",
        ],
    }


def service_environment(root: Path, config: dict, environ: dict) -> dict:
    return {
        **env_values(root, environ),
        "BACKEND_PORT": str(config["backend_port"]),
        "FRONTEND_PORT": str(config["frontend_port"]),
        "VITE_API_TARGET": config["api_target"],
        "QDRANT_URL": config["qdrant_url"],
        "KB_DB_PATH": config["kb_db_path"],
    }


def process_snapshot(pid: int) -> dict | None:
    if not isinstance(pid, int) or pid <= 0:
        return None
    try:
        if os.name == "nt":
            query = (
                "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
                "$ErrorActionPreference='Stop'; "
                f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={pid}'; "
                "if($p){[pscustomobject]@{command=$p.CommandLine; "
                "created=$p.CreationDate.ToUniversalTime().ToString('o')}|ConvertTo-Json -Compress}"
            )
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", query],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True,
            )
            return (
                json.loads(result.stdout.lstrip("\ufeff"))
                if result.stdout.strip()
                else None
            )
        result = subprocess.run(
            ["ps", "-ww", "-p", str(pid), "-o", "lstart=", "-o", "args="],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode and result.stderr.strip():
            raise RuntimeError(f"Cannot inspect pid={pid}: {result.stderr.strip()}")
        parts = result.stdout.strip().split(None, 5)
        if result.returncode or len(parts) != 6:
            return None
        return {"created": " ".join(parts[:5]), "command": parts[5]}
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise RuntimeError(
            f"Cannot inspect pid={pid}; ownership cannot be verified"
        ) from error


def is_owned(record: dict, snapshot: dict | None, root: Path) -> bool:
    if (
        not snapshot
        or not record.get("created")
        or record.get("created") != snapshot.get("created")
    ):
        return False
    command = snapshot.get("command") or ""
    markers = {
        "backend": str(root / "backend"),
        "temporal-worker": str(root / "backend/scripts/run_temporal_worker.py"),
        "frontend": str(root / "frontend/node_modules/vite/bin/vite.js"),
    }
    marker = markers.get(record.get("name"))
    # The creation marker prevents a recycled PID from inheriting project ownership.
    normalized = os.path.normcase(command)
    return bool(
        marker
        and re.search(
            re.escape(os.path.normcase(marker)) + r"(?=$|[\s\"'])", normalized
        )
        and (
            record.get("name") != "backend"
            or ("uvicorn" in command and "app.main:app" in command)
        )
    )


def port_owners(port: int) -> list[str]:
    """Read listener PIDs for diagnostics only; these are never stop targets."""
    try:
        if os.name == "nt":
            query = f"@(Get-NetTCPConnection -State Listen -LocalPort {port} -ErrorAction SilentlyContinue).OwningProcess | ConvertTo-Json -Compress"
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", query],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            values = json.loads(result.stdout) if result.stdout.strip() else []
            pids = values if isinstance(values, list) else [values]
        elif shutil.which("lsof"):
            result = subprocess.run(
                ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            pids = result.stdout.split()
        elif shutil.which("ss"):
            result = subprocess.run(
                ["ss", "-H", "-ltnp", f"sport = :{port}"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            pids = re.findall(r"pid=(\d+)", result.stdout)
        else:
            pids = []
        return [
            f"pid={pid}" for pid in sorted({int(pid) for pid in pids if int(pid) > 0})
        ]
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []


def assert_ports_available(config: dict) -> None:
    for name in ("backend", "frontend"):
        port = config[f"{name}_port"]
        try:
            with socket.socket() as listener:
                if os.name != "nt":
                    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind(("127.0.0.1", port))
                listener.listen()
        except OSError as error:
            owners = (
                ", ".join(port_owners(port))
                or "owner unavailable (check system permissions)"
            )
            raise RuntimeError(
                f"{name} port {port} is occupied by {owners}; select another port or stop its owner explicitly. No process was killed."
            ) from error


def terminate_process(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass


def fetch_json(url: str):
    with urllib.request.urlopen(url, timeout=3) as response:
        return json.load(response)


def assert_no_active_runs(config: dict, lookback_hours: int) -> None:
    try:
        runs = fetch_json(f"{config['api_target']}/api/runs")
    except (OSError, ValueError) as error:
        raise RuntimeError(
            "Cannot verify active runs; use --force only if interrupting this project's runs is intended"
        ) from error
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    active = []
    for run in runs:
        if run.get("status") not in {"queued", "running"}:
            continue
        timestamp = run.get("updated_at") or run.get("created_at")
        try:
            updated_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            if updated_at.astimezone(timezone.utc) < cutoff:
                continue
        except (AttributeError, ValueError):
            pass
        active.append(str(run.get("id")))
    if active:
        raise RuntimeError(
            f"Active runs: {', '.join(active[:5])}. Use --force only to interrupt them intentionally."
        )


def stop_services(root: Path, force=False, lookback_hours=6) -> None:
    registry = read_registry(root)
    services = registry["services"]
    snapshots = {record["pid"]: process_snapshot(record["pid"]) for record in services}
    unowned = [
        str(record["pid"])
        for record in services
        if snapshots[record["pid"]]
        and not is_owned(record, snapshots[record["pid"]], root)
    ]
    if unowned:
        raise RuntimeError(
            f"PID ownership could not be verified: {', '.join(unowned)}. No process was killed; inspect logs/runtime/services.json."
        )
    if not force and any(
        record["name"] == "backend" and snapshots[record["pid"]] for record in services
    ):
        assert_no_active_runs(registry["config"], lookback_hours)
    remaining = []
    for record in reversed(services):
        snapshot = process_snapshot(record["pid"])
        if not snapshot:
            continue
        if not is_owned(record, snapshot, root):
            remaining.append(record)
            continue
        terminate_process(record["pid"])
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and is_owned(
            record, process_snapshot(record["pid"]), root
        ):
            time.sleep(0.1)
        if is_owned(record, process_snapshot(record["pid"]), root):
            remaining.append(record)
        else:
            print(f"[plan_a] stopped {record['name']} pid={record['pid']}")
    registry["services"] = remaining
    write_registry(root, registry)
    if remaining:
        raise RuntimeError(
            "Some recorded services did not stop; ownership records were retained"
        )


def wait_http(url: str, timeout=40) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if 200 <= response.status < 300:
                    return
        except OSError:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"Readiness timed out: {url}; see logs/runtime")


def print_endpoints(config: dict) -> None:
    print(f"Frontend:    http://127.0.0.1:{config['frontend_port']}")
    print(f"Backend:     {config['api_target']}")
    print(f"API proxy:   {config['api_target']}")
    print(f"Temporal UI: {config['temporal_ui_url']}")
    print(f"Qdrant:      {config['qdrant_url']}")
    print(f"KB SQLite:   {config['kb_db_path']}")


def start_services(root: Path, args) -> None:
    config = resolve_config(
        root, os.environ, args.backend_port, args.frontend_port, args.qdrant_port
    )
    if not args.no_clean:
        stop_services(root, args.force, args.active_run_lookback_hours)
    elif any(
        process_snapshot(record["pid"]) for record in read_registry(root)["services"]
    ):
        raise RuntimeError(
            "Recorded services are still running; stop them before using --no-clean"
        )
    assert_ports_available(config)
    python = os.environ.get("PYTHON_EXECUTABLE") or sys.executable
    node = os.environ.get("NODE_EXECUTABLE") or shutil.which("node")
    if not node or not (root / "frontend/node_modules/vite/bin/vite.js").exists():
        raise RuntimeError(
            "Node.js or frontend/node_modules/vite is missing; install frontend dependencies first"
        )
    if not args.no_docker:
        subprocess.run(
            [
                "docker",
                "compose",
                "up",
                "-d",
                "--wait",
                "postgres",
                "temporal",
                "temporal-ui",
                "qdrant",
            ],
            cwd=root,
            check=True,
        )
    registry = {"root": str(root), "config": config, "services": []}
    write_registry(root, registry)
    processes = []
    try:
        for name, command in service_commands(root, config, python, node).items():
            log_dir = registry_path(root).parent
            with (
                (log_dir / f"{name}.out.log").open("ab") as stdout,
                (log_dir / f"{name}.err.log").open("ab") as stderr,
            ):
                process = subprocess.Popen(
                    command,
                    cwd=root / "frontend" if name == "frontend" else root,
                    env=service_environment(root, config, os.environ),
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                    if os.name == "nt"
                    else 0,
                    start_new_session=os.name != "nt",
                )
            processes.append(process)
            snapshot = process_snapshot(process.pid)
            if not snapshot:
                raise RuntimeError(f"Could not record {name} pid={process.pid}")
            registry["services"].append({"name": name, "pid": process.pid, **snapshot})
            write_registry(root, registry)
            print(f"[plan_a] {name} pid={process.pid}")
        if not args.no_health_check:
            wait_http(f"{config['api_target']}/api/health")
            wait_http(f"http://127.0.0.1:{config['frontend_port']}")
            if not args.no_docker:
                wait_http(f"{config['qdrant_url']}/readyz")
                wait_http(config["temporal_ui_url"])
        for process in processes:
            if process.poll() is not None:
                raise RuntimeError(
                    f"Service pid={process.pid} exited; see logs/runtime"
                )
    except BaseException:
        # These handles were created by this invocation, including a PID not yet recorded.
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
        registry["services"] = []
        write_registry(root, registry)
        raise
    print("[plan_a] started" if args.no_health_check else "[plan_a] ready")
    print_endpoints(config)


def show_status(root: Path) -> None:
    config = status_config(root, os.environ)
    print_endpoints(config)
    for name in ("backend", "frontend"):
        owners = ", ".join(port_owners(config[f"{name}_port"])) or "no visible listener"
        print(f"{name} port={config[f'{name}_port']} listener={owners}")
    for record in read_registry(root)["services"]:
        snapshot = process_snapshot(record["pid"])
        state = (
            "owned"
            if is_owned(record, snapshot, root)
            else "unverified"
            if snapshot
            else "stopped"
        )
        print(f"{record['name']}: pid={record['pid']} ownership={state}")
    for url in (
        f"{config['api_target']}/api/health",
        f"http://127.0.0.1:{config['frontend_port']}",
        f"{config['qdrant_url']}/readyz",
        config["temporal_ui_url"],
    ):
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                print(f"HTTP {response.status} {url}")
        except OSError as error:
            print(f"HTTP unavailable {url}: {error}")
    try:
        runtime = fetch_json(f"{config['api_target']}/api/runtime")
        fields = (
            "default_execution_mode",
            "run_orchestration_backend",
            "temporal_traffic_percent",
            "demo_mode",
            "web_search_provider",
        )
        print("Runtime: " + ", ".join(f"{key}={runtime.get(key)}" for key in fields))
        runs = fetch_json(f"{config['api_target']}/api/runs")
        active = [
            f"{run.get('id')} status={run.get('status')}"
            for run in runs
            if run.get("status") in {"queued", "running"}
        ]
        print("Active runs: " + (", ".join(active) or "none"))
    except (OSError, ValueError) as error:
        print(f"Runtime/run status unavailable: {error}")
    if shutil.which("docker"):
        subprocess.run(["docker", "compose", "ps"], cwd=root, check=False)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop", "status"])
    parser.add_argument("--backend-port", type=int)
    parser.add_argument("--frontend-port", type=int)
    parser.add_argument("--qdrant-port", type=int)
    parser.add_argument("--active-run-lookback-hours", type=int, default=6)
    for flag in ("no-docker", "no-clean", "no-health-check", "force", "stop-docker"):
        parser.add_argument(f"--{flag}", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action == "start":
            start_services(ROOT, args)
        elif args.action == "stop":
            stop_services(ROOT, args.force, args.active_run_lookback_hours)
            if args.stop_docker:
                subprocess.run(
                    [
                        "docker",
                        "compose",
                        "stop",
                        "temporal-ui",
                        "temporal",
                        "postgres",
                        "qdrant",
                    ],
                    cwd=ROOT,
                    check=True,
                )
        else:
            show_status(ROOT)
    except (
        OSError,
        ValueError,
        TypeError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as error:
        print(f"[plan_a] {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
