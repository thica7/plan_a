"""Qdrant vector store adapter for Knowledge Base."""

from __future__ import annotations

import asyncio
import hashlib
import math
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

from qdrant_client import QdrantClient
from qdrant_client.models import (
    DatetimeRange,
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PointStruct,
    SearchParams,
    VectorParams,
)

from .models import KnowledgeScope, RetrievalHit

COLLECTION_NAME = "knowledge_chunks"
EMBEDDING_DIM = 1024  # bge-m3
_MAX_RETRIES = 3
_RETRY_BASE_SECONDS = 0.2
T = TypeVar("T")


class VectorStore:
    """Async-friendly Qdrant adapter. Uses sync client under the hood with
    async wrappers so it integrates cleanly with the FastAPI event loop."""

    def __init__(self, url: str | None = None, *, client: QdrantClient | None = None) -> None:
        url = url or os.getenv("QDRANT_URL", "http://localhost:6333")
        self._client = client
        self._url = url
        self._initialised = False
        self._collection_base = os.getenv("KB_VECTOR_COLLECTION", COLLECTION_NAME)
        self._model_version = os.getenv("KB_EMBEDDING_MODEL_VERSION", "hash-embedding-v1")
        self._dimensions = int(os.getenv("KB_EMBEDDING_DIM", str(EMBEDDING_DIM)))
        self._index_version = os.getenv("KB_INDEX_VERSION", "v1")

    @property
    def collection_name(self) -> str:
        identity = f"{self._index_version}:{self._model_version}:{self._dimensions}"
        fingerprint = hashlib.sha256(identity.encode()).hexdigest()[:16]
        return f"{self._collection_base}__{fingerprint}"

    def configure_index(
        self, model_version: str, dimensions: int, *, index_version: str | None = None
    ) -> None:
        if dimensions <= 0 or not model_version:
            raise ValueError("Index model and dimension must be specified")
        version = index_version or os.getenv("KB_INDEX_VERSION", "v1")
        identity = (model_version, dimensions, version)
        if self._initialised and identity != (
            self._model_version,
            self._dimensions,
            self._index_version,
        ):
            raise ValueError("Index model changed; create a separate vector store or reindex")
        self._model_version, self._dimensions, self._index_version = identity

    def status(self) -> dict[str, Any]:
        return {
            "collection": self.collection_name,
            "index_version": self._index_version,
            "model_version": self._model_version,
            "dimensions": self._dimensions,
        }

    async def initialise(self) -> None:
        if self._initialised:
            return
        if self._client is None:
            self._client = QdrantClient(url=self._url)
        collections = self._client.get_collections().collections
        names = {c.name for c in collections}
        if self.collection_name not in names:
            self._client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=self._dimensions, distance=Distance.COSINE),
            )
        else:
            info = self._client.get_collection(self.collection_name)
            vectors = info.config.params.vectors
            if not isinstance(vectors, VectorParams) or vectors.size != self._dimensions:
                raise ValueError(
                    "Collection dimension does not match the configured index; reindex required"
                )
        self._initialised = True

    async def _with_retry(self, operation: Callable[[], T]) -> T:
        for attempt in range(_MAX_RETRIES):
            try:
                return operation()
            except Exception:
                if attempt >= _MAX_RETRIES - 1:
                    raise
                await asyncio.sleep(_RETRY_BASE_SECONDS * (2**attempt))
        raise RuntimeError("Retry loop exhausted")

    async def upsert(
        self,
        chunk_ids: list[str],
        vectors: list[list[float]],
        payloads: list[dict[str, Any]],
    ) -> None:
        if not (len(chunk_ids) == len(vectors) == len(payloads)):
            raise ValueError("Vector batch lengths must match")
        for vector, payload in zip(vectors, payloads, strict=True):
            if len(vector) != self._dimensions or not all(math.isfinite(value) for value in vector):
                raise ValueError("Vector dimension must match index and values must be finite")
            if payload.get("embedding_model") != self._model_version:
                raise ValueError("Payload model must match the configured index")
            if payload.get("index_version", self._index_version) != self._index_version:
                raise ValueError("Payload index version must match the configured index")
        await self.initialise()
        points = [
            PointStruct(id=cid, vector=vec, payload=pl)
            for cid, vec, pl in zip(chunk_ids, vectors, payloads, strict=True)
        ]
        # Batch upsert (Qdrant handles large batches natively)
        batch_size = 100
        for i in range(0, len(points), batch_size):
            batch = points[i : i + batch_size]
            await self._with_retry(
                lambda batch=batch: self._client.upsert(
                    collection_name=self.collection_name,
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
        scope: KnowledgeScope | None = None,
        market: str | None = None,
        source_roles: list[str] | None = None,
        max_age_days: int | None = None,
    ) -> list[RetrievalHit]:
        if len(query_vector) != self._dimensions:
            raise ValueError("Query vector dimension does not match index")
        await self.initialise()
        must_conditions: list[FieldCondition] = [
            FieldCondition(key="embedding_model", match=MatchValue(value=self._model_version)),
            FieldCondition(key="index_version", match=MatchValue(value=self._index_version)),
        ]
        if competitors:
            must_conditions.append(
                FieldCondition(key="competitor_key", match=MatchAny(
                    any=[item.casefold() for item in competitors]
                ))
            )
        if dimensions:
            must_conditions.append(FieldCondition(key="dimension_key", match=MatchAny(
                any=[item.casefold() for item in dimensions]
            )))
        if scope is not None:
            must_conditions.append(FieldCondition(
                key="workspace_id", match=MatchValue(value=scope.workspace_id)
            ))
            project_match = (
                MatchAny(any=[scope.project_id, ""])
                if scope.project_id is not None and scope.include_workspace_library
                else MatchValue(value=scope.project_id or "")
            )
            must_conditions.append(FieldCondition(key="project_id", match=project_match))
        if market is not None:
            must_conditions.append(FieldCondition(key="market", match=MatchValue(value=market)))
        if source_roles:
            must_conditions.append(FieldCondition(
                key="source_role", match=MatchAny(any=source_roles)
            ))
        if max_age_days is not None:
            if max_age_days < 0:
                raise ValueError("max_age_days must be nonnegative")
            now = datetime.now(UTC)
            must_conditions.append(FieldCondition(
                key="observed_at", range=DatetimeRange(
                    gte=now - timedelta(days=max_age_days), lte=now,
                ),
            ))

        search_filter = Filter(must=must_conditions) if must_conditions else None

        results = await self._search_points(query_vector, search_filter, top_k)

        hits: list[RetrievalHit] = []
        for r in results:
            pl = r.payload or {}
            if scope is not None and (
                not pl.get("workspace_id") or "project_id" not in pl
                or not pl.get("document_content_hash") or not pl.get("document_version")
                or not pl.get("fetched_at")
                or pl.get("source_role") not in {"source", "historical_report"}
            ):
                continue
            metadata = dict(pl.get("metadata", {})) if isinstance(pl.get("metadata"), dict) else {}
            metadata["vector_index"] = {
                "model_version": pl.get("embedding_model"),
                "index_version": pl.get("index_version"),
                "dimensions": pl.get("embedding_dimensions"),
                "chunk_content_hash": pl.get("content_hash"),
            }
            hits.append(
                RetrievalHit(
                    chunk_id=pl.get("chunk_id", str(r.id)),
                    document_id=pl.get("document_id", ""),
                    text=pl.get("text", ""),
                    score=r.score,
                    url=pl.get("url"),
                    title=pl.get("title", ""),
                    competitor=pl.get("competitor"),
                    dimension=pl.get("dimension"),
                    source_type=pl.get("source_type", ""),
                    workspace_id=pl.get("workspace_id") or None,
                    project_id=pl.get("project_id") or None,
                    market=pl.get("market"),
                    source_role=pl.get("source_role", "source"),
                    document_version=pl.get("document_version", 1),
                    source_published_at=pl.get("source_published_at"),
                    source_updated_at=pl.get("source_updated_at"),
                    last_verified_at=pl.get("last_verified_at"),
                    fetched_at=pl.get("fetched_at"),
                    content_hash=pl.get("document_content_hash", ""),
                    metadata=metadata,
                )
            )
        return hits

    async def _search_points(
        self,
        query_vector: list[float],
        search_filter: Filter | None,
        top_k: int,
    ) -> list[Any]:
        search_params = SearchParams(exact=False, hnsw_ef=128)
        if hasattr(self._client, "search"):
            return await self._with_retry(
                lambda: self._client.search(
                    collection_name=self.collection_name,
                    query_vector=query_vector,
                    limit=top_k,
                    query_filter=search_filter,
                    search_params=search_params,
                )
            )
        response = await self._with_retry(
            lambda: self._client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                limit=top_k,
                query_filter=search_filter,
                search_params=search_params,
            )
        )
        return list(response.points)

    async def delete_by_document(self, document_id: str) -> None:
        await self.delete_by_documents([document_id])

    async def delete_by_documents(self, document_ids: list[str]) -> None:
        if not document_ids:
            return
        await self.initialise()
        match = (
            MatchValue(value=document_ids[0])
            if len(document_ids) == 1
            else MatchAny(any=document_ids)
        )
        collections = self._client.get_collections().collections
        for collection in collections:
            if collection.name != self._collection_base and not collection.name.startswith(
                self._collection_base + "__"
            ):
                continue
            await self._with_retry(
                lambda name=collection.name: self._client.delete(
                    collection_name=name,
                    points_selector=Filter(must=[FieldCondition(key="document_id", match=match)]),
                ),
            )

    async def collection_info(self) -> dict[str, Any]:
        await self.initialise()
        info = await self._with_retry(
            lambda: self._client.get_collection(collection_name=self.collection_name)
        )
        return {
            "name": self.collection_name,
            **self.status(),
            "status": getattr(info, "status", None),
            "vectors_count": getattr(info, "vectors_count", None),
            "points_count": getattr(info, "points_count", None),
            "indexed_vectors_count": getattr(info, "indexed_vectors_count", None),
        }
