from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from packages.agents.writer.structured_hygiene import has_source_token

Confidence = Literal["high", "medium", "low"]
EvidenceRole = Literal[
    "official_fact",
    "community_signal",
    "simulated_research",
    "inference",
    "evidence_gap",
]


def _clean_source_ids(value: list[str]) -> list[str]:
    cleaned = [item.strip() for item in value if item.strip()]
    if len(cleaned) != len(set(cleaned)):
        raise ValueError("source_ids must not contain duplicates")
    return cleaned


def _clean_required_string(field_name: str, value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be blank")
    return cleaned


class CitedText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    source_ids: list[str] = Field(default_factory=list)
    confidence: Confidence
    evidence_role: EvidenceRole

    @field_validator("text", mode="before")
    @classmethod
    def _text_has_no_markdown_source_tokens(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("text must be a string")
        text = value.strip()
        if has_source_token(text):
            raise ValueError("text must not contain Markdown source tokens")
        return text

    @field_validator("source_ids")
    @classmethod
    def _source_ids_are_clean(cls, value: list[str]) -> list[str]:
        return _clean_source_ids(value)

    @model_validator(mode="after")
    def _source_ids_required_except_gap(self) -> CitedText:
        if self.evidence_role != "evidence_gap" and not self.source_ids:
            raise ValueError(
                "source_ids are required unless evidence_role is evidence_gap"
            )
        if self.evidence_role == "evidence_gap" and self.confidence == "high":
            raise ValueError("evidence gaps cannot be high confidence")
        return self


class CompetitorPosture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor: str = Field(min_length=1)
    posture: CitedText


class ExecutiveSummarySection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation: CitedText
    risk_adjusted_rationale: CitedText
    competitor_postures: list[CompetitorPosture] = Field(min_length=1)
    confidence_boundary: CitedText
    next_actions: list[CitedText] = Field(min_length=1)


class CompetitorUserTheme(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor: str = Field(min_length=1)
    direct_user_signals: list[CitedText] = Field(default_factory=list)
    simulated_research_signals: list[CitedText] = Field(default_factory=list)
    adoption_blockers: list[CitedText] = Field(default_factory=list)
    switching_triggers: list[CitedText] = Field(default_factory=list)
    evidence_gaps: list[CitedText] = Field(default_factory=list)


class UserReviewThemesSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor_themes: list[CompetitorUserTheme] = Field(min_length=1)
    cross_competitor_patterns: list[CitedText] = Field(default_factory=list)
    evidence_limits: list[CitedText] = Field(default_factory=list)


class CompetitorDeepDiveSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor: str = Field(min_length=1)
    positioning: list[CitedText] = Field(default_factory=list)
    pricing_packaging: list[CitedText] = Field(default_factory=list)
    feature_capabilities: list[CitedText] = Field(default_factory=list)
    persona_adoption: list[CitedText] = Field(default_factory=list)
    community_feedback: list[CitedText] = Field(default_factory=list)
    competitive_plays: list[CitedText] = Field(default_factory=list)
    evidence_gaps: list[CitedText] = Field(default_factory=list)


class MatrixCell(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    source_ids: list[str] = Field(default_factory=list)
    confidence: Confidence

    @field_validator("summary", mode="before")
    @classmethod
    def _summary_has_no_source_tokens(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("matrix summary must be a string")
        summary = value.strip()
        if has_source_token(summary):
            raise ValueError("matrix summary must not contain Markdown source tokens")
        return summary

    @field_validator("source_ids")
    @classmethod
    def _source_ids_are_clean(cls, value: list[str]) -> list[str]:
        return _clean_source_ids(value)


class MatrixDimensionRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension: str = Field(min_length=1)
    cells: list[MatrixCell] = Field(min_length=1)


class DecisionMatrixSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimensions: list[MatrixDimensionRow] = Field(min_length=1)
    interpretation: list[CitedText] = Field(default_factory=list)
    confidence_notes: list[CitedText] = Field(default_factory=list)


class CompetitorSwot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor: str = Field(min_length=1)
    strengths: list[CitedText] = Field(default_factory=list)
    weaknesses: list[CitedText] = Field(default_factory=list)
    opportunities: list[CitedText] = Field(default_factory=list)
    threats: list[CitedText] = Field(default_factory=list)


class SwotSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitors: list[CompetitorSwot] = Field(min_length=1)


class BattlecardPlay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor: str = Field(min_length=1)
    target_buyer: str = Field(min_length=1)
    use_when: CitedText
    attack_points: list[CitedText] = Field(min_length=1)
    defense_points: list[CitedText] = Field(min_length=1)
    likely_objections: list[CitedText] = Field(min_length=1)
    rebuttal_talk_tracks: list[CitedText] = Field(min_length=1)
    proof_needed_before_external_use: list[CitedText] = Field(min_length=1)


class BattlecardSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plays: list[BattlecardPlay] = Field(default_factory=list)
    evidence_limits: list[CitedText] = Field(default_factory=list)


class SourceAppendixRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: str = ""
    competitor: str = ""
    dimension: str = ""
    evidence_role: EvidenceRole
    confidence: Confidence

    @field_validator("source_id", mode="before")
    @classmethod
    def _source_id_is_clean(cls, value: Any) -> str:
        return _clean_required_string("source_id", value)

    @field_validator("title", mode="before")
    @classmethod
    def _title_is_clean(cls, value: Any) -> str:
        return _clean_required_string("title", value)


class ReportCore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executive_summary: ExecutiveSummarySection
    decision_summary: list[CitedText] = Field(min_length=1)
    competitive_findings: list[CitedText] = Field(min_length=1)
    user_review_themes: UserReviewThemesSection
    competitor_deep_dives: list[CompetitorDeepDiveSection] = Field(min_length=1)
    decision_matrix: DecisionMatrixSection
    swot: SwotSection
    battlecard: BattlecardSection
    community_triangulation: list[CitedText] = Field(default_factory=list)


class ReportSupport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_quality: list[CitedText] = Field(default_factory=list)
    user_research_evidence: list[CitedText] = Field(default_factory=list)
    rag_gap_fill: list[CitedText] = Field(default_factory=list)
    scenario_qa: list[CitedText] = Field(default_factory=list)
    claim_risk: list[CitedText] = Field(default_factory=list)
    next_collection: list[CitedText] = Field(default_factory=list)
    evidence_appendix: list[SourceAppendixRow] = Field(default_factory=list)


class ReportMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    writer_mode: str = Field(min_length=1)
    segment_count: int = Field(ge=0)
    source_count: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)
    structured_report_version: str = Field(min_length=1)


class StructuredReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_language: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    competitors: list[str] = Field(min_length=1)
    dimensions: list[str] = Field(default_factory=list)
    core: ReportCore
    support: ReportSupport
    metadata: ReportMetadata

    def iter_cited_text(self) -> Iterable[tuple[str, CitedText]]:
        yield from _walk_cited_text("core", self.core)
        yield from _walk_cited_text("support", self.support)

    def iter_matrix_cells(self) -> Iterable[tuple[str, MatrixCell]]:
        for row_index, row in enumerate(self.core.decision_matrix.dimensions):
            for cell_index, cell in enumerate(row.cells):
                yield (
                    f"core.decision_matrix.dimensions[{row_index}].cells[{cell_index}]",
                    cell,
                )

    def iter_source_appendix_rows(self) -> Iterable[tuple[str, SourceAppendixRow]]:
        for row_index, row in enumerate(self.support.evidence_appendix):
            yield f"support.evidence_appendix[{row_index}]", row

    def compact_summary(self) -> dict[str, Any]:
        return {
            "writer_mode": self.metadata.writer_mode,
            "structured_report_version": self.metadata.structured_report_version,
            "competitors": list(self.competitors),
            "dimensions": list(self.dimensions),
            "core_section_count": 9,
            "support_section_count": 7,
            "source_count": self.metadata.source_count,
            "segment_count": self.metadata.segment_count,
            "warning_count": len(self.metadata.warnings),
        }


def _walk_cited_text(prefix: str, value: Any) -> Iterable[tuple[str, CitedText]]:
    if isinstance(value, CitedText):
        yield prefix, value
        return
    if isinstance(value, BaseModel):
        for field_name in type(value).model_fields:
            child = getattr(value, field_name)
            child_prefix = f"{prefix}.{field_name}"
            yield from _walk_cited_text(child_prefix, child)
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_cited_text(f"{prefix}[{index}]", child)
