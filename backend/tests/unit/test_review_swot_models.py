import pytest
from pydantic import ValidationError

from packages.schema.models import (
    CompetitorKnowledge,
    ReviewThemeItem,
    ReviewThemeSummary,
    SWOTAnalysis,
    SWOTItem,
)


def test_competitor_knowledge_carries_review_and_swot_defaults() -> None:
    knowledge = CompetitorKnowledge(competitor="Cursor")

    assert knowledge.review_summary.competitor == ""
    assert knowledge.review_summary.praise_themes == []
    assert knowledge.swot_analysis.competitor == ""
    assert knowledge.swot_analysis.strengths == []


def test_review_theme_summary_requires_cited_items() -> None:
    item = ReviewThemeItem(
        theme="Fast local workflow",
        evidence="Users praise the fast edit loop.",
        source_ids=["review-1"],
        confidence=0.82,
    )
    summary = ReviewThemeSummary(
        competitor="Cursor",
        praise_themes=[item],
        sentiment_hint="positive",
        source_ids=["review-1"],
        confidence=0.82,
    )

    assert summary.praise_themes[0].source_ids == ["review-1"]
    assert summary.sentiment_hint == "positive"


def test_review_theme_items_mark_uncited_claims_as_gaps() -> None:
    with pytest.raises(ValidationError):
        ReviewThemeItem(theme="Uncited")

    gap = ReviewThemeItem(theme="Uncited", evidence_gap=True)

    assert gap.source_ids == []
    assert gap.evidence_gap is True


def test_swot_items_mark_uncited_claims_as_gaps() -> None:
    cited = SWOTItem(
        text="Clear pricing supports direct comparison.",
        source_ids=["pricing-1"],
        confidence=0.76,
    )
    gap = SWOTItem(
        text="Review volume is insufficient for sentiment claims.",
        evidence_gap=True,
    )
    swot = SWOTAnalysis(competitor="Cursor", strengths=[cited], weaknesses=[gap])

    assert swot.strengths[0].evidence_gap is False
    assert swot.weaknesses[0].source_ids == []
    assert swot.weaknesses[0].evidence_gap is True


def test_swot_items_reject_uncited_non_gap_claims() -> None:
    with pytest.raises(ValidationError):
        SWOTItem(text="Uncited")

    gap = SWOTItem(text="Uncited", evidence_gap=True)

    assert gap.source_ids == []
    assert gap.evidence_gap is True
