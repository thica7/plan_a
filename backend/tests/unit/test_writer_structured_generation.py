from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from packages.agents.writer.assembler import StructuredReportAssembler
from packages.agents.writer.logic import (
    WriterAgentMixin,
    build_structured_writer_section_plan,
)
from packages.agents.writer.structured_report import ExecutiveSummarySection
from packages.orchestrator.service import RunRecord
from packages.schema.api_dto import RunDetail
from packages.schema.models import AnalysisPlan, RawSource
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


def _run_detail_for_structured_writer() -> RunDetail:
    return RunDetail(
        id="run-structured-writer-generation",
        topic="AI coding assistants",
        status="running",
        execution_mode="real",
        created_at="2026-06-19T00:00:00",
        updated_at="2026-06-19T00:00:00",
        output_language="zh-CN",
        plan=AnalysisPlan(
            topic="AI coding assistants",
            competitors=["Cursor", "Windsurf"],
            dimensions=["pricing", "feature", "persona"],
        ),
    )


def _raw_source(source_id: str) -> RawSource:
    return RawSource(
        id=source_id,
        competitor="Cursor" if source_id != "raw-source-b" else "Windsurf",
        dimension="pricing" if source_id != "raw-source-survey" else "persona",
        source_type=(
            "webpage_verified"
            if source_id != "raw-source-survey"
            else "simulated_interview"
        ),
        title=f"Source {source_id}",
        snippet=f"Evidence from {source_id}.",
        content_hash=f"{source_id}-hash",
        confidence=0.9,
    )


def _writer_record_with_sources(source_ids: list[str]) -> RunRecord:
    detail = _run_detail_for_structured_writer()
    detail.raw_sources = [_raw_source(source_id) for source_id in source_ids]
    return RunRecord(detail=detail)


class _MinimalEvidencePackResult:
    metrics = SimpleNamespace(segment_count=6)

    def to_prompt_json(self) -> str:
        return json.dumps(
            {
                "coverage": {"raw_source_count": 3},
                "claims": [{"text": "compact evidence", "source_ids": ["raw-source-a"]}],
            }
        )

    def segment_inputs(self) -> list[dict[str, object]]:
        return []


def _minimal_evidence_pack_result() -> _MinimalEvidencePackResult:
    return _MinimalEvidencePackResult()


def test_structured_section_plan_has_core_before_support_and_no_markdown_layout_ownership() -> None:
    plan = build_structured_writer_section_plan(
        competitors=["Cursor", "Windsurf"],
        dimensions=["pricing", "feature", "persona"],
    )

    assert [item["section_id"] for item in plan][:4] == [
        "executive_summary",
        "decision_summary",
        "competitive_findings",
        "user_review_themes",
    ]
    assert plan[-1]["section_id"] == "support"
    assert all(item["owns_markdown_layout"] is False for item in plan)


@pytest.mark.asyncio
async def test_writer_structured_report_builds_full_report_from_section_payloads(monkeypatch) -> None:
    from test_writer_structured_renderer import _report

    record = _writer_record_with_sources(
        ["raw-source-a", "raw-source-b", "raw-source-survey"]
    )
    fixture = _report("zh-CN")
    harness = _WriterHarness([])

    async def fake_section_json(
        record, *, segment, section_schema, allowed_source_ids, timeout_seconds
    ):
        mapping = {
            "ExecutiveSummarySection": fixture.core.executive_summary,
            "UserReviewThemesSection": fixture.core.user_review_themes,
            "DecisionMatrixSection": fixture.core.decision_matrix,
            "SwotSection": fixture.core.swot,
            "BattlecardSection": fixture.core.battlecard,
            "ReportSupport": fixture.support,
        }
        if section_schema.__name__ in mapping:
            return mapping[section_schema.__name__]
        return fixture.core.competitor_deep_dives[0]

    monkeypatch.setattr(harness, "_writer_structured_section_json", fake_section_json)

    report = await harness._writer_structured_report(
        record,
        evidence_pack_result=_minimal_evidence_pack_result(),
        timeout_seconds=10,
    )

    assert report.core.executive_summary.recommendation.text
    assert report.support.evidence_appendix[0].source_id == "raw-source-a"


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
