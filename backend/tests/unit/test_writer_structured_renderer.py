from __future__ import annotations

import pytest

from packages.agents.writer.structured_renderer import render_structured_report
from packages.agents.writer.structured_report import (
    BattlecardPlay,
    BattlecardSection,
    CitedText,
    CompetitorDeepDiveSection,
    CompetitorPosture,
    CompetitorSwot,
    CompetitorUserTheme,
    DecisionMatrixSection,
    ExecutiveSummarySection,
    MatrixCell,
    MatrixDimensionRow,
    ReportCore,
    ReportMetadata,
    ReportSupport,
    SourceAppendixRow,
    StructuredReport,
    SwotSection,
    UserReviewThemesSection,
)
from packages.business_intel.report_sections import build_report_section_index


def _claim(
    text: str,
    source_ids: list[str] | None = None,
    confidence: str = "high",
    evidence_role: str = "official_fact",
) -> CitedText:
    return CitedText(
        text=text,
        source_ids=source_ids or ["raw-source-a"],
        confidence=confidence,
        evidence_role=evidence_role,
    )


def _gap(text: str) -> CitedText:
    return CitedText(
        text=text,
        source_ids=[],
        confidence="low",
        evidence_role="evidence_gap",
    )


def _report(output_language: str = "zh-CN") -> StructuredReport:
    executive_summary = ExecutiveSummarySection(
        recommendation=_claim("优先以 Cursor 作为团队采购基线。"),
        risk_adjusted_rationale=_claim(
            "Windsurf 功能覆盖更宽，但可靠性风险使其更适合作为挑战者。",
            source_ids=["raw-source-b"],
            confidence="medium",
        ),
        competitor_postures=[
            CompetitorPosture(
                competitor="Cursor",
                posture=_claim("Cursor 适合作为成熟工作流的默认选择。"),
            ),
            CompetitorPosture(
                competitor="Windsurf",
                posture=_claim(
                    "Windsurf 适合在功能广度场景中作为挑战者验证。",
                    source_ids=["raw-source-b"],
                    confidence="medium",
                ),
            ),
        ],
        confidence_boundary=_claim(
            "本结论适用于团队采购，不覆盖个人尝鲜场景。",
            confidence="medium",
        ),
        next_actions=[
            _claim("采购前刷新 Cursor 与 Windsurf 的公开价格。", confidence="medium")
        ],
    )
    user_theme = CompetitorUserTheme(
        competitor="Cursor",
        direct_user_signals=[_claim("直接用户信号显示 Cursor 上手阻力较低。")],
        simulated_research_signals=[
            _claim(
                "模拟访谈显示团队更看重稳定的 IDE 工作流。",
                confidence="medium",
                evidence_role="simulated_research",
            )
        ],
        adoption_blockers=[_claim("采用障碍集中在预算审批与安全审查。")],
        switching_triggers=[_claim("当挑战者价格或协作能力显著领先时会触发切换。")],
        evidence_gaps=[_gap("缺少最新直接买家访谈来验证长期留存。")],
    )
    deep_dive = CompetitorDeepDiveSection(
        competitor="Cursor",
        positioning=[_claim("Cursor 定位为 AI 原生编码工作流。")],
        pricing_packaging=[_claim("Cursor 的公开价格更易进入采购核验。")],
        feature_capabilities=[_claim("Cursor 强调编辑器内代码理解与生成。")],
        persona_adoption=[_claim("主要采用画像是需要团队级落地的工程负责人。")],
        community_feedback=[_claim("社区反馈集中在效率提升与上下文体验。")],
        competitive_plays=[_claim("对 Windsurf 时应强调落地成熟度。")],
        evidence_gaps=[_gap("仍需补充企业安全审批证据。")],
    )
    decision_matrix = DecisionMatrixSection(
        dimensions=[
            MatrixDimensionRow(
                dimension="pricing",
                cells=[
                    MatrixCell(
                        competitor="Cursor",
                        summary="公开价格更易核验",
                        source_ids=["raw-source-a"],
                        confidence="high",
                    ),
                    MatrixCell(
                        competitor="Windsurf",
                        summary="采购前需要刷新价格",
                        source_ids=["raw-source-b"],
                        confidence="medium",
                    ),
                ],
            )
        ],
        interpretation=[_claim("价格维度上 Cursor 的证据更易复核。")],
        confidence_notes=[
            _claim(
                "Windsurf 的价格置信度低于 Cursor。",
                source_ids=["raw-source-b"],
                confidence="medium",
            )
        ],
    )
    swot = SwotSection(
        competitors=[
            CompetitorSwot(
                competitor="Cursor",
                strengths=[_claim("优势是工作流成熟且采购信息清晰。")],
                weaknesses=[_claim("弱点是需要持续证明团队版价值。")],
                opportunities=[_claim("机会是从个人开发者扩展到团队采购。")],
                threats=[_claim("威胁来自功能更激进的挑战者。")],
            )
        ]
    )
    battlecard = BattlecardSection(
        plays=[
            BattlecardPlay(
                competitor="Windsurf",
                target_buyer="工程负责人",
                use_when=_claim(
                    "当买方关注功能覆盖而非落地风险时使用。",
                    source_ids=["raw-source-b"],
                    confidence="medium",
                ),
                attack_points=[_claim("追问 Windsurf 在团队级稳定性上的证据。")],
                defense_points=[_claim("用 Cursor 的采购核验与工作流成熟度防守。")],
                likely_objections=[_claim("买方可能认为 Windsurf 功能更多。")],
                rebuttal_talk_tracks=[_claim("将功能广度与风险调整后的采用成功率拆开讨论。")],
                proof_needed_before_external_use=[_claim("外部使用前补齐最新价格和安全材料。")],
            )
        ],
        evidence_limits=[_gap("战报仍缺少最新竞品成交反馈。")],
    )
    core = ReportCore(
        executive_summary=executive_summary,
        decision_summary=[_claim("决策摘要建议以 Cursor 为采购基线。")],
        competitive_findings=[_claim("竞争发现显示成熟度与功能广度存在取舍。")],
        user_review_themes=UserReviewThemesSection(
            competitor_themes=[user_theme],
            cross_competitor_patterns=[_claim("用户评价共同关注上下文质量与稳定性。")],
            evidence_limits=[_gap("缺少多行业用户评论样本。")],
        ),
        competitor_deep_dives=[deep_dive],
        decision_matrix=decision_matrix,
        swot=swot,
        battlecard=battlecard,
        community_triangulation=[_claim("社区三角验证需要区分直接用户与模拟调研。")],
    )
    support = ReportSupport(
        source_quality=[_claim("来源质量以公开材料和社区信号为主。")],
        user_research_evidence=[_claim("用户研究证据包含直接信号与模拟调研。")],
        rag_gap_fill=[_gap("RAG 补缺需要继续采集企业采购案例。")],
        scenario_qa=[_claim("场景 QA 覆盖团队采购而非个人尝鲜。")],
        claim_risk=[_claim("声明风险主要来自价格时效性。")],
        next_collection=[_claim("后续采集应优先补齐 Windsurf 最新价格。")],
        evidence_appendix=[
            SourceAppendixRow(
                source_id="raw-source-a",
                title="Cursor pricing",
                competitor="Cursor",
                dimension="pricing",
                evidence_role="official_fact",
                confidence="high",
            )
        ],
    )
    return StructuredReport(
        output_language=output_language,
        topic="AI coding agent competitive analysis",
        competitors=["Cursor", "Windsurf"],
        dimensions=["pricing", "feature"],
        core=core,
        support=support,
        metadata=ReportMetadata(
            writer_mode="structured",
            segment_count=8,
            source_count=2,
            warnings=[],
            structured_report_version="1",
        ),
    )


def test_renderer_localizes_zh_structural_headings_and_keeps_support_after_core() -> None:
    rendered = render_structured_report(_report())

    assert "## 执行摘要" in rendered
    assert "## 战报" in rendered
    assert "### Pricing and Packaging" not in rendered
    assert rendered.index("## 战报") < rendered.index("## 支撑材料")
    assert "Segment Evidence Pack JSON" not in rendered


def test_renderer_emits_structured_section_markers_for_layer_indexing() -> None:
    rendered = render_structured_report(_report())

    assert "<!-- report-section:key=executive_summary layer=core -->" in rendered
    assert "<!-- report-section:key=evidence_support layer=support -->" in rendered

    index = build_report_section_index(rendered)
    support_section = next(
        section for section in index.sections if section.section_key == "evidence_support"
    )
    assert support_section.layer == "support"
    assert index.is_support_or_audit_line(support_section.line_start + 1) is True


def test_renderer_section_marker_lines_do_not_carry_citations() -> None:
    rendered = render_structured_report(_report("zh-CN"))
    marker_lines = [
        line for line in rendered.splitlines() if line.startswith("<!-- report-section:")
    ]

    assert marker_lines
    assert all("[source:" not in line for line in marker_lines)


def test_renderer_zh_structural_headings_are_localized() -> None:
    rendered = render_structured_report(_report("zh-CN"))

    assert "## 执行摘要" in rendered
    assert "Direct User / Community Signals" not in rendered
    assert "Direct User and Community Signals" not in rendered
    assert "Pricing and Packaging" not in rendered
    assert "#### 直接用户与社区信号" in rendered


def test_renderer_omits_empty_claim_group_headings() -> None:
    report = _report()
    theme = report.core.user_review_themes.competitor_themes[0]
    theme.direct_user_signals = []
    theme.adoption_blockers = []
    theme.switching_triggers = []

    rendered = render_structured_report(report)

    assert "#### 直接用户与社区信号\n\n####" not in rendered
    assert "#### 采用障碍\n\n####" not in rendered
    assert "#### 切换触发器\n\n####" not in rendered
    assert "#### 模拟调研信号" in rendered


def test_renderer_puts_citations_in_body_cells_not_table_headers() -> None:
    rendered = render_structured_report(_report())

    header_line = next(
        line for line in rendered.splitlines() if line.startswith("| 维度 |")
    )

    assert "[source:" not in header_line
    assert "| pricing | 公开价格更易核验 [source:raw-source-a] |" in rendered


def test_renderer_keeps_text_fields_free_of_raw_source_tokens_until_render_time() -> None:
    rendered = render_structured_report(_report())

    assert "优先以 Cursor 作为团队采购基线。 [source:raw-source-a]" in rendered
    assert "[source: raw-source-a]" not in rendered


def test_renderer_omits_metadata_and_keeps_zh_appendix_header_citation_free() -> None:
    rendered = render_structured_report(_report())

    appendix_header = next(
        line for line in rendered.splitlines() if line.startswith("| 来源 ID |")
    )

    assert "structured_report_version" not in rendered
    assert "writer_mode" not in rendered
    assert "source_count" not in rendered
    assert appendix_header == "| 来源 ID | 标题 | 竞品 | 维度 | 角色 | 置信度 |"
    assert "[source:" not in appendix_header


def test_renderer_keeps_english_appendix_header_for_non_zh_reports() -> None:
    rendered = render_structured_report(_report(output_language="en-US"))

    appendix_header = next(
        line for line in rendered.splitlines() if line.startswith("| Source ID |")
    )

    assert appendix_header == (
        "| Source ID | Title | Competitor | Dimension | Role | Confidence |"
    )
    assert "[source:" not in appendix_header


def test_renderer_collapses_inline_newlines_without_creating_markdown_injection() -> None:
    report = _report()
    report.topic = "AI coding\n## injected topic"
    report.competitors[0] = "Cursor\n## injected competitor"
    report.core.battlecard.plays[0].target_buyer = (
        "工程负责人\n## injected buyer"
    )
    report.core.executive_summary.recommendation.text = "第一行\n| fake row |"

    rendered = render_structured_report(report)
    lines = rendered.splitlines()
    matrix_header = next(line for line in lines if line.startswith("| 维度 |"))

    assert lines[0] == "# AI coding ## injected topic"
    assert "Cursor ## injected competitor" in matrix_header
    assert "工程负责人 ## injected buyer" in rendered
    assert "第一行 | fake row | [source:raw-source-a]" in rendered
    assert "## injected topic" not in lines[1:]
    assert "## injected competitor" not in lines
    assert "## injected buyer" not in lines
    assert "| fake row |" not in lines


def test_renderer_rejects_raw_source_tokens_in_structural_and_claim_text() -> None:
    report = _report()
    report.topic = "AI coding [source:raw-source-a]"

    with pytest.raises(ValueError, match="source tokens"):
        render_structured_report(report)

    report = _report()
    report.core.executive_summary.recommendation.text = (
        "优先采购 Cursor [source:raw-source-a]"
    )

    with pytest.raises(ValueError, match="source tokens"):
        render_structured_report(report)


def test_renderer_rejects_invalid_source_ids_before_rendering_citation_tokens() -> None:
    report = _report()
    report.core.executive_summary.recommendation.source_ids = ["bad id]"]

    with pytest.raises(ValueError, match="source id"):
        render_structured_report(report)


def test_renderer_escapes_matrix_cell_pipes_and_collapses_newlines() -> None:
    report = _report()
    report.core.decision_matrix.dimensions[0].cells[0].summary = (
        "公开|价格\r\n需要\n核验"
    )

    rendered = render_structured_report(report)
    matrix_row = next(
        line for line in rendered.splitlines() if line.startswith("| pricing |")
    )

    assert "公开\\|价格 需要 核验 [source:raw-source-a]" in matrix_row
    assert not any(line.startswith("| 需要") for line in rendered.splitlines())


def test_renderer_renders_missing_matrix_cell_as_localized_gap_without_citation() -> None:
    report = _report()
    report.core.decision_matrix.dimensions[0].cells = [
        report.core.decision_matrix.dimensions[0].cells[0]
    ]

    rendered = render_structured_report(report)
    matrix_row = next(
        line for line in rendered.splitlines() if line.startswith("| pricing |")
    )

    assert matrix_row.endswith("| 证据缺口 |")
    assert "证据缺口 [source:" not in matrix_row


def test_renderer_renders_multiple_source_ids_as_consecutive_tokens() -> None:
    report = _report()
    report.core.executive_summary.recommendation.source_ids = [
        "raw-source-a",
        "raw-source-b",
    ]

    rendered = render_structured_report(report)

    assert (
        "优先以 Cursor 作为团队采购基线。 [source:raw-source-a][source:raw-source-b]"
        in rendered
    )
