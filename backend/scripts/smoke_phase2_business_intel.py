from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.business_intel import (  # noqa: E402
    build_business_intel_plan,
    business_findings_to_redo_scopes,
    generate_dynamic_scenario_pack,
    list_business_qa_rules,
    list_scenario_packs,
)
from packages.business_intel.homepage import verify_homepage  # noqa: E402
from packages.schema.enterprise import BusinessQAFinding  # noqa: E402

PRESET_CASES = (
    {
        "id": "l1_direct_battlecard",
        "topic": "Cursor vs Copilot battlecard",
        "competitors": ["Cursor", "Copilot"],
        "dimensions": ["pricing", "feature"],
        "layer": "L1",
    },
    {
        "id": "l2_adjacent_workflow",
        "topic": "Enterprise AI search workflow alternatives",
        "competitors": ["Glean", "Coveo", "Elastic"],
        "dimensions": ["feature", "integrations"],
        "layer": "L2",
    },
    {
        "id": "l3_market_landscape",
        "topic": "AI coding assistant market landscape",
        "competitors": ["Cursor", "Copilot", "Windsurf", "Tabnine", "Codeium"],
        "dimensions": ["market", "persona"],
        "layer": "L3",
    },
)


def main() -> None:
    rules = list_business_qa_rules()
    packs = list_scenario_packs()
    dynamic_pack = generate_dynamic_scenario_pack(
        topic="AI meeting assistant market landscape",
        competitors=["Fathom", "Otter", "Fireflies", "Avoma"],
        dimensions=["market"],
    )
    plan_layers = {
        build_business_intel_plan(
            topic="Cursor vs Copilot pricing battlecard",
            competitors=["Cursor", "Copilot"],
            dimensions=["pricing"],
        ).competitor_layer.layer,
        build_business_intel_plan(
            topic="Enterprise AI search security review",
            competitors=["Glean", "Coveo"],
            dimensions=["security"],
        ).competitor_layer.layer,
        build_business_intel_plan(
            topic="AI coding assistant market landscape",
            competitors=["Cursor", "Copilot", "Windsurf", "Tabnine", "Codeium"],
            dimensions=["market"],
        ).competitor_layer.layer,
    }
    preset_runs = [_build_preset_summary(case) for case in PRESET_CASES]
    route_findings = [
        _finding("coverage_min_verified"),
        _finding("claim_has_evidence"),
        _finding("cross_competitor_matrix"),
        _finding("security_official_source"),
        _finding("landscape_breadth"),
    ]
    redo_kinds = {scope.kind for scope in business_findings_to_redo_scopes(route_findings)}
    summary = {
        "component": "phase2_business_intel",
        "ok": bool(
            len(rules) == 8
            and len(packs) >= 5
            and dynamic_pack.is_dynamic
            and plan_layers == {"L1", "L2", "L3"}
            and all(item["ok"] for item in preset_runs)
            and verify_homepage("FAKE_PRODUCT_NOT_EXISTS").verified is False
            and redo_kinds == {"collector", "writer_only", "comparator", "analyst", "full"}
        ),
        "qa_rule_count": len(rules),
        "scenario_pack_count": len(packs),
        "dynamic_scenario_id": dynamic_pack.id,
        "demo_layers": sorted(plan_layers),
        "preset_runs": preset_runs,
        "redo_kinds": sorted(redo_kinds),
    }
    print(json.dumps(summary, ensure_ascii=False))
    if not summary["ok"]:
        raise SystemExit("Phase 2 business intel smoke failed.")


def _build_preset_summary(case: dict[str, object]) -> dict[str, object]:
    plan = build_business_intel_plan(
        topic=str(case["topic"]),
        competitors=list(case["competitors"]),  # type: ignore[arg-type]
        dimensions=list(case["dimensions"]),  # type: ignore[arg-type]
        requested_layer=str(case["layer"]),
        requested_scenario_id=str(case["id"]),
    )
    required_dimensions = set(plan.scenario_pack.required_dimensions)
    recommended_dimensions = set(plan.recommended_dimensions)
    return {
        "scenario_id": plan.scenario_pack.id,
        "layer": plan.competitor_layer.layer,
        "qa_rule_count": len(plan.qa_rules),
        "recommended_dimensions": plan.recommended_dimensions,
        "ok": (
            plan.scenario_pack.id == case["id"]
            and plan.competitor_layer.layer == case["layer"]
            and bool(plan.qa_rules)
            and required_dimensions <= recommended_dimensions
        ),
    }


def _finding(rule_id: str) -> BusinessQAFinding:
    return BusinessQAFinding(
        id=f"finding-{rule_id}",
        rule_id=rule_id,
        rule_name=rule_id,
        severity="warn",
        dimension="pricing",
        message=f"{rule_id} finding",
        recommendation=f"Redo for {rule_id}",
    )


if __name__ == "__main__":
    main()
