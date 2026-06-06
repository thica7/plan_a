from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.identity import stable_prefixed_id

CandidateOrigin = Literal[
    "trusted_registry",
    "perplexity",
    "web_search",
    "homepage_derived",
    "llm_fallback",
    "manual",
]

CaptureStatus = Literal["ok", "failed", "rejected"]
ExtractionStatus = Literal["extracted", "partial", "empty", "not_applicable"]
EvidenceStatus = Literal["accepted", "rejected", "unreviewed"]
GapSeverity = Literal["info", "warn", "blocker"]
RepairStrategy = Literal[
    "targeted_discovery",
    "pricing_model_repair",
    "feature_slot_repair",
    "persona_schema_repair",
    "mark_not_applicable",
    "human_review",
]
RepairRequiredAction = Literal[
    "add_evidence",
    "rewrite_claim",
    "downgrade_claim",
    "delete_claim",
    "rewrite_report",
    "human_review",
    "rerun_scope",
]


class ResearchBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResearchBrief(ResearchBaseModel):
    run_id: str
    topic: str
    competitor: str
    dimension: str
    execution_mode: Literal["demo", "real"] = "real"
    homepage_hint: str | None = None
    target_source_count: int = Field(default=3, ge=1, le=10)
    max_search_queries: int = Field(default=2, ge=0, le=10)
    max_candidates: int = Field(default=12, ge=1, le=50)
    max_fetches: int = Field(default=6, ge=1, le=30)
    max_advanced_fetches: int = Field(default=3, ge=0, le=20)
    max_repair_rounds: int = Field(default=1, ge=0, le=3)
    gap_ids: list[str] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def branch_key(self) -> str:
        return stable_prefixed_id(
            "research-branch", self.run_id, self.competitor, self.dimension, length=16
        )


class SourceCandidate(ResearchBaseModel):
    id: str = ""
    title: str
    url: str
    snippet: str = ""
    origin: CandidateOrigin
    competitor: str = ""
    dimension: str = ""
    rank: int = 0
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    query: str | None = None
    reason: str = ""
    date: str | None = None
    last_updated: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def fill_stable_id(self) -> SourceCandidate:
        if not self.id:
            self.id = stable_prefixed_id(
                "source-candidate",
                self.origin,
                self.competitor,
                self.dimension,
                str(self.url).rstrip("/"),
                self.rank,
                length=20,
            )
        return self

    def to_search_result(self):
        from packages.search import SearchResult

        return SearchResult(
            title=self.title,
            url=str(self.url),
            snippet=self.snippet,
            date=self.date,
            last_updated=self.last_updated,
        )


class CapturedPage(ResearchBaseModel):
    id: str = ""
    candidate_id: str
    requested_url: str
    final_url: str
    status: CaptureStatus
    title: str = ""
    text: str = ""
    markdown: str = ""
    snippet: str = ""
    content_hash: str
    status_code: int | None = None
    error: str | None = None
    fetch_method: str = ""
    quality_score: float = Field(default=0.0, ge=0.0, le=1.0)
    text_length: int = Field(default=0, ge=0)
    failure_reason: str | None = None
    captured_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def fill_stable_id_and_snippet(self) -> CapturedPage:
        if not self.id:
            self.id = stable_prefixed_id(
                "captured-page",
                self.candidate_id,
                str(self.final_url).rstrip("/"),
                self.content_hash,
                length=20,
            )
        if not self.snippet:
            self.snippet = (self.text or self.markdown)[:700]
        if not self.text_length:
            self.text_length = len(self.text or self.markdown)
        return self


class EvidenceQuote(ResearchBaseModel):
    text: str
    source_url: str | None = None
    field: str = ""
    start_offset: int | None = None
    end_offset: int | None = None


class ExtractionResult(ResearchBaseModel):
    id: str = ""
    competitor: str
    dimension: str
    source_candidate_id: str
    captured_page_id: str
    fields: dict[str, Any] = Field(default_factory=dict)
    quotes: list[EvidenceQuote] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    extractor_name: str
    extractor_version: str = "1"
    status: ExtractionStatus = "extracted"
    missing_fields: list[str] = Field(default_factory=list)
    not_applicable_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def fill_stable_id(self) -> ExtractionResult:
        if not self.id:
            self.id = stable_prefixed_id(
                "extraction",
                self.extractor_name,
                self.competitor,
                self.dimension,
                self.captured_page_id,
                self.extractor_version,
                length=20,
            )
        return self


class EvidenceItem(ResearchBaseModel):
    id: str = ""
    competitor: str
    dimension: str
    field: str
    value: Any = None
    source_candidate_id: str
    captured_page_id: str
    source_url: str | None = None
    quote: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    status: EvidenceStatus = "unreviewed"
    rejection_reason: str | None = None
    raw_source_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def fill_stable_id(self) -> EvidenceItem:
        if not self.id:
            self.id = stable_prefixed_id(
                "evidence-item",
                self.competitor,
                self.dimension,
                self.field,
                self.captured_page_id,
                self.quote or self.value,
                length=20,
            )
        return self


class QualityGap(ResearchBaseModel):
    id: str = ""
    severity: GapSeverity
    dimension: str
    competitor: str | None = None
    field: str | None = None
    reason: str
    suggested_action: RepairStrategy
    acceptance_rule: str
    source_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def fill_stable_id(self) -> QualityGap:
        if not self.id:
            self.id = stable_prefixed_id(
                "quality-gap",
                self.severity,
                self.dimension,
                self.competitor or "",
                self.field or "",
                self.reason,
                length=20,
            )
        return self


class RepairTask(ResearchBaseModel):
    id: str = ""
    gap_id: str
    strategy: RepairStrategy
    required_action: RepairRequiredAction = "add_evidence"
    competitor: str | None = None
    dimension: str
    target_fields: list[str] = Field(default_factory=list)
    query_hints: list[str] = Field(default_factory=list)
    max_queries: int = Field(default=3, ge=0, le=10)
    max_candidates: int = Field(default=12, ge=1, le=50)
    max_fetches: int = Field(default=6, ge=1, le=30)
    acceptance_rule: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def fill_stable_id(self) -> RepairTask:
        if not self.id:
            self.id = stable_prefixed_id(
                "repair-task",
                self.gap_id,
                self.strategy,
                self.required_action,
                self.competitor or "",
                self.dimension,
                self.target_fields,
                length=20,
            )
        return self


class NormalizedPricingField(ResearchBaseModel):
    kind: Literal["pricing"] = "pricing"
    dimension: str = "pricing"
    competitor: str = ""
    model_type: str = ""
    tier_name: str = ""
    price: str = ""
    billing_cycle: str = ""
    usage_limit: str = ""
    enterprise_condition: str = ""
    source_quote: str = ""
    evidence_item_ids: list[str] = Field(default_factory=list)
    source_url: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class NormalizedFeatureField(ResearchBaseModel):
    kind: Literal["feature"] = "feature"
    dimension: str = "feature"
    competitor: str = ""
    slot: str
    support_level: str = ""
    evidence_terms: list[str] = Field(default_factory=list)
    evidence_quote: str = ""
    evidence_item_ids: list[str] = Field(default_factory=list)
    source_url: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class NormalizedPersonaField(ResearchBaseModel):
    kind: Literal["persona"] = "persona"
    dimension: str = "persona"
    competitor: str = ""
    segment: str = ""
    role: str = ""
    company_size: str = ""
    use_case: str = ""
    pain_point: str = ""
    confidence_reason: str = ""
    evidence_quote: str = ""
    evidence_item_ids: list[str] = Field(default_factory=list)
    source_url: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


NormalizedEvidenceField = (
    NormalizedPricingField | NormalizedFeatureField | NormalizedPersonaField
)


class ResearchResult(ResearchBaseModel):
    brief: ResearchBrief
    candidates: list[SourceCandidate] = Field(default_factory=list)
    captured_pages: list[CapturedPage] = Field(default_factory=list)
    extractions: list[ExtractionResult] = Field(default_factory=list)
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    normalized_fields: list[NormalizedEvidenceField] = Field(default_factory=list)
    raw_source_ids: list[str] = Field(default_factory=list)
    gaps: list[QualityGap] = Field(default_factory=list)
    repair_tasks: list[RepairTask] = Field(default_factory=list)
    assembly: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
