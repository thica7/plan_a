from __future__ import annotations

import socket
from collections import Counter
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from app.deps import (
    get_app_settings,
    get_enterprise_store,
    get_preference_memory,
    get_run_journal,
)
from packages.agents.pydantic_ai_adapter import pydantic_ai_available
from packages.compliance import build_data_retention_report
from packages.config import Settings
from packages.enterprise import EnterpriseStore
from packages.governance import build_model_route_decision
from packages.memory import PreferenceMemoryStore, RunJournal
from packages.observability import LangfuseAdapter, LangfuseConfig
from packages.schema.enterprise import MemoryStats, NotificationRecord
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


def get_metrics_preference_memory() -> PreferenceMemoryStore | None:
    try:
        return get_preference_memory()
    except RuntimeError:
        return None


PreferenceMemoryDep = Annotated[
    PreferenceMemoryStore | None,
    Depends(get_metrics_preference_memory),
]


@router.get("/metrics", response_class=PlainTextResponse)
def metrics(
    settings: SettingsDep,
    journal: RunJournalDep,
    enterprise_store: EnterpriseStoreDep,
    preference_memory: PreferenceMemoryDep,
) -> PlainTextResponse:
    runs = journal.load_runs()
    counts = Counter(run.status for run in runs)
    notifications = _load_notifications(enterprise_store)
    memory_stats = _load_memory_stats(preference_memory)
    memory_confirmed_ratio = (
        memory_stats.confirmed_candidate_count / memory_stats.candidate_count
        if memory_stats and memory_stats.candidate_count
        else 0.0
    )
    retention_reports = _load_retention_reports(enterprise_store, settings)
    retention_expired_count = sum(report.expired_count for report in retention_reports)
    retention_expiring_soon_count = sum(report.expiring_soon_count for report in retention_reports)
    retention_status = _retention_status(retention_reports)
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
    langfuse_health = LangfuseAdapter(
        LangfuseConfig(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
    ).health()
    langfuse_disabled_reason = _metric_label_value(
        str(langfuse_health["disabled_reason"] or "none")
    )
    langfuse_mirror_errors = sum(
        1
        for span in trace_spans
        if getattr(span, "metadata", {}).get("langfuse_mirror_status") == "error"
    )
    model_route = build_model_route_decision(settings)
    selected_provider_kind = (
        model_route.selected.provider_kind if model_route.selected is not None else "none"
    )
    temporal_cutover = temporal_cutover_status(settings)
    lines = [
        "# HELP competiscope_api_up Competiscope API process health.",
        "# TYPE competiscope_api_up gauge",
        "competiscope_api_up 1",
        "# HELP competiscope_runs_total Runs recorded by status.",
        "# TYPE competiscope_runs_total gauge",
    ]
    for status in (
        "queued",
        "running",
        "interrupted",
        "completed",
        "completed_with_blockers",
        "failed",
    ):
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
            "# HELP competiscope_auth_policy_engine Active authorization policy engine.",
            "# TYPE competiscope_auth_policy_engine gauge",
            (
                'competiscope_auth_policy_engine{engine="internal"} '
                f'{1 if settings.auth_policy_engine == "internal" else 0}'
            ),
            (
                'competiscope_auth_policy_engine{engine="opa"} '
                f'{1 if settings.auth_policy_engine == "opa" else 0}'
            ),
            (
                'competiscope_auth_policy_engine{engine="cerbos"} '
                f'{1 if settings.auth_policy_engine == "cerbos" else 0}'
            ),
            "# HELP competiscope_auth_policy_external_configured External PDP URL config.",
            "# TYPE competiscope_auth_policy_external_configured gauge",
            f"competiscope_auth_policy_external_configured {1 if settings.auth_policy_url else 0}",
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
            "# HELP competiscope_langfuse_configured Langfuse key configuration status.",
            "# TYPE competiscope_langfuse_configured gauge",
            f"competiscope_langfuse_configured {_bool_metric(langfuse_health['configured'])}",
            "# HELP competiscope_langfuse_enabled Langfuse client availability status.",
            "# TYPE competiscope_langfuse_enabled gauge",
            f"competiscope_langfuse_enabled {_bool_metric(langfuse_health['enabled'])}",
            "# HELP competiscope_langfuse_errors_total Langfuse adapter errors observed.",
            "# TYPE competiscope_langfuse_errors_total gauge",
            f"competiscope_langfuse_errors_total {langfuse_health['error_count']}",
            (
                "# HELP competiscope_langfuse_disabled Langfuse disabled state by "
                "fixed reason."
            ),
            "# TYPE competiscope_langfuse_disabled gauge",
            (
                f'competiscope_langfuse_disabled{{reason="{langfuse_disabled_reason}"}} '
                f"{0 if langfuse_health['enabled'] else 1}"
            ),
            (
                "# HELP competiscope_langfuse_mirror_errors_total Persisted run spans "
                "whose Langfuse mirror failed."
            ),
            "# TYPE competiscope_langfuse_mirror_errors_total gauge",
            f"competiscope_langfuse_mirror_errors_total {langfuse_mirror_errors}",
            (
                "# HELP competiscope_pydantic_ai_model_backed_enabled Model-backed "
                "Pydantic-AI execution switch."
            ),
            "# TYPE competiscope_pydantic_ai_model_backed_enabled gauge",
            (
                "competiscope_pydantic_ai_model_backed_enabled "
                f"{1 if settings.pydantic_ai_model_backed_enabled else 0}"
            ),
            "# HELP competiscope_model_route_status Active model router status.",
            "# TYPE competiscope_model_route_status gauge",
            (
                'competiscope_model_route_status{status="selected"} '
                f'{1 if model_route.status == "selected" else 0}'
            ),
            (
                'competiscope_model_route_status{status="fallback"} '
                f'{1 if model_route.status == "fallback" else 0}'
            ),
            (
                'competiscope_model_route_status{status="blocked"} '
                f'{1 if model_route.status == "blocked" else 0}'
            ),
            "# HELP competiscope_model_route_selected Active selected model provider kind.",
            "# TYPE competiscope_model_route_selected gauge",
            (
                'competiscope_model_route_selected{provider_kind="primary"} '
                f'{1 if selected_provider_kind == "primary" else 0}'
            ),
            (
                'competiscope_model_route_selected{provider_kind="backup"} '
                f'{1 if selected_provider_kind == "backup" else 0}'
            ),
            (
                'competiscope_model_route_selected{provider_kind="demo"} '
                f'{1 if selected_provider_kind == "demo" else 0}'
            ),
            (
                'competiscope_model_route_selected{provider_kind="none"} '
                f'{1 if selected_provider_kind == "none" else 0}'
            ),
            (
                "# HELP competiscope_model_route_blocked_reasons_total Current "
                "model route blocked reason count."
            ),
            "# TYPE competiscope_model_route_blocked_reasons_total gauge",
            f"competiscope_model_route_blocked_reasons_total {len(model_route.blocked_reasons)}",
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
            "# HELP competiscope_memory_feedback_total MemoryAgent feedback records.",
            "# TYPE competiscope_memory_feedback_total gauge",
            f"competiscope_memory_feedback_total {_memory_metric(memory_stats, 'feedback_count')}",
            "# HELP competiscope_memory_candidates_total MemoryAgent candidates by status.",
            "# TYPE competiscope_memory_candidates_total gauge",
            (
                'competiscope_memory_candidates_total{status="all"} '
                f"{_memory_metric(memory_stats, 'candidate_count')}"
            ),
            (
                'competiscope_memory_candidates_total{status="confirmed"} '
                f"{_memory_metric(memory_stats, 'confirmed_candidate_count')}"
            ),
            (
                "# HELP competiscope_memory_candidate_confirmed_ratio Share of "
                "MemoryAgent candidates approved for future run recall."
            ),
            "# TYPE competiscope_memory_candidate_confirmed_ratio gauge",
            f"competiscope_memory_candidate_confirmed_ratio {memory_confirmed_ratio:.6f}",
            "# HELP competiscope_retention_status Current aggregate retention status.",
            "# TYPE competiscope_retention_status gauge",
            (
                'competiscope_retention_status{status="pass"} '
                f'{1 if retention_status == "pass" else 0}'
            ),
            (
                'competiscope_retention_status{status="warn"} '
                f'{1 if retention_status == "warn" else 0}'
            ),
            (
                'competiscope_retention_status{status="fail"} '
                f'{1 if retention_status == "fail" else 0}'
            ),
            (
                "# HELP competiscope_retention_expired_records_total Records beyond "
                "configured retention windows."
            ),
            "# TYPE competiscope_retention_expired_records_total gauge",
            f"competiscope_retention_expired_records_total {retention_expired_count}",
            (
                "# HELP competiscope_retention_expiring_soon_records_total Records "
                "approaching configured retention windows."
            ),
            "# TYPE competiscope_retention_expiring_soon_records_total gauge",
            f"competiscope_retention_expiring_soon_records_total {retention_expiring_soon_count}",
            "# HELP competiscope_retention_physical_delete_enabled Retention delete mode.",
            "# TYPE competiscope_retention_physical_delete_enabled gauge",
            (
                "competiscope_retention_physical_delete_enabled "
                f"{1 if settings.retention_physical_delete_enabled else 0}"
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


def _load_memory_stats(preference_memory: PreferenceMemoryStore | None) -> MemoryStats | None:
    if preference_memory is None:
        return None
    try:
        return preference_memory.stats()
    except Exception:  # noqa: BLE001 - metrics should degrade instead of failing health scrape.
        return None


def _memory_metric(stats: MemoryStats | None, field_name: str) -> int:
    value = getattr(stats, field_name, 0) if stats is not None else 0
    return int(value) if isinstance(value, int) else 0


def _load_retention_reports(
    enterprise_store: EnterpriseStore | None,
    settings: Settings,
) -> list[object]:
    if enterprise_store is None:
        return []
    try:
        return [
            build_data_retention_report(
                store=enterprise_store,
                workspace_id=workspace.id,
                settings=settings,
            )
            for workspace in enterprise_store.list_workspaces()
        ]
    except Exception:  # noqa: BLE001 - metrics should degrade instead of failing health scrape.
        return []


def _retention_status(reports: list[object]) -> str:
    statuses = {str(getattr(report, "status", "pass")) for report in reports}
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    return "pass"


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


def _bool_metric(value: object) -> int:
    return 1 if value is True else 0


def _metric_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
