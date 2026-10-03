"""Retrieval boundaries, canonical provenance and cache revalidation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from packages.knowledge.embeddings import HashEmbeddingProvider
from packages.knowledge.ingestion import IngestionPipeline
from packages.knowledge.models import DocumentCreate, RetrievalHit, RetrievalRequest
from packages.knowledge.repository import KnowledgeRepository
from packages.knowledge.reranker import HashRerankerProvider
from packages.knowledge.retrieval import RetrievalService, _filter_hits_by_request


class MemoryVectors:
    def __init__(self):
        self.payloads = {}
        self.calls = []
        self.override = None

    async def upsert(self, ids, _vectors, payloads):
        self.payloads.update(zip(ids, payloads, strict=True))

    async def search(self, _vector, **kwargs):
        self.calls.append(kwargs)
        if self.override is not None:
            return self.override
        return [
            RetrievalHit(
                chunk_id=key,
                document_id=p["document_id"],
                text=p["text"],
                score=1.0,
                workspace_id=p["workspace_id"] or None,
                project_id=p["project_id"] or None,
                competitor=p["competitor"],
                dimension=p["dimension"],
                market=p["market"],
                source_role=p["source_role"],
                source_type=p["source_type"],
                source_published_at=p["source_published_at"],
                last_verified_at=p["last_verified_at"],
                fetched_at=p["fetched_at"],
                document_version=p["document_version"],
                content_hash=p["document_content_hash"],
                metadata={
                    "vector_index": {
                        "model_version": p["embedding_model"],
                        "index_version": p["index_version"],
                        "dimensions": p["embedding_dimensions"],
                        "chunk_content_hash": p["content_hash"],
                    }
                },
            )
            for key, p in self.payloads.items()
        ]


def doc(**overrides):
    values = dict(
        title="Vacuum guide",
        source_type="manual",
        text="vacuum battery runtime sixty minutes",
        workspace_id="ws-a",
        project_id="project-a",
        competitor="Vacuum X Pro",
        dimension="specs",
        market="CN",
    )
    values.update(overrides)
    return DocumentCreate(**values)


def request(**overrides):
    values = dict(
        query="vacuum",
        workspace_id="ws-a",
        project_id="project-a",
        mode="dense",
        enable_query_rewrite=False,
        competitors=["Vacuum X Pro"],
        dimensions=["specs"],
        market="CN",
        source_roles=["source"],
        max_age_days=7,
        top_k=1,
        final_top_k=1,
    )
    values.update(overrides)
    return RetrievalRequest(**values)


def service(repo, vectors):
    provider = HashEmbeddingProvider(dimensions=8)
    return RetrievalService(
        repo, vectors, embed_fn=provider.embed_documents, embedding_provider=provider
    )


async def ingest(repo, vectors, **values):
    return await IngestionPipeline(repo, vectors).ingest(
        doc(**values), embedding_provider=HashEmbeddingProvider(dimensions=8)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["dense", "hybrid", "sparse"])
async def test_service_passes_the_same_filter_contract_before_limits(tmp_path, mode):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        vectors = MemoryVectors()
        await ingest(repo, vectors)
        sparse_calls = []
        original = repo.search_chunks

        async def search_chunks(query, **kwargs):
            sparse_calls.append(kwargs)
            return await original(query, **kwargs)

        repo.search_chunks = search_chunks
        req = request(mode=mode, include_workspace_library=True)
        await service(repo, vectors).retrieve(req)
        for call in [*vectors.calls, *sparse_calls]:
            assert call["scope"] == req.scope
            assert call["market"] == "CN"
            assert call["source_roles"] == ["source"]
            assert call["max_age_days"] == 7
            assert call["competitors"] == ["Vacuum X Pro"]
            assert call["dimensions"] == ["specs"]
            assert call.get("limit", call.get("top_k")) == 1


@pytest.mark.asyncio
async def test_sparse_service_filters_foreign_strong_match_before_top_one(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        vectors = MemoryVectors()
        for values in [
            {"workspace_id": "ws-b"},
            {"project_id": "project-b"},
            {"project_id": None},
            {"competitor": "Vacuum X"},
            {"dimension": "pricing"},
            {"market": "US"},
            {"source_type": "report"},
            {"workspace_id": None, "project_id": None},
            {"source_published_at": datetime.now(UTC) - timedelta(days=100)},
        ]:
            await ingest(repo, vectors, text="vacuum", **values)
        own = await ingest(repo, vectors, text="vacuum has a battery lasting sixty minutes")
        result = await service(repo, vectors).retrieve(request(mode="sparse"))
        assert [hit.document_id for hit in result.hits] == [own]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        {"document_version": 99},
        {"content_hash": "wrong"},
        {"chunk_id": "missing"},
        {"workspace_id": "ws-b"},
        {"project_id": "project-b"},
        {"workspace_id": None, "project_id": None},
        {"text": "payload does not match canonical chunk"},
        {"metadata": {"vector_index": {"model_version": "old", "index_version": "v1"}}},
        {
            "metadata": {
                "vector_index": {"model_version": "hash-embedding-v1", "index_version": "old"}
            }
        },
    ],
)
async def test_dense_rejects_stale_wrong_or_unscoped_payloads(tmp_path, mutation):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        vectors = MemoryVectors()
        await ingest(repo, vectors)
        hit = (await vectors.search([]))[0]
        vectors.override = [hit.model_copy(update=mutation)]
        result = await service(repo, vectors).retrieve(request())
        assert result.hits == []


@pytest.mark.asyncio
async def test_dense_rejects_a_chunk_from_another_document(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        vectors = MemoryVectors()
        own = await ingest(repo, vectors)
        other = await ingest(repo, vectors, project_id="other", text="vacuum other source")
        hits = await vectors.search([])
        first = next(hit for hit in hits if hit.document_id == own)
        second = next(hit for hit in hits if hit.document_id == other)
        vectors.override = [first.model_copy(update={"chunk_id": second.chunk_id})]
        assert (await service(repo, vectors).retrieve(request())).hits == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["dense", "sparse"])
@pytest.mark.parametrize(
    "change", ["archive", "version", "hash", "expired", "future", "delete_chunk"]
)
async def test_cached_hits_are_rechecked_against_current_documents(tmp_path, mode, change):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        vectors = MemoryVectors()
        own = await ingest(repo, vectors)
        engine = service(repo, vectors)
        req = request(mode=mode)
        first = await engine.retrieve(req)
        assert first.hits
        if change == "archive":
            await repo.soft_delete(own)
        elif change == "delete_chunk":
            await repo._connection.execute("DELETE FROM chunks WHERE document_id=?", [own])
        else:
            column, value = {
                "version": ("version", 99),
                "hash": ("content_hash", "new-hash"),
                "expired": (
                    "source_published_at",
                    (datetime.now(UTC) - timedelta(days=100)).isoformat(),
                ),
                "future": (
                    "source_published_at",
                    (datetime.now(UTC) + timedelta(days=1)).isoformat(),
                ),
            }[change]
            await repo._connection.execute(
                f"UPDATE documents SET {column}=? WHERE id=?", [value, own]
            )
        second = await engine.retrieve(req)
        if mode == "sparse" and change in {"version", "hash"}:
            assert second.hits[0].document_version == (99 if change == "version" else 1)
            assert second.hits[0].content_hash == (
                "new-hash" if change == "hash" else first.hits[0].content_hash
            )
        else:
            assert second.hits == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["dense", "sparse"])
async def test_empty_result_does_not_hide_newly_ingested_sources(tmp_path, mode):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        vectors = MemoryVectors()
        engine = service(repo, vectors)
        req = request(mode=mode)
        assert (await engine.retrieve(req)).hits == []
        own = await ingest(repo, vectors)
        assert [hit.document_id for hit in (await engine.retrieve(req)).hits] == [own]


@pytest.mark.asyncio
async def test_cache_keys_isolate_scope_market_role_and_age(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        vectors = MemoryVectors()
        await ingest(repo, vectors)
        engine = service(repo, vectors)
        req = request()
        assert (await engine.retrieve(req)).hits
        assert (await engine.retrieve(req)).hits
        assert len(vectors.calls) == 1
        for field, value in [
            ("workspace_id", "ws-b"),
            ("project_id", "project-b"),
            ("include_workspace_library", True),
            ("market", "US"),
            ("source_roles", ["historical_report"]),
            ("max_age_days", 1),
        ]:
            await engine.retrieve(req.model_copy(update={field: value}))
        assert len(vectors.calls) == 7


@pytest.mark.asyncio
async def test_healthy_scoped_sparse_responses_still_use_cache(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        vectors = MemoryVectors()
        own = await ingest(repo, vectors)
        searches = []
        original = repo.search_chunks

        async def search_chunks(*args, **kwargs):
            searches.append(kwargs)
            return await original(*args, **kwargs)

        repo.search_chunks = search_chunks
        engine = service(repo, vectors)
        req = request(mode="sparse")
        for _ in range(2):
            response = await engine.retrieve(req)
            assert [hit.document_id for hit in response.hits] == [own]
            assert response.diagnostics["degraded"] is False
        assert len(searches) == 1
        assert vectors.calls == []


@pytest.mark.asyncio
async def test_dense_cache_rejects_a_changed_provider_dimension(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        vectors = MemoryVectors()
        await ingest(repo, vectors)
        engine = service(repo, vectors)
        assert (await engine.retrieve(request())).hits
        engine._embedding_provider.dimensions = 16
        assert (await engine.retrieve(request())).hits == []
        assert len(vectors.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("dimensions", 16), ("model_version", "hash-other-v2")])
async def test_hybrid_cache_invalidates_when_embedding_identity_changes(tmp_path, field, value):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        vectors = MemoryVectors()
        await ingest(repo, vectors)
        engine = service(repo, vectors)
        req = request(mode="hybrid")
        first = await engine.retrieve(req)
        assert len(first.hits) == 1
        assert len(vectors.calls) == 1
        assert first.diagnostics["embedding"][field] == getattr(engine._embedding_provider, field)
        setattr(engine._embedding_provider, field, value)
        second = await engine.retrieve(req)
        assert len(vectors.calls) == 2
        assert len(second.hits) == 1  # Current SQLite source remains available.
        assert second.diagnostics["embedding"][field] == value


@pytest.mark.asyncio
async def test_hybrid_cache_invalidates_when_requested_index_version_changes(tmp_path, monkeypatch):
    monkeypatch.setenv("KB_INDEX_VERSION", "v1")
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        vectors = MemoryVectors()
        vectors.status = lambda: {
            "model_version": "hash-embedding-v1",
            "dimensions": 8,
            "index_version": "v1",
            "collection": "old",
        }
        await ingest(repo, vectors)
        engine = service(repo, vectors)
        req = request(mode="hybrid")
        assert (await engine.retrieve(req)).hits
        monkeypatch.setenv("KB_INDEX_VERSION", "v2")
        response = await engine.retrieve(req)
        assert response.hits
        assert len(vectors.calls) == 2
        assert response.hits[0].score == 1.0  # Only the current SQLite contribution.


@pytest.mark.asyncio
async def test_custom_embedder_still_checks_current_requested_index_version(tmp_path, monkeypatch):
    monkeypatch.setenv("KB_INDEX_VERSION", "v1")
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        vectors = MemoryVectors()
        await ingest(repo, vectors)
        engine = RetrievalService(
            repo,
            vectors,
            embed_fn=lambda texts: HashEmbeddingProvider(dimensions=8).embed_documents(texts),
        )
        req = request()
        assert (await engine.retrieve(req)).hits
        monkeypatch.setenv("KB_INDEX_VERSION", "v2")
        assert (await engine.retrieve(req)).hits == []


@pytest.mark.asyncio
async def test_hybrid_cache_invalidates_when_actual_vector_index_identity_changes(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        vectors = MemoryVectors()
        identity = {
            "model_version": "hash-embedding-v1",
            "dimensions": 8,
            "index_version": "v1",
            "collection": "first",
        }
        vectors.status = lambda: identity.copy()
        await ingest(repo, vectors)
        engine = service(repo, vectors)
        req = request(mode="hybrid")
        assert (await engine.retrieve(req)).hits
        identity["collection"] = "second"
        response = await engine.retrieve(req)
        assert response.hits
        assert len(vectors.calls) == 2
        assert response.diagnostics["index"]["collection"] == "second"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_backed", [True, False])
async def test_cache_invalidates_when_reranker_model_changes(tmp_path, provider_backed):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        vectors = MemoryVectors()
        await ingest(repo, vectors)
        engine = service(repo, vectors)
        reranker = HashRerankerProvider(model_version="rerank-v1")
        engine._rerank_fn = reranker.rerank
        engine._reranker_provider = reranker if provider_backed else None
        engine._rerank_model = reranker.model_version
        req = request(mode="hybrid")
        assert (await engine.retrieve(req)).hits[0].rerank_model == "rerank-v1"
        reranker.model_version = "rerank-v2"
        engine._rerank_model = reranker.model_version
        second = await engine.retrieve(req)
        assert len(vectors.calls) == 2
        assert second.hits[0].rerank_model == "rerank-v2"


@pytest.mark.asyncio
async def test_hybrid_cache_preserves_dense_provenance_to_recheck_failed_index(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        vectors = MemoryVectors()
        own = await ingest(repo, vectors)
        engine = service(repo, vectors)
        req = request(mode="hybrid")
        first = await engine.retrieve(req)
        assert first.hits
        assert "vector_index" in first.hits[0].metadata
        await repo.set_indexing_state(own, "failed", error="index unavailable")
        second = await engine.retrieve(req)
        assert len(vectors.calls) == 2
        assert second.hits[0].score == 1.0
        assert "vector_index" not in second.hits[0].metadata
        assert second.diagnostics["effective_mode"] == "sparse"
        assert second.diagnostics["degraded"] is True


@pytest.mark.asyncio
async def test_provenance_and_source_times_survive_retrieval_and_rerank(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        vectors = MemoryVectors()
        fetched = datetime.now(UTC) - timedelta(days=100)
        published = fetched - timedelta(days=10)
        verified = (datetime.now(UTC) - timedelta(days=1)).astimezone(
            timezone(timedelta(hours=-12))
        )
        own = await ingest(
            repo,
            vectors,
            fetched_at=fetched,
            source_published_at=published,
            last_verified_at=verified,
        )
        engine = service(repo, vectors)
        engine._rerank_fn = lambda _query, texts: [1.0] * len(texts)
        hit = (await engine.retrieve(request())).hits[0]
        stored = await repo.get_document(own)
        assert hit.document_id == own
        assert hit.chunk_id == (await repo.get_chunks_for_document(own))[0].id
        assert hit.document_version == stored.version
        assert hit.content_hash == stored.content_hash
        assert hit.fetched_at == fetched
        assert hit.source_published_at == published
        assert hit.last_verified_at == verified
        assert vectors.payloads[hit.chunk_id]["observed_at"] == verified.isoformat()


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["last_verified_at", "source_published_at", "fetched_at"])
async def test_future_source_time_is_not_fresh_but_unrestricted_search_is_available(
    tmp_path, field
):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        vectors = MemoryVectors()
        own = await ingest(repo, vectors, **{field: datetime.now(UTC) + timedelta(days=1)})
        req = request()
        assert await repo.search_chunks("vacuum", scope=req.scope, max_age_days=7) == []
        assert await repo.search_documents("vacuum", scope=req.scope, max_age_days=7) == []
        assert (await service(repo, vectors).retrieve(req)).hits == []
        assert [
            hit.document_id
            for hit in (await service(repo, vectors).retrieve(request(max_age_days=None))).hits
        ] == [own]


@pytest.mark.parametrize(
    "mutation",
    [
        {"workspace_id": "ws-b"},
        {"project_id": "project-b"},
        {"workspace_id": None},
        {"competitor": "Vacuum X"},
        {"dimension": "pricing"},
        {"market": "US"},
        {"source_role": "historical_report"},
        {"source_published_at": datetime.now(UTC) - timedelta(days=100)},
        {"last_verified_at": datetime.now(UTC) + timedelta(days=1)},
        {"source_published_at": datetime.now(UTC) + timedelta(days=1)},
        {"fetched_at": datetime.now(UTC) + timedelta(days=1)},
    ],
)
def test_final_defensive_filter_uses_all_typed_conditions(mutation):
    hit = RetrievalHit(
        chunk_id="c",
        document_id="d",
        text="vacuum",
        score=1,
        workspace_id="ws-a",
        project_id="project-a",
        competitor="Vacuum X Pro",
        dimension="specs",
        market="CN",
        fetched_at=datetime.now(UTC),
    )
    assert _filter_hits_by_request([hit.model_copy(update=mutation)], request()) == []
