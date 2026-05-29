from __future__ import annotations

import socket
from collections import Counter
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from app.deps import get_app_settings, get_run_journal
from packages.config import Settings
from packages.memory import RunJournal

router = APIRouter()
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
RunJournalDep = Annotated[RunJournal, Depends(get_run_journal)]


@router.get("/metrics", response_class=PlainTextResponse)
def metrics(settings: SettingsDep, journal: RunJournalDep) -> PlainTextResponse:
    runs = journal.load_runs()
    counts = Counter(run.status for run in runs)
    lines = [
        "# HELP competiscope_api_up Competiscope API process health.",
        "# TYPE competiscope_api_up gauge",
        "competiscope_api_up 1",
        "# HELP competiscope_runs_total Runs recorded by status.",
        "# TYPE competiscope_runs_total gauge",
    ]
    for status in ("queued", "running", "interrupted", "completed", "failed"):
        lines.append(f'competiscope_runs_total{{status="{status}"}} {counts[status]}')
    lines.extend(
        [
            "# HELP competiscope_run_orchestration_backend Active run orchestration backend.",
            "# TYPE competiscope_run_orchestration_backend gauge",
            (
                'competiscope_run_orchestration_backend{backend="langgraph"} '
                f'{1 if settings.run_orchestration_backend == "langgraph" else 0}'
            ),
            (
                'competiscope_run_orchestration_backend{backend="temporal"} '
                f'{1 if settings.run_orchestration_backend == "temporal" else 0}'
            ),
            "# HELP competiscope_temporal_server_up Temporal frontend socket reachability.",
            "# TYPE competiscope_temporal_server_up gauge",
            f"competiscope_temporal_server_up {_socket_up(settings.temporal_address)}",
            "# HELP competiscope_enterprise_store_configured Enterprise store config validity.",
            "# TYPE competiscope_enterprise_store_configured gauge",
            f"competiscope_enterprise_store_configured {_enterprise_store_configured(settings)}",
        ]
    )
    return PlainTextResponse("\n".join(lines) + "\n")


def _enterprise_store_configured(settings: Settings) -> int:
    if settings.enterprise_store_backend == "memory":
        return 1
    if settings.enterprise_store_backend == "postgres" and settings.enterprise_database_url:
        return 1
    return 0


def _socket_up(address: str) -> int:
    if ":" not in address:
        return 0
    host, raw_port = address.rsplit(":", 1)
    try:
        port = int(raw_port)
    except ValueError:
        return 0
    try:
        with socket.create_connection((host.strip("[]") or "127.0.0.1", port), timeout=0.5):
            pass
    except OSError:
        return 0
    return 1
