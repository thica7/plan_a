from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from langgraph.types import Command
from test_run_evidence_snapshot import make_detail

from packages.config import Settings
from packages.memory import KBCache, KBCacheEntry, RunJournal
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.evidence_context import EvidenceUseRejectedError
from packages.orchestrator.graph import (
    _add_demo_nodes,
    _add_real_nodes,
    _send_analysts,
    build_demo_analysis_graph,
    build_real_analysis_graph,
    build_scoped_redo_graph,
)
from packages.orchestrator.service import RunRecord, RunService
from packages.research.evidence.snapshot import current_snapshot
from packages.schema.models import CompetitorKnowledge
from packages.skills.registry import SkillRegistry


class NodeCapture:
    def __init__(self):
        self.nodes = {}

    def add_node(self, name, node):
        self.nodes[name] = node


class ReplayService(RunService):
    """Only external agent work is synthetic; snapshots and journals are real."""

    def __init__(self, journal):
        super().__init__(
            skill_registry=SkillRegistry.from_default_path(),
            settings=Settings(demo_mode=True, analyst_react_enabled=False),
            journal=journal,
            kb_cache=KBCache.in_memory(),
            graph_checkpointer=GraphCheckpointer.in_memory(),
        )
        if not self._runs:
            detail = make_detail()
            detail.plan.collaboration_mode = "assisted"
            self._runs[detail.id] = RunRecord(detail=detail)
        self.record = next(iter(self._runs.values()))
        self.qa_snapshots = []
        self.branch_snapshots = []
        self.review_count = 0
        self.redo_evidence = False

    async def _real_planner_step(self, record):
        pass

    _demo_planner_step = _real_planner_step

    async def _real_planner_hitl_step(self, record):
        pass

    async def _real_collector_dispatch_step(self, record, dimensions, competitors):
        pass

    async def _real_collector_branch_step(self, record, dimension, competitor):
        if self.review_count:
            record.detail.raw_sources = make_detail(price="4299 CNY").raw_sources

    _demo_collector_branch_step = _real_collector_branch_step

    async def _real_collect_join_step(self, record, dimensions):
        pass

    _demo_collect_join_step = _real_collect_join_step

    async def _run_survey_interview_enrichment(self, record, dimensions, competitors):
        if not any(source.id == "survey-source" for source in record.detail.raw_sources):
            source = record.detail.raw_sources[0].model_copy(deep=True)
            source.id = "survey-source"
            source.source_type = "survey_response"
            source.dimension = "feature"
            source.metadata["normalized_fields"] = []
            record.detail.raw_sources.append(source)

    async def _real_phase_qa_step(self, record, phase):
        if phase == "collect":
            self.qa_snapshots.append(self._current_evidence_snapshot(record))

    _demo_phase_qa_step = _real_phase_qa_step

    async def _real_evidence_hitl_step(self, record, dimensions, competitors):
        self.review_count += 1
        if self.redo_evidence and self.review_count == 1:
            return {"evidence_route": "redo", "dimensions": dimensions,
                    "target_competitors": competitors}
        return {"evidence_route": "accept"}

    async def _real_analyst_dispatch_step(self, record, dimensions, competitors):
        pass

    async def _real_analyst_branch_step(
        self, record, dimension, competitor, *, expected_snapshot_id=None
    ):
        view, use = self._begin_evidence_use(
            record, agent="analyst", competitor=competitor, dimension=dimension
        )
        assert view.snapshot_id == expected_snapshot_id
        self.branch_snapshots.append(view.snapshot_id)
        self._validate_evidence_use(record, use)

    _demo_analyst_branch_step = _real_analyst_branch_step

    async def _real_analyst_join_step(self, record, dimensions, competitors):
        pass

    async def _real_comparator_step(self, record):
        pass

    _demo_comparator_step = _real_comparator_step
    _real_reflector_step = _real_comparator_step
    _demo_reflector_step = _real_comparator_step
    _real_writer_step = _real_comparator_step
    _demo_writer_step = _real_comparator_step
    _real_qa_step = _real_comparator_step
    _demo_qa_step = _real_comparator_step

    async def _real_qa_hitl_step(self, record):
        return {"redo_kind": "end"}


@pytest.mark.asyncio
@pytest.mark.parametrize("builder", [build_real_analysis_graph, build_demo_analysis_graph,
                                         build_scoped_redo_graph])
async def test_survey_and_hitl_recollection_freeze_before_all_analyst_sends(tmp_path, builder):
    service = ReplayService(RunJournal(tmp_path / "journal.db"))
    service.redo_evidence = True
    record = service.record
    result = await builder(service).ainvoke({
        "run_id": record.detail.id, "dimensions": record.detail.plan.dimensions,
        "target_competitors": record.detail.plan.competitors, "redo_kind": "collector",
    })
    first, second = service.qa_snapshots
    assert first.phase == second.phase == "collect"
    assert "survey-source" in {source.id for source in first.sources}
    assert any(fact.value == "3999 CNY" for fact in first.facts)
    assert any(fact.value == "4299 CNY" for fact in second.facts)
    analysis = current_snapshot(record.detail)
    assert analysis.phase == "analysis"
    assert analysis.version == second.version + 1
    assert len(service.branch_snapshots) == 4
    assert set(service.branch_snapshots) == {analysis.id}
    assert result["evidence_snapshot_id"] == analysis.id
    assert "evidence_snapshots" not in result
    assert all(use.snapshot_id == analysis.id for use in record.detail.evidence_consumptions)
    await service._graph_checkpointer.aclose()


def test_send_payload_carries_only_fixed_snapshot_id():
    sends = _send_analysts({
        "run_id": "run", "dimensions": ["pricing", "feature"],
        "target_competitors": ["A", "B"], "evidence_snapshot_id": "frozen-analysis",
    })
    assert len(sends) == 4
    assert all(send.arg["evidence_snapshot_id"] == "frozen-analysis" for send in sends)
    assert all(set(send.arg) == {
        "run_id", "branch_dimensions", "branch_competitors", "evidence_snapshot_id"
    } for send in sends)


@pytest.mark.asyncio
@pytest.mark.parametrize("add_nodes", [_add_real_nodes, _add_demo_nodes])
async def test_repeated_qa_dispatch_and_journal_reopen_keep_snapshot_identity(tmp_path, add_nodes):
    path = tmp_path / "journal.db"
    service = ReplayService(RunJournal(path))
    capture = NodeCapture()
    add_nodes(capture, service)
    record = service.record
    state = {"run_id": record.detail.id}
    collect = await capture.nodes["collect_qa"](state)
    again = await capture.nodes["collect_qa"](state)
    assert collect["evidence_snapshot_id"] == again["evidence_snapshot_id"]
    dispatch = await capture.nodes["analyst_dispatch"](state)
    repeated = await capture.nodes["analyst_dispatch"](state)
    assert dispatch["evidence_snapshot_id"] == repeated["evidence_snapshot_id"]
    branch_state = {"run_id": record.detail.id, "branch_dimensions": ["pricing"],
                    "branch_competitors": ["Product A"],
                    "evidence_snapshot_id": dispatch["evidence_snapshot_id"]}
    branch = await capture.nodes["analyst"](branch_state)
    assert set(branch) == {"completed_analyst_branches"}
    saved = record.detail.model_dump(mode="json")
    reopened = ReplayService(RunJournal(path))
    restored = reopened.record.detail
    for field in ("evidence_snapshots", "evidence_snapshot_id", "evidence_consumptions"):
        assert restored.model_dump(mode="json")[field] == saved[field]
    frozen = await reopened._prepare_evidence_snapshot(reopened.record, phase="analysis")
    assert frozen.id == dispatch["evidence_snapshot_id"]
    assert len(restored.evidence_snapshots) == 2
    assert current_snapshot(restored).facts == current_snapshot(record.detail).facts
    await service._graph_checkpointer.aclose()
    await reopened._graph_checkpointer.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("add_nodes", [_add_real_nodes, _add_demo_nodes])
async def test_old_send_is_rejected_before_branch_enters(tmp_path, add_nodes):
    service = ReplayService(RunJournal(tmp_path / "journal.db"))
    record = service.record
    first = await service._prepare_evidence_snapshot(record, phase="analysis")
    record.detail.raw_sources = make_detail(price="4299 CNY").raw_sources
    await service._prepare_evidence_snapshot(record, phase="analysis")
    capture = NodeCapture()
    add_nodes(capture, service)
    with pytest.raises(EvidenceUseRejectedError):
        await capture.nodes["analyst"]({
            "run_id": record.detail.id, "branch_dimensions": ["pricing"],
            "branch_competitors": ["Product A"], "evidence_snapshot_id": first.id,
        })
    assert service.branch_snapshots == []
    assert record.detail.evidence_consumptions == []
    await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("add_nodes", [_add_real_nodes, _add_demo_nodes])
async def test_analyst_without_dispatch_snapshot_fails_explicitly(tmp_path, add_nodes):
    service = ReplayService(RunJournal(tmp_path / "journal.db"))
    await service._prepare_evidence_snapshot(service.record, phase="analysis")
    capture = NodeCapture()
    add_nodes(capture, service)
    with pytest.raises(EvidenceUseRejectedError, match="fixed evidence snapshot ID"):
        await capture.nodes["analyst"]({
            "run_id": service.record.detail.id, "branch_dimensions": ["pricing"],
            "branch_competitors": ["Product A"],
        })
    assert service.branch_snapshots == []
    await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_legacy_unfinished_resume_seals_first_snapshot_at_safe_entry(tmp_path):
    path = tmp_path / "journal.db"
    original = ReplayService(RunJournal(path))
    original.record.detail.report_md = "Historical unfinished draft"
    original.record.detail.current_node = "writer"
    original._persist_run(original.record.detail.id)
    service = ReplayService(RunJournal(path))
    record = service.record
    observed = []

    async def invoke(command, **kwargs):
        observed.append(command.update["evidence_snapshot_id"])
        assert current_snapshot(record.detail).phase == "analysis"
        return {}

    service._real_graph = SimpleNamespace(ainvoke=invoke)
    assert await service._invoke_graph(
        record, kind="real", thread_id=record.detail.id,
        graph_input=Command(resume={"decision": "accept"}, update={"run_id": record.detail.id}),
    )
    assert observed == [record.detail.evidence_snapshot_id]
    assert len(record.detail.evidence_snapshots) == 1
    assert record.detail.report_md == "Historical unfinished draft"
    assert RunJournal(path).load_run(record.detail.id).evidence_snapshot_id == observed[0]
    await original._graph_checkpointer.aclose()
    await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_new_planner_hitl_resume_waits_for_collect_qa_to_seal_first_snapshot():
    from test_evidence_hitl import _advance, _service

    from packages.schema.api_dto import RunCreateRequest

    service = _service()
    try:
        detail = await service.create_run(RunCreateRequest(
            topic="Snapshot freeze timing", competitors=["A"], dimensions=["pricing"],
            execution_mode="demo", collaboration_mode="assisted", research_depth="quick",
        ))
        await service.run_pipeline(detail.id)
        assert detail.current_node == "planner_hitl"
        assert detail.evidence_snapshots == []
        await _advance(service, detail.id, "evidence_hitl", "interrupted")
        record = service._runs[detail.id]
        assert [snapshot.phase for snapshot in record.detail.evidence_snapshots] == ["collect"]
        await _advance(service, detail.id, "qa_hitl", "interrupted")
        assert [snapshot.phase for snapshot in record.detail.evidence_snapshots] == [
            "collect", "analysis"
        ]
    finally:
        await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_legacy_downstream_graph_resume_seals_once_after_journal_reopen(tmp_path):
    from test_evidence_hitl import _advance, _service

    from packages.schema.api_dto import RunCreateRequest

    journal = RunJournal(tmp_path / "journal.db")
    checkpoint = tmp_path / "checkpoints.db"
    original = _service(journal=journal, checkpointer=GraphCheckpointer(checkpoint))
    try:
        detail = await original.create_run(RunCreateRequest(
            topic="Historical final QA restore", competitors=["A"], dimensions=["pricing"],
            execution_mode="demo", collaboration_mode="assisted", research_depth="quick",
        ))
        await original.run_pipeline(detail.id)
        await _advance(original, detail.id, "evidence_hitl", "interrupted")
        await _advance(original, detail.id, "qa_hitl", "interrupted")
        stored = original._runs[detail.id].detail
        # A legacy serialized detail has no additive evidence fields.
        stored.evidence_snapshots = []
        stored.evidence_snapshot_id = None
        stored.evidence_consumptions = []
        original._persist_run(detail.id)
    finally:
        await original._graph_checkpointer.aclose()
    restored = _service(journal=RunJournal(tmp_path / "journal.db"),
                        checkpointer=GraphCheckpointer(checkpoint))
    try:
        assert restored._runs[detail.id].detail.current_node == "qa_hitl"
        assert restored._runs[detail.id].detail.evidence_snapshots == []
        await _advance(restored, detail.id, None, "completed")
        record = restored._runs[detail.id]
        snapshot = current_snapshot(record.detail)
        assert snapshot.phase == "analysis" and snapshot.version == 1
        assert len(record.detail.evidence_snapshots) == 1
        assert snapshot.sources
        reopened = RunJournal(tmp_path / "journal.db").load_run(detail.id)
        assert current_snapshot(reopened).model_dump_json() == snapshot.model_dump_json()
    finally:
        await restored._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_unknown_legacy_resume_fails_without_inventing_analysis_snapshot(tmp_path):
    service = ReplayService(RunJournal(tmp_path / "journal.db"))
    record = service.record
    with pytest.raises(ValueError, match="unknown recovery entry"):
        await service._invoke_graph(record, kind="real", thread_id=record.detail.id,
                                    graph_input=Command(resume={"decision": "accept"}))
    assert record.detail.evidence_snapshots == []
    await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["writer_only", "comparator"])
@pytest.mark.parametrize("existing", [False, True])
async def test_scoped_bypass_seals_legacy_once_and_reuses_existing_analysis(
    tmp_path, kind, existing
):
    service = ReplayService(RunJournal(tmp_path / "journal.db"))
    record = service.record
    first = await service._prepare_evidence_snapshot(record, phase="analysis") if existing else None
    result = await build_scoped_redo_graph(service).ainvoke({
        "run_id": record.detail.id, "redo_kind": kind,
    })
    snapshot = current_snapshot(record.detail)
    assert result["evidence_snapshot_id"] == snapshot.id
    assert snapshot.phase == "analysis"
    assert len(record.detail.evidence_snapshots) == 1
    if first is not None:
        assert snapshot.id == first.id
    await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["writer_only", "comparator"])
async def test_scoped_bypass_rejects_collect_snapshot_before_any_downstream_node(
    tmp_path, monkeypatch, kind
):
    path = tmp_path / "journal.db"
    service = ReplayService(RunJournal(path))
    record = service.record
    collect = await service._prepare_evidence_snapshot(record, phase="collect")
    history = [snapshot.model_dump_json() for snapshot in record.detail.evidence_snapshots]
    calls = []

    async def downstream(_record):
        calls.append("downstream")

    for name in ("_real_comparator_step", "_real_reflector_step", "_real_writer_step",
                 "_real_qa_step"):
        monkeypatch.setattr(service, name, downstream)
    try:
        with pytest.raises(EvidenceUseRejectedError, match="analysis"):
            await build_scoped_redo_graph(service).ainvoke({
                "run_id": record.detail.id, "redo_kind": kind,
            })
        assert calls == []
        assert record.detail.evidence_snapshot_id == collect.id
        assert current_snapshot(record.detail).content_hash == collect.content_hash
        assert [snapshot.model_dump_json()
                for snapshot in record.detail.evidence_snapshots] == history
        persisted = RunJournal(path).load_run(record.detail.id)
        assert persisted.evidence_snapshot_id == collect.id
        assert [snapshot.model_dump_json() for snapshot in persisted.evidence_snapshots] == history
    finally:
        await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["completed", "completed_with_blockers"])
async def test_completed_legacy_report_stays_read_only(tmp_path, status):
    service = ReplayService(RunJournal(tmp_path / "journal.db"))
    detail = service.record.detail
    detail.status = status
    detail.report_md = "Historical report"
    before = detail.model_dump_json()
    returned = await service.run_pipeline(detail.id)
    assert returned.model_dump_json() == before
    assert detail.evidence_snapshots == []
    await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", ["pointer", "hash"])
async def test_corrupt_snapshot_is_rejected_before_graph_invocation(tmp_path, corruption):
    service = ReplayService(RunJournal(tmp_path / "journal.db"))
    record = service.record
    snapshot = await service._prepare_evidence_snapshot(record, phase="analysis")
    if corruption == "pointer":
        record.detail.evidence_snapshot_id = "missing"
    else:
        record.detail.evidence_snapshots[0] = snapshot.model_copy(update={"content_hash": "bad"})
    invoked = []

    async def invoke(*args, **kwargs):
        invoked.append(True)
        return {}

    service._real_graph = SimpleNamespace(ainvoke=invoke)
    with pytest.raises(ValueError, match="evidence snapshot"):
        await service._invoke_graph(record, kind="real", thread_id=record.detail.id,
                                    graph_input=Command(resume={"decision": "accept"}))
    assert invoked == []
    assert len(record.detail.evidence_snapshots) == 1
    await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["one_shot", "timeout", "react"])
@pytest.mark.parametrize("change", ["price", "collect_phase"])
async def test_actual_waiting_analyst_rejects_changed_price_before_any_result_merge(
    tmp_path, monkeypatch, mode, change
):
    service = ReplayService(RunJournal(tmp_path / "journal.db"))
    record = service.record
    first = await service._prepare_evidence_snapshot(record, phase="analysis")
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def complete(*args, **kwargs):
        calls.append("model")
        entered.set()
        await release.wait()
        if mode == "timeout":
            raise TimeoutError("Synthetic timeout")
        return {}

    monkeypatch.setattr(service, "_trace_llm_json", complete)
    if mode == "react":
        monkeypatch.setattr(service, "_should_use_analyst_react", lambda *args, **kwargs: True)
        monkeypatch.setattr(service, "_run_analyst_competitor_react", complete)
    task = asyncio.create_task(RunService._real_analyst_branch_step(
        service, record, "pricing", "Product A", expected_snapshot_id=first.id
    ))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        if change == "price":
            record.detail.raw_sources = make_detail(price="4299 CNY").raw_sources
        current = await service._prepare_evidence_snapshot(
            record, phase="collect" if change == "collect_phase" else "analysis"
        )
        if change == "collect_phase":
            assert current.facts == first.facts
        release.set()
        with pytest.raises(EvidenceUseRejectedError):
            await asyncio.wait_for(task, 3)
        assert record.detail.competitor_knowledge == {}
        assert record.detail.claim_card_bundles == []
        assert not any(message.message_type == "competitor_knowledge_ready"
                       for message in record.detail.agent_messages)
        assert service._kb_cache.stats()["entries"] == 0
        assert record.detail.evidence_consumptions[0].status == "rejected"
        restored = RunJournal(tmp_path / "journal.db").load_run(record.detail.id)
        assert restored.evidence_consumptions[0].status == "rejected"
        assert restored.evidence_consumptions[0].snapshot_id == first.id
        assert calls == ["model"]
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["price", "collect_phase"])
async def test_actual_cache_hit_rejects_changed_price_before_cache_application(
    tmp_path, monkeypatch, change
):
    service = ReplayService(RunJournal(tmp_path / "journal.db"))
    record = service.record
    first = await service._prepare_evidence_snapshot(record, phase="analysis")
    cache_hash = service._kb_cache_content_hash(record.detail, "Product A", "pricing")
    entry = KBCacheEntry(
        competitor="Product A", dimension="pricing", content_hash=cache_hash,
        source_ids=[record.detail.raw_sources[0].id],
        knowledge=CompetitorKnowledge(competitor="Product A"),
    )
    service._kb_cache.put(entry)
    entered, release = asyncio.Event(), asyncio.Event()
    emit = service.emit

    async def emit_with_barrier(run_id, event_type, *args, **kwargs):
        if event_type == "node_started":
            entered.set()
            await release.wait()
        await emit(run_id, event_type, *args, **kwargs)

    async def forbidden_model(*args, **kwargs):
        raise AssertionError("Cache replay must not call a model")

    monkeypatch.setattr(service, "emit", emit_with_barrier)
    monkeypatch.setattr(service, "_trace_llm_json", forbidden_model)
    task = asyncio.create_task(RunService._real_analyst_branch_step(
        service, record, "pricing", "Product A", expected_snapshot_id=first.id
    ))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        if change == "price":
            record.detail.raw_sources = make_detail(price="4299 CNY").raw_sources
        current = await service._prepare_evidence_snapshot(
            record, phase="collect" if change == "collect_phase" else "analysis"
        )
        if change == "collect_phase":
            assert current.facts == first.facts
        release.set()
        with pytest.raises(EvidenceUseRejectedError):
            await asyncio.wait_for(task, 3)
        assert record.detail.competitor_knowledge == {}
        assert record.detail.competitor_kbs == {}
        assert record.detail.claim_card_bundles == []
        assert service._kb_cache.get("Product A", "pricing", cache_hash) == entry
        assert record.detail.evidence_consumptions[0].status == "rejected"
        restored = RunJournal(tmp_path / "journal.db").load_run(record.detail.id)
        assert restored.evidence_consumptions[0].status == "rejected"
        assert restored.evidence_consumptions[0].snapshot_id == first.id
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_actual_demo_branch_validates_its_local_credential_before_merge(tmp_path):
    service = ReplayService(RunJournal(tmp_path / "journal.db"))
    record = service.record
    snapshot = await service._prepare_evidence_snapshot(record, phase="analysis")
    await RunService._demo_analyst_branch_step(
        service, record, "pricing", "Product A", expected_snapshot_id=snapshot.id
    )
    use, = record.detail.evidence_consumptions
    assert use.snapshot_id == snapshot.id
    assert use.status == "validated"
    assert use.validated_snapshot_id == snapshot.id
    assert record.detail.competitor_kbs["Product A"].slices["pricing"]
    await service._graph_checkpointer.aclose()
