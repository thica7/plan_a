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
            and verify_homepage("FAKE_PRODUCT_NOT_EXISTS").verified is False
            and redo_kinds == {"collector", "writer_only", "comparator", "analyst", "full"}
        ),
        "qa_rule_count": len(rules),
        "scenario_pack_count": len(packs),
        "dynamic_scenario_id": dynamic_pack.id,
        "demo_layers": sorted(plan_layers),
        "redo_kinds": sorted(redo_kinds),
    }
    print(json.dumps(summary, ensure_ascii=False))
    if not summary["ok"]:
        raise SystemExit("Phase 2 business intel smoke failed.")


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
