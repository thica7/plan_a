"""Offline replay captures actual prompts/tools and artifact commit boundaries."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import pytest

from packages.agents.writer.repair import WriterRepairPlan
from packages.config import Settings
from packages.enterprise import build_enterprise_projection
from packages.identity.source_resolver import resolve_source_token
from packages.knowledge.models import DocumentCreate, KnowledgeScope
from packages.knowledge.repository import KnowledgeRepository
from packages.llm.doubao_client import LLMUsage
from packages.memory import KBCache, RunJournal
from packages.observability.trace_store import TraceStore
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.evidence_context import EvidenceUseRejectedError
from packages.orchestrator.service import RunRecord, RunService
from packages.research.evidence.snapshot import seal_snapshot
from packages.schema.api_dto import RunDetail
from packages.schema.models import AnalysisPlan, QCIssue, RawSource, RedoScope
from packages.skills.registry import SkillRegistry


def replay_detail():
    now = datetime.now(UTC)
    detail = RunDetail(
        id="alignment-replay",
        workspace_id="ws-replay",
        project_id="project-replay",
        topic="fixed product comparison",
        status="running",
        execution_mode="real",
        created_at=now,
        updated_at=now,
        plan=AnalysisPlan(
            topic="fixed product comparison",
            competitors=["Phone X", "Phone X Pro"],
            dimensions=["pricing", "feature"],
            research_depth="quick",
        ),
    )
    for product, price in [("Phone X", 3999), ("Phone X Pro", 5999)]:
        for dimension in detail.plan.dimensions:
            detail.raw_sources.append(
                RawSource(
                    id=f"{product.replace(' ', '-')}-{dimension}",
                    competitor=product,
                    dimension=dimension,
                    source_type="official_docs",
                    title=f"{product} {dimension}",
                    snippet=f"Original {product} {dimension}: {price}",
                    content_hash=f"body-{product}-{dimension}",
                    confidence=0.9,
                    extracted_at=now,
                    metadata={
                        "last_verified_at": now.isoformat(),
                        "hidden": "SECRET_METADATA",
                        "normalized_fields": [
                            {
                                "kind": dimension,
                                "competitor": product,
                                "dimension": dimension,
                                "price" if dimension == "pricing" else "support_level": price
                                if dimension == "pricing"
                                else True,
                                "unit": "CNY",
                                "market": "CN",
                                "source_quote": f"Original {price}",
                                "confidence": 0.9,
                            }
                        ],
                    },
                )
            )
    return detail


class InputReplay(RunService):
    def __init__(self, tmp_path, *, react=False):
        super().__init__(
            SkillRegistry.from_default_path(),
            Settings(
                demo_mode=True,
                analyst_react_enabled=react,
                writer_structured_report_enabled=False,
            ),
            journal=RunJournal(tmp_path / "journal.db"),
            kb_cache=KBCache.in_memory(),
            graph_checkpointer=GraphCheckpointer.in_memory(),
        )
        self.record = RunRecord(detail=replay_detail())
        self._runs[self.record.detail.id] = self.record
        self.inputs = []
        self.turns = {}

    async def _trace_llm_json(self, record, **kwargs):
        self.inputs.append(kwargs)
        if kwargs["agent"] == "analyst":
            product = kwargs["user"].split("Competitor: ")[1].splitlines()[0]
            dimension = kwargs["user"].split("Dimension: ")[1].splitlines()[0]
            source_id = f"{product.replace(' ', '-')}-{dimension}"
            claim = {"claim": f"{product} captured", "source_ids": [source_id], "confidence": 0.9}
            result = {
                "pricing_model" if dimension == "pricing" else "feature_tree": {
                    "summary_claims": [claim]
                }
            }
            if "react_turn" in kwargs["name"]:
                turn = self.turns.get(source_id, 0) + 1
                self.turns[source_id] = turn
                return (
                    {"action": "inspect_sources"}
                    if turn == 1
                    else {"action": "finish", "structured_knowledge": result}
                )
            return result
        if kwargs["agent"] == "comparator":
            return {"matrix_summary": ["Fixed products compared"], "winner_by_dimension": {}}
        return {"coverage_gaps": [], "gate_status": "pass"}

    async def _trace_llm_text(self, record, **kwargs):
        self.inputs.append(kwargs)
        return "## Competitive Findings\nCaptured [source:Phone-X-pricing]"


@pytest.mark.asyncio
@pytest.mark.parametrize("react", [False, True])
async def test_actual_analyst_inputs_and_tools_use_fixed_product_dimension_view(tmp_path, react):
    service = InputReplay(tmp_path, react=react)
    record = service.record
    snapshot = seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    # Mutable live sources are intentionally poisoned after freezing.
    for source in record.detail.raw_sources:
        source.snippet = "LIVE_POISON"
        source.metadata["normalized_fields"][0]["price"] = 99999
    for product in record.detail.plan.competitors:
        for dimension in record.detail.plan.dimensions:
            await service._real_analyst_branch_step(
                record, dimension, product, expected_snapshot_id=snapshot.id
            )
    for item in service.inputs:
        user = item["user"]
        assert "LIVE_POISON" not in user and "SECRET_METADATA" not in user and "99999" not in user
        assert snapshot.id in user and '"snapshot_version":1' in user
        product = user.split("Competitor: ")[1].splitlines()[0]
        dimension = user.split("Dimension: ")[1].splitlines()[0]
        assert f"{product.replace(' ', '-')}-{dimension}" in user
        assert ("5999" if product == "Phone X Pro" else "3999") in user
        if dimension == "feature":
            assert '"value":true' in user
        for other in snapshot.sources:
            if other.competitor != product or other.dimension != dimension:
                assert other.id not in user
    if react:
        tools = [
            item for item in record.detail.tool_call_messages if item.tool_name == "inspect_sources"
        ]
        assert len(tools) == 4
        assert all("LIVE_POISON" not in json.dumps(item.model_dump(mode="json")) for item in tools)
    assert len(record.detail.evidence_consumptions) == 4
    assert all(item.status == "validated" for item in record.detail.evidence_consumptions)
    assert snapshot == record.detail.evidence_snapshots[0]


@pytest.mark.asyncio
async def test_direct_analyst_records_safe_initial_analysis_and_rejects_collect(tmp_path):
    service = InputReplay(tmp_path)
    record = service.record
    await service._real_analyst_branch_step(record, "pricing", "Phone X")
    assert record.detail.evidence_consumptions
    assert record.detail.evidence_snapshots[-1].phase == "analysis"
    seal_snapshot(record.detail, phase="collect", canonical_documents={})
    before = len(service.inputs)
    with pytest.raises(EvidenceUseRejectedError):
        await service._real_analyst_branch_step(record, "pricing", "Phone X")
    assert len(service.inputs) == before


@pytest.mark.asyncio
async def test_comparator_reflector_actual_input_and_premerge_guard(tmp_path):
    service = InputReplay(tmp_path)
    record = service.record
    snapshot = seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    for product in record.detail.plan.competitors:
        for dimension in record.detail.plan.dimensions:
            await service._real_analyst_branch_step(
                record, dimension, product, expected_snapshot_id=snapshot.id
            )
    record.detail.raw_sources[0].snippet = "LIVE_POISON"
    await service._real_comparator_step(record)
    await service._real_reflector_step(record)
    for item in service.inputs:
        if item["agent"] in {"comparator", "reflector"}:
            assert snapshot.id in item["user"]
            assert "LIVE_POISON" not in item["user"]
            assert '"value":3999' in item["user"]
    assert {item.agent for item in record.detail.evidence_consumptions} >= {
        "analyst",
        "comparator",
        "reflector",
    }


@pytest.mark.asyncio
async def test_writer_segment_actual_input_uses_selected_ids_and_typed_snapshot(tmp_path):
    service = InputReplay(tmp_path)
    record = service.record
    snapshot = seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    await service._writer_segment_markdown(
        record,
        segment={
            "segment_name": "competitive_findings",
            "segment_competitor": "Phone X",
            "allowed_source_ids": ["Phone-X-pricing"],
            "groups": [],
        },
        timeout_seconds=1,
        language_guidance="",
        memory_context="",
        layer_context="",
        required_sections="",
        retry_count=0,
    )
    user = service.inputs[-1]["user"]
    assert snapshot.id in user and '"value":3999' in user
    assert "Phone-X-Pro-pricing" not in user
    consumption = record.detail.evidence_consumptions[-1]
    assert consumption.id in user
    assert consumption.source_ids == ("Phone-X-pricing",)
    assert consumption.status == "validated"
    assert consumption.estimated_bytes <= 8192


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [False, True])
async def test_writer_draft_does_not_publish_before_guard_or_lose_concurrent_messages(
    tmp_path, monkeypatch, changed
):
    service = InputReplay(tmp_path)
    record = service.record
    snapshot = seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    record.detail.report_md = "previous report"
    entered, release = asyncio.Event(), asyncio.Event()
    external_writes = []

    async def writer(candidate, *args):
        entered.set()
        candidate.detail.report_md = "DRAFT_ARTIFACT"
        await release.wait()
        return "accepted report [source:Phone-X-pricing]"

    monkeypatch.setattr(service, "_writer_markdown_report_from_evidence_pack", writer)
    monkeypatch.setattr(service, "_harden_report_markdown", lambda detail, md: md)
    monkeypatch.setattr(
        service,
        "_sync_enterprise_projection",
        lambda current, **kw: external_writes.append(current.detail.report_md),
    )
    task = asyncio.create_task(service._real_writer_step(record))
    await asyncio.wait_for(entered.wait(), 3)
    assert record.detail.report_md == "previous report"
    human = service._append_agent_message(
        record,
        from_agent="human",
        to_agent="writer",
        message_type="human_note",
        payload_schema="MarkdownReport",
        payload={"report_md": "human note"},
    )
    if changed:
        record.detail.raw_sources[0].metadata["normalized_fields"][0]["price"] = 4299
        seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    release.set()
    if changed:
        with pytest.raises(EvidenceUseRejectedError):
            await task
        assert record.detail.report_md == "previous report"
        assert external_writes == []
        assert not any(
            message.message_type == "report_ready" for message in record.detail.agent_messages
        )
    else:
        await task
        assert record.detail.report_md.startswith("accepted report")
        assert external_writes == [record.detail.report_md]
        assert any(
            item.agent == "writer" and item.snapshot_id == snapshot.id
            for item in record.detail.evidence_consumptions
        )
    assert human in record.detail.agent_messages
    assert len({item.id for item in record.detail.agent_messages}) == len(
        record.detail.agent_messages
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("delete", "canonical_document_unavailable"),
        ("update", "version_mismatch"),
        ("scope", "canonical_document_unavailable"),
    ],
)
async def test_final_qa_reloads_only_cited_canonical_document_and_reports_exact_gap(
    tmp_path, monkeypatch, mutation, reason
):
    path = tmp_path / "knowledge.db"
    monkeypatch.setenv("KB_DB_PATH", str(path))
    service = InputReplay(tmp_path)
    record = service.record
    source = record.detail.raw_sources[0]
    async with KnowledgeRepository(str(path)) as repo:
        document = await repo.upsert_document(
            DocumentCreate(
                workspace_id="ws-replay",
                project_id="project-replay",
                competitor=source.competitor,
                dimension=source.dimension,
                source_type=source.source_type,
                title=source.title,
                text="Canonical original 3999",
                last_verified_at=datetime.now(UTC),
            ),
            "canonical-body",
        )
        source.metadata.update(
            kb_document_id=document.id,
            kb_document_version=document.version,
            kb_document_content_hash=document.content_hash,
        )
    snapshot = await service._prepare_evidence_snapshot(record, phase="analysis")
    record.detail.report_md = f"Quoted price [source:{source.id}]"
    async with KnowledgeRepository(str(path)) as repo:
        if mutation == "delete":
            await repo.delete_document(document.id)
        elif mutation == "update":
            await repo._connection.execute(
                "UPDATE documents SET version = version + 1, "
                "content_hash = ?, text = ? WHERE id = ?",
                ("changed-canonical-body", "Canonical replacement 4299", document.id),
            )
            await repo._connection.commit()
        else:
            await repo._connection.execute(
                "UPDATE documents SET project_id = ? WHERE id = ?", ("other-project", document.id)
            )
            await repo._connection.commit()
    reads, qa_inputs = [], []
    original_read = KnowledgeRepository.get_document

    async def read(repo, document_id, *, scope=None):
        reads.append((document_id, scope))
        return await original_read(repo, document_id, scope=scope)

    monkeypatch.setattr(KnowledgeRepository, "get_document", read)
    monkeypatch.setattr(service, "_build_qa_issues", lambda detail: qa_inputs.append(detail) or [])
    await service._real_qa_step(record)
    assert [item[0] for item in reads] == [document.id]
    assert reads[0][1] == KnowledgeScope(
        workspace_id="ws-replay", project_id="project-replay", include_workspace_library=True
    )
    assert {item.id for item in qa_inputs[0].raw_sources} == {source.id}
    issue = next(
        item for item in record.detail.qa_findings if item.metadata.get("evidence_reason") == reason
    )
    assert issue.severity == "blocker"
    assert issue.metadata["source_ids"] == [source.id]
    assert set(issue.metadata["fact_ids"]) == {
        item.id for item in snapshot.facts if item.source_id == source.id
    }
    assert issue.redo_scope.kind == "collector"
    assert issue.redo_scope.target_competitor == source.competitor
    assert issue.redo_scope.target_subagent == source.dimension
    assert record.detail.evidence_snapshot_id == snapshot.id
    assert "4299" not in record.detail.report_md
    use = record.detail.evidence_consumptions[-1]
    assert use.agent == "qa" and use.snapshot_id == snapshot.id
    assert use.requested_source_ids == (source.id,) and use.estimated_bytes <= 8192


@pytest.mark.asyncio
async def test_full_writer_actual_llm_prompt_guard_and_live_accounting(tmp_path, monkeypatch):
    service = InputReplay(tmp_path)
    record = service.record
    snapshot = seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    for source in record.detail.raw_sources:
        source.snippet = "LIVE_POISON"
    monkeypatch.setattr(service, "_harden_report_markdown", lambda detail, report: report)
    await service._real_writer_step(record)
    call = next(item for item in service.inputs if item["agent"] == "writer")
    assert snapshot.id in call["user"] and "LIVE_POISON" not in call["user"]
    assert '"value":3999' in call["user"]
    assert record.detail.report_md
    assert next(
        item for item in record.detail.agent_messages if item.message_type == "report_ready"
    )
    assert any(item.kind == "writer" for item in record.detail.evidence_artifact_dependencies)
    assert all(
        item.status == "validated"
        for item in record.detail.evidence_consumptions
        if item.agent == "writer"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["timeout", "empty", "cache"])
async def test_analyst_fallback_cache_record_actual_dependencies(tmp_path, monkeypatch, mode):
    service = InputReplay(tmp_path)
    record = service.record
    snapshot = seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    if mode == "cache":
        await service._real_analyst_branch_step(
            record, "pricing", "Phone X", expected_snapshot_id=snapshot.id
        )
        service.inputs.clear()
    else:

        async def complete(*args, **kwargs):
            service.inputs.append(kwargs)
            if mode == "timeout":
                raise TimeoutError("offline timeout")
            return {}

        monkeypatch.setattr(service, "_trace_llm_json", complete)
    await service._real_analyst_branch_step(
        record, "pricing", "Phone X", expected_snapshot_id=snapshot.id
    )
    use = record.detail.evidence_consumptions[-1]
    assert use.source_ids == ("Phone-X-pricing",)
    assert use.status == ("reused" if mode == "cache" else "validated")
    if mode == "cache":
        assert service.inputs == [] and use.reused_from_snapshot_id == snapshot.id
    else:
        assert snapshot.id in service.inputs[-1]["user"]


@pytest.mark.asyncio
@pytest.mark.parametrize("agent", ["comparator", "reflector"])
async def test_upstream_product_mutation_before_return_cannot_commit(tmp_path, monkeypatch, agent):
    service = InputReplay(tmp_path)
    record = service.record
    seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    for product in record.detail.plan.competitors:
        for dimension in record.detail.plan.dimensions:
            await service._real_analyst_branch_step(record, dimension, product)
    if agent == "reflector":
        await service._real_comparator_step(record)
    before = record.detail.comparison_matrix
    entered, release = asyncio.Event(), asyncio.Event()

    async def waiting(*args, **kwargs):
        entered.set()
        await release.wait()
        return (
            {"matrix_summary": ["new matrix"]} if agent == "comparator" else {"gate_status": "pass"}
        )

    monkeypatch.setattr(service, "_trace_llm_json", waiting)
    task = asyncio.create_task(getattr(service, f"_real_{agent}_step")(record))
    await asyncio.wait_for(entered.wait(), 2)
    record.detail.competitor_kbs["Phone X"].slices["pricing"] = ["changed upstream analysis"]
    release.set()
    with pytest.raises(EvidenceUseRejectedError):
        await task
    assert record.detail.comparison_matrix == before
    assert not record.detail.reflections


@pytest.mark.asyncio
async def test_collector_qa_and_final_qa_phase_and_release_block(tmp_path, monkeypatch):
    service = InputReplay(tmp_path)
    record = service.record
    collect = seal_snapshot(record.detail, phase="collect", canonical_documents={})
    await service._real_phase_qa_step(record, "collect")
    assert any(
        item.agent == "collect_qa" and item.snapshot_id == collect.id
        for item in record.detail.evidence_consumptions
    )
    with pytest.raises(EvidenceUseRejectedError):
        await service._real_qa_step(record)
    seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    record.detail.report_md = "Invalid [source:missing-original-source]"
    monkeypatch.setattr(service, "_build_qa_issues", lambda detail: [])
    await service._real_qa_step(record)
    assert record.detail.qa_findings[0].metadata["unpublishable_evidence"]
    record.detail.status = "completed"
    assert service._sync_enterprise_projection(record, notify_release_gate=True) is None
    assert record.detail.status == "completed_with_blockers"


@pytest.mark.asyncio
async def test_final_qa_cannot_commit_audit_of_report_changed_during_canonical_read(
    tmp_path, monkeypatch
):
    service = InputReplay(tmp_path)
    record = service.record
    seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    record.detail.report_md = "Original report [source:Phone-X-pricing]"
    original = service._final_qa_evidence

    async def audit(current):
        result = await original(current)
        current.detail.report_md = "Different report [source:Phone-X-Pro-pricing]"
        return result

    monkeypatch.setattr(service, "_final_qa_evidence", audit)
    with pytest.raises(EvidenceUseRejectedError):
        await service._real_qa_step(record)
    assert record.detail.qa_findings == []


@pytest.mark.asyncio
async def test_final_qa_audits_original_report_facts_and_blocks_known_current_correction(
    tmp_path, monkeypatch
):
    service = InputReplay(tmp_path)
    record = service.record
    original = seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    view, use = service._begin_evidence_use(record, agent="writer", source_ids=["Phone-X-pricing"])
    service._validate_evidence_use(record, use)
    record.detail.report_md = "Price 3999 [source:Phone-X-pricing]"
    service._record_evidence_artifact(
        record,
        kind="writer",
        uses=[use],
        payload={"report_md": record.detail.report_md, "artifact": None},
    )
    record.detail.raw_sources[0].metadata["normalized_fields"][0]["price"] = 4299
    current = seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    inputs = []
    monkeypatch.setattr(service, "_build_qa_issues", lambda detail: inputs.append(detail) or [])
    await service._real_qa_step(record)
    issue = next(
        item
        for item in record.detail.qa_findings
        if item.metadata.get("evidence_reason") == "source_dependency_changed"
    )
    assert issue.metadata["snapshot_id"] == original.id
    assert set(issue.metadata["fact_ids"]) == {
        fact.id for fact in original.facts if fact.source_id == "Phone-X-pricing"
    }
    assert inputs[0].raw_sources[0].metadata["normalized_fields"][0]["price"] == 3999
    assert (
        record.detail.report_md.startswith("Price 3999")
        and record.detail.evidence_snapshot_id == current.id
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("context_change", [None, "currency", "market", "time"])
async def test_comparator_alignment_uses_same_fact_slot_and_context(tmp_path, context_change):
    service = InputReplay(tmp_path)
    record = service.record
    record.detail.plan.dimensions = ["pricing"]
    record.detail.raw_sources = [
        source for source in record.detail.raw_sources if source.dimension == "pricing"
    ]
    for source in record.detail.raw_sources:
        source.metadata["normalized_fields"].append(
            {
                "kind": "pricing",
                "competitor": source.competitor,
                "dimension": "pricing",
                "tier_name": "Base",
                "billing_cycle": "monthly",
                "market": "CN",
                "source_quote": "Base is billed monthly",
                "confidence": 0.9,
            }
        )
    other_price = record.detail.raw_sources[1].metadata["normalized_fields"][0]
    if context_change == "currency":
        other_price["unit"] = "USD"
    elif context_change == "market":
        other_price["market"] = "US"
    elif context_change == "time":
        other_price["qualifiers"] = {"effective_at": "2026-09-01"}
    seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    for product in record.detail.plan.competitors:
        await service._real_analyst_branch_step(record, "pricing", product)
    await service._real_comparator_step(record)
    reasons = [text for text in record.detail.comparison_matrix.summary if "Not comparable" in text]
    assert bool(reasons) == bool(context_change)


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [False, True])
async def test_writer_actual_transport_usage_and_trace_survive_draft_rejection(
    tmp_path, monkeypatch, changed
):
    service = InputReplay(tmp_path)
    record = service.record
    seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    service._trace_store = TraceStore(tmp_path / "trace.db")
    # Execute the original accounting/trace path; only the provider transport is replayed.
    monkeypatch.setattr(service, "_trace_llm_text", RunService._trace_llm_text.__get__(service))
    monkeypatch.setattr(service, "_harden_report_markdown", lambda detail, report: report)
    entered, release = asyncio.Event(), asyncio.Event()
    captured, writes = [], []

    async def complete_text(*, system, user):
        captured.append(user)
        entered.set()
        await release.wait()
        return "## Competitive Findings\nKnown price [source:Phone-X-pricing]"

    monkeypatch.setattr(service._llm, "complete_text", complete_text)
    monkeypatch.setattr(
        service._llm,
        "consume_last_usage",
        lambda: LLMUsage(prompt_tokens=117, completion_tokens=23, total_tokens=140),
    )
    monkeypatch.setattr(
        service,
        "_sync_enterprise_projection",
        lambda current, **kw: writes.append(current.detail.report_md),
    )
    task = asyncio.create_task(service._real_writer_step(record))
    await asyncio.wait_for(entered.wait(), 3)
    assert record.detail.llm_budget_checkpoint["calls"] == 1
    assert not any(
        item.message_type == "report_ready"
        for item in service._trace_store.list_agent_messages(record.detail.id)
    )
    human = service._append_agent_message(
        record,
        from_agent="human",
        to_agent="writer",
        message_type="human_note",
        payload_schema="MarkdownReport",
        payload={"report_md": "human while awaiting"},
    )
    if changed:
        record.detail.raw_sources[0].metadata["normalized_fields"][0]["price"] = 4299
        seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    release.set()
    if changed:
        with pytest.raises(EvidenceUseRejectedError):
            await task
        assert record.detail.report_md == "" and writes == []
        assert not any(
            item.message_type == "report_ready"
            for item in service._trace_store.list_agent_messages(record.detail.id)
        )
    else:
        await task
        assert writes == [record.detail.report_md]
        assert (
            sum(
                item.message_type == "report_ready"
                for item in service._trace_store.list_agent_messages(record.detail.id)
            )
            == 1
        )
    assert record.detail.llm_budget_checkpoint["calls"] == 1
    assert record.detail.llm_budget_checkpoint["tokens_charged"] == 140
    assert record.llm_budget.tokens_used == 140
    spans = [
        item for item in service._trace_store.list_spans(record.detail.id) if item.kind == "llm"
    ]
    assert len(spans) == 1 and spans[0].metadata["llm_tokens_charged"] == 140
    assert human.id in {
        item.id for item in service._trace_store.list_agent_messages(record.detail.id)
    }
    assert len(record.detail.agent_messages) == len(
        {item.id for item in record.detail.agent_messages}
    )


@pytest.mark.asyncio
async def test_comparator_budget_omission_drops_unsupported_analytic_branch(tmp_path, monkeypatch):
    service = InputReplay(tmp_path)
    record = service.record
    record.detail.plan.research_depth = "deep"
    record.detail.raw_sources[0].metadata["normalized_fields"][0]["source_quote"] = "q" * 5000
    seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    original = service._trace_llm_json

    async def answer(candidate, **kwargs):
        if kwargs["agent"] == "analyst":
            service.inputs.append(kwargs)
            return {
                "pricing_model": {
                    "notes": [
                        {
                            "claim": "OMITTED_ANALYTIC_SENTINEL",
                            "source_ids": ["Phone-X-pricing"],
                            "confidence": 0.9,
                        }
                    ]
                }
            }
        return await original(candidate, **kwargs)

    monkeypatch.setattr(service, "_trace_llm_json", answer)
    await service._real_analyst_branch_step(record, "pricing", "Phone X")
    assert (
        "OMITTED_ANALYTIC_SENTINEL" in record.detail.competitor_kbs["Phone X"].slices["pricing"][0]
    )
    record.detail.plan.research_depth = "quick"
    await service._real_comparator_step(record)
    use = record.detail.evidence_consumptions[-1]
    assert "Phone-X-pricing" not in use.source_ids
    user = service.inputs[-1]["user"]
    assert "OMITTED_ANALYTIC_SENTINEL" not in user
    assert "context_budget_exceeded" in user


@pytest.mark.asyncio
async def test_analyst_rejects_claim_for_same_branch_source_omitted_by_budget(
    tmp_path, monkeypatch
):
    service = InputReplay(tmp_path)
    record = service.record
    record.detail.raw_sources[0].metadata["normalized_fields"][0]["source_quote"] = "q" * 5000
    seal_snapshot(record.detail, phase="analysis", canonical_documents={})

    async def answer(candidate, **kwargs):
        service.inputs.append(kwargs)
        return {
            "pricing_model": {
                "notes": [
                    {
                        "claim": "UNCONSUMED_MODEL_CLAIM",
                        "source_ids": ["Phone-X-pricing"],
                        "confidence": 0.9,
                    }
                ]
            }
        }

    monkeypatch.setattr(service, "_trace_llm_json", answer)
    await service._real_analyst_branch_step(record, "pricing", "Phone X")
    use = record.detail.evidence_consumptions[-1]
    assert use.source_ids == ()
    assert "Phone-X-pricing" not in service.inputs[-1]["user"]
    assert not record.detail.competitor_knowledge["Phone X"].pricing_model.notes
    assert "UNCONSUMED_MODEL_CLAIM" not in str(record.detail.claim_card_bundles)


@pytest.mark.asyncio
async def test_long_valid_analysis_is_an_explicit_prompt_gap_within_view_budget(tmp_path):
    service = InputReplay(tmp_path)
    record = service.record
    seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    await service._real_analyst_branch_step(record, "pricing", "Phone X")
    record.detail.competitor_kbs["Phone X"].slices["pricing"] = ["LONG_ANALYSIS_SENTINEL" * 2000]
    producer = record.detail.evidence_consumptions[-1]
    service._record_evidence_artifact(
        record,
        kind="analyst",
        competitor="Phone X",
        dimension="pricing",
        uses=[producer],
        payload=service._analyst_evidence_artifact_payload(record.detail, "Phone X", "pricing"),
    )
    await service._real_comparator_step(record)
    user = service.inputs[-1]["user"]
    assert "LONG_ANALYSIS_SENTINEL" not in user
    assert "analysis_context_budget_exceeded" in user
    view = json.loads(user.split("Evidence View JSON: ")[1])
    assert view["estimated_bytes"] <= 8192
    assert any(fact["value"] == 3999 for fact in view["facts"])


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["fragment", "evidence_id", "alias"])
async def test_existing_legal_citation_resolves_before_fixed_qa(tmp_path, kind):
    service = InputReplay(tmp_path)
    record = service.record
    seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    projection = build_enterprise_projection(
        record.detail, workspace_id=record.detail.workspace_id, project_id=record.detail.project_id
    )
    record.detail.enterprise_projection = projection
    evidence = next(x for x in projection.evidence_records if x.raw_source_id == "Phone-X-pricing")
    if kind == "fragment":
        token = "Phone-X-pricing#plan"
    elif kind == "evidence_id":
        token = evidence.id
    else:
        token = "legacy-phone-price"
        evidence.metadata["raw_source_aliases"] = [token]
    record.detail.report_md = f"Original price [source:{token}]"
    canonical = resolve_source_token(token, service._source_alias_map(record.detail))
    projected, issues, uses = await service._final_qa_evidence(record)
    assert canonical == "Phone-X-pricing"
    assert not issues
    assert [x.id for x in projected.raw_sources] == ["Phone-X-pricing"]


@pytest.mark.asyncio
async def test_two_matching_fact_slots_remain_comparable(tmp_path):
    service = InputReplay(tmp_path)
    record = service.record
    record.detail.plan.dimensions = ["feature"]
    record.detail.raw_sources = [x for x in record.detail.raw_sources if x.dimension == "feature"]
    for source in record.detail.raw_sources:
        source.metadata["normalized_fields"] = [
            {
                "kind": "feature",
                "dimension": "feature",
                "competitor": source.competitor,
                "slot": slot,
                "support_level": "supported",
                "evidence_quote": f"{slot} supported",
                "evidence_item_ids": [f"{source.id}-{slot}"],
                "unit": "capability",
                "market": "CN",
                "confidence": 0.9,
            }
            for slot in ["camera", "display"]
        ]
    seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    for product in record.detail.plan.competitors:
        await service._real_analyst_branch_step(record, "feature", product)

    async def comparator(current, **kwargs):
        service.inputs.append(kwargs)
        return {
            "matrix_summary": ["same slot/context supported"],
            "winner_by_dimension": {"feature": "Phone X"},
        }

    service._trace_llm_json = comparator
    await service._real_comparator_step(record)
    assert not any("Not comparable" in x for x in record.detail.comparison_matrix.summary)


@pytest.mark.asyncio
async def test_shard_notes_survive_section_writer_input(tmp_path):
    service = InputReplay(tmp_path)
    record = service.record
    seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    note = "SHARD_SYNTHESIS_FROM_PHONE_X_PRICING_3999 [source:Phone-X-pricing]"
    segment = service._writer_section_segment_from_shards(
        record.detail,
        section_id="competitive_findings",
        segment_competitor=None,
        shard_notes=[note],
        allowed_source_ids={"Phone-X-pricing"},
    )
    await service._writer_segment_markdown(
        record,
        segment=segment,
        timeout_seconds=1,
        language_guidance="",
        memory_context="",
        layer_context="",
        required_sections="",
        retry_count=0,
    )
    user = service.inputs[-1]["user"]
    assert note in user


@pytest.mark.asyncio
@pytest.mark.parametrize("depth,budget", [("quick", 8192), ("standard", 16384), ("deep", 24576)])
async def test_writer_segment_data_budget_includes_wrapper(tmp_path, depth, budget):
    service = InputReplay(tmp_path)
    record = service.record
    record.detail.plan.research_depth = depth
    # Fill one source's paired value/quote up to just below the evidence-view bound.
    record.detail.raw_sources = [record.detail.raw_sources[0]]
    source = record.detail.raw_sources[0]
    record.detail.plan.competitors = ["Phone X"]
    record.detail.plan.dimensions = ["pricing"]
    size = (budget - 2250) // 3
    source.metadata["normalized_fields"][0].update(
        source_quote="Q" * size, price="V" * size, evidence_item_ids=["original-price-item"]
    )
    seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    segment = {
        "segment_name": "competitive_findings",
        "section_id": "competitive_findings",
        "allowed_source_ids": [source.id],
        "required_h2_headings": ["Competitive findings"],
        "repair_targets": {"reason": "Publication wording repair " * 10},
    }
    await service._writer_segment_markdown(
        record,
        segment=segment,
        timeout_seconds=1,
        language_guidance="",
        memory_context="",
        layer_context="",
        required_sections="",
        retry_count=0,
    )
    user = service.inputs[-1]["user"]
    context = user.split("Segment Context JSON: ")[1].split("\n\nRequired sections")[0]
    use = record.detail.evidence_consumptions[-1]
    assert len(context.encode()) <= budget
    assert use.max_bytes == budget
    assert use.estimated_bytes == len(context.encode())
    assert use.estimated_tokens == len(context.encode()) + 256
    assert use.requested_source_ids == (source.id,)
    data = json.loads(context)
    for fact in data["evidence_view"]["facts"]:
        if fact["field"] == "price":
            assert fact["value"] == "V" * size
            assert fact["quote"] == "Q" * size
    if not use.source_ids:
        assert "context_budget_exceeded" in context
        assert data["citation_source_ids"] == []


@pytest.mark.asyncio
async def test_missing_unit_and_market_are_not_comparable(tmp_path):
    service = InputReplay(tmp_path)
    record = service.record
    record.detail.plan.dimensions = ["pricing"]
    record.detail.raw_sources = [x for x in record.detail.raw_sources if x.dimension == "pricing"]
    for source in record.detail.raw_sources:
        row = source.metadata["normalized_fields"][0]
        row.pop("unit", None)
        row.pop("market", None)
        row["evidence_item_ids"] = [f"{source.id}-original-item"]
    seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    for product in record.detail.plan.competitors:
        await service._real_analyst_branch_step(record, "pricing", product)

    async def comparator(current, **kwargs):
        service.inputs.append(kwargs)
        return {
            "matrix_summary": ["compared prices"],
            "winner_by_dimension": {"pricing": "Phone X"},
        }

    service._trace_llm_json = comparator
    await service._real_comparator_step(record)
    assert any(
        "Not comparable" in x or "comparison_basis_unknown" in x
        for x in record.detail.comparison_matrix.summary
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("dimension", ["feature", "pricing"])
async def test_matching_slots_allow_boolean_without_units_and_prices_in_matching_tiers(
    tmp_path, dimension
):
    service = InputReplay(tmp_path)
    record = service.record
    record.detail.plan.dimensions = [dimension]
    record.detail.plan.research_depth = "standard"
    record.detail.raw_sources = [
        source for source in record.detail.raw_sources if source.dimension == dimension
    ]
    for source in record.detail.raw_sources:
        if dimension == "feature":
            rows = [
                {
                    "kind": "feature",
                    "slot": slot,
                    "support_level": True,
                    "evidence_quote": f"{slot} supported",
                    "confidence": 0.9,
                }
                for slot in ("camera", "display")
            ]
        else:
            rows = [
                {
                    "kind": "pricing",
                    "tier_name": tier,
                    "price": price,
                    "unit": "CNY",
                    "market": "CN",
                    "billing_cycle": "monthly",
                    "source_quote": f"{tier} {price} CNY monthly CN",
                    "confidence": 0.9,
                }
                for tier, price in (("Starter", 20), ("Pro", 40))
            ]
        source.metadata["normalized_fields"] = [
            {**row, "competitor": source.competitor, "dimension": dimension} for row in rows
        ]
    seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    for product in record.detail.plan.competitors:
        await service._real_analyst_branch_step(record, dimension, product)

    async def comparator(current, **kwargs):
        service.inputs.append(kwargs)
        return {
            "matrix_summary": ["Aligned same slot"],
            "winner_by_dimension": {dimension: "Phone X"},
        }

    service._trace_llm_json = comparator
    await service._real_comparator_step(record)
    assert len(record.detail.evidence_consumptions[-1].fact_ids) == (
        12 if dimension == "pricing" else 8
    )
    assert not any("Not comparable" in item for item in record.detail.comparison_matrix.summary)
    assert record.detail.comparison_matrix.winner_by_dimension[dimension] == "Phone X"


@pytest.mark.asyncio
@pytest.mark.parametrize("over_budget", [False, True])
async def test_writer_shard_notes_require_selected_sources_and_explicit_budget_gap(
    tmp_path, over_budget
):
    service = InputReplay(tmp_path)
    record = service.record
    seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    valid = (
        "LONG_SHARD_NOTE" * 1500 if over_budget else "VALID_SHARD_NOTE"
    ) + " [source:Phone-X-pricing]"
    segment = service._writer_section_segment_from_shards(
        record.detail,
        section_id="competitive_findings",
        segment_competitor="Phone X",
        shard_notes=[valid, "OTHER_PRODUCT_NOTE [source:Phone-X-Pro-pricing]"],
        allowed_source_ids={"Phone-X-pricing"},
    )
    await service._writer_segment_markdown(
        record,
        segment=segment,
        timeout_seconds=1,
        language_guidance="",
        memory_context="",
        layer_context="",
        required_sections="",
        retry_count=0,
    )
    user = service.inputs[-1]["user"]
    assert "OTHER_PRODUCT_NOTE" not in user
    assert "shard_notes_gap" in user
    if over_budget:
        assert "LONG_SHARD_NOTE" not in user
        assert "shard_notes_context_budget_exceeded" in user
    else:
        assert valid in user
        assert "receives evidence shard notes" in user
    context = user.split("Segment Context JSON: ")[1].split("\n\nRequired sections")[0]
    assert len(context.encode()) == record.detail.evidence_consumptions[-1].estimated_bytes
    assert len(context.encode()) <= 8192


@pytest.mark.asyncio
async def test_writer_rejects_oversized_controls_before_llm_or_artifact_write(tmp_path):
    service = InputReplay(tmp_path)
    record = service.record
    seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    record.detail.report_md = "Previous report"
    with pytest.raises(EvidenceUseRejectedError, match="control contract exceeds context budget"):
        await service._writer_segment_markdown(
            record,
            segment={
                "segment_name": "competitive_findings",
                "allowed_source_ids": ["Phone-X-pricing"],
                "repair_targets": {"reason": "MANDATORY_CONTROL" * 1000},
            },
            timeout_seconds=1,
            language_guidance="",
            memory_context="",
            layer_context="",
            required_sections="",
            retry_count=0,
        )
    assert not service.inputs
    assert record.detail.report_md == "Previous report"
    assert record.detail.evidence_consumptions[-1].status == "rejected"


def test_writer_view_budget_is_optional_in_legacy_json_and_cannot_exceed_stage_budget(tmp_path):
    service = InputReplay(tmp_path)
    seal_snapshot(service.record.detail, phase="analysis", canonical_documents={})
    _, use = service._begin_evidence_use(service.record, agent="writer")
    legacy = use.model_dump(mode="json")
    assert "view_max_bytes" not in legacy
    with pytest.raises(ValueError, match="view budget exceeds stage budget"):
        type(use).model_validate({**legacy, "view_max_bytes": use.max_bytes + 1})
    # model_copy bypasses Pydantic validation; the commit guard still rejects it.
    changed = use.model_copy(update={"view_max_bytes": use.max_bytes + 1})
    service.record.detail.evidence_consumptions = [changed]
    with pytest.raises(EvidenceUseRejectedError, match="view budget exceeds stage budget"):
        service._validate_evidence_use(service.record, changed)


@pytest.mark.asyncio
async def test_different_price_tiers_require_matching_product_counterparts(tmp_path):
    service = InputReplay(tmp_path)
    record = service.record
    record.detail.plan.dimensions = ["pricing"]
    record.detail.raw_sources = [
        source for source in record.detail.raw_sources if source.dimension == "pricing"
    ]
    for source, tier in zip(record.detail.raw_sources, ["Starter", "Enterprise"], strict=True):
        row = source.metadata["normalized_fields"][0]
        row.update(
            tier_name=tier,
            billing_cycle="monthly",
            source_quote=f"{tier} {row['price']} CNY monthly CN",
            evidence_item_ids=[f"{source.id}-{tier}"],
        )
    seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    for product in record.detail.plan.competitors:
        await service._real_analyst_branch_step(record, "pricing", product)

    async def comparator(current, **kwargs):
        service.inputs.append(kwargs)
        return {
            "matrix_summary": ["Compare Starter with Enterprise"],
            "winner_by_dimension": {"pricing": "Phone X"},
        }

    service._trace_llm_json = comparator
    await service._real_comparator_step(record)
    matrix = record.detail.comparison_matrix
    assert matrix.winner_by_dimension["pricing"] == "tie"
    assert any("comparison_counterpart_missing" in item for item in matrix.summary)
    assert any("Starter" in item and "Phone X Pro" in item for item in matrix.summary)
    assert any("Enterprise" in item and "Phone X" in item for item in matrix.summary)


def seed_previous_writer_report(service, *, producer=True, phase="analysis"):
    record = service.record
    snapshot = seal_snapshot(record.detail, phase=phase, canonical_documents={})
    record.detail.report_md = "## Competitive Findings\nPrice is 3999 CNY. [source:Phone-X-pricing]"
    if producer:
        _, use = service._begin_evidence_use(
            record,
            agent="writer" if phase == "analysis" else "collect_qa",
            source_ids=["Phone-X-pricing"],
        )
        service._validate_evidence_use(record, use)
        use = record.detail.evidence_consumptions[-1]
        if phase == "collect":
            use = use.model_copy(update={"agent": "writer"})
            record.detail.evidence_consumptions[-1] = use
        service._record_evidence_artifact(
            record,
            kind="writer",
            uses=[use],
            payload={"report_md": record.detail.report_md, "artifact": None},
        )
    return snapshot


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["timeout", "error", "anti_regression"])
@pytest.mark.parametrize("producer", [True, False])
async def test_actual_writer_preserve_retains_original_producer_or_blocks_unknown(
    tmp_path, monkeypatch, mode, producer
):
    service = InputReplay(tmp_path)
    record = service.record
    original = seed_previous_writer_report(service, producer=producer)
    previous = record.detail.report_md
    dependency = next(iter(record.detail.evidence_artifact_dependencies), None)
    record.detail.raw_sources[0].metadata["normalized_fields"][0]["price"] = 4299
    current = seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    monkeypatch.setattr(service, "_harden_report_markdown", lambda detail, text: text)
    projections = []
    monkeypatch.setattr(
        service, "_sync_enterprise_projection", lambda *a, **kw: projections.append(1)
    )
    calls = []

    async def complete(current_record, **kwargs):
        calls.append(kwargs)
        if mode == "timeout":
            raise TimeoutError("offline forced timeout")
        if mode == "error":
            raise RuntimeError("offline forced failure")
        return "## Competitive Findings\nNew inferior draft [source:Phone-X-pricing]"

    monkeypatch.setattr(service, "_trace_llm_text", complete)
    if mode == "anti_regression":
        issue = QCIssue(
            id="preserve-redo",
            severity="warn",
            detected_by="text_quality",
            target_agent="writer",
            problem="Preserve verified report depth",
            field_path="report_md",
            redo_scope=RedoScope(kind="writer_only", rationale="Preserve verified report depth"),
        )
        service._append_agent_message(
            record,
            from_agent="qa",
            to_agent="writer",
            message_type="redo_request",
            payload_schema="RedoRequestPayload",
            payload={
                "issues": [issue.model_dump(mode="json")],
                "issue_ids": [issue.id],
                "redo_scope": issue.redo_scope.model_dump(mode="json"),
            },
        )
        monkeypatch.setattr(
            "packages.agents.writer.logic.build_writer_repair_plan",
            lambda *a, **kw: WriterRepairPlan(
                mode="full",
                reason="verify preservation",
                previous_report_protectable=True,
                anti_regression_required=True,
            ),
        )
        monkeypatch.setattr(
            "packages.agents.writer.logic.report_regression_problem",
            lambda *a, **kw: "candidate loses verified report depth",
        )
    await service._real_writer_step(record)
    assert calls and current.id in calls[0]["user"]
    assert record.detail.report_md == previous
    committed = next(x for x in record.detail.evidence_artifact_dependencies if x.kind == "writer")
    if producer:
        assert committed == dependency
        assert service._final_qa_snapshot(record).id == original.id
    else:
        assert committed.consumption_ids == ()
    _, issues, _ = await service._final_qa_evidence(record)
    reasons = {x.metadata["evidence_reason"] for x in issues}
    assert ("source_dependency_changed" if producer else "writer_producer_unverified") in reasons
    assert all(x.metadata["unpublishable_evidence"] for x in issues)
    assert projections == []


@pytest.mark.asyncio
async def test_actual_preserved_report_hardening_cannot_forge_new_producer(tmp_path, monkeypatch):
    service = InputReplay(tmp_path)
    record = service.record
    original = seed_previous_writer_report(service)
    dependency = record.detail.evidence_artifact_dependencies[-1]
    previous = record.detail.report_md

    async def timeout(*args, **kwargs):
        raise TimeoutError("offline timeout")

    monkeypatch.setattr(service, "_trace_llm_text", timeout)
    monkeypatch.setattr(
        service, "_harden_report_markdown", lambda detail, text: text + "\nHardener added prose"
    )
    await service._real_writer_step(record)
    assert record.detail.report_md != previous
    assert record.detail.evidence_artifact_dependencies[-1] == dependency
    assert service._final_qa_snapshot(record).id == original.id
    _, issues, _ = await service._final_qa_evidence(record)
    assert any(x.metadata["evidence_reason"] == "writer_producer_unverified" for x in issues)


@pytest.mark.asyncio
async def test_actual_new_writer_report_records_current_generation(tmp_path, monkeypatch):
    service = InputReplay(tmp_path)
    record = service.record
    original = seed_previous_writer_report(service)
    record.detail.raw_sources[0].metadata["normalized_fields"][0]["price"] = 4299
    current = seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    monkeypatch.setattr(service, "_harden_report_markdown", lambda detail, text: text)
    await service._real_writer_step(record)
    dependency = record.detail.evidence_artifact_dependencies[-1]
    consumed = [
        x for x in record.detail.evidence_consumptions if x.id in dependency.consumption_ids
    ]
    assert consumed and {x.snapshot_id for x in consumed} == {current.id}
    assert original.id != service._final_qa_snapshot(record).id == current.id
    _, issues, _ = await service._final_qa_evidence(record)
    assert not issues


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["run", "workspace", "project", "collect"])
async def test_historical_qa_rejects_foreign_identity_or_collect_snapshot(tmp_path, changed):
    service = InputReplay(tmp_path)
    record = service.record
    original = seed_previous_writer_report(
        service, phase="collect" if changed == "collect" else "analysis"
    )
    original_dump = original.model_dump(mode="json")
    if changed != "collect":
        field = {"run": "id", "workspace": "workspace_id", "project": "project_id"}[changed]
        setattr(record.detail, field, f"different-{changed}")
    if changed == "run":
        current_detail = record.detail.model_copy(deep=True)
        current_detail.evidence_snapshots = []
        current_detail.evidence_snapshot_id = None
        current = seal_snapshot(current_detail, phase="analysis", canonical_documents={})
        record.detail.evidence_snapshots.append(current)
        record.detail.evidence_snapshot_id = current.id
    else:
        seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    before = len(record.detail.evidence_consumptions)
    with pytest.raises(EvidenceUseRejectedError, match="identity|scope|phase"):
        service._begin_evidence_use(record, agent="qa", source_ids=["Phone-X-pricing"])
    assert len(record.detail.evidence_consumptions) == before
    assert original.model_dump(mode="json") == original_dump


@pytest.mark.asyncio
@pytest.mark.parametrize("token", ["Phone-X-pricing", "Phone-X-pricing#plan"])
async def test_new_writer_producer_survives_actual_projection_normalization(
    tmp_path, monkeypatch, token
):
    service = InputReplay(tmp_path)
    record = service.record
    source = next(item for item in record.detail.raw_sources if item.id == "Phone-X-pricing")
    source.metadata.update(market="CN", source_material_level="full_source")
    row = source.metadata["normalized_fields"][0]
    row.update(
        price={"amount": 3999, "currency": "CNY"},
        source_quote="Phone X 128 GB, new device, CNY 3999 including tax.",
        evidence_item_ids=["item-phone-x-current-price"],
        qualifiers={
            "price_type": "official_current",
            "price_basis": "device",
            "model": "Phone X",
            "capacity": "128 GB",
            "condition": "new",
            "billing_interval": "one_time",
            "tax_scope": "included",
            "verified_at": record.detail.created_at.isoformat(),
        },
    )
    original = seal_snapshot(record.detail, phase="analysis", canonical_documents={})

    async def complete(*args, **kwargs):
        return f"## Competitive Findings\nPrice 3999 CNY [source:{token}]"

    monkeypatch.setattr(service, "_trace_llm_text", complete)
    monkeypatch.setattr(service, "_harden_report_markdown", lambda detail, text: text)
    projections = []

    def project(candidate, **kwargs):
        projection = build_enterprise_projection(
            candidate.detail,
            workspace_id=candidate.detail.workspace_id,
            project_id=candidate.detail.project_id,
        )
        candidate.detail.enterprise_projection = projection
        candidate.detail.report_md = projection.report_version.report_md
        projections.append(projection)
        return projection

    monkeypatch.setattr(service, "_sync_enterprise_projection", project)
    await service._real_writer_step(record)
    _, issues, uses = await service._final_qa_evidence(record)
    assert len(projections) == 1
    assert "[source:Phone-X-pricing]" in record.detail.report_md
    assert "#plan" not in record.detail.report_md
    assert issues == []
    assert {use.snapshot_id for use in uses} == {original.id}


@pytest.mark.asyncio
async def test_same_scope_historical_qa_retains_original_hash_and_audits_change(tmp_path):
    service = InputReplay(tmp_path)
    record = service.record
    original = seed_previous_writer_report(service)
    original_dump = original.model_dump(mode="json")
    record.detail.raw_sources[0].metadata["normalized_fields"][0]["price"] = 4299
    seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    _, issues, uses = await service._final_qa_evidence(record)
    for use in uses:
        service._validate_evidence_use(record, use)
    assert {x.snapshot_id for x in uses} == {original.id}
    assert {x.metadata["evidence_reason"] for x in issues} == {"source_dependency_changed"}
    assert original.model_dump(mode="json") == original_dump


@pytest.mark.asyncio
@pytest.mark.parametrize("historical_writer", [True, False])
async def test_analyst_checkpoint_uses_current_analysis_after_real_reanalysis(
    tmp_path, monkeypatch, historical_writer
):
    service = InputReplay(tmp_path)
    record = service.record
    original = seed_previous_writer_report(service)
    original_dump = original.model_dump(mode="json")
    record.detail.raw_sources[0].metadata["normalized_fields"][0]["price"] = 4299
    current = seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    for product in record.detail.plan.competitors:
        for dimension in record.detail.plan.dimensions:
            await service._real_analyst_branch_step(
                record, dimension, product, expected_snapshot_id=current.id
            )
    assert service._evidence_artifact_valid(
        record,
        kind="analyst",
        competitor="Phone X",
        dimension="pricing",
        payload=service._analyst_evidence_artifact_payload(record.detail, "Phone X", "pricing"),
    )
    if not historical_writer:
        record.detail.evidence_artifact_dependencies = [
            item for item in record.detail.evidence_artifact_dependencies if item.kind != "writer"
        ]
    captured = []
    build = service._build_analyst_qa_issues

    def inspect(detail, missing):
        captured.append(detail)
        return build(detail, missing)

    monkeypatch.setattr(service, "_build_analyst_qa_issues", inspect)
    record.detail.current_node = "analyst_join"
    start_ids = {use.id for use in record.detail.evidence_consumptions}
    await service._real_phase_qa_step(record, "analyst")
    uses = [use for use in record.detail.evidence_consumptions if use.id not in start_ids]
    prices = [
        row["price"]
        for source in captured[0].raw_sources
        for row in source.metadata["normalized_fields"]
        if "price" in row
    ]
    assert uses and {use.snapshot_id for use in uses} == {current.id}
    assert {use.agent for use in uses} == {"analyst_qa"}
    assert 4299 in prices and 3999 not in prices
    assert record.detail.qa_findings == []
    assert original.model_dump(mode="json") == original_dump


def test_analyst_checkpoint_credential_rejects_unaccepted_collect_phase(tmp_path):
    service = InputReplay(tmp_path)
    record = service.record
    seal_snapshot(record.detail, phase="collect", canonical_documents={})
    _, use = service._begin_evidence_use(
        record, agent="analyst_qa", source_ids=["Phone-X-pricing"]
    )
    with pytest.raises(EvidenceUseRejectedError, match="not currently accepted"):
        service._validate_evidence_use(record, use)
    assert record.detail.evidence_consumptions[-1].status == "rejected"
