from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from packages.agents.writer.assembler import StructuredReportAssembler
from packages.agents.writer.logic import (
    CitedTextListSection,
    STRUCTURED_SECTION_INPUT_TARGET_CHARS,
    WriterAgentMixin,
    build_structured_writer_section_plan,
    _structured_section_inputs,
)
from packages.agents.writer.structured_report import (
    BattlecardSection,
    ExecutiveSummarySection,
    ReportSupport,
)
from packages.agents.writer.structured_sections import StructuredSectionGenerationError
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
        self.emitted_events: list[tuple[str, str, str | None, str | None, str, dict[str, object] | None]] = []

    async def _trace_llm_text(self, record, *, agent, subagent, name, system, user) -> str:
        self.prompts.append(system + "\n" + user)
        return self.responses.pop(0)

    async def emit(
        self,
        run_id: str,
        event_type: str,
        node: str | None,
        subagent: str | None,
        message: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        self.emitted_events.append(
            (run_id, event_type, node, subagent, message, payload)
        )


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


def _section_fixture_for_schema(section_schema, segment):
    fixture = _report("zh-CN")
    if section_schema.__name__ == "CitedTextListSection":
        return section_schema(items=[fixture.core.decision_summary[0]])
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
    if section_schema.__name__ == "CompetitorDeepDiveSection":
        return fixture.core.competitor_deep_dives[0].model_copy(
            update={"competitor": str(segment.get("competitor") or "Cursor")}
        )
    raise AssertionError(f"unexpected section schema {section_schema.__name__}")


class _SegmentedEvidencePackResult:
    metrics = SimpleNamespace(segment_count=5, segmented_writer_required=True)

    def to_prompt_json(self) -> str:
        return "FULL_PACK_SHOULD_NOT_BE_REPEATED"

    def segment_inputs(self) -> list[dict[str, object]]:
        return [
            {
                "segment_name": "decision_summary",
                "content": "budgeted decision evidence",
                "allowed_source_ids": ["raw-source-a"],
            },
            {
                "segment_name": "user_research",
                "content": "budgeted user evidence",
                "allowed_source_ids": ["raw-source-survey"],
            },
            {
                "segment_name": "competitor_deep_dives",
                "segment_competitor": "Cursor",
                "content": "budgeted Cursor evidence",
                "allowed_source_ids": ["raw-source-a"],
            },
            {
                "segment_name": "competitor_deep_dives",
                "segment_competitor": "Windsurf",
                "content": "budgeted Windsurf evidence",
                "allowed_source_ids": ["raw-source-b"],
            },
            {
                "segment_name": "swot_matrix",
                "content": "budgeted SWOT evidence",
                "source_registry": [{"id": "raw-source-a"}],
            },
            {
                "segment_name": "support_appendix",
                "content": "budgeted support evidence",
                "source_registry": [{"source_id": "raw-source-b"}],
            },
        ]


class _MultiShardEvidencePackResult:
    metrics = SimpleNamespace(segment_count=2, segmented_writer_required=True)

    def to_prompt_json(self) -> str:
        return "FULL_PACK_SHOULD_NOT_BE_REPEATED"

    def segment_inputs(self) -> list[dict[str, object]]:
        return [
            {
                "segment_name": "decision_summary",
                "segment_batch": 1,
                "content": "PRIMARY_DECISION_FULL_CONTENT",
                "allowed_source_ids": ["raw-source-a"],
            },
            {
                "segment_name": "decision_summary",
                "segment_batch": 2,
                "content": "SECONDARY_DECISION_FULL_CONTENT",
                "allowed_source_ids": ["raw-source-b"],
            },
        ]


class _NoExecutiveEvidencePackResult:
    metrics = SimpleNamespace(segment_count=1, segmented_writer_required=True)

    def to_prompt_json(self) -> str:
        return "FULL_PACK_SHOULD_NOT_BE_REPEATED"

    def segment_inputs(self) -> list[dict[str, object]]:
        return [
            {
                "segment_name": "support_appendix",
                "segment_batch": 1,
                "content": "SUPPORT_ONLY_FULL_CONTENT",
                "allowed_source_ids": ["raw-source-a"],
            }
        ]


class _LargeDecisionSegmentEvidencePackResult:
    metrics = SimpleNamespace(segment_count=1, segmented_writer_required=True)

    def to_prompt_json(self) -> str:
        return "FULL_PACK_SHOULD_NOT_BE_REPEATED"

    def segment_inputs(self) -> list[dict[str, object]]:
        source_registry = [
            {
                "id": f"raw-source-{index:02d}",
                "competitor": "Cursor" if index % 2 else "Windsurf",
                "dimension": "pricing" if index % 3 else "persona",
                "source_type": "webpage_verified",
                "title": f"Large source {index}",
                "url": f"https://example.com/research/{index}/" + ("path/" * 20),
                "confidence": 0.9,
                "authority_role": "vendor_official" if index % 2 else "community",
                "short_source_note": "source note " * 80,
                "quality_score": 0.91,
                "represented_by_count": 4,
                "representation_types": ["fact", "signal", "quote"],
            }
            for index in range(1, 41)
        ]
        groups = [
            {
                "competitor": competitor,
                "dimension": dimension,
                "source_ids": [item["id"] for item in source_registry],
                "official_source_ids": [source_registry[0]["id"]],
                "community_source_ids": [source_registry[1]["id"]],
                "user_research_source_ids": [source_registry[2]["id"]],
                "confidence_summary": {"avg": 0.87, "min": 0.75, "max": 0.97},
                "coverage_notes": ["coverage note " * 60 for _ in range(5)],
                "facts": [
                    {
                        "kind": "pricing_fact",
                        "competitor": competitor,
                        "dimension": dimension,
                        "values": {"summary": "fact detail " * 120},
                        "source_ids": [source_registry[fact_index]["id"]],
                        "quote_ids": [f"quote-{fact_index}"],
                        "confidence": 0.88,
                    }
                    for fact_index in range(8)
                ],
                "unstructured_signals": [
                    {
                        "source_id": source_registry[signal_index]["id"],
                        "competitor": competitor,
                        "dimension": dimension,
                        "source_type": "webpage_verified",
                        "signal_summary": "signal detail " * 120,
                        "salient_terms": ["pricing", "persona", "workflow"],
                        "confidence": 0.86,
                        "quote_ids": [f"quote-{signal_index}"],
                    }
                    for signal_index in range(6)
                ],
                "kb_signals": [
                    {
                        "competitor": competitor,
                        "dimension": dimension,
                        "text": "knowledge detail " * 120,
                        "source_ids": [source_registry[kb_index]["id"]],
                        "merged_into_present": True,
                    }
                    for kb_index in range(6)
                ],
                "conflicts": [
                    {
                        "claim_area": "pricing",
                        "positions": {"official": "official claim " * 40},
                        "source_ids_by_position": {"official": [source_registry[0]["id"]]},
                        "confidence_by_position": {"official": 0.9},
                        "resolution_status": "resolved",
                    }
                ],
            }
            for competitor in ("Cursor", "Windsurf", "Claude Code", "GitHub Copilot")
            for dimension in ("pricing", "feature", "persona")
        ]
        return [
            {
                "schema_version": "writer_evidence_pack.v1",
                "segment_name": "decision_summary",
                "section_id": "decision_summary",
                "output_language": "zh-CN",
                "source_registry": source_registry,
                "groups": groups,
                "quotes": [
                    {
                        "id": f"quote-{index}",
                        "excerpt": "quote detail " * 120,
                        "full_text_source_ids": [source_registry[index % 40]["id"]],
                    }
                    for index in range(40)
                ],
                "matrix": {
                    "winner_by_dimension": {"pricing": "Cursor"},
                    "summary": ["matrix summary " * 80 for _ in range(6)],
                    "cells": [
                        {
                            "competitor": competitor,
                            "dimension": dimension,
                            "value": "matrix cell detail " * 120,
                            "source_ids": [source_registry[0]["id"]],
                            "confidence": 0.86,
                        }
                        for competitor in (
                            "Cursor",
                            "Windsurf",
                            "Claude Code",
                            "GitHub Copilot",
                        )
                        for dimension in ("pricing", "feature", "persona")
                    ],
                },
                "allowed_source_ids": [item["id"] for item in source_registry],
                "segment_input_chars": 230_000,
            }
        ]


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
    calls: list[tuple[str, str, object]] = []

    async def fake_section_json(
        record, *, segment, section_schema, allowed_source_ids, timeout_seconds
    ):
        calls.append(
            (
                str(segment["section_id"]),
                section_schema.__name__,
                segment.get("competitor"),
            )
        )
        if section_schema.__name__ == "CitedTextListSection":
            return section_schema(
                items=[
                    fixture.core.executive_summary.recommendation.model_copy(
                        update={"text": f"Generated {segment['section_id']}"}
                    )
                ]
            )
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
    expected_calls = []
    for item in build_structured_writer_section_plan(
        competitors=["Cursor", "Windsurf"],
        dimensions=["pricing", "feature", "persona"],
    ):
        section_id = str(item["section_id"])
        schema_name = (
            "CitedTextListSection"
            if item["schema"] == "list[CitedText]"
            else str(item["schema"])
        )
        expected_calls.append((section_id, schema_name, item.get("competitor")))
    assert calls == expected_calls
    assert (
        "decision_summary",
        "CitedTextListSection",
        None,
    ) in calls
    assert (
        "competitive_findings",
        "CitedTextListSection",
        None,
    ) in calls
    assert (
        "community_triangulation",
        "CitedTextListSection",
        None,
    ) in calls
    assert report.core.community_triangulation[0].text == (
        "Generated community_triangulation"
    )


def test_structured_section_inputs_use_budgeted_segments_when_segmented() -> None:
    inputs = _structured_section_inputs(
        evidence_pack_result=_SegmentedEvidencePackResult(),
        competitors=["Cursor", "Windsurf"],
        dimensions=["pricing", "feature", "persona"],
    )

    serialized_inputs = json.dumps(inputs, ensure_ascii=False)

    assert "FULL_PACK_SHOULD_NOT_BE_REPEATED" not in serialized_inputs
    assert "budgeted decision evidence" in json.dumps(
        inputs["executive_summary"], ensure_ascii=False
    )
    assert "budgeted user evidence" in json.dumps(
        inputs["user_review_themes"], ensure_ascii=False
    )
    assert "budgeted Cursor evidence" in json.dumps(
        inputs["competitor_deep_dive::Cursor"], ensure_ascii=False
    )
    assert "budgeted Windsurf evidence" not in json.dumps(
        inputs["competitor_deep_dive::Cursor"], ensure_ascii=False
    )
    assert "budgeted support evidence" in json.dumps(
        inputs["support"], ensure_ascii=False
    )
    assert inputs["executive_summary"]["allowed_source_ids"] == ["raw-source-a"]
    assert inputs["user_review_themes"]["allowed_source_ids"] == ["raw-source-survey"]
    assert inputs["support"]["allowed_source_ids"] == ["raw-source-b"]


def test_structured_section_inputs_fall_back_to_prompt_json_without_segments() -> None:
    inputs = _structured_section_inputs(
        evidence_pack_result=_minimal_evidence_pack_result(),
        competitors=["Cursor", "Windsurf"],
        dimensions=["pricing", "feature", "persona"],
    )

    assert "compact evidence" in json.dumps(
        inputs["executive_summary"], ensure_ascii=False
    )


def test_structured_section_inputs_keep_one_primary_segment_and_compact_omitted_refs() -> None:
    inputs = _structured_section_inputs(
        evidence_pack_result=_MultiShardEvidencePackResult(),
        competitors=["Cursor", "Windsurf"],
        dimensions=["pricing", "feature", "persona"],
    )

    decision_summary = inputs["decision_summary"]
    serialized = json.dumps(decision_summary, ensure_ascii=False)

    assert "FULL_PACK_SHOULD_NOT_BE_REPEATED" not in serialized
    assert len(decision_summary["evidence_segments"]) == 1
    assert "PRIMARY_DECISION_FULL_CONTENT" in serialized
    assert "SECONDARY_DECISION_FULL_CONTENT" not in serialized
    assert decision_summary["allowed_source_ids"] == ["raw-source-a"]
    assert decision_summary["additional_segment_count"] == 1
    assert decision_summary["additional_segment_refs"] == [
        {
            "segment_name": "decision_summary",
            "segment_competitor": None,
            "segment_batch": 2,
            "allowed_source_ids": ["raw-source-b"],
            "source_count": 1,
        }
    ]


def test_structured_section_inputs_keep_empty_scope_when_no_matching_segments() -> None:
    inputs = _structured_section_inputs(
        evidence_pack_result=_NoExecutiveEvidencePackResult(),
        competitors=["Cursor", "Windsurf"],
        dimensions=["pricing", "feature", "persona"],
    )

    executive_summary = inputs["executive_summary"]
    serialized = json.dumps(executive_summary, ensure_ascii=False)

    assert "FULL_PACK_SHOULD_NOT_BE_REPEATED" not in serialized
    assert "SUPPORT_ONLY_FULL_CONTENT" not in serialized
    assert executive_summary["evidence_segments"] == []
    assert executive_summary["allowed_source_ids"] == []
    assert executive_summary["additional_segment_refs"] == []


def test_structured_section_inputs_compact_large_primary_segments_without_losing_scope() -> None:
    inputs = _structured_section_inputs(
        evidence_pack_result=_LargeDecisionSegmentEvidencePackResult(),
        competitors=["Cursor", "Windsurf", "Claude Code", "GitHub Copilot"],
        dimensions=["pricing", "feature", "persona"],
    )

    executive_summary = inputs["executive_summary"]
    serialized = json.dumps(executive_summary, ensure_ascii=False)

    assert len(serialized) <= STRUCTURED_SECTION_INPUT_TARGET_CHARS
    assert "FULL_PACK_SHOULD_NOT_BE_REPEATED" not in serialized
    assert "fact detail " * 20 not in serialized
    assert len(executive_summary["allowed_source_ids"]) == 40
    segment = executive_summary["evidence_segments"][0]
    assert segment["section_projection"] == "compact"
    assert len(segment["source_registry"]) == 40
    assert len(segment["groups"]) == 12
    assert {item["id"] for item in segment["source_registry"]} == set(
        executive_summary["allowed_source_ids"]
    )


@pytest.mark.asyncio
async def test_writer_structured_report_rejects_citations_outside_section_evidence_scope(
    monkeypatch,
) -> None:
    record = _writer_record_with_sources(["raw-source-a", "raw-source-b"])
    harness = _WriterHarness([])

    async def fake_section_json(
        record, *, segment, section_schema, allowed_source_ids, timeout_seconds
    ):
        if segment["section_id"] == "executive_summary":
            payload = {
                "recommendation": {
                    "text": "Badly scoped recommendation.",
                    "source_ids": ["raw-source-b"],
                    "confidence": "high",
                    "evidence_role": "official_fact",
                },
                "risk_adjusted_rationale": {
                    "text": "Scoped rationale.",
                    "source_ids": ["raw-source-a"],
                    "confidence": "high",
                    "evidence_role": "official_fact",
                },
                "competitor_postures": [
                    {
                        "competitor": "Cursor",
                        "posture": {
                            "text": "Scoped posture.",
                            "source_ids": ["raw-source-a"],
                            "confidence": "high",
                            "evidence_role": "official_fact",
                        },
                    }
                ],
                "confidence_boundary": {
                    "text": "Scoped boundary.",
                    "source_ids": ["raw-source-a"],
                    "confidence": "high",
                    "evidence_role": "official_fact",
                },
                "next_actions": [
                    {
                        "text": "Scoped action.",
                        "source_ids": ["raw-source-a"],
                        "confidence": "high",
                        "evidence_role": "official_fact",
                    }
                ],
            }
            return section_schema.model_validate(payload)
        raise AssertionError("generation should stop at the scoped citation failure")

    async def validating_section_json(
        record, *, segment, section_schema, allowed_source_ids, timeout_seconds
    ):
        section = await fake_section_json(
            record,
            segment=segment,
            section_schema=section_schema,
            allowed_source_ids=allowed_source_ids,
            timeout_seconds=timeout_seconds,
        )
        cited_source_ids: set[str] = set()

        def collect_source_ids(value) -> None:
            if isinstance(value, dict):
                raw_source_ids = value.get("source_ids")
                if isinstance(raw_source_ids, list):
                    cited_source_ids.update(
                        source_id
                        for source_id in raw_source_ids
                        if isinstance(source_id, str)
                    )
                for child in value.values():
                    collect_source_ids(child)
                return
            if isinstance(value, list):
                for child in value:
                    collect_source_ids(child)

        collect_source_ids(section.model_dump())
        invalid_source_ids = cited_source_ids - set(allowed_source_ids)
        if invalid_source_ids:
            raise ValueError(
                "structured writer response used disallowed source_ids: "
                f"{', '.join(sorted(invalid_source_ids))}"
            )
        return section

    monkeypatch.setattr(harness, "_writer_structured_section_json", validating_section_json)

    with pytest.raises(ValueError, match="raw-source-b"):
        await harness._writer_structured_report(
            record,
            evidence_pack_result=_SegmentedEvidencePackResult(),
            timeout_seconds=10,
        )


@pytest.mark.asyncio
async def test_writer_structured_report_rejects_citations_when_section_scope_is_empty(
    monkeypatch,
) -> None:
    record = _writer_record_with_sources(["raw-source-a"])
    harness = _WriterHarness([])

    async def validating_section_json(
        record, *, segment, section_schema, allowed_source_ids, timeout_seconds
    ):
        assert segment["section_id"] == "executive_summary"
        assert allowed_source_ids == set()
        payload = {
            "recommendation": {
                "text": "Citation should be rejected.",
                "source_ids": ["raw-source-a"],
                "confidence": "high",
                "evidence_role": "official_fact",
            },
            "risk_adjusted_rationale": {
                "text": "No scoped evidence is available.",
                "source_ids": [],
                "confidence": "low",
                "evidence_role": "evidence_gap",
            },
            "competitor_postures": [
                {
                    "competitor": "Cursor",
                    "posture": {
                        "text": "No scoped evidence is available.",
                        "source_ids": [],
                        "confidence": "low",
                        "evidence_role": "evidence_gap",
                    },
                }
            ],
            "confidence_boundary": {
                "text": "No scoped evidence is available.",
                "source_ids": [],
                "confidence": "low",
                "evidence_role": "evidence_gap",
            },
            "next_actions": [
                {
                    "text": "Collect scoped executive-summary evidence.",
                    "source_ids": [],
                    "confidence": "low",
                    "evidence_role": "evidence_gap",
                }
            ],
        }
        section = section_schema.model_validate(payload)
        cited_source_ids = {
            source_id
            for value in section.model_dump().values()
            if isinstance(value, dict)
            for source_id in value.get("source_ids", [])
            if isinstance(source_id, str)
        }
        invalid_source_ids = cited_source_ids - set(allowed_source_ids)
        if invalid_source_ids:
            raise ValueError(
                "structured writer response used disallowed source_ids: "
                f"{', '.join(sorted(invalid_source_ids))}"
            )
        return section

    monkeypatch.setattr(harness, "_writer_structured_section_json", validating_section_json)

    with pytest.raises(ValueError, match="raw-source-a"):
        await harness._writer_structured_report(
            record,
            evidence_pack_result=_NoExecutiveEvidencePackResult(),
            timeout_seconds=10,
        )


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
    assert 'evidence_role="evidence_gap", confidence="low"' in prompt
    assert "[source:" not in prompt


def test_structured_section_prompt_requires_requested_output_language() -> None:
    prompt = _WriterHarness([])._structured_section_prompt(
        segment={
            "section_id": "executive_summary",
            "content": "Evidence",
            "output_language": "zh-CN",
        },
        section_schema=ExecutiveSummarySection,
        allowed_source_ids={"raw-source-a"},
    )

    assert "Write every narrative text field in Simplified Chinese" in prompt
    assert "product names, source IDs, URLs, and technical terms" in prompt


def test_battlecard_prompt_requires_cited_derivative_talk_tracks() -> None:
    prompt = _WriterHarness([])._structured_section_prompt(
        segment={
            "section_id": "battlecard",
            "content": "Decision matrix and SWOT evidence",
            "output_language": "zh-CN",
        },
        section_schema=BattlecardSection,
        allowed_source_ids={"raw-source-a", "raw-source-b"},
    )

    assert "BattlecardSection is a cited derivative section" in prompt
    assert "use_when, attack_points, defense_points" in prompt
    assert "rebuttal_talk_tracks" in prompt
    assert "Do not output inference with empty source_ids" in prompt
    assert "proof_needed_before_external_use or evidence_limits" in prompt


def test_cited_text_list_prompt_rejects_schema_echo_shape() -> None:
    prompt = _WriterHarness([])._structured_section_prompt(
        segment={
            "section_id": "decision_summary",
            "content": "Decision evidence",
            "output_language": "zh-CN",
        },
        section_schema=CitedTextListSection,
        allowed_source_ids={"raw-source-a", "raw-source-b"},
        previous_validation_error="$defs extra inputs are not permitted",
    )

    assert 'exactly {"items": [' in prompt
    assert "Schema JSON describes the shape; it is not the output" in prompt
    assert "Never return $defs, properties, required, title, type, or additionalProperties" in prompt


@pytest.mark.asyncio
async def test_structured_writer_emits_section_progress_events(monkeypatch) -> None:
    harness = _WriterHarness([])
    record = _writer_record_with_sources(["raw-source-a", "raw-source-b"])
    fixture = _report("zh-CN")

    async def section_json(record, *, segment, section_schema, allowed_source_ids, timeout_seconds):
        section_id = segment["section_id"]
        if section_id == "executive_summary":
            return fixture.core.executive_summary
        if section_id == "decision_summary":
            return SimpleNamespace(items=fixture.core.decision_summary)
        if section_id == "competitive_findings":
            return SimpleNamespace(items=fixture.core.competitive_findings)
        if section_id == "user_review_themes":
            return fixture.core.user_review_themes
        if section_id == "competitor_deep_dive":
            competitor = str(segment["competitor"])
            return fixture.core.competitor_deep_dives[0].model_copy(
                update={"competitor": competitor}
            )
        if section_id == "decision_matrix":
            return fixture.core.decision_matrix
        if section_id == "swot":
            return fixture.core.swot
        if section_id == "battlecard":
            return fixture.core.battlecard
        if section_id == "community_triangulation":
            return SimpleNamespace(items=fixture.core.community_triangulation)
        if section_id == "support":
            return fixture.support
        raise AssertionError(f"unexpected section_id {section_id}")

    monkeypatch.setattr(harness, "_writer_structured_section_json", section_json)

    await harness._writer_structured_report(
        record,
        evidence_pack_result=_minimal_evidence_pack_result(),
        timeout_seconds=10,
    )

    started = [
        event
        for event in harness.emitted_events
        if event[1] == "writer_structured_section_started"
    ]
    completed = [
        event
        for event in harness.emitted_events
        if event[1] == "writer_structured_section_completed"
    ]
    expected_count = len(
        build_structured_writer_section_plan(
            competitors=record.detail.plan.competitors,
            dimensions=record.detail.plan.dimensions,
        )
    )
    assert len(started) == expected_count
    assert len(completed) == expected_count
    assert started[0][5]["section_key"] == "executive_summary"
    assert completed[-1][5]["section_key"] == "support"


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


@pytest.mark.asyncio
async def test_structured_section_json_raises_typed_failure_after_retry() -> None:
    harness = _WriterHarness(["not json", "still not json"])

    with pytest.raises(Exception) as exc_info:
        await harness._writer_structured_section_json(
            record=object(),
            segment={"section_id": "executive_summary", "content": "Evidence"},
            section_schema=ExecutiveSummarySection,
            allowed_source_ids={"raw-source-a"},
            timeout_seconds=5.0,
        )

    assert exc_info.value.__class__.__name__ == "StructuredSectionGenerationError"
    assert exc_info.value.section_key == "executive_summary"
    assert exc_info.value.section_id == "executive_summary"
    assert exc_info.value.schema_name == "ExecutiveSummarySection"
    assert "structured writer response must be a JSON object" in exc_info.value.message
    assert "executive_summary" in str(exc_info.value)
    assert len(harness.prompts) == 2


@pytest.mark.asyncio
async def test_structured_section_json_wraps_initial_timeout_as_typed_failure(
    monkeypatch,
) -> None:
    harness = _WriterHarness([])

    async def raise_timeout(*args, **kwargs):
        raise TimeoutError("section timed out")

    monkeypatch.setattr(harness, "_trace_llm_text", raise_timeout)

    with pytest.raises(StructuredSectionGenerationError) as exc_info:
        await harness._writer_structured_section_json(
            record=object(),
            segment={"section_id": "executive_summary", "content": "Evidence"},
            section_schema=ExecutiveSummarySection,
            allowed_source_ids={"raw-source-a"},
            timeout_seconds=5.0,
        )

    assert exc_info.value.error_kind == "timeout"
    assert exc_info.value.attempt == "initial"
    assert exc_info.value.section_key == "executive_summary"


@pytest.mark.asyncio
async def test_structured_section_json_wraps_retry_provider_exception_as_typed_failure(
    monkeypatch,
) -> None:
    harness = _WriterHarness([])
    calls = 0

    async def invalid_then_provider_error(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return "not json"
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(harness, "_trace_llm_text", invalid_then_provider_error)

    with pytest.raises(StructuredSectionGenerationError) as exc_info:
        await harness._writer_structured_section_json(
            record=object(),
            segment={"section_id": "executive_summary", "content": "Evidence"},
            section_schema=ExecutiveSummarySection,
            allowed_source_ids={"raw-source-a"},
            timeout_seconds=5.0,
        )

    assert calls == 2
    assert exc_info.value.error_kind == "llm_exception"
    assert exc_info.value.attempt == "retry"
    assert "provider unavailable" in exc_info.value.message


@pytest.mark.asyncio
async def test_structured_report_emits_section_failed_event(monkeypatch) -> None:
    harness = _WriterHarness([])
    record = _writer_record_with_sources(["raw-source-a", "raw-source-b"])

    async def failing_section_json(
        record, *, segment, section_schema, allowed_source_ids, timeout_seconds
    ):
        if str(segment["section_id"]) == "decision_matrix":
            from packages.agents.writer.structured_sections import (
                StructuredSectionGenerationError,
            )

            raise StructuredSectionGenerationError(
                section_key="decision_matrix",
                section_id="decision_matrix",
                schema_name="DecisionMatrixSection",
                message="source_ids are required unless evidence_role is evidence_gap",
            )
        return _section_fixture_for_schema(section_schema, segment)

    monkeypatch.setattr(harness, "_writer_structured_section_json", failing_section_json)

    with pytest.raises(Exception) as exc_info:
        await harness._writer_structured_report(
            record,
            evidence_pack_result=_minimal_evidence_pack_result(),
            timeout_seconds=10,
        )

    assert exc_info.value.__class__.__name__ == "StructuredReportGenerationError"
    failed = [
        event
        for event in harness.emitted_events
        if event[1] == "writer_structured_section_failed"
    ]
    assert len(failed) == 1
    payload = failed[0][5]
    assert payload is not None
    assert payload["section_key"] == "decision_matrix"
    assert payload["section_id"] == "decision_matrix"
    assert payload["schema_name"] == "DecisionMatrixSection"
    assert payload["section_schema"] == "DecisionMatrixSection"
    assert payload["section_index"] == 7
    assert payload["section_total"] == 11
    assert payload["error"] == (
        "source_ids are required unless evidence_role is evidence_gap"
    )


@pytest.mark.asyncio
async def test_structured_report_emits_section_failed_event_for_timeout(
    monkeypatch,
) -> None:
    harness = _WriterHarness([])
    record = _writer_record_with_sources(["raw-source-a", "raw-source-b"])

    async def raise_timeout(*args, **kwargs):
        raise TimeoutError("section timed out")

    monkeypatch.setattr(harness, "_trace_llm_text", raise_timeout)

    with pytest.raises(Exception) as exc_info:
        await harness._writer_structured_report(
            record,
            evidence_pack_result=_minimal_evidence_pack_result(),
            timeout_seconds=10,
        )

    assert exc_info.value.__class__.__name__ == "StructuredReportGenerationError"
    failed = [
        event
        for event in harness.emitted_events
        if event[1] == "writer_structured_section_failed"
    ]
    assert len(failed) == 1
    payload = failed[0][5]
    assert payload is not None
    assert payload["section_key"] == "executive_summary"
    assert payload["schema_name"] == "ExecutiveSummarySection"
    assert payload["error_kind"] == "timeout"
    assert payload["attempt"] == "initial"


@pytest.mark.asyncio
async def test_structured_section_json_rejects_disallowed_support_appendix_source_id() -> None:
    payload = {
        "source_quality": [],
        "user_research_evidence": [],
        "rag_gap_fill": [],
        "scenario_qa": [],
        "claim_risk": [],
        "next_collection": [],
        "evidence_appendix": [
            {
                "source_id": "raw-source-b",
                "title": "Out of scope source",
                "competitor": "Windsurf",
                "dimension": "pricing",
                "evidence_role": "official_fact",
                "confidence": "high",
            }
        ],
    }
    harness = _WriterHarness([json.dumps(payload), json.dumps(payload)])

    with pytest.raises(StructuredSectionGenerationError, match="raw-source-b"):
        await harness._writer_structured_section_json(
            record=object(),
            segment={"section_id": "support", "content": "Evidence"},
            section_schema=ReportSupport,
            allowed_source_ids={"raw-source-a"},
            timeout_seconds=5.0,
        )


@pytest.mark.asyncio
async def test_structured_section_json_normalizes_high_confidence_evidence_gaps() -> None:
    payload = {
        "source_quality": [
            {
                "text": "Official pricing evidence is available.",
                "source_ids": ["raw-source-a"],
                "confidence": "high",
                "evidence_role": "official_fact",
            },
            {
                "text": "Direct buyer interview evidence was not collected.",
                "source_ids": [],
                "confidence": "high",
                "evidence_role": "evidence_gap",
            },
        ],
        "user_research_evidence": [
            {
                "text": "No verified user interviews were collected.",
                "source_ids": [],
                "confidence": "high",
                "evidence_role": "inference",
                "evidence_gap": True,
            }
        ],
        "rag_gap_fill": [],
        "scenario_qa": [],
        "claim_risk": [],
        "next_collection": [],
        "evidence_appendix": [],
    }
    harness = _WriterHarness([json.dumps(payload), json.dumps(payload)])

    section = await harness._writer_structured_section_json(
        record=object(),
        segment={"section_id": "support", "content": "Evidence"},
        section_schema=ReportSupport,
        allowed_source_ids={"raw-source-a"},
        timeout_seconds=5.0,
    )

    assert section.source_quality[1].evidence_role == "evidence_gap"
    assert section.source_quality[1].confidence == "low"
    assert section.user_research_evidence[0].evidence_role == "evidence_gap"
    assert section.user_research_evidence[0].confidence == "low"
