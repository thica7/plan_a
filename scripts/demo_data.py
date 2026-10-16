#!/usr/bin/env python3
"""Plan consistent demo backups, isolated restores and restart acceptance checks.

Default is dry-run. Backup execution requires --allow-stop and briefly stops all
writers. Restore and fault execution require an explicit plan-a-drill-* project.
No operation deletes volumes or reads/prints host .env credentials. Backups contain
application data: keep their directory private. Redis is disposable, not backed up.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tarfile
import time
import uuid
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
HELPER_IMAGE = "alpine:3.21.3"
DATA_VOLUMES = ("run-data", "artifact-data", "qdrant_data")
WRITERS = ("nginx", "backend", "temporal-worker", "temporal", "temporal-ui", "qdrant")
SERVICES = set(WRITERS) | {"postgres", "frontend", "redis"}
DATABASE_LIST = [
    "sh",
    "-c",
    'psql -U "$POSTGRES_USER" -d postgres -At -c "SELECT datname FROM pg_database WHERE NOT datistemplate ORDER BY datname"',
]
DATABASE_DUMP = [
    "sh",
    "-c",
    'pg_dump -U "$POSTGRES_USER" --format=custom --no-owner --no-acl "$1"',
    "sh",
]
DATABASE_RESTORE = [
    "sh",
    "-c",
    'pg_restore -U "$POSTGRES_USER" -d template1 --create --clean --if-exists --no-owner --no-acl --exit-on-error',
]
RUN_PROBE = """import hashlib,json,sqlite3,sys
c=sqlite3.connect('file:/app/runs/run_journal.db?mode=ro',uri=True)
r=c.execute('select id,status,execution_mode from runs where id=?',(sys.argv[1],)).fetchone()
if r is None: raise RuntimeError('run missing')
e=c.execute('select event_id,event_json from events where run_id=? order by event_id',(sys.argv[1],)).fetchall()
h=e[:int(sys.argv[2])] if len(sys.argv)>2 else e
digest=hashlib.sha256(json.dumps(h,separators=(',',':')).encode()).hexdigest()
a=c.execute("select count(*) from runs where execution_mode='real' and status in ('queued','running','interrupted')").fetchone()[0]
print(json.dumps(dict(id=r[0],status=r[1],execution_mode=r[2],events=len(e),last_event=e[-1][0] if e else 0,history_hash=digest,active_real_runs=a)))
"""


def validate_project(project: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", project):
        raise ValueError("Invalid project name")
    return project


def compose(project: str) -> list[str]:
    return [
        "docker",
        "compose",
        "-f",
        str(ROOT / "docker-compose.yml"),
        "--project-name",
        validate_project(project),
        "--profile",
        "redis",
    ]


def volume_command(
    project: str, volume: str, directory: Path, *, restore: bool
) -> list[str]:
    validate_project(project)
    if volume not in DATA_VOLUMES:
        raise ValueError("Unknown data volume")
    path = str(directory.resolve())
    if "," in path:
        raise ValueError("Backup directory must not contain ,")
    if restore:
        mounts = [
            "-v",
            f"{project}_{volume}:/target",
            "--mount",
            f"type=bind,source={path},target=/backup,readonly",
        ]
        archive = ["tar", "xzf", f"/backup/{volume}.tar.gz", "-C", "/target"]
    else:
        mounts = [
            "-v",
            f"{project}_{volume}:/source:ro",
            "--mount",
            f"type=bind,source={path},target=/backup",
        ]
        archive = ["tar", "czf", f"/backup/{volume}.tar.gz", "-C", "/source", "."]
    return (
        ["docker", "run", "--rm", "--network", "none"]
        + mounts
        + [HELPER_IMAGE]
        + archive
    )


def data_plan(
    action: str,
    project: str,
    directory: Path,
    *,
    target: str | None = None,
    run_id: str | None = None,
) -> dict:
    command = compose(project)
    directory = directory.resolve()
    if action == "backup":
        steps = [
            {
                "description": "After ownership and volume preflight, stop all writers",
                "command": command + ["stop", "--timeout", "120", *WRITERS],
            },
            {
                "description": "Discover all application/Temporal databases",
                "command": command + ["exec", "-T", "postgres", *DATABASE_LIST],
            },
            {
                "description": "Export each discovered database to a private archive",
                "command": command
                + ["exec", "-T", "postgres", *DATABASE_DUMP, "<discovered-database>"],
            },
        ]
        steps += [
            {
                "description": f"Cold archive {volume}",
                "command": volume_command(project, volume, directory, restore=False),
            }
            for volume in DATA_VOLUMES
        ]
        steps.append(
            {
                "description": "Write SHA256 manifest, then restart only previously running writers",
                "command": command + ["start", "<previously-running-writers>"],
            }
        )
    elif action == "restore":
        if not target:
            raise ValueError("restore requires --target-project")
        validate_execution(action, project, target, False)
        steps = [
            {
                "description": "Verify manifest, archive paths and checksums; require target containers/volumes absent",
                "command": [
                    "docker",
                    "ps",
                    "-aq",
                    "--filter",
                    f"label=com.docker.compose.project={target}",
                ],
            }
        ]
        steps += [
            {
                "description": f"Create and restore fresh {volume}",
                "command": volume_command(target, volume, directory, restore=True),
            }
            for volume in DATA_VOLUMES
        ]
        steps += [
            {
                "description": "Start only the isolated Postgres without publishing host ports",
                "command": isolated_postgres_command(target),
            },
            {
                "description": "Restore each database, stop and remove temporary container; leave application services stopped",
                "command": [
                    "docker",
                    "exec",
                    "-i",
                    f"{target}-restore-postgres",
                    *DATABASE_RESTORE,
                ],
            },
        ]
    elif action == "fault":
        validate_execution(action, project, None, False)
        if not run_id or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", run_id):
            raise ValueError("fault requires a safe --run-id from a demo task")
        steps = [
            {
                "description": "Check stored demo task status/events before and after restart",
                "command": command
                + ["exec", "-T", "backend", "python", "-c", RUN_PROBE, run_id],
            },
            {
                "description": "Write unique persistent marker, restart owned backend and running Worker",
                "command": command
                + ["restart", "backend", "<running-worker-if-present>"],
            },
            {
                "description": "Check /api/readyz, marker equality, event continuity and waiting state",
                "command": command
                + ["exec", "-T", "backend", "python", "-c", RUN_PROBE, run_id],
            },
        ]
    else:
        raise ValueError("Unknown operation")
    return {
        "dry_run": True,
        "action": action,
        "project": project,
        "target_project": target,
        "directory": str(directory),
        "steps": steps,
        "note": "Angle-bracket values are resolved from preflight during --execute. No command runs in dry-run.",
    }


def validate_execution(
    action: str, project: str, target: str | None, allow_stop: bool
) -> None:
    validate_project(project)
    if action == "backup" and not allow_stop:
        raise ValueError(
            "Backup execution requires explicit --allow-stop for consistency"
        )
    isolated = target if action == "restore" else project
    if action in {"restore", "fault"}:
        if (
            not isolated
            or not isolated.startswith("plan-a-drill-")
            or isolated == project
            and action == "restore"
        ):
            raise ValueError("Restore/fault requires a separate plan-a-drill-* project")
        validate_project(isolated)


def run_command(
    command: list[str],
    *,
    input_path: Path | None = None,
    output_path: Path | None = None,
) -> bytes:
    input_file = input_path.open("rb") if input_path else None
    output_file = output_path.open("wb") if output_path else None
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            stdin=input_file,
            stdout=output_file or subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        return result.stdout or b""
    finally:
        if input_file:
            input_file.close()
        if output_file:
            output_file.close()


def validate_ownership(labels: dict, project: str, *, root: Path | None = None) -> None:
    root = (root or ROOT).resolve()
    labels = labels if isinstance(labels, dict) else {}
    valid = labels.get("com.docker.compose.project") == project
    valid &= labels.get("com.docker.compose.service") in SERVICES
    valid &= labels.get("com.docker.compose.project.working_dir") == str(root)
    valid &= labels.get("com.docker.compose.project.config_files") == str(
        root / "docker-compose.yml"
    )
    if not valid:
        raise RuntimeError("Compose ownership mismatch; no services were changed")


def project_inventory(project: str, *, root: Path | None = None) -> list[dict]:
    container_ids = (
        run_command(
            [
                "docker",
                "ps",
                "-aq",
                "--filter",
                f"label=com.docker.compose.project={validate_project(project)}",
            ]
        )
        .decode()
        .split()
    )
    result = []
    for container in container_ids:
        labels = json.loads(
            run_command(
                ["docker", "inspect", "--format", "{{json .Config.Labels}}", container]
            )
        )
        validate_ownership(labels, project, root=root)
        running = (
            run_command(
                ["docker", "inspect", "--format", "{{.State.Running}}", container]
            ).strip()
            == b"true"
        )
        result.append(
            {"service": labels["com.docker.compose.service"], "running": running}
        )
    return result


def validate_volume_ownership(labels: dict, project: str, volume: str) -> None:
    if (
        not isinstance(labels, dict)
        or labels.get("com.docker.compose.project") != project
        or labels.get("com.docker.compose.volume") != volume
    ):
        raise RuntimeError("Volume ownership mismatch; no services were changed")


def assert_project_ownership(project: str, *, root: Path | None = None) -> list[dict]:
    """Allow a new project or existing resources owned by this exact checkout."""
    inventory = project_inventory(project, root=root)
    expected = {
        f"{project}_{volume}": volume for volume in (*DATA_VOLUMES, "postgres-data")
    }
    existing = set(run_command(["docker", "volume", "ls", "-q"]).decode().splitlines())
    labelled = set(
        run_command(
            [
                "docker",
                "volume",
                "ls",
                "-q",
                "--filter",
                f"label=com.docker.compose.project={project}",
            ]
        )
        .decode()
        .splitlines()
    )
    for name in sorted((existing & expected.keys()) | labelled):
        if name not in expected:
            raise RuntimeError("Volume ownership mismatch; unexpected project volume")
        labels = json.loads(
            run_command(
                [
                    "docker",
                    "volume",
                    "inspect",
                    "--format",
                    "{{json .Labels}}",
                    name,
                ]
            )
        )
        validate_volume_ownership(labels, project, expected[name])
    return inventory


def assert_source_volumes(project: str) -> None:
    for volume in (*DATA_VOLUMES, "postgres-data"):
        labels = json.loads(
            run_command(
                [
                    "docker",
                    "volume",
                    "inspect",
                    "--format",
                    "{{json .Labels}}",
                    f"{project}_{volume}",
                ]
            )
        )
        validate_volume_ownership(labels, project, volume)


def expected_files(databases: list[str]) -> set[str]:
    if (
        not databases
        or len(databases) != len(set(databases))
        or not all(
            isinstance(database, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,63}", database)
            for database in databases
        )
    ):
        raise ValueError("Invalid manifest database names")
    return {f"{volume}.tar.gz" for volume in DATA_VOLUMES} | {
        f"postgres-{database}.dump" for database in databases
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_manifest(
    directory: Path, project: str, databases: list[str], running: list[str]
) -> None:
    manifest = {
        "version": 1,
        "project": validate_project(project),
        "databases": databases,
        "running_services": running,
        "files": {
            name: sha256(directory / name) for name in sorted(expected_files(databases))
        },
        "consistency": "API/worker/Temporal/Qdrant stopped; Postgres custom dumps; Redis excluded",
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


def verify_backup(directory: Path) -> dict:
    manifest_path = directory / "manifest.json"
    if manifest_path.is_symlink():
        raise ValueError("Invalid manifest path")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("version") != 1 or not isinstance(manifest.get("files"), dict):
        raise ValueError("Invalid manifest format")
    validate_project(manifest.get("project", ""))
    databases = manifest.get("databases")
    if not isinstance(databases, list) or set(manifest["files"]) != expected_files(
        databases
    ):
        raise ValueError("Invalid manifest file list")
    for name, digest in manifest["files"].items():
        path = directory / name
        if (
            path.is_symlink()
            or not path.is_file()
            or not isinstance(digest, str)
            or sha256(path) != digest
        ):
            raise ValueError("Backup checksum mismatch; restore refused")
        if name.endswith(".tar.gz"):
            with tarfile.open(path, "r:gz") as archive:
                for member in archive:
                    item = PurePosixPath(member.name)
                    if (
                        item.is_absolute()
                        or ".." in item.parts
                        or not (member.isfile() or member.isdir())
                    ):
                        raise ValueError(
                            "Unsafe backup archive member; restore refused"
                        )
    return manifest


def execute_backup(project: str, directory: Path) -> dict:
    inventory = project_inventory(project)
    running = sorted({item["service"] for item in inventory if item["running"]})
    if "postgres" not in running:
        raise RuntimeError("Source Postgres must be running")
    assert_source_volumes(project)
    if directory.exists() and any(directory.iterdir()):
        raise ValueError("Backup directory must be absent or empty")
    # Resolve safe database names before stopping services, without exporting credentials.
    databases = (
        run_command(compose(project) + ["exec", "-T", "postgres", *DATABASE_LIST])
        .decode()
        .splitlines()
    )
    expected_files(databases)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    stopped = [service for service in WRITERS if service in running]
    try:
        if stopped:
            run_command(compose(project) + ["stop", "--timeout", "120", *stopped])
        databases = (
            run_command(compose(project) + ["exec", "-T", "postgres", *DATABASE_LIST])
            .decode()
            .splitlines()
        )
        expected_files(databases)
        for database in databases:
            run_command(
                compose(project) + ["exec", "-T", "postgres", *DATABASE_DUMP, database],
                output_path=directory / f"postgres-{database}.dump",
            )
        for volume in DATA_VOLUMES:
            run_command(volume_command(project, volume, directory, restore=False))
        write_manifest(directory, project, databases, running)
        verify_backup(directory)
    finally:
        if stopped:
            run_command(compose(project) + ["start", *stopped])
    return {
        "action": "backup",
        "project": project,
        "directory": str(directory),
        "verified": True,
    }


def isolated_postgres_command(project: str) -> list[str]:
    # Compose run omits service ports unless --service-ports is explicit. Reuse
    # its configured credentials without copying them into command arguments.
    return compose(project) + [
        "run",
        "--no-deps",
        "-d",
        "--name",
        f"{project}-restore-postgres",
        "postgres",
    ]


def execute_restore(target: str, directory: Path) -> dict:
    manifest = verify_backup(directory)
    validate_execution("restore", manifest["project"], target, False)
    if project_inventory(target):
        raise RuntimeError("Restore target must be empty")
    existing = set(run_command(["docker", "volume", "ls", "-q"]).decode().splitlines())
    if any(
        f"{target}_{volume}" in existing for volume in (*DATA_VOLUMES, "postgres-data")
    ):
        raise RuntimeError("Restore target volumes must be empty and new")
    for volume in (*DATA_VOLUMES, "postgres-data"):
        run_command(
            [
                "docker",
                "volume",
                "create",
                "--label",
                f"com.docker.compose.project={target}",
                "--label",
                f"com.docker.compose.volume={volume}",
                f"{target}_{volume}",
            ]
        )
    for volume in DATA_VOLUMES:
        run_command(volume_command(target, volume, directory, restore=True))
    name = f"{target}-restore-postgres"
    run_command(isolated_postgres_command(target))
    try:
        for attempt in range(60):
            try:
                run_command(
                    [
                        "docker",
                        "exec",
                        name,
                        "sh",
                        "-c",
                        'pg_isready -h 127.0.0.1 -U "$POSTGRES_USER" -d postgres',
                    ]
                )
                break
            except subprocess.CalledProcessError:
                if attempt == 59:
                    raise RuntimeError("Isolated Postgres readiness timed out")
                time.sleep(1)
        for database in manifest["databases"]:
            run_command(
                ["docker", "exec", "-i", name, *DATABASE_RESTORE],
                input_path=directory / f"postgres-{database}.dump",
            )
    finally:
        run_command(["docker", "stop", "--time", "30", name])
        run_command(["docker", "rm", name])
    return {
        "action": "restore",
        "project": target,
        "verified": True,
        "note": "Restored fresh volumes using the configured Postgres credentials; all application services remain stopped.",
    }


def validate_fault_result(
    before: dict, after: dict, marker: str, actual_marker: str
) -> None:
    if actual_marker != marker:
        raise RuntimeError("Persistent marker was lost")
    if (
        before.get("id") != after.get("id")
        or before.get("execution_mode") != "demo"
        or after.get("execution_mode") != "demo"
    ):
        raise RuntimeError("Demo task persistence failed")
    if after.get("events", -1) < before.get("events", 0) or after.get(
        "last_event", -1
    ) < before.get("last_event", 0):
        raise RuntimeError("Task event persistence failed")
    if before.get("history_hash") != after.get("history_hash"):
        raise RuntimeError("Task event history persistence failed")
    if (
        before.get("status", "").startswith("waiting")
        or before.get("status") == "interrupted"
    ) and after.get("status") != before["status"]:
        raise RuntimeError("Human waiting state changed during restart")
    if (
        before.get("status")
        in {"completed", "completed_with_blockers", "failed", "cancelled"}
        and after.get("status") != before["status"]
    ):
        raise RuntimeError("Terminal task state changed during restart")


def execute_fault(project: str, run_id: str) -> dict:
    validate_execution("fault", project, None, False)
    running = {
        item["service"] for item in project_inventory(project) if item["running"]
    }
    if "backend" not in running:
        raise RuntimeError("Isolated backend must already be running")
    prefix = compose(project) + ["exec", "-T", "backend", "python", "-c"]
    before = json.loads(run_command(prefix + [RUN_PROBE, run_id]))
    if before.get("execution_mode") != "demo" or before.get("active_real_runs", 0):
        raise RuntimeError("Fault acceptance only supports an existing demo task")
    marker = uuid.uuid4().hex
    path = f"/app/runs/.demo-drill-{marker}"
    run_command(
        prefix
        + [
            "from pathlib import Path; import sys; Path(sys.argv[1]).write_text(sys.argv[2])",
            path,
            marker,
        ]
    )
    services = [
        service for service in ("backend", "temporal-worker") if service in running
    ]
    run_command(compose(project) + ["restart", *services])
    ready = "import json,urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/api/readyz', timeout=3); assert r.status==200 and json.load(r)['status'] in ('ok','warn')"
    for attempt in range(60):
        try:
            run_command(prefix + [ready])
            break
        except subprocess.CalledProcessError:
            if attempt == 59:
                raise RuntimeError("Restart readiness timed out")
            time.sleep(1)
    after = json.loads(run_command(prefix + [RUN_PROBE, run_id, str(before["events"])]))
    actual_marker = (
        run_command(
            prefix
            + [
                "from pathlib import Path; import sys; print(Path(sys.argv[1]).read_text())",
                path,
            ]
        )
        .decode()
        .strip()
    )
    validate_fault_result(before, after, marker, actual_marker)
    run_command(
        prefix
        + ["from pathlib import Path; import sys; Path(sys.argv[1]).unlink()", path]
    )
    return {
        "action": "fault",
        "project": project,
        "verified": True,
        "before": before,
        "after": after,
        "note": "Checked persisted marker/task/events across restart. This does not prove model side-effect replay or full workflow completion.",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("backup", "restore", "fault"))
    parser.add_argument("--project", required=True)
    parser.add_argument("--directory", type=Path, default=ROOT / "backups" / "demo")
    parser.add_argument("--target-project")
    parser.add_argument("--run-id")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-stop", action="store_true")
    args = parser.parse_args(argv)
    try:
        directory = args.directory.resolve()
        plan = data_plan(
            args.action,
            args.project,
            directory,
            target=args.target_project,
            run_id=args.run_id,
        )
        if not args.execute:
            print(json.dumps(plan, indent=2))
            return 0
        validate_execution(
            args.action, args.project, args.target_project, args.allow_stop
        )
        if args.action == "backup":
            result = execute_backup(args.project, directory)
        elif args.action == "restore":
            result = execute_restore(args.target_project, directory)
        else:
            result = execute_fault(args.project, args.run_id)
        print(json.dumps(result, indent=2))
    except subprocess.CalledProcessError:
        print(
            "[plan_a] Container operation failed; inspect the deployment machine. No volumes were deleted.",
            file=sys.stderr,
        )
        return 1
    except (OSError, ValueError, RuntimeError, tarfile.TarError) as error:
        print(f"[plan_a] {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
