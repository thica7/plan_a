from __future__ import annotations

from packages.rag.structured_claims import (
    extract_structured_source_claims,
    find_structured_source_conflicts,
)
from packages.schema.models import RawSource


def _source(
    source_id: str,
    snippet: str,
    *,
    origin: str = "web_fetch",
    dimension: str = "security",
) -> RawSource:
    return RawSource(
        id=source_id,
        competitor="Acme",
        dimension=dimension,
        source_type="webpage_verified",
        title="Acme docs",
        url="https://acme.example/docs",
        snippet=snippet,
        content_hash=f"hash-{source_id}",
        confidence=0.9,
        candidate_origin=origin,
        metadata={"kb_retrieved": origin == "rag_kb"},
    )


def test_structured_source_claims_extract_binary_support_claims() -> None:
    claims = extract_structured_source_claims(
        [
            _source(
                "kb-sso",
                "Acme supports SSO and SCIM for enterprise workspaces.",
                origin="rag_kb",
            )
        ],
        dimension="security",
    )

    sso_claim = next(claim for claim in claims if claim.claim_area == "support:sso")

    assert sso_claim.subject == "Acme"
    assert sso_claim.predicate == "supports:sso"
    assert sso_claim.value == "true"
    assert sso_claim.position == "supported"
    assert sso_claim.is_kb_reuse is True


def test_structured_source_conflicts_require_kb_and_live_positions() -> None:
    conflicts = find_structured_source_conflicts(
        [
            _source("kb-sso", "Acme supports SSO for enterprise workspaces.", origin="rag_kb"),
            _source("live-sso", "Acme does not support SSO for enterprise workspaces."),
        ],
        dimension="security",
    )

    assert len(conflicts) == 1
    assert conflicts[0].claim_area == "support:sso"
    assert conflicts[0].source_ids_by_position == {
        "supported": ["kb-sso"],
        "unsupported": ["live-sso"],
    }


def test_structured_source_conflicts_detect_price_mismatch() -> None:
    conflicts = find_structured_source_conflicts(
        [
            _source(
                "kb-price",
                "Acme Pro plan costs $20 per month for developer teams.",
                origin="rag_kb",
                dimension="pricing",
            ),
            _source(
                "live-price",
                "Acme Pro plan costs $30 per month for developer teams.",
                dimension="pricing",
            ),
        ],
        dimension="pricing",
    )

    assert conflicts[0].claim_area == "price:pro:month"
    assert conflicts[0].source_ids_by_position == {
        "$20/month": ["kb-price"],
        "$30/month": ["live-price"],
    }