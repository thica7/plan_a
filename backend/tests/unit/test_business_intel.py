from datetime import datetime

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
    compare_run_quality,
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
from packages.business_intel.entity_resolver import trusted_source_candidates
from packages.business_intel.homepage import verify_homepage
from packages.business_intel.layers import assess_competitor_layer
from packages.schema.api_dto import RunDetail
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
from packages.schema.models import AnalysisPlan, RawSource, RunMetrics
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



def test_pricing_dimension_does_not_override_workflow_or_market_scope() -> None:
    workflow_plan = build_business_intel_plan(
        topic="Enterprise AI search workflow pricing and switching risk",
        competitors=["Glean", "Coveo", "Elastic"],
        dimensions=["pricing", "integrations", "security"],
    )
    landscape_plan = build_business_intel_plan(
        topic="AI coding assistant market landscape with pricing benchmarks",
        competitors=["Cursor", "Copilot", "Windsurf", "Tabnine"],
        dimensions=["pricing", "market", "benchmark"],
    )

    assert workflow_plan.competitor_layer.layer == "L2"
    assert workflow_plan.scenario_pack.id in {
        "enterprise_risk_review",
        "l2_adjacent_workflow",
    }
    assert "pricing" in workflow_plan.recommended_dimensions
    assert landscape_plan.competitor_layer.layer == "L3"
    assert landscape_plan.scenario_pack.id == "l3_market_landscape"
    assert "pricing" in landscape_plan.recommended_dimensions


def test_focused_pricing_scope_still_selects_l1_pricing_pack() -> None:
    plan = build_business_intel_plan(
        topic="Cursor vs Copilot pricing packaging comparison",
        competitors=["Cursor", "Copilot"],
        dimensions=["pricing", "feature"],
    )

    assert plan.competitor_layer.layer == "L1"
    assert plan.scenario_pack.id == "l1_pricing_pack"
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
    unknown = verify_homepage("Alpha")
    phantom = verify_homepage("FAKE_PRODUCT_NOT_EXISTS")

    assert pack.is_dynamic is True
    assert pack.competitor_layer == "L3"
    assert pack.seed_competitors == ["Fathom", "Otter", "Fireflies", "Avoma"]
    assert "market" in pack.required_dimensions
    assert good.verified is True
    assert unknown.verified is False
    assert unknown.homepage_url is None
    assert unknown.reason == "no_verified_homepage"
    assert phantom.verified is False
    assert phantom.reason == "phantom_name"


def test_entity_resolver_seeds_llm_official_sources() -> None:
    gpt = verify_homepage("GPT-5.5")
    claude = verify_homepage("Claude")
    gemini = verify_homepage("Gemini")
    llama = verify_homepage("Llama 4")
    unknown = verify_homepage("Unverified New Entrant", "https://example.com")

    assert gpt.verified is True
    assert "openai.com" in str(gpt.homepage_url)
    assert claude.verified is True
    assert gemini.verified is True
    assert llama.verified is True
    assert unknown.verified is False

    assert any(
        "developers.openai.com" in item.url
        for item in trusted_source_candidates("GPT-5.5", "pricing")
    )
    assert any(
        "docs.anthropic.com" in item.url or "claude.com" in item.url
        for item in trusted_source_candidates("Claude", "feature")
    )
    assert any(
        "ai.google.dev" in item.url for item in trusted_source_candidates("Gemini", "pricing")
    )
    assert any(
        "ai.meta.com" in item.url or "llama.com" in item.url
        for item in trusted_source_candidates("Llama 4", "feature")
    )


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
        finding.rule_id == "coverage_min_verified" and finding.dimension == "enterprise_sso"
        for finding in evaluation.findings
    )
    assert any(
        finding.finding_type == "competitive_bias" and "enterprise_sso" in (finding.dimension or "")
        for finding in red_team.findings
    )
    assert any(
        score.dimension == "enterprise_sso" for score in score_report.scores[0].dimension_scores
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
    assert "extract_facts" not in suggestion.proposed_skill.tools_allowlist


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
    claim_issue = next(
        issue for issue in blocked.issues if issue.rule_id == "claim_uses_low_confidence_evidence"
    )
    assert claim_issue.competitor_id == competitor.id
    assert claim_issue.competitor_name == competitor.name
    assert claim_issue.dimension == "pricing"


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


def test_report_release_gate_counts_high_quality_triangulated_community_evidence() -> None:
    competitor = _competitor()
    evidence = [
        EvidenceRecord(
            id="evidence-1",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="community-1",
            competitor_id=competitor.id,
            dimension="pricing",
            source_type="github_discussion",
            title="Cursor pricing community discussion",
            url="https://github.com/orgs/community/discussions/1",
            snippet="Multiple independent users report Cursor Pro pricing at $20 per month.",
            content_hash="hash-1",
            reliability_score=0.85,
            quality_label="accepted",
            metadata={
                "community_evidence": True,
                "community_claim_clusters": [
                    {
                        "label": "community_triangulated",
                        "confidence": 0.84,
                        "claim_type": "pricing",
                        "independent_domain_count": 3,
                        "source_ids": ["community-1", "community-2", "community-3"],
                    }
                ],
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
            claim_text="Community sources triangulate Cursor pricing at $20 per month.",
            evidence_ids=["evidence-1"],
            confidence=0.84,
        )
    ]
    report = _report_version(
        report_md=_structured_release_report(source_token="evidence-1"),
        evidence_ids=["evidence-1"],
        claim_ids=["claim-1"],
    )

    gate = evaluate_report_release_gate(
        project=_project(),
        report_version=report,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )

    assert "verified_evidence_rate" not in {issue.rule_id for issue in gate.issues}
    assert gate.allowed is True


def test_report_release_gate_counts_collector_threshold_triangulated_community_evidence() -> None:
    competitor = _competitor()
    evidence = [
        EvidenceRecord(
            id="evidence-1",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="community-1",
            competitor_id=competitor.id,
            dimension="pricing",
            source_type="github_discussion",
            title="Cursor pricing community discussion",
            url="https://github.com/orgs/community/discussions/1",
            snippet="Multiple independent users report Cursor Pro pricing at $20 per month.",
            content_hash="hash-1",
            reliability_score=0.9,
            quality_label="accepted",
            metadata={
                "community_evidence": True,
                "community_claim_clusters": [
                    {
                        "label": "community_triangulated",
                        "confidence": 0.70,
                        "kind": "pricing",
                        "independent_domain_count": 2,
                        "source_ids": ["community-1", "community-2"],
                    }
                ],
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
            claim_text="Community sources triangulate Cursor pricing at $20 per month.",
            evidence_ids=["evidence-1"],
            confidence=0.8,
        )
    ]
    report = _report_version(
        report_md=_structured_release_report(source_token="evidence-1"),
        evidence_ids=["evidence-1"],
        claim_ids=["claim-1"],
    )

    gate = evaluate_report_release_gate(
        project=_project(),
        report_version=report,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )

    assert "verified_evidence_rate" not in {issue.rule_id for issue in gate.issues}
    assert gate.allowed is True


def test_report_release_gate_still_blocks_untriangulated_community_evidence() -> None:
    competitor = _competitor()
    evidence = [
        EvidenceRecord(
            id="evidence-1",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="community-1",
            competitor_id=competitor.id,
            dimension="pricing",
            source_type="snippet_only",
            title="Cursor pricing reddit snippet",
            url="https://www.reddit.com/r/cursor/comments/example",
            snippet="One community snippet reports Cursor pricing.",
            content_hash="hash-1",
            reliability_score=0.9,
            quality_label="accepted",
            metadata={"community_evidence": True},
        )
    ]
    claims = [
        ClaimRecord(
            id="claim-1",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id=competitor.id,
            claim_type="pricing",
            claim_text="A community snippet reports Cursor pricing.",
            evidence_ids=["evidence-1"],
            confidence=0.8,
        )
    ]
    report = _report_version(
        report_md=_structured_release_report(source_token="evidence-1"),
        evidence_ids=["evidence-1"],
        claim_ids=["claim-1"],
    )

    gate = evaluate_report_release_gate(
        project=_project(),
        report_version=report,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )

    assert "verified_evidence_rate" in {issue.rule_id for issue in gate.issues}
    assert gate.allowed is False


def test_report_release_gate_does_not_dilute_rate_with_auxiliary_evidence() -> None:
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
        ),
        EvidenceRecord(
            id="evidence-2",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="snippet-1",
            competitor_id=competitor.id,
            dimension="persona",
            source_type="snippet_only",
            title="Cursor community snippet",
            url="https://www.reddit.com/r/cursor/comments/example",
            snippet="A community snippet provides auxiliary user sentiment.",
            content_hash="hash-2",
            reliability_score=0.55,
            quality_label="unreviewed",
            metadata={"community_evidence": True},
        ),
        EvidenceRecord(
            id="evidence-3",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="survey-1",
            competitor_id=competitor.id,
            dimension="persona",
            source_type="survey_simulated",
            title="Cursor persona survey synthesis",
            url=None,
            snippet="A simulated survey summarizes buyer persona concerns.",
            content_hash="hash-3",
            reliability_score=0.76,
            quality_label="unreviewed",
        ),
        EvidenceRecord(
            id="evidence-4",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="interview-1",
            competitor_id=competitor.id,
            dimension="persona",
            source_type="interview_record",
            title="Cursor persona interview synthesis",
            url=None,
            snippet="A synthetic interview summarizes adoption blockers.",
            content_hash="hash-4",
            reliability_score=0.82,
            quality_label="unreviewed",
        ),
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
        report_md=_structured_release_report(source_token="evidence-1"),
        evidence_ids=["evidence-1", "evidence-2", "evidence-3", "evidence-4"],
        claim_ids=["claim-1"],
    )

    gate = evaluate_report_release_gate(
        project=_project(),
        report_version=report,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )

    assert "verified_evidence_rate" not in {issue.rule_id for issue in gate.issues}
    assert gate.allowed is True


def test_report_release_gate_does_not_dilute_rate_with_community_observations() -> None:
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
        ),
        EvidenceRecord(
            id="evidence-2",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="forum-1",
            competitor_id=competitor.id,
            dimension="feature",
            source_type="community_forum",
            title="Cursor community forum observation",
            url="https://forum.cursor.com/t/example/1",
            snippet="A forum thread describes a feature limitation in actual use.",
            content_hash="hash-2",
            reliability_score=0.92,
            quality_label="unreviewed",
            metadata={
                "community_evidence": True,
                "community_claim_clusters": [
                    {
                        "label": "community_observed",
                        "confidence": 0.65,
                        "kind": "feature_limitation",
                        "independent_domain_count": 1,
                        "source_ids": ["forum-1"],
                    }
                ],
            },
        ),
        EvidenceRecord(
            id="evidence-3",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="discussion-1",
            competitor_id=competitor.id,
            dimension="persona",
            source_type="github_discussion",
            title="Cursor community discussion observation",
            url="https://github.com/orgs/community/discussions/1",
            snippet="A community discussion describes user sentiment.",
            content_hash="hash-3",
            reliability_score=0.92,
            quality_label="unreviewed",
            metadata={
                "community_evidence": True,
                "community_claim_clusters": [
                    {
                        "label": "community_observed",
                        "confidence": 0.65,
                        "kind": "persona_signal",
                        "independent_domain_count": 1,
                        "source_ids": ["discussion-1"],
                    }
                ],
            },
        ),
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
        report_md=_structured_release_report(source_token="evidence-1"),
        evidence_ids=["evidence-1", "evidence-2", "evidence-3"],
        claim_ids=["claim-1"],
    )

    gate = evaluate_report_release_gate(
        project=_project(),
        report_version=report,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )

    assert "verified_evidence_rate" not in {issue.rule_id for issue in gate.issues}
    assert gate.allowed is True


def test_report_release_gate_uses_report_homepage_snapshot_for_competitors() -> None:
    competitor = _competitor().model_copy(update={"homepage_url": None, "metadata": {}})
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
            "report_competitor_homepages": [
                {
                    "competitor_id": competitor.id,
                    "competitor_name": competitor.name,
                    "homepage_url": "https://cursor.com/",
                    "homepage_verified": True,
                }
            ]
        }
    )

    gate = evaluate_report_release_gate(
        project=_project(),
        report_version=report,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )

    assert gate.allowed is True
    assert "homepage_verified" not in {issue.rule_id for issue in gate.issues}


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


def test_run_quality_does_not_give_full_core_depth_to_short_core_sections() -> None:
    detail = _quality_run_detail(
        report_md=_medium_but_still_thin_core_report(),
        competitors=["Cursor", "Claude Code", "GitHub Copilot", "Windsurf"],
        dimensions=["pricing", "feature", "persona"],
    )

    comparison = compare_run_quality(detail)
    metrics = {metric.name: metric.target_value for metric in comparison.metrics}

    assert metrics["core_analysis_depth_score"] < 1.0
    assert metrics["core_section_depth_score"] < 1.0


def test_report_release_gate_blocks_report_with_thin_core_quality_metrics() -> None:
    competitor_names = ["Cursor", "Claude Code", "GitHub Copilot", "Windsurf"]
    competitors = [
        CompetitorRecord(
            id=f"competitor-{index}",
            workspace_id="workspace-1",
            name=name,
            normalized_name=name.casefold().replace(" ", "-"),
            layer="L1",
            metadata={"homepage_verified": True},
        )
        for index, name in enumerate(competitor_names, start=1)
    ]
    evidence = [
        EvidenceRecord(
            id=f"evidence-{index}",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id=f"evidence-{index}",
            competitor_id=competitor.id,
            dimension="pricing",
            source_type="webpage_verified",
            title=f"{competitor.name} pricing",
            url=f"https://example.com/{index}/pricing",
            snippet=f"{competitor.name} publishes pricing and product positioning.",
            content_hash=f"hash-{index}",
            reliability_score=0.9,
            quality_label="accepted",
        )
        for index, competitor in enumerate(competitors, start=1)
    ]
    claims = [
        ClaimRecord(
            id=f"claim-{index}",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id=competitor.id,
            claim_type="pricing",
            claim_text=f"{competitor.name} publishes pricing and product positioning.",
            evidence_ids=[f"evidence-{index}"],
            confidence=0.9,
        )
        for index, competitor in enumerate(competitors, start=1)
    ]
    report_md = f"""
## Executive Summary
The report has the required release headings but the core analysis remains too compressed for a
decision-grade release. [source:evidence-1]

{_medium_but_still_thin_core_report()}

## Claim Validation & Evidence Risk
The scoped claims are cited but still require fuller treatment in the core report. [source:evidence-1]

## RAG Gap-Fill
Retrieval gaps remain summarized too briefly for publication. [source:evidence-1]

## Scenario Checklist
The L1 pricing scenario is referenced but not deeply expanded. [source:evidence-1]

## Next Collection / Verification Plan
Collect stronger customer voice and procurement evidence before final release. [source:evidence-1]

## Evidence Appendix
- evidence-1 through evidence-4: accepted pricing evidence. [source:evidence-1]
""".strip()
    report = _report_version(
        report_md=report_md,
        evidence_ids=[item.id for item in evidence],
        claim_ids=[item.id for item in claims],
    )

    gate = evaluate_report_release_gate(
        project=_project(),
        report_version=report,
        competitors=competitors,
        evidence=evidence,
        claims=claims,
    )
    report_depth_issues = [
        issue for issue in gate.issues if issue.rule_id == "report_depth_required"
    ]

    assert len(report_md) > 900
    assert report_depth_issues
    assert any(
        "core_section_depth_score" in issue.message or "swot_section_score" in issue.message
        for issue in report_depth_issues
    )


def test_report_release_gate_accepts_chinese_report_structure() -> None:
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
    structured_zh = """
# Cursor 直接战报

## 执行摘要
Cursor 定价信息可用于直接战报评估，结论仍限定在已验证定价证据范围内。 [source:evidence-1]
该摘要说明置信度、适用边界和后续采购前需要补充的企业安全材料。 [source:evidence-1]

## 来源质量与覆盖
报告使用已接受的网页证据，并将结论限定在可验证的定价覆盖范围内。 [source:evidence-1]
来源质量说明区分官方页面、已抓取网页和仍需后续验证的低置信线索。
该报告避免把搜索摘要当作最终事实。 [source:evidence-1]

## 横向决策矩阵
| 维度 | Cursor |
| --- | --- |
| 定价 | Cursor 发布可核验定价信息。 [source:evidence-1] |

## 场景 QA 清单
- 场景：l1_pricing_pack；层级：L1；推荐维度：pricing、feature、persona。
- 分析问题：哪些套餐门槛影响感知价值？
- 证据要求：定价行必须使用官方或已抓取网页证据。
- QA 规则：claim_has_evidence、source_reliability_min、homepage_verified。

## 战报
销售和产品团队可把定价透明度作为第一条战报线索。 [source:evidence-1]
安全、采购和企业管控主张应保留为后续验证项。 [source:evidence-1]
该战报不使用绝对赢家表述，而是说明已验证证据支持哪些短期定位。
采购结论还需要更强来源。 [source:evidence-1]

## 声明校验与证据风险
定价声明有已接受证据支撑。 [source:evidence-1]
更广泛的安全、采购或企业控制声明不应在缺少独立来源时发布。 [source:evidence-1]
风险说明明确列出低置信来源、单一来源结论和需要降级处理的主张。 [source:evidence-1]

## 下一步采集与验证计划
下一轮应补充官方企业安全文档、当前采购包装和买方异议证据。 [source:evidence-1]
补充后重新运行声明校验，确认定价、功能和 persona 结论都能映射到高质量来源。 [source:evidence-1]

## 证据附录
- evidence-1：Cursor pricing，webpage_verified，confidence 0.90。 [source:evidence-1]
""".strip()
    report = _report_version(report_md=structured_zh)

    gate = evaluate_report_release_gate(
        project=_project(),
        report_version=report,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )

    assert len(structured_zh) >= 900
    assert "report_structure_required" not in {issue.rule_id for issue in gate.issues}


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


def test_claim_validator_marks_high_risk_status_and_conflicts() -> None:
    competitor = _competitor()
    supported_security = EvidenceRecord(
        id="evidence-security",
        workspace_id="workspace-1",
        project_id="project-1",
        raw_source_id="security-1",
        competitor_id=competitor.id,
        dimension="security",
        source_type="webpage_verified",
        title="Cursor enterprise security",
        url="https://cursor.sh/security",
        snippet="Cursor enterprise-ready security includes SSO, SAML, SOC 2, and audit logs.",
        content_hash="hash-security",
        reliability_score=0.92,
        quality_label="accepted",
    )
    conflicting_security = supported_security.model_copy(
        update={
            "id": "evidence-security-conflict",
            "raw_source_id": "security-conflict",
            "snippet": "Cursor does not support SSO or SAML for this enterprise plan.",
            "content_hash": "hash-security-conflict",
        }
    )
    claims = [
        ClaimRecord(
            id="claim-single-source-risk",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id=competitor.id,
            claim_type="security",
            claim_text="Cursor is enterprise-ready with SSO and SOC 2 controls.",
            evidence_ids=["evidence-security"],
            confidence=0.9,
        ),
        ClaimRecord(
            id="claim-conflict",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id=competitor.id,
            claim_type="security",
            claim_text="Cursor has SSO and SAML controls.",
            evidence_ids=["evidence-security-conflict"],
            confidence=0.9,
        ),
    ]

    report = validate_project_claims(
        project_id="project-1",
        claims=claims,
        evidence=[supported_security, conflicting_security],
    )

    single_source = next(
        item for item in report.results if item.claim_id == "claim-single-source-risk"
    )
    conflict = next(item for item in report.results if item.claim_id == "claim-conflict")
    assert single_source.high_risk is True
    assert single_source.validation_status == "weak_support"
    assert single_source.recommended_action == "downgrade_claim"
    assert any(reason.startswith("matched:") for reason in single_source.risk_reasons)
    assert conflict.high_risk is True
    assert conflict.status == "unsupported"
    assert conflict.validation_status == "conflicting"
    assert conflict.recommended_action == "human_review"
    assert report.high_risk_claim_count == 2
    assert report.high_risk_validated_count == 2
    assert report.validation_status_counts["weak_support"] == 1
    assert report.validation_status_counts["conflicting"] == 1
    assert {issue.issue_type for issue in report.issues} >= {
        "single_source_support",
        "conflicting_evidence",
    }


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


def test_report_release_gate_warns_on_unresolved_run_qa_metadata() -> None:
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
                    "target_subagent": "pricing",
                    "target_competitor": "Cursor",
                    "problem": "No granular pricing comparison.",
                    "redo_scope": {
                        "kind": "collector",
                        "target_subagent": "pricing",
                        "target_competitor": "Cursor",
                        "target_competitors": ["Cursor"],
                        "rationale": "Collect verified pricing tier evidence.",
                    },
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

    assert gate.allowed is True
    issue = next(issue for issue in gate.issues if issue.rule_id == "run_qa_findings_unresolved")
    assert issue.severity == "warn"
    assert issue.competitor_name == "Cursor"
    assert issue.dimension == "pricing"
    assert issue.recommendation == "Collect verified pricing tier evidence."


def test_report_release_gate_blocks_blocker_run_qa_metadata() -> None:
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
                    "id": "qa-blocker-1",
                    "severity": "blocker",
                    "target_subagent": "pricing",
                    "target_competitor": "Cursor",
                    "problem": "Pricing source is missing.",
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

    issue = next(issue for issue in gate.issues if issue.rule_id == "run_qa_findings_unresolved")
    assert gate.allowed is False
    assert issue.severity == "blocker"


def test_report_release_gate_separates_malformed_source_tokens_from_missing_sources() -> None:
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
        report_md=(
            "# Report\n\nCursor publishes pricing. [source:evidence-1] "
            "Persona caveat. [source: all persona cells]"
        ),
        evidence_ids=["evidence-1"],
        claim_ids=["claim-1"],
    )

    gate = evaluate_report_release_gate(
        project=_project(),
        report_version=report,
        competitors=[competitor],
        evidence=evidence,
        claims=claims,
    )
    rule_ids = {issue.rule_id for issue in gate.issues}

    assert "report_citation_token_format" in rule_ids
    assert "report_citation_resolves" not in rule_ids


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
                "online_failures": [
                    {
                        "gap_id": "gap-security",
                        "stage": "robots",
                        "url": "https://cursor.example/trust",
                        "error": "Blocked by robots.txt",
                    }
                ],
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
    assert "robots" in issues["rag_gap_fill_chain_unclosed"].message
    assert (
        "online search/fetch/robots failures"
        in issues["rag_gap_fill_chain_unclosed"].recommendation
    )


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


def test_report_release_gate_does_not_treat_appendix_caveat_as_strong_conclusion() -> None:
    competitor = _competitor()
    evidence = [
        EvidenceRecord(
            id="evidence-1",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="community-risk-1",
            competitor_id=competitor.id,
            dimension="pricing",
            source_type="snippet_only",
            title="Cursor pricing community risk",
            url="https://example.com/community-risk",
            snippet="Community users mention rate-limit concerns.",
            content_hash="hash-1",
            reliability_score=0.55,
            quality_label="unreviewed",
        )
    ]
    report = _report_version(
        report_md=(
            "## Evidence Appendix\n"
            "QA rule: community posts only identify pricing risk and are not used "
            "as winner or procurement recommendation evidence. [source:community-risk-1]"
        ),
        evidence_ids=["evidence-1"],
    )

    gate = evaluate_report_release_gate(
        project=_project(),
        report_version=report,
        competitors=[competitor],
        evidence=evidence,
        claims=[],
    )

    assert "strong_conclusion_uses_weak_source" not in {
        issue.rule_id for issue in gate.issues
    }


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


def test_report_release_gate_resolves_raw_source_alias_tokens() -> None:
    competitor = _competitor()
    evidence = [
        EvidenceRecord(
            id="evidence-1",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="pricing-old",
            competitor_id=competitor.id,
            dimension="pricing",
            source_type="webpage_verified",
            title="Cursor pricing",
            url="https://cursor.sh/pricing",
            snippet="Cursor publishes pricing.",
            content_hash="hash-1",
            reliability_score=0.9,
            quality_label="accepted",
            metadata={"raw_source_aliases": ["pricing-current"]},
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
        report_md=_structured_release_report(source_token="pricing-current"),
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


def _quality_run_detail(
    *,
    report_md: str,
    competitors: list[str] | None = None,
    dimensions: list[str] | None = None,
) -> RunDetail:
    competitors = competitors or ["Cursor"]
    dimensions = dimensions or ["pricing"]
    return RunDetail(
        id="run-quality",
        topic="Cursor pricing",
        status="completed",
        execution_mode="real",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        plan=AnalysisPlan(
            topic="Cursor pricing",
            competitors=competitors,
            dimensions=dimensions,
            competitor_layer="L1",
        ),
        raw_sources=[
            RawSource(
                id="evidence-1",
                competitor="Cursor",
                dimension="pricing",
                source_type="webpage_verified",
                title="Cursor pricing",
                url="https://cursor.sh/pricing",
                snippet="Cursor publishes pricing.",
                content_hash="hash-1",
                confidence=0.9,
            )
        ],
        metrics=RunMetrics(llm_calls=3, source_coverage_rate=1.0, claim_citation_rate=1.0),
        report_md=report_md,
    )


def _medium_but_still_thin_core_report() -> str:
    citation = "[source:evidence-1]"
    return f"""
# AI Coding Agent Battlecard

## Decision Summary
- Recommended action: use Cursor as the primary evaluation anchor because standalone pricing
  and focused workflow claims are easier to explain during a first-pass procurement discussion.
  {citation}
- Immediate move: validate security, enterprise packaging, and switching costs before making
  a replacement recommendation against Copilot, Claude Code, or Windsurf. {citation}

## Competitive Findings
- Pricing: Cursor appears easiest to frame as a standalone purchase, while Copilot benefits
  from Microsoft adjacency and Claude Code needs clearer usage-cost framing. {citation}
- Feature: agentic coding workflows are converging, so differentiation depends on context
  management, IDE fit, policy controls, and team onboarding. {citation}
- Persona: individual developers, platform buyers, and AI-forward teams all evaluate these
  tools differently, which means one winner claim would be premature. {citation}

## User Review Themes
- Praise: evaluators can understand Cursor pricing and workflow positioning quickly. {citation}
- Complaint: buyers still need stronger enterprise controls, migration proof, and onboarding
  evidence before replacing an incumbent workflow. {citation}
- Switching trigger: teams move only when workflow gains outweigh governance and training cost.
  {citation}

## Competitor Deep Dives
- Cursor wins on focused positioning and pricing clarity, but still needs procurement and
  governance validation before an enterprise recommendation is safe. {citation}
- Claude Code is strongest when sophisticated teams value deeper agentic workflows, but its
  buying motion needs clearer cost and rollout guardrails. {citation}
- GitHub Copilot wins on distribution and Microsoft familiarity, but can look less differentiated
  in a pure agent-workflow comparison. {citation}
- Windsurf can remain attractive for AI-native workflow experiments, but the current evidence
  needs stronger enterprise adoption proof. {citation}

## SWOT Analysis
- Strengths: Cursor has focused workflow framing; Copilot has distribution; Claude Code has
  advanced agentic depth; Windsurf has AI-native workflow appeal. {citation}
- Weaknesses: each competitor still has unanswered questions around procurement, packaging,
  or governance evidence. {citation}
- Opportunities: the response should tie pricing clarity to onboarding speed and qualify
  claims that require security or enterprise proof. {citation}
- Threats: bundled distribution, unclear usage costs, and migration friction can overturn a
  simple feature-led recommendation. {citation}

## Side-by-Side Decision Matrix
| Dimension | Cursor | Claude Code | GitHub Copilot | Windsurf |
| --- | --- | --- | --- | --- |
| Pricing | Clearer standalone framing. {citation} | Needs usage-cost validation. {citation} | Benefits from bundle context. {citation} | Needs package proof. {citation} |
| Feature | Focused coding workflow. {citation} | Advanced agentic depth. {citation} | IDE distribution breadth. {citation} | AI-native workflow. {citation} |
| Persona | Developer-led evaluators. {citation} | Advanced technical teams. {citation} | Enterprise platform buyers. {citation} | AI-forward teams. {citation} |

## Battlecard
- Win theme: lead with pricing clarity plus focused developer workflow, then qualify all
  unsupported enterprise claims. {citation}
- Objection handling: when buyers prefer Copilot, ask whether bundled familiarity or actual
  workflow productivity is the priority. {citation}
- Validation ask: collect direct customer voice, trust-center proof, and current package terms
  before finalizing a replacement recommendation. {citation}

## Source Quality & Coverage
Accepted source coverage is present, but this sample remains intentionally compact. {citation}
""".strip()


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
