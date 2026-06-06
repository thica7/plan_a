from __future__ import annotations

from packages.knowledge.embeddings import (
    BgeM3Provider,
    EmbeddingProvider,
    HashEmbeddingProvider,
)


def test_hash_embedding_is_deterministic() -> None:
    provider = HashEmbeddingProvider(dimensions=8)

    first = provider.embed_query("pricing plan")
    second = provider.embed_query("pricing plan")
    other = provider.embed_query("feature matrix")

    assert first == second
    assert first != other
    assert len(first) == 8


def test_hash_embedding_documents_match_interface() -> None:
    provider: EmbeddingProvider = HashEmbeddingProvider(dimensions=4)

    vectors = provider.embed_documents(["one", "two"])

    assert len(vectors) == 2
    assert all(len(vector) == 4 for vector in vectors)
    assert provider.model_version == "hash-embedding-v1"


def test_bge_provider_falls_back_without_model_download() -> None:
    provider = BgeM3Provider(batch_size=1)
    provider._load_error = RuntimeError("force fallback")

    vectors = provider.embed_documents(["one", "two"])

    assert len(vectors) == 2
    assert all(len(vector) == 1024 for vector in vectors)
    assert provider.model_version == "BAAI/bge-m3"
