from __future__ import annotations

from packages.research.models import QualityGap
from packages.schema.enterprise import BusinessQAFinding, ReportReleaseGate


def quality_gaps_from_release_gate(gate: ReportReleaseGate) -> list[QualityGap]:
    return [_quality_gap_from_release_issue(issue) for issue in gate.issues]


def _quality_gap_from_release_issue(issue: BusinessQAFinding) -> QualityGap:
    dimension = _dimension_from_issue(issue)
    return QualityGap(
        severity=_severity(issue),
        dimension=dimension,
        competitor=issue.competitor_name,
        field=_field_from_issue(issue),
        reason=f"{issue.rule_id}: {issue.message}",
        suggested_action=_repair_strategy(issue.rule_id, dimension),
        acceptance_rule=issue.recommendation or _default_acceptance_rule(issue.rule_id),
        source_ids=issue.evidence_ids,
        metadata={
            "source": "release_gate",
            "release_gate_issue_id": issue.id,
            "rule_id": issue.rule_id,
            "rule_name": issue.rule_name,
            "claim_ids": issue.claim_ids,
        },
    )


def _severity(issue: BusinessQAFinding) -> str:
    if issue.severity == "blocker":
        return "blocker"
    if issue.severity == "warn":
        return "warn"
    return "info"


def _dimension_from_issue(issue: BusinessQAFinding) -> str:
    if issue.dimension:
        return issue.dimension
    text = f"{issue.rule_id} {issue.rule_name} {issue.message}".casefold()
    if "pricing" in text or "billing" in text or "tier" in text:
        return "pricing"
    if "persona" in text or "customer" in text or "user" in text:
        return "persona"
    if "feature" in text or "capability" in text:
        return "feature"
    if "security" in text or "sso" in text or "soc" in text or "iso" in text:
        return "security"
    if "citation" in text or "report" in text or "structure" in text:
        return "report"
    if "claim" in text:
        return "claim"
    return "general"


def _field_from_issue(issue: BusinessQAFinding) -> str | None:
    if issue.claim_ids:
        return "claim_evidence"
    if issue.evidence_ids:
        return "evidence"
    if "citation" in issue.rule_id:
        return "source_citation"
    if "structure" in issue.rule_id:
        return "report_structure"
    if "depth" in issue.rule_id:
        return "report_depth"
    return None


def _repair_strategy(rule_id: str, dimension: str) -> str:
    if rule_id in {
        "report_citation_resolves",
        "report_citation_token_format",
        "report_structure_required",
        "report_depth_required",
        "strong_conclusion_uses_weak_source",
    }:
        return "human_review"
    if "pricing" in dimension:
        return "pricing_model_repair"
    if "persona" in dimension:
        return "persona_schema_repair"
    if "feature" in dimension:
        return "feature_slot_repair"
    if rule_id in {
        "claim_uses_low_confidence_evidence",
        "claim_self_consistency_required",
        "claim_evidence_in_report",
        "verified_evidence_rate",
        "source_policy_review_required",
        "rag_gap_fill_chain_unclosed",
        "run_qa_findings_unresolved",
        "business_qa_clean_required",
        "readiness_required",
    }:
        return "targeted_discovery"
    return "human_review"


def _default_acceptance_rule(rule_id: str) -> str:
    if "citation" in rule_id:
        return "All report source tokens resolve to scoped canonical RawSource/Evidence ids."
    if "claim" in rule_id:
        return "Every release claim has accepted, verified, high-confidence evidence."
    if "evidence" in rule_id or "source" in rule_id:
        return "Release-scoped evidence meets verified source and policy requirements."
    return "Release gate passes with no blocker issues."
