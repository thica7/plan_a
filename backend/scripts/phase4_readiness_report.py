from __future__ import annotations

import argparse
import asyncio
import json
import socket
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.config import Settings  # noqa: E402
from packages.enterprise import EnterpriseMemoryStore  # noqa: E402
from packages.orchestrator.service import RunService  # noqa: E402
from packages.skills.registry import SkillRegistry  # noqa: E402
from packages.workflows.activities import CompetitiveIntelActivities  # noqa: E402
from packages.workflows.models import CompetitiveIntelWorkflowInput  # noqa: E402


@dataclass(frozen=True)
class ReadinessCheck:
    name: str
    status: str
    detail: str


async def main() -> None:
    args = _parse_args()
    settings = Settings(
        demo_mode=True,
        ark_api_key=None,
        ark_model=None,
        ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
        llm_timeout_seconds=30,
        llm_temperature=0.2,
        enterprise_store_backend="memory",
        enterprise_database_url=None,
    )
    checks = [
        _server_socket_check(settings),
        *(await _activity_idempotency_checks(settings)),
    ]
    summary = {
        "component": "phase4_readiness",
        "generated_at": datetime.now(UTC).isoformat(),
        "ok": _is_ok(checks, require_server=args.require_server),
        "require_server": args.require_server,
        "checks": [check.__dict__ for check in checks],
    }
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(_render_markdown(summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not summary["ok"]:
        raise SystemExit("Phase 4 readiness check failed.")


async def _activity_idempotency_checks(settings: Settings) -> list[ReadinessCheck]:
    store = EnterpriseMemoryStore()
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=settings,
        enterprise_store=store,
    )
    activities = CompetitiveIntelActivities(service)
    request = CompetitiveIntelWorkflowInput(
        topic="AI coding assistant phase4 readiness",
        competitors=["Cursor", "GitHub Copilot"],
        dimensions=["pricing"],
        execution_mode="demo",
        idempotency_key="phase4-readiness-idempotency",
    )

    created = await activities.create_run(request)
    duplicate = await activities.create_run(request)
    completed = await activities.run_langgraph_pipeline(created.run_id)
    event_count = len(service.get_trace(created.run_id) or [])
    completed_again = await activities.run_langgraph_pipeline(created.run_id)
    projection = await activities.load_projection(created.run_id)

    stable_run = created.run_id == duplicate.run_id
    pipeline_idempotent = (
        completed.status == "completed"
        and completed_again.status == "completed"
        and len(service.get_trace(created.run_id) or []) == event_count
    )
    projection_ready = bool(
        projection.report_version_id
        and projection.evidence_count >= 1
        and projection.claim_count >= 1
    )
    return [
        ReadinessCheck(
            name="workflow_create_idempotency",
            status="ok" if stable_run else "error",
            detail=f"run_id={created.run_id} duplicate_run_id={duplicate.run_id}",
        ),
        ReadinessCheck(
            name="langgraph_activity_idempotency",
            status="ok" if pipeline_idempotent else "error",
            detail=f"status={completed.status} event_count={event_count}",
        ),
        ReadinessCheck(
            name="enterprise_projection",
            status="ok" if projection_ready else "error",
            detail=(
                f"report_version_id={projection.report_version_id} "
                f"evidence_count={projection.evidence_count} claim_count={projection.claim_count}"
            ),
        ),
    ]


def _server_socket_check(settings: Settings) -> ReadinessCheck:
    host, port = _parse_host_port(settings.temporal_address)
    if host is None or port is None:
        return ReadinessCheck(
            name="temporal_server_socket",
            status="warn",
            detail=f"invalid address={settings.temporal_address}",
        )
    try:
        with socket.create_connection((host, port), timeout=0.5):
            pass
    except OSError:
        return ReadinessCheck(
            name="temporal_server_socket",
            status="warn",
            detail=f"unreachable address={settings.temporal_address}",
        )
    return ReadinessCheck(
        name="temporal_server_socket",
        status="ok",
        detail=f"reachable address={settings.temporal_address}",
    )


def _parse_host_port(address: str) -> tuple[str | None, int | None]:
    if ":" not in address:
        return None, None
    host, raw_port = address.rsplit(":", 1)
    try:
        return host.strip("[]") or "127.0.0.1", int(raw_port)
    except ValueError:
        return None, None


def _is_ok(checks: list[ReadinessCheck], *, require_server: bool) -> bool:
    for check in checks:
        if check.status == "error":
            return False
        if require_server and check.name == "temporal_server_socket" and check.status != "ok":
            return False
    return True


def _render_markdown(summary: dict[str, object]) -> str:
    checks = list(summary["checks"])  # type: ignore[arg-type]
    lines = [
        "# Phase 4 Readiness Report",
        "",
        f"- Generated at: {summary['generated_at']}",
        f"- Require Temporal server: {summary['require_server']}",
        f"- Overall: {'PASS' if summary['ok'] else 'FAIL'}",
        "",
        "| Check | Status | Detail |",
        "|---|---:|---|",
    ]
    for check in checks:
        lines.append(f"| {check['name']} | {check['status']} | {check['detail']} |")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "This report validates the Phase 4 thin-shell contract: the same idempotency "
            "key produces the same run, rerunning the LangGraph activity does not append "
            "duplicate trace events, and the enterprise projection contains a report "
            "version with evidence and claims.",
            "",
            "Server reachability is reported separately because local development can run "
            "the deterministic activity checks without a Temporal Server. Use "
            "`--require-server` in release rehearsal to make server reachability a hard gate.",
        ]
    )
    return "\n".join(lines) + "\n"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a Phase 4 readiness report.")
    parser.add_argument("--report", default=None, help="Optional markdown report path.")
    parser.add_argument(
        "--require-server",
        action="store_true",
        help="Fail if the configured Temporal Server socket is not reachable.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(main())
