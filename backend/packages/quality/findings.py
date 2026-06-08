from __future__ import annotations

from collections.abc import Iterable

from packages.business_intel.redo import (
    business_findings_to_redo_scopes,
    claim_validation_issues_to_redo_scopes,
    evidence_gaps_to_redo_scopes,
    red_team_findings_to_redo_scopes,
)
from packages.research.models import QualityGap
from packages.schema.enterprise import (
    BusinessQAFinding,
    ClaimValidationIssue,
    ClaimValidationReport,
    ClaimValidationResult,
    EvidenceGapItem,
    EvidenceGapReport,
    RedTeamFinding,
    RedTeamReport,
    ReportReleaseGate,
)
from packages.schema.evals import EvalOpsReport
from packages.schema.models import QCIssue, RedoScope
from packages.schema.quality import (
    QualityFinding,
    QualityFindingRequiredAction,
    QualityFindingSeverity,
)


def quality_findings_from_qc_issues(
    issues: Iterable[QCIssue],
    *,
    source_agent: str = "RuntimeQA",
    framework: str = "langgraph-qa",
) -> list[QualityFinding]:
    return [
        QualityFinding(
            source_agent=source_agent,
            framework=framework,
            source_id=issue.id,
            severity=issue.severity,
            issue_type=issue.detected_by,
            competitor_name=issue.target_competitor,
            dimension=issue.target_subagent,
            field_path=issue.field_path,
            report_section=_report_section_for_finding(issue.detected_by, issue.target_subagent),
            message=issue.problem,
            recommendation=issue.redo_scope.rationale,
            required_action=_required_action_from_redo(issue.redo_scope),
            acceptance_rule=_acceptance_rule_for_action(_required_action_from_redo(issue.redo_scope)),
            redo_scope=issue.redo_scope,
            metadata={
                "target_agent": issue.target_agent,
                "target_subagent": issue.target_subagent,
                "self_found": issue.self_found,
            },
        )
        for issue in issues
    ]


def quality_findings_from_business_qa(
    findings: Iterable[BusinessQAFinding],
    *,
    source_agent: str = "BusinessQA",
    framework: str = "deterministic-rules",
) -> list[QualityFinding]:
    result: list[QualityFinding] = []
    for finding in findings:
        action = _required_action_from_business_rule(finding)
        result.append(
            QualityFinding(
                source_agent=source_agent,
                framework=framework,
                source_id=finding.id,
                severity=finding.severity,
                issue_type=finding.rule_id,
                competitor_id=finding.competitor_id,
                competitor_name=finding.competitor_name,
                dimension=finding.dimension,
                field_path=finding.rule_id,
                report_section=_report_section_for_finding(finding.rule_id, finding.dimension),
                claim_ids=finding.claim_ids,
                evidence_ids=finding.evidence_ids,
                message=finding.message,
                recommendation=finding.recommendation,
                required_action=action,
                acceptance_rule=finding.recommendation or _acceptance_rule_for_action(action),
                redo_scope=_first_redo_scope(business_findings_to_redo_scopes([finding])),
                metadata={
                    "rule_id": finding.rule_id,
                    "rule_name": finding.rule_name,
                },
            )
        )
    return result


def quality_findings_from_release_gate(gate: ReportReleaseGate | None) -> list[QualityFinding]:
    if gate is None:
        return [
            QualityFinding(
                source_agent="ReleaseGate",
                framework="enterprise-release-gate",
                source_id="release_gate.missing_report",
                severity="warn",
                issue_type="missing_report_version",
                report_section="Report Lifecycle",
                message="No ReportVersion exists yet; release readiness cannot be evaluated.",
                recommendation="Generate a report version after evidence and claims are projected.",
                required_action="rewrite_report",
                acceptance_rule="A ReportVersion exists and release gate can evaluate it.",
            )
        ]
    return quality_findings_from_business_qa(
        gate.issues,
        source_agent="ReleaseGate",
        framework="enterprise-release-gate",
    )


def quality_findings_from_evidence_gaps(
    report_or_gaps: EvidenceGapReport | Iterable[EvidenceGapItem],
    *,
    framework: str | None = None,
) -> list[QualityFinding]:
    if isinstance(report_or_gaps, EvidenceGapReport):
        gaps = report_or_gaps.gaps
        framework = framework or report_or_gaps.framework
    else:
        gaps = list(report_or_gaps)
        framework = framework or "pydantic-ai"
    result: list[QualityFinding] = []
    for gap in gaps:
        action: QualityFindingRequiredAction = (
            "add_evidence"
            if gap.gap_type
            in {
                "missing_dimension_coverage",
                "missing_verified_source",
                "stale_or_rejected_evidence",
                "claim_without_usable_evidence",
            }
            else "human_review"
        )
        result.append(
            QualityFinding(
                source_agent="EvidenceGap",
                framework=framework,
                source_id=gap.id,
                severity=_severity_from_gap(gap.severity),
                issue_type=gap.gap_type,
                competitor_id=gap.competitor_id,
                competitor_name=gap.competitor_name,
                dimension=gap.dimension,
                field_path=gap.source_type_required,
                report_section=_report_section_for_finding(gap.gap_type, gap.dimension),
                claim_ids=gap.claim_ids,
                evidence_ids=gap.evidence_ids,
                message=gap.message,
                recommendation=gap.recommended_query,
                required_action=action,
                acceptance_rule=gap.recommended_query
                or _acceptance_rule_for_action(action),
                redo_scope=_first_redo_scope(evidence_gaps_to_redo_scopes([gap])),
                metadata={
                    "gap_type": gap.gap_type,
                    "retrieval_query": gap.retrieval_query,
                    "retrieval_candidate_chunk_count": gap.retrieval_candidate_chunk_count,
                    "retrieval_unique_evidence_count": gap.retrieval_unique_evidence_count,
                },
            )
        )
    return result


def quality_findings_from_red_team(
    report_or_findings: RedTeamReport | Iterable[RedTeamFinding],
    *,
    framework: str | None = None,
) -> list[QualityFinding]:
    if isinstance(report_or_findings, RedTeamReport):
        findings = report_or_findings.findings
        framework = framework or report_or_findings.framework
    else:
        findings = list(report_or_findings)
        framework = framework or "pydantic-ai"
    result: list[QualityFinding] = []
    for finding in findings:
        action = _required_action_from_red_team(finding)
        result.append(
            QualityFinding(
                source_agent="RedTeam",
                framework=framework,
                source_id=finding.id,
                severity=_severity_from_red_team(finding.severity),
                issue_type=finding.finding_type,
                competitor_id=finding.competitor_id,
                competitor_name=finding.competitor_name,
                dimension=finding.dimension,
                report_section=_report_section_for_finding(
                    finding.finding_type,
                    finding.dimension,
                ),
                claim_ids=finding.claim_ids,
                evidence_ids=finding.evidence_ids,
                message=finding.message,
                recommendation=finding.recommendation,
                required_action=action,
                acceptance_rule=finding.recommendation or _acceptance_rule_for_action(action),
                redo_scope=_first_redo_scope(red_team_findings_to_redo_scopes([finding])),
            )
        )
    return result


def quality_findings_from_claim_validation(
    report_or_issues: ClaimValidationReport | Iterable[ClaimValidationIssue],
    *,
    framework: str = "deterministic-self-consistency",
) -> list[QualityFinding]:
    if isinstance(report_or_issues, ClaimValidationReport):
        issues = report_or_issues.issues
        results_by_claim = {item.claim_id: item for item in report_or_issues.results}
    else:
        issues = list(report_or_issues)
        results_by_claim = {}
    result: list[QualityFinding] = []
    for issue in issues:
        action = _required_action_from_claim_issue(issue)
        validation = results_by_claim.get(issue.claim_id)
        result.append(
            QualityFinding(
                source_agent="ClaimValidator",
                framework=framework,
                source_id=issue.id,
                severity=issue.severity,
                issue_type=issue.issue_type,
                field_path=f"claim.{issue.claim_id}.{issue.issue_type}",
                report_section=_report_section_for_finding(issue.issue_type, None),
                claim_ids=[issue.claim_id],
                evidence_ids=issue.evidence_ids,
                message=issue.message,
                recommendation=_claim_issue_recommendation(issue),
                required_action=action,
                acceptance_rule=_acceptance_rule_for_action(action),
                redo_scope=_first_redo_scope(claim_validation_issues_to_redo_scopes([issue])),
                metadata=_claim_validation_metadata(validation),
            )
        )
    return result


def quality_findings_from_quality_gaps(
    gaps: Iterable[QualityGap],
    *,
    source_agent: str = "ResearchPipeline",
    framework: str = "clean-research-pipeline",
) -> list[QualityFinding]:
    result: list[QualityFinding] = []
    for gap in gaps:
        action = _required_action_from_gap(gap)
        result.append(
            QualityFinding(
                source_agent=source_agent,
                framework=framework,
                source_id=gap.id,
                severity=gap.severity,
                issue_type=str(gap.suggested_action),
                competitor_name=gap.competitor,
                dimension=gap.dimension,
                field_path=gap.field,
                report_section=_report_section_for_finding(
                    str(gap.suggested_action),
                    gap.dimension,
                ),
                evidence_ids=gap.source_ids,
                message=gap.reason,
                recommendation=str(gap.suggested_action),
                required_action=action,
                acceptance_rule=gap.acceptance_rule,
                metadata=gap.metadata,
            )
        )
    return result


def quality_findings_from_evalops(report: EvalOpsReport) -> list[QualityFinding]:
    return [
        QualityFinding(
            source_agent="EvalOps",
            framework="deterministic-regression-gate",
            source_id=issue.id,
            severity=_severity_from_eval_status(issue.status),
            status="resolved" if issue.status == "pass" else "open",
            issue_type=issue.kind,
            report_section=_report_section_for_finding(issue.kind, None),
            message=issue.summary or issue.id,
            recommendation="Investigate the regression gate issue before publishing.",
            required_action="human_review" if issue.status != "pass" else "none",
            acceptance_rule="Regression gate returns pass.",
            metadata={
                "regression_gate_status": report.regression_gate_status,
                "regression_gate_reason": report.regression_gate_reason,
            },
        )
        for issue in report.regression_gate_issues
    ]


def _first_redo_scope(scopes: list[RedoScope]) -> RedoScope | None:
    return scopes[0] if scopes else None


def _required_action_from_redo(scope: RedoScope) -> QualityFindingRequiredAction:
    if scope.kind == "collector":
        return "add_evidence"
    if scope.kind == "analyst":
        return "rewrite_claim"
    if scope.kind == "writer_only":
        return "rewrite_report"
    if scope.kind in {"comparator", "full"}:
        return "rerun_scope"
    return "human_review"


def _required_action_from_business_rule(
    finding: BusinessQAFinding,
) -> QualityFindingRequiredAction:
    text = f"{finding.rule_id} {finding.message}".casefold()
    if "citation" in text or "report_structure" in text or "report_depth" in text:
        return "rewrite_report"
    if (
        "low_confidence" in text
        or "single_source" in text
        or "single-source" in text
        or "missing_evidence" in text
    ):
        return "add_evidence"
    if "weak_text_support" in text:
        return "rewrite_claim"
    if "strong_conclusion" in text or "weak_source" in text:
        return "downgrade_claim"
    if "run_qa_findings_unresolved" in text:
        return "rerun_scope"
    return "human_review"


def _required_action_from_red_team(
    finding: RedTeamFinding,
) -> QualityFindingRequiredAction:
    if finding.finding_type in {"weak_evidence", "stale_or_rejected_evidence"}:
        return "add_evidence"
    if finding.finding_type in {"unsupported_claim", "competitive_bias"}:
        return "rewrite_claim"
    if finding.finding_type == "report_risk":
        return "rewrite_report"
    return "human_review"


def _required_action_from_claim_issue(
    issue: ClaimValidationIssue,
) -> QualityFindingRequiredAction:
    if issue.issue_type in {
        "missing_evidence",
        "stale_or_rejected_evidence",
        "low_evidence_quality",
        "single_source_support",
    }:
        return "add_evidence"
    if issue.issue_type in {"weak_text_support", "low_self_consistency"}:
        return "rewrite_claim"
    if issue.issue_type == "low_confidence":
        return "downgrade_claim"
    return "human_review"


def _required_action_from_gap(gap: QualityGap) -> QualityFindingRequiredAction:
    required_action = gap.metadata.get("required_action")
    if isinstance(required_action, str):
        return _coerce_required_action(required_action)
    if gap.suggested_action in {
        "targeted_discovery",
        "pricing_model_repair",
        "feature_slot_repair",
        "persona_schema_repair",
    }:
        return "add_evidence"
    if gap.suggested_action == "mark_not_applicable":
        return "downgrade_claim"
    return "human_review"


def _coerce_required_action(action: str) -> QualityFindingRequiredAction:
    allowed = {
        "none",
        "add_evidence",
        "rewrite_claim",
        "downgrade_claim",
        "delete_claim",
        "rewrite_report",
        "rerun_scope",
        "human_review",
        "monitor",
    }
    return action if action in allowed else "human_review"  # type: ignore[return-value]


def _severity_from_gap(severity: str) -> QualityFindingSeverity:
    if severity == "critical":
        return "blocker"
    if severity in {"high", "medium"}:
        return "warn"
    return "info"


def _severity_from_red_team(severity: str) -> QualityFindingSeverity:
    if severity == "critical":
        return "blocker"
    if severity in {"high", "medium"}:
        return "warn"
    return "info"


def _severity_from_eval_status(status: str) -> QualityFindingSeverity:
    if status == "fail":
        return "blocker"
    if status == "warn":
        return "warn"
    return "info"


def _claim_issue_recommendation(issue: ClaimValidationIssue) -> str:
    if issue.issue_type in {
        "missing_evidence",
        "stale_or_rejected_evidence",
        "low_evidence_quality",
        "single_source_support",
    }:
        return "Collect stronger verified evidence or downgrade the claim."
    if issue.issue_type in {"weak_text_support", "low_self_consistency"}:
        return "Rewrite the claim so it is directly supported by cited evidence."
    if issue.issue_type == "low_confidence":
        return "Downgrade this claim or route it to human review."
    return "Review this claim before publishing."


def _claim_validation_metadata(
    validation: ClaimValidationResult | None,
) -> dict[str, object]:
    if validation is None:
        return {}
    return {
        "validation_status": validation.status,
        "risk_validation_status": validation.validation_status,
        "high_risk": validation.high_risk,
        "risk_reasons": validation.risk_reasons,
        "recommended_action": validation.recommended_action,
        "rationale": validation.rationale,
        "support_score": validation.support_score,
        "text_support_score": validation.text_support_score,
        "evidence_quality_score": validation.evidence_quality_score,
        "triangulation_score": validation.triangulation_score,
        "self_consistency_score": validation.self_consistency_score,
        "consistency_votes": validation.consistency_votes,
        "validation_samples": [
            sample.model_dump(mode="json") for sample in validation.validation_samples
        ],
    }


def _report_section_for_finding(issue_type: str, dimension: str | None) -> str:
    dimension_key = (dimension or "").casefold()
    issue_key = issue_type.casefold()
    if "pricing" in dimension_key:
        return "Pricing Analysis"
    if "feature" in dimension_key:
        return "Feature Matrix"
    if "persona" in dimension_key or "user" in dimension_key:
        return "Persona And Buyer Signals"
    if "citation" in issue_key or "source" in issue_key or "evidence" in issue_key:
        return "Evidence Appendix"
    if "claim" in issue_key or "consistency" in issue_key or "support" in issue_key:
        return "Claim Validation"
    if "report" in issue_key or "structure" in issue_key:
        return "Report Structure"
    if "regression" in issue_key or "metric" in issue_key:
        return "EvalOps"
    return "General Review"


def _acceptance_rule_for_action(action: QualityFindingRequiredAction) -> str:
    return {
        "none": "No follow-up action is required.",
        "add_evidence": "Accepted verified evidence supports the affected field or claim.",
        "rewrite_claim": "The claim text is rewritten to match cited evidence.",
        "downgrade_claim": "The report marks the claim as weak, caveated, or non-decisive.",
        "delete_claim": "The unsupported claim is removed from release scope.",
        "rewrite_report": "The affected report section is regenerated and source tokens resolve.",
        "rerun_scope": "Scoped redo completes and the finding is no longer blocking.",
        "human_review": "A reviewer records an explicit decision or follow-up.",
        "monitor": "The finding is tracked without blocking publication.",
    }[action]
