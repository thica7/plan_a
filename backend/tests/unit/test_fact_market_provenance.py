from __future__ import annotations

import socket
from copy import deepcopy
from datetime import UTC, datetime

import pytest
from test_run_evidence_snapshot import make_detail, make_document
from test_structured_pricing_pipeline import SUBSCRIPTION, local_chain

# isort: split
from packages.config import Settings
from packages.knowledge.models import DocumentCreate, KnowledgeScope
from packages.knowledge.repository import KnowledgeRepository
from packages.memory import KBCache, RunJournal
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunRecord, RunService
from packages.research.evidence.answer_guard import evaluate_answer_boundary
from packages.research.evidence.answer_models import AnswerRequirement
from packages.research.evidence.snapshot import seal_snapshot
from packages.research.evidence.views import select_evidence_view
from packages.schema.models import TargetProduct
from packages.skills.registry import SkillRegistry


@pytest.fixture(autouse=True)
def isolated_storage_and_network(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPETISCOPE_LOAD_ENV_FILES", "0")
    monkeypatch.setenv("KB_DB_PATH", str(tmp_path / "kb.db"))

    def forbid(*args, **kwargs):
        raise AssertionError("No network or model transport is permitted")

    monkeypatch.setattr(socket.socket, "connect", forbid)
    monkeypatch.setattr(socket.socket, "connect_ex", forbid)
    monkeypatch.setattr(socket, "create_connection", forbid)


def service_record(tmp_path, sources):
    detail = make_detail()
    detail.id = "market-provenance"
    detail.plan.competitors = ["Acme"]
    detail.plan.dimensions = ["pricing"]
    detail.plan.target_product = TargetProduct(name="Acme", market="US")
    detail.raw_sources = sources
    service = RunService(
        settings=Settings(demo_mode=True),
        skill_registry=SkillRegistry.from_default_path(),
        journal=RunJournal(tmp_path / "journal.db"),
        kb_cache=KBCache.in_memory(),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    record = RunRecord(detail=detail)
    service._runs[detail.id] = record
    return service, record


def source_text(market):
    return SUBSCRIPTION.replace("market: US.", f"market: {market}." if market else "")


async def pricing_view(service, record):
    snapshot = await service._prepare_evidence_snapshot(record, phase="analysis")
    view = select_evidence_view(
        snapshot, agent="writer", competitor="Acme", dimension="pricing"
    )
    boundary = evaluate_answer_boundary(
        view,
        AnswerRequirement(
            competitor="Acme",
            dimension="pricing",
            intent="current_price",
            market="US",
            as_of=datetime.now(UTC).date(),
        ),
    )
    return view, boundary


def assert_pricing_market(view, boundary, market):
    assert view.facts
    assert {fact.market for fact in view.facts} == {market}
    assert {source.market for source in view.sources} == {market}
    assert boundary.status == ("answer" if market == "US" else "insufficient")
    if market is None:
        assert "market" in boundary.missing_fields


@pytest.mark.asyncio
@pytest.mark.parametrize("market", [None, "CN", "US"])
async def test_capture_to_kb_keeps_source_pricing_market(tmp_path, monkeypatch, market):
    result, sources = await local_chain(monkeypatch, source_text(market))
    assert len(sources) == 1
    source = sources[0]
    assert source.metadata["market"] == market
    assert {row["market"] for row in source.metadata["normalized_fields"]} == {market}
    original_rows = deepcopy(source.metadata["normalized_fields"])
    service, record = service_record(tmp_path, sources)
    assert_pricing_market(*(await pricing_view(service, record)), market)

    await service._persist_captured_sources_to_kb(record, record.detail, sources, result)
    assert source.metadata["kb_full_source_ingest_status"] == "stored"
    scope = KnowledgeScope(
        workspace_id=record.detail.workspace_id, project_id=record.detail.project_id
    )
    async with KnowledgeRepository() as repo:
        stored = await repo.get_document(source.metadata["kb_document_id"], scope=scope)
    assert stored is not None
    assert stored.market == market
    assert stored.metadata["requested_market"] == "US"
    assert stored.text == result.captured_pages[0].text
    assert stored.metadata["normalized_fields"] == original_rows
    assert_pricing_market(*(await pricing_view(service, record)), market)

    # Join must retain the full document with the same source market identity.
    summary = await service._sync_collected_sources_to_kb(record, record.detail, sources)
    assert summary["ingested"] == 0
    assert summary["skipped"][0]["reason"] == "full_source_already_stored"
    async with KnowledgeRepository() as repo:
        after = await repo.get_document(stored.id, scope=scope)
    assert after.version == stored.version and after.text == stored.text
    assert source.metadata["normalized_fields"] == original_rows
    assert_pricing_market(*(await pricing_view(service, record)), market)


@pytest.mark.asyncio
@pytest.mark.parametrize("market", [None, "CN", "US"])
async def test_summary_ingest_keeps_source_pricing_market(tmp_path, monkeypatch, market):
    _, sources = await local_chain(monkeypatch, source_text(market))
    service, record = service_record(tmp_path, sources)

    summary = await service._sync_collected_sources_to_kb(record, record.detail, sources)

    assert summary["ingested"] == 1
    async with KnowledgeRepository() as repo:
        documents = await repo.list_documents(
            scope=KnowledgeScope(
                workspace_id=record.detail.workspace_id, project_id=record.detail.project_id
            )
        )
    assert len(documents) == 1
    assert documents[0].market == market
    assert documents[0].metadata["requested_market"] == "US"
    assert documents[0].metadata["source_material_level"] == "summary"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "row_market,canonical_market", [(None, "US"), ("CN", "US"), ("US", None)]
)
async def test_legacy_canonical_market_cannot_override_pricing_rows(
    tmp_path, monkeypatch, row_market, canonical_market
):
    result, sources = await local_chain(monkeypatch, source_text(row_market))
    service, record = service_record(tmp_path, sources)
    source = sources[0]
    # Simulate a legacy directory market also copied into source metadata.
    source.metadata["market"] = canonical_market
    async with KnowledgeRepository() as repo:
        document = await repo.upsert_document(
            DocumentCreate(
                workspace_id=record.detail.workspace_id,
                project_id=record.detail.project_id,
                competitor=source.competitor,
                dimension=source.dimension,
                market=canonical_market,
                source_role="source",
                url=str(source.url),
                title=source.title,
                text=result.captured_pages[0].text,
                source_type=source.source_type,
                fetched_at=source.extracted_at,
                last_verified_at=source.extracted_at,
                metadata={"source_material_level": "full_source"},
            ),
            "legacy-canonical-hash",
        )
    source.metadata.update(
        kb_document_id=document.id,
        kb_document_version=document.version,
        kb_document_content_hash=document.content_hash,
    )
    before = source.model_dump_json()

    assert_pricing_market(*(await pricing_view(service, record)), row_market)

    assert source.model_dump_json() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("rows", ["mixed", "absent"])
async def test_ambiguous_pricing_source_market_stays_unknown_through_legacy_directory(
    tmp_path, monkeypatch, rows
):
    text = SUBSCRIPTION
    if rows == "mixed":
        text += "\n" + SUBSCRIPTION.replace("USD 20", "USD 21").replace("market: US", "market: CN")
    result, sources = await local_chain(monkeypatch, text)
    source = sources[0]
    if rows == "mixed":
        assert {row["market"] for row in source.metadata["normalized_fields"]} == {"CN", "US"}
    else:
        source.metadata["normalized_fields"] = []
        # The old metadata label must not grant price scope without price rows.
        source.metadata["market"] = "US"
    service, record = service_record(tmp_path, sources)

    def assert_unknown(view, boundary):
        assert view.sources[0].market is None
        if rows == "mixed":
            assert {fact.market for fact in view.facts} == {"CN", "US"}
        else:
            assert not view.facts
        assert boundary.status == "insufficient"

    assert_unknown(*(await pricing_view(service, record)))
    await service._persist_captured_sources_to_kb(record, record.detail, sources, result)
    scope = KnowledgeScope(
        workspace_id=record.detail.workspace_id, project_id=record.detail.project_id
    )
    async with KnowledgeRepository() as repo:
        stored = await repo.get_document(source.metadata["kb_document_id"], scope=scope)
        assert stored is not None and stored.market is None
        legacy = await repo.upsert_document(
            DocumentCreate(**{**stored.model_dump(), "market": "US"}), stored.content_hash
        )
    assert_unknown(*(await pricing_view(service, record)))
    source.metadata.update(
        kb_document_id=legacy.id,
        kb_document_version=legacy.version,
        kb_document_content_hash=legacy.content_hash,
    )
    assert_unknown(*(await pricing_view(service, record)))


@pytest.mark.parametrize("kind", ["feature", "persona"])
@pytest.mark.parametrize("market", [None, "CN"])
def test_nonpricing_fact_market_does_not_inherit_query_classification(kind, market):
    detail = make_detail()
    detail.plan.target_product = TargetProduct(name="Product A", market="US")
    detail.plan.dimensions = [kind]
    source = detail.raw_sources[0]
    source.dimension = kind
    source.url = f"https://product-a.example/{kind}"
    source.metadata["market"] = "US"
    quote = (
        "Product A supports document comments."
        if kind == "feature" else "Product A serves developers."
    )
    if market:
        quote += f" market: {market}."
    source.metadata["normalized_fields"] = [
        {
            "kind": kind,
            "competitor": source.competitor,
            "dimension": kind,
            "market": market,
            "evidence_quote": quote,
            "evidence_item_ids": ["original-observation"],
            "confidence": 0.8,
            **(
                {"slot": "comments", "support_level": "supported"}
                if kind == "feature" else {"role": "developers"}
            ),
        }
    ]
    source.snippet = quote
    before = seal_snapshot(detail, phase="analysis", canonical_documents={})
    assert before.facts
    assert {fact.market for fact in before.facts} == {market}

    document = make_document(dimension=kind, market="US", url=str(source.url), text=quote)
    source.metadata.update(
        kb_document_id=document.id,
        kb_document_version=document.version,
        kb_document_content_hash=document.content_hash,
    )
    after = seal_snapshot(detail, phase="analysis", canonical_documents={document.id: document})
    assert document.market == "US", "The directory can retain its query classification"
    assert {fact.market for fact in after.facts} == {market}
    assert {
        row.get("market")
        for row in after.sources[0].to_raw_source().metadata["normalized_fields"]
    } == {market}
