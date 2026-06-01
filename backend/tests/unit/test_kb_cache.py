from packages.memory import KBCache, KBCacheEntry
from packages.schema.models import CompetitorKnowledge, KnowledgeClaim, PricingModel


def test_kb_cache_round_trips_competitor_dimension_slice() -> None:
    cache = KBCache.in_memory()
    knowledge = CompetitorKnowledge(
        competitor="A",
        pricing_model=PricingModel(
            notes=[
                KnowledgeClaim(
                    claim="A has transparent pricing.", source_ids=["pricing-1"], confidence=0.9
                )
            ]
        ),
        source_ids=["pricing-1"],
        confidence=0.9,
    )
    entry = KBCacheEntry(
        competitor="A",
        dimension="pricing",
        content_hash="hash-1",
        kb_slice=["A has transparent pricing. [source:pricing-1]"],
        source_ids=["pricing-1"],
        confidence=0.9,
        knowledge=knowledge,
    )

    cache.put(entry)
    restored = cache.get("A", "pricing", "hash-1")

    assert restored is not None
    assert restored.competitor == "A"
    assert restored.dimension == "pricing"
    assert restored.kb_slice == ["A has transparent pricing. [source:pricing-1]"]
    assert restored.knowledge.pricing_model.notes[0].source_ids == ["pricing-1"]
    assert cache.stats()["entries"] == 1
