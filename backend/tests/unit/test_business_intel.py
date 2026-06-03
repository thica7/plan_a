import packages.agents.pydantic_ai_adapter as pydantic_ai_adapter
from packages.agents.executor import AgentExecutionRequest
from packages.business_intel import (
    analyze_evidence_gaps,
    analyze_red_team,
    build_business_intel_plan,
    build_evidence_gap_agent,
    build_red_team_agent,
    business_findings_to_redo_scopes,
    claim_validation_issues_to_redo_scopes,
    evaluate_business_qa,
    evaluate_report_release_gate,
    evidence_gaps_to_redo_scopes,
    generate_dynamic_scenario_pack,
    list_business_qa_rules,
    list_scenario_packs,
    red_team_findings_to_redo_scopes,
    score_competitors,
    score_project_readiness,
    validate_project_claims,
)
from packages.business_intel.homepage import verify_homepage
from packages.business_intel.layers import assess_competitor_layer
from packages.schema.enterprise import (
    BusinessQAEvaluation,
    BusinessQAFinding,
    ClaimRecord,
    ClaimValidationIssue,
    CompetitorRecord,
    EvidenceGapItem,
    EvidenceRecord,
    ProjectRecord,
    RedTeamFinding,
    ReportVersionRecord,
    SourceRegistryRecord,
)
from packages.skills.registry import SkillRegistry


def test_layer_assessment_prefers_direct_for_focused_pricing_comparison() -> None:
    assessment = assess_competitor_layer(
        topic="Cursor vs Copilot pricing battlecard",
        competitors=["Cursor", "Copilot"],
        dimensions=["pricing", "feature"],
    )

    assert assessment.layer == "L1"
    assert assessment.confidence >= 0.55
    assert "pricing_dimension" in assessment.signals


def test_layer_assessment_detects_market_landscape() -> None:
    assessment = assess_competitor_layer(
        topic="AI coding assistant market landscape",
        competitors=["Cursor", "Copilot", "Windsurf", "Tabnine", "Codeium"],
        dimensions=["market", "persona"],
    )

    assert assessment.layer == "L3"
    assert "many_competitors" in assessment.signals


def test_business_plan_selects_scenario_and_rules() -> None:
    plan = build_business_intel_plan(
        topic="Enterprise AI assistant security review",
        competitors=["A", "B"],
        dimensions=["security"],
    )

    assert plan.competitor_layer.layer in {"L1", "L2"}
    assert plan.scenario_pack.id == "enterprise_risk_review"
    assert "security" in plan.recommended_dimensions
    assert {rule.id for rule in plan.qa_rules} >= {
        "coverage_min_verified",
        "security_official_source",
    }


def test_scenario_pack_catalog_and_qa_rules_are_loaded() -> None:
    packs = list_scenario_packs()
    rules = list_business_qa_rules()
    packs_by_id = {pack.id: pack for pack in packs}

    assert len(packs) >= 5
    assert len(rules) == 8
    assert {"l1_direct_battlecard", "l2_adjacent_workflow", "l3_market_landscape"} <= set(
        packs_by_id
    )
    assert packs_by_id["l1_direct_battlecard"].competitor_layer == "L1"
    assert packs_by_id["l2_adjacent_workflow"].competitor_layer == "L2"
    assert packs_by_id["l3_market_landscape"].competitor_layer == "L3"
    assert all(packs_by_id[item].required_dimensions for item in packs_by_id)
    assert all(packs_by_id[item].seed_competitors for item in packs_by_id)
    assert any(rule.id == "claim_has_evidence" for rule in rules)
    assert any(rule.id == "homepage_verified" for rule in rules)


def test_scenario_pack_required_dimensions_have_registered_skills() -> None:
    registered_dimensions = set(SkillRegistry.from_default_path().names())

    missing = {
        f"{pack.id}:{dimension}"
        for pack in list_scenario_packs()
        for dimension in pack.required_dimensions
        if dimension not in registered_dimensions
    }

    assert not missing


def test_l1_l2_l3_presets_build_complete_business_plans() -> None:
    cases = [
        (
            "l1_direct_battlecard",
            "Cursor vs Copilot battlecard",
            ["Cursor", "Copilot"],
            ["pricing", "feature"],
            "L1",
        ),
        (
            "l2_adjacent_workflow",
            "Enterprise AI search workflow alternatives",
            ["Glean", "Coveo", "Elastic"],
            ["feature", "integrations"],
            "L2",
        ),
        (
            "l3_market_landscape",
            "AI coding assistant market landscape",
            ["Cursor", "Copilot", "Windsurf", "Tabnine", "Codeium"],
            ["market", "persona"],
            "L3",
        ),
    ]

    for scenario_id, topic, competitors, dimensions, layer in cases:
        plan = build_business_intel_plan(
            topic=topic,
            competitors=competitors,
            dimensions=dimensions,
            requested_layer=layer,
            requested_scenario_id=scenario_id,
        )

        assert plan.scenario_pack.id == scenario_id
        assert plan.competitor_layer.layer == layer
        assert set(plan.scenario_pack.required_dimensions) <= set(plan.recommended_dimensions)
        assert plan.qa_rules


def test_dynamic_scenario_pack_and_homepage_gate_are_deterministic() -> None:
    pack = generate_dynamic_scenario_pack(
        topic="AI meeting assistant landscape",
        competitors=["Fathom", "Otter", "Fireflies", "Avoma"],
        dimensions=["market"],
    )
    good = verify_homepage("Cursor")
    phantom = verify_homepage("FAKE_PRODUCT_NOT_EXISTS")

    assert pack.is_dynamic is True
    assert pack.competitor_layer == "L3"
    assert pack.seed_competitors == ["Fathom", "Otter", "Fireflies", "Avoma"]
    assert "market" in pack.required_dimensions
    assert good.verified is True
    assert phantom.verified is False
    assert phantom.reason == "phantom_name"


def test_dynamic_schema_dimensions_drive_quality_risk_and_scoring() -> None:
    plan = build_business_intel_plan(
        topic="Cursor vs Copilot enterprise battlecard",
        competitors=["Cursor"],
        dimensions=["pricing", "enterprise_sso"],
        requested_layer="L1",
        requested_scenario_id="l1_direct_battlecard",
    )
    competitor = _competitor()
    evidence = [
        EvidenceRecord(
            id="evidence-pricing",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="pricing-1",
            competitor_id=competitor.id,
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing",
            url="https://cursor.sh/pricing",
            snippet="Cursor publishes pricing.",
            content_hash="hash-pricing",
            reliability_score=0.9,
            quality_label="accepted",
        )
    ]
    claims: list[ClaimRecord] = []

    evaluation = evaluate_business_qa(
        project_id="project-1",
        plan=plan,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )
    red_team = analyze_red_team(
        project_id="project-1",
        plan=plan,
        qa_evaluation=evaluation,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
        report_versions=[_report_version(evidence_ids=["evidence-pricing"])],
    )
    score_report = score_competitors(
        project_id="project-1",
        plan=plan,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )

    assert "enterprise_sso" in plan.requested_dimensions
    assert any(
        finding.rule_id == "coverage_min_verified"
        and finding.dimension == "enterprise_sso"
        for finding in evaluation.findings
    )
    assert any(
        finding.finding_type == "competitive_bias"
        and "enterprise_sso" in (finding.dimension or "")
        for finding in red_team.findings
    )
    assert any(
        score.dimension == "enterprise_sso"
        for score in score_report.scores[0].dimension_scores
    )


def test_business_qa_evaluator_passes_verified_pricing_pack() -> None:
    plan = build_business_intel_plan(
        topic="Cursor vs Copilot pricing comparison",
        competitors=["Cursor"],
        dimensions=["pricing"],
        requested_scenario_id="l1_pricing_pack",
    )
    competitor = _competitor()
    evidence = [
        EvidenceRecord(
            id="evidence-1",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="pricing-1",
            competitor_id=competitor.id,
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing",
            url="https://cursor.sh/pricing",
            snippet="Cursor publishes pricing.",
            content_hash="hash-1",
            reliability_score=0.9,
            quality_label="accepted",
        )
    ]
    claims = [
        ClaimRecord(
            id="claim-1",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id=competitor.id,
            claim_type="pricing",
            claim_text="Cursor publishes pricing.",
            evidence_ids=["evidence-1"],
            confidence=0.9,
        )
    ]

    evaluation = evaluate_business_qa(
        project_id="project-1",
        plan=plan,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )
    gaps = analyze_evidence_gaps(
        project_id="project-1",
        plan=plan,
        qa_evaluation=evaluation,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )
    readiness = score_project_readiness(
        project_id="project-1",
        plan=plan,
        qa_evaluation=evaluation,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )

    assert evaluation.finding_count == 0
    assert gaps.gap_count == 0
    assert evaluation.passed_rules == evaluation.total_rules
    assert readiness.risk_level == "ready"
    assert readiness.score >= 85
    assert readiness.recommendations[0].action_type == "approve_report"


def test_evidence_gaps_generate_pending_schema_suggestions_for_new_dimensions() -> None:
    plan = build_business_intel_plan(
        topic="Cursor vs Copilot pricing battlecard",
        competitors=["Cursor", "Copilot"],
        dimensions=["pricing"],
        requested_scenario_id="l1_pricing_pack",
    )
    qa_evaluation = BusinessQAEvaluation(
        project_id="project-1",
        scenario_id=plan.scenario_pack.id,
        competitor_layer=plan.competitor_layer.layer,
        total_rules=1,
        warn_count=2,
        finding_count=2,
        findings=[
            BusinessQAFinding(
                id="qa-compliance-cursor",
                severity="warn",
                rule_id="emergent_dimension",
                rule_name="Emergent dimension",
                message="Cursor needs compliance evidence.",
                recommendation="Collect official compliance evidence.",
                competitor_id="competitor-cursor",
                competitor_name="Cursor",
                dimension="compliance",
            ),
            BusinessQAFinding(
                id="qa-compliance-copilot",
                severity="warn",
                rule_id="emergent_dimension",
                rule_name="Emergent dimension",
                message="Copilot needs compliance evidence.",
                recommendation="Collect official compliance evidence.",
                competitor_id="competitor-copilot",
                competitor_name="Copilot",
                dimension="compliance",
            ),
        ],
    )

    report = analyze_evidence_gaps(
        project_id="project-1",
        plan=plan,
        qa_evaluation=qa_evaluation,
        competitors=[],
        evidence=[],
        claims=[],
    )

    assert len(report.schema_suggestions) == 1
    suggestion = report.schema_suggestions[0]
    assert suggestion.status == "pending_review"
    assert suggestion.normalized_dimension == "compliance"
    assert suggestion.source_gap_ids
    assert suggestion.proposed_skill.name == "compliance"
    assert suggestion.proposed_skill.output.required_dimension == "compliance"
    assert "fetch_page" in suggestion.proposed_skill.tools_allowlist


def test_report_release_gate_requires_clean_qa_and_verified_evidence() -> None:
    competitor = _competitor()
    evidence = [
        EvidenceRecord(
            id="evidence-1",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="pricing-1",
            competitor_id=competitor.id,
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing",
            url="https://cursor.sh/pricing",
            snippet="Cursor publishes pricing.",
            content_hash="hash-1",
            reliability_score=0.9,
            quality_label="accepted",
        )
    ]
    claims = [
        ClaimRecord(
            id="claim-1",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id=competitor.id,
            claim_type="pricing",
            claim_text="Cursor publishes pricing.",
            evidence_ids=["evidence-1"],
            confidence=0.9,
        )
    ]
    report = ReportVersionRecord(
        id="report-1",
        workspace_id="workspace-1",
        project_id="project-1",
        version_number=1,
        topic_normalized="cursor-pricing",
        competitor_layer="L1",
        competitor_set_hash="hash",
        report_md=_structured_release_report(),
        claim_ids=["claim-1"],
        evidence_ids=["evidence-1"],
    )
    project = ProjectRecord(
        id="project-1",
        workspace_id="workspace-1",
        name="Cursor pricing",
        topic="Cursor vs Copilot pricing comparison",
        topic_normalized="cursor-pricing",
        competitor_layer="L1",
        competitor_set_hash="hash",
        scenario_id="l1_pricing_pack",
    )

    passing = evaluate_report_release_gate(
        project=project,
        report_version=report,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )
    blocked = evaluate_report_release_gate(
        project=project,
        report_version=report,
        competitors=[competitor],
        evidence=[evidence[0].model_copy(update={"quality_label": "stale"})],
        claims=claims,
    )

    assert passing.allowed is True
    assert passing.status == "pass"
    assert blocked.allowed is False
    assert blocked.status == "blocked"
    assert {issue.rule_id for issue in blocked.issues} >= {
        "business_qa_clean_required",
        "verified_evidence_rate",
    }


def test_report_release_gate_blocks_pending_source_policy_review() -> None:
    competitor = _competitor()
    evidence = [
        EvidenceRecord(
            id="evidence-1",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="pricing-1",
            competitor_id=competitor.id,
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing",
            url="https://cursor.sh/pricing",
            snippet="Cursor publishes pricing.",
            content_hash="hash-1",
            reliability_score=0.9,
            quality_label="accepted",
            metadata={
                "policy_review_status": "pending",
                "policy_review_reason": "Source Registry review queue requires approval.",
            },
        )
    ]
    claims = [
        ClaimRecord(
            id="claim-1",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id=competitor.id,
            claim_type="pricing",
            claim_text="Cursor publishes pricing.",
            evidence_ids=["evidence-1"],
            confidence=0.9,
        )
    ]
    report = ReportVersionRecord(
        id="report-1",
        workspace_id="workspace-1",
        project_id="project-1",
        version_number=1,
        topic_normalized="cursor-pricing",
        competitor_layer="L1",
        competitor_set_hash="hash",
        report_md=_structured_release_report(),
        claim_ids=["claim-1"],
        evidence_ids=["evidence-1"],
    )

    gate = evaluate_report_release_gate(
        project=_project(),
        report_version=report,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )

    assert gate.allowed is False
    assert "source_policy_review_required" in {issue.rule_id for issue in gate.issues}


def test_report_release_gate_uses_source_registry_review_status() -> None:
    competitor = _competitor()
    evidence = [
        EvidenceRecord(
            id="evidence-1",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="pricing-1",
            competitor_id=competitor.id,
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing",
            url="https://cursor.sh/pricing",
            snippet="Cursor publishes pricing.",
            content_hash="hash-1",
            reliability_score=0.9,
            quality_label="accepted",
        )
    ]
    claims = [
        ClaimRecord(
            id="claim-1",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id=competitor.id,
            claim_type="pricing",
            claim_text="Cursor publishes pricing.",
            evidence_ids=["evidence-1"],
            confidence=0.9,
        )
    ]
    source_registry = [
        SourceRegistryRecord(
            id="source-1",
            workspace_id="workspace-1",
            domain="cursor.sh",
            source_type="webpage_verified",
            display_name="Cursor",
            homepage_url="https://cursor.sh",
            trust_level="verified",
            robots_status="allowed",
            policy_review_status="pending",
            policy_review_reason="Legal review required before publication.",
        )
    ]

    gate = evaluate_report_release_gate(
        project=_project(),
        report_version=_report_version(evidence_ids=["evidence-1"]),
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
        source_registry=source_registry,
    )

    assert gate.allowed is False
    assert "source_policy_review_required" in {issue.rule_id for issue in gate.issues}


def test_report_release_gate_blocks_rejected_report_status() -> None:
    competitor = _competitor()
    evidence = [
        EvidenceRecord(
            id="evidence-1",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="pricing-1",
            competitor_id=competitor.id,
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing",
            url="https://cursor.sh/pricing",
            snippet="Cursor publishes pricing.",
            content_hash="hash-1",
            reliability_score=0.9,
            quality_label="accepted",
        )
    ]
    claims = [
        ClaimRecord(
            id="claim-1",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id=competitor.id,
            claim_type="pricing",
            claim_text="Cursor publishes pricing.",
            evidence_ids=["evidence-1"],
            confidence=0.9,
        )
    ]
    report = _report_version().model_copy(update={"status": "rejected"})

    gate = evaluate_report_release_gate(
        project=_project(),
        report_version=report,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )

    assert gate.allowed is False
    assert "report_status_releasable" in {issue.rule_id for issue in gate.issues}


def test_report_release_gate_blocks_unstructured_report() -> None:
    competitor = _competitor()
    evidence = [
        EvidenceRecord(
            id="evidence-1",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="pricing-1",
            competitor_id=competitor.id,
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing",
            url="https://cursor.sh/pricing",
            snippet="Cursor publishes pricing.",
            content_hash="hash-1",
            reliability_score=0.9,
            quality_label="accepted",
        )
    ]
    claims = [
        ClaimRecord(
            id="claim-1",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id=competitor.id,
            claim_type="pricing",
            claim_text="Cursor publishes pricing.",
            evidence_ids=["evidence-1"],
            confidence=0.9,
        )
    ]
    report = _report_version(report_md="Cursor publishes pricing. [source:evidence-1]")

    gate = evaluate_report_release_gate(
        project=_project(),
        report_version=report,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )

    assert gate.allowed is False
    assert "report_structure_required" in {issue.rule_id for issue in gate.issues}


def test_report_release_gate_blocks_structured_but_thin_report() -> None:
    competitor = _competitor()
    evidence = [
        EvidenceRecord(
            id="evidence-1",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="pricing-1",
            competitor_id=competitor.id,
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing",
            url="https://cursor.sh/pricing",
            snippet="Cursor publishes pricing.",
            content_hash="hash-1",
            reliability_score=0.9,
            quality_label="accepted",
        )
    ]
    claims = [
        ClaimRecord(
            id="claim-1",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id=competitor.id,
            claim_type="pricing",
            claim_text="Cursor publishes pricing.",
            evidence_ids=["evidence-1"],
            confidence=0.9,
        )
    ]
    thin_structured = """
# Cursor Direct Battlecard

## Executive Summary
Cursor publishes pricing. [source:evidence-1]

## Source Quality & Coverage
Accepted pricing source. [source:evidence-1]

## Side-by-Side Decision Matrix
| Dimension | Cursor |
| --- | --- |
| Pricing | Published. [source:evidence-1] |

## Battlecard
Pricing is visible. [source:evidence-1]

## Claim Validation & Evidence Risk
Claim is backed. [source:evidence-1]

## Next Collection / Verification Plan
Collect feature evidence next. [source:evidence-1]

## Evidence Appendix
- evidence-1. [source:evidence-1]
""".strip()
    report = _report_version(report_md=thin_structured)

    gate = evaluate_report_release_gate(
        project=_project(),
        report_version=report,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )
    rule_ids = {issue.rule_id for issue in gate.issues}

    assert len(thin_structured) < 900
    assert gate.allowed is False
    assert "report_depth_required" in rule_ids
    assert "report_structure_required" not in rule_ids


def test_claim_validator_cross_checks_evidence_support() -> None:
    competitor = _competitor()
    accepted = EvidenceRecord(
        id="evidence-1",
        workspace_id="workspace-1",
        project_id="project-1",
        raw_source_id="pricing-1",
        competitor_id=competitor.id,
        dimension="pricing",
        source_type="webpage_verified",
        title="Cursor pricing",
        url="https://cursor.sh/pricing",
        snippet="Cursor publishes pricing tiers for teams.",
        content_hash="hash-1",
        reliability_score=0.9,
        quality_label="accepted",
    )
    stale = accepted.model_copy(
        update={"id": "evidence-stale", "quality_label": "stale", "content_hash": "hash-stale"}
    )
    claims = [
        ClaimRecord(
            id="claim-supported",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id=competitor.id,
            claim_type="pricing",
            claim_text="Cursor publishes pricing tiers.",
            evidence_ids=["evidence-1"],
            confidence=0.9,
        ),
        ClaimRecord(
            id="claim-blocked",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id=competitor.id,
            claim_type="pricing",
            claim_text="Cursor has unpublished discounts.",
            evidence_ids=["evidence-stale"],
            confidence=0.9,
        ),
        ClaimRecord(
            id="claim-weak",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id=competitor.id,
            claim_type="feature",
            claim_text="Cursor dominates enterprise procurement.",
            evidence_ids=["evidence-1"],
            confidence=0.4,
        ),
    ]

    report = validate_project_claims(
        project_id="project-1",
        claims=claims,
        evidence=[accepted, stale],
    )

    statuses = {item.claim_id: item.status for item in report.results}
    supported = next(item for item in report.results if item.claim_id == "claim-supported")
    weak = next(item for item in report.results if item.claim_id == "claim-weak")
    assert statuses["claim-supported"] == "supported"
    assert statuses["claim-blocked"] == "blocked"
    assert statuses["claim-weak"] in {"weak", "unsupported"}
    assert supported.self_consistency_score >= 80
    assert supported.consistency_votes == {
        "text_support": 1,
        "evidence_quality": 1,
        "triangulation": 1,
    }
    assert [sample.checker for sample in supported.validation_samples] == [
        "text_support",
        "evidence_quality",
        "triangulation",
    ]
    assert all(sample.vote == "pass" for sample in supported.validation_samples)
    assert supported.validation_samples[0].evidence_ids == ["evidence-1"]
    assert weak.self_consistency_score < supported.self_consistency_score
    assert weak.triangulation_score == 70
    assert any(sample.vote == "fail" for sample in weak.validation_samples)
    assert report.self_consistency_score >= 70
    assert report.blocker_count == 1
    assert report.warn_count >= 1


def test_report_release_gate_warns_on_high_risk_single_source_claim() -> None:
    competitor = _competitor()
    evidence = [
        EvidenceRecord(
            id="evidence-security-1",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="security-1",
            competitor_id=competitor.id,
            dimension="security",
            source_type="webpage_verified",
            title="Cursor security",
            url="https://cursor.sh/security",
            snippet="Cursor documents SSO, audit logs, and SOC 2 controls.",
            content_hash="hash-security",
            reliability_score=0.9,
            quality_label="accepted",
        )
    ]
    claims = [
        ClaimRecord(
            id="claim-security",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id=competitor.id,
            claim_type="security",
            claim_text="Cursor has SOC 2, SSO, and audit log controls.",
            evidence_ids=["evidence-security-1"],
            confidence=0.9,
        )
    ]
    report = _report_version(
        evidence_ids=["evidence-security-1"],
        claim_ids=["claim-security"],
        report_md=(
            "# Report\n\nCursor has SOC 2, SSO, and audit log controls "
            "[source:evidence-security-1]."
        ),
    )

    gate = evaluate_report_release_gate(
        project=_project(),
        report_version=report,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )

    assert gate.allowed is False
    consistency_issues = [
        issue for issue in gate.issues if issue.rule_id == "claim_self_consistency_required"
    ]
    assert consistency_issues
    assert consistency_issues[0].severity == "warn"
    assert "single_source_support" in consistency_issues[0].message
    assert "listed claim-validation issue types" in consistency_issues[0].recommendation


def test_report_release_gate_blocks_unresolved_run_qa_metadata() -> None:
    competitor = _competitor()
    evidence = [
        EvidenceRecord(
            id="evidence-1",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="pricing-1",
            competitor_id=competitor.id,
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing",
            url="https://cursor.sh/pricing",
            snippet="Cursor publishes pricing.",
            content_hash="hash-1",
            reliability_score=0.9,
            quality_label="accepted",
        )
    ]
    claims = [
        ClaimRecord(
            id="claim-1",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id=competitor.id,
            claim_type="pricing",
            claim_text="Cursor publishes pricing.",
            evidence_ids=["evidence-1"],
            confidence=0.9,
        )
    ]
    report = _report_version(
        quality_metadata={
            "run_qa_findings": [
                {
                    "id": "qa-1",
                    "severity": "warn",
                    "problem": "No granular pricing comparison.",
                }
            ]
        }
    )
    project = _project()

    gate = evaluate_report_release_gate(
        project=project,
        report_version=report,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )

    assert gate.allowed is False
    assert "run_qa_findings_unresolved" in {issue.rule_id for issue in gate.issues}


def test_report_release_gate_blocks_failed_schema_metadata() -> None:
    competitor = _competitor()
    evidence = [
        EvidenceRecord(
            id="evidence-1",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="pricing-1",
            competitor_id=competitor.id,
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing",
            url="https://cursor.sh/pricing",
            snippet="Cursor publishes pricing.",
            content_hash="hash-1",
            reliability_score=0.9,
            quality_label="accepted",
        )
    ]
    claims = [
        ClaimRecord(
            id="claim-1",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id=competitor.id,
            claim_type="pricing",
            claim_text="Cursor publishes pricing.",
            evidence_ids=["evidence-1"],
            confidence=0.9,
        )
    ]
    report = _report_version(quality_metadata={"schema_pass_rate": 0.5})

    gate = evaluate_report_release_gate(
        project=_project(),
        report_version=report,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )

    assert gate.allowed is False
    assert "run_schema_validation_failed" in {issue.rule_id for issue in gate.issues}


def test_report_release_gate_blocks_unclosed_rag_gap_fill_chain() -> None:
    competitor = _competitor()
    evidence = [
        EvidenceRecord(
            id="evidence-1",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="pricing-1",
            competitor_id=competitor.id,
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing",
            url="https://cursor.sh/pricing",
            snippet="Cursor publishes pricing.",
            content_hash="hash-1",
            reliability_score=0.9,
            quality_label="accepted",
        )
    ]
    claims = [
        ClaimRecord(
            id="claim-1",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id=competitor.id,
            claim_type="pricing",
            claim_text="Cursor publishes pricing.",
            evidence_ids=["evidence-1"],
            confidence=0.9,
        )
    ]
    report = _report_version(
        quality_metadata={
            "rag_gap_fill": {
                "before_gap_count": 2,
                "after_gap_count": 1,
                "gap_fill_chain_closed": False,
                "unfilled_gap_ids": ["gap-security"],
                "gap_evidence_links": {},
            }
        }
    )

    gate = evaluate_report_release_gate(
        project=_project(),
        report_version=report,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )

    assert gate.allowed is False
    issues = {issue.rule_id: issue for issue in gate.issues}
    assert "rag_gap_fill_chain_unclosed" in issues
    assert "gap-security" in issues["rag_gap_fill_chain_unclosed"].message


def test_report_release_gate_reads_remaining_gap_ids_from_gap_fill_metadata() -> None:
    competitor = _competitor()
    report = _report_version(
        quality_metadata={
            "rag_gap_fill": {
                "before_gap_count": 2,
                "after_gap_count": 1,
                "gap_fill_chain_closed": False,
                "remaining_gap_ids": ["gap-pricing"],
                "gap_evidence_links": {},
            }
        }
    )

    gate = evaluate_report_release_gate(
        project=_project(),
        report_version=report,
        competitors=[competitor],
        evidence=[],
        claims=[],
    )

    issues = {issue.rule_id: issue for issue in gate.issues}
    assert "rag_gap_fill_chain_unclosed" in issues
    assert "gap-pricing" in issues["rag_gap_fill_chain_unclosed"].message


def test_report_release_gate_allows_closed_rag_gap_fill_chain() -> None:
    competitor = _competitor()
    evidence = [
        EvidenceRecord(
            id="evidence-1",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="pricing-1",
            competitor_id=competitor.id,
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing",
            url="https://cursor.sh/pricing",
            snippet="Cursor publishes pricing.",
            content_hash="hash-1",
            reliability_score=0.9,
            quality_label="accepted",
        )
    ]
    claims = [
        ClaimRecord(
            id="claim-1",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id=competitor.id,
            claim_type="pricing",
            claim_text="Cursor publishes pricing.",
            evidence_ids=["evidence-1"],
            confidence=0.9,
        )
    ]
    report = _report_version(
        quality_metadata={
            "rag_gap_fill": {
                "before_gap_count": 1,
                "after_gap_count": 0,
                "gap_fill_chain_closed": True,
                "filled_gap_ids": ["gap-pricing"],
                "gap_evidence_links": {"gap-pricing": ["evidence-1"]},
            }
        }
    )

    gate = evaluate_report_release_gate(
        project=_project(),
        report_version=report,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )

    assert "rag_gap_fill_chain_unclosed" not in {issue.rule_id for issue in gate.issues}


def test_report_release_gate_blocks_strong_conclusion_from_search_only_source() -> None:
    competitor = _competitor()
    evidence = [
        EvidenceRecord(
            id="evidence-1",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="pricing-1",
            competitor_id=competitor.id,
            dimension="pricing",
            source_type="web_search_result",
            title="Cursor pricing search result",
            url="https://example.com/pricing",
            snippet="Search result summary.",
            content_hash="hash-1",
            reliability_score=0.68,
            quality_label="unreviewed",
        )
    ]
    claims = [
        ClaimRecord(
            id="claim-1",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id=competitor.id,
            claim_type="pricing",
            claim_text="Cursor is the pricing winner.",
            evidence_ids=["evidence-1"],
            confidence=0.68,
        )
    ]
    report = _report_version(
        report_md="## Executive Summary\nCursor is the pricing winner. [source:pricing-1]",
        evidence_ids=["evidence-1"],
    )
    project = _project()

    gate = evaluate_report_release_gate(
        project=project,
        report_version=report,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )

    assert gate.allowed is False
    assert {
        "claim_uses_low_confidence_evidence",
        "strong_conclusion_uses_weak_source",
    } <= {issue.rule_id for issue in gate.issues}


def test_report_release_gate_blocks_missing_source_tokens() -> None:
    competitor = _competitor()
    evidence = [
        EvidenceRecord(
            id="evidence-1",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="pricing-1",
            competitor_id=competitor.id,
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing",
            url="https://cursor.sh/pricing",
            snippet="Cursor publishes pricing.",
            content_hash="hash-1",
            reliability_score=0.9,
            quality_label="accepted",
        )
    ]
    claims = [
        ClaimRecord(
            id="claim-1",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id=competitor.id,
            claim_type="pricing",
            claim_text="Cursor publishes pricing.",
            evidence_ids=["evidence-1"],
            confidence=0.9,
        )
    ]
    report = _report_version(
        report_md="Cursor publishes pricing. [source:missing-source]",
        evidence_ids=["evidence-1"],
    )

    gate = evaluate_report_release_gate(
        project=_project(),
        report_version=report,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )

    assert gate.allowed is False
    assert "report_citation_resolves" in {issue.rule_id for issue in gate.issues}


def test_report_release_gate_resolves_rag_chunk_source_tokens() -> None:
    competitor = _competitor()
    evidence = [
        EvidenceRecord(
            id="evidence-1",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="pricing-1",
            competitor_id=competitor.id,
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing",
            url="https://cursor.sh/pricing",
            snippet="Cursor publishes pricing.",
            content_hash="hash-1",
            reliability_score=0.9,
            quality_label="accepted",
        )
    ]
    claims = [
        ClaimRecord(
            id="claim-1",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id=competitor.id,
            claim_type="pricing",
            claim_text="Cursor publishes pricing.",
            evidence_ids=["evidence-1"],
            confidence=0.9,
        )
    ]
    report = _report_version(
        report_md=_structured_release_report(source_token="evidence-1#chunk:0"),
        evidence_ids=["evidence-1"],
    )

    gate = evaluate_report_release_gate(
        project=_project(),
        report_version=report,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )

    assert gate.allowed is True
    assert "report_citation_resolves" not in {issue.rule_id for issue in gate.issues}


def test_business_qa_evaluator_flags_stale_evidence_and_broken_claim_links() -> None:
    plan = build_business_intel_plan(
        topic="Cursor vs Copilot pricing comparison",
        competitors=["Cursor"],
        dimensions=["pricing"],
        requested_scenario_id="l1_pricing_pack",
    )
    competitor = _competitor()
    evidence = [
        EvidenceRecord(
            id="evidence-1",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="pricing-1",
            competitor_id=competitor.id,
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing",
            url="https://cursor.sh/pricing",
            snippet="Cursor publishes pricing.",
            content_hash="hash-1",
            reliability_score=0.9,
            quality_label="stale",
        )
    ]
    claims = [
        ClaimRecord(
            id="claim-1",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id=competitor.id,
            claim_type="pricing",
            claim_text="Cursor publishes pricing.",
            evidence_ids=["missing-evidence"],
            confidence=0.9,
        )
    ]

    evaluation = evaluate_business_qa(
        project_id="project-1",
        plan=plan,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )
    gaps = analyze_evidence_gaps(
        project_id="project-1",
        plan=plan,
        qa_evaluation=evaluation,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )
    readiness = score_project_readiness(
        project_id="project-1",
        plan=plan,
        qa_evaluation=evaluation,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )

    assert evaluation.finding_count >= 2
    assert evaluation.blocker_count >= 1
    assert {finding.rule_id for finding in evaluation.findings} >= {
        "claim_has_evidence",
        "pricing_currentness",
    }
    assert gaps.gap_count >= 2
    assert {gap.gap_type for gap in gaps.gaps} >= {
        "claim_without_usable_evidence",
        "missing_dimension_coverage",
    }
    assert readiness.risk_level == "blocked"
    assert readiness.score < 85
    assert readiness.recommendations[0].priority == "critical"


def test_business_qa_rules_cover_five_redo_scope_routes() -> None:
    plan = build_business_intel_plan(
        topic="Enterprise AI assistant security review",
        competitors=["A", "B"],
        dimensions=["security", "feature"],
        requested_scenario_id="dynamic_enterprise",
    )
    competitors = [
        CompetitorRecord(
            id="competitor-a",
            workspace_id="workspace-1",
            name="A",
            normalized_name="a",
            layer="L2",
            metadata={"homepage_verified": False},
        ),
        CompetitorRecord(
            id="competitor-b",
            workspace_id="workspace-1",
            name="B",
            normalized_name="b",
            layer="L2",
            metadata={"homepage_verified": False},
        ),
    ]
    evidence = [
        EvidenceRecord(
            id="evidence-low",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="source-low",
            competitor_id="competitor-a",
            dimension="security",
            source_type="webpage_verified",
            title="Low confidence security note",
            snippet="Security claim.",
            content_hash="hash-low",
            reliability_score=0.2,
            quality_label="unreviewed",
        )
    ]
    claims = [
        ClaimRecord(
            id="claim-broken",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id="competitor-a",
            claim_type="security",
            claim_text="A supports enterprise security controls.",
            evidence_ids=["missing-evidence"],
            confidence=0.6,
        )
    ]

    evaluation = evaluate_business_qa(
        project_id="project-1",
        plan=plan,
        competitors=competitors,
        evidence=evidence,
        claims=claims,
    )
    synthetic_findings = [
        *evaluation.findings,
        evaluation.findings[0].model_copy(update={"rule_id": "cross_competitor_matrix"}),
        evaluation.findings[0].model_copy(update={"rule_id": "security_official_source"}),
        evaluation.findings[0].model_copy(update={"rule_id": "landscape_breadth"}),
    ]
    scopes = business_findings_to_redo_scopes(synthetic_findings)

    assert {scope.kind for scope in scopes} >= {
        "collector",
        "writer_only",
        "comparator",
        "analyst",
        "full",
    }


def test_quality_agent_findings_map_to_redo_scopes() -> None:
    claim_scopes = claim_validation_issues_to_redo_scopes(
        [
            ClaimValidationIssue(
                id="issue-1",
                claim_id="claim-1",
                severity="blocker",
                issue_type="missing_evidence",
                message="Claim lacks usable evidence.",
            ),
            ClaimValidationIssue(
                id="issue-2",
                claim_id="claim-2",
                severity="warn",
                issue_type="weak_text_support",
                message="Evidence text does not strongly support the claim.",
                evidence_ids=["evidence-2"],
            ),
            ClaimValidationIssue(
                id="issue-3",
                claim_id="claim-3",
                severity="warn",
                issue_type="low_self_consistency",
                message="Claim failed the consistency threshold.",
                evidence_ids=["evidence-3", "evidence-4"],
            ),
        ]
    )
    gap_scopes = evidence_gaps_to_redo_scopes(
        [
            EvidenceGapItem(
                id="gap-1",
                severity="high",
                gap_type="missing_verified_source",
                competitor_name="Cursor",
                dimension="security",
                message="Need official security evidence.",
                recommended_query="Cursor security official docs",
            )
        ]
    )
    red_team_scopes = red_team_findings_to_redo_scopes(
        [
            RedTeamFinding(
                id="red-1",
                severity="high",
                finding_type="report_risk",
                dimension="summary",
                message="Report overstates the conclusion.",
                recommendation="Rewrite the conclusion with evidence caveats.",
            ),
            RedTeamFinding(
                id="red-2",
                severity="high",
                finding_type="weak_evidence",
                competitor_name="Cursor",
                dimension="pricing",
                message="Pricing claim needs stronger evidence.",
                recommendation="Collect current pricing evidence.",
            ),
        ]
    )

    assert [scope.kind for scope in claim_scopes] == ["collector", "analyst", "analyst"]
    assert claim_scopes[0].target_subagent == "claim_validation:claim-1:missing_evidence"
    assert claim_scopes[1].target_subagent == "claim_validation:claim-2:weak_text_support"
    assert claim_scopes[2].target_subagent == "claim_validation:claim-3:low_self_consistency"
    assert "Claim claim-2 failed weak_text_support" in claim_scopes[1].rationale
    assert "Evidence ids: evidence-3, evidence-4." in claim_scopes[2].rationale
    assert gap_scopes[0].kind == "collector"
    assert gap_scopes[0].target_competitor == "Cursor"
    assert gap_scopes[0].target_subagent == "security"
    assert {scope.kind for scope in red_team_scopes} == {"writer_only", "collector"}


def test_phase3_red_team_and_evidence_gap_agents_hit_exit_criteria() -> None:
    plan = build_business_intel_plan(
        topic="Cursor vs Copilot pricing comparison",
        competitors=["Cursor", "Copilot"],
        dimensions=["pricing"],
        requested_scenario_id="l1_pricing_pack",
    )
    competitors = [
        _competitor(),
        CompetitorRecord(
            id="competitor-copilot",
            workspace_id="workspace-1",
            name="Copilot",
            normalized_name="copilot",
            layer="L1",
            metadata={"homepage_verified": False},
        ),
    ]
    evidence = [
        EvidenceRecord(
            id="evidence-stale",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="pricing-1",
            competitor_id="competitor-cursor",
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing",
            url="https://cursor.sh/pricing",
            snippet="Cursor pricing.",
            content_hash="hash-1",
            reliability_score=0.2,
            quality_label="stale",
        )
    ]
    claims = [
        ClaimRecord(
            id="claim-unsupported",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id="competitor-cursor",
            claim_type="pricing",
            claim_text="Cursor pricing is better.",
            evidence_ids=["missing-evidence"],
            confidence=0.4,
        )
    ]
    evaluation = evaluate_business_qa(
        project_id="project-1",
        plan=plan,
        competitors=competitors,
        evidence=evidence,
        claims=claims,
    )
    gaps = analyze_evidence_gaps(
        project_id="project-1",
        plan=plan,
        qa_evaluation=evaluation,
        competitors=competitors,
        evidence=evidence,
        claims=claims,
    )
    red_team = analyze_red_team(
        project_id="project-1",
        plan=plan,
        qa_evaluation=evaluation,
        competitors=competitors,
        evidence=evidence,
        claims=claims,
        report_versions=[],
    )

    assert gaps.framework == "pydantic-ai"
    assert gaps.gap_count >= 1
    assert any(gap.competitor_id == "competitor-copilot" for gap in gaps.gaps)
    assert red_team.framework == "pydantic-ai"
    assert red_team.high_severity_count >= 2


async def test_phase3_pydantic_ai_executors_return_structured_outputs() -> None:
    plan = build_business_intel_plan(
        topic="Cursor vs Copilot pricing comparison",
        competitors=["Cursor"],
        dimensions=["pricing"],
        requested_scenario_id="l1_pricing_pack",
    )
    competitor = _competitor()
    evaluation = evaluate_business_qa(
        project_id="project-1",
        plan=plan,
        competitors=[competitor],
        evidence=[],
        claims=[],
    )

    gap_result = await build_evidence_gap_agent().execute(
        AgentExecutionRequest(
            run_id="run-1",
            agent_name="evidence_gap",
            payload={
                "project_id": "project-1",
                "plan": plan.model_dump(mode="json"),
                "qa_evaluation": evaluation.model_dump(mode="json"),
                "competitors": [competitor.model_dump(mode="json")],
                "evidence": [],
                "claims": [],
            },
        )
    )
    red_team_result = await build_red_team_agent().execute(
        AgentExecutionRequest(
            run_id="run-1",
            agent_name="red_team",
            payload={
                "project_id": "project-1",
                "plan": plan.model_dump(mode="json"),
                "qa_evaluation": evaluation.model_dump(mode="json"),
                "competitors": [competitor.model_dump(mode="json")],
                "evidence": [],
                "claims": [],
                "report_versions": [],
            },
        )
    )

    assert gap_result.status == "ok"
    assert gap_result.metadata["framework"] == "pydantic-ai"
    assert gap_result.metadata["execution_mode"] == "deterministic_handler"
    assert gap_result.metadata["typed_contract_enforced"] is True
    assert gap_result.metadata["input_schema_hash"]
    assert gap_result.metadata["output_schema_hash"]
    assert gap_result.metadata["runtime_prompt_hash"]
    assert gap_result.metadata["runtime_prompt_chars"] > 0
    assert gap_result.metadata["pydantic_ai_runtime_agent_created"] is True
    assert gap_result.metadata["pydantic_ai_runtime_agent_class"] == "Agent"
    assert gap_result.metadata["pydantic_ai_model_backed_capable"] is True
    assert gap_result.metadata["pydantic_ai_model_backed_requested"] is False
    assert gap_result.payload["gap_count"] >= 1
    assert red_team_result.status == "ok"
    assert red_team_result.metadata["framework"] == "pydantic-ai"
    assert red_team_result.metadata["execution_mode"] == "deterministic_handler"
    assert red_team_result.metadata["typed_contract_enforced"] is True
    assert red_team_result.metadata["input_schema_hash"]
    assert red_team_result.metadata["output_schema_hash"]
    assert red_team_result.metadata["pydantic_ai_runtime_agent_created"] is True
    assert red_team_result.metadata["pydantic_ai_runtime_agent_class"] == "Agent"
    assert red_team_result.metadata["pydantic_ai_model_backed_capable"] is True
    assert red_team_result.metadata["pydantic_ai_model_backed_requested"] is False
    assert red_team_result.payload["high_severity_count"] >= 1


async def test_pydantic_ai_agent_can_execute_through_test_model_runtime() -> None:
    plan = build_business_intel_plan(
        topic="Cursor vs Copilot pricing comparison",
        competitors=["Cursor", "Copilot"],
        dimensions=["pricing"],
        requested_scenario_id="l1_pricing_pack",
    )
    evaluation = evaluate_business_qa(
        project_id="project-1",
        plan=plan,
        competitors=[_competitor()],
        evidence=[],
        claims=[],
    )

    result = await build_evidence_gap_agent().execute(
        AgentExecutionRequest(
            run_id="run-1",
            agent_name="evidence_gap",
            context={"pydantic_ai_execution_mode": "test_model"},
            payload={
                "project_id": "project-1",
                "plan": plan.model_dump(mode="json"),
                "qa_evaluation": evaluation.model_dump(mode="json"),
                "competitors": [_competitor().model_dump(mode="json")],
                "evidence": [],
                "claims": [],
            },
        )
    )

    assert result.status == "ok"
    assert result.metadata["execution_mode"] == "pydantic_ai_test_model_backed"
    assert result.metadata["pydantic_ai_model_backed_requested"] is True
    assert result.metadata["pydantic_ai_runtime_result_type"] == "AgentRunResult"
    assert result.metadata["runtime_prompt_hash"]
    assert result.metadata["runtime_prompt_chars"] > 0
    assert result.payload["gap_count"] >= 1


async def test_pydantic_ai_model_backed_path_falls_back_with_typed_metadata(monkeypatch) -> None:
    class FailingAgent:
        async def run(self, prompt: str):
            assert "Output JSON schema" in prompt
            raise RuntimeError("provider timeout")

    monkeypatch.setattr(
        pydantic_ai_adapter,
        "_load_pydantic_ai_agent_class_name",
        lambda: ("Agent", True),
    )
    monkeypatch.setattr(
        pydantic_ai_adapter,
        "_create_pydantic_ai_agent",
        lambda **kwargs: FailingAgent(),
    )
    plan = build_business_intel_plan(
        topic="Cursor vs Copilot pricing comparison",
        competitors=["Cursor", "Copilot"],
        dimensions=["pricing"],
        requested_scenario_id="l1_pricing_pack",
    )
    evaluation = evaluate_business_qa(
        project_id="project-1",
        plan=plan,
        competitors=[_competitor()],
        evidence=[],
        claims=[],
    )

    result = await build_evidence_gap_agent().execute(
        AgentExecutionRequest(
            run_id="run-1",
            agent_name="evidence_gap",
            context={
                "pydantic_ai_execution_mode": "model_backed",
                "pydantic_ai_model": "openai:test-model",
            },
            payload={
                "project_id": "project-1",
                "plan": plan.model_dump(mode="json"),
                "qa_evaluation": evaluation.model_dump(mode="json"),
                "competitors": [_competitor().model_dump(mode="json")],
                "evidence": [],
                "claims": [],
            },
        )
    )

    assert result.status == "ok"
    assert result.metadata["execution_mode"] == "pydantic_ai_model_backed_fallback"
    assert result.metadata["pydantic_ai_model_backed_requested"] is True
    assert result.metadata["pydantic_ai_model_backed_fallback"] is True
    assert result.metadata["pydantic_ai_model_backed_error"] == "provider timeout"
    assert result.metadata["pydantic_ai_model_name"] == "openai:test-model"
    assert result.metadata["typed_contract_enforced"] is True
    assert result.metadata["runtime_prompt_hash"]
    assert result.metadata["runtime_prompt_chars"] > 0
    assert result.payload["gap_count"] >= 1


def test_phase3_competitor_scores_return_ranked_scorecards() -> None:
    plan = build_business_intel_plan(
        topic="Cursor vs Copilot pricing comparison",
        competitors=["Cursor", "Copilot"],
        dimensions=["pricing"],
        requested_scenario_id="l1_pricing_pack",
    )
    competitors = [
        _competitor(),
        CompetitorRecord(
            id="competitor-copilot",
            workspace_id="workspace-1",
            name="Copilot",
            normalized_name="copilot",
            layer="L1",
            metadata={"homepage_verified": True},
        ),
    ]
    evidence = [
        EvidenceRecord(
            id="evidence-cursor",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="pricing-1",
            competitor_id="competitor-cursor",
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing",
            url="https://cursor.sh/pricing",
            snippet="Cursor pricing.",
            content_hash="hash-1",
            reliability_score=0.9,
            quality_label="accepted",
        )
    ]
    claims = [
        ClaimRecord(
            id="claim-cursor",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id="competitor-cursor",
            claim_type="pricing",
            claim_text="Cursor publishes pricing.",
            evidence_ids=["evidence-cursor"],
            confidence=0.9,
        )
    ]

    report = score_competitors(
        project_id="project-1",
        plan=plan,
        competitors=competitors,
        evidence=evidence,
        claims=claims,
    )

    assert report.scores[0].competitor_id == "competitor-cursor"
    assert report.scores[0].total_score > report.scores[1].total_score
    assert report.scores[0].dimension_scores[0].dimension == "pricing"


def _competitor() -> CompetitorRecord:
    return CompetitorRecord(
        id="competitor-cursor",
        workspace_id="workspace-1",
        name="Cursor",
        normalized_name="cursor",
        layer="L1",
        metadata={"homepage_verified": True},
    )


def _project() -> ProjectRecord:
    return ProjectRecord(
        id="project-1",
        workspace_id="workspace-1",
        name="Cursor pricing",
        topic="Cursor vs Copilot pricing comparison",
        topic_normalized="cursor-pricing",
        competitor_layer="L1",
        competitor_set_hash="hash",
        scenario_id="l1_pricing_pack",
    )


def _report_version(
    *,
    report_md: str = "",
    evidence_ids: list[str] | None = None,
    claim_ids: list[str] | None = None,
    quality_metadata: dict[str, object] | None = None,
) -> ReportVersionRecord:
    return ReportVersionRecord(
        id="report-1",
        workspace_id="workspace-1",
        project_id="project-1",
        version_number=1,
        topic_normalized="cursor-pricing",
        competitor_layer="L1",
        competitor_set_hash="hash",
        report_md=report_md or _structured_release_report(),
        claim_ids=claim_ids or ["claim-1"],
        evidence_ids=evidence_ids or ["evidence-1"],
        quality_metadata=quality_metadata or {},
    )


def _structured_release_report(source_token: str = "evidence-1") -> str:
    citation = f"[source:{source_token}]"
    return f"""
# Cursor Direct Battlecard

## Executive Summary
Cursor publishes pricing and can be reviewed as a direct L1 battlecard item. {citation}

## Source Quality & Coverage
The report uses accepted webpage evidence and keeps the conclusion scoped to verified pricing
coverage. {citation}

## Side-by-Side Decision Matrix
| Dimension | Cursor |
| --- | --- |
| Pricing | Cursor publishes pricing. {citation} |

## Battlecard
Use pricing transparency as the battlecard point, while keeping security and procurement claims
out of scope until separately verified. {citation}

## Claim Validation & Evidence Risk
The scoped pricing claim is backed by accepted evidence. Broader security or procurement claims
remain excluded until independent evidence is attached. {citation}

## Next Collection / Verification Plan
Collect additional feature, security, and procurement evidence before making broader release
recommendations. {citation}

## Evidence Appendix
- {source_token}: Cursor pricing evidence. {citation}
""".strip()
