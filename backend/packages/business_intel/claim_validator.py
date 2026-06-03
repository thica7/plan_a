from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlparse

from packages.schema.enterprise import (
    ClaimRecord,
    ClaimValidationIssue,
    ClaimValidationReport,
    ClaimValidationResult,
    EvidenceRecord,
)

_TOKEN_RE = re.compile(r"[a-z0-9\u4e00-\u9fff]+", re.IGNORECASE)
_STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "by",
    "for",
    "from",
    "has",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}
HIGH_RISK_CLAIM_RE = re.compile(
    r"\b("
    r"best|better|leading|leader|dominates|dominant|recommended|safest|safer|"
    r"enterprise-ready|soc\s*2|sso|saml|scim|audit log|compliance|security|"
    r"cheapest|lowest|highest|fastest|most reliable"
    r")\b",
    flags=re.IGNORECASE,
)


def validate_project_claims(
    *,
    project_id: str,
    claims: list[ClaimRecord],
    evidence: list[EvidenceRecord],
) -> ClaimValidationReport:
    evidence_by_id = {item.id: item for item in evidence}
    results: list[ClaimValidationResult] = []
    issues: list[ClaimValidationIssue] = []

    for claim in claims:
        usable = [
            evidence_by_id[evidence_id]
            for evidence_id in claim.evidence_ids
            if evidence_id in evidence_by_id
            and evidence_by_id[evidence_id].quality_label not in {"rejected", "stale"}
        ]
        claim_issue_ids: list[str] = []
        text_support_score = _support_score(claim, usable)
        evidence_quality_score = _evidence_quality_score(usable)
        triangulation_score = _triangulation_score(usable)
        support_score = _self_consistency_score(
            text_support_score,
            evidence_quality_score,
            triangulation_score,
        )
        consistency_votes = _consistency_votes(
            text_support_score=text_support_score,
            evidence_quality_score=evidence_quality_score,
            triangulation_score=triangulation_score,
        )

        if not claim.evidence_ids or not usable:
            issue = _issue(
                claim.id,
                "blocker",
                "missing_evidence"
                if not claim.evidence_ids
                else "stale_or_rejected_evidence",
                "Claim has no usable evidence after quality filtering.",
                claim.evidence_ids,
            )
            issues.append(issue)
            claim_issue_ids.append(issue.id)
        elif text_support_score < 40:
            issue = _issue(
                claim.id,
                "warn",
                "weak_text_support",
                "Evidence text has weak lexical support for the claim.",
                [item.id for item in usable],
            )
            issues.append(issue)
            claim_issue_ids.append(issue.id)
        elif evidence_quality_score < 55:
            issue = _issue(
                claim.id,
                "warn",
                "low_evidence_quality",
                (
                    "Usable evidence is present, but source quality is too weak for "
                    "confident reporting."
                ),
                [item.id for item in usable],
            )
            issues.append(issue)
            claim_issue_ids.append(issue.id)
        elif _requires_triangulation(claim) and triangulation_score < 90:
            issue = _issue(
                claim.id,
                "warn",
                "single_source_support",
                (
                    "High-risk or comparative claim should be supported by multiple "
                    "independent sources."
                ),
                [item.id for item in usable],
            )
            issues.append(issue)
            claim_issue_ids.append(issue.id)

        if claim.confidence < 0.55:
            issue = _issue(
                claim.id,
                "warn",
                "low_confidence",
                "Claim confidence is below the enterprise review threshold.",
                [item.id for item in usable],
            )
            issues.append(issue)
            claim_issue_ids.append(issue.id)

        if support_score < 55 and usable:
            issue = _issue(
                claim.id,
                "warn",
                "low_self_consistency",
                (
                    "Claim failed the multi-check consistency threshold across text, "
                    "source quality, and triangulation."
                ),
                [item.id for item in usable],
            )
            issues.append(issue)
            claim_issue_ids.append(issue.id)

        has_blocker = any(
            item.endswith(":missing_evidence")
            or item.endswith(":stale_or_rejected_evidence")
            for item in claim_issue_ids
        )
        if has_blocker:
            status = "blocked"
        elif support_score >= 75 and not claim_issue_ids:
            status = "supported"
        elif support_score >= 55:
            status = "weak"
        else:
            status = "unsupported"

        results.append(
            ClaimValidationResult(
                claim_id=claim.id,
                status=status,
                support_score=support_score,
                text_support_score=text_support_score,
                evidence_quality_score=evidence_quality_score,
                triangulation_score=triangulation_score,
                self_consistency_score=support_score,
                consistency_votes=consistency_votes,
                validation_samples=_consistency_samples(
                    text_support_score=text_support_score,
                    evidence_quality_score=evidence_quality_score,
                    triangulation_score=triangulation_score,
                    usable_evidence_ids=[item.id for item in usable],
                ),
                usable_evidence_ids=[item.id for item in usable],
                issue_ids=claim_issue_ids,
            )
        )

    low_consistency_count = len(
        [
            item
            for item in results
            if item.status != "blocked" and item.self_consistency_score < 55
        ]
    )
    return ClaimValidationReport(
        project_id=project_id,
        total_claims=len(claims),
        supported_count=sum(1 for item in results if item.status == "supported"),
        weak_count=sum(1 for item in results if item.status == "weak"),
        unsupported_count=sum(1 for item in results if item.status == "unsupported"),
        blocked_count=sum(1 for item in results if item.status == "blocked"),
        issue_count=len(issues),
        blocker_count=sum(1 for item in issues if item.severity == "blocker"),
        warn_count=sum(1 for item in issues if item.severity == "warn"),
        self_consistency_score=_average_score(
            [item.self_consistency_score for item in results if item.status != "blocked"]
        ),
        low_consistency_count=low_consistency_count,
        results=results,
        issues=issues,
        generated_at=datetime.utcnow(),
    )


def _issue(
    claim_id: str,
    severity: str,
    issue_type: str,
    message: str,
    evidence_ids: list[str],
) -> ClaimValidationIssue:
    return ClaimValidationIssue(
        id=f"{claim_id}:{issue_type}",
        claim_id=claim_id,
        severity=severity,  # type: ignore[arg-type]
        issue_type=issue_type,  # type: ignore[arg-type]
        message=message,
        evidence_ids=evidence_ids,
    )


def _support_score(claim: ClaimRecord, evidence: list[EvidenceRecord]) -> int:
    if not evidence:
        return 0
    claim_tokens = _tokens(claim.claim_text)
    if not claim_tokens:
        return 0
    best = 0.0
    for item in evidence:
        text_tokens = _tokens(f"{item.title} {item.snippet} {item.dimension}")
        overlap = len(claim_tokens & text_tokens) / max(len(claim_tokens), 1)
        quality_boost = 0.15 if item.quality_label == "accepted" else 0.0
        confidence_boost = min(item.reliability_score, 1.0) * 0.15
        best = max(best, min(overlap + quality_boost + confidence_boost, 1.0))
    return round(best * 100)


def _evidence_quality_score(evidence: list[EvidenceRecord]) -> int:
    if not evidence:
        return 0
    best = 0.0
    for item in evidence:
        source_boost = 0.18 if item.source_type == "webpage_verified" else 0.0
        quality_boost = {
            "accepted": 0.16,
            "unreviewed": 0.04,
            "rejected": -0.35,
            "stale": -0.35,
        }.get(item.quality_label, 0.0)
        score = min(max(item.reliability_score + source_boost + quality_boost, 0.0), 1.0)
        best = max(best, score)
    return round(best * 100)


def _triangulation_score(evidence: list[EvidenceRecord]) -> int:
    if not evidence:
        return 0
    usable_domains = {_evidence_domain(item) for item in evidence}
    usable_domains.discard("")
    verified_count = len([item for item in evidence if item.source_type == "webpage_verified"])
    if len(usable_domains) >= 2 and verified_count >= 2:
        return 100
    if len(evidence) >= 2 and verified_count >= 1:
        return 85
    if verified_count >= 1:
        return 70
    return 45


def _self_consistency_score(
    text_support_score: int,
    evidence_quality_score: int,
    triangulation_score: int,
) -> int:
    return round(
        text_support_score * 0.5
        + evidence_quality_score * 0.3
        + triangulation_score * 0.2
    )


def _consistency_votes(
    *,
    text_support_score: int,
    evidence_quality_score: int,
    triangulation_score: int,
) -> dict[str, int]:
    return {
        "text_support": 1 if text_support_score >= 70 else 0,
        "evidence_quality": 1 if evidence_quality_score >= 75 else 0,
        "triangulation": 1 if triangulation_score >= 70 else 0,
    }


def _consistency_samples(
    *,
    text_support_score: int,
    evidence_quality_score: int,
    triangulation_score: int,
    usable_evidence_ids: list[str],
) -> list[dict[str, object]]:
    return [
        _consistency_sample(
            checker="text_support",
            score=text_support_score,
            threshold=70,
            evidence_ids=usable_evidence_ids,
            pass_rationale="Evidence text overlaps with the claim strongly enough.",
            fail_rationale="Evidence text does not lexically support the claim strongly enough.",
        ),
        _consistency_sample(
            checker="evidence_quality",
            score=evidence_quality_score,
            threshold=75,
            evidence_ids=usable_evidence_ids,
            pass_rationale="Usable evidence quality meets the enterprise review threshold.",
            fail_rationale="Usable evidence quality is below the enterprise review threshold.",
        ),
        _consistency_sample(
            checker="triangulation",
            score=triangulation_score,
            threshold=70,
            evidence_ids=usable_evidence_ids,
            pass_rationale="The claim has enough independent source triangulation for review.",
            fail_rationale="The claim lacks enough independent source triangulation.",
        ),
    ]


def _consistency_sample(
    *,
    checker: str,
    score: int,
    threshold: int,
    evidence_ids: list[str],
    pass_rationale: str,
    fail_rationale: str,
) -> dict[str, object]:
    passed = score >= threshold
    return {
        "checker": checker,
        "vote": "pass" if passed else "fail",
        "score": score,
        "threshold": threshold,
        "rationale": pass_rationale if passed else fail_rationale,
        "evidence_ids": evidence_ids,
    }


def _requires_triangulation(claim: ClaimRecord) -> bool:
    return bool(HIGH_RISK_CLAIM_RE.search(f"{claim.claim_text} {claim.claim_type}"))


def _evidence_domain(evidence: EvidenceRecord) -> str:
    raw = str(evidence.url or evidence.canonical_url or "")
    if not raw:
        return evidence.raw_source_id
    return urlparse(raw).netloc.casefold()


def _average_score(values: list[int]) -> int:
    if not values:
        return 0
    return round(sum(values) / len(values))


def _tokens(value: str) -> set[str]:
    tokens = {item.casefold() for item in _TOKEN_RE.findall(value)}
    return {item for item in tokens if len(item) > 1 and item not in _STOPWORDS}
