from __future__ import annotations

import uuid

import pytest
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

from app.routes.knowledge import get_knowledge_provider_status, reindex_knowledge_document
from packages.auth import EnterpriseUserContext
from packages.knowledge.embeddings import HashEmbeddingProvider
from packages.knowledge.ingestion import IngestionPipeline
from packages.knowledge.models import DocumentCreate, RetrievalRequest
from packages.knowledge.repository import KnowledgeRepository
from packages.knowledge.reranker import BgeRerankerV2M3Provider
from packages.knowledge.retrieval import RetrievalService
from packages.knowledge.vector_store import VectorStore
from packages.rag.embedder import HashingRagEmbedder

pytestmark = pytest.mark.filterwarnings("ignore:Local mode performs exact:UserWarning")


@pytest.fixture(autouse=True)
def no_proxy(monkeypatch):
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        monkeypatch.delenv(name, raising=False)


def local_store(client=None):
    return VectorStore(client=client or QdrantClient(":memory:"))


@pytest.mark.asyncio
async def test_model_and_version_changes_use_independent_collections():
    client = QdrantClient(":memory:")
    first, second, third = [local_store(client) for _ in range(3)]
    first.configure_index("hash-v1", 2, index_version="v1")
    second.configure_index("semantic-v1", 2, index_version="v1")
    third.configure_index("hash-v1", 2, index_version="v2")
    assert len({first.collection_name, second.collection_name, third.collection_name}) == 3
    payload = {
        "document_id": "doc",
        "text": "pricing",
        "embedding_model": "hash-v1",
        "embedding_dimensions": 2,
        "index_version": "v1",
    }
    await first.upsert([str(uuid.uuid4())], [[1.0, 0.0]], [payload])
    assert len(await first.search([1.0, 0.0])) == 1
    assert await second.search([1.0, 0.0]) == []
    assert await third.search([1.0, 0.0]) == []


@pytest.mark.asyncio
async def test_document_cleanup_removes_all_model_versions():
    client = QdrantClient(":memory:")
    first, second = local_store(client), local_store(client)
    for store, model in ((first, "hash-v1"), (second, "semantic-v1")):
        store.configure_index(model, 2)
        payload = {
            "document_id": "doc",
            "text": "pricing",
            "embedding_model": model,
            "index_version": "v1",
        }
        await store.upsert([str(uuid.uuid4())], [[1.0, 0.0]], [payload])
    await first.delete_by_document("doc")
    assert await first.search([1.0, 0.0]) == []
    assert await second.search([1.0, 0.0]) == []


@pytest.mark.asyncio
async def test_upsert_rejects_wrong_model_dimension_and_batch_length():
    store = local_store()
    store.configure_index("hash-v1", 2)
    with pytest.raises(ValueError, match="batch"):
        await store.upsert([str(uuid.uuid4())], [], [])
    with pytest.raises(ValueError, match="dimension"):
        await store.upsert([str(uuid.uuid4())], [[1.0]], [{}])
    with pytest.raises(ValueError, match="model"):
        await store.upsert([str(uuid.uuid4())], [[1.0, 0.0]], [{"embedding_model": "semantic-v1"}])
    client = store._client
    client.create_collection(
        store.collection_name, vectors_config=VectorParams(size=3, distance=Distance.COSINE)
    )
    with pytest.raises(ValueError, match="dimension"):
        await store.initialise()


@pytest.mark.asyncio
async def test_hybrid_reports_sparse_fallback_and_provider_status(tmp_path):
    class Unavailable:
        async def search(self, *_args, **_kwargs):
            raise RuntimeError("Qdrant unavailable")

    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        provider = HashEmbeddingProvider(dimensions=8)
        await IngestionPipeline(repo, object()).ingest(
            DocumentCreate(
                title="Pricing",
                text="Enterprise pricing starts at ten dollars.",
                source_type="manual",
            )
        )
        response = await RetrievalService(
            repo, Unavailable(), embed_fn=provider.embed_documents, embedding_provider=provider
        ).retrieve(RetrievalRequest(query="pricing", enable_query_rewrite=False))
        assert response.hits
        assert response.diagnostics["effective_mode"] == "sparse"
        assert response.diagnostics["degraded"] is True
        assert "Qdrant unavailable" in response.diagnostics["reason"]
        assert response.diagnostics["embedding"]["effective_provider"] == "hash"
        assert response.hits[0].metadata["retrieval"]["effective_mode"] == "sparse"


def test_reranker_and_project_hashing_report_effective_provider():
    reranker = BgeRerankerV2M3Provider()
    reranker._load_error = RuntimeError("reranker unavailable")
    reranker.rerank("定价", ["企业定价"])
    assert reranker.status()["effective_provider"] == "hash"
    assert reranker.status()["degraded"] is True
    assert reranker.model_version == "hash-reranker-v1"
    assert HashingRagEmbedder().status()["effective_provider"] == "hash"


@pytest.mark.asyncio
async def test_reindex_api_returns_ready_document_and_provider_status(tmp_path, monkeypatch):
    import app.routes.knowledge as routes

    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        store = local_store()
        monkeypatch.setattr(routes, "_vector_store_for_ingest", lambda _provider: store)
        doc_id = await IngestionPipeline(repo, object()).ingest(
            DocumentCreate(title="Legacy", text="Legacy pricing guide", source_type="manual")
        )
        user = EnterpriseUserContext(
            user_id="owner", role="owner", workspace_id="default-workspace"
        )
        provider = HashEmbeddingProvider(dimensions=8)
        doc = await reindex_knowledge_document(doc_id, repo, provider, user)
        assert doc.indexing_status == "ready"
        status = await get_knowledge_provider_status(provider, None, user)
        assert status["embedding"]["effective_provider"] == "hash"
        assert status["embedding"]["dimensions"] == 8
