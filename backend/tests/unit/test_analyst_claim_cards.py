from packages.agents.analysts.cards import build_claim_card_bundle
from packages.schema.models import KnowledgeClaim, RawSource


def _source(source_id: str, source_type: str = "official") -> RawSource:
    return RawSource(
        id=source_id,
        competitor="Cursor",
        covered_competitors=["Cursor"],
        dimension="pricing",
        source_type=source_type,
        title="Cursor pricing",
        url="https://example.com/pricing",
        snippet="Cursor Pro is a paid plan.",
        content_hash=f"hash-{source_id}",
        confidence=0.86,
        quality_score=0.9,
        metadata={"normalized_fields": [{"type": "price_point", "value": "Pro paid plan"}]},
    )


def test_build_claim_card_bundle_from_knowledge_claims() -> None:
    bundle = build_claim_card_bundle(
        run_id="run-1",
        competitor="Cursor",
        dimension="pricing",
        claims=[
            KnowledgeClaim(
                claim="Cursor has a paid Pro plan.",
                source_ids=["raw-source-1"],
                confidence=0.84,
            )
        ],
        sources=[_source("raw-source-1")],
        producer_stage="analyst:pricing:Cursor",
    )
    assert bundle.run_id == "run-1"
    assert bundle.competitor == "Cursor"
    assert bundle.dimension == "pricing"
    assert bundle.source_ids == ["raw-source-1"]
    assert bundle.gap_count == 0
    assert len(bundle.cards) == 1
    assert bundle.cards[0].support_level == "official"
    assert bundle.cards[0].produced_by == "analyst"


def test_build_claim_card_bundle_emits_gap_card_for_empty_claims() -> None:
    bundle = build_claim_card_bundle(
        run_id="run-1",
        competitor="Cursor",
        dimension="persona",
        claims=[],
        sources=[],
        producer_stage="analyst:persona:Cursor",
    )
    assert bundle.gap_count == 1
    assert bundle.cards[0].support_level == "gap"
    assert bundle.cards[0].evidence_strength == "insufficient"
    assert bundle.cards[0].source_ids == []


def test_simulated_sources_become_simulated_cards() -> None:
    source = _source("raw-source-sim", source_type="simulated_interview")
    bundle = build_claim_card_bundle(
        run_id="run-1",
        competitor="Cursor",
        dimension="persona",
        claims=[
            KnowledgeClaim(
                claim="Simulated interview suggests startup developers value speed.",
                source_ids=[source.id],
                confidence=0.76,
            )
        ],
        sources=[source],
        producer_stage="analyst:persona:Cursor",
    )
    assert bundle.cards[0].support_level == "simulated"
    assert bundle.cards[0].evidence_strength == "moderate"


def test_two_community_sources_become_triangulated_community_card() -> None:
    reddit_source = _source("raw-source-reddit", source_type="reddit_thread")
    forum_source = _source("raw-source-forum", source_type="community_forum")
    bundle = build_claim_card_bundle(
        run_id="run-1",
        competitor="Cursor",
        dimension="pricing",
        claims=[
            KnowledgeClaim(
                claim="Community users discuss Cursor pricing as paid.",
                source_ids=[reddit_source.id, forum_source.id],
                confidence=0.78,
            )
        ],
        sources=[reddit_source, forum_source],
        producer_stage="analyst:pricing:Cursor",
    )
    assert bundle.cards[0].support_level == "triangulated_community"


def test_duplicate_community_source_id_stays_single_source_card() -> None:
    community_source = _source("raw-source-community", source_type="community_forum")
    bundle = build_claim_card_bundle(
        run_id="run-1",
        competitor="Cursor",
        dimension="pricing",
        claims=[
            KnowledgeClaim(
                claim="Community users discuss Cursor pricing as paid.",
                source_ids=[community_source.id, community_source.id],
                confidence=0.78,
            )
        ],
        sources=[community_source],
        producer_stage="analyst:pricing:Cursor",
    )
    assert bundle.cards[0].support_level == "single_source"
    assert bundle.cards[0].source_ids == [community_source.id]


def test_official_source_takes_priority_over_single_community_source() -> None:
    official_source = _source("raw-source-official", source_type="official")
    community_source = _source("raw-source-community", source_type="community_forum")
    bundle = build_claim_card_bundle(
        run_id="run-1",
        competitor="Cursor",
        dimension="pricing",
        claims=[
            KnowledgeClaim(
                claim="Cursor pricing is documented officially and discussed by users.",
                source_ids=[official_source.id, community_source.id],
                confidence=0.82,
            )
        ],
        sources=[official_source, community_source],
        producer_stage="analyst:pricing:Cursor",
    )
    assert bundle.cards[0].support_level == "official"


def test_unknown_claim_sources_become_gap_card() -> None:
    bundle = build_claim_card_bundle(
        run_id="run-1",
        competitor="Cursor",
        dimension="pricing",
        claims=[
            KnowledgeClaim(
                claim="Cursor has an unsupported pricing claim.",
                source_ids=["missing-source"],
                confidence=0.8,
            )
        ],
        sources=[_source("raw-source-1")],
        producer_stage="analyst:pricing:Cursor",
    )
    assert bundle.gap_count == 1
    assert bundle.cards[0].support_level == "gap"
    assert bundle.cards[0].source_ids == []
    assert "missing-source" in bundle.cards[0].metadata["dropped_source_ids"]


def test_mixed_supported_and_unsupported_claims_emit_supported_and_gap_cards() -> None:
    bundle = build_claim_card_bundle(
        run_id="run-1",
        competitor="Cursor",
        dimension="pricing",
        claims=[
            KnowledgeClaim(
                claim="Cursor has a paid Pro plan.",
                source_ids=["raw-source-1"],
                confidence=0.84,
            ),
            KnowledgeClaim(
                claim="Cursor has an unsupported enterprise-only discount.",
                source_ids=["missing-source"],
                confidence=0.72,
            ),
        ],
        sources=[_source("raw-source-1")],
        producer_stage="analyst:pricing:Cursor",
    )
    assert len(bundle.cards) == 2
    assert bundle.gap_count == 1
    assert any(card.support_level == "official" for card in bundle.cards)
    gap_card = next(card for card in bundle.cards if card.support_level == "gap")
    assert gap_card.evidence_strength == "insufficient"
    assert gap_card.source_ids == []
    assert gap_card.metadata["missing_source_ids"] == ["missing-source"]
    assert gap_card.metadata["original_claim_confidence"] == 0.72


def test_manual_source_is_single_source_unless_trusted_official() -> None:
    manual_source = _source("raw-source-manual", source_type="manual")
    manual_bundle = build_claim_card_bundle(
        run_id="run-1",
        competitor="Cursor",
        dimension="pricing",
        claims=[
            KnowledgeClaim(
                claim="Manual note says Cursor pricing changed.",
                source_ids=[manual_source.id],
                confidence=0.8,
            )
        ],
        sources=[manual_source],
        producer_stage="analyst:pricing:Cursor",
    )
    assert manual_bundle.cards[0].support_level == "single_source"

    trusted_manual_source = _source("raw-source-trusted-manual", source_type="manual")
    trusted_manual_source.metadata["trusted_official"] = True
    trusted_bundle = build_claim_card_bundle(
        run_id="run-1",
        competitor="Cursor",
        dimension="pricing",
        claims=[
            KnowledgeClaim(
                claim="Trusted manual note captures vendor-verified pricing.",
                source_ids=[trusted_manual_source.id],
                confidence=0.8,
            )
        ],
        sources=[trusted_manual_source],
        producer_stage="analyst:pricing:Cursor",
    )
    assert trusted_bundle.cards[0].support_level == "official"
