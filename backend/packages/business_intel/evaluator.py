from __future__ import annotations

import hashlib

from packages.schema.enterprise import (
    BusinessIntelPlan,
    BusinessQAEvaluation,
    BusinessQAFinding,
    BusinessQARule,
    ClaimRecord,
    CompetitorRecord,
    EvidenceRecord,
)

BAD_QUALITY_LABELS = {"rejected", "stale"}


def evaluate_business_qa(
    *,
    project_id: str,
    plan: BusinessIntelPlan,
    competitors: list[CompetitorRecord],
    evidence: list[EvidenceRecord],
    claims: list[ClaimRecord],
) -> BusinessQAEvaluation:
    findings: list[BusinessQAFinding] = []
    for rule in plan.qa_rules:
        findings.extend(
            _evaluate_rule(
                rule=rule,
                plan=plan,
                competitors=competitors,
                evidence=evidence,
                claims=claims,
            )
        )

    rules_with_findings = {finding.rule_id for finding in findings}
    return BusinessQAEvaluation(
        project_id=project_id,
        scenario_id=plan.scenario_pack.id,
        competitor_layer=plan.competitor_layer.layer,
        total_rules=len(plan.qa_rules),
        passed_rules=len([rule for rule in plan.qa_rules if rule.id not in rules_with_findings]),
        finding_count=len(findings),
        blocker_count=len([item for item in findings if item.severity == "blocker"]),
        warn_count=len([item for item in findings if item.severity == "warn"]),
        info_count=len([item for item in findings if item.severity == "info"]),
        findings=findings,
    )


def _evaluate_rule(
    *,
    rule: BusinessQARule,
    plan: BusinessIntelPlan,
    competitors: list[CompetitorRecord],
    evidence: list[EvidenceRecord],
    claims: list[ClaimRecord],
) -> list[BusinessQAFinding]:
    if rule.id == "claim_has_evidence":
        return _claim_linkage_findings(rule=rule, evidence=evidence, claims=claims)
    if rule.id == "landscape_breadth":
        return _landscape_findings(rule=rule, competitors=competitors)
    if rule.id == "homepage_verified":
        return _homepage_findings(rule=rule, competitors=competitors)
    if rule.id == "source_reliability_min":
        return _source_reliability_findings(rule=rule, evidence=evidence)
    return _coverage_findings(
        rule=rule,
        plan=plan,
        competitors=competitors,
        evidence=evidence,
    )


def _coverage_findings(
    *,
    rule: BusinessQARule,
    plan: BusinessIntelPlan,
    competitors: list[CompetitorRecord],
    evidence: list[EvidenceRecord],
) -> list[BusinessQAFinding]:
    findings: list[BusinessQAFinding] = []
    dimensions = _dimensions_for_rule(rule, plan)
    for competitor in competitors:
        for dimension in dimensions:
            matching = [
                item
                for item in evidence
                if item.competitor_id == competitor.id
                and _same_dimension(item.dimension, dimension)
                and item.quality_label not in BAD_QUALITY_LABELS
            ]
            eligible = [
                item
                for item in matching
                if not rule.require_verified_source or item.source_type == "webpage_verified"
            ]
            if len(eligible) >= rule.min_sources_per_competitor:
                continue
            findings.append(
                _finding(
                    rule=rule,
                    competitor=competitor,
                    dimension=dimension,
                    message=(
                        f"{competitor.name} needs {rule.min_sources_per_competitor} "
                        f"{'verified ' if rule.require_verified_source else ''}"
                        f"evidence item(s) for {dimension}."
                    ),
                    evidence_ids=[item.id for item in matching],
                    recommendation=rule.rationale,
                )
            )
    return findings


def _homepage_findings(
    *,
    rule: BusinessQARule,
    competitors: list[CompetitorRecord],
) -> list[BusinessQAFinding]:
    findings: list[BusinessQAFinding] = []
    for competitor in competitors:
        if competitor.metadata.get("homepage_verified") is True or competitor.homepage_url:
            continue
        findings.append(
            _finding(
                rule=rule,
                competitor=competitor,
                dimension="homepage",
                message=f"{competitor.name} does not have a verified homepage.",
                recommendation=rule.rationale,
            )
        )
    return findings


def _source_reliability_findings(
    *,
    rule: BusinessQARule,
    evidence: list[EvidenceRecord],
) -> list[BusinessQAFinding]:
    findings: list[BusinessQAFinding] = []
    for item in evidence:
        if item.quality_label in BAD_QUALITY_LABELS or item.reliability_score >= 0.5:
            continue
        findings.append(
            _finding(
                rule=rule,
                competitor=None,
                dimension=item.dimension,
                message=f"Evidence {item.id} has low reliability score.",
                evidence_ids=[item.id],
                recommendation=rule.rationale,
            )
        )
    return findings


def _claim_linkage_findings(
    *,
    rule: BusinessQARule,
    evidence: list[EvidenceRecord],
    claims: list[ClaimRecord],
) -> list[BusinessQAFinding]:
    evidence_by_id = {item.id: item for item in evidence}
    findings: list[BusinessQAFinding] = []
    for claim in claims:
        linked_evidence = [evidence_by_id.get(item) for item in claim.evidence_ids]
        usable_evidence = [
            item
            for item in linked_evidence
            if item is not None and item.quality_label not in BAD_QUALITY_LABELS
        ]
        if usable_evidence:
            continue
        findings.append(
            _finding(
                rule=rule,
                competitor=None,
                dimension=claim.claim_type,
                message="Claim has no usable EvidenceRecord after quality filtering.",
                claim_ids=[claim.id],
                evidence_ids=claim.evidence_ids,
                recommendation=(
                    "Attach an accepted or unreviewed evidence record, or reject the claim."
                ),
            )
        )
    return findings


def _landscape_findings(
    *,
    rule: BusinessQARule,
    competitors: list[CompetitorRecord],
) -> list[BusinessQAFinding]:
    if len(competitors) >= 4:
        return []
    return [
        _finding(
            rule=rule,
            competitor=None,
            dimension="market",
            message="Landscape analysis has fewer than four competitors.",
            recommendation="Add more competitors or downgrade the project to L1/L2.",
        )
    ]


def _dimensions_for_rule(rule: BusinessQARule, plan: BusinessIntelPlan) -> list[str]:
    if rule.required_dimensions:
        return rule.required_dimensions
    return plan.scenario_pack.required_dimensions or plan.requested_dimensions


def _same_dimension(left: str, right: str) -> bool:
    left_key = left.casefold().strip()
    right_key = right.casefold().strip()
    return left_key == right_key or left_key in right_key or right_key in left_key


def _finding(
    *,
    rule: BusinessQARule,
    competitor: CompetitorRecord | None,
    dimension: str | None,
    message: str,
    evidence_ids: list[str] | None = None,
    claim_ids: list[str] | None = None,
    recommendation: str = "",
) -> BusinessQAFinding:
    raw = "|".join(
        [
            rule.id,
            competitor.id if competitor else "",
            dimension or "",
            message,
        ]
    )
    return BusinessQAFinding(
        id=f"business-qa-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}",
        rule_id=rule.id,
        rule_name=rule.name,
        severity=rule.severity,
        competitor_id=competitor.id if competitor else None,
        competitor_name=competitor.name if competitor else None,
        dimension=dimension,
        message=message,
        evidence_ids=evidence_ids or [],
        claim_ids=claim_ids or [],
        recommendation=recommendation,
    )
