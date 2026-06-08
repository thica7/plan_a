from __future__ import annotations

from statistics import mean
from typing import Literal

from packages.business_intel.dimensions import effective_analysis_dimensions
from packages.business_intel.evaluator import BAD_QUALITY_LABELS
from packages.identity import compute_recommendation_id
from packages.schema.enterprise import (
    BusinessIntelPlan,
    BusinessQAEvaluation,
    BusinessQAFinding,
    BusinessRecommendation,
    ClaimRecord,
    CompetitorDimensionScore,
    CompetitorRecord,
    CompetitorScore,
    CompetitorScoreReport,
    EvidenceRecord,
    ProjectReadinessScore,
)


def score_project_readiness(
    *,
    project_id: str,
    plan: BusinessIntelPlan,
    qa_evaluation: BusinessQAEvaluation,
    competitors: list[CompetitorRecord],
    evidence: list[EvidenceRecord],
    claims: list[ClaimRecord],
) -> ProjectReadinessScore:
    evidence_score = _evidence_score(evidence)
    claim_score = _claim_score(claims, evidence)
    coverage_score = _coverage_score(plan, competitors, evidence)
    qa_score = _qa_score(qa_evaluation)
    score = round(
        qa_score * 0.35 + coverage_score * 0.25 + evidence_score * 0.25 + claim_score * 0.15
    )
    risk_level = _risk_level(score, qa_evaluation)
    recommendations = _recommendations(
        plan=plan,
        qa_evaluation=qa_evaluation,
        competitors=competitors,
        evidence=evidence,
        claims=claims,
        coverage_score=coverage_score,
    )
    return ProjectReadinessScore(
        project_id=project_id,
        score=score,
        risk_level=risk_level,
        evidence_score=evidence_score,
        claim_score=claim_score,
        coverage_score=coverage_score,
        qa_score=qa_score,
        summary=_summary(score, risk_level, qa_evaluation, coverage_score),
        recommendations=recommendations,
    )


def score_competitors(
    *,
    project_id: str,
    plan: BusinessIntelPlan,
    competitors: list[CompetitorRecord],
    evidence: list[EvidenceRecord],
    claims: list[ClaimRecord],
) -> CompetitorScoreReport:
    dimensions = effective_analysis_dimensions(plan)
    scores = [
        _score_competitor(
            competitor=competitor,
            dimensions=dimensions,
            evidence=[item for item in evidence if item.competitor_id == competitor.id],
            claims=[item for item in claims if item.competitor_id == competitor.id],
        )
        for competitor in competitors
    ]
    scores = sorted(scores, key=lambda item: item.total_score, reverse=True)
    ranked = [item.model_copy(update={"rank": index + 1}) for index, item in enumerate(scores)]
    return CompetitorScoreReport(
        project_id=project_id,
        top_competitor_id=ranked[0].competitor_id if ranked else None,
        scores=ranked,
    )


def _score_competitor(
    *,
    competitor: CompetitorRecord,
    dimensions: list[str],
    evidence: list[EvidenceRecord],
    claims: list[ClaimRecord],
) -> CompetitorScore:
    usable_evidence = [item for item in evidence if item.quality_label not in BAD_QUALITY_LABELS]
    evidence_score = _evidence_score(usable_evidence)
    claim_score = _claim_score(claims, usable_evidence)
    coverage_score = _competitor_coverage_score(dimensions, usable_evidence)
    risk_penalty = _competitor_risk_penalty(evidence=evidence, claims=claims)
    dimension_scores = [
        _dimension_score(
            dimension=dimension,
            evidence=[
                item for item in usable_evidence if _same_dimension(item.dimension, dimension)
            ],
            claims=[item for item in claims if _same_dimension(item.claim_type, dimension)],
        )
        for dimension in dimensions
    ]
    total_score = max(
        0,
        round(
            evidence_score * 0.30
            + claim_score * 0.25
            + coverage_score * 0.30
            + _dimension_average(dimension_scores) * 0.15
            - risk_penalty
        ),
    )
    return CompetitorScore(
        competitor_id=competitor.id,
        competitor_name=competitor.name,
        total_score=total_score,
        evidence_score=evidence_score,
        claim_score=claim_score,
        coverage_score=coverage_score,
        risk_penalty=risk_penalty,
        rank=1,
        dimension_scores=dimension_scores,
        recommendation=_competitor_recommendation(total_score, risk_penalty, coverage_score),
    )


def _evidence_score(evidence: list[EvidenceRecord]) -> int:
    if not evidence:
        return 0
    weighted = [
        item.reliability_score * _quality_multiplier(item.quality_label) for item in evidence
    ]
    return _percent(mean(weighted))


def _claim_score(claims: list[ClaimRecord], evidence: list[EvidenceRecord]) -> int:
    if not claims:
        return 0
    usable_evidence_ids = {
        item.id for item in evidence if item.quality_label not in BAD_QUALITY_LABELS
    }
    weighted: list[float] = []
    for claim in claims:
        has_usable_evidence = any(item in usable_evidence_ids for item in claim.evidence_ids)
        status_multiplier = {
            "accepted": 1.0,
            "proposed": 0.82,
            "disputed": 0.45,
            "deprecated": 0.15,
            "rejected": 0.0,
        }.get(claim.status, 0.6)
        evidence_multiplier = 1.0 if has_usable_evidence else 0.25
        weighted.append(claim.confidence * status_multiplier * evidence_multiplier)
    return _percent(mean(weighted))


def _coverage_score(
    plan: BusinessIntelPlan,
    competitors: list[CompetitorRecord],
    evidence: list[EvidenceRecord],
) -> int:
    dimensions = effective_analysis_dimensions(plan)
    if not competitors or not dimensions:
        return 0
    expected = len(competitors) * len(dimensions)
    covered = 0
    for competitor in competitors:
        for dimension in dimensions:
            if any(
                item.competitor_id == competitor.id
                and _same_dimension(item.dimension, dimension)
                and item.quality_label not in BAD_QUALITY_LABELS
                for item in evidence
            ):
                covered += 1
    return round(covered / expected * 100)


def _competitor_coverage_score(dimensions: list[str], evidence: list[EvidenceRecord]) -> int:
    if not dimensions:
        return 0
    covered = 0
    for dimension in dimensions:
        if any(_same_dimension(item.dimension, dimension) for item in evidence):
            covered += 1
    return round(covered / len(dimensions) * 100)


def _dimension_score(
    *,
    dimension: str,
    evidence: list[EvidenceRecord],
    claims: list[ClaimRecord],
) -> CompetitorDimensionScore:
    evidence_part = min(1.0, len(evidence) / 2)
    avg_evidence_reliability = (
        mean([item.reliability_score for item in evidence]) if evidence else 0.0
    )
    avg_claim_confidence = mean([item.confidence for item in claims]) if claims else 0.0
    score = _percent(
        evidence_part * 0.35 + avg_evidence_reliability * 0.35 + avg_claim_confidence * 0.30
    )
    return CompetitorDimensionScore(
        dimension=dimension,
        score=score,
        evidence_count=len(evidence),
        claim_count=len(claims),
        average_confidence=round(avg_claim_confidence, 2),
        rationale=_dimension_rationale(dimension, evidence, claims),
    )


def _competitor_risk_penalty(
    *,
    evidence: list[EvidenceRecord],
    claims: list[ClaimRecord],
) -> int:
    bad_evidence = len([item for item in evidence if item.quality_label in BAD_QUALITY_LABELS])
    low_reliability = len([item for item in evidence if item.reliability_score < 0.5])
    unsupported_claims = len([item for item in claims if not item.evidence_ids])
    return min(40, bad_evidence * 8 + low_reliability * 5 + unsupported_claims * 10)


def _dimension_average(scores: list[CompetitorDimensionScore]) -> int:
    if not scores:
        return 0
    return round(mean([item.score for item in scores]))


def _qa_score(evaluation: BusinessQAEvaluation) -> int:
    penalty = evaluation.blocker_count * 22 + evaluation.warn_count * 8 + evaluation.info_count * 3
    return max(0, 100 - penalty)


def _recommendations(
    *,
    plan: BusinessIntelPlan,
    qa_evaluation: BusinessQAEvaluation,
    competitors: list[CompetitorRecord],
    evidence: list[EvidenceRecord],
    claims: list[ClaimRecord],
    coverage_score: int,
) -> list[BusinessRecommendation]:
    recommendations: list[BusinessRecommendation] = []
    if qa_evaluation.blocker_count > 0:
        recommendations.append(
            _recommendation(
                priority="critical",
                title="Resolve blocker QA findings",
                detail=(
                    f"{qa_evaluation.blocker_count} blocker finding(s) prevent this "
                    "project from being decision-ready."
                ),
                action_type="fix_claim",
            )
        )
    for finding in qa_evaluation.findings[:3]:
        recommendations.append(_recommendation_for_finding(finding))

    stale_count = len([item for item in evidence if item.quality_label in BAD_QUALITY_LABELS])
    if stale_count:
        recommendations.append(
            _recommendation(
                priority="medium",
                title="Review rejected or stale evidence",
                detail=f"{stale_count} evidence item(s) are excluded from readiness scoring.",
                action_type="review_evidence",
            )
        )
    if not claims and evidence:
        recommendations.append(
            _recommendation(
                priority="high",
                title="Extract claims from collected evidence",
                detail="Evidence exists, but no structured claims have been projected yet.",
                action_type="fix_claim",
            )
        )
    if coverage_score < 70 and competitors:
        recommendations.append(
            _recommendation(
                priority="high",
                title="Close evidence coverage gaps",
                detail=(
                    f"Required coverage for {plan.scenario_pack.name} is only {coverage_score}%."
                ),
                action_type="collect_evidence",
            )
        )
    if plan.competitor_layer.layer == "L3" and len(competitors) < 4:
        recommendations.append(
            _recommendation(
                priority="medium",
                title="Expand competitor set for landscape analysis",
                detail="L3 landscape projects are more reliable with at least four competitors.",
                action_type="expand_competitors",
            )
        )
    if not recommendations:
        recommendations.append(
            _recommendation(
                priority="low",
                title="Prepare report for review",
                detail="Current evidence, coverage, claims, and QA checks look decision-ready.",
                action_type="approve_report",
            )
        )
    return _dedupe_recommendations(recommendations)


def _recommendation_for_finding(finding: BusinessQAFinding) -> BusinessRecommendation:
    action_type: Literal[
        "collect_evidence",
        "review_evidence",
        "fix_claim",
        "expand_competitors",
        "approve_report",
    ] = "collect_evidence"
    target_type: Literal["project", "competitor", "dimension", "evidence", "claim"] = "project"
    target_id = None
    if finding.claim_ids:
        action_type = "fix_claim"
        target_type = "claim"
        target_id = finding.claim_ids[0]
    elif finding.evidence_ids:
        action_type = "review_evidence"
        target_type = "evidence"
        target_id = finding.evidence_ids[0]
    elif finding.competitor_id:
        target_type = "competitor"
        target_id = finding.competitor_id
    elif finding.dimension:
        target_type = "dimension"
        target_id = finding.dimension

    priority = {"blocker": "critical", "warn": "high", "info": "medium"}[finding.severity]
    return _recommendation(
        priority=priority,
        title=finding.rule_name,
        detail=finding.message,
        action_type=action_type,
        target_type=target_type,
        target_id=target_id,
    )


def _risk_level(
    score: int,
    evaluation: BusinessQAEvaluation,
) -> Literal["ready", "watch", "at_risk", "blocked"]:
    if evaluation.blocker_count > 0:
        return "blocked"
    if score < 70:
        return "at_risk"
    if score < 85:
        return "watch"
    return "ready"


def _summary(
    score: int,
    risk_level: str,
    evaluation: BusinessQAEvaluation,
    coverage_score: int,
) -> str:
    if risk_level == "blocked":
        return (
            f"Score {score}: blocked by {evaluation.blocker_count} critical business QA "
            f"finding(s); coverage is {coverage_score}%."
        )
    if risk_level == "at_risk":
        return (
            f"Score {score}: evidence and QA gaps remain material; coverage is {coverage_score}%."
        )
    if risk_level == "watch":
        return f"Score {score}: usable but still worth reviewing warnings before approval."
    return f"Score {score}: ready for stakeholder review or report approval."


def _recommendation(
    *,
    priority: Literal["critical", "high", "medium", "low"],
    title: str,
    detail: str,
    action_type: Literal[
        "collect_evidence",
        "review_evidence",
        "fix_claim",
        "expand_competitors",
        "approve_report",
    ],
    target_type: Literal["project", "competitor", "dimension", "evidence", "claim"] = "project",
    target_id: str | None = None,
) -> BusinessRecommendation:
    return BusinessRecommendation(
        id=compute_recommendation_id(
            target_id or "project",
            action_type,
            title,
            [priority, detail, target_type],
        ),
        priority=priority,
        title=title,
        detail=detail,
        action_type=action_type,
        target_type=target_type,
        target_id=target_id,
    )


def _competitor_recommendation(total_score: int, risk_penalty: int, coverage_score: int) -> str:
    if risk_penalty >= 20:
        return "Review evidence quality before recommending this competitor."
    if coverage_score < 70:
        return "Collect missing required-dimension evidence before final ranking."
    if total_score >= 85:
        return "Strong evidence-backed competitor profile; suitable for report recommendation."
    if total_score >= 70:
        return "Usable competitor profile with remaining review items."
    return "Insufficient confidence for stakeholder recommendation."


def _dimension_rationale(
    dimension: str,
    evidence: list[EvidenceRecord],
    claims: list[ClaimRecord],
) -> str:
    if not evidence:
        return f"No usable evidence for {dimension}."
    if not claims:
        return f"{dimension} has evidence but no projected claims."
    return f"{dimension} has {len(evidence)} usable evidence item(s) and {len(claims)} claim(s)."


def _dedupe_recommendations(
    recommendations: list[BusinessRecommendation],
) -> list[BusinessRecommendation]:
    seen: set[str] = set()
    deduped: list[BusinessRecommendation] = []
    for recommendation in recommendations:
        key = f"{recommendation.title}|{recommendation.detail}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(recommendation)
    return deduped[:6]


def _quality_multiplier(quality_label: str) -> float:
    return {
        "accepted": 1.0,
        "unreviewed": 0.75,
        "stale": 0.2,
        "rejected": 0.0,
    }.get(quality_label, 0.5)


def _same_dimension(left: str, right: str) -> bool:
    left_key = left.casefold().strip()
    right_key = right.casefold().strip()
    return left_key == right_key or left_key in right_key or right_key in left_key


def _percent(value: float) -> int:
    return max(0, min(100, round(value * 100)))
