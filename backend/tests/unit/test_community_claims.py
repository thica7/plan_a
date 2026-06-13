from __future__ import annotations

from packages.community.claims import (
    cluster_community_claims,
    extract_community_claims_from_source,
)
from packages.community.models import CommunityClaim
from packages.community.scoring import independent_domain_count
from packages.schema.models import RawSource


def test_extracts_concrete_pricing_and_limit_claims() -> None:
    source = _source(
        source_id="reddit-cursor-pricing",
        source_type="reddit_thread",
        snippet=(
            "Users report Cursor Pro is $20 per month and Ultra is $200 per month. "
            "Several comments mention usage limits and quota confusion."
        ),
    )

    claims = extract_community_claims_from_source(source)

    assert [claim.kind for claim in claims] == ["pricing", "pricing", "usage_limit"]
    assert claims[0].normalized_value == "$20 per month"
    assert claims[1].normalized_value == "$200 per month"
    assert claims[2].normalized_value == "usage limits"


def test_extracts_complaints_switching_and_feature_limitation() -> None:
    source = _source(
        source_id="github-feature-limit",
        source_type="github_issue",
        dimension="feature",
        snippet=(
            "Users complain about context window limitations in large repositories. "
            "One team switched from Cursor to Copilot because enterprise rollout was easier."
        ),
    )

    claims = extract_community_claims_from_source(source)

    kinds = {claim.kind for claim in claims}
    assert "feature_limitation" in kinds
    assert "complaint" in kinds
    assert "switching_trigger" in kinds


def test_metadata_community_evidence_with_non_community_source_type_does_not_crash() -> None:
    source = RawSource(
        id="verified-community-snippet",
        competitor="Cursor",
        dimension="pricing",
        source_type="webpage_verified",
        title="Verified page mentioning community pricing",
        url="https://example-verified-community-snippet.com/thread",
        snippet="Cursor Pro is $20 per month according to community users.",
        content_hash="verified-community-snippet-hash",
        confidence=0.72,
        metadata={"community_evidence": True},
    )

    claims = extract_community_claims_from_source(source)

    assert len(claims) == 1
    assert claims[0].kind == "pricing"
    assert claims[0].normalized_value == "$20 per month"
    assert claims[0].source_type == "snippet_only"
    assert claims[0].is_snippet_only is True


def test_cluster_confidence_rises_with_independent_agreement() -> None:
    sources = [
        _source("reddit-cursor-pricing", "reddit_thread", "Cursor Pro is $20 per month."),
        _source("forum-cursor-pricing", "community_forum", "Cursor Pro price is $20 per month."),
        _source("g2-cursor-pricing", "review_site", "Cursor Pro costs $20 per month."),
    ]
    claims = [
        claim
        for source in sources
        for claim in extract_community_claims_from_source(source)
    ]

    clusters = cluster_community_claims(claims)

    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster.label == "community_triangulated"
    assert cluster.confidence >= 0.80
    assert cluster.independent_domain_count == 3
    assert cluster.source_ids == [
        "reddit-cursor-pricing",
        "forum-cursor-pricing",
        "g2-cursor-pricing",
    ]


def test_staff_signal_does_not_lower_three_domain_confidence_floor() -> None:
    sources = [
        _source("reddit-cursor-staff", "reddit_thread", "Cursor Pro is $20 per month."),
        _source("forum-cursor-staff", "community_forum", "Cursor Pro price is $20 per month."),
        _source("g2-cursor-staff", "review_site", "Cursor Pro costs $20 per month."),
    ]
    sources[0].metadata["community_authority_signal"] = "staff"
    claims = [
        claim
        for source in sources
        for claim in extract_community_claims_from_source(source)
    ]

    clusters = cluster_community_claims(claims)

    assert len(clusters) == 1
    assert clusters[0].independent_domain_count == 3
    assert clusters[0].confidence == 0.82


def test_single_staff_source_is_observed_not_triangulated() -> None:
    source = _source(
        "forum-cursor-staff-single",
        "community_forum",
        "Cursor Pro is $20 per month.",
    )
    source.confidence = 0.86
    source.metadata["community_authority_signal"] = "staff"
    claims = extract_community_claims_from_source(source)

    clusters = cluster_community_claims(claims)

    assert len(clusters) == 1
    assert clusters[0].confidence >= 0.80
    assert clusters[0].independent_domain_count == 1
    assert clusters[0].source_ids == ["forum-cursor-staff-single"]
    assert clusters[0].label == "community_observed"


def test_sibling_subdomains_count_as_one_independent_domain() -> None:
    claims = [
        _community_claim("forum-cursor-subdomain", "https://forum.cursor.com/t/a"),
        _community_claim("community-cursor-subdomain", "https://community.cursor.com/t/b"),
        _community_claim("help-cursor-subdomain", "https://help.cursor.com/t/c"),
    ]

    clusters = cluster_community_claims(claims)

    assert independent_domain_count(claims) == 1
    assert len(clusters) == 1
    assert clusters[0].independent_domain_count == 1
    assert clusters[0].label == "community_observed"


def test_public_suffix_domains_remain_independent_sources() -> None:
    claims = [
        _community_claim("alpha-uk", "https://alpha.co.uk/thread"),
        _community_claim("beta-uk", "https://beta.co.uk/thread"),
        _community_claim("gamma-uk", "https://gamma.co.uk/thread"),
    ]

    clusters = cluster_community_claims(claims)

    assert independent_domain_count(claims) == 3
    assert len(clusters) == 1
    assert clusters[0].independent_domain_count == 3
    assert clusters[0].label == "community_triangulated"
    assert clusters[0].confidence == 0.82


def test_country_code_public_suffix_domains_remain_independent_sources() -> None:
    claims = [
        _community_claim("alpha-br", "https://alpha.com.br/thread"),
        _community_claim("beta-br", "https://beta.com.br/thread"),
        _community_claim("gamma-br", "https://gamma.com.br/thread"),
    ]

    clusters = cluster_community_claims(claims)

    assert independent_domain_count(claims) == 3
    assert len(clusters) == 1
    assert clusters[0].independent_domain_count == 3
    assert clusters[0].label == "community_triangulated"
    assert clusters[0].confidence == 0.82


def test_contested_low_confidence_cluster_is_clamped_to_zero() -> None:
    claims = [
        _community_claim(
            "low-confidence-review-a",
            "https://example-a.com/review",
            kind="complaint",
            normalized_value="latency complaint",
            confidence=0.02,
        ),
        _community_claim(
            "low-confidence-review-b",
            "https://example-b.com/review",
            kind="complaint",
            normalized_value="pricing complaint",
            confidence=0.02,
        ),
    ]

    clusters = cluster_community_claims(claims)

    assert len(clusters) == 1
    assert clusters[0].label == "community_contested"
    assert clusters[0].confidence == 0.0


def test_cluster_keeps_distinct_pricing_values_separate() -> None:
    sources = [
        _source("reddit-cursor-20", "reddit_thread", "Cursor Pro is $20 per month."),
        _source("forum-cursor-25", "community_forum", "Cursor Pro is $25 per month."),
    ]
    claims = [
        claim
        for source in sources
        for claim in extract_community_claims_from_source(source)
    ]

    clusters = cluster_community_claims(claims)

    assert [cluster.normalized_value for cluster in clusters] == [
        "$20 per month",
        "$25 per month",
    ]
    assert all(cluster.label == "community_observed" for cluster in clusters)
    assert all(cluster.conflict_values == [] for cluster in clusters)


def test_single_snippet_only_source_is_capped() -> None:
    source = _source(
        source_id="snippet-only",
        source_type="snippet_only",
        snippet="Search result says Cursor Pro is $20 per month.",
    )

    claims = extract_community_claims_from_source(source)
    clusters = cluster_community_claims(claims)

    assert clusters[0].label == "community_observed"
    assert clusters[0].confidence == 0.55


def _source(
    source_id: str,
    source_type: str,
    snippet: str,
    *,
    dimension: str = "pricing",
) -> RawSource:
    return RawSource(
        id=source_id,
        competitor="Cursor",
        dimension=dimension,
        source_type=source_type,
        title=source_id,
        url=f"https://example-{source_id}.com/thread",
        snippet=snippet,
        content_hash=f"{source_id}-hash",
        confidence=0.72 if source_type != "snippet_only" else 0.55,
        metadata={
            "community_evidence": True,
            "community_source_type": source_type,
        },
    )


def _community_claim(
    source_id: str,
    url: str,
    *,
    kind: str = "feature_limitation",
    normalized_value: str = "feature limitation",
    confidence: float = 0.72,
) -> CommunityClaim:
    return CommunityClaim(
        competitor="Cursor",
        dimension="review",
        kind=kind,
        claim=f"Community source reports {normalized_value}.",
        normalized_value=normalized_value,
        source_id=source_id,
        source_type="community_forum",
        url=url,
        evidence=normalized_value,
        confidence=confidence,
    )
