from __future__ import annotations

import socket
from collections import Counter
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from app.deps import get_app_settings, get_enterprise_store, get_run_journal
from packages.agents.pydantic_ai_adapter import pydantic_ai_available
from packages.config import Settings
from packages.enterprise import EnterpriseStore
from packages.memory import RunJournal
from packages.schema.enterprise import NotificationRecord
from packages.workflows.service import temporal_cutover_status

router = APIRouter()
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
RunJournalDep = Annotated[RunJournal, Depends(get_run_journal)]

TEMPORAL_REGISTERED_WORKFLOWS = (
    "CompetitiveIntelWorkflow",
    "MonitorWorkflow",
    "ReportApprovalWorkflow",
    "ScheduledScanWorkflow",
)


def get_metrics_enterprise_store(settings: SettingsDep) -> EnterpriseStore | None:
    if not _enterprise_store_configured(settings):
        return None
    try:
        return get_enterprise_store()
    except RuntimeError:
        return None


EnterpriseStoreDep = Annotated[EnterpriseStore | None, Depends(get_metrics_enterprise_store)]


@router.get("/metrics", response_class=PlainTextResponse)
def metrics(
    settings: SettingsDep,
    journal: RunJournalDep,
    enterprise_store: EnterpriseStoreDep,
) -> PlainTextResponse:
    runs = journal.load_runs()
    counts = Counter(run.status for run in runs)
    notifications = _load_notifications(enterprise_store)
    notification_counts = Counter(
        (item.notification_type, item.status) for item in notifications
    )
    release_gate_blocked_count = sum(
        count
        for (notification_type, _status), count in notification_counts.items()
        if notification_type == "release_gate_blocked"
    )
    input_tokens = sum(run.metrics.input_tokens_estimate for run in runs)
    output_tokens = sum(run.metrics.output_tokens_estimate for run in runs)
    trace_spans = [span for run in runs for span in run.trace_spans]
    trace_context_coverage = _trace_context_coverage(trace_spans)
    temporal_cutover = temporal_cutover_status(settings)
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
            (
                "# HELP competiscope_temporal_traffic_percent_target Target percentage "
                "of run traffic routed through Temporal."
            ),
            "# TYPE competiscope_temporal_traffic_percent_target gauge",
            f"competiscope_temporal_traffic_percent_target {settings.temporal_traffic_percent}",
            "# HELP competiscope_temporal_cutover_ready Phase 4 Temporal cutover readiness.",
            "# TYPE competiscope_temporal_cutover_ready gauge",
            f"competiscope_temporal_cutover_ready {1 if temporal_cutover.ready else 0}",
            "# HELP competiscope_temporal_server_up Temporal frontend socket reachability.",
            "# TYPE competiscope_temporal_server_up gauge",
            f"competiscope_temporal_server_up {_socket_up(settings.temporal_address)}",
            "# HELP competiscope_enterprise_store_configured Enterprise store config validity.",
            "# TYPE competiscope_enterprise_store_configured gauge",
            f"competiscope_enterprise_store_configured {_enterprise_store_configured(settings)}",
            "# HELP competiscope_trace_spans_total Trace spans persisted in run details.",
            "# TYPE competiscope_trace_spans_total gauge",
            f"competiscope_trace_spans_total {sum(run.metrics.total_spans for run in runs)}",
            (
                "# HELP competiscope_trace_context_coverage_ratio Ratio of spans with "
                "trace_id, otel_span_id, and traceparent."
            ),
            "# TYPE competiscope_trace_context_coverage_ratio gauge",
            f"competiscope_trace_context_coverage_ratio {trace_context_coverage:.6f}",
            "# HELP competiscope_llm_calls_total LLM calls persisted in run metrics.",
            "# TYPE competiscope_llm_calls_total gauge",
            f"competiscope_llm_calls_total {sum(run.metrics.llm_calls for run in runs)}",
            "# HELP competiscope_token_estimate_total Token estimates persisted in run metrics.",
            "# TYPE competiscope_token_estimate_total gauge",
            f'competiscope_token_estimate_total{{kind="input"}} {input_tokens}',
            f'competiscope_token_estimate_total{{kind="output"}} {output_tokens}',
            f'competiscope_token_estimate_total{{kind="total"}} {input_tokens + output_tokens}',
            "# HELP competiscope_cost_estimate_usd_total Estimated LLM cost in USD.",
            "# TYPE competiscope_cost_estimate_usd_total gauge",
            (
                "competiscope_cost_estimate_usd_total "
                f"{round(sum(run.metrics.cost_estimate_usd for run in runs), 6)}"
            ),
            "# HELP competiscope_qa_findings_total QA findings persisted across runs.",
            "# TYPE competiscope_qa_findings_total gauge",
            f"competiscope_qa_findings_total {sum(len(run.qa_findings) for run in runs)}",
            "# HELP competiscope_pydantic_ai_available Pydantic-AI runtime import status.",
            "# TYPE competiscope_pydantic_ai_available gauge",
            f"competiscope_pydantic_ai_available {1 if pydantic_ai_available() else 0}",
            (
                "# HELP competiscope_pydantic_ai_model_backed_enabled Model-backed "
                "Pydantic-AI execution switch."
            ),
            "# TYPE competiscope_pydantic_ai_model_backed_enabled gauge",
            (
                "competiscope_pydantic_ai_model_backed_enabled "
                f"{1 if settings.pydantic_ai_model_backed_enabled else 0}"
            ),
            "# HELP competiscope_compliance_redaction_enabled Trace text redaction status.",
            "# TYPE competiscope_compliance_redaction_enabled gauge",
            (
                "competiscope_compliance_redaction_enabled "
                f"{1 if settings.compliance_redaction_enabled else 0}"
            ),
            "# HELP competiscope_compliance_redactions_total Trace text redactions applied.",
            "# TYPE competiscope_compliance_redactions_total gauge",
            (
                "competiscope_compliance_redactions_total "
                f"{sum(run.metrics.compliance_redaction_count for run in runs)}"
            ),
            (
                "# HELP competiscope_compliance_require_trace_context Compliance "
                "trace-context requirement."
            ),
            "# TYPE competiscope_compliance_require_trace_context gauge",
            (
                "competiscope_compliance_require_trace_context "
                f"{1 if settings.compliance_require_trace_context else 0}"
            ),
            "# HELP competiscope_compliance_require_source_urls Compliance source URL requirement.",
            "# TYPE competiscope_compliance_require_source_urls gauge",
            (
                "competiscope_compliance_require_source_urls "
                f"{1 if settings.compliance_require_source_urls else 0}"
            ),
            "# HELP competiscope_notifications_total Enterprise notifications by type and status.",
            "# TYPE competiscope_notifications_total gauge",
        ]
    )
    for notification_type, status in sorted(
        {("release_gate_blocked", "queued"), *notification_counts.keys()}
    ):
        lines.append(
            "competiscope_notifications_total"
            f'{{type="{notification_type}",status="{status}"}} '
            f"{notification_counts[(notification_type, status)]}"
        )
    lines.extend(
        [
            (
                "# HELP competiscope_release_gate_blocked_notifications_total "
                "Blocked release gate notifications."
            ),
            "# TYPE competiscope_release_gate_blocked_notifications_total gauge",
            (
                "competiscope_release_gate_blocked_notifications_total "
                f"{release_gate_blocked_count}"
            ),
            "# HELP competiscope_temporal_workflow_registered_total Registered Temporal workflows.",
            "# TYPE competiscope_temporal_workflow_registered_total gauge",
        ]
    )
    for workflow in TEMPORAL_REGISTERED_WORKFLOWS:
        lines.append(
            f'competiscope_temporal_workflow_registered_total{{workflow="{workflow}"}} 1'
        )
    return PlainTextResponse("\n".join(lines) + "\n")


def _load_notifications(enterprise_store: EnterpriseStore | None) -> list[NotificationRecord]:
    if enterprise_store is None:
        return []
    try:
        return enterprise_store.list_notifications(limit=10_000)
    except Exception:  # noqa: BLE001 - metrics should degrade instead of failing health scrape.
        return []


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


def _trace_context_coverage(spans: list[object]) -> float:
    if not spans:
        return 0.0
    complete = sum(
        1
        for span in spans
        if getattr(span, "trace_id", "")
        and getattr(span, "otel_span_id", "")
        and getattr(span, "traceparent", "")
    )
    return complete / len(spans)
