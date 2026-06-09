from packages.enterprise.embedding_index import (
    EMBEDDING_DIMENSIONS,
    cosine_similarity,
    deterministic_embedding,
)


def test_deterministic_embedding_is_stable_and_normalized() -> None:
    first = deterministic_embedding("Cursor enterprise pricing")
    second = deterministic_embedding("Cursor enterprise pricing")

    assert first == second
    assert len(first) == EMBEDDING_DIMENSIONS
    assert 0.99 <= cosine_similarity(first, first) <= 1.01


def test_deterministic_embedding_scores_related_text_higher() -> None:
    query = deterministic_embedding("enterprise pricing")
    related = deterministic_embedding("Cursor enterprise pricing plan")
    unrelated = deterministic_embedding("mobile photo editing filters")

    assert cosine_similarity(query, related) > cosine_similarity(query, unrelated)
