"""Storage namespace isolation and typed source context contracts."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from pydantic import ValidationError

from packages.knowledge import models
from packages.knowledge.ingestion import IngestionPipeline
from packages.knowledge.models import DocumentCreate, RetrievalHit, RetrievalRequest
from packages.knowledge.repository import _BASE_SCHEMA, KnowledgeRepository


@pytest_asyncio.fixture
async def repo(tmp_path):
    repository = KnowledgeRepository(str(tmp_path / "knowledge.db"))
    await repository.initialise()
    try:
        yield repository
    finally:
        await repository.close()


def _scope(workspace_id="workspace-a", project_id="project-a"):
    return models.KnowledgeScope(workspace_id=workspace_id, project_id=project_id)


def _doc(**overrides):
    values = {
        "url": "https://example.com/specs",
        "title": "Vacuum specs",
        "source_type": "webpage_verified",
        "workspace_id": "workspace-a",
        "project_id": "project-a",
        "competitor": "Vacuum X Pro",
        "dimension": "specs",
        "market": "CN",
        "text": "vacuum battery runtime is sixty minutes",
    }
    values.update(overrides)
    return DocumentCreate(**values)


async def _ingest(repo, **values):
    return await IngestionPipeline(repo, object()).ingest(_doc(**values))


@pytest.mark.asyncio
@pytest.mark.parametrize("other", [{"workspace_id": "workspace-b"}, {"project_id": "project-b"}])
async def test_same_body_and_url_remain_independent_across_scopes(repo, other):
    first = await _ingest(repo)
    second = await _ingest(repo, **other)
    assert second != first
    assert (await repo.get_document(first)).is_active
    assert (await repo.get_document(second)).is_active


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "other",
    [
        {"competitor": "Vacuum X"},
        {"dimension": "battery"},
        {"market": "US"},
        {"source_role": "historical_report"},
    ],
)
async def test_same_scope_body_and_url_are_namespaced_by_exact_source_identity(repo, other):
    first = await _ingest(repo)
    second = await _ingest(repo, **other)
    assert first != second
    assert (await repo.get_document(first)).is_active
    assert (await repo.get_document(second)).version == 1


def test_scope_and_source_models_preserve_typed_contract():
    scope = _scope(project_id=None)
    assert scope.project_id is None
    with pytest.raises(ValidationError):
        _scope(workspace_id="   ")
    report = _doc(source_type="report", source_role="source")
    assert report.source_role == "historical_report"
    assert report.scope == _scope()
    request = RetrievalRequest(
        query="vacuum",
        workspace_id="workspace-a",
        project_id=None,
        market="CN",
        source_roles=["source"],
        max_age_days=30,
    )
    assert request.scope == scope
    assert request.source_roles == ["source"]
    assert request.max_age_days == 30
    hit = RetrievalHit(
        chunk_id="c",
        document_id="d",
        text="report",
        score=1,
        workspace_id="workspace-a",
        source_type="report",
    )
    assert hit.source_role == "historical_report"


@pytest.mark.asyncio
async def test_scoped_reads_hide_legacy_and_other_projects_including_public_library(repo):
    legacy = await _ingest(
        repo, workspace_id=None, project_id=None, url="https://example.com/legacy"
    )
    own = await _ingest(repo, text="vacuum project battery", url="https://example.com/own")
    other = await _ingest(
        repo, project_id="project-b", text="vacuum other battery", url="https://example.com/other"
    )
    public = await _ingest(
        repo, project_id=None, text="vacuum public battery", url="https://example.com/public"
    )
    scope = _scope()
    assert await repo.get_document(other, scope=scope) is None
    assert await repo.get_document(legacy, scope=scope) is None
    assert [doc.id for doc in await repo.list_documents(scope=scope)] == [own]
    assert await repo.count_documents(scope=scope) == 1
    assert [doc.id for doc in await repo.list_documents_for_evidence_sync(scope=scope)] == [own]
    assert {doc.id for doc in await repo.search_documents("vacuum", scope=scope)} == {own}
    assert {hit.document_id for hit in await repo.search_chunks("vacuum", scope=scope)} == {own}
    assert [doc.id for doc in await repo.list_documents(scope=_scope(project_id=None))] == [public]
    assert len(await repo.list_documents()) == 4
    assert (await repo.knowledge_stats(scope=scope))["doc_count"] == 1
    assert (await repo.knowledge_stats(scope=scope))["chunk_count"] == 1
    assert (await repo.knowledge_stats(scope=scope))["fts_size"] == 2


@pytest.mark.asyncio
async def test_namespace_hash_lookup_and_legacy_dedup_remain_compatible(repo):
    scoped = await _ingest(repo)
    legacy = await _ingest(
        repo,
        workspace_id=None,
        project_id=None,
        competitor="Other",
        url="https://example.com/legacy",
    )
    legacy_again = await _ingest(
        repo,
        workspace_id=None,
        project_id=None,
        competitor="Another",
        market="US",
        url="https://example.com/another",
    )
    content_hash = hashlib.sha256(_doc().text.encode()).hexdigest()[:16]
    assert legacy_again == legacy
    assert await repo.get_document_by_content_hash(content_hash) == await repo.get_document(legacy)
    matching = await repo.get_document_by_content_hash(
        content_hash, scope=_scope(), competitor="Vacuum X Pro", dimension="specs", market="CN"
    )
    assert matching.id == scoped
    assert (
        await repo.get_document_by_content_hash(
            content_hash,
            scope=_scope("workspace-b"),
            competitor="Vacuum X Pro",
            dimension="specs",
            market="CN",
        )
        is None
    )


@pytest.mark.asyncio
async def test_scoped_fts_filters_apply_before_limit_with_exact_model_suffix(repo):
    for index, overrides in enumerate(
        [
            {"workspace_id": "workspace-b"},
            {"project_id": "project-b"},
            {"competitor": "Vacuum X"},
            {"dimension": "pricing"},
            {"market": "US"},
            {"source_role": "historical_report"},
        ]
    ):
        await _ingest(
            repo,
            url=f"https://example.com/noise-{index}",
            title="vacuum " * 10,
            text=("vacuum " * (10 + index)),
            **overrides,
        )
    wanted = await _ingest(
        repo, url="https://example.com/wanted", text="vacuum battery detailed runtime explanation"
    )
    filters = {
        "scope": _scope(),
        "competitors": ["Vacuum X Pro"],
        "dimensions": ["specs"],
        "market": "CN",
        "source_roles": ["source"],
    }
    docs = await repo.search_documents("vacuum", limit=1, **filters)
    hits = await repo.search_chunks("vacuum", limit=1, **filters)
    assert [doc.id for doc in docs] == [wanted]
    assert [hit.document_id for hit in hits] == [wanted]
    assert hits[0].workspace_id == "workspace-a"
    assert hits[0].project_id == "project-a"
    assert hits[0].market == "CN"
    assert hits[0].source_role == "source"
    assert hits[0].document_version == 1


@pytest.mark.asyncio
async def test_versions_rollback_and_merge_are_limited_to_namespace(repo):
    original = await _ingest(repo, metadata={"run_id": "good"})
    peer = await _ingest(repo, workspace_id="workspace-b", metadata={"run_id": "bad"})
    changed = await _ingest(
        repo, text="vacuum battery runtime is seventy minutes", metadata={"run_id": "bad"}
    )
    assert not (await repo.get_document(original)).is_active
    assert (await repo.get_document(peer)).is_active
    assert (await repo.get_document(changed)).version == 2
    assert (await repo.get_document(changed)).parent_document_id == original
    assert [doc.id for doc in await repo.get_document_versions(changed, scope=_scope())] == [
        original,
        changed,
    ]
    assert await repo.get_document_versions(changed, scope=_scope("workspace-b")) == []
    assert await repo.merge_document_version(changed, peer, scope=_scope()) is None
    result = await repo.rollback_documents(run_id="bad", scope=_scope())
    assert result.archived_document_ids == [changed]
    assert result.restored_document_ids == [original]
    assert (await repo.get_document(peer)).is_active


@pytest.mark.asyncio
async def test_rollback_does_not_restore_other_namespace_history(repo):
    old_peer = await _ingest(repo, workspace_id="workspace-b")
    new_peer = await _ingest(repo, workspace_id="workspace-b", text="vacuum peer new body")
    own = await _ingest(repo, text="vacuum own body", metadata={"run_id": "bad"})
    result = await repo.rollback_documents(run_id="bad", scope=_scope())
    assert result.archived_document_ids == [own]
    assert result.restored_document_ids == []
    assert not (await repo.get_document(old_peer)).is_active
    assert (await repo.get_document(new_peer)).is_active


@pytest.mark.asyncio
async def test_reopening_preserves_active_scoped_duplicates_and_namespace_indexes(repo):
    ids = [
        await _ingest(repo),
        await _ingest(repo, workspace_id="workspace-b"),
        await _ingest(repo, competitor="Vacuum X"),
        await _ingest(repo, project_id=None),
    ]
    await repo.close()
    await repo.initialise()
    assert all([(await repo.get_document(doc_id)).is_active for doc_id in ids])
    async with repo._connection.execute("SELECT name FROM sqlite_master WHERE type='index'") as cur:
        indexes = {row["name"] for row in await cur.fetchall()}
    assert "ux_documents_active_canonical_url" not in indexes
    assert "ux_documents_active_content_hash" not in indexes
    assert "ux_documents_namespace_active_canonical_url" in indexes
    assert "ux_documents_namespace_active_content_hash" in indexes
    async with repo._connection.execute("SELECT MAX(id) AS version FROM _schema_version") as cur:
        assert (await cur.fetchone())["version"] == 14


@pytest.mark.asyncio
async def test_reopening_migrated_database_removes_recreated_legacy_global_indexes(repo):
    original_time = datetime(2024, 1, 1, tzinfo=UTC)
    original_id = await _ingest(
        repo,
        fetched_at=original_time,
        source_published_at=original_time,
        source_updated_at=original_time,
        last_verified_at=original_time,
        metadata={"authority": "original"},
    )
    async with repo._connection.execute(
        "SELECT * FROM documents WHERE id = ?", [original_id]
    ) as cur:
        original_row = dict(await cur.fetchone())
    original_chunks = await repo.get_chunks_for_document(original_id)
    async with repo._connection.execute("SELECT * FROM _schema_version ORDER BY id") as cur:
        original_migrations = [dict(row) for row in await cur.fetchall()]
    assert original_migrations[-1]["id"] == 14
    await repo.close()

    with sqlite3.connect(repo.db_path) as db:
        db.execute(
            "CREATE UNIQUE INDEX ux_documents_active_canonical_url ON documents(canonical_url) "
            "WHERE is_active=1 AND canonical_url IS NOT NULL"
        )
        db.execute(
            "CREATE UNIQUE INDEX ux_documents_active_content_hash ON documents(content_hash) "
            "WHERE is_active=1"
        )

    await repo.initialise()
    other_id = await _ingest(repo, workspace_id="workspace-b")
    assert other_id != original_id
    assert (await repo.get_document(other_id)).is_active
    assert (await repo.get_document(other_id)).version == 1
    assert await _ingest(repo) == original_id
    assert await _ingest(repo, workspace_id="workspace-b") == other_id
    async with repo._connection.execute(
        "SELECT * FROM documents WHERE id = ?", [original_id]
    ) as cur:
        assert dict(await cur.fetchone()) == original_row
    assert await repo.get_chunks_for_document(original_id) == original_chunks
    assert await repo.count_documents() == 2
    async with repo._connection.execute("SELECT name FROM sqlite_master WHERE type='index'") as cur:
        indexes = {row["name"] for row in await cur.fetchall()}
    assert "ux_documents_active_canonical_url" not in indexes
    assert "ux_documents_active_content_hash" not in indexes
    assert "ux_documents_namespace_active_canonical_url" in indexes
    assert "ux_documents_namespace_active_content_hash" in indexes
    async with repo._connection.execute("SELECT * FROM _schema_version ORDER BY id") as cur:
        assert [dict(row) for row in await cur.fetchall()] == original_migrations


@pytest.mark.asyncio
async def test_migration_keeps_legacy_scope_null_and_classifies_reports(tmp_path):
    path = str(tmp_path / "legacy.db")
    with sqlite3.connect(path) as db:
        db.executescript(_BASE_SCHEMA)
        db.execute(
            "INSERT INTO documents "
            "(id,title,source_type,content_hash,text,fetched_at,metadata_json) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                "old",
                "Old report",
                "report",
                "old-hash",
                "vacuum report",
                datetime.now(UTC).isoformat(),
                '{"workspace_id":"spoof","project_id":"spoof"}',
            ),
        )
        db.execute(
            "CREATE UNIQUE INDEX ux_documents_active_canonical_url ON documents(canonical_url) "
            "WHERE is_active=1 AND canonical_url IS NOT NULL"
        )
        db.execute(
            "CREATE UNIQUE INDEX ux_documents_active_content_hash ON documents(content_hash) "
            "WHERE is_active=1"
        )
    repository = KnowledgeRepository(path)
    await repository.initialise()
    try:
        doc = await repository.get_document("old")
        assert doc.workspace_id is None
        assert doc.project_id is None
        assert doc.source_role == "historical_report"
        assert await repository.search_documents("vacuum", scope=_scope("spoof", "spoof")) == []
        new = await _ingest(repository, text="vacuum report")
        assert new != "old"
        await repository.close()
        await repository.initialise()
        assert (await repository.get_document("old")).is_active
        assert (await repository.get_document(new)).is_active
    finally:
        await repository.close()


class _Vectors:
    def __init__(self):
        self.payloads = []

    async def upsert(self, _ids, _vectors, payloads):
        self.payloads.extend(payloads)


@pytest.mark.asyncio
async def test_ingest_keeps_actual_timestamps_and_typed_scope_on_duplicates(repo):
    fetched = datetime(2024, 1, 1, tzinfo=UTC)
    verified = datetime(2024, 1, 2, tzinfo=UTC)
    published = datetime(2023, 12, 1, tzinfo=UTC)
    vectors = _Vectors()
    pipeline = IngestionPipeline(repo, vectors)
    doc_id = await pipeline.ingest(
        _doc(fetched_at=fetched, last_verified_at=verified, source_published_at=published),
        embed_fn=lambda texts: [[1.0, 2.0]] * len(texts),
        embedding_model="test-model",
    )
    assert (
        await pipeline.ingest(
            _doc(fetched_at=datetime.now(UTC), last_verified_at=datetime.now(UTC))
        )
        == doc_id
    )
    stored = await repo.get_document(doc_id)
    assert stored.fetched_at == fetched
    assert stored.last_verified_at == verified
    assert stored.source_published_at == published
    assert len(vectors.payloads) == 1
    payload = vectors.payloads[0]
    assert payload["workspace_id"] == "workspace-a"
    assert payload["project_id"] == "project-a"
    assert payload["market"] == "CN"
    assert payload["source_role"] == "source"
    assert payload["fetched_at"] == fetched.isoformat()
    assert payload["last_verified_at"] == verified.isoformat()
    assert payload["source_published_at"] == published.isoformat()
    assert payload["document_version"] == 1
    assert payload["document_content_hash"] == stored.content_hash
    public_vectors = _Vectors()
    await IngestionPipeline(repo, public_vectors).ingest(
        _doc(project_id=None),
        embed_fn=lambda texts: [[1.0, 2.0]] * len(texts),
        embedding_model="test-model",
    )
    assert public_vectors.payloads[0]["project_id"] == ""


@pytest.mark.asyncio
async def test_age_filter_uses_verified_then_actual_fetched_time(repo):
    old = datetime.now(UTC) - timedelta(days=100)
    recent = datetime.now(UTC) - timedelta(days=1)
    fresh_id = await _ingest(
        repo, fetched_at=old, last_verified_at=recent, text="vacuum fresh verified"
    )
    await _ingest(repo, fetched_at=old, text="vacuum old fetched", url="https://example.com/old")
    assert [
        doc.id for doc in await repo.search_documents("vacuum", scope=_scope(), max_age_days=30)
    ] == [fresh_id]
    assert [
        hit.document_id
        for hit in await repo.search_chunks("vacuum", scope=_scope(), max_age_days=30)
    ] == [fresh_id]


@pytest.mark.asyncio
async def test_explicit_workspace_library_reuse_excludes_other_projects(repo):
    own = await _ingest(repo, text="vacuum own project")
    library = await _ingest(repo, project_id=None, text="vacuum library body")
    await _ingest(repo, project_id="project-b", text="vacuum another project")
    await _ingest(repo, workspace_id="workspace-b", project_id=None, text="vacuum another library")
    scope = models.KnowledgeScope(
        workspace_id="workspace-a", project_id="project-a", include_workspace_library=True
    )
    assert {doc.id for doc in await repo.search_documents("vacuum", scope=scope)} == {own, library}
    assert {hit.document_id for hit in await repo.search_chunks("vacuum", scope=scope)} == {
        own,
        library,
    }
    assert await repo.count_documents(scope=scope) == 2
    request = RetrievalRequest(
        query="vacuum",
        workspace_id="workspace-a",
        project_id="project-a",
        include_workspace_library=True,
    )
    assert request.scope == scope
    assert (await repo.get_document(own)).scope.include_workspace_library is False


@pytest.mark.asyncio
async def test_old_publication_is_not_made_fresh_by_recent_fetch(repo):
    old = datetime.now(UTC) - timedelta(days=100)
    recent = datetime.now(UTC) - timedelta(days=1)
    await _ingest(repo, fetched_at=recent, source_published_at=old, text="vacuum old publication")
    verified = await _ingest(
        repo,
        fetched_at=recent,
        source_published_at=old,
        last_verified_at=recent,
        url="https://example.com/verified",
        text="vacuum recently verified",
    )
    assert [
        doc.id for doc in await repo.search_documents("vacuum", scope=_scope(), max_age_days=7)
    ] == [verified]
    assert [
        hit.document_id
        for hit in await repo.search_chunks("vacuum", scope=_scope(), max_age_days=7)
    ] == [verified]
    assert [doc.id for doc in await repo.list_documents(scope=_scope(), max_age_days=7)] == [
        verified
    ]
    assert await repo.count_documents(scope=_scope(), max_age_days=7) == 1
    assert [
        doc.id
        for doc in await repo.list_documents_for_evidence_sync(scope=_scope(), max_age_days=7)
    ] == [verified]


@pytest.mark.asyncio
async def test_library_read_flag_does_not_expand_rollback_write_scope(repo):
    library = await _ingest(
        repo, project_id=None, text="vacuum library source", metadata={"run_id": "bad"}
    )
    own = await _ingest(repo, text="vacuum project source", metadata={"run_id": "bad"})
    scope = models.KnowledgeScope(
        workspace_id="workspace-a", project_id="project-a", include_workspace_library=True
    )
    assert (await repo.get_document(library, scope=scope)).id == library
    result = await repo.rollback_documents(run_id="bad", scope=scope, restore_previous=False)
    assert result.archived_document_ids == [own]
    assert (await repo.get_document(library)).is_active
    assert not (await repo.get_document(own)).is_active
    assert scope.include_workspace_library is True


@pytest.mark.asyncio
async def test_library_read_flag_does_not_expand_merge_write_scope(repo):
    library_old = await _ingest(repo, project_id=None, text="vacuum library old source")
    library_new = await _ingest(repo, project_id=None, text="vacuum library new source")
    own_old = await _ingest(repo, text="vacuum project old source")
    own_new = await _ingest(repo, text="vacuum project new source")
    scope = models.KnowledgeScope(
        workspace_id="workspace-a", project_id="project-a", include_workspace_library=True
    )
    assert (await repo.get_document(library_new, scope=scope)).id == library_new
    assert await repo.merge_document_version(library_new, library_old, scope=scope) is None
    assert (await repo.get_document(library_new)).is_active
    assert not (await repo.get_document(library_old)).is_active
    own_restored = await repo.merge_document_version(own_new, own_old, scope=scope)
    assert own_restored.id == own_old
    assert own_restored.is_active
    assert not (await repo.get_document(own_new)).is_active
    assert scope.include_workspace_library is True


@pytest.mark.asyncio
async def test_recent_ingest_stats_compare_instants_with_timezone_offsets(repo):
    fetched = (datetime.now(UTC) - timedelta(hours=23)).astimezone(timezone(timedelta(hours=-12)))
    await _ingest(repo, fetched_at=fetched)
    stats = await repo.knowledge_stats(scope=_scope())
    assert stats["last_24h_ingest_count"] == 1


@pytest.mark.asyncio
async def test_document_list_orders_actual_fetch_instants_across_timezone_offsets(repo):
    now = datetime.now(UTC)
    older_time = now - timedelta(hours=25)
    newer_time = (now - timedelta(hours=23)).astimezone(timezone(timedelta(hours=-12)))
    older = await _ingest(repo, fetched_at=older_time, text="vacuum older source")
    newer = await _ingest(
        repo, fetched_at=newer_time, text="vacuum newer source", url="https://example.com/newer"
    )
    assert [doc.id for doc in await repo.list_documents(scope=_scope())] == [newer, older]
    stored = await repo.get_document(newer)
    assert stored.fetched_at == newer_time
    assert stored.fetched_at.utcoffset() == timedelta(0)


@pytest.mark.asyncio
async def test_archive_cutoff_compares_actual_fetch_instants_across_timezone_offsets(repo):
    now = datetime.now(UTC)
    older_time = now - timedelta(hours=25)
    newer_time = (now - timedelta(hours=23)).astimezone(timezone(timedelta(hours=-12)))
    older = await _ingest(repo, fetched_at=older_time, text="vacuum older source")
    newer = await _ingest(
        repo, fetched_at=newer_time, text="vacuum newer source", url="https://example.com/newer"
    )
    assert await repo.archive_old_documents(now - timedelta(hours=24)) == 1
    assert not (await repo.get_document(older)).is_active
    assert (await repo.get_document(newer)).is_active


@pytest.mark.parametrize("model_name", ["scope", "document", "request"])
@pytest.mark.parametrize("project_id", ["", " ", "\t\n"])
def test_non_null_project_ids_must_be_nonempty_without_rewriting_valid_ids(model_name, project_id):
    def create(value):
        if model_name == "scope":
            return _scope(project_id=value)
        if model_name == "document":
            return _doc(project_id=value)
        return RetrievalRequest(query="vacuum", workspace_id="workspace-a", project_id=value)

    with pytest.raises(ValidationError, match="project_id"):
        create(project_id)
    assert create(" project:a ").project_id == " project:a "
    assert create(None).project_id is None


@pytest.mark.asyncio
async def test_naive_actual_fetch_keeps_existing_utc_semantics(repo):
    naive = datetime(2024, 1, 1, 12, 30)
    doc_id = await _ingest(repo, fetched_at=naive)
    assert (await repo.get_document(doc_id)).fetched_at == naive.replace(tzinfo=UTC)
