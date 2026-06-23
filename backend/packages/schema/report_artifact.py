from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ReportArtifactLayer = Literal["core", "support", "audit"]
EvidenceStrength = Literal["insufficient", "weak", "moderate", "strong"]
ClaimSupportLevel = Literal[
    "official",
    "triangulated_community",
    "single_source",
    "simulated",
    "inferred",
    "gap",
]
ReportProducer = Literal["analyst", "comparator", "writer", "qa", "legacy", "system"]
DecisionCardType = Literal[
    "dimension_winner",
    "overall_recommendation",
    "risk_adjusted_recommendation",
    "why_not",
    "battlecard_position",
    "swot_interpretation",
]
DecisionPosture = Literal[
    "strong",
    "tentative",
    "watch",
    "avoid",
    "insufficient_evidence",
]
LegacyArtifactSource = Literal["report_md", "report_artifact_v2"]


class ClaimCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    run_id: str
    competitor: str
    dimension: str
    claim_type: str
    claim: str
    source_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_strength: EvidenceStrength
    support_level: ClaimSupportLevel
    scope: str
    caveats: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    applicability: str
    produced_by: Literal["analyst"] = "analyst"
    producer_stage: str
    derived_from: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_sources_for_factual_claims(self) -> ClaimCard:
        if self.evidence_strength != "insufficient" and not self.source_ids:
            raise ValueError(
                "claim cards with evidence_strength other than 'insufficient' require source_ids"
            )
        if not self.source_ids and self.support_level != "gap":
            raise ValueError("claims without source_ids require support_level='gap'")
        if self.support_level == "gap" and self.evidence_strength != "insufficient":
            raise ValueError(
                "claim cards with support_level='gap' require evidence_strength='insufficient'"
            )
        return self


class ClaimCardBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    competitor: str
    dimension: str
    cards: list[ClaimCard] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    coverage: dict[str, Any] = Field(default_factory=dict)
    gap_count: int = Field(default=0, ge=0)
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    producer_context: dict[str, Any] = Field(default_factory=dict)


class DecisionCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    run_id: str
    decision_type: DecisionCardType
    subject: str
    recommendation: str
    posture: DecisionPosture
    rationale: str
    claim_card_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    winner: str | None = None
    alternatives: list[str] = Field(default_factory=list)
    why_not: dict[str, str] = Field(default_factory=dict)
    risk_factors: list[str] = Field(default_factory=list)
    evidence_strength: EvidenceStrength
    confidence: float = Field(ge=0.0, le=1.0)
    produced_by: Literal["comparator"] = "comparator"
    producer_stage: Literal["comparator"] = "comparator"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_claim_cards(self) -> DecisionCard:
        if not self.claim_card_ids:
            raise ValueError("decision cards require claim_card_ids")
        if self.posture == "strong" and self.evidence_strength not in {
            "strong",
            "moderate",
        }:
            raise ValueError(
                "decision cards with posture='strong' require moderate or strong evidence_strength"
            )
        return self


class DecisionCardBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    cards: list[DecisionCard] = Field(default_factory=list)
    matrix_snapshot: dict[str, Any] = Field(default_factory=dict)
    coverage_by_dimension: dict[str, Any] = Field(default_factory=dict)
    recommendation_card_id: str | None = None
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    producer_context: dict[str, Any] = Field(default_factory=dict)


class ReportLayerSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_key: str
    heading: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    source_ids: list[str] = Field(default_factory=list)
    claim_card_ids: list[str] = Field(default_factory=list)
    decision_card_ids: list[str] = Field(default_factory=list)


class ReportLayer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layer: ReportArtifactLayer
    markdown: str = ""
    sections: list[ReportLayerSection] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SectionBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    section_key: str
    layer: ReportArtifactLayer
    required_questions: list[str] = Field(default_factory=list)
    allowed_claim_card_ids: list[str] = Field(default_factory=list)
    allowed_decision_card_ids: list[str] = Field(default_factory=list)
    allowed_source_ids: list[str] = Field(default_factory=list)
    must_include: list[str] = Field(default_factory=list)
    must_not_claim: list[str] = Field(default_factory=list)
    tone: str = ""
    minimum_depth: dict[str, Any] = Field(default_factory=dict)
    citation_policy: dict[str, Any] = Field(default_factory=dict)
    repair_targets: dict[str, Any] = Field(default_factory=dict)


class ReportQualityAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    core_gate: dict[str, Any] = Field(default_factory=dict)
    support_gate: dict[str, Any] = Field(default_factory=dict)
    audit_gate: dict[str, Any] = Field(default_factory=dict)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    blockers: list[dict[str, Any]] = Field(default_factory=list)
    revision_count: int = Field(default=0, ge=0)


class ReportArtifactRenderCache(BaseModel):
    model_config = ConfigDict(extra="forbid")

    core_markdown: str = ""
    support_markdown: str = ""
    audit_markdown: str = ""
    full_markdown: str = ""


class ReportArtifactLegacyInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: LegacyArtifactSource
    report_md_alias: bool = False


class ReportArtifactV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_version: Literal[2] = 2
    run_id: str
    core_report: ReportLayer
    support_appendix: ReportLayer = Field(
        default_factory=lambda: ReportLayer(layer="support")
    )
    audit_log: ReportLayer = Field(default_factory=lambda: ReportLayer(layer="audit"))
    claim_card_bundles: list[ClaimCardBundle] = Field(default_factory=list)
    decision_card_bundle: DecisionCardBundle | None = None
    section_briefs: list[SectionBrief] = Field(default_factory=list)
    quality: ReportQualityAccount = Field(default_factory=ReportQualityAccount)
    render_cache: ReportArtifactRenderCache
    legacy: ReportArtifactLegacyInfo
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_layer_slots_and_render_cache(self) -> ReportArtifactV2:
        if self.core_report.layer != "core":
            raise ValueError("core_report.layer must be 'core'")
        if self.support_appendix.layer != "support":
            raise ValueError("support_appendix.layer must be 'support'")
        if self.audit_log.layer != "audit":
            raise ValueError("audit_log.layer must be 'audit'")

        if self.render_cache.core_markdown != self.core_report.markdown:
            raise ValueError(
                "render_cache.core_markdown must equal core_report.markdown"
            )
        if self.render_cache.support_markdown != self.support_appendix.markdown:
            raise ValueError(
                "render_cache.support_markdown must equal support_appendix.markdown"
            )
        if self.render_cache.audit_markdown != self.audit_log.markdown:
            raise ValueError(
                "render_cache.audit_markdown must equal audit_log.markdown"
            )

        expected_full_markdown = "\n\n".join(
            markdown
            for markdown in (
                self.core_report.markdown,
                self.support_appendix.markdown,
                self.audit_log.markdown,
            )
            if markdown
        )
        if self.render_cache.full_markdown != expected_full_markdown:
            raise ValueError(
                "render_cache.full_markdown must match joined layer markdown"
            )
        return self


__all__ = [
    "ClaimCard",
    "ClaimCardBundle",
    "DecisionCard",
    "DecisionCardBundle",
    "ReportArtifactLegacyInfo",
    "ReportArtifactRenderCache",
    "ReportArtifactV2",
    "ReportLayer",
    "ReportLayerSection",
    "ReportQualityAccount",
    "SectionBrief",
]
