from __future__ import annotations

import json
import re
from datetime import datetime
from typing import TYPE_CHECKING

from packages.identity import stable_prefixed_id
from packages.orchestrator.scoping import assign_redo_scope, build_redo_scope
from packages.schema.api_dto import RunDetail
from packages.schema.models import QCIssue, RedoScope, ReflectionRecord

if TYPE_CHECKING:
    from packages.orchestrator.service import RunRecord


QA_CONFIDENCE_OUTLIER_THRESHOLD = 0.7


class ReflectorAgentMixin:
    async def _real_reflector_step(self, record: RunRecord) -> None:
        detail = record.detail
        detail.current_node = "reflector"
        self._consume_queued_agent_messages(
            record,
            to_agent="reflector",
            consumer_agent="reflector",
            message_types={"comparison_matrix_ready", "decision_card_bundle_ready"},
        )
        await self.emit(detail.id, "node_started", "reflector", None, "Calling reflector.")
        fallback: dict[str, object] = {"used": False, "deterministic_fallback": False}
        try:
            payload = await self._trace_llm_json(
                record,
                agent="reflector",
                subagent=None,
                name="coverage_reflection",
                system=(
                    "You are a reflector. Find coverage gaps before QA. Be strict but concise. "
                    "Treat comparison-matrix cells with source_ids across every competitor and "
                    "dimension as side-by-side comparison coverage; only report "
                    "cross_competitor_gaps when the matrix lacks cells, source_ids, or aligned "
                    "dimension coverage. Only report confidence_outliers for cells below the "
                    f"QA confidence threshold {QA_CONFIDENCE_OUTLIER_THRESHOLD:.2f}."
                ),
                user=(
                    f"Competitors: {', '.join(detail.plan.competitors)}\n"
                    f"Dimensions: {', '.join(detail.plan.dimensions)}\n"
                    f"Comparison Matrix JSON: "
                    f"{json.dumps(self._reflector_matrix_digest(detail), ensure_ascii=False)}\n"
                    f"Source digest JSON: "
                    f"{json.dumps(self._source_digest(detail.raw_sources), ensure_ascii=False)}"
                ),
                schema_hint='{"coverage_gaps":["gap"],"confidence_outliers":["outlier"],"cross_competitor_gaps":["gap"],'
                '"suggested_redo_dimension":"dimension or null"}',
            )
        except Exception as exc:  # noqa: BLE001 - deterministic reflection keeps the run alive.
            payload = self._deterministic_reflector_payload(detail)
            fallback = {
                "used": True,
                "reason": "llm_error",
                "deterministic_fallback": True,
                "error": str(exc),
            }
        module_status = "fallback" if fallback.get("used") else "llm"
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
        detail.reflections.append(
            ReflectionRecord(
                iteration=1,
                coverage_gaps=self._string_list(payload.get("coverage_gaps")),
                confidence_outliers=self._string_list(payload.get("confidence_outliers")),
                cross_competitor_gaps=self._string_list(payload.get("cross_competitor_gaps")),
                suggested_redos=suggested_redos,
            )
        )
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
            {"reflection": payload, "fallback": fallback, "module_status": module_status},
        )

    def _deterministic_reflector_payload(self, detail: RunDetail) -> dict[str, object]:
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
        groups = [
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
                if group_name == "confidence" and self._confidence_outlier_is_below_threshold(
                    detail, finding
                ) is False:
                    continue
                dimension = self._infer_dimension_from_text(detail, finding)
                competitor = self._infer_competitor_from_text(detail, finding)
                issue = QCIssue(
                    id=stable_prefixed_id(
                        "qc-issue",
                        "reflector",
                        group_name,
                        index,
                        finding,
                        length=16,
                    ),
                    severity="warn",
                    detected_by="reflector",
                    target_agent=target_agent,
                    target_subagent=dimension,
                    target_competitor=competitor
                    if target_agent in {"collector", "analyst"}
                    else None,
                    field_path=f"{field_path}[{index - 1}]",
                    problem=finding,
                    redo_scope=build_redo_scope(
                        detected_by="reflector",
                        target_agent=target_agent,
                        target_subagent=dimension,
                        target_competitor=competitor
                        if target_agent in {"collector", "analyst"}
                        else None,
                        field_path=f"{field_path}[{index - 1}]",
                        problem=finding,
                    ),
                    self_found=True,
                )
                if target_agent in {"collector", "analyst"} and dimension is None:
                    issue.redo_scope = RedoScope(kind="full", rationale=finding)
                else:
                    issue.redo_scope = assign_redo_scope(issue)
                issues.append(issue)
        return issues

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

    def _reflector_matrix_digest(self, detail: RunDetail) -> dict[str, object]:
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
                    "value": self._reflector_matrix_cell_value(cell.dimension, cell.value),
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
