"""Hybrid retrieval service: dense vector + FTS keyword + RRF fusion + rerank."""

from __future__ import annotations

import inspect
import math
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from collections.abc import Callable
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, Field

from packages.config import get_settings
from packages.llm import DoubaoClient

from .models import RetrievalHit, RetrievalRequest, RetrievalResponse
from .repository import KnowledgeRepository

_DEFAULT_CACHE_TTL_SECONDS = 300.0
_DEFAULT_CACHE_MAXSIZE = 256


class RetrievalPreset(BaseModel):
    name: str
    description: str
    dense_weight: float = Field(ge=0.0, le=1.0)
    sparse_weight: float = Field(ge=0.0, le=1.0)
    top_k: int = Field(ge=1)
    rerank_top_k: int = Field(ge=0)
    mmr_lambda: float = Field(ge=0.0, le=1.0)
    query_rewrite_enabled: bool


_BUILTIN_PRESETS: tuple[RetrievalPreset, ...] = (
    RetrievalPreset(
        name="general",
        description="Balanced hybrid retrieval for broad competitor analysis.",
        dense_weight=0.7,
        sparse_weight=0.3,
        top_k=10,
        rerank_top_k=20,
        mmr_lambda=0.1,
        query_rewrite_enabled=True,
    ),
    RetrievalPreset(
        name="pricing",
        description="Keyword-first retrieval for prices, plan names, and numeric facts.",
        dense_weight=0.3,
        sparse_weight=0.7,
        top_k=5,
        rerank_top_k=15,
        mmr_lambda=0.0,
        query_rewrite_enabled=False,
    ),
    RetrievalPreset(
        name="comparison",
        description="Diverse hybrid retrieval for cross-competitor comparisons.",
        dense_weight=0.5,
        sparse_weight=0.5,
        top_k=15,
        rerank_top_k=30,
        mmr_lambda=0.2,
        query_rewrite_enabled=True,
    ),
)


def get_retrieval_presets() -> list[RetrievalPreset]:
    return [preset.model_copy(deep=True) for preset in _BUILTIN_PRESETS]


def get_retrieval_preset(name: str) -> RetrievalPreset:
    for preset in _BUILTIN_PRESETS:
        if preset.name == name:
            return preset.model_copy(deep=True)
    raise ValueError(f"Unknown retrieval preset: {name}")


def apply_retrieval_preset(request: RetrievalRequest) -> RetrievalRequest:
    if not request.preset:
        return request
    preset = get_retrieval_preset(request.preset)
    return request.model_copy(update={
        "dense_weight": preset.dense_weight,
        "sparse_weight": preset.sparse_weight,
        "top_k": preset.top_k,
        "rerank_top_k": preset.rerank_top_k,
        "final_top_k": preset.top_k,
        "mmr_lambda": preset.mmr_lambda,
        "enable_query_rewrite": preset.query_rewrite_enabled,
    })


class QueryRewriter(ABC):
    """Produces alternate query phrasings for recall-oriented retrieval."""

    @abstractmethod
    async def rewrite(self, query: str, *, num_rewrites: int) -> list[str]:
        """Return alternate phrasings for query."""


class DefaultQueryRewriter(QueryRewriter):
    """LLM-backed query rewriter with a safe offline no-op fallback."""

    def __init__(self, llm: DoubaoClient | None = None) -> None:
        self._llm = llm or DoubaoClient(get_settings())

    async def rewrite(self, query: str, *, num_rewrites: int) -> list[str]:
        if num_rewrites <= 0:
            return []
        try:
            payload = await self._llm.complete_json(
                system=(
                    "Rewrite retrieval queries for a competitive intelligence knowledge base. "
                    "Return concise paraphrases that preserve the user's intent."
                ),
                user=f"Query: {query}\nReturn {num_rewrites} paraphrases.",
                schema_hint='{"rewrites": ["paraphrase 1", "paraphrase 2"]}',
            )
        except Exception:
            return []
        raw_rewrites = payload.get("rewrites", [])
        if not isinstance(raw_rewrites, list):
            return []

        rewrites: list[str] = []
        seen = {query.strip().lower()}
        for item in raw_rewrites:
            if not isinstance(item, str):
                continue
            rewrite = item.strip()
            key = rewrite.lower()
            if not rewrite or key in seen:
                continue
            rewrites.append(rewrite)
            seen.add(key)
            if len(rewrites) >= num_rewrites:
                break
        return rewrites


class _TTLCache:
    def __init__(self, *, maxsize: int, ttl_seconds: float) -> None:
        self._maxsize = max(1, maxsize)
        self._ttl_seconds = ttl_seconds
        self._items: OrderedDict[str, tuple[float, Any]] = OrderedDict()

        @lru_cache(maxsize=self._maxsize)
        def cached_get(key: str, bucket: int) -> Any | None:
            item = self._items.get(key)
            if item is None:
                return None
            created_at, value = item
            if time.monotonic() - created_at >= self._ttl_seconds:
                return None
            return value

        self._cached_get = cached_get

    def get(self, key: str) -> Any | None:
        now = time.monotonic()
        bucket = int(now / self._ttl_seconds) if self._ttl_seconds > 0 else 0
        value = self._cached_get(key, bucket)
        if value is None:
            item = self._items.get(key)
            if item is not None and now - item[0] >= self._ttl_seconds:
                self._items.pop(key, None)
            return None
        self._items.move_to_end(key)
        return value

    def set(self, key: str, value: Any) -> None:
        self._items[key] = (time.monotonic(), value)
        self._cached_get.cache_clear()
        self._items.move_to_end(key)
        while len(self._items) > self._maxsize:
            self._items.popitem(last=False)


def _normalise_scores(hits: list[RetrievalHit]) -> list[RetrievalHit]:
    """Min-max normalise scores to [0, 1]."""
    if not hits:
        return hits
    scores = [h.score for h in hits]
    lo, hi = min(scores), max(scores)
    span = hi - lo if hi > lo else 1.0
    for h in hits:
        h.score = (h.score - lo) / span
    return hits


def _rrf_fusion(
    dense_hits: list[RetrievalHit],
    sparse_hits: list[RetrievalHit],
    k: int = 60,
    dense_weight: float = 1.0,
    sparse_weight: float = 1.0,
) -> list[RetrievalHit]:
    """Reciprocal Rank Fusion of two ranked lists."""
    return _rrf_fuse_ranked_lists(
        [dense_hits, sparse_hits],
        weights=[dense_weight, sparse_weight],
        k=k,
    )


def _rrf_fuse_ranked_lists(
    ranked_lists: list[list[RetrievalHit]],
    *,
    weights: list[float] | None = None,
    k: int = 60,
) -> list[RetrievalHit]:
    rrf_scores: dict[str, float] = {}
    hit_map: dict[str, RetrievalHit] = {}
    weights = weights or [1.0] * len(ranked_lists)

    for hits, weight in zip(ranked_lists, weights, strict=False):
        for rank, hit in enumerate(hits, 1):
            rrf_scores[hit.chunk_id] = rrf_scores.get(hit.chunk_id, 0.0) + weight / (k + rank)
            hit_map[hit.chunk_id] = hit.model_copy(deep=True)

    sorted_ids = sorted(rrf_scores, key=lambda cid: rrf_scores[cid], reverse=True)
    result: list[RetrievalHit] = []
    for cid in sorted_ids:
        hit = hit_map[cid]
        hit.score = rrf_scores[cid]
        result.append(hit)
    return result


class RetrievalService:
    """Orchestrates hybrid retrieval across Qdrant + SQLite FTS."""

    def __init__(
        self,
        repo: KnowledgeRepository,
        vector_store: Any,
        *,
        embed_fn: Callable[[list[str]], Any],
        rerank_fn: Callable[[str, list[str]], Any] | None = None,
        rerank_model: str | None = None,
        query_rewriter: QueryRewriter | None = None,
        dense_weight: float = 1.0,
        sparse_weight: float = 1.0,
        score_threshold: float = 0.0,
        cache_ttl: float = _DEFAULT_CACHE_TTL_SECONDS,
        cache_maxsize: int = _DEFAULT_CACHE_MAXSIZE,
    ) -> None:
        self._repo = repo
        self._vs = vector_store
        self._embed_fn = embed_fn
        self._rerank_fn = rerank_fn
        self._rerank_model = rerank_model
        self._query_rewriter = query_rewriter or DefaultQueryRewriter()
        self._dense_weight = dense_weight
        self._sparse_weight = sparse_weight
        self._score_threshold = score_threshold
        self._embedding_cache = _TTLCache(maxsize=cache_maxsize, ttl_seconds=cache_ttl)
        self._retrieval_cache = _TTLCache(maxsize=cache_maxsize, ttl_seconds=cache_ttl)
        self._reset_observability_counts()

    async def retrieve(self, request: RetrievalRequest) -> RetrievalResponse:
        request = apply_retrieval_preset(request)
        self._reset_observability_counts()
        started_at = time.monotonic()
        cache_hit = False

        if request.enable_query_rewrite and request.num_rewrites > 0:
            response = await self._retrieve_with_rewrites(request)
        else:
            cache_key = self._cache_key(request)
            cached = self._retrieval_cache.get(cache_key)
            if cached is not None:
                cache_hit = True
                response = cached.model_copy(deep=True)
            else:
                response = await self._retrieve_without_rewrites(request)
                self._retrieval_cache.set(cache_key, response.model_copy(deep=True))

        await self._record_observability(
            request,
            latency_ms=(time.monotonic() - started_at) * 1000,
            cache_hit=cache_hit,
        )
        return response

    async def _retrieve_with_rewrites(self, request: RetrievalRequest) -> RetrievalResponse:
        rewrites = await self._query_rewriter.rewrite(
            request.query,
            num_rewrites=request.num_rewrites,
        )
        queries = [request.query, *rewrites[: request.num_rewrites]]
        ranked_lists = [
            await self._search_once(query, request)
            for query in queries
        ]
        fused = _rrf_fuse_ranked_lists(ranked_lists)
        fused = _filter_hits_by_request(fused, request)
        fused = self._filter_by_score_threshold(fused)
        top = await self._post_process(request.query, fused, request)
        return RetrievalResponse(hits=top, query=request.query, total=len(fused))

    async def _retrieve_without_rewrites(self, request: RetrievalRequest) -> RetrievalResponse:
        fused = await self._search_once(request.query, request)
        fused = _filter_hits_by_request(fused, request)
        fused = self._filter_by_score_threshold(fused)
        top = await self._post_process(request.query, fused, request)
        return RetrievalResponse(hits=top, query=request.query, total=len(fused))

    async def _search_once(
        self,
        query: str,
        request: RetrievalRequest,
    ) -> list[RetrievalHit]:
        dense_hits: list[RetrievalHit] = []
        sparse_hits: list[RetrievalHit] = []

        if request.mode in {"dense", "hybrid"}:
            qvec = await self._embed_query(query)
            dense_hits = await self._vs.search(
                qvec,
                top_k=request.top_k,
                competitors=request.competitors or None,
                dimensions=request.dimensions or None,
            )
            dense_hits = _normalise_scores(dense_hits)
            self._dense_hits += len(dense_hits)

        if request.mode == "hybrid":
            sparse_hits = await self._sparse_search(
                query,
                request.top_k,
                competitors=request.competitors or None,
                dimensions=request.dimensions or None,
            )
            self._sparse_hits += len(sparse_hits)

        if request.mode == "hybrid" and dense_hits and sparse_hits:
            return _rrf_fusion(
                dense_hits,
                sparse_hits,
                dense_weight=request.dense_weight,
                sparse_weight=request.sparse_weight,
            )
        if dense_hits:
            return dense_hits
        return sparse_hits

    async def _sparse_search(
        self,
        query: str,
        top_k: int,
        *,
        competitors: list[str] | None = None,
        dimensions: list[str] | None = None,
    ) -> list[RetrievalHit]:
        keyword_docs = await self._repo.search_documents(
            query,
            limit=top_k,
            competitors=competitors,
            dimensions=dimensions,
        )
        sparse_hits: list[RetrievalHit] = []
        chunks_by_doc = await self._repo.get_chunks_for_documents([doc.id for doc in keyword_docs])
        for doc_rank, doc in enumerate(keyword_docs, 1):
            chunks = chunks_by_doc.get(doc.id, [])
            weight_fn = getattr(self._repo, "get_document_weight", None)
            document_weight = weight_fn(doc) if callable(weight_fn) else 1.0
            for chunk in chunks[:3]:
                sparse_hits.append(RetrievalHit(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    text=chunk.text,
                    score=(1.0 / doc_rank) * document_weight,
                    url=doc.url,
                    title=doc.title,
                    competitor=doc.competitor,
                    dimension=doc.dimension,
                    source_type=doc.source_type,
                    content_hash=doc.content_hash,
                ))
        return sparse_hits

    def _filter_by_score_threshold(self, hits: list[RetrievalHit]) -> list[RetrievalHit]:
        if self._score_threshold <= 0:
            return hits
        return [hit for hit in hits if hit.score >= self._score_threshold]

    async def _post_process(
        self,
        query: str,
        hits: list[RetrievalHit],
        request: RetrievalRequest,
    ) -> list[RetrievalHit]:
        if self._rerank_fn and hits and request.rerank_top_k > 0:
            rerank_count = min(request.rerank_top_k, len(hits))
            self._reranked_hits += rerank_count
            rerank_hits = hits[:rerank_count]
            scores = await _maybe_await(self._rerank_fn(query, [hit.text for hit in rerank_hits]))
            for hit, score in zip(rerank_hits, scores, strict=False):
                hit.rerank_score = float(score)
                hit.rerank_model = self._rerank_model
            rerank_hits.sort(key=lambda h: h.rerank_score or 0.0, reverse=True)
            hits = [*rerank_hits, *hits[rerank_count:]]

        if request.mmr_lambda > 0:
            hits = await self._mmr_rerank(query, hits, request)

        return _prefer_document_diversity(hits, final_top_k=request.final_top_k)

    async def _mmr_rerank(
        self,
        query: str,
        hits: list[RetrievalHit],
        request: RetrievalRequest,
    ) -> list[RetrievalHit]:
        if not hits:
            return hits

        lambda_value = max(0.0, min(1.0, request.mmr_lambda))
        candidate_count = min(max(request.rerank_top_k, request.final_top_k), len(hits))
        candidates = hits[:candidate_count]
        rest = hits[candidate_count:]
        query_vector = await self._embed_query(query)
        vectors = await self._embed_texts([hit.text for hit in candidates])
        selected: list[int] = []
        remaining = set(range(len(candidates)))

        while remaining and len(selected) < request.final_top_k:
            best_index = max(
                remaining,
                key=lambda idx: self._mmr_score(
                    query_vector,
                    vectors[idx],
                    [vectors[selected_idx] for selected_idx in selected],
                    relevance=candidates[idx].rerank_score
                    if candidates[idx].rerank_score is not None
                    else candidates[idx].score,
                    lambda_value=lambda_value,
                ),
            )
            selected.append(best_index)
            remaining.remove(best_index)

        ordered = [candidates[idx] for idx in selected]
        ordered.extend(candidates[idx] for idx in remaining)
        ordered.extend(rest)
        return ordered

    @staticmethod
    def _mmr_score(
        query_vector: list[float],
        candidate_vector: list[float],
        selected_vectors: list[list[float]],
        *,
        relevance: float,
        lambda_value: float,
    ) -> float:
        similarity_to_query = _cosine(query_vector, candidate_vector)
        relevance_score = max(relevance, similarity_to_query)
        diversity_penalty = max(
            (_cosine(candidate_vector, selected_vector) for selected_vector in selected_vectors),
            default=0.0,
        )
        return lambda_value * relevance_score - (1.0 - lambda_value) * diversity_penalty

    async def _embed_query(self, query: str) -> list[float]:
        cached = self._embedding_cache.get(query)
        if cached is not None:
            return cached
        vector = (await _maybe_await(self._embed_fn([query])))[0]
        self._embedding_cache.set(query, vector)
        return vector

    async def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return await _maybe_await(self._embed_fn(texts))

    @staticmethod
    def _cache_key(request: RetrievalRequest) -> str:
        return request.model_dump_json()

    def _reset_observability_counts(self) -> None:
        self._dense_hits = 0
        self._sparse_hits = 0
        self._reranked_hits = 0

    async def _record_observability(
        self,
        request: RetrievalRequest,
        *,
        latency_ms: float,
        cache_hit: bool,
    ) -> None:
        record_fn = getattr(self._repo, "record_retrieval_trace", None)
        if not callable(record_fn):
            return
        try:
            from packages.observability import RetrievalObservability

            record = RetrievalObservability(
                query=request.query,
                preset_used=request.preset,
                dense_hits=self._dense_hits,
                sparse_hits=self._sparse_hits,
                reranked_hits=self._reranked_hits,
                latency_ms=latency_ms,
                cache_hit=cache_hit,
                competitor=",".join(request.competitors) if request.competitors else None,
                dimension=",".join(request.dimensions) if request.dimensions else None,
                retrieval_preset=request.preset,
            )
            await record_fn(record)
        except Exception:
            return


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    limit = min(len(left), len(right))
    numerator = sum(left[i] * right[i] for i in range(limit))
    left_norm = math.sqrt(sum(left[i] * left[i] for i in range(limit)))
    right_norm = math.sqrt(sum(right[i] * right[i] for i in range(limit)))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def _prefer_document_diversity(hits: list[RetrievalHit], *, final_top_k: int) -> list[RetrievalHit]:
    if final_top_k <= 0:
        return []

    selected: list[RetrievalHit] = []
    overflow: list[RetrievalHit] = []
    seen_documents: set[str] = set()
    for hit in hits:
        document_key = hit.document_id or hit.chunk_id
        if document_key in seen_documents:
            overflow.append(hit)
            continue
        selected.append(hit)
        seen_documents.add(document_key)
        if len(selected) >= final_top_k:
            return selected

    selected.extend(overflow[: final_top_k - len(selected)])
    return selected[:final_top_k]


def _filter_hits_by_request(
    hits: list[RetrievalHit],
    request: RetrievalRequest,
) -> list[RetrievalHit]:
    competitors = {item.casefold() for item in request.competitors if item.strip()}
    dimensions = {item.casefold() for item in request.dimensions if item.strip()}
    if not competitors and not dimensions:
        return hits

    filtered: list[RetrievalHit] = []
    for hit in hits:
        if competitors and (hit.competitor or "").casefold() not in competitors:
            continue
        if dimensions and (hit.dimension or "").casefold() not in dimensions:
            continue
        filtered.append(hit)
    return filtered


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value
