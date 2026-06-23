from __future__ import annotations

import re
from collections.abc import Sequence

from packages.agents.writer.structured_hygiene import (
    has_source_token,
    is_valid_source_id,
)
from packages.agents.writer.structured_report import (
    CitedText,
    MatrixCell,
    SourceAppendixRow,
    StructuredReport,
)
from packages.business_intel.report_sections import SectionLayer, report_section_marker


_WHITESPACE_RE = re.compile(r"\s+")

STRUCTURED_REPORT_ZH_LABELS = {
    "adoption_blockers": "采用障碍",
    "attack_points": "攻击点",
    "battlecard": "战报",
    "claim_risk": "声明风险",
    "community_feedback": "社区与用户反馈",
    "community_triangulation": "社区三角验证",
    "competitor_deep_dives": "竞品深挖",
    "competitive_findings": "竞争发现",
    "competitive_plays": "竞争打法",
    "confidence_boundary": "置信边界",
    "confidence_notes": "置信度说明",
    "decision_matrix": "决策矩阵",
    "decision_summary": "决策摘要",
    "defense_points": "防守点",
    "direct_user_signals": "直接用户与社区信号",
    "evidence_appendix": "证据附录",
    "evidence_gaps": "证据缺口",
    "evidence_limits": "证据边界",
    "executive_summary": "执行摘要",
    "feature_capabilities": "功能与工作流能力",
    "interpretation": "矩阵解读",
    "likely_objections": "可能异议",
    "matrix_gap": "证据缺口",
    "next_actions": "下一步行动",
    "next_collection": "后续采集",
    "persona_adoption": "用户画像与采用路径",
    "positioning": "定位与核心价值",
    "pricing_packaging": "定价与包装",
    "proof_needed_before_external_use": "外部使用前所需证明",
    "rag_gap_fill": "RAG 补缺",
    "recommendation": "建议",
    "rebuttal_talk_tracks": "回应话术",
    "risk_adjusted_rationale": "风险调整理由",
    "scenario_qa": "场景 QA",
    "simulated_research_signals": "模拟调研信号",
    "source_quality": "来源质量",
    "strengths": "优势",
    "support_materials": "支撑材料",
    "swot": "SWOT 分析",
    "switching_triggers": "切换触发器",
    "target_buyer": "目标买方",
    "threats": "威胁",
    "use_when": "适用场景",
    "user_research_evidence": "用户研究证据",
    "user_review_themes": "用户评价整理",
    "weaknesses": "劣势",
    "opportunities": "机会",
}

STRUCTURED_REPORT_EN_LABELS = {
    "adoption_blockers": "Adoption Blockers",
    "attack_points": "Attack Points",
    "battlecard": "Battlecards",
    "claim_risk": "Claim Risk",
    "community_feedback": "Community and User Feedback",
    "community_triangulation": "Community Triangulation",
    "competitor_deep_dives": "Competitor Deep Dives",
    "competitive_findings": "Competitive Findings",
    "competitive_plays": "Competitive Plays",
    "confidence_boundary": "Confidence Boundary",
    "confidence_notes": "Confidence Notes",
    "decision_matrix": "Decision Matrix",
    "decision_summary": "Decision Summary",
    "defense_points": "Defense Points",
    "direct_user_signals": "Direct User and Community Signals",
    "evidence_appendix": "Evidence Appendix",
    "evidence_gaps": "Evidence Gaps",
    "evidence_limits": "Evidence Limits",
    "executive_summary": "Executive Summary",
    "feature_capabilities": "Feature and Workflow Capabilities",
    "interpretation": "Matrix Interpretation",
    "likely_objections": "Likely Objections",
    "matrix_gap": "Evidence gap",
    "next_actions": "Next Actions",
    "next_collection": "Next Collection",
    "persona_adoption": "User Persona and Adoption Path",
    "positioning": "Positioning and Core Value",
    "pricing_packaging": "Pricing and Packaging",
    "proof_needed_before_external_use": "Proof Needed Before External Use",
    "rag_gap_fill": "RAG Gap Fill",
    "recommendation": "Recommendation",
    "rebuttal_talk_tracks": "Rebuttal Talk Tracks",
    "risk_adjusted_rationale": "Risk-Adjusted Rationale",
    "scenario_qa": "Scenario QA",
    "simulated_research_signals": "Simulated Research Signals",
    "source_quality": "Source Quality",
    "strengths": "Strengths",
    "support_materials": "Support Materials",
    "swot": "SWOT Analysis",
    "switching_triggers": "Switching Triggers",
    "target_buyer": "Target Buyer",
    "threats": "Threats",
    "use_when": "Use When",
    "user_research_evidence": "User Research Evidence",
    "user_review_themes": "User Review Themes",
    "weaknesses": "Weaknesses",
    "opportunities": "Opportunities",
}


def render_structured_report(report: StructuredReport) -> str:
    is_zh = _is_zh(report.output_language)
    labels = _labels_for(is_zh)
    lines: list[str] = [f"# {_inline_text(report.topic, 'topic')}", ""]

    _render_executive_summary(lines, report, labels)
    _section_heading(lines, "decision_summary", "core", labels["decision_summary"])
    _bullet_list(lines, report.core.decision_summary)
    _section_heading(lines, "competitive_findings", "core", labels["competitive_findings"])
    _bullet_list(lines, report.core.competitive_findings)
    _render_user_review_themes(lines, report, labels)
    _render_deep_dives(lines, report, labels)
    _render_decision_matrix(lines, report, labels, is_zh)
    _render_swot(lines, report, labels)
    _render_battlecard(lines, report, labels)
    _section_heading(
        lines,
        "community_evidence_triangulation",
        "core",
        labels["community_triangulation"],
    )
    _bullet_list(lines, report.core.community_triangulation)
    _render_support(lines, report, labels, is_zh)

    return "\n".join(lines).strip() + "\n"


def _is_zh(output_language: str) -> bool:
    return output_language.lower().startswith("zh")


def _labels_for(is_zh: bool) -> dict[str, str]:
    return STRUCTURED_REPORT_ZH_LABELS if is_zh else STRUCTURED_REPORT_EN_LABELS


def _render_executive_summary(
    lines: list[str],
    report: StructuredReport,
    labels: dict[str, str],
) -> None:
    summary = report.core.executive_summary
    _section_heading(lines, "executive_summary", "core", labels["executive_summary"])
    _labeled_claim(lines, labels["recommendation"], summary.recommendation)
    _labeled_claim(
        lines,
        labels["risk_adjusted_rationale"],
        summary.risk_adjusted_rationale,
    )
    for posture in summary.competitor_postures:
        _labeled_claim(lines, posture.competitor, posture.posture)
    _labeled_claim(lines, labels["confidence_boundary"], summary.confidence_boundary)
    _heading(lines, 3, labels["next_actions"])
    _bullet_list(lines, summary.next_actions)


def _render_user_review_themes(
    lines: list[str],
    report: StructuredReport,
    labels: dict[str, str],
) -> None:
    themes = report.core.user_review_themes
    _section_heading(lines, "review_theme_summary", "core", labels["user_review_themes"])
    for theme in themes.competitor_themes:
        _heading(lines, 3, theme.competitor)
        _claim_group(lines, labels["direct_user_signals"], theme.direct_user_signals)
        _claim_group(
            lines,
            labels["simulated_research_signals"],
            theme.simulated_research_signals,
        )
        _claim_group(lines, labels["adoption_blockers"], theme.adoption_blockers)
        _claim_group(lines, labels["switching_triggers"], theme.switching_triggers)
        _claim_group(lines, labels["evidence_gaps"], theme.evidence_gaps)
    _claim_group(lines, labels["competitive_findings"], themes.cross_competitor_patterns)
    _claim_group(lines, labels["evidence_limits"], themes.evidence_limits)


def _render_deep_dives(
    lines: list[str],
    report: StructuredReport,
    labels: dict[str, str],
) -> None:
    _section_heading(lines, "competitor_deep_dives", "core", labels["competitor_deep_dives"])
    for deep_dive in report.core.competitor_deep_dives:
        _heading(lines, 3, deep_dive.competitor)
        _claim_group(lines, labels["positioning"], deep_dive.positioning)
        _claim_group(lines, labels["pricing_packaging"], deep_dive.pricing_packaging)
        _claim_group(lines, labels["feature_capabilities"], deep_dive.feature_capabilities)
        _claim_group(lines, labels["persona_adoption"], deep_dive.persona_adoption)
        _claim_group(lines, labels["community_feedback"], deep_dive.community_feedback)
        _claim_group(lines, labels["competitive_plays"], deep_dive.competitive_plays)
        _claim_group(lines, labels["evidence_gaps"], deep_dive.evidence_gaps)


def _render_decision_matrix(
    lines: list[str],
    report: StructuredReport,
    labels: dict[str, str],
    is_zh: bool,
) -> None:
    _section_heading(lines, "side_by_side_matrix", "core", labels["decision_matrix"])
    dimension_label = "维度" if is_zh else "Dimension"
    competitors = [
        _inline_text(competitor, "competitor") for competitor in report.competitors
    ]
    header = [dimension_label, *competitors]
    lines.append(_table_row(header))
    lines.append(_table_row(["---", *(["---"] * len(report.competitors))]))
    for row in report.core.decision_matrix.dimensions:
        cells_by_competitor = {
            _inline_text(cell.competitor, "matrix cell competitor"): cell
            for cell in row.cells
        }
        rendered_cells = [
            _render_matrix_cell(cells_by_competitor.get(competitor), labels)
            for competitor in competitors
        ]
        lines.append(
            _table_row(
                [_inline_text(row.dimension, "matrix dimension"), *rendered_cells]
            )
        )
    lines.append("")
    _claim_group(lines, labels["interpretation"], report.core.decision_matrix.interpretation)
    _claim_group(
        lines,
        labels["confidence_notes"],
        report.core.decision_matrix.confidence_notes,
    )


def _render_swot(
    lines: list[str],
    report: StructuredReport,
    labels: dict[str, str],
) -> None:
    _section_heading(lines, "swot_analysis", "core", labels["swot"])
    for competitor in report.core.swot.competitors:
        _heading(lines, 3, competitor.competitor)
        _claim_group(lines, labels["strengths"], competitor.strengths)
        _claim_group(lines, labels["weaknesses"], competitor.weaknesses)
        _claim_group(lines, labels["opportunities"], competitor.opportunities)
        _claim_group(lines, labels["threats"], competitor.threats)


def _render_battlecard(
    lines: list[str],
    report: StructuredReport,
    labels: dict[str, str],
) -> None:
    _section_heading(lines, "battlecard", "core", labels["battlecard"])
    for play in report.core.battlecard.plays:
        _heading(lines, 3, play.competitor)
        lines.append(
            f"- {labels['target_buyer']}: "
            f"{_inline_text(play.target_buyer, 'target_buyer')}"
        )
        _labeled_claim(lines, labels["use_when"], play.use_when)
        _claim_group(lines, labels["attack_points"], play.attack_points)
        _claim_group(lines, labels["defense_points"], play.defense_points)
        _claim_group(lines, labels["likely_objections"], play.likely_objections)
        _claim_group(lines, labels["rebuttal_talk_tracks"], play.rebuttal_talk_tracks)
        _claim_group(
            lines,
            labels["proof_needed_before_external_use"],
            play.proof_needed_before_external_use,
        )
    _claim_group(lines, labels["evidence_limits"], report.core.battlecard.evidence_limits)


def _render_support(
    lines: list[str],
    report: StructuredReport,
    labels: dict[str, str],
    is_zh: bool,
) -> None:
    support = report.support
    _section_heading(lines, "evidence_support", "support", labels["support_materials"])
    _claim_group(lines, labels["source_quality"], support.source_quality)
    _claim_group(lines, labels["user_research_evidence"], support.user_research_evidence)
    _claim_group(lines, labels["rag_gap_fill"], support.rag_gap_fill)
    _claim_group(lines, labels["scenario_qa"], support.scenario_qa)
    _claim_group(lines, labels["claim_risk"], support.claim_risk)
    _claim_group(lines, labels["next_collection"], support.next_collection)
    _heading(lines, 3, labels["evidence_appendix"])
    _appendix_table(lines, support.evidence_appendix, is_zh)


def _claim_group(
    lines: list[str],
    heading: str,
    claims: Sequence[CitedText],
) -> None:
    if not claims:
        return
    _heading(lines, 4, heading)
    _bullet_list(lines, claims)


def _bullet_list(lines: list[str], claims: Sequence[CitedText]) -> None:
    for claim in claims:
        lines.append(f"- {_render_cited_text(claim)}")
    lines.append("")


def _labeled_claim(lines: list[str], label: str, claim: CitedText) -> None:
    lines.append(f"- {_inline_text(label, 'label')}: {_render_cited_text(claim)}")


def _render_cited_text(claim: CitedText) -> str:
    return (
        f"{_inline_text(claim.text, 'claim text')}"
        f"{_citation_suffix(claim.source_ids)}"
    )


def _render_matrix_cell(cell: MatrixCell | None, labels: dict[str, str]) -> str:
    if cell is None:
        return labels["matrix_gap"]
    return (
        f"{_inline_text(cell.summary, 'matrix summary')}"
        f"{_citation_suffix(cell.source_ids)}"
    )


def _citation_suffix(source_ids: Sequence[str]) -> str:
    if not source_ids:
        return ""
    return " " + "".join(
        f"[source:{_source_id(source_id)}]" for source_id in source_ids
    )


def _appendix_table(
    lines: list[str],
    rows: Sequence[SourceAppendixRow],
    is_zh: bool,
) -> None:
    header = (
        ["来源 ID", "标题", "竞品", "维度", "角色", "置信度"]
        if is_zh
        else ["Source ID", "Title", "Competitor", "Dimension", "Role", "Confidence"]
    )
    lines.append(_table_row(header))
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for row in rows:
        lines.append(
            _table_row(
                [
                    _source_id(row.source_id),
                    _inline_text(row.title, "source title"),
                    _inline_text(row.competitor, "source competitor"),
                    _inline_text(row.dimension, "source dimension"),
                    row.evidence_role,
                    row.confidence,
                ]
            )
        )
    lines.append("")


def _section_heading(
    lines: list[str],
    section_key: str,
    layer: SectionLayer,
    text: str,
) -> None:
    lines.append(report_section_marker(section_key, layer))
    _heading(lines, 2, text)


def _heading(lines: list[str], level: int, text: str) -> None:
    lines.append(f"{'#' * level} {_inline_text(text, 'heading')}")


def _table_row(values: Sequence[str]) -> str:
    return "| " + " | ".join(_table_cell(value) for value in values) + " |"


def _table_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\r\n", " ").replace("\n", " ")


def _inline_text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    if has_source_token(value):
        raise ValueError(f"{field_name} must not contain Markdown source tokens")
    return _WHITESPACE_RE.sub(" ", value).strip()


def _source_id(value: str) -> str:
    source_id = _inline_text(value, "source id")
    if not is_valid_source_id(source_id):
        raise ValueError("source id contains invalid characters")
    return source_id
