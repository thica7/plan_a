from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class WorkspaceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str = ""
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class UserRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    email: str
    display_name: str
    role: Literal["owner", "admin", "analyst", "reviewer", "viewer"] = "owner"
    status: Literal["active", "disabled"] = "active"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ProjectRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    workspace_id: str
    name: str
    topic: str
    topic_normalized: str
    competitor_layer: Literal["L1", "L2", "L3", "unknown"] = "unknown"
    competitor_set_hash: str = ""
    scenario_id: str | None = None
    created_by: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class CompetitorRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    workspace_id: str
    name: str
    normalized_name: str
    layer: Literal["L1", "L2", "L3", "unknown"] = "unknown"
    homepage_url: HttpUrl | None = None
    aliases: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ProjectCompetitorLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    competitor_id: str
    role: Literal["target", "baseline", "adjacent"] = "target"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class EvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    workspace_id: str
    project_id: str
    run_id: str | None = None
    raw_source_id: str
    competitor_id: str
    dimension: str
    source_type: str
    title: str
    url: HttpUrl | None = None
    snippet: str = ""
    content_hash: str
    reliability_score: float = Field(default=0.0, ge=0.0, le=1.0)
    freshness_score: float = Field(default=0.0, ge=0.0, le=1.0)
    quality_label: Literal["unreviewed", "accepted", "rejected", "stale"] = "unreviewed"
    captured_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ClaimRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    workspace_id: str
    project_id: str
    run_id: str | None = None
    competitor_id: str
    claim_type: str
    claim_text: str
    evidence_ids: list[str] = Field(min_length=1)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    status: Literal["proposed", "accepted", "disputed", "rejected", "deprecated"] = "proposed"
    created_by_agent: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ReportVersionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    workspace_id: str
    project_id: str
    run_id: str | None = None
    parent_version_id: str | None = None
    version_number: int = Field(ge=1)
    topic_normalized: str
    competitor_layer: Literal["L1", "L2", "L3", "unknown"] = "unknown"
    competitor_set_hash: str
    status: Literal["draft", "in_review", "approved", "published", "archived"] = "draft"
    report_md: str = ""
    claim_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    published_at: datetime | None = None


class EnterpriseRunProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    project_id: str
    run_id: str
    evidence_records: list[EvidenceRecord] = Field(default_factory=list)
    claim_records: list[ClaimRecord] = Field(default_factory=list)
    report_version: ReportVersionRecord


class AuditLogRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    workspace_id: str
    actor_type: Literal["user", "agent", "workflow", "system"]
    actor_id: str | None = None
    action: str
    resource_type: str
    resource_id: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
