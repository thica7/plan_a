from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from packages.config import Settings
from packages.memory import RunJournal
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunService
from packages.schema.api_dto import RunCreateRequest
from packages.schema.models import RawSource
from packages.search import SearchResult
from packages.skills.registry import SkillRegistry


def _service(journal: RunJournal) -> RunService:
    return RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False, ark_api_key="test-key", ark_model="test-model",
            ark_base_url="https://llm.example.invalid/v3", run_llm_max_calls=120,
        ),
        journal=journal,
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )


async def _poll_run(service: RunService, run_id: str) -> None:
    assert service.get_run(run_id) is not None
    assert any(summary.id == run_id for summary in service.list_runs())
    stream = service.stream_events(run_id)
    try:
        assert (await anext(stream)).run_id == run_id
    finally:
        await stream.aclose()


@pytest.mark.asyncio
async def test_polling_during_real_planner_keeps_discovered_collector_scope(monkeypatch) -> None:
    service = _service(RunJournal.in_memory())
    discovery_started, scope_started = asyncio.Event(), asyncio.Event()
    discovery_release, scope_release = asyncio.Event(), asyncio.Event()
    rivals = ["Steam Deck OLED", "ROG Ally X"]
    collected: list[str] = []

    async def fake_complete_json(*, system: str, user: str, schema_hint: str) -> dict:
        if "scoping agent" in system:
            discovery_started.set()
            await discovery_release.wait()
            return {
                "candidates": [{"name": name, "relationship": "direct"} for name in rivals],
                "selected_competitors": rivals,
            }
        scope_started.set()
        await scope_release.wait()
        return {"complexity": "low", "homepage_hints": {}}

    async def fake_search(*args, **kwargs) -> list[SearchResult]:
        return [SearchResult(
            title=name, url=f"https://products.example.invalid/{index}", snippet=name,
        ) for index, name in enumerate(rivals)]

    async def fake_fetch(*args, **kwargs) -> SimpleNamespace:
        return SimpleNamespace(
            ok=True, title="Nintendo Switch 2", text="Nintendo Switch 2 supports handheld play.",
            url="https://www.nintendo.com/switch2/", content_hash="target-page",
            fetch_method="test", error=None,
        )

    async def collector(record, dimension: str, competitor: str) -> None:
        collected.append(competitor)

    async def downstream(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(service._llm, "complete_json", fake_complete_json)
    monkeypatch.setattr(service, "_search", SimpleNamespace(is_enabled=True))
    monkeypatch.setattr(service, "_trace_search", fake_search)
    monkeypatch.setattr(service, "_trace_fetch", fake_fetch)
    monkeypatch.setattr(service, "_real_collector_branch_step", collector)
    for name in (
        "_real_collect_join_step", "_run_survey_interview_enrichment",
        "_real_phase_qa_step", "_real_analyst_branch_step", "_real_analyst_join_step",
        "_real_comparator_step", "_real_reflector_step", "_real_writer_step", "_real_qa_step",
    ):
        monkeypatch.setattr(service, name, downstream)
    detail = await service.create_run(RunCreateRequest(
        topic="分析掌上游戏机的功能", competitors=[], dimensions=["feature"],
        target_product={
            "name": "Nintendo Switch 2", "category": "掌上游戏机",
            "official_url": "https://www.nintendo.com/switch2/",
        },
        research_depth="quick", execution_mode="real", hitl_enabled=False,
    ))
    assert detail.plan.competitors == []
    task = asyncio.create_task(service.run_pipeline(detail.id))
    try:
        await asyncio.wait_for(discovery_started.wait(), 3)
        await _poll_run(service, detail.id)
        discovery_release.set()
        await asyncio.wait_for(scope_started.wait(), 3)
        await _poll_run(service, detail.id)
        scope_release.set()
        await asyncio.wait_for(task, 3)
        record = service._runs[detail.id]
        ready = next(
            message for message in record.detail.agent_messages
            if message.message_type == "analysis_plan_ready"
        )
        planned = ready.payload["plan"]["competitors"]
        assert planned == ["Nintendo Switch 2", *rivals]
        assert sorted(collected) == sorted(planned)
        assert record.detail.plan.competitors == planned
        assert record.detail.plan.target_product_evidence.status == "verified"
        assert record.detail.metrics.llm_calls == 2
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["real", "demo", "scoped_redo"])
async def test_active_graph_keeps_live_detail_and_inactive_graph_refreshes_journal(
    monkeypatch, kind: str,
) -> None:
    journal = RunJournal.in_memory()
    service = _service(journal)
    detail = await service.create_run(RunCreateRequest(
        topic="Journal ownership", competitors=["Cursor"], dimensions=["feature"],
        execution_mode="real", hitl_enabled=False,
    ))
    record = service._runs[detail.id]
    entered, release = asyncio.Event(), asyncio.Event()

    async def invoke(*args, **kwargs) -> dict:
        record.detail.plan.competitors = ["Live product"]
        record.detail.raw_sources = [RawSource(
            id="live-evidence", competitor="Live product", dimension="feature",
            source_type="webpage_verified", title="Live specification",
            snippet="Live product supports storage expansion.", content_hash="live-page",
            confidence=0.9,
        )]
        entered.set()
        await release.wait()
        return {}

    monkeypatch.setattr(service, f"_{kind}_graph", SimpleNamespace(ainvoke=invoke))
    task = asyncio.create_task(service._invoke_graph(
        record, kind=kind, thread_id=detail.id, graph_input={},
    ))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        live = record.detail
        await _poll_run(service, detail.id)
        assert record.detail is live
        assert record.detail.plan.competitors == ["Live product"]
        assert [source.id for source in record.detail.raw_sources] == ["live-evidence"]
        release.set()
        assert await task is True
        refreshed = journal.load_run(detail.id)
        refreshed.plan.competitors = ["External update"]
        journal.save_run(refreshed)
        assert service.get_run(detail.id).plan.competitors == ["External update"]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_another_service_still_observes_journal_updates_during_owned_execution(
    monkeypatch,
) -> None:
    journal = RunJournal.in_memory()
    owner = _service(journal)
    detail = await owner.create_run(RunCreateRequest(
        topic="External observer", competitors=["Cursor"], dimensions=["feature"],
        execution_mode="real", hitl_enabled=False,
    ))
    observer = _service(journal)
    entered, release = asyncio.Event(), asyncio.Event()

    async def invoke(*args, **kwargs) -> dict:
        entered.set()
        await release.wait()
        return {}

    monkeypatch.setattr(owner, "_real_graph", SimpleNamespace(ainvoke=invoke))
    task = asyncio.create_task(owner._invoke_graph(
        owner._runs[detail.id], kind="real", thread_id=detail.id, graph_input={},
    ))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        for competitors in (["First update"], ["Second update"]):
            snapshot = journal.load_run(detail.id)
            snapshot.plan.competitors = competitors
            journal.save_run(snapshot)
            assert observer.get_run(detail.id).plan.competitors == competitors
        release.set()
        await task
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await owner._graph_checkpointer.aclose()
        await observer._graph_checkpointer.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["exception", "cancel", "interrupt"])
async def test_graph_exit_releases_live_ownership_for_journal_refresh(
    monkeypatch, outcome: str,
) -> None:
    journal = RunJournal.in_memory()
    service = _service(journal)
    detail = await service.create_run(RunCreateRequest(
        topic="Ownership release", competitors=["Cursor"], dimensions=["feature"],
        execution_mode="real", hitl_enabled=False,
    ))
    record = service._runs[detail.id]
    entered, release = asyncio.Event(), asyncio.Event()

    async def invoke(*args, **kwargs) -> dict:
        entered.set()
        await release.wait()
        if outcome == "exception":
            raise RuntimeError("Graph failed")
        return {"__interrupt__": ["review"]}

    monkeypatch.setattr(service, "_real_graph", SimpleNamespace(ainvoke=invoke))
    task = asyncio.create_task(service._invoke_graph(
        record, kind="real", thread_id=detail.id, graph_input={},
    ))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        if outcome == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        elif outcome == "exception":
            release.set()
            with pytest.raises(RuntimeError, match="Graph failed"):
                await task
        else:
            release.set()
            assert await task is False
        snapshot = journal.load_run(detail.id)
        snapshot.plan.competitors = ["After graph exit"]
        journal.save_run(snapshot)
        assert service.get_run(detail.id).plan.competitors == ["After graph exit"]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_nested_graph_exit_keeps_outer_execution_owned(monkeypatch) -> None:
    journal = RunJournal.in_memory()
    service = _service(journal)
    detail = await service.create_run(RunCreateRequest(
        topic="Nested graph ownership", competitors=["Cursor"], dimensions=["feature"],
        execution_mode="real", hitl_enabled=False,
    ))
    record = service._runs[detail.id]

    async def inner(*args, **kwargs) -> dict:
        return {}

    async def outer(*args, **kwargs) -> dict:
        record.detail.plan.competitors = ["Outer live product"]
        await service._invoke_graph(record, kind="demo", thread_id="inner", graph_input={})
        await _poll_run(service, detail.id)
        assert record.detail.plan.competitors == ["Outer live product"]
        return {}

    monkeypatch.setattr(service, "_real_graph", SimpleNamespace(ainvoke=outer))
    monkeypatch.setattr(service, "_demo_graph", SimpleNamespace(ainvoke=inner))
    try:
        assert await service._invoke_graph(
            record, kind="real", thread_id=detail.id, graph_input={},
        ) is True
    finally:
        await service._graph_checkpointer.aclose()
