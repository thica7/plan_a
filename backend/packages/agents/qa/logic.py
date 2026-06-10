from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from packages.identity import stable_prefixed_id
from packages.orchestrator.scoping import assign_redo_scope, build_redo_scope
from packages.research.evidence import publishable_text_noise_problem
from packages.schema.api_dto import RunDetail
from packages.schema.models import (
    CompetitorKnowledge,
    KnowledgeClaim,
    QCIssue,
    RedoScope,
)
from packages.sources import (
    malformed_source_tokens,
    resolve_source_token,
    source_token_alias_map,
)

CORE_SCHEMA_DIMENSIONS = ("pricing", "feature", "persona")

if TYPE_CHECKING:
    from packages.orchestrator.service import RunRecord


class QualityAgentMixin:
    def _initial_redo_scope(
        self,
        *,
        detected_by: str,
        target_agent: str,
        field_path: str,
        problem: str,
        target_subagent: str | None = None,
        target_competitor: str | None = None,
    ) -> RedoScope:
        return build_redo_scope(
            detected_by=detected_by,
            target_agent=target_agent,
            target_subagent=target_subagent,
            target_competitor=target_competitor,
            field_path=field_path,
            problem=problem,
        )

    async def _real_phase_qa_step(
        self, record: RunRecord, phase: Literal["collect", "analyst"]
    ) -> None:
        detail = record.detail
        detail.current_node = "qa"
        self._consume_queued_agent_messages(
            record,
            to_agent="qa",
            consumer_agent="qa",
            message_types={
                "collect_join_completed" if phase == "collect" else "analyst_join_completed"
            },
        )
        await self.emit(
            detail.id,
            "node_started",
            "qa",
            phase,
            f"Running {phase} checkpoint QA.",
        )
        if phase == "collect":
            issues = self._build_collect_qa_issues(detail)
        else:
            issues = self._build_collect_qa_issues(detail)
            issues.extend(self._build_analyst_qa_issues(detail, self._missing_dimensions(detail)))
        detail.qa_findings = issues
        self._refresh_quality_metrics(detail)
        if issues:
            next_agent = "redo_router"
        elif phase == "collect":
            next_agent = "analyst_dispatch"
        else:
            next_agent = "comparator"
        self._append_agent_message(
            record,
            from_agent="qa",
            to_agent=next_agent,
            message_type=f"{phase}_qa_result",
            payload_schema="QCIssue[]",
            payload={
                "phase": phase,
                "qa_findings": [issue.model_dump(mode="json") for issue in issues],
            },
        )
        for issue in issues:
            await self.emit(
                detail.id,
                "qa_issue",
                "qa",
                phase,
                issue.problem,
                {"issue": issue.model_dump(mode="json"), "phase": phase},
            )
        detail.updated_at = datetime.utcnow()
        await self.emit(
            detail.id,
            "node_completed",
            "qa",
            phase,
            f"{phase.title()} checkpoint QA completed with {len(issues)} issue(s).",
        )

    def _phase_has_blockers(self, record: RunRecord, phase: Literal["collect", "analyst"]) -> bool:
        return bool(self._blocking_phase_issues(record.detail, phase))

    def _route_phase_qa(
        self, state: dict[str, object], phase: Literal["collect", "analyst"]
    ) -> str:
        record = self._runs[str(state["run_id"])]
        detail = record.detail
        blockers = self._blocking_phase_issues(detail, phase)
        if not blockers:
            detail.qa_findings = []
            detail.updated_at = datetime.utcnow()
            self._persist_run(detail.id)
            return "pass"

        attempt_key = "collect_qa_attempts" if phase == "collect" else "analyst_qa_attempts"
        attempts = int(state.get(attempt_key, 0) or 0)
        if attempts >= detail.max_iterations:
            detail.status = "failed"
            detail.current_node = f"{phase}_qa"
            detail.updated_at = datetime.utcnow()
            self._persist_run(detail.id)
            return "fail"

        dimensions = self._issue_dimensions(detail, blockers)
        target_competitors = self._issue_target_competitors(detail, blockers)
        if phase == "collect":
            if target_competitors:
                detail.raw_sources = [
                    source
                    for source in detail.raw_sources
                    if not (
                        source.dimension in dimensions
                        and any(
                            self._source_matches_competitor(source, competitor)
                            for competitor in target_competitors
                        )
                    )
                ]
            else:
                detail.raw_sources = [
                    source for source in detail.raw_sources if source.dimension not in dimensions
                ]
        for dimension in dimensions:
            if target_competitors:
                for competitor in target_competitors:
                    self._clear_competitor_dimension_output(detail, competitor, dimension)
            else:
                self._clear_dimension_outputs(detail, dimension)
        detail.comparison_matrix = None
        detail.reflections = []
        detail.updated_at = datetime.utcnow()
        self._persist_run(detail.id)
        return "retry"

    def _blocking_phase_issues(
        self,
        detail: RunDetail,
        phase: Literal["collect", "analyst"],
    ) -> list[QCIssue]:
        target_agent = "collector" if phase == "collect" else "analyst"
        return [
            issue
            for issue in detail.qa_findings
            if issue.severity == "blocker" and issue.target_agent == target_agent
        ]

    def _issue_dimensions(self, detail: RunDetail, issues: list[QCIssue]) -> set[str]:
        dimensions = {
            issue.target_subagent
            for issue in issues
            if issue.target_subagent in detail.plan.dimensions
        }
        return set(dimensions) or set(detail.plan.dimensions)

    def _issue_target_competitors(self, detail: RunDetail, issues: list[QCIssue]) -> set[str]:
        competitors = {
            issue.target_competitor
            for issue in issues
            if issue.target_competitor in detail.plan.competitors
        }
        return set(competitors)

    async def _real_qa_step(self, record: RunRecord) -> None:
        detail = record.detail
        detail.current_node = "qa"
        self._consume_queued_agent_messages(
            record,
            to_agent="qa",
            consumer_agent="qa",
            message_types={"report_ready"},
        )
        await self.emit(detail.id, "node_started", "qa", None, "Running deterministic QA.")
        issues = self._build_qa_issues(detail)
        detail.qa_findings = issues
        self._refresh_quality_metrics(detail)
        self._sync_report_with_final_qa(detail)
        self._append_agent_message(
            record,
            from_agent="qa",
            to_agent="redo_router" if issues else "orchestrator",
            message_type="final_qa_result",
            payload_schema="QCIssue[]",
            payload={"qa_findings": [issue.model_dump(mode="json") for issue in issues]},
        )
        for issue in issues:
            await self.emit(
                detail.id,
                "qa_issue",
                "qa",
                None,
                issue.problem,
                {"issue": issue.model_dump(mode="json")},
            )
        detail.updated_at = datetime.utcnow()
        await self.emit(
            detail.id,
            "node_completed",
            "qa",
            None,
            f"QA completed with {len(issues)} issue(s).",
        )

    async def _real_qa_hitl_step(self, record: RunRecord) -> dict[str, object]:
        detail = record.detail
        detail.current_node = "qa_hitl"
        await self.emit(detail.id, "node_started", "hitl", "qa", "QA HITL checkpoint reached.")
        decision = await self._maybe_interrupt(
            record,
            stage="qa",
            message="QA findings are ready for review.",
            payload={
                "qa_findings": [issue.model_dump(mode="json") for issue in detail.qa_findings]
            },
        )
        if decision.decision == "force_pass":
            detail.qa_findings = []
            detail.updated_at = datetime.utcnow()
            await self.emit(
                detail.id,
                "node_completed",
                "qa",
                None,
                "QA findings force-passed by reviewer.",
                {"decision": decision.model_dump(exclude_none=True)},
            )
            route_state: dict[str, object] = {"redo_kind": "end"}
        elif decision.decision == "redo":
            route_state = await self._prepare_graph_redo_from_qa(record)
        else:
            route_state = {"redo_kind": "end"}
        await self.emit(
            detail.id,
            "node_completed",
            "hitl",
            "qa",
            f"QA HITL checkpoint completed with {decision.decision}.",
            {"decision": decision.model_dump(exclude_none=True)},
        )
        return route_state

    def _sync_report_with_final_qa(self, detail: RunDetail) -> None:
        if not detail.report_md.strip():
            return
        detail.report_md = self._strip_stale_qa_claims(detail.report_md)
        ensure_sections = getattr(self, "_ensure_report_required_sections", None)
        if callable(ensure_sections):
            detail.report_md = ensure_sections(detail, detail.report_md)
        severity_counts = {
            "blocker": sum(1 for issue in detail.qa_findings if issue.severity == "blocker"),
            "warn": sum(1 for issue in detail.qa_findings if issue.severity == "warn"),
            "info": sum(1 for issue in detail.qa_findings if issue.severity == "info"),
        }
        if detail.qa_findings:
            top_issues = "\n".join(
                f"- {issue.severity}: {issue.problem}"
                for issue in sorted(
                    detail.qa_findings,
                    key=lambda item: {"blocker": 0, "warn": 1, "info": 2}.get(item.severity, 3),
                )[:8]
            )
            if severity_counts["blocker"]:
                status_text = "**Status: blocked for review.**"
                readiness_text = (
                    "This report is not ready for enterprise publishing until these issues "
                    "are resolved or explicitly force-passed by a reviewer."
                )
            else:
                status_text = "**Status: passed with warnings.**"
                readiness_text = (
                    "This report is publishable from the deterministic QA perspective, "
                    "with warnings retained for reviewer attention."
                )
            section = (
                "\n\n## Final QA Gate Status\n"
                f"{status_text} "
                f"QA found {severity_counts['blocker']} blocker(s), "
                f"{severity_counts['warn']} warning(s), and {severity_counts['info']} "
                f"info item(s). {readiness_text}\n\n"
                f"{top_issues}"
            )
        else:
            section = (
                "\n\n## Final QA Gate Status\n"
                "**Status: passed.** No unresolved deterministic QA findings were recorded "
                "for this run."
            )
        detail.report_md = detail.report_md.rstrip() + section

    def _strip_stale_qa_claims(self, markdown: str) -> str:
        patterns = [
            r"\*\*Unresolved QA Findings:\*\*\s*None flagged[^\n]*",
            r"Unresolved QA Findings:\s*None flagged[^\n]*",
            r"No unresolved QA findings were recorded[^\n]*",
            r"all source claims meet minimum confidence thresholds[^\n]*",
        ]
        cleaned = markdown
        for pattern in patterns:
            cleaned = re.sub(
                pattern,
                "Unresolved QA findings are summarized in the Final QA Gate Status section.",
                cleaned,
                flags=re.IGNORECASE,
            )
        cleaned = re.sub(
            r"\n+## Final QA Gate Status\n.*\Z",
            "",
            cleaned,
            flags=re.IGNORECASE | re.DOTALL,
        )
        return cleaned.rstrip()

    def _build_qa_issues(self, detail: RunDetail) -> list[QCIssue]:
        self._ensure_structured_knowledge(detail)
        missing_dimensions = self._missing_dimensions(detail)
        issues = self._build_collect_qa_issues(detail)
        issues.extend(self._build_analyst_qa_issues(detail, missing_dimensions))
        issues.extend(self._build_phantom_citation_issues(detail))
        issues.extend(self._build_text_quality_issues(detail))
        issues.extend(self._build_matrix_consistency_issues(detail))
        issues.extend(self._build_reflector_qa_issues(detail))
        return self._dedupe_qa_issues(issues)

    def _dedupe_qa_issues(self, issues: list[QCIssue]) -> list[QCIssue]:
        deduped: list[QCIssue] = []
        seen_ids: set[str] = set()
        for issue in issues:
            if issue.id in seen_ids:
                continue
            seen_ids.add(issue.id)
            deduped.append(issue)
        return deduped

    def _missing_dimensions(self, detail: RunDetail) -> list[str]:
        return [
            dimension
            for dimension in detail.plan.dimensions
            if not any(source.dimension == dimension for source in detail.raw_sources)
        ]

    def _build_collect_qa_issues(self, detail: RunDetail) -> list[QCIssue]:
        issues: list[QCIssue] = []
        missing_dimensions = self._missing_dimensions(detail)
        strict_source_qa = self._memory_enforces_strict_source_qa(
            detail.plan
        ) or detail.execution_mode == "real"
        unverified_sources = [
            source
            for source in detail.raw_sources
            if source.dimension in detail.plan.dimensions
            and source.source_type != "webpage_verified"
            and source.url is not None
        ]

        for dimension in missing_dimensions:
            scope = RedoScope(
                kind="collector",
                target_subagent=dimension,
                rationale=f"No sources collected for {dimension}.",
            )
            issues.append(
                QCIssue(
                    id=stable_prefixed_id("qc-issue", "missing", dimension, length=16),
                    severity="blocker",
                    detected_by="coverage",
                    target_agent="collector",
                    target_subagent=dimension,
                    field_path=f"raw_sources[{dimension}]",
                    problem=f"No evidence sources were collected for {dimension}.",
                    redo_scope=scope,
                    self_found=False,
                )
            )

        for source in unverified_sources:
            dimension = source.dimension
            if dimension in missing_dimensions:
                continue
            covered = source.covered_competitors or self._normalize_covered_competitors(
                detail, source.competitor
            )
            targets = [
                competitor for competitor in covered if competitor in detail.plan.competitors
            ] or [None]
            for competitor in targets:
                field_path = f"raw_sources[{source.id}].source_type"
                problem = (
                    f"Source {source.id} for {dimension} is not fetched webpage evidence "
                    "and should be recollected or verified."
                )
                if strict_source_qa:
                    problem += " MemoryAgent QA policy escalates unverified evidence to a blocker."
                issue = QCIssue(
                    id=stable_prefixed_id(
                        "qc-issue",
                        "unverified",
                        dimension,
                        competitor or source.competitor,
                        source.id,
                        length=16,
                    ),
                    severity="blocker" if strict_source_qa else "warn",
                    detected_by="coverage",
                    target_agent="collector",
                    target_subagent=dimension,
                    target_competitor=competitor,
                    field_path=field_path,
                    problem=problem,
                    redo_scope=self._initial_redo_scope(
                        detected_by="coverage",
                        target_agent="collector",
                        target_subagent=dimension,
                        target_competitor=competitor,
                        field_path=field_path,
                        problem=problem,
                    ),
                    self_found=False,
                )
                issue.redo_scope = assign_redo_scope(issue)
                issues.append(issue)

        issues.extend(self._build_source_quality_issues(detail))
        issues.extend(self._build_source_coverage_issues(detail, missing_dimensions))
        return issues

    def _build_source_quality_issues(self, detail: RunDetail) -> list[QCIssue]:
        issues: list[QCIssue] = []
        seen: set[str] = set()
        strict_source_qa = self._memory_enforces_strict_source_qa(
            detail.plan
        ) or detail.execution_mode == "real"
        for source in detail.raw_sources:
            if source.dimension not in detail.plan.dimensions:
                continue
            if source.source_type != "webpage_verified":
                continue
            problem = self._source_quality_problem(source)
            if problem is None:
                continue
            covered = source.covered_competitors or self._normalize_covered_competitors(
                detail, source.competitor
            )
            targets = [
                competitor for competitor in covered if competitor in detail.plan.competitors
            ] or [None]
            for competitor in targets:
                issue_id = stable_prefixed_id(
                    "qc-issue",
                    "low-quality-source",
                    source.dimension,
                    competitor or source.competitor,
                    source.id,
                    length=16,
                )
                if issue_id in seen:
                    continue
                seen.add(issue_id)
                field_path = f"raw_sources[{source.id}]"
                issue = QCIssue(
                    id=issue_id,
                    severity="blocker" if strict_source_qa else "warn",
                    detected_by="coverage",
                    target_agent="collector",
                    target_subagent=source.dimension,
                    target_competitor=competitor,
                    field_path=field_path,
                    problem=problem,
                    redo_scope=self._initial_redo_scope(
                        detected_by="coverage",
                        target_agent="collector",
                        target_subagent=source.dimension,
                        target_competitor=competitor,
                        field_path=field_path,
                        problem=problem,
                    ),
                    self_found=False,
                )
                issue.redo_scope = assign_redo_scope(issue)
                issues.append(issue)
        return issues

    def _build_source_coverage_issues(
        self,
        detail: RunDetail,
        missing_dimensions: list[str],
    ) -> list[QCIssue]:
        issues: list[QCIssue] = []
        expected_competitors = set(detail.plan.competitors)
        seen_issue_ids: set[str] = set()
        for source in detail.raw_sources:
            if source.dimension not in detail.plan.dimensions:
                continue
            covered = source.covered_competitors or self._normalize_covered_competitors(
                detail, source.competitor
            )
            unknown = sorted(value for value in covered if value not in expected_competitors)
            if not covered or unknown:
                issue_id = stable_prefixed_id(
                    "qc-issue",
                    "invalid-source-coverage",
                    source.id,
                    length=16,
                )
                if issue_id in seen_issue_ids:
                    continue
                seen_issue_ids.add(issue_id)
                issues.append(
                    QCIssue(
                        id=issue_id,
                        severity="blocker",
                        detected_by="coverage",
                        target_agent="collector",
                        target_subagent=source.dimension,
                        field_path=f"raw_sources[{source.id}].covered_competitors",
                        problem=f"Source {source.id} is not mapped to known plan competitors.",
                        redo_scope=RedoScope(
                            kind="collector",
                            target_subagent=source.dimension,
                            rationale=(
                                f"Source {source.id} needs competitor coverage normalization."
                            ),
                        ),
                        self_found=False,
                    )
                )

        for dimension in detail.plan.dimensions:
            if dimension in missing_dimensions:
                continue
            for competitor in detail.plan.competitors:
                if any(
                    source.dimension == dimension
                    and self._source_matches_competitor(source, competitor)
                    for source in detail.raw_sources
                ):
                    continue
                issues.append(
                    QCIssue(
                        id=stable_prefixed_id(
                            "qc-issue",
                            "missing-source",
                            dimension,
                            competitor,
                            length=16,
                        ),
                        severity="blocker",
                        detected_by="coverage",
                        target_agent="collector",
                        target_subagent=dimension,
                        target_competitor=competitor,
                        field_path=f"raw_sources[{dimension}][{competitor}]",
                        problem=f"No {dimension} source covers {competitor}.",
                        redo_scope=RedoScope(
                            kind="collector",
                            target_subagent=dimension,
                            target_competitor=competitor,
                            rationale=f"Collect {dimension} evidence for {competitor}.",
                        ),
                        self_found=False,
                    )
                )
        return issues

    def _build_analyst_qa_issues(
        self,
        detail: RunDetail,
        missing_dimensions: list[str],
    ) -> list[QCIssue]:
        self._ensure_structured_knowledge(detail)
        issues = self._build_empty_analyst_issues(detail, missing_dimensions)
        issues.extend(self._build_kb_citation_issues(detail))
        issues.extend(self._build_structured_knowledge_issues(detail, missing_dimensions))
        return issues

    def _ensure_structured_knowledge(self, detail: RunDetail) -> None:
        for competitor, kb in detail.competitor_kbs.items():
            for dimension, findings in kb.slices.items():
                knowledge = detail.competitor_knowledge.get(competitor)
                if self._structured_slice_has_claims(knowledge, dimension):
                    continue
                self._merge_structured_knowledge_slice(detail, competitor, dimension, findings)

    def _structured_slice_has_claims(
        self, knowledge: CompetitorKnowledge | None, dimension: str
    ) -> bool:
        if knowledge is None:
            return False
        dimension_key = dimension.casefold()
        if "pricing" in dimension_key:
            return bool(
                knowledge.pricing_model.notes
                or any(tier.claims for tier in knowledge.pricing_model.tiers)
            )
        if "persona" in dimension_key or "user" in dimension_key:
            return bool(
                knowledge.user_personas.summary_claims
                or any(segment.claims for segment in knowledge.user_personas.segments)
            )
        return bool(
            knowledge.feature_tree.summary_claims
            or any(node.claims for node in knowledge.feature_tree.nodes)
        )

    def _build_structured_knowledge_issues(
        self,
        detail: RunDetail,
        missing_dimensions: list[str],
    ) -> list[QCIssue]:
        issues: list[QCIssue] = []
        source_aliases = self._source_alias_map(detail)
        for competitor in detail.plan.competitors:
            knowledge = detail.competitor_knowledge.get(competitor)
            for dimension in detail.plan.dimensions:
                if dimension in missing_dimensions:
                    continue
                has_sources = any(
                    source.dimension == dimension
                    and self._source_matches_competitor(source, competitor)
                    for source in detail.raw_sources
                )
                if not has_sources:
                    continue
                kb = detail.competitor_kbs.get(competitor)
                if not kb or not kb.slices.get(dimension):
                    continue
                claims = self._structured_claims_for_dimension(knowledge, dimension)
                if not claims:
                    field_path = f"competitor_knowledge[{competitor}].{dimension}"
                    problem = (
                        f"{competitor} has sources for {dimension}, "
                        "but no structured knowledge claims."
                    )
                    issue = QCIssue(
                        id=stable_prefixed_id(
                            "qc-issue",
                            "schema-missing",
                            dimension,
                            competitor,
                            length=16,
                        ),
                        severity="blocker",
                        detected_by="schema",
                        target_agent="analyst",
                        target_subagent=dimension,
                        target_competitor=competitor,
                        field_path=field_path,
                        problem=problem,
                        redo_scope=self._initial_redo_scope(
                            detected_by="schema",
                            target_agent="analyst",
                            target_subagent=dimension,
                            target_competitor=competitor,
                            field_path=field_path,
                            problem=problem,
                        ),
                        self_found=False,
                    )
                    issue.redo_scope = assign_redo_scope(issue)
                    issues.append(issue)
                    continue
                shape_issue = self._structured_schema_shape_issue(competitor, dimension, knowledge)
                if shape_issue is not None:
                    issues.append(shape_issue)
                for index, claim in enumerate(claims):
                    if not claim.source_ids:
                        field_path = (
                            f"competitor_knowledge[{competitor}].{dimension}"
                            f".claims[{index}].source_ids"
                        )
                        problem = f"{competitor} {dimension} claim is missing source_ids."
                        issue = QCIssue(
                            id=stable_prefixed_id(
                                "qc-issue",
                                "schema-claim-no-source",
                                dimension,
                                competitor,
                                index,
                                length=16,
                            ),
                            severity="blocker",
                            detected_by="schema",
                            target_agent="analyst",
                            target_subagent=dimension,
                            target_competitor=competitor,
                            field_path=field_path,
                            problem=problem,
                            redo_scope=self._initial_redo_scope(
                                detected_by="schema",
                                target_agent="analyst",
                                target_subagent=dimension,
                                target_competitor=competitor,
                                field_path=field_path,
                                problem=problem,
                            ),
                            self_found=False,
                        )
                        issue.redo_scope = assign_redo_scope(issue)
                        issues.append(issue)
                    for source_id in claim.source_ids:
                        if resolve_source_token(source_id, source_aliases):
                            continue
                        field_path = (
                            f"competitor_knowledge[{competitor}].{dimension}"
                            f".claims[{index}].source_ids"
                        )
                        problem = (
                            f"{competitor} {dimension} structured claim references "
                            f"unknown source id {source_id}."
                        )
                        issue = QCIssue(
                            id=stable_prefixed_id(
                                "qc-issue",
                                "schema-claim-unknown-source",
                                dimension,
                                competitor,
                                source_id,
                                length=16,
                            ),
                            severity="blocker",
                            detected_by="schema",
                            target_agent="analyst",
                            target_subagent=dimension,
                            target_competitor=competitor,
                            field_path=field_path,
                            problem=problem,
                            redo_scope=self._initial_redo_scope(
                                detected_by="schema",
                                target_agent="analyst",
                                target_subagent=dimension,
                                target_competitor=competitor,
                                field_path=field_path,
                                problem=problem,
                            ),
                            self_found=False,
                        )
                        issue.redo_scope = assign_redo_scope(issue)
                        issues.append(issue)
        return issues

    def _structured_schema_shape_issue(
        self,
        competitor: str,
        dimension: str,
        knowledge: CompetitorKnowledge | None,
    ) -> QCIssue | None:
        if knowledge is None:
            return None
        dimension_key = dimension.casefold()
        field_path = f"competitor_knowledge[{competitor}].{dimension}"
        if "pricing" in dimension_key and not knowledge.pricing_model.tiers:
            problem = f"{competitor} pricing schema has claims but no pricing_model.tiers entries."
            field_path = f"competitor_knowledge[{competitor}].pricing_model.tiers"
        elif (
            "persona" in dimension_key or "user" in dimension_key
        ) and not knowledge.user_personas.segments:
            problem = (
                f"{competitor} persona schema has claims but no user_personas.segments entries."
            )
            field_path = f"competitor_knowledge[{competitor}].user_personas.segments"
        elif (
            "pricing" not in dimension_key
            and "persona" not in dimension_key
            and "user" not in dimension_key
            and not knowledge.feature_tree.nodes
        ):
            problem = f"{competitor} feature schema has claims but no feature_tree.nodes entries."
            field_path = f"competitor_knowledge[{competitor}].feature_tree.nodes"
        else:
            return None
        issue = QCIssue(
            id=stable_prefixed_id("qc-issue", "schema-shape", dimension, competitor, length=16),
            severity="blocker",
            detected_by="schema",
            target_agent="analyst",
            target_subagent=dimension,
            target_competitor=competitor,
            field_path=field_path,
            problem=problem,
            redo_scope=self._initial_redo_scope(
                detected_by="schema",
                target_agent="analyst",
                target_subagent=dimension,
                target_competitor=competitor,
                field_path=field_path,
                problem=problem,
            ),
            self_found=False,
        )
        issue.redo_scope = assign_redo_scope(issue)
        return issue

    def _structured_claims_for_dimension(
        self,
        knowledge: CompetitorKnowledge | None,
        dimension: str,
    ) -> list[KnowledgeClaim]:
        if knowledge is None:
            return []
        dimension_key = dimension.casefold()
        if "pricing" in dimension_key:
            return [
                *knowledge.pricing_model.notes,
                *[claim for tier in knowledge.pricing_model.tiers for claim in tier.claims],
            ]
        if "persona" in dimension_key or "user" in dimension_key:
            return [
                *knowledge.user_personas.summary_claims,
                *[
                    claim
                    for segment in knowledge.user_personas.segments
                    for claim in segment.claims
                ],
            ]
        return [
            *knowledge.feature_tree.summary_claims,
            *[claim for node in knowledge.feature_tree.nodes for claim in node.claims],
        ]

    def _build_empty_analyst_issues(
        self,
        detail: RunDetail,
        missing_dimensions: list[str],
    ) -> list[QCIssue]:
        issues: list[QCIssue] = []
        for dimension in detail.plan.dimensions:
            if dimension in missing_dimensions:
                continue
            for competitor in detail.plan.competitors:
                has_sources = any(
                    source.dimension == dimension
                    and self._source_matches_competitor(source, competitor)
                    for source in detail.raw_sources
                )
                kb = detail.competitor_kbs.get(competitor)
                has_findings = bool(kb and kb.slices.get(dimension))
                if not has_sources or has_findings:
                    continue
                field_path = f"competitor_kbs[{competitor}].slices[{dimension}]"
                problem = (
                    f"{dimension.title()} analyst did not produce structured "
                    f"findings for {competitor}."
                )
                issue = QCIssue(
                    id=stable_prefixed_id(
                        "qc-issue",
                        "empty-analyst",
                        dimension,
                        competitor,
                        length=16,
                    ),
                    severity="blocker",
                    detected_by="schema",
                    target_agent="analyst",
                    target_subagent=dimension,
                    target_competitor=competitor,
                    field_path=field_path,
                    problem=problem,
                    redo_scope=self._initial_redo_scope(
                        detected_by="schema",
                        target_agent="analyst",
                        target_subagent=dimension,
                        target_competitor=competitor,
                        field_path=field_path,
                        problem=problem,
                    ),
                    self_found=False,
                )
                issue.redo_scope = assign_redo_scope(issue)
                issues.append(issue)
        return issues

    def _build_kb_citation_issues(self, detail: RunDetail) -> list[QCIssue]:
        source_aliases = self._source_alias_map(detail)
        issues: list[QCIssue] = []
        for competitor, kb in detail.competitor_kbs.items():
            for dimension, findings in kb.slices.items():
                for cited_id in sorted(
                    cited_id
                    for finding in findings
                    for cited_id in self._extract_cited_source_ids(finding)
                    if not resolve_source_token(cited_id, source_aliases)
                ):
                    field_path = f"competitor_kbs[{competitor}].slices[{dimension}]"
                    problem = (
                        f"{dimension.title()} analyst cites unknown source id "
                        f"{cited_id} for {competitor}."
                    )
                    issue = QCIssue(
                        id=stable_prefixed_id(
                            "qc-issue",
                            "kb-unknown-source",
                            competitor,
                            dimension,
                            cited_id,
                            length=16,
                        ),
                        severity="blocker",
                        detected_by="citation",
                        target_agent="analyst",
                        target_subagent=dimension,
                        target_competitor=competitor,
                        field_path=field_path,
                        problem=problem,
                        redo_scope=self._initial_redo_scope(
                            detected_by="citation",
                            target_agent="analyst",
                            target_subagent=dimension,
                            target_competitor=competitor,
                            field_path=field_path,
                            problem=problem,
                        ),
                        self_found=False,
                    )
                    issue.redo_scope = assign_redo_scope(issue)
                    issues.append(issue)
        return issues

    def _build_phantom_citation_issues(self, detail: RunDetail) -> list[QCIssue]:
        source_aliases = self._source_alias_map(detail)
        cited_ids = self._extract_cited_source_ids(detail.report_md)
        phantom_ids = sorted(
            cited_id for cited_id in cited_ids if not resolve_source_token(cited_id, source_aliases)
        )
        issues: list[QCIssue] = []
        for malformed in malformed_source_tokens(detail.report_md):
            problem = f"Report contains malformed source token {malformed}."
            issue = QCIssue(
                id=stable_prefixed_id("qc-issue", "malformed-citation", malformed, length=16),
                severity="blocker",
                detected_by="citation",
                target_agent="writer",
                field_path="report_md",
                problem=problem,
                redo_scope=self._initial_redo_scope(
                    detected_by="citation",
                    target_agent="writer",
                    field_path="report_md",
                    problem=problem,
                ),
                self_found=False,
            )
            issue.redo_scope = assign_redo_scope(issue)
            issues.append(issue)
        for cited_id in phantom_ids:
            problem = f"Report cites unknown source id {cited_id}."
            issue = QCIssue(
                id=stable_prefixed_id("qc-issue", "phantom-citation", cited_id, length=16),
                severity="blocker",
                detected_by="citation",
                target_agent="writer",
                field_path="report_md",
                problem=problem,
                redo_scope=self._initial_redo_scope(
                    detected_by="citation",
                    target_agent="writer",
                    field_path="report_md",
                    problem=problem,
                ),
                self_found=False,
            )
            issue.redo_scope = assign_redo_scope(issue)
            issues.append(issue)
        return issues

    def _build_text_quality_issues(self, detail: RunDetail) -> list[QCIssue]:
        issues: list[QCIssue] = []
        issues.extend(self._build_report_text_quality_issues(detail))
        issues.extend(self._build_claim_text_quality_issues(detail))
        return issues

    def _build_report_text_quality_issues(self, detail: RunDetail) -> list[QCIssue]:
        issues: list[QCIssue] = []
        for line_number, line in enumerate(detail.report_md.splitlines(), start=1):
            problem_key = publishable_text_noise_problem(line)
            if not problem_key:
                continue
            field_path = f"report_md.line[{line_number}]"
            problem = (
                f"Report line {line_number} contains non-publishable text noise "
                f"({problem_key})."
            )
            issue = QCIssue(
                id=stable_prefixed_id(
                    "qc-issue",
                    "report-text-noise",
                    detail.id,
                    line_number,
                    problem_key,
                    length=16,
                ),
                severity="blocker",
                detected_by="text_quality",
                target_agent="writer",
                field_path=field_path,
                problem=problem,
                redo_scope=self._initial_redo_scope(
                    detected_by="text_quality",
                    target_agent="writer",
                    field_path=field_path,
                    problem=problem,
                ),
                self_found=False,
            )
            issue.redo_scope = assign_redo_scope(issue)
            issues.append(issue)
            if len(issues) >= 5:
                break
        return issues

    def _build_claim_text_quality_issues(self, detail: RunDetail) -> list[QCIssue]:
        issues: list[QCIssue] = []
        for competitor in detail.plan.competitors:
            knowledge = detail.competitor_knowledge.get(competitor)
            for dimension in detail.plan.dimensions:
                for index, claim in enumerate(
                    self._structured_claims_for_dimension(knowledge, dimension)
                ):
                    problem_key = publishable_text_noise_problem(claim.claim)
                    if not problem_key:
                        continue
                    field_path = (
                        f"competitor_knowledge[{competitor}].{dimension}"
                        f".claims[{index}].claim"
                    )
                    problem = (
                        f"{competitor} {dimension} claim contains non-publishable "
                        f"text noise ({problem_key})."
                    )
                    issue = QCIssue(
                        id=stable_prefixed_id(
                            "qc-issue",
                            "claim-text-noise",
                            competitor,
                            dimension,
                            index,
                            problem_key,
                            length=16,
                        ),
                        severity="blocker",
                        detected_by="text_quality",
                        target_agent="analyst",
                        target_subagent=dimension,
                        target_competitor=competitor,
                        field_path=field_path,
                        problem=problem,
                        redo_scope=self._initial_redo_scope(
                            detected_by="text_quality",
                            target_agent="analyst",
                            target_subagent=dimension,
                            target_competitor=competitor,
                            field_path=field_path,
                            problem=problem,
                        ),
                        self_found=False,
                    )
                    issue.redo_scope = assign_redo_scope(issue)
                    issues.append(issue)
                    if len(issues) >= 8:
                        return issues
        return issues

    def _refresh_report_source_qa_findings(self, detail: RunDetail) -> bool:
        refreshed = self._build_phantom_citation_issues(detail)
        retained = [
            issue
            for issue in detail.qa_findings
            if not (
                issue.detected_by == "citation"
                and issue.target_agent == "writer"
                and issue.field_path == "report_md"
            )
        ]
        updated = [*retained, *refreshed]
        if [issue.id for issue in updated] == [issue.id for issue in detail.qa_findings]:
            return False
        detail.qa_findings = updated
        return True

    def _build_matrix_consistency_issues(self, detail: RunDetail) -> list[QCIssue]:
        if detail.comparison_matrix is None:
            if detail.competitor_kbs and detail.report_md:
                issue = QCIssue(
                    id=stable_prefixed_id(
                        "qc-issue",
                        "matrix-missing",
                        "comparison_matrix",
                        length=16,
                    ),
                    severity="blocker",
                    detected_by="consistency",
                    target_agent="comparator",
                    field_path="comparison_matrix",
                    problem="Comparison matrix is missing even though structured KB data exists.",
                    redo_scope=self._initial_redo_scope(
                        detected_by="consistency",
                        target_agent="comparator",
                        field_path="comparison_matrix",
                        problem=(
                            "Comparison matrix is missing even though structured KB data exists."
                        ),
                    ),
                    self_found=False,
                )
                issue.redo_scope = assign_redo_scope(issue)
                return [issue]
            return []

        issues: list[QCIssue] = []
        matrix = detail.comparison_matrix
        expected_competitors = set(detail.plan.competitors)
        expected_dimensions = set(detail.plan.dimensions)
        matrix_competitors = set(matrix.competitors)
        matrix_dimensions = set(matrix.dimensions)
        source_aliases = self._source_alias_map(detail)
        seen_cells: set[tuple[str, str]] = set()

        if matrix_competitors != expected_competitors:
            issues.append(
                self._matrix_issue(
                    "matrix-competitors-mismatch",
                    "blocker",
                    "comparison_matrix.competitors",
                    "Comparison matrix competitors do not match the analysis plan.",
                )
            )

        if matrix_dimensions != expected_dimensions:
            issues.append(
                self._matrix_issue(
                    "matrix-dimensions-mismatch",
                    "blocker",
                    "comparison_matrix.dimensions",
                    "Comparison matrix dimensions do not match the analysis plan.",
                )
            )

        for cell in matrix.cells:
            cell_key = (cell.competitor, cell.dimension)
            cell_id = self._issue_id_fragment(f"{cell.competitor}-{cell.dimension}")
            if cell_key in seen_cells:
                issues.append(
                    self._matrix_issue(
                        f"matrix-duplicate-cell-{cell_id}",
                        "warn",
                        f"comparison_matrix.cells[{cell.competitor},{cell.dimension}]",
                        (
                            "Comparison matrix contains a duplicate cell for "
                            f"{cell.competitor} / {cell.dimension}."
                        ),
                    )
                )
            seen_cells.add(cell_key)

            if (
                cell.competitor not in expected_competitors
                or cell.dimension not in expected_dimensions
            ):
                issues.append(
                    self._matrix_issue(
                        f"matrix-extra-cell-{cell_id}",
                        "warn",
                        f"comparison_matrix.cells[{cell.competitor},{cell.dimension}]",
                        (
                            "Comparison matrix contains a cell outside the analysis "
                            f"plan: {cell.competitor} / {cell.dimension}."
                        ),
                    )
                )
            for source_id in cell.source_ids:
                if not resolve_source_token(source_id, source_aliases):
                    issues.append(
                        self._matrix_issue(
                            f"matrix-unknown-source-{self._issue_id_fragment(source_id)}",
                            "blocker",
                            "comparison_matrix.cells[].source_ids",
                            f"Comparison matrix references unknown source id {source_id}.",
                        )
                    )
            for cited_id in self._extract_cited_source_ids(cell.value):
                canonical_cited = resolve_source_token(cited_id, source_aliases)
                canonical_cell_sources = {
                    canonical
                    for source_id in cell.source_ids
                    if (canonical := resolve_source_token(source_id, source_aliases))
                }
                if canonical_cited and canonical_cited not in canonical_cell_sources:
                    issues.append(
                        self._matrix_issue(
                            f"matrix-missing-cited-source-{self._issue_id_fragment(cell.competitor)}-"
                            f"{self._issue_id_fragment(cell.dimension)}-{self._issue_id_fragment(cited_id)}",
                            "blocker",
                            (
                                f"comparison_matrix.cells[{cell.competitor},"
                                f"{cell.dimension}].source_ids"
                            ),
                            (
                                f"Comparison matrix cell for {cell.competitor} / "
                                f"{cell.dimension} cites "
                                f"{cited_id} in its value but omits it from source_ids."
                            ),
                        )
                    )

        for competitor in detail.plan.competitors:
            for dimension in detail.plan.dimensions:
                if (competitor, dimension) in seen_cells:
                    continue
                missing_id = self._issue_id_fragment(f"{competitor}-{dimension}")
                issues.append(
                    self._matrix_issue(
                        f"matrix-missing-cell-{missing_id}",
                        "warn",
                        f"comparison_matrix.cells[{competitor},{dimension}]",
                        f"Comparison matrix is missing the {dimension} cell for {competitor}.",
                    )
                )
        return issues

    def _source_alias_map(self, detail: RunDetail) -> dict[str, str]:
        projection = detail.enterprise_projection
        return source_token_alias_map(
            raw_sources=detail.raw_sources,
            evidence=projection.evidence_records if projection else (),
            scoped_evidence_ids=projection.report_version.evidence_ids if projection else None,
        )

    def _matrix_issue(
        self,
        issue_id: str,
        severity: Literal["info", "warn", "blocker"],
        field_path: str,
        problem: str,
    ) -> QCIssue:
        issue = QCIssue(
            id=stable_prefixed_id("qc-issue", issue_id, field_path, problem, length=16),
            severity=severity,
            detected_by="consistency",
            target_agent="comparator",
            field_path=field_path,
            problem=problem,
            redo_scope=self._initial_redo_scope(
                detected_by="consistency",
                target_agent="comparator",
                field_path=field_path,
                problem=problem,
            ),
            self_found=False,
        )
        issue.redo_scope = assign_redo_scope(issue)
        return issue

    def _clear_dimension_outputs(self, detail: RunDetail, dimension: str) -> None:
        for kb in detail.competitor_kbs.values():
            kb.slices.pop(dimension, None)
            valid_source_ids = {
                source.id
                for source in detail.raw_sources
                if self._source_matches_competitor(source, kb.competitor)
            }
            kb.sources = [source_id for source_id in kb.sources if source_id in valid_source_ids]
        for competitor in detail.plan.competitors:
            self._clear_structured_knowledge_slice(detail, competitor, dimension)
        if detail.comparison_matrix is not None:
            detail.comparison_matrix = self._build_comparison_matrix(
                detail,
                {
                    "matrix_summary": detail.comparison_matrix.summary,
                    "winner_by_dimension": detail.comparison_matrix.winner_by_dimension,
                },
            )

    def _clear_competitor_dimension_output(
        self,
        detail: RunDetail,
        competitor: str,
        dimension: str,
    ) -> None:
        kb = detail.competitor_kbs.get(competitor)
        if kb is not None:
            kb.slices.pop(dimension, None)
            valid_source_ids = {
                source.id
                for source in detail.raw_sources
                if self._source_matches_competitor(source, competitor)
            }
            kb.sources = [source_id for source_id in kb.sources if source_id in valid_source_ids]
        self._clear_structured_knowledge_slice(detail, competitor, dimension)
        if detail.comparison_matrix is not None:
            detail.comparison_matrix = self._build_comparison_matrix(
                detail,
                {
                    "matrix_summary": detail.comparison_matrix.summary,
                    "winner_by_dimension": detail.comparison_matrix.winner_by_dimension,
                },
            )

    def _clear_structured_knowledge_slice(
        self, detail: RunDetail, competitor: str, dimension: str
    ) -> None:
        knowledge = detail.competitor_knowledge.get(competitor)
        if knowledge is None:
            return
        dimension_key = dimension.casefold()
        if "pricing" in dimension_key:
            knowledge.pricing_model.tiers = []
            knowledge.pricing_model.notes = []
        elif "persona" in dimension_key or "user" in dimension_key:
            knowledge.user_personas.segments = []
            knowledge.user_personas.summary_claims = []
        else:
            knowledge.feature_tree.nodes = []
            knowledge.feature_tree.summary_claims = []
        valid_source_ids = {
            source.id
            for source in detail.raw_sources
            if self._source_matches_competitor(source, competitor)
        }
        knowledge.source_ids = [
            source_id for source_id in knowledge.source_ids if source_id in valid_source_ids
        ]
        detail.competitor_knowledge[competitor] = knowledge
