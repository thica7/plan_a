"""Offline repair replay exercises real producers and persisted cache credentials."""

from __future__ import annotations

import asyncio
import copy

import pytest
from test_agent_evidence_alignment import InputReplay

from packages.memory import KBCache
from packages.orchestrator.evidence_context import EvidenceUseRejectedError
from packages.schema.models import RedoScope
from packages.schema.survey import UserResearchImportRequest, UserResearchMaterial


def repair_service(tmp_path):
    service = InputReplay(tmp_path)
    service._kb_cache = KBCache(tmp_path / "cache.db")
    return service


@pytest.mark.asyncio
async def test_price_correction_reuses_unaffected_producer(tmp_path):
    service = repair_service(tmp_path)
    record = service.record
    old = await service._prepare_evidence_snapshot(record, phase="analysis")
    b_source = record.detail.raw_sources[-1].model_dump(mode="json")
    await service._real_analyst_branch_step(record, "pricing", "Phone X")
    await service._real_analyst_branch_step(record, "feature", "Phone X Pro")
    b_key = service._kb_cache_content_hash(record.detail, "Phone X Pro", "feature")
    a_key = service._kb_cache_content_hash(record.detail, "Phone X", "pricing")
    original = record.detail.evidence_consumptions[-1]
    source = record.detail.raw_sources[0]
    source.metadata = copy.deepcopy(source.metadata)
    source.metadata["normalized_fields"][0]["price"] = 4299
    source.metadata["normalized_fields"][0]["source_quote"] = "4299 CNY"
    new = await service._prepare_evidence_snapshot(record, phase="analysis")
    assert "pricing" not in record.detail.competitor_kbs["Phone X"].slices
    assert not any(
        item.competitor == "Phone X" and item.dimension == "pricing"
        for item in record.detail.claim_card_bundles
    )
    assert any(
        item.competitor == "Phone X Pro" and item.dimension == "feature"
        for item in record.detail.claim_card_bundles
    )
    assert new.version > old.version
    assert service._kb_cache_content_hash(record.detail, "Phone X", "pricing") != a_key
    assert service._kb_cache_content_hash(record.detail, "Phone X Pro", "feature") == b_key
    service._kb_cache = KBCache(tmp_path / "cache.db")
    await service._real_analyst_branch_step(record, "pricing", "Phone X")
    await service._real_analyst_branch_step(record, "feature", "Phone X Pro")
    prompts = [item["user"] for item in service.inputs if item["agent"] == "analyst"]
    accepted = [item for item in prompts if "QA feedback for this branch: []" in item]
    assert sum("Competitor: Phone X\n" in item for item in accepted) == 2
    assert sum("Competitor: Phone X Pro\n" in item for item in accepted) == 1
    assert "4299" in prompts[-1] and "3999" not in prompts[-1]
    assert record.detail.raw_sources[-1].model_dump(mode="json") == b_source
    reused = record.detail.evidence_consumptions[-1]
    assert reused.status == "reused"
    assert reused.reused_from_snapshot_id == original.snapshot_id == old.id
    assert reused.validated_snapshot_id == new.id
    assert record.detail.evidence_snapshots[0] == old
    producer = next(
        item
        for item in record.detail.evidence_artifact_dependencies
        if item.kind == "analyst"
        and item.competitor == "Phone X Pro"
        and item.dimension == "feature"
    )
    assert producer.consumption_ids == (original.id,)
    assert (
        next(
            item for item in record.detail.evidence_consumptions if item.id == original.id
        ).validated_snapshot_id
        == new.id
    )


@pytest.mark.asyncio
async def test_import_blocks_old_use_before_new_snapshot_is_prepared(tmp_path):
    service = repair_service(tmp_path)
    record = service.record
    old = await service._prepare_evidence_snapshot(record, phase="analysis")
    _, use = service._begin_evidence_use(
        record, agent="analyst", competitor="Phone X", dimension="pricing"
    )
    service.import_user_research_materials(
        record.detail.id,
        UserResearchImportRequest(
            materials=[
                UserResearchMaterial(
                    source_type="interview_record",
                    competitor="Phone X",
                    dimension="pricing",
                    text="Customer confirmed 4299 CNY",
                )
            ]
        ),
    )
    assert record.detail.evidence_snapshot_id == old.id
    with pytest.raises(EvidenceUseRejectedError):
        service._validate_evidence_use(record, use)


@pytest.mark.asyncio
async def test_cited_retired_source_is_auditable_but_not_publishable(tmp_path):
    service = repair_service(tmp_path)
    record = service.record
    old = await service._prepare_evidence_snapshot(record, phase="analysis")
    source_id = record.detail.raw_sources[0].id
    record.detail.report_md = f"Old price [source:{source_id}]"
    service._prepare_redo_scope_inputs(
        record.detail,
        RedoScope(
            rationale="refresh evidence",
            kind="collector",
            target_subagent="pricing",
            target_competitor="Phone X",
        ),
    )
    assert any(item.id == source_id for item in record.detail.raw_sources)
    new = await service._prepare_evidence_snapshot(record, phase="analysis")
    view, _ = service._begin_evidence_use(
        record, agent="analyst", competitor="Phone X", dimension="pricing"
    )
    assert source_id not in view.source_ids
    assert any(item.id == source_id for item in old.sources)
    assert new.id != old.id


@pytest.mark.asyncio
async def test_real_late_analyst_cannot_commit_after_correction(tmp_path):
    service = repair_service(tmp_path)
    record = service.record
    await service._prepare_evidence_snapshot(record, phase="analysis")
    waiting, release = asyncio.Event(), asyncio.Event()
    trace = service._trace_llm_json

    async def delayed(record, **kwargs):
        result = await trace(record, **kwargs)
        waiting.set()
        await release.wait()
        return result

    service._trace_llm_json = delayed
    late = asyncio.create_task(service._real_analyst_branch_step(record, "pricing", "Phone X"))
    await waiting.wait()
    record.detail.raw_sources[0].metadata["normalized_fields"][0]["price"] = 4299
    await service._prepare_evidence_snapshot(record, phase="analysis")
    release.set()
    with pytest.raises(EvidenceUseRejectedError):
        await late
    assert "Phone X" not in record.detail.competitor_knowledge
    assert record.detail.evidence_consumptions[-1].status == "rejected"


@pytest.mark.asyncio
async def test_comparator_change_invalidates_writer_even_with_unchanged_sources(
    tmp_path, monkeypatch
):
    from packages.agents.writer.repair import build_writer_repair_plan

    service = repair_service(tmp_path)
    record = service.record
    await service._prepare_evidence_snapshot(record, phase="analysis")
    for competitor in record.detail.plan.competitors:
        for dimension in record.detail.plan.dimensions:
            await service._real_analyst_branch_step(record, dimension, competitor)
    await service._real_comparator_step(record)

    async def draft(draft_record):
        draft_record.detail.report_md = "## Findings\nCaptured [source:Phone-X-pricing]"

    service._write_report_draft = draft
    await service._real_writer_step(record)
    payload = service._writer_evidence_artifact_payload(record.detail)
    assert service._evidence_artifact_valid(record, kind="writer", payload=payload)
    before = [item.model_dump(mode="json") for item in record.detail.raw_sources]
    record.detail.comparison_matrix.summary.append("Decision corrected: global positioning")
    assert not service._evidence_artifact_valid(record, kind="writer", payload=payload)
    assert [item.model_dump(mode="json") for item in record.detail.raw_sources] == before
    _, issues, _ = await service._final_qa_evidence(record)
    assert any(
        item.metadata.get("evidence_reason") == "writer_producer_unverified"
        and item.metadata.get("unpublishable_evidence")
        for item in issues
    )
    plan = build_writer_repair_plan(record.detail, [], upstream_data_changed=True)
    assert plan.mode == "full"
    from types import MethodType

    from packages.agents.writer.logic import WriterAgentMixin

    service._write_report_draft = MethodType(WriterAgentMixin._write_report_draft, service)
    from types import SimpleNamespace

    monkeypatch.setattr(
        "packages.agents.writer.logic.build_writer_evidence_pack",
        lambda detail: SimpleNamespace(
            telemetry_payload=lambda: {}, preflight_errors=lambda: ["test_missing_dependency"]
        ),
    )
    with pytest.raises(RuntimeError, match="preflight failed"):
        await service._real_writer_step(record)
    actual = [item for item in record.events if "writer_repair_mode" in item.payload]
    assert actual[-1].payload["writer_repair_mode"] == "full"
    assert actual[-1].payload["writer_repair_sections"] == []


@pytest.mark.asyncio
async def test_cache_key_is_scoped_and_covers_market_original_dates_and_status(tmp_path):
    service = repair_service(tmp_path)
    detail = service.record.detail
    await service._prepare_evidence_snapshot(service.record, phase="analysis")
    before = service._kb_cache_content_hash(detail, "Phone X", "pricing")
    for field, value in [("workspace_id", "other-workspace"), ("project_id", "other-project")]:
        original = getattr(detail, field)
        setattr(detail, field, value)
        with pytest.raises(EvidenceUseRejectedError):
            service._kb_cache_content_hash(detail, "Phone X", "pricing")
        setattr(detail, field, original)
    detail.raw_sources[0].metadata["normalized_fields"][0]["market"] = "US"
    await service._prepare_evidence_snapshot(service.record, phase="analysis")
    market_key = service._kb_cache_content_hash(detail, "Phone X", "pricing")
    assert market_key != before
    detail.raw_sources[0].metadata["last_verified_at"] = "2020-01-01T00:00:00+00:00"
    await service._prepare_evidence_snapshot(service.record, phase="analysis")
    assert service._kb_cache_content_hash(detail, "Phone X", "pricing") != market_key


@pytest.mark.asyncio
async def test_writer_only_redo_keeps_accepted_snapshot(tmp_path):
    service = repair_service(tmp_path)
    record = service.record
    snapshot = await service._prepare_evidence_snapshot(record, phase="analysis")

    async def draft(draft_record):
        draft_record.detail.report_md = "Reworded [source:Phone-X-pricing]"

    service._write_report_draft = draft
    service._prepare_redo_scope_inputs(
        record.detail, RedoScope(kind="writer_only", rationale="reword")
    )
    await service._real_writer_step(record)
    assert record.detail.evidence_snapshot_id == snapshot.id
    assert len(record.detail.evidence_snapshots) == 1
    assert all(item.snapshot_id == snapshot.id for item in record.detail.evidence_consumptions)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata", [{"producer_consumption_ids": ()}, {"producer_snapshot_id": "unknown-snapshot"}]
)
async def test_legacy_cache_without_producer_metadata_is_a_conservative_miss(tmp_path, metadata):
    service = repair_service(tmp_path)
    record = service.record
    await service._prepare_evidence_snapshot(record, phase="analysis")
    await service._real_analyst_branch_step(record, "pricing", "Phone X")
    key = service._kb_cache_content_hash(record.detail, "Phone X", "pricing")
    entry = service._kb_cache.get("Phone X", "pricing", key)
    service._kb_cache.put(entry.model_copy(update=metadata))
    service._kb_cache = KBCache(tmp_path / "cache.db")
    await service._real_analyst_branch_step(record, "pricing", "Phone X")
    assert len([item for item in service.inputs if item["agent"] == "analyst"]) == 2


@pytest.mark.asyncio
async def test_canonical_status_revokes_actual_view_and_cached_producer(tmp_path, monkeypatch):
    from packages.knowledge.models import DocumentCreate
    from packages.knowledge.repository import KnowledgeRepository

    service = repair_service(tmp_path)
    record = service.record
    monkeypatch.setenv("KB_DB_PATH", str(tmp_path / "knowledge.db"))
    source = record.detail.raw_sources[0]
    async with KnowledgeRepository() as repo:
        doc = await repo.upsert_document(
            DocumentCreate(
                workspace_id=record.detail.workspace_id,
                project_id=record.detail.project_id,
                competitor=source.competitor,
                dimension=source.dimension,
                title=source.title,
                source_type=source.source_type,
                text="3999 CNY official pricing",
                metadata={"normalized_fields": source.metadata["normalized_fields"]},
            ),
            "canonical-price-body",
        )
    source.metadata.update(
        {
            "kb_document_id": doc.id,
            "kb_document_version": doc.version,
            "kb_document_content_hash": doc.content_hash,
        }
    )
    await service._prepare_evidence_snapshot(record, phase="analysis")
    await service._real_analyst_branch_step(record, "pricing", "Phone X")
    before = service._kb_cache_content_hash(record.detail, "Phone X", "pricing")
    assert before
    async with KnowledgeRepository() as repo:
        await repo._connection.execute(
            "UPDATE documents SET status = 'archived', is_active = 0 WHERE id = ?", (doc.id,)
        )
        await repo._connection.commit()
    await service._prepare_evidence_snapshot(record, phase="analysis")
    view, _ = service._begin_evidence_use(
        record, agent="analyst", competitor="Phone X", dimension="pricing"
    )
    assert source.id not in view.source_ids
    assert service._kb_cache_content_hash(record.detail, "Phone X", "pricing") != before
    assert "pricing" not in record.detail.competitor_kbs["Phone X"].slices


@pytest.mark.asyncio
async def test_cache_scope_and_market_changes_call_real_model_again(tmp_path):
    service = repair_service(tmp_path)
    record = service.record
    await service._prepare_evidence_snapshot(record, phase="analysis")
    await service._real_analyst_branch_step(record, "pricing", "Phone X")
    for field, value in [
        ("workspace_id", "isolated-workspace"),
        ("project_id", "isolated-project"),
    ]:
        setattr(record.detail, field, value)
        await service._prepare_evidence_snapshot(record, phase="analysis")
        await service._real_analyst_branch_step(record, "pricing", "Phone X")
    record.detail.raw_sources[0].metadata["normalized_fields"][0]["market"] = "US"
    await service._prepare_evidence_snapshot(record, phase="analysis")
    await service._real_analyst_branch_step(record, "pricing", "Phone X")
    assert len([item for item in service.inputs if item["agent"] == "analyst"]) == 4


@pytest.mark.asyncio
async def test_full_redo_blocks_old_producer_until_new_evidence_is_sealed(tmp_path):
    service = repair_service(tmp_path)
    record = service.record
    await service._prepare_evidence_snapshot(record, phase="analysis")
    _, use = service._begin_evidence_use(
        record, agent="analyst", competitor="Phone X", dimension="pricing"
    )
    service._prepare_redo_scope_inputs(
        record.detail, RedoScope(kind="full", rationale="replace evidence")
    )
    with pytest.raises(EvidenceUseRejectedError):
        service._validate_evidence_use(record, use)


@pytest.mark.asyncio
async def test_real_collector_readmits_refetched_stable_id_after_server_retirement(
    tmp_path, monkeypatch
):
    from packages.schema.models import TargetProduct
    from packages.tools.evidence_fetch import EvidenceFetchResult
    from packages.tools.source_discovery import SourceCandidate

    service = repair_service(tmp_path)
    record = service.record
    record.detail.raw_sources = []
    record.detail.plan.target_product = TargetProduct(name="Phone X", market="CN", category="phone")
    monkeypatch.setenv("KB_DB_PATH", str(tmp_path / "knowledge.db"))
    url = "https://phone-x.example/pricing"
    calls = []

    async def fetch(record, agent, subagent, target_url, context=None, **kwargs):
        calls.append(target_url)
        return EvidenceFetchResult(
            url=target_url,
            ok=True,
            title="Phone X pricing",
            text="Phone X price starts at CNY 3999 for the base tier in CN.\n" * 12,
            content_hash="fixed-official-body",
            status_code=200,
            fetch_method="test_fetch",
            quality_score=0.96,
            text_length=720,
        )

    async def no_kb(*args, **kwargs):
        return []

    async def collect(record, dimension, competitor, context, **kwargs):
        return await service._collect_competitor_with_research_pipeline(
            record,
            record.detail,
            dimension,
            competitor,
            context,
            batch_sources=[],
            target_source_count=1,
            include_official=False,
            seed_candidates=[
                SourceCandidate(
                    title="Phone X pricing",
                    url=url,
                    origin="manual",
                    competitor=competitor,
                    dimension=dimension,
                    rank=0,
                    confidence=0.95,
                )
            ],
            enable_search=False,
            enable_repair=False,
        )

    service._trace_fetch = fetch
    service._collect_competitor_from_kb = no_kb
    service._collect_competitor_with_web_search = collect
    service._collect_community_sources_for_branch = no_kb
    await service._real_collector_branch_step(record, "pricing", "Phone X")
    assert len(record.detail.raw_sources) == 1
    first_source = record.detail.raw_sources[0].model_copy(deep=True)
    first = await service._prepare_evidence_snapshot(record, phase="analysis")
    record.detail.report_md = f"Original [source:{first_source.id}]"
    service._prepare_redo_scope_inputs(
        record.detail,
        RedoScope(
            kind="collector",
            target_subagent="pricing",
            target_competitor="Phone X",
            rationale="refetch current pricing",
        ),
    )
    await service._real_collector_branch_step(record, "pricing", "Phone X")
    record.detail.raw_sources = service._normalize_collected_sources(record.detail, ["pricing"])
    current = await service._prepare_evidence_snapshot(record, phase="analysis")
    view, _ = service._begin_evidence_use(
        record, agent="analyst", competitor="Phone X", dimension="pricing"
    )
    assert calls == [url, url]
    assert first_source.id in view.source_ids
    assert first_source.id not in record.detail.evidence_retired_source_ids
    assert len(record.detail.raw_sources) == 1
    assert record.detail.raw_sources[0].content_hash == first_source.content_hash
    assert (
        record.detail.raw_sources[0].metadata["fetched_at"] != first_source.metadata["fetched_at"]
    )
    assert not record.detail.raw_sources[0].metadata.get("redo_preserved_for_existing_citation")
    assert current.version > first.version
    assert record.detail.evidence_snapshots[0] == first


@pytest.mark.asyncio
async def test_trusted_research_target_market_changes_cache_identity_and_actual_model_call(
    tmp_path,
):
    from packages.schema.models import TargetProduct

    service = repair_service(tmp_path)
    record = service.record
    record.detail.plan.target_product = TargetProduct(name="Phone X", market="CN", category="phone")
    await service._prepare_evidence_snapshot(record, phase="analysis")
    await service._real_analyst_branch_step(record, "pricing", "Phone X")
    old = service._kb_cache_content_hash(record.detail, "Phone X", "pricing")
    record.detail.plan.target_product.market = "US"
    assert service._kb_cache_content_hash(record.detail, "Phone X", "pricing") != old
    await service._real_analyst_branch_step(record, "pricing", "Phone X")
    assert len([item for item in service.inputs if item["agent"] == "analyst"]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("price_changed", [True, False])
async def test_collect_to_analysis_compares_last_accepted_analysis(
    tmp_path, monkeypatch, price_changed
):
    from types import MethodType, SimpleNamespace

    from packages.agents.writer.logic import WriterAgentMixin
    from packages.research.evidence.snapshot import changed_evidence

    service = repair_service(tmp_path)
    record = service.record
    original = await service._prepare_evidence_snapshot(record, phase="analysis")
    for competitor in record.detail.plan.competitors:
        for dimension in record.detail.plan.dimensions:
            await service._real_analyst_branch_step(record, dimension, competitor)
    await service._real_comparator_step(record)

    async def draft(draft_record):
        draft_record.detail.report_md = "## Findings\nCaptured [source:Phone-X-pricing]"

    service._write_report_draft = draft
    await service._real_writer_step(record)
    original_dependencies = tuple(record.detail.evidence_artifact_dependencies)
    original_sources = [item.model_dump(mode="json") for item in record.detail.raw_sources]
    b_dependency = next(
        item
        for item in original_dependencies
        if (item.kind, item.competitor, item.dimension) == ("analyst", "Phone X Pro", "feature")
    )
    b_payload = service._analyst_evidence_artifact_payload(record.detail, "Phone X Pro", "feature")
    history = original.model_dump_json()
    if price_changed:
        source = record.detail.raw_sources[0]
        source.metadata = copy.deepcopy(source.metadata)
        source.metadata["normalized_fields"][0]["price"] = 4299
        source.metadata["normalized_fields"][0]["source_quote"] = "4299 CNY"
    collect = await service._prepare_evidence_snapshot(record, phase="collect")
    with pytest.raises(EvidenceUseRejectedError):
        await service._real_analyst_branch_step(record, "pricing", "Phone X")
    accepted = await service._prepare_evidence_snapshot(record, phase="analysis")
    assert not changed_evidence(collect, accepted).changed_sources
    assert record.detail.evidence_snapshots[0].model_dump_json() == history
    assert (
        service._analyst_evidence_artifact_payload(record.detail, "Phone X Pro", "feature")
        == b_payload
    )
    assert (
        next(
            item
            for item in record.detail.evidence_artifact_dependencies
            if (item.kind, item.competitor, item.dimension) == ("analyst", "Phone X Pro", "feature")
        )
        == b_dependency
    )
    assert record.detail.raw_sources[-1].model_dump(mode="json") == original_sources[-1]
    if price_changed:
        assert changed_evidence(original, accepted).changed_sources
        assert "pricing" not in record.detail.competitor_kbs["Phone X"].slices
        assert not any(
            item.competitor == "Phone X" and item.dimension == "pricing"
            for item in record.detail.claim_card_bundles
        )
        assert record.detail.comparison_matrix is None
        assert record.detail.decision_card_bundle is None
        assert record.detail.evidence_writer_rewrite_required
        assert all(
            next(
                item for item in record.detail.evidence_consumptions if item.id == use_id
            ).validated_snapshot_id
            == accepted.id
            for use_id in b_dependency.consumption_ids
        )
        service._write_report_draft = MethodType(WriterAgentMixin._write_report_draft, service)
        monkeypatch.setattr(
            "packages.agents.writer.logic.build_writer_evidence_pack",
            lambda detail: SimpleNamespace(
                telemetry_payload=lambda: {}, preflight_errors=lambda: ["test_gap"]
            ),
        )
        with pytest.raises(RuntimeError, match="preflight failed"):
            await service._real_writer_step(record)
        event = next(
            item for item in reversed(record.events) if "writer_repair_mode" in item.payload
        )
        assert event.payload["writer_repair_mode"] == "full"
        assert event.payload["writer_repair_sections"] == []
    else:
        assert tuple(record.detail.evidence_artifact_dependencies) == original_dependencies
        assert record.detail.comparison_matrix is not None
        assert not record.detail.evidence_writer_rewrite_required
        assert service._evidence_artifact_valid(
            record, kind="analyst", competitor="Phone X Pro", dimension="feature", payload=b_payload
        )
        assert all(
            next(
                item for item in record.detail.evidence_consumptions if item.id == use_id
            ).validated_snapshot_id
            == accepted.id
            for use_id in b_dependency.consumption_ids
        )
