from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.business_intel import (  # noqa: E402
    analyze_evidence_gaps,
    analyze_red_team,
    build_business_intel_plan,
    evaluate_business_qa,
    score_competitors,
)
from packages.schema.enterprise import ClaimRecord, CompetitorRecord, EvidenceRecord  # noqa: E402


def main() -> None:
    plan = build_business_intel_plan(
        topic="Cursor vs Copilot pricing comparison",
        competitors=["Cursor", "Copilot"],
        dimensions=["pricing"],
        requested_scenario_id="l1_pricing_pack",
    )
    competitors = [
        CompetitorRecord(
            id="competitor-cursor",
            workspace_id="workspace-1",
            name="Cursor",
            normalized_name="cursor",
            layer="L1",
            metadata={"homepage_verified": True},
        ),
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
        ),
        EvidenceRecord(
            id="evidence-stale",
            workspace_id="workspace-1",
            project_id="project-1",
            raw_source_id="pricing-2",
            competitor_id="competitor-cursor",
            dimension="pricing",
            source_type="webpage_verified",
            title="Old Cursor pricing",
            url="https://cursor.sh/pricing",
            snippet="Old pricing.",
            content_hash="hash-2",
            reliability_score=0.2,
            quality_label="stale",
        ),
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
        ),
        ClaimRecord(
            id="claim-unsupported",
            workspace_id="workspace-1",
            project_id="project-1",
            competitor_id="competitor-copilot",
            claim_type="pricing",
            claim_text="Copilot pricing is better.",
            evidence_ids=["missing-evidence"],
            confidence=0.4,
        ),
    ]
    qa_evaluation = evaluate_business_qa(
        project_id="project-1",
        plan=plan,
        competitors=competitors,
        evidence=evidence,
        claims=claims,
    )
    gaps = analyze_evidence_gaps(
        project_id="project-1",
        plan=plan,
        qa_evaluation=qa_evaluation,
        competitors=competitors,
        evidence=evidence,
        claims=claims,
    )
    red_team = analyze_red_team(
        project_id="project-1",
        plan=plan,
        qa_evaluation=qa_evaluation,
        competitors=competitors,
        evidence=evidence,
        claims=claims,
        report_versions=[],
    )
    scores = score_competitors(
        project_id="project-1",
        plan=plan,
        competitors=competitors,
        evidence=evidence,
        claims=claims,
    )
    payload = {
        "component": "phase3_strict",
        "ok": (
            red_team.high_severity_count >= 2
            and gaps.gap_count >= 1
            and len(scores.scores) == 2
            and gaps.framework == "pydantic-ai"
            and red_team.framework == "pydantic-ai"
        ),
        "red_team_high_severity_count": red_team.high_severity_count,
        "evidence_gap_count": gaps.gap_count,
        "competitor_score_count": len(scores.scores),
        "top_competitor_id": scores.top_competitor_id,
        "pydantic_ai_available": red_team.pydantic_ai_available and gaps.pydantic_ai_available,
    }
    print(json.dumps(payload, ensure_ascii=False))
    if not payload["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
