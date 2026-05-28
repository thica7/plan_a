from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

from packages.orchestrator.scoping import assign_redo_scope
from packages.schema.api_dto import RunDetail
from packages.schema.models import QCIssue, RedoScope, ReflectionRecord

if TYPE_CHECKING:
    from packages.orchestrator.service import RunRecord


class ReflectorAgentMixin:
    async def _real_reflector_step(self, record: RunRecord) -> None:
        detail = record.detail
        detail.current_node = "reflector"
        self._consume_queued_agent_messages(
            record,
            to_agent="reflector",
            consumer_agent="reflector",
            message_types={"comparison_matrix_ready"},
        )
        await self.emit(detail.id, "node_started", "reflector", None, "Calling reflector.")
        payload = await self._trace_llm_json(
            record,
            agent="reflector",
            subagent=None,
            name="coverage_reflection",
            system="You are a reflector. Find coverage gaps before QA. Be strict but concise.",
            user=(
                f"Competitors: {', '.join(detail.plan.competitors)}\n"
                f"Dimensions: {', '.join(detail.plan.dimensions)}\n"
                f"Source digest JSON: "
                f"{json.dumps(self._source_digest(detail.raw_sources), ensure_ascii=False)}"
            ),
            schema_hint='{"coverage_gaps":["gap"],"confidence_outliers":["outlier"],"cross_competitor_gaps":["gap"],'
            '"suggested_redo_dimension":"dimension or null"}',
        )
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
            payload={"reflection": detail.reflections[-1].model_dump(mode="json")},
        )
        detail.updated_at = datetime.utcnow()
        await self.emit(
            detail.id,
            "node_completed",
            "reflector",
            None,
            "Reflector completed.",
            {"reflection": payload},
        )

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
                dimension = self._infer_dimension_from_text(detail, finding)
                competitor = self._infer_competitor_from_text(detail, finding)
                issue = QCIssue(
                    id=f"reflector-{group_name}-{index}-{self._issue_id_fragment(finding)[:48]}",
                    severity="warn",
                    detected_by="reflector",
                    target_agent=target_agent,
                    target_subagent=dimension,
                    target_competitor=competitor
                    if target_agent in {"collector", "analyst"}
                    else None,
                    field_path=f"{field_path}[{index - 1}]",
                    problem=finding,
                    redo_scope=RedoScope(kind="full", rationale="placeholder"),
                    self_found=True,
                )
                if target_agent in {"collector", "analyst"} and dimension is None:
                    issue.redo_scope = RedoScope(kind="full", rationale=finding)
                else:
                    issue.redo_scope = assign_redo_scope(issue)
                issues.append(issue)
        return issues

    def _infer_dimension_from_text(self, detail: RunDetail, text: str) -> str | None:
        normalized = text.casefold()
        for dimension in detail.plan.dimensions:
            if dimension.casefold() in normalized:
                return dimension
        return None

    def _infer_competitor_from_text(self, detail: RunDetail, text: str) -> str | None:
        normalized = text.casefold()
        for competitor in sorted(detail.plan.competitors, key=len, reverse=True):
            if competitor.casefold() in normalized:
                return competitor
        return None
