from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from packages.agents.pydantic_ai_adapter import (
    PydanticAIAgentExecutor,
    pydantic_ai_available,
)
from packages.business_intel.dimensions import effective_analysis_dimensions
from packages.business_intel.evaluator import BAD_QUALITY_LABELS
from packages.identity import compute_evidence_gap_id, compute_schema_suggestion_id
from packages.schema.enterprise import (
    BusinessIntelPlan,
    BusinessQAEvaluation,
    ClaimRecord,
    CompetitorRecord,
    EvidenceGapItem,
    EvidenceGapReport,
    EvidenceRecord,
    SchemaEvolutionSuggestion,
)
from packages.schema.models import SkillOutputSpec, SkillSpec


class EvidenceGapInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    plan: BusinessIntelPlan
    qa_evaluation: BusinessQAEvaluation
    competitors: list[CompetitorRecord] = Field(default_factory=list)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    claims: list[ClaimRecord] = Field(default_factory=list)


def build_evidence_gap_agent() -> PydanticAIAgentExecutor[EvidenceGapInput, EvidenceGapReport]:
    return PydanticAIAgentExecutor(
        name="evidence_gap",
        input_type=EvidenceGapInput,
        output_type=EvidenceGapReport,
        handler=_evidence_gap_handler,
        system_prompt=(
            "Find missing, stale, rejected, or low-confidence evidence gaps for "
            "the selected competitive-intelligence scenario."
        ),
    )


def _evidence_gap_handler(agent_input: EvidenceGapInput) -> EvidenceGapReport:
    return analyze_evidence_gaps(
        project_id=agent_input.project_id,
        plan=agent_input.plan,
        qa_evaluation=agent_input.qa_evaluation,
        competitors=agent_input.competitors,
        evidence=agent_input.evidence,
        claims=agent_input.claims,
    )


def analyze_evidence_gaps(
    *,
    project_id: str,
    plan: BusinessIntelPlan,
    qa_evaluation: BusinessQAEvaluation,
    competitors: list[CompetitorRecord],
    evidence: list[EvidenceRecord],
    claims: list[ClaimRecord],
) -> EvidenceGapReport:
    gaps: list[EvidenceGapItem] = []
    gaps.extend(_coverage_gaps(plan=plan, competitors=competitors, evidence=evidence))
    gaps.extend(_quality_gaps(evidence=evidence, competitors=competitors))
    gaps.extend(_claim_gaps(claims=claims, evidence=evidence))
    gaps.extend(_landscape_gaps(plan=plan, competitors=competitors))
    gaps.extend(_qa_only_gaps(qa_evaluation=qa_evaluation, existing_gaps=gaps))
    gaps = _dedupe_gaps(gaps)
    return EvidenceGapReport(
        project_id=project_id,
        scenario_id=plan.scenario_pack.id,
        gap_count=len(gaps),
        critical_count=len([item for item in gaps if item.severity == "critical"]),
        high_count=len([item for item in gaps if item.severity == "high"]),
        medium_count=len([item for item in gaps if item.severity == "medium"]),
        low_count=len([item for item in gaps if item.severity == "low"]),
        gaps=gaps,
        schema_suggestions=_schema_evolution_suggestions(plan=plan, gaps=gaps),
        pydantic_ai_available=pydantic_ai_available(),
    )


def _coverage_gaps(
    *,
    plan: BusinessIntelPlan,
    competitors: list[CompetitorRecord],
    evidence: list[EvidenceRecord],
) -> list[EvidenceGapItem]:
    dimensions = effective_analysis_dimensions(plan)
    gaps: list[EvidenceGapItem] = []
    for competitor in competitors:
        for dimension in dimensions:
            usable = [
                item
                for item in evidence
                if item.competitor_id == competitor.id
                and _same_dimension(item.dimension, dimension)
                and item.quality_label not in BAD_QUALITY_LABELS
            ]
            verified = [item for item in usable if item.source_type == "webpage_verified"]
            if not usable:
                gaps.append(
                    _gap(
                        severity="high",
                        gap_type="missing_dimension_coverage",
                        competitor=competitor,
                        dimension=dimension,
                        source_type_required="any usable source",
                        message=f"{competitor.name} has no usable evidence for {dimension}.",
                        recommended_query=_query(competitor.name, dimension),
                    )
                )
            elif not verified:
                gaps.append(
                    _gap(
                        severity="medium",
                        gap_type="missing_verified_source",
                        competitor=competitor,
                        dimension=dimension,
                        source_type_required="webpage_verified",
                        message=(
                            f"{competitor.name} has {dimension} evidence, but no verified source."
                        ),
                        recommended_query=_query(competitor.name, dimension),
                        evidence_ids=[item.id for item in usable],
                    )
                )
    return gaps


def _quality_gaps(
    *,
    evidence: list[EvidenceRecord],
    competitors: list[CompetitorRecord],
) -> list[EvidenceGapItem]:
    competitor_by_id = {item.id: item for item in competitors}
    gaps: list[EvidenceGapItem] = []
    for item in evidence:
        if item.quality_label not in BAD_QUALITY_LABELS:
            continue
        competitor = competitor_by_id.get(item.competitor_id)
        gaps.append(
            _gap(
                severity="medium",
                gap_type="stale_or_rejected_evidence",
                competitor=competitor,
                dimension=item.dimension,
                message=(
                    f"{item.title} is marked {item.quality_label} and will not support claims."
                ),
                recommended_query=_query(
                    competitor.name if competitor else item.competitor_id,
                    item.dimension,
                ),
                evidence_ids=[item.id],
            )
        )
    return gaps


def _claim_gaps(
    *,
    claims: list[ClaimRecord],
    evidence: list[EvidenceRecord],
) -> list[EvidenceGapItem]:
    evidence_by_id = {item.id: item for item in evidence}
    gaps: list[EvidenceGapItem] = []
    for claim in claims:
        linked = [evidence_by_id.get(item) for item in claim.evidence_ids]
        usable = [
            item
            for item in linked
            if item is not None and item.quality_label not in BAD_QUALITY_LABELS
        ]
        if usable:
            continue
        gaps.append(
            _gap(
                severity="critical",
                gap_type="claim_without_usable_evidence",
                dimension=claim.claim_type,
                message="Claim has no accepted or unreviewed evidence after quality filtering.",
                recommended_query=f"{claim.claim_type} official evidence",
                evidence_ids=claim.evidence_ids,
                claim_ids=[claim.id],
            )
        )
    return gaps


def _landscape_gaps(
    *,
    plan: BusinessIntelPlan,
    competitors: list[CompetitorRecord],
) -> list[EvidenceGapItem]:
    if plan.competitor_layer.layer != "L3" or len(competitors) >= 4:
        return []
    return [
        _gap(
            severity="medium",
            gap_type="landscape_breadth",
            dimension="market",
            message="L3 landscape analysis has fewer than four competitors.",
            recommended_query=f"{plan.topic} market landscape competitors",
        )
    ]


def _qa_only_gaps(
    *,
    qa_evaluation: BusinessQAEvaluation,
    existing_gaps: list[EvidenceGapItem],
) -> list[EvidenceGapItem]:
    existing_keys = {
        (item.competitor_id, item.dimension, tuple(item.claim_ids), tuple(item.evidence_ids))
        for item in existing_gaps
    }
    gaps: list[EvidenceGapItem] = []
    for finding in qa_evaluation.findings:
        key = (
            finding.competitor_id,
            finding.dimension,
            tuple(finding.claim_ids),
            tuple(finding.evidence_ids),
        )
        if key in existing_keys:
            continue
        gaps.append(
            _gap(
                severity=_severity_from_qa(finding.severity),
                gap_type=(
                    "claim_without_usable_evidence"
                    if finding.claim_ids
                    else "missing_dimension_coverage"
                ),
                competitor_id=finding.competitor_id,
                competitor_name=finding.competitor_name,
                dimension=finding.dimension,
                message=finding.message,
                recommended_query=finding.recommendation,
                evidence_ids=finding.evidence_ids,
                claim_ids=finding.claim_ids,
            )
        )
    return gaps


def _gap(
    *,
    severity: str,
    gap_type: str,
    message: str,
    competitor: CompetitorRecord | None = None,
    competitor_id: str | None = None,
    competitor_name: str | None = None,
    dimension: str | None = None,
    source_type_required: str | None = None,
    recommended_query: str = "",
    evidence_ids: list[str] | None = None,
    claim_ids: list[str] | None = None,
) -> EvidenceGapItem:
    resolved_competitor_id = competitor.id if competitor else competitor_id
    resolved_competitor_name = competitor.name if competitor else competitor_name
    return EvidenceGapItem(
        id=compute_evidence_gap_id(
            severity=severity,
            gap_type=gap_type,
            competitor_id=resolved_competitor_id,
            dimension=dimension,
            message=message,
            evidence_ids=evidence_ids or [],
            claim_ids=claim_ids or [],
        ),
        severity=severity,  # type: ignore[arg-type]
        gap_type=gap_type,  # type: ignore[arg-type]
        competitor_id=resolved_competitor_id,
        competitor_name=resolved_competitor_name,
        dimension=dimension,
        source_type_required=source_type_required,
        message=message,
        recommended_query=recommended_query,
        evidence_ids=evidence_ids or [],
        claim_ids=claim_ids or [],
    )


def _dedupe_gaps(gaps: list[EvidenceGapItem]) -> list[EvidenceGapItem]:
    seen: set[tuple[str | None, str | None, str, tuple[str, ...], tuple[str, ...]]] = set()
    deduped: list[EvidenceGapItem] = []
    for gap in gaps:
        key = (
            gap.competitor_id,
            gap.dimension,
            gap.gap_type,
            tuple(gap.evidence_ids),
            tuple(gap.claim_ids),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(gap)
    return sorted(deduped, key=lambda item: (_severity_rank(item.severity), item.gap_type))


def _schema_evolution_suggestions(
    *,
    plan: BusinessIntelPlan,
    gaps: list[EvidenceGapItem],
) -> list[SchemaEvolutionSuggestion]:
    known_dimensions = {
        _dimension_key(dimension)
        for dimension in [
            *plan.requested_dimensions,
            *plan.scenario_pack.required_dimensions,
            *plan.scenario_pack.optional_dimensions,
        ]
        if dimension
    }
    gaps_by_new_dimension: dict[str, list[EvidenceGapItem]] = {}
    for gap in gaps:
        if not gap.dimension:
            continue
        dimension_key = _dimension_key(gap.dimension)
        if not dimension_key or dimension_key in known_dimensions:
            continue
        if gap.gap_type not in {"missing_dimension_coverage", "claim_without_usable_evidence"}:
            continue
        gaps_by_new_dimension.setdefault(dimension_key, []).append(gap)

    suggestions: list[SchemaEvolutionSuggestion] = []
    for dimension_key, dimension_gaps in sorted(gaps_by_new_dimension.items()):
        gap_ids = [gap.id for gap in dimension_gaps]
        suggestions.append(
            SchemaEvolutionSuggestion(
                id=compute_schema_suggestion_id(dimension_key, gap_ids),
                dimension=dimension_gaps[0].dimension or dimension_key,
                normalized_dimension=dimension_key,
                reason=(
                    f"{len(dimension_gaps)} evidence gap(s) reference a dimension that is not "
                    "covered by the active scenario schema."
                ),
                source_gap_ids=gap_ids,
                proposed_skill=_draft_skill_spec(dimension_key),
            )
        )
    return suggestions


def _draft_skill_spec(dimension_key: str) -> SkillSpec:
    return SkillSpec(
        name=dimension_key,
        subagent_class="GenericCollector",
        description=(
            f"Pending collector schema for {dimension_key} evidence discovered by gap analysis."
        ),
        tools_allowlist=["web_search", "robots_check", "fetch_page", "extract_facts"],
        query_templates=[
            f"{{competitor}} {dimension_key} official documentation",
            f"{{competitor}} {dimension_key} policy",
            f"{{competitor}} {dimension_key} evidence",
        ],
        source_type="webpage",
        output=SkillOutputSpec(
            prefix=dimension_key,
            confidence_default=0.8,
            confidence_no_url=0.45,
            required_dimension=dimension_key,
        ),
    )


def _query(competitor_name: str, dimension: str) -> str:
    if dimension == "pricing":
        return f"{competitor_name} pricing official"
    if dimension == "security":
        return f"{competitor_name} security trust center official"
    if dimension == "integrations":
        return f"{competitor_name} integrations documentation official"
    if dimension == "market":
        return f"{competitor_name} market positioning evidence"
    return f"{competitor_name} {dimension} official documentation"


def _same_dimension(left: str, right: str) -> bool:
    left_key = left.casefold().strip()
    right_key = right.casefold().strip()
    return left_key == right_key or left_key in right_key or right_key in left_key


def _dimension_key(value: str) -> str:
    return "_".join(value.casefold().strip().replace("-", " ").split())


def _severity_from_qa(severity: str) -> str:
    return {"blocker": "critical", "warn": "high", "info": "medium"}.get(severity, "low")


def _severity_rank(severity: str) -> int:
    return {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(severity, 4)
