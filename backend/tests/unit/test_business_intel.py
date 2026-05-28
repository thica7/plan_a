from packages.business_intel import (
    build_business_intel_plan,
    evaluate_business_qa,
    list_business_qa_rules,
    list_scenario_packs,
)
from packages.business_intel.layers import assess_competitor_layer
from packages.schema.enterprise import ClaimRecord, CompetitorRecord, EvidenceRecord


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
    rules = list_business_qa_rules(layer="L1")

    assert len(packs) >= 5
    assert any(pack.id == "l1_direct_battlecard" for pack in packs)
    assert any(rule.id == "claim_has_evidence" for rule in rules)


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

    assert evaluation.finding_count == 0
    assert evaluation.passed_rules == evaluation.total_rules


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

    assert evaluation.finding_count >= 2
    assert evaluation.blocker_count >= 1
    assert {finding.rule_id for finding in evaluation.findings} >= {
        "claim_has_evidence",
        "pricing_currentness",
    }


def _competitor() -> CompetitorRecord:
    return CompetitorRecord(
        id="competitor-cursor",
        workspace_id="workspace-1",
        name="Cursor",
        normalized_name="cursor",
        layer="L1",
    )
