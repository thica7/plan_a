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


def test_non_review_payload_preserves_existing_review_summary_citations() -> None:
    harness = AnalystHarness()
    detail = RunDetail(
        id="run-feature-after-persona",
        idempotency_key="",
        workspace_id="default-workspace",
        project_id=None,
        topic="AI coding assistant",
        status="running",
        execution_mode="demo",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        plan=AnalysisPlan(
            topic="AI coding",
            competitors=["Cursor"],
            dimensions=["persona", "feature"],
        ),
        competitor_knowledge={"Cursor": CompetitorKnowledge(competitor="Cursor")},
        raw_sources=[
            RawSource(
                id="persona-1",
                competitor="Cursor",
                dimension="persona",
                source_type="review_site",
                title="Cursor persona reviews",
                snippet="Developers praise Cursor for fast coding workflow.",
                content_hash="personahash",
                confidence=0.82,
            ),
            RawSource(
                id="feature-1",
                competitor="Cursor",
                dimension="feature",
                source_type="vendor_docs",
                title="Cursor features",
                snippet="Cursor provides repository context.",
                content_hash="featurehash",
                confidence=0.76,
            ),
        ],
    )
    persona_payload = {
        "user_personas": {
            "segments": [
                {
                    "name": "Developers",
                    "role": "Developer",
                    "company_size": "Team",
                    "pain_points": [],
                    "use_cases": ["coding workflow"],
                    "claims": [
                        {
                            "claim": "Developers use Cursor for faster coding workflow.",
                            "source_ids": ["persona-1"],
                            "confidence": 0.82,
                        }
                    ],
                }
            ],
            "summary_claims": [],
        },
        "review_summary": {
            "competitor": "Cursor",
            "dimension": "persona",
            "praise_themes": [
                {
                    "theme": "Fast coding workflow",
                    "evidence": "Developers praise Cursor for fast coding workflow.",
                    "source_ids": ["persona-1"],
                    "confidence": 0.82,
                }
            ],
            "complaint_themes": [],
            "adoption_blockers": [],
            "switching_triggers": [],
            "persona_segments": ["Developers"],
            "sentiment_hint": "positive",
            "source_ids": ["persona-1"],
            "confidence": 0.82,
        },
    }
    feature_payload = {
        "feature_tree": {
            "nodes": [
                {
                    "name": "Repository context",
                    "description": "Cursor provides repository context.",
                    "claims": [
                        {
                            "claim": "Cursor provides repository context.",
                            "source_ids": ["feature-1"],
                            "confidence": 0.76,
                        }
                    ],
                    "children": [],
                }
            ],
            "summary_claims": [],
        }
    }

    harness._merge_structured_knowledge_payload(detail, "Cursor", "persona", persona_payload)
    harness._merge_structured_knowledge_payload(detail, "Cursor", "feature", feature_payload)

    item = detail.competitor_knowledge["Cursor"].review_summary.praise_themes[0]
    assert item.source_ids == ["persona-1"]
    assert item.evidence_gap is False
    assert detail.competitor_knowledge["Cursor"].review_summary.source_ids == ["persona-1"]


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


def test_merge_replaces_empty_persona_review_summary_with_source_theme() -> None:
    harness = AnalystHarness()
    detail = RunDetail(
        id="run-windsurf-empty-review-summary",
        idempotency_key="",
        workspace_id="default-workspace",
        project_id=None,
        topic="AI coding assistant persona",
        status="running",
        execution_mode="demo",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        plan=AnalysisPlan(topic="AI coding", competitors=["Windsurf"], dimensions=["persona"]),
        competitor_knowledge={"Windsurf": CompetitorKnowledge(competitor="Windsurf")},
        raw_sources=[
            RawSource(
                id="persona-1",
                competitor="Windsurf",
                dimension="persona",
                source_type="interview_record",
                title="Windsurf target-user proxy interview note",
                snippet=(
                    "Buyers evaluate persona through fit with workflow, onboarding effort, "
                    "and switching risk."
                ),
                content_hash="windsurf-persona-hash",
                confidence=0.56,
            )
        ],
    )
    payload = {
        "user_personas": {
            "segments": [
                {
                    "name": "Windsurf Cascade IDE developers",
                    "role": "technical buyer",
                    "company_size": "unknown",
                    "pain_points": ["developer onboarding"],
                    "use_cases": ["agentic coding"],
                    "claims": [
                        {
                            "claim": (
                                "Buyers evaluate Windsurf through workflow fit, "
                                "onboarding effort, and switching risk."
                            ),
                            "source_ids": ["persona-1"],
                            "confidence": 0.56,
                        }
                    ],
                }
            ],
            "summary_claims": [],
        },
        "review_summary": {
            "competitor": "Windsurf",
            "dimension": "persona",
            "praise_themes": [],
            "complaint_themes": [],
            "adoption_blockers": [],
            "switching_triggers": [],
            "persona_segments": [],
            "sentiment_hint": "unknown",
            "source_ids": ["persona-1"],
            "confidence": 0.56,
        },
    }

    harness._merge_structured_knowledge_payload(detail, "Windsurf", "persona", payload)

    summary = detail.competitor_knowledge["Windsurf"].review_summary
    cited_items = [
        item
        for item in [
            *summary.praise_themes,
            *summary.complaint_themes,
            *summary.adoption_blockers,
            *summary.switching_triggers,
        ]
        if item.source_ids
    ]
    assert cited_items
    assert any(item.source_ids == ["persona-1"] for item in cited_items)


def test_merge_empty_persona_review_summary_uses_all_persona_sources() -> None:
    harness = AnalystHarness()
    detail = RunDetail(
        id="run-cursor-empty-review-summary",
        idempotency_key="",
        workspace_id="default-workspace",
        project_id=None,
        topic="AI coding assistant persona",
        status="running",
        execution_mode="demo",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        plan=AnalysisPlan(topic="AI coding", competitors=["Cursor"], dimensions=["persona"]),
        competitor_knowledge={"Cursor": CompetitorKnowledge(competitor="Cursor")},
        raw_sources=[
            RawSource(
                id="homepage-1",
                competitor="Cursor",
                dimension="persona",
                source_type="webpage_verified",
                title="Cursor: AI coding agent",
                snippet="Cursor is used by teams and enterprise engineers.",
                content_hash="homepage-hash",
                confidence=0.96,
            ),
            RawSource(
                id="customers-1",
                competitor="Cursor",
                dimension="persona",
                source_type="webpage_verified",
                title="Cursor customers",
                snippet="Cursor has become the preferred IDE for most Coinbase developers.",
                content_hash="customers-hash",
                confidence=0.96,
            ),
            RawSource(
                id="interview-1",
                competitor="Cursor",
                dimension="persona",
                source_type="interview_record",
                title="Cursor persona interview synthesis",
                snippet=(
                    "Respondents discussed onboarding effort, workflow fit uncertainty, "
                    "and switching cost."
                ),
                content_hash="interview-hash",
                confidence=0.62,
            ),
        ],
    )
    payload = {
        "user_personas": {
            "segments": [
                {
                    "name": "Enterprise engineering teams",
                    "role": "Engineer",
                    "company_size": "Enterprise",
                    "pain_points": [],
                    "use_cases": ["coding"],
                    "claims": [
                        {
                            "claim": "Cursor is used by teams and enterprise engineers.",
                            "source_ids": ["homepage-1"],
                            "confidence": 0.96,
                        }
                    ],
                }
            ],
            "summary_claims": [],
        },
        "review_summary": {
            "competitor": "Cursor",
            "dimension": "persona",
            "praise_themes": [],
            "complaint_themes": [],
            "adoption_blockers": [],
            "switching_triggers": [],
            "persona_segments": ["teams", "enterprise"],
            "sentiment_hint": "unknown",
            "source_ids": ["homepage-1"],
            "confidence": 0.0,
        },
    }

    harness._merge_structured_knowledge_payload(detail, "Cursor", "persona", payload)

    summary = detail.competitor_knowledge["Cursor"].review_summary
    source_ids = {
        source_id
        for item in [
            *summary.praise_themes,
            *summary.complaint_themes,
            *summary.adoption_blockers,
            *summary.switching_triggers,
        ]
        for source_id in item.source_ids
    }
    assert "customers-1" in source_ids
    assert "interview-1" in source_ids


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
