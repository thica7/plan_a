from __future__ import annotations

from packages.quality import (
    quality_findings_from_claim_validation,
    quality_findings_from_evalops,
    quality_findings_from_evidence_gaps,
    quality_findings_from_qc_issues,
    quality_findings_from_red_team,
    quality_findings_from_release_gate,
)
from packages.schema.enterprise import (
    BusinessQAEvaluation,
    BusinessQAFinding,
    ClaimValidationIssue,
    ClaimValidationReport,
    ClaimValidationResult,
    EvidenceGapItem,
    ProjectReadinessScore,
    RedTeamFinding,
    ReportReleaseGate,
)
from packages.schema.evals import EvalOpsRegressionGateIssue, EvalOpsReport
from packages.schema.models import QCIssue, RedoScope


def test_qc_issue_becomes_unified_quality_finding() -> None:
    issue = QCIssue(
        id="qa-collector-1",
        severity="blocker",
        detected_by="coverage",
        target_agent="collector",
        target_subagent="pricing",
        target_competitor="Cursor",
        field_path="raw_sources[pricing]",
        problem="Cursor pricing lacks verified evidence.",
        redo_scope=RedoScope(
            kind="collector",
            target_subagent="pricing",
            target_competitor="Cursor",
            target_competitors=["Cursor"],
            rationale="Collect official Cursor pricing evidence.",
        ),
    )

    findings = quality_findings_from_qc_issues([issue])

    assert len(findings) == 1
    finding = findings[0]
    assert finding.source_agent == "RuntimeQA"
    assert finding.source_id == issue.id
    assert finding.severity == "blocker"
    assert finding.competitor_name == "Cursor"
    assert finding.dimension == "pricing"
    assert finding.field_path == "raw_sources[pricing]"
    assert finding.report_section == "Pricing Analysis"
    assert finding.required_action == "add_evidence"
    assert finding.repairable is True
    assert finding.redo_scope == issue.redo_scope


def test_release_gate_finding_preserves_claim_evidence_and_action() -> None:
    issue = BusinessQAFinding(
        id="release-issue-1",
        rule_id="claim_self_consistency_required",
        rule_name="Claim self consistency required",
        severity="warn",
        competitor_id="competitor-1",
        competitor_name="Cursor",
        dimension="pricing",
        message="Single-source support is too weak for a high-risk pricing claim.",
        evidence_ids=["evidence-1"],
        claim_ids=["claim-1"],
        recommendation="Collect another independent verified source.",
    )
    gate = ReportReleaseGate(
        report_version_id="version-1",
        workspace_id="workspace-1",
        project_id="project-1",
        allowed=True,
        status="pass",
        readiness=ProjectReadinessScore(
            project_id="project-1",
            score=91,
            risk_level="ready",
            evidence_score=90,
            claim_score=90,
            coverage_score=90,
            qa_score=94,
            summary="Ready with warnings.",
        ),
        qa_evaluation=BusinessQAEvaluation(
            project_id="project-1",
            scenario_id="l1_pricing_pack",
            competitor_layer="L1",
        ),
        issue_count=1,
        blocker_count=0,
        warn_count=1,
        issues=[issue],
    )

    findings = quality_findings_from_release_gate(gate)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.source_agent == "ReleaseGate"
    assert finding.framework == "enterprise-release-gate"
    assert finding.issue_type == "claim_self_consistency_required"
    assert finding.claim_ids == ["claim-1"]
    assert finding.evidence_ids == ["evidence-1"]
    assert finding.report_section == "Pricing Analysis"
    assert finding.required_action == "add_evidence"
    assert finding.repairable is True
    assert finding.redo_scope is not None


def test_evidence_gap_and_red_team_findings_share_contract() -> None:
    gap = EvidenceGapItem(
        id="gap-1",
        severity="high",
        gap_type="missing_verified_source",
        competitor_id="competitor-1",
        competitor_name="Cursor",
        dimension="feature",
        source_type_required="webpage_verified",
        message="Cursor feature evidence needs a verified source.",
        recommended_query="Cursor feature official docs",
        evidence_ids=["evidence-1"],
    )
    red_team = RedTeamFinding(
        id="red-1",
        severity="critical",
        finding_type="unsupported_claim",
        competitor_id="competitor-1",
        competitor_name="Cursor",
        dimension="feature",
        message="A feature claim is unsupported.",
        recommendation="Attach evidence or remove the claim.",
        claim_ids=["claim-1"],
    )

    gap_finding = quality_findings_from_evidence_gaps([gap])[0]
    red_finding = quality_findings_from_red_team([red_team])[0]

    assert gap_finding.source_agent == "EvidenceGap"
    assert gap_finding.severity == "warn"
    assert gap_finding.report_section == "Feature Matrix"
    assert gap_finding.required_action == "add_evidence"
    assert gap_finding.repairable is True
    assert gap_finding.redo_scope is not None
    assert red_finding.source_agent == "RedTeam"
    assert red_finding.severity == "blocker"
    assert red_finding.report_section == "Feature Matrix"
    assert red_finding.required_action == "rewrite_claim"
    assert red_finding.repairable is True
    assert red_finding.claim_ids == ["claim-1"]


def test_claim_validation_finding_carries_scores_and_samples() -> None:
    issue = ClaimValidationIssue(
        id="claim-validation-issue-1",
        claim_id="claim-1",
        severity="warn",
        issue_type="weak_text_support",
        message="Evidence text weakly supports the claim.",
        evidence_ids=["evidence-1"],
    )
    report = ClaimValidationReport(
        project_id="project-1",
        total_claims=1,
        weak_count=1,
        issue_count=1,
        warn_count=1,
        self_consistency_score=52,
        results=[
            ClaimValidationResult(
                claim_id="claim-1",
                status="weak",
                validation_status="weak_support",
                high_risk=True,
                risk_reasons=["matched:enterprise-ready"],
                recommended_action="downgrade_claim",
                rationale="High-risk claim validation status is weak_support.",
                support_score=52,
                text_support_score=38,
                evidence_quality_score=80,
                triangulation_score=70,
                self_consistency_score=52,
                consistency_votes={"text_support": 0, "evidence_quality": 1},
                usable_evidence_ids=["evidence-1"],
                issue_ids=[issue.id],
            )
        ],
        issues=[issue],
    )

    findings = quality_findings_from_claim_validation(report)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.source_agent == "ClaimValidator"
    assert finding.required_action == "rewrite_claim"
    assert finding.repairable is True
    assert finding.report_section == "Claim Validation"
    assert finding.claim_ids == ["claim-1"]
    assert finding.evidence_ids == ["evidence-1"]
    assert finding.metadata["validation_status"] == "weak"
    assert finding.metadata["risk_validation_status"] == "weak_support"
    assert finding.metadata["high_risk"] is True
    assert finding.metadata["recommended_action"] == "downgrade_claim"
    assert finding.metadata["text_support_score"] == 38


def test_evalops_regression_issue_uses_quality_finding_contract() -> None:
    report = EvalOpsReport(
        run_count=1,
        evaluated_run_ids=["run-1"],
        real_run_count=1,
        demo_run_count=0,
        real_run_ratio=1.0,
        real_quality_chain_rate=0.8,
        regressed_run_count=1,
        hitl_enabled_run_rate=0.0,
        human_correction_rate=0.0,
        redo_iteration_count=0,
        redo_convergence_ratio=1.0,
        golden_set_size=30,
        golden_set_pass_rate=0.9,
        report_quality_score=88,
        source_recall=0.8,
        manual_baseline_hours_per_report=6.0,
        manual_baseline_hours=6.0,
        automation_runtime_hours=0.2,
        manual_time_saved_hours=5.8,
        task_time_saved_hours=5.8,
        time_savings_rate=0.96,
        cost_per_report_usd=1.2,
        regression_gate_status="warn",
        regression_gate_reason="Report quality regressed against baseline.",
        regression_gate_issues=[
            EvalOpsRegressionGateIssue(
                kind="metric",
                id="report_quality_score",
                status="warn",
                summary="Report quality score dropped below target.",
            )
        ],
    )

    finding = quality_findings_from_evalops(report)[0]

    assert finding.source_agent == "EvalOps"
    assert finding.severity == "warn"
    assert finding.status == "open"
    assert finding.report_section == "EvalOps"
    assert finding.required_action == "human_review"
    assert finding.repairable is False
    assert finding.metadata["regression_gate_status"] == "warn"
