from datetime import datetime

from packages.agents.analysts.logic import AnalystAgentMixin
from packages.schema.api_dto import RunDetail
from packages.schema.models import AnalysisPlan, CompetitorKnowledge, RawSource


class AnalystHarness(AnalystAgentMixin):
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
