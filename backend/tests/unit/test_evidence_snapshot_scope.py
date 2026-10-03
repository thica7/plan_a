from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from test_run_evidence_snapshot import make_detail, make_document
from test_stage_evidence_views import FixedTime

from packages.knowledge.models import DocumentCreate, KnowledgeChunk
from packages.knowledge.repository import KnowledgeRepository
from packages.memory.run_journal import RunJournal
from packages.research.evidence.snapshot import current_snapshot, seal_snapshot
from packages.schema.api_dto import RunDetail


def context_api():
    from packages.orchestrator.evidence_context import EvidenceContextMixin

    return EvidenceContextMixin


def context_harness(tmp_path):
    class Context(context_api()):
        def __init__(self):
            self.journal = RunJournal(tmp_path / "journal.db")
            self.record = None

        def _persist_run(self, run_id):
            assert self.record.detail.id == run_id
            self.journal.save_run(self.record.detail)

    from packages.orchestrator.service import RunRecord

    context = Context()
    context.record = RunRecord(detail=make_detail())
    return context, context.record


async def seed_reference(tmp_path, monkeypatch, *, overrides=None, chunk_ids=("chunk-a",)):
    monkeypatch.setenv("KB_DB_PATH", str(tmp_path / "knowledge.db"))
    values = make_document(**(overrides or {})).model_dump()
    async with KnowledgeRepository() as repo:
        doc = await repo.upsert_document(DocumentCreate(**values), values["content_hash"])
        await repo.insert_chunks(
            [
                KnowledgeChunk(
                    id=chunk_id,
                    document_id=doc.id,
                    chunk_index=index,
                    text="Original price evidence",
                    token_count=4,
                    embedding_model="test",
                    content_hash="chunk-hash",
                )
                for index, chunk_id in enumerate(chunk_ids)
            ]
        )
    return doc


def attach(detail, doc):
    detail.raw_sources[0].metadata.update(
        {
            "kb_document_id": doc.id,
            "kb_document_version": doc.version,
            "kb_document_content_hash": doc.content_hash,
            "kb_chunk_id": "chunk-a",
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("project_id", ["project-a", None])
async def test_prepare_uses_scoped_canonical_identity_and_persists(
    tmp_path, monkeypatch, project_id
):
    context, record = context_harness(tmp_path)
    doc = await seed_reference(
        tmp_path, monkeypatch, overrides={"project_id": project_id, "last_verified_at": None}
    )
    attach(record.detail, doc)
    record.detail.raw_sources[0].metadata.update(
        {
            "kb_document_workspace_id": "spoof",
            "kb_document_project_id": "spoof",
            "last_verified_at": "2099-01-01",
            "source_published_at": "2099-01-02",
        }
    )
    first = await context._prepare_evidence_snapshot(record, phase="analysis")
    second = await context._prepare_evidence_snapshot(record, phase="analysis")
    assert first.id == second.id
    assert (
        first.sources[0].document_project_id is project_id
        or first.sources[0].document_project_id == project_id
    )
    assert first.sources[0].document_workspace_id == doc.workspace_id
    assert first.sources[0].last_verified_at is None
    assert first.sources[0].source_published_at == doc.source_published_at
    restored = RunJournal(tmp_path / "journal.db").load_run(record.detail.id)
    assert current_snapshot(restored).id == first.id
    assert record.detail.raw_sources[0].metadata["kb_document_workspace_id"] == "spoof"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"workspace_id": "workspace-b"}, "canonical_document_unavailable"),
        ({"workspace_id": None}, "canonical_document_unavailable"),
        ({"project_id": "project-b"}, "canonical_document_unavailable"),
        ({"competitor": "Product A Pro"}, "identity_mismatch"),
    ],
)
async def test_scope_unknown_ownership_and_full_model_reject(
    tmp_path, monkeypatch, overrides, reason
):
    context, record = context_harness(tmp_path)
    doc = await seed_reference(tmp_path, monkeypatch, overrides=overrides)
    attach(record.detail, doc)
    snapshot = await context._prepare_evidence_snapshot(record, phase="analysis")
    assert not snapshot.sources and not snapshot.facts
    assert reason in {gap.reason for gap in snapshot.gaps}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,reason",
    [
        ("version", "version_mismatch"),
        ("hash", "hash_mismatch"),
        ("chunk", "chunk_reference_unavailable"),
        ("missing", "canonical_document_unavailable"),
    ],
)
async def test_original_reference_mismatch_is_not_silently_refreshed(
    tmp_path, monkeypatch, case, reason
):
    context, record = context_harness(tmp_path)
    doc = await seed_reference(tmp_path, monkeypatch)
    attach(record.detail, doc)
    reference = record.detail.raw_sources[0].metadata
    if case == "version":
        reference["kb_document_version"] += 1
    elif case == "hash":
        reference["kb_document_content_hash"] = "changed"
    elif case == "chunk":
        reference["kb_chunk_id"] = "other-document-chunk"
    else:
        reference["kb_document_id"] = "missing-doc"
    before = record.detail.raw_sources[0].model_dump_json()
    snapshot = await context._prepare_evidence_snapshot(record, phase="analysis")
    assert not snapshot.sources
    assert reason in {gap.reason for gap in snapshot.gaps}
    assert record.detail.raw_sources[0].model_dump_json() == before


@pytest.mark.asyncio
async def test_chunks_are_read_only_after_document_authorization(tmp_path, monkeypatch):
    context, record = context_harness(tmp_path)
    doc = await seed_reference(tmp_path, monkeypatch, overrides={"workspace_id": "workspace-b"})
    attach(record.detail, doc)
    original = KnowledgeRepository.get_chunks_for_document

    async def forbid(repo, document_id):
        raise AssertionError("out-of-scope document must not expose chunks")

    monkeypatch.setattr(KnowledgeRepository, "get_chunks_for_document", forbid)
    snapshot = await context._prepare_evidence_snapshot(record, phase="analysis")
    assert not snapshot.sources
    monkeypatch.setattr(KnowledgeRepository, "get_chunks_for_document", original)


@pytest.mark.asyncio
async def test_corrupt_chunk_document_id_is_rejected(tmp_path, monkeypatch):
    context, record = context_harness(tmp_path)
    doc = await seed_reference(tmp_path, monkeypatch)
    attach(record.detail, doc)

    async def wrong_chunks(repo, document_id):
        return [
            KnowledgeChunk(
                id="chunk-a",
                document_id="other-doc",
                chunk_index=0,
                text="unrelated",
                token_count=1,
                embedding_model="test",
                content_hash="x",
            )
        ]

    monkeypatch.setattr(KnowledgeRepository, "get_chunks_for_document", wrong_chunks)
    snapshot = await context._prepare_evidence_snapshot(record, phase="analysis")
    assert not snapshot.sources
    assert "chunk_identity_mismatch" in {gap.reason for gap in snapshot.gaps}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reference,reason",
    [
        ({"chunk_id": "other-document-chunk"}, "chunk_reference_mismatch"),
        ({"chunk_id": 17}, "chunk_reference_invalid"),
        ({"chunk_id": ""}, "chunk_reference_invalid"),
        ({"kb_chunk_id": ""}, "chunk_reference_invalid"),
        ({"kb_chunk_id": None}, "chunk_reference_invalid"),
        ({"kb_chunk_ids": [" "]}, "chunk_reference_invalid"),
    ],
)
async def test_every_explicit_chunk_reference_is_validated(
    tmp_path, monkeypatch, reference, reason
):
    context, record = context_harness(tmp_path)
    doc = await seed_reference(tmp_path, monkeypatch)
    attach(record.detail, doc)
    first = await context._prepare_evidence_snapshot(record, phase="analysis")
    before = first.model_dump_json()
    record.detail.raw_sources[0].metadata.update(reference)
    raw_before = record.detail.raw_sources[0].model_dump_json()

    rejected = await context._prepare_evidence_snapshot(record, phase="analysis")

    assert not rejected.sources and not rejected.facts
    assert reason in {gap.reason for gap in rejected.gaps}
    assert rejected.content_hash != first.content_hash
    assert record.detail.evidence_snapshots[0].model_dump_json() == before
    assert record.detail.raw_sources[0].model_dump_json() == raw_before


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["prepare", "seal"])
@pytest.mark.parametrize("alias", ["chunk-b", " chunk-b "])
async def test_conflicting_single_chunk_aliases_revoke_use(
    tmp_path, monkeypatch, entrypoint, alias
):
    context, record = context_harness(tmp_path)
    doc = await seed_reference(tmp_path, monkeypatch, chunk_ids=("chunk-a", "chunk-b"))
    attach(record.detail, doc)
    first = await context._prepare_evidence_snapshot(record, phase="analysis")
    before = first.model_dump_json()
    _, use = context._begin_evidence_use(record, agent="analyst")
    record.detail.raw_sources[0].metadata["chunk_id"] = alias
    raw_before = record.detail.raw_sources[0].model_dump_json()

    if entrypoint == "prepare":
        rejected = await context._prepare_evidence_snapshot(record, phase="analysis")
    else:
        rejected = seal_snapshot(record.detail, phase="analysis", canonical_documents={doc.id: doc})

    assert not rejected.sources and not rejected.facts
    assert {(gap.reason, gap.document_id) for gap in rejected.gaps} == {
        ("chunk_reference_mismatch", doc.id)
    }
    assert rejected.content_hash != first.content_hash
    with pytest.raises(ValueError, match="evidence"):
        context._validate_evidence_use(record, use)
    assert record.detail.raw_sources[0].model_dump_json() == raw_before
    assert record.detail.evidence_snapshots[0].model_dump_json() == before
    restored = context.journal.load_run(record.detail.id)
    assert restored.evidence_snapshot_id == rejected.id
    assert restored.evidence_consumptions[0].status == "rejected"


@pytest.mark.asyncio
@pytest.mark.parametrize("reference", ["single", "multiple"])
async def test_all_verified_chunk_references_participate_in_snapshot_and_use(
    tmp_path, monkeypatch, reference
):
    context, record = context_harness(tmp_path)
    doc = await seed_reference(tmp_path, monkeypatch, chunk_ids=("chunk-a", "chunk-b"))
    attach(record.detail, doc)
    metadata = record.detail.raw_sources[0].metadata
    metadata.pop("kb_chunk_id")
    metadata.update(
        {"chunk_id": "chunk-a"} if reference == "single" else {"kb_chunk_ids": ["chunk-a"]}
    )
    first = await context._prepare_evidence_snapshot(record, phase="analysis")
    before = first.model_dump_json()
    first_view, use = context._begin_evidence_use(record, agent="analyst")
    metadata.update(
        {"chunk_id": "chunk-b"}
        if reference == "single"
        else {"kb_chunk_ids": ["chunk-a", "chunk-b"]}
    )
    raw_before = record.detail.raw_sources[0].model_dump_json()

    second = await context._prepare_evidence_snapshot(record, phase="analysis")

    assert second.id != first.id and second.version == first.version + 1
    expected = ("chunk-b",) if reference == "single" else ("chunk-a", "chunk-b")
    assert first.sources[0].chunk_ids == ("chunk-a",)
    assert second.sources[0].chunk_ids == expected
    assert second.sources[0].chunk_id == ("chunk-b" if reference == "single" else None)
    second_view, _ = context._begin_evidence_use(record, agent="analyst")
    assert second_view.dependency_hash != first_view.dependency_hash
    assert second_view.sources[0].to_raw_source().metadata["kb_chunk_ids"] == list(expected)
    assert {tuple(source.chunk_ids) for source in second_view.sources} == {expected}
    assert json.loads(second_view.to_prompt_json())["sources"][0]["chunk_ids"] == list(expected)

    def observations(snapshot):
        return {
            (fact.field, fact.value_json, fact.quote, fact.evidence_item_ids)
            for fact in snapshot.facts
        }

    assert observations(first) == observations(second)
    with pytest.raises(ValueError, match="evidence"):
        context._validate_evidence_use(record, use)
    assert record.detail.raw_sources[0].model_dump_json() == raw_before
    assert record.detail.evidence_snapshots[0].model_dump_json() == before
    restored = context.journal.load_run(record.detail.id)
    assert restored.evidence_consumptions[0].status == "rejected"
    if reference == "multiple":
        metadata["kb_chunk_ids"].reverse()
        assert (await context._prepare_evidence_snapshot(record, phase="analysis")).id == second.id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reference,expected",
    [
        ({"kb_chunk_id": "chunk-a", "chunk_id": "chunk-a"}, ("chunk-a",)),
        ({"kb_chunk_id": " chunk-a ", "chunk_id": "chunk-a"}, ("chunk-a",)),
        ({"chunk_id": "chunk-b"}, ("chunk-b",)),
        (
            {"kb_chunk_id": "chunk-a", "kb_chunk_ids": ["chunk-b", "chunk-a"]},
            ("chunk-a", "chunk-b"),
        ),
        ({"chunk_id": "chunk-a", "kb_chunk_ids": ["chunk-b"]}, ("chunk-a", "chunk-b")),
    ],
)
async def test_equal_chunk_aliases_and_multiple_references_remain_supported(
    tmp_path, monkeypatch, reference, expected
):
    context, record = context_harness(tmp_path)
    doc = await seed_reference(tmp_path, monkeypatch, chunk_ids=("chunk-a", "chunk-b"))
    attach(record.detail, doc)
    record.detail.raw_sources[0].metadata.pop("kb_chunk_id")
    record.detail.raw_sources[0].metadata.update(reference)
    raw_before = record.detail.raw_sources[0].model_dump_json()

    snapshot = await context._prepare_evidence_snapshot(record, phase="analysis")

    assert snapshot.sources and snapshot.facts and not snapshot.gaps
    assert snapshot.sources[0].model_dump().get("chunk_ids") == expected
    assert record.detail.raw_sources[0].model_dump_json() == raw_before


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["prepare", "seal"])
@pytest.mark.parametrize(
    "alias,case,reason",
    [
        ("document_id", "different", "canonical_reference_mismatch"),
        ("document_id", "blank", "canonical_reference_invalid"),
        ("document_id", "none", "canonical_reference_invalid"),
        ("document_id", "type", "canonical_reference_invalid"),
        ("document_version", "different", "version_mismatch"),
        ("document_version", "blank", "version_mismatch"),
        ("document_version", "none", "version_mismatch"),
        ("document_version", "type", "version_mismatch"),
        ("document_version", "float", "version_mismatch"),
        ("kb_content_hash", "different", "hash_mismatch"),
        ("kb_content_hash", "blank", "hash_mismatch"),
        ("kb_content_hash", "none", "hash_mismatch"),
        ("kb_content_hash", "type", "hash_mismatch"),
    ],
)
async def test_every_explicit_document_alias_is_validated(
    tmp_path, monkeypatch, entrypoint, alias, case, reason
):
    context, record = context_harness(tmp_path)
    doc = await seed_reference(tmp_path, monkeypatch)
    attach(record.detail, doc)
    first = await context._prepare_evidence_snapshot(record, phase="analysis")
    before = first.model_dump_json()
    values = {
        "different": doc.version + 1 if alias == "document_version" else "conflicting-reference",
        "blank": " ",
        "none": None,
        "type": True if alias == "document_version" else 17,
        "float": float(doc.version),
    }
    record.detail.raw_sources[0].metadata[alias] = values[case]
    raw_before = record.detail.raw_sources[0].model_dump_json()
    get_document = KnowledgeRepository.get_document

    async def authorized_document_only(repo, document_id, *, scope):
        assert document_id == doc.id, "conflicting aliases must not authorize another lookup"
        return await get_document(repo, document_id, scope=scope)

    monkeypatch.setattr(KnowledgeRepository, "get_document", authorized_document_only)
    if entrypoint == "prepare":
        rejected = await context._prepare_evidence_snapshot(record, phase="analysis")
    else:
        rejected = seal_snapshot(record.detail, phase="analysis", canonical_documents={doc.id: doc})

    assert not rejected.sources and not rejected.facts
    assert {(gap.reason, gap.document_id) for gap in rejected.gaps} == {(reason, doc.id)}
    assert rejected.content_hash != first.content_hash
    assert record.detail.evidence_snapshots[0].model_dump_json() == before
    assert record.detail.raw_sources[0].model_dump_json() == raw_before


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["prepare", "seal"])
@pytest.mark.parametrize(
    "primary,alias,reason",
    [
        ("kb_document_id", "document_id", "canonical_reference_invalid"),
        ("kb_document_version", "document_version", "version_mismatch"),
        ("kb_document_content_hash", "kb_content_hash", "hash_mismatch"),
    ],
)
async def test_null_primary_identity_is_not_masked_by_valid_alias(
    tmp_path, monkeypatch, entrypoint, primary, alias, reason
):
    context, record = context_harness(tmp_path)
    doc = await seed_reference(tmp_path, monkeypatch)
    attach(record.detail, doc)
    metadata = record.detail.raw_sources[0].metadata
    metadata[alias] = metadata[primary]
    metadata[primary] = None
    raw_before = record.detail.raw_sources[0].model_dump_json()
    if entrypoint == "prepare":
        rejected = await context._prepare_evidence_snapshot(record, phase="analysis")
    else:
        rejected = seal_snapshot(record.detail, phase="analysis", canonical_documents={doc.id: doc})
    assert not rejected.sources and not rejected.facts
    assert {(gap.reason, gap.document_id) for gap in rejected.gaps} == {(reason, doc.id)}
    assert record.detail.raw_sources[0].model_dump_json() == raw_before


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["prepare", "seal"])
@pytest.mark.parametrize("alias", ["document_id", "document_version", "kb_content_hash"])
async def test_equal_identity_aliases_keep_canonical_reference(
    tmp_path, monkeypatch, entrypoint, alias
):
    context, record = context_harness(tmp_path)
    doc = await seed_reference(tmp_path, monkeypatch)
    attach(record.detail, doc)
    record.detail.raw_sources[0].metadata[alias] = {
        "document_id": doc.id,
        "document_version": doc.version,
        "kb_content_hash": doc.content_hash,
    }[alias]
    raw_before = record.detail.raw_sources[0].model_dump_json()
    if entrypoint == "prepare":
        snapshot = await context._prepare_evidence_snapshot(record, phase="analysis")
    else:
        snapshot = seal_snapshot(record.detail, phase="analysis", canonical_documents={doc.id: doc})
    assert snapshot.sources and snapshot.facts and not snapshot.gaps
    assert snapshot.sources[0].document_id == doc.id
    assert record.detail.raw_sources[0].model_dump_json() == raw_before


@pytest.mark.asyncio
async def test_no_kb_sources_do_not_open_default_repository(tmp_path, monkeypatch):
    context, record = context_harness(tmp_path)

    def forbid(*args, **kwargs):
        raise AssertionError("non-KB evidence cannot open a database")

    monkeypatch.setattr("packages.orchestrator.evidence_context.KnowledgeRepository", forbid)
    snapshot = await context._prepare_evidence_snapshot(record, phase="analysis")
    assert snapshot.sources


def test_unprepared_scope_pointer_and_hash_are_explicit_errors(tmp_path, monkeypatch):
    context, record = context_harness(tmp_path)
    with pytest.raises(ValueError, match="snapshot"):
        context._begin_evidence_use(record, agent="analyst")
    snapshot = seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    record.detail.evidence_snapshot_id = "missing"
    with pytest.raises(ValueError, match="pointer"):
        context._begin_evidence_use(record, agent="analyst")
    record.detail.evidence_snapshot_id = snapshot.id
    record.detail.evidence_snapshots[-1] = snapshot.model_copy(update={"content_hash": "wrong"})
    with pytest.raises(ValueError, match="hash"):
        context._begin_evidence_use(record, agent="analyst")


def test_local_consumer_dependencies_validate_unaffected_branch_and_reject_changed_branch(
    tmp_path, monkeypatch
):
    context, record = context_harness(tmp_path)
    from packages.research.evidence import views

    monkeypatch.setattr(views, "datetime", FixedTime)
    detail = record.detail
    other = make_detail().raw_sources[0]
    other.id = "product-b"
    other.competitor = "Product B"
    other.metadata["normalized_fields"][0]["competitor"] = "Product B"
    detail.raw_sources.append(other)
    first = seal_snapshot(detail, phase="analysis", canonical_documents={})
    view_a, use_a = context._begin_evidence_use(
        record, agent="analyst", competitor="Product A", dimension="pricing"
    )
    view_b, use_b = context._begin_evidence_use(
        record, agent="analyst", competitor="Product B", dimension="pricing"
    )
    assert use_a.id != use_b.id
    assert use_a.source_ids == view_a.source_ids and use_a.fact_ids == view_a.fact_ids
    assert view_a.dependency_hash == use_a.dependency_hash
    original_body_hash = detail.raw_sources[0].content_hash
    detail.raw_sources[0].metadata["normalized_fields"][0]["price"] = "4299 CNY"
    second = seal_snapshot(detail, phase="analysis", canonical_documents={})
    assert second.id != first.id and second.version == first.version + 1
    assert detail.raw_sources[0].content_hash == original_body_hash
    current_b, _ = context._begin_evidence_use(
        record, agent="analyst", competitor="Product B", dimension="pricing"
    )
    assert current_b.dependency_hash == view_b.dependency_hash
    assert current_b.source_ids == view_b.source_ids and current_b.fact_ids == view_b.fact_ids
    context._validate_evidence_use(record, use_b)
    with pytest.raises(ValueError, match="evidence"):
        context._validate_evidence_use(record, use_a)
    saved = {item.id: item for item in detail.evidence_consumptions}
    assert saved[use_b.id].snapshot_id == first.id
    assert saved[use_b.id].validated_snapshot_id == second.id
    assert saved[use_b.id].status == "validated"
    assert saved[use_a.id].status == "rejected"
    restored = context.journal.load_run(detail.id)
    assert restored.evidence_consumptions == detail.evidence_consumptions
    # A previously rejected producer stays rejected even when its old values return.
    detail.raw_sources[0].metadata["normalized_fields"][0]["price"] = "3999 CNY"
    seal_snapshot(detail, phase="analysis", canonical_documents={})
    restored_a, _ = context._begin_evidence_use(
        record, agent="analyst", competitor="Product A", dimension="pricing"
    )
    assert restored_a.dependency_hash == use_a.dependency_hash
    with pytest.raises(ValueError, match="already rejected"):
        context._validate_evidence_use(record, use_a)
    assert use_a.status == "started"
    assert (
        next(item for item in detail.evidence_consumptions if item.id == use_a.id).status
        == "rejected"
    )


@pytest.mark.parametrize("change", ["delete", "scope"])
def test_revoked_source_and_scope_reject_old_credentials(tmp_path, monkeypatch, change):
    context, record = context_harness(tmp_path)
    from packages.research.evidence import views

    monkeypatch.setattr(views, "datetime", FixedTime)
    seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    _, use = context._begin_evidence_use(record, agent="writer")
    if change == "delete":
        record.detail.raw_sources.clear()
        seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    else:
        record.detail.workspace_id = "other-workspace"
    with pytest.raises(ValueError, match="evidence|scope"):
        context._validate_evidence_use(record, use)
    assert record.detail.evidence_consumptions[-1].status == "rejected"


def test_depth_budgets_and_service_mixin_wiring(tmp_path, monkeypatch):
    context, record = context_harness(tmp_path)
    from packages.orchestrator.service import RunService
    from packages.research.evidence import views

    assert issubclass(RunService, context_api())
    monkeypatch.setattr(views, "datetime", FixedTime)
    seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    for depth, budget in (("quick", 8192), ("standard", 16384), ("deep", 24576)):
        record.detail.plan.research_depth = depth
        view, use = context._begin_evidence_use(record, agent="analyst")
        assert use.max_bytes == view.max_bytes == budget


def task1_v1_payload(case):
    fixture = json.loads(
        (Path(__file__).parents[1] / "fixtures" / "task1_evidence_v1_snapshots.json").read_text()
    )
    assert fixture["origin_commit"] == "1f0bb1a"
    legacy = fixture["snapshots"][case]
    assert all("chunk_ids" not in source for source in legacy["sources"])
    detail = make_detail()
    documents = {}
    if case != "non_kb":
        document = make_document()
        attach(detail, document)
        documents[document.id] = document
        if case == "kb_no_chunk":
            detail.raw_sources[0].metadata.pop("kb_chunk_id")
    payload = detail.model_dump(mode="json")
    payload.update(evidence_snapshots=[legacy], evidence_snapshot_id=legacy["id"])
    return payload, documents


@pytest.mark.parametrize("case", ["non_kb", "kb_no_chunk", "kb_single_chunk"])
def test_task1_v1_snapshot_survives_journal_reopen_without_rewriting_history(tmp_path, case):
    payload, _ = task1_v1_payload(case)
    legacy = payload["evidence_snapshots"][0]
    path = tmp_path / "legacy-journal.db"
    journal = RunJournal(path)
    journal.save_run(make_detail())
    # Put the actual Task 1 wire format in storage, before the new model reads it.
    with sqlite3.connect(path) as connection:
        connection.execute(
            "update runs set detail_json = ? where id = ?", (json.dumps(payload), payload["id"])
        )

    restored = RunJournal(path).load_run(payload["id"])
    snapshot = current_snapshot(restored)

    assert snapshot.id == legacy["id"] and snapshot.content_hash == legacy["content_hash"]
    assert snapshot.sources[0].payload_json == legacy["sources"][0]["payload_json"]
    assert tuple(fact.id for fact in snapshot.facts) == tuple(
        fact["id"] for fact in legacy["facts"]
    )
    if case == "kb_single_chunk":
        assert snapshot.sources[0].chunk_id == "chunk-a"
    before = snapshot.model_dump_json()
    RunJournal(path).save_run(restored)
    reopened = RunJournal(path).load_run(payload["id"])
    assert current_snapshot(reopened).model_dump_json() == before


@pytest.mark.parametrize("case", ["non_kb", "kb_no_chunk"])
def test_task1_v1_unchanged_input_reuses_snapshot_with_empty_new_chunk_refs(case):
    payload, documents = task1_v1_payload(case)
    detail = RunDetail.model_validate(payload)
    legacy = detail.evidence_snapshots[0]
    before = legacy.model_dump_json()

    reused = seal_snapshot(detail, phase="analysis", canonical_documents=documents)

    assert reused is legacy
    assert reused.id == payload["evidence_snapshot_id"]
    assert reused.content_hash == payload["evidence_snapshots"][0]["content_hash"]
    assert len(detail.evidence_snapshots) == 1
    assert detail.evidence_snapshots[0].model_dump_json() == before


@pytest.mark.parametrize("case", ["non_kb", "kb_no_chunk", "kb_single_chunk"])
def test_task1_v1_snapshot_rejects_injected_nonempty_chunk_refs(case):
    payload, _ = task1_v1_payload(case)
    detail = RunDetail.model_validate(payload)
    legacy = current_snapshot(detail)
    forged_source = legacy.sources[0].model_copy(update={"chunk_ids": ("injected-chunk",)})
    detail.evidence_snapshots[0] = legacy.model_copy(update={"sources": (forged_source,)})
    with pytest.raises(ValueError, match="content hash"):
        current_snapshot(detail)


def test_new_snapshot_nonempty_chunk_refs_remain_hash_protected():
    detail = make_detail()
    document = make_document()
    attach(detail, document)
    snapshot = seal_snapshot(detail, phase="analysis", canonical_documents={document.id: document})
    assert current_snapshot(detail).sources[0].chunk_ids == ("chunk-a",)
    forged_source = snapshot.sources[0].model_copy(update={"chunk_ids": ("different-chunk",)})
    detail.evidence_snapshots[0] = snapshot.model_copy(update={"sources": (forged_source,)})
    with pytest.raises(ValueError, match="content hash"):
        current_snapshot(detail)
