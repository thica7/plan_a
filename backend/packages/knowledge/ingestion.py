"""Document ingestion pipeline: chunk -> embed -> store in Qdrant + SQLite."""

from __future__ import annotations

import hashlib
import inspect
import math
import os
import re
import uuid
from collections.abc import Callable
from typing import Any

from .embeddings import EmbeddingProvider
from .models import DocumentCreate, KnowledgeChunk, KnowledgeDocument
from .repository import KnowledgeRepository

# Simple token-count approximation (chars / 4)
_CHAR_TOKEN_RATIO = 4
_DEFAULT_CHUNK_SIZE = 1000  # characters
_DEFAULT_CHUNK_OVERLAP = 200
_DEFAULT_EMBEDDING_MODEL = "custom-embedding"


class IngestionPipeline:
    """Chunks a document, embeds its chunks, and stores metadata + vectors."""

    def __init__(
        self,
        repo: KnowledgeRepository,
        vector_store: Any,
        *,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = _DEFAULT_CHUNK_OVERLAP,
    ) -> None:
        self._repo = repo
        self._vs = vector_store
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    async def ingest(
        self,
        doc: DocumentCreate,
        *,
        embed_fn: Callable[[list[str]], Any] | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        embedding_model: str = _DEFAULT_EMBEDDING_MODEL,
        crawl_run_id: str | None = None,
    ) -> str:
        """Ingest a document. Returns the document ID.

        Args:
            doc: Document payload.
            embed_fn: Callable that takes list[str] -> list[list[float]].
                      If None, stores chunks without embeddings (for offline indexing).
        """
        if embedding_provider is not None:
            embed_fn = embedding_provider.embed_documents
            embedding_model = embedding_provider.model_version

        content_hash = hashlib.sha256(doc.text.encode()).hexdigest()[:16]
        stored = await self._repo.get_document_by_content_hash(content_hash)
        if stored is None:
            stored = await self._repo.upsert_document(doc, content_hash)
        chunks = await self._repo.get_chunks_for_document(stored.id)
        if not chunks:
            chunks = self._chunk_text(
                stored.text, stored.id, content_hash, "", crawl_run_id=crawl_run_id
            )
            await self._repo.insert_chunks(chunks)
        index_version = os.getenv("KB_INDEX_VERSION", "v1")
        if embed_fn and chunks:
            dimensions = getattr(embedding_provider, "dimensions", None)
            if (
                stored.indexing_status == "ready"
                and stored.embedding_model == embedding_model
                and stored.index_version == index_version
                and (dimensions is None or stored.embedding_dimensions == dimensions)
            ):
                return stored.id
            await self._index_chunks(
                stored, chunks, embed_fn, embedding_model, embedding_provider, index_version
            )
        return stored.id

    async def reindex_document(
        self,
        document_id: str,
        *,
        embedding_provider: EmbeddingProvider,
    ) -> str:
        """Rebuild vectors for a saved document without changing versions or chunk IDs."""
        stored = await self._repo.get_document(document_id)
        if stored is None:
            raise ValueError(f"Document not found: {document_id}")
        if not stored.is_active or stored.status not in {"active", "stale"}:
            raise ValueError("Only active or stale documents can be reindexed")
        chunks = await self._repo.get_chunks_for_document(document_id)
        if not chunks:
            chunks = self._chunk_text(stored.text, stored.id, stored.content_hash, "")
            await self._repo.insert_chunks(chunks)
        if chunks:
            await self._index_chunks(
                stored,
                chunks,
                embedding_provider.embed_documents,
                embedding_provider.model_version,
                embedding_provider,
                os.getenv("KB_INDEX_VERSION", "v1"),
            )
        return stored.id

    async def _index_chunks(
        self,
        stored: KnowledgeDocument,
        chunks: list[KnowledgeChunk],
        embed_fn: Callable[[list[str]], Any],
        embedding_model: str,
        provider: EmbeddingProvider | None,
        index_version: str,
    ) -> None:
        await self._repo.set_indexing_state(
            stored.id, "pending", embedding_model=embedding_model, index_version=index_version
        )
        stage = "embedding"
        dimensions: int | None = None
        try:
            vectors = await _maybe_await(embed_fn([chunk.text for chunk in chunks]))
            if provider is not None:
                embedding_model = provider.model_version
            if len(vectors) != len(chunks) or not vectors or not vectors[0]:
                raise ValueError("Embedding batch must contain one nonempty vector per chunk")
            dimensions = len(vectors[0])
            if any(
                len(vector) != dimensions or not all(math.isfinite(value) for value in vector)
                for vector in vectors
            ):
                raise ValueError(
                    "Embedding vectors must have matching dimensions and finite values"
                )
            stage = "upsert"
            configure = getattr(self._vs, "configure_index", None)
            if callable(configure):
                configure(embedding_model, dimensions, index_version=index_version)
            payloads = [
                {
                    "chunk_id": chunk.id,
                    "document_id": stored.id,
                    "url": stored.url or "",
                    "title": stored.title,
                    "competitor": stored.competitor or "",
                    "dimension": stored.dimension or "",
                    "source_type": stored.source_type,
                    "content_hash": chunk.content_hash,
                    "crawl_run_id": chunk.crawl_run_id or "",
                    "text": chunk.text,
                    "metadata": stored.metadata,
                    "embedding_model": embedding_model,
                    "embedding_dimensions": dimensions,
                    "index_version": index_version,
                }
                for chunk in chunks
            ]
            await self._vs.upsert([chunk.id for chunk in chunks], vectors, payloads)
        except Exception as exc:
            await self._repo.set_indexing_state(
                stored.id,
                "failed",
                error=f"{stage}: {exc}",
                embedding_model=embedding_model,
                dimensions=dimensions,
                index_version=index_version,
            )
            raise
        await self._repo.set_indexing_state(
            stored.id,
            "ready",
            embedding_model=embedding_model,
            dimensions=dimensions,
            index_version=index_version,
        )

    def _chunk_text(
        self,
        text: str,
        document_id: str,
        content_hash: str,
        embedding_model: str = _DEFAULT_EMBEDDING_MODEL,
        *,
        crawl_run_id: str | None = None,
    ) -> list[KnowledgeChunk]:
        """Split text into paragraph-aware chunks."""
        if not text:
            return []

        chunks: list[KnowledgeChunk] = []
        idx = 0
        current_parts: list[str] = []
        current_size = 0

        def append_chunk(chunk_text: str) -> None:
            nonlocal idx
            if chunk_text.strip():
                chunk_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{document_id}:{idx}"))
                chunks.append(
                    KnowledgeChunk(
                        id=chunk_id,
                        document_id=document_id,
                        chunk_index=idx,
                        text=chunk_text,
                        token_count=self._estimate_tokens(chunk_text),
                        embedding_model=embedding_model,
                        content_hash=hashlib.sha256(chunk_text.encode()).hexdigest()[:16],
                        crawl_run_id=crawl_run_id,
                    )
                )
                idx += 1

        def flush_current() -> None:
            nonlocal current_parts, current_size
            if current_parts:
                append_chunk("\n\n".join(current_parts))
                current_parts = []
                current_size = 0

        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        for paragraph in paragraphs:
            if len(paragraph) > self._chunk_size:
                flush_current()
                for chunk_text in self._split_long_paragraph(paragraph):
                    append_chunk(chunk_text)
                continue

            projected_size = current_size + len(paragraph) + (2 if current_parts else 0)
            if current_parts and projected_size > self._chunk_size:
                flush_current()
            current_parts.append(paragraph)
            current_size += len(paragraph) + (2 if len(current_parts) > 1 else 0)

        flush_current()

        return chunks

    def _split_long_paragraph(self, paragraph: str) -> list[str]:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?。！？])\s+", paragraph) if s.strip()]
        if len(sentences) <= 1:
            return self._split_by_character_window(paragraph)

        chunks: list[str] = []
        current: list[str] = []
        current_size = 0
        for sentence in sentences:
            if len(sentence) > self._chunk_size:
                if current:
                    chunks.append(" ".join(current))
                    current = []
                    current_size = 0
                chunks.extend(self._split_by_character_window(sentence))
                continue
            projected_size = current_size + len(sentence) + (1 if current else 0)
            if current and projected_size > self._chunk_size:
                chunks.append(" ".join(current))
                current = []
                current_size = 0
            current.append(sentence)
            current_size += len(sentence) + (1 if len(current) > 1 else 0)
        if current:
            chunks.append(" ".join(current))
        return chunks

    def _split_by_character_window(self, text: str) -> list[str]:
        chunks: list[str] = []
        step = max(1, self._chunk_size - self._chunk_overlap)
        start = 0
        while start < len(text):
            chunk_text = text[start : start + self._chunk_size].strip()
            if chunk_text:
                chunks.append(chunk_text)
            start += step
        return chunks

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        word_count = len(re.findall(r"\w+", text))
        if word_count:
            return max(1, int(word_count * 1.3))
        return max(1, len(text) // _CHAR_TOKEN_RATIO)


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value
