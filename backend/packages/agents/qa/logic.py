from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from packages.business_intel.report_sections import build_report_section_index
from packages.identity import stable_prefixed_id
from packages.orchestrator.scoping import assign_redo_scope, build_redo_scope
from packages.rag.structured_claims import find_structured_source_conflicts
from packages.research.evidence import publishable_text_noise_problem
from packages.schema.api_dto import RunDetail
from packages.schema.models import (
    CompetitorKnowledge,
    KnowledgeClaim,
    QCIssue,
    RawSource,
    RedoScope,
    ReviewThemeItem,
    ReviewThemeSummary,
)
from packages.sources import (
    malformed_source_tokens,
    resolve_source_token,
    source_token_alias_map,
    source_tokens,
)

CORE_SCHEMA_DIMENSIONS = ("pricing", "feature", "persona")
SOURCE_TOKEN_TEXT_RE = re.compile(r"(?:\[source:[^\]]+\]|\u3010source:[^\u3011]+\u3011)")
REPORT_SECTION_MARKER_RE = re.compile(r"(?m)^<!--\s*report-section:[^>]*-->\s*$")
REVIEW_SUMMARY_DIMENSION_HINTS = (
    "review",
    "persona",
    "user",
    "customer",
    "buyer",
    "feedback",
    "adoption",
    "switching",
)
PERSONA_EVIDENCE_DIMENSION_HINTS = (
    "persona",
    "user",
    "customer",
    "buyer",
    "review",
    "feedback",
    "adoption",
    "switching",
)
PERSONA_SYNTHETIC_SOURCE_TYPES = {"survey_simulated"}
PERSONA_QUALITATIVE_SOURCE_TYPES = {
    "survey_response",
    "interview_record",
    "manual_transcript",
    "manual_note",
    "manual",
}
COMMUNITY_PUBLIC_SOURCE_TYPES = {
    "community_forum",
    "reddit_thread",
    "github_discussion",
    "github_issue",
    "review_site",
    "developer_blog",
}
PERSONA_PUBLIC_SOURCE_TYPES = {"webpage_verified", *COMMUNITY_PUBLIC_SOURCE_TYPES}
PERSONA_SIGNAL_TERMS = (
    "persona",
    "target user",
    "customer",
    "customers",
    "buyer",
    "developer",
    "developers",
    "engineering team",
    "enterprise team",
    "team",
    "case study",
    "customer story",
    "review",
    "feedback",
    "adoption",
    "onboarding",
    "switching",
    "workflow fit",
    "use case",
    "pain point",
)
FRESHNESS_STALE_STATUSES = {"archived", "deleted", "stale"}
FRESHNESS_DIMENSION_WINDOWS_DAYS = (
    (("pricing", "price", "plan", "billing"), 45),
    (("security", "trust", "compliance", "privacy", "procurement"), 90),
    (("feature", "api", "docs", "model", "integration"), 120),
    (("persona", "user", "customer", "review", "community"), 180),
)
CONTRADICTION_FACT_TERMS = (
    "sso",
    "saml",
    "scim",
    "soc 2",
    "iso",
    "audit log",
    "api",
    "free plan",
    "enterprise plan",
    "self-hosted",
)
PRICING_PLAN_TERMS = ("free", "pro", "team", "teams", "business", "enterprise")
PRICE_AMOUNT_RE = re.compile(
    r"(?:\$|usd\s*)(?P<prefix>\d+(?:\.\d+)?)|"
    r"(?P<suffix>\d+(?:\.\d+)?)\s*(?:usd|dollars?)",
    flags=re.IGNORECASE,
)

if TYPE_CHECKING:
    from packages.orchestrator.service import RunRecord


@dataclass(frozen=True)
class PersonaEvidenceStrength:
    source_count: int
    verified_count: int
    qualitative_count: int
    synthetic_count: int
    persona_signal_count: int
    has_independent_public_signal: bool
    is_weak: bool
    reason: str


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
        if REPORT_SECTION_MARKER_RE.search(detail.report_md):
            detail.report_md = detail.report_md.rstrip()
            return
        ensure_sections = getattr(self, "_ensure_report_required_sections", None)
        if callable(ensure_sections):
            detail.report_md = ensure_sections(detail, detail.report_md)
        detail.report_md = detail.report_md.rstrip()

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
                "Unresolved QA findings are tracked in the run QA metadata.",
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
        issues.extend(self._build_community_official_commitment_issues(detail))
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

    def _dimension_needs_persona_strength_gate(self, dimension: str) -> bool:
        normalized = dimension.casefold().replace("-", "_")
        return any(hint in normalized for hint in PERSONA_EVIDENCE_DIMENSION_HINTS)

    def _persona_source_text(self, source: RawSource) -> str:
        return " ".join([source.title, str(source.url or ""), source.snippet]).casefold()

    def _persona_source_is_synthetic(self, source: RawSource) -> bool:
        return source.source_type in PERSONA_SYNTHETIC_SOURCE_TYPES or bool(
            source.metadata.get("fallback_synthetic")
            or source.metadata.get("synthetic_fallback")
            or source.metadata.get("survey_interview_synthetic")
        )

    def _source_has_persona_signal(self, source: RawSource) -> bool:
        text = self._persona_source_text(source)
        return any(term in text for term in PERSONA_SIGNAL_TERMS)

    def _persona_evidence_strength(
        self,
        detail: RunDetail,
        dimension: str,
        competitor: str,
    ) -> PersonaEvidenceStrength:
        sources = [
            source
            for source in detail.raw_sources
            if source.dimension == dimension and self._source_matches_competitor(source, competitor)
        ]
        verified_count = sum(
            1 for source in sources if source.source_type in PERSONA_PUBLIC_SOURCE_TYPES
        )
        qualitative_count = sum(
            1 for source in sources if source.source_type in PERSONA_QUALITATIVE_SOURCE_TYPES
        )
        synthetic_count = sum(1 for source in sources if self._persona_source_is_synthetic(source))
        signal_count = sum(1 for source in sources if self._source_has_persona_signal(source))
        public_signal = any(
            source.source_type in PERSONA_PUBLIC_SOURCE_TYPES
            and not self._persona_source_is_synthetic(source)
            and self._source_has_persona_signal(source)
            for source in sources
        )
        if not sources:
            reason = "no_sources"
        elif len(sources) == 1 and self._persona_source_is_synthetic(sources[0]):
            reason = "single_low_confidence_synthetic"
        elif (
            len(sources) == 1
            and sources[0].source_type in PERSONA_QUALITATIVE_SOURCE_TYPES
            and sources[0].confidence < 0.7
        ):
            reason = "single_low_confidence_qualitative"
        elif (
            len(sources) == 1
            and sources[0].source_type in PERSONA_QUALITATIVE_SOURCE_TYPES
            and sources[0].confidence >= 0.8
            and signal_count > 0
            and not self._persona_source_is_synthetic(sources[0])
        ):
            reason = "strong"
        elif synthetic_count == len(sources):
            reason = "synthetic_only"
        elif signal_count == 0:
            reason = "no_persona_signal"
        elif not public_signal and len(sources) < 2:
            reason = "too_few_sources"
        else:
            reason = "strong"
        return PersonaEvidenceStrength(
            source_count=len(sources),
            verified_count=verified_count,
            qualitative_count=qualitative_count,
            synthetic_count=synthetic_count,
            persona_signal_count=signal_count,
            has_independent_public_signal=public_signal,
            is_weak=reason != "strong",
            reason=reason,
        )

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
            and source.source_type not in COMMUNITY_PUBLIC_SOURCE_TYPES
            and not source.metadata.get("community_evidence")
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
        issues.extend(self._build_source_freshness_issues(detail))
        issues.extend(self._build_source_contradiction_issues(detail))
        issues.extend(self._build_source_coverage_issues(detail, missing_dimensions))
        issues.extend(self._build_persona_evidence_strength_issues(detail, missing_dimensions))
        issues.extend(self._build_community_attempt_issues(detail))
        return issues

    def _build_community_attempt_issues(self, detail: RunDetail) -> list[QCIssue]:
        if detail.execution_mode != "real":
            return []
        if not self._settings.collector_community_enabled:
            return []
        if self._settings.collector_community_target_sources_per_branch <= 0:
            return []
        search_enabled = getattr(getattr(self, "_search", None), "is_enabled", True)
        if callable(search_enabled):
            search_enabled = search_enabled()
        if not search_enabled:
            return []
        attempted = {
            (
                str(message.payload.get("competitor") or ""),
                str(message.payload.get("dimension") or ""),
            )
            for message in detail.agent_messages
            if (
                message.message_type
                in {"community_search_completed", "community_search_failed"}
                and isinstance(message.payload, dict)
            )
        }
        issues: list[QCIssue] = []
        for competitor in detail.plan.competitors:
            for dimension in detail.plan.dimensions:
                has_community_source = any(
                    source.dimension == dimension
                    and self._source_matches_competitor(source, competitor)
                    and source.metadata.get("community_evidence")
                    for source in detail.raw_sources
                )
                if has_community_source or (competitor, dimension) in attempted:
                    continue
                problem = (
                    f"Community triangulation was not attempted for {competitor} / {dimension}."
                )
                issues.append(
                    QCIssue(
                        id=stable_prefixed_id(
                            "qc-issue",
                            "community-not-attempted",
                            competitor,
                            dimension,
                            length=16,
                        ),
                        severity="warn",
                        detected_by="coverage",
                        target_agent="collector",
                        target_subagent=dimension,
                        target_competitor=competitor,
                        field_path=(
                            "agent_messages.community_search_attempt"
                            f"[{competitor}][{dimension}]"
                        ),
                        problem=problem,
                        redo_scope=RedoScope(
                            kind="collector",
                            target_subagent=dimension,
                            target_competitor=competitor,
                            rationale=problem,
                        ),
                        self_found=False,
                    )
                )
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

    def _build_source_freshness_issues(self, detail: RunDetail) -> list[QCIssue]:
        issues: list[QCIssue] = []
        seen: set[str] = set()
        strict_source_qa = self._memory_enforces_strict_source_qa(
            detail.plan
        ) or detail.execution_mode == "real"
        for source in detail.raw_sources:
            if source.dimension not in detail.plan.dimensions:
                continue
            problem = self._source_freshness_problem(source)
            if problem is None:
                continue
            targets = [
                competitor
                for competitor in (
                    source.covered_competitors
                    or self._normalize_covered_competitors(detail, source.competitor)
                )
                if competitor in detail.plan.competitors
            ] or [None]
            for competitor in targets:
                issue_id = stable_prefixed_id(
                    "qc-issue",
                    "source-freshness",
                    source.dimension,
                    competitor or source.competitor,
                    source.id,
                    problem,
                    length=16,
                )
                if issue_id in seen:
                    continue
                seen.add(issue_id)
                issue = QCIssue(
                    id=issue_id,
                    severity=(
                        "blocker"
                        if strict_source_qa and "missing original observation date" not in problem
                        else "warn"
                    ),
                    detected_by="coverage",
                    target_agent="collector",
                    target_subagent=source.dimension,
                    target_competitor=competitor,
                    field_path=f"raw_sources[{source.id}].freshness",
                    problem=problem,
                    redo_scope=self._initial_redo_scope(
                        detected_by="coverage",
                        target_agent="collector",
                        target_subagent=source.dimension,
                        target_competitor=competitor,
                        field_path=f"raw_sources[{source.id}].freshness",
                        problem=problem,
                    ),
                    self_found=False,
                    metadata=self._source_freshness_issue_metadata(source),
                )
                issue.redo_scope = assign_redo_scope(issue)
                issues.append(issue)
        return issues

    def _source_freshness_problem(self, source: RawSource) -> str | None:
        metadata = source.metadata
        status = self._source_document_status(source)
        limit_days = self._freshness_limit_days(source.dimension)
        if status in FRESHNESS_STALE_STATUSES:
            return (
                f"Source {source.id} is marked {status}; recollect current "
                f"{source.dimension} evidence before using it."
            )
        observed_at = self._source_observed_at(source)
        if observed_at is None:
            if metadata.get("kb_retrieved") or source.candidate_origin == "rag_kb":
                return (
                    f"Source {source.id} is reused from KB but is missing original "
                    "observation date metadata; recollect or verify it before relying on it."
                )
            return None
        now = datetime.now(UTC).replace(tzinfo=None)
        age_days = max(0, (now - observed_at).days)
        if age_days <= limit_days:
            return None
        return (
            f"Source {source.id} is {age_days} days old, exceeding the "
            f"{limit_days}-day freshness policy for {source.dimension} evidence."
        )

    def _source_freshness_issue_metadata(self, source: RawSource) -> dict[str, object]:
        observed_at = self._source_observed_at(source)
        status = self._source_document_status(source)
        limit_days = self._freshness_limit_days(source.dimension)
        metadata: dict[str, object] = {
            "issue_kind": "source_freshness",
            "source_ids": [source.id],
            "raw_source_ids": [source.id],
            "freshness_policy_days": limit_days,
            "evidence_audit_trail": [self._source_audit_trail_item(source)],
        }
        if status:
            metadata["kb_document_status"] = status
            if status in FRESHNESS_STALE_STATUSES:
                metadata["freshness_basis"] = "kb_document_status"
        if observed_at is None:
            metadata["freshness_basis"] = metadata.get(
                "freshness_basis", "missing_observation_date"
            )
            return metadata
        now = datetime.now(UTC).replace(tzinfo=None)
        metadata["observed_at"] = observed_at.isoformat()
        metadata["source_age_days"] = max(0, (now - observed_at).days)
        metadata["freshness_basis"] = metadata.get("freshness_basis", "source_age")
        return metadata

    def _source_document_status(self, source: RawSource) -> str:
        metadata = source.metadata
        return str(
            metadata.get("kb_document_status")
            or metadata.get("document_status")
            or metadata.get("status")
            or ""
        ).casefold()

    def _source_observed_at(self, source: RawSource) -> datetime | None:
        metadata = source.metadata
        is_kb_reuse = bool(metadata.get("kb_retrieved") or source.candidate_origin == "rag_kb")
        keys = (
            ("kb_last_seen_at", "kb_fetched_at")
            if is_kb_reuse
            else ("last_verified_at", "fetched_at", "crawl_fetched_at", "captured_at")
        )
        for key in keys:
            parsed = self._parse_source_datetime(metadata.get(key))
            if parsed is not None:
                return parsed
        if is_kb_reuse:
            return None
        return self._parse_source_datetime(source.extracted_at)

    def _parse_source_datetime(self, value: object) -> datetime | None:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                return None
            try:
                parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
            except ValueError:
                return None
        else:
            return None
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(UTC).replace(tzinfo=None)
        return parsed

    def _freshness_limit_days(self, dimension: str) -> int:
        normalized = dimension.casefold()
        for hints, days in FRESHNESS_DIMENSION_WINDOWS_DAYS:
            if any(hint in normalized for hint in hints):
                return days
        return 120

    def _build_source_contradiction_issues(self, detail: RunDetail) -> list[QCIssue]:
        issues: list[QCIssue] = []
        for dimension in detail.plan.dimensions:
            for competitor in detail.plan.competitors:
                sources = [
                    source
                    for source in detail.raw_sources
                    if source.dimension == dimension
                    and self._source_matches_competitor(source, competitor)
                ]
                for conflict in self._source_contradictions(sources, dimension)[:4]:
                    source_ids = sorted(
                        {
                            source_id
                            for ids in conflict["source_ids_by_position"].values()
                            for source_id in ids
                        }
                    )
                    field_path = f"raw_sources[{dimension}][{competitor}].contradictions"
                    positions = ", ".join(sorted(conflict["source_ids_by_position"]))
                    problem = (
                        f"{competitor} {dimension} evidence has conflicting "
                        f"{conflict['claim_area']} positions ({positions}) across "
                        f"sources {', '.join(source_ids)}."
                    )
                    issue = QCIssue(
                        id=stable_prefixed_id(
                            "qc-issue",
                            "source-contradiction",
                            dimension,
                            competitor,
                            conflict["claim_area"],
                            source_ids,
                            length=16,
                        ),
                        severity="blocker" if detail.execution_mode == "real" else "warn",
                        detected_by="consistency",
                        target_agent="collector",
                        target_subagent=dimension,
                        target_competitor=competitor,
                        field_path=field_path,
                        problem=problem,
                        redo_scope=self._initial_redo_scope(
                            detected_by="consistency",
                            target_agent="collector",
                            target_subagent=dimension,
                            target_competitor=competitor,
                            field_path=field_path,
                            problem=problem,
                        ),
                        self_found=False,
                        metadata=self._source_contradiction_issue_metadata(
                            sources,
                            conflict,
                            competitor=competitor,
                            dimension=dimension,
                        ),
                    )
                    issue.redo_scope = assign_redo_scope(issue)
                    issues.append(issue)
        return issues

    def _source_contradictions(
        self,
        sources: list[RawSource],
        dimension: str,
    ) -> list[dict[str, object]]:
        return [
            conflict.to_qa_payload()
            for conflict in find_structured_source_conflicts(sources, dimension=dimension)
        ]

    def _source_contradiction_issue_metadata(
        self,
        sources: list[RawSource],
        conflict: dict[str, object],
        *,
        competitor: str,
        dimension: str,
    ) -> dict[str, object]:
        source_ids_by_position = self._source_ids_by_position(conflict)
        source_ids = sorted(
            {
                source_id
                for source_ids in source_ids_by_position.values()
                for source_id in source_ids
            }
        )
        sources_by_id = {source.id: source for source in sources}
        audit_trail = [
            self._source_audit_trail_item(sources_by_id[source_id], position=position)
            for position, position_source_ids in source_ids_by_position.items()
            for source_id in position_source_ids
            if source_id in sources_by_id
        ][:8]
        return {
            "issue_kind": "source_contradiction",
            "claim_area": str(conflict.get("claim_area") or ""),
            "competitor": competitor,
            "dimension": dimension,
            "source_ids": source_ids,
            "raw_source_ids": source_ids,
            "source_ids_by_position": source_ids_by_position,
            "source_evidence_pairs": self._source_conflict_pairs(
                source_ids_by_position,
                sources_by_id,
                claim_area=str(conflict.get("claim_area") or ""),
            ),
            "evidence_audit_trail": audit_trail,
        }

    def _source_ids_by_position(
        self,
        conflict: dict[str, object],
    ) -> dict[str, list[str]]:
        value = conflict.get("source_ids_by_position")
        if not isinstance(value, dict):
            return {}
        result: dict[str, list[str]] = {}
        for position, source_ids in value.items():
            if not isinstance(source_ids, list):
                continue
            normalized = [
                str(source_id).strip()
                for source_id in source_ids
                if str(source_id).strip()
            ]
            if normalized:
                result[str(position)] = sorted(set(normalized))
        return result

    def _source_conflict_pairs(
        self,
        source_ids_by_position: dict[str, list[str]],
        sources_by_id: dict[str, RawSource],
        *,
        claim_area: str,
    ) -> list[dict[str, object]]:
        pairs: list[dict[str, object]] = []
        positions = sorted(source_ids_by_position)
        for left_index, left_position in enumerate(positions):
            for right_position in positions[left_index + 1 :]:
                for left_id in source_ids_by_position[left_position]:
                    for right_id in source_ids_by_position[right_position]:
                        left = sources_by_id.get(left_id)
                        right = sources_by_id.get(right_id)
                        if left is None or right is None:
                            continue
                        left_is_kb = self._source_is_kb_reuse(left)
                        right_is_kb = self._source_is_kb_reuse(right)
                        if left_is_kb == right_is_kb:
                            continue
                        kb_source = left if left_is_kb else right
                        live_source = right if left_is_kb else left
                        kb_position = left_position if left_is_kb else right_position
                        live_position = right_position if left_is_kb else left_position
                        pairs.append(
                            self._compact_metadata(
                                {
                                    "claim_area": claim_area,
                                    "kb_source_id": kb_source.id,
                                    "kb_position": kb_position,
                                    "kb_document_id": self._source_metadata_text(
                                        kb_source,
                                        "kb_document_id",
                                        "document_id",
                                    ),
                                    "kb_chunk_id": self._source_metadata_text(
                                        kb_source,
                                        "kb_chunk_id",
                                        "chunk_id",
                                    ),
                                    "kb_title": kb_source.title,
                                    "kb_url": str(kb_source.url or ""),
                                    "live_source_id": live_source.id,
                                    "live_position": live_position,
                                    "live_title": live_source.title,
                                    "live_url": str(live_source.url or ""),
                                }
                            )
                        )
                        if len(pairs) >= 8:
                            return pairs
        return pairs

    def _source_audit_trail_item(
        self,
        source: RawSource,
        *,
        position: str | None = None,
    ) -> dict[str, object]:
        return self._compact_metadata(
            {
                "source_id": source.id,
                "raw_source_id": source.id,
                "competitor": source.competitor,
                "dimension": source.dimension,
                "source_type": source.source_type,
                "title": source.title,
                "url": str(source.url or ""),
                "position": position,
                "candidate_origin": source.candidate_origin,
                "fetch_method": source.fetch_method,
                "confidence": source.confidence,
                "quality_score": source.quality_score,
                "kb_document_id": self._source_metadata_text(
                    source,
                    "kb_document_id",
                    "document_id",
                ),
                "kb_document_version": source.metadata.get("kb_document_version"),
                "kb_document_status": self._source_document_status(source),
                "kb_chunk_id": self._source_metadata_text(source, "kb_chunk_id", "chunk_id"),
                "kb_chunk_ids": source.metadata.get("kb_chunk_ids"),
                "kb_retrieval_query": self._source_metadata_text(source, "kb_retrieval_query"),
                "kb_hit_score": source.metadata.get("kb_hit_score"),
                "kb_rerank_score": source.metadata.get("kb_rerank_score"),
                "kb_raw_source_id": self._source_metadata_text(source, "kb_raw_source_id"),
                "kb_collector_run_id": self._source_metadata_text(
                    source,
                    "kb_collector_run_id",
                ),
                "kb_freshness_score": source.metadata.get("kb_freshness_score"),
                "kb_fetched_at": self._source_metadata_text(source, "kb_fetched_at"),
                "kb_last_seen_at": self._source_metadata_text(source, "kb_last_seen_at"),
                "kb_indexed_at": self._source_metadata_text(source, "kb_indexed_at"),
                "is_kb_reuse": self._source_is_kb_reuse(source),
            }
        )

    def _source_metadata_text(self, source: RawSource, *keys: str) -> str:
        for key in keys:
            value = source.metadata.get(key)
            if value is None or value == "":
                continue
            return str(value)
        return ""

    def _source_is_kb_reuse(self, source: RawSource) -> bool:
        return bool(source.candidate_origin == "rag_kb" or source.metadata.get("kb_retrieved"))

    def _compact_metadata(self, metadata: dict[str, object]) -> dict[str, object]:
        return {
            key: value
            for key, value in metadata.items()
            if value is not None and value != "" and value != []
        }

    def _source_contradiction_positions(
        self,
        source: RawSource,
        dimension: str,
    ) -> list[tuple[str, str]]:
        text = f"{source.title}\n{source.snippet}".casefold()
        positions = self._binary_contradiction_positions(text)
        if "pricing" in dimension.casefold():
            positions.extend(self._pricing_contradiction_positions(text))
        return positions

    def _binary_contradiction_positions(self, text: str) -> list[tuple[str, str]]:
        positions: list[tuple[str, str]] = []
        for term in CONTRADICTION_FACT_TERMS:
            start = text.find(term)
            if start < 0:
                continue
            window = text[max(0, start - 90) : start + len(term) + 90]
            claim_area = f"support:{term}"
            if self._negative_position_window(window, term):
                positions.append((claim_area, "unsupported"))
            elif self._positive_position_window(window):
                positions.append((claim_area, "supported"))
        return positions

    def _positive_position_window(self, window: str) -> bool:
        return any(
            marker in window
            for marker in (
                "supports",
                "support ",
                "includes",
                "include ",
                "available",
                "offers",
                "provides",
                "has ",
            )
        )

    def _negative_position_window(self, window: str, term: str) -> bool:
        return any(
            marker in window
            for marker in (
                f"does not support {term}",
                f"doesn't support {term}",
                f"not support {term}",
                f"no {term}",
                f"without {term}",
                f"{term} is not available",
                f"{term} unavailable",
                f"{term} removed",
                f"{term} deprecated",
                f"{term} discontinued",
                f"no longer supports {term}",
            )
        )

    def _pricing_contradiction_positions(self, text: str) -> list[tuple[str, str]]:
        positions: list[tuple[str, str]] = []
        for match in PRICE_AMOUNT_RE.finditer(text):
            value = match.group("prefix") or match.group("suffix")
            if not value:
                continue
            window = text[max(0, match.start() - 80) : match.end() + 80]
            plan = next((term for term in PRICING_PLAN_TERMS if term in window), "")
            if not plan:
                continue
            cadence = "year" if any(term in window for term in ("year", "annual")) else "month"
            normalized_amount = value.rstrip("0").rstrip(".") if "." in value else value
            positions.append((f"price:{plan}:{cadence}", f"${normalized_amount}/{cadence}"))
        if "free plan" in text or "free tier" in text:
            if self._negative_position_window(text, "free plan"):
                positions.append(("support:free plan", "unsupported"))
            elif self._positive_position_window(text):
                positions.append(("support:free plan", "supported"))
        return positions

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

    def _build_persona_evidence_strength_issues(
        self,
        detail: RunDetail,
        missing_dimensions: list[str],
    ) -> list[QCIssue]:
        issues: list[QCIssue] = []
        for dimension in detail.plan.dimensions:
            if dimension in missing_dimensions:
                continue
            if not self._dimension_needs_persona_strength_gate(dimension):
                continue
            for competitor in detail.plan.competitors:
                strength = self._persona_evidence_strength(detail, dimension, competitor)
                if not strength.is_weak or strength.reason == "no_sources":
                    continue
                field_path = f"raw_sources[{dimension}][{competitor}]"
                problem = (
                    f"{competitor} {dimension} evidence is weak: "
                    f"{strength.reason.replace('_', ' ')} with {strength.source_count} "
                    f"source(s), {strength.verified_count} verified public source(s), and "
                    f"{strength.persona_signal_count} persona signal source(s)."
                )
                issue = QCIssue(
                    id=stable_prefixed_id(
                        "qc-issue",
                        "weak-persona-evidence",
                        dimension,
                        competitor,
                        strength.reason,
                        length=16,
                    ),
                    severity="blocker" if detail.execution_mode == "real" else "warn",
                    detected_by="coverage",
                    target_agent="collector",
                    target_subagent=dimension,
                    target_competitor=competitor,
                    field_path=field_path,
                    problem=problem,
                    redo_scope=RedoScope(
                        kind="collector",
                        target_subagent=dimension,
                        target_competitor=competitor,
                        rationale=f"Collect stronger public {dimension} evidence for {competitor}.",
                    ),
                    self_found=False,
                )
                issue.redo_scope = assign_redo_scope(issue)
                issues.append(issue)
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
                or self._qa_review_summary_has_cited_items(knowledge)
            )
        if self._dimension_uses_review_summary(dimension):
            return self._qa_review_summary_has_cited_items(knowledge)
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
            self._dimension_uses_review_summary(dimension)
            and not self._qa_review_summary_has_cited_items(knowledge)
        ):
            problem = (
                f"{competitor} review schema has claims but no cited review_summary themes."
            )
            field_path = f"competitor_knowledge[{competitor}].review_summary"
        elif (
            "pricing" not in dimension_key
            and "persona" not in dimension_key
            and "user" not in dimension_key
            and not self._dimension_uses_review_summary(dimension)
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
            claims = [
                *knowledge.pricing_model.notes,
                *[claim for tier in knowledge.pricing_model.tiers for claim in tier.claims],
            ]
        elif "persona" in dimension_key or "user" in dimension_key:
            claims = [
                *knowledge.user_personas.summary_claims,
                *[
                    claim
                    for segment in knowledge.user_personas.segments
                    for claim in segment.claims
                ],
            ]
        elif self._dimension_uses_review_summary(dimension):
            claims = []
        else:
            claims = [
                *knowledge.feature_tree.summary_claims,
                *[claim for node in knowledge.feature_tree.nodes for claim in node.claims],
            ]
        if self._dimension_uses_review_summary(dimension):
            claims = [*claims, *self._qa_review_summary_claims(knowledge)]
        return claims

    def _dimension_uses_review_summary(self, dimension: str) -> bool:
        key = dimension.casefold().replace("-", "_")
        return any(hint in key for hint in REVIEW_SUMMARY_DIMENSION_HINTS)

    def _qa_review_summary_has_cited_items(self, knowledge: CompetitorKnowledge) -> bool:
        return bool(self._qa_review_summary_claims(knowledge))

    def _qa_review_summary_claims(self, knowledge: CompetitorKnowledge) -> list[KnowledgeClaim]:
        claims: list[KnowledgeClaim] = []
        seen: set[tuple[str, tuple[str, ...]]] = set()
        for item in (
            *knowledge.review_summary.praise_themes,
            *knowledge.review_summary.complaint_themes,
            *knowledge.review_summary.adoption_blockers,
            *knowledge.review_summary.switching_triggers,
        ):
            if not item.source_ids:
                continue
            source_ids = self._ordered_source_ids(item.source_ids)
            if not source_ids:
                continue
            claim_text = self._qa_review_theme_claim_text(item)
            key = (claim_text.casefold(), tuple(source_ids))
            if key in seen:
                continue
            seen.add(key)
            claims.append(
                KnowledgeClaim(
                    claim=claim_text,
                    source_ids=source_ids,
                    confidence=item.confidence,
                )
            )
        return claims

    def _qa_review_theme_claim_text(self, item: ReviewThemeItem) -> str:
        theme = " ".join((item.theme or "").split())
        evidence = " ".join((item.evidence or "").split())
        if theme and evidence:
            return f"{theme}: {evidence}"
        return theme or evidence or "Review theme"

    def _ordered_source_ids(self, source_ids: list[str]) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        for source_id in source_ids:
            clean = str(source_id).strip()
            if clean and clean not in seen:
                seen.add(clean)
                ordered.append(clean)
        return ordered

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

    def _build_community_official_commitment_issues(
        self,
        detail: RunDetail,
    ) -> list[QCIssue]:
        source_by_id = {source.id: source for source in detail.raw_sources}
        source_aliases = self._source_alias_map(detail)
        section_index = build_report_section_index(detail.report_md)
        issues: list[QCIssue] = []
        for line_number, line in enumerate(detail.report_md.splitlines(), start=1):
            if section_index.is_support_or_audit_line(line_number):
                continue
            normalized = SOURCE_TOKEN_TEXT_RE.sub("", line).casefold()
            if not self._is_community_official_commitment_line(normalized):
                continue
            line_source_ids = [
                source_id
                for cited_id in source_tokens(line)
                for source_id in [resolve_source_token(cited_id, source_aliases)]
                if source_id is not None
            ]
            for source_id in line_source_ids:
                source = source_by_id.get(source_id)
                if source is None:
                    continue
                if not source.metadata.get("community_evidence"):
                    continue
                if source.metadata.get("official_commitment"):
                    continue
                if self._line_cites_scoped_official_source(
                    line_source_ids,
                    community_source=source,
                    source_by_id=source_by_id,
                ):
                    continue
                if self._community_source_has_official_confirmed_cluster(
                    source,
                    source_by_id=source_by_id,
                ):
                    continue
                problem = (
                    "Report presents a community observation as official commitment; "
                    f"line {line_number} cites {source_id}."
                )
                issues.append(
                    QCIssue(
                        id=stable_prefixed_id(
                            "qc-issue",
                            "community-official-commitment",
                            source_id,
                            line_number,
                            length=16,
                        ),
                        severity="blocker",
                        detected_by="citation",
                        target_agent="writer",
                        field_path=f"report_md.line[{line_number}]",
                        problem=problem,
                        redo_scope=RedoScope(
                            kind="writer_only",
                            rationale=problem,
                        ),
                        self_found=False,
                    )
                )
        return issues

    def _line_cites_scoped_official_source(
        self,
        line_source_ids: list[str],
        *,
        community_source: RawSource,
        source_by_id: dict[str, RawSource],
    ) -> bool:
        return any(
            self._is_scoped_official_source(
                source_by_id.get(source_id),
                community_source=community_source,
            )
            for source_id in line_source_ids
        )

    def _community_source_has_official_confirmed_cluster(
        self,
        source: RawSource,
        *,
        source_by_id: dict[str, RawSource],
    ) -> bool:
        clusters = source.metadata.get("community_claim_clusters")
        if not isinstance(clusters, list):
            return False
        for cluster in clusters:
            if not isinstance(cluster, dict):
                continue
            if cluster.get("label") != "official_confirmed":
                continue
            official_source_ids = cluster.get("official_source_ids")
            if not isinstance(official_source_ids, list):
                continue
            if any(
                isinstance(official_source_id, str)
                and self._is_scoped_official_source(
                    source_by_id.get(official_source_id),
                    community_source=source,
                )
                for official_source_id in official_source_ids
            ):
                return True
        return False

    def _is_scoped_official_source(
        self,
        source: RawSource | None,
        *,
        community_source: RawSource,
    ) -> bool:
        if source is None:
            return False
        if source.metadata.get("community_evidence"):
            return False
        return (
            source.source_type == "webpage_verified"
            and source.competitor == community_source.competitor
            and source.dimension == community_source.dimension
        )

    def _is_community_official_commitment_line(self, normalized_line: str) -> bool:
        if self._is_community_official_caveat(normalized_line):
            return False
        return any(
            (
                re.search(
                    pattern,
                    normalized_line,
                )
                is not None
            )
            for pattern in (
                r"\bofficial\b.{0,80}\b(?:is|are|confirms?|confirmed)\b",
                r"\bofficial\b.{0,80}:",
                r"\bofficial\s+pricing\s*:",
                r"\baccording to official\b.{0,80}",
                r"\bofficial docs say\b",
                r"\bofficial sources confirm\b",
                r"\bofficially confirmed\b",
                r"\bofficial commitment\b",
            )
        )

    def _is_community_official_caveat(self, normalized_line: str) -> bool:
        return any(
            phrase in normalized_line
            for phrase in (
                "not official",
                "no official confirmation",
                "not an official",
                "not an official commitment",
                "unofficial",
                "not officially confirmed",
                "official sources were unavailable",
                "official sources unavailable",
                "official sources are unavailable",
                "official source not found",
                "no official evidence",
                "without official evidence",
                "may not reflect official",
                "may not reflect the official",
                "does not reflect official",
                "does not reflect the official",
                "not reflect official",
                "not reflect the official",
                "may not represent official",
                "may not represent the official",
                "not represent official",
                "not represent the official",
            )
        )

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
        valid_source_ids = {
            source.id
            for source in detail.raw_sources
            if self._source_matches_competitor(source, competitor)
        }
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
        if self._dimension_uses_review_summary(dimension):
            self._clear_review_summary_removed_sources(
                knowledge,
                competitor=competitor,
                dimension=dimension,
                valid_source_ids=valid_source_ids,
            )
        knowledge.source_ids = [
            source_id for source_id in knowledge.source_ids if source_id in valid_source_ids
        ]
        detail.competitor_knowledge[competitor] = knowledge

    def _clear_review_summary_removed_sources(
        self,
        knowledge: CompetitorKnowledge,
        *,
        competitor: str,
        dimension: str,
        valid_source_ids: set[str],
    ) -> None:
        review_summary = knowledge.review_summary
        review_summary.source_ids = self._ordered_source_ids(
            [source_id for source_id in review_summary.source_ids if source_id in valid_source_ids]
        )
        has_cited_theme = False
        for items in (
            review_summary.praise_themes,
            review_summary.complaint_themes,
            review_summary.adoption_blockers,
            review_summary.switching_triggers,
        ):
            retained_items: list[ReviewThemeItem] = []
            for item in items:
                had_source_ids = bool(item.source_ids)
                item.source_ids = self._ordered_source_ids(
                    [source_id for source_id in item.source_ids if source_id in valid_source_ids]
                )
                if item.source_ids:
                    has_cited_theme = True
                    retained_items.append(item)
                elif not had_source_ids:
                    retained_items.append(item)
            items[:] = retained_items
        if not review_summary.source_ids and not has_cited_theme:
            knowledge.review_summary = ReviewThemeSummary(
                competitor=competitor,
                dimension=dimension,
            )
