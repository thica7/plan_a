from datetime import UTC, datetime, timedelta

import pytest
from test_collector_full_source_storage import capture_fixture
from test_collector_knowledge_scope import good_hit, service_and_detail

from packages.orchestrator.service import RunRecord
from packages.research.evidence.admission import raw_source_from_capture
from packages.tools.ingest_document import ingest_document_reference


@pytest.mark.asyncio
@pytest.mark.parametrize("project_id", ["project-a", None])
async def test_small_reference_carries_stored_scope(tmp_path, monkeypatch, project_id):
    monkeypatch.setenv("KB_DB_PATH", str(tmp_path / "kb.db"))
    reference = await ingest_document_reference(
        url="https://vacuum.example/specs", title="Vacuum", text="battery facts",
        competitor="Vacuum X Pro", dimension="feature", source_type="manual",
        workspace_id="ws-a", project_id=project_id, index_vectors=False,
        metadata={"workspace_id": "evil", "project_id": "evil"},
    )
    assert reference["workspace_id"] == "ws-a"
    assert reference["project_id"] == project_id
    assert "text" not in reference


@pytest.mark.parametrize("project_id", ["project-a", None])
def test_kb_reference_uses_typed_scope_and_dates_for_qa(project_id):
    service, detail = service_and_detail()
    fetched = datetime.now(UTC) - timedelta(days=3)
    hit = good_hit(
        project_id=project_id, fetched_at=fetched.isoformat(),
        last_verified_at=None, source_published_at=None,
        metadata={"workspace_id": "evil", "project_id": "evil",
                  "last_verified_at": "2099-01-01T00:00:00Z",
                  "source_published_at": "2099-01-02", "source_updated_at": "2099-01-03"},
    )
    source = service._raw_source_from_kb_hit(
        detail, "Vacuum X Pro", "feature", hit, rank=1, query="battery"
    )
    assert service._source_observed_at(source) == fetched.replace(tzinfo=None)
    assert source.metadata["kb_document_workspace_id"] == "ws-a"
    assert source.metadata["kb_document_project_id"] == project_id
    audit = service._source_audit_trail_item(source)
    assert audit["kb_document_workspace_id"] == "ws-a"
    assert audit.get("kb_document_project_id") == project_id
    assert "kb_document_project_id" in audit
    live = source.model_copy(
        update={"id": "live", "candidate_origin": "web_search", "metadata": {}}
    )
    pair = service._source_conflict_pairs(
        {"supported": [source.id], "unsupported": [live.id]},
        {source.id: source, live.id: live}, claim_area="battery",
    )[0]
    assert pair["kb_document_workspace_id"] == "ws-a"
    assert pair.get("kb_document_project_id") == project_id
    assert "kb_document_project_id" in pair


@pytest.mark.parametrize("cached", [False, True])
def test_successful_capture_verifies_at_original_capture_even_with_old_publication(cached):
    service, detail = service_and_detail()
    candidate, page, _, _ = capture_fixture(service, detail)
    page.captured_at = datetime.now(UTC) - timedelta(days=90 if cached else 1)
    page.metadata.update(last_verified_at="2099-01-01T00:00:00Z", cache_hit=cached)
    source = raw_source_from_capture(
        service._research_brief(detail, "Vacuum X Pro", "feature"), candidate, page, confidence=0.7
    )
    assert source.metadata["last_verified_at"] == page.captured_at.isoformat()
    assert service._source_observed_at(source) == page.captured_at.replace(tzinfo=None)


@pytest.mark.parametrize("changes", [{"status": "failed"}, {"failure_reason": "invalid page"}])
def test_failed_capture_does_not_claim_page_supplied_verification(changes):
    service, detail = service_and_detail()
    candidate, page, _, _ = capture_fixture(service, detail)
    page = page.model_copy(update={**changes, "metadata": {"last_verified_at": "2099-01-01"}})
    source = raw_source_from_capture(
        service._research_brief(detail, "Vacuum X Pro", "feature"), candidate, page, confidence=0.7
    )
    assert "last_verified_at" not in source.metadata


@pytest.mark.asyncio
async def test_capture_verification_survives_storage_failure(monkeypatch):
    service, detail = service_and_detail()
    _, page, source, result = capture_fixture(service, detail)

    async def fail(**kwargs):
        raise RuntimeError("isolated storage failure")

    monkeypatch.setattr("packages.tools.ingest_document.ingest_document_reference", fail)
    await service._persist_captured_sources_to_kb(
        RunRecord(detail=detail), detail, [source], result
    )
    assert source.metadata["kb_full_source_ingest_status"] == "failed"
    assert source.metadata["last_verified_at"] == page.captured_at.isoformat()


@pytest.mark.asyncio
async def test_capture_reference_scope_comes_from_stored_reference(tmp_path, monkeypatch):
    monkeypatch.setenv("KB_DB_PATH", str(tmp_path / "kb.db"))
    service, detail = service_and_detail()
    _, _, source, result = capture_fixture(service, detail)
    await service._persist_captured_sources_to_kb(
        RunRecord(detail=detail), detail, [source], result
    )
    assert source.metadata["kb_document_workspace_id"] == "ws-a"
    assert source.metadata["kb_document_project_id"] == "project-a"


@pytest.mark.asyncio
@pytest.mark.parametrize("dimension", ["pricing", "version", "价格", "定价", "版本"])
async def test_dated_price_or_version_is_not_refreshed_by_capture(tmp_path, monkeypatch, dimension):
    from packages.knowledge.models import KnowledgeScope, RetrievalRequest
    from packages.knowledge.repository import KnowledgeRepository
    from packages.knowledge.retrieval import RetrievalService

    monkeypatch.setenv("KB_DB_PATH", str(tmp_path / "kb.db"))
    service, detail = service_and_detail(dimension)
    candidate, page, _, result = capture_fixture(service, detail)
    candidate.date = "2020-01-01"
    brief = service._research_brief(detail, "Vacuum X Pro", dimension)
    source = raw_source_from_capture(brief, candidate, page, confidence=0.7)
    assert source.metadata["capture_verified_at"] == page.captured_at.isoformat()
    assert "last_verified_at" not in source.metadata
    assert service._source_observed_at(source) == datetime(2020, 1, 1)
    await service._persist_captured_sources_to_kb(
        RunRecord(detail=detail), detail, [source], result
    )
    async with KnowledgeRepository() as repo:
        scope = KnowledgeScope(workspace_id=detail.workspace_id, project_id=detail.project_id)
        stored = await repo.get_document(source.metadata["kb_document_id"], scope=scope)
        assert stored.last_verified_at is None
        assert stored.source_published_at == datetime(2020, 1, 1, tzinfo=UTC)
        assert stored.fetched_at == page.captured_at
        hits = await RetrievalService(repo, object(), embed_fn=lambda _: []).retrieve(
            RetrievalRequest(
                query="battery", workspace_id=detail.workspace_id, project_id=detail.project_id,
                mode="sparse", max_age_days=7, enable_query_rewrite=False,
            )
        )
        assert hits.hits == []


@pytest.mark.asyncio
@pytest.mark.parametrize("dimension", ["pricing", "版本", "feature"])
async def test_crawl_dated_price_respects_fact_date_but_feature_verifies_capture(
    tmp_path, monkeypatch, dimension
):
    from app.routes import knowledge
    from packages.crawler.models import CrawlRequest, CrawlResult, ParsedPage
    from packages.knowledge.models import KnowledgeScope
    from packages.knowledge.repository import KnowledgeRepository

    fetched = datetime.now(UTC)
    published = datetime(2020, 1, 1, tzinfo=UTC)
    result = CrawlResult(
        request=CrawlRequest(url="https://vacuum.example/specs", dimension=dimension),
        success=True,
        page=ParsedPage(url="https://vacuum.example/specs", title="facts", text="battery facts",
                      content_hash="capture", fetched_at=fetched),
    )
    monkeypatch.setenv("KB_INGEST_ON_CRAWL", "1")
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        scope = KnowledgeScope(workspace_id="ws", project_id="project")
        reference = await knowledge.ingest_crawl_result(
            repo, result, scope=scope, source_published_at=published
        )
        document = await repo.get_document(reference["document_id"], scope=scope)
        assert document.last_verified_at == (fetched if dimension == "feature" else None)
        assert document.source_published_at == published


@pytest.mark.asyncio
async def test_updated_only_old_price_keeps_typed_date_across_capture_kb_and_qa(
    tmp_path, monkeypatch
):
    from packages.knowledge.models import KnowledgeScope, RetrievalRequest
    from packages.knowledge.repository import KnowledgeRepository
    from packages.knowledge.retrieval import RetrievalService

    monkeypatch.setenv("KB_DB_PATH", str(tmp_path / "kb.db"))
    service, detail = service_and_detail("pricing")
    candidate, page, _, result = capture_fixture(service, detail)
    candidate.date = None
    candidate.last_updated = "2020-02-01"
    source = raw_source_from_capture(
        service._research_brief(detail, "Vacuum X Pro", "pricing"), candidate, page, confidence=0.7
    )
    assert "last_verified_at" not in source.metadata
    await service._persist_captured_sources_to_kb(
        RunRecord(detail=detail), detail, [source], result
    )
    async with KnowledgeRepository() as repo:
        scope = KnowledgeScope(workspace_id=detail.workspace_id, project_id=detail.project_id)
        doc = await repo.get_document(source.metadata["kb_document_id"], scope=scope)
        assert doc.source_updated_at == datetime(2020, 2, 1, tzinfo=UTC)
        assert doc.source_published_at is None
        retrieval = RetrievalService(repo, object(), embed_fn=lambda _: [])
        request = RetrievalRequest(
            query="battery", workspace_id=detail.workspace_id, project_id=detail.project_id,
            mode="sparse", enable_query_rewrite=False,
        )
        hits = (await retrieval.retrieve(request)).hits
        assert hits and hits[0].source_updated_at == doc.source_updated_at
        hit = hits[0].model_dump(mode="json")
        hit["metadata"].update(source_updated_at="2099-01-01", last_verified_at="2099-01-01")
        reused = service._raw_source_from_kb_hit(
            detail, "Vacuum X Pro", "pricing", hit, rank=1, query="battery"
        )
        assert service._source_observed_at(reused) == datetime(2020, 2, 1)
        assert (await retrieval.retrieve(request.model_copy(update={"max_age_days": 7}))).hits == []


@pytest.mark.asyncio
async def test_updated_date_payload_precedence_and_duplicate_keep_original_time(tmp_path):
    from packages.knowledge.ingestion import IngestionPipeline
    from packages.knowledge.models import DocumentCreate, RetrievalRequest
    from packages.knowledge.repository import KnowledgeRepository
    from packages.knowledge.retrieval import RetrievalService, _filter_hits_by_request

    payloads = []

    class Vectors:
        async def upsert(self, ids, vectors, values):
            payloads.extend(values)

    old = datetime(2020, 2, 1, tzinfo=UTC)
    recent = datetime.now(UTC) - timedelta(days=1)
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        doc = DocumentCreate(
            title="price", text="battery price facts", source_type="manual",
            workspace_id="ws", source_updated_at=old, source_published_at=recent,
        )
        pipeline = IngestionPipeline(repo, Vectors())
        doc_id = await pipeline.ingest(doc, embed_fn=lambda texts: [[1.0, 0.0] for _ in texts])
        assert payloads[0]["source_updated_at"] == old.isoformat()
        assert payloads[0]["observed_at"] == old.isoformat()
        duplicate = doc.model_copy(update={"source_updated_at": recent})
        assert await pipeline.ingest(duplicate) == doc_id
        stored = await repo.get_document(doc_id)
        assert stored.source_updated_at == old
        hits = (await RetrievalService(repo, object(), embed_fn=lambda _: []).retrieve(
            RetrievalRequest(query="battery", workspace_id="ws", mode="sparse",
                             enable_query_rewrite=False)
        )).hits
        assert _filter_hits_by_request(
            hits, RetrievalRequest(query="battery", workspace_id="ws", max_age_days=7)
        ) == []


@pytest.mark.asyncio
async def test_updated_date_migration_does_not_trust_legacy_generic_metadata(tmp_path):
    import aiosqlite

    from packages.knowledge.models import DocumentCreate
    from packages.knowledge.repository import KnowledgeRepository

    path = str(tmp_path / "kb.db")
    async with KnowledgeRepository(path) as repo:
        doc = await repo.upsert_document(
            DocumentCreate(title="legacy", text="facts", source_type="manual",
                           metadata={"source_updated_at": "2099-01-01"}), "legacy-hash"
        )
        assert doc.source_updated_at is None
    async with aiosqlite.connect(path) as db:
        await db.execute("ALTER TABLE documents DROP COLUMN source_updated_at")
        await db.execute("DELETE FROM _schema_version WHERE id = 14")
        await db.commit()
    async with KnowledgeRepository(path) as repo:
        stored = await repo.get_document(doc.id)
        assert stored.source_updated_at is None
        async with repo._connection.execute("SELECT id FROM _schema_version WHERE id = 14") as cur:
            assert await cur.fetchone()


@pytest.mark.parametrize("field,candidate_field", [
    ("source_published_at", "date"), ("source_updated_at", "last_updated"),
])
def test_capture_dates_from_candidate_override_generic_metadata(field, candidate_field):
    service, detail = service_and_detail()
    candidate, page, _, _ = capture_fixture(service, detail)
    setattr(candidate, candidate_field, "2020-02-01")
    page = page.model_copy(update={field: "2021-01-01"})
    page.metadata[field] = "2099-01-01"
    brief = service._research_brief(detail, "Vacuum X Pro", "pricing")
    source = raw_source_from_capture(
        brief, candidate, page, confidence=0.7, metadata={field: "2099-01-02"}
    )
    assert source.metadata[field] == "2020-02-01"


@pytest.mark.parametrize("field", ["source_published_at", "source_updated_at"])
def test_capture_generic_dates_do_not_supply_missing_typed_dates(field):
    service, detail = service_and_detail()
    candidate, page, _, _ = capture_fixture(service, detail)
    candidate.date = None
    candidate.last_updated = None
    page.metadata[field] = "2099-01-01"
    source = raw_source_from_capture(
        service._research_brief(detail, "Vacuum X Pro", "pricing"),
        candidate, page, confidence=0.7, metadata={field: "2099-01-02"},
    )
    assert field not in source.metadata


@pytest.mark.asyncio
@pytest.mark.parametrize("dates,observed", [
    ({"source_published_at": "2020-01-01"}, datetime(2020, 1, 1)),
    ({"source_updated_at": "2020-02-01"}, datetime(2020, 2, 1)),
    ({"source_published_at": "2020-01-01", "source_updated_at": "2020-02-01"},
     datetime(2020, 2, 1)),
])
async def test_fetch_typed_dates_survive_capture_storage_and_qa(
    tmp_path, monkeypatch, dates, observed
):
    from packages.knowledge.models import KnowledgeScope, RetrievalRequest
    from packages.knowledge.repository import KnowledgeRepository
    from packages.knowledge.retrieval import RetrievalService
    from packages.research.capture.webfetch_adapter import fetch_candidate_page
    from packages.tools.evidence_fetch import EvidenceFetchResult

    monkeypatch.setenv("KB_DB_PATH", str(tmp_path / "kb.db"))
    service, detail = service_and_detail("pricing")
    candidate, original, _, result = capture_fixture(service, detail)
    candidate.date = None
    candidate.last_updated = None

    async def fetch(url):
        return EvidenceFetchResult(
            url=url, ok=True, title=original.title, text=original.text,
            content_hash=original.content_hash, quality_score=0.9,
            capture_metadata={"source_published_at": "2099-01-01",
                              "source_updated_at": "2099-02-01"}, **dates,
        )

    page = await fetch_candidate_page(candidate, fetch)
    result.captured_pages = [page]
    for field in ("source_published_at", "source_updated_at"):
        assert getattr(page, field) == dates.get(field)
    source = raw_source_from_capture(
        service._research_brief(detail, "Vacuum X Pro", "pricing"),
        candidate, page, confidence=0.7,
        metadata={"source_published_at": "2099-03-01", "source_updated_at": "2099-04-01"},
    )
    assert "last_verified_at" not in source.metadata
    assert service._source_observed_at(source) == observed
    await service._persist_captured_sources_to_kb(
        RunRecord(detail=detail), detail, [source], result
    )
    async with KnowledgeRepository() as repo:
        doc = await repo.get_document(
            source.metadata["kb_document_id"],
            scope=KnowledgeScope(workspace_id=detail.workspace_id, project_id=detail.project_id),
        )
        for field in ("source_published_at", "source_updated_at"):
            expected = (
                datetime.fromisoformat(dates[field]).replace(tzinfo=UTC)
                if field in dates else None
            )
            assert getattr(doc, field) == expected
        assert doc.last_verified_at is None
        retrieval = RetrievalService(repo, object(), embed_fn=lambda _: [])
        request = RetrievalRequest(
            query="battery", workspace_id=detail.workspace_id, project_id=detail.project_id,
            mode="sparse", enable_query_rewrite=False,
        )
        hits = (await retrieval.retrieve(request)).hits
        assert hits
        reused = service._raw_source_from_kb_hit(
            detail, "Vacuum X Pro", "pricing", hits[0].model_dump(mode="json"),
            rank=1, query="battery",
        )
        assert service._source_observed_at(reused) == observed
        assert (await retrieval.retrieve(request.model_copy(update={"max_age_days": 7}))).hits == []


@pytest.mark.asyncio
async def test_real_local_vector_updated_date_survives_and_filters_before_limit(tmp_path):
    from qdrant_client import QdrantClient

    from packages.knowledge.embeddings import HashEmbeddingProvider
    from packages.knowledge.ingestion import IngestionPipeline
    from packages.knowledge.models import DocumentCreate, KnowledgeScope
    from packages.knowledge.repository import KnowledgeRepository
    from packages.knowledge.vector_store import VectorStore

    provider = HashEmbeddingProvider(dimensions=8)
    client = QdrantClient(path=str(tmp_path / "qdrant"))
    store = VectorStore(client=client)
    store.configure_index(provider.model_version, provider.dimensions)
    def source(**dates):
        return DocumentCreate(title="facts", source_type="manual", workspace_id="ws-a",
                              project_id="p-a", **{"text": "vacuum", **dates})
    old = datetime(2020, 1, 1, tzinfo=UTC)
    recent = datetime.now(UTC) - timedelta(days=1)
    try:
        async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
            pipeline = IngestionPipeline(repo, store)
            await pipeline.ingest(
                source(source_updated_at=old), embedding_provider=provider
            )
            current_id = await pipeline.ingest(
                source(text="vacuum current", source_updated_at=recent, source_published_at=old),
                embedding_provider=provider,
            )
            hits = await store.search(
                provider.embed_query("vacuum"),
                scope=KnowledgeScope(workspace_id="ws-a", project_id="p-a"),
                max_age_days=7, top_k=1,
            )
            assert [hit.document_id for hit in hits] == [current_id]
            assert hits[0].source_updated_at == recent
            assert hits[0].source_published_at == old
    finally:
        client.close()
