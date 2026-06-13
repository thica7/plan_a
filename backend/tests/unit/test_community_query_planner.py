from __future__ import annotations

from packages.community.query_planner import build_community_queries


def test_pricing_queries_include_forum_reddit_and_github_discussion() -> None:
    queries = build_community_queries(
        competitor="Cursor",
        dimension="pricing",
        topic="AI coding assistants",
        limit=4,
    )

    assert queries == [
        "Cursor pricing usage limit reddit AI coding assistants",
        "Cursor pricing usage limit forum AI coding assistants",
        "Cursor billing quota GitHub discussion AI coding assistants",
        "Cursor hidden limit cost overage AI coding assistants",
    ]


def test_feature_queries_include_issue_and_limitation_language() -> None:
    queries = build_community_queries(
        competitor="GitHub Copilot",
        dimension="feature",
        topic="AI coding assistants",
        limit=3,
    )

    assert queries == [
        "GitHub Copilot context window issue discussion AI coding assistants",
        "GitHub Copilot agent mode complaints reddit AI coding assistants",
        "GitHub Copilot feature limitation forum AI coding assistants",
    ]


def test_persona_queries_include_adoption_and_switching_language() -> None:
    queries = build_community_queries(
        competitor="Claude Code",
        dimension="persona",
        topic="AI coding assistants",
        limit=3,
    )

    assert queries == [
        "Claude Code user reviews pros cons reddit AI coding assistants",
        "Claude Code switched from Claude Code to alternative AI coding assistants",
        "Claude Code adoption blockers enterprise developers AI coding assistants",
    ]


def test_review_queries_prioritize_public_review_sites() -> None:
    queries = build_community_queries(
        competitor="Windsurf",
        dimension="review",
        topic="AI coding assistants",
        limit=4,
    )

    assert queries == [
        "Windsurf G2 reviews pros cons AI coding assistants",
        "Windsurf Capterra reviews AI coding assistants",
        "Windsurf TrustRadius reviews AI coding assistants",
        "Windsurf customer complaints alternatives AI coding assistants",
    ]


def test_query_planner_dedupes_and_respects_limit() -> None:
    queries = build_community_queries(
        competitor="Cursor",
        dimension="pricing and review",
        topic="AI coding assistants",
        limit=3,
    )

    assert len(queries) == 3
    assert len(set(queries)) == 3
    assert all("  " not in query for query in queries)
