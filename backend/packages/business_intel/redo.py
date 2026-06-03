from __future__ import annotations

from packages.schema.enterprise import (
    BusinessQAFinding,
    ClaimValidationIssue,
    EvidenceGapItem,
    RedTeamFinding,
)
from packages.schema.models import RedoScope

RULE_REDO_KIND = {
    "coverage_min_verified": "collector",
    "claim_has_evidence": "writer_only",
    "pricing_currentness": "collector",
    "cross_competitor_matrix": "comparator",
    "security_official_source": "analyst",
    "landscape_breadth": "full",
    "homepage_verified": "collector",
    "source_reliability_min": "collector",
}


def business_findings_to_redo_scopes(findings: list[BusinessQAFinding]) -> list[RedoScope]:
    scopes: list[RedoScope] = []
    for finding in findings:
        kind = RULE_REDO_KIND.get(finding.rule_id, "collector")
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
        scopes.append(
            RedoScope(
                kind=kind,  # type: ignore[arg-type]
                target_subagent="claim_validation",
                rationale=issue.message,
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
