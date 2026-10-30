"""Persistent native PG15 for a same-OS-user, private-socket local workspace.

The owner connection exists only during explicit initialization. Nothing here
removes data, adopts an existing cluster, downloads dependencies, or opens TCP.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg.conninfo import make_conninfo

from packages.enterprise.postgres import EnterprisePostgresStore
from packages.task_center.connection_logging import protected_connection_logging
from packages.task_center.migrations import apply_migrations
from scripts.migrate_task_center import grant_application_role

_OWNER = "plan_a_workspace_owner"
_APP = "plan_a_workspace_app"
_DATABASE = "plan_a_workspace"
_KIND = "plan-a-persistent-postgres"


class WorkspacePostgresError(RuntimeError):
    """A sanitized dependency, ownership, process, or initialization failure."""


class PersistentWorkspacePostgres:
    """Own one durable cluster; constructing this object performs no IO."""

    def __init__(self, root: Path, *, binary_dir: Path) -> None:
        self.root = Path(os.path.abspath(root))
        self.binary_dir = Path(os.path.abspath(binary_dir))
        self._set_paths()

    def _set_paths(self) -> None:
        self.postgres_dir = self.root / "postgres"
        self.data_dir = self.postgres_dir / "data"
        self.marker_path = self.postgres_dir / ".workspace-postgres.json"
        self.process_path = self.postgres_dir / "process.json"
        digest = hashlib.sha256(os.fsencode(self.root)).hexdigest()[:20]
        temporary = Path("/private/tmp" if sys.platform == "darwin" else "/tmp")
        self.socket_dir = temporary / f"pwpg-{os.getuid()}-{digest}"

    @staticmethod
    def _check_path(path: Path, *, directory: bool = False, private: bool = False) -> None:
        try:
            info = path.lstat()
        except OSError:
            raise WorkspacePostgresError(
                "workspace PostgreSQL ownership cannot be verified"
            ) from None
        valid_kind = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
        expected = 0o700 if directory else 0o600
        if (
            not valid_kind
            or info.st_uid != os.getuid()
            or (private and stat.S_IMODE(info.st_mode) != expected)
        ):
            raise WorkspacePostgresError("workspace PostgreSQL ownership or symbolic path mismatch")

    @classmethod
    def _read_json(cls, path: Path) -> dict:
        cls._check_path(path, private=True)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise WorkspacePostgresError(
                "workspace PostgreSQL ownership record is invalid"
            ) from None
        if not isinstance(value, dict):
            raise WorkspacePostgresError("workspace PostgreSQL ownership record is invalid")
        return value

    @classmethod
    def _write_json(cls, path: Path, value: dict) -> None:
        if path.exists() or path.is_symlink():
            cls._check_path(path, private=True)
        temporary = path.with_name(path.name + ".tmp")
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(path)
        except OSError:
            raise WorkspacePostgresError(
                "workspace PostgreSQL ownership record could not be saved"
            ) from None

    def _marker(self) -> dict:
        self._check_path(self.root, directory=True)
        self._check_path(self.postgres_dir, directory=True, private=True)
        marker = self._read_json(self.marker_path)
        if (
            marker.get("kind") != _KIND
            or marker.get("version") != 1
            or marker.get("uid") != os.getuid()
            or marker.get("root") != str(self.root)
            or type(marker.get("initialized")) is not bool
        ):
            raise WorkspacePostgresError("workspace PostgreSQL ownership marker mismatch")
        if self.data_dir.exists() or self.data_dir.is_symlink():
            self._check_path(self.data_dir, directory=True, private=True)
        elif marker["initialized"]:
            raise WorkspacePostgresError("workspace PostgreSQL ownership data directory is missing")
        if self.socket_dir.exists() or self.socket_dir.is_symlink():
            self._check_socket()
        return marker

    @contextmanager
    def _operation(self, *, create: bool = False) -> Iterator[dict | None]:
        if self.root.is_symlink():
            raise WorkspacePostgresError("workspace PostgreSQL symbolic root is not allowed")
        self.root = self.root.resolve()
        self._set_paths()
        if not self.root.exists():
            if not create:
                yield None
                return
            self.root.mkdir(parents=True, mode=0o700)
        self._check_path(self.root, directory=True)
        if not self.postgres_dir.exists() and not self.postgres_dir.is_symlink():
            if not create:
                yield None
                return
            self.postgres_dir.mkdir(mode=0o700)
            self._write_json(
                self.marker_path,
                {
                    "kind": _KIND,
                    "version": 1,
                    "uid": os.getuid(),
                    "root": str(self.root),
                    "initialized": False,
                },
            )
        self._marker()
        lock_path = self.postgres_dir / ".operation.lock"
        try:
            fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        except OSError:
            raise WorkspacePostgresError("workspace PostgreSQL ownership lock is unsafe") from None
        with os.fdopen(fd, "r+") as lock:
            self._check_path(lock_path, private=True)
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            yield self._marker()

    def _run(self, binary: str, *args: str) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                [str(self.binary_dir / binary), *args],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise WorkspacePostgresError(f"workspace PostgreSQL {binary} could not run") from None
        if result.returncode:
            raise WorkspacePostgresError(
                f"workspace PostgreSQL {binary} failed (exit {result.returncode}); "
                "owned data retained for diagnosis"
            )
        return result

    def _check_tools(self, *, vector: bool = False) -> None:
        for binary in ("initdb", "pg_ctl", "postgres"):
            output = self._run(binary, "--version").stdout
            if not re.search(r"\b15\.\d+\b", output):
                raise WorkspacePostgresError(
                    "workspace PostgreSQL requires native PostgreSQL 15 tools"
                )
        if vector:
            sharedir = Path(self._run("pg_config", "--sharedir").stdout.strip())
            pkglibdir = Path(self._run("pg_config", "--pkglibdir").stdout.strip())
            if not (
                (sharedir / "extension/vector.control").is_file()
                and (pkglibdir / "vector.so").is_file()
            ):
                raise WorkspacePostgresError(
                    "workspace PostgreSQL 15 pgvector extension is missing"
                )

    def _ensure_socket(self) -> None:
        marker = self.socket_dir / ".workspace-postgres-socket"
        if not self.socket_dir.exists() and not self.socket_dir.is_symlink():
            self.socket_dir.mkdir(mode=0o700)
            self._write_json(marker, {"kind": _KIND, "root": str(self.root), "uid": os.getuid()})
        self._check_socket()

    def _check_socket(self) -> None:
        self._check_path(self.socket_dir, directory=True, private=True)
        marker = self.socket_dir / ".workspace-postgres-socket"
        if self._read_json(marker) != {"kind": _KIND, "root": str(self.root), "uid": os.getuid()}:
            raise WorkspacePostgresError("workspace PostgreSQL socket ownership mismatch")

    def _check_cluster(self) -> None:
        self._check_path(self.data_dir, directory=True, private=True)
        for name in ("PG_VERSION", "postgresql.conf", "pg_hba.conf", "pg_ident.conf"):
            self._check_path(self.data_dir / name)
        if (self.data_dir / "PG_VERSION").read_text().strip() != "15":
            raise WorkspacePostgresError("workspace PostgreSQL data requires PostgreSQL 15")
        for path in (self.data_dir / "postgresql.auto.conf", self.postgres_dir / "postgres.log"):
            if path.exists() or path.is_symlink():
                self._check_path(path)

    @staticmethod
    def _snapshot(pid: int) -> dict | None:
        try:
            result = subprocess.run(
                ["/bin/ps", "-ww", "-p", str(pid), "-o", "lstart=", "-o", "args="],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
                env={
                    **os.environ,
                    "LC_ALL": ("en_US.UTF-8" if sys.platform == "darwin" else "C.UTF-8"),
                    "TZ": "UTC",
                },
            )
            if result.returncode == 1 and not result.stdout.strip() and not result.stderr.strip():
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    return None
            parts = result.stdout.strip().split(None, 5)
            if result.returncode or result.stderr.strip() or len(parts) != 6:
                raise ValueError
            created = " ".join(parts[:5])
            epoch = int(
                datetime.strptime(created, "%a %b %d %H:%M:%S %Y").replace(tzinfo=UTC).timestamp()
            )
            return {"created": created, "command": parts[5], "epoch": epoch}
        except (OSError, ValueError, subprocess.TimeoutExpired):
            raise WorkspacePostgresError(
                "could not verify workspace PostgreSQL process identity"
            ) from None

    def _pid_record(self) -> dict | None:
        pid_path = self.data_dir / "postmaster.pid"
        if not pid_path.exists() and not pid_path.is_symlink():
            return None
        self._check_path(pid_path)
        try:
            lines = pid_path.read_text().splitlines()
            pid, started = int(lines[0]), int(lines[2])
            if (
                pid <= 1
                or started <= 0
                or lines[1] != str(self.data_dir)
                or lines[3] != "5432"
                or lines[4] != str(self.socket_dir)
            ):
                raise ValueError
        except (OSError, ValueError, IndexError):
            raise WorkspacePostgresError(
                "workspace PostgreSQL PID data identity mismatch"
            ) from None
        return {"pid": pid, "started": started, "pgdata": str(self.data_dir)}

    def _command_matches(self, command: str) -> bool:
        for binary in (self.binary_dir / "postgres", (self.binary_dir / "postgres").resolve()):
            prefix = f"{binary} -D {self.data_dir}"
            if command == prefix or command.startswith(prefix + " "):
                return True
        return False

    def _running(self, *, capture: bool = False) -> int | None:
        pid_record = self._pid_record()
        record = None
        if self.process_path.exists() or self.process_path.is_symlink():
            record = self._read_json(self.process_path)
        if pid_record is None:
            if record is not None:
                pid = record.get("pid")
                if type(pid) is not int or pid <= 1 or self._snapshot(pid) is not None:
                    raise WorkspacePostgresError("workspace PostgreSQL PID identity is incomplete")
            return None
        snapshot = self._snapshot(pid_record["pid"])
        if snapshot is None:
            return None
        if (
            not self._command_matches(snapshot["command"])
            or abs(snapshot["epoch"] - pid_record["started"]) > 5
        ):
            raise WorkspacePostgresError("workspace PostgreSQL process identity mismatch")
        expected = {**pid_record, "created": snapshot["created"], "command": snapshot["command"]}
        if capture:
            self._write_json(self.process_path, expected)
        elif record != expected:
            raise WorkspacePostgresError("workspace PostgreSQL recorded PID identity mismatch")
        return pid_record["pid"]

    def _status(self, marker: dict | None) -> dict:
        running = self._running() is not None if marker is not None else False
        initialized = marker["initialized"] if marker is not None else False
        return {
            "state": "running" if running else ("stopped" if initialized else "uninitialized"),
            "initialized": initialized,
            "running": running,
        }

    def status(self) -> dict:
        """Read ownership and live process identity; never expose connection details."""
        with self._operation() as marker:
            return self._status(marker)

    def _start(self) -> None:
        if self._running() is not None:
            return
        self._check_cluster()
        self._ensure_socket()
        options = (
            "-c listen_addresses='' "
            f"-c unix_socket_directories='{self.socket_dir}' "
            "-c unix_socket_permissions=0700 -c max_connections=32"
        )
        try:
            self._run(
                "pg_ctl",
                "-D",
                str(self.data_dir),
                "-l",
                str(self.postgres_dir / "postgres.log"),
                "-w",
                "-t",
                "15",
                "-o",
                options,
                "start",
            )
        except WorkspacePostgresError:
            # pg_ctl may time out after creating a server. Capture only a server
            # matching our data, command and creation time before attempting stop.
            if self._running(capture=True) is not None:
                self._stop()
            raise
        if self._running(capture=True) is None:
            raise WorkspacePostgresError("workspace PostgreSQL did not publish a live owned PID")

    def start(self) -> dict:
        with self._operation() as marker:
            if marker is None or not marker["initialized"]:
                raise WorkspacePostgresError("workspace PostgreSQL must be explicitly initialized")
            if self._running() is None:
                self._check_tools()
                self._start()
            return self._status(marker)

    def _stop(self) -> None:
        if self._running() is not None:
            self._run("pg_ctl", "-D", str(self.data_dir), "-m", "fast", "-w", "-t", "15", "stop")
            if self._pid_record() is not None:
                raise WorkspacePostgresError(
                    "workspace PostgreSQL did not stop; owned data retained"
                )
            # pg_ctl -w confirmed this verified server exited. Retire only its
            # registry so an unrelated future reuse of its PID cannot block start.
            self._check_path(self.process_path, private=True)
            self.process_path.unlink()
        if self._running() is not None:
            raise WorkspacePostgresError("workspace PostgreSQL did not stop; owned data retained")

    def stop(self) -> dict:
        """Stop only the verified server and preserve every database file."""
        with self._operation() as marker:
            if marker is not None:
                self._stop()
            return self._status(marker)

    def _conninfo(self, *, owner: bool = False, database: str = _DATABASE) -> str:
        return make_conninfo(
            host=str(self.socket_dir),
            port=5432,
            dbname=database,
            user=_OWNER if owner else _APP,
            connect_timeout=3,
        )

    def _initialize_schema(self) -> None:
        owner_url = self._conninfo(owner=True)
        with protected_connection_logging():
            with psycopg.connect(
                self._conninfo(owner=True, database="postgres"), autocommit=True
            ) as conn:
                if (
                    conn.execute(
                        "SELECT 1 FROM pg_database WHERE datname=%s", (_DATABASE,)
                    ).fetchone()
                    is None
                ):
                    conn.execute("CREATE DATABASE plan_a_workspace OWNER plan_a_workspace_owner")
            with psycopg.connect(owner_url) as conn:
                if (
                    conn.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (_APP,)).fetchone()
                    is None
                ):
                    conn.execute(
                        "CREATE ROLE plan_a_workspace_app LOGIN NOSUPERUSER NOBYPASSRLS "
                        "NOINHERIT NOCREATEDB NOCREATEROLE NOREPLICATION"
                    )
                conn.execute("REVOKE ALL ON DATABASE plan_a_workspace FROM PUBLIC")
                conn.execute("GRANT CONNECT ON DATABASE plan_a_workspace TO plan_a_workspace_app")
                conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            store = EnterprisePostgresStore(owner_url, auto_migrate=False, pool_max_size=1)
            try:
                store.migrate()
            finally:
                store.close()
            apply_migrations(owner_url)
            with psycopg.connect(owner_url) as conn:
                conn.execute("GRANT USAGE ON SCHEMA public TO plan_a_workspace_app")
                conn.execute(
                    "GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES "
                    "IN SCHEMA public TO plan_a_workspace_app"
                )
                conn.execute(
                    "GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO plan_a_workspace_app"
                )
            grant_application_role(owner_url, _APP)

    def initialise(self) -> dict:
        """Explicit owner-only schema installation, safely retryable without reset."""
        with self._operation(create=True) as marker:
            assert marker is not None
            if marker["initialized"]:
                return self._status(marker)
            self._check_tools(vector=True)
            if not (self.data_dir / "PG_VERSION").exists():
                if self.data_dir.exists() and any(self.data_dir.iterdir()):
                    raise WorkspacePostgresError(
                        "workspace PostgreSQL partial data retained; refusing to reset initdb"
                    )
                self._run(
                    "initdb",
                    "-D",
                    str(self.data_dir),
                    "-U",
                    _OWNER,
                    "--auth-local=trust",
                    "--auth-host=reject",
                    "--encoding=UTF8",
                    "--no-locale",
                )
            started_here = self._running() is None
            try:
                self._start()
                try:
                    self._initialize_schema()
                except Exception:
                    raise WorkspacePostgresError(
                        "workspace PostgreSQL schema initialization failed; owned data retained"
                    ) from None
                marker["initialized"] = True
                self._write_json(self.marker_path, marker)
            finally:
                if started_here:
                    self._stop()
            return self._status(marker)

    def app_environment(self) -> dict[str, str]:
        """Return restricted configuration for direct injection; callers must not print it."""
        with self._operation() as marker:
            if marker is None or not marker["initialized"]:
                raise WorkspacePostgresError("workspace PostgreSQL must be explicitly initialized")
            dsn = self._conninfo()
            return {
                "ENTERPRISE_STORE_BACKEND": "postgres",
                "ENTERPRISE_DATABASE_URL": dsn,
                "ENTERPRISE_POOL_MAX_SIZE": "4",
                "TASK_CENTER_ENABLED": "true",
                "TASK_CENTER_DATABASE_URL": dsn,
                "TASK_CENTER_POOL_MIN_SIZE": "1",
                "TASK_CENTER_POOL_MAX_SIZE": "4",
                "TASK_CENTER_POOL_MAX_WAITING": "32",
                "TASK_CENTER_POOL_TIMEOUT_SECONDS": "5",
            }
