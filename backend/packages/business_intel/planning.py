from __future__ import annotations

from packages.business_intel.layers import assess_competitor_layer
from packages.business_intel.qa_rules import list_business_qa_rules
from packages.business_intel.scenarios import recommend_scenario_pack, recommended_dimensions
from packages.schema.enterprise import BusinessIntelPlan


def build_business_intel_plan(
    *,
    topic: str,
    competitors: list[str],
    dimensions: list[str],
    requested_layer: str | None = None,
    requested_scenario_id: str | None = None,
) -> BusinessIntelPlan:
    layer = assess_competitor_layer(
        topic=topic,
        competitors=competitors,
        dimensions=dimensions,
        requested_layer=requested_layer,
    )
    scenario_pack = recommend_scenario_pack(
        topic=topic,
        competitors=competitors,
        dimensions=dimensions,
        requested_layer=layer.layer,
        requested_scenario_id=requested_scenario_id,
    )
    if requested_layer is None and scenario_pack.competitor_layer != layer.layer:
        layer = layer.model_copy(
            update={
                "layer": scenario_pack.competitor_layer,
                "signals": [*layer.signals, "scenario_pack_override"],
                "rationale": (
                    f"Scenario pack `{scenario_pack.id}` is optimized for "
                    f"{scenario_pack.competitor_layer} analysis."
                ),
            }
        )
    qa_rules = list_business_qa_rules(
        layer=layer.layer,
        rule_ids=scenario_pack.qa_rule_ids,
    )
    return BusinessIntelPlan(
        topic=topic,
        competitor_layer=layer,
        scenario_pack=scenario_pack,
        requested_dimensions=dimensions,
        recommended_dimensions=recommended_dimensions(scenario_pack, dimensions),
        qa_rules=qa_rules,
    )
