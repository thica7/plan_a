import asyncio
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from packages.agents import SubagentContext
from packages.agents.collectors import logic as collector_logic
from packages.config import Settings
from packages.memory import RunJournal
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunService
from packages.research.budget import research_depth_budget
from packages.schema.api_dto import CollectorResearchUsage, HitlResumeRequest, RunCreateRequest
from packages.schema.models import QCIssue, RawSource, RedoScope, TargetProductEvidence
from packages.search import SearchResult
from packages.skills.registry import SkillRegistry
from packages.tools.evidence_fetch import EvidenceFetchResult


def _service(
    *,
    journal: RunJournal | None = None,
    real: bool = False,
    checkpointer: GraphCheckpointer | None = None,
    search_enabled: bool = False,
) -> RunService:
    return RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=not real,
            ark_api_key="key" if real else None,
            ark_model="model" if real else None,
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            pplx_api_key="pplx-key" if search_enabled else None,
            hitl_enabled=False,
            hitl_timeout_seconds=0,
        ),
        journal=journal,
        graph_checkpointer=checkpointer or GraphCheckpointer.in_memory(),
    )


async def _wait_for(service: RunService, run_id: str, node: str | None, status: str) -> None:
    async def wait() -> None:
        while True:
            detail = service._runs[run_id].detail
            if detail is not None and detail.current_node == node and detail.status == status:
                if status == "interrupted":
                    record = service._runs[run_id]
                    if record.active_graph_kind == "demo":
                        graph = await service._get_demo_graph()
                    elif record.active_graph_kind == "scoped_redo":
                        graph = await service._get_scoped_redo_graph()
                    else:
                        graph = await service._get_real_graph()
                    snapshot = await graph.aget_state(
                        {"configurable": {"thread_id": record.active_thread_id}}
                    )
                    if not any(task.name == node and task.interrupts for task in snapshot.tasks):
                        await asyncio.sleep(0.01)
                        continue
                return
            await asyncio.sleep(0.01)

    await asyncio.wait_for(wait(), timeout=5)


async def _advance(service: RunService, run_id: str, node: str | None, status: str) -> None:
    await service.resume(run_id, HitlResumeRequest(decision="accept"))
    await _wait_for(service, run_id, node, status)


def _warning(problem: str = "Evidence date should be checked.") -> QCIssue:
    return QCIssue(
        id="qc-evidence-date",
        severity="warn",
        detected_by="coverage",
        target_agent="collector",
        target_subagent="pricing",
        target_competitor="A",
        field_path="raw_sources[source-a].freshness",
        problem=problem,
        redo_scope=RedoScope(
            kind="collector",
            target_subagent="pricing",
            target_competitor="A",
            target_competitors=["A"],
            rationale="Refresh source date.",
        ),
    )


@pytest.mark.asyncio
async def test_assisted_demo_pauses_at_planner_evidence_and_final_qa() -> None:
    service = _service()
    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic="Evidence review flow",
                competitors=["A"],
                dimensions=["pricing"],
                execution_mode="demo",
                collaboration_mode="assisted",
                research_depth="standard",
            )
        )
        await service.run_pipeline(detail.id)
        assert detail.status == "interrupted"
        assert detail.current_node == "planner_hitl"

        await _advance(service, detail.id, "evidence_hitl", "interrupted")
        assert service.has_pending_interrupt(detail.id)
        assert service._runs[detail.id].pending_interrupts["evidence"]["interrupt_node"] == "evidence_hitl"

        await _advance(service, detail.id, "qa_hitl", "interrupted")
        await _advance(service, detail.id, None, "completed")

        stages = [
            event.payload.get("stage")
            for event in service.get_trace(detail.id) or []
            if event.type == "interrupt"
        ]
        assert stages == ["planner", "evidence", "qa"]
        lifecycle = [
            message.payload["hitl_lifecycle"]["review_kind"]
            for message in detail.agent_messages
            if message.message_type == "hitl_lifecycle"
            and message.payload["hitl_lifecycle"]["lifecycle_stage"] == "requested"
        ]
        assert lifecycle == ["planner_review", "evidence_review", "qa_review"]
    finally:
        await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_ai_and_legacy_hitl_modes_keep_their_existing_pause_counts() -> None:
    service = _service()
    try:
        ai = await service.create_run(
            RunCreateRequest(
                topic="AI evidence flow",
                competitors=["A"],
                dimensions=["pricing"],
                execution_mode="demo",
                collaboration_mode="ai",
            )
        )
        await service.run_pipeline(ai.id)
        assert ai.status == "completed"
        assert [event for event in service.get_trace(ai.id) or [] if event.type == "interrupt"] == []

        legacy = await service.create_run(
            RunCreateRequest(
                topic="Legacy evidence flow",
                competitors=["A"],
                dimensions=["pricing"],
                execution_mode="demo",
                hitl_enabled=True,
            )
        )
        await service.run_pipeline(legacy.id)
        await _advance(service, legacy.id, "qa_hitl", "interrupted")
        await _advance(service, legacy.id, None, "completed")
        stages = [
            event.payload.get("stage")
            for event in service.get_trace(legacy.id) or []
            if event.type == "interrupt"
        ]
        assert stages == ["planner", "qa"]
    finally:
        await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_evidence_interrupt_lists_current_sources_dates_and_collect_qa_snapshot() -> None:
    service = _service()
    original_phase_qa = service._demo_phase_qa_step

    async def phase_qa_with_warning(record, phase):  # noqa: ANN001, ANN202
        await original_phase_qa(record, phase)
        if phase == "collect":
            source = record.detail.raw_sources[0]
            source.title = "T" * 400
            source.metadata = {
                "fetched_at": "2026-09-28T12:00:00Z",
                "source_published_at": "2026-09-15",
                "source_updated_at": "2026-09-27",
            }
            record.detail.qa_findings = [_warning("P" * 1000)]

    service._demo_phase_qa_step = phase_qa_with_warning  # type: ignore[method-assign]
    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic="Evidence payload",
                competitors=["A"],
                dimensions=["pricing"],
                execution_mode="demo",
                collaboration_mode="assisted",
            )
        )
        await service.run_pipeline(detail.id)
        await _advance(service, detail.id, "evidence_hitl", "interrupted")

        interrupt_event = next(
            event
            for event in reversed(service.get_trace(detail.id) or [])
            if event.type == "interrupt" and event.payload.get("stage") == "evidence"
        )
        payload = interrupt_event.payload
        source = payload["sources"][0]
        assert source["id"] == detail.raw_sources[0].id
        assert source["competitor"] == "A"
        assert source["dimension"] == "pricing"
        assert source["url"] == str(detail.raw_sources[0].url)
        assert source["source_type"] == "webpage_verified"
        assert source["confidence"] == 0.82
        assert source["fetched_at"] == "2026-09-28T12:00:00Z"
        assert source["source_published_at"] == "2026-09-15"
        assert source["source_updated_at"] == "2026-09-27"
        assert len(source["title"]) < 400
        assert payload["qa_findings"][0]["id"] == "qc-evidence-date"
        assert len(payload["qa_findings"][0]["problem"]) < 1000
        assert "raw_sources" not in payload["run"]
        assert "agent_messages" not in payload["run"]
        assert [issue.id for issue in detail.collect_qa_findings] == ["qc-evidence-date"]
        assert detail.qa_findings == []
    finally:
        await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_evidence_payload_bounds_all_untrusted_source_and_issue_text() -> None:
    service = _service()
    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic="Bounded evidence payload",
                competitors=["A"],
                dimensions=["pricing"],
                execution_mode="demo",
                collaboration_mode="assisted",
            )
        )
        long_text = "X" * 10_000
        detail.raw_sources = [
            RawSource(
                id=long_text,
                competitor=long_text,
                dimension=long_text,
                source_type=long_text,
                title=long_text,
                url="https://example.com/" + "u" * 1500,
                content_hash="hash",
                confidence=0.8,
            )
        ]
        issue = _warning(long_text)
        issue.id = long_text
        issue.target_agent = long_text
        issue.target_subagent = long_text
        issue.target_competitor = long_text
        issue.field_path = long_text
        detail.collect_qa_findings = [issue]

        payload = service._evidence_review_payload(detail)
        source = payload["sources"][0]
        finding = payload["qa_findings"][0]
        assert len(source["id"]) <= 128
        assert len(source["competitor"]) <= 240
        assert len(source["dimension"]) <= 128
        assert len(source["source_type"]) <= 128
        assert len(source["url"]) <= 1024
        assert len(finding["id"]) <= 128
        assert len(finding["target_agent"]) <= 128
        assert len(finding["target_subagent"]) <= 128
        assert len(finding["target_competitor"]) <= 240
        assert len(finding["field_path"]) <= 240
        assert len(finding["problem"]) <= 500
        assert len(json.dumps(payload)) < 5000
    finally:
        await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_evidence_payload_prioritizes_scoped_sources_before_truncation() -> None:
    service = _service()
    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic="Scoped evidence source preview",
                competitors=["A", "B"],
                dimensions=["pricing"],
                execution_mode="demo",
                collaboration_mode="assisted",
            )
        )
        old = RawSource(
            id="old-0",
            competitor="A",
            covered_competitors=["A"],
            dimension="pricing",
            source_type="webpage_verified",
            title="Old pricing source",
            url="https://example.com/a/pricing",
            content_hash="old-hash",
            confidence=0.8,
        )
        target = old.model_copy(
            update={
                "id": "target-last",
                "competitor": "B",
                "covered_competitors": ["B"],
                "url": "https://example.com/b/pricing",
            }
        )
        detail.raw_sources = [
            old.model_copy(update={"id": f"old-{index}"}) for index in range(105)
        ] + [target]
        detail.evidence_review_dimensions = ["pricing"]
        detail.evidence_review_competitors = ["B"]

        scoped = service._evidence_review_payload(detail)
        assert scoped["sources"][0]["id"] == "target-last"
        assert scoped["source_count"] == 106
        assert len(scoped["sources"]) == 100
        assert scoped["sources_truncated"] is True

        detail.evidence_review_competitors = ["A", "B"]
        global_review = service._evidence_review_payload(detail)
        assert global_review["sources"][0]["id"] == "old-0"
        assert global_review["source_count"] == 106
        assert global_review["sources_truncated"] is True
    finally:
        await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_evidence_redo_is_persisted_and_rejected_before_resume_when_exhausted() -> None:
    service = _service()
    collector_calls = 0
    refresh_was_active = False
    redo_feedback: list[dict[str, object]] = []
    original_collector = service._demo_collector_branch_step
    original_phase_qa = service._demo_phase_qa_step

    async def phase_qa_with_warning(record, phase):  # noqa: ANN001, ANN202
        await original_phase_qa(record, phase)
        if phase == "collect":
            record.detail.qa_findings = [_warning()]

    async def counting_collector(record, dimension, competitor):  # noqa: ANN001, ANN202
        nonlocal collector_calls, refresh_was_active
        collector_calls += 1
        if collector_calls == 2:
            redo_feedback.extend(
                service._qa_feedback_for_branch(record.detail, "collector", dimension, competitor)
            )
            assert record.detail.raw_sources
            refresh_was_active = getattr(record.detail, "evidence_refresh_active", False)
        await original_collector(record, dimension, competitor)

    service._demo_collector_branch_step = counting_collector  # type: ignore[method-assign]
    service._demo_phase_qa_step = phase_qa_with_warning  # type: ignore[method-assign]
    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic="Evidence redo budget",
                competitors=["A"],
                dimensions=["pricing"],
                execution_mode="demo",
                collaboration_mode="assisted",
                research_depth="standard",
            )
        )
        await service.run_pipeline(detail.id)
        await _advance(service, detail.id, "evidence_hitl", "interrupted")
        assert collector_calls == 1

        await service.resume(detail.id, HitlResumeRequest(decision="redo", note="Check again"))
        await _wait_for(service, detail.id, "evidence_hitl", "interrupted")
        assert detail.evidence_repair_rounds == 1
        assert collector_calls == 2
        assert refresh_was_active is True
        assert any(item["problem"] == "Check again" for item in redo_feedback)
        assert any(item["id"] == "qc-evidence-date" for item in redo_feedback)
        assert detail.evidence_refresh_active is False
        collect_tasks = [
            message for message in detail.agent_messages
            if message.message_type == "collect_task"
        ]
        assert collect_tasks[1].payload["evidence_review_note"] == "Check again"
        assert collect_tasks[1].payload["collect_qa_findings"][0]["id"] == "qc-evidence-date"

        with pytest.raises(ValueError, match="Evidence redo limit reached"):
            await service.resume(detail.id, HitlResumeRequest(decision="redo"))
        assert detail.status == "interrupted"
        assert detail.current_node == "evidence_hitl"
        assert service.has_pending_interrupt(detail.id)
        assert detail.evidence_repair_rounds == 1
        await _advance(service, detail.id, "qa_hitl", "interrupted")
    finally:
        await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_evidence_refresh_refetches_existing_url_without_removing_old_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetched_urls: list[str] = []

    async def fetch_page(url: str) -> EvidenceFetchResult:
        fetched_urls.append(url)
        return EvidenceFetchResult(
            url=url,
            ok=True,
            title="Updated A pricing",
            text=("A pricing has a Free plan and a Pro plan at $20 per month. " * 8),
            content_hash="new-pricing-hash",
            status_code=200,
            quality_score=0.9,
            text_length=440,
        )

    monkeypatch.setattr("packages.agents.collectors.logic.fetch_evidence_page", fetch_page)
    service = _service(real=True)
    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic="Refresh existing pricing URL",
                competitors=["A"],
                dimensions=["pricing"],
                execution_mode="real",
                collaboration_mode="assisted",
                research_depth="standard",
            )
        )
        old_source = RawSource(
            id="old-pricing",
            competitor="A",
            covered_competitors=["A"],
            dimension="pricing",
            source_type="webpage_verified",
            title="Old A pricing",
            url="https://example.com/pricing",
            content_hash="old-pricing-hash",
            confidence=0.8,
        )
        detail.raw_sources = [old_source]
        detail.evidence_refresh_active = True

        source = await service._source_from_search_result(
            detail,
            "A",
            "pricing",
            SearchResult(
                title="A pricing",
                url="https://example.com/pricing",
                snippet="Current A pricing plans.",
            ),
        )

        assert fetched_urls == ["https://example.com/pricing"]
        assert detail.raw_sources == [old_source]
        assert source is not None
        assert source.content_hash != old_source.content_hash
    finally:
        await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("competitor", "old_url", "include_official", "with_target_product"),
    [
        ("A", "https://example.com/a/pricing", False, False),
        ("OpenAI", "https://example.com/openai/custom-pricing", True, False),
        ("OpenAI", "https://example.com/openai/custom-pricing", True, True),
    ],
)
async def test_real_refresh_pipeline_refetches_old_url_when_search_budget_is_exhausted(
    monkeypatch: pytest.MonkeyPatch,
    competitor: str,
    old_url: str,
    include_official: bool,
    with_target_product: bool,
) -> None:
    service = _service(real=True, search_enabled=True)
    network_calls: list[str] = []
    seed_candidates = []
    original_pipeline = collector_logic.run_research_pipeline

    async def observe_pipeline(brief, **kwargs):  # noqa: ANN001, ANN202
        seed_candidates.extend(kwargs.get("seed_candidates") or [])
        return await original_pipeline(brief, **kwargs)

    async def allow_robots(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        return SimpleNamespace(allowed=True)

    async def fetch_page(url: str, **_kwargs) -> EvidenceFetchResult:  # noqa: ANN003
        network_calls.append(url)
        text = f"{competitor} pricing offers a Free plan and a Pro plan at $20 per month. " * 8
        return EvidenceFetchResult(
            url=url,
            ok=True,
            title="Current A pricing",
            text=text,
            content_hash="new-pricing-hash",
            status_code=200,
            quality_score=0.9,
            text_length=len(text),
        )

    monkeypatch.setattr(collector_logic, "run_research_pipeline", observe_pipeline)
    monkeypatch.setattr(service, "_trace_robots", allow_robots)
    monkeypatch.setattr("packages.orchestrator.service.fetch_evidence_page", fetch_page)
    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic=f"{competitor} brand refresh",
                competitors=[competitor],
                dimensions=["pricing"],
                target_product={
                    "name": competitor,
                    "official_url": "https://openai.com/pricing",
                } if with_target_product else None,
                execution_mode="real",
                collaboration_mode="assisted",
                research_depth="standard",
            )
        )
        old = RawSource(
            id="old-pricing-source",
            competitor=competitor,
            covered_competitors=[competitor],
            dimension="pricing",
            source_type="webpage_verified",
            title=f"Old {competitor} pricing",
            url=old_url,
            content_hash="old-pricing-hash",
            confidence=0.8,
            metadata={
                "source_published_at": "2026-09-01",
                "source_updated_at": "2026-09-15",
            },
        )
        detail.raw_sources = [old]
        detail.evidence_refresh_active = True
        detail.plan.homepage_hints = {}
        if with_target_product:
            detail.plan.target_product_evidence = TargetProductEvidence(
                status="verified",
                source_url="https://openai.com/pricing",
                title="OpenAI official pricing",
            )
        budget = research_depth_budget("standard")
        assert budget is not None
        context = SubagentContext(detail.id, "collector", f"pricing::{competitor}")
        detail.collector_research_usage[context.subagent] = CollectorResearchUsage(
            search_calls=budget.max_search_queries,
            fetch_calls=budget.max_fetches - 1,
        )

        await service._collect_competitor_with_web_search(
            service._runs[detail.id], "pricing", competitor, context,
            seed_sources=[], include_official=include_official,
        )

        assert network_calls == [old_url]
        assert detail.collector_research_usage[context.subagent].fetch_calls == budget.max_fetches
        assert detail.collector_research_usage[context.subagent].search_calls == budget.max_search_queries
        assert detail.raw_sources == [old]
        assert seed_candidates[0].origin == "web_search"
        assert seed_candidates[0].confidence <= 0.5
        assert seed_candidates[0].date == "2026-09-01"
        assert seed_candidates[0].last_updated == "2026-09-15"
    finally:
        await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_refresh_without_old_url_keeps_trusted_registry_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(real=True, search_enabled=True)
    network_calls: list[str] = []
    seed_candidates = []
    original_pipeline = collector_logic.run_research_pipeline

    async def observe_pipeline(brief, **kwargs):  # noqa: ANN001, ANN202
        seed_candidates.extend(kwargs.get("seed_candidates") or [])
        return await original_pipeline(brief, **kwargs)

    async def allow_robots(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        return SimpleNamespace(allowed=True)

    async def fetch_page(url: str, **_kwargs) -> EvidenceFetchResult:  # noqa: ANN003
        network_calls.append(url)
        text = "OpenAI API pricing documents current model rates and usage tiers. " * 8
        return EvidenceFetchResult(
            url=url, ok=True, title="OpenAI API pricing", text=text,
            content_hash="registry-pricing-hash", status_code=200,
            quality_score=0.9, text_length=len(text),
        )

    monkeypatch.setattr(collector_logic, "run_research_pipeline", observe_pipeline)
    monkeypatch.setattr(service, "_trace_robots", allow_robots)
    monkeypatch.setattr("packages.orchestrator.service.fetch_evidence_page", fetch_page)
    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic="OpenAI registry fallback",
                competitors=["OpenAI"],
                dimensions=["pricing"],
                target_product={
                    "name": "OpenAI",
                    "official_url": "https://openai.com/pricing",
                },
                execution_mode="real",
                collaboration_mode="assisted",
                research_depth="standard",
            )
        )
        detail.raw_sources = []
        detail.evidence_refresh_active = True
        detail.plan.homepage_hints = {}
        detail.plan.target_product_evidence = TargetProductEvidence(
            status="verified",
            source_url="https://openai.com/pricing",
            title="OpenAI official pricing",
        )
        budget = research_depth_budget("standard")
        assert budget is not None
        context = SubagentContext(detail.id, "collector", "pricing::OpenAI")
        detail.collector_research_usage[context.subagent] = CollectorResearchUsage(
            search_calls=budget.max_search_queries,
            fetch_calls=budget.max_fetches - 1,
        )

        await service._collect_competitor_with_web_search(
            service._runs[detail.id], "pricing", "OpenAI", context,
            seed_sources=[], include_official=True,
        )

        assert network_calls == ["https://developers.openai.com/api/docs/pricing"]
        assert detail.collector_research_usage[context.subagent].fetch_calls == budget.max_fetches
        assert any(
            candidate.url == "https://openai.com/pricing"
            and candidate.metadata["authority"] == "unverified"
            for candidate in seed_candidates
        )
    finally:
        await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_duplicate_refresh_keeps_new_fetch_time_and_original_page_date() -> None:
    service = _service(real=True)
    old_time = (datetime.utcnow() - timedelta(days=90)).replace(microsecond=0).isoformat()
    new_time = (datetime.utcnow() - timedelta(days=1)).replace(microsecond=0).isoformat()
    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic="Same content evidence refresh",
                competitors=["A"],
                dimensions=["pricing"],
                execution_mode="real",
                collaboration_mode="assisted",
            )
        )
        detail.evidence_refresh_active = True
        old = RawSource(
            id="same-pricing-source",
            competitor="A",
            covered_competitors=["A"],
            dimension="pricing",
            source_type="webpage_verified",
            title="A pricing",
            url="https://example.com/a/pricing",
            content_hash="same-content-hash",
            confidence=0.8,
            metadata={"fetched_at": old_time},
        )
        new = old.model_copy(update={"metadata": {"fetched_at": new_time}})
        detail.raw_sources = [old, new]

        refreshed = service._normalize_collected_sources(detail, ["pricing"])

        assert len(refreshed) == 1
        assert refreshed[0].metadata["fetched_at"] == new_time
        assert service._source_freshness_problem(refreshed[0]) is None
        assert [item["fetched_at"] for item in refreshed[0].metadata["refresh_observations"]] == [
            old_time, new_time,
        ]

        old_page = old.model_copy(
            update={"metadata": {"fetched_at": old_time, "source_published_at": old_time}}
        )
        new_page = old.model_copy(
            update={"metadata": {"fetched_at": new_time, "source_published_at": new_time}}
        )
        detail.raw_sources = [old_page, new_page]

        published = service._normalize_collected_sources(detail, ["pricing"])

        assert len(published) == 1
        assert published[0].metadata["fetched_at"] == new_time
        assert published[0].metadata["source_published_at"] == old_time
        assert service._source_observed_at(published[0]) == datetime.fromisoformat(old_time)
        assert service._source_freshness_problem(published[0]) is not None

        new_page_update = old.model_copy(
            update={"metadata": {"fetched_at": new_time, "source_updated_at": new_time}}
        )
        detail.raw_sources = [old_page, new_page_update]
        mixed_dates = service._normalize_collected_sources(detail, ["pricing"])
        assert mixed_dates[0].metadata.get("source_updated_at") is None
        assert service._source_observed_at(mixed_dates[0]) == datetime.fromisoformat(old_time)
    finally:
        await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_kb_refresh_uses_new_web_identity_without_losing_kb_provenance() -> None:
    service = _service(real=True)
    old_time = (datetime.utcnow() - timedelta(days=120)).replace(microsecond=0).isoformat()
    new_time = (datetime.utcnow() - timedelta(days=1)).replace(microsecond=0).isoformat()
    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic="KB source live refresh",
                competitors=["A"],
                dimensions=["pricing"],
                execution_mode="real",
                collaboration_mode="assisted",
            )
        )
        detail.evidence_refresh_active = True
        old_kb = RawSource(
            id="kb-pricing-source",
            competitor="A",
            covered_competitors=["A"],
            dimension="pricing",
            source_type="webpage_verified",
            title="A pricing",
            url="https://example.com/a/pricing",
            content_hash="same-pricing-hash",
            confidence=0.6,
            candidate_origin="rag_kb",
            fetch_method="rag_kb_retrieve",
            metadata={
                "kb_retrieved": True,
                "kb_document_id": "kb-doc-1",
                "kb_fetched_at": old_time,
            },
        )
        live_web = old_kb.model_copy(
            update={
                "id": "web-pricing-source",
                "confidence": 0.9,
                "candidate_origin": "web_search",
                "fetch_method": "basic_httpx",
                "metadata": {"fetched_at": new_time},
            }
        )
        detail.raw_sources = [old_kb, live_web]

        normalized = service._normalize_collected_sources(detail, ["pricing"])

        assert len(normalized) == 1
        refreshed = normalized[0]
        assert refreshed.id == "web-pricing-source"
        assert refreshed.candidate_origin == "web_search"
        assert refreshed.fetch_method == "basic_httpx"
        assert refreshed.metadata["fetched_at"] == new_time
        assert refreshed.metadata.get("kb_retrieved") is not True
        assert refreshed.metadata["prior_kb_document_id"] == "kb-doc-1"
        assert refreshed.metadata["prior_kb_fetched_at"] == old_time
        assert [item["candidate_origin"] for item in refreshed.metadata["refresh_observations"]] == [
            "rag_kb", "web_search",
        ]
        assert service._source_observed_at(refreshed) == datetime.fromisoformat(new_time)
        assert service._source_freshness_problem(refreshed) is None

        old_page = old_kb.model_copy(
            update={"metadata": {**old_kb.metadata, "source_published_at": old_time}}
        )
        new_page = live_web.model_copy(
            update={"metadata": {
                "fetched_at": new_time,
                "source_published_at": new_time,
                "last_verified_at": new_time,
            }}
        )
        detail.raw_sources = [old_page, new_page]
        published = service._normalize_collected_sources(detail, ["pricing"])[0]
        assert published.metadata["source_published_at"] == old_time
        assert service._source_observed_at(published) == datetime.fromisoformat(old_time)
        assert service._source_freshness_problem(published) is not None
    finally:
        await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_quick_evidence_redo_rejects_without_consuming_interrupt() -> None:
    service = _service()
    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic="Quick evidence budget",
                competitors=["A"],
                dimensions=["pricing"],
                execution_mode="demo",
                collaboration_mode="assisted",
                research_depth="quick",
            )
        )
        await service.run_pipeline(detail.id)
        await _advance(service, detail.id, "evidence_hitl", "interrupted")
        with pytest.raises(ValueError, match="Evidence redo limit reached"):
            await service.resume(detail.id, HitlResumeRequest(decision="redo"))
        assert detail.status == "interrupted"
        assert service._runs[detail.id].pending_interrupts["evidence"]["interrupt_node"] == "evidence_hitl"
        assert detail.evidence_repair_rounds == 0
    finally:
        await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_real_evidence_redo_rejects_when_all_relevant_fetch_budgets_are_exhausted() -> None:
    service = _service(real=True)
    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic="Exhausted evidence fetch budget",
                competitors=["A", "B"],
                dimensions=["pricing"],
                execution_mode="real",
                collaboration_mode="assisted",
                research_depth="standard",
            )
        )
        detail.status = "interrupted"
        detail.current_node = "evidence_hitl"
        detail.collector_research_usage = {
            "pricing::A": CollectorResearchUsage(search_calls=0, fetch_calls=5),
            "pricing::B": CollectorResearchUsage(search_calls=0, fetch_calls=5),
        }
        record = service._runs[detail.id]
        record.pending_interrupts["evidence"] = {
            "stage": "evidence", "graph_kind": "real", "thread_id": detail.id,
            "interrupt_node": "evidence_hitl",
        }

        assert service._evidence_review_payload(detail)["redo_remaining"] == 0
        with pytest.raises(ValueError, match="Evidence redo limit reached.*fetch budget"):
            await service.resume(detail.id, HitlResumeRequest(decision="redo"))
        assert detail.status == "interrupted"
        assert detail.evidence_repair_rounds == 0
        assert service.has_pending_interrupt(detail.id)
    finally:
        await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_evidence_redo_uses_reviewed_branch_scope_and_fetch_not_search_budget() -> None:
    service = _service(real=True)

    async def fake_resume_graph(_run_id, _request):  # noqa: ANN001, ANN202
        return None

    service._resume_interrupted_graph = fake_resume_graph  # type: ignore[method-assign]
    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic="Scoped evidence fetch budget",
                competitors=["A", "B"],
                dimensions=["pricing"],
                execution_mode="real",
                collaboration_mode="assisted",
                research_depth="standard",
            )
        )
        detail.status = "interrupted"
        detail.current_node = "evidence_hitl"
        detail.evidence_review_dimensions = ["pricing"]
        detail.evidence_review_competitors = ["A"]
        detail.collector_research_usage = {
            "pricing::A": CollectorResearchUsage(search_calls=0, fetch_calls=5),
            "pricing::B": CollectorResearchUsage(search_calls=0, fetch_calls=0),
        }
        record = service._runs[detail.id]
        record.pending_interrupts["evidence"] = {
            "stage": "evidence", "graph_kind": "scoped_redo", "thread_id": "redo-thread",
            "interrupt_node": "evidence_hitl",
        }

        assert service._evidence_review_payload(detail)["redo_remaining"] == 0
        with pytest.raises(ValueError, match="Evidence redo limit reached.*fetch budget"):
            await service.resume(detail.id, HitlResumeRequest(decision="redo"))
        assert service.has_pending_interrupt(detail.id)

        detail.collector_research_usage["pricing::A"].fetch_calls = 4
        assert service._evidence_review_payload(detail)["redo_remaining"] == 1
        await service.resume(detail.id, HitlResumeRequest(decision="redo"))
        assert detail.status == "running"
    finally:
        await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_journal_hydrates_evidence_pending_interrupt_and_repair_counter(tmp_path) -> None:
    journal = RunJournal(tmp_path / "evidence-runs.db")
    original = _service(journal=journal)
    try:
        detail = await original.create_run(
            RunCreateRequest(
                topic="Evidence journal resume",
                competitors=["A"],
                dimensions=["pricing"],
                execution_mode="demo",
                collaboration_mode="assisted",
            )
        )
        detail.status = "running"
        detail.current_node = "evidence_hitl"
        detail.evidence_repair_rounds = 1
        original._persist_run(detail.id)
    finally:
        await original._graph_checkpointer.aclose()

    reloaded = _service(journal=journal)

    async def fake_resume_graph(_run_id, _request):  # noqa: ANN001, ANN202
        return None

    reloaded._resume_interrupted_graph = fake_resume_graph  # type: ignore[method-assign]
    try:
        hydrated = reloaded.get_run(detail.id)
        assert hydrated is not None
        assert hydrated.status == "interrupted"
        assert hydrated.evidence_repair_rounds == 1
        assert reloaded._runs[detail.id].pending_interrupts["evidence"]["interrupt_node"] == "evidence_hitl"
        await reloaded.resume(detail.id, HitlResumeRequest(decision="accept"))
        assert hydrated.status == "running"
    finally:
        await reloaded._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_scoped_redo_evidence_interrupt_restores_its_graph_thread_from_journal(tmp_path) -> None:
    journal = RunJournal(tmp_path / "scoped-evidence-runs.db")
    checkpoint_path = tmp_path / "scoped-evidence-checkpoints.db"
    original = _service(
        journal=journal, real=True, checkpointer=GraphCheckpointer(checkpoint_path)
    )

    async def no_collect(_record, _dimension, _competitor):  # noqa: ANN001, ANN202
        return None

    async def passed_qa(record, _phase):  # noqa: ANN001, ANN202
        record.detail.qa_findings = []

    original._real_collector_branch_step = no_collect  # type: ignore[method-assign]
    original._real_phase_qa_step = passed_qa  # type: ignore[method-assign]
    try:
        detail = await original.create_run(
            RunCreateRequest(
                topic="Scoped evidence journal",
                competitors=["A"],
                dimensions=["pricing"],
                execution_mode="real",
                collaboration_mode="assisted",
            )
        )
        detail.status = "completed"
        detail.report_md = "Before scoped evidence redo"
        detail.qa_findings = [_warning().model_copy(update={"severity": "blocker"})]
        await original.run_scoped_redo(detail.id)
        assert detail.status == "interrupted"
        assert detail.current_node == "evidence_hitl"
        assert detail.evidence_review_dimensions == ["pricing"]
        assert detail.evidence_review_competitors == ["A"]
        thread_id = original._runs[detail.id].active_thread_id
        assert original._runs[detail.id].active_graph_kind == "scoped_redo"
    finally:
        await original._graph_checkpointer.aclose()

    reloaded = _service(
        journal=journal, real=True, checkpointer=GraphCheckpointer(checkpoint_path)
    )

    async def no_analyst(_record, _dimension, _competitor):  # noqa: ANN001, ANN202
        return None

    async def no_node(_record):  # noqa: ANN001, ANN202
        return None

    reloaded._real_analyst_branch_step = no_analyst  # type: ignore[method-assign]
    reloaded._real_phase_qa_step = passed_qa  # type: ignore[method-assign]
    reloaded._real_comparator_step = no_node  # type: ignore[method-assign]
    reloaded._real_reflector_step = no_node  # type: ignore[method-assign]
    reloaded._real_writer_step = no_node  # type: ignore[method-assign]
    reloaded._real_qa_step = no_node  # type: ignore[method-assign]
    try:
        assert reloaded.has_pending_interrupt(detail.id)
        assert reloaded._runs[detail.id].active_graph_kind == "scoped_redo"
        assert reloaded._runs[detail.id].active_thread_id == thread_id
        assert reloaded._runs[detail.id].detail.evidence_review_dimensions == ["pricing"]
        assert reloaded._runs[detail.id].detail.evidence_review_competitors == ["A"]
        await reloaded.resume(detail.id, HitlResumeRequest(decision="accept"))
        await _wait_for(reloaded, detail.id, "qa_hitl", "interrupted")
        assert reloaded._runs[detail.id].active_graph_kind == "scoped_redo"
        await reloaded.resume(detail.id, HitlResumeRequest(decision="accept"))
        await _wait_for(reloaded, detail.id, None, "completed")
        completed = reloaded._runs[detail.id].detail
        assert len(completed.revisions) == 1
        assert completed.revisions[0].stage == "collector"
        assert completed.revisions[0].redo_scopes[0].target_subagent == "pricing"
        assert completed.revisions[0].issue_ids == ["qc-evidence-date"]
        assert completed.pending_graph_redo is None
    finally:
        await reloaded._graph_checkpointer.aclose()

    final_reload = _service(journal=journal, real=True)
    try:
        persisted = final_reload.get_run(detail.id)
        assert persisted is not None
        assert len(persisted.revisions) == 1
        assert persisted.revisions[0].issue_ids == ["qc-evidence-date"]
        assert persisted.pending_graph_redo is None
    finally:
        await final_reload._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_force_pass_preserves_original_findings_and_reviewer_note() -> None:
    service = _service()
    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic="QA force pass audit",
                competitors=["A"],
                dimensions=["pricing"],
                execution_mode="demo",
            )
        )
        detail.qa_findings = [_warning()]
        record = service._runs[detail.id]

        async def force_pass(_record, *, stage, message, payload):  # noqa: ANN001, ANN202
            return HitlResumeRequest(decision="force_pass", note="Source was reviewed manually.")

        service._maybe_interrupt = force_pass  # type: ignore[method-assign]
        route = await service._real_qa_hitl_step(record)

        assert route["redo_kind"] == "end"
        assert detail.qa_findings == []
        assert [issue.id for issue in detail.overridden_qa_findings] == ["qc-evidence-date"]
        assert detail.qa_override_note == "Source was reviewed manually."
        assert datetime.fromisoformat(detail.qa_override_at.isoformat()) == detail.qa_override_at
    finally:
        await service._graph_checkpointer.aclose()
