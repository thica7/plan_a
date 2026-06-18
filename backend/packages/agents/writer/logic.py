from __future__ import annotations

import asyncio
import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import TYPE_CHECKING

from packages.agents.writer.assembler import assemble_report_sections
from packages.agents.writer.evidence_pack import (
    SEGMENT_INPUT_TARGET_CHARS,
    build_writer_evidence_pack,
)
from packages.agents.writer.quality_preflight import run_writer_quality_preflight
from packages.agents.writer.repair import (
    WriterRepairPlan,
    apply_line_repair,
    build_writer_repair_plan,
    replace_markdown_section,
    report_regression_problem,
    section_regression_problem,
)
from packages.agents.writer.segment_contract import (
    segment_contract_for,
    validate_segment_contract,
)
from packages.business_intel.release_gate import REPORT_RICHNESS_MINIMUMS
from packages.business_intel.report_quality import compare_run_quality
from packages.business_intel.scenarios import get_scenario_pack
from packages.i18n.language import (
    language_instruction,
    normalize_output_language,
    repair_mojibake_text,
    report_label,
)
from packages.identity.source_resolver import (
    SOURCE_TOKEN_RE,
    source_token_match_value,
    source_tokens,
)
from packages.rag.grounded_prompt import build_run_grounding_prompt
from packages.research.evidence.normalization import normalized_fields_from_source
from packages.research.evidence.text import source_business_snippet
from packages.schema.api_dto import RunDetail
from packages.schema.models import (
    ComparisonCell,
    FeatureNode,
    KnowledgeClaim,
    QCIssue,
    RawSource,
    SWOTItem,
)

if TYPE_CHECKING:
    from packages.orchestrator.service import RunRecord


USER_RESEARCH_SOURCE_TYPE_ORDER = (
    "survey_simulated",
    "survey_response",
    "interview_record",
    "manual_transcript",
    "manual_user_note",
    "manual_note",
    "manual",
)
USER_RESEARCH_SOURCE_TYPES = set(USER_RESEARCH_SOURCE_TYPE_ORDER)
CJK_TEXT_RE = re.compile(r"[\u3400-\u9fff]")
PRICING_LINE_TOKENS = (
    "price",
    "pricing",
    "cost",
    "$",
    "定价",
    "价格",
    "费用",
    "套餐",
    "月费",
    "席位",
    "报价",
)
FEATURE_LINE_TOKENS = (
    "feature",
    "capability",
    "function",
    "功能",
    "特征",
    "能力",
    "代码补全",
    "代理",
    "上下文",
)
PERSONA_LINE_TOKENS = (
    "persona",
    "customer",
    "user",
    "buyer",
    "use case",
    "用户",
    "用户画像",
    "买家",
    "采购",
    "客户",
    "访谈",
    "调查",
    "评价",
    "评论",
    "采纳",
    "采用",
    "切换",
    "痛点",
    "阻力",
)
CLAIM_LINE_TOKENS = PRICING_LINE_TOKENS + FEATURE_LINE_TOKENS + PERSONA_LINE_TOKENS
WRITER_NORMALIZED_FIELD_DROP_KEYS = {
    "content",
    "extracted_text",
    "full_text",
    "html",
    "markdown",
    "page_content",
    "raw",
    "raw_html",
    "raw_markdown",
    "raw_text",
    "text",
}
WRITER_NORMALIZED_FIELD_QUOTE_KEY_PARTS = (
    "evidence",
    "excerpt",
    "quote",
)
WRITER_NORMALIZED_FIELD_LONG_KEY_PARTS = (
    "blocker",
    "claim",
    "description",
    "note",
    "pain",
    "rationale",
    "reason",
    "summary",
    "trigger",
)
WRITER_NORMALIZED_SNIPPET_LIMIT = 1600


def writer_user_research_policy_text() -> str:
    source_types = ", ".join(USER_RESEARCH_SOURCE_TYPE_ORDER)
    return (
        f"Treat {source_types} as user-research signals, not as official factual proof."
    )


def _assemble_repair_quality_gate(
    detail: RunDetail,
    markdown: str,
) -> dict[str, object]:
    candidate = detail.model_copy(update={"report_md": markdown})
    comparison = compare_run_quality(candidate)
    metric_by_name = {metric.name: metric.target_value for metric in comparison.metrics}
    quality_gate_metrics = {
        name: float(metric_by_name.get(name) or 0.0)
        for name in REPORT_RICHNESS_MINIMUMS
    }
    reasons = [
        name
        for name, minimum in REPORT_RICHNESS_MINIMUMS.items()
        if quality_gate_metrics[name] < minimum
    ]
    return {
        "quality_gate_passed": not reasons,
        "quality_gate_reasons": reasons,
        "quality_gate_metrics": quality_gate_metrics,
        **quality_gate_metrics,
    }


class WriterEvidencePreflightError(RuntimeError):
    """Raised when writer evidence cannot safely be sent to the LLM."""


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
        redo_messages = []
        for to_agent in ("writer", "writer_only"):
            redo_messages.extend(
                self._consume_queued_agent_messages(
                    record,
                    to_agent=to_agent,
                    consumer_agent="writer",
                    message_types={"redo_request"},
                )
            )
        await self.emit(detail.id, "node_started", "writer", None, "Calling report writer.")
        previous_report = detail.report_md
        writer_mode = "real LLM call"
        writer_error: str | None = None
        writer_repair_mode = "none"
        writer_repair_sections: list[str] = []
        writer_repair_decision = ""
        anti_regression_reason: str | None = None
        previous_report_protected = False
        redo_issue_by_id: dict[str, QCIssue] = {}
        for message in redo_messages:
            for item in message.payload.get("issues", []):
                issue = QCIssue.model_validate(item)
                redo_issue_by_id.setdefault(issue.id, issue)
        pending_redo = record.pending_graph_redo
        pending_issue_ids: set[str] = set()
        writer_only_pending_issue_ids: set[str] = set()
        if pending_redo is not None and pending_redo.issue_ids:
            pending_issue_ids = set(pending_redo.issue_ids)
            for issue in detail.qa_findings:
                if issue.id in pending_issue_ids:
                    redo_issue_by_id.setdefault(issue.id, issue)
            for message in record.detail.agent_messages:
                if message.message_type != "redo_request":
                    continue
                raw_issue_ids = message.payload.get("issue_ids", [])
                if not raw_issue_ids or not (set(raw_issue_ids) & pending_issue_ids):
                    continue
                for item in message.payload.get("issues", []):
                    issue = QCIssue.model_validate(item)
                    if issue.id in pending_issue_ids:
                        redo_issue_by_id.setdefault(issue.id, issue)
            if pending_redo.redo_scope.kind == "writer_only":
                writer_only_pending_issue_ids = pending_issue_ids
        redo_issues = list(redo_issue_by_id.values())
        redo_source_message_ids = [message.id for message in redo_messages]
        if writer_only_pending_issue_ids:
            writer_only_messages_without_issue_ids: list[str] = []
            for message in record.detail.agent_messages:
                if message.message_type != "redo_request":
                    continue
                raw_issue_ids = message.payload.get("issue_ids", [])
                if raw_issue_ids:
                    message_issue_ids = set(raw_issue_ids)
                    if message_issue_ids & writer_only_pending_issue_ids:
                        redo_source_message_ids.append(message.id)
                    continue
                redo_scope = message.payload.get("redo_scope", {})
                redo_scope_kind = (
                    redo_scope.get("kind") if isinstance(redo_scope, dict) else None
                )
                if redo_scope_kind == "writer_only":
                    writer_only_messages_without_issue_ids.append(message.id)
            if len(writer_only_messages_without_issue_ids) == 1:
                redo_source_message_ids.append(writer_only_messages_without_issue_ids[0])
        redo_source_message_ids = list(dict.fromkeys(redo_source_message_ids))
        upstream_redo_stages = {"collector", "analyst", "comparator", "full"}
        upstream_data_changed = (
            pending_redo is not None
            and (
                pending_redo.stage in upstream_redo_stages
                or pending_redo.redo_scope.kind in upstream_redo_stages
            )
        )
        if redo_issues or upstream_data_changed:
            repair_plan = build_writer_repair_plan(
                detail,
                redo_issues,
                upstream_data_changed=upstream_data_changed,
            )
        else:
            repair_plan = None
        timeout_seconds = max(0.05, float(self._settings.writer_timeout_seconds))
        assemble_repair_succeeded = False
        if repair_plan is not None and repair_plan.mode == "assemble":
            writer_repair_mode = repair_plan.mode
            writer_repair_sections = repair_plan.sections
            writer_repair_decision = repair_plan.reason
            previous_report_protected = repair_plan.previous_report_protectable
            assembled = assemble_report_sections(
                [previous_report],
                output_language=detail.output_language,
                competitors=detail.plan.competitors,
            )
            preflight = run_writer_quality_preflight(detail, assembled.markdown)
            quality_gate = _assemble_repair_quality_gate(detail, assembled.markdown)
            await self.emit(
                detail.id,
                "writer_assemble_repair_completed",
                "writer",
                None,
                "Writer assembler repair completed",
                {
                    **assembled.telemetry,
                    "quality_preflight": preflight.telemetry_payload(),
                    **quality_gate,
                },
            )
            if preflight.passed and quality_gate["quality_gate_passed"]:
                detail.report_md = self._harden_report_markdown(
                    detail,
                    assembled.markdown,
                )
                writer_mode = "writer repair: assemble"
                assemble_repair_succeeded = True
            else:
                repair_plan = WriterRepairPlan(
                    mode="full",
                    reason=(
                        "assembler repair did not pass writer quality preflight "
                        "or depth gate"
                    ),
                    previous_report_protectable=True,
                    anti_regression_required=True,
                )
        if (
            not assemble_repair_succeeded
            and repair_plan is not None
            and repair_plan.mode == "line"
        ):
            writer_repair_mode = repair_plan.mode
            writer_repair_sections = repair_plan.sections
            writer_repair_decision = repair_plan.reason
            previous_report_protected = repair_plan.previous_report_protectable
            detail.report_md = self._harden_report_markdown(
                detail,
                apply_line_repair(previous_report, redo_issues),
            )
            writer_mode = "writer repair: line"
        elif (
            not assemble_repair_succeeded
            and repair_plan is not None
            and repair_plan.mode == "section"
        ):
            writer_repair_mode = repair_plan.mode
            writer_repair_sections = repair_plan.sections
            writer_repair_decision = repair_plan.reason
            previous_report_protected = repair_plan.previous_report_protectable
            try:
                report_md = previous_report
                for section in repair_plan.sections:
                    section_md = await asyncio.wait_for(
                        self._writer_section_repair_markdown(
                            record,
                            sections=[section],
                            previous_report=previous_report,
                        ),
                        timeout=timeout_seconds,
                    )
                    self._require_writer_report_output(section_md)
                    report_md = replace_markdown_section(
                        report_md,
                        section,
                        detail.output_language,
                        section_md,
                    )
                hardened_report = self._harden_report_markdown(detail, report_md)
                if repair_plan.anti_regression_required:
                    repair_comparison_metrics = detail.metrics.model_copy(
                        update={
                            "llm_calls": max(detail.metrics.llm_calls, 1),
                            "source_coverage_rate": max(
                                detail.metrics.source_coverage_rate, 1.0
                            ),
                            "claim_citation_rate": max(
                                detail.metrics.claim_citation_rate, 1.0
                            ),
                        }
                    )
                    previous_detail = detail.model_copy(
                        update={
                            "report_md": previous_report,
                            "qa_findings": [],
                            "metrics": repair_comparison_metrics,
                        }
                    )
                    candidate_detail = detail.model_copy(
                        update={
                            "report_md": hardened_report,
                            "qa_findings": [],
                            "metrics": repair_comparison_metrics,
                        }
                    )
                    anti_regression_reason = section_regression_problem(
                        previous_detail,
                        candidate_detail,
                        protected_sections=repair_plan.sections,
                    )
                if anti_regression_reason:
                    detail.report_md = self._preserve_hardened_previous_report(
                        detail,
                        previous_report,
                    )
                    writer_mode = "preserved previous report after writer anti-regression"
                else:
                    detail.report_md = hardened_report
                    writer_mode = "writer repair: section"
            except WriterEvidencePreflightError as exc:
                writer_error = str(exc)
                await self._fail_writer_without_report(
                    record,
                    writer_error,
                    writer_repair_mode=writer_repair_mode,
                    writer_repair_sections=writer_repair_sections,
                    writer_repair_decision=writer_repair_decision,
                    anti_regression_reason=anti_regression_reason,
                    previous_report_protected=previous_report_protected,
                )
            except TimeoutError as exc:
                timeout_reason = str(exc) or f"writer LLM exceeded {timeout_seconds:g}s"
                writer_error = timeout_reason
                if previous_report.strip():
                    detail.report_md = self._preserve_hardened_previous_report(
                        detail,
                        previous_report,
                    )
                    writer_mode = "preserved previous report after writer error"
                else:
                    await self._fail_writer_without_report(
                        record,
                        writer_error,
                        writer_repair_mode=writer_repair_mode,
                        writer_repair_sections=writer_repair_sections,
                        writer_repair_decision=writer_repair_decision,
                        anti_regression_reason=anti_regression_reason,
                        previous_report_protected=previous_report_protected,
                    )
            except Exception as exc:  # noqa: BLE001 - preserve existing reports, fail otherwise.
                writer_error = str(exc)
                if previous_report.strip():
                    detail.report_md = self._preserve_hardened_previous_report(
                        detail,
                        previous_report,
                    )
                    writer_mode = "preserved previous report after writer error"
                else:
                    await self._fail_writer_without_report(
                        record,
                        writer_error,
                        writer_repair_mode=writer_repair_mode,
                        writer_repair_sections=writer_repair_sections,
                        writer_repair_decision=writer_repair_decision,
                        anti_regression_reason=anti_regression_reason,
                        previous_report_protected=previous_report_protected,
                    )
        elif not assemble_repair_succeeded:
            if repair_plan is not None and repair_plan.mode == "full":
                writer_repair_mode = repair_plan.mode
                writer_repair_sections = repair_plan.sections
                writer_repair_decision = repair_plan.reason
                previous_report_protected = repair_plan.previous_report_protectable
            evidence_pack_result = build_writer_evidence_pack(detail)
            await self.emit(
                detail.id,
                "writer_preflight",
                "writer",
                None,
                "Writer evidence pack prepared.",
                evidence_pack_result.telemetry_payload(),
            )
            preflight_errors = evidence_pack_result.preflight_errors()
            if preflight_errors:
                await self._fail_writer_without_report(
                    record,
                    "writer evidence pack preflight failed: "
                    + ", ".join(preflight_errors),
                    writer_repair_mode=writer_repair_mode,
                    writer_repair_sections=writer_repair_sections,
                    writer_repair_decision=writer_repair_decision,
                    anti_regression_reason=anti_regression_reason,
                    previous_report_protected=previous_report_protected,
                )
            layer_context = self._writer_layer_context(detail)
            memory_context = "\n".join(detail.plan.memory_prompt_context) or "none"
            required_sections = self._writer_required_sections(detail)
            grounding_prompt = await self._writer_grounding_prompt(detail)
            user_research_policy = writer_user_research_policy_text()
            language_guidance = language_instruction(detail.output_language)
            try:
                if evidence_pack_result.metrics.segmented_writer_required:
                    report_md = await self._writer_segmented_report_markdown(
                        record,
                        evidence_pack_result=evidence_pack_result,
                        timeout_seconds=timeout_seconds,
                        language_guidance=language_guidance,
                        memory_context=memory_context,
                        layer_context=layer_context,
                        required_sections=required_sections,
                    )
                    writer_mode = "real segmented LLM call"
                else:
                    writer_context_json = evidence_pack_result.to_prompt_json()
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
                                "tentative and list the exact evidence gap. Do not claim all sources "
                                "are verified when any source_type is web_search_result or "
                                "llm_public_knowledge. "
                                "Follow the Grounded Evidence Contract exactly. "
                                f"{language_guidance} "
                                f"{user_research_policy} "
                                "Honor confirmed memory guidance when it does not conflict with "
                                "evidence, schema requirements, or compliance policy. "
                                "Use the requested competitive layer to choose the report shape: L1 "
                                "is a direct battlecard, L2 is adjacent workflow and enterprise-risk "
                                "analysis, and L3 is market landscape and category strategy."
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
                                f"{self._writer_community_policy_text()}\n"
                                f"Writer Evidence Pack JSON: {writer_context_json}\n\n"
                                f"Required sections:\n{required_sections}\n"
                                "Target 16,000-20,000 characters for the first draft. Use about "
                                "70-80% of the report on the Core analysis layer: decision summary, "
                                "competitive findings, user review themes, competitor deep dives, "
                                "SWOT, matrix interpretation, and layer-specific implications. "
                                "Core section minimums: Decision Summary 800+ characters; "
                                "Competitive Findings 1,200+; User Review Themes 1,000+ when "
                                "review, community, survey, interview, or persona evidence exists; "
                                "Competitor Deep Dives 1,400+ and every competitor covered; SWOT "
                                "1,400+ with explicit Strengths, Weaknesses, Opportunities, and "
                                "Threats for every competitor; Matrix Interpretation 900+; "
                                "Layer-specific Battlecard/Workflow/Market section 1,200+. Keep "
                                "the Support/audit layer concise and complete; it is the audit trail, "
                                "not the main readout. Prefer deeper cited analysis and decision "
                                "implications over repeated source IDs or QA boilerplate."
                            ),
                        ),
                        timeout=timeout_seconds,
                    )
                self._require_writer_report_output(report_md)
                hardened_report = self._harden_report_markdown(detail, report_md)
                if (
                    previous_report.strip()
                    and repair_plan is not None
                    and repair_plan.anti_regression_required
                ):
                    repair_comparison_metrics = detail.metrics.model_copy(
                        update={
                            "llm_calls": max(detail.metrics.llm_calls, 1),
                            "source_coverage_rate": max(
                                detail.metrics.source_coverage_rate, 1.0
                            ),
                            "claim_citation_rate": max(
                                detail.metrics.claim_citation_rate, 1.0
                            ),
                        }
                    )
                    previous_detail = detail.model_copy(
                        update={
                            "report_md": previous_report,
                            "qa_findings": [],
                            "metrics": repair_comparison_metrics,
                        }
                    )
                    candidate_detail = detail.model_copy(
                        update={
                            "report_md": hardened_report,
                            "qa_findings": [],
                            "metrics": repair_comparison_metrics,
                        }
                    )
                    protected_sections = repair_plan.sections or [
                        "review_theme_summary",
                        "swot_analysis",
                        "competitor_deep_dives",
                        self._layer_section_label_key(detail),
                    ]
                    anti_regression_reason = report_regression_problem(
                        previous_detail,
                        candidate_detail,
                        protected_sections=protected_sections,
                    )
                if anti_regression_reason:
                    detail.report_md = self._preserve_hardened_previous_report(
                        detail,
                        previous_report,
                    )
                    writer_mode = "preserved previous report after writer anti-regression"
                else:
                    detail.report_md = hardened_report
            except TimeoutError as exc:
                timeout_reason = str(exc) or f"writer LLM exceeded {timeout_seconds:g}s"
                writer_error = timeout_reason
                if previous_report.strip():
                    detail.report_md = self._preserve_hardened_previous_report(
                        detail,
                        previous_report,
                    )
                    writer_mode = "preserved previous report after writer error"
                else:
                    await self._fail_writer_without_report(
                        record,
                        writer_error,
                        writer_repair_mode=writer_repair_mode,
                        writer_repair_sections=writer_repair_sections,
                        writer_repair_decision=writer_repair_decision,
                        anti_regression_reason=anti_regression_reason,
                        previous_report_protected=previous_report_protected,
                    )
            except Exception as exc:  # noqa: BLE001 - preserve existing reports, fail otherwise.
                writer_error = str(exc)
                if previous_report.strip():
                    detail.report_md = self._preserve_hardened_previous_report(
                        detail,
                        previous_report,
                    )
                    writer_mode = "preserved previous report after writer error"
                else:
                    await self._fail_writer_without_report(
                        record,
                        writer_error,
                        writer_repair_mode=writer_repair_mode,
                        writer_repair_sections=writer_repair_sections,
                        writer_repair_decision=writer_repair_decision,
                        anti_regression_reason=anti_regression_reason,
                        previous_report_protected=previous_report_protected,
                    )
        repair_metadata = {
            "writer_repair_mode": writer_repair_mode,
            "writer_repair_sections": writer_repair_sections,
            "writer_repair_decision": writer_repair_decision,
            "anti_regression_reason": anti_regression_reason,
            "previous_report_protected": previous_report_protected,
        }
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
                **repair_metadata,
            },
            source_message_ids=redo_source_message_ids,
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
                **repair_metadata,
                **self._enterprise_projection_payload(projection),
            },
        )
        await self.emit(detail.id, "node_completed", "writer", None, "Writer completed.")

    async def _fail_writer_without_report(
        self,
        record: RunRecord,
        reason: str,
        *,
        writer_repair_mode: str,
        writer_repair_sections: Sequence[str],
        writer_repair_decision: str,
        anti_regression_reason: str | None,
        previous_report_protected: bool,
    ) -> None:
        detail = record.detail
        detail.status = "failed"
        detail.current_node = None
        detail.updated_at = datetime.utcnow()
        await self.emit(
            detail.id,
            "run_failed",
            "writer",
            None,
            f"Writer failed before report generation: {reason}",
            {
                "error": reason,
                "writer_repair_mode": writer_repair_mode,
                "writer_repair_sections": list(writer_repair_sections),
                "writer_repair_decision": writer_repair_decision,
                "anti_regression_reason": anti_regression_reason,
                "previous_report_protected": previous_report_protected,
            },
        )
        raise RuntimeError(f"Writer failed before report generation: {reason}")

    def _require_writer_report_output(self, report_md: str) -> None:
        if not report_md.strip():
            raise RuntimeError("Writer returned empty report content")

    async def _writer_segmented_report_markdown(
        self,
        record: RunRecord,
        *,
        evidence_pack_result,
        timeout_seconds: float,
        language_guidance: str,
        memory_context: str,
        layer_context: str,
        required_sections: str,
    ) -> str:
        detail = record.detail
        sections = await self._writer_segment_markdown_parts(
            record,
            evidence_pack_result=evidence_pack_result,
            segments=evidence_pack_result.segment_inputs(),
            timeout_seconds=timeout_seconds,
            language_guidance=language_guidance,
            memory_context=memory_context,
            layer_context=layer_context,
            required_sections=required_sections,
        )
        assembled = assemble_report_sections(
            sections,
            output_language=detail.output_language,
            competitors=detail.plan.competitors,
        )
        await self.emit(
            detail.id,
            "writer_assembly_completed",
            "writer",
            None,
            "Writer segmented report assembled",
            assembled.telemetry,
        )
        preflight = run_writer_quality_preflight(detail, assembled.markdown)
        await self.emit(
            detail.id,
            "writer_quality_preflight",
            "writer",
            None,
            "Writer assembled report quality preflight completed",
            preflight.telemetry_payload(),
        )
        if preflight.passed:
            return assembled.markdown

        hardened = self._harden_report_markdown(detail, assembled.markdown)
        repaired = assemble_report_sections(
            [hardened],
            output_language=detail.output_language,
            competitors=detail.plan.competitors,
        )
        repaired_preflight = run_writer_quality_preflight(detail, repaired.markdown)
        await self.emit(
            detail.id,
            "writer_quality_preflight_repair",
            "writer",
            None,
            "Writer assembled report quality preflight repair completed",
            {
                **repaired_preflight.telemetry_payload(),
                "initial_failure_reasons": list(preflight.failure_reasons),
                "repair_strategy": "harden_required_sections",
            },
        )
        if repaired_preflight.passed:
            return repaired.markdown

        raise RuntimeError(
            "Writer assembled report failed quality preflight: "
            f"{', '.join(repaired_preflight.failure_reasons)}"
        )

    async def _writer_segment_markdown_parts(
        self,
        record: RunRecord,
        *,
        evidence_pack_result,
        segments: Sequence[dict[str, object]],
        timeout_seconds: float,
        language_guidance: str,
        memory_context: str,
        layer_context: str,
        required_sections: str,
    ) -> list[str]:
        detail = record.detail
        sections: list[str] = []
        shards_by_section: dict[str, list[str]] = {}
        section_allowed_source_ids: dict[str, set[str]] = {}
        for segment in segments:
            segment_md, contract = await self._writer_validated_segment_markdown(
                record,
                evidence_pack_result=evidence_pack_result,
                segment=segment,
                timeout_seconds=timeout_seconds,
                language_guidance=language_guidance,
                memory_context=memory_context,
                layer_context=layer_context,
                required_sections=required_sections,
            )
            if contract.segment_kind == "evidence_shard":
                section_id = contract.section_id
                shards_by_section.setdefault(section_id, []).append(segment_md)
                section_allowed_source_ids.setdefault(section_id, set()).update(
                    source_id
                    for source_id in (segment.get("allowed_source_ids") or [])
                    if isinstance(source_id, str)
                )
                continue
            sections.append(segment_md)

        for section_id, shard_notes in shards_by_section.items():
            section_segment = self._writer_section_segment_from_shards(
                detail,
                section_id=section_id,
                shard_notes=shard_notes,
                allowed_source_ids=section_allowed_source_ids[section_id],
            )
            section_md, _ = await self._writer_validated_segment_markdown(
                record,
                evidence_pack_result=evidence_pack_result,
                segment=section_segment,
                timeout_seconds=timeout_seconds,
                language_guidance=language_guidance,
                memory_context=memory_context,
                layer_context=layer_context,
                required_sections=required_sections,
            )
            sections.append(section_md)
        return sections

    def _writer_section_segment_from_shards(
        self,
        detail: RunDetail,
        *,
        section_id: str,
        shard_notes: Sequence[str],
        allowed_source_ids: set[str],
    ) -> dict[str, object]:
        section_segment: dict[str, object] = {
            "segment_name": section_id,
            "segment_kind": "section_fragment",
            "section_id": section_id,
            "output_language": detail.output_language,
            "segment_input_chars": 0,
            "allowed_source_ids": sorted(allowed_source_ids),
            "groups": [],
            "sources": [],
            "shard_notes": list(shard_notes),
            "segment_batch": "from_evidence_shards",
        }
        self._refresh_segment_input_chars(section_segment)
        if section_segment["segment_input_chars"] > SEGMENT_INPUT_TARGET_CHARS:
            section_segment["segment_input_target_chars"] = SEGMENT_INPUT_TARGET_CHARS
            section_segment["segment_over_budget_reason"] = (
                "shard_notes_exceed_budget"
            )
            self._refresh_segment_input_chars(section_segment)
        return section_segment

    def _refresh_segment_input_chars(self, segment: dict[str, object]) -> None:
        segment["segment_input_chars"] = 0
        while True:
            segment_input_chars = len(json.dumps(segment, ensure_ascii=False))
            if segment["segment_input_chars"] == segment_input_chars:
                return
            segment["segment_input_chars"] = segment_input_chars

    async def _writer_validated_segment_markdown(
        self,
        record: RunRecord,
        *,
        evidence_pack_result,
        segment: dict[str, object],
        timeout_seconds: float,
        language_guidance: str,
        memory_context: str,
        layer_context: str,
        required_sections: str,
    ):
        detail = record.detail
        contract = segment_contract_for(segment)
        segment_with_contract = {
            **segment,
            "allowed_heading_keys": list(contract.allowed_heading_keys),
            "required_heading_keys": list(contract.required_heading_keys),
            "forbidden_heading_keys": list(contract.forbidden_heading_keys),
            "allowed_h2_headings": [
                report_label(detail.output_language, key)
                for key in contract.allowed_heading_keys
            ],
            "required_h2_headings": [
                report_label(detail.output_language, key)
                for key in contract.required_heading_keys
            ],
            "forbidden_h2_headings": [
                report_label(detail.output_language, key)
                for key in contract.forbidden_heading_keys
            ],
        }
        allowed_source_id_list = [
            source_id
            for source_id in (segment.get("allowed_source_ids") or [])
            if isinstance(source_id, str)
        ]
        groups = segment.get("groups") or []
        payload = {
            "segment_name": segment["segment_name"],
            "segment_kind": contract.segment_kind,
            "section_id": contract.section_id,
            "allowed_heading_keys": list(contract.allowed_heading_keys),
            "required_heading_keys": list(contract.required_heading_keys),
            "forbidden_heading_keys": list(contract.forbidden_heading_keys),
            "segment_essential": contract.essential,
            "segment_competitor": segment.get("segment_competitor"),
            "segment_dimension": segment.get("segment_dimension"),
            "segment_batch": segment.get("segment_batch"),
            "segment_over_budget_reason": segment.get("segment_over_budget_reason"),
            "segment_input_chars": segment.get("segment_input_chars", 0),
            "segment_input_target_chars": segment.get("segment_input_target_chars"),
            "segment_source_count": len(allowed_source_id_list),
            "segment_group_count": len(groups) if isinstance(groups, list) else 0,
            "segment_allowed_source_ids": allowed_source_id_list,
            "segment_retry_count": 0,
        }
        await self.emit(
            detail.id,
            "writer_segment_preflight",
            "writer",
            None,
            f"Writer segment prepared: {segment['segment_name']}",
            payload,
        )
        segment_md = await self._writer_segment_markdown(
            record,
            segment=segment_with_contract,
            timeout_seconds=timeout_seconds,
            language_guidance=language_guidance,
            memory_context=memory_context,
            layer_context=layer_context,
            required_sections=required_sections,
            retry_count=0,
        )
        allowed_source_ids = set(allowed_source_id_list)
        segment_md = self._sanitize_writer_segment_citations(
            evidence_pack_result,
            segment_md,
            allowed_source_ids=allowed_source_ids,
        )
        invalid_sources = evidence_pack_result.validate_segment_citations(
            segment_md,
            allowed_source_ids=allowed_source_ids,
        )
        if invalid_sources:
            segment_md = await self._writer_segment_markdown(
                record,
                segment=segment_with_contract,
                timeout_seconds=timeout_seconds,
                language_guidance=language_guidance,
                memory_context=memory_context,
                layer_context=layer_context,
                required_sections=required_sections,
                retry_count=1,
                citation_error_ids=invalid_sources,
            )
            segment_md = self._sanitize_writer_segment_citations(
                evidence_pack_result,
                segment_md,
                allowed_source_ids=allowed_source_ids,
            )
            invalid_sources = evidence_pack_result.validate_segment_citations(
                segment_md,
                allowed_source_ids=allowed_source_ids,
            )
        if invalid_sources:
            raise RuntimeError(
                "Writer segment cited invalid source IDs after retry: "
                f"{', '.join(invalid_sources)}"
            )
        validation = validate_segment_contract(segment_md, contract)
        await self.emit(
            detail.id,
            "writer_segment_validated",
            "writer",
            None,
            f"Writer segment validated: {segment['segment_name']}",
            {
                "segment_name": segment["segment_name"],
                "segment_kind": contract.segment_kind,
                "section_id": contract.section_id,
                "validation_status": validation.status,
                "validation_errors": list(validation.errors),
                "h2_headings": list(validation.h2_headings),
                "forbidden_headings": list(validation.forbidden_headings),
                "forbidden_heading_keys": list(validation.forbidden_heading_keys),
                "invalid_heading_keys": list(validation.invalid_heading_keys),
                "missing_required_heading_keys": list(
                    validation.missing_required_heading_keys
                ),
                "segment_retry_count": 0,
            },
        )
        if validation.status != "pass":
            contract_errors = validation.errors
            contract_forbidden_headings = validation.forbidden_headings
            contract_missing_required_heading_keys = (
                validation.missing_required_heading_keys
            )
            segment_md = await self._writer_segment_markdown(
                record,
                segment=segment_with_contract,
                timeout_seconds=timeout_seconds,
                language_guidance=language_guidance,
                memory_context=memory_context,
                layer_context=layer_context,
                required_sections=required_sections,
                retry_count=1,
                contract_errors=contract_errors,
                contract_forbidden_headings=contract_forbidden_headings,
                contract_missing_required_heading_keys=(
                    contract_missing_required_heading_keys
                ),
            )
            segment_md = self._sanitize_writer_segment_citations(
                evidence_pack_result,
                segment_md,
                allowed_source_ids=allowed_source_ids,
            )
            invalid_sources = evidence_pack_result.validate_segment_citations(
                segment_md,
                allowed_source_ids=allowed_source_ids,
            )
            if invalid_sources:
                segment_md = await self._writer_segment_markdown(
                    record,
                    segment=segment_with_contract,
                    timeout_seconds=timeout_seconds,
                    language_guidance=language_guidance,
                    memory_context=memory_context,
                    layer_context=layer_context,
                    required_sections=required_sections,
                    retry_count=2,
                    citation_error_ids=invalid_sources,
                    contract_errors=contract_errors,
                    contract_forbidden_headings=contract_forbidden_headings,
                    contract_missing_required_heading_keys=(
                        contract_missing_required_heading_keys
                    ),
                )
                segment_md = self._sanitize_writer_segment_citations(
                    evidence_pack_result,
                    segment_md,
                    allowed_source_ids=allowed_source_ids,
                )
                invalid_sources = evidence_pack_result.validate_segment_citations(
                    segment_md,
                    allowed_source_ids=allowed_source_ids,
                )
            if invalid_sources:
                raise RuntimeError(
                    "Writer segment cited invalid source IDs after contract retry: "
                    f"{', '.join(invalid_sources)}"
                )
            validation = validate_segment_contract(segment_md, contract)
            if validation.status != "pass":
                raise RuntimeError(
                    "Writer segment violated heading contract after retry: "
                    f"{segment['segment_name']}: {'; '.join(validation.errors)}"
                )
            await self.emit(
                detail.id,
                "writer_segment_validated",
                "writer",
                None,
                f"Writer segment validated: {segment['segment_name']}",
                {
                    "segment_name": segment["segment_name"],
                    "segment_kind": contract.segment_kind,
                    "section_id": contract.section_id,
                    "validation_status": validation.status,
                    "validation_errors": list(validation.errors),
                    "h2_headings": list(validation.h2_headings),
                    "forbidden_headings": list(validation.forbidden_headings),
                    "forbidden_heading_keys": list(validation.forbidden_heading_keys),
                    "invalid_heading_keys": list(validation.invalid_heading_keys),
                    "missing_required_heading_keys": list(
                        validation.missing_required_heading_keys
                    ),
                    "segment_retry_count": 1,
                },
            )
        return segment_md.strip(), contract

    def _sanitize_writer_segment_citations(
        self,
        evidence_pack_result,
        markdown: str,
        *,
        allowed_source_ids: set[str],
    ) -> str:
        sanitizer = getattr(evidence_pack_result, "sanitize_segment_citations", None)
        if callable(sanitizer):
            return sanitizer(markdown, allowed_source_ids=allowed_source_ids)
        return markdown

    def _writer_segment_required_outline(
        self,
        detail: RunDetail,
        segment: dict[str, object],
    ) -> str:
        contract = segment_contract_for(segment)
        section_id = contract.section_id
        competitor = str(segment.get("segment_competitor") or "").strip()
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        source_warning = (
            "Do not copy placeholder source IDs from examples. Use only IDs from "
            "allowed_source_ids in Segment Evidence Pack JSON."
        )
        deep_dive_competitor = competitor or "<segment_competitor>"

        if contract.segment_kind == "evidence_shard":
            return "\n".join(
                [
                    "Required segment outline:",
                    "Evidence shard only.",
                    "Do not write any ## H2 heading.",
                    "Return compact cited evidence notes as bullets.",
                    (
                        "Preserve exact source IDs for facts that should be cited by "
                        "the section writer."
                    ),
                    source_warning,
                ]
            )
        if section_id == "decision_summary":
            return "\n".join(
                [
                    "Required segment outline:",
                    "## Decision Summary",
                    "- Recommended decision / buying posture.",
                    "- Confidence level and what must not be overstated.",
                    "## Competitive Findings",
                    "### Pricing and Packaging",
                    "### Feature and Workflow Capability",
                    "### User Persona and Adoption",
                    "### Cross-Competitor Risks and Implications",
                    (
                        "Must include: at least three cited bullets and one "
                        "cross-competitor comparison."
                    ),
                    source_warning,
                ]
            )
        if section_id == "review_theme_summary":
            return "\n".join(
                [
                    "Required segment outline:",
                    "## User Review Themes",
                    "### <competitor>",
                    "#### Direct User / Community Signals",
                    "#### Simulated Survey and Interview Signals",
                    "#### Adoption Blockers",
                    "#### Switching Triggers",
                    "#### Evidence Gaps",
                    "## Community Evidence Triangulation",
                    "### Official Facts vs Community Observations",
                    "### Repeated Signals",
                    "### Contested or Low-Confidence Signals",
                    (
                        "Must include: separate direct user/community signals from "
                        "simulated survey/interview signals."
                    ),
                    source_warning,
                ]
            )
        if section_id == "competitor_deep_dives":
            return "\n".join(
                [
                    "Required segment outline:",
                    "## Competitor Deep Dives"
                    if not is_zh
                    else f"## {report_label(detail.output_language, 'competitor_deep_dives')}",
                    f"### {deep_dive_competitor}",
                    "#### Positioning and Core Value",
                    "#### Pricing and Packaging",
                    "#### Feature Capabilities",
                    "#### User Persona and Adoption",
                    "#### Community Feedback, Adoption Blockers, and Switching Triggers",
                    "#### Competitive Plays and Evidence Gaps",
                    (
                        "Must include: exactly one competitor ownership H3 matching "
                        "segment_competitor."
                    ),
                    source_warning,
                ]
            )
        if section_id == "swot_matrix":
            return "\n".join(
                [
                    "Required segment outline:",
                    "## Side-by-Side Decision Matrix",
                    "| Dimension | <competitor 1> | <competitor 2> |",
                    "|---|---|---|",
                    "## SWOT Analysis",
                    "### <competitor>",
                    "#### Strengths",
                    "#### Weaknesses",
                    "#### Opportunities",
                    "#### Threats",
                    (
                        "Must include: matrix interpretation and all four SWOT quadrants "
                        "for every competitor."
                    ),
                    source_warning,
                ]
            )
        if section_id == "evidence_support":
            return "\n".join(
                [
                    "Required segment outline:",
                    (
                        "Support headings are allowed and optional; include only "
                        "applicable support sections."
                    ),
                    f"## {report_label(detail.output_language, 'evidence_support')}",
                    f"## {report_label(detail.output_language, 'source_quality')}",
                    f"## {report_label(detail.output_language, 'user_research_evidence')}",
                    f"## {report_label(detail.output_language, 'rag_gap_fill')}",
                    f"## {report_label(detail.output_language, 'scenario_checklist')}",
                    f"## {report_label(detail.output_language, 'confidence_notes')}",
                    f"## {report_label(detail.output_language, 'claim_risk')}",
                    f"## {report_label(detail.output_language, 'next_collection')}",
                    f"## {report_label(detail.output_language, 'evidence_appendix')}",
                    (
                        "Must include: concise source-quality, coverage, confidence, "
                        "and gap support without restarting core analysis."
                    ),
                    source_warning,
                ]
            )
        return "\n".join(
            [
                "Required segment outline:",
                "Write only headings allowed by this segment contract.",
                source_warning,
            ]
        )

    async def _writer_segment_markdown(
        self,
        record: RunRecord,
        *,
        segment: dict[str, object],
        timeout_seconds: float,
        language_guidance: str,
        memory_context: str,
        layer_context: str,
        required_sections: str,
        retry_count: int,
        citation_error_ids: list[str] | None = None,
        contract_errors: list[str] | None = None,
        contract_forbidden_headings: list[str] | None = None,
        contract_missing_required_heading_keys: list[str] | None = None,
    ) -> str:
        detail = record.detail
        segment_json = json.dumps(segment, ensure_ascii=False)
        allowed_h2_headings = ", ".join(
            heading
            for heading in segment.get("allowed_h2_headings", [])
            if isinstance(heading, str)
        )
        required_h2_headings = ", ".join(
            heading
            for heading in segment.get("required_h2_headings", [])
            if isinstance(heading, str)
        )
        forbidden_h2_headings = ", ".join(
            heading
            for heading in segment.get("forbidden_h2_headings", [])
            if isinstance(heading, str)
        )
        segment_outline = self._writer_segment_required_outline(detail, segment)
        citation_warning = ""
        if citation_error_ids:
            citation_warning = (
                "Previous segment cited source IDs outside this segment: "
                f"{', '.join(citation_error_ids)}. Rewrite using only allowed_source_ids. "
                "Use exact [source:ID] syntax with no space after source:. Do not put "
                "multiple source IDs inside one [source:...] token; cite multiple "
                "sources as consecutive citations such as [source:A][source:B].\n"
            )
        contract_warning = ""
        if contract_errors:
            forbidden = ", ".join(contract_forbidden_headings or [])
            missing = ", ".join(contract_missing_required_heading_keys or [])
            contract_warning = (
                "Previous segment violated its heading contract: "
                f"{'; '.join(contract_errors)}. "
                f"Missing required H2 heading keys: {missing or 'none'}. "
                f"Forbidden H2 headings found: {forbidden or 'none'}. "
                "Rewrite only this segment and obey the segment contract exactly.\n"
            )
        user_research_gap_instruction = ""
        if (
            segment.get("segment_name") == "user_research"
            and not segment.get("groups")
            and not segment.get("allowed_source_ids")
        ):
            user_research_gap_instruction = (
                "This user_research segment has no groups or allowed sources; write "
                "the section as an evidence gap/absence note and do not invent user "
                "research findings.\n"
            )
        shard_instruction = ""
        if segment.get("segment_kind") == "evidence_shard":
            shard_instruction += (
                "This is an evidence shard. Return compact structured notes as bullets. "
                "Do not write any ## H2 heading. Do not write a final report section. "
                "Preserve exact source IDs for facts that should be cited by the section writer.\n"
            )
        if segment.get("shard_notes"):
            shard_instruction += (
                "This section writer receives evidence shard notes in segment.shard_notes. "
                "Write exactly one canonical report section or allowed section group from those notes.\n"
            )
        user_research_policy = writer_user_research_policy_text()
        return await asyncio.wait_for(
            self._trace_llm_text(
                record,
                agent="writer",
                subagent=None,
                name="report_writer_segment",
                system=(
                    "You are a senior enterprise competitive-intelligence analyst writing "
                    "one section group of a larger markdown report. Return only markdown "
                    "for this segment. Cite factual claims only with source IDs in "
                    "allowed_source_ids. Do not invent source IDs. Use exact [source:ID] "
                    "syntax with no space after source:. Do not combine multiple source "
                    "IDs inside one [source:...] token; write consecutive citations "
                    "like [source:A][source:B]. "
                    "Do not use web_search_result or confidence < 0.75 as the sole support "
                    "for a winner, legal/security certification, pricing, or procurement "
                    "recommendation. If evidence is incomplete, say the conclusion is "
                    "tentative and list the exact evidence gap. Do not claim all sources "
                    "are verified when any source_type is web_search_result or "
                    "llm_public_knowledge. "
                    f"{user_research_policy} "
                    f"{language_guidance}"
                ),
                user=(
                    f"Topic: {detail.topic}\n"
                    f"Competitors: {', '.join(detail.plan.competitors)}\n"
                    f"Dimensions: {', '.join(detail.plan.dimensions)}\n"
                    f"segment_name={segment['segment_name']}\n"
                    f"segment_kind={segment.get('segment_kind', 'section_fragment')}\n"
                    f"section_id={segment.get('section_id', segment['segment_name'])}\n"
                    f"segment_competitor={segment.get('segment_competitor') or 'all'}\n"
                    f"retry_count={retry_count}\n"
                    "Allowed H2 headings for this segment: "
                    f"{allowed_h2_headings or 'none'}\n"
                    "Required H2 headings for this segment: "
                    f"{required_h2_headings or 'none'}\n"
                    "Forbidden H2 headings for this segment: "
                    f"{forbidden_h2_headings or 'none'}\n"
                    f"{segment_outline}\n"
                    f"{citation_warning}"
                    f"{contract_warning}"
                    f"{user_research_gap_instruction}"
                    f"{shard_instruction}"
                    "Do not write headings outside this segment's contract. "
                    "Do not write support or appendix sections unless "
                    "segment_kind=support_fragment. If segment_kind=evidence_shard, "
                    "do not write any ## H2 headings.\n"
                    f"Confirmed Memory Preferences:\n{memory_context}\n"
                    f"Layer Report Context: {layer_context}\n"
                    f"{self._writer_community_policy_text()}\n"
                    f"Segment Evidence Pack JSON: {segment_json}\n\n"
                    f"Required sections for full report:\n{required_sections}\n"
                    "Write with consulting depth for this segment. Keep support material "
                    "concise and preserve [source:ID] citation syntax."
                ),
            ),
            timeout=timeout_seconds,
        )

    async def _writer_section_repair_markdown(
        self,
        record: RunRecord,
        *,
        sections: Sequence[str],
        previous_report: str,
    ) -> str:
        detail = record.detail
        evidence_pack_result = build_writer_evidence_pack(detail)
        preflight_errors = evidence_pack_result.preflight_errors()
        if preflight_errors:
            raise WriterEvidencePreflightError(
                "writer evidence pack preflight failed: "
                + ", ".join(preflight_errors)
            )
        segmented_writer_required = getattr(
            getattr(evidence_pack_result, "metrics", None),
            "segmented_writer_required",
            False,
        )
        if segmented_writer_required:
            if hasattr(evidence_pack_result, "repair_segment_inputs"):
                repair_payloads = evidence_pack_result.repair_segment_inputs(sections)
            else:
                repair_payloads = [evidence_pack_result.repair_segment_input(sections)]
            repair_segments = [
                segment
                for payload in repair_payloads
                for segment in (payload.get("segments") or [])
                if isinstance(segment, dict)
            ]
            repair_has_evidence_shards = any(
                segment.get("segment_kind") == "evidence_shard"
                for segment in repair_segments
            )
            writer_context_jsons = [
                json.dumps(payload, ensure_ascii=False) for payload in repair_payloads
            ]
        else:
            repair_payloads = []
            repair_segments = []
            repair_has_evidence_shards = False
            writer_context_jsons = [evidence_pack_result.to_prompt_json()]
        telemetry_payload = (
            evidence_pack_result.telemetry_payload()
            if hasattr(evidence_pack_result, "telemetry_payload")
            else {}
        )
        telemetry_payload = dict(telemetry_payload)
        telemetry_payload.update(
            {
                "writer_repair_mode": "section",
                "writer_repair_sections": list(sections),
                "segmented_writer_required": bool(segmented_writer_required),
                "repair_segment_count": (
                    len(repair_payloads) if segmented_writer_required else 1
                ),
            }
        )
        if repair_payloads:
            telemetry_payload["repair_input_chars"] = [
                payload.get("repair_input_chars") for payload in repair_payloads
            ]
            telemetry_payload["repair_part_count"] = len(repair_payloads)
        await self.emit(
            detail.id,
            "writer_preflight",
            "writer",
            None,
            "Writer evidence pack prepared for section repair.",
            telemetry_payload,
        )
        language_guidance = language_instruction(detail.output_language)
        section_headings = "\n".join(
            self._writer_section_heading_instruction(detail, section) for section in sections
        )
        if repair_has_evidence_shards:
            timeout_seconds = max(0.05, float(self._settings.writer_timeout_seconds))
            repaired_sections = await self._writer_segment_markdown_parts(
                record,
                evidence_pack_result=evidence_pack_result,
                segments=repair_segments,
                timeout_seconds=timeout_seconds,
                language_guidance=language_guidance,
                memory_context="\n".join(detail.plan.memory_prompt_context) or "none",
                layer_context=self._writer_layer_context(detail),
                required_sections=self._writer_required_sections(detail),
            )
            return self._join_section_repair_parts(repaired_sections, section_headings)

        repaired_sections = []
        for writer_context_json in writer_context_jsons:
            repaired_sections.append(
                await self._trace_llm_text(
                    record,
                    agent="writer",
                    subagent=None,
                    name="report_section_repair",
                    system=(
                        "You are a senior enterprise competitive-intelligence analyst repairing "
                        "one section of an existing markdown report. Return only the requested "
                        "section markdown. Preserve existing [source:ID] syntax, never invent "
                        "source IDs, and cite factual claims with available source IDs. "
                        f"{language_guidance}"
                    ),
                    user=(
                        f"Topic: {detail.topic}\n"
                        f"Competitors: {', '.join(detail.plan.competitors)}\n"
                        f"Dimensions: {', '.join(detail.plan.dimensions)}\n"
                        f"Repair only these sections: {', '.join(sections)}\n"
                        f"Expected section headings:\n{section_headings}\n"
                        "return only the requested section markdown; do not rewrite unrelated "
                        "sections or include commentary outside the section.\n"
                        "Use the exact requested level-2 heading for each returned section.\n"
                        "You must preserve existing [source:ID] syntax.\n"
                        f"{self._writer_community_policy_text()}\n"
                        f"Writer Evidence Pack JSON: {writer_context_json}\n\n"
                        f"Previous report:\n{previous_report}"
                    ),
                )
            )
        return self._join_section_repair_parts(repaired_sections, section_headings)

    def _writer_community_policy_text(self) -> str:
        return (
            "Official facts vs community observations: official docs may support official "
            "commitments; community_triangulated, community_observed, and "
            "community_contested clusters may support actual-use risks, user evaluation, "
            "and pricing caveats. Do not present community observations as official "
            "commitments unless an official source also supports the same claim."
        )

    def _writer_section_heading_instruction(self, detail: RunDetail, section: str) -> str:
        try:
            heading = report_label(detail.output_language, section)
        except KeyError:
            heading = section
        return f"{section} -> ## {heading}"

    def _join_section_repair_parts(
        self,
        parts: Sequence[str],
        section_headings: str,
    ) -> str:
        requested_headings = {
            line.split("->", 1)[1].strip()
            for line in section_headings.splitlines()
            if "->" in line
        }
        seen_headings: set[str] = set()
        cleaned_parts: list[str] = []
        for part in parts:
            cleaned_lines: list[str] = []
            for line in part.strip().splitlines():
                heading = line.strip()
                is_top_level_heading = heading.startswith("## ") and not heading.startswith(
                    "### "
                )
                if heading in requested_headings or is_top_level_heading:
                    if heading in seen_headings:
                        continue
                    seen_headings.add(heading)
                cleaned_lines.append(line)
            cleaned_part = "\n".join(cleaned_lines).strip()
            if cleaned_part:
                cleaned_parts.append(cleaned_part)
        return "\n\n".join(cleaned_parts)

    def _preserve_hardened_previous_report(
        self,
        detail: RunDetail,
        previous_report: str,
    ) -> str:
        return self._harden_report_markdown(detail, previous_report)

    def _backfill_layer_sections(
        self,
        detail: RunDetail,
        source_ids: list[str],
    ) -> list[str]:
        return self._backfill_layer_sections_lines(detail, source_ids)

    def _backfill_layer_sections_lines(
        self,
        detail: RunDetail,
        source_ids: list[str],
    ) -> list[str]:
        refs = self._format_source_refs(source_ids)
        heading = self._layer_section_heading(detail)
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        layer = detail.plan.competitor_layer
        if layer == "L1":
            if is_zh:
                bullets = [
                    f"- 直接战报定位：把当前赢家作为短期替代或对抗话术的候选主线，但只在引用证据覆盖的范围内使用。{refs}",
                    f"- 反对意见处理：优先围绕定价、包装、功能对齐、采购阻力和切换触发组织回答，不把弱单元格包装成确定结论。{refs}",
                    f"- 行动偏向：使用置信度最高的维度赢家作为初始战报骨架，并在发布前验证单来源、低置信度或社区观察支持的声明。{refs}",
                    f"- 落地检查：每条战报话术都要同时包含可引用证据、目标买家、可能反驳点和下一步验证任务，避免只给一句赢家判断。{refs}",
                ]
            else:
                bullets = [
                    f"- Direct-use position: treat the current winners as candidate near-term replacement or objection-handling lines only within the cited evidence boundary.{refs}",
                    f"- Objection handling: organize responses around pricing, packaging, feature parity, procurement friction, and switching triggers without turning weak cells into settled conclusions.{refs}",
                    f"- Action bias: use the highest-confidence dimension winners as the initial battlecard spine, then verify single-source, low-confidence, or community-observed claims before publication.{refs}",
                    f"- Deployment check: every battlecard line should pair cited evidence, target buyer, likely rebuttal, and next validation task instead of stopping at a one-sentence winner claim.{refs}",
                ]
        elif layer == "L2":
            if is_zh:
                bullets = [
                    f"- 相邻工作流威胁：从工作流重叠、集成杠杆和切换成本阅读矩阵，而不是只比较孤立功能。{refs}",
                    f"- 采购风险：在提出企业建议前，把已证实的组织控制措施与搜索线索、社区观察或低置信度声明分开。{refs}",
                    f"- 监控列表：重点关注相邻竞品能通过一次集成、权限或打包变化吞并目标工作流的维度。{refs}",
                    f"- 行动节奏：把强证据维度写成可执行建议，把弱证据维度转为验证任务，避免把工作流风险过早定性。{refs}",
                ]
            else:
                bullets = [
                    f"- Adjacent-workflow threat: read the matrix through workflow overlap, integration leverage, and switching-cost exposure rather than isolated feature parity.{refs}",
                    f"- Buying risk: separate proven enterprise controls from search leads, community observations, or low-confidence claims before making procurement recommendations.{refs}",
                    f"- Watchlist: monitor dimensions where adjacent competitors could absorb the target workflow through one integration, permission, or packaging change.{refs}",
                    f"- Action cadence: turn strong-evidence dimensions into recommendations and weak-evidence dimensions into validation tasks instead of overstating workflow risk.{refs}",
                ]
        elif layer == "L3":
            if is_zh:
                bullets = [
                    f"- 类别视角：避免只宣布单一直接赢家，应按细分市场、趋势信号和基准强度给竞品分组。{refs}",
                    f"- 战略视角：当证据广度仍不足以支撑景观级覆盖时，把建议写成投资组合选项而不是终局判断。{refs}",
                    f"- 不确定性视角：在做类别范围声明前，优先增加竞品、市场级来源和跨来源验证。{refs}",
                    f"- 决策节奏：用高置信信号确定短期动作，用低覆盖区域定义观察指标和后续研究任务。{refs}",
                ]
            else:
                bullets = [
                    f"- Category view: avoid a single direct winner and group competitors by segment, trend signal, and benchmark strength.{refs}",
                    f"- Strategy view: treat recommendations as portfolio options while evidence breadth remains below landscape-grade coverage.{refs}",
                    f"- Uncertainty view: prioritize adding competitors, market-level sources, and cross-source validation before making category-wide claims.{refs}",
                    f"- Decision cadence: use high-confidence signals for near-term action and low-coverage areas for watch metrics and follow-up research tasks.{refs}",
                ]
        else:
            if is_zh:
                bullets = [
                    f"- 业务含义：当前报告应作为带不确定性边界的证据读数，而不是最终市场结论。{refs}",
                    f"- 决策使用：把高置信矩阵单元转成可行动建议，把弱单元格保留为验证任务。{refs}",
                    f"- 风险控制：当来源为单条、搜索线索或低置信度时，不要夸大采购、合规、功能或价格结论。{refs}",
                    f"- 后续动作：优先补齐影响赢家判断的来源，再扩大到支持层审计材料。{refs}",
                ]
            else:
                bullets = [
                    f"- Business implication: use this as an evidence-indexed readout with explicit uncertainty rather than a final market conclusion.{refs}",
                    f"- Decision use: turn high-confidence matrix cells into action and keep weak cells as validation tasks.{refs}",
                    f"- Risk control: do not overstate procurement, compliance, feature, or pricing claims when support is single-source, search-only, or low-confidence.{refs}",
                    f"- Next action: fill the sources that could change winner judgments before expanding support-layer audit material.{refs}",
                ]
        return ["", f"## {heading}", *bullets]

    def _backfill_decision_summary_section(
        self, detail: RunDetail, source_ids: list[str]
    ) -> list[str]:
        refs = self._format_source_refs(source_ids)
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        dimensions = ", ".join(detail.plan.dimensions) or (
            "所请求的维度" if is_zh else "the requested dimensions"
        )
        competitors = ", ".join(detail.plan.competitors) or detail.topic
        if detail.comparison_matrix is not None and detail.comparison_matrix.winner_by_dimension:
            winners = ", ".join(
                f"{dimension}: {winner}"
                for dimension, winner in detail.comparison_matrix.winner_by_dimension.items()
            )
        else:
            winners = (
                "尚无评分赢家；将来源覆盖率和 QA 状态作为约束条件"
                if is_zh
                else "no scored winner yet; use source coverage and QA status as constraints"
            )
        if is_zh:
            return [
                "",
                f"## {report_label(detail.output_language, 'decision_summary')}",
                (
                    f"- 推荐行动：使用此 {self._writer_layer_label(detail)} 对比 "
                    f"{competitors} 在 {dimensions} 上的表现；决策锚定在 {winners}。{refs}"
                ),
                (
                    "- 决策姿态：优先考虑具有已证实、高置信度证据的维度，"
                    "并将薄弱单元格路由到验证计划中。"
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

    def _backfill_competitive_findings_section(self, detail: RunDetail) -> list[str]:
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        lines = [
            "",
            f"## {report_label(detail.output_language, 'competitive_findings')}",
        ]
        return self._backfill_competitive_findings_lines(detail, lines, is_zh)

    def _backfill_competitive_findings_lines(
        self,
        detail: RunDetail,
        lines: list[str],
        is_zh: bool,
    ) -> list[str]:
        if detail.comparison_matrix is None:
            source_ids = self._matrix_source_ids(detail)
            refs = self._format_source_refs(source_ids)
            if is_zh:
                lines.extend(
                    [
                        f"- 竞争发现暂以证据覆盖为核心约束：结构化对比矩阵尚未形成，因此不能直接宣布赢家。{refs}",
                        f"- 可用信号应先按竞品、维度和来源类型分层阅读，避免把单条搜索线索或低置信度材料提升为采购结论。{refs}",
                        f"- 决策含义是先补齐关键单元格，再把价格、功能、用户人群和切换触发转成正式竞争建议。{refs}",
                        f"- 下一轮优先收集能够互相印证的官方页面、社区讨论、案例或访谈材料，让矩阵具备可解释的强弱差异。{refs}",
                    ]
                )
            else:
                lines.extend(
                    [
                        (
                            "- Competitive findings are currently constrained by source coverage: "
                            f"the structured comparison matrix is not available, so no winner should be declared yet.{refs}"
                        ),
                        (
                            "- Read the available signals by competitor, dimension, and source type before promoting "
                            f"any search-only or low-confidence item into a buying conclusion.{refs}"
                        ),
                        (
                            "- The practical decision is to fill the key cells first, then turn pricing, feature, "
                            f"persona, and switching signals into a formal competitive recommendation.{refs}"
                        ),
                        (
                            "- Next collection should prioritize mutually confirming official pages, community "
                            f"discussions, case studies, or interviews so the matrix can explain real strengths and weaknesses.{refs}"
                        ),
                    ]
                )
            return lines

        matrix_refs = self._matrix_source_ids(detail)
        matrix_ref_text = self._format_source_refs(matrix_refs)
        dimensions = ", ".join(detail.plan.dimensions) or (
            "请求维度" if is_zh else "requested dimensions"
        )
        winners = ", ".join(
            f"{dimension}: {winner}"
            for dimension, winner in detail.comparison_matrix.winner_by_dimension.items()
            if winner
        ) or ("尚无确认赢家" if is_zh else "no confirmed winners")
        if is_zh:
            lines.append(
                f"- 总体读数：本轮矩阵覆盖 {dimensions}，当前赢家线索为 {winners}；这些结论应被视为带证据边界的竞争判断，而不是脱离来源的绝对排名。{matrix_ref_text}"
            )
        else:
            lines.append(
                f"- Overall read: the current matrix covers {dimensions}, with winner signals at {winners}; "
                f"treat these as evidence-bounded competitive judgments, not absolute rankings detached from the cited cells.{matrix_ref_text}"
            )

        for dimension in detail.plan.dimensions:
            cells = [
                cell for cell in detail.comparison_matrix.cells if cell.dimension == dimension
            ]
            if not cells:
                continue
            source_ids = [source_id for cell in cells for source_id in cell.source_ids]
            refs = self._format_source_refs(source_ids)
            winner = detail.comparison_matrix.winner_by_dimension.get(dimension)
            cell_summary = "; ".join(
                f"{cell.competitor}: {self._trim_sentence(cell.value, 140)}"
                for cell in cells[:4]
            )
            confidence_values = [cell.confidence for cell in cells]
            confidence_summary = (
                f"{min(confidence_values):.2f}-{max(confidence_values):.2f}"
                if confidence_values
                else "unknown"
            )
            if winner:
                if is_zh:
                    lines.append(
                        f"- {dimension}：{winner} 在该维度领先；可写成竞争优势的前提是同时保留对比单元格的差异：{cell_summary or '暂无单元格摘要'}。{refs}"
                    )
                    lines.append(
                        f"- {dimension} 的证据姿态：单元格置信度区间为 {confidence_summary}，销售或产品话术应强调已引用材料能证明的部分，并把弱单元格列入验证任务。{refs}"
                    )
                else:
                    lines.append(
                        f"- {dimension}: {winner} leads this dimension, but the implication should stay tied to "
                        f"the cited cell differences: {cell_summary or 'no cell summary available'}.{refs}"
                    )
                    lines.append(
                        f"- {dimension} evidence posture: cell confidence ranges {confidence_summary}; sales or "
                        f"product messaging should emphasize only what the cited material can support and route weaker cells into verification tasks.{refs}"
                    )
            else:
                if is_zh:
                    lines.append(
                        f"- {dimension}：存在可用于对比的证据，但暂不宣布明确赢家；当前单元格显示 {cell_summary or '暂无单元格摘要'}。{refs}"
                    )
                    lines.append(
                        f"- {dimension} 的处理方式：置信度区间为 {confidence_summary}，应把差异转成待验证假设，而不是直接转成采购或市场声明。{refs}"
                    )
                else:
                    lines.append(
                        f"- {dimension}: evidence exists for comparison, but no clear winner should be asserted "
                        f"without another validation pass; current cells show {cell_summary or 'no cell summary available'}.{refs}"
                    )
                    lines.append(
                        f"- {dimension} handling: confidence ranges {confidence_summary}, so the difference should "
                        f"become a validation hypothesis rather than an immediate procurement or market claim.{refs}"
                    )

        if len(lines) == 2:
            refs = self._format_source_refs(matrix_refs)
            if is_zh:
                lines.append(f"- 尚无维度级别的发现；在做出竞争建议之前，请使用收集任务。{refs}")
            else:
                lines.append(
                    "- No dimension-level findings are available yet; use collection tasks before "
                    f"making a competitive recommendation.{refs}"
                )
        elif is_zh:
            lines.append(
                f"- 竞争建议落地时，应把赢家、证据强度、弱单元格和下一步验证放在同一段中呈现；这样能让报告既可行动，又不会把证据缺口包装成确定事实。{matrix_ref_text}"
            )
        else:
            lines.append(
                "- When turning these findings into action, present the winner, evidence strength, weak cells, "
                f"and next validation step together; that keeps the report usable without packaging evidence gaps as settled facts.{matrix_ref_text}"
            )
        return lines

    def _backfill_side_by_side_matrix_section(self, detail: RunDetail) -> list[str]:
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        lines = [
            "",
            f"## {report_label(detail.output_language, 'side_by_side_matrix')}",
        ]
        matrix = detail.comparison_matrix
        if matrix is None or not matrix.cells:
            refs = self._format_source_refs(self._matrix_source_ids(detail))
            if is_zh:
                lines.extend(
                    [
                        f"- 结构化对比矩阵尚不可用；所有维度判断都应先作为证据缺口处理。{refs}",
                        f"- 宣布赢家前，需要先为每个竞品和维度补齐或重新生成矩阵单元格。{refs}",
                    ]
                )
            else:
                lines.extend(
                    [
                        (
                            "- The structured comparison matrix is not available yet; "
                            f"treat all dimension-level reads as evidence gaps.{refs}"
                        ),
                        (
                            "- Before declaring winners, collect or regenerate matrix cells "
                            f"for every requested competitor and dimension.{refs}"
                        ),
                    ]
                )
            return lines

        matrix_refs = self._format_source_refs(self._matrix_source_ids(detail))
        winners = ", ".join(
            f"{dimension}: {winner}"
            for dimension, winner in matrix.winner_by_dimension.items()
            if winner
        )
        if winners:
            prefix = (
                "- 结构化矩阵中的赢家信号："
                if is_zh
                else "- Winner signals from the structured matrix: "
            )
            lines.append(f"{prefix}{winners}.{matrix_refs}")
        summary_prefix = "- 矩阵备注：" if is_zh else "- Matrix note: "
        for summary_item in matrix.summary[:3]:
            lines.append(
                f"{summary_prefix}"
                f"{self._markdown_table_cell(summary_item, limit=260)}{matrix_refs}"
            )

        table_header = (
            "| 竞品 | 维度 | 发现 | 置信度 | 证据 |"
            if is_zh
            else "| Competitor | Dimension | Finding | Confidence | Evidence |"
        )
        lines.extend(
            [
                "",
                table_header,
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for cell in self._ordered_comparison_cells(detail):
            refs = self._format_source_refs(cell.source_ids)
            lines.append(
                "| "
                f"{self._markdown_table_cell(cell.competitor)} | "
                f"{self._markdown_table_cell(cell.dimension)} | "
                f"{self._markdown_table_cell(cell.value, limit=260)} | "
                f"{cell.confidence:.2f} | "
                f"{refs or '-'} |"
            )
        return lines

    def _backfill_competitor_deep_dives_section(self, detail: RunDetail) -> list[str]:
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
                    f"- {competitor} 注意事项：在将这些转为外部宣传信息之前，"
                    "监控定价、包装、功能和买家反对意见声明。"
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

    def _backfill_evidence_support_section(self, detail: RunDetail) -> list[str]:
        refs = self._format_source_refs(self._matrix_source_ids(detail))
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        if is_zh:
            return [
                "",
                f"## {report_label(detail.output_language, 'evidence_support')}",
                (
                    "- 使用以下支持部分来审计来源质量、场景 QA、知识覆盖、"
                    f"声明风险以及剩余的验证任务。{refs}"
                ),
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

    def _backfill_source_quality_section(self, detail: RunDetail) -> list[str]:
        heading = report_label(detail.output_language, "source_quality")
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        if not detail.raw_sources:
            return [
                "",
                f"## {heading}",
                (
                    "- 没有可用的原始来源，因此所有结论在使用前都需要进行收集。"
                    if is_zh
                    else (
                        "- No raw sources are available, so all conclusions require "
                        "collection before use."
                    )
                ),
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

    def _backfill_scenario_checklist_section(self, detail: RunDetail) -> list[str]:
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

    def _backfill_next_collection_plan(self, detail: RunDetail) -> list[str]:
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
                lines.append(f"- 解决 QA 发现：{issue.problem}")
            else:
                lines.append(f"- Resolve QA finding: {issue.problem}")
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

    def _writer_source_appendix_lines(self, detail: RunDetail) -> list[str]:
        evidence_pack_result = build_writer_evidence_pack(detail)
        lines = ["", f"## {report_label(detail.output_language, 'evidence_appendix')}"]
        for row in evidence_pack_result.source_appendix_rows():
            source_id = row["source_id"]
            title = row["title"] or source_id
            source_type = row["source_type"]
            competitor = row["competitor"]
            dimension = row["dimension"]
            confidence = row["confidence"]
            url = row["url"] or "no url"
            lines.append(
                f"- [source:{source_id}] {title} | {source_type} | "
                f"{competitor}/{dimension} | confidence={confidence} | {url}"
            )
        return lines

    def _backfill_evidence_appendix(self, detail: RunDetail) -> list[str]:
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
            raise RuntimeError("Writer returned empty report content")
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
                self._backfill_decision_summary_section(detail, source_ids),
            ),
            (
                self._report_label_aliases("competitive_findings"),
                self._backfill_competitive_findings_section(detail),
            ),
            (
                self._report_label_aliases("review_theme_summary"),
                self._backfill_review_theme_section(detail),
            ),
            (
                self._report_label_aliases("competitor_deep_dives"),
                self._backfill_competitor_deep_dives_section(detail),
            ),
            (
                self._report_label_aliases("side_by_side_matrix"),
                self._backfill_side_by_side_matrix_section(detail),
            ),
            (
                self._report_label_aliases("swot_analysis"),
                self._backfill_swot_section(detail),
            ),
            (
                layer_heading_aliases,
                self._backfill_layer_sections(detail, source_ids),
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
                self._backfill_evidence_support_section(detail),
            ),
            (
                report_label(detail.output_language, "source_quality"),
                self._report_label_aliases("source_quality"),
                self._backfill_source_quality_section(detail),
            ),
            (
                report_label(detail.output_language, "memory_context"),
                self._report_label_aliases("memory_context"),
                self._backfill_memory_context_section(detail),
            ),
            (
                report_label(detail.output_language, "user_research_evidence"),
                self._report_label_aliases("user_research_evidence"),
                self._backfill_user_research_section(detail),
            ),
            (
                report_label(detail.output_language, "rag_gap_fill"),
                self._report_label_aliases("rag_gap_fill"),
                self._backfill_rag_gap_fill_section(detail),
            ),
            (
                report_label(detail.output_language, "scenario_checklist"),
                self._report_label_aliases("scenario_checklist"),
                self._backfill_scenario_checklist_section(detail),
            ),
            (
                report_label(detail.output_language, "claim_risk"),
                self._report_label_aliases("claim_risk"),
                self._backfill_claim_validation_section(detail),
            ),
            (
                report_label(detail.output_language, "next_collection"),
                self._report_label_aliases("next_collection"),
                self._backfill_next_collection_plan(detail),
            ),
            (
                report_label(detail.output_language, "evidence_appendix"),
                self._report_label_aliases("evidence_appendix"),
                self._backfill_evidence_appendix(detail),
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

    def _layer_section_heading(self, detail: RunDetail) -> str:
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
        compact_heading = self._compact_report_heading_text(heading)
        compact_alias = self._compact_report_heading_text(alias)
        return (
            normalized_heading == normalized_alias
            or normalized_alias in normalized_heading
            or compact_heading == compact_alias
            or compact_alias in compact_heading
        )

    def _normalize_report_heading_text(self, heading: str) -> str:
        cleaned = re.sub(r"\s+", " ", heading.strip().strip("#").strip())
        cleaned = re.sub(
            r"^(?:section\s+)?(?:\d+(?:\.\d+)*|[ivxlcdm]+)[\.)]\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        return cleaned.casefold()

    def _compact_report_heading_text(self, heading: str) -> str:
        return re.sub(r"\s+", "", self._normalize_report_heading_text(heading))

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
            self._report_label_aliases("review_theme_summary"),
            self._report_label_aliases("dimension_winners"),
            self._report_label_aliases("comparison_matrix", "side_by_side_matrix"),
            self._report_label_aliases("competitor_deep_dives"),
            self._report_label_aliases("swot_analysis"),
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
                f"{report_label(output_language, 'review_theme_summary')}: summarize cited "
                "user praise, complaints, adoption blockers, and switching triggers; mark "
                "missing review evidence as an evidence gap."
            ),
            (
                f"{report_label(output_language, 'competitor_deep_dives')}: cover where "
                "each competitor wins, has weaknesses, and needs watchouts."
            ),
            (
                f"{report_label(output_language, 'swot_analysis')}: include Strengths, "
                "Weaknesses, Opportunities, and Threats for each competitor using cited SWOT "
                "analysis or explicit evidence-gap notes. Use explicit quadrant labels "
                "`Strengths`, `Weaknesses`, `Opportunities`, and `Threats` (or the localized "
                "equivalents) under every competitor instead of only writing general prose."
            ),
            (
                f"{report_label(output_language, 'side_by_side_matrix')}: cover every "
                "competitor and dimension with cited cells."
            ),
        ]
        if any(source.metadata.get("community_evidence") for source in detail.raw_sources):
            analysis_sections.append(
                f"{report_label(output_language, 'community_evidence_triangulation')}: "
                "separate official facts from community observations, contested claims, "
                "and actual-use risks."
            )
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
                "must be closed before publication, including the gap id or topic, suggested "
                "retrieval query, evidence needed, current status, and how the gap affects the "
                "recommendation. Do not use a one-line placeholder."
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
        core_lines = [
            "Core analysis layer (target 65-75% of the report body):",
            *(
                f"{index}. {section}"
                for index, section in enumerate(
                    [*analysis_sections, *layer_sections], start=1
                )
            ),
        ]
        support_lines = [
            "Support/audit layer (concise audit trail after core analysis):",
            *(
                f"{index}. {section}"
                for index, section in enumerate(support_sections, start=1)
            ),
        ]
        return "\n".join([*core_lines, *support_lines])

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
            "qa_findings": [self._writer_issue_digest(issue) for issue in detail.qa_findings],
            "reflections": [
                {
                    "iteration": reflection.iteration,
                    "coverage_gaps": list(reflection.coverage_gaps),
                    "confidence_outliers": list(reflection.confidence_outliers),
                    "cross_competitor_gaps": list(reflection.cross_competitor_gaps),
                }
                for reflection in detail.reflections
            ],
        }

    def _writer_source_digest(self, sources: list[RawSource]) -> list[dict[str, object]]:
        digests: list[dict[str, object]] = []
        for source in sources:
            snippet = self._writer_source_snippet(source)
            digest = {
                "id": source.id,
                "competitor": source.competitor,
                "covered_competitors": source.covered_competitors,
                "dimension": source.dimension,
                "source_type": source.source_type,
                "title": source.title,
                "url": str(source.url) if source.url else None,
                "snippet": snippet,
                "confidence": round(source.confidence, 3),
            }
            if not snippet:
                digest["snippet_quality"] = "omitted_no_clean_business_snippet"
            normalized_fields = self._writer_normalized_fields_digest(source)
            if normalized_fields:
                digest["normalized_fields"] = normalized_fields
            if source.metadata.get("community_evidence"):
                digest["community_evidence"] = True
                community_source_type = self._writer_metadata_string(
                    source.metadata.get("community_source_type")
                )
                if community_source_type is not None:
                    digest["community_source_type"] = community_source_type
                community_authority_signal = self._writer_metadata_string(
                    source.metadata.get("community_authority_signal")
                )
                if community_authority_signal is not None:
                    digest["community_authority_signal"] = community_authority_signal
                digest["official_commitment"] = bool(
                    source.metadata.get("official_commitment", False)
                )
                clusters = self._writer_community_cluster_list_digest(
                    source.metadata.get("community_claim_clusters")
                )
                if clusters:
                    digest["community_claim_clusters"] = clusters
            digests.append(digest)
        return digests

    def _writer_source_snippet(self, source: RawSource) -> str:
        raw_len = len(source.snippet or "")
        normalized_limit = (
            WRITER_NORMALIZED_SNIPPET_LIMIT
            if normalized_fields_from_source(source)
            else max(raw_len, 50000)
        )
        return source_business_snippet(
            source,
            dimension=source.dimension,
            limit=normalized_limit,
        )

    def _writer_normalized_fields_digest(
        self,
        source: RawSource,
    ) -> list[dict[str, object]]:
        fields = normalized_fields_from_source(source)
        digests: list[dict[str, object]] = []
        for field in fields:
            if not isinstance(field, Mapping):
                continue
            digest: dict[str, object] = {}
            for raw_key, raw_value in field.items():
                key = str(raw_key)
                normalized_key = key.strip().lower()
                if normalized_key in WRITER_NORMALIZED_FIELD_DROP_KEYS:
                    continue
                value = self._writer_normalized_field_value(normalized_key, raw_value)
                if value is not None:
                    digest[key] = value
            if digest:
                digests.append(digest)
        return digests

    def _writer_normalized_field_value(
        self,
        key: str,
        value: object,
    ) -> object | None:
        if isinstance(value, str):
            if not value.strip():
                return None
            return self._trim_sentence(
                value,
                self._writer_normalized_field_limit(key),
            )
        if isinstance(value, bool):
            return value
        if isinstance(value, int | float):
            return value if math.isfinite(float(value)) else None
        if isinstance(value, list):
            items: list[object] = []
            for item in value:
                item_value = self._writer_normalized_field_value(key, item)
                if item_value is not None:
                    items.append(item_value)
                if len(items) >= 5:
                    break
            return items or None
        if isinstance(value, Mapping):
            nested: dict[str, object] = {}
            for raw_key, raw_value in value.items():
                nested_key = str(raw_key)
                normalized_nested_key = nested_key.strip().lower()
                if normalized_nested_key in WRITER_NORMALIZED_FIELD_DROP_KEYS:
                    continue
                nested_value = self._writer_normalized_field_value(
                    normalized_nested_key,
                    raw_value,
                )
                if nested_value is not None:
                    nested[nested_key] = nested_value
            return nested or None
        return None

    def _writer_normalized_field_limit(self, key: str) -> int:
        if any(part in key for part in WRITER_NORMALIZED_FIELD_QUOTE_KEY_PARTS):
            return 1200
        if any(part in key for part in WRITER_NORMALIZED_FIELD_LONG_KEY_PARTS):
            return 800
        return 400

    def _writer_source_text_keys(
        self,
        detail: RunDetail,
        *,
        competitor: str,
        dimension: str | None = None,
    ) -> set[str]:
        keys: set[str] = set()
        for source in detail.raw_sources:
            if dimension is not None and source.dimension != dimension:
                continue
            if not self._source_matches_competitor(source, competitor):
                continue
            snippet = self._writer_source_snippet(source)
            key = self._writer_dedupe_text_key(snippet)
            if key:
                keys.add(key)
        return keys

    def _writer_dedupe_text_key(self, value: str) -> str:
        return " ".join(value.split()).casefold()

    def _writer_metadata_string(self, value: object, limit: int = 80) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        return self._trim_sentence(value, limit)

    def _writer_community_cluster_list_digest(
        self,
        clusters: object,
    ) -> list[dict[str, object]]:
        if not isinstance(clusters, list):
            return []
        digests: list[dict[str, object]] = []
        for cluster in clusters:
            if not isinstance(cluster, Mapping):
                continue
            digest = self._writer_community_cluster_digest(cluster)
            if digest:
                digests.append(digest)
            if len(digests) >= 5:
                break
        return digests

    def _writer_community_cluster_digest(
        self,
        cluster: Mapping[str, object],
    ) -> dict[str, object]:
        digest: dict[str, object] = {}
        for key, limit in (
            ("kind", 80),
            ("label", 80),
            ("claim", 180),
            ("normalized_value", 120),
        ):
            value = cluster.get(key)
            if isinstance(value, str) and value.strip():
                digest[key] = self._trim_sentence(value, limit)
        confidence = self._writer_cluster_confidence(cluster.get("confidence"))
        if confidence is not None:
            digest["confidence"] = confidence
        for key, count, limit in (
            ("source_ids", 6, 80),
            ("official_source_ids", 6, 80),
            ("evidence", 3, 180),
            ("conflict_values", 5, 120),
        ):
            values = self._writer_string_list_digest(
                cluster.get(key),
                count=count,
                limit=limit,
            )
            if values:
                digest[key] = values
        return digest

    def _writer_cluster_confidence(self, value: object) -> float | None:
        if isinstance(value, bool):
            return None
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(confidence):
            return None
        return round(confidence, 3)

    def _writer_string_list_digest(
        self,
        values: object,
        *,
        count: int,
        limit: int,
    ) -> list[str]:
        if not isinstance(values, list):
            return []
        digest: list[str] = []
        for value in values:
            if isinstance(value, str) and value.strip():
                digest.append(self._trim_sentence(value, limit))
            if len(digest) >= count:
                break
        return digest

    def _writer_competitor_digest(self, detail: RunDetail, competitor: str) -> dict[str, object]:
        kb = detail.competitor_kbs.get(competitor)
        knowledge = detail.competitor_knowledge.get(competitor)
        slices = {}
        if kb is not None:
            slices = {
                dimension: self._writer_unique_kb_findings(
                    detail,
                    competitor=competitor,
                    dimension=dimension,
                    findings=findings,
                )
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

    def _writer_unique_kb_findings(
        self,
        detail: RunDetail,
        *,
        competitor: str,
        dimension: str,
        findings: Sequence[str],
    ) -> list[str]:
        source_text_keys = self._writer_source_text_keys(
            detail,
            competitor=competitor,
            dimension=dimension,
        )
        unique: list[str] = []
        seen: set[str] = set()
        for finding in findings:
            key = self._writer_dedupe_text_key(finding)
            if not key or key in seen or key in source_text_keys:
                continue
            unique.append(finding)
            seen.add(key)
        return unique

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
                for item in detail.comparison_matrix.summary
            ],
            "cells": [
                {
                    "competitor": cell.competitor,
                    "dimension": cell.dimension,
                    "value": self._writer_matrix_cell_value(cell),
                    "source_ids": cell.source_ids,
                    "confidence": round(cell.confidence, 3),
                }
                for cell in detail.comparison_matrix.cells
            ],
        }

    def _writer_matrix_summary_item(self, item: str) -> str:
        return item

    def _writer_matrix_cell_value(self, cell: object) -> str:
        return str(getattr(cell, "value", ""))

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
            "problem": issue.problem,
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

    def _ordered_comparison_cells(self, detail: RunDetail) -> list[ComparisonCell]:
        matrix = detail.comparison_matrix
        if matrix is None:
            return []
        ordered_cells: list[ComparisonCell] = []
        seen_indexes: set[int] = set()
        competitors = matrix.competitors or detail.plan.competitors
        dimensions = matrix.dimensions or detail.plan.dimensions
        for competitor in competitors:
            for dimension in dimensions:
                for index, cell in enumerate(matrix.cells):
                    if index in seen_indexes:
                        continue
                    if cell.competitor == competitor and cell.dimension == dimension:
                        ordered_cells.append(cell)
                        seen_indexes.add(index)
        for index, cell in enumerate(matrix.cells):
            if index not in seen_indexes:
                ordered_cells.append(cell)
        return ordered_cells

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

    def _backfill_memory_context_section(self, detail: RunDetail) -> list[str]:
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

    def _backfill_review_theme_section(self, detail: RunDetail) -> list[str]:
        summaries = [
            knowledge.review_summary
            for knowledge in detail.competitor_knowledge.values()
            if self._review_summary_has_content(knowledge.review_summary)
        ]
        needs_review = self._needs_review_theme_section(detail)

        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        lines = ["", f"## {report_label(detail.output_language, 'review_theme_summary')}"]
        if not summaries:
            refs = self._format_source_refs(self._matrix_source_ids(detail))
            if is_zh:
                if needs_review:
                    lines.append(
                        "- 已请求评价、用户或买家维度分析，但尚无可引用的结构化评价主题；"
                        f"相关结论需保留为 Evidence gap。{refs}"
                    )
                else:
                    lines.append(
                        "- 本核心报告节尚无可引用的用户评价主题；"
                        f"不要编造评价结论，需标记为 Evidence gap。{refs}"
                    )
            else:
                if needs_review:
                    lines.append(
                        "- Review, user, or buyer analysis was requested, but no cited review "
                        f"themes are available yet; keep conclusions as Evidence gap.{refs}"
                    )
                else:
                    lines.append(
                        "- This required core report section has no cited user-review themes "
                        f"yet; do not invent review conclusions. Evidence gap.{refs}"
                    )
            return lines

        category_labels = (
            ("Praise", "好评主题", "praise_themes"),
            ("Complaints", "投诉主题", "complaint_themes"),
            ("Adoption blockers", "采用阻碍", "adoption_blockers"),
            ("Switching triggers", "切换触发", "switching_triggers"),
        )
        for summary in summaries[:4]:
            competitor = summary.competitor or "Unknown competitor"
            lines.append(f"### {competitor}")
            if is_zh:
                lines.append(f"- 情绪提示: {summary.sentiment_hint}")
            else:
                lines.append(f"- Sentiment hint: {summary.sentiment_hint}")
            for en_label, zh_label, field_name in category_labels:
                label = zh_label if is_zh else en_label
                items = getattr(summary, field_name)
                for item in items[:2]:
                    refs = self._format_source_refs(item.source_ids or summary.source_ids)
                    evidence = f" - {item.evidence}" if item.evidence else ""
                    gap = " Evidence gap." if item.evidence_gap else ""
                    lines.append(f"- {label}: {item.theme}{evidence}{gap}{refs}")
        return lines

    def _needs_review_theme_section(self, detail: RunDetail) -> bool:
        review_hints = (
            "review",
            "persona",
            "user",
            "customer",
            "buyer",
            "feedback",
        )
        return any(
            any(hint in dimension.casefold().replace("-", "_") for hint in review_hints)
            for dimension in detail.plan.dimensions
        )

    def _review_summary_has_content(self, summary: object) -> bool:
        return any(
            getattr(summary, field_name, None)
            for field_name in (
                "praise_themes",
                "complaint_themes",
                "adoption_blockers",
                "switching_triggers",
            )
        )

    def _backfill_swot_section(self, detail: RunDetail) -> list[str]:
        analyses = [
            knowledge.swot_analysis
            for knowledge in detail.competitor_knowledge.values()
            if self._swot_analysis_has_content(knowledge.swot_analysis)
        ]
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        lines = ["", f"## {report_label(detail.output_language, 'swot_analysis')}"]
        if not analyses:
            if is_zh:
                lines.append("- 优势: 证据缺口（Evidence gap）：尚无可引用的 SWOT 优势证据。")
                lines.append("- 劣势: 证据缺口（Evidence gap）：尚无可引用的 SWOT 劣势证据。")
                lines.append("- 机会: 证据缺口（Evidence gap）：尚无可引用的 SWOT 机会证据。")
                lines.append("- 威胁: 证据缺口（Evidence gap）：尚无可引用的 SWOT 威胁证据。")
            else:
                lines.append(
                    "- Strengths: Evidence gap - no cited SWOT strength is established yet."
                )
                lines.append(
                    "- Weaknesses: Evidence gap - no cited SWOT weakness is established yet."
                )
                lines.append(
                    "- Opportunities: Evidence gap - no cited SWOT opportunity is established yet."
                )
                lines.append(
                    "- Threats: Evidence gap - no cited SWOT threat is established yet."
                )
            return lines

        for analysis in analyses[:4]:
            lines.append(f"### {analysis.competitor or 'Unknown competitor'}")
            if is_zh:
                lines.extend(
                    self._swot_item_lines(
                        "优势",
                        analysis.strengths,
                        gap_text="证据缺口（Evidence gap）。",
                        empty_gap_text="证据缺口（Evidence gap）：尚无可引用条目。",
                    )
                )
                lines.extend(
                    self._swot_item_lines(
                        "劣势",
                        analysis.weaknesses,
                        gap_text="证据缺口（Evidence gap）。",
                        empty_gap_text="证据缺口（Evidence gap）：尚无可引用条目。",
                    )
                )
                lines.extend(
                    self._swot_item_lines(
                        "机会",
                        analysis.opportunities,
                        gap_text="证据缺口（Evidence gap）。",
                        empty_gap_text="证据缺口（Evidence gap）：尚无可引用条目。",
                    )
                )
                lines.extend(
                    self._swot_item_lines(
                        "威胁",
                        analysis.threats,
                        gap_text="证据缺口（Evidence gap）。",
                        empty_gap_text="证据缺口（Evidence gap）：尚无可引用条目。",
                    )
                )
            else:
                lines.extend(self._swot_item_lines("Strengths", analysis.strengths))
                lines.extend(self._swot_item_lines("Weaknesses", analysis.weaknesses))
                lines.extend(self._swot_item_lines("Opportunities", analysis.opportunities))
                lines.extend(self._swot_item_lines("Threats", analysis.threats))
        return lines

    def _swot_analysis_has_content(self, analysis: object) -> bool:
        return any(
            getattr(analysis, field_name, None)
            for field_name in ("strengths", "weaknesses", "opportunities", "threats")
        )

    def _swot_item_lines(
        self,
        label: str,
        items: Sequence[SWOTItem] | Sequence[object],
        *,
        gap_text: str = "Evidence gap.",
        empty_gap_text: str = "Evidence gap - no cited item is established yet.",
    ) -> list[str]:
        if not items:
            return [f"- {label}: {empty_gap_text}"]
        lines: list[str] = []
        for item in items[:2]:
            text = str(getattr(item, "text", "") or "No SWOT item text available.")
            refs = self._format_source_refs(getattr(item, "source_ids", []))
            gap = f" {gap_text}" if getattr(item, "evidence_gap", False) else ""
            lines.append(f"- {label}: {text}{gap}{refs}")
        return lines

    def _backfill_user_research_section(self, detail: RunDetail) -> list[str]:
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
                    "- 已请求用户画像或评论分析，但尚未附加用户研究来源；"
                    "将画像结论保持在证据差距通道中。"
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

    def _backfill_rag_gap_fill_section(self, detail: RunDetail) -> list[str]:
        collector_gaps = [
            issue
            for issue in detail.qa_findings
            if issue.target_agent == "collector" and issue.severity in {"warn", "blocker"}
            and not issue.field_path.startswith("release_gate.")
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
                    f"- 差距：{issue.problem} 目标={target}；"
                    f"竞品={competitor}；重新执行={scope.kind}。"
                    f"建议的检索查询：{query}。{sources}"
                )
            lines.append(
                "- 运行“证据差距填补”操作以检索、重排并附加已证实的证据。"
                "详细差距标识和检索上下文保留在运行审计元数据中。"
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
                    f"- Gap: {issue.problem} Target={target}; "
                    f"competitor={competitor}; redo={scope.kind}. "
                    f"Suggested retrieval query: {query}.{sources}"
                )
            lines.append(
                "- Run the Evidence Gap Fill action to retrieve, rerank, and attach verified "
                "evidence. Detailed gap identifiers and retrieval contexts stay in the run "
                "audit metadata."
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

    def _backfill_claim_validation_section(self, detail: RunDetail) -> list[str]:
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
                    labels.append(
                        f"置信度 {claim.confidence:.2f}"
                        if is_zh
                        else f"confidence {claim.confidence:.2f}"
                    )
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
                    "- No low-confidence or single-source high-risk structured claims were "
                    "detected."
                    f"{self._format_source_refs(self._matrix_source_ids(detail))}"
                )

        for issue in detail.qa_findings[:4]:
            if is_zh:
                lines.append(
                    f"- QA {issue.severity}："
                    f"{self._trim_sentence(issue.problem)}"
                )
            else:
                lines.append(
                    f"- QA {issue.severity}: "
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

    def _markdown_table_cell(self, value: object, *, limit: int | None = None) -> str:
        text = " ".join(str(value or "").split())
        if limit is not None:
            text = self._trim_sentence(text, limit)
        return text.replace("|", "\\|") or "-"

    def _extract_cited_source_ids(self, report_md: str) -> set[str]:
        cited = set(source_tokens(report_md))
        for pattern in (
            r"(?<![-\w])source(?:\s+id)?\s*:\s*([A-Za-z0-9_.:-]+)",
            r"\[source(?:\s+id)?\s+([A-Za-z0-9_.:-]+)\]",
        ):
            cited.update(re.findall(pattern, report_md, flags=re.IGNORECASE))
        return cited

    def _repair_report_source_tokens(self, detail: RunDetail, markdown: str) -> str:
        valid_source_ids = {source.id for source in detail.raw_sources}
        if not valid_source_ids:
            return markdown

        repaired_lines: list[str] = []
        for line in markdown.splitlines():
            repaired_lines.append(
                SOURCE_TOKEN_RE.sub(
                    lambda match, current_line=line: self._repair_report_source_token(
                        detail,
                        current_line,
                        source_token_match_value(match),
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
        if self._report_line_is_explicit_gap_statement(stripped):
            return False
        if CJK_TEXT_RE.search(stripped):
            normalized = stripped.casefold()
            if len(stripped) >= 12 and any(
                token in normalized for token in CLAIM_LINE_TOKENS
            ):
                return True
        return bool(re.search(r"[A-Za-z0-9]", stripped)) and len(stripped) >= 24

    def _report_line_is_explicit_gap_statement(self, line: str) -> bool:
        normalized = line.casefold()
        return any(
            marker in normalized
            for marker in (
                "evidence gap",
                "no cited swot",
                "no cited item",
                "no cited user-review",
                "证据缺口",
                "尚无可引用",
            )
        )

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
                and any(token in normalized for token in PRICING_LINE_TOKENS)
            )
            or (
                dimension == "feature"
                and any(token in normalized for token in FEATURE_LINE_TOKENS)
            )
            or (
                dimension == "persona"
                and any(token in normalized for token in PERSONA_LINE_TOKENS)
            )
        ]

        def unique(ids: list[str]) -> list[str]:
            seen: set[str] = set()
            return [
                source_id for source_id in ids if not (source_id in seen or seen.add(source_id))
            ]

        source_dimensions = {source.id: source.dimension for source in detail.raw_sources}

        def rank_source_ids_by_dimension(ids: list[str], primary_dimension: str) -> list[str]:
            primary_ids = [
                source_id
                for source_id in ids
                if source_dimensions.get(source_id) == primary_dimension
            ]
            other_ids = [
                source_id
                for source_id in ids
                if source_dimensions.get(source_id) != primary_dimension
            ]
            return [*primary_ids, *other_ids]

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
        if "pricing" in matched_dimensions:
            source_ids = rank_source_ids_by_dimension(source_ids, "pricing")
        elif "feature" in matched_dimensions:
            source_ids = rank_source_ids_by_dimension(source_ids, "feature")
        if "persona" in matched_dimensions and not {
            "pricing",
            "feature",
        }.intersection(matched_dimensions):
            source_type_rank = {
                source_type: index
                for index, source_type in enumerate(USER_RESEARCH_SOURCE_TYPE_ORDER)
            }
            preferred_user_research_sources = [
                source
                for source in detail.raw_sources
                if source.id in source_ids and source.source_type in USER_RESEARCH_SOURCE_TYPES
            ]
            preferred_user_research_ids = [
                source.id
                for source in sorted(
                    preferred_user_research_sources,
                    key=lambda source: source_type_rank.get(
                        source.source_type, len(source_type_rank)
                    ),
                )
            ]
            if preferred_user_research_ids:
                source_ids = [*preferred_user_research_ids, *source_ids]
        return unique(source_ids)
