from __future__ import annotations

from urllib.parse import urlparse

from packages.community.models import CommunitySourceClassification


def classify_community_source(
    url: str,
    title: str = "",
    snippet: str = "",
) -> CommunitySourceClassification:
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    path = parsed.path.casefold()
    text = f"{title} {snippet}".casefold()
    authority = _authority_signal(text)

    if _host_matches_domain(host, "reddit.com"):
        return CommunitySourceClassification(
            source_type="reddit_thread",
            is_community=True,
            base_confidence=0.62,
            authority_signal=authority,
            reason="reddit_thread",
        )
    if host == "github.com" and "/discussions/" in path:
        return CommunitySourceClassification(
            source_type="github_discussion",
            is_community=True,
            base_confidence=0.86 if authority == "maintainer" else 0.74,
            authority_signal=authority,
            reason="github_discussion",
        )
    if host == "github.com" and "/issues/" in path:
        return CommunitySourceClassification(
            source_type="github_issue",
            is_community=True,
            base_confidence=0.86 if authority == "maintainer" else 0.74,
            authority_signal=authority,
            reason="github_issue",
        )
    if _is_review_site(host):
        return CommunitySourceClassification(
            source_type="review_site",
            is_community=True,
            base_confidence=0.72,
            authority_signal=authority,
            reason="review_site",
        )
    if _is_forum(host, path):
        return CommunitySourceClassification(
            source_type="community_forum",
            is_community=True,
            base_confidence=0.88 if authority == "staff" else 0.70,
            authority_signal=authority,
            reason="community_forum",
        )
    if _is_developer_blog(host):
        return CommunitySourceClassification(
            source_type="developer_blog",
            is_community=True,
            base_confidence=0.56,
            authority_signal=authority,
            reason="developer_blog",
        )
    return CommunitySourceClassification(
        source_type="snippet_only",
        is_community=False,
        base_confidence=0.35,
        authority_signal=authority,
        reason="not_community_source",
    )


def _authority_signal(text: str) -> str:
    if any(token in text for token in ("staff", "moderator", "mod response", "admin")):
        return "staff"
    if any(token in text for token in ("maintainer", "owner", "member")):
        return "maintainer"
    return "user"


def _is_review_site(host: str) -> bool:
    return any(
        _host_matches_domain(host, domain)
        for domain in ("g2.com", "capterra.com", "trustradius.com", "producthunt.com")
    )


def _is_forum(host: str, path: str) -> bool:
    return (
        host.startswith("forum.")
        or host.startswith("community.")
        or "discourse" in host
        or "/forum/" in path
        or "/t/" in path
    )


def _is_developer_blog(host: str) -> bool:
    return any(
        _host_matches_domain(host, domain)
        for domain in ("dev.to", "medium.com", "substack.com", "hashnode.dev")
    )


def _host_matches_domain(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")
