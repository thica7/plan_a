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


class RunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(default="default-workspace", min_length=1, max_length=120)
    project_id: str | None = Field(default=None, min_length=1, max_length=160)
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
    workspace_id: str = "default-workspace"
    project_id: str | None = None
    topic: str
    status: Literal["queued", "running", "interrupted", "completed", "failed"]
    execution_mode: Literal["demo", "real"]
    created_at: datetime
    updated_at: datetime


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


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_execution_mode: Literal["demo", "real"]
    demo_mode: bool
    has_ark_api_key: bool
    has_ark_model: bool
    ark_base_url: str
    ark_model: str | None = None
    web_search_provider: str
    has_web_search_key: bool
    auto_redo_enabled: bool
    auto_redo_warn_enabled: bool
    hitl_enabled: bool
    hitl_timeout_seconds: float


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
