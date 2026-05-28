from __future__ import annotations

import hashlib
from statistics import mean
from typing import Literal

from packages.business_intel.evaluator import BAD_QUALITY_LABELS
from packages.schema.enterprise import (
    BusinessIntelPlan,
    BusinessQAEvaluation,
    BusinessQAFinding,
    BusinessRecommendation,
    ClaimRecord,
    CompetitorRecord,
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
        qa_score * 0.35
        + coverage_score * 0.25
        + evidence_score * 0.25
        + claim_score * 0.15
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


def _evidence_score(evidence: list[EvidenceRecord]) -> int:
    if not evidence:
        return 0
    weighted = [
        item.reliability_score * _quality_multiplier(item.quality_label)
        for item in evidence
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
    dimensions = plan.scenario_pack.required_dimensions or plan.requested_dimensions
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


def _qa_score(evaluation: BusinessQAEvaluation) -> int:
    penalty = (
        evaluation.blocker_count * 22
        + evaluation.warn_count * 8
        + evaluation.info_count * 3
    )
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
                    f"Required coverage for {plan.scenario_pack.name} is only "
                    f"{coverage_score}%."
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
            f"Score {score}: evidence and QA gaps remain material; "
            f"coverage is {coverage_score}%."
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
    raw = "|".join([priority, title, detail, action_type, target_type, target_id or ""])
    return BusinessRecommendation(
        id=f"recommendation-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}",
        priority=priority,
        title=title,
        detail=detail,
        action_type=action_type,
        target_type=target_type,
        target_id=target_id,
    )


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
