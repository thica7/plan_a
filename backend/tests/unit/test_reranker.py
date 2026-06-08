from __future__ import annotations

from packages.knowledge.reranker import HashRerankerProvider, RerankerProvider


def test_hash_reranker_is_deterministic() -> None:
    provider = HashRerankerProvider()
    texts = ["pricing starts at ten dollars", "security controls"]

    first = provider.rerank("pricing", texts)
    second = provider.rerank("pricing", texts)

    assert first == second
    assert len(first) == 2
    assert all(0.0 <= score <= 1.0 for score in first)
    assert first[0] > first[1]


def test_hash_reranker_matches_interface() -> None:
    provider: RerankerProvider = HashRerankerProvider(model_version="test-reranker")

    scores = provider.rerank("query", ["query text"])

    assert len(scores) == 1
    assert provider.model_version == "test-reranker"
