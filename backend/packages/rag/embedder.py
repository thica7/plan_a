from __future__ import annotations

from dataclasses import dataclass

from packages.enterprise.embedding_index import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    deterministic_embedding,
    embedding_hash,
)


@dataclass(frozen=True)
class RagEmbedding:
    text: str
    vector: list[float]
    embedding_model: str = EMBEDDING_MODEL
    embedding_dimensions: int = EMBEDDING_DIMENSIONS
    embedding_hash: str = ""


class HashingRagEmbedder:
    """Deterministic local embedder used until provider-backed embeddings are enabled."""

    embedding_model = EMBEDDING_MODEL
    embedding_dimensions = EMBEDDING_DIMENSIONS

    def embed_text(self, text: str) -> RagEmbedding:
        normalized = " ".join(text.split())
        return RagEmbedding(
            text=normalized,
            vector=deterministic_embedding(normalized),
            embedding_hash=embedding_hash(normalized),
        )


DEFAULT_RAG_EMBEDDER = HashingRagEmbedder()


def embed_text(text: str) -> RagEmbedding:
    return DEFAULT_RAG_EMBEDDER.embed_text(text)
