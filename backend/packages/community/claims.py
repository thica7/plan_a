from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from typing import TypeVar

from packages.community.models import CommunityClaim, CommunityClaimCluster
from packages.community.scoring import cluster_confidence, independent_domain_count
from packages.schema.models import RawSource

COMMUNITY_SOURCE_TYPES = {
    "community_forum",
    "reddit_thread",
    "github_discussion",
    "github_issue",
    "review_site",
    "developer_blog",
    "snippet_only",
}

T = TypeVar("T")


def extract_community_claims_from_source(source: RawSource) -> list[CommunityClaim]:
    if source.source_type not in COMMUNITY_SOURCE_TYPES and not source.metadata.get(
        "community_evidence"
    ):
        return []
    text = " ".join([source.title, source.snippet]).strip()
    claims: list[CommunityClaim] = []
    claims.extend(_pricing_claims(source, text))
    claims.extend(_usage_limit_claims(source, text))
    claims.extend(_feature_claims(source, text))
    claims.extend(_review_claims(source, text))
    return _dedupe_claims(claims)


def cluster_community_claims(claims: list[CommunityClaim]) -> list[CommunityClaimCluster]:
    grouped: dict[tuple[str, str, str, str], list[CommunityClaim]] = defaultdict(list)
    for claim in claims:
        grouped[_cluster_key(claim)].append(claim)

    clusters: list[CommunityClaimCluster] = []
    for (competitor, dimension, kind, key_value), items in grouped.items():
        values = sorted(
            {item.normalized_value for item in items if item.normalized_value}
        )
        contested = len(values) > 1 and not key_value
        if contested:
            cluster_items = items
            normalized_value = ""
        else:
            normalized_value = values[0] if values else ""
            cluster_items = items
        confidence = cluster_confidence(cluster_items, contested=contested)
        source_ids = _ordered_unique(item.source_id for item in cluster_items)
        source_types = _ordered_unique(item.source_type for item in cluster_items)
        evidence = _ordered_unique(
            item.evidence for item in cluster_items if item.evidence
        )
        independent_count = independent_domain_count(cluster_items)
        if contested:
            label = "community_contested"
        elif confidence >= 0.80 and independent_count >= 2 and len(source_ids) >= 2:
            label = "community_triangulated"
        elif cluster_items:
            label = "community_observed"
        else:
            label = "insufficient_evidence"
        clusters.append(
            CommunityClaimCluster(
                competitor=competitor,
                dimension=dimension,
                kind=kind,
                normalized_value=normalized_value,
                label=label,
                claim=_cluster_claim_text(kind, normalized_value, label),
                source_ids=source_ids,
                source_types=source_types,
                independent_domain_count=independent_count,
                confidence=confidence,
                conflict_values=values if contested else [],
                evidence=evidence[:5],
            )
        )
    return sorted(
        clusters,
        key=lambda item: (
            item.competitor,
            item.dimension,
            item.kind,
            item.normalized_value,
        ),
    )


def _cluster_key(claim: CommunityClaim) -> tuple[str, str, str, str]:
    key_value = ""
    if claim.kind in {"pricing", "usage_limit"} and claim.normalized_value:
        key_value = claim.normalized_value
    return (claim.competitor, claim.dimension, claim.kind, key_value)


def _pricing_claims(source: RawSource, text: str) -> list[CommunityClaim]:
    claims: list[CommunityClaim] = []
    for match in re.finditer(
        (
            r"\$\s?\d+(?:\.\d+)?\s*(?:/|per)\s*"
            r"(?:month|mo|year|yr|user|seat|1m tokens|mtok|tokens?)"
        ),
        text,
        flags=re.IGNORECASE,
    ):
        value = _normalize_price(match.group(0))
        claims.append(
            _claim(
                source,
                "pricing",
                value,
                f"{source.competitor} is reported as {value}.",
                text,
            )
        )
    return claims


def _usage_limit_claims(source: RawSource, text: str) -> list[CommunityClaim]:
    normalized = text.casefold()
    if not any(
        token in normalized
        for token in ("usage limit", "quota", "rate limit", "credit limit")
    ):
        return []
    value = "usage limits" if "limit" in normalized else "quota"
    return [_claim(source, "usage_limit", value, f"Users report {value}.", text)]


def _feature_claims(source: RawSource, text: str) -> list[CommunityClaim]:
    normalized = text.casefold()
    claims: list[CommunityClaim] = []
    if any(
        token in normalized
        for token in ("context window", "limitation", "bug", "issue")
    ):
        claims.append(
            _claim(
                source,
                "feature_limitation",
                "feature limitation",
                "Users report feature limitations.",
                text,
            )
        )
    return claims


def _review_claims(source: RawSource, text: str) -> list[CommunityClaim]:
    normalized = text.casefold()
    claims: list[CommunityClaim] = []
    if any(
        token in normalized
        for token in ("complain", "complaint", "confusing", "friction", "pain")
    ):
        claims.append(
            _claim(
                source,
                "complaint",
                "complaint",
                "Users report complaints or friction.",
                text,
            )
        )
    if any(
        token in normalized
        for token in (
            "adoption blocker",
            "rollout",
            "procurement",
            "security review",
            "onboarding",
        )
    ):
        claims.append(
            _claim(
                source,
                "adoption_blocker",
                "adoption blocker",
                "Users report adoption blockers.",
                text,
            )
        )
    if "switched from" in normalized or "switching" in normalized:
        claims.append(
            _claim(
                source,
                "switching_trigger",
                "switching trigger",
                "Users report switching triggers.",
                text,
            )
        )
    if any(
        token in normalized for token in ("developer", "team", "enterprise", "buyer")
    ):
        claims.append(
            _claim(
                source,
                "persona_signal",
                "persona signal",
                "Community source describes user or buyer segments.",
                text,
            )
        )
    return claims


def _claim(
    source: RawSource,
    kind: str,
    normalized_value: str,
    claim_text: str,
    text: str,
) -> CommunityClaim:
    source_type = str(source.metadata.get("community_source_type") or source.source_type)
    if source_type not in COMMUNITY_SOURCE_TYPES:
        source_type = "snippet_only"
    return CommunityClaim(
        competitor=source.competitor,
        dimension=source.dimension,
        kind=kind,
        claim=claim_text,
        normalized_value=normalized_value,
        source_id=source.id,
        source_type=source_type,
        url=str(source.url or ""),
        evidence=_evidence_window(text, normalized_value),
        confidence=source.confidence,
        author_signal=str(source.metadata.get("community_authority_signal") or "user"),
        is_snippet_only=source_type == "snippet_only"
        or source.source_type == "snippet_only",
    )


def _normalize_price(value: str) -> str:
    normalized = " ".join(value.replace("/", " per ").split())
    normalized = re.sub(r"\bmo\b", "month", normalized)
    normalized = re.sub(r"\byr\b", "year", normalized)
    return normalized


def _evidence_window(text: str, needle: str) -> str:
    if not needle:
        return " ".join(text.split())[:220]
    normalized = text.casefold()
    index = normalized.find(needle.casefold())
    if index < 0:
        return " ".join(text.split())[:220]
    start = max(0, index - 90)
    end = min(len(text), index + len(needle) + 130)
    return " ".join(text[start:end].split())[:240]


def _cluster_claim_text(kind: str, normalized_value: str, label: str) -> str:
    if kind == "pricing" and normalized_value:
        return f"Multiple community sources report pricing at {normalized_value}."
    if kind == "usage_limit":
        return "Community sources report usage limit or quota concerns."
    if kind == "feature_limitation":
        return "Community sources report feature limitations in actual use."
    if kind == "switching_trigger":
        return "Community sources describe switching triggers."
    if label == "community_contested":
        return "Community sources conflict on this claim."
    return "Community sources describe user sentiment or adoption signals."


def _dedupe_claims(claims: list[CommunityClaim]) -> list[CommunityClaim]:
    result: list[CommunityClaim] = []
    seen: set[tuple[str, str, str]] = set()
    for claim in claims:
        key = (claim.kind, claim.normalized_value, claim.source_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(claim)
    return result


def _ordered_unique(values: Iterable[T]) -> list[T]:
    result: list[T] = []
    seen: set[str] = set()
    for value in values:
        key = str(value).casefold()
        if not str(value).strip() or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result
