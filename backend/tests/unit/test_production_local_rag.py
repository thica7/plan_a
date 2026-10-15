"""Production wiring contract; tiny models replace CPU inference only in unit tests."""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import UTC, datetime

import pytest
from qdrant_client import QdrantClient
from test_collector_full_source_storage import capture_fixture
from test_collector_knowledge_scope import collect, service_and_detail

from packages.knowledge import local_models
from packages.knowledge.embeddings import get_embedding_provider_from_env
from packages.knowledge.ingestion import IngestionPipeline
from packages.knowledge.models import DocumentCreate, RetrievalRequest
from packages.knowledge.repository import KnowledgeRepository
from packages.knowledge.reranker import get_reranker_provider_from_env
from packages.knowledge.retrieval import RetrievalService
from packages.knowledge.vector_store import VectorStore
from packages.tools import ingest_document, rag_retrieve

E5_ID = "intfloat/multilingual-e5-small"
E5_REV = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
RERANK_ID = "BAAI/bge-reranker-v2-m3"
RERANK_REV = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
pytestmark = pytest.mark.filterwarnings("ignore:Local mode performs exact:UserWarning")


@pytest.fixture
def configured(monkeypatch, tmp_path):
    models = []
    for model_id, revision in ((E5_ID, E5_REV), (RERANK_ID, RERANK_REV)):
        directory = tmp_path / model_id.replace("/", "--") / revision
        directory.mkdir(parents=True)
        body = b"frozen-test-weight"
        (directory / "model.safetensors").write_bytes(body)
        models.append(
            dict(
                model_id=model_id,
                revision=revision,
                local_path=str(directory),
                files=[
                    dict(
                        file="model.safetensors",
                        bytes=len(body),
                        sha256=hashlib.sha256(body).hexdigest(),
                    )
                ],
            )
        )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(dict(models=models)))
    monkeypatch.setattr(local_models, "_MANIFEST_PATH", manifest, raising=False)
    monkeypatch.setenv("KB_EMBEDDING_PROVIDER", "local-e5")
    monkeypatch.setenv("KB_RERANKER_PROVIDER", "local-cross-encoder")
    monkeypatch.setenv("KB_RETRIEVAL_MODE", "hybrid")
    monkeypatch.setenv("KB_DB_PATH", str(tmp_path / "kb.db"))
    monkeypatch.delenv("KB_EMBEDDING_LOCAL_PATH", raising=False)
    monkeypatch.delenv("KB_LOCAL_MODEL_STRICT", raising=False)
    calls = {"embedding": [], "reranker": []}

    class Embedding:
        def encode(self, texts, **kwargs):
            calls["embedding"].append((texts, threading.get_ident()))
            return [[1.0] + [0.0] * 383 for _ in texts]

    class Reranker:
        def predict(self, pairs, **kwargs):
            calls["reranker"].append((pairs, threading.get_ident()))
            return [1.0] * len(pairs)

    monkeypatch.setattr(local_models, "_load_sentence_transformer", lambda *a, **k: Embedding())
    monkeypatch.setattr(local_models, "_load_cross_encoder", lambda *a, **k: Reranker())
    return calls, models


def test_env_factory_loads_frozen_local_models_and_reuses_provider(configured):
    embedding = get_embedding_provider_from_env()
    reranker = get_reranker_provider_from_env()
    assert embedding is get_embedding_provider_from_env()
    assert reranker is get_reranker_provider_from_env()
    assert embedding.model_version == f"{E5_ID}@{E5_REV}"
    assert embedding.dimensions == 384
    assert embedding.embed_query("中文能力") == [1.0] + [0.0] * 383
    assert reranker.rerank("中文能力", ["中文材料"])[0] > 0.5
    assert embedding.status()["effective_provider"] == "local-sentence-transformer"
    assert reranker.status()["effective_provider"] == "local-cross-encoder"


@pytest.mark.parametrize("mutation", ["missing", "revision", "tampered"])
def test_factory_failure_never_substitutes_hash(configured, monkeypatch, mutation):
    _, models = configured
    if mutation == "missing":
        monkeypatch.setenv("KB_EMBEDDING_LOCAL_PATH", "/missing/frozen/e5")
    elif mutation == "revision":
        monkeypatch.setenv("KB_EMBEDDING_REVISION", "unfrozen")
    else:
        from pathlib import Path

        (Path(models[0]["local_path"]) / "model.safetensors").write_bytes(b"tampered")
    provider = get_embedding_provider_from_env()
    assert provider.status()["degraded"] is True
    assert provider.status()["effective_provider"] == "unavailable"
    assert "hash" not in provider.model_version
    with pytest.raises(RuntimeError):
        provider.embed_query("中文")
    monkeypatch.setenv("KB_LOCAL_MODEL_STRICT", "1")
    with pytest.raises((ValueError, FileNotFoundError)):
        get_embedding_provider_from_env()


@pytest.mark.asyncio
async def test_ingest_and_query_use_distinct_e5_prefixes_off_event_loop(configured, monkeypatch):
    provider = get_embedding_provider_from_env()
    client = QdrantClient(":memory:")
    store = VectorStore(client=client)
    async with KnowledgeRepository() as repo:
        await IngestionPipeline(repo, store).ingest(
            DocumentCreate(
                title="中文材料",
                text="产品可导出工作记录。",
                source_type="official",
                workspace_id="ws",
                project_id="project",
                competitor="Product",
                dimension="feature",
            ),
            embedding_provider=provider,
        )
        response = await RetrievalService(
            repo, store, embed_fn=provider.embed_documents, embedding_provider=provider
        ).retrieve(
            RetrievalRequest(
                query="怎么保存记录",
                mode="hybrid",
                workspace_id="ws",
                project_id="project",
                competitors=["Product"],
                dimensions=["feature"],
                enable_query_rewrite=False,
            )
        )
    assert response.hits
    encoded = configured[0]["embedding"]
    assert encoded[0][0] == ["passage: 产品可导出工作记录。"]
    assert encoded[1][0] == ["query: 怎么保存记录"]
    assert all(tid != threading.get_ident() for _, tid in encoded)
    assert response.diagnostics["embedding"]["inference_calls"] == 2
    client.close()


@pytest.mark.asyncio
async def test_collector_full_summary_ingest_and_tool_share_local_hybrid_reranker(
    configured, monkeypatch
):
    client = QdrantClient(":memory:")
    # Each production call gets its own namespace adapter on the same client.
    monkeypatch.setattr(
        "packages.knowledge.vector_store.VectorStore", lambda: VectorStore(client=client)
    )
    rag_retrieve._get_embedding_provider.cache_clear()
    service, detail = service_and_detail()
    _, page, source, result = capture_fixture(service, detail)
    # Avoid a huge fake corpus; preserve actual collector capture admission/persistence.
    page.text = "Vacuum X Pro supports a sixty minute battery runtime and exports device records."
    from packages.orchestrator.service import RunRecord

    record = RunRecord(detail=detail)
    await service._persist_captured_sources_to_kb(record, detail, [source], result)
    async with KnowledgeRepository() as repo:
        full = await repo.get_document(source.metadata["kb_document_id"])
        assert full.indexing_status == "ready"
        assert full.embedding_model == f"{E5_ID}@{E5_REV}"
        assert full.metadata["source_material_level"] == "full_source"
        assert full.text == page.text
    hits = await collect(service, detail)
    assert hits
    assert configured[0]["reranker"]
    # Ranking diagnostics stay separate from the original body/normalized facts.
    assert hits[0].metadata["kb_retrieval"]["requested_mode"] == "hybrid"
    assert (
        hits[0].metadata["kb_retrieval"]["embedding"]["effective_provider"]
        == "local-sentence-transformer"
    )
    summary = source.model_copy(deep=True)
    summary.id = "summary-source"
    summary.url = "https://vacuum.example/summary"
    summary.metadata = {}
    summary.confidence = 0.9
    result = await service._sync_collected_sources_to_kb(record, detail, [summary])
    assert result["ingested"] == 1
    async with KnowledgeRepository() as repo:
        docs = await repo.search_documents("battery")
        summaries = [doc for doc in docs if doc.metadata.get("source_material_level") == "summary"]
        assert summaries and summaries[0].indexing_status == "ready"
    client.close()


@pytest.mark.asyncio
async def test_missing_model_preserves_canonical_body_and_exposes_sparse_fallback(
    configured, monkeypatch
):
    monkeypatch.setenv("KB_EMBEDDING_LOCAL_PATH", "/missing/frozen/e5")
    monkeypatch.setenv("KB_RERANKER_PROVIDER", "none")
    rag_retrieve._get_embedding_provider.cache_clear()
    reference = await ingest_document.ingest_document_reference(
        "https://example.test/source",
        "导出",
        "该产品支持工作记录导出和历史版本恢复。",
        "Product",
        "feature",
        "official",
        workspace_id="ws",
        project_id="project",
    )
    assert reference["indexing_status"] == "failed"
    assert reference["embedding"]["effective_provider"] == "unavailable"
    hits = await rag_retrieve.rag_retrieve_tool.ainvoke(
        dict(
            query="记录导出",
            competitors=["Product"],
            dimensions=["feature"],
            top_k=2,
            workspace_id="ws",
            project_id="project",
            mode="hybrid",
        )
    )
    assert hits
    assert hits[0]["metadata"]["retrieval"]["effective_mode"] == "sparse"
    assert hits[0]["metadata"]["retrieval"]["degraded"] is True


@pytest.mark.asyncio
async def test_empty_model_namespace_reports_sparse_until_reindex(configured):
    from packages.knowledge.embeddings import HashEmbeddingProvider

    client = QdrantClient(":memory:")
    provider = get_embedding_provider_from_env()
    async with KnowledgeRepository() as repo:
        old_store = VectorStore(client=client)
        document_id = await IngestionPipeline(repo, old_store).ingest(
            DocumentCreate(
                url="https://example.test/original",
                title="导出",
                text="产品支持记录导出。",
                source_type="official",
                workspace_id="ws",
                project_id="project",
                competitor="Product",
                dimension="feature",
                fetched_at=datetime(2026, 10, 1, tzinfo=UTC),
            ),
            embedding_provider=HashEmbeddingProvider(dimensions=384),
        )
        before = await repo.get_document(document_id)
        chunk_ids = [c.id for c in await repo.get_chunks_for_document(document_id)]
        store = VectorStore(client=client)
        service = RetrievalService(
            repo, store, embed_fn=provider.embed_documents, embedding_provider=provider
        )
        request = RetrievalRequest(
            query="记录导出",
            mode="hybrid",
            workspace_id="ws",
            project_id="project",
            enable_query_rewrite=False,
        )
        first = await service.retrieve(request)
        assert first.hits and "vector_index" not in first.hits[0].metadata
        assert first.diagnostics["effective_mode"] == "sparse"
        assert first.diagnostics["semantic_enabled"] is False
        assert "namespace" in first.diagnostics["reason"]
        await IngestionPipeline(repo, store).reindex_document(
            document_id, embedding_provider=provider
        )
        after = await repo.get_document(document_id)
        assert (after.id, after.version, after.content_hash, after.fetched_at) == (
            before.id,
            before.version,
            before.content_hash,
            before.fetched_at,
        )
        assert chunk_ids == [c.id for c in await repo.get_chunks_for_document(document_id)]
        response = await service.retrieve(request)
        assert response.diagnostics["degraded"] is False
        assert response.hits[0].metadata["vector_index"]["model_version"] == provider.model_version
        assert old_store.collection_name != store.collection_name
    client.close()


@pytest.mark.asyncio
async def test_missing_reranker_keeps_hybrid_ranking_and_reports_failure(configured, monkeypatch):
    monkeypatch.setenv("KB_RERANKER_LOCAL_PATH", "/missing/frozen/reranker")
    provider = get_embedding_provider_from_env()
    reranker = get_reranker_provider_from_env()
    client = QdrantClient(":memory:")
    store = VectorStore(client=client)
    async with KnowledgeRepository() as repo:
        await IngestionPipeline(repo, store).ingest(
            DocumentCreate(
                title="记录",
                text="产品支持导出工作记录。",
                source_type="official",
            ),
            embedding_provider=provider,
        )
        response = await RetrievalService(
            repo,
            store,
            embed_fn=provider.embed_documents,
            embedding_provider=provider,
            rerank_fn=reranker.rerank,
            reranker_provider=reranker,
        ).retrieve(
            RetrievalRequest(query="保存工作记录", mode="hybrid", enable_query_rewrite=False)
        )
        assert response.hits and response.hits[0].rerank_score is None
        assert response.diagnostics["effective_mode"] == "hybrid"
        assert response.diagnostics["reranker"]["effective_provider"] == "unavailable"
        assert response.diagnostics["degraded"] is True
        assert "Reranking unavailable" in response.diagnostics["reason"]
    client.close()


@pytest.mark.asyncio
async def test_explicit_local_qdrant_path_is_shared_and_persistent(tmp_path, monkeypatch):
    monkeypatch.setenv("KB_QDRANT_LOCAL_PATH", str(tmp_path / "qdrant"))
    from packages.knowledge.embeddings import HashEmbeddingProvider

    provider = HashEmbeddingProvider(dimensions=8)
    first, second = VectorStore(), VectorStore()
    first.configure_index(provider.model_version, 8)
    second.configure_index(provider.model_version, 8)
    await first.initialise()
    await second.initialise()
    assert first._client is second._client
    assert first.status()["backend"] == "qdrant-local"
    assert (tmp_path / "qdrant").is_dir()
    first._client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing", "loader"])
async def test_non_strict_local_dense_failure_uses_same_scoped_sparse_candidates(
    configured, monkeypatch, failure
):
    from datetime import timedelta

    if failure == "missing":
        monkeypatch.setenv("KB_EMBEDDING_LOCAL_PATH", "/missing/frozen/e5")
    else:

        def unavailable(*args, **kwargs):
            raise ImportError("local model cannot load")

        monkeypatch.setattr(local_models, "_load_sentence_transformer", unavailable)
    monkeypatch.setenv("KB_LOCAL_MODEL_STRICT", "0")
    monkeypatch.setenv("KB_RERANKER_PROVIDER", "none")
    rag_retrieve._get_embedding_provider.cache_clear()
    base = dict(
        title="Records",
        text="Product exports task history records as CSV files.",
        source_type="official",
        workspace_id="ws",
        project_id="project",
        market="CN",
        source_role="source",
        competitor="Product",
        dimension="feature",
    )
    async with KnowledgeRepository() as repo:
        for index, changes in enumerate(
            (
                {},
                {"workspace_id": "other"},
                {"project_id": "other"},
                {"market": "US"},
                {"source_role": "historical_report"},
                {"fetched_at": datetime.now(UTC) - timedelta(days=2)},
            )
        ):
            doc = base | changes | {"text": base["text"] + f" Observation {index}."}
            await IngestionPipeline(repo, object()).ingest(DocumentCreate(**doc))
    request = dict(
        query="exports task history records",
        competitors=["Product"],
        dimensions=["feature"],
        top_k=5,
        mode="dense",
        workspace_id="ws",
        project_id="project",
        market="CN",
        source_roles=["source"],
        max_age_days=1,
    )
    hits = await rag_retrieve.rag_retrieve_tool.ainvoke(request)
    assert len(hits) == 1
    assert hits[0]["workspace_id"] == "ws" and hits[0]["project_id"] == "project"
    assert hits[0]["market"] == "CN" and hits[0]["source_role"] == "source"
    diagnostics = hits[0]["metadata"]["retrieval"]
    assert diagnostics["requested_mode"] == "dense"
    assert diagnostics["effective_mode"] == "sparse"
    assert diagnostics["degraded"] is True
    assert diagnostics["semantic_enabled"] is False
    assert diagnostics["candidates"] == {"dense": 0, "sparse": 1, "reranked": 0}
    monkeypatch.setenv("KB_LOCAL_MODEL_STRICT", "1")
    rag_retrieve._get_embedding_provider.cache_clear()
    with pytest.raises((RuntimeError, FileNotFoundError)):
        await rag_retrieve.rag_retrieve_tool.ainvoke(request)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["hybrid", "sparse"])
async def test_summary_sync_exposes_actual_index_state_separately_from_saved_body(
    configured, monkeypatch, mode
):
    from packages.orchestrator.service import RunRecord

    monkeypatch.setenv("KB_RETRIEVAL_MODE", mode)
    monkeypatch.setenv("KB_EMBEDDING_LOCAL_PATH", "/missing/frozen/e5")
    service, detail = service_and_detail()
    _, _, source, _ = capture_fixture(service, detail)
    source.id = "summary-source"
    source.url = "https://vacuum.example/summary"
    source.metadata = {}
    source.confidence = 0.9
    record = RunRecord(detail=detail)
    result = await service._sync_collected_sources_to_kb(record, detail, [source])
    assert result["ingested"] == 1
    assert result["indexed"] == 0
    assert result["index_failed"] == int(mode == "hybrid")
    receipt = result["results"][0]
    assert receipt["source_id"] == source.id
    assert receipt["index_vectors_requested"] is (mode == "hybrid")
    assert receipt["indexing_status"] == ("failed" if mode == "hybrid" else "pending")
    if mode == "hybrid":
        assert "embedding:" in receipt["indexing_error"]
        assert receipt["embedding"]["degraded"] is True
        assert receipt["embedding"]["effective_provider"] == "unavailable"
    else:
        assert receipt["indexing_error"] is None
        assert receipt["embedding"] is None
    trace = record.detail.trace_spans[-1]
    assert json.loads(trace.full_output) == result
    assert trace.metadata["index_failed"] == result["index_failed"]
    async with KnowledgeRepository() as repo:
        stored = await repo.get_document(receipt["document_id"])
        assert stored.text == service._kb_text_from_raw_source(source)
        assert stored.metadata["source_material_level"] == "summary"
        assert stored.indexing_status == receipt["indexing_status"]
