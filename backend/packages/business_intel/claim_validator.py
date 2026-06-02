from __future__ import annotations

import re
from datetime import datetime

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
        support_score = _support_score(claim, usable)

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
        elif support_score < 40:
            issue = _issue(
                claim.id,
                "warn",
                "weak_text_support",
                "Evidence text has weak lexical support for the claim.",
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

        has_blocker = any(
            item.endswith(":missing_evidence")
            or item.endswith(":stale_or_rejected_evidence")
            for item in claim_issue_ids
        )
        if has_blocker:
            status = "blocked"
        elif support_score >= 70 and not claim_issue_ids:
            status = "supported"
        elif support_score >= 40:
            status = "weak"
        else:
            status = "unsupported"

        results.append(
            ClaimValidationResult(
                claim_id=claim.id,
                status=status,
                support_score=support_score,
                usable_evidence_ids=[item.id for item in usable],
                issue_ids=claim_issue_ids,
            )
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


def _tokens(value: str) -> set[str]:
    tokens = {item.casefold() for item in _TOKEN_RE.findall(value)}
    return {item for item in tokens if len(item) > 1 and item not in _STOPWORDS}
