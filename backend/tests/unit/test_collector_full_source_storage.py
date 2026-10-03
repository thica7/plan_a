from datetime import UTC, datetime, timedelta

import pytest
from test_collector_knowledge_scope import service_and_detail

from packages.agents import SubagentContext
from packages.knowledge.models import KnowledgeScope, RetrievalRequest
from packages.knowledge.repository import KnowledgeRepository
from packages.knowledge.retrieval import RetrievalService
from packages.orchestrator.service import RunRecord
from packages.research.evidence.admission import raw_source_from_capture
from packages.research.models import CapturedPage, ResearchResult, SourceCandidate
from packages.search import SearchResult


def capture_fixture(service, detail):
    brief = service._research_brief(detail, "Vacuum X Pro", "feature")
    candidate = SourceCandidate(
        title="Vacuum X Pro specs",
        url="https://vacuum.example/specs",
        origin="web_search",
        date="2026-01-01",
    )
    page = CapturedPage(
        candidate_id=candidate.id,
        requested_url=candidate.url,
        final_url=candidate.url,
        status="ok",
        title=candidate.title,
        text="Vacuum X Pro battery specifications. " * 1800 + "uniquetailmarker 123 minute runtime",
        content_hash="original-capture",
        fetch_method="browser_fetch",
        quality_score=0.8,
        captured_at=datetime.now(UTC) - timedelta(days=1),
        metadata={
            "workspace_id": "evil",
            "project_id": "evil",
            "kb_document_id": "forged",
            "fetched_at": datetime.now(UTC).isoformat(),
        },
    )
    source = raw_source_from_capture(
        brief,
        candidate,
        page,
        confidence=0.68,
        snippet="Vacuum X Pro offers sixty minute battery runtime.",
    )
    result = ResearchResult(brief=brief, candidates=[candidate], captured_pages=[page])
    return candidate, page, source, result


async def call_hook(monkeypatch, service, detail, source, result, hook):
    async def pipeline(*args, **kwargs):
        return result

    monkeypatch.setattr("packages.agents.collectors.logic.run_research_pipeline", pipeline)
    monkeypatch.setattr(
        service, "_raw_sources_from_research_result", lambda *args, **kwargs: [source]
    )
    record = RunRecord(detail=detail)
    context = SubagentContext(run_id=detail.id, agent="collector", subagent="feature::Vacuum X Pro")
    if hook == "main":
        sources = await service._collect_competitor_with_research_pipeline(
            record,
            detail,
            "feature",
            "Vacuum X Pro",
            context,
            batch_sources=[],
            target_source_count=1,
            include_official=False,
            enable_search=False,
        )
        assert sources == [source]
    else:
        obtained = await service._source_from_search_result(
            detail,
            "Vacuum X Pro",
            "feature",
            SearchResult(title=source.title, url=str(source.url), snippet="search summary"),
            record,
            context,
        )
        assert obtained is source
    return record


@pytest.mark.asyncio
@pytest.mark.parametrize("hook", ["main", "search"])
async def test_capture_body_tail_is_searchable_and_join_preserves_document(
    tmp_path, monkeypatch, hook
):
    monkeypatch.setenv("KB_DB_PATH", str(tmp_path / "kb.db"))
    service, detail = service_and_detail()
    _, page, source, result = capture_fixture(service, detail)
    original_id = source.id
    record = await call_hook(monkeypatch, service, detail, source, result, hook)
    assert source.metadata.get("kb_document_id") != "forged"
    assert source.metadata.get("kb_document_version") == 1
    assert source.content_hash == "original-capture"
    assert source.id == original_id
    assert source.confidence == 0.68
    assert "uniquetailmarker" not in source.model_dump_json()
    scope = KnowledgeScope(workspace_id=detail.workspace_id, project_id=detail.project_id)
    async with KnowledgeRepository() as repo:
        stored = await repo.get_document(source.metadata["kb_document_id"], scope=scope)
        assert stored.text == page.text
        assert stored.workspace_id == "ws-a"
        assert stored.market == "CN"
        assert stored.last_verified_at == page.captured_at
        assert stored.fetched_at == page.captured_at
        assert stored.source_published_at == datetime(2026, 1, 1, tzinfo=UTC)
        response = await RetrievalService(repo, object(), embed_fn=lambda texts: []).retrieve(
            RetrievalRequest(
                query="uniquetailmarker",
                workspace_id=detail.workspace_id,
                project_id=detail.project_id,
                market="CN",
                competitors=["Vacuum X Pro"],
                dimensions=["feature"],
                source_roles=["source"],
                max_age_days=30,
                mode="sparse",
                enable_query_rewrite=False,
            )
        )
        assert response.hits
        assert "uniquetailmarker" in response.hits[0].text
    summary = await service._sync_collected_sources_to_kb(record, detail, [source])
    assert summary["ingested"] == 0
    async with KnowledgeRepository() as repo:
        after = await repo.get_document(stored.id, scope=scope)
        assert after.is_active
        assert after.text == page.text
        assert after.version == stored.version


def test_admission_overwrites_untrusted_capture_references_and_drops_full_body():
    service, detail = service_and_detail()
    candidate, page, _, _ = capture_fixture(service, detail)
    page.metadata.update(full_text=page.text, text=page.text, markdown=page.text, html=page.text)
    source = raw_source_from_capture(
        service._research_brief(detail, "Vacuum X Pro", "feature"), candidate, page, confidence=0.68
    )
    assert source.metadata["captured_page_id"] == page.id
    assert source.metadata["fetched_at"] == page.captured_at.isoformat()
    assert "kb_document_id" not in source.metadata
    assert "uniquetailmarker" not in source.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_id",
        "wrong_url",
        "wrong_hash",
        "wrong_time",
        "unknown_hash",
        "failed",
        "demo",
        "ambiguous",
    ],
)
async def test_wrong_failed_and_demo_captures_never_become_full_documents(
    tmp_path, monkeypatch, mutation
):
    monkeypatch.setenv("KB_DB_PATH", str(tmp_path / "kb.db"))
    service, detail = service_and_detail()
    _, page, source, result = capture_fixture(service, detail)
    if mutation == "wrong_id":
        source.metadata["captured_page_id"] = "different-page"
    elif mutation == "wrong_url":
        page.final_url = "https://vacuum.example/different"
    elif mutation == "wrong_hash":
        page.content_hash = "different-hash"
    elif mutation == "wrong_time":
        page.captured_at -= timedelta(days=1)
    elif mutation == "unknown_hash":
        page.content_hash = ""
    elif mutation == "failed":
        page.status = "failed"
    elif mutation == "demo":
        source.source_type = "web_search_result"
    else:
        result.captured_pages.append(page.model_copy(deep=True))
    await call_hook(monkeypatch, service, detail, source, result, "main")
    assert not source.metadata.get("kb_document_version")
    async with KnowledgeRepository() as repo:
        docs = await repo.search_documents(
            "uniquetailmarker", scope=KnowledgeScope(workspace_id="ws-a", project_id="project-a")
        )
        assert docs == []


@pytest.mark.asyncio
async def test_failed_full_ingest_is_traced_and_join_does_not_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("KB_DB_PATH", str(tmp_path / "kb.db"))
    service, detail = service_and_detail()
    _, _, source, result = capture_fixture(service, detail)
    source.confidence = 0.9

    async def fail(**kwargs):
        raise OSError("sqlite write failed")

    monkeypatch.setattr(
        "packages.tools.ingest_document.ingest_document_reference", fail, raising=False
    )
    record = await call_hook(monkeypatch, service, detail, source, result, "main")
    assert not source.metadata.get("kb_document_version")
    assert any(
        "sqlite write failed" in (span.full_output or "") for span in record.detail.trace_spans
    )
    summary = await service._sync_collected_sources_to_kb(record, detail, [source])
    assert summary["attempted"] == 0
    assert summary["skipped"][0]["reason"] == "full_source_ingest_failed"


@pytest.mark.asyncio
async def test_legacy_summary_without_reference_does_not_archive_same_namespace_full_page(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("KB_DB_PATH", str(tmp_path / "kb.db"))
    service, detail = service_and_detail()
    _, page, source, result = capture_fixture(service, detail)
    record = await call_hook(monkeypatch, service, detail, source, result, "main")
    document_id = source.metadata["kb_document_id"]
    legacy = source.model_copy(deep=True)
    legacy.confidence = 0.9
    legacy.metadata = {}
    summary = await service._sync_collected_sources_to_kb(record, detail, [legacy])
    assert summary["ingested"] == 0
    assert summary["skipped"][0]["reason"] == "full_source_already_stored"
    async with KnowledgeRepository() as repo:
        stored = await repo.get_document(
            document_id, scope=KnowledgeScope(workspace_id="ws-a", project_id="project-a")
        )
        assert stored.is_active
        assert stored.text == page.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation", ["foreign_scope", "wrong_hash", "wrong_version", "nonexistent"]
)
async def test_forged_reference_cannot_skip_valid_summary_ingestion(
    tmp_path, monkeypatch, mutation
):
    monkeypatch.setenv("KB_DB_PATH", str(tmp_path / "kb.db"))
    service, detail = service_and_detail()
    _, _, source, _ = capture_fixture(service, detail)
    source.confidence = 0.9
    from packages.tools.ingest_document import ingest_document_reference

    reference = await ingest_document_reference(
        url=str(source.url),
        title=source.title,
        text="Older source material from a different acquisition.",
        competitor=source.competitor,
        dimension=source.dimension,
        source_type="manual",
        workspace_id="ws-a",
        project_id="project-b" if mutation == "foreign_scope" else "project-a",
        market="CN",
        metadata={"source_material_level": "full_source"},
        index_vectors=False,
    )
    source.metadata = dict(
        kb_document_id=reference["document_id"],
        kb_document_version=99 if mutation == "wrong_version" else reference["document_version"],
        kb_document_content_hash="forged"
        if mutation == "wrong_hash"
        else reference["content_hash"],
    )
    if mutation == "nonexistent":
        source.metadata["kb_document_id"] = "no-such-document"
        # The real older page is a summary, so it may be replaced by fresh summary material.
        async with KnowledgeRepository() as repo:
            await repo._connection.execute(
                "UPDATE documents SET metadata_json='{}' WHERE id=?", [reference["document_id"]]
            )
    elif mutation in {"wrong_hash", "wrong_version"}:
        async with KnowledgeRepository() as repo:
            await repo._connection.execute(
                "UPDATE documents SET metadata_json='{}' WHERE id=?", [reference["document_id"]]
            )
    summary = await service._sync_collected_sources_to_kb(
        RunRecord(detail=detail), detail, [source]
    )
    assert summary["ingested"] == 1
    async with KnowledgeRepository() as repo:
        own = await repo.list_documents(
            scope=KnowledgeScope(workspace_id="ws-a", project_id="project-a")
        )
        assert len(own) == 1
        assert own[0].metadata["source_material_level"] == "summary"
        assert source.snippet in own[0].text


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", ["kb_full_source_ingest_status", "kb_retrieved"])
async def test_untrusted_skip_flags_cannot_block_legacy_summary(tmp_path, monkeypatch, flag):
    monkeypatch.setenv("KB_DB_PATH", str(tmp_path / "kb.db"))
    service, detail = service_and_detail()
    _, _, source, _ = capture_fixture(service, detail)
    source.confidence = 0.9
    source.metadata = {flag: "failed" if flag == "kb_full_source_ingest_status" else True}
    summary = await service._sync_collected_sources_to_kb(
        RunRecord(detail=detail), detail, [source]
    )
    assert summary["ingested"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes,expected",
    [
        ({}, True),
        ({"project_id": "project-b"}, False),
        ({"workspace_id": "ws-b"}, False),
        ({"project_id": None}, False),
        ({"competitor": "Vacuum X"}, False),
        ({"dimension": "pricing"}, False),
        ({"market": "US"}, False),
        ({"market": None}, False),
        ({"source_role": "historical_report"}, False),
    ],
)
async def test_sql_full_source_guard_uses_exact_namespace(tmp_path, monkeypatch, changes, expected):
    from packages.tools.ingest_document import ingest_document_reference

    monkeypatch.setenv("KB_DB_PATH", str(tmp_path / "kb.db"))
    fields = dict(
        url="https://vacuum.example/specs/",
        title="Vacuum specs",
        text="Complete vacuum page",
        source_type="manual",
        competitor="Vacuum X Pro",
        dimension="feature",
        workspace_id="ws-a",
        project_id="project-a",
        market="CN",
        metadata={"source_material_level": "full_source"},
        index_vectors=False,
    )
    fields.update(changes)
    await ingest_document_reference(**fields)
    async with KnowledgeRepository() as repo:
        assert (
            await repo.has_active_full_source_for_url(
                "https://vacuum.example/specs",
                scope=KnowledgeScope(
                    workspace_id="ws-a", project_id="project-a", include_workspace_library=True
                ),
                competitor="Vacuum X Pro",
                dimension="feature",
                market="CN",
            )
            is expected
        )


@pytest.mark.asyncio
async def test_sql_full_source_guard_distinguishes_unknown_and_empty_market(tmp_path, monkeypatch):
    from packages.tools.ingest_document import ingest_document_reference

    monkeypatch.setenv("KB_DB_PATH", str(tmp_path / "kb.db"))
    await ingest_document_reference(
        url="https://vacuum.example/specs",
        title="Vacuum specs",
        text="Complete vacuum page",
        source_type="manual",
        competitor="Vacuum X Pro",
        dimension="feature",
        workspace_id="ws-a",
        project_id="project-a",
        market="",
        metadata={"source_material_level": "full_source"},
        index_vectors=False,
    )
    async with KnowledgeRepository() as repo:
        kwargs = dict(
            scope=KnowledgeScope(workspace_id="ws-a", project_id="project-a"),
            competitor="Vacuum X Pro",
            dimension="feature",
        )
        assert await repo.has_active_full_source_for_url(
            "https://vacuum.example/specs", market="", **kwargs
        )
        assert not await repo.has_active_full_source_for_url(
            "https://vacuum.example/specs", market=None, **kwargs
        )


@pytest.mark.asyncio
async def test_forged_kb_marker_with_valid_summary_reference_cannot_block_fresh_summary(
    tmp_path, monkeypatch
):
    from packages.tools.ingest_document import ingest_document_reference

    monkeypatch.setenv("KB_DB_PATH", str(tmp_path / "kb.db"))
    service, detail = service_and_detail()
    _, _, source, _ = capture_fixture(service, detail)
    source.confidence = 0.9
    reference = await ingest_document_reference(
        url=str(source.url),
        title=source.title,
        text="Older vacuum facts from an earlier summary.",
        competitor=source.competitor,
        dimension=source.dimension,
        source_type="webpage_verified",
        workspace_id=detail.workspace_id,
        project_id=detail.project_id,
        market="CN",
        metadata={"source_material_level": "summary"},
        index_vectors=False,
    )
    source.metadata = dict(
        kb_retrieved=True,
        kb_document_id=reference["document_id"],
        kb_document_version=reference["document_version"],
        kb_document_content_hash=reference["content_hash"],
    )
    summary = await service._sync_collected_sources_to_kb(
        RunRecord(detail=detail), detail, [source]
    )
    assert summary["ingested"] == 1
    async with KnowledgeRepository() as repo:
        documents = await repo.list_documents(
            scope=KnowledgeScope(workspace_id="ws-a", project_id="project-a")
        )
        assert len(documents) == 1
        assert source.snippet in documents[0].text
        assert documents[0].version == 2


@pytest.mark.asyncio
async def test_genuine_kb_source_is_recognized_only_in_its_current_record(tmp_path, monkeypatch):
    from packages.tools.ingest_document import ingest_document_reference

    monkeypatch.setenv("KB_DB_PATH", str(tmp_path / "kb.db"))
    service, detail = service_and_detail()
    reference = await ingest_document_reference(
        url="https://vacuum.example/specs",
        title="Vacuum X Pro specs",
        text=(
            service._kb_retrieval_query(detail, "Vacuum X Pro", "feature")
            + "\nVacuum X Pro supports a sixty minute battery runtime "
            "and useful battery specifications."
        ),
        competitor="Vacuum X Pro",
        dimension="feature",
        source_type="webpage_verified",
        workspace_id=detail.workspace_id,
        project_id=detail.project_id,
        market="CN",
        metadata={"source_material_level": "summary"},
        index_vectors=False,
    )
    record = RunRecord(detail=detail)
    sources = await service._collect_competitor_from_kb(
        record,
        detail,
        "feature",
        "Vacuum X Pro",
        SubagentContext(run_id=detail.id, agent="collector", subagent="feature::Vacuum X Pro"),
        target_source_count=1,
    )
    assert len(sources) == 1
    source = sources[0]
    source.metadata.pop("kb_retrieved")
    summary = await service._sync_collected_sources_to_kb(record, detail, [source])
    assert summary["skipped"][0]["reason"] == "already_from_kb"
    assert summary["ingested"] == 0
    source.metadata["kb_retrieved"] = True
    replayed = await service._sync_collected_sources_to_kb(
        RunRecord(detail=detail), detail, [source]
    )
    assert replayed["skipped"][0]["reason"] == "low_confidence"
    async with KnowledgeRepository() as repo:
        stored = await repo.get_document(reference["document_id"])
        assert stored.is_active
        assert stored.version == 1


@pytest.mark.asyncio
async def test_concurrent_collect_join_cannot_replace_full_source_after_summary_precheck(
    tmp_path, monkeypatch
):
    import asyncio

    from packages.tools import ingest_document

    monkeypatch.setenv("KB_DB_PATH", str(tmp_path / "kb.db"))
    service, detail = service_and_detail()
    full_detail = detail.model_copy(update={"id": "concurrent-full-run"}, deep=True)
    _, page, full_source, result = capture_fixture(service, full_detail)
    summary_source = full_source.model_copy(
        update={"id": "concurrent-summary-source", "confidence": 0.9, "metadata": {}}, deep=True
    )
    summary_record = RunRecord(detail=detail)
    full_record = RunRecord(detail=full_detail)
    summary_checked = asyncio.Event()
    continue_summary = asyncio.Event()

    class BorrowedRepository:
        def __init__(self, repository):
            self.repository = repository

        def __getattr__(self, name):
            return getattr(self.repository, name)

        async def close(self):
            # The outer context owns the two real SQLite connections.
            pass

    async with KnowledgeRepository() as summary_repo, KnowledgeRepository() as full_repo:
        borrowed = iter([BorrowedRepository(full_repo), BorrowedRepository(summary_repo)])
        monkeypatch.setattr(ingest_document, "KnowledgeRepository", lambda: next(borrowed))

        async def check_then_pause(checked_detail, source):
            found = await summary_repo.has_active_full_source_for_url(
                str(source.url),
                scope=KnowledgeScope(
                    workspace_id=checked_detail.workspace_id, project_id=checked_detail.project_id
                ),
                competitor=source.competitor,
                dimension=source.dimension,
                market="CN",
            )
            assert found is False
            summary_checked.set()
            await continue_summary.wait()
            return found

        monkeypatch.setattr(service, "_has_stored_full_source", check_then_pause)
        summary_task = asyncio.create_task(
            service._sync_collected_sources_to_kb(summary_record, detail, [summary_source])
        )
        try:
            await asyncio.wait_for(summary_checked.wait(), 3)
            await service._persist_captured_sources_to_kb(
                full_record, full_detail, [full_source], result
            )
        finally:
            continue_summary.set()
        await summary_task
        document = await summary_repo.get_document(full_source.metadata["kb_document_id"])
        assert document.is_active
        assert document.text == page.text
        assert document.content_hash == full_source.metadata["kb_document_content_hash"]
        assert document.version == 1
        response = await RetrievalService(summary_repo, object(), embed_fn=lambda _: []).retrieve(
            RetrievalRequest(
                query="uniquetailmarker",
                workspace_id=detail.workspace_id,
                project_id=detail.project_id,
                competitors=["Vacuum X Pro"],
                dimensions=["feature"],
                market="CN",
                source_roles=["source"],
                mode="sparse",
                enable_query_rewrite=False,
            )
        )
        assert response.hits
        assert "uniquetailmarker" in response.hits[0].text


@pytest.mark.asyncio
async def test_summary_returns_existing_full_without_building_chunks_or_touching_pending_index(
    tmp_path,
):
    import asyncio
    import hashlib

    from packages.knowledge.ingestion import IngestionPipeline
    from packages.knowledge.models import DocumentCreate

    inserted = asyncio.Event()
    continue_full = asyncio.Event()
    document_ids = []
    embedded_texts = []
    vector_calls = []

    class Vectors:
        async def upsert(self, ids, vectors, payloads):
            vector_calls.append(payloads)

    def embed(texts):
        embedded_texts.extend(texts)
        return [[1.0, 0.0] for _ in texts]

    full = DocumentCreate(
        url="https://vacuum.example/specs",
        title="Vacuum X Pro full specs",
        source_type="webpage_verified",
        text="Vacuum X Pro battery specs. " * 2000 + "pendingtailmarker",
        workspace_id="ws-a",
        project_id="project-a",
        competitor="Vacuum X Pro",
        dimension="feature",
        market="CN",
        metadata={"source_material_level": "full_source"},
    )
    summary = full.model_copy(
        update={
            "text": "Vacuum X Pro abbreviated battery summary.",
            "metadata": {"source_material_level": "summary"},
        }
    )
    db_path = str(tmp_path / "kb.db")
    async with (
        KnowledgeRepository(db_path) as full_repo,
        KnowledgeRepository(db_path) as summary_repo,
    ):
        original_upsert = full_repo.upsert_document

        async def pause_after_insert(doc, content_hash):
            stored = await original_upsert(doc, content_hash)
            document_ids.append(stored.id)
            inserted.set()
            await continue_full.wait()
            return stored

        full_repo.upsert_document = pause_after_insert
        full_task = asyncio.create_task(IngestionPipeline(full_repo, object()).ingest(full))
        try:
            await asyncio.wait_for(inserted.wait(), 3)
            initial = await summary_repo.get_document(document_ids[0])
            summary_id = await IngestionPipeline(summary_repo, Vectors()).ingest(
                summary, embed_fn=embed
            )
            current = await summary_repo.get_document(document_ids[0])
            assert summary_id == initial.id
            assert current.is_active
            assert current.text == full.text
            assert current.content_hash == hashlib.sha256(full.text.encode()).hexdigest()[:16]
            assert current.fetched_at == initial.fetched_at
            assert current.indexing_status == "pending"
            assert await summary_repo.get_chunks_for_document(initial.id) == []
            assert embedded_texts == []
            assert vector_calls == []
        finally:
            continue_full.set()
            await full_task
        chunks = await summary_repo.get_chunks_for_document(document_ids[0])
        assert chunks
        assert any("pendingtailmarker" in chunk.text for chunk in chunks)
        assert all(
            chunk.content_hash == hashlib.sha256(chunk.text.encode()).hexdigest()[:16]
            for chunk in chunks
        )


@pytest.mark.asyncio
async def test_same_body_full_source_promotes_summary_without_replacing_document(tmp_path):
    from packages.knowledge.ingestion import IngestionPipeline
    from packages.knowledge.models import DocumentCreate

    original_time = datetime(2026, 1, 1, tzinfo=UTC)
    summary = DocumentCreate(
        url="https://vacuum.example/specs",
        title="Original vacuum specs",
        source_type="webpage_search",
        text="Vacuum X Pro battery specifications. " * 80 + "promotiontailmarker",
        markdown="Original markdown",
        workspace_id="ws-a",
        project_id="project-a",
        competitor="Vacuum X Pro",
        dimension="feature",
        market="CN",
        fetched_at=original_time,
        source_published_at=original_time,
        source_updated_at=original_time,
        last_verified_at=original_time,
        metadata={"source_material_level": "summary", "authority": "original"},
    )
    full = summary.model_copy(
        update={
            "title": "New full capture title",
            "source_type": "webpage_verified",
            "markdown": "New full capture markdown",
            "fetched_at": original_time + timedelta(days=1),
            "source_published_at": original_time + timedelta(days=1),
            "source_updated_at": original_time + timedelta(days=1),
            "last_verified_at": original_time + timedelta(days=1),
            "metadata": {
                "source_material_level": "full_source",
                "authority": "incoming",
                "capture_reference": "incoming-only",
            },
        },
        deep=True,
    )
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        pipeline = IngestionPipeline(repo, object())
        document_id = await pipeline.ingest(summary, crawl_run_id="original-run")
        await repo.set_indexing_state(
            document_id, "ready", embedding_model="original-model",
            dimensions=2, index_version="original-index",
        )
        original = await repo.get_document(document_id)
        original_chunks = await repo.get_chunks_for_document(document_id)

        assert await pipeline.ingest(full, crawl_run_id="full-run") == document_id
        promoted = await repo.get_document(document_id)
        expected = original.model_copy(deep=True)
        expected.metadata["source_material_level"] = "full_source"
        assert promoted.metadata["source_material_level"] == "full_source"
        assert promoted == expected
        assert await repo.get_chunks_for_document(document_id) == original_chunks

        assert await pipeline.ingest(summary) == document_id
        later_summary = summary.model_copy(update={"text": "A later abbreviated summary."})
        assert await pipeline.ingest(later_summary) == document_id
        assert await repo.get_document(document_id) == expected
        assert await repo.get_chunks_for_document(document_id) == original_chunks
        assert [doc.id for doc in await repo.list_documents(scope=summary.scope)] == [document_id]


@pytest.mark.asyncio
async def test_concurrent_same_body_full_source_promotes_transaction_duplicate(
    tmp_path, monkeypatch
):
    import asyncio

    from packages.knowledge.ingestion import IngestionPipeline
    from packages.knowledge.models import DocumentCreate

    summary = DocumentCreate(
        url="https://vacuum.example/specs",
        title="Original vacuum specs",
        source_type="webpage_search",
        text="Vacuum X Pro battery specifications. " * 80 + "transactionpromotiontail",
        workspace_id="ws-a",
        project_id="project-a",
        competitor="Vacuum X Pro",
        dimension="feature",
        market="CN",
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        metadata={"source_material_level": "summary", "authority": "original"},
    )
    full = summary.model_copy(
        update={
            "title": "New full capture title",
            "fetched_at": datetime(2026, 1, 2, tzinfo=UTC),
            "metadata": {"source_material_level": "full_source", "authority": "incoming"},
        },
        deep=True,
    )
    full_checked = asyncio.Event()
    continue_full = asyncio.Event()
    db_path = str(tmp_path / "kb.db")
    async with (
        KnowledgeRepository(db_path) as summary_repo,
        KnowledgeRepository(db_path) as full_repo,
    ):
        original_lookup = full_repo.get_document_by_content_hash

        async def pause_after_hash_miss(*args, **kwargs):
            found = await original_lookup(*args, **kwargs)
            assert found is None
            full_checked.set()
            await continue_full.wait()
            return found

        monkeypatch.setattr(full_repo, "get_document_by_content_hash", pause_after_hash_miss)
        full_task = asyncio.create_task(
            IngestionPipeline(full_repo, object()).ingest(full, crawl_run_id="full-run")
        )
        try:
            await asyncio.wait_for(full_checked.wait(), 3)
            summary_pipeline = IngestionPipeline(summary_repo, object())
            document_id = await summary_pipeline.ingest(summary, crawl_run_id="original-run")
            await summary_repo.set_indexing_state(
                document_id, "ready", embedding_model="original-model",
                dimensions=2, index_version="original-index",
            )
            original = await summary_repo.get_document(document_id)
            original_chunks = await summary_repo.get_chunks_for_document(document_id)
        finally:
            continue_full.set()
        assert await full_task == document_id
        expected = original.model_copy(deep=True)
        expected.metadata["source_material_level"] = "full_source"
        promoted = await summary_repo.get_document(document_id)
        assert promoted.metadata["source_material_level"] == "full_source"
        assert promoted == expected
        assert await summary_repo.get_chunks_for_document(document_id) == original_chunks

        later_summary = summary.model_copy(update={"text": "A later abbreviated summary."})
        assert await summary_pipeline.ingest(later_summary) == document_id
        assert await summary_repo.get_document(document_id) == expected
        assert await summary_repo.get_chunks_for_document(document_id) == original_chunks
        assert [doc.id for doc in await summary_repo.list_documents(scope=summary.scope)] == [
            document_id
        ]
