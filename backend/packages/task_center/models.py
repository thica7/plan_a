"""Public projections and trusted, internal task-center inputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from packages.auth.rbac import EnterpriseUserContext
from packages.schema.api_dto import RunCreateRequest

SubmissionStatus = Literal["pending", "dispatching", "dispatched", "cancelled", "dispatch_failed"]
Enforcement = Literal["block", "monitor"]


@dataclass(frozen=True)
class QuotaSeed:
    run_limit: int
    enforcement: Enforcement
    legacy_runs: list[Any] = field(default_factory=list)
    policy_version: int = 1

    def __post_init__(self) -> None:
        if (
            type(self.run_limit) is not int
            or self.run_limit < 0
            or self.enforcement not in ("block", "monitor")
            or type(self.policy_version) is not int
            or self.policy_version < 1
        ):
            raise ValueError("invalid trusted quota policy")


class SubmissionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: RunCreateRequest
    idempotency_key: str = Field(min_length=1, max_length=200)


class SubmissionView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    workspace_id: str
    project_id: str | None
    status: SubmissionStatus
    expected_run_id: str
    run_id: str | None
    workflow_id: str | None
    created_at: datetime
    updated_at: datetime
    period_start: datetime
    dispatch_attempt_count: int
    last_error_code: str | None
    run_status: str | None = None
    run_status_observed_at: datetime | None = None


class SubmissionPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[SubmissionView]
    next_cursor: str | None = None


class QuotaSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: str
    period_start: datetime
    period_end: datetime
    limit: int
    enforcement: Enforcement
    imported_count: int
    reserved_count: int
    available: int


class QuotaLedgerEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    workspace_id: str
    submission_id: str
    period_start: datetime
    action: Literal["reserve", "release"]
    amount: int
    created_at: datetime


class QuotaLedgerPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[QuotaLedgerEntry]
    next_cursor: str | None = None
    snapshot: QuotaSnapshot


@dataclass(frozen=True)
class DispatchClaim:
    """Trusted relay payload, deliberately separate from public API models."""

    submission_id: str
    workspace_id: str
    expected_run_id: str
    epoch: int
    generation: int
    owner_token: str
    lease_until: datetime
    attempt_count: int
    request: RunCreateRequest
    actor: EnterpriseUserContext
    delivery_intent: str = "runtime"
    execution_backend: str = "langgraph"
