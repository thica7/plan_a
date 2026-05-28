from __future__ import annotations

from packages.schema.enterprise import BusinessQAFinding
from packages.schema.models import RedoScope

RULE_REDO_KIND = {
    "coverage_min_verified": "collector",
    "claim_has_evidence": "writer_only",
    "pricing_currentness": "collector",
    "cross_competitor_matrix": "comparator",
    "security_official_source": "analyst",
    "landscape_breadth": "full",
    "homepage_verified": "collector",
    "source_reliability_min": "collector",
}


def business_findings_to_redo_scopes(findings: list[BusinessQAFinding]) -> list[RedoScope]:
    scopes: list[RedoScope] = []
    seen: set[tuple[str, str | None, str | None]] = set()
    for finding in findings:
        kind = RULE_REDO_KIND.get(finding.rule_id, "collector")
        key = (kind, finding.dimension, finding.competitor_id)
        if key in seen:
            continue
        seen.add(key)
        scopes.append(
            RedoScope(
                kind=kind,  # type: ignore[arg-type]
                target_subagent=finding.dimension,
                target_competitor=finding.competitor_name,
                target_competitors=[finding.competitor_name]
                if finding.competitor_name
                else [],
                rationale=finding.recommendation or finding.message,
            )
        )
    return scopes
