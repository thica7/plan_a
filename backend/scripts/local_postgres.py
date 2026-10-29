"""Private, explicitly owned PostgreSQL cluster used by local verification."""

from __future__ import annotations

import os
import secrets
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

import psycopg
from psycopg.conninfo import make_conninfo


class OwnedPostgresError(RuntimeError):
    """Starting or cleaning up our private cluster failed."""


class OwnedPostgres:
    """Own a random mode-0700 directory and only the server started inside it.

    No TCP listener is created. Trust authentication is restricted to the private
    Unix socket; host authentication is rejected. Existing services are untouched.
    """

    def __init__(self, *, binary_dir: Path = Path("/opt/homebrew/bin")) -> None:
        self.binary_dir = binary_dir
        self.root: Path | None = None
        self.data_dir: Path | None = None
        self.socket_dir: Path | None = None
        self.pid = 0
        self._marker = secrets.token_hex(24)
        self.owner_dsn = ""
        self.app_dsn = ""

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
            raise OwnedPostgresError(f"owned PostgreSQL {binary} could not run") from None
        if result.returncode:
            raise OwnedPostgresError(
                f"owned PostgreSQL {binary} failed with exit {result.returncode}"
            )
        return result

    def _assert_owned_directory(self) -> None:
        if (
            self.root is None
            or self.root.parent != Path("/private/tmp")
            or not self.root.name.startswith("task-center-pg-")
            or self.root.is_symlink()
            or self.root.stat().st_uid != os.getuid()
            or (self.root / ".owned-postgres").read_text() != self._marker
        ):
            raise OwnedPostgresError("refusing to operate on an unowned PostgreSQL directory")

    def _server_pid(self) -> int | None:
        self._assert_owned_directory()
        assert self.data_dir is not None
        pid_file = self.data_dir / "postmaster.pid"
        if not pid_file.exists():
            return None
        lines = pid_file.read_text().splitlines()
        if len(lines) < 2 or lines[1] != str(self.data_dir):
            raise OwnedPostgresError("owned PostgreSQL PID file does not match its directory")
        try:
            pid = int(lines[0])
            if pid <= 1 or (self.pid and pid != self.pid):
                raise ValueError
            result = subprocess.run(
                ["/bin/ps", "-p", str(pid), "-o", "args="],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            command = shlex.split(result.stdout.strip())
        except (ValueError, OSError, subprocess.TimeoutExpired):
            raise OwnedPostgresError("could not verify owned PostgreSQL PID") from None
        if result.stderr.strip():
            raise OwnedPostgresError("could not verify owned PostgreSQL PID")
        if result.returncode:
            if result.returncode == 1 and not result.stdout.strip():
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    return None
                except OSError:
                    pass
            raise OwnedPostgresError("could not verify owned PostgreSQL PID")
        if (
            not command
            or Path(command[0]).name != "postgres"
            or "-D" not in command
            or command[command.index("-D") + 1] != str(self.data_dir)
        ):
            raise OwnedPostgresError("refusing to signal a PostgreSQL PID we do not own")
        return pid

    @property
    def is_running(self) -> bool:
        if self.root is None or not self.root.exists():
            return False
        return self._server_pid() is not None

    def start(self) -> OwnedPostgres:
        if self.root is not None:
            raise OwnedPostgresError("an owned PostgreSQL instance can only be started once")
        allocated_root = Path(tempfile.mkdtemp(prefix="task-center-pg-", dir="/private/tmp"))
        self.root = allocated_root
        marker_ready = False
        try:
            self.data_dir = allocated_root / "data"
            self.socket_dir = allocated_root / "socket"
            allocated_root.chmod(0o700)
            (allocated_root / ".owned-postgres").write_text(self._marker)
            marker_ready = True
            self.socket_dir.mkdir(mode=0o700)
            self._run(
                "initdb",
                "-D",
                str(self.data_dir),
                "-U",
                "task_center_owner",
                "--auth-local=trust",
                "--auth-host=reject",
                "--encoding=UTF8",
                "--no-locale",
            )
            self._run(
                "pg_ctl",
                "-D",
                str(self.data_dir),
                "-l",
                str(self.root / "postgres.log"),
                "-w",
                "-t",
                "15",
                "-o",
                f"-c listen_addresses='' -c unix_socket_directories='{self.socket_dir}' "
                "-c unix_socket_permissions=0700 -c max_connections=32",
                "start",
            )
            self.pid = self._server_pid() or 0
            if not self.pid:
                raise OwnedPostgresError("owned PostgreSQL did not publish a valid PID")
            self.owner_dsn = make_conninfo(
                host=str(self.socket_dir),
                port=5432,
                dbname="postgres",
                user="task_center_owner",
                connect_timeout=3,
            )
            self.app_dsn = make_conninfo(
                host=str(self.socket_dir),
                port=5432,
                dbname="postgres",
                user="task_center_app",
                connect_timeout=3,
            )
            with psycopg.connect(self.owner_dsn) as conn:
                conn.execute(
                    "CREATE ROLE task_center_app LOGIN NOSUPERUSER NOBYPASSRLS "
                    "NOINHERIT NOCREATEDB NOCREATEROLE NOREPLICATION"
                )
        except BaseException:
            if marker_ready:
                self.stop()
            else:
                # No PostgreSQL command can run before the marker is written.
                # Only remove the directory just returned by our mkdtemp call.
                shutil.rmtree(allocated_root)
            raise
        return self

    def grant_app_access(self) -> None:
        """Grant DML after explicit migrations; never grant DDL or TRUNCATE."""
        if not self.is_running:
            raise OwnedPostgresError("owned PostgreSQL is not running")
        with psycopg.connect(self.owner_dsn) as conn:
            conn.execute("GRANT USAGE ON SCHEMA task_center TO task_center_app")
            conn.execute(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES "
                "IN SCHEMA task_center TO task_center_app"
            )
            conn.execute(
                "REVOKE INSERT, UPDATE, DELETE ON task_center.schema_migrations "
                "FROM task_center_app"
            )
            conn.execute(
                "REVOKE UPDATE, DELETE ON task_center.quota_entries, "
                "task_center.audit_events FROM task_center_app"
            )

    def stop(self) -> None:
        if self.root is None or not self.root.exists():
            return
        pid = self._server_pid()
        if pid is not None:
            self._run("pg_ctl", "-D", str(self.data_dir), "-m", "fast", "-w", "-t", "15", "stop")
        if self._server_pid() is not None:
            raise OwnedPostgresError("owned PostgreSQL did not stop; directory retained")
        shutil.rmtree(self.root)

    def __enter__(self) -> OwnedPostgres:
        return self.start()

    def __exit__(self, *args: object) -> None:
        self.stop()
