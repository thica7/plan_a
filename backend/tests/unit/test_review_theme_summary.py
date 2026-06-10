from datetime import datetime

from packages.agents.analysts.logic import AnalystAgentMixin
from packages.agents.qa.logic import QualityAgentMixin
from packages.schema.api_dto import RunDetail
from packages.schema.models import (
    AnalysisPlan,
    CompetitorKB,
    CompetitorKnowledge,
    RawSource,
    ReviewThemeItem,
    ReviewThemeSummary,
)


class AnalystHarness(AnalystAgentMixin):
    pass


class AnalystQualityHarness(AnalystAgentMixin, QualityAgentMixin):
    pass


def test_review_payload_builds_praise_complaints_and_switching() -> None:
    harness = AnalystHarness()
    payload = harness._deterministic_structured_knowledge_payload(
        competitor="Cursor",
        dimension="review",
        dimension_sources=[
            {
                "id": "review-1",
                "title": "Cursor G2 reviews",
                "summary": (
                    "Customers praise fast coding workflow and complain about onboarding "
                    "friction. Some teams switch from Copilot for repository context."
                ),
                "confidence": 0.82,
                "source_type": "review_site",
            }
        ],
    )

    summary = payload["review_summary"]
    assert summary["competitor"] == "Cursor"
    assert summary["praise_themes"][0]["source_ids"] == ["review-1"]
    assert summary["complaint_themes"][0]["source_ids"] == ["review-1"]
    assert summary["switching_triggers"][0]["source_ids"] == ["review-1"]
    assert summary["sentiment_hint"] == "mixed"


def test_merge_structured_payload_preserves_review_summary() -> None:
    harness = AnalystHarness()
    detail = RunDetail(
        id="run-review",
        idempotency_key="",
        workspace_id="default-workspace",
        project_id=None,
        topic="AI coding assistant user reviews",
        status="running",
        execution_mode="demo",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        plan=AnalysisPlan(topic="AI coding", competitors=["Cursor"], dimensions=["review"]),
        competitor_knowledge={"Cursor": CompetitorKnowledge(competitor="Cursor")},
        raw_sources=[
            RawSource(
                id="review-1",
                competitor="Cursor",
                dimension="review",
                source_type="review_site",
                title="Cursor reviews",
                snippet="Users praise speed but complain about onboarding.",
                content_hash="reviewhash",
                confidence=0.82,
            )
        ],
    )
    payload = {
        "review_summary": {
            "competitor": "Cursor",
            "dimension": "review",
            "praise_themes": [
                {
                    "theme": "Speed",
                    "evidence": "Users praise speed.",
                    "source_ids": ["review-1"],
                    "confidence": 0.82,
                }
            ],
            "complaint_themes": [],
            "adoption_blockers": [],
            "switching_triggers": [],
            "persona_segments": [],
            "sentiment_hint": "positive",
            "source_ids": ["review-1"],
            "confidence": 0.82,
        }
    }

    harness._merge_structured_knowledge_payload(detail, "Cursor", "review", payload)

    assert detail.competitor_knowledge["Cursor"].review_summary.praise_themes[0].theme == "Speed"


def test_merge_structured_payload_sanitizes_review_summary_source_ids() -> None:
    harness = AnalystHarness()
    detail = RunDetail(
        id="run-review-sanitized",
        idempotency_key="",
        workspace_id="default-workspace",
        project_id=None,
        topic="AI coding assistant user reviews",
        status="running",
        execution_mode="demo",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        plan=AnalysisPlan(topic="AI coding", competitors=["Cursor"], dimensions=["review"]),
        competitor_knowledge={"Cursor": CompetitorKnowledge(competitor="Cursor")},
        raw_sources=[
            RawSource(
                id="review-1",
                competitor="Cursor",
                dimension="review",
                source_type="review_site",
                title="Cursor reviews",
                snippet="Users praise speed but complain about onboarding.",
                content_hash="reviewhash",
                confidence=0.82,
            )
        ],
    )
    payload = {
        "review_summary": {
            "competitor": "Cursor",
            "dimension": "review",
            "praise_themes": [
                {
                    "theme": "Speed",
                    "evidence": "Users praise speed.",
                    "source_ids": ["review-1", "fake-source"],
                    "confidence": 0.82,
                }
            ],
            "complaint_themes": [
                {
                    "theme": "Onboarding friction",
                    "evidence": "Users complain about onboarding.",
                    "source_ids": ["fake-source"],
                    "confidence": 0.61,
                }
            ],
            "adoption_blockers": [],
            "switching_triggers": [],
            "persona_segments": [],
            "sentiment_hint": "mixed",
            "source_ids": ["review-1", "fake-source"],
            "confidence": 0.82,
        }
    }

    harness._merge_structured_knowledge_payload(detail, "Cursor", "review", payload)

    summary = detail.competitor_knowledge["Cursor"].review_summary
    assert summary.source_ids == ["review-1"]
    assert summary.praise_themes[0].source_ids == ["review-1"]
    assert summary.complaint_themes[0].source_ids == []
    assert summary.complaint_themes[0].evidence_gap is True


def test_review_summary_only_payload_counts_as_structured_claims() -> None:
    harness = AnalystHarness()
    claims = harness._claims_from_structured_payload(
        {
            "review_summary": {
                "competitor": "Cursor",
                "dimension": "review",
                "praise_themes": [
                    {
                        "theme": "Speed",
                        "evidence": "Users praise speed.",
                        "source_ids": ["review-1"],
                        "confidence": 0.82,
                    }
                ],
                "complaint_themes": [],
                "adoption_blockers": [],
                "switching_triggers": [],
                "persona_segments": [],
                "sentiment_hint": "positive",
                "source_ids": ["review-1"],
                "confidence": 0.82,
            }
        },
        "review",
    )

    assert len(claims) == 1
    assert claims[0].source_ids == ["review-1"]
    assert "Speed" in claims[0].claim


def test_merge_review_payload_without_summary_builds_review_summary_from_sources() -> None:
    harness = AnalystHarness()
    detail = RunDetail(
        id="run-review-fallback",
        idempotency_key="",
        workspace_id="default-workspace",
        project_id=None,
        topic="AI coding assistant user reviews",
        status="running",
        execution_mode="demo",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        plan=AnalysisPlan(topic="AI coding", competitors=["Cursor"], dimensions=["review"]),
        competitor_knowledge={"Cursor": CompetitorKnowledge(competitor="Cursor")},
        raw_sources=[
            RawSource(
                id="review-1",
                competitor="Cursor",
                dimension="review",
                source_type="review_site",
                title="Cursor reviews",
                snippet="Users praise speed but complain about onboarding.",
                content_hash="reviewhash",
                confidence=0.82,
            )
        ],
    )

    harness._merge_structured_knowledge_payload(detail, "Cursor", "review", {})

    summary = detail.competitor_knowledge["Cursor"].review_summary
    assert summary.praise_themes[0].source_ids == ["review-1"]
    assert detail.competitor_kbs["Cursor"].slices["review"]


def test_non_review_payload_sanitizes_supplied_review_summary_source_ids() -> None:
    harness = AnalystHarness()
    detail = RunDetail(
        id="run-feature-review-summary",
        idempotency_key="",
        workspace_id="default-workspace",
        project_id=None,
        topic="AI coding assistant features",
        status="running",
        execution_mode="demo",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        plan=AnalysisPlan(topic="AI coding", competitors=["Cursor"], dimensions=["feature"]),
        competitor_knowledge={"Cursor": CompetitorKnowledge(competitor="Cursor")},
        raw_sources=[
            RawSource(
                id="feature-1",
                competitor="Cursor",
                dimension="feature",
                source_type="vendor_docs",
                title="Cursor features",
                snippet="Cursor has repository context.",
                content_hash="featurehash",
                confidence=0.76,
            )
        ],
    )
    payload = {
        "review_summary": {
            "competitor": "Cursor",
            "dimension": "feature",
            "praise_themes": [
                {
                    "theme": "Repository context",
                    "evidence": "Users praise repository context.",
                    "source_ids": ["feature-1", "fake-source"],
                    "confidence": 0.76,
                }
            ],
            "complaint_themes": [
                {
                    "theme": "Fake-only complaint",
                    "evidence": "This should become an evidence gap.",
                    "source_ids": ["fake-source"],
                    "confidence": 0.5,
                }
            ],
            "adoption_blockers": [],
            "switching_triggers": [],
            "persona_segments": [],
            "sentiment_hint": "mixed",
            "source_ids": ["feature-1", "fake-source"],
            "confidence": 0.76,
        }
    }

    harness._merge_structured_knowledge_payload(detail, "Cursor", "feature", payload)

    summary = detail.competitor_knowledge["Cursor"].review_summary
    assert summary.source_ids == ["feature-1"]
    assert summary.praise_themes[0].source_ids == ["feature-1"]
    assert summary.complaint_themes[0].source_ids == []
    assert summary.complaint_themes[0].evidence_gap is True


def test_merge_repairs_uncited_review_items_before_validation() -> None:
    harness = AnalystHarness()
    detail = RunDetail(
        id="run-review-gap-repair",
        idempotency_key="",
        workspace_id="default-workspace",
        project_id=None,
        topic="AI coding assistant user reviews",
        status="running",
        execution_mode="demo",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        plan=AnalysisPlan(topic="AI coding", competitors=["Cursor"], dimensions=["review"]),
        competitor_knowledge={"Cursor": CompetitorKnowledge(competitor="Cursor")},
        raw_sources=[
            RawSource(
                id="review-1",
                competitor="Cursor",
                dimension="review",
                source_type="review_site",
                title="Cursor reviews",
                snippet="Users praise speed.",
                content_hash="reviewhash",
                confidence=0.82,
            )
        ],
    )
    payload = {
        "review_summary": {
            "competitor": "Cursor",
            "dimension": "review",
            "praise_themes": [
                {
                    "theme": "Uncited praise",
                    "evidence": "Users praise the workflow.",
                    "confidence": 0.4,
                }
            ],
            "complaint_themes": [],
            "adoption_blockers": [],
            "switching_triggers": [],
            "persona_segments": [],
            "sentiment_hint": "positive",
            "source_ids": [],
            "confidence": 0.4,
        }
    }

    harness._merge_structured_knowledge_payload(detail, "Cursor", "review", payload)

    item = detail.competitor_knowledge["Cursor"].review_summary.praise_themes[0]
    assert item.theme == "Uncited praise"
    assert item.source_ids == []
    assert item.evidence_gap is True


def test_qa_accepts_review_summary_without_requiring_feature_tree_nodes() -> None:
    detail = RunDetail(
        id="run-review-qa",
        idempotency_key="",
        workspace_id="default-workspace",
        project_id=None,
        topic="AI coding assistant user reviews",
        status="running",
        execution_mode="demo",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        plan=AnalysisPlan(topic="AI coding", competitors=["Cursor"], dimensions=["review"]),
        competitor_kbs={
            "Cursor": CompetitorKB(
                competitor="Cursor",
                slices={"review": ["Users praise speed. [source:review-1]"]},
                sources=["review-1"],
                confidence=0.82,
            )
        },
        competitor_knowledge={
            "Cursor": CompetitorKnowledge(
                competitor="Cursor",
                review_summary=ReviewThemeSummary(
                    competitor="Cursor",
                    dimension="review",
                    praise_themes=[
                        ReviewThemeItem(
                            theme="Speed",
                            evidence="Users praise speed.",
                            source_ids=["review-1"],
                            confidence=0.82,
                        )
                    ],
                    source_ids=["review-1"],
                    sentiment_hint="positive",
                    confidence=0.82,
                ),
                source_ids=["review-1"],
                confidence=0.82,
            )
        },
        raw_sources=[
            RawSource(
                id="review-1",
                competitor="Cursor",
                dimension="review",
                source_type="review_site",
                title="Cursor reviews",
                snippet="Users praise speed.",
                content_hash="reviewhash",
                confidence=0.82,
            )
        ],
    )

    issues = AnalystQualityHarness()._build_structured_knowledge_issues(detail, [])

    assert not any("feature_tree.nodes" in issue.problem for issue in issues)
    assert not any(
        issue.severity == "blocker"
        and issue.detected_by == "schema"
        and issue.target_subagent == "review"
        for issue in issues
    )
