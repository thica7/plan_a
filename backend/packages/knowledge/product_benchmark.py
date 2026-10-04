"""Offline product research retrieval diagnostic over one fixed, scoped SQLite corpus."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import resource
import statistics
import sys
import tempfile
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from qdrant_client import QdrantClient

from . import lexical
from .eval import RetrievalLabel, evaluate_query
from .ingestion import IngestionPipeline
from .models import DocumentCreate, RetrievalIntent, RetrievalRequest
from .product_eval_data import DatasetValidationError, load_dataset
from .repository import KnowledgeRepository
from .retrieval import QueryRewriter, RetrievalService
from .vector_store import VectorStore

_ROOT = Path(__file__).resolve().parents[3]
_SCOPE = {"workspace_id": "product-eval-offline", "project_id": "fixed-corpus"}


class _NeverUsedVectorStore:
    async def search(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("offline benchmark cannot search vectors")

    async def upsert(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("offline benchmark cannot index vectors")


class _NeverRewrite(QueryRewriter):
    async def rewrite(self, query: str, *, num_rewrites: int) -> list[str]:
        raise AssertionError("offline benchmark cannot rewrite queries")


def _never_embed(texts: list[str]) -> None:
    raise AssertionError("offline benchmark cannot embed")


class _BenchmarkRepository(KnowledgeRepository):
    as_of: date | None = None

    def _add_scope_filters(self, clauses: list[str], params: list[Any], **kwargs: Any) -> None:
        super()._add_scope_filters(clauses, params, **kwargs)
        if self.as_of is None:
            return
        prefix = kwargs.get("prefix", "")
        for column in ("source_published_at", "source_updated_at"):
            clauses.append(f"({prefix}{column} IS NULL OR substr({prefix}{column}, 1, 10) <= ?)")
            params.append(self.as_of.isoformat())
        clauses.append(
            f"({prefix}source_published_at IS NOT NULL OR "
            f"{prefix}source_updated_at IS NOT NULL OR "
            f"json_extract({prefix}metadata_json, '$.eval_fetched_date') <= ?)"
        )
        params.append(self.as_of.isoformat())


def provider_readiness(status: dict[str, Any] | None) -> dict[str, Any]:
    """Report real model readiness only; retrieval quality needs a separate evaluation."""
    status = status or {}
    requested = status.get("requested_provider") or "unconfigured"
    effective = status.get("effective_provider") or "unconfigured"
    model = status.get("model_version")
    dimensions = status.get("dimensions")
    unusable = {"hash", "custom", "uninitialized", "unconfigured", "none", "degraded"}
    ready = (
        isinstance(requested, str)
        and requested.lower() not in unusable
        and "hash" not in requested.lower()
        and requested == effective
        and isinstance(effective, str)
        and effective.lower() not in unusable
        and "hash" not in effective.lower()
        and "hash" not in str(model).lower()
        and isinstance(model, str)
        and bool(model.strip())
        and type(dimensions) is int
        and dimensions > 0
        and not status.get("degraded", False)
    )
    return {
        "requested_provider": requested,
        "effective_provider": effective,
        "model_version": model,
        "dimensions": dimensions,
        "index_version": status.get("index_version"),
        "degraded": bool(status.get("degraded", False)),
        "semantic_ready": ready,
        "semantic_quality_verified": False,
        "reason": status.get("reason") or (None if ready else "real semantic model unavailable"),
    }


def _reranker_ready(status: dict[str, Any]) -> bool:
    requested = status.get("requested_provider")
    effective = status.get("effective_provider")
    model = status.get("model_version")
    forbidden = ("hash", "custom", "uninitialized", "unconfigured", "degraded", "none")
    return (
        isinstance(requested, str)
        and bool(requested.strip())
        and requested == effective
        and isinstance(effective, str)
        and bool(effective.strip())
        and isinstance(model, str)
        and bool(model.strip())
        and not any(
            blocked in value.lower()
            for value in (requested, effective, model)
            for blocked in forbidden
        )
        and type(status.get("inference_calls")) is int
        and status["inference_calls"] >= 0
        and not status.get("degraded", False)
    )


def _parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def _source_after_as_of(source: dict[str, Any], as_of: date) -> bool:
    dated = [
        _parse_datetime(source[field])
        for field in ("published_at", "updated_at")
        if source[field] is not None
    ]
    if any(value.date() > as_of for value in dated):
        return True
    return not dated and _parse_datetime(source["fetched_at"]).date() > as_of


def _language(query: str) -> str:
    """Text heuristic; it does not measure cross-language retrieval quality."""
    has_cjk = any("\u4e00" <= char <= "\u9fff" for char in query)
    has_latin = any("a" <= char.lower() <= "z" for char in query)
    return (
        "mixed"
        if has_cjk and has_latin
        else "cjk"
        if has_cjk
        else "latin"
        if has_latin
        else "other"
    )


def _p95(values: list[float]) -> float:
    return (
        sorted(values)[min(len(values) - 1, max(0, int(0.95 * len(values) + 0.999999) - 1))]
        if values
        else 0.0
    )


def _group(rows: list[dict[str, Any]], field: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(row.get(field) or "unspecified"), []).append(row)
    output = {}
    for key, members in groups.items():
        scored = [member["metrics"] for member in members if member["metrics"] is not None]
        output[key] = {
            "query_count": len(members),
            "answer_query_count": len(scored),
            "recall_at_k": statistics.mean(item["recall_at_k"] for item in scored)
            if scored
            else None,
            "mrr": statistics.mean(item["mrr"] for item in scored) if scored else None,
            "ndcg_at_k": statistics.mean(item["ndcg_at_k"] for item in scored) if scored else None,
        }
    return output


def _load_intent_plans(
    path: Path, selected_ids: set[str]
) -> tuple[dict[str, RetrievalIntent], str]:
    content = path.read_bytes()
    plans: dict[str, RetrievalIntent] = {}
    for line_number, line in enumerate(content.decode("utf-8").splitlines(), 1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"intent plan line {line_number}: invalid JSON") from exc
        if not isinstance(row, dict) or set(row) != {"query_id", "intent"}:
            raise ValueError(
                f"intent plan line {line_number}: expected only query_id and intent keys"
            )
        query_id = row["query_id"]
        if not isinstance(query_id, str) or not query_id.strip() or query_id not in selected_ids:
            raise ValueError(f"intent plan line {line_number}: unknown or blank query_id")
        if query_id in plans:
            raise ValueError(f"intent plan line {line_number}: duplicate query_id")
        if not isinstance(row["intent"], dict):
            raise ValueError(f"intent plan line {line_number}: intent must be an object")
        try:
            plans[query_id] = RetrievalIntent.model_validate(row["intent"])
        except ValidationError as exc:
            raise ValueError(f"intent plan line {line_number}: invalid intent: {exc}") from exc
    return plans, hashlib.sha256(content).hexdigest()


def _lexical_plan(query: str, product: str, policy: str, version: str) -> dict[str, Any]:
    plan = lexical.build_lexical_plan(query, [product])
    return {
        "query": query,
        "version": version,
        "strict_query": KnowledgeRepository._to_fts_query(query),
        "fallback_query": plan.fallback_query if policy == "bounded" else None,
        "concepts": plan.concepts if policy == "bounded" else [],
        "literals": plan.literals if policy == "bounded" else [],
        "disabled_reason": plan.disabled_reason if policy == "bounded" else "policy_disabled",
    }


async def run_product_benchmark(
    corpus_path: str | Path,
    queries_path: str | Path,
    labels_path: str | Path,
    *,
    mode: str = "formal",
    lexical_policy: str = "bounded",
    intent_policy: str = "raw",
    intent_plan_path: Path | str | None = None,
    top_k: int = 5,
    retrieval_mode: str = "sparse",
    candidate_top_k: int = 20,
    enable_rerank: bool = False,
    embedding_provider: Any = None,
    reranker_provider: Any = None,
) -> dict[str, Any]:
    """Run scoped offline sparse retrieval over a single fixed corpus snapshot."""
    if mode not in {"formal", "candidate-diagnostic", "tuning-diagnostic"}:
        raise ValueError("mode must be formal, candidate-diagnostic, or tuning-diagnostic")
    if lexical_policy not in {"strict", "bounded"}:
        raise ValueError("lexical_policy must be strict or bounded")
    if intent_policy not in {"raw", "structured"}:
        raise ValueError("intent_policy must be raw or structured")
    if intent_policy == "raw" and intent_plan_path is not None:
        raise ValueError("raw intent_policy cannot include an intent plan")
    if not 1 <= top_k <= 100:
        raise ValueError("top_k must be between 1 and 100")
    if retrieval_mode not in {"sparse", "dense", "hybrid"}:
        raise ValueError("retrieval_mode must be sparse, dense, or hybrid")
    if retrieval_mode != "sparse" and not top_k <= candidate_top_k <= 100:
        raise ValueError("candidate_top_k must be between top_k and 100")
    if retrieval_mode != "sparse" and (
        embedding_provider is None
        or not provider_readiness(embedding_provider.status())["semantic_ready"]
    ):
        raise ValueError("embedding_provider must be an initialized real model")
    if enable_rerank:
        rerank_status = reranker_provider.status() if reranker_provider is not None else {}
        if retrieval_mode != "hybrid" or not _reranker_ready(rerank_status):
            raise ValueError(
                "reranker_provider must be an initialized real model for hybrid rerank"
            )
    dataset = load_dataset(
        corpus_path, queries_path, labels_path, require_reviewed=mode == "formal"
    )
    all_labels = (
        load_dataset(corpus_path, queries_path, labels_path, require_reviewed=False).labels
        if mode == "formal"
        else dataset.labels
    )
    selected_purpose = "tuning" if mode == "tuning-diagnostic" else "evaluation"
    selected = {
        query_id: label
        for query_id, label in dataset.labels.items()
        if dataset.queries[query_id]["purpose"] == selected_purpose
    }
    if not selected:
        raise ValueError(f"no {selected_purpose} labels available for {mode}")
    intent_plans, intent_plan_sha256 = (
        _load_intent_plans(Path(intent_plan_path), set(selected))
        if intent_plan_path is not None
        else ({}, None)
    )
    purpose_excluded = sum(
        dataset.queries[query_id]["purpose"] != selected_purpose for query_id in all_labels
    )
    dataset_counts = {**dataset.counts, "included": len(selected), "labels_loaded": len(all_labels)}
    dataset_reasons = list(dataset.reasons)
    if purpose_excluded:
        excluded_purpose = "evaluation" if selected_purpose == "tuning" else "tuning"
        reason = f"{excluded_purpose}_excluded"
        if reason not in dataset_reasons:
            dataset_reasons.append(reason)
    policy_version = (
        lexical.build_lexical_plan("", []).version
        if lexical_policy == "bounded"
        else "strict-terms-v1"
    )
    lexical_policy_report = {
        "name": lexical_policy,
        "version": policy_version,
        "fallback_enabled": lexical_policy == "bounded",
        "planner_source_sha256": hashlib.sha256(Path(lexical.__file__).read_bytes()).hexdigest(),
    }
    provider_status = embedding_provider.status() if embedding_provider is not None else None
    provider = provider_readiness(provider_status)
    reranker_status = reranker_provider.status() if reranker_provider is not None else None
    embedding_calls_before = (provider_status or {}).get("inference_calls", 0)
    reranker_calls_before = (reranker_status or {}).get("inference_calls", 0)
    vector_store: Any = _NeverUsedVectorStore()
    qdrant_client: QdrantClient | None = None
    rows: list[dict[str, Any]] = []
    latencies: list[float] = []
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="product-eval-") as directory:
        try:
            db_path = Path(directory) / "corpus.db"
            if retrieval_mode != "sparse":
                qdrant_client = QdrantClient(path=str(Path(directory) / "qdrant"))
                vector_store = VectorStore(client=qdrant_client)
                vector_store.configure_index(
                    embedding_provider.model_version, embedding_provider.dimensions
                )
            async with _BenchmarkRepository(
                str(db_path), lexical_fallback=lexical_policy == "bounded"
            ) as repo:
                pipeline = IngestionPipeline(repo, vector_store)
                doc_ids: dict[str, str] = {}
                for source in dataset.sources.values():
                    doc = DocumentCreate(
                        title=source["title"],
                        text=source["text"],
                        url=source["url"],
                        source_type="report"
                        if source["role"] == "historical_report"
                        else "webpage_verified",
                        competitor=source["product"],
                        market=source["market"],
                        source_role=source["role"],
                        source_published_at=_parse_datetime(source["published_at"]),
                        source_updated_at=_parse_datetime(source["updated_at"]),
                        fetched_at=_parse_datetime(source["fetched_at"]),
                        metadata={
                            "eval_source_id": source["id"],
                            "full_content_hash": source["content_hash"],
                            "eval_fetched_date": _parse_datetime(source["fetched_at"])
                            .date()
                            .isoformat(),
                            **{
                                key: source[key]
                                for key in ("structured_facts", "text_kind", "provenance")
                                if key in source
                            },
                        },
                        **_SCOPE,
                    )
                    doc_ids[source["id"]] = await pipeline.ingest(
                        doc,
                        embedding_provider=embedding_provider
                        if retrieval_mode != "sparse"
                        else None,
                    )
                if len(set(doc_ids.values())) != len(doc_ids):
                    raise ValueError("distinct sources share one stored document in fixed corpus")
                stored_docs = {
                    doc_id: await repo.get_document(doc_id) for doc_id in set(doc_ids.values())
                }
                for source_id, doc_id in doc_ids.items():
                    document = stored_docs[doc_id]
                    if (
                        document is None
                        or not document.is_active
                        or document.status != "active"
                        or document.metadata.get("eval_source_id") != source_id
                    ):
                        raise ValueError(
                            f"fixed corpus source is not active and unique: {source_id}"
                        )
                stored_chunks = {
                    chunk.id: chunk
                    for chunks in (await repo.get_chunks_for_documents(list(stored_docs))).values()
                    for chunk in chunks
                }
                ingest_ms = (time.perf_counter() - started) * 1000
                db_bytes = db_path.stat().st_size
                for query_id, label in selected.items():
                    query = dataset.queries[query_id]
                    lexical_plan = {
                        **_lexical_plan(
                            query["query"], query["product"], lexical_policy, policy_version
                        ),
                        "legacy_original": True,
                    }
                    repo.as_of = date.fromisoformat(query["as_of"])
                    date_exclusions = [
                        {"source_id": source["id"], "reason": "source_date_after_as_of"}
                        for source in dataset.sources.values()
                        if source["product"] == query["product"]
                        and source["market"] == query["market"]
                        and source["role"] == "source"
                        and _source_after_as_of(source, repo.as_of)
                    ]
                    # The production response cache key has no as_of field.
                    # A cold service keeps each date isolated while sharing the same DB.
                    service = RetrievalService(
                        repo,
                        vector_store,
                        embed_fn=(
                            lambda texts: [embedding_provider.embed_query(text) for text in texts]
                        )
                        if retrieval_mode != "sparse"
                        else _never_embed,
                        embedding_provider=embedding_provider
                        if retrieval_mode != "sparse"
                        else None,
                        query_rewriter=_NeverRewrite(),
                        rerank_fn=reranker_provider.rerank if enable_rerank else None,
                        reranker_provider=reranker_provider if enable_rerank else None,
                    )
                    request = RetrievalRequest(
                        query=query["query"],
                        intent_policy=intent_policy,
                        retrieval_intent=intent_plans.get(query_id),
                        competitors=[query["product"]],
                        market=query["market"],
                        source_roles=["source"],
                        mode=retrieval_mode,
                        top_k=candidate_top_k if retrieval_mode != "sparse" else top_k,
                        final_top_k=top_k,
                        rerank_top_k=candidate_top_k if enable_rerank else 0,
                        mmr_lambda=0,
                        enable_query_rewrite=False,
                        num_rewrites=0,
                        **_SCOPE,
                    )
                    began = time.perf_counter()
                    response = await service.retrieve(request)
                    latency_ms = (time.perf_counter() - began) * 1000
                    diagnostics = response.diagnostics
                    if enable_rerank and not _reranker_ready(reranker_provider.status()):
                        raise RuntimeError("Reranker provider unavailable after retrieval")
                    canonical_rejection = (
                        retrieval_mode == "hybrid"
                        and diagnostics.get("reason")
                        == "Dense candidates rejected by canonical document validation"
                    )
                    if retrieval_mode != "sparse" and (
                        (
                            diagnostics.get("effective_mode") != retrieval_mode
                            and not canonical_rejection
                        )
                        or (diagnostics.get("degraded") and not canonical_rejection)
                        or not provider_readiness(embedding_provider.status())["semantic_ready"]
                        or (enable_rerank and not _reranker_ready(reranker_provider.status()))
                    ):
                        raise RuntimeError(
                            f"Dense retrieval unavailable: {diagnostics.get('reason')}"
                        )
                    query_plan = response.diagnostics["query_plan"]
                    lexical_plans = [
                        _lexical_plan(
                            search_query, query["product"], lexical_policy, policy_version
                        )
                        for search_query in query_plan["queries"]
                    ]
                    latencies.append(latency_ms)
                    hits = []
                    for rank, hit in enumerate(response.hits, 1):
                        document = stored_docs.get(hit.document_id)
                        chunk = stored_chunks.get(hit.chunk_id)
                        if (
                            document is None
                            or chunk is None
                            or chunk.document_id != hit.document_id
                            or chunk.text != hit.text
                            or document.version != hit.document_version
                            or document.content_hash != hit.content_hash
                        ):
                            raise RuntimeError("retrieval hit differs from stored corpus snapshot")
                        source_id = hit.metadata.get("eval_source_id")
                        source = dataset.sources.get(source_id)
                        offset = source["text"].find(hit.text) if source else -1
                        hits.append(
                            {
                                "rank": rank,
                                "source_id": source_id,
                                "document_id": hit.document_id,
                                "chunk_id": hit.chunk_id,
                                "document_version": hit.document_version,
                                "content_hash": source["content_hash"] if source else None,
                                "document_content_hash": document.content_hash,
                                "chunk_content_hash": chunk.content_hash,
                                "market": hit.market,
                                "role": hit.source_role,
                                "product": hit.competitor,
                                "workspace_id": hit.workspace_id,
                                "project_id": hit.project_id,
                                "excerpt_start": offset if offset >= 0 else None,
                                "excerpt_end": offset + len(hit.text) if offset >= 0 else None,
                                "metadata": {
                                    "lexical_retrieval": hit.metadata.get("lexical_retrieval"),
                                    "structured_facts": hit.metadata.get("structured_facts"),
                                    "text_kind": hit.metadata.get("text_kind"),
                                    "provenance": hit.metadata.get("provenance"),
                                },
                            }
                        )
                    proof_ids = list(dict.fromkeys(proof["source_id"] for proof in label["proofs"]))
                    retrieved = {hit["source_id"] for hit in hits}
                    metrics = None
                    if label["expected_outcome"] == "answer":
                        metrics = evaluate_query(
                            RetrievalLabel(query["query"], [doc_ids[sid] for sid in proof_ids], []),
                            response.hits,
                            top_k=top_k,
                        )
                        metrics.pop("query")
                    proof_checks = []
                    for proof in label["proofs"]:
                        source = dataset.sources[proof["source_id"]]
                        quote_in_hit = any(
                            hit["source_id"] == proof["source_id"]
                            and hit["excerpt_start"] is not None
                            and hit["excerpt_start"] <= proof["start"]
                            and hit["excerpt_end"] >= proof["end"]
                            for hit in hits
                        )
                        proof_checks.append(
                            {
                                **proof,
                                "content_hash": source["content_hash"],
                                "retrieved": proof["source_id"] in retrieved,
                                "quote_matches_saved_excerpt": (
                                    source["text"][proof["start"] : proof["end"]] == proof["quote"]
                                ),
                                "quote_in_retrieved_excerpt": quote_in_hit,
                            }
                        )
                    failure_reasons = []
                    if any(sid not in retrieved for sid in proof_ids):
                        failure_reasons.append("proof_source_not_retrieved")
                    if any(not proof["quote_in_retrieved_excerpt"] for proof in proof_checks):
                        failure_reasons.append("proof_excerpt_not_retrieved")
                    eligible_count = sum(
                        source["product"] == query["product"]
                        and source["market"] == query["market"]
                        and source["role"] == "source"
                        and not _source_after_as_of(source, repo.as_of)
                        for source in dataset.sources.values()
                    )
                    if metrics is not None:
                        top_one = response.hits[:1]
                        metrics["recall_at_1"] = evaluate_query(
                            RetrievalLabel(query["query"], [doc_ids[sid] for sid in proof_ids], []),
                            top_one,
                            top_k=1,
                        )["recall_at_k"]
                    rows.append(
                        {
                            "query_id": query_id,
                            "eligible_source_count": eligible_count,
                            "retrieval_diagnostics": diagnostics,
                            "proof_excerpt_in_top_1": any(
                                proof["quote_in_retrieved_excerpt"]
                                and hits
                                and proof["source_id"] == hits[0]["source_id"]
                                and hits[0]["excerpt_start"] <= proof["start"]
                                and hits[0]["excerpt_end"] >= proof["end"]
                                for proof in proof_checks
                            ),
                            "original_query": query["query"],
                            "lexical_plan": lexical_plan,
                            "lexical_plans": lexical_plans,
                            "query_plan": query_plan,
                            "fact_query_results": response.diagnostics.get(
                                "fact_query_results", []
                            ),
                            "expected_outcome": label["expected_outcome"],
                            "review_status": label["review_status"],
                            "category": query.get("category"),
                            "language": _language(query["query"]),
                            "market": query["market"],
                            "product": query["product"],
                            "as_of": query["as_of"],
                            "hits": hits,
                            "metrics": metrics,
                            "proofs": proof_checks,
                            "proof_excerpt_recall": (
                                sum(proof["quote_in_retrieved_excerpt"] for proof in proof_checks)
                                / len(proof_checks)
                                if label["expected_outcome"] == "answer"
                                else None
                            ),
                            "non_gold_source_count": (
                                len(retrieved - set(proof_ids))
                                if label["expected_outcome"] == "answer"
                                else None
                            ),
                            "date_exclusions": date_exclusions,
                            "missing_source_ids": [
                                sid for sid in proof_ids if sid not in retrieved
                            ],
                            "failure_reasons": failure_reasons,
                            "retrieval_empty": not bool(hits),
                            "retrieval_noise_count": len(hits)
                            if label["expected_outcome"] != "answer"
                            else None,
                            "latency_ms": latency_ms,
                            "ragas_input": {
                                "query": query["query"],
                                "response": None,
                                "reference_facts": label["expected_facts"],
                                "review_status": label["review_status"],
                                "retrieved_source_ids": [hit["source_id"] for hit in hits],
                                "contexts": [
                                    {
                                        key: hit[key]
                                        for key in (
                                            "source_id",
                                            "content_hash",
                                            "excerpt_start",
                                            "excerpt_end",
                                        )
                                    }
                                    for hit in hits
                                ],
                            },
                        }
                    )
            db_bytes = max(db_bytes, db_path.stat().st_size)
        finally:
            if qdrant_client is not None:
                qdrant_client.close()
    embedding_calls = (
        embedding_provider.status().get("inference_calls", 0) - embedding_calls_before
        if retrieval_mode != "sparse"
        else 0
    )
    reranker_calls = (
        reranker_provider.status().get("inference_calls", 0) - reranker_calls_before
        if enable_rerank
        else 0
    )
    if retrieval_mode != "sparse":
        provider = provider_readiness(embedding_provider.status())
        if not provider["semantic_ready"]:
            raise RuntimeError("Embedding provider degraded during retrieval")
        reranker_status = reranker_provider.status() if reranker_provider is not None else None
        if enable_rerank and not _reranker_ready(reranker_status):
            raise RuntimeError("Reranker provider unavailable after retrieval")
    scored = [row["metrics"] for row in rows if row["metrics"] is not None]

    def mean(name: str) -> float | None:
        return statistics.mean(item[name] for item in scored) if scored else None

    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "mode": mode,
        "selected_purpose": selected_purpose,
        "selected_label_count": len(selected),
        "purpose_excluded_label_count": purpose_excluded,
        "dataset": dataset_counts,
        "dataset_reasons": dataset_reasons,
        "lexical_policy": lexical_policy_report,
        "intent_policy": intent_policy,
        "intent_plan_sha256": intent_plan_sha256,
        "semantic_quality_verified": False,
        "provider": provider,
        "reranker": reranker_status or {"effective_provider": "unconfigured"},
        "model_calls": embedding_calls + reranker_calls,
        "embedding_model_calls": embedding_calls,
        "reranker_model_calls": reranker_calls,
        "external_model_calls": 0,
        "index": vector_store.status() if retrieval_mode != "sparse" else None,
        "queries": rows,
        "modes": {
            name: (
                {
                    "status": "completed",
                    "top_k": top_k,
                    "candidate_top_k": candidate_top_k,
                    "query_count": len(rows),
                    "answer_query_count": len(scored),
                    "recall_at_k": mean("recall_at_k"),
                    "recall_at_1": mean("recall_at_1"),
                    "mrr": mean("mrr"),
                    "ndcg_at_k": mean("ndcg_at_k"),
                    "mean_proof_excerpt_recall": statistics.mean(
                        row["proof_excerpt_recall"]
                        for row in rows
                        if row["proof_excerpt_recall"] is not None
                    )
                    if scored
                    else None,
                    "mean_non_gold_source_count": statistics.mean(
                        row["non_gold_source_count"]
                        for row in rows
                        if row["non_gold_source_count"] is not None
                    )
                    if scored
                    else None,
                }
                if name
                == (
                    "sparse"
                    if retrieval_mode == "sparse"
                    else "dense"
                    if retrieval_mode == "dense"
                    else "rrf_rerank"
                    if enable_rerank
                    else "rrf"
                )
                else {
                    "status": "not_run",
                    "reason": "mode not executed in this run",
                }
            )
            for name in ("sparse", "dense", "rrf", "rrf_rerank")
        },
        "outcomes": {
            outcome: {
                "query_count": len(group),
                "retrieval_empty": sum(row["retrieval_empty"] for row in group),
                "retrieval_noise_count": sum(row["retrieval_noise_count"] or 0 for row in group),
            }
            for outcome in ("clarify", "insufficient")
            if (group := [row for row in rows if row["expected_outcome"] == outcome])
        },
        "groups": {
            field: _group(rows, field)
            for field in ("category", "language", "market", "product", "as_of")
        },
        "index_ingest_ms": ingest_ms,
        "retrieval_latency_ms": {
            "p50": statistics.median(latencies) if latencies else 0.0,
            "p95": _p95(latencies),
        },
        "sqlite_file_bytes": db_bytes,
        "peak_rss_bytes": rss if sys.platform == "darwin" else rss * 1024,
        "peak_rss_scope": {
            "scope": "process_lifetime",
            "includes_embedding_and_reranker": (
                embedding_provider is not None and reranker_provider is not None
            ),
            "resident_model_ids": [
                status.get("model_id") or status.get("model_version")
                for status in (provider_status, reranker_status)
                if status is not None
            ],
        },
        "model_calls_scope": "arm_delta_excluding_initialization",
        "factual_quality": {
            "status": "not_run",
            "reason": "no generated answer or human adjudication",
        },
        "clarification_behavior": {"status": "not_run", "reason": "no answer model executed"},
        "refusal_behavior": {"status": "not_run", "reason": "no answer model executed"},
        "ragas": {
            "status": "not_run",
            "reason": "no model response or reviewed reference for answer scoring",
        },
        "snapshot": {
            "scope": _SCOPE,
            "source_roles": ["source"],
            "date_rule": "exclude dates after as_of; undated sources require fetched_at <= as_of",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=["formal", "candidate-diagnostic", "tuning-diagnostic"],
        default="formal",
    )
    parser.add_argument("--lexical-policy", choices=["strict", "bounded"], default="bounded")
    parser.add_argument("--intent-policy", choices=["raw", "structured"], default="raw")
    parser.add_argument("--intent-plan", type=Path)
    parser.add_argument("--corpus", type=Path, default=_ROOT / "eval/product-research-corpus.jsonl")
    parser.add_argument(
        "--queries", type=Path, default=_ROOT / "eval/product-research-queries-draft.jsonl"
    )
    parser.add_argument("--labels", type=Path, default=_ROOT / "eval/product-research-labels.jsonl")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = asyncio.run(
            run_product_benchmark(
                args.corpus,
                args.queries,
                args.labels,
                mode=args.mode,
                lexical_policy=args.lexical_policy,
                top_k=args.top_k,
                intent_policy=args.intent_policy,
                intent_plan_path=args.intent_plan,
            )
        )
    except DatasetValidationError as exc:
        parser.exit(
            2,
            json.dumps(
                {
                    "status": "not_ready",
                    "reason": str(exc),
                    "counts": exc.counts,
                    "reasons": exc.reasons,
                },
                ensure_ascii=False,
            )
            + "\n",
        )
    except (ValueError, OSError) as exc:
        parser.exit(2, f"benchmark unavailable: {exc}\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
