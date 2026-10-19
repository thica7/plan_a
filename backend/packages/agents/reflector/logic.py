from __future__ import annotations

import json
import re
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from packages.identity import stable_prefixed_id
from packages.llm.errors import LLMExecutionLimitError
from packages.orchestrator.evidence_context import EvidenceUseRejectedError
from packages.orchestrator.scoping import assign_redo_scope, build_redo_scope
from packages.schema.api_dto import RunDetail
from packages.schema.models import ComparisonCell, ComparisonMatrix, QCIssue, RedoScope, ReflectionRecord

if TYPE_CHECKING:
    from packages.orchestrator.service import RunRecord


QA_CONFIDENCE_OUTLIER_THRESHOLD = 0.7


def _question_delivery_scope(detail):
    """Recognize a narrow explicit delivery; ambiguity retains comparison gates."""
    from packages.research.question_scope import research_questions
    plan = detail.plan
    brief = plan.decision_brief
    result = {'mode': 'comparison', 'requires_comparison': True}
    if len(plan.competitors) != 1 or brief is None or not brief.decision_question.strip():
        return result
    product = plan.competitors[0].strip().casefold()
    if plan.target_product and plan.target_product.name.strip().casefold() != product:
        return result
    intent = ' '.join([detail.topic, plan.topic, *brief.model_dump().values(),
                      *(plan.target_product.use_cases if plan.target_product else [])])
    if re.search(r'\b(?:compar\w*|rank\w*|versus|vs|PM|better|worse|superior|inferior|outperform\w*)\b|'
                 r'\b(?:more|less)\b.{0,40}\bthan\b|side.by.side|all\s+features|'
                 r'(?:full|complete)\s+(?:analysis|research|report|feature)|'
                 r'竞品|比较|对比|排名|全功能|全维度|(?:完整|全面).{0,8}(?:分析|研究|报告)', intent, re.I):
        return result
    if any(req.intent == 'price_comparison' for req in plan.answer_requirements):
        return result
    questions = [q for dimension in plan.dimensions
                 for q in research_questions(detail, plan.competitors[0], dimension)]
    if not questions or any(not re.search(r'[?？]|是否|能否|如何|哪些|什么|怎样', q['question'])
                            for q in questions):
        return result
    return {'mode': 'single_product_questions', 'requires_comparison': False,
            'question_ids': [q['question_id'] for q in questions]}


def _comparison_gap_inapplicable(detail, finding):
    """Only explicit comparison coverage limitations can be outside question scope.

    Current selected product cells must still be present and cited. Question
    evidence/answers are checked independently by the existing final claim QA.
    Unknown reasons and unsupported conclusions retain their original gate.
    """
    if _question_delivery_scope(detail)['requires_comparison'] or detail.comparison_matrix is None:
        return False
    cells = {(cell.competitor.casefold(), cell.dimension.casefold()): cell
             for cell in detail.comparison_matrix.cells}
    if any((cell := cells.get((product.casefold(), dimension.casefold()))) is None or not cell.source_ids
           for product in detail.plan.competitors for dimension in detail.plan.dimensions):
        return False
    text = finding.casefold()
    if re.search(r'\b(?:question|answer|claim|conclusion|citation|unknown|unverified)\b|'
                 r'问题|未回答|结论|错引|未知', text):
        return False
    # A closed structural grammar keeps mixed findings conservative: appending
    # a missing rule or other unknown clause makes the entire finding applicable.
    structural_reasons = (
        r'feature\s+dimension\s+(?:is\s+marked|assessment\s+status\s+is)\s+'
        r'insufficient_evidence\s*\(gap_count\s*=\s*\d+\),?\s*blocking\s+'
        r'(?:a\s+)?(?:validated|confident)\s+feature\s+comparison\.?',
        r'(?:no|missing)\s+(?:multi|cross)[- ]competitor\s+(?:[a-z]+\s+)?matrix'
        r'(?:\s+exists)?(?:[.;]\s*cross[- ]competitor\s+comparison\s+cannot\s+be\s+produced)?\.?',
    )
    return any(re.fullmatch(pattern, text.strip()) for pattern in structural_reasons)


class ReflectorAgentMixin:
    async def _real_reflector_step(self, record: RunRecord) -> None:
        detail = record.detail
        await self._ensure_analysis_evidence(record)
        view, use, question_packets = await self._begin_question_evidence_use(record, agent="reflector")
        projected, dependency_gaps = self._project_evidence_detail(record, [view])
        coverage = self._producer_coverage_digest(record, view,
            max_bytes=max(0, use.max_bytes - len(view.to_prompt_json().encode("utf-8"))))
        matrix_json = self._bounded_analysis_json(view, coverage, max_bytes=use.max_bytes)
        coverage_capacity_omitted = coverage.get("context_omitted") and coverage.get("matrix_valid")
        coverage_counts = coverage if coverage_capacity_omitted else None
        # A metadata-only projection is authorized by current producer credentials.
        # Its empty values must never be used as original product observations.
        if coverage.get("matrix_status") == "validated" and not coverage.get("context_omitted"):
            projected.comparison_matrix = ComparisonMatrix(
                competitors=detail.plan.competitors, dimensions=detail.plan.dimensions,
                cells=[ComparisonCell(**cell, value="") for cell in coverage["cells"]])
        context_omissions = [gap for gap in dependency_gaps if gap.startswith("Analysis context omitted:")]
        dependency_gaps = [gap for gap in dependency_gaps if gap not in context_omissions]
        question_context_gaps, question_unverified_gaps = [], []
        for packet in self._question_packet_prompt(record, question_packets, view.facts):
            for question in packet['questions']:
                if not question['evidence_gaps']:
                    continue
                context_omitted = question['evidence_gap'] == 'context_budget_exceeded'
                finding = (
                    f"Question {'context omitted' if context_omitted else 'evidence unverified'}: "
                    f"{packet['competitor']} / {packet['dimension']} / {question['question_id']}; "
                    + ', '.join(question['evidence_gaps'])
                    + f"; missing_core_fact_ids={question['missing_core_fact_ids']}; "
                    f"missing_exception_fact_ids={question['missing_exception_fact_ids']}."
                )
                (question_context_gaps if context_omitted else question_unverified_gaps).append(finding)
        baseline = self._analysis_artifacts_hash(detail)
        detail.current_node = "reflector"
        self._consume_queued_agent_messages(
            record,
            to_agent="reflector",
            consumer_agent="reflector",
            message_types={"comparison_matrix_ready", "decision_card_bundle_ready"},
        )
        await self.emit(detail.id, "node_started", "reflector", None, "Calling reflector.")
        fallback: dict[str, object] = {"used": False, "deterministic_fallback": False}
        from packages.schema.decision_brief import decision_brief_prompt_context
        delivery_scope = _question_delivery_scope(detail)
        try:
            payload = await self._trace_question_llm_json(
                record, evidence_view=view, evidence_use=use, question_packets=question_packets,
                agent="reflector",
                subagent=None,
                name="coverage_reflection",
                system=(
                    "You are a reflector. Find coverage gaps before QA. Be strict but concise. "
                    "producer_coverage_only contains current verified producer references and coverage metadata, "
                    "not original fact text. omitted_fact_count and context_budget_exceeded mean collected "
                    "material was not sent in this small view; never turn them into collection or matrix gaps. "
                    "Assessment status and gap_count retain unresolved comparison limitations; do not infer a winner. "
                    "Assess coverage against the decision brief and delivery_scope. Explicit single-product "
                    "questions do not require additional competitors or an exhaustive feature comparison. "
                    "Question evidence packets bind each question to complete originals in Evidence View JSON. "
                    "Review each actual question against its supplied rules and all prerequisites. "
                    "A published limit or access scope can answer a requested quantity or domain without "
                    "repeating the user value; a logical negative need not be stated a second time verbatim. "
                    "Do not require the source to repeat the question. Missing packet originals are context "
                    "omissions, not proof that all collected sources lack the rule. Unknown findings, "
                    "unavailable sources and genuinely missing rules still require review and blocking as needed. "
                    "Still report missing evidence for the actual questions and unsupported conclusions. "
                    "Treat comparison-matrix cells with source_ids across every competitor and "
                    "dimension as side-by-side comparison coverage; only report "
                    "cross_competitor_gaps when the matrix lacks cells, source_ids, or aligned "
                    "dimension coverage. Only report confidence_outliers for cells below the "
                    f"QA confidence threshold {QA_CONFIDENCE_OUTLIER_THRESHOLD:.2f}."
                ),
                user=(
                    decision_brief_prompt_context(detail.plan.decision_brief)
                    + f"Delivery scope: {json.dumps(delivery_scope, ensure_ascii=False)}\n"
                    + f"Competitors: {', '.join(detail.plan.competitors)}\n"
                    f"Dimensions: {', '.join(detail.plan.dimensions)}\n"
                    f"Comparison Matrix JSON: "
                    f"{matrix_json}\n"
                    f"Evidence View JSON: {view.to_prompt_json()}\n"
                    f"Analysis dependency gaps: {json.dumps(dependency_gaps, ensure_ascii=False)}"
                ),
                schema_hint='{"coverage_gaps":["gap"],"confidence_outliers":["outlier"],"cross_competitor_gaps":["gap"],'
                '"suggested_redo_dimension":"dimension or null","gate_status":"pass|warn|block",'
                '"blocking_gaps":["gap"],"writer_constraints":["constraint"]}',
            )
            list_fields = ('coverage_gaps', 'confidence_outliers', 'cross_competitor_gaps',
                           'blocking_gaps', 'writer_constraints')
            if (not any(field in payload for field in list_fields)
                    or any(not isinstance(payload[field], list)
                           or any(not isinstance(item, str) for item in payload[field])
                           for field in list_fields if field in payload)
                    or ('gate_status' in payload and payload['gate_status'] not in {'pass', 'warn', 'block'})):
                raise ValueError('invalid_structured_payload')
        except EvidenceUseRejectedError:
            raise
        except Exception as exc:  # noqa: BLE001 - deterministic reflection keeps the run alive.
            payload = self._deterministic_reflector_payload(projected, producer_coverage=coverage_counts)
            fallback = {
                "used": True,
                "reason": str(exc) if isinstance(exc, LLMExecutionLimitError) or str(exc) == "invalid_structured_payload" else "llm_error",
                "deterministic_fallback": True,
                "error": str(exc),
            }
        module_status = "fallback" if fallback.get("used") else "llm"
        coverage_gaps = [
            *self._string_list(payload.get("coverage_gaps")),
            *dependency_gaps,
            *question_context_gaps,
            *question_unverified_gaps,
            *(
                f"Evidence gap: {gap.reason} ({gap.source_id or gap.fact_id or 'coverage'})"
                for gap in view.gaps if gap.reason != "context_budget_exceeded"
            ),
        ]
        confidence_outliers = self._string_list(payload.get("confidence_outliers"))
        cross_competitor_gaps = self._string_list(payload.get("cross_competitor_gaps"))
        if coverage_counts and coverage_counts["confidence_min"] < QA_CONFIDENCE_OUTLIER_THRESHOLD:
            confidence_outliers = self._unique_strings([*confidence_outliers,
                f"Matrix cell confidence {coverage_counts['confidence_min']:.2f} is below {QA_CONFIDENCE_OUTLIER_THRESHOLD:.2f}."])
        suggested_dimension = payload.get("suggested_redo_dimension")
        suggested_redos = []
        if isinstance(suggested_dimension, str) and suggested_dimension in detail.plan.dimensions:
            suggested_redos.append(
                RedoScope(
                    kind="collector",
                    target_subagent=suggested_dimension,
                    rationale=f"Reflector suggested more {suggested_dimension} evidence.",
                )
            )
        gate_status, blocking_gaps = self._reflection_gate(
            projected,
            coverage_gaps=coverage_gaps,
            confidence_outliers=confidence_outliers,
            cross_competitor_gaps=cross_competitor_gaps,
            llm_gate_status=payload.get("gate_status"),
            llm_blocking_gaps=self._string_list(payload.get("blocking_gaps")),
            producer_coverage=coverage_counts,
        )
        if coverage_capacity_omitted and gate_status == "pass":
            # Incomplete context raises the minimum status; it never lowers a block.
            gate_status = "warn"
        if question_unverified_gaps:
            gate_status = 'block'
            blocking_gaps = self._unique_strings([*blocking_gaps, *question_unverified_gaps])[:5]
        writer_constraints = self._reflection_writer_constraints(
            gate_status=gate_status,
            blocking_gaps=blocking_gaps,
            llm_constraints=[
                *(["Keep affected question answers unverified until the original context is restored: "
                   + ' '.join(question_context_gaps)
                   + " Do not infer that all collected sources lack the rule."] if question_context_gaps else []),
                *self._string_list(payload.get("writer_constraints")),
                *(["Some collected original facts were omitted from this view; preserve producer limitations."]
                  if context_omissions else []),
                *(["Producer coverage exceeds context capacity; coverage review remains incomplete."]
                  if coverage_capacity_omitted else [])],
        )
        self._validate_evidence_use(record, use)
        if coverage != self._producer_coverage_digest(record, view,
                max_bytes=max(0, use.max_bytes - len(view.to_prompt_json().encode("utf-8")))):
            raise EvidenceUseRejectedError("Reflector producer coverage changed before commit")
        if baseline != self._analysis_artifacts_hash(detail):
            raise EvidenceUseRejectedError("Reflector analysis artifacts changed before commit")
        detail.reflections.append(
            ReflectionRecord(
                iteration=1,
                coverage_gaps=coverage_gaps,
                confidence_outliers=confidence_outliers,
                cross_competitor_gaps=cross_competitor_gaps,
                suggested_redos=suggested_redos,
                gate_status=gate_status,
                blocking_gaps=blocking_gaps,
                writer_constraints=writer_constraints,
            )
        )
        self._record_evidence_artifact(record, kind="reflector", uses=[use],
            payload=detail.reflections[-1].model_dump(mode="json"))
        self._append_agent_message(
            record,
            from_agent="reflector",
            to_agent="writer",
            message_type="reflection_ready",
            payload_schema="ReflectionRecord",
            payload={
                "reflection": detail.reflections[-1].model_dump(mode="json"),
                "module_status": module_status,
                "fallback": fallback,
            },
        )
        detail.updated_at = datetime.utcnow()
        await self.emit(
            detail.id,
            "node_completed",
            "reflector",
            None,
            (
                "Reflector completed with deterministic fallback."
                if module_status == "fallback"
                else "Reflector completed."
            ),
            {
                "reflection": {
                    **payload,
                    "gate_status": gate_status,
                    "blocking_gaps": blocking_gaps,
                    "writer_constraints": writer_constraints,
                },
                "fallback": fallback,
                "module_status": module_status,
            },
        )

        self._finish_delivery_phase(record, 'reflector', None)

    @staticmethod
    def _coverage_metadata_blockers(coverage):
        """Local structure checks consume verified counts, never unsent fact values."""
        gaps = []
        if coverage["missing_cell_count"]:
            gaps.append(f"Missing comparison cell count: {coverage['missing_cell_count']} (verified producer metadata).")
        if coverage["uncited_cell_count"]:
            gaps.append(f"Missing comparison cell source_ids: {coverage['uncited_cell_count']} cell(s) has no source_ids.")
        if coverage["unavailable_count"]:
            gaps.append(f"Analysis dependency unavailable count: {coverage['unavailable_count']}; reanalyse.")
        return gaps

    def _reflection_gate(
        self,
        detail: RunDetail,
        *,
        coverage_gaps: list[str],
        confidence_outliers: list[str],
        cross_competitor_gaps: list[str],
        llm_gate_status: object,
        llm_blocking_gaps: list[str],
        producer_coverage=None,
    ) -> tuple[Literal["pass", "warn", "block"], list[str]]:
        original_llm_gaps = llm_blocking_gaps
        llm_blocking_gaps = [gap for gap in llm_blocking_gaps if not _comparison_gap_inapplicable(detail, gap)]
        coverage_gaps = [gap for gap in coverage_gaps if not _comparison_gap_inapplicable(detail, gap)]
        cross_competitor_gaps = [gap for gap in cross_competitor_gaps
                                 if not _comparison_gap_inapplicable(detail, gap)]
        if llm_gate_status == 'block' and original_llm_gaps and not llm_blocking_gaps:
            llm_gate_status = 'warn'
        blocking_gaps: list[str] = []
        if producer_coverage is not None:
            blocking_gaps.extend(self._coverage_metadata_blockers(producer_coverage))
        elif detail.comparison_matrix is None:
            blocking_gaps.append("Comparison matrix is missing before writing.")
        else:
            cells_by_key = {
                (cell.competitor.casefold(), cell.dimension.casefold()): cell
                for cell in detail.comparison_matrix.cells
            }
            for dimension in detail.plan.dimensions:
                for competitor in detail.plan.competitors:
                    cell = cells_by_key.get(
                        (competitor.casefold(), dimension.casefold())
                    )
                    if cell is None:
                        blocking_gaps.append(
                            f"Missing comparison cell for {competitor} / {dimension}."
                        )
                        continue
                    if not cell.source_ids:
                        blocking_gaps.append(
                            f"Comparison cell for {competitor} / {dimension} has no source_ids."
                        )

        for finding in [*cross_competitor_gaps, *coverage_gaps, *llm_blocking_gaps]:
            normalized = finding.casefold()
            is_blocking_gap = any(
                token in normalized
                for token in (
                    "comparison matrix is missing",
                    "missing comparison matrix",
                    "missing comparison cell",
                    "lacks cells",
                    "has no source_ids",
                    "has no source ids",
                )
            )
            if is_blocking_gap:
                blocking_gaps.append(finding)

        blocking_gaps = self._unique_strings(blocking_gaps)[:5]
        if blocking_gaps:
            return "block", blocking_gaps
        if llm_gate_status == "block":
            if producer_coverage is not None and not llm_blocking_gaps:
                llm_blocking_gaps = [*coverage_gaps, *cross_competitor_gaps, *confidence_outliers] or [
                    "Reflector explicitly blocked coverage; the blocking reason still requires review."]
            return "block", self._unique_strings(llm_blocking_gaps)[:5]
        if (
            llm_gate_status == "warn"
            or coverage_gaps
            or confidence_outliers
            or cross_competitor_gaps
        ):
            return "warn", []
        return "pass", []

    def _reflection_writer_constraints(
        self,
        *,
        gate_status: Literal["pass", "warn", "block"],
        blocking_gaps: list[str],
        llm_constraints: list[str],
    ) -> list[str]:
        constraints = [
            "Use comparison_matrix.winner_by_dimension as the only winner source; "
            "do not recompute winners from raw sources.",
            "Cite only source IDs provided by the report brief/source registry.",
        ]
        if gate_status == "block":
            constraints.append(
                "Treat this as draft-only until blocking coverage gaps are resolved; "
                "do not present definitive recommendations."
            )
        elif gate_status == "warn":
            constraints.append(
                "Surface coverage or confidence gaps in claim risk, RAG gap fill, "
                "or next collection sections."
            )
        for gap in blocking_gaps:
            constraints.append(f"Do not overstate conclusions affected by: {gap}")
        constraints.extend(llm_constraints)
        return self._unique_strings(constraints)[:8]

    def _unique_strings(self, values: list[str]) -> list[str]:
        unique: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = " ".join(str(value or "").split())
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            unique.append(text)
        return unique

    def _deterministic_reflector_payload(self, detail: RunDetail, *, producer_coverage=None) -> dict[str, object]:
        if producer_coverage is not None:
            return {"coverage_gaps": [], "confidence_outliers": [],
                    "cross_competitor_gaps": self._coverage_metadata_blockers(producer_coverage),
                    "suggested_redo_dimension": None}
        coverage_gaps: list[str] = []
        confidence_outliers: list[str] = []
        cross_competitor_gaps: list[str] = []
        matrix = detail.comparison_matrix
        if matrix is None:
            cross_competitor_gaps.append("Comparison matrix is missing before reflection.")
        else:
            cells_by_key = {
                (cell.competitor.casefold(), cell.dimension.casefold()): cell
                for cell in matrix.cells
            }
            for dimension in detail.plan.dimensions:
                for competitor in detail.plan.competitors:
                    cell = cells_by_key.get((competitor.casefold(), dimension.casefold()))
                    if cell is None:
                        cross_competitor_gaps.append(
                            f"Missing comparison cell for {competitor} / {dimension}."
                        )
                        continue
                    if not cell.source_ids:
                        coverage_gaps.append(
                            f"Comparison cell for {competitor} / {dimension} has no source_ids."
                        )
                    if cell.confidence < QA_CONFIDENCE_OUTLIER_THRESHOLD:
                        confidence_outliers.append(
                            f"{competitor} / {dimension} confidence {cell.confidence:.2f} "
                            f"is below {QA_CONFIDENCE_OUTLIER_THRESHOLD:.2f}."
                        )
        return {
            "coverage_gaps": coverage_gaps[:5],
            "confidence_outliers": confidence_outliers[:5],
            "cross_competitor_gaps": cross_competitor_gaps[:5],
            "suggested_redo_dimension": None,
        }

    def _build_reflector_qa_issues(self, detail: RunDetail) -> list[QCIssue]:
        if not detail.reflections:
            return []

        latest = detail.reflections[-1]
        issues: list[QCIssue] = []
        surfaced_findings = {
            *latest.coverage_gaps,
            *latest.confidence_outliers,
            *latest.cross_competitor_gaps,
        }
        blocking_only_gaps = [
            gap for gap in latest.blocking_gaps if gap not in surfaced_findings
        ]
        groups = [
            ("blocking", blocking_only_gaps, "collector", "reflections[-1].blocking_gaps"),
            ("coverage", latest.coverage_gaps, "collector", "reflections[-1].coverage_gaps"),
            (
                "confidence",
                latest.confidence_outliers,
                "collector",
                "reflections[-1].confidence_outliers",
            ),
            (
                "cross-competitor",
                latest.cross_competitor_gaps,
                "comparator",
                "reflections[-1].cross_competitor_gaps",
            ),
        ]
        for group_name, findings, target_agent, field_path in groups:
            for index, finding in enumerate(findings[:5], start=1):
                if not finding.strip():
                    continue
                if _comparison_gap_inapplicable(detail, finding):
                    continue
                if group_name == "confidence" and self._confidence_outlier_is_below_threshold(
                    detail, finding
                ) is False:
                    continue
                dimension = self._infer_dimension_from_text(detail, finding)
                competitor = self._infer_competitor_from_text(detail, finding)
                issue_target_agent = (
                    self._blocking_gap_target_agent(finding)
                    if group_name == "blocking"
                    else target_agent
                )
                issue = QCIssue(
                    id=stable_prefixed_id(
                        "qc-issue",
                        "reflector",
                        group_name,
                        index,
                        finding,
                        length=16,
                    ),
                    severity=("blocker" if finding in latest.blocking_gaps else "warn"),
                    detected_by="reflector",
                    target_agent=issue_target_agent,
                    target_subagent=dimension,
                    target_competitor=competitor
                    if issue_target_agent in {"collector", "analyst"}
                    else None,
                    field_path=f"{field_path}[{index - 1}]",
                    problem=finding,
                    redo_scope=build_redo_scope(
                        detected_by="reflector",
                        target_agent=issue_target_agent,
                        target_subagent=dimension,
                        target_competitor=competitor
                        if issue_target_agent in {"collector", "analyst"}
                        else None,
                        field_path=f"{field_path}[{index - 1}]",
                        problem=finding,
                    ),
                    self_found=True,
                )
                if issue_target_agent in {"collector", "analyst"} and dimension is None:
                    issue.redo_scope = RedoScope(kind="full", rationale=finding)
                else:
                    issue.redo_scope = assign_redo_scope(issue)
                issues.append(issue)
        return issues

    def _blocking_gap_target_agent(self, finding: str) -> str:
        normalized = finding.casefold()
        if any(
            token in normalized
            for token in (
                "comparison matrix is missing",
                "missing comparison matrix",
                "missing comparison cell",
                "lacks cells",
            )
        ):
            return "comparator"
        return "collector"

    def _confidence_outlier_is_below_threshold(self, detail: RunDetail, text: str) -> bool:
        normalized = text.casefold()
        if not any(
            token in normalized
            for token in ("low confidence", "below", "under", "threshold")
        ):
            return True
        values = [
            float(value)
            for value in re.findall(r"(?<!\d)(?:0(?:\.\d+)?|1(?:\.0+)?)(?!\d)", text)
        ]
        confidence_values = [value for value in values if 0.0 <= value <= 1.0]
        if confidence_values and min(confidence_values) < QA_CONFIDENCE_OUTLIER_THRESHOLD:
            return True

        mentioned_dimensions = [
            dimension
            for dimension in detail.plan.dimensions
            if dimension.casefold() in normalized
        ]
        mentioned_competitors = [
            competitor
            for competitor in detail.plan.competitors
            if competitor.casefold() in normalized
        ]
        matrix = detail.comparison_matrix
        if matrix is None:
            return not confidence_values
        cells = [
            cell
            for cell in matrix.cells
            if (
                not mentioned_dimensions
                or cell.dimension.casefold()
                in {dimension.casefold() for dimension in mentioned_dimensions}
            )
            and (
                not mentioned_competitors
                or cell.competitor.casefold()
                in {competitor.casefold() for competitor in mentioned_competitors}
            )
        ]
        if not cells:
            return not confidence_values
        return min(cell.confidence for cell in cells) < QA_CONFIDENCE_OUTLIER_THRESHOLD

    def _infer_dimension_from_text(self, detail: RunDetail, text: str) -> str | None:
        normalized = text.casefold()
        for dimension in detail.plan.dimensions:
            if dimension.casefold() in normalized:
                return dimension
        return None

    def _reflector_matrix_digest(self, detail: RunDetail, *, evidence_view=None) -> dict[str, object]:
        if detail.comparison_matrix is None:
            return {"winner_by_dimension": {}, "summary": [], "cells": []}
        return {
            "winner_by_dimension": detail.comparison_matrix.winner_by_dimension,
            "summary": detail.comparison_matrix.summary,
            "cells": [
                {
                    "competitor": cell.competitor,
                    "dimension": cell.dimension,
                    "source_ids": cell.source_ids,
                    "confidence": round(cell.confidence, 3),
                    **({"evidence_fact_refs": [f.id for f in evidence_view.facts
                         if f.competitor == cell.competitor and f.dimension == cell.dimension]}
                       if evidence_view is not None else
                       {"value": self._reflector_matrix_cell_value(cell.dimension, cell.value)}),
                }
                for cell in detail.comparison_matrix.cells
            ],
        }

    def _reflector_matrix_cell_value(self, dimension: str, value: str) -> str:
        return value

    def _infer_competitor_from_text(self, detail: RunDetail, text: str) -> str | None:
        normalized = text.casefold()
        for competitor in sorted(detail.plan.competitors, key=len, reverse=True):
            if competitor.casefold() in normalized:
                return competitor
        return None
