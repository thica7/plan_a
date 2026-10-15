from types import SimpleNamespace

import pytest
from test_answer_guard_workflow import fixture_detail
from test_stage_evidence_views import FixedTime

from packages.agents.writer.prompt_builder import WriterPrompt, WriterPromptBuilder
from packages.config import Settings
from packages.memory import KBCache, RunJournal
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunRecord, RunService
from packages.research.evidence.snapshot import seal_snapshot
from packages.skills.registry import SkillRegistry


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["first_draft", "segment", "repair"])
async def test_actual_writer_uses_builder(route, monkeypatch, tmp_path):
    monkeypatch.setattr("packages.research.evidence.views.datetime", FixedTime)
    service = RunService(
        settings=Settings(demo_mode=True),
        skill_registry=SkillRegistry.from_default_path(),
        journal=RunJournal(tmp_path / "journal.db"),
        kb_cache=KBCache.in_memory(),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    record = RunRecord(detail=fixture_detail())
    service._runs[record.detail.id] = record
    seal_snapshot(record.detail, phase="analysis", canonical_documents={})
    methods = {
        "first_draft": "first_draft_prompt",
        "segment": "segment_prompt",
        "repair": "section_repair_prompt",
    }
    monkeypatch.setattr(
        WriterPromptBuilder,
        methods[route],
        lambda *args, **kwargs: WriterPrompt("builder-system", "builder-user"),
    )
    captured = []

    async def capture(_record, **kwargs):
        captured.append(kwargs)
        return "## Decision Summary\nEvidence remains limited."

    async def grounding(_detail):
        return "Grounded Evidence Contract"

    monkeypatch.setattr(service, "_trace_llm_text", capture)
    monkeypatch.setattr(service, "_writer_grounding_prompt", grounding)
    if route == "first_draft":
        pack = SimpleNamespace(metrics=SimpleNamespace(segmented_writer_required=False))
        await service._writer_markdown_report_from_evidence_pack(record, pack, 1)
    elif route == "segment":
        await service._writer_segment_markdown(
            record,
            segment={
                "segment_name": "decision_summary",
                "section_id": "decision_summary",
                "allowed_source_ids": [s.id for s in record.detail.raw_sources],
            },
            timeout_seconds=1,
            language_guidance="",
            memory_context="",
            layer_context="",
            required_sections="",
            retry_count=0,
        )
    else:
        await service._writer_section_repair_markdown(
            record,
            sections=["decision_summary"],
            previous_report="## Decision Summary\nOld report.",
        )
    assert captured[-1]["system"] == "builder-system"
    assert captured[-1]["user"] == "builder-user"
