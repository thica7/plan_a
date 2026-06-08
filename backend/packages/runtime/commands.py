from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from packages.schema.api_dto import (
    HitlResumeRequest,
    ReportApprovalSignalRequest,
    ReportApprovalStartRequest,
    RunCreateRequest,
)
from packages.schema.enterprise import (
    ManualReportRevisionRequest,
    MonitorJobCreateRequest,
    MonitorJobUpdateRequest,
)

RuntimeCommandType = Literal[
    "create_run",
    "create_monitor_job",
    "update_monitor_job",
    "pause_monitor_job",
    "resume_monitor_job",
    "trigger_monitor_job",
    "request_review",
    "resume_review",
    "request_redo",
    "revise_report",
    "request_approval",
    "approve_report",
    "reject_report",
    "publish_report",
    "archive_report",
]
RuntimeCommandStatus = Literal["accepted", "succeeded", "blocked", "failed"]
RuntimeCommandRoute = Literal["temporal", "langgraph", "enterprise", "none"]


class RuntimeCommandError(Exception):
    def __init__(
        self,
        status_code: int,
        detail: Any,
        *,
        command_type: RuntimeCommandType | None = None,
    ) -> None:
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail
        self.command_type = command_type


class CreateRunCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request: RunCreateRequest


class CreateMonitorJobCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request: MonitorJobCreateRequest


class UpdateMonitorJobCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    monitor_id: str = Field(min_length=1, max_length=200)
    request: MonitorJobUpdateRequest


class PauseMonitorJobCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    monitor_id: str = Field(min_length=1, max_length=200)


class ResumeMonitorJobCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    monitor_id: str = Field(min_length=1, max_length=200)


class TriggerMonitorJobCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    monitor_id: str = Field(min_length=1, max_length=200)


class ReviseReportCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_version_id: str = Field(min_length=1, max_length=200)
    request: ManualReportRevisionRequest


class ResumeReviewCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1, max_length=200)
    request: HitlResumeRequest


class RequestRedoCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1, max_length=200)


class RequestApprovalCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request: ReportApprovalStartRequest


class ApproveReportCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_version_id: str = Field(min_length=1, max_length=200)
    request: ReportApprovalSignalRequest


class RejectReportCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_version_id: str = Field(min_length=1, max_length=200)
    request: ReportApprovalSignalRequest


class PublishReportCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_version_id: str = Field(min_length=1, max_length=200)


class RuntimeCommandResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    command_id: str
    command_type: RuntimeCommandType
    status: RuntimeCommandStatus
    resource_type: str
    resource_id: str | None = None
    workspace_id: str | None = None
    project_id: str | None = None
    run_id: str | None = None
    report_version_id: str | None = None
    audit_correlation_id: str
    replay_correlation_id: str
    route: RuntimeCommandRoute = "none"
    payload: Any = None
    metadata: dict[str, Any] = Field(default_factory=dict)
