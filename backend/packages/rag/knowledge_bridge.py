from __future__ import annotations

import re
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urlparse

from packages.identity import (
    compute_competitor_id,
    compute_raw_source_id,
    normalize_key,
    stable_prefixed_id,
)
from packages.knowledge.models import KnowledgeChunk, KnowledgeDocument
from packages.knowledge.repository import KnowledgeRepository
from packages.schema.enterprise import (
    EvidenceRecord,
    EvidenceReindexResult,
    KnowledgeEvidenceSyncRequest,
    KnowledgeEvidenceSyncResult,
)

MAX_METADATA_CHUNK_IDS = 50
DEFAULT_METADATA_KEYS = {
    "robots_status",
    "source_policy",
    "fetch_status",
    "http_status",
    "content_type",
    "language",
    "author",
    "published_at",
    "updated_at",
}
_WHITESPACE_RE = re.compile(r"\s+")


class KnowledgeEvidenceStore(Protocol):
    def upsert_evidence(self, evidence: EvidenceRecord) -> EvidenceRecord: ...

    def upsert_evidence_batch(self, evidence: list[EvidenceRecord]) -> list[EvidenceRecord]: ...

    def reindex_evidence_embeddings(
        self,
        *,
        workspace_id: str | None = None,
        project_id: str | None = None,
    ) -> EvidenceReindexResult: ...


async def sync_knowledge_to_evidence(
    *,
    repo: KnowledgeRepository,
    store: KnowledgeEvidenceStore,
    workspace_id: str,
    project_id: str,
    request: KnowledgeEvidenceSyncRequest,
    competitor_id_map: dict[str, str] | None = None,
) -> KnowledgeEvidenceSyncResult:
    started_at = datetime.now(UTC)
    started_perf = time.perf_counter()
    documents = await repo.list_documents_for_evidence_sync(
        crawl_run_id=request.crawl_run_id,
        competitors=_non_empty(request.competitors),
        dimensions=_non_empty(request.dimensions),
        source_types=_non_empty(request.source_types),
        limit=request.limit,
        offset=request.offset,
    )
    states = await repo.get_evidence_sync_states(
        workspace_id=workspace_id,
        project_id=project_id,
        document_ids=[doc.id for doc in documents],
    )
    pending_documents = [
        doc
        for doc in documents
        if request.force_resync or states.get(doc.id, {}).get("content_hash") != doc.content_hash
    ]
    skipped_count = len(documents) - len(pending_documents)
    chunks_by_doc = await repo.get_chunks_for_documents([doc.id for doc in pending_documents])

    evidence_records: list[EvidenceRecord] = []
    chunk_count = 0
    crawl_run_ids: set[str] = set()
    for document in pending_documents:
        chunks = chunks_by_doc.get(document.id, [])
        if request.crawl_run_id:
            chunks = [chunk for chunk in chunks if chunk.crawl_run_id == request.crawl_run_id]
        chunk_count += len(chunks)
        crawl_run_ids.update(chunk.crawl_run_id for chunk in chunks if chunk.crawl_run_id)
        evidence_records.append(
            knowledge_document_to_evidence_record(
                document,
                chunks=chunks,
                workspace_id=workspace_id,
                project_id=project_id,
                run_id=request.run_id,
                competitor_id_map=competitor_id_map or {},
                snippet_chars=request.snippet_chars,
                full_text_chars=request.full_text_chars,
                max_selected_chunks=request.max_selected_chunks,
                metadata_keys=request.metadata_keys,
            )
        )

    # 批量写入让 Postgres 复用同一个连接和事务，内存版也只抢一次锁。
    stored = store.upsert_evidence_batch(evidence_records) if evidence_records else []
    await repo.record_evidence_sync_states(
        [
            {
                "workspace_id": workspace_id,
                "project_id": project_id,
                "document_id": item.metadata["kb_document_id"],
                "content_hash": item.content_hash,
                "evidence_id": item.id,
                "metadata": {
                    "run_id": item.run_id,
                    "crawl_run_ids": item.metadata.get("kb_crawl_run_ids", []),
                },
            }
            for item in stored
        ]
    )

    reindex_skipped = False
    if request.reindex_embeddings and len(stored) <= request.reindex_max_documents:
        reindex = store.reindex_evidence_embeddings(
            workspace_id=workspace_id,
            project_id=project_id,
        )
    else:
        reindex_skipped = request.reindex_embeddings and len(stored) > request.reindex_max_documents
        reindex = _incremental_index_result(stored)

    completed_at = datetime.now(UTC)
    elapsed_ms = max(0.0, (time.perf_counter() - started_perf) * 1000)
    result = KnowledgeEvidenceSyncResult(
        workspace_id=workspace_id,
        project_id=project_id,
        loaded_count=len(documents),
        ingested_count=len(stored),
        skipped_count=skipped_count,
        chunk_count=chunk_count,
        indexed_count=reindex.indexed_count,
        duplicate_count=reindex.duplicate_count,
        reindex_skipped=reindex_skipped,
        elapsed_ms=elapsed_ms,
        evidence_ids=[item.id for item in stored],
        crawl_run_ids=sorted(crawl_run_ids),
        competitors=_sorted_unique(item.metadata.get("kb_competitor_name", "") for item in stored),
        dimensions=_sorted_unique(item.dimension for item in stored),
    )
    metric_id = await repo.record_evidence_sync_metric(
        workspace_id=workspace_id,
        project_id=project_id,
        status="succeeded",
        started_at=started_at,
        completed_at=completed_at,
        duration_ms=elapsed_ms,
        loaded_count=result.loaded_count,
        ingested_count=result.ingested_count,
        skipped_count=result.skipped_count,
        chunk_count=result.chunk_count,
        indexed_count=result.indexed_count,
        duplicate_count=result.duplicate_count,
        request=request.model_dump(mode="json"),
    )
    return result.model_copy(update={"metric_id": metric_id})


def knowledge_document_to_evidence_record(
    document: KnowledgeDocument,
    *,
    chunks: list[KnowledgeChunk],
    workspace_id: str,
    project_id: str,
    run_id: str | None = None,
    competitor_id_map: dict[str, str] | None = None,
    snippet_chars: int = 500,
    full_text_chars: int = 6000,
    max_selected_chunks: int = 8,
    metadata_keys: list[str] | None = None,
) -> EvidenceRecord:
    competitor = _document_competitor(document)
    dimension = _document_dimension(document)
    crawl_run_ids = sorted({chunk.crawl_run_id for chunk in chunks if chunk.crawl_run_id})
    resolved_run_id = run_id or _metadata_text(document.metadata, "run_id") or _first(crawl_run_ids)
    resolved_run_id = resolved_run_id or "kb-crawler"
    source_text, selected_chunk_count, source_text_length = _selected_source_text(
        document,
        chunks=chunks,
        budget=max(snippet_chars, full_text_chars, 1000),
        max_selected_chunks=max_selected_chunks,
    )
    snippet = _clip(source_text or document.title, snippet_chars)
    full_text = _clip(source_text, full_text_chars)
    canonical_url = document.canonical_url or document.url or ""
    content_hash = document.content_hash

    # EvidenceRecord 是当前系统的证据主模型；稳定 ID 保证重复同步覆盖同一条证据。
    evidence_id = stable_prefixed_id(
        "evidence-kb",
        workspace_id,
        project_id,
        document.id,
        content_hash,
        length=20,
    )
    raw_source_id = compute_raw_source_id(
        source_type=document.source_type,
        competitor=competitor,
        dimension=dimension,
        url=canonical_url,
        content_hash=content_hash,
        title=document.title,
        snippet=snippet,
        run_id=resolved_run_id,
        source_role="kb-crawler",
    )
    metadata = _sync_metadata(
        document,
        chunks=chunks,
        competitor=competitor,
        crawl_run_ids=crawl_run_ids,
        full_text=full_text,
        full_text_chars=full_text_chars,
        source_text_length=source_text_length,
        selected_chunk_count=selected_chunk_count,
        metadata_keys=metadata_keys or [],
    )
    return EvidenceRecord(
        id=evidence_id,
        workspace_id=workspace_id,
        project_id=project_id,
        run_id=resolved_run_id,
        raw_source_id=raw_source_id,
        competitor_id=_competitor_id(workspace_id, competitor, competitor_id_map or {}),
        dimension=dimension,
        source_type=document.source_type,
        title=document.title,
        url=_http_url_or_none(document.url or document.canonical_url),
        canonical_url=canonical_url,
        snippet=snippet,
        content_hash=content_hash,
        reliability_score=_reliability_score(document.source_type),
        freshness_score=_freshness_score(document.last_seen_at or document.fetched_at),
        quality_label="unreviewed",
        first_seen_run_id=_first(crawl_run_ids) or resolved_run_id,
        last_seen_run_id=_last(crawl_run_ids) or resolved_run_id,
        captured_at=document.fetched_at,
        metadata=metadata,
    )


def _sync_metadata(
    document: KnowledgeDocument,
    *,
    chunks: list[KnowledgeChunk],
    competitor: str,
    crawl_run_ids: list[str],
    full_text: str,
    full_text_chars: int,
    source_text_length: int,
    selected_chunk_count: int,
    metadata_keys: list[str],
) -> dict[str, object]:
    # 只保存精选 chunk 和白名单 metadata，避免长网页和爬虫内部字段放大存储与索引成本。
    metadata: dict[str, object] = {
        "kb_sync": True,
        "kb_document_id": document.id,
        "kb_document_version": document.version,
        "kb_parent_document_id": document.parent_document_id,
        "kb_competitor_name": competitor,
        "kb_chunk_count": len(chunks),
        "kb_selected_chunk_count": selected_chunk_count,
        "kb_omitted_chunk_count": max(0, len(chunks) - selected_chunk_count),
        "kb_chunk_ids": [chunk.id for chunk in chunks[:MAX_METADATA_CHUNK_IDS]],
        "kb_chunk_ids_truncated": len(chunks) > MAX_METADATA_CHUNK_IDS,
        "kb_crawl_run_ids": crawl_run_ids,
        "source_material_level": "kb_crawler_document",
        "source_text_length": source_text_length,
        "source_text_chars_stored": len(full_text),
        "source_text_truncated": source_text_length > len(full_text),
        "source_full_text_limit": full_text_chars,
        "robots_status": document.metadata.get("robots_status", "unknown"),
        "kb_source_metadata": _safe_source_metadata(document.metadata, metadata_keys),
    }
    if full_text:
        metadata["full_text"] = full_text
    return metadata


def _selected_source_text(
    document: KnowledgeDocument,
    *,
    chunks: list[KnowledgeChunk],
    budget: int,
    max_selected_chunks: int,
) -> tuple[str, int, int]:
    if chunks:
        source_text_length = sum(len(_normalized_text(chunk.text)) for chunk in chunks)
        pieces: list[str] = []
        selected_count = 0
        remaining = max(0, budget)
        for chunk in _select_high_value_chunks(document, chunks, max_selected_chunks):
            text = _normalized_text(chunk.text)
            if not text or remaining <= 0:
                continue
            piece = text[:remaining].strip()
            if piece:
                pieces.append(piece)
                selected_count += 1
                remaining -= len(piece)
        return "\n\n".join(pieces), selected_count, source_text_length
    fallback = _normalized_text(document.markdown or document.text)
    return fallback[: max(0, budget)].strip(), 0, len(fallback)


def _select_high_value_chunks(
    document: KnowledgeDocument,
    chunks: list[KnowledgeChunk],
    limit: int,
) -> list[KnowledgeChunk]:
    query_terms = _tokens(
        " ".join(
            part
            for part in [
                document.title,
                document.competitor or "",
                document.dimension or "",
                _metadata_text(document.metadata, "competitor") or "",
                _metadata_text(document.metadata, "dimension") or "",
            ]
            if part
        )
    )
    ranked = sorted(
        chunks,
        key=lambda chunk: (
            -_chunk_value_score(chunk, query_terms),
            chunk.chunk_index,
        ),
    )
    selected = ranked[:limit]
    return sorted(selected, key=lambda chunk: chunk.chunk_index)


def _chunk_value_score(chunk: KnowledgeChunk, query_terms: set[str]) -> float:
    text = _normalized_text(chunk.text)
    if not text:
        return 0.0
    tokens = _tokens(text)
    overlap = len(tokens & query_terms)
    length_score = min(len(text), 1200) / 1200
    early_bonus = 1.0 / (chunk.chunk_index + 1)
    return overlap * 3.0 + length_score + early_bonus


def _incremental_index_result(stored: list[EvidenceRecord]) -> EvidenceReindexResult:
    duplicate_count = sum(1 for item in stored if item.metadata.get("embedding_duplicate_of"))
    return EvidenceReindexResult(
        indexed_count=max(0, len(stored) - duplicate_count),
        duplicate_count=duplicate_count,
    )


def _safe_source_metadata(metadata: dict[str, Any], extra_keys: list[str]) -> dict[str, object]:
    allowed = DEFAULT_METADATA_KEYS | {key for key in extra_keys if key.strip()}
    result: dict[str, object] = {}
    for key in sorted(allowed):
        if key not in metadata:
            continue
        value = _safe_metadata_value(metadata[key])
        if value is not None:
            result[key] = value
    result["omitted_key_count"] = max(0, len(metadata) - len(result))
    return result


def _safe_metadata_value(value: Any) -> object | None:
    if isinstance(value, str):
        return _clip(value, 500)
    if isinstance(value, bool | int | float) or value is None:
        return value
    if isinstance(value, list):
        return [_safe_metadata_value(item) for item in value[:20]]
    if isinstance(value, dict):
        safe: dict[str, object] = {}
        for key, item in list(value.items())[:20]:
            if isinstance(key, str):
                nested = _safe_metadata_value(item)
                if nested is not None:
                    safe[key] = nested
        return safe
    return str(value)[:200]


def _document_competitor(document: KnowledgeDocument) -> str:
    return (
        document.competitor
        or _metadata_text(document.metadata, "competitor")
        or _metadata_text(document.metadata, "competitor_name")
        or "unknown"
    )


def _document_dimension(document: KnowledgeDocument) -> str:
    return (
        document.dimension
        or _metadata_text(document.metadata, "dimension")
        or _metadata_text(document.metadata, "category")
        or "general"
    )


def _competitor_id(
    workspace_id: str,
    competitor: str,
    competitor_id_map: dict[str, str],
) -> str:
    key = normalize_key(competitor)
    return competitor_id_map.get(key) or compute_competitor_id(workspace_id, competitor)


def _reliability_score(source_type: str) -> float:
    key = normalize_key(source_type)
    if "official" in key or "verified" in key:
        return 0.85
    if "report" in key or "manual" in key:
        return 0.75
    if "search" in key:
        return 0.65
    return 0.6


def _freshness_score(value: datetime | None) -> float:
    if value is None:
        return 0.5
    now = datetime.now(UTC)
    timestamp = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    age_days = max(0, (now - timestamp).days)
    if age_days <= 7:
        return 1.0
    if age_days <= 30:
        return 0.85
    if age_days <= 90:
        return 0.7
    if age_days <= 180:
        return 0.55
    return 0.4


def _http_url_or_none(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return value
    return None


def _metadata_text(metadata: dict[str, object], key: str) -> str | None:
    value = metadata.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _normalized_text(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value).strip()


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", value.casefold()) if len(token) >= 2}


def _clip(value: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    normalized = _normalized_text(value)
    return normalized[:max_chars].strip()


def _non_empty(values: list[str]) -> list[str] | None:
    result = [value for value in values if value.strip()]
    return result or None


def _first(values: list[str]) -> str | None:
    return values[0] if values else None


def _last(values: list[str]) -> str | None:
    return values[-1] if values else None


def _sorted_unique(values: Iterable[object]) -> list[str]:
    return sorted({str(value) for value in values if str(value).strip()})
