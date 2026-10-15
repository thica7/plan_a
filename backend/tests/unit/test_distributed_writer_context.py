from test_stage_evidence_views import distributed_detail
from types import SimpleNamespace

import pytest

from packages.config import Settings
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunRecord, RunService
from packages.research.evidence.snapshot import seal_snapshot
from packages.skills.registry import SkillRegistry


def test_writer_actual_prompt_includes_each_collected_product_with_price_gaps():
    detail = distributed_detail()
    detail.plan.dimensions = ["feature", "pricing"]
    service = RunService(SkillRegistry.from_default_path(), Settings(demo_mode=True), graph_checkpointer=GraphCheckpointer.in_memory())
    record = RunRecord(detail)
    seal_snapshot(detail, phase="analysis", canonical_documents={})
    selected, use = service._writer_segment_evidence(record, {"segment_name": "full_report", "allowed_source_ids": [source.id for source in detail.raw_sources]})
    assert {fact["competitor"] for fact in selected["evidence_view"]["facts"]} == set(detail.plan.competitors)
    assert use.estimated_bytes <= 8192
    assert all(boundary["status"] != "answer" for boundary in selected["answer_boundaries"] if boundary["requirement"]["dimension"] == "pricing")
    for boundary in selected["answer_boundaries"]:
        assert boundary["view_fact_ids"]  # Full producer credential remains persisted.


@pytest.mark.asyncio
async def test_first_draft_grounding_has_only_the_consumed_sources(monkeypatch):
    detail = distributed_detail(dimensions=("feature", "pricing"))
    # The legacy whole-report route remains available to demo runs. Real quick
    # multi-dimension generation is covered by test_dimension_writer instead.
    detail.execution_mode = "demo"
    detail.raw_sources = [s for s in detail.raw_sources if s.dimension == "feature" or s.competitor == "Notion"]
    service = RunService(SkillRegistry.from_default_path(), Settings(demo_mode=True), graph_checkpointer=GraphCheckpointer.in_memory())
    record = RunRecord(detail)
    service._runs[detail.id] = record
    seal_snapshot(detail, phase="analysis", canonical_documents={})
    grounded = []
    async def grounding(projected):
        grounded.extend(s.id for s in projected.raw_sources)
        return "Grounded Evidence Contract"
    async def model(*args, **kwargs):
        return "## 执行摘要\n本轮证据存在缺口。"
    monkeypatch.setattr(service, "_writer_grounding_prompt", grounding)
    monkeypatch.setattr(service, "_trace_llm_text", model)
    await service._writer_markdown_report_from_evidence_pack(record, SimpleNamespace(metrics=SimpleNamespace(segmented_writer_required=False)), 1)
    use = detail.evidence_consumptions[-1]
    assert set(grounded) == set(use.source_ids)
    assert set(grounded) < {source.id for source in detail.raw_sources}


def test_writer_reclaims_budget_when_incomplete_price_controls_drop_out():
    detail = distributed_detail(dimensions=("feature", "pricing"), observations=8)
    detail.raw_sources = [s for s in detail.raw_sources if s.dimension == "feature" or s.competitor == "Notion"]
    for source in detail.raw_sources:
        if source.dimension == "pricing":
            source.metadata["normalized_fields"] = source.metadata["normalized_fields"][:1]
            row = source.metadata["normalized_fields"][0]
            row.update(amount=10, currency="USD", billing_interval="unknown", tax_scope="unknown")
    service = RunService(SkillRegistry.from_default_path(), Settings(demo_mode=True), graph_checkpointer=GraphCheckpointer.in_memory())
    record = RunRecord(detail)
    seal_snapshot(detail, phase="analysis", canonical_documents={})
    selected, use = service._writer_segment_evidence(record, {"segment_name": "full_report", "allowed_source_ids": [s.id for s in detail.raw_sources]})
    assert {fact["competitor"] for fact in selected["evidence_view"]["facts"] if fact["dimension"] == "feature"} == set(detail.plan.competitors)
    assert use.estimated_bytes <= 8192
    import json
    payload = json.loads(service._writer_evidence_context_json(selected))
    boundary = next(b for b in payload["answer_boundaries"] if b["requirement"]["competitor"] == "Notion" and b["requirement"]["dimension"] == "pricing")
    assert boundary["evidence_status"] == "collected_but_omitted"
