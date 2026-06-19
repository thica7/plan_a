from __future__ import annotations

from urllib.parse import urlparse

from packages.community.models import CommunityClaim

COUNTRY_CODE_PUBLIC_SUFFIX_SECOND_LABELS = {
    "ac",
    "co",
    "com",
    "edu",
    "gov",
    "ne",
    "net",
    "or",
    "org",
}


def independent_domain_count(claims: list[CommunityClaim]) -> int:
    domains = {_domain(claim.url) for claim in claims if _domain(claim.url)}
    return len(domains)


def cluster_confidence(claims: list[CommunityClaim], *, contested: bool) -> float:
    if not claims:
        return 0.0
    if all(claim.is_snippet_only for claim in claims):
        return 0.55
    max_confidence = max(claim.confidence for claim in claims)
    source_count = len({claim.source_id for claim in claims})
    domain_count = independent_domain_count(claims)
    has_staff_signal = any(
        claim.author_signal in {"staff", "maintainer"} for claim in claims
    )
    if contested:
        return max(0.0, min(0.72, max_confidence - 0.08))
    confidence = min(0.65, max_confidence)
    if domain_count >= 3:
        confidence = max(confidence, 0.82)
    elif domain_count >= 2:
        confidence = max(confidence, 0.70)
    if has_staff_signal and source_count >= 1:
        confidence = max(confidence, min(0.92, max_confidence + 0.06))
    return confidence


def _domain(url: str) -> str:
    hostname = (urlparse(url).hostname or "").casefold().removeprefix("www.")
    labels = hostname.split(".")
    if (
        len(labels) >= 3
        and len(labels[-1]) == 2
        and labels[-2] in COUNTRY_CODE_PUBLIC_SUFFIX_SECOND_LABELS
    ):
        return ".".join(labels[-3:])
    if len(labels) >= 3:
        return ".".join(labels[-2:])
    return hostname
