from __future__ import annotations

import hashlib

from packages.business_intel.evaluator import BAD_QUALITY_LABELS, evaluate_business_qa
from packages.business_intel.planning import build_business_intel_plan
from packages.business_intel.scorer import score_project_readiness
from packages.schema.enterprise import (
    BusinessQAFinding,
    ClaimRecord,
    CompetitorRecord,
    EvidenceRecord,
    ProjectReadinessScore,
    ProjectRecord,
    ReportReleaseGate,
    ReportVersionRecord,
)

MIN_VERIFIED_EVIDENCE_RATE = 0.8
MIN_READY_SCORE = 85


def evaluate_report_release_gate(
    *,
    project: ProjectRecord,
    report_version: ReportVersionRecord,
    competitors: list[CompetitorRecord],
    evidence: list[EvidenceRecord],
    claims: list[ClaimRecord],
) -> ReportReleaseGate:
    """Strict enterprise gate for approving or publishing a report version."""

    scoped_evidence = _scope_evidence(report_version, evidence)
    scoped_claims = _scope_claims(report_version, claims)
    dimensions = sorted({item.dimension for item in scoped_evidence}) or [
        "pricing",
        "feature",
        "persona",
    ]
    plan = build_business_intel_plan(
        topic=project.topic,
        competitors=[item.name for item in competitors],
        dimensions=dimensions,
        requested_layer=project.competitor_layer if project.competitor_layer != "unknown" else None,
        requested_scenario_id=project.scenario_id,
    )
    qa_evaluation = evaluate_business_qa(
        project_id=project.id,
        plan=plan,
        competitors=competitors,
        evidence=scoped_evidence,
        claims=scoped_claims,
    )
    readiness = score_project_readiness(
        project_id=project.id,
        plan=plan,
        qa_evaluation=qa_evaluation,
        competitors=competitors,
        evidence=scoped_evidence,
        claims=scoped_claims,
    )
    issues = [
        *_report_integrity_issues(report_version, scoped_evidence, scoped_claims),
        *_source_quality_issues(scoped_evidence),
        *_readiness_issues(readiness),
        *_strict_qa_issues(qa_evaluation.findings),
    ]
    blocker_count = len([item for item in issues if item.severity == "blocker"])
    warn_count = len([item for item in issues if item.severity == "warn"])
    allowed = blocker_count == 0 and qa_evaluation.finding_count == 0
    return ReportReleaseGate(
        report_version_id=report_version.id,
        workspace_id=report_version.workspace_id,
        project_id=report_version.project_id,
        allowed=allowed,
        status="pass" if allowed else "blocked",
        readiness=readiness,
        qa_evaluation=qa_evaluation,
        issue_count=len(issues),
        blocker_count=blocker_count,
        warn_count=warn_count,
        issues=issues,
    )


def _scope_evidence(
    report_version: ReportVersionRecord,
    evidence: list[EvidenceRecord],
) -> list[EvidenceRecord]:
    allowed_ids = set(report_version.evidence_ids)
    return [item for item in evidence if item.id in allowed_ids]


def _scope_claims(
    report_version: ReportVersionRecord,
    claims: list[ClaimRecord],
) -> list[ClaimRecord]:
    allowed_ids = set(report_version.claim_ids)
    return [item for item in claims if item.id in allowed_ids]


def _report_integrity_issues(
    report_version: ReportVersionRecord,
    evidence: list[EvidenceRecord],
    claims: list[ClaimRecord],
) -> list[BusinessQAFinding]:
    issues: list[BusinessQAFinding] = []
    if not report_version.report_md.strip():
        issues.append(
            _gate_issue(
                "report_body_required",
                "Report body required",
                "Report body is empty; approval is blocked until a readable report exists.",
                recommendation="Regenerate the report after evidence and claims are available.",
            )
        )
    if not evidence:
        issues.append(
            _gate_issue(
                "report_evidence_required",
                "Report evidence required",
                "Report version has no scoped evidence records.",
                recommendation="Collect and attach verified EvidenceRecord items before approval.",
            )
        )
    if not claims:
        issues.append(
            _gate_issue(
                "report_claim_required",
                "Report claims required",
                "Report version has no scoped knowledge claims.",
                recommendation="Project structured claims from accepted evidence before approval.",
            )
        )
    evidence_ids = {item.id for item in evidence}
    for claim in claims:
        missing = [item for item in claim.evidence_ids if item not in evidence_ids]
        if not missing:
            continue
        issues.append(
            _gate_issue(
                "claim_evidence_in_report",
                "Claim evidence must be in report",
                f"Claim {claim.id} cites evidence outside this report version.",
                claim_ids=[claim.id],
                evidence_ids=missing,
                recommendation="Attach the cited evidence to this report or remove the claim.",
            )
        )
    return issues


def _source_quality_issues(evidence: list[EvidenceRecord]) -> list[BusinessQAFinding]:
    if not evidence:
        return []
    verified = [
        item
        for item in evidence
        if item.source_type == "webpage_verified"
        and item.quality_label not in BAD_QUALITY_LABELS
        and item.reliability_score >= 0.5
    ]
    verified_rate = len(verified) / len(evidence)
    if verified_rate >= MIN_VERIFIED_EVIDENCE_RATE:
        return []
    return [
        _gate_issue(
            "verified_evidence_rate",
            "Verified evidence rate",
            (
                f"Only {verified_rate:.0%} of report evidence is verified and usable; "
                f"minimum is {MIN_VERIFIED_EVIDENCE_RATE:.0%}."
            ),
            evidence_ids=[item.id for item in evidence],
            recommendation=(
                "Replace weak sources with verified webpages or mark bad evidence stale/rejected."
            ),
        )
    ]


def _readiness_issues(readiness: ProjectReadinessScore) -> list[BusinessQAFinding]:
    if readiness.risk_level == "ready" and readiness.score >= MIN_READY_SCORE:
        return []
    return [
        _gate_issue(
            "readiness_required",
            "Readiness threshold",
            (
                f"Readiness is {readiness.risk_level} with score {readiness.score}; "
                f"approval requires ready and score >= {MIN_READY_SCORE}."
            ),
            recommendation="Resolve evidence, coverage, claim, and QA gaps before approval.",
        )
    ]


def _strict_qa_issues(findings: list[BusinessQAFinding]) -> list[BusinessQAFinding]:
    if not findings:
        return []
    warn_count = len([item for item in findings if item.severity == "warn"])
    blocker_count = len([item for item in findings if item.severity == "blocker"])
    return [
        _gate_issue(
            "business_qa_clean_required",
            "Business QA must be clean",
            (
                "Report approval requires zero business QA findings; "
                f"current evaluation has {blocker_count} blocker(s) and {warn_count} warning(s)."
            ),
            recommendation="Resolve all Business QA findings or keep the report in draft.",
        )
    ]


def _gate_issue(
    rule_id: str,
    rule_name: str,
    message: str,
    *,
    evidence_ids: list[str] | None = None,
    claim_ids: list[str] | None = None,
    recommendation: str,
) -> BusinessQAFinding:
    raw = "|".join([rule_id, message, ",".join(evidence_ids or []), ",".join(claim_ids or [])])
    return BusinessQAFinding(
        id=f"release-gate-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}",
        rule_id=rule_id,
        rule_name=rule_name,
        severity="blocker",
        message=message,
        evidence_ids=evidence_ids or [],
        claim_ids=claim_ids or [],
        recommendation=recommendation,
    )
