from __future__ import annotations

from packages.quality import (
    quality_findings_from_claim_validation,
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
    assert finding.required_action == "add_evidence"
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
    assert finding.required_action == "add_evidence"
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
    assert gap_finding.required_action == "add_evidence"
    assert gap_finding.redo_scope is not None
    assert red_finding.source_agent == "RedTeam"
    assert red_finding.severity == "blocker"
    assert red_finding.required_action == "rewrite_claim"
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
    assert finding.claim_ids == ["claim-1"]
    assert finding.evidence_ids == ["evidence-1"]
    assert finding.metadata["validation_status"] == "weak"
    assert finding.metadata["text_support_score"] == 38
