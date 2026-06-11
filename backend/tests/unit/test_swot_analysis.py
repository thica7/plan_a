from datetime import datetime

from packages.agents.comparator.logic import ComparatorAgentMixin
from packages.schema.api_dto import RunDetail
from packages.schema.models import (
    AnalysisPlan,
    ComparisonCell,
    ComparisonMatrix,
    CompetitorKnowledge,
    KnowledgeClaim,
    ReviewThemeItem,
    ReviewThemeSummary,
)


class ComparatorHarness(ComparatorAgentMixin):
    pass


def test_swot_builder_uses_matrix_and_review_themes() -> None:
    harness = ComparatorHarness()
    cursor = CompetitorKnowledge(
        competitor="Cursor",
        source_ids=["knowledge-1"],
        review_summary=ReviewThemeSummary(
            competitor="Cursor",
            praise_themes=[
                ReviewThemeItem(
                    theme="Fast workflow",
                    evidence="Users praise fast repository-aware editing.",
                    source_ids=["review-1"],
                    confidence=0.82,
                )
            ],
            complaint_themes=[
                ReviewThemeItem(
                    theme="Onboarding friction",
                    evidence="Users complain onboarding takes effort.",
                    source_ids=["review-2"],
                    confidence=0.64,
                )
            ],
            adoption_blockers=[
                ReviewThemeItem(
                    theme="Procurement blocker",
                    evidence="Security review slows team adoption.",
                    source_ids=["review-3"],
                    confidence=0.7,
                )
            ],
            switching_triggers=[
                ReviewThemeItem(
                    theme="Switching trigger",
                    evidence="Teams switch for repository context.",
                    source_ids=["review-4"],
                    confidence=0.78,
                )
            ],
            source_ids=["review-1", "review-2", "review-3", "review-4"],
            confidence=0.74,
        ),
    )
    cursor.user_personas.summary_claims = [
        KnowledgeClaim(
            claim="Developer teams adopt Cursor for repository-aware coding.",
            source_ids=["persona-1"],
            confidence=0.74,
        )
    ]
    copilot = CompetitorKnowledge(competitor="Copilot")
    detail = RunDetail(
        id="run-swot",
        idempotency_key="",
        workspace_id="default-workspace",
        project_id=None,
        topic="AI coding assistant reviews",
        status="running",
        execution_mode="demo",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        plan=AnalysisPlan(
            topic="AI coding",
            competitors=["Cursor", "Copilot"],
            dimensions=["review", "enterprise"],
        ),
        competitor_knowledge={"Cursor": cursor, "Copilot": copilot},
        comparison_matrix=ComparisonMatrix(
            competitors=["Cursor", "Copilot"],
            dimensions=["review", "enterprise"],
            cells=[
                ComparisonCell(
                    competitor="Cursor",
                    dimension="review",
                    value="Strong review signal.",
                    source_ids=["matrix-review-1"],
                    confidence=0.82,
                ),
                ComparisonCell(
                    competitor="Copilot",
                    dimension="review",
                    value="Weaker review signal.",
                    source_ids=["matrix-review-2"],
                    confidence=0.51,
                ),
                ComparisonCell(
                    competitor="Cursor",
                    dimension="enterprise",
                    value="Needs more enterprise controls.",
                    source_ids=["matrix-enterprise-1"],
                    confidence=0.6,
                ),
                ComparisonCell(
                    competitor="Copilot",
                    dimension="enterprise",
                    value="Stronger enterprise controls.",
                    source_ids=["matrix-enterprise-2"],
                    confidence=0.8,
                ),
            ],
            winner_by_dimension={"review": "Cursor", "enterprise": "Copilot"},
        ),
    )

    harness._refresh_swot_analyses(detail)

    swot = detail.competitor_knowledge["Cursor"].swot_analysis
    assert swot.competitor == "Cursor"
    assert any("review" in item.text for item in swot.strengths)
    assert any(item.text == "Fast workflow" for item in swot.strengths)
    assert any("enterprise" in item.text for item in swot.weaknesses)
    assert any(item.text == "Onboarding friction" for item in swot.weaknesses)
    assert any(item.text == "Procurement blocker" for item in swot.weaknesses)
    assert swot.opportunities[0].text == "Switching trigger"
    assert swot.threats[0].evidence_gap is True
    assert all(item.source_ids for item in swot.strengths + swot.weaknesses + swot.opportunities)
    assert swot.source_ids == [
        "knowledge-1",
        "matrix-review-1",
        "matrix-enterprise-1",
        "review-1",
        "review-2",
        "review-3",
        "review-4",
    ]
    assert 0 < swot.confidence <= 1


def test_swot_builder_uses_persona_claim_for_opportunity_when_review_trigger_missing() -> None:
    harness = ComparatorHarness()
    knowledge = CompetitorKnowledge(competitor="Cursor")
    knowledge.user_personas.summary_claims = [
        KnowledgeClaim(
            claim="Developer teams adopt Cursor for repository-aware coding.",
            source_ids=["persona-1"],
            confidence=0.74,
        )
    ]
    detail = RunDetail(
        id="run-swot-persona",
        idempotency_key="",
        workspace_id="default-workspace",
        project_id=None,
        topic="AI coding assistant reviews",
        status="running",
        execution_mode="demo",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        plan=AnalysisPlan(
            topic="AI coding",
            competitors=["Cursor"],
            dimensions=["review"],
        ),
        competitor_knowledge={"Cursor": knowledge},
        comparison_matrix=ComparisonMatrix(
            competitors=["Cursor"],
            dimensions=["review"],
            cells=[
                ComparisonCell(
                    competitor="Cursor",
                    dimension="review",
                    value="Strong review signal.",
                    source_ids=["matrix-review-1"],
                    confidence=0.82,
                )
            ],
            winner_by_dimension={"review": "Cursor"},
        ),
    )

    harness._refresh_swot_analyses(detail)

    swot = detail.competitor_knowledge["Cursor"].swot_analysis
    assert swot.opportunities[0].text == (
        "Developer teams adopt Cursor for repository-aware coding."
    )
    assert swot.opportunities[0].source_ids == ["persona-1"]


def test_swot_builder_ignores_unknown_and_tie_matrix_winners_for_weaknesses() -> None:
    harness = ComparatorHarness()
    cursor = CompetitorKnowledge(competitor="Cursor")
    copilot = CompetitorKnowledge(competitor="Copilot")
    detail = RunDetail(
        id="run-swot-unknown-winner",
        idempotency_key="",
        workspace_id="default-workspace",
        project_id=None,
        topic="AI coding assistant reviews",
        status="running",
        execution_mode="demo",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        plan=AnalysisPlan(
            topic="AI coding",
            competitors=["Cursor", "Copilot"],
            dimensions=["review", "pricing", "enterprise"],
        ),
        competitor_knowledge={"Cursor": cursor, "Copilot": copilot},
        comparison_matrix=ComparisonMatrix(
            competitors=["Cursor", "Copilot"],
            dimensions=["review", "pricing", "enterprise"],
            cells=[
                ComparisonCell(
                    competitor="Cursor",
                    dimension="review",
                    value="Review evidence is inconclusive.",
                    source_ids=["matrix-review-1"],
                    confidence=0.52,
                ),
                ComparisonCell(
                    competitor="Cursor",
                    dimension="pricing",
                    value="Pricing evidence is tied.",
                    source_ids=["matrix-pricing-1"],
                    confidence=0.58,
                ),
                ComparisonCell(
                    competitor="Cursor",
                    dimension="enterprise",
                    value="Enterprise evidence is also tied.",
                    source_ids=["matrix-enterprise-1"],
                    confidence=0.6,
                ),
                ComparisonCell(
                    competitor="Copilot",
                    dimension="review",
                    value="Review evidence is inconclusive.",
                    source_ids=["matrix-review-2"],
                    confidence=0.52,
                ),
            ],
            winner_by_dimension={
                "review": "HallucinatedVendor",
                "pricing": " tie ",
                "enterprise": "TIE",
            },
        ),
    )

    harness._refresh_swot_analyses(detail)

    cursor_weaknesses = detail.competitor_knowledge["Cursor"].swot_analysis.weaknesses
    assert cursor_weaknesses == []
    swot_text = " ".join(
        item.text
        for item in (
            detail.competitor_knowledge["Cursor"].swot_analysis.strengths
            + detail.competitor_knowledge["Cursor"].swot_analysis.weaknesses
            + detail.competitor_knowledge["Cursor"].swot_analysis.opportunities
            + detail.competitor_knowledge["Cursor"].swot_analysis.threats
        )
    )
    assert "HallucinatedVendor" not in swot_text
