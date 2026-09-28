from __future__ import annotations

import sqlite3

import pytest

from packages.enterprise.embedding_index import cosine_similarity, deterministic_embedding
from packages.knowledge.embeddings import BgeM3Provider, HashEmbeddingProvider
from packages.knowledge.ingestion import IngestionPipeline
from packages.knowledge.models import DocumentCreate, RetrievalHit, RetrievalRequest
from packages.knowledge.repository import KnowledgeRepository
from packages.knowledge.retrieval import RetrievalService
from packages.rag.bm25 import tokenize


class MemoryVectors:
    def __init__(self, fail_once=False):
        self.fail_once = fail_once
        self.calls = []
        self.points = {}

    async def upsert(self, ids, vectors, payloads):
        self.calls.append(list(ids))
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("vector unavailable")
        self.points.update(
            {
                key: (vector, payload)
                for key, vector, payload in zip(ids, vectors, payloads, strict=True)
            }
        )

    async def search(self, vector, **kwargs):
        return [
            RetrievalHit(
                chunk_id=key, document_id=payload["document_id"], text=payload["text"], score=1.0
            )
            for key, (_, payload) in self.points.items()
        ]


def document(text, **kwargs):
    return DocumentCreate(
        title="Generic guide",
        source_type="manual",
        competitor="Acme",
        dimension="pricing",
        text=text,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_sparse_search_returns_seventh_matching_chunk(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        pipeline = IngestionPipeline(repo, object(), chunk_size=40, chunk_overlap=0)
        doc_id = await pipeline.ingest(
            document(
                "\n\n".join(
                    [f"Section {i} ordinary explanation." for i in range(6)]
                    + ["Tail only: xenon pricing announcement."]
                )
            )
        )
        chunks = await repo.get_chunks_for_document(doc_id)
        assert len(chunks) == 7
        response = await RetrievalService(repo, object(), embed_fn=lambda _: []).retrieve(
            RetrievalRequest(query="xenon", mode="sparse", enable_query_rewrite=False)
        )
        assert len(response.hits) == 1
        assert "xenon" in response.hits[0].text
        assert response.hits[0].chunk_id == chunks[-1].id


@pytest.mark.asyncio
async def test_chinese_fts_migrates_existing_index_and_keeps_scope(tmp_path):
    path = str(tmp_path / "kb.db")
    async with KnowledgeRepository(path) as repo:
        doc_id = await IngestionPipeline(repo, object()).ingest(
            document("企业套餐包含审计日志与权限控制。")
        )
        await IngestionPipeline(repo, object()).ingest(
            DocumentCreate(
                title="Other",
                source_type="manual",
                competitor="Other",
                dimension="pricing",
                text="企业套餐也包含审计日志。",
            )
        )
    # Recreate the old unsegmented FTS index to exercise the upgrade, not only new DBs.
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM _schema_version WHERE id >= 10")
        for name in (
            "documents_ai",
            "documents_ad",
            "documents_au",
            "chunks_ai",
            "chunks_ad",
            "chunks_au",
        ):
            db.execute(f"DROP TRIGGER IF EXISTS {name}")
        db.execute("DROP TABLE chunks_fts")
        db.execute(
            "CREATE VIRTUAL TABLE chunks_fts USING fts5(text, content='chunks', content_rowid='rowid')"
        )
        db.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('rebuild')")
    async with KnowledgeRepository(path) as repo:
        response = await RetrievalService(repo, object(), embed_fn=lambda _: []).retrieve(
            RetrievalRequest(
                query="审计日志",
                mode="sparse",
                competitors=["Acme"],
                dimensions=["pricing"],
                enable_query_rewrite=False,
            )
        )
        assert [hit.document_id for hit in response.hits] == [doc_id]
        assert (await repo.get_document(doc_id)).indexing_status == "pending"


def test_chinese_project_hashing_and_bm25_are_nonzero():
    query = deterministic_embedding("企业定价")
    related = deterministic_embedding("企业定价套餐每月收费")
    unrelated = deterministic_embedding("照片编辑滤镜")
    assert any(query)
    assert cosine_similarity(query, related) > cosine_similarity(query, unrelated)
    assert set(tokenize("企业定价")) & set(tokenize("企业定价套餐"))


@pytest.mark.asyncio
async def test_failed_vector_write_retries_existing_chunk_ids(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        vectors = MemoryVectors(fail_once=True)
        pipeline = IngestionPipeline(repo, vectors)
        payload = document("Pricing starts at ten dollars.")
        provider = HashEmbeddingProvider(dimensions=8)
        with pytest.raises(RuntimeError, match="vector unavailable"):
            await pipeline.ingest(payload, embedding_provider=provider)
        failed = (await repo.list_documents())[0]
        assert failed.indexing_status == "failed"
        assert failed.indexing_error.startswith("upsert:")
        doc_id = await pipeline.ingest(payload, embedding_provider=provider)
        ready = await repo.get_document(doc_id)
        assert doc_id == failed.id
        assert vectors.calls[0] == vectors.calls[1]
        assert ready.indexing_status == "ready"
        assert ready.indexing_error is None
        assert ready.embedding_model == provider.model_version
        assert ready.embedding_dimensions == 8
        assert len(vectors.points) == len(await repo.get_chunks_for_document(doc_id))
        await pipeline.ingest(payload, embedding_provider=provider)
        assert len(vectors.calls) == 2


@pytest.mark.asyncio
async def test_embedding_failure_and_legacy_document_can_reindex(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        vectors = MemoryVectors()
        pipeline = IngestionPipeline(repo, vectors)
        payload = document("Legacy document needs vectors.")
        doc_id = await pipeline.ingest(payload)
        ids = [chunk.id for chunk in await repo.get_chunks_for_document(doc_id)]

        def fail(_):
            raise RuntimeError("embedding unavailable")

        with pytest.raises(RuntimeError):
            await pipeline.ingest(payload, embed_fn=fail, embedding_model="test-v1")
        assert (await repo.get_document(doc_id)).indexing_error.startswith("embedding:")
        await pipeline.reindex_document(
            doc_id, embedding_provider=HashEmbeddingProvider(dimensions=8)
        )
        assert vectors.calls[0] == ids
        assert (await repo.get_document(doc_id)).indexing_status == "ready"


def test_bge_fallback_reports_effective_hash_model():
    provider = BgeM3Provider()
    provider._load_error = RuntimeError("model unavailable")
    provider.embed_documents(["中文文档"])
    status = provider.status()
    assert status["requested_provider"] == "bge-m3"
    assert status["effective_provider"] == "hash"
    assert status["model_version"] == "hash-embedding-v1"
    assert status["dimensions"] == 1024
    assert status["degraded"] is True
    assert "model unavailable" in status["reason"]
    assert provider.model_version == status["model_version"]


@pytest.mark.asyncio
async def test_dense_excludes_documents_without_ready_index(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        vectors = MemoryVectors()
        pipeline = IngestionPipeline(repo, vectors)
        doc_id = await pipeline.ingest(document("pending pricing"))
        chunk = (await repo.get_chunks_for_document(doc_id))[0]
        vectors.points[chunk.id] = ([1.0], {"document_id": doc_id, "text": chunk.text})
        result = await RetrievalService(repo, vectors, embed_fn=lambda _: [[1.0]]).retrieve(
            RetrievalRequest(query="pricing", mode="dense", enable_query_rewrite=False)
        )
        assert result.hits == []
