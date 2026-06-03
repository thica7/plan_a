from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from packages.schema.models import (
    AgentMessage,
    AnalysisPlan,
    ComparisonMatrix,
    CompetitorDiscovery,
    CompetitorKB,
    CompetitorKnowledge,
    QCIssue,
    RawSource,
    ReflectionRecord,
    RevisionRecord,
    RunMetrics,
    ToolCallMessage,
    TraceSpan,
)

RunStatus = Literal[
    "queued",
    "running",
    "interrupted",
    "completed",
    "completed_with_blockers",
    "failed",
]


class RunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(default="default-workspace", min_length=1, max_length=120)
    project_id: str | None = Field(default=None, min_length=1, max_length=160)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=200)
    topic: str = Field(min_length=2, max_length=200)
    competitors: list[str] = Field(default_factory=list, max_length=8)
    dimensions: list[str] = Field(min_length=1, max_length=8)
    competitor_layer: Literal["L1", "L2", "L3"] | None = None
    scenario_id: str | None = Field(default=None, min_length=1, max_length=120)
    execution_mode: Literal["auto", "demo", "real"] = "auto"
    auto_redo_warn_enabled: bool | None = None


class HitlResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["accept", "modify_plan", "force_pass", "redo"]
    note: str | None = None
    dimensions: list[str] | None = None


class RunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    idempotency_key: str = ""
    workspace_id: str = "default-workspace"
    project_id: str | None = None
    topic: str
    status: RunStatus
    execution_mode: Literal["demo", "real"]
    created_at: datetime
    updated_at: datetime


class WorkflowStartResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: str
    workflow_type: Literal["CompetitiveIntelWorkflow"] = "CompetitiveIntelWorkflow"
    run_id: str
    idempotency_key: str
    task_queue: str
    status: Literal["started", "already_started"]


class WorkflowStateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: str
    task_queue: str
    status: Literal[
        "initialized",
        "creating_run",
        "running_langgraph",
        "loading_projection",
        "running",
        "waiting",
        "completed",
        "partial",
        "empty",
        "interrupted",
        "timed_out",
        "failed",
        "unknown",
    ] = "unknown"
    state: dict[str, Any] = Field(default_factory=dict)


class ScheduledScanStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(min_length=1, max_length=120)
    schedule_id: str = Field(default="default-weekly-scan", min_length=1, max_length=160)
    requested_by: str = Field(default="system-user", min_length=1, max_length=120)
    project_ids: list[str] = Field(default_factory=list, max_length=50)
    dimensions: list[str] = Field(
        default_factory=lambda: ["pricing", "feature", "persona"],
        min_length=1,
        max_length=8,
    )
    execution_mode: Literal["auto", "demo", "real"] = "auto"
    max_projects: int = Field(default=10, ge=1, le=50)
    cron_schedule: str | None = Field(default=None, min_length=1, max_length=120)


class ScheduledScanStartResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: str
    workflow_type: Literal["ScheduledScanWorkflow"] = "ScheduledScanWorkflow"
    workspace_id: str
    schedule_id: str
    task_queue: str
    status: Literal["started", "already_started"]


class MonitorStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(min_length=1, max_length=120)
    project_id: str = Field(min_length=1, max_length=160)
    monitor_id: str = Field(default="default-project-monitor", min_length=1, max_length=160)
    requested_by: str = Field(default="system-user", min_length=1, max_length=120)
    dimensions: list[str] = Field(
        default_factory=lambda: ["pricing", "feature", "persona"],
        min_length=1,
        max_length=8,
    )
    execution_mode: Literal["auto", "demo", "real"] = "auto"
    interval_seconds: int = Field(default=604800, ge=1, le=2592000)
    max_cycles: int = Field(default=1, ge=1, le=52)


class MonitorStartResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: str
    workflow_type: Literal["MonitorWorkflow"] = "MonitorWorkflow"
    workspace_id: str
    project_id: str
    monitor_id: str
    task_queue: str
    status: Literal["started", "already_started"]


class ReportApprovalStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_version_id: str = Field(min_length=1, max_length=200)
    requested_by: str = Field(default="system-user", min_length=1, max_length=120)
    approver_ids: list[str] = Field(default_factory=list, max_length=20)
    timeout_seconds: int = Field(default=86400, ge=1, le=604800)


class ReportApprovalStartResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: str
    workflow_type: Literal["ReportApprovalWorkflow"] = "ReportApprovalWorkflow"
    report_version_id: str
    task_queue: str
    status: Literal["started", "already_started"]


class ReportApprovalSignalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approver_id: str = Field(min_length=1, max_length=120)
    note: str = Field(default="", max_length=1000)


class ReportApprovalSignalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: str
    workflow_type: Literal["ReportApprovalWorkflow"] = "ReportApprovalWorkflow"
    report_version_id: str
    decision: Literal["approved", "rejected"]
    status: Literal["signaled"]


class RunDetail(RunSummary):
    plan: AnalysisPlan
    max_iterations: int = Field(default=2, ge=1)
    auto_redo_warn_enabled: bool = False
    report_md: str = ""
    raw_sources: list[RawSource] = Field(default_factory=list)
    competitor_kbs: dict[str, CompetitorKB] = Field(default_factory=dict)
    competitor_knowledge: dict[str, CompetitorKnowledge] = Field(default_factory=dict)
    competitor_discovery: CompetitorDiscovery | None = None
    comparison_matrix: ComparisonMatrix | None = None
    qa_findings: list[QCIssue] = Field(default_factory=list)
    reflections: list[ReflectionRecord] = Field(default_factory=list)
    revisions: list[RevisionRecord] = Field(default_factory=list)
    agent_messages: list[AgentMessage] = Field(default_factory=list)
    tool_call_messages: list[ToolCallMessage] = Field(default_factory=list)
    trace_spans: list[TraceSpan] = Field(default_factory=list)
    metrics: RunMetrics = Field(default_factory=RunMetrics)
    current_node: str | None = None


class RunQualityMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    target_value: float
    baseline_value: float | None = None
    delta: float | None = None
    weight: float = Field(default=0.0, ge=0.0, le=1.0)
    direction: Literal["higher_is_better", "lower_is_better"] = "higher_is_better"
    status: Literal["improved", "regressed", "unchanged", "baseline_missing"]


class RunQualityComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_run_id: str
    baseline_run_id: str | None = None
    target_execution_mode: Literal["demo", "real"]
    baseline_execution_mode: Literal["demo", "real"] | None = None
    target_score: int = Field(ge=0, le=100)
    baseline_score: int | None = Field(default=None, ge=0, le=100)
    delta_score: int | None = None
    verdict: Literal["pass", "warn", "fail"]
    real_collection_signal: bool = False
    real_llm_signal: bool = False
    report_quality_signal: bool = False
    metrics: list[RunQualityMetric] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_execution_mode: Literal["demo", "real"]
    run_orchestration_backend: Literal["langgraph", "temporal"]
    demo_mode: bool
    has_ark_api_key: bool
    has_ark_model: bool
    ark_base_url: str
    ark_model: str | None = None
    has_backup_llm_api_key: bool
    has_backup_llm_model: bool
    backup_llm_base_url: str
    backup_llm_model: str | None = None
    web_search_provider: str
    has_web_search_key: bool
    auto_redo_enabled: bool
    auto_redo_warn_enabled: bool
    hitl_enabled: bool
    hitl_timeout_seconds: float
    hitl_demo_ready: bool
    hitl_ready_reason: str
    hitl_review_checkpoints: list[str]
    temporal_address: str
    temporal_namespace: str
    temporal_task_queue: str
    temporal_traffic_percent: int
    temporal_cutover_ready: bool
    temporal_cutover_reason: str
    compliance_redaction_enabled: bool
    compliance_redact_api_keys: bool
    compliance_redact_emails: bool
    compliance_redact_phones: bool
    compliance_allowed_domains: list[str]
    compliance_blocked_domains: list[str]
    compliance_require_source_urls: bool
    compliance_require_trace_context: bool
    pydantic_ai_model_backed_enabled: bool
    pydantic_ai_model_name: str | None = None
    pydantic_ai_available: bool
    pydantic_ai_model_backed_ready: bool
    pydantic_ai_model_backed_reason: str
    artifact_storage_backend: str
    artifact_storage_root: str
    auth_policy_engine: str
    auth_policy_external_configured: bool


class HealthCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: Literal["ok", "warn", "error"]
    detail: str = ""


class HealthStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "warn", "error"]
    service: str
    version: str
    checks: list[HealthCheck] = Field(default_factory=list)


class LlmSmokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(default="Reply with exactly: ok", min_length=2, max_length=500)


class SearchSmokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(default="AI coding assistant competitors", min_length=2, max_length=300)
    max_results: int = Field(default=3, ge=1, le=10)


class FetchSmokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: HttpUrl = "https://example.com"  # type: ignore[assignment]


class SmokeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component: Literal["llm", "search", "fetch", "minimal_run"]
    ok: bool
    message: str
    elapsed_ms: int
    details: dict[str, Any] = Field(default_factory=dict)
