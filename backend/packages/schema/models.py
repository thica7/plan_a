from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class RedoScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["writer_only", "comparator", "analyst", "collector", "full"]
    target_subagent: str | None = None
    target_competitor: str | None = None
    rationale: str


class QCIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    severity: Literal["info", "warn", "blocker"]
    detected_by: Literal["citation", "consistency", "coverage", "schema", "reflector"]
    target_agent: str
    target_subagent: str | None = None
    field_path: str
    problem: str
    redo_scope: RedoScope
    self_found: bool = False


class ReflectionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    iteration: int
    coverage_gaps: list[str] = Field(default_factory=list)
    confidence_outliers: list[str] = Field(default_factory=list)
    cross_competitor_gaps: list[str] = Field(default_factory=list)
    suggested_redos: list[RedoScope] = Field(default_factory=list)


class AnalysisPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str
    competitors: list[str]
    dimensions: list[str]
    complexity: Literal["low", "medium", "high"] = "medium"
    homepage_hints: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RawSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    competitor: str
    covered_competitors: list[str] = Field(default_factory=list)
    dimension: str
    source_type: str
    title: str
    url: HttpUrl | None = None
    snippet: str = ""
    content_hash: str
    confidence: float = Field(ge=0.0, le=1.0)
    extracted_at: datetime = Field(default_factory=datetime.utcnow)


class CompetitorKB(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor: str
    slices: dict[str, list[str]] = Field(default_factory=dict)
    sources: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ComparisonCell(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor: str
    dimension: str
    value: str
    source_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ComparisonMatrix(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitors: list[str]
    dimensions: list[str]
    cells: list[ComparisonCell] = Field(default_factory=list)
    winner_by_dimension: dict[str, str] = Field(default_factory=dict)
    summary: list[str] = Field(default_factory=list)


class CompetitorCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    rank: int
    selected: bool = False
    rationale: str = ""
    evidence_titles: list[str] = Field(default_factory=list)
    evidence_urls: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class CompetitorDiscovery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    candidates: list[CompetitorCandidate] = Field(default_factory=list)
    selected_competitors: list[str] = Field(default_factory=list)
    rationale: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RevisionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    iteration: int
    stage: str
    before_md: str = ""
    after_md: str = ""
    issue_ids: list[str] = Field(default_factory=list)
    issue_count_before: int = 0
    issue_count_after: int = 0
    convergence_ratio: float = Field(default=1.0, ge=0.0)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class TraceSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["llm", "search", "fetch", "tool"]
    agent: str
    subagent: str | None = None
    name: str
    status: Literal["ok", "error"]
    model: str | None = None
    provider: str | None = None
    duration_ms: int = Field(ge=0)
    input_chars: int = Field(default=0, ge=0)
    output_chars: int = Field(default=0, ge=0)
    input_tokens_estimate: int = Field(default=0, ge=0)
    output_tokens_estimate: int = Field(default=0, ge=0)
    cost_estimate_usd: float = Field(default=0.0, ge=0.0)
    input_preview: str = ""
    output_preview: str = ""
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RunMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_spans: int = 0
    total_duration_ms: int = 0
    llm_calls: int = 0
    search_calls: int = 0
    fetch_calls: int = 0
    input_tokens_estimate: int = 0
    output_tokens_estimate: int = 0
    cost_estimate_usd: float = 0.0


class SkillOutputSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prefix: str
    confidence_default: float = Field(default=0.8, ge=0.0, le=1.0)
    confidence_no_url: float = Field(default=0.5, ge=0.0, le=1.0)
    required_dimension: str


class SkillSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    subagent_class: str = "GenericCollector"
    description: str
    tools_allowlist: list[str]
    query_templates: list[str]
    max_turns: int = Field(default=6, ge=1, le=12)
    source_type: str
    output: SkillOutputSpec
