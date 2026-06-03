from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

CREATE_RUN_ACTIVITY = "create_competitive_intel_run"
RUN_LANGGRAPH_ACTIVITY = "run_competitive_intel_langgraph"
LOAD_PROJECTION_ACTIVITY = "load_competitive_intel_projection"
REQUEST_REPORT_APPROVAL_ACTIVITY = "request_report_approval"
APPROVE_REPORT_VERSION_ACTIVITY = "approve_report_version"
REJECT_REPORT_VERSION_ACTIVITY = "reject_report_version"
LIST_SCHEDULED_SCAN_TARGETS_ACTIVITY = "list_scheduled_scan_targets"
RUN_SCHEDULED_SCAN_PROJECT_ACTIVITY = "run_scheduled_scan_project"
RECORD_SCHEDULED_SCAN_NOTIFICATION_ACTIVITY = "record_scheduled_scan_notification"
RUN_MONITOR_CYCLE_ACTIVITY = "run_monitor_cycle"
RECORD_MONITOR_ANOMALY_NOTIFICATION_ACTIVITY = "record_monitor_anomaly_notification"
DEFAULT_TEMPORAL_TASK_QUEUE = "competitive-intel"

RunStatus = Literal[
    "queued",
    "running",
    "interrupted",
    "completed",
    "completed_with_blockers",
    "failed",
]
ExecutionMode = Literal["auto", "demo", "real"]
WorkflowStatus = Literal["completed", "interrupted", "failed"]
ScheduledScanStatus = Literal["completed", "partial", "failed", "empty"]
ScheduledScanProjectStatus = Literal["completed", "interrupted", "failed"]
MonitorStatus = Literal["completed", "partial", "failed"]
MonitorCycleStatus = Literal["completed", "interrupted", "failed"]
MonitorAnomalySeverity = Literal["info", "warning", "critical"]
MonitorAnomalyType = Literal[
    "scan_failed",
    "report_missing",
    "report_changed",
    "evidence_drop",
    "claim_drop",
]
ReportApprovalDecision = Literal["approved", "rejected", "timed_out"]
ReportApprovalSignalDecision = Literal["approved", "rejected"]
ReportVersionWorkflowStatus = Literal["draft", "in_review", "approved", "published", "archived"]


@dataclass(frozen=True)
class CompetitiveIntelWorkflowInput:
    topic: str
    dimensions: list[str]
    competitors: list[str] = field(default_factory=list)
    workspace_id: str = "default-workspace"
    project_id: str | None = None
    idempotency_key: str = ""
    competitor_layer: Literal["L1", "L2", "L3"] | None = None
    scenario_id: str | None = None
    execution_mode: ExecutionMode = "auto"
    auto_redo_warn_enabled: bool | None = None
    hitl_enabled: bool | None = None


@dataclass(frozen=True)
class WorkflowRunState:
    run_id: str
    idempotency_key: str
    status: RunStatus
    workspace_id: str
    project_id: str | None
    current_node: str | None = None
    report_chars: int = 0
    qa_finding_count: int = 0


@dataclass(frozen=True)
class WorkflowProjectionState:
    run_id: str
    workspace_id: str
    project_id: str | None
    report_version_id: str | None = None
    evidence_count: int = 0
    claim_count: int = 0


@dataclass(frozen=True)
class CompetitiveIntelWorkflowResult:
    run_id: str
    idempotency_key: str
    status: WorkflowStatus
    workspace_id: str
    project_id: str | None
    report_version_id: str | None = None
    evidence_count: int = 0
    claim_count: int = 0
    report_chars: int = 0
    qa_finding_count: int = 0


@dataclass(frozen=True)
class ScheduledScanWorkflowInput:
    workspace_id: str
    schedule_id: str = "default-weekly-scan"
    requested_by: str = "system-user"
    project_ids: list[str] = field(default_factory=list)
    dimensions: list[str] = field(default_factory=lambda: ["pricing", "feature", "persona"])
    execution_mode: ExecutionMode = "auto"
    max_projects: int = 10


@dataclass(frozen=True)
class ScheduledScanTarget:
    project_id: str
    workspace_id: str
    topic: str
    competitors: list[str] = field(default_factory=list)
    dimensions: list[str] = field(default_factory=list)
    competitor_layer: Literal["L1", "L2", "L3"] | None = None
    scenario_id: str | None = None


@dataclass(frozen=True)
class ScheduledScanProjectInput:
    request: ScheduledScanWorkflowInput
    target: ScheduledScanTarget
    scan_started_at: str


@dataclass(frozen=True)
class ScheduledScanProjectResult:
    project_id: str
    run_id: str | None
    status: ScheduledScanProjectStatus
    report_version_id: str | None = None
    evidence_count: int = 0
    claim_count: int = 0
    error: str = ""


@dataclass(frozen=True)
class ScheduledScanNotificationInput:
    request: ScheduledScanWorkflowInput
    results: list[ScheduledScanProjectResult]
    scan_started_at: str


@dataclass(frozen=True)
class ScheduledScanNotificationState:
    notification_id: str | None
    status: str


@dataclass(frozen=True)
class ScheduledScanWorkflowResult:
    workspace_id: str
    schedule_id: str
    status: ScheduledScanStatus
    scanned_project_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    interrupted_count: int = 0
    run_ids: list[str] = field(default_factory=list)
    report_version_ids: list[str] = field(default_factory=list)
    notification_id: str | None = None
    scan_started_at: str = ""


@dataclass(frozen=True)
class MonitorWorkflowInput:
    workspace_id: str
    project_id: str
    monitor_id: str = "default-project-monitor"
    requested_by: str = "system-user"
    dimensions: list[str] = field(default_factory=lambda: ["pricing", "feature", "persona"])
    execution_mode: ExecutionMode = "auto"
    interval_seconds: int = 604800
    max_cycles: int = 1


@dataclass(frozen=True)
class MonitorSnapshot:
    project_id: str
    report_version_id: str | None = None
    run_id: str | None = None
    evidence_count: int = 0
    claim_count: int = 0
    report_chars: int = 0
    report_hash: str = ""


@dataclass(frozen=True)
class MonitorAnomaly:
    id: str
    severity: MonitorAnomalySeverity
    anomaly_type: MonitorAnomalyType
    message: str
    metadata: dict[str, str | int] = field(default_factory=dict)


@dataclass(frozen=True)
class MonitorCycleInput:
    request: MonitorWorkflowInput
    cycle_index: int
    monitor_started_at: str


@dataclass(frozen=True)
class MonitorCycleResult:
    cycle_index: int
    project_id: str
    status: MonitorCycleStatus
    previous: MonitorSnapshot | None = None
    current: MonitorSnapshot | None = None
    run_id: str | None = None
    report_version_id: str | None = None
    anomalies: list[MonitorAnomaly] = field(default_factory=list)
    error: str = ""


@dataclass(frozen=True)
class MonitorAnomalyNotificationInput:
    request: MonitorWorkflowInput
    cycle_result: MonitorCycleResult
    monitor_started_at: str


@dataclass(frozen=True)
class MonitorAnomalyNotificationState:
    notification_id: str | None
    status: str
    anomaly_count: int = 0


@dataclass(frozen=True)
class MonitorWorkflowResult:
    workspace_id: str
    project_id: str
    monitor_id: str
    status: MonitorStatus
    cycle_count: int = 0
    failed_count: int = 0
    anomaly_count: int = 0
    run_ids: list[str] = field(default_factory=list)
    notification_ids: list[str] = field(default_factory=list)
    monitor_started_at: str = ""


@dataclass(frozen=True)
class ReportApprovalWorkflowInput:
    report_version_id: str
    requested_by: str = "system-user"
    approver_ids: list[str] = field(default_factory=list)
    timeout_seconds: int = 86400


@dataclass(frozen=True)
class ReportApprovalDecisionInput:
    report_version_id: str
    approver_id: str
    note: str = ""


@dataclass(frozen=True)
class ReportApprovalState:
    report_version_id: str
    workspace_id: str
    project_id: str
    status: ReportVersionWorkflowStatus
    approver_id: str | None = None
    note: str = ""


@dataclass(frozen=True)
class ReportApprovalWorkflowResult:
    report_version_id: str
    workspace_id: str
    project_id: str
    decision: ReportApprovalDecision
    final_status: ReportVersionWorkflowStatus
    approver_id: str | None = None
    note: str = ""
