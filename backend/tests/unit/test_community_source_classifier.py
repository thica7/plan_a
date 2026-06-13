from __future__ import annotations

from packages.community.source_classifier import classify_community_source
from packages.research.models import SourceCandidate


def test_classifies_reddit_thread() -> None:
    result = classify_community_source(
        url="https://www.reddit.com/r/cursor/comments/abc123/cursor_pricing_limits/",
        title="Cursor pricing limits?",
        snippet="Users report Cursor Pro usage limits and cost confusion.",
    )

    assert result.source_type == "reddit_thread"
    assert result.is_community is True
    assert result.base_confidence == 0.62


def test_classifier_accepts_positional_url_argument() -> None:
    result = classify_community_source("https://www.reddit.com/r/cursor/comments/abc")

    assert result.source_type == "reddit_thread"
    assert result.is_community is True


def test_does_not_classify_domain_lookalikes_as_community_sources() -> None:
    reddit = classify_community_source("https://notreddit.com/r/cursor/comments/abc")
    review = classify_community_source("https://evilg2.com/products/cursor/reviews")
    blog = classify_community_source("https://notmedium.com/post")

    assert reddit.is_community is False
    assert reddit.reason == "not_community_source"
    assert review.is_community is False
    assert blog.is_community is False


def test_classifies_github_discussion_and_issue() -> None:
    discussion = classify_community_source(
        url="https://github.com/org/repo/discussions/42",
        title="Copilot billing discussion",
        snippet="Maintainer answered the billing quota question.",
    )
    issue = classify_community_source(
        url="https://github.com/org/repo/issues/99",
        title="Context window limitation",
        snippet="Maintainer confirmed the issue is a known limitation.",
    )

    assert discussion.source_type == "github_discussion"
    assert discussion.authority_signal == "maintainer"
    assert discussion.base_confidence == 0.86
    assert issue.source_type == "github_issue"
    assert issue.authority_signal == "maintainer"


def test_classifies_official_forum_and_review_site() -> None:
    forum = classify_community_source(
        url="https://forum.cursor.com/t/usage-based-pricing/123",
        title="Usage based pricing",
        snippet="A staff member explains current usage limits.",
    )
    review = classify_community_source(
        url="https://www.g2.com/products/cursor/reviews",
        title="Cursor reviews",
        snippet="Users list pros, cons, and adoption blockers.",
    )

    assert forum.source_type == "community_forum"
    assert forum.authority_signal == "staff"
    assert forum.base_confidence == 0.88
    assert review.source_type == "review_site"
    assert review.base_confidence == 0.72


def test_classifies_developer_blog_and_non_community() -> None:
    blog = classify_community_source(
        url="https://dev.to/team/cursor-vs-copilot-review",
        title="Cursor vs Copilot hands-on review",
        snippet="A developer compares limitations and workflow fit.",
    )
    official = classify_community_source(
        url="https://docs.github.com/en/copilot",
        title="GitHub Copilot docs",
        snippet="Official product documentation.",
    )

    assert blog.source_type == "developer_blog"
    assert blog.base_confidence == 0.56
    assert official.is_community is False
    assert official.reason == "not_community_source"


def test_community_search_candidate_origin_is_accepted() -> None:
    candidate = SourceCandidate(
        title="Cursor pricing reddit",
        url="https://reddit.com/r/cursor/comments/abc",
        snippet="Cursor Pro is reported at $20 per month.",
        origin="community_search",
        competitor="Cursor",
        dimension="pricing",
    )

    assert candidate.origin == "community_search"
