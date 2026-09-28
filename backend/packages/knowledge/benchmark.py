"""Deterministic retrieval -> evidence admission -> citation benchmark.

Run from the repository root:
    PYTHONPATH=backend .venv/bin/python -m packages.knowledge.benchmark --output report.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import tempfile
import time
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient

from packages.agents.qa.logic import FRESHNESS_DIMENSION_WINDOWS_DAYS
from packages.research.evidence import admit_evidence_items, citation_refs_from_evidence_items
from packages.research.models import CapturedPage, EvidenceQuote, ExtractionResult, SourceCandidate

from .embeddings import HashEmbeddingProvider
from .eval import RetrievalLabel, evaluate_retrieval
from .ingestion import IngestionPipeline
from .models import DocumentCreate, RetrievalHit, RetrievalRequest
from .repository import KnowledgeRepository
from .reranker import HashRerankerProvider
from .retrieval import RetrievalService
from .tokenization import lexical_tokens
from .vector_store import VectorStore

_ROOT = Path(__file__).resolve().parents[3]
_AS_OF = datetime(2026, 6, 15, tzinfo=UTC)


def load_benchmark_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for name in ("rag-kb-quality-gate-eval.jsonl", "rag-retrieval-eval.jsonl"):
        cases.extend(
            json.loads(line)
            for line in (_ROOT / "eval" / name).read_text().splitlines()
            if line.strip()
        )
    return cases


class _FailFirstUpsert:
    def __init__(self, store: VectorStore) -> None:
        self.store = store
        self.ids: list[list[str]] = []

    def configure_index(self, *args: Any, **kwargs: Any) -> None:
        self.store.configure_index(*args, **kwargs)

    async def upsert(
        self, ids: list[str], vectors: list[list[float]], payloads: list[dict[str, Any]]
    ) -> None:
        self.ids.append(ids)
        if len(self.ids) == 1:
            raise RuntimeError("benchmark first vector write failed")
        await self.store.upsert(ids, vectors, payloads)


class _LegacyRepository(KnowledgeRepository):
    @staticmethod
    def _to_fts_query(query: str) -> str:
        return " ".join(f'"{term}"' for term in re.findall(r"[\w-]+", query))


class _LegacyRetrievalService(RetrievalService):
    async def _sparse_search(self, query: str, top_k: int, **filters: Any) -> list[RetrievalHit]:
        documents = await self._repo.search_documents(query, limit=top_k, **filters)
        chunks_by_doc = await self._repo.get_chunks_for_documents([doc.id for doc in documents])
        return [
            RetrievalHit(
                chunk_id=chunk.id,
                document_id=doc.id,
                text=chunk.text,
                score=self._repo.get_document_weight(doc) / rank,
                url=doc.url,
                title=doc.title,
                competitor=doc.competitor,
                dimension=doc.dimension,
                source_type=doc.source_type,
                content_hash=doc.content_hash,
                fetched_at=doc.fetched_at,
                last_seen_at=doc.last_seen_at,
                status=doc.status,
                metadata=doc.metadata,
            )
            for rank, doc in enumerate(documents, 1)
            for chunk in chunks_by_doc[doc.id][:3]
        ]


async def run_benchmark(*, top_k: int = 3, legacy_sparse: bool = False) -> dict[str, Any]:
    """No downloads, network, query rewriting or model API calls."""
    provider = HashEmbeddingProvider(dimensions=64)
    reranker = HashRerankerProvider()
    mode_results: dict[str, list[dict[str, Any]]] = {
        name: [] for name in ("sparse", "hybrid", "rerank")
    }
    labels: list[RetrievalLabel] = []
    hits_by_mode: dict[str, list[list[RetrievalHit]]] = {name: [] for name in mode_results}
    recovery: dict[str, Any] = {}
    ingestion_ms: list[float] = []
    with tempfile.TemporaryDirectory(prefix="rag-benchmark-") as directory:
        for case_index, case in enumerate(load_benchmark_cases()):
            client = QdrantClient(":memory:")
            store = VectorStore(client=client)
            repository_type = _LegacyRepository if legacy_sparse else KnowledgeRepository
            async with repository_type(str(Path(directory) / f"case-{case_index}.db")) as repo:
                if legacy_sparse:
                    await repo._connection.create_function(
                        "kb_tokens", 1, lambda text: text, deterministic=True
                    )
                doc_ids: dict[str, str] = {}
                started = time.perf_counter()
                for source in case["evidence"]:
                    payload = DocumentCreate(
                        title=source["title"],
                        text=source["snippet"],
                        source_type=source["source_type"],
                        url=source.get("url"),
                        competitor=case["competitor"],
                        dimension=case["dimension"],
                        metadata={
                            "eval_source_id": source["source_id"],
                            "candidate_origin": source["candidate_origin"],
                        },
                    )
                    active_store: Any = (
                        _FailFirstUpsert(store) if source.get("fail_first_upsert") else store
                    )
                    pipeline = IngestionPipeline(
                        repo, active_store, chunk_size=120, chunk_overlap=0
                    )
                    if source.get("fail_first_upsert"):
                        try:
                            await pipeline.ingest(payload, embedding_provider=provider)
                        except RuntimeError:
                            pass
                    doc_id = await pipeline.ingest(payload, embedding_provider=provider)
                    doc_ids[source["source_id"]] = doc_id
                    if source.get("fail_first_upsert"):
                        recovery = {
                            "same_chunk_ids": active_store.ids[0] == active_store.ids[1],
                            "status": (await repo.get_document(doc_id)).indexing_status,
                        }
                    observed = (
                        source.get("observed_at") or source.get("fetched_at") or _AS_OF.isoformat()
                    )
                    observed_at = datetime.fromisoformat(observed.replace("Z", "+00:00"))
                    age = max(0, (_AS_OF - observed_at).days)
                    window = next(
                        (
                            days
                            for hints, days in FRESHNESS_DIMENSION_WINDOWS_DAYS
                            if any(hint in case["dimension"] for hint in hints)
                        ),
                        120,
                    )
                    await repo._connection.execute(
                        "UPDATE documents SET fetched_at = ?, last_seen_at = ?, status = CASE WHEN status = 'active' AND ? THEN 'stale' ELSE status END WHERE id = ?",
                        (observed, observed, age > window, doc_id),
                    )
                ingestion_ms.append((time.perf_counter() - started) * 1000)
                relevant_docs = [doc_ids[source_id] for source_id in case["relevant_source_ids"]]
                relevant_chunks: list[str] = []
                if case.get("relevant_chunk_contains"):
                    for doc_id in relevant_docs:
                        relevant_chunks.extend(
                            chunk.id
                            for chunk in await repo.get_chunks_for_document(doc_id)
                            if case["relevant_chunk_contains"] in chunk.text
                        )
                    relevant_docs = []
                query = case.get("retrieval_query", case["query"])
                labels.append(
                    RetrievalLabel(
                        query=query,
                        relevant_doc_ids=relevant_docs,
                        relevant_chunk_ids=relevant_chunks,
                    )
                )
                for name in mode_results:
                    service_type = _LegacyRetrievalService if legacy_sparse else RetrievalService
                    service = service_type(
                        repo,
                        store,
                        embed_fn=provider.embed_documents,
                        embedding_provider=provider,
                        rerank_fn=reranker.rerank if name == "rerank" else None,
                        reranker_provider=reranker if name == "rerank" else None,
                    )
                    started = time.perf_counter()
                    with warnings.catch_warnings():
                        warnings.filterwarnings("ignore", message="Local mode performs exact")
                        response = await service.retrieve(
                            RetrievalRequest(
                                query=query,
                                mode="sparse" if name == "sparse" else "hybrid",
                                competitors=[case["competitor"]],
                                dimensions=[case["dimension"]],
                                top_k=max(top_k, 10),
                                final_top_k=top_k,
                                rerank_top_k=10 if name == "rerank" else 0,
                                enable_query_rewrite=False,
                            )
                        )
                    latency = (time.perf_counter() - started) * 1000
                    citations, rejected = _admit_hits(case, query, response.hits)
                    hits_by_mode[name].append(response.hits)
                    mode_results[name].append(
                        {
                            "id": case["id"],
                            "scenario": case["scenario"],
                            "query": query,
                            "original_query": case["query"],
                            "latency_ms": latency,
                            "hits": [hit.model_dump(mode="json") for hit in response.hits],
                            "citations": citations,
                            "admission_rejections": rejected,
                            "insufficient_evidence": not citations,
                            "scope_leaks": sum(
                                hit.competitor != case["competitor"]
                                or hit.dimension != case["dimension"]
                                for hit in response.hits
                            ),
                        }
                    )
            client.close()
    modes: dict[str, Any] = {}
    for name, queries in mode_results.items():
        metrics = evaluate_retrieval(labels, hits_by_mode[name], top_k=top_k)
        citations = [citation for query in queries for citation in query["citations"]]
        metrics.update(
            latency_ms=_latencies([query["latency_ms"] for query in queries]),
            citation_correctness=sum(citation["correct"] for citation in citations)
            / max(1, len(citations)),
            stale_source_misuse=sum(citation["status"] != "active" for citation in citations),
            scope_leaks=sum(query["scope_leaks"] for query in queries),
            queries=queries,
        )
        modes[name] = metrics
    return {
        "provider": provider.status(),
        "reranker": reranker.status(),
        "model_calls": 0,
        "legacy_sparse": legacy_sparse,
        "reference_date": _AS_OF.isoformat(),
        "query_rewriting": False,
        "datasets": ["rag-kb-quality-gate-eval.jsonl", "rag-retrieval-eval.jsonl"],
        "ingestion_ms": _latencies(ingestion_ms),
        "index_recovery": recovery,
        "modes": modes,
    }


def _admit_hits(
    case: dict[str, Any], query: str, hits: list[RetrievalHit]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    citations: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    for hit in hits:
        if not hit.url:
            continue
        candidate = SourceCandidate(
            title=hit.title or "",
            url=hit.url,
            origin="manual",
            competitor=case["competitor"],
            dimension=case["dimension"],
            metadata=hit.metadata,
        )
        lexical_match = bool(set(lexical_tokens(query)) & set(lexical_tokens(hit.text)))
        admissible = hit.status == "active" and lexical_match
        page = CapturedPage(
            candidate_id=candidate.id,
            requested_url=hit.url,
            final_url=hit.url,
            status="ok" if admissible else "rejected",
            text=hit.text,
            content_hash=hit.content_hash,
            quality_score=0.9,
            fetch_method="rag_kb_retrieve",
            failure_reason=None if admissible else "stale_or_no_query_support",
        )
        quote = hit.text[:420]
        extraction = ExtractionResult(
            competitor=case["competitor"],
            dimension=case["dimension"],
            source_candidate_id=candidate.id,
            captured_page_id=page.id,
            fields={"retrieved_fact": quote},
            quotes=[EvidenceQuote(text=quote, source_url=hit.url, field="retrieved_fact")],
            confidence=0.9,
            extractor_name="benchmark-verbatim-quote",
        )
        items = admit_evidence_items([extraction], captured_pages=[page], candidates=[candidate])
        accepted = [item for item in items if item.status == "accepted"]
        rejections.extend(
            {"chunk_id": hit.chunk_id, "reason": item.rejection_reason}
            for item in items
            if item.status != "accepted"
        )
        for citation in citation_refs_from_evidence_items(accepted):
            citations.append(
                {
                    **citation,
                    "document_id": hit.document_id,
                    "chunk_id": hit.chunk_id,
                    "status": hit.status,
                    "eval_source_id": hit.metadata.get("eval_source_id"),
                    "correct": citation["source_url"] == hit.url and citation["quote"] in hit.text,
                }
            )
    return citations, rejections


def _latencies(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "mean": statistics.mean(values),
        "p50": statistics.median(values),
        "p95": ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))],
        "max": max(values),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--legacy-sparse",
        action="store_true",
        help="Reproduce old FTS and first-three-chunks recall on the same corpus",
    )
    args = parser.parse_args()
    if args.top_k < 1:
        parser.error("--top-k must be positive")
    report = asyncio.run(run_benchmark(top_k=args.top_k, legacy_sparse=args.legacy_sparse))
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n")
    else:
        print(output)


if __name__ == "__main__":
    main()
