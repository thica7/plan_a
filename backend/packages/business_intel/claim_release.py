from __future__ import annotations

from collections.abc import Iterable

from packages.business_intel.claim_validator import validate_project_claims
from packages.schema.enterprise import (
    ClaimRecord,
    ClaimReleaseDecision,
    ClaimValidationIssue,
    EvidenceRecord,
)


def plan_claim_release_decisions(
    *,
    project_id: str,
    claims: list[ClaimRecord],
    evidence: list[EvidenceRecord],
) -> list[ClaimReleaseDecision]:
    """Convert claim validation into explicit publish/repair actions."""

    validation = validate_project_claims(project_id=project_id, claims=claims, evidence=evidence)
    claims_by_id = {claim.id: claim for claim in claims}
    issues_by_id = {issue.id: issue for issue in validation.issues}

    decisions: list[ClaimReleaseDecision] = []
    for result in validation.results:
        claim = claims_by_id.get(result.claim_id)
        if claim is None:
            continue
        issues = [
            issues_by_id[issue_id]
            for issue_id in result.issue_ids
            if issue_id in issues_by_id
        ]
        issue_types = [issue.issue_type for issue in issues]
        action = _action_for_result(result.status, issue_types)
        decisions.append(
            ClaimReleaseDecision(
                claim_id=claim.id,
                action=action,
                publishable=action == "keep",
                competitor_id=claim.competitor_id,
                dimension=claim.claim_type,
                reason=_reason(action, issue_types),
                issue_types=issue_types,
                evidence_ids=result.usable_evidence_ids or claim.evidence_ids,
                support_score=result.support_score,
                text_support_score=result.text_support_score,
                evidence_quality_score=result.evidence_quality_score,
                triangulation_score=result.triangulation_score,
                acceptance_rule=_acceptance_rule(action, issues),
            )
        )
    return decisions


def apply_claim_release_decisions(
    claims: list[ClaimRecord],
    decisions: list[ClaimReleaseDecision],
) -> list[ClaimRecord]:
    decisions_by_id = {decision.claim_id: decision for decision in decisions}
    updated: list[ClaimRecord] = []
    for claim in claims:
        decision = decisions_by_id.get(claim.id)
        if decision is None:
            updated.append(claim)
            continue
        updated.append(claim.model_copy(update={"status": _claim_status(decision.action)}))
    return updated


def publishable_claim_ids(
    claims: list[ClaimRecord],
    decisions: list[ClaimReleaseDecision],
) -> list[str]:
    publishable = {decision.claim_id for decision in decisions if decision.publishable}
    return [claim.id for claim in claims if claim.id in publishable]


def claim_release_summary(decisions: Iterable[ClaimReleaseDecision]) -> dict[str, object]:
    counts = {
        action: 0
        for action in ["keep", "add_evidence", "downgrade", "delete", "human_review"]
    }
    decision_payloads: list[dict[str, object]] = []
    for decision in decisions:
        counts[decision.action] += 1
        decision_payloads.append(decision.model_dump(mode="json"))
    return {
        "action_counts": counts,
        "publishable_claim_count": counts["keep"],
        "withheld_claim_count": (
            counts["add_evidence"]
            + counts["downgrade"]
            + counts["delete"]
            + counts["human_review"]
        ),
        "decisions": decision_payloads,
    }


def append_claim_release_section(
    report_md: str,
    decisions: list[ClaimReleaseDecision],
) -> str:
    withheld = [decision for decision in decisions if not decision.publishable]
    if not withheld:
        return report_md
    lines = [
        report_md.rstrip(),
        "",
        "## Claim Release Controls",
        (
            "The publication scope keeps only claims that passed claim self-consistency. "
            "Claims below that bar are withheld from release scope and routed to repair."
        ),
    ]
    for decision in withheld[:12]:
        source_refs = " ".join(f"[source:{item}]" for item in decision.evidence_ids[:2])
        source_suffix = f" {source_refs}" if source_refs else ""
        lines.append(
            "- "
            f"`{decision.claim_id}` action={decision.action}; "
            f"dimension={decision.dimension}; score={decision.support_score}; "
            f"reason={decision.reason}.{source_suffix}"
        )
    if len(withheld) > 12:
        lines.append(f"- {len(withheld) - 12} additional withheld claim(s) recorded in metadata.")
    return "\n".join(lines).rstrip() + "\n"


def _action_for_result(status: str, issue_types: list[str]) -> str:
    issue_set = set(issue_types)
    if status == "supported":
        return "keep"
    if status == "blocked":
        return "delete"
    if status == "unsupported":
        if "missing_evidence" in issue_set or "stale_or_rejected_evidence" in issue_set:
            return "delete"
        return "downgrade"
    if "single_source_support" in issue_set or "low_evidence_quality" in issue_set:
        return "add_evidence"
    if issue_set & {"weak_text_support", "low_self_consistency", "low_confidence"}:
        return "downgrade"
    return "human_review"


def _claim_status(action: str) -> str:
    if action == "keep":
        return "accepted"
    if action == "delete":
        return "rejected"
    if action == "downgrade":
        return "deprecated"
    return "disputed"


def _reason(action: str, issue_types: list[str]) -> str:
    issue_summary = ", ".join(issue_types) if issue_types else "no issue"
    if action == "keep":
        return "claim passed release self-consistency checks"
    if action == "add_evidence":
        return f"claim requires stronger independent evidence: {issue_summary}"
    if action == "downgrade":
        return f"claim is retained only as a caveat until repaired: {issue_summary}"
    if action == "delete":
        return f"claim is removed from release scope: {issue_summary}"
    return f"claim requires human review: {issue_summary}"


def _acceptance_rule(action: str, issues: list[ClaimValidationIssue]) -> str:
    if action == "keep":
        return "Claim remains publishable while validation status is supported."
    issue_types = {issue.issue_type for issue in issues}
    if action == "add_evidence":
        if "single_source_support" in issue_types:
            return "Collect at least two independent verified sources before publishing this claim."
        return "Replace weak evidence with accepted verified webpage evidence before publishing."
    if action == "downgrade":
        return "Rewrite the claim as tentative caveat text or remove it from release claims."
    if action == "delete":
        return "Remove the unsupported claim from the release-scoped claim list."
    return "Route this claim to human review before approval."
