from __future__ import annotations

from packages.schema.enterprise import (
    BusinessQAFinding,
    ClaimValidationIssue,
    EvidenceGapItem,
    RedTeamFinding,
)
from packages.schema.models import RedoScope

EVIDENCE_REPAIR_CLAIM_ISSUE_TYPES = {
    "missing_evidence",
    "stale_or_rejected_evidence",
    "low_evidence_quality",
    "single_source_support",
}

CLAIM_REWRITE_ISSUE_TYPES = {
    "conflicting_evidence",
    "weak_text_support",
    "low_self_consistency",
}

RULE_REDO_KIND = {
    "coverage_min_verified": "collector",
    "claim_has_evidence": "writer_only",
    "claim_uses_low_confidence_evidence": "collector",
    "pricing_currentness": "collector",
    "cross_competitor_matrix": "comparator",
    "security_official_source": "analyst",
    "landscape_breadth": "full",
    "homepage_verified": "collector",
    "source_reliability_min": "collector",
    "source_policy_review_required": "collector",
    "verified_evidence_rate": "collector",
    "claim_self_consistency_required": "analyst",
    "claim_evidence_in_report": "analyst",
    "report_claim_required": "analyst",
    "report_body_required": "writer_only",
    "report_citation_resolves": "writer_only",
    "report_citation_token_format": "writer_only",
    "report_depth_required": "writer_only",
    "report_evidence_required": "collector",
    "report_status_releasable": "writer_only",
    "report_structure_required": "writer_only",
    "run_schema_validation_failed": "full",
    "rag_gap_fill_chain_unclosed": "collector",
    "strong_conclusion_uses_weak_source": "writer_only",
}


def business_findings_to_redo_scopes(findings: list[BusinessQAFinding]) -> list[RedoScope]:
    scopes: list[RedoScope] = []
    for finding in findings:
        kind = _business_finding_redo_kind(finding)
        scopes.append(
            RedoScope(
                kind=kind,  # type: ignore[arg-type]
                target_subagent=finding.dimension,
                target_competitor=finding.competitor_name,
                target_competitors=[finding.competitor_name]
                if finding.competitor_name
                else [],
                rationale=finding.recommendation or finding.message,
            )
        )
    return dedupe_redo_scopes(scopes)


def _business_finding_redo_kind(finding: BusinessQAFinding) -> str:
    if finding.rule_id == "claim_self_consistency_required":
        issue_types = _claim_validation_issue_types(finding)
        if issue_types & EVIDENCE_REPAIR_CLAIM_ISSUE_TYPES:
            return "collector"
        if issue_types & CLAIM_REWRITE_ISSUE_TYPES:
            return "analyst"
        return "analyst"

    mapped = RULE_REDO_KIND.get(finding.rule_id)
    if mapped:
        return mapped

    text = f"{finding.rule_id} {finding.message}".casefold()
    if any(issue_type in text for issue_type in EVIDENCE_REPAIR_CLAIM_ISSUE_TYPES):
        return "collector"
    if (
        "low_confidence_evidence" in text
        or "verified_evidence" in text
        or "source_policy" in text
        or "evidence_required" in text
        or "rag_gap_fill" in text
    ):
        return "collector"
    if any(issue_type in text for issue_type in CLAIM_REWRITE_ISSUE_TYPES):
        return "analyst"
    if "strong_conclusion" in text or "weak_source" in text:
        return "writer_only"
    if "citation" in text or "source token" in text or "report_" in text:
        return "writer_only"
    return "writer_only"


def _claim_validation_issue_types(finding: BusinessQAFinding) -> set[str]:
    raw_issue_types = finding.metadata.get("claim_validation_issue_types")
    issue_types: set[str] = set()
    if isinstance(raw_issue_types, list):
        issue_types = {
            str(item).strip().casefold() for item in raw_issue_types if str(item).strip()
        }
    if issue_types:
        return issue_types

    text = f"{finding.rule_id} {finding.message}".casefold()
    return {
        issue_type
        for issue_type in EVIDENCE_REPAIR_CLAIM_ISSUE_TYPES | CLAIM_REWRITE_ISSUE_TYPES
        if issue_type in text
    }


def claim_validation_issues_to_redo_scopes(
    issues: list[ClaimValidationIssue],
) -> list[RedoScope]:
    scopes: list[RedoScope] = []
    collector_issue_types = {
        "missing_evidence",
        "stale_or_rejected_evidence",
        "low_evidence_quality",
        "single_source_support",
    }
    for issue in issues:
        kind = "collector" if issue.issue_type in collector_issue_types else "analyst"
        evidence_hint = (
            f" Evidence ids: {', '.join(issue.evidence_ids)}."
            if issue.evidence_ids
            else " Evidence ids: none."
        )
        scopes.append(
            RedoScope(
                kind=kind,  # type: ignore[arg-type]
                target_subagent=f"claim_validation:{issue.claim_id}:{issue.issue_type}",
                rationale=(
                    f"Claim {issue.claim_id} failed {issue.issue_type}: "
                    f"{issue.message}{evidence_hint}"
                ),
            )
        )
    return dedupe_redo_scopes(scopes)


def evidence_gaps_to_redo_scopes(gaps: list[EvidenceGapItem]) -> list[RedoScope]:
    scopes = [
        RedoScope(
            kind="collector",
            target_subagent=gap.dimension,
            target_competitor=gap.competitor_name,
            target_competitors=[gap.competitor_name] if gap.competitor_name else [],
            rationale=gap.recommended_query or gap.message,
        )
        for gap in gaps
        if gap.severity in {"critical", "high"}
    ]
    return dedupe_redo_scopes(scopes)


def red_team_findings_to_redo_scopes(findings: list[RedTeamFinding]) -> list[RedoScope]:
    scopes: list[RedoScope] = []
    for finding in findings:
        if finding.severity not in {"critical", "high"}:
            continue
        kind = "writer_only" if finding.finding_type == "report_risk" else "analyst"
        if finding.finding_type in {"weak_evidence", "stale_or_rejected_evidence"}:
            kind = "collector"
        scopes.append(
            RedoScope(
                kind=kind,  # type: ignore[arg-type]
                target_subagent=finding.dimension,
                target_competitor=finding.competitor_name,
                target_competitors=[finding.competitor_name]
                if finding.competitor_name
                else [],
                rationale=finding.recommendation or finding.message,
            )
        )
    return dedupe_redo_scopes(scopes)


def dedupe_redo_scopes(scopes: list[RedoScope]) -> list[RedoScope]:
    result: list[RedoScope] = []
    seen: set[tuple[str, str | None, str | None, tuple[str, ...]]] = set()
    for scope in scopes:
        key = (
            scope.kind,
            scope.target_subagent,
            scope.target_competitor,
            tuple(scope.target_competitors),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(scope)
    return result
