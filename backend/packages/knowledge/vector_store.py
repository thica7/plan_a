"""Qdrant vector store adapter for Knowledge Base."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, TypeVar

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PointStruct,
    SearchParams,
    VectorParams,
)

from .models import RetrievalHit

COLLECTION_NAME = "knowledge_chunks"
EMBEDDING_DIM = 1024  # bge-m3
_MAX_RETRIES = 3
_RETRY_BASE_SECONDS = 0.2
T = TypeVar("T")


class VectorStore:
    """Async-friendly Qdrant adapter. Uses sync client under the hood with
    async wrappers so it integrates cleanly with the FastAPI event loop."""

    def __init__(self, url: str = "http://localhost:6333") -> None:
        self._client = QdrantClient(url=url)
        self._initialised = False

    async def initialise(self) -> None:
        if self._initialised:
            return
        collections = self._client.get_collections().collections
        names = {c.name for c in collections}
        if COLLECTION_NAME not in names:
            self._client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
            )
        self._initialised = True

    async def _with_retry(self, operation: Callable[[], T]) -> T:
        for attempt in range(_MAX_RETRIES):
            try:
                return operation()
            except Exception:
                if attempt >= _MAX_RETRIES - 1:
                    raise
                await asyncio.sleep(_RETRY_BASE_SECONDS * (2 ** attempt))
        raise RuntimeError("Retry loop exhausted")

    async def upsert(
        self,
        chunk_ids: list[str],
        vectors: list[list[float]],
        payloads: list[dict[str, Any]],
    ) -> None:
        points = [
            PointStruct(id=cid, vector=vec, payload=pl)
            for cid, vec, pl in zip(chunk_ids, vectors, payloads, strict=False)
        ]
        # Batch upsert (Qdrant handles large batches natively)
        batch_size = 100
        for i in range(0, len(points), batch_size):
            batch = points[i : i + batch_size]
            await self._with_retry(
                lambda batch=batch: self._client.upsert(
                    collection_name=COLLECTION_NAME,
                    points=batch,
                )
            )

    async def search(
        self,
        query_vector: list[float],
        *,
        top_k: int = 20,
        competitors: list[str] | None = None,
        dimensions: list[str] | None = None,
    ) -> list[RetrievalHit]:
        must_conditions: list[FieldCondition] = []
        if competitors:
            must_conditions.append(
                FieldCondition(key="competitor", match=MatchAny(any=competitors))
            )
        if dimensions:
            must_conditions.append(
                FieldCondition(key="dimension", match=MatchAny(any=dimensions))
            )

        search_filter = Filter(must=must_conditions) if must_conditions else None

        results = await self._with_retry(
            lambda: self._client.search(
                collection_name=COLLECTION_NAME,
                query_vector=query_vector,
                limit=top_k,
                query_filter=search_filter,
                search_params=SearchParams(exact=False, hnsw_ef=128),
            )
        )

        hits: list[RetrievalHit] = []
        for r in results:
            pl = r.payload or {}
            hits.append(RetrievalHit(
                chunk_id=pl.get("chunk_id", str(r.id)),
                document_id=pl.get("document_id", ""),
                text=pl.get("text", ""),
                score=r.score,
                url=pl.get("url"),
                title=pl.get("title", ""),
                competitor=pl.get("competitor"),
                dimension=pl.get("dimension"),
                source_type=pl.get("source_type", ""),
                content_hash=pl.get("content_hash", ""),
            ))
        return hits

    async def delete_by_document(self, document_id: str) -> None:
        await self.delete_by_documents([document_id])

    async def delete_by_documents(self, document_ids: list[str]) -> None:
        if not document_ids:
            return
        match = (
            MatchValue(value=document_ids[0])
            if len(document_ids) == 1
            else MatchAny(any=document_ids)
        )
        await self._with_retry(
            lambda: self._client.delete(
                collection_name=COLLECTION_NAME,
                points_selector=Filter(
                    must=[FieldCondition(key="document_id", match=match)]
                ),
            ),
        )

    async def collection_info(self) -> dict[str, Any]:
        info = await self._with_retry(
            lambda: self._client.get_collection(collection_name=COLLECTION_NAME)
        )
        return {
            "name": COLLECTION_NAME,
            "status": getattr(info, "status", None),
            "vectors_count": getattr(info, "vectors_count", None),
            "points_count": getattr(info, "points_count", None),
            "indexed_vectors_count": getattr(info, "indexed_vectors_count", None),
        }
