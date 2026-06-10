from datetime import datetime

from packages.agents.writer.logic import WriterAgentMixin
from packages.config import Settings
from packages.enterprise.projection import _build_report_version
from packages.i18n.language import (
    REPORT_LABELS,
    language_instruction,
    normalize_output_language,
)
from packages.orchestrator.service import RunService, _active_run_fingerprint
from packages.schema.api_dto import RunCreateRequest, RunDetail
from packages.schema.enterprise import EvidenceRecord
from packages.schema.models import AnalysisPlan, ComparisonCell, ComparisonMatrix, RawSource
from packages.skills.registry import SkillRegistry


class _WriterHarness(WriterAgentMixin):
    def _source_matches_competitor(self, source: RawSource, competitor: str) -> bool:
        return source.competitor == competitor


def _settings() -> Settings:
    return Settings(
        demo_mode=True,
        ark_api_key=None,
        ark_model=None,
        ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
        llm_timeout_seconds=10,
        llm_temperature=0.2,
    )


def test_run_create_request_defaults_to_chinese_output_language() -> None:
    request = RunCreateRequest(
        topic="AI 编程助手竞品分析",
        dimensions=["pricing"],
    )

    assert request.output_language == "zh-CN"


def test_run_detail_persists_output_language() -> None:
    detail = RunDetail(
        id="run-language",
        topic="AI 编程助手竞品分析",
        status="queued",
        execution_mode="demo",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        plan=AnalysisPlan(
            topic="AI 编程助手竞品分析",
            competitors=["Cursor"],
            dimensions=["pricing"],
        ),
        output_language="en-US",
    )

    restored = RunDetail.model_validate_json(detail.model_dump_json())

    assert restored.output_language == "en-US"


def test_language_helper_normalizes_unknown_values_to_chinese() -> None:
    assert normalize_output_language("en-US") == "en-US"
    assert normalize_output_language("zh-CN") == "zh-CN"
    assert normalize_output_language("fr-FR") == "zh-CN"
    assert normalize_output_language(None) == "zh-CN"


def test_language_instruction_preserves_citation_syntax() -> None:
    zh_instruction = language_instruction("zh-CN")
    en_instruction = language_instruction("en-US")

    assert "Simplified Chinese" in zh_instruction
    assert "[source:ID]" in zh_instruction
    assert "Use English" in en_instruction
    assert "citation syntax" in en_instruction


def test_report_labels_are_localized() -> None:
    assert REPORT_LABELS["zh-CN"]["executive_summary"] == "执行摘要"
    assert REPORT_LABELS["en-US"]["executive_summary"] == "Executive Summary"


def test_report_labels_include_analysis_first_sections() -> None:
    expected_en = {
        "executive_takeaway": "Executive Takeaway",
        "decision_summary": "Decision Summary",
        "competitive_findings": "Competitive Findings",
        "competitor_deep_dives": "Competitor Deep Dives",
        "evidence_support": "Evidence & QA Support",
    }

    for key, label in expected_en.items():
        assert REPORT_LABELS["en-US"][key] == label
        assert REPORT_LABELS["zh-CN"][key]


def test_active_run_fingerprint_includes_output_language() -> None:
    common = dict(
        workspace_id="workspace",
        project_id="project",
        topic="AI coding assistants",
        competitors=["Cursor"],
        dimensions=["pricing"],
        competitor_layer="L1",
        scenario_id=None,
        execution_mode="demo",
        auto_redo_warn_enabled=False,
        hitl_enabled=False,
    )

    zh = _active_run_fingerprint(output_language="zh-CN", **common)
    en = _active_run_fingerprint(output_language="en-US", **common)

    assert zh != en


def _language_run_detail(output_language: str) -> RunDetail:
    now = datetime.utcnow()
    return RunDetail(
        id=f"run-{output_language}",
        topic="AI 编程助手竞品分析",
        status="completed",
        execution_mode="demo",
        output_language=output_language,  # type: ignore[arg-type]
        created_at=now,
        updated_at=now,
        plan=AnalysisPlan(
            topic="AI 编程助手竞品分析",
            competitors=["Cursor", "Copilot"],
            dimensions=["pricing"],
            competitor_layer="L1",
        ),
        raw_sources=[
            RawSource(
                id="src-1",
                competitor="Cursor",
                dimension="pricing",
                source_type="official_docs",
                title="Cursor pricing",
                snippet="Cursor pricing page",
                content_hash="hash-1",
                confidence=0.92,
            )
        ],
        comparison_matrix=ComparisonMatrix(
            competitors=["Cursor", "Copilot"],
            dimensions=["pricing"],
            cells=[
                ComparisonCell(
                    competitor="Cursor",
                    dimension="pricing",
                    value="Strong packaging evidence.",
                    source_ids=["src-1"],
                    confidence=0.9,
                )
            ],
            winner_by_dimension={"pricing": "Cursor"},
            summary=["Cursor has stronger pricing evidence."],
        ),
    )


def test_demo_report_uses_chinese_headings_by_default() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=_settings(),
    )

    report = service._demo_report(_language_run_detail("zh-CN"))

    assert "## 执行摘要" in report
    assert "## 来源质量与覆盖" in report
    assert "[source:src-1]" in report
    assert "## Executive Summary" not in report


def test_demo_report_can_use_english_headings() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=_settings(),
    )

    report = service._demo_report(_language_run_detail("en-US"))

    assert "## Executive Summary" in report
    assert "## Source Quality & Coverage" in report


def test_fallback_report_uses_chinese_headings() -> None:
    report = _WriterHarness()._fallback_report_markdown(
        _language_run_detail("zh-CN"),
        "writer timeout",
    )

    assert "# AI 编程助手竞品分析 直接战报" in report
    assert f"## {REPORT_LABELS['zh-CN']['executive_takeaway']}" in report
    assert "## 维度结论" in report
    assert "[source:src-1]" in report


def test_report_projection_carries_output_language_metadata() -> None:
    detail = _language_run_detail("zh-CN")
    detail.report_md = "## 执行摘要\n结论 [source:src-1]"
    evidence = EvidenceRecord(
        id="evidence-1",
        workspace_id="workspace",
        project_id="project",
        run_id=detail.id,
        raw_source_id="src-1",
        competitor_id="competitor-cursor",
        dimension="pricing",
        source_type="official_docs",
        title="Cursor pricing",
        snippet="Cursor pricing page",
        content_hash="hash-1",
        reliability_score=0.92,
    )

    version = _build_report_version(
        detail,
        workspace_id="workspace",
        project_id="project",
        version_number=1,
        competitor_layer="L1",
        claim_records=[],
        evidence_records=[evidence],
        competitor_id_map={"Cursor": "competitor-cursor", "Copilot": "competitor-copilot"},
    )

    assert version.quality_metadata["output_language"] == "zh-CN"
