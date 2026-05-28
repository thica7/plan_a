from __future__ import annotations

from packages.business_intel.layers import assess_competitor_layer
from packages.schema.enterprise import ScenarioPack

SCENARIO_PACKS: tuple[ScenarioPack, ...] = (
    ScenarioPack(
        id="l1_direct_battlecard",
        name="Direct battlecard",
        description="Direct replacement comparison for sales, product, and pricing decisions.",
        competitor_layer="L1",
        required_dimensions=["pricing", "feature", "security"],
        optional_dimensions=["integrations", "persona"],
        analyst_questions=[
            "Where is each competitor clearly stronger than us?",
            "Which claims need first-party or official-source proof?",
            "What objections should sales prepare for?",
        ],
        evidence_requirements=[
            "At least one official or verified source per competitor.",
            "Pricing claims must cite current pricing or plan documentation.",
        ],
        qa_rule_ids=["coverage_min_verified", "claim_has_evidence", "pricing_currentness"],
    ),
    ScenarioPack(
        id="l1_pricing_pack",
        name="Pricing and packaging",
        description="Focused pricing-packaging comparison for monetization decisions.",
        competitor_layer="L1",
        required_dimensions=["pricing"],
        optional_dimensions=["feature", "persona"],
        analyst_questions=[
            "Which plan gates drive perceived value?",
            "Which pricing claims are stale or ambiguous?",
            "Where do free, pro, and enterprise tiers diverge?",
        ],
        evidence_requirements=[
            "Pricing rows require official pricing-page evidence.",
            "Enterprise-only claims need explicit qualification.",
        ],
        qa_rule_ids=["claim_has_evidence", "pricing_currentness"],
    ),
    ScenarioPack(
        id="l2_adjacent_workflow",
        name="Adjacent workflow watch",
        description=(
            "Adjacent alternative analysis for workflow expansion and ecosystem positioning."
        ),
        competitor_layer="L2",
        required_dimensions=["feature", "integrations"],
        optional_dimensions=["pricing", "persona", "security"],
        analyst_questions=[
            "Which adjacent workflow could absorb our core use case?",
            "Which integrations change switching cost?",
            "Which buyer personas overlap?",
        ],
        evidence_requirements=[
            "Cross-category claims must identify the workflow overlap.",
            "Integration claims need product documentation or marketplace evidence.",
        ],
        qa_rule_ids=["coverage_min_verified", "cross_competitor_matrix"],
    ),
    ScenarioPack(
        id="l3_market_landscape",
        name="Market landscape",
        description="Category-level landscape for segmentation, trend, and benchmark decisions.",
        competitor_layer="L3",
        required_dimensions=["feature", "persona", "market"],
        optional_dimensions=["pricing", "integrations", "security"],
        analyst_questions=[
            "Which competitor clusters define the category?",
            "What trend signals affect product strategy?",
            "Where are evidence gaps too broad for a direct battlecard?",
        ],
        evidence_requirements=[
            "Landscape claims should cite multiple independent sources when possible.",
            "Segment labels must be derived from evidence, not only model judgment.",
        ],
        qa_rule_ids=["coverage_min_verified", "cross_competitor_matrix", "landscape_breadth"],
    ),
    ScenarioPack(
        id="enterprise_risk_review",
        name="Enterprise readiness review",
        description=(
            "Enterprise buying-risk review across security, governance, and deployment readiness."
        ),
        competitor_layer="L2",
        required_dimensions=["security", "integrations"],
        optional_dimensions=["pricing", "feature"],
        analyst_questions=[
            "Which enterprise controls are officially documented?",
            "Where are security or compliance claims unsupported?",
            "What adoption risks matter to an enterprise buyer?",
        ],
        evidence_requirements=[
            "Security claims require official docs, trust-center, or policy evidence.",
            "Unverified enterprise claims should remain proposed until reviewed.",
        ],
        qa_rule_ids=["coverage_min_verified", "security_official_source", "claim_has_evidence"],
    ),
)


def list_scenario_packs() -> list[ScenarioPack]:
    return list(SCENARIO_PACKS)


def get_scenario_pack(scenario_id: str) -> ScenarioPack | None:
    return next((pack for pack in SCENARIO_PACKS if pack.id == scenario_id), None)


def recommend_scenario_pack(
    *,
    topic: str,
    competitors: list[str],
    dimensions: list[str],
    requested_layer: str | None = None,
    requested_scenario_id: str | None = None,
) -> ScenarioPack:
    if requested_scenario_id:
        pack = get_scenario_pack(requested_scenario_id)
        if pack is not None:
            return pack

    text = " ".join([topic, *dimensions]).casefold()
    if "pricing" in text and "market" not in text and len(competitors) <= 3:
        return _pack("l1_pricing_pack")
    if "security" in text or "enterprise" in text or "compliance" in text:
        return _pack("enterprise_risk_review")

    layer = assess_competitor_layer(
        topic=topic,
        competitors=competitors,
        dimensions=dimensions,
        requested_layer=requested_layer,
    ).layer
    if layer == "L3":
        return _pack("l3_market_landscape")
    if layer == "L2":
        return _pack("l2_adjacent_workflow")
    return _pack("l1_direct_battlecard")


def recommended_dimensions(pack: ScenarioPack, requested_dimensions: list[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for dimension in [*requested_dimensions, *pack.required_dimensions, *pack.optional_dimensions]:
        key = dimension.casefold().strip()
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(dimension)
    return merged


def _pack(scenario_id: str) -> ScenarioPack:
    pack = get_scenario_pack(scenario_id)
    if pack is None:
        raise ValueError(f"Unknown scenario pack: {scenario_id}")
    return pack
