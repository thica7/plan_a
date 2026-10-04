"""Document ingestion pipeline: chunk -> embed -> store in Qdrant + SQLite."""

from __future__ import annotations

import hashlib
import inspect
import math
import os
import re
import uuid
from collections.abc import Callable
from datetime import UTC
from typing import Any

from .embeddings import EmbeddingProvider
from .models import DocumentCreate, KnowledgeChunk, KnowledgeDocument
from .repository import KnowledgeRepository

# Offline estimate only; UTF-8 bytes account for unspaced multilingual text.
_BYTES_PER_ESTIMATED_TOKEN = 4
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
        crawl_source_id: str | None = None,
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
        if crawl_source_id is not None:
            # The guarded upsert must run even when this body already exists.
            stored = await self._repo.upsert_document(
                doc, content_hash, crawl_source_id=crawl_source_id,
            )
        else:
            stored = await self._repo.get_document_by_content_hash(
                content_hash, scope=doc.scope, competitor=doc.competitor, dimension=doc.dimension,
                market=doc.market, source_role=doc.source_role,
            )
            if stored is None or (
                doc.metadata.get("source_material_level") == "full_source"
                and stored.metadata.get("source_material_level") != "full_source"
            ):
                stored = await self._repo.upsert_document(doc, content_hash)
        if stored.content_hash != content_hash:
            # A summary downgrade was declined; its caller must not build or index the full page.
            return stored.id
        chunks = await self._repo.get_chunks_for_document(stored.id)
        if not chunks:
            chunks = self._chunk_text(
                stored.text, stored.id, content_hash, "", crawl_run_id=crawl_run_id,
                structure=stored.metadata, markdown=stored.markdown,
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
            chunks = self._chunk_text(
                stored.text, stored.id, stored.content_hash, "",
                structure=stored.metadata, markdown=stored.markdown,
            )
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
            observed_at = (stored.last_verified_at or stored.source_updated_at
                           or stored.source_published_at or stored.fetched_at)
            if observed_at.tzinfo is None:
                observed_at = observed_at.replace(tzinfo=UTC)
            payloads = [
                {
                    "chunk_id": chunk.id,
                    "document_id": stored.id,
                    "url": stored.url or "",
                    "title": stored.title,
                    "competitor": stored.competitor or "",
                    "competitor_key": (stored.competitor or "").casefold(),
                    "dimension": stored.dimension or "",
                    "dimension_key": (stored.dimension or "").casefold(),
                    "source_type": stored.source_type,
                    "workspace_id": stored.workspace_id or "",
                    "project_id": stored.project_id or "",
                    "market": stored.market,
                    "source_role": stored.source_role,
                    "source_published_at": (
                        stored.source_published_at.isoformat()
                        if stored.source_published_at else None
                    ),
                    "last_verified_at": (
                        stored.last_verified_at.isoformat() if stored.last_verified_at else None
                    ),
                    "source_updated_at": (
                        stored.source_updated_at.isoformat() if stored.source_updated_at else None
                    ),
                    "fetched_at": stored.fetched_at.isoformat(),
                    "observed_at": observed_at.isoformat(),
                    "document_version": stored.version,
                    "content_hash": chunk.content_hash,
                    "document_content_hash": stored.content_hash,
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
        structure: dict[str, Any] | None = None,
        markdown: str = "",
    ) -> list[KnowledgeChunk]:
        """Split text into paragraph-aware chunks."""
        if not text:
            return []

        chunks: list[KnowledgeChunk] = []
        idx = 0
        headings = [
            {"level": len(match.group(1)), "text": match.group(2).strip()}
            for line in markdown.splitlines()
            if (match := re.match(r"^(#{1,6})\s+(.+?)\s*$", line))
        ] or (structure or {}).get("headings", [])
        heading_positions: list[tuple[int, dict[str, Any]]] = []
        cursor = 0
        for heading in headings:
            value = heading.get("text", "")
            match = re.search(rf"(?m)^{re.escape(value)}$", text[cursor:]) if value else None
            pos = cursor + match.start() if match else -1
            if pos >= 0:
                heading_positions.append((pos, heading))
                cursor = pos + len(value)
        heading_starts = {position for position, _ in heading_positions}

        def append_chunk(chunk_text: str, start: int, extra: dict[str, Any] | None = None) -> None:
            nonlocal idx
            if chunk_text.strip():
                metadata: dict[str, Any] = {"structure": "unknown"}
                heading_path: list[dict[str, Any]] = []
                for position, heading in heading_positions:
                    if position <= start:
                        level = heading.get("level", 1)
                        while heading_path and heading_path[-1].get("level", 1) >= level:
                            heading_path.pop()
                        heading_path.append(heading)
                    else:
                        break
                if heading_path:
                    metadata.update({
                        "heading": heading_path[-1],
                        "heading_path": heading_path,
                        "structure": "body",
                    })
                if extra:
                    metadata.update(extra)
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
                        metadata=metadata,
                    )
                )
                idx += 1

        def append_plain(start: int, end: int) -> None:
            segment = text[start:end]
            paragraph_spans: list[tuple[int, int]] = []
            boundary = start
            for match in re.finditer(r"\n\s*\n", segment):
                paragraph_spans.append((boundary, start + match.start()))
                boundary = start + match.end()
            paragraph_spans.append((boundary, end))
            current_start: int | None = None
            current_end = 0

            def flush() -> None:
                nonlocal current_start
                if current_start is not None:
                    append_chunk(text[current_start:current_end], current_start)
                    current_start = None

            for paragraph_start, paragraph_end in paragraph_spans:
                while paragraph_start < paragraph_end and text[paragraph_start].isspace():
                    paragraph_start += 1
                while paragraph_end > paragraph_start and text[paragraph_end - 1].isspace():
                    paragraph_end -= 1
                if paragraph_start == paragraph_end:
                    continue
                if paragraph_start in heading_starts and current_start is not None:
                    flush()
                if paragraph_end - paragraph_start > self._chunk_size:
                    flush()
                    for piece in self._split_long_paragraph(text[paragraph_start:paragraph_end]):
                        position = text.find(piece, paragraph_start, paragraph_end)
                        append_chunk(piece, position)
                    continue
                if current_start is not None and paragraph_end - current_start > self._chunk_size:
                    flush()
                if current_start is None:
                    current_start = paragraph_start
                current_end = paragraph_end
            flush()

        tables = (structure or {}).get("tables", [])
        offset = 0
        for table in tables:
            table_text = table.get("text") if isinstance(table, dict) else None
            if not isinstance(table_text, str) or not table_text:
                continue
            position = text.find(table_text, offset)
            if position < 0:
                continue
            table_start = position
            previous_end = position
            while previous_end > offset and text[previous_end - 1].isspace():
                previous_end -= 1
            previous_break = text.rfind("\n\n", offset, previous_end)
            previous_start = previous_break + 2 if previous_break >= 0 else offset
            if (
                previous_start < previous_end
                and not any(previous_start <= head < position for head in heading_starts)
            ):
                table_start = previous_start
            table_end = position + len(table_text)
            next_start = table_end
            while next_start < len(text) and text[next_start].isspace():
                next_start += 1
            next_break = text.find("\n\n", next_start)
            next_end = next_break if next_break >= 0 else len(text)
            if (
                next_start < next_end
                and not any(next_start <= head < next_end for head in heading_starts)
                and not any(
                    isinstance(other, dict) and other.get("text") == text[next_start:next_end]
                    for other in tables
                )
            ):
                table_end = next_end
            append_plain(offset, table_start)
            chunk_text = text[table_start:table_end]
            table_metadata: dict[str, Any] = {
                "structure": "table", "overflow": len(chunk_text) > self._chunk_size,
            }
            if len(chunk_text) > self._chunk_size:
                table_metadata["overflow_chars"] = len(chunk_text) - self._chunk_size
            if table.get("structure_gap"):
                table_metadata["structure_gap"] = table["structure_gap"]
            if table.get("structure_gaps"):
                table_metadata["structure_gaps"] = table["structure_gaps"]
            append_chunk(chunk_text, table_start, table_metadata)
            offset = table_end
        append_plain(offset, len(text))

        return chunks

    def _split_long_paragraph(self, paragraph: str) -> list[str]:
        boundaries = [
            match.end() for match in re.finditer(r"[!?。！？]|(?<!\d)\.(?!\d)", paragraph)
            if paragraph[match.start()] in "。！？"
            or match.end() == len(paragraph)
            or not paragraph[match.end()].isascii()
            or paragraph[match.end()].isspace()
        ]
        if not boundaries:
            return self._split_by_character_window(paragraph)
        spans: list[tuple[int, int]] = []
        start = 0
        for boundary in boundaries:
            if boundary > start:
                spans.append((start, boundary))
            start = boundary
            while start < len(paragraph) and paragraph[start].isspace():
                start += 1
        if start < len(paragraph):
            spans.append((start, len(paragraph)))
        chunks: list[str] = []
        current_start: int | None = None
        current_end = 0
        for start, end in spans:
            if end - start > self._chunk_size:
                if current_start is not None:
                    chunks.append(paragraph[current_start:current_end])
                    current_start = None
                chunks.extend(self._split_by_character_window(paragraph[start:end]))
                continue
            if current_start is not None and end - current_start > self._chunk_size:
                chunks.append(paragraph[current_start:current_end])
                current_start = None
            if current_start is None:
                current_start = start
            current_end = end
        if current_start is not None:
            chunks.append(paragraph[current_start:current_end])
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
        return max(1, math.ceil(len(text.encode("utf-8")) / _BYTES_PER_ESTIMATED_TOKEN))


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value
