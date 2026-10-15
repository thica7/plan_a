from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from langgraph.types import Command
from test_evidence_snapshot_graph import ReplayService
from test_fact_market_provenance import (
    isolated_storage_and_network,  # noqa: F401 - apply the isolated-storage fixture
    local_chain,
    service_record,
    source_text,
)

# isort: split
from packages.knowledge.models import DocumentCreate, KnowledgeScope
from packages.knowledge.repository import KnowledgeRepository
from packages.memory import RunJournal
from packages.orchestrator.evidence_context import EvidenceUseRejectedError
from packages.orchestrator.graph import build_scoped_redo_graph
from packages.research.evidence import snapshot as snapshot_module
from packages.research.evidence.answer_guard import evaluate_answer_boundary
from packages.research.evidence.answer_models import AnswerRequirement
from packages.research.evidence.snapshot import current_snapshot
from packages.research.evidence.snapshot_models import (
    EvidenceArtifactDependency,
    EvidenceConsumption,
)
from packages.research.evidence.views import select_evidence_view
from packages.schema.models import QCIssue, RedoScope


def seal_legacy_directory_policy(monkeypatch, detail, document, *, phase="analysis"):
    """Construct the pre-fix policy with a valid hash; never mutate saved history."""
    fields = snapshot_module._fields

    def legacy_fields(source, allowed):
        rows = fields(source, allowed)
        for row in rows:
            row["market"] = document.market
        return rows

    with monkeypatch.context() as patch:
        patch.setattr(snapshot_module, "_fields", legacy_fields)
        legacy = snapshot_module.seal_snapshot(
            detail, phase=phase, canonical_documents={document.id: document}
        )
    # A missing policy is the historical wire format, including its own hash.
    if hasattr(legacy, "fact_market_policy_version"):
        legacy = legacy.model_copy(update={"fact_market_policy_version": None})
        legacy = legacy.model_copy(
            update={"content_hash": snapshot_module._digest(snapshot_module._contract(legacy))}
        )
        legacy = legacy.model_copy(update={"id": snapshot_module._snapshot_id(legacy)})
        detail.evidence_snapshots = [legacy]
        detail.evidence_snapshot_id = legacy.id
    return legacy


async def seed_legacy(tmp_path, monkeypatch, *, market=None, dimension="pricing", phase="analysis"):
    result, sources = await local_chain(monkeypatch, source_text(market))
    source = sources[0]
    service, record = service_record(tmp_path, sources)
    record.detail.current_node = "writer"
    record.detail.plan.dimensions = [dimension]
    if dimension != "pricing":
        source.dimension = dimension
        quote = (
            "Acme supports document comments." if dimension == "feature"
            else "Acme serves developers."
        )
        if market:
            quote += f" market: {market}."
        source.snippet = quote
        source.metadata["normalized_fields"] = [{
            "kind": dimension, "dimension": dimension, "competitor": "Acme",
            "market": market, "evidence_quote": quote, "evidence_item_ids": ["original"],
            "confidence": source.confidence,
            **({"slot": "comments", "support_level": "supported"}
               if dimension == "feature" else {"role": "developers"}),
        }]
    async with KnowledgeRepository() as repo:
        document = await repo.upsert_document(
            DocumentCreate(
                workspace_id=record.detail.workspace_id,
                project_id=record.detail.project_id,
                competitor=source.competitor, dimension=source.dimension,
                market="US", source_role="source", url=str(source.url), title=source.title,
                text=result.captured_pages[0].text if dimension == "pricing" else source.snippet,
                source_type=source.source_type, fetched_at=source.extracted_at,
                last_verified_at=source.extracted_at,
                metadata={"source_material_level": "full_source"},
            ),
            "legacy-directory-hash",
        )
    source.metadata.update(
        kb_document_id=document.id, kb_document_version=document.version,
        kb_document_content_hash=document.content_hash,
    )
    legacy = seal_legacy_directory_policy(monkeypatch, record.detail, document, phase=phase)
    assert {fact.market for fact in legacy.facts} == {"US"}
    assert {
        row["market"] for row in legacy.sources[0].to_raw_source().metadata["normalized_fields"]
    } == {"US"}, "Legacy projections also lost the original row market"
    service._journal.save_run(record.detail)
    return service, record, legacy


def legacy_use(record, legacy, *, agent="writer"):
    view = select_evidence_view(legacy, agent=agent, competitor="Acme", dimension="pricing")
    use = EvidenceConsumption(
        id="legacy-producer", run_id=record.detail.id,
        workspace_id=record.detail.workspace_id, project_id=record.detail.project_id,
        agent=agent, snapshot_id=legacy.id, snapshot_version=legacy.version,
        dependency_hash=view.dependency_hash, competitor="Acme", dimension="pricing",
        source_ids=view.source_ids, fact_ids=view.fact_ids, max_bytes=view.max_bytes,
        status="validated", created_at=legacy.created_at,
    )
    record.detail.evidence_consumptions.append(use)
    return use


@pytest.mark.asyncio
@pytest.mark.parametrize("market", [None, "CN", "US"])
async def test_reopened_accepted_legacy_snapshot_is_upgraded_once(
    tmp_path, monkeypatch, market
):
    service, record, legacy = await seed_legacy(tmp_path, monkeypatch, market=market)
    record.detail.report_md = "Legacy price report"
    use = legacy_use(record, legacy)
    record.detail.evidence_artifact_dependencies = [EvidenceArtifactDependency(
        kind="writer", consumption_ids=(use.id,),
        payload_hash=service._evidence_artifact_hash(
            service._writer_evidence_artifact_payload(record.detail)
        ), upstream_hash=service._artifact_upstream_hash(record.detail, "writer"),
    )]
    service._journal.save_run(record.detail)
    historical = legacy.model_dump_json()
    reopened = ReplayService(RunJournal(tmp_path / "journal.db"))
    restored = reopened.record
    raw_before = restored.detail.raw_sources[0].model_dump_json()

    refreshed = await reopened._ensure_analysis_evidence(restored)

    assert refreshed.id != legacy.id and refreshed.version == legacy.version + 1
    assert refreshed.parent_id == legacy.id
    view, _ = reopened._begin_evidence_use(
        restored, agent="writer", competitor="Acme", dimension="pricing"
    )
    assert {fact.market for fact in view.facts} == {market}
    requirement = AnswerRequirement(
        competitor="Acme", dimension="pricing", intent="current_price", market="US",
        as_of=datetime.now(UTC).date(),
    )
    if market is None:
        legacy_view = select_evidence_view(
            legacy, agent="writer", competitor="Acme", dimension="pricing"
        )
        assert evaluate_answer_boundary(legacy_view, requirement).status == "answer"
    boundary = evaluate_answer_boundary(view, requirement)
    assert boundary.status == ("answer" if market == "US" else "insufficient")
    if market is None:
        assert "market" in boundary.missing_fields
    if market != "US":
        assert restored.detail.evidence_writer_rewrite_required
        assert restored.detail.evidence_consumptions[0].status == "rejected"
    assert restored.detail.evidence_snapshots[0].model_dump_json() == historical
    assert restored.detail.raw_sources[0].model_dump_json() == raw_before

    async def forbid(*args, **kwargs):
        raise AssertionError("A current accepted snapshot must be reused")

    monkeypatch.setattr(reopened, "_prepare_evidence_snapshot", forbid)
    assert (await reopened._ensure_analysis_evidence(restored)).id == refreshed.id
    persisted = RunJournal(tmp_path / "journal.db").load_run(restored.detail.id)
    assert persisted.evidence_snapshots[0].model_dump_json() == historical
    await service._graph_checkpointer.aclose()
    await reopened._graph_checkpointer.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("dimension", ["feature", "persona"])
@pytest.mark.parametrize("market", [None, "CN"])
async def test_accepted_legacy_nonpricing_facts_are_resealed_from_original_rows(
    tmp_path, monkeypatch, dimension, market
):
    service, record, legacy = await seed_legacy(
        tmp_path, monkeypatch, market=market, dimension=dimension
    )
    historical = legacy.model_dump_json()
    refreshed = await service._ensure_analysis_evidence(record)
    assert refreshed.id != legacy.id
    assert {fact.market for fact in refreshed.facts} == {market}
    assert record.detail.evidence_snapshots[0].model_dump_json() == historical
    await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("agent", ["analyst", "comparator", "reflector", "writer", "qa"])
async def test_synchronous_new_consumption_rejects_old_market_policy(tmp_path, monkeypatch, agent):
    service, record, legacy = await seed_legacy(tmp_path, monkeypatch)
    historical = legacy.model_dump_json()
    with pytest.raises(EvidenceUseRejectedError, match="policy|reseal"):
        service._begin_evidence_use(record, agent=agent)
    assert record.detail.evidence_snapshots[0].model_dump_json() == historical
    await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_old_producer_cannot_commit_against_legacy_policy(tmp_path, monkeypatch):
    service, record, legacy = await seed_legacy(tmp_path, monkeypatch)
    use = legacy_use(record, legacy)
    with pytest.raises(EvidenceUseRejectedError, match="policy|reseal"):
        service._validate_evidence_use(record, use)
    assert record.detail.evidence_consumptions[0].status == "rejected"
    await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", [
    "planner_hitl", "collector", "collector_dispatch", "collect_join", "collect_qa",
    "survey_interview", "evidence_hitl", "refresh", "dirty", "collect_phase",
    "workspace", "project",
])
async def test_legacy_upgrade_cannot_accept_unreviewed_inputs_or_cross_scope(
    tmp_path, monkeypatch, case
):
    service, record, legacy = await seed_legacy(
        tmp_path, monkeypatch, phase="collect" if case == "collect_phase" else "analysis"
    )
    if case == "refresh":
        record.detail.evidence_refresh_active = True
    elif case == "dirty":
        record.detail.evidence_inputs_dirty = True
        record.detail.raw_sources.append(
            record.detail.raw_sources[0].model_copy(update={"id": "new"})
        )
    elif case == "workspace":
        record.detail.workspace_id = "another-workspace"
    elif case == "project":
        record.detail.project_id = "another-project"
    elif case != "collect_phase":
        record.detail.current_node = case
    history = [item.model_dump_json() for item in record.detail.evidence_snapshots]

    with pytest.raises(EvidenceUseRejectedError):
        await service._ensure_analysis_evidence(record)

    assert [item.model_dump_json() for item in record.detail.evidence_snapshots] == history
    assert record.detail.evidence_snapshot_id == legacy.id
    await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_concurrent_legacy_upgrades_share_one_new_snapshot(tmp_path, monkeypatch):
    service, record, legacy = await seed_legacy(tmp_path, monkeypatch)
    document_lookup = KnowledgeRepository.get_document
    entered = 0
    ready = asyncio.Event()

    async def concurrent_lookup(repo, *args, **kwargs):
        nonlocal entered
        entered += 1
        if entered == 2:
            ready.set()
        await asyncio.wait_for(ready.wait(), timeout=3)
        return await document_lookup(repo, *args, **kwargs)

    monkeypatch.setattr(KnowledgeRepository, "get_document", concurrent_lookup)
    snapshots = await asyncio.gather(
        service._ensure_analysis_evidence(record), service._ensure_analysis_evidence(record)
    )
    assert entered == 2
    assert snapshots[0].id == snapshots[1].id != legacy.id
    assert len(record.detail.evidence_snapshots) == 2
    await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["dirty", "source", "evidence_hitl"])
async def test_upgrade_rejects_inputs_changed_while_canonical_lookup_waits(
    tmp_path, monkeypatch, change
):
    service, record, legacy = await seed_legacy(tmp_path, monkeypatch)
    document_lookup = KnowledgeRepository.get_document
    entered = asyncio.Event()
    resume = asyncio.Event()

    async def paused_lookup(repo, *args, **kwargs):
        entered.set()
        await asyncio.wait_for(resume.wait(), timeout=3)
        return await document_lookup(repo, *args, **kwargs)

    monkeypatch.setattr(KnowledgeRepository, "get_document", paused_lookup)
    upgrade = asyncio.create_task(service._ensure_analysis_evidence(record))
    await asyncio.wait_for(entered.wait(), timeout=3)
    if change == "dirty":
        record.detail.evidence_inputs_dirty = True
    elif change == "source":
        record.detail.raw_sources.append(
            record.detail.raw_sources[0].model_copy(update={"id": "unreviewed-source"})
        )
    else:
        record.detail.current_node = change
    resume.set()
    with pytest.raises(EvidenceUseRejectedError, match="accepted|inputs"):
        await upgrade
    assert record.detail.evidence_snapshot_id == legacy.id
    assert len(record.detail.evidence_snapshots) == 1
    if change == "dirty":
        assert record.detail.evidence_inputs_dirty
    await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["source", "body"])
async def test_upgrade_cannot_add_unaccepted_source_or_body_even_without_dirty_flag(
    tmp_path, monkeypatch, change
):
    service, record, legacy = await seed_legacy(tmp_path, monkeypatch)
    if change == "source":
        record.detail.raw_sources.append(
            record.detail.raw_sources[0].model_copy(update={"id": "unreviewed-source"})
        )
    else:
        record.detail.raw_sources[0].content_hash = "unreviewed-body"
    assert not record.detail.evidence_inputs_dirty
    with pytest.raises(EvidenceUseRejectedError, match="accepted"):
        await service._ensure_analysis_evidence(record)
    assert record.detail.evidence_snapshot_id == legacy.id
    assert len(record.detail.evidence_snapshots) == 1
    await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["writer_only", "comparator"])
async def test_scoped_redo_upgrades_accepted_legacy_policy_before_consumption(
    tmp_path, monkeypatch, kind
):
    original, _, legacy = await seed_legacy(tmp_path, monkeypatch)
    service = ReplayService(RunJournal(tmp_path / "journal.db"))
    seen = []

    async def consume(record):
        view, use = service._begin_evidence_use(record, agent="writer")
        seen.append(view.snapshot_id)
        assert {fact.market for fact in view.facts} == {None}
        service._validate_evidence_use(record, use)

    monkeypatch.setattr(service, "_real_writer_step", consume)
    result = await build_scoped_redo_graph(service).ainvoke({
        "run_id": service.record.detail.id, "redo_kind": kind,
    })
    snapshot = current_snapshot(service.record.detail)
    assert seen == [snapshot.id] and snapshot.id != legacy.id
    assert result["evidence_snapshot_id"] == snapshot.id
    assert len(service.record.detail.evidence_snapshots) == 2
    await original._graph_checkpointer.aclose()
    await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["writer_only", "comparator"])
@pytest.mark.parametrize("case", ["dirty", "evidence_hitl"])
async def test_scoped_redo_without_snapshot_cannot_accept_pending_sources(
    tmp_path, monkeypatch, kind, case
):
    original, record, _ = await seed_legacy(tmp_path, monkeypatch)
    record.detail.evidence_snapshots = []
    record.detail.evidence_snapshot_id = None
    if case == "dirty":
        record.detail.evidence_inputs_dirty = True
    else:
        record.detail.current_node = case
    original._journal.save_run(record.detail)
    service = ReplayService(RunJournal(tmp_path / "journal.db"))
    with pytest.raises(EvidenceUseRejectedError, match="accepted"):
        await build_scoped_redo_graph(service).ainvoke({
            "run_id": service.record.detail.id, "redo_kind": kind,
        })
    assert service.record.detail.evidence_snapshots == []
    await original._graph_checkpointer.aclose()
    await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["real", "demo", "scoped_redo"])
async def test_service_graph_resume_upgrades_before_new_consumption(tmp_path, monkeypatch, kind):
    original, _, legacy = await seed_legacy(tmp_path, monkeypatch)
    service = ReplayService(RunJournal(tmp_path / "journal.db"))
    record = service.record
    history = legacy.model_dump_json()
    invoked = []

    async def invoke(command, **kwargs):
        invoked.append(command.update["evidence_snapshot_id"])
        view, use = service._begin_evidence_use(record, agent="writer")
        assert {fact.market for fact in view.facts} == {None}
        service._validate_evidence_use(record, use)
        return {}

    setattr(service, f"_{kind}_graph", SimpleNamespace(ainvoke=invoke))
    command = Command(resume={"decision": "accept"}, update={"run_id": record.detail.id})
    assert await service._invoke_graph(
        record, kind=kind, thread_id=record.detail.id, graph_input=command
    )
    snapshot = current_snapshot(record.detail)
    assert snapshot.id != legacy.id and snapshot.version == legacy.version + 1
    assert invoked == [snapshot.id]
    assert record.detail.evidence_snapshots[0].model_dump_json() == history
    assert await service._invoke_graph(
        record, kind=kind, thread_id=record.detail.id, graph_input=command
    )
    assert invoked == [snapshot.id, snapshot.id]
    assert len(record.detail.evidence_snapshots) == 2
    await original._graph_checkpointer.aclose()
    await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_historical_gap_body_requires_formal_acceptance_before_actual_writer(
    tmp_path, monkeypatch
):
    original, record, _ = await seed_legacy(tmp_path, monkeypatch)
    source = record.detail.raw_sources[0]
    async with KnowledgeRepository() as repo:
        document = await repo.get_document(
            source.metadata["kb_document_id"],
            scope=KnowledgeScope(
                workspace_id=record.detail.workspace_id, project_id=record.detail.project_id
            ),
        )
    rejected = source.model_copy(
        deep=True, update={"id": "historical-gap", "covered_competitors": ["unplanned"]}
    )
    rejected.content_hash = hashlib.sha256(source_text(None).encode()).hexdigest()
    record.detail.raw_sources.append(rejected)
    record.detail.evidence_snapshots = []
    record.detail.evidence_snapshot_id = None
    legacy = seal_legacy_directory_policy(monkeypatch, record.detail, document)
    assert any(gap.source_id == rejected.id for gap in legacy.gaps)
    assert rejected.id not in {item.id for item in legacy.sources}
    history = legacy.model_dump_json()

    _, replacements = await local_chain(monkeypatch, source_text("US"))
    replacement = replacements[0].model_copy(deep=True, update={"id": rejected.id})
    replacement.content_hash = hashlib.sha256(source_text("US").encode()).hexdigest()
    assert replacement.content_hash != rejected.content_hash
    record.detail.raw_sources[-1] = replacement
    record.detail.plan.answer_requirements = [AnswerRequirement(
        competitor="Acme", dimension="pricing", intent="current_price", market="US",
        as_of=datetime.now(UTC).date(),
    )]
    record.detail.plan.collaboration_mode = "assisted"
    assert not record.detail.evidence_inputs_dirty
    original._journal.save_run(record.detail)
    service = ReplayService(RunJournal(tmp_path / "journal.db"))
    record = service.record
    generated = []

    async def generate(record, **kwargs):
        generated.append(kwargs["user"])
        return "Evidence reviewed."

    monkeypatch.setattr(service, "_trace_llm_text", generate)

    async def write(record):
        await service._writer_segment_markdown(
            record,
            segment={"segment_name": "competitor_deep_dives", "segment_competitor": "Acme",
                     "dimension": "pricing", "allowed_source_ids": [replacement.id]},
            timeout_seconds=5, language_guidance="", memory_context="", layer_context="",
            required_sections="", retry_count=0,
        )

    with pytest.raises(EvidenceUseRejectedError, match="accepted"):
        await write(record)
    assert not generated and not record.detail.report_answer_boundaries
    assert record.detail.evidence_snapshot_id == legacy.id
    assert record.detail.evidence_snapshots[0].model_dump_json() == history

    # Full redo reaches the real Graph acceptance nodes before the Writer can
    # consume the replacement body. External generation remains deterministic.
    monkeypatch.setattr(service, "_real_writer_step", write)
    assert await service._invoke_graph(
        record, kind="scoped_redo", thread_id=record.detail.id,
        graph_input={"run_id": record.detail.id, "redo_kind": "full"},
    )
    assert service.review_count == 1
    boundary = record.detail.report_answer_boundaries[-1]
    assert boundary.status == "answer" and boundary.allowed_fact_ids
    assert len(generated) == 1
    assert {fact.market for fact in current_snapshot(record.detail).facts
            if fact.source_id == replacement.id} == {"US"}
    assert record.detail.evidence_snapshots[0].model_dump_json() == history
    await original._graph_checkpointer.aclose()
    await service._graph_checkpointer.aclose()


async def paused_actual_qa_graph(
    tmp_path, monkeypatch, *, current_policy=False, issues=True, redo_kind="full",
    final_qa_attempts=0,
):
    service, record, _ = await seed_legacy(tmp_path, monkeypatch)
    source = record.detail.raw_sources[0]
    async with KnowledgeRepository() as repo:
        document = await repo.get_document(
            source.metadata["kb_document_id"],
            scope=KnowledgeScope(
                workspace_id=record.detail.workspace_id, project_id=record.detail.project_id
            ),
        )
    gap_source = source.model_copy(
        deep=True, update={"id": "unchanged-gap", "covered_competitors": ["unplanned"]}
    )
    record.detail.raw_sources.append(gap_source)
    record.detail.evidence_snapshots = []
    record.detail.evidence_snapshot_id = None
    legacy = seal_legacy_directory_policy(monkeypatch, record.detail, document)
    if current_policy:
        await service._prepare_evidence_snapshot(record, phase="analysis")
    record.detail.hitl_enabled = True
    record.detail.plan.collaboration_mode = "assisted"
    record.detail.current_node = "qa_hitl"
    record.detail.qa_findings = [QCIssue(
        id="redo-full", severity="blocker", detected_by="coverage", target_agent="orchestrator",
        field_path="report", problem="Recollect and formally accept evidence",
        redo_scope=RedoScope(kind=redo_kind, rationale="Recollect evidence"),
    )] if issues else []
    service._persist_run(record.detail.id)
    graph = await service._get_real_graph()
    config = {"configurable": {"thread_id": record.detail.id}}
    await graph.aupdate_state(config, {
        "run_id": record.detail.id, "evidence_snapshot_id": record.detail.evidence_snapshot_id,
        "dimensions": record.detail.plan.dimensions,
        "target_competitors": record.detail.plan.competitors,
        "final_qa_attempts": final_qa_attempts,
    }, as_node="qa")
    first = await graph.ainvoke(None, config=config)
    assert first.get("__interrupt__") and "qa" in record.pending_interrupts
    assert record.detail.current_node == "qa_hitl"
    service._cancel_hitl_timeout(record)
    return service, record, legacy, graph


@pytest.mark.asyncio
@pytest.mark.parametrize("redo_kind", ["full", "collector"])
async def test_actual_paused_qa_redo_reaches_formal_acceptance_before_writer(
    tmp_path, monkeypatch, redo_kind
):
    service, record, legacy, graph = await paused_actual_qa_graph(
        tmp_path, monkeypatch, redo_kind=redo_kind
    )
    history = legacy.model_dump_json()
    original_gap = record.detail.raw_sources[-1].model_dump_json()
    assert not record.detail.evidence_inputs_dirty
    generated = []

    async def noop(*args, **kwargs):
        pass

    for name in (
        "_real_planner_step", "_real_planner_hitl_step", "_real_collector_dispatch_step",
        "_real_collect_join_step", "_run_survey_interview_enrichment", "_real_phase_qa_step",
        "_real_analyst_dispatch_step", "_real_analyst_branch_step", "_real_analyst_join_step",
        "_real_comparator_step", "_real_reflector_step", "_real_qa_step",
    ):
        monkeypatch.setattr(service, name, noop)

    async def collect(record, *args, **kwargs):
        _, sources = await local_chain(monkeypatch, source_text("US"))
        record.detail.raw_sources = sources

    async def generate(record, **kwargs):
        generated.append(kwargs["user"])
        return "Evidence reviewed."

    async def write(record):
        await service._writer_segment_markdown(
            record,
            segment={"segment_name": "competitor_deep_dives", "segment_competitor": "Acme",
                     "dimension": "pricing",
                     "allowed_source_ids": [record.detail.raw_sources[0].id]},
            timeout_seconds=5, language_guidance="", memory_context="", layer_context="",
            required_sections="", retry_count=0,
        )

    monkeypatch.setattr(service, "_real_collector_branch_step", collect)
    monkeypatch.setattr(service, "_trace_llm_text", generate)
    monkeypatch.setattr(service, "_real_writer_step", write)
    record.detail.plan.answer_requirements = [AnswerRequirement(
        competitor="Acme", dimension="pricing", intent="current_price", market="US",
        as_of=datetime.now(UTC).date(),
    )]
    record.detail.status = "running"
    assert record.detail.raw_sources[-1].model_dump_json() == original_gap
    command = Command(resume={"decision": "redo"}, update={"run_id": record.detail.id})
    assert not await service._invoke_graph(
        record, kind="real", thread_id=record.detail.id, graph_input=command
    )
    assert record.detail.current_node == "evidence_hitl"
    assert "evidence" in record.pending_interrupts
    assert current_snapshot(record.detail).phase == "collect"
    assert not generated
    assert record.detail.evidence_snapshots[0].model_dump_json() == history
    with pytest.raises(EvidenceUseRejectedError, match="accepted"):
        await write(record)
    service._cancel_hitl_timeout(record)

    record.detail.status = "running"
    assert not await service._invoke_graph(
        record, kind="real", thread_id=record.detail.id,
        graph_input=Command(resume={"decision": "accept"}, update={"run_id": record.detail.id}),
    )
    assert record.detail.current_node == "qa_hitl" and "qa" in record.pending_interrupts
    assert len(generated) == 1
    boundary = record.detail.report_answer_boundaries[-1]
    assert boundary.status == "answer" and boundary.allowed_fact_ids
    accepted = current_snapshot(record.detail)
    assert accepted.phase == "analysis" and accepted.id == boundary.snapshot_id
    service._cancel_hitl_timeout(record)
    record.detail.status = "running"
    assert await service._invoke_graph(
        record, kind="real", thread_id=record.detail.id,
        graph_input=Command(resume={"decision": "accept"}, update={"run_id": record.detail.id}),
    )
    assert current_snapshot(record.detail).id == accepted.id
    assert record.detail.evidence_snapshots[0].model_dump_json() == history
    await service._graph_checkpointer.aclose()


def patch_actual_redo_consumers(monkeypatch, service, record):
    """Stub generation while retaining actual snapshot consumption and Writer guard."""
    generated = []

    async def noop(*args, **kwargs):
        pass

    for name in (
        "_real_analyst_dispatch_step", "_real_analyst_join_step", "_real_phase_qa_step",
        "_real_comparator_step", "_real_reflector_step", "_real_qa_step",
    ):
        monkeypatch.setattr(service, name, noop)

    async def analyse(record, dimension, competitor, *, expected_snapshot_id=None):
        view, use = service._begin_evidence_use(
            record, agent="analyst", competitor=competitor, dimension=dimension
        )
        assert view.snapshot_id == expected_snapshot_id
        service._validate_evidence_use(record, use)

    async def review(*args, **kwargs):
        raise AssertionError("Partial analysis redo cannot accept evidence")

    async def generate(record, **kwargs):
        generated.append(kwargs["user"])
        return "Evidence reviewed."

    async def write(record):
        await service._writer_segment_markdown(
            record,
            segment={"segment_name": "competitor_deep_dives", "segment_competitor": "Acme",
                     "dimension": "pricing",
                     "allowed_source_ids": [source.id for source in record.detail.raw_sources]},
            timeout_seconds=5, language_guidance="", memory_context="", layer_context="",
            required_sections="", retry_count=0,
        )

    monkeypatch.setattr(service, "_real_analyst_branch_step", analyse)
    monkeypatch.setattr(service, "_real_evidence_hitl_step", review)
    monkeypatch.setattr(service, "_trace_llm_text", generate)
    monkeypatch.setattr(service, "_real_writer_step", write)
    record.detail.plan.answer_requirements = [AnswerRequirement(
        competitor="Acme", dimension="pricing", intent="current_price", market="US",
        as_of=datetime.now(UTC).date(),
    )]
    return generated, write


async def replace_gap_with_us_body(monkeypatch, record):
    gap_id = record.detail.raw_sources[-1].id
    old_hash = record.detail.raw_sources[-1].content_hash
    _, sources = await local_chain(monkeypatch, source_text("US"))
    replacement = sources[0].model_copy(deep=True, update={"id": gap_id})
    replacement.content_hash = hashlib.sha256(source_text("US").encode()).hexdigest()
    record.detail.raw_sources[-1] = replacement
    assert replacement.content_hash != old_hash and not record.detail.evidence_inputs_dirty
    return gap_id


@pytest.mark.asyncio
@pytest.mark.parametrize("redo_kind", ["writer_only", "comparator", "analyst"])
async def test_actual_qa_partial_redo_cannot_accept_replaced_legacy_gap(
    tmp_path, monkeypatch, redo_kind
):
    service, record, legacy, graph = await paused_actual_qa_graph(
        tmp_path, monkeypatch, redo_kind=redo_kind
    )
    history = legacy.model_dump_json()
    gap_id = await replace_gap_with_us_body(monkeypatch, record)
    assert gap_id in {gap.source_id for gap in legacy.gaps}
    generated, write = patch_actual_redo_consumers(monkeypatch, service, record)
    with pytest.raises(EvidenceUseRejectedError, match="accepted"):
        await write(record)
    record.detail.status = "running"
    with pytest.raises(EvidenceUseRejectedError, match="accepted"):
        await service._invoke_graph(
            record, kind="real", thread_id=record.detail.id,
            graph_input=Command(resume={"decision": "redo"}, update={"run_id": record.detail.id}),
        )
    assert not generated and not record.detail.report_answer_boundaries
    assert current_snapshot(record.detail).id == legacy.id
    assert record.detail.evidence_snapshots[0].model_dump_json() == history
    service._cancel_hitl_timeout(record)
    await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["unchanged", "source_body", "dirty"])
@pytest.mark.parametrize("redo_kind", ["writer_only", "comparator", "analyst"])
async def test_actual_current_policy_partial_redo_reuses_only_accepted_snapshot(
    tmp_path, monkeypatch, change, redo_kind
):
    service, record, legacy, graph = await paused_actual_qa_graph(
        tmp_path, monkeypatch, current_policy=True, redo_kind=redo_kind
    )
    accepted = current_snapshot(record.detail)
    history = [item.model_dump_json() for item in record.detail.evidence_snapshots]
    if change == "source_body":
        gap_id = await replace_gap_with_us_body(monkeypatch, record)
        assert gap_id not in {fact.source_id for fact in accepted.facts}
    elif change == "dirty":
        record.detail.evidence_inputs_dirty = True
    generated, _ = patch_actual_redo_consumers(monkeypatch, service, record)
    record.detail.status = "running"
    command = Command(resume={"decision": "redo"}, update={"run_id": record.detail.id})
    if change == "dirty":
        with pytest.raises(EvidenceUseRejectedError, match="accepted"):
            await service._invoke_graph(
                record, kind="real", thread_id=record.detail.id, graph_input=command
            )
        assert not generated and record.detail.evidence_inputs_dirty
    else:
        assert not await service._invoke_graph(
            record, kind="real", thread_id=record.detail.id, graph_input=command
        )
        assert len(generated) == 1
        boundary = record.detail.report_answer_boundaries[-1]
        assert boundary.status == "insufficient" and not boundary.allowed_fact_ids
        assert boundary.snapshot_id == accepted.id
        assert "qa" in record.pending_interrupts
    assert current_snapshot(record.detail).id == accepted.id
    assert [item.model_dump_json() for item in record.detail.evidence_snapshots] == history
    service._cancel_hitl_timeout(record)
    await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "decision,issues", [("accept", True), ("force_pass", True), ("redo", False)]
)
async def test_actual_qa_approval_or_noop_cannot_bypass_legacy_gap_policy(
    tmp_path, monkeypatch, decision, issues
):
    service, record, legacy, graph = await paused_actual_qa_graph(
        tmp_path, monkeypatch, issues=issues
    )
    history = legacy.model_dump_json()
    record.detail.status = "running"
    with pytest.raises(EvidenceUseRejectedError, match="accepted"):
        await service._invoke_graph(
            record, kind="real", thread_id=record.detail.id,
            graph_input=Command(resume={"decision": decision}, update={"run_id": record.detail.id}),
        )
    assert "qa" in record.pending_interrupts
    assert len(record.detail.evidence_snapshots) == 1
    assert record.detail.evidence_snapshots[0].model_dump_json() == history
    service._cancel_hitl_timeout(record)
    await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_actual_qa_redo_end_without_new_policy_cannot_approve_legacy_report(
    tmp_path, monkeypatch
):
    service, record, legacy, graph = await paused_actual_qa_graph(
        tmp_path, monkeypatch, redo_kind="writer_only", final_qa_attempts=2
    )
    record.detail.report_md = "Historical unreviewed price report"
    history = legacy.model_dump_json()
    record.detail.status = "running"
    with pytest.raises(EvidenceUseRejectedError, match="policy"):
        await service._invoke_graph(
            record, kind="real", thread_id=record.detail.id,
            graph_input=Command(resume={"decision": "redo"}, update={"run_id": record.detail.id}),
        )
    assert record.detail.evidence_snapshot_id == legacy.id
    assert record.detail.evidence_snapshots[0].model_dump_json() == history
    service._cancel_hitl_timeout(record)
    await service._graph_checkpointer.aclose()
