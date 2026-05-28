from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

CREATE_RUN_ACTIVITY = "create_competitive_intel_run"
RUN_LANGGRAPH_ACTIVITY = "run_competitive_intel_langgraph"
LOAD_PROJECTION_ACTIVITY = "load_competitive_intel_projection"
REQUEST_REPORT_APPROVAL_ACTIVITY = "request_report_approval"
APPROVE_REPORT_VERSION_ACTIVITY = "approve_report_version"
REJECT_REPORT_VERSION_ACTIVITY = "reject_report_version"
DEFAULT_TEMPORAL_TASK_QUEUE = "competitive-intel"

RunStatus = Literal["queued", "running", "interrupted", "completed", "failed"]
ExecutionMode = Literal["auto", "demo", "real"]
WorkflowStatus = Literal["completed", "interrupted", "failed"]
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
