"""Real Qdrant local persistence and pre-limit filters; no semantic/HTTP claim."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from qdrant_client import QdrantClient

from packages.knowledge.embeddings import HashEmbeddingProvider
from packages.knowledge.ingestion import IngestionPipeline
from packages.knowledge.models import DocumentCreate, KnowledgeScope, RetrievalRequest
from packages.knowledge.repository import KnowledgeRepository
from packages.knowledge.retrieval import RetrievalService
from packages.knowledge.vector_store import VectorStore

pytestmark = pytest.mark.filterwarnings("ignore:Local mode performs exact:UserWarning")


def source(**overrides):
    values = dict(
        title="Guide",
        source_type="manual",
        text="vacuum",
        workspace_id="ws-a",
        project_id="p-a",
        competitor="Vacuum X Pro",
        dimension="specs",
        market="CN",
    )
    values.update(overrides)
    return DocumentCreate(**values)


def store_at(path, provider):
    client = QdrantClient(path=str(path))
    store = VectorStore(client=client)
    store.configure_index(provider.model_version, provider.dimensions)
    return store, client


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "competitor,dimension",
    [
        ("Vacuum X Pro", "specs"),
        ("Straße Pro", "Größe"),
    ],
)
async def test_actual_local_search_filters_stronger_foreign_points_before_top_one(
    tmp_path,
    competitor,
    dimension,
):
    provider = HashEmbeddingProvider(dimensions=16)
    store, client = store_at(tmp_path / "qdrant", provider)
    try:
        async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
            pipeline = IngestionPipeline(repo, store)
            old = datetime.now(UTC) - timedelta(days=100)
            future = datetime.now(UTC) + timedelta(days=1)
            for values in [
                {"workspace_id": "ws-b"},
                {"project_id": "p-b"},
                {"project_id": None},
                {"workspace_id": None, "project_id": None},
                {"competitor": "Vacuum X"},
                {"dimension": "pricing"},
                {"market": "US"},
                {"source_type": "report"},
                {"source_published_at": old},
                {"last_verified_at": old, "competitor": competitor.upper()},
                {"source_published_at": future, "competitor": competitor.lower()},
                {"last_verified_at": future, "competitor": competitor.swapcase()},
            ]:
                await pipeline.ingest(
                    source(
                        **{
                            "competitor": competitor,
                            "dimension": dimension,
                            **values,
                        }
                    ),
                    embedding_provider=provider,
                )
            verified = (datetime.now(UTC) - timedelta(days=1)).astimezone(
                timezone(timedelta(hours=-12))
            )
            own = await pipeline.ingest(
                source(
                    text="vacuum battery runtime sixty minutes",
                    fetched_at=old,
                    source_published_at=old,
                    last_verified_at=verified,
                    competitor=competitor,
                    dimension=dimension,
                ),
                embedding_provider=provider,
            )
            vector = provider.embed_query("vacuum")
            assert (await store.search(vector, top_k=1))[0].document_id != own
            filters = dict(
                scope=KnowledgeScope(workspace_id="ws-a", project_id="p-a"),
                competitors=[competitor.upper()],
                dimensions=[dimension.upper()],
                market="CN",
                source_roles=["source"],
                max_age_days=7,
            )
            dense = await store.search(vector, top_k=1, **filters)
            sparse = await repo.search_chunks("vacuum", limit=1, **filters)
            documents = await repo.search_documents("vacuum", limit=1, **filters)
            assert [hit.document_id for hit in dense] == [own]
            assert [hit.document_id for hit in sparse] == [own]
            assert [document.id for document in documents] == [own]
            doc = await repo.get_document(own)
            assert dense[0].document_version == doc.version
            assert dense[0].content_hash == doc.content_hash
            assert dense[0].last_verified_at == verified
            assert dense[0].fetched_at == old
    finally:
        client.close()


@pytest.mark.asyncio
async def test_local_project_and_explicit_public_library_have_identical_scope(tmp_path):
    provider = HashEmbeddingProvider(dimensions=8)
    store, client = store_at(tmp_path / "qdrant", provider)
    try:
        async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
            pipeline = IngestionPipeline(repo, store)
            ids = {}
            for label, values in [
                ("own", {}),
                ("library", {"project_id": None}),
                ("peer", {"project_id": "p-b"}),
                ("foreign-library", {"workspace_id": "ws-b", "project_id": None}),
                ("unknown", {"workspace_id": None, "project_id": None}),
            ]:
                ids[label] = await pipeline.ingest(source(**values), embedding_provider=provider)
            for scope, allowed in [
                (KnowledgeScope(workspace_id="ws-a", project_id="p-a"), {ids["own"]}),
                (
                    KnowledgeScope(
                        workspace_id="ws-a", project_id="p-a", include_workspace_library=True
                    ),
                    {ids["own"], ids["library"]},
                ),
                (KnowledgeScope(workspace_id="ws-a"), {ids["library"]}),
            ]:
                vector_hits = await store.search(provider.embed_query("vacuum"), scope=scope)
                sql_hits = await repo.search_chunks("vacuum", scope=scope)
                assert {hit.document_id for hit in vector_hits} == allowed
                assert {hit.document_id for hit in sql_hits} == allowed
                assert all(
                    hit.project_id is None
                    for hit in vector_hits
                    if hit.document_id == ids["library"]
                )
    finally:
        client.close()


@pytest.mark.asyncio
async def test_local_vectors_reopen_and_delete_with_canonical_provenance(tmp_path):
    provider = HashEmbeddingProvider(dimensions=8)
    path = tmp_path / "qdrant"
    store, client = store_at(path, provider)
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        try:
            own = await IngestionPipeline(repo, store).ingest(source(), embedding_provider=provider)
        finally:
            client.close()
        reopened, new_client = store_at(path, provider)
        try:
            engine = RetrievalService(
                repo, reopened, embed_fn=provider.embed_documents, embedding_provider=provider
            )
            req = RetrievalRequest(
                query="vacuum",
                workspace_id="ws-a",
                project_id="p-a",
                mode="dense",
                enable_query_rewrite=False,
            )
            result = await engine.retrieve(req)
            assert [hit.document_id for hit in result.hits] == [own]
            assert result.hits[0].content_hash == (await repo.get_document(own)).content_hash
            assert result.hits[0].chunk_id == (await repo.get_chunks_for_document(own))[0].id
            await reopened.delete_by_document(own)
            assert await reopened.search(provider.embed_query("vacuum"), scope=req.scope) == []
        finally:
            new_client.close()


@pytest.mark.asyncio
async def test_cached_hybrid_local_response_invalidates_on_requested_index_version(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("KB_INDEX_VERSION", "v1")
    provider = HashEmbeddingProvider(dimensions=8)
    store, client = store_at(tmp_path / "qdrant", provider)
    try:
        async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
            own = await IngestionPipeline(repo, store).ingest(source(), embedding_provider=provider)
            engine = RetrievalService(
                repo, store, embed_fn=provider.embed_documents, embedding_provider=provider
            )
            req = RetrievalRequest(
                query="vacuum",
                workspace_id="ws-a",
                project_id="p-a",
                mode="hybrid",
                enable_query_rewrite=False,
            )
            first = await engine.retrieve(req)
            assert first.hits[0].document_id == own
            assert first.diagnostics["degraded"] is False
            monkeypatch.setenv("KB_INDEX_VERSION", "v2")
            second = await engine.retrieve(req)
            assert second.hits[0].document_id == own
            assert second.hits[0].score == 1.0
            assert second.diagnostics["effective_mode"] == "sparse"
            assert second.diagnostics["degraded"] is True
            assert "Index model changed" in second.diagnostics["reason"]
    finally:
        client.close()


@pytest.mark.asyncio
async def test_empty_and_missing_market_remain_distinct_in_actual_sql_and_vectors(tmp_path):
    provider = HashEmbeddingProvider(dimensions=8)
    store, client = store_at(tmp_path / "qdrant", provider)
    try:
        async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
            pipeline = IngestionPipeline(repo, store)
            missing = await pipeline.ingest(source(market=None), embedding_provider=provider)
            empty = await pipeline.ingest(source(market=""), embedding_provider=provider)
            assert missing != empty
            scope = KnowledgeScope(workspace_id="ws-a", project_id="p-a")
            hits = await store.search(provider.embed_query("vacuum"), scope=scope, market="")
            assert [hit.document_id for hit in hits] == [empty]
            assert hits[0].market == ""
            assert [
                hit.document_id
                for hit in (await repo.search_chunks("vacuum", scope=scope, market=""))
            ] == [empty]
            unrestricted = await store.search(provider.embed_query("vacuum"), scope=scope)
            assert {hit.document_id: hit.market for hit in unrestricted} == {
                missing: None,
                empty: "",
            }
            engine = RetrievalService(
                repo, store, embed_fn=provider.embed_documents, embedding_provider=provider
            )
            req = RetrievalRequest(
                query="vacuum",
                workspace_id="ws-a",
                project_id="p-a",
                market="",
                mode="dense",
                enable_query_rewrite=False,
            )
            assert [hit.document_id for hit in (await engine.retrieve(req)).hits] == [empty]
            assert [
                hit.document_id
                for hit in (await engine.retrieve(req.model_copy(update={"mode": "sparse"}))).hits
            ] == [empty]
            assert {
                hit.document_id
                for hit in (await engine.retrieve(req.model_copy(update={"market": None}))).hits
            } == {missing, empty}
    finally:
        client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("seed_old_degraded_cache", [False, True])
async def test_actual_reindex_recovery_rechecks_dense_after_degraded_response(
    tmp_path,
    seed_old_degraded_cache,
):
    provider = HashEmbeddingProvider(dimensions=8)
    store, client = store_at(tmp_path / "qdrant", provider)
    try:
        async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
            pipeline = IngestionPipeline(repo, store)
            own = await pipeline.ingest(source(), embedding_provider=provider)
            search_calls = []
            original = store.search

            async def search(*args, **kwargs):
                search_calls.append(kwargs)
                return await original(*args, **kwargs)

            store.search = search
            engine = RetrievalService(
                repo, store, embed_fn=provider.embed_documents, embedding_provider=provider
            )
            req = RetrievalRequest(
                query="vacuum",
                workspace_id="ws-a",
                project_id="p-a",
                mode="hybrid",
                enable_query_rewrite=False,
            )
            first = await engine.retrieve(req)
            assert first.hits[0].document_id == own
            assert first.diagnostics["degraded"] is False
            await repo.set_indexing_state(own, "failed", error="index failed")
            failed = await engine.retrieve(req)
            assert failed.hits[0].document_id == own
            assert failed.diagnostics["degraded"] is True
            assert len(search_calls) == 2
            if seed_old_degraded_cache:
                engine._retrieval_cache.set(
                    engine._response_cache_key(req), failed.model_copy(deep=True)
                )
            await pipeline.reindex_document(own, embedding_provider=provider)
            assert (await repo.get_document(own)).indexing_status == "ready"
            recovered = await engine.retrieve(req)
            assert len(search_calls) == 3
            assert recovered.hits[0].document_id == own
            assert "vector_index" in recovered.hits[0].metadata
            assert recovered.diagnostics["degraded"] is False
            assert recovered.diagnostics["effective_mode"] == "hybrid"
    finally:
        client.close()
