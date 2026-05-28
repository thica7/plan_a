from packages.business_intel import (
    build_business_intel_plan,
    list_business_qa_rules,
    list_scenario_packs,
)
from packages.business_intel.layers import assess_competitor_layer


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
