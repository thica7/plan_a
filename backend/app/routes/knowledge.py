"""Knowledge Base API routes."""

from __future__ import annotations

import asyncio
import base64
import difflib
import json
import os
import uuid
from datetime import datetime
from functools import lru_cache
from typing import Annotated, Any, Literal

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel

from packages.crawler.models import CrawlRequest, CrawlResult
from packages.knowledge.embeddings import (
    EmbeddingProvider,
    HashEmbeddingProvider,
    get_embedding_provider_from_env,
)
from packages.knowledge.eval import RetrievalLabel, evaluate_retrieval
from packages.knowledge.ingestion import IngestionPipeline
from packages.knowledge.models import (
    DocumentCreate,
    KnowledgeDocument,
    RetrievalRequest,
    RetrievalResponse,
)
from packages.knowledge.parsers import ParsedDocument, parse_document
from packages.knowledge.repository import KnowledgeRepository
from packages.knowledge.reranker import RerankerProvider, get_reranker_provider_from_env
from packages.knowledge.retrieval import RetrievalService

router = APIRouter()
_repository = KnowledgeRepository()
_repository_lock = asyncio.Lock()
_repository_initialised = False


class CrawlJobCreate(BaseModel):
    url: str
    run_id: str | None = None
    competitor: str | None = None
    dimension: str | None = None


class CrawlJob(BaseModel):
    id: str
    run_id: str | None = None
    url: str
    competitor: str | None = None
    dimension: str | None = None
    status: str
    attempt_count: int
    error: str | None = None
    result_metadata: dict[str, Any] = {}
    created_at: datetime
    updated_at: datetime


class BatchIngestItem(BaseModel):
    source: Literal["url", "text", "base64"]
    url: str | None = None
    text: str | None = None
    title: str | None = None
    content_b64: str | None = None
    mime: str | None = None
    filename: str | None = None


class BatchIngestOptions(BaseModel):
    max_concurrent: int = 4
    fail_fast: bool = False


class BatchIngestRequest(BaseModel):
    items: list[BatchIngestItem]
    options: BatchIngestOptions = BatchIngestOptions()


class RejectedItem(BaseModel):
    index: int
    reason: str


class BatchIngestResponse(BaseModel):
    job_id: str
    accepted: int
    rejected: list[RejectedItem]


class IngestJob(BaseModel):
    id: str
    status: str
    total_items: int
    accepted_items: int
    completed_items: int
    failed_items: int
    rejected: list[dict[str, Any]]
    failed: list[dict[str, Any]]
    results: list[dict[str, Any]]
    options: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class DocumentDiffResponse(BaseModel):
    document_id: str
    against: str
    diff: list[str]


class DocumentMergeRequest(BaseModel):
    target_document_id: str


class EvalLabel(BaseModel):
    query: str
    relevant_doc_ids: list[str] = []
    relevant_chunk_ids: list[str] = []


class EvalRequest(BaseModel):
    labels: list[EvalLabel]
    top_k: int = 10


class EvalRunSummary(BaseModel):
    id: str
    created_at: datetime
    top_k: int
    metrics: dict[str, Any]


class EvalRunDetail(EvalRunSummary):
    labels: list[dict[str, Any]]
    results: list[dict[str, Any]]


class KnowledgeStatsResponse(BaseModel):
    doc_count: int
    chunk_count: int
    average_chunk_length: float
    source_breakdown: dict[str, int]
    last_24h_ingest_count: int
    fts_size: int


async def get_repository() -> KnowledgeRepository:
    global _repository_initialised
    if not _repository_initialised:
        async with _repository_lock:
            if not _repository_initialised:
                await _repository.initialise()
                _repository_initialised = True
    return _repository


@lru_cache(maxsize=1)
def get_embedding_provider() -> EmbeddingProvider:
    return get_embedding_provider_from_env() or HashEmbeddingProvider()


@lru_cache(maxsize=1)
def get_reranker_provider() -> RerankerProvider | None:
    return get_reranker_provider_from_env()


RepositoryDep = Annotated[KnowledgeRepository, Depends(get_repository)]
EmbeddingProviderDep = Annotated[EmbeddingProvider, Depends(get_embedding_provider)]
RerankerProviderDep = Annotated[RerankerProvider | None, Depends(get_reranker_provider)]


@router.get("/knowledge/documents", response_model=list[KnowledgeDocument])
async def list_knowledge_documents(
    response: Response,
    repo: RepositoryDep,
    competitor: str | None = None,
    dimension: str | None = None,
    source_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[KnowledgeDocument]:
    try:
        total = await repo.count_documents(
            competitor=competitor,
            dimension=dimension,
            source_type=source_type,
        )
        response.headers["X-Total-Count"] = str(total)
        response.headers["X-Limit"] = str(limit)
        response.headers["X-Offset"] = str(offset)
        return await repo.list_documents(
            competitor=competitor,
            dimension=dimension,
            source_type=source_type,
            limit=limit,
            offset=offset,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/knowledge/documents/{document_id}", response_model=KnowledgeDocument)
async def get_knowledge_document(
    document_id: str,
    repo: RepositoryDep,
) -> KnowledgeDocument:
    try:
        document = await repo.get_document(document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return document
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/knowledge/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge_document(
    document_id: str,
    repo: RepositoryDep,
) -> None:
    try:
        document = await repo.get_document(document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        await repo.delete_document(document_id)
        from packages.knowledge.vector_store import VectorStore

        await VectorStore().delete_by_document(document_id)
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/knowledge/documents/{document_id}/versions", response_model=list[KnowledgeDocument])
async def get_knowledge_document_versions(
    document_id: str,
    repo: RepositoryDep,
) -> list[KnowledgeDocument]:
    versions = await repo.get_document_versions(document_id)
    if not versions:
        raise HTTPException(status_code=404, detail="Document not found")
    return versions


@router.get("/knowledge/documents/{document_id}/diff", response_model=DocumentDiffResponse)
async def diff_knowledge_document(
    document_id: str,
    repo: RepositoryDep,
    against: str = Query(...),
) -> DocumentDiffResponse:
    document = await repo.get_document(document_id)
    other = await repo.get_document(against)
    if document is None or other is None:
        raise HTTPException(status_code=404, detail="Document not found")
    diff = list(difflib.unified_diff(
        other.text.splitlines(),
        document.text.splitlines(),
        fromfile=other.id,
        tofile=document.id,
        lineterm="",
    ))
    return DocumentDiffResponse(document_id=document.id, against=other.id, diff=diff)


@router.post("/knowledge/documents/{document_id}/merge", response_model=KnowledgeDocument)
async def merge_knowledge_document_version(
    document_id: str,
    request: DocumentMergeRequest,
    repo: RepositoryDep,
) -> KnowledgeDocument:
    merged = await repo.merge_document_version(document_id, request.target_document_id)
    if merged is None:
        raise HTTPException(status_code=404, detail="Document version not found")
    return merged


@router.post("/knowledge/search", response_model=RetrievalResponse)
async def search_knowledge(
    request: RetrievalRequest,
    repo: RepositoryDep,
    embedding_provider: EmbeddingProviderDep,
    reranker_provider: RerankerProviderDep,
) -> RetrievalResponse:
    try:
        service = RetrievalService(
            repo=repo,
            vector_store=_vector_store_for_search(),
            embed_fn=embedding_provider.embed_documents,
            rerank_fn=reranker_provider.rerank if reranker_provider else None,
            rerank_model=reranker_provider.model_version if reranker_provider else None,
        )
        return await service.retrieve(request)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/knowledge/eval", response_model=EvalRunDetail)
async def evaluate_knowledge(
    request: EvalRequest,
    repo: RepositoryDep,
    embedding_provider: EmbeddingProviderDep,
    reranker_provider: RerankerProviderDep,
) -> EvalRunDetail:
    top_k = max(1, request.top_k)
    labels = [
        RetrievalLabel(
            query=label.query,
            relevant_doc_ids=label.relevant_doc_ids,
            relevant_chunk_ids=label.relevant_chunk_ids,
        )
        for label in request.labels
    ]
    service = RetrievalService(
        repo=repo,
        vector_store=_vector_store_for_search(),
        embed_fn=embedding_provider.embed_documents,
        rerank_fn=reranker_provider.rerank if reranker_provider else None,
        rerank_model=reranker_provider.model_version if reranker_provider else None,
    )
    responses = [
        await service.retrieve(
            RetrievalRequest(
                query=label.query,
                top_k=top_k,
                rerank_top_k=top_k,
                final_top_k=top_k,
            )
        )
        for label in labels
    ]
    hits_by_query = [response.hits for response in responses]
    metrics = evaluate_retrieval(labels, hits_by_query, top_k=top_k)
    run_id = str(uuid.uuid4())
    result_payload = [
        {
            "query": label.query,
            "hits": [hit.model_dump(mode="json") for hit in response.hits],
        }
        for label, response in zip(labels, responses, strict=False)
    ]
    label_payload = [label.model_dump(mode="json") for label in request.labels]
    await repo.record_eval_run(
        run_id=run_id,
        top_k=top_k,
        metrics=metrics,
        labels=label_payload,
        results=result_payload,
    )
    stored = await repo.get_eval_run(run_id)
    if stored is None:
        raise HTTPException(status_code=500, detail="Eval run was not persisted")
    return EvalRunDetail(**stored)


@router.get("/knowledge/eval/runs", response_model=list[EvalRunSummary])
async def list_knowledge_eval_runs(
    repo: RepositoryDep,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[EvalRunSummary]:
    rows = await repo.list_eval_runs(limit=limit, offset=offset)
    return [EvalRunSummary(**row) for row in rows]


@router.get("/knowledge/eval/runs/{run_id}", response_model=EvalRunDetail)
async def get_knowledge_eval_run(
    run_id: str,
    repo: RepositoryDep,
) -> EvalRunDetail:
    row = await repo.get_eval_run(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Eval run not found")
    return EvalRunDetail(**row)


@router.get("/knowledge/stats", response_model=KnowledgeStatsResponse)
async def get_knowledge_stats(repo: RepositoryDep) -> KnowledgeStatsResponse:
    stats = await repo.knowledge_stats()
    return KnowledgeStatsResponse(**stats)


@router.get("/knowledge/crawl-jobs", response_model=list[CrawlJob])
async def list_knowledge_crawl_jobs(
    response: Response,
    repo: RepositoryDep,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[CrawlJob]:
    total = await repo.count_crawl_jobs(status=status_filter)
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Limit"] = str(limit)
    response.headers["X-Offset"] = str(offset)
    rows = await repo.list_crawl_jobs(status=status_filter, limit=limit, offset=offset)
    return [_row_to_crawl_job(row) for row in rows]


@router.post("/knowledge/crawl-jobs", response_model=CrawlJob, status_code=201)
async def create_knowledge_crawl_job(
    request: CrawlJobCreate,
    repo: RepositoryDep,
) -> CrawlJob:
    job_id = await repo.create_crawl_job(
        request.url,
        run_id=request.run_id,
        competitor=request.competitor,
        dimension=request.dimension,
    )
    asyncio.create_task(_run_crawl_job(job_id))
    row = await repo.get_crawl_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Crawl job not found")
    return _row_to_crawl_job(row)


@router.get("/knowledge/crawl-jobs/{job_id}", response_model=CrawlJob)
async def get_knowledge_crawl_job(
    job_id: str,
    repo: RepositoryDep,
) -> CrawlJob:
    row = await repo.get_crawl_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Crawl job not found")
    return _row_to_crawl_job(row)


@router.post("/knowledge/batch", response_model=BatchIngestResponse, status_code=202)
async def create_knowledge_batch(
    request: BatchIngestRequest,
    repo: RepositoryDep,
    embedding_provider: EmbeddingProviderDep,
) -> BatchIngestResponse:
    rejected: list[RejectedItem] = []
    accepted_items: list[tuple[int, BatchIngestItem]] = []
    for index, item in enumerate(request.items):
        reason = _validate_batch_item(item)
        if reason:
            rejected.append(RejectedItem(index=index, reason=reason))
        else:
            accepted_items.append((index, item))

    job_id = str(uuid.uuid4())
    options = {
        "max_concurrent": max(1, min(request.options.max_concurrent, 16)),
        "fail_fast": request.options.fail_fast,
    }
    await repo.create_ingest_job(
        job_id,
        total_items=len(request.items),
        accepted_items=len(accepted_items),
        rejected_items=[item.model_dump() for item in rejected],
        options=options,
    )

    if accepted_items:
        asyncio.create_task(_process_batch_ingest(
            job_id,
            accepted_items,
            repo=repo,
            options=options,
            embedding_provider=embedding_provider,
        ))
    else:
        await repo.update_ingest_job_status(job_id, "success")

    return BatchIngestResponse(job_id=job_id, accepted=len(accepted_items), rejected=rejected)


@router.get("/knowledge/ingest-jobs/{job_id}", response_model=IngestJob)
async def get_knowledge_ingest_job(
    job_id: str,
    repo: RepositoryDep,
) -> IngestJob:
    row = await repo.get_ingest_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Ingest job not found")
    return _row_to_ingest_job(row)


@router.get("/knowledge/ingest-jobs", response_model=list[IngestJob])
async def list_knowledge_ingest_jobs(
    repo: RepositoryDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[IngestJob]:
    rows = await repo.list_ingest_jobs(limit=limit, offset=offset)
    return [_row_to_ingest_job(row) for row in rows]


async def _run_crawl_job(job_id: str) -> None:
    repo = await get_repository()
    row = await repo.get_crawl_job(job_id)
    if row is None:
        return
    job = _row_to_crawl_job(row)

    await repo.update_crawl_job(job_id, status="running")
    from packages.crawler.scheduler import CrawlerScheduler

    scheduler = CrawlerScheduler()
    try:
        result = await scheduler.crawl_sync(
            CrawlRequest(
                url=job.url,
                run_id=job.run_id,
                competitor=job.competitor,
                dimension=job.dimension,
            )
        )
        final_status = "success" if result.success else "failed"
        error = result.error
        result_metadata: dict[str, Any] = {}
        if result.success:
            result_metadata = await ingest_crawl_result(
                repo,
                result,
                embedding_provider=get_embedding_provider(),
            )
    except Exception as exc:
        final_status = "failed"
        error = str(exc)
        result_metadata = {}
    finally:
        await scheduler.stop()

    await repo.update_crawl_job(
        job_id,
        status=final_status,
        error=error,
        result_metadata=result_metadata,
    )


def _row_to_crawl_job(row: aiosqlite.Row) -> CrawlJob:
    return CrawlJob(
        id=row["id"],
        run_id=row["run_id"],
        url=row["url"],
        competitor=row["competitor"],
        dimension=row["dimension"],
        status=row["status"],
        attempt_count=row["attempt_count"],
        error=row["error"],
        result_metadata=json.loads(row["result_metadata_json"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _row_to_ingest_job(row: aiosqlite.Row) -> IngestJob:
    return IngestJob(
        id=row["id"],
        status=row["status"],
        total_items=row["total_items"],
        accepted_items=row["accepted_items"],
        completed_items=row["completed_items"],
        failed_items=row["failed_items"],
        rejected=json.loads(row["rejected_items_json"]),
        failed=json.loads(row["failed_items_json"]),
        results=json.loads(row["result_items_json"]),
        options=json.loads(row["options_json"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


async def ingest_crawl_result(
    repo: KnowledgeRepository,
    result: CrawlResult,
    *,
    embedding_provider: EmbeddingProvider | None = None,
) -> dict[str, Any]:
    if not _kb_ingest_on_crawl():
        return {"ingested": False, "reason": "disabled"}
    if not result.page or not result.page.text.strip():
        return {"ingested": False, "reason": "empty_page"}

    page = result.page
    doc = DocumentCreate(
        url=page.url,
        canonical_url=page.url,
        title=page.title or page.url,
        source_type="webpage_verified",
        competitor=result.request.competitor,
        dimension=result.request.dimension,
        text=page.text,
        markdown=page.markdown,
        metadata={
            "content_type": page.content_type,
            "status_code": page.status_code,
            "content_length": page.content_length,
            "crawl_content_hash": page.content_hash,
            "meta_description": page.meta_description,
            "meta_keywords": page.meta_keywords,
            "links": page.links,
            "tables": page.tables,
            "fetched_at": page.fetched_at.isoformat(),
        },
    )
    pipeline = IngestionPipeline(
        repo=repo,
        vector_store=_vector_store_for_ingest(embedding_provider),
    )
    document_id = await pipeline.ingest(doc, embedding_provider=embedding_provider)
    return {"ingested": True, "document_id": document_id}


async def _process_batch_ingest(
    job_id: str,
    items: list[tuple[int, BatchIngestItem]],
    *,
    repo: KnowledgeRepository,
    options: dict[str, Any],
    embedding_provider: EmbeddingProvider | None,
) -> None:
    await repo.update_ingest_job_status(job_id, "running")
    semaphore = asyncio.Semaphore(options["max_concurrent"])
    failed_fast = asyncio.Event()
    update_lock = asyncio.Lock()

    async def run_one(index: int, item: BatchIngestItem) -> None:
        if failed_fast.is_set():
            async with update_lock:
                await repo.record_ingest_job_failure(
                    job_id,
                    index=index,
                    reason="skipped due to fail_fast",
                )
            return
        async with semaphore:
            item_repo = KnowledgeRepository(repo.db_path)
            try:
                await item_repo.initialise()
                document_id = await _ingest_batch_item(
                    item_repo,
                    index,
                    item,
                    embedding_provider=embedding_provider,
                )
                async with update_lock:
                    await repo.record_ingest_job_success(
                        job_id,
                        index=index,
                        document_id=document_id,
                    )
            except Exception as exc:
                if options["fail_fast"]:
                    failed_fast.set()
                async with update_lock:
                    await repo.record_ingest_job_failure(
                        job_id,
                        index=index,
                        reason=str(exc),
                    )
            finally:
                await item_repo.close()

    await asyncio.gather(*(run_one(index, item) for index, item in items))
    row = await repo.get_ingest_job(job_id)
    if row is None:
        return
    final_status = "failed" if row["failed_items"] else "success"
    await repo.update_ingest_job_status(job_id, final_status)


async def _ingest_batch_item(
    repo: KnowledgeRepository,
    index: int,
    item: BatchIngestItem,
    *,
    embedding_provider: EmbeddingProvider | None,
) -> str:
    if item.source == "url":
        return await _ingest_url_batch_item(repo, item, embedding_provider=embedding_provider)

    if item.source == "text":
        parsed = parse_document(
            (item.text or "").encode("utf-8"),
            "text/plain",
            item.title or f"batch-item-{index}.txt",
        )
        parsed.title = item.title or parsed.title
        return await _ingest_parsed_document(
            repo,
            parsed,
            source_type="manual",
            source_url=None,
            canonical_url=None,
            embedding_provider=embedding_provider,
        )

    try:
        content = base64.b64decode(item.content_b64 or "", validate=True)
    except Exception as exc:
        raise ValueError("invalid base64 content") from exc
    parsed = parse_document(content, item.mime or "", item.filename)
    return await _ingest_parsed_document(
        repo,
        parsed,
        source_type="manual",
        source_url=None,
        canonical_url=item.filename,
        embedding_provider=embedding_provider,
    )


async def _ingest_url_batch_item(
    repo: KnowledgeRepository,
    item: BatchIngestItem,
    *,
    embedding_provider: EmbeddingProvider | None,
) -> str:
    from packages.crawler.scheduler import CrawlerScheduler

    scheduler = CrawlerScheduler()
    try:
        result = await scheduler.crawl_sync(CrawlRequest(url=item.url or ""))
        if not result.success or result.page is None:
            raise ValueError(result.error or "crawl failed")
        metadata = await ingest_crawl_result(repo, result, embedding_provider=embedding_provider)
        if not metadata.get("document_id"):
            raise ValueError(metadata.get("reason") or "crawl result was not ingested")
        return str(metadata["document_id"])
    finally:
        await scheduler.stop()


async def _ingest_parsed_document(
    repo: KnowledgeRepository,
    parsed: ParsedDocument,
    *,
    source_type: str,
    source_url: str | None,
    canonical_url: str | None,
    embedding_provider: EmbeddingProvider | None,
) -> str:
    if not parsed.text.strip():
        raise ValueError("parsed document is empty")
    if len(parsed.warnings) > _warning_threshold():
        raise ValueError("parser warning threshold exceeded")

    metadata = dict(parsed.metadata)
    metadata.update({
        "parser_version": parsed.parser_version,
        "warnings": parsed.warnings,
        "mime_type": parsed.mime_type,
        "tables": parsed.tables,
    })
    doc = DocumentCreate(
        url=source_url,
        canonical_url=canonical_url,
        title=parsed.title or canonical_url or source_url or "Untitled",
        source_type=source_type,
        text=parsed.text,
        markdown=metadata.get("markdown", ""),
        metadata=metadata,
    )
    pipeline = IngestionPipeline(
        repo=repo,
        vector_store=_vector_store_for_ingest(embedding_provider),
    )
    return await pipeline.ingest(doc, embedding_provider=embedding_provider)


def _validate_batch_item(item: BatchIngestItem) -> str | None:
    if item.source == "url" and not item.url:
        return "url is required"
    if item.source == "text" and not (item.text or "").strip():
        return "text is required"
    if item.source == "base64":
        if not item.content_b64:
            return "content_b64 is required"
        if not item.mime:
            return "mime is required"
    return None


def _kb_ingest_on_crawl() -> bool:
    return os.getenv("KB_INGEST_ON_CRAWL", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
        "disabled",
    }


def _warning_threshold() -> int:
    try:
        return int(os.getenv("KB_INGEST_WARNING_THRESHOLD", "3"))
    except ValueError:
        return 3


def _vector_store_for_search():
    from packages.knowledge.vector_store import VectorStore

    return VectorStore()


def _vector_store_for_ingest(embedding_provider: EmbeddingProvider | None):
    if embedding_provider is None:
        return _NoopVectorStore()
    from packages.knowledge.vector_store import VectorStore

    return VectorStore()


class _NoopVectorStore:
    async def upsert(
        self,
        chunk_ids: list[str],
        vectors: list[list[float]],
        payloads: list[dict[str, Any]],
    ) -> None:
        return None
