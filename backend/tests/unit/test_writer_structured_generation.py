from __future__ import annotations

import json

import pytest

from packages.agents.writer.assembler import StructuredReportAssembler
from packages.agents.writer.logic import WriterAgentMixin
from packages.agents.writer.structured_report import ExecutiveSummarySection
from test_writer_structured_renderer import _report


def test_structured_assembler_accepts_complete_report_and_emits_coverage_telemetry() -> None:
    report = _report("zh-CN")
    result = StructuredReportAssembler().assemble(
        report=report,
        expected_competitors=["Cursor", "Windsurf"],
    )

    assert result.report is report
    assert result.telemetry["missing_deep_dive_competitors"] == ["Windsurf"]
    assert result.telemetry["duplicate_deep_dive_competitors"] == []
    assert result.telemetry["missing_battlecard_competitors"] == ["Cursor"]


def test_structured_assembler_reports_duplicate_deep_dives() -> None:
    report = _report("zh-CN")
    first = report.core.competitor_deep_dives[0]
    report.core.competitor_deep_dives.append(first.model_copy())

    result = StructuredReportAssembler().assemble(
        report=report,
        expected_competitors=["Cursor", "Windsurf"],
    )

    assert result.telemetry["duplicate_deep_dive_competitors"] == ["Cursor"]


class _WriterHarness(WriterAgentMixin):
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.prompts: list[str] = []

    async def _trace_llm_text(self, record, *, agent, subagent, name, system, user) -> str:
        self.prompts.append(system + "\n" + user)
        return self.responses.pop(0)


def test_structured_section_prompt_includes_evidence_role_guidance() -> None:
    prompt = _WriterHarness([])._structured_section_prompt(
        segment={"section_id": "executive_summary", "content": "Evidence"},
        section_schema=ExecutiveSummarySection,
        allowed_source_ids={"raw-source-a"},
    )

    for role in (
        "official_fact",
        "community_signal",
        "simulated_research",
        "inference",
        "evidence_gap",
    ):
        assert role in prompt
    assert "official/product/vendor facts" in prompt
    assert "user/community/forum signals" in prompt
    assert "simulated interviews/surveys" in prompt
    assert "reasoned conclusions" in prompt
    assert "missing/unsupported evidence" in prompt
    assert "[source:" not in prompt


@pytest.mark.asyncio
async def test_structured_section_json_accepts_valid_json_and_rejects_markdown_citations() -> None:
    payload = {
        "recommendation": {
            "text": "优先以 Cursor 作为团队采购基线。",
            "source_ids": ["raw-source-a"],
            "confidence": "high",
            "evidence_role": "official_fact",
        },
        "risk_adjusted_rationale": {
            "text": "Windsurf 功能覆盖更宽，但 Cursor 在团队落地风险上更稳。",
            "source_ids": ["raw-source-a"],
            "confidence": "high",
            "evidence_role": "official_fact",
        },
        "competitor_postures": [
            {
                "competitor": "Cursor",
                "posture": {
                    "text": "主力候选。",
                    "source_ids": ["raw-source-a"],
                    "confidence": "high",
                    "evidence_role": "official_fact",
                },
            }
        ],
        "confidence_boundary": {
            "text": "结论适用于团队采购。",
            "source_ids": ["raw-source-a"],
            "confidence": "high",
            "evidence_role": "official_fact",
        },
        "next_actions": [
            {
                "text": "先做两周试点。",
                "source_ids": ["raw-source-a"],
                "confidence": "high",
                "evidence_role": "official_fact",
            }
        ],
    }
    harness = _WriterHarness([json.dumps(payload)])

    section = await harness._writer_structured_section_json(
        record=object(),
        segment={"section_id": "executive_summary", "content": "Evidence"},
        section_schema=ExecutiveSummarySection,
        allowed_source_ids={"raw-source-a"},
        timeout_seconds=5.0,
    )

    assert section.recommendation.text == "优先以 Cursor 作为团队采购基线。"
    assert "[source:" not in harness.prompts[0]


@pytest.mark.asyncio
async def test_structured_section_json_retries_invalid_json_once() -> None:
    valid_payload = {
        "recommendation": {
            "text": "Choose Cursor.",
            "source_ids": ["raw-source-a"],
            "confidence": "high",
            "evidence_role": "official_fact",
        },
        "risk_adjusted_rationale": {
            "text": "Cursor is lower risk for team rollout than Windsurf.",
            "source_ids": ["raw-source-a"],
            "confidence": "high",
            "evidence_role": "official_fact",
        },
        "competitor_postures": [
            {
                "competitor": "Cursor",
                "posture": {
                    "text": "Primary option.",
                    "source_ids": ["raw-source-a"],
                    "confidence": "high",
                    "evidence_role": "official_fact",
                },
            }
        ],
        "confidence_boundary": {
            "text": "Team procurement only.",
            "source_ids": ["raw-source-a"],
            "confidence": "high",
            "evidence_role": "official_fact",
        },
        "next_actions": [
            {
                "text": "Run a pilot.",
                "source_ids": ["raw-source-a"],
                "confidence": "high",
                "evidence_role": "official_fact",
            }
        ],
    }
    harness = _WriterHarness(["## Markdown response", json.dumps(valid_payload)])

    section = await harness._writer_structured_section_json(
        record=object(),
        segment={"section_id": "executive_summary", "content": "Evidence"},
        section_schema=ExecutiveSummarySection,
        allowed_source_ids={"raw-source-a"},
        timeout_seconds=5.0,
    )

    assert section.recommendation.text == "Choose Cursor."
    assert len(harness.prompts) == 2
    assert "Return JSON only" in harness.prompts[1]
