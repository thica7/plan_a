from __future__ import annotations

import hashlib

from packages.business_intel.evaluator import BAD_QUALITY_LABELS
from packages.schema.enterprise import (
    BusinessIntelPlan,
    BusinessQAEvaluation,
    ClaimRecord,
    CompetitorRecord,
    EvidenceGapItem,
    EvidenceGapReport,
    EvidenceRecord,
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
    )


def _coverage_gaps(
    *,
    plan: BusinessIntelPlan,
    competitors: list[CompetitorRecord],
    evidence: list[EvidenceRecord],
) -> list[EvidenceGapItem]:
    dimensions = plan.scenario_pack.required_dimensions or plan.requested_dimensions
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
                            f"{competitor.name} has {dimension} evidence, "
                            "but no verified source."
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
    raw = "|".join(
        [
            severity,
            gap_type,
            resolved_competitor_id or "",
            dimension or "",
            message,
            ",".join(evidence_ids or []),
            ",".join(claim_ids or []),
        ]
    )
    return EvidenceGapItem(
        id=f"evidence-gap-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}",
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


def _severity_from_qa(severity: str) -> str:
    return {"blocker": "critical", "warn": "high", "info": "medium"}.get(severity, "low")


def _severity_rank(severity: str) -> int:
    return {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(severity, 4)
