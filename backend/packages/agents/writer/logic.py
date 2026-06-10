from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Iterable
from datetime import datetime
from typing import TYPE_CHECKING

from packages.business_intel.scenarios import get_scenario_pack
from packages.i18n.language import (
    language_instruction,
    normalize_output_language,
    repair_mojibake_text,
    report_label,
)
from packages.rag.grounded_prompt import build_run_grounding_prompt
from packages.research.evidence.normalization import normalized_fields_from_source
from packages.research.evidence.text import source_business_snippet
from packages.schema.api_dto import RunDetail
from packages.schema.models import FeatureNode, KnowledgeClaim, QCIssue, RawSource

if TYPE_CHECKING:
    from packages.orchestrator.service import RunRecord


USER_RESEARCH_SOURCE_TYPE_ORDER = (
    "survey_simulated",
    "survey_response",
    "interview_record",
    "manual_transcript",
    "manual_note",
    "manual",
)
USER_RESEARCH_SOURCE_TYPES = set(USER_RESEARCH_SOURCE_TYPE_ORDER)


def writer_user_research_policy_text() -> str:
    source_types = ", ".join(USER_RESEARCH_SOURCE_TYPE_ORDER)
    return (
        f"Treat {source_types} as user-research signals, not as official factual proof."
    )


class WriterAgentMixin:
    async def _real_writer_step(self, record: RunRecord) -> None:
        detail = record.detail
        detail.current_node = "writer"
        self._consume_queued_agent_messages(
            record,
            to_agent="writer",
            consumer_agent="writer",
            message_types={"reflection_ready"},
        )
        await self.emit(detail.id, "node_started", "writer", None, "Calling report writer.")
        previous_report = detail.report_md
        writer_mode = "real LLM call"
        writer_error: str | None = None
        writer_context_json = json.dumps(
            self._writer_context_package(detail),
            ensure_ascii=False,
        )
        layer_context = self._writer_layer_context(detail)
        memory_context = "\n".join(detail.plan.memory_prompt_context) or "none"
        required_sections = self._writer_required_sections(detail)
        grounding_prompt = await self._writer_grounding_prompt(detail)
        user_research_policy = writer_user_research_policy_text()
        language_guidance = language_instruction(detail.output_language)
        try:
            timeout_seconds = max(0.05, float(self._settings.writer_timeout_seconds))
            report_md = await asyncio.wait_for(
                self._trace_llm_text(
                    record,
                    agent="writer",
                    subagent=None,
                    name="report_writer",
                    system=(
                        "You are a senior enterprise competitive-intelligence analyst. "
                        "Produce a concise decision-grade markdown first draft, not a short "
                        "summary. Use an analysis-first structure: lead with an executive "
                        "takeaway, decision summary, competitive findings, competitor deep "
                        "dives, and the selected layer-specific analysis. Put source quality, "
                        "scenario QA, claim risk, RAG gap-fill, verification tasks, and the "
                        "evidence appendix after the core analysis as support material. Write "
                        "with consulting depth: side-by-side matrices, dimension analysis, "
                        "risks, buying implications, and explicit next validation tasks. Cite "
                        "factual claims with existing source IDs using [source:ID]. Do not "
                        "invent source IDs. "
                        "Do not use web_search_result or confidence < 0.75 as the sole support "
                        "for a winner, legal/security certification, pricing, or procurement "
                        "recommendation. If evidence is incomplete, say the conclusion is "
                        "tentative and list the exact evidence gap. Do not claim all sources are "
                        "verified when any source_type is web_search_result or "
                        "llm_public_knowledge. "
                        "Follow the Grounded Evidence Contract exactly. "
                        f"{language_guidance} "
                        f"{user_research_policy} "
                        "Honor confirmed memory guidance when it does not conflict with evidence, "
                        "schema requirements, or compliance policy. "
                        "Use the requested competitive layer to choose the report shape: L1 is a "
                        "direct battlecard, L2 is adjacent workflow and enterprise-risk analysis, "
                        "and L3 is market landscape and category strategy."
                    ),
                    user=(
                        f"Topic: {detail.topic}\n"
                        f"Competitors: {', '.join(detail.plan.competitors)}\n"
                        f"Dimensions: {', '.join(detail.plan.dimensions)}\n"
                        f"Competitive Layer: {detail.plan.competitor_layer}\n"
                        f"Scenario ID: {detail.plan.scenario_id or 'auto'}\n"
                        "Scenario Recommended Dimensions: "
                        f"{', '.join(detail.plan.scenario_recommended_dimensions)}\n"
                        f"QA Rule IDs: {', '.join(detail.plan.qa_rule_ids)}\n"
                        f"Confirmed Memory Preferences:\n{memory_context}\n"
                        f"Layer Report Context: {layer_context}\n"
                        f"{grounding_prompt}\n"
                        f"Writer Context JSON: {writer_context_json}\n\n"
                        f"Required sections:\n{required_sections}\n"
                        "Keep the first draft around 5,500 characters. Spend most of the body "
                        "on cited analysis and implications; keep evidence and QA support "
                        "concise but complete."
                    ),
                ),
                timeout=timeout_seconds,
            )
            detail.report_md = self._harden_report_markdown(detail, report_md)
        except TimeoutError as exc:
            timeout_reason = str(exc) or f"writer LLM exceeded {timeout_seconds:g}s"
            writer_error = timeout_reason
            if previous_report.strip():
                detail.report_md = previous_report
                writer_mode = "preserved previous report after writer error"
            else:
                detail.report_md = self._harden_report_markdown(
                    detail,
                    self._fallback_report_markdown(detail, writer_error),
                )
                writer_mode = "deterministic fallback after writer error"
        except Exception as exc:  # noqa: BLE001 - writer fallback keeps long runs demo-safe.
            writer_error = str(exc)
            if previous_report.strip():
                detail.report_md = previous_report
                writer_mode = "preserved previous report after writer error"
            else:
                detail.report_md = self._harden_report_markdown(
                    detail,
                    self._fallback_report_markdown(detail, writer_error),
                )
                writer_mode = "deterministic fallback after writer error"
        self._append_agent_message(
            record,
            from_agent="writer",
            to_agent="qa",
            message_type="report_ready",
            payload_schema="MarkdownReport",
            payload={
                "report_md": detail.report_md,
                "writer_mode": writer_mode,
                "error": writer_error,
            },
        )
        detail.updated_at = datetime.utcnow()
        projection = self._sync_enterprise_projection(record)
        await self.emit(
            detail.id,
            "report_updated",
            "writer",
            None,
            f"Report markdown updated from {writer_mode}.",
            {
                "report_md": detail.report_md,
                "writer_mode": writer_mode,
                "error": writer_error,
                **self._enterprise_projection_payload(projection),
            },
        )
        await self.emit(detail.id, "node_completed", "writer", None, "Writer completed.")

    def _fallback_report_markdown(self, detail: RunDetail, reason: str) -> str:
        layer_label = self._writer_layer_label(detail)
        output_language = detail.output_language
        is_zh = normalize_output_language(output_language) == "zh-CN"
        lines = [
            f"# {detail.topic} {layer_label}",
            "",
            f"## {report_label(output_language, 'executive_takeaway')}",
        ]
        matrix_sources = self._matrix_source_ids(detail)
        if is_zh:
            lines.append(
                "这份基于证据索引的报告汇总最新结构化知识和对比矩阵，并保留明确的不确定性说明。"
                + self._format_source_refs(matrix_sources)
            )
        else:
            lines.append(
                "This evidence-indexed report summarizes the latest structured knowledge "
                "and comparison matrix while preserving explicit uncertainty."
                + self._format_source_refs(matrix_sources)
            )
        lines.extend(self._fallback_decision_summary_section(detail, matrix_sources))
        lines.extend(self._fallback_competitive_findings_section(detail))
        if detail.comparison_matrix is not None:
            lines.extend(["", f"## {report_label(output_language, 'dimension_winners')}"])
            for dimension, winner in detail.comparison_matrix.winner_by_dimension.items():
                source_ids = [
                    source_id
                    for cell in detail.comparison_matrix.cells
                    if cell.dimension == dimension
                    for source_id in cell.source_ids
                ]
                lines.append(f"- {dimension}: {winner}{self._format_source_refs(source_ids)}")
            lines.extend(["", f"## {report_label(output_language, 'comparison_matrix')}"])
            for cell in detail.comparison_matrix.cells:
                lines.append(
                    f"- {cell.competitor} / {cell.dimension}: {cell.value}"
                    f"{self._format_source_refs(cell.source_ids)}"
                )
        lines.extend(self._fallback_competitor_deep_dives_section(detail))
        lines.extend(self._fallback_layer_sections(detail, matrix_sources, fallback=False))
        lines.extend(self._fallback_evidence_support_section(detail))
        lines.extend(self._fallback_source_quality_section(detail))
        lines.extend(self._fallback_scenario_checklist_section(detail))
        lines.extend(["", f"## {report_label(output_language, 'knowledge_coverage')}"])
        for competitor in detail.plan.competitors:
            knowledge = detail.competitor_knowledge.get(competitor)
            source_ids = knowledge.source_ids if knowledge is not None else []
            confidence = f"{knowledge.confidence:.2f}" if knowledge is not None else "unknown"
            lines.append(
                f"- {competitor}: confidence {confidence}{self._format_source_refs(source_ids)}"
            )
        if detail.reflections:
            latest = detail.reflections[-1]
            lines.extend(["", f"## {report_label(output_language, 'confidence_notes')}"])
            notes = [
                *latest.coverage_gaps[:3],
                *latest.confidence_outliers[:2],
                *latest.cross_competitor_gaps[:2],
            ]
            for note in notes:
                lines.append(f"- {note}{self._format_source_refs(matrix_sources)}")
        lines.extend(self._fallback_claim_validation_section(detail))
        lines.extend(self._fallback_next_collection_plan(detail))
        lines.extend(self._fallback_evidence_appendix(detail))
        lines.extend(
            [
                "",
                f"## {report_label(output_language, 'generation_notes')}",
                "- 确定性写作器因叙事写作器未完成，已基于结构化证据生成本报告。"
                if is_zh
                else (
                    "- The deterministic writer generated this report from structured "
                    "evidence because the narrative writer could not complete."
                ),
                f"- 内部原因：{reason}" if is_zh else f"- Internal reason: {reason}",
            ]
        )
        return "\n".join(lines)

    def _fallback_layer_sections(
        self,
        detail: RunDetail,
        source_ids: list[str],
        *,
        fallback: bool = True,
    ) -> list[str]:
        refs = self._format_source_refs(source_ids)
        layer = detail.plan.competitor_layer
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        if layer == "L1":
            if is_zh:
                return [
                    "",
                    f"## {self._layer_section_heading(detail, fallback=fallback)}",
                    f"- 直接使用定位：在更强证据改变矩阵之前，将此视为近期替代决策。{refs}",
                    f"- 反对意见处理：在销售或产品响应中，优先考虑定价、包装、功能对齐以及切换触发因素。{refs}",
                    f"- 行动偏向：使用置信度最高的维度赢家作为初始战报核心，在发布前验证薄弱单元格。{refs}",
                ]
            return [
                "",
                f"## {self._layer_section_heading(detail, fallback=fallback)}",
                (
                    "- Direct-use position: treat this as a near-term replacement decision "
                    f"until stronger evidence changes the matrix.{refs}"
                ),
                (
                    "- Objection handling: prioritize pricing, packaging, feature parity, "
                    f"and switching triggers in sales or product response.{refs}"
                ),
                (
                    "- Action bias: use the highest-confidence dimension winners as the "
                    f"initial battlecard spine, then verify weak cells before publication.{refs}"
                ),
            ]
        if layer == "L2":
            if is_zh:
                return [
                    "",
                    f"## {self._layer_section_heading(detail, fallback=fallback)}",
                    f"- 相邻工作流威胁：通过工作流重叠、集成杠杆和切换成本暴露来解读矩阵。{refs}",
                    f"- 购买风险：在提出采购建议之前，将已证实的组织控制措施与仅限搜索或低置信度的声明区分开来。{refs}",
                    f"- 监视列表：监控相邻竞品只需一次集成或打包更改即可吞并目标工作流的维度。{refs}",
                ]
            return [
                "",
                f"## {self._layer_section_heading(detail, fallback=fallback)}",
                (
                    "- Adjacent-workflow threat: read the matrix through workflow overlap, "
                    f"integration leverage, and switching-cost exposure.{refs}"
                ),
                (
                    "- Buying risk: separate proven enterprise controls from search-only or "
                    f"low-confidence claims before procurement recommendations.{refs}"
                ),
                (
                    "- Watchlist: monitor the dimensions where adjacent competitors could "
                    f"absorb the target workflow with one integration or packaging change.{refs}"
                ),
            ]
        if layer == "L3":
            if is_zh:
                return [
                    "",
                    f"## {self._layer_section_heading(detail, fallback=fallback)}",
                    f"- 类别视角：避免单一直接赢家，按细分市场、趋势信号和基准强度对竞品进行分组。{refs}",
                    f"- 战略视角：在证据广度仍低于景观级覆盖率时，将建议视为投资组合选项。{refs}",
                    f"- 不确定性视角：在做出类别范围的声明之前，优先增加竞品和市场级来源。{refs}",
                ]
            return [
                "",
                f"## {self._layer_section_heading(detail, fallback=fallback)}",
                (
                    "- Category view: avoid a single direct winner and group competitors by "
                    f"segment, trend signal, and benchmark strength.{refs}"
                ),
                (
                    "- Strategy view: treat recommendations as portfolio options while "
                    f"evidence breadth remains below landscape-grade coverage.{refs}"
                ),
                (
                    "- Uncertainty view: prioritize adding competitors and market-level "
                    f"sources before making category-wide claims.{refs}"
                ),
            ]
        if is_zh:
            implication = (
                "在叙事写作器能够重新生成更完整版本之前，请使用此基于证据的临时读取版本。"
                if fallback
                else (
                    "将此部分用作具有明确不确定性的基于证据的业务读取版本。"
                )
            )
        else:
            implication = (
                "Use this evidence-indexed interim readout until the narrative writer "
                "can regenerate a fuller version."
                if fallback
                else (
                    "Use this section as an evidence-indexed business readout with explicit "
                    "uncertainty."
                )
            )
        return [
            "",
            f"## {self._layer_section_heading(detail, fallback=fallback)}",
            f"- {implication}{refs}",
        ]

    def _fallback_decision_summary_section(
        self, detail: RunDetail, source_ids: list[str]
    ) -> list[str]:
        refs = self._format_source_refs(source_ids)
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        dimensions = ", ".join(detail.plan.dimensions) or ("所请求的维度" if is_zh else "the requested dimensions")
        competitors = ", ".join(detail.plan.competitors) or detail.topic
        if detail.comparison_matrix is not None and detail.comparison_matrix.winner_by_dimension:
            winners = ", ".join(
                f"{dimension}: {winner}"
                for dimension, winner in detail.comparison_matrix.winner_by_dimension.items()
            )
        else:
            winners = "尚无评分赢家；将来源覆盖率和 QA 状态作为约束条件" if is_zh else "no scored winner yet; use source coverage and QA status as constraints"
        if is_zh:
            return [
                "",
                f"## {report_label(detail.output_language, 'decision_summary')}",
                (
                    f"- 推荐行动：使用此 {self._writer_layer_label(detail)} 对比 "
                    f"{competitors} 在 {dimensions} 上的表现；决策锚定在 {winners}。{refs}"
                ),
                (
                    "- 决策姿态：优先考虑具有已证实、高置信度证据的维度，并将薄弱单元格路由到验证计划中。"
                    f"{refs}"
                ),
                (
                    "- 当证据为单来源或仅限搜索时，不要夸大矩阵赢家、采购准备就绪度、安全姿态"
                    f"或定价结论。{refs}"
                ),
            ]
        return [
            "",
            f"## {report_label(detail.output_language, 'decision_summary')}",
            (
                f"- Recommended action: use this {self._writer_layer_label(detail)} to compare "
                f"{competitors} on {dimensions}; anchor the decision on {winners}.{refs}"
            ),
            (
                "- Decision posture: prioritize dimensions with verified, high-confidence "
                f"evidence and route weak cells into the verification plan.{refs}"
            ),
            (
                "- Do not overstate matrix winners, procurement readiness, security posture, "
                f"or pricing conclusions when evidence is single-source or search-only.{refs}"
            ),
        ]

    def _fallback_competitive_findings_section(self, detail: RunDetail) -> list[str]:
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        lines = [
            "",
            f"## {report_label(detail.output_language, 'competitive_findings')}",
        ]
        if detail.comparison_matrix is None:
            source_ids = self._matrix_source_ids(detail)
            if is_zh:
                lines.append(
                    "- 结构化对比数据仍然稀疏；将来源覆盖率、QA 发现和层上下文作为主要的决策约束。"
                    f"{self._format_source_refs(source_ids)}"
                )
            else:
                lines.append(
                    "- Structured comparison data is still thin; treat source coverage, QA "
                    "findings, and layer context as the main decision constraints."
                    f"{self._format_source_refs(source_ids)}"
                )
            return lines

        for dimension in detail.plan.dimensions:
            cells = [
                cell for cell in detail.comparison_matrix.cells if cell.dimension == dimension
            ]
            source_ids = [source_id for cell in cells for source_id in cell.source_ids]
            winner = detail.comparison_matrix.winner_by_dimension.get(dimension)
            if winner:
                if is_zh:
                    lines.append(
                        f"- {dimension}：{winner} 在该维度领先，但其含义应与引用的单元格和置信水平保持一致。"
                        f"{self._format_source_refs(source_ids)}"
                    )
                else:
                    lines.append(
                        f"- {dimension}: {winner} leads this dimension, but the implication "
                        "should stay tied to the cited cells and confidence levels."
                        f"{self._format_source_refs(source_ids)}"
                    )
            elif cells:
                if is_zh:
                    lines.append(
                        f"- {dimension}：存在用于对比的证据，但在进行另一次验证之前，不应断言明确的赢家。"
                        f"{self._format_source_refs(source_ids)}"
                    )
                else:
                    lines.append(
                        f"- {dimension}: evidence exists for comparison, but no clear winner "
                        "should be asserted without another validation pass."
                        f"{self._format_source_refs(source_ids)}"
                    )
        if len(lines) == 2:
            if is_zh:
                lines.append(
                    "- 尚无维度级别的发现；在做出竞争建议之前，请使用收集任务。"
                    f"{self._format_source_refs(self._matrix_source_ids(detail))}"
                )
            else:
                lines.append(
                    "- No dimension-level findings are available yet; use collection tasks before "
                    "making a competitive recommendation."
                    f"{self._format_source_refs(self._matrix_source_ids(detail))}"
                )
        return lines

    def _fallback_competitor_deep_dives_section(self, detail: RunDetail) -> list[str]:
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        lines = [
            "",
            f"## {report_label(detail.output_language, 'competitor_deep_dives')}",
        ]
        matrix = detail.comparison_matrix
        for competitor in detail.plan.competitors:
            if matrix is None:
                source_ids = [
                    source.id for source in detail.raw_sources if source.competitor == competitor
                ][:4]
                if is_zh:
                    lines.append(
                        f"- {competitor} 优势：尚未确立；在声称优势之前，请使用已证实的证据。"
                        f"{self._format_source_refs(source_ids)}"
                    )
                    lines.append(
                        f"- {competitor} 劣势：覆盖不足的维度在链接更多来源之前仍未解决。"
                        f"{self._format_source_refs(source_ids)}"
                    )
                    lines.append(
                        f"- {competitor} 注意事项：在 QA 和来源覆盖率提高之前，避免绝对声明。"
                        f"{self._format_source_refs(source_ids)}"
                    )
                else:
                    lines.append(
                        f"- {competitor} wins: not established yet; use verified evidence before "
                        f"claiming advantage.{self._format_source_refs(source_ids)}"
                    )
                    lines.append(
                        f"- {competitor} weaknesses: under-covered dimensions remain unresolved "
                        f"until more sources are linked.{self._format_source_refs(source_ids)}"
                    )
                    lines.append(
                        f"- {competitor} watchouts: avoid absolute claims until QA and source "
                        f"coverage improve.{self._format_source_refs(source_ids)}"
                    )
                continue

            competitor_cells = [
                cell for cell in matrix.cells if cell.competitor == competitor
            ]
            source_ids = [source_id for cell in competitor_cells for source_id in cell.source_ids]
            winning_dimensions = [
                dimension
                for dimension, winner in matrix.winner_by_dimension.items()
                if winner == competitor
            ]
            weaker_dimensions = [
                dimension
                for dimension, winner in matrix.winner_by_dimension.items()
                if winner and winner != competitor
            ]
            if is_zh:
                wins = ", ".join(winning_dimensions) or "尚无确认的维度赢家"
                weaknesses = ", ".join(weaker_dimensions) or "尚无明确的矩阵落后维度"
                lines.append(
                    f"- {competitor} 优势：{wins}；保持声明限定在引用的维度证据范围内。"
                    f"{self._format_source_refs(source_ids)}"
                )
                lines.append(
                    f"- {competitor} 劣势：{weaknesses}；验证差距是真正的竞争劣势还是收集限制。"
                    f"{self._format_source_refs(source_ids)}"
                )
                lines.append(
                    f"- {competitor} 注意事项：在将这些转为外部宣传信息之前，监控定价、包装、功能和买家反对意见声明。"
                    f"{self._format_source_refs(source_ids)}"
                )
            else:
                wins = ", ".join(winning_dimensions) or "no confirmed dimension winner yet"
                weaknesses = ", ".join(weaker_dimensions) or "no explicit matrix loss yet"
                lines.append(
                    f"- {competitor} wins: {wins}; keep the claim scoped to the cited "
                    f"dimension evidence.{self._format_source_refs(source_ids)}"
                )
                lines.append(
                    f"- {competitor} weaknesses: {weaknesses}; verify whether gaps are real "
                    "competitive disadvantages or collection limits."
                    f"{self._format_source_refs(source_ids)}"
                )
                lines.append(
                    f"- {competitor} watchouts: monitor pricing, packaging, feature, and buyer "
                    "objection claims before turning this into external messaging."
                    f"{self._format_source_refs(source_ids)}"
                )
        return lines

    def _fallback_evidence_support_section(self, detail: RunDetail) -> list[str]:
        refs = self._format_source_refs(self._matrix_source_ids(detail))
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        if is_zh:
            return [
                "",
                f"## {report_label(detail.output_language, 'evidence_support')}",
                f"- 使用以下支持部分来审计来源质量、场景 QA、知识覆盖、声明风险以及剩余的验证任务。{refs}",
                f"- 保持支持材料简洁且完整，以便上面的决策分析仍为主要读取内容。{refs}",
            ]
        return [
            "",
            f"## {report_label(detail.output_language, 'evidence_support')}",
            (
                "- Use the following support sections to audit source quality, scenario QA, "
                f"knowledge coverage, claim risk, and remaining verification tasks.{refs}"
            ),
            (
                "- Keep support material concise and complete so the decision analysis above "
                f"remains the primary readout.{refs}"
            ),
        ]

    def _fallback_source_quality_section(self, detail: RunDetail) -> list[str]:
        heading = report_label(detail.output_language, "source_quality")
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        if not detail.raw_sources:
            return [
                "",
                f"## {heading}",
                "- 没有可用的原始来源，因此所有结论在使用前都需要进行收集。" if is_zh else "- No raw sources are available, so all conclusions require collection before use.",
            ]
        by_type: dict[str, list[tuple[str, float]]] = {}
        for source in detail.raw_sources:
            by_type.setdefault(source.source_type, []).append((source.id, source.confidence))
        lines = ["", f"## {heading}"]
        for source_type, values in sorted(by_type.items()):
            source_ids = [source_id for source_id, _confidence in values]
            avg_confidence = sum(confidence for _source_id, confidence in values) / len(values)
            if is_zh:
                lines.append(
                    f"- {source_type}：{len(values)} 个来源，平均置信度 "
                    f"{avg_confidence:.2f}{self._format_source_refs(source_ids)}"
                )
            else:
                lines.append(
                    f"- {source_type}: {len(values)} source(s), avg confidence "
                    f"{avg_confidence:.2f}{self._format_source_refs(source_ids)}"
                )
        return lines

    def _fallback_scenario_checklist_section(self, detail: RunDetail) -> list[str]:
        scenario_id = detail.plan.scenario_id or "auto"
        pack = get_scenario_pack(scenario_id) if detail.plan.scenario_id else None
        recommended = detail.plan.scenario_recommended_dimensions or detail.plan.dimensions
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        if is_zh:
            lines = [
                "",
                f"## {report_label(detail.output_language, 'scenario_checklist')}",
                (
                    f"- 场景：{scenario_id}；竞品层：{detail.plan.competitor_layer}；"
                    f"推荐维度：{', '.join(recommended) or '无'}。"
                ),
            ]
            if pack is not None:
                lines.append(f"- 场景意图：{pack.description}")
                for question in pack.analyst_questions[:3]:
                    lines.append(f"- 分析师问题：{question}")
                for requirement in pack.evidence_requirements[:3]:
                    lines.append(f"- 证据要求：{requirement}")
            if detail.plan.qa_rule_ids:
                lines.append(f"- QA 规则：{', '.join(detail.plan.qa_rule_ids)}")
        else:
            lines = [
                "",
                f"## {report_label(detail.output_language, 'scenario_checklist')}",
                (
                    f"- Scenario: {scenario_id}; layer: {detail.plan.competitor_layer}; "
                    f"recommended dimensions: {', '.join(recommended) or 'none'}."
                ),
            ]
            if pack is not None:
                lines.append(f"- Scenario intent: {pack.description}")
                for question in pack.analyst_questions[:3]:
                    lines.append(f"- Analyst question: {question}")
                for requirement in pack.evidence_requirements[:3]:
                    lines.append(f"- Evidence requirement: {requirement}")
            if detail.plan.qa_rule_ids:
                lines.append(f"- QA rules: {', '.join(detail.plan.qa_rule_ids)}")
        return lines

    def _fallback_next_collection_plan(self, detail: RunDetail) -> list[str]:
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        lines = ["", f"## {report_label(detail.output_language, 'next_collection')}"]
        source_ids_by_dimension: dict[str, list[str]] = {}
        for source in detail.raw_sources:
            source_ids_by_dimension.setdefault(source.dimension, []).append(source.id)
        planned = 0
        for dimension in detail.plan.dimensions:
            source_ids = source_ids_by_dimension.get(dimension, [])
            if len(source_ids) >= max(1, min(2, len(detail.plan.competitors))):
                continue
            planned += 1
            if is_zh:
                lines.append(
                    f"- 为覆盖不足的竞品添加更强的 {dimension} 证据"
                    f"{self._format_source_refs(source_ids)}"
                )
            else:
                lines.append(
                    f"- Add stronger {dimension} evidence for under-covered competitors"
                    f"{self._format_source_refs(source_ids)}"
                )
        for issue in detail.qa_findings[:3]:
            planned += 1
            if is_zh:
                lines.append(f"- 解决 QA 发现 `{issue.id}`：{issue.problem}")
            else:
                lines.append(f"- Resolve QA finding `{issue.id}`: {issue.problem}")
        if planned == 0:
            if is_zh:
                lines.append(
                    "- 仅针对陈旧、被拒绝或低置信度的证据重新进行收集。"
                )
            else:
                lines.append(
                    "- Re-run collection only for stale, rejected, or low-confidence evidence."
                )
        return lines

    def _fallback_evidence_appendix(self, detail: RunDetail) -> list[str]:
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        lines = ["", f"## {report_label(detail.output_language, 'evidence_appendix')}"]
        if not detail.raw_sources:
            if is_zh:
                lines.append("- 本报告草案未附带任何证据记录。")
            else:
                lines.append("- No evidence records are attached to this report draft.")
            return lines
        for source in detail.raw_sources[:8]:
            if is_zh:
                lines.append(
                    f"- {source.id}：{source.title} / {source.source_type} / 置信度 "
                    f"{source.confidence:.2f} [source:{source.id}]"
                )
            else:
                lines.append(
                    f"- {source.id}: {source.title} / {source.source_type} / confidence "
                    f"{source.confidence:.2f} [source:{source.id}]"
                )
        if len(detail.raw_sources) > 8:
            omitted_count = len(detail.raw_sources) - 8
            if is_zh:
                lines.append(f"- 附录中省略了 {omitted_count} 个额外来源。")
            else:
                lines.append(f"- {omitted_count} additional source(s) omitted from this appendix.")
        return lines

    def _harden_report_markdown(self, detail: RunDetail, markdown: str) -> str:
        repaired = repair_mojibake_text(markdown)
        return self._ensure_report_claim_citations(
            detail,
            self._repair_report_source_tokens(
                detail,
                self._ensure_report_required_sections(detail, repaired),
            ),
        )

    def _ensure_report_required_sections(self, detail: RunDetail, markdown: str) -> str:
        hardened = markdown.strip()
        if not hardened:
            hardened = self._fallback_report_markdown(detail, "empty writer output")
        source_ids = self._matrix_source_ids(detail)
        executive_headings = self._report_label_aliases(
            "executive_takeaway",
            "executive_summary",
            "executive_overview",
        )
        layer_heading_aliases = self._report_label_aliases(
            self._layer_section_label_key(detail)
        )
        core_section_groups = [
            (
                executive_headings,
                [
                    "",
                    f"## {report_label(detail.output_language, 'executive_takeaway')}",
                    (
                        "This report is structured as decision analysis first, with evidence "
                        "and QA support after the core competitive readout."
                        f"{self._format_source_refs(source_ids)}"
                    ),
                ],
            ),
            (
                self._report_label_aliases("decision_summary"),
                self._fallback_decision_summary_section(detail, source_ids),
            ),
            (
                self._report_label_aliases("competitive_findings"),
                self._fallback_competitive_findings_section(detail),
            ),
            (
                self._report_label_aliases("competitor_deep_dives"),
                self._fallback_competitor_deep_dives_section(detail),
            ),
            (
                layer_heading_aliases,
                self._fallback_layer_sections(detail, source_ids, fallback=False),
            ),
        ]
        core_blocks = [
            self._section_body(lines)
            for headings, lines in core_section_groups
            if lines and not self._report_has_any_heading(hardened, headings)
        ]
        if core_blocks:
            support_headings = [
                heading
                for aliases in self._support_report_heading_alias_groups()
                for heading in aliases
            ]
            insert_at = self._first_report_heading_index(hardened, support_headings)
            core_block = "\n\n".join(core_blocks)
            if insert_at is None:
                hardened = f"{hardened}\n\n{core_block}"
            else:
                hardened = (
                    f"{hardened[:insert_at].rstrip()}\n\n{core_block}\n\n"
                    f"{hardened[insert_at:].lstrip()}"
                )

        support_section_groups = [
            (
                report_label(detail.output_language, "evidence_support"),
                self._report_label_aliases("evidence_support"),
                self._fallback_evidence_support_section(detail),
            ),
            (
                report_label(detail.output_language, "source_quality"),
                self._report_label_aliases("source_quality"),
                self._fallback_source_quality_section(detail),
            ),
            (
                report_label(detail.output_language, "memory_context"),
                self._report_label_aliases("memory_context"),
                self._fallback_memory_context_section(detail),
            ),
            (
                report_label(detail.output_language, "user_research_evidence"),
                self._report_label_aliases("user_research_evidence"),
                self._fallback_user_research_section(detail),
            ),
            (
                report_label(detail.output_language, "rag_gap_fill"),
                self._report_label_aliases("rag_gap_fill"),
                self._fallback_rag_gap_fill_section(detail),
            ),
            (
                report_label(detail.output_language, "scenario_checklist"),
                self._report_label_aliases("scenario_checklist"),
                self._fallback_scenario_checklist_section(detail),
            ),
            (
                report_label(detail.output_language, "claim_risk"),
                self._report_label_aliases("claim_risk"),
                self._fallback_claim_validation_section(detail),
            ),
            (
                report_label(detail.output_language, "next_collection"),
                self._report_label_aliases("next_collection"),
                self._fallback_next_collection_plan(detail),
            ),
            (
                report_label(detail.output_language, "evidence_appendix"),
                self._report_label_aliases("evidence_appendix"),
                self._fallback_evidence_appendix(detail),
            ),
        ]
        support_order_heading_groups = self._support_report_heading_alias_groups()
        for heading, heading_aliases, lines in support_section_groups:
            if lines and not self._report_has_any_heading(hardened, heading_aliases):
                support_index = next(
                    index
                    for index, aliases in enumerate(support_order_heading_groups)
                    if heading in aliases
                )
                later_headings = [
                    later_heading
                    for aliases in support_order_heading_groups[support_index + 1 :]
                    for later_heading in aliases
                ]
                insert_at = self._first_report_heading_index(hardened, later_headings)
                section_body = self._section_body(lines)
                if insert_at is None:
                    hardened = f"{hardened}\n\n{section_body}"
                else:
                    hardened = (
                        f"{hardened[:insert_at].rstrip()}\n\n{section_body}\n\n"
                        f"{hardened[insert_at:].lstrip()}"
                    )
        return self._normalize_report_section_order(detail, hardened)

    def _layer_section_heading(self, detail: RunDetail, *, fallback: bool = True) -> str:
        return report_label(detail.output_language, self._layer_section_label_key(detail))

    def _layer_section_label_key(self, detail: RunDetail) -> str:
        if detail.plan.competitor_layer == "L1":
            return "battlecard"
        if detail.plan.competitor_layer == "L2":
            return "workflow_enterprise_risk"
        if detail.plan.competitor_layer == "L3":
            return "market_landscape"
        return "business_implications"

    def _report_label_aliases(self, *keys: str) -> list[str]:
        labels: list[str] = []
        for key in keys:
            for output_language in ("en-US", "zh-CN"):
                label = report_label(output_language, key)
                if label not in labels:
                    labels.append(label)
        return labels

    def _support_report_heading_alias_groups(self) -> list[list[str]]:
        return [
            self._report_label_aliases("evidence_support"),
            self._report_label_aliases("source_quality"),
            self._report_label_aliases("memory_context"),
            self._report_label_aliases("user_research_evidence"),
            self._report_label_aliases("rag_gap_fill"),
            self._report_label_aliases("scenario_checklist"),
            self._report_label_aliases("knowledge_coverage"),
            self._report_label_aliases("confidence_notes"),
            self._report_label_aliases("claim_risk"),
            self._report_label_aliases("next_collection"),
            self._report_label_aliases("evidence_appendix"),
            self._report_label_aliases("generation_notes"),
        ]

    def _report_has_heading(self, markdown: str, heading: str) -> bool:
        return any(
            self._report_heading_matches(match.group(1), heading)
            for match in self._iter_report_headings(markdown)
        )

    def _report_has_any_heading(self, markdown: str, headings: Iterable[str]) -> bool:
        return any(self._report_has_heading(markdown, heading) for heading in headings)

    def _first_report_heading_index(
        self, markdown: str, headings: Iterable[str]
    ) -> int | None:
        heading_list = list(headings)
        positions = [
            match.start()
            for match in self._iter_report_headings(markdown)
            if any(
                self._report_heading_matches(match.group(1), heading)
                for heading in heading_list
            )
        ]
        return min(positions) if positions else None

    def _iter_report_headings(self, markdown: str) -> Iterable[re.Match[str]]:
        return re.finditer(
            r"^\s*#{1,6}\s+(.+?)\s*#*\s*$",
            markdown,
            flags=re.IGNORECASE | re.MULTILINE,
        )

    def _report_heading_matches(self, heading: str, alias: str) -> bool:
        normalized_heading = self._normalize_report_heading_text(heading)
        normalized_alias = self._normalize_report_heading_text(alias)
        return normalized_heading == normalized_alias or normalized_alias in normalized_heading

    def _normalize_report_heading_text(self, heading: str) -> str:
        cleaned = re.sub(r"\s+", " ", heading.strip().strip("#").strip())
        cleaned = re.sub(
            r"^(?:section\s+)?(?:\d+(?:\.\d+)*|[ivxlcdm]+)[\.)]\s+",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        return cleaned.casefold()

    def _normalize_report_section_order(self, detail: RunDetail, markdown: str) -> str:
        matches = list(
            re.finditer(
                r"^##\s+(.+?)\s*$",
                markdown,
                flags=re.MULTILINE,
            )
        )
        if not matches:
            return markdown

        heading_groups = self._ordered_report_heading_groups(detail)
        heading_order = [
            (index, heading)
            for index, group in enumerate(heading_groups)
            for heading in group
        ]
        support_heading_aliases = [
            heading
            for group in self._support_report_heading_alias_groups()
            for heading in group
        ]
        first_support_start = min(
            (
                match.start()
                for match in matches
                if any(
                    self._report_heading_matches(match.group(1).strip(), heading)
                    for heading in support_heading_aliases
                )
            ),
            default=None,
        )
        known_sections: dict[int, list[str]] = {}
        pre_support_unknown_sections: list[str] = []
        tail_unknown_sections: list[str] = []
        for index, match in enumerate(matches):
            section_end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
            heading = match.group(1).strip()
            section = markdown[match.start() : section_end].strip()
            order_index = next(
                (
                    index
                    for index, known_heading in heading_order
                    if self._report_heading_matches(heading, known_heading)
                ),
                None,
            )
            if order_index is None:
                if first_support_start is not None and match.start() < first_support_start:
                    pre_support_unknown_sections.append(section)
                else:
                    tail_unknown_sections.append(section)
            else:
                known_sections.setdefault(order_index, []).append(section)

        if not known_sections:
            return markdown

        preamble = markdown[: matches[0].start()].strip()
        support_start_index = len(heading_groups) - len(
            self._support_report_heading_alias_groups()
        )
        core_sections = [
            section
            for index in range(support_start_index)
            for section in known_sections.get(index, [])
        ]
        support_sections = [
            section
            for index in range(support_start_index, len(heading_groups))
            for section in known_sections.get(index, [])
        ]
        return "\n\n".join(
            part
            for part in [
                preamble,
                *core_sections,
                *pre_support_unknown_sections,
                *support_sections,
                *tail_unknown_sections,
            ]
            if part
        )

    def _ordered_report_heading_groups(self, detail: RunDetail) -> list[list[str]]:
        return [
            self._report_label_aliases(
                "executive_takeaway",
                "executive_summary",
                "executive_overview",
            ),
            self._report_label_aliases("decision_summary"),
            self._report_label_aliases("competitive_findings"),
            self._report_label_aliases("dimension_winners"),
            self._report_label_aliases("comparison_matrix", "side_by_side_matrix"),
            self._report_label_aliases("competitor_deep_dives"),
            self._report_label_aliases(self._layer_section_label_key(detail)),
            *self._support_report_heading_alias_groups(),
        ]

    def _section_body(self, lines: list[str]) -> str:
        return "\n".join(lines).strip()

    def _writer_layer_label(self, detail: RunDetail) -> str:
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        if detail.plan.competitor_layer == "L1":
            return "直接战报" if is_zh else "Direct Battlecard"
        if detail.plan.competitor_layer == "L2":
            return "相邻工作流评估" if is_zh else "Adjacent Workflow Review"
        if detail.plan.competitor_layer == "L3":
            return "市场格局" if is_zh else "Market Landscape"
        return "竞品分析报告" if is_zh else "Competitive Analysis Report"

    def _writer_layer_context(self, detail: RunDetail) -> str:
        layer = detail.plan.competitor_layer
        scenario = detail.plan.scenario_id or "auto"
        recommended = ", ".join(detail.plan.scenario_recommended_dimensions) or "none"
        if layer == "L1":
            focus = (
                "Direct replacement comparison. Emphasize winner/loser tradeoffs, pricing "
                "and packaging, feature parity, sales objections, switching triggers, and "
                "near-term product response."
            )
        elif layer == "L2":
            focus = (
                "Adjacent workflow comparison. Emphasize workflow overlap, ecosystem and "
                "integration leverage, enterprise adoption risk, switching cost, and where "
                "an adjacent product could absorb the user's use case."
            )
        elif layer == "L3":
            focus = (
                "Market landscape analysis. Emphasize category segmentation, clusters, trend "
                "signals, benchmark dimensions, uncertainty, and strategy options rather than "
                "a simplistic direct winner."
            )
        else:
            focus = "General competitive-intelligence report with explicit uncertainty."
        return f"{focus} Scenario={scenario}. Recommended dimensions={recommended}."

    def _writer_required_sections(self, detail: RunDetail) -> str:
        output_language = detail.output_language
        analysis_sections = [
            (
                f"{report_label(output_language, 'executive_takeaway')}: lead with the "
                "decision-grade takeaway and confidence caveats."
            ),
            (
                f"{report_label(output_language, 'decision_summary')}: state the recommended "
                "action, decision posture, and what not to overstate."
            ),
            (
                f"{report_label(output_language, 'competitive_findings')}: summarize the "
                "highest-impact dimension findings and implications."
            ),
            (
                f"{report_label(output_language, 'competitor_deep_dives')}: cover where "
                "each competitor wins, has weaknesses, and needs watchouts."
            ),
            (
                f"{report_label(output_language, 'side_by_side_matrix')}: cover every "
                "competitor and dimension with cited cells."
            ),
        ]
        layer = detail.plan.competitor_layer
        if layer == "L1":
            layer_sections = [
                (
                    f"{report_label(output_language, 'battlecard')}: where each competitor "
                    "wins, loses, is vulnerable, and how to handle objections."
                ),
                "Pricing, packaging, feature parity, switching triggers, and sales response.",
                "Recommended product or go-to-market response with evidence limits.",
            ]
        elif layer == "L2":
            layer_sections = [
                (
                    f"{report_label(output_language, 'workflow_enterprise_risk')}: workflow "
                    "overlap, ecosystem leverage, and enterprise-risk implications."
                ),
                "Enterprise buying risks, switching costs, integration exposure, and controls.",
                "Strategic watchlist for adjacent competitors that could absorb the workflow.",
            ]
        elif layer == "L3":
            layer_sections = [
                (
                    f"{report_label(output_language, 'market_landscape')}: market "
                    "segmentation, competitor clusters, and category strategy."
                ),
                "Trend and benchmark signals by category segment.",
                "Strategic options with uncertainty and evidence gaps clearly separated.",
            ]
        else:
            layer_sections = [
                (
                    f"{report_label(output_language, 'business_implications')}: business "
                    "implications and next validation tasks."
                )
            ]
        support_sections = [
            (
                f"{report_label(output_language, 'evidence_support')}: place source quality, "
                "QA, RAG gap-fill, claim risk, verification, and appendices after the core "
                "analysis."
            ),
            (
                f"{report_label(output_language, 'source_quality')}: separate official or "
                "verified sources from search-only or low-confidence leads."
            ),
            (
                f"{report_label(output_language, 'memory_context')}: include confirmed memory "
                "guidance only when present and not conflicting with evidence."
            ),
            (
                f"{report_label(output_language, 'user_research_evidence')}: treat surveys, "
                "interviews, and manual notes as directional signals, not official proof."
            ),
            (
                f"{report_label(output_language, 'rag_gap_fill')}: list retrieval gaps that "
                "must be closed before publication."
            ),
            (
                f"{report_label(output_language, 'scenario_checklist')}: tie the selected "
                "ScenarioPack to analyst questions, evidence requirements, and QA rules."
            ),
            (
                f"{report_label(output_language, 'claim_risk')}: list weak claims, "
                "low-confidence sources, and single-source high-risk conclusions."
            ),
            (
                f"{report_label(output_language, 'next_collection')}: next collection and "
                "verification tasks."
            ),
            (
                f"{report_label(output_language, 'evidence_appendix')}: important source IDs "
                "with type and confidence."
            ),
        ]
        return "\n".join(
            f"{index}. {section}"
            for index, section in enumerate(
                [*analysis_sections, *layer_sections, *support_sections],
                start=1,
            )
        )

    async def _writer_grounding_prompt(self, detail: RunDetail) -> str:
        grounding = build_run_grounding_prompt(
            sources=detail.raw_sources,
            qa_findings=detail.qa_findings,
        )
        # Enrich with KB retrieval context
        try:
            from packages.tools.rag_retrieve import rag_retrieve_tool
            query = getattr(detail.plan, "topic", "") or ""
            if query:
                kb_results = await rag_retrieve_tool.ainvoke({
                    "query": query,
                    "competitors": list(detail.plan.competitors),
                    "dimensions": list(detail.plan.dimensions),
                    "top_k": 5,
                })
                if kb_results:
                    grounding += "\n\n## Additional KB Evidence\n"
                    for r in kb_results[:5]:
                        grounding += f"- {r}\n"
        except Exception:
            pass  # Non-fatal: RAG enrichment is optional
        return grounding

    def _writer_context_package(self, detail: RunDetail) -> dict[str, object]:
        return {
            "sources": self._writer_source_digest(detail.raw_sources),
            "competitors": {
                competitor: self._writer_competitor_digest(detail, competitor)
                for competitor in detail.plan.competitors
            },
            "comparison_matrix": self._writer_matrix_digest(detail),
            "qa_findings": [self._writer_issue_digest(issue) for issue in detail.qa_findings[:10]],
            "reflections": [
                {
                    "iteration": reflection.iteration,
                    "coverage_gaps": [
                        self._trim_sentence(item, 180) for item in reflection.coverage_gaps[:4]
                    ],
                    "confidence_outliers": [
                        self._trim_sentence(item, 180)
                        for item in reflection.confidence_outliers[:4]
                    ],
                    "cross_competitor_gaps": [
                        self._trim_sentence(item, 180)
                        for item in reflection.cross_competitor_gaps[:4]
                    ],
                }
                for reflection in detail.reflections[-2:]
            ],
        }

    def _writer_source_digest(self, sources: list[RawSource]) -> list[dict[str, object]]:
        digests: list[dict[str, object]] = []
        for source in sources[:24]:
            snippet = source_business_snippet(source, dimension=source.dimension, limit=240)
            digest = {
                "id": source.id,
                "competitor": source.competitor,
                "covered_competitors": source.covered_competitors,
                "dimension": source.dimension,
                "source_type": source.source_type,
                "title": self._trim_sentence(source.title, 120),
                "url": str(source.url) if source.url else None,
                "snippet": self._trim_sentence(snippet, 240),
                "confidence": round(source.confidence, 3),
            }
            if not snippet:
                digest["snippet_quality"] = "omitted_no_clean_business_snippet"
            normalized_fields = normalized_fields_from_source(source)
            if normalized_fields:
                digest["normalized_fields"] = normalized_fields
            digests.append(digest)
        return digests

    def _writer_competitor_digest(self, detail: RunDetail, competitor: str) -> dict[str, object]:
        kb = detail.competitor_kbs.get(competitor)
        knowledge = detail.competitor_knowledge.get(competitor)
        slices = {}
        if kb is not None:
            slices = {
                dimension: [self._trim_sentence(item, 180) for item in findings[:3]]
                for dimension, findings in kb.slices.items()
                if dimension in detail.plan.dimensions
            }
        return {
            "kb_slices": slices,
            "source_ids": (knowledge.source_ids[:8] if knowledge is not None else []),
            "confidence": (
                round(knowledge.confidence, 3) if knowledge is not None else None
            ),
            "pricing": self._writer_pricing_digest(knowledge),
            "feature_tree": self._writer_feature_tree_digest(knowledge),
            "feature_claims": self._writer_feature_claim_digest(knowledge),
            "persona_claims": self._writer_persona_claim_digest(knowledge),
        }

    def _writer_pricing_digest(self, knowledge: object | None) -> dict[str, object]:
        if knowledge is None or not hasattr(knowledge, "pricing_model"):
            return {"tiers": [], "notes": []}
        pricing = knowledge.pricing_model
        return {
            "tiers": [
                {
                    "name": self._trim_sentence(tier.name, 80),
                    "price": self._trim_sentence(tier.price, 80),
                    "claims": self._writer_claim_digest(tier.claims, limit=2),
                }
                for tier in pricing.tiers[:4]
            ],
            "notes": self._writer_claim_digest(pricing.notes, limit=3),
        }

    def _writer_feature_claim_digest(self, knowledge: object | None) -> list[dict[str, object]]:
        if knowledge is None or not hasattr(knowledge, "feature_tree"):
            return []
        claims = list(knowledge.feature_tree.summary_claims)
        for node in knowledge.feature_tree.nodes[:4]:
            claims.extend(node.claims[:2])
        return self._writer_claim_digest(claims, limit=8)

    def _writer_feature_tree_digest(self, knowledge: object | None) -> list[dict[str, object]]:
        if knowledge is None or not hasattr(knowledge, "feature_tree"):
            return []
        nodes = list(knowledge.feature_tree.nodes)
        return [
            {
                "name": self._trim_sentence(node.name, 80),
                "description": self._trim_sentence(node.description, 160),
                "source_ids": self._feature_node_source_ids(node)[:4],
                "claim_count": len(node.claims),
                "child_count": len(node.children),
            }
            for node in nodes[:8]
        ]

    def _writer_persona_claim_digest(self, knowledge: object | None) -> list[dict[str, object]]:
        if knowledge is None or not hasattr(knowledge, "user_personas"):
            return []
        claims = list(knowledge.user_personas.summary_claims)
        for segment in knowledge.user_personas.segments[:4]:
            claims.extend(segment.claims[:2])
        return self._writer_claim_digest(claims, limit=8)

    def _writer_claim_digest(
        self,
        claims: list[KnowledgeClaim],
        *,
        limit: int,
    ) -> list[dict[str, object]]:
        return [
            {
                "claim": self._trim_sentence(claim.claim, 180),
                "source_ids": claim.source_ids[:4],
                "confidence": round(claim.confidence, 3),
            }
            for claim in claims[:limit]
        ]

    def _writer_matrix_digest(self, detail: RunDetail) -> dict[str, object]:
        if detail.comparison_matrix is None:
            return {"winner_by_dimension": {}, "summary": [], "cells": []}
        return {
            "winner_by_dimension": detail.comparison_matrix.winner_by_dimension,
            "summary": [
                self._writer_matrix_summary_item(item)
                for item in detail.comparison_matrix.summary[:6]
            ],
            "cells": [
                {
                    "competitor": cell.competitor,
                    "dimension": cell.dimension,
                    "value": self._writer_matrix_cell_value(cell),
                    "source_ids": cell.source_ids[:4],
                    "confidence": round(cell.confidence, 3),
                }
                for cell in detail.comparison_matrix.cells[:32]
            ],
        }

    def _writer_matrix_summary_item(self, item: str) -> str:
        long_summary = item.startswith(
            ("[feature-standardization:", "[pricing-standardization:")
        )
        limit = 1200 if long_summary else 180
        return self._trim_sentence(item, limit)

    def _writer_matrix_cell_value(self, cell: object) -> str:
        dimension = str(getattr(cell, "dimension", "")).casefold()
        limit = 1200 if "feature" in dimension or "pricing" in dimension else 180
        return self._trim_sentence(str(getattr(cell, "value", "")), limit)

    def _feature_node_source_ids(self, node: FeatureNode) -> list[str]:
        source_ids: list[str] = []
        seen: set[str] = set()
        claims = [*node.claims, *self._feature_child_claims(node)]
        for claim in claims:
            for source_id in claim.source_ids:
                if source_id not in seen:
                    seen.add(source_id)
                    source_ids.append(source_id)
        return source_ids

    def _writer_issue_digest(self, issue: QCIssue) -> dict[str, object]:
        return {
            "id": issue.id,
            "severity": issue.severity,
            "target_agent": issue.target_agent,
            "target_subagent": issue.target_subagent,
            "target_competitor": issue.target_competitor,
            "problem": self._trim_sentence(issue.problem, 180),
        }

    def _matrix_source_ids(self, detail: RunDetail) -> list[str]:
        if detail.comparison_matrix is None:
            return [source.id for source in detail.raw_sources[:3]]
        source_ids: list[str] = []
        seen: set[str] = set()
        for cell in detail.comparison_matrix.cells:
            for source_id in cell.source_ids:
                if source_id not in seen:
                    seen.add(source_id)
                    source_ids.append(source_id)
                if len(source_ids) >= 6:
                    return source_ids
        return source_ids

    def _format_source_refs(self, source_ids: Iterable[str]) -> str:
        unique = []
        seen: set[str] = set()
        for source_id in source_ids:
            if source_id and source_id not in seen:
                unique.append(source_id)
                seen.add(source_id)
            if len(unique) >= 4:
                break
        if not unique:
            return ""
        return " " + " ".join(f"[source:{source_id}]" for source_id in unique)

    def _fallback_memory_context_section(self, detail: RunDetail) -> list[str]:
        if not detail.plan.memory_prompt_context:
            return []
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        candidate_ids = ", ".join(detail.plan.memory_candidate_ids) or ("无" if is_zh else "none")
        if is_zh:
            lines = [
                "",
                f"## {report_label(detail.output_language, 'memory_context')}",
                (
                    "已确认的 MemoryAgent 指导被用作规划和写作上下文；"
                    "任何被记住的领域事实在发布前仍需要当前的证据支持。"
                ),
                f"- 候选 ID：{candidate_ids}",
                f"- 召回得分：{detail.plan.memory_recall_score}/100",
            ]
        else:
            lines = [
                "",
                f"## {report_label(detail.output_language, 'memory_context')}",
                (
                    "Confirmed MemoryAgent guidance was used as planning and writing context; "
                    "any remembered domain fact still needs current evidence before publication."
                ),
                f"- Candidate IDs: {candidate_ids}",
                f"- Recall score: {detail.plan.memory_recall_score}/100",
            ]
        lines.extend(
            f"- {self._memory_context_label(item, is_zh=is_zh)}: {item}"
            for item in detail.plan.memory_prompt_context[:6]
        )
        return lines

    def _memory_context_label(self, item: str, *, is_zh: bool = False) -> str:
        normalized = item.casefold()
        if normalized.startswith("[domain fact") or "domain fact" in normalized:
            return "领域事实" if is_zh else "Domain fact"
        if normalized.startswith("[qa policy") or "qa policy" in normalized:
            return "QA策略" if is_zh else "QA policy"
        if normalized.startswith("[failure pattern") or "failure pattern" in normalized:
            return "失败模式" if is_zh else "Failure pattern"
        return "指导" if is_zh else "Guidance"

    def _fallback_user_research_section(self, detail: RunDetail) -> list[str]:
        research_sources = [
            source
            for source in detail.raw_sources
            if source.source_type in USER_RESEARCH_SOURCE_TYPES
        ]
        persona_requested = any(
            dimension.casefold().replace("-", "_") in {"persona", "user", "review"}
            for dimension in detail.plan.dimensions
        )
        if not research_sources and not persona_requested:
            return []
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        if is_zh:
            lines = [
                "",
                f"## {report_label(detail.output_language, 'user_research_evidence')}",
                (
                    "调查问卷、访谈和手动笔记输入被视为方向性的买家或用户信号，而非官方的事实证明。"
                ),
            ]
            if not research_sources:
                lines.append(
                    "- 已请求用户画像或评论分析，但尚未附加用户研究来源；将画像结论保持在证据差距通道中。"
                    f"{self._format_source_refs(self._matrix_source_ids(detail))}"
                )
                return lines
            for source in research_sources[:5]:
                lines.append(
                    f"- {source.title} / {source.source_type} / 置信度 {source.confidence:.2f}"
                    f" [source:{source.id}]"
                )
        else:
            lines = [
                "",
                f"## {report_label(detail.output_language, 'user_research_evidence')}",
                (
                    "Survey, interview, and manual-note inputs are treated as directional "
                    "buyer or user signals, not as official factual proof."
                ),
            ]
            if not research_sources:
                lines.append(
                    "- Persona or review analysis was requested, but no user-research source "
                    "is attached yet; keep persona conclusions in the evidence-gap lane."
                    f"{self._format_source_refs(self._matrix_source_ids(detail))}"
                )
                return lines
            for source in research_sources[:5]:
                lines.append(
                    f"- {source.title} / {source.source_type} / confidence {source.confidence:.2f}"
                    f" [source:{source.id}]"
                )
        return lines

    def _fallback_rag_gap_fill_section(self, detail: RunDetail) -> list[str]:
        collector_gaps = [
            issue
            for issue in detail.qa_findings
            if issue.target_agent == "collector" and issue.severity in {"warn", "blocker"}
        ]
        if not collector_gaps:
            return []
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        if is_zh:
            lines = [
                "",
                f"## {report_label(detail.output_language, 'rag_gap_fill')}",
                (
                    "在报告发布或用作最终决策产物之前，应通过检索来填补收集器证据差距。"
                ),
            ]
            for issue in collector_gaps[:5]:
                scope = issue.redo_scope
                target = scope.target_subagent or issue.target_subagent or issue.field_path
                competitor = scope.target_competitor or issue.target_competitor or "所有竞品"
                query = self._gap_fill_query(detail, issue)
                sources = self._format_source_refs(self._matrix_source_ids(detail))
                lines.append(
                    f"- 差距 `{issue.id}`：{issue.problem} 目标={target}；"
                    f"竞品={competitor}；重新执行={scope.kind}。"
                    f"建议的检索查询：{query}。{sources}"
                )
            lines.append(
                "- 运行“证据差距填补”操作以检索、重排并附加已证实的证据。生成的草案版本应链接已填补的差距 ID 和检索上下文。"
            )
        else:
            lines = [
                "",
                f"## {report_label(detail.output_language, 'rag_gap_fill')}",
                (
                    "Collector evidence gaps should be closed through retrieval before this "
                    "report is published or used as a final decision artifact."
                ),
            ]
            for issue in collector_gaps[:5]:
                scope = issue.redo_scope
                target = scope.target_subagent or issue.target_subagent or issue.field_path
                competitor = scope.target_competitor or issue.target_competitor or "all competitors"
                query = self._gap_fill_query(detail, issue)
                sources = self._format_source_refs(self._matrix_source_ids(detail))
                lines.append(
                    f"- Gap `{issue.id}`: {issue.problem} Target={target}; "
                    f"competitor={competitor}; redo={scope.kind}. "
                    f"Suggested retrieval query: {query}.{sources}"
                )
            lines.append(
                "- Run the Evidence Gap Fill action to retrieve, rerank, and attach verified "
                "evidence. The resulting draft version should link filled gap IDs and "
                "retrieval contexts."
            )
        return lines

    def _gap_fill_query(self, detail: RunDetail, issue: QCIssue) -> str:
        dimension = issue.target_subagent or "evidence"
        competitor = (
            issue.target_competitor
            or ", ".join(detail.plan.competitors[:3])
            or detail.topic
        )
        query = f"{competitor} {dimension} {issue.problem}".strip()
        return " ".join(query.split())[:180]

    def _fallback_claim_validation_section(self, detail: RunDetail) -> list[str]:
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        lines = ["", f"## {report_label(detail.output_language, 'claim_risk')}"]
        source_by_id = {source.id: source for source in detail.raw_sources}
        claims = self._knowledge_claims(detail)
        issue_counts = {
            "blocker": sum(1 for issue in detail.qa_findings if issue.severity == "blocker"),
            "warn": sum(1 for issue in detail.qa_findings if issue.severity == "warn"),
            "info": sum(1 for issue in detail.qa_findings if issue.severity == "info"),
        }
        if is_zh:
            lines.append(
                "- QA 状态："
                f"{issue_counts['blocker']} 个阻碍型，{issue_counts['warn']} 个警告型，"
                f"{issue_counts['info']} 个信息型发现，存在于 {len(claims)} 个结构化声明中。"
                f"{self._format_source_refs(self._matrix_source_ids(detail))}"
            )
        else:
            lines.append(
                "- QA status: "
                f"{issue_counts['blocker']} blocker(s), {issue_counts['warn']} warning(s), "
                f"{issue_counts['info']} info finding(s) across {len(claims)} structured claim(s)."
                f"{self._format_source_refs(self._matrix_source_ids(detail))}"
            )

        weak_claims = [
            claim
            for claim in claims
            if claim.confidence < 0.65
            or self._claim_has_weak_sources(claim.source_ids, source_by_id)
            or self._claim_needs_triangulation(claim.claim, claim.source_ids)
        ]
        if weak_claims:
            for claim in weak_claims[:5]:
                labels = []
                if claim.confidence < 0.65:
                    labels.append(f"置信度 {claim.confidence:.2f}" if is_zh else f"confidence {claim.confidence:.2f}")
                if self._claim_has_weak_sources(claim.source_ids, source_by_id):
                    labels.append("弱来源组合" if is_zh else "weak source mix")
                if self._claim_needs_triangulation(claim.claim, claim.source_ids):
                    labels.append("需要交叉验证" if is_zh else "needs triangulation")
                if is_zh:
                    lines.append(
                        f"- 审查声明 ({', '.join(labels)})：{self._trim_sentence(claim.claim)}"
                        f"{self._format_source_refs(claim.source_ids)}"
                    )
                else:
                    lines.append(
                        f"- Review claim ({', '.join(labels)}): {self._trim_sentence(claim.claim)}"
                        f"{self._format_source_refs(claim.source_ids)}"
                    )
        else:
            if is_zh:
                lines.append(
                    "- 未检测到低置信度或单来源的高风险结构化声明。"
                    f"{self._format_source_refs(self._matrix_source_ids(detail))}"
                )
            else:
                lines.append(
                    "- No low-confidence or single-source high-risk structured claims were detected."
                    f"{self._format_source_refs(self._matrix_source_ids(detail))}"
                )

        for issue in detail.qa_findings[:4]:
            if is_zh:
                lines.append(
                    f"- QA {issue.severity} `{issue.id}`："
                    f"{self._trim_sentence(issue.problem)}"
                )
            else:
                lines.append(
                    f"- QA {issue.severity} `{issue.id}`: "
                    f"{self._trim_sentence(issue.problem)}"
                )

        reflection_gaps = self._reflection_gap_notes(detail)
        for note in reflection_gaps[:4]:
            if is_zh:
                lines.append(
                    f"- 证据差距：{self._trim_sentence(note)}"
                    f"{self._format_source_refs(self._matrix_source_ids(detail))}"
                )
            else:
                lines.append(
                    f"- Evidence gap: {self._trim_sentence(note)}"
                    f"{self._format_source_refs(self._matrix_source_ids(detail))}"
                )
        return lines

    def _knowledge_claims(self, detail: RunDetail) -> list[KnowledgeClaim]:
        claims = []
        for knowledge in detail.competitor_knowledge.values():
            for node in knowledge.feature_tree.nodes:
                claims.extend(node.claims)
                claims.extend(self._feature_child_claims(node))
            claims.extend(knowledge.feature_tree.summary_claims)
            for tier in knowledge.pricing_model.tiers:
                claims.extend(tier.claims)
            claims.extend(knowledge.pricing_model.notes)
            for segment in knowledge.user_personas.segments:
                claims.extend(segment.claims)
            claims.extend(knowledge.user_personas.summary_claims)
        return claims

    def _feature_child_claims(self, node: FeatureNode) -> list[KnowledgeClaim]:
        claims = []
        for child in node.children:
            claims.extend(child.claims)
            claims.extend(self._feature_child_claims(child))
        return claims

    def _claim_has_weak_sources(
        self, source_ids: list[str], source_by_id: dict[str, RawSource]
    ) -> bool:
        if not source_ids:
            return True
        sources = [source_by_id[source_id] for source_id in source_ids if source_id in source_by_id]
        if not sources:
            return True
        weak_types = {"web_search_result", "llm_public_knowledge"}
        return all(
            source.source_type in weak_types or source.confidence < 0.75
            for source in sources
        )

    def _claim_needs_triangulation(self, claim: str, source_ids: list[str]) -> bool:
        if len(set(source_ids)) >= 2:
            return False
        return bool(
            re.search(
                r"\b(best|better|leader|recommended|safest|cheapest|fastest|"
                r"enterprise-ready|soc\s*2|sso|saml|security|compliance)\b",
                claim,
                flags=re.IGNORECASE,
            )
        )

    def _reflection_gap_notes(self, detail: RunDetail) -> list[str]:
        if not detail.reflections:
            return []
        latest = detail.reflections[-1]
        return [
            *latest.coverage_gaps,
            *latest.confidence_outliers,
            *latest.cross_competitor_gaps,
        ]

    def _trim_sentence(self, value: str, limit: int = 220) -> str:
        text = " ".join(value.split())
        if len(text) <= limit:
            return text
        return f"{text[: limit - 1].rstrip()}..."

    def _extract_cited_source_ids(self, report_md: str) -> set[str]:
        patterns = [
            r"\bsource(?:\s+id)?\s*:\s*([A-Za-z0-9_.:-]+)",
            r"\[source(?:\s+id)?\s+([A-Za-z0-9_.:-]+)\]",
        ]
        cited: set[str] = set()
        for pattern in patterns:
            cited.update(re.findall(pattern, report_md, flags=re.IGNORECASE))
        return cited

    def _repair_report_source_tokens(self, detail: RunDetail, markdown: str) -> str:
        valid_source_ids = {source.id for source in detail.raw_sources}
        if not valid_source_ids:
            return markdown

        repaired_lines: list[str] = []
        for line in markdown.splitlines():
            repaired_lines.append(
                re.sub(
                    r"\[source:([A-Za-z0-9_.:#-]+)\]",
                    lambda match, current_line=line: self._repair_report_source_token(
                        detail,
                        current_line,
                        match.group(1),
                        valid_source_ids,
                    ),
                    line,
                )
            )
        return "\n".join(repaired_lines)

    def _repair_report_source_token(
        self,
        detail: RunDetail,
        line: str,
        token: str,
        valid_source_ids: set[str],
    ) -> str:
        source_id = token.split("#", 1)[0]
        if source_id in valid_source_ids:
            return f"[source:{token}]"

        dimension_match = [
            source.id
            for source in detail.raw_sources
            if source.dimension.casefold() == source_id.casefold()
        ]
        replacement_ids = dimension_match or self._source_ids_for_report_line(detail, line)
        if not replacement_ids:
            return f"[source:{token}]"
        return f"[source:{replacement_ids[0]}]"

    def _ensure_report_claim_citations(self, detail: RunDetail, markdown: str) -> str:
        hardened_lines: list[str] = []
        for line in markdown.splitlines():
            if not self._report_line_needs_citation(line):
                hardened_lines.append(line)
                continue
            if self._extract_cited_source_ids(line):
                hardened_lines.append(line)
                continue
            source_ids = self._source_ids_for_report_line(detail, line)
            if not source_ids:
                hardened_lines.append(line)
                continue
            citation_text = " ".join(f"[source:{source_id}]" for source_id in source_ids[:2])
            stripped = line.rstrip()
            if stripped.startswith("|") and stripped.endswith("|"):
                hardened_lines.append(f"{stripped[:-1].rstrip()} {citation_text} |")
            else:
                hardened_lines.append(f"{stripped} {citation_text}")
        return "\n".join(hardened_lines)

    def _report_line_needs_citation(self, line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return False
        if stripped.startswith("#"):
            return False
        if set(stripped) <= {"-", " ", "|", ":"}:
            return False
        if re.fullmatch(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?", stripped):
            return False
        return bool(re.search(r"[A-Za-z0-9]", stripped)) and len(stripped) >= 24

    def _source_ids_for_report_line(self, detail: RunDetail, line: str) -> list[str]:
        normalized = line.casefold()
        matched_competitors = [
            competitor
            for competitor in detail.plan.competitors
            if competitor.casefold() in normalized
        ]
        matched_dimensions = [
            dimension
            for dimension in detail.plan.dimensions
            if dimension.casefold() in normalized
            or (
                dimension == "pricing"
                and any(token in normalized for token in ("price", "pricing", "cost", "$"))
            )
            or (
                dimension == "feature"
                and any(token in normalized for token in ("feature", "capability", "function"))
            )
            or (
                dimension == "persona"
                and any(
                    token in normalized
                    for token in ("persona", "customer", "user", "buyer", "use case")
                )
            )
        ]

        def unique(ids: list[str]) -> list[str]:
            seen: set[str] = set()
            return [
                source_id for source_id in ids if not (source_id in seen or seen.add(source_id))
            ]

        source_ids = [
            source.id
            for source in detail.raw_sources
            if (
                not matched_competitors
                or any(
                    self._source_matches_competitor(source, competitor)
                    for competitor in matched_competitors
                )
            )
            and (not matched_dimensions or source.dimension in matched_dimensions)
        ]
        if not source_ids and matched_competitors:
            source_ids = [
                source.id
                for source in detail.raw_sources
                if any(
                    self._source_matches_competitor(source, competitor)
                    for competitor in matched_competitors
                )
            ]
        if not source_ids and matched_dimensions:
            source_ids = [
                source.id for source in detail.raw_sources if source.dimension in matched_dimensions
            ]
        if not source_ids:
            source_ids = [source.id for source in detail.raw_sources]
        return unique(source_ids)
