from __future__ import annotations

import hashlib
import re

from packages.business_intel.evaluator import BAD_QUALITY_LABELS, evaluate_business_qa
from packages.business_intel.claim_validator import validate_project_claims
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
MIN_RELEASE_SOURCE_CONFIDENCE = 0.75
STRONG_CONCLUSION_RE = re.compile(
    r"\b("
    r"winner|leading option|best option|safer|safest|recommended|recommendation|"
    r"dimension winner|executive summary|soc\s*2|iso\s*/?\s*iec|ip indemnity|"
    r"sso|saml|scim|audit log|pricing transparency"
    r")\b",
    flags=re.IGNORECASE,
)


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
        *_claim_evidence_quality_issues(scoped_claims, scoped_evidence),
        *_claim_validation_issues(scoped_claims, scoped_evidence),
        *_report_citation_quality_issues(report_version, scoped_evidence),
        *_run_quality_issues(report_version),
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


def _claim_evidence_quality_issues(
    claims: list[ClaimRecord],
    evidence: list[EvidenceRecord],
) -> list[BusinessQAFinding]:
    evidence_by_id = {item.id: item for item in evidence}
    issues: list[BusinessQAFinding] = []
    for claim in claims:
        weak = [
            item
            for evidence_id in claim.evidence_ids
            if (item := evidence_by_id.get(evidence_id)) is not None
            and (
                item.source_type != "webpage_verified"
                or item.reliability_score < MIN_RELEASE_SOURCE_CONFIDENCE
                or item.quality_label in BAD_QUALITY_LABELS
            )
        ]
        if not weak:
            continue
        issues.append(
            _gate_issue(
                "claim_uses_low_confidence_evidence",
                "Claim evidence confidence",
                (
                    f"Claim {claim.id} depends on {len(weak)} weak evidence item(s); "
                    "release claims require verified webpage evidence with confidence >= "
                    f"{MIN_RELEASE_SOURCE_CONFIDENCE:.2f}."
                ),
                claim_ids=[claim.id],
                evidence_ids=[item.id for item in weak],
                recommendation=(
                    "Redo collection for this claim using official or fetched webpages before "
                    "publishing."
                ),
            )
        )
    return issues


def _claim_validation_issues(
    claims: list[ClaimRecord],
    evidence: list[EvidenceRecord],
) -> list[BusinessQAFinding]:
    if not claims:
        return []
    project_id = claims[0].project_id
    validation = validate_project_claims(project_id=project_id, claims=claims, evidence=evidence)
    issues: list[BusinessQAFinding] = []
    for result in validation.results:
        if result.status == "supported":
            continue
        severity = "blocker" if result.status in {"blocked", "unsupported"} else "warn"
        issues.append(
            _gate_issue(
                "claim_self_consistency_required",
                "Claim self-consistency",
                (
                    f"Claim {result.claim_id} validation is {result.status}; "
                    f"self-consistency={result.self_consistency_score}, "
                    f"text={result.text_support_score}, "
                    f"evidence={result.evidence_quality_score}, "
                    f"triangulation={result.triangulation_score}."
                ),
                severity=severity,
                claim_ids=[result.claim_id],
                evidence_ids=result.usable_evidence_ids,
                recommendation=(
                    "Collect stronger independent evidence or downgrade the claim before release."
                ),
            )
        )
    return issues


def _report_citation_quality_issues(
    report_version: ReportVersionRecord,
    evidence: list[EvidenceRecord],
) -> list[BusinessQAFinding]:
    evidence_by_token: dict[str, EvidenceRecord] = {}
    for item in evidence:
        evidence_by_token[item.id] = item
        evidence_by_token[item.raw_source_id] = item

    issues: list[BusinessQAFinding] = []
    for line in report_version.report_md.splitlines():
        if not STRONG_CONCLUSION_RE.search(line):
            continue
        weak = [
            evidence_by_token[token]
            for token in _cited_source_tokens(line)
            if token in evidence_by_token
            and (
                evidence_by_token[token].source_type != "webpage_verified"
                or evidence_by_token[token].reliability_score < MIN_RELEASE_SOURCE_CONFIDENCE
                or evidence_by_token[token].quality_label in BAD_QUALITY_LABELS
            )
        ]
        if not weak:
            continue
        issues.append(
            _gate_issue(
                "strong_conclusion_uses_weak_source",
                "Strong conclusion source quality",
                (
                    "A strong report conclusion cites weak or search-only evidence. "
                    f"Line: {line.strip()[:220]}"
                ),
                evidence_ids=[item.id for item in weak],
                recommendation=(
                    "Rewrite the conclusion as tentative or recollect official/verified sources."
                ),
            )
        )
    return issues


def _run_quality_issues(report_version: ReportVersionRecord) -> list[BusinessQAFinding]:
    findings = report_version.quality_metadata.get("run_qa_findings", [])
    if not isinstance(findings, list) or not findings:
        return []
    blocker_count = sum(1 for item in findings if _mapping_value(item, "severity") == "blocker")
    warn_count = sum(1 for item in findings if _mapping_value(item, "severity") == "warn")
    top_problems = [
        str(_mapping_value(item, "problem") or _mapping_value(item, "id") or "quality issue")
        for item in findings[:3]
    ]
    return [
        _gate_issue(
            "run_qa_findings_unresolved",
            "Run QA findings unresolved",
            (
                "Report release requires a clean run-level QA result; "
                f"current run has {blocker_count} blocker(s) and {warn_count} warning(s). "
                f"Top issue(s): {'; '.join(top_problems)}"
            ),
            recommendation=(
                "Run scoped redo for the affected collector/analyst/comparator branches before "
                "publishing."
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
    severity: str = "blocker",
    recommendation: str,
) -> BusinessQAFinding:
    raw = "|".join([rule_id, message, ",".join(evidence_ids or []), ",".join(claim_ids or [])])
    return BusinessQAFinding(
        id=f"release-gate-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}",
        rule_id=rule_id,
        rule_name=rule_name,
        severity=severity,  # type: ignore[arg-type]
        message=message,
        evidence_ids=evidence_ids or [],
        claim_ids=claim_ids or [],
        recommendation=recommendation,
    )


def _cited_source_tokens(line: str) -> list[str]:
    return re.findall(r"\[source:([A-Za-z0-9_.:-]+)\]", line)


def _mapping_value(value: object, key: str) -> object:
    if isinstance(value, dict):
        return value.get(key)
    return None
