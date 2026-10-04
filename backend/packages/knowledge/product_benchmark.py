"""Offline product research retrieval diagnostic over one fixed, scoped SQLite corpus."""

from __future__ import annotations

import argparse
import asyncio
import json
import resource
import statistics
import sys
import tempfile
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .eval import RetrievalLabel, evaluate_query
from .ingestion import IngestionPipeline
from .models import DocumentCreate, RetrievalRequest
from .product_eval_data import DatasetValidationError, load_dataset
from .repository import KnowledgeRepository
from .retrieval import QueryRewriter, RetrievalService

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


async def run_product_benchmark(
    corpus_path: str | Path,
    queries_path: str | Path,
    labels_path: str | Path,
    *,
    mode: str = "formal",
    top_k: int = 5,
    embedding_provider: Any = None,
    reranker_provider: Any = None,
) -> dict[str, Any]:
    """Run FTS once per labeled query over a single offline corpus snapshot."""
    if mode not in {"formal", "candidate-diagnostic"}:
        raise ValueError("mode must be formal or candidate-diagnostic")
    if not 1 <= top_k <= 100:
        raise ValueError("top_k must be between 1 and 100")
    dataset = load_dataset(
        corpus_path, queries_path, labels_path, require_reviewed=mode == "formal"
    )
    selected = {
        query_id: label
        for query_id, label in dataset.labels.items()
        if dataset.queries[query_id]["purpose"] == "evaluation"
    }
    if mode == "candidate-diagnostic" and not selected:
        raise ValueError("no evaluation labels available for candidate diagnostic")
    provider_status = embedding_provider.status() if embedding_provider is not None else None
    provider = provider_readiness(provider_status)
    reranker_status = reranker_provider.status() if reranker_provider is not None else None
    vector_store = _NeverUsedVectorStore()
    rows: list[dict[str, Any]] = []
    latencies: list[float] = []
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="product-eval-") as directory:
        db_path = Path(directory) / "corpus.db"
        async with _BenchmarkRepository(str(db_path)) as repo:
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
                    },
                    **_SCOPE,
                )
                doc_ids[source["id"]] = await pipeline.ingest(doc)
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
                    raise ValueError(f"fixed corpus source is not active and unique: {source_id}")
            stored_chunks = {
                chunk.id: chunk
                for chunks in (await repo.get_chunks_for_documents(list(stored_docs))).values()
                for chunk in chunks
            }
            ingest_ms = (time.perf_counter() - started) * 1000
            db_bytes = db_path.stat().st_size
            for query_id, label in selected.items():
                query = dataset.queries[query_id]
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
                    embed_fn=_never_embed,
                    query_rewriter=_NeverRewrite(),
                    rerank_fn=None,
                    reranker_provider=None,
                )
                request = RetrievalRequest(
                    query=query["query"],
                    competitors=[query["product"]],
                    market=query["market"],
                    source_roles=["source"],
                    mode="sparse",
                    top_k=top_k,
                    final_top_k=top_k,
                    rerank_top_k=0,
                    mmr_lambda=0,
                    enable_query_rewrite=False,
                    num_rewrites=0,
                    **_SCOPE,
                )
                began = time.perf_counter()
                response = await service.retrieve(request)
                latency_ms = (time.perf_counter() - began) * 1000
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
                rows.append(
                    {
                        "query_id": query_id,
                        "original_query": query["query"],
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
                        "date_exclusions": date_exclusions,
                        "missing_source_ids": [sid for sid in proof_ids if sid not in retrieved],
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
    scored = [row["metrics"] for row in rows if row["metrics"] is not None]

    def mean(name: str) -> float | None:
        return statistics.mean(item[name] for item in scored) if scored else None

    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "mode": mode,
        "dataset": dataset.counts,
        "dataset_reasons": dataset.reasons,
        "semantic_quality_verified": False,
        "provider": provider,
        "reranker": reranker_status or {"effective_provider": "unconfigured"},
        "model_calls": 0,
        "queries": rows,
        "modes": {
            "sparse": {
                "status": "completed",
                "top_k": top_k,
                "query_count": len(rows),
                "answer_query_count": len(scored),
                "recall_at_k": mean("recall_at_k"),
                "mrr": mean("mrr"),
                "ndcg_at_k": mean("ndcg_at_k"),
            },
            **{
                name: {
                    "status": "not_run",
                    "reason": "offline run has no vector index or model execution",
                }
                for name in ("dense", "rrf", "rrf_rerank")
            },
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
    parser.add_argument("--mode", choices=["formal", "candidate-diagnostic"], default="formal")
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
                args.corpus, args.queries, args.labels, mode=args.mode, top_k=args.top_k
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
