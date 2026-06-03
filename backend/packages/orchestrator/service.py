import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from langgraph.types import Command, interrupt

from app.events import RunEvent
from packages.agents import SubagentContext
from packages.agents.analysts.logic import AnalystAgentMixin
from packages.agents.collectors.logic import CollectorAgentMixin
from packages.agents.comparator.logic import ComparatorAgentMixin
from packages.agents.planner.logic import PlannerAgentMixin
from packages.agents.qa.logic import QualityAgentMixin
from packages.agents.reflector.logic import ReflectorAgentMixin
from packages.agents.survey.logic import SurveyInterviewAgentMixin
from packages.agents.writer.logic import WriterAgentMixin
from packages.business_intel import (
    build_business_intel_plan,
    evaluate_report_release_gate,
    validate_project_claims,
)
from packages.business_intel.homepage import verify_homepages
from packages.compliance import compliance_policy_from_settings, redact_text
from packages.config import Settings
from packages.enterprise import (
    EnterpriseStore,
    WorkspaceQuotaExceededError,
    build_enterprise_projection,
)
from packages.governance import build_model_policy_report, model_policy_block_message
from packages.identity import compute_competitor_set_hash, compute_topic_normalized
from packages.llm import DoubaoClient
from packages.memory import KBCache, PreferenceMemoryStore, RunJournal
from packages.observability import (
    LangfuseAdapter,
    LangfuseConfig,
    TraceStore,
    build_run_event,
    otel_span_id_for_span,
    trace_id_for_run,
    traceparent_for_span,
)
from packages.orchestrator.audit import build_revision_record, convergence_ratio
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.graph import (
    build_demo_analysis_graph,
    build_real_analysis_graph,
    build_scoped_redo_graph,
)
from packages.schema.api_dto import HitlResumeRequest, RunCreateRequest, RunDetail, RunSummary
from packages.schema.enterprise import (
    ClaimValidationReport,
    EnterpriseRunProjection,
    NotificationRecord,
    ReportReleaseGate,
    UserFeedbackRecord,
)
from packages.schema.models import (
    AgentMessage,
    AnalysisPlan,
    CompetitorCandidate,
    CompetitorDiscovery,
    QCIssue,
    RawSource,
    RedoScope,
    ReflectionRecord,
    RunMetrics,
    ToolCallMessage,
    TraceSpan,
)
from packages.search import PerplexitySearchClient, SearchResult
from packages.skills.registry import SkillRegistry
from packages.tools import WebSearchRequest, fetch_page, robots_check, web_search

CORE_SCHEMA_DIMENSIONS = ("pricing", "feature", "persona")


def _aggregate_consistency_votes(validation: ClaimValidationReport) -> dict[str, int]:
    totals = {"text_support": 0, "evidence_quality": 0, "triangulation": 0}
    for result in validation.results:
        for key in totals:
            totals[key] += result.consistency_votes.get(key, 0)
    totals["supported_claims"] = validation.supported_count
    totals["weak_claims"] = validation.weak_count
    totals["unsupported_claims"] = validation.unsupported_count
    totals["blocked_claims"] = validation.blocked_count
    return totals


def _claim_validation_sample_payload(validation: ClaimValidationReport) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for result in validation.results:
        for sample in result.validation_samples:
            samples.append(
                {
                    "claim_id": result.claim_id,
                    **sample.model_dump(mode="json"),
                }
            )
    return samples


@dataclass
class PendingGraphRedo:
    iteration: int
    stage: str
    redo_scope: RedoScope
    redo_scopes: list[RedoScope]
    before_md: str
    issue_ids: list[str]
    qa_issue_ids_before: list[str]
    issue_count_before: int
    auto_continue: bool = False


@dataclass
class RunRecord:
    detail: RunDetail
    events: list[RunEvent] = field(default_factory=list)
    subscribers: list[asyncio.Queue[RunEvent]] = field(default_factory=list)
    pending_interrupts: dict[str, dict[str, Any]] = field(default_factory=dict)
    hitl_timeout_tasks: dict[str, asyncio.Task[None]] = field(default_factory=dict)
    active_graph_kind: Literal["real", "demo", "scoped_redo"] | None = None
    active_thread_id: str | None = None
    pending_graph_redo: PendingGraphRedo | None = None


class RunService(
    PlannerAgentMixin,
    CollectorAgentMixin,
    SurveyInterviewAgentMixin,
    AnalystAgentMixin,
    ComparatorAgentMixin,
    ReflectorAgentMixin,
    WriterAgentMixin,
    QualityAgentMixin,
):
    def __init__(
        self,
        skill_registry: SkillRegistry,
        settings: Settings,
        journal: RunJournal | None = None,
        kb_cache: KBCache | None = None,
        preference_memory: PreferenceMemoryStore | None = None,
        trace_store: TraceStore | None = None,
        graph_checkpointer: GraphCheckpointer | None = None,
        enterprise_store: EnterpriseStore | None = None,
    ) -> None:
        self._skill_registry = skill_registry
        self._settings = settings
        self._llm = DoubaoClient(settings)
        self._search = PerplexitySearchClient(settings)
        self._journal = journal
        self._kb_cache = kb_cache
        self._preference_memory = preference_memory
        self._trace_store = trace_store
        self._langfuse = LangfuseAdapter(
            LangfuseConfig(
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
                host=settings.langfuse_host,
            )
        )
        self._graph_checkpointer = graph_checkpointer or GraphCheckpointer.from_default_path()
        self._enterprise_store = enterprise_store
        self._real_graph = None
        self._demo_graph = None
        self._scoped_redo_graph = None
        self._runs: dict[str, RunRecord] = {}
        self._lock = asyncio.Lock()
        self._hydrate_runs()

    async def create_run(self, request: RunCreateRequest) -> RunDetail:
        self._ensure_workspace_quota_allows_run(request.workspace_id)
        execution_mode = self._resolve_execution_mode(request.execution_mode)
        competitors = self._normalize_competitor_names(request.competitors)
        homepage_verifications = verify_homepages(competitors)
        verified_competitors = [
            competitor
            for competitor in competitors
            if homepage_verifications[competitor].verified
        ]
        if verified_competitors:
            competitors = verified_competitors
        valid_dimensions = self._normalize_requested_dimensions(
            request.dimensions,
            require_core_schema=not competitors,
        )
        memory_context = None
        if self._preference_memory is not None and request.project_id:
            memory_context = self._preference_memory.recall(
                workspace_id=request.workspace_id,
                project_id=request.project_id,
                query=f"{request.topic} {' '.join(valid_dimensions)}",
                limit=6,
                mark_used=True,
            )
            valid_dimensions = self._apply_memory_dimension_preferences(
                valid_dimensions,
                memory_context.prompt_context,
                [tag for item in memory_context.candidates for tag in item.tags],
            )
        homepage_verifications = verify_homepages(competitors)
        business_plan = build_business_intel_plan(
            topic=request.topic,
            competitors=competitors,
            dimensions=valid_dimensions,
            requested_layer=request.competitor_layer,
            requested_scenario_id=request.scenario_id,
        )
        now = datetime.utcnow()
        run_id = _run_id_for_idempotency_key(request.idempotency_key) or str(uuid4())
        idempotency_key = request.idempotency_key or f"run:{run_id}"
        if request.idempotency_key:
            async with self._lock:
                existing = self._load_run_record(run_id)
            if existing is not None:
                return existing.detail
        plan = AnalysisPlan(
            topic=request.topic,
            competitors=competitors,
            dimensions=valid_dimensions,
            complexity="medium",
            competitor_layer=business_plan.competitor_layer.layer,
            scenario_id=business_plan.scenario_pack.id,
            scenario_recommended_dimensions=business_plan.recommended_dimensions,
            qa_rule_ids=[rule.id for rule in business_plan.qa_rules],
            memory_candidate_ids=[
                candidate.id for candidate in memory_context.candidates
            ]
            if memory_context is not None
            else [],
            memory_prompt_context=memory_context.prompt_context
            if memory_context is not None
            else [],
            memory_recall_score=round(
                max((candidate.match_score for candidate in memory_context.candidates), default=0)
                * 100
            )
            if memory_context is not None
            else 0,
            homepage_hints={
                name: str(homepage_verifications[name].homepage_url)
                for name in competitors
                if homepage_verifications[name].homepage_url is not None
            },
            homepage_verified={
                name: homepage_verifications[name].verified for name in competitors
            },
        )
        detail = RunDetail(
            id=run_id,
            idempotency_key=idempotency_key,
            workspace_id=request.workspace_id,
            project_id=request.project_id,
            topic=request.topic,
            status="queued",
            execution_mode=execution_mode,
            created_at=now,
            updated_at=now,
            plan=plan,
            max_iterations=self._settings.max_iterations,
            auto_redo_warn_enabled=(
                self._settings.auto_redo_warn_enabled
                if request.auto_redo_warn_enabled is None
                else request.auto_redo_warn_enabled
            ),
            hitl_enabled=(
                self._settings.hitl_enabled
                if request.hitl_enabled is None
                else request.hitl_enabled
            ),
            current_node="planner",
        )
        async with self._lock:
            self._runs[run_id] = RunRecord(detail=detail)
        if self._enterprise_store is not None:
            context = self._enterprise_store.start_run(
                detail,
                workspace_id=request.workspace_id,
                project_id=request.project_id,
            )
            detail.workspace_id = context.workspace_id
            detail.project_id = context.project_id
        self._persist_run(run_id)
        await self.emit(
            run_id,
            "run_created",
            "planner",
            None,
            "Run accepted and plan drafted.",
            {
                "plan": plan.model_dump(mode="json"),
                "memory_recall": {
                    "candidate_ids": plan.memory_candidate_ids,
                    "score": plan.memory_recall_score,
                    "prompt_context": plan.memory_prompt_context,
                },
            },
        )
        if plan.memory_candidate_ids:
            await self.emit(
                run_id,
                "memory.recalled",
                "memory",
                None,
                f"MemoryAgent recalled {len(plan.memory_candidate_ids)} confirmed preference(s).",
                {
                    "candidate_ids": plan.memory_candidate_ids,
                    "prompt_context": plan.memory_prompt_context,
                    "score": plan.memory_recall_score,
                    "query": request.topic,
                },
            )
        return detail

    async def ensure_run_visible(self, request: RunCreateRequest) -> RunDetail:
        detail = await self.create_run(request)
        self._persist_run(detail.id)
        return detail

    def ensure_workspace_quota_allows_run(self, workspace_id: str) -> None:
        self._ensure_workspace_quota_allows_run(workspace_id)

    def list_runs(self) -> list[RunSummary]:
        self._refresh_runs_from_journal()
        return [
            RunSummary(
                id=record.detail.id,
                idempotency_key=record.detail.idempotency_key,
                workspace_id=record.detail.workspace_id,
                project_id=record.detail.project_id,
                topic=record.detail.topic,
                status=record.detail.status,
                execution_mode=record.detail.execution_mode,
                created_at=record.detail.created_at,
                updated_at=record.detail.updated_at,
            )
            for record in sorted(
                self._runs.values(),
                key=lambda item: item.detail.created_at,
                reverse=True,
            )
        ]

    def get_run(self, run_id: str) -> RunDetail | None:
        record = self._load_run_record(run_id)
        return record.detail if record else None

    def get_trace(self, run_id: str) -> list[RunEvent] | None:
        record = self._load_run_record(run_id)
        return record.events if record else None

    def get_trace_spans(self, run_id: str) -> list[TraceSpan] | None:
        record = self._load_run_record(run_id)
        if record is not None:
            return record.detail.trace_spans
        if self._trace_store is not None:
            spans = self._trace_store.list_spans(run_id)
            return spans or None
        return None

    def get_agent_messages(self, run_id: str) -> list[AgentMessage] | None:
        record = self._load_run_record(run_id)
        if record is not None:
            return record.detail.agent_messages
        if self._trace_store is not None:
            messages = self._trace_store.list_agent_messages(run_id)
            return messages or None
        return None

    def get_tool_call_messages(self, run_id: str) -> list[ToolCallMessage] | None:
        record = self._load_run_record(run_id)
        if record is not None:
            return record.detail.tool_call_messages
        if self._trace_store is not None:
            messages = self._trace_store.list_tool_call_messages(run_id)
            return messages or None
        return None

    def can_start_redo(self, run_id: str) -> bool:
        record = self._runs.get(run_id)
        return bool(
            record and record.detail.qa_findings and not self._redo_limit_reached(record.detail)
        )

    def has_pending_interrupt(self, run_id: str) -> bool:
        record = self._runs.get(run_id)
        return bool(record and record.pending_interrupts)

    async def resume(self, run_id: str, request: HitlResumeRequest) -> RunDetail | None:
        record = self._runs.get(run_id)
        if record is None:
            return None
        if record.pending_interrupts:
            self._cancel_hitl_timeout(record)
            if request.dimensions:
                record.detail.plan.dimensions = self._normalize_requested_dimensions(
                    request.dimensions,
                    require_core_schema=self._plan_requires_core_schema(record.detail),
                )
            memory_feedback_payload = self._capture_hitl_memory_feedback(record, request)
            if memory_feedback_payload is not None:
                self._refresh_quality_metrics(record.detail)
            record.detail.status = "running"
            record.detail.updated_at = datetime.utcnow()
            self._persist_run(run_id)
            await self.emit(
                run_id,
                "node_completed",
                "hitl",
                None,
                f"HITL decision received: {request.decision}",
                request.model_dump(exclude_none=True),
            )
            if memory_feedback_payload is not None:
                await self.emit(
                    run_id,
                    "memory.feedback_captured",
                    "memory",
                    None,
                    "HITL feedback was captured as reviewable MemoryAgent candidate input.",
                    memory_feedback_payload,
                )
            asyncio.create_task(self._resume_interrupted_graph(run_id, request))
            return record.detail
        if request.decision == "redo" and not record.detail.qa_findings:
            record.detail.status = "completed"
            record.detail.current_node = None
            record.detail.updated_at = datetime.utcnow()
            self._persist_run(run_id)
            await self.emit(run_id, "node_completed", "hitl", None, "No QA findings to redo.")
            return record.detail
        if request.decision == "redo" and self._redo_limit_reached(record.detail):
            record.detail.status = "completed"
            record.detail.current_node = None
            record.detail.updated_at = datetime.utcnow()
            self._persist_run(run_id)
            await self.emit(
                run_id,
                "node_completed",
                "hitl",
                None,
                f"Maximum redo iterations reached ({record.detail.max_iterations}).",
                {"max_iterations": record.detail.max_iterations},
            )
            return record.detail
        if request.dimensions:
            record.detail.plan.dimensions = self._normalize_requested_dimensions(
                request.dimensions,
                require_core_schema=self._plan_requires_core_schema(record.detail),
            )
        memory_feedback_payload = self._capture_hitl_memory_feedback(record, request)
        if memory_feedback_payload is not None:
            self._refresh_quality_metrics(record.detail)
        record.detail.status = "running"
        record.detail.updated_at = datetime.utcnow()
        self._persist_run(run_id)
        await self.emit(
            run_id,
            "node_completed",
            "hitl",
            None,
            f"HITL decision received: {request.decision}",
            request.model_dump(exclude_none=True),
        )
        if memory_feedback_payload is not None:
            await self.emit(
                run_id,
                "memory.feedback_captured",
                "memory",
                None,
                "HITL feedback was captured as reviewable MemoryAgent candidate input.",
                memory_feedback_payload,
            )
        return record.detail

    async def run_scoped_redo(self, run_id: str, *, auto_continue: bool = False) -> None:
        record = self._runs.get(run_id)
        if record is None:
            return
        detail = record.detail
        if self._redo_limit_reached(detail):
            detail.status = "completed"
            detail.current_node = None
            detail.updated_at = datetime.utcnow()
            self._persist_run(run_id)
            await self.emit(
                run_id,
                "run_completed",
                "orchestrator",
                None,
                f"Maximum redo iterations reached ({detail.max_iterations}).",
                {"max_iterations": detail.max_iterations},
            )
            return
        if not detail.qa_findings:
            await self.emit(run_id, "node_completed", "hitl", None, "No QA findings to redo.")
            return

        issues = self._select_redo_issues(detail)
        scope = self._merge_redo_scopes(issues)
        before_report = detail.report_md
        before_issue_count = len(detail.qa_findings)
        before_issue_ids = [item.id for item in detail.qa_findings]
        selected_issue_ids = [item.id for item in issues]
        revision_iteration = len(detail.revisions) + 1
        detail.status = "running"
        detail.updated_at = datetime.utcnow()
        self._persist_run(run_id)
        await self.emit(
            run_id,
            "node_started",
            "orchestrator",
            scope.target_subagent,
            f"Scoped redo started: {scope.kind}.",
            {
                "redo_scope": scope.model_dump(mode="json"),
                "issues": [item.model_dump(mode="json") for item in issues],
            },
        )
        self._append_agent_message(
            record,
            from_agent="qa",
            to_agent=scope.kind
            if scope.kind in {"collector", "analyst", "comparator", "writer_only"}
            else "orchestrator",
            message_type="redo_request",
            payload_schema="RedoRequestPayload",
            payload={
                "redo_scope": scope.model_dump(mode="json"),
                "issues": [item.model_dump(mode="json") for item in issues],
                "issue_ids": selected_issue_ids,
            },
        )

        try:
            if detail.execution_mode == "demo":
                await self._run_demo_graph_pipeline(run_id)
                record.pending_graph_redo = PendingGraphRedo(
                    iteration=revision_iteration,
                    stage=scope.kind,
                    redo_scope=scope,
                    redo_scopes=[item.redo_scope for item in issues],
                    before_md=before_report,
                    issue_ids=selected_issue_ids,
                    qa_issue_ids_before=before_issue_ids,
                    issue_count_before=before_issue_count,
                    auto_continue=auto_continue,
                )
                await self._record_pending_graph_redo(record)
                return

            record.pending_graph_redo = PendingGraphRedo(
                iteration=revision_iteration,
                stage=scope.kind,
                redo_scope=scope,
                redo_scopes=[item.redo_scope for item in issues],
                before_md=before_report,
                issue_ids=selected_issue_ids,
                qa_issue_ids_before=before_issue_ids,
                issue_count_before=before_issue_count,
                auto_continue=auto_continue,
            )
            await self._run_real_scoped_redo(record, scope)
            if detail.status == "interrupted":
                return

            await self._finalize_scoped_redo_graph(record)
        except Exception as exc:  # noqa: BLE001 - convert background task failures into run state.
            detail.status = "failed"
            detail.current_node = None
            detail.updated_at = datetime.utcnow()
            await self.emit(
                run_id,
                "run_failed",
                "orchestrator",
                None,
                f"Scoped redo failed: {exc}",
                {"error": str(exc), "redo_scope": scope.model_dump(mode="json")},
            )

    async def stream_events(self, run_id: str):
        if self._journal is not None:
            yielded_ids: set[int] = set()
            while True:
                record = self._load_run_record(run_id)
                events = record.events if record is not None else self._journal.load_events(run_id)
                for event in events:
                    if event.id in yielded_ids:
                        continue
                    yielded_ids.add(event.id)
                    yield event
                await asyncio.sleep(0.5)

        record = self._runs[run_id]
        for event in record.events:
            yield event

        queue: asyncio.Queue[RunEvent] = asyncio.Queue()
        record.subscribers.append(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            record.subscribers.remove(queue)

    async def run_pipeline(self, run_id: str) -> RunDetail | None:
        record = self._runs.get(run_id)
        if record is None:
            return None
        try:
            if record.detail.execution_mode == "real":
                await self._run_real_pipeline(run_id)
            else:
                await self._run_demo_graph_pipeline(run_id)
        except Exception as exc:  # noqa: BLE001 - convert background task failures into run state.
            record.detail.status = "failed"
            record.detail.current_node = None
            record.detail.updated_at = datetime.utcnow()
            await self.emit(
                run_id,
                "run_failed",
                "orchestrator",
                None,
                f"Run failed: {exc}",
                {"error": str(exc)},
            )
        return record.detail

    async def _run_demo_graph_pipeline(self, run_id: str) -> None:
        record = self._runs.get(run_id)
        if record is None:
            return
        record.detail.status = "running"
        completed = await self._invoke_graph(
            record,
            kind="demo",
            thread_id=f"{run_id}:demo",
            graph_input={
                "run_id": run_id,
                "dimensions": list(record.detail.plan.dimensions),
                "current_node": "planner",
                "redo_kind": None,
                "collect_qa_attempts": 0,
                "analyst_qa_attempts": 0,
            },
        )
        if not completed:
            return
        await self._finalize_demo_pipeline(record)

    async def _run_real_pipeline(self, run_id: str) -> None:
        record = self._runs.get(run_id)
        if record is None:
            return
        record.detail.status = "running"
        completed = await self._invoke_graph(
            record,
            kind="real",
            thread_id=run_id,
            graph_input={
                "run_id": run_id,
                "dimensions": list(record.detail.plan.dimensions),
                "current_node": "planner",
                "redo_kind": None,
                "collect_qa_attempts": 0,
                "analyst_qa_attempts": 0,
            },
        )
        if not completed:
            return
        await self._finalize_real_pipeline(record)

    async def _resume_interrupted_graph(self, run_id: str, request: HitlResumeRequest) -> None:
        record = self._runs.get(run_id)
        if record is None:
            return
        kind = record.active_graph_kind or "real"
        thread_id = record.active_thread_id or run_id
        try:
            completed = await self._invoke_graph(
                record,
                kind=kind,
                thread_id=thread_id,
                graph_input=Command(resume=request.model_dump(mode="json", exclude_none=True)),
            )
            if not completed:
                return
            if kind == "scoped_redo":
                await self._finalize_scoped_redo_graph(record)
            elif kind == "demo":
                await self._finalize_demo_pipeline(record)
            else:
                await self._finalize_real_pipeline(record)
        except Exception as exc:  # noqa: BLE001 - background resume failures must surface in run state.
            record.detail.status = "failed"
            record.detail.current_node = None
            record.detail.updated_at = datetime.utcnow()
            record.pending_interrupts.clear()
            self._cancel_hitl_timeout(record)
            await self.emit(
                run_id,
                "run_failed",
                "orchestrator",
                None,
                f"Run resume failed: {exc}",
                {"error": str(exc)},
            )

    async def _invoke_graph(
        self,
        record: RunRecord,
        *,
        kind: Literal["real", "demo", "scoped_redo"],
        thread_id: str,
        graph_input: Any,
    ) -> bool:
        if kind == "real":
            graph = await self._get_real_graph()
        elif kind == "demo":
            graph = await self._get_demo_graph()
        else:
            graph = await self._get_scoped_redo_graph()
        record.active_graph_kind = kind
        record.active_thread_id = thread_id
        result = await graph.ainvoke(
            graph_input,
            config={"configurable": {"thread_id": thread_id}},
        )
        if isinstance(result, dict) and result.get("__interrupt__"):
            return False
        if record.detail.status in {"interrupted", "failed"}:
            return False
        record.active_graph_kind = None
        record.active_thread_id = None
        return True

    async def _finalize_real_pipeline(self, record: RunRecord) -> None:
        if record.detail.status == "failed":
            return
        if record.detail.status == "interrupted":
            return
        await self._record_pending_graph_redo(record)
        if await self._maybe_run_auto_redo(record):
            return

        record.detail.status = "completed"
        record.detail.current_node = None
        record.detail.updated_at = datetime.utcnow()
        projection = self._sync_enterprise_projection(record, notify_release_gate=True)
        gate = self._apply_release_gate_run_status(record, projection)
        await self._emit_quality_decision_events(record, projection, gate)
        await self.emit(
            record.detail.id,
            "run_completed",
            "orchestrator",
            None,
            self._run_completed_message(record.detail.status, "Real API run completed."),
            self._enterprise_projection_payload(projection),
        )

    async def _finalize_scoped_redo_graph(self, record: RunRecord) -> None:
        detail = record.detail
        if detail.status == "failed" or detail.status == "interrupted":
            return
        pending = record.pending_graph_redo
        await self._record_pending_graph_redo(record)
        detail.status = "completed"
        detail.current_node = None
        detail.updated_at = datetime.utcnow()
        if (pending and pending.auto_continue) and await self._maybe_run_auto_redo(record):
            return
        projection = self._sync_enterprise_projection(record, notify_release_gate=True)
        gate = self._apply_release_gate_run_status(record, projection)
        await self._emit_quality_decision_events(record, projection, gate)
        await self.emit(
            detail.id,
            "run_completed",
            "orchestrator",
            None,
            self._run_completed_message(
                detail.status,
                f"Scoped redo completed: {pending.stage if pending else 'redo'}.",
            ),
            {
                "redo_scope": pending.redo_scope.model_dump(mode="json") if pending else None,
                **self._enterprise_projection_payload(projection),
            },
        )

    async def _finalize_demo_pipeline(self, record: RunRecord) -> None:
        if record.detail.status in {"failed", "interrupted"}:
            return
        await self._record_pending_graph_redo(record)
        record.detail.status = "completed"
        record.detail.current_node = None
        record.detail.updated_at = datetime.utcnow()
        projection = self._sync_enterprise_projection(record, notify_release_gate=True)
        gate = self._apply_release_gate_run_status(record, projection)
        await self._emit_quality_decision_events(record, projection, gate)
        await self.emit(
            record.detail.id,
            "run_completed",
            "orchestrator",
            None,
            self._run_completed_message(record.detail.status, "Demo graph run completed."),
            self._enterprise_projection_payload(projection),
        )

    async def _demo_planner_step(self, record: RunRecord) -> None:
        detail = record.detail
        detail.current_node = "planner"
        if not detail.plan.competitors:
            detail.plan.competitors = ["Demo Alpha", "Demo Beta", "Demo Gamma"]
            detail.plan.homepage_hints = {
                competitor: f"https://example.com/{self._issue_id_fragment(competitor)}"
                for competitor in detail.plan.competitors
            }
            detail.competitor_discovery = CompetitorDiscovery(
                query=f"{detail.topic} competitors",
                selected_competitors=detail.plan.competitors,
                rationale="Demo topic-only run uses stable fixture competitors.",
                candidates=[
                    CompetitorCandidate(
                        name=competitor,
                        rank=index + 1,
                        selected=True,
                        rationale="Demo fixture competitor.",
                        confidence=0.75,
                    )
                    for index, competitor in enumerate(detail.plan.competitors)
                ],
            )
        self._append_agent_message(
            record,
            from_agent="planner",
            to_agent="collector_dispatch",
            message_type="analysis_plan_ready",
            payload_schema="AnalysisPlan",
            payload={"plan": detail.plan.model_dump(mode="json"), "mode": "demo_graph"},
        )
        detail.updated_at = datetime.utcnow()
        await self.emit(
            detail.id,
            "node_completed",
            "planner",
            None,
            "Demo planner completed through graph.",
            {"plan": detail.plan.model_dump(mode="json")},
        )

    async def _demo_collector_branch_step(
        self, record: RunRecord, dimension: str, competitor: str
    ) -> None:
        detail = record.detail
        branch_id = self._analyst_branch_id(dimension, competitor)
        detail.current_node = "collector"
        task_message = self._append_agent_message(
            record,
            from_agent="collector_dispatch",
            to_agent="collector",
            message_type="collect_task",
            payload_schema="CollectTaskPayload",
            payload={"competitor": competitor, "dimension": dimension, "mode": "demo_graph"},
        )
        self._consume_agent_message(record, task_message, consumer_agent="collector")
        source = self._demo_source(detail, dimension, competitor)
        detail.raw_sources.append(source)
        self._append_agent_message(
            record,
            from_agent="collector",
            to_agent="collect_join",
            message_type="raw_sources_collected",
            payload_schema="RawSource[]",
            payload={
                "competitor": competitor,
                "dimension": dimension,
                "source_ids": [source.id],
                "sources": [source.model_dump(mode="json")],
            },
            source_message_ids=[task_message.id],
        )
        detail.updated_at = datetime.utcnow()
        await self.emit(
            detail.id,
            "node_completed",
            "collector",
            branch_id,
            f"Demo collector completed {competitor} / {dimension}.",
            {"source_id": source.id},
        )

    async def _demo_collect_join_step(self, record: RunRecord, dimensions: list[str]) -> None:
        detail = record.detail
        detail.current_node = "collect_join"
        self._consume_queued_agent_messages(
            record,
            to_agent="collect_join",
            consumer_agent="collect_join",
            message_types={"raw_sources_collected"},
        )
        detail.raw_sources = self._normalize_collected_sources(detail, dimensions)
        self._append_agent_message(
            record,
            from_agent="collect_join",
            to_agent="qa",
            message_type="collect_join_completed",
            payload_schema="RawSourceDigest",
            payload={
                "dimensions": dimensions,
                "source_ids": [source.id for source in detail.raw_sources],
            },
        )
        detail.updated_at = datetime.utcnow()
        await self.emit(
            detail.id,
            "node_completed",
            "collect_join",
            "collect_join",
            "Demo collect join completed.",
        )

    async def _demo_phase_qa_step(
        self, record: RunRecord, phase: Literal["collect", "analyst"]
    ) -> None:
        detail = record.detail
        detail.current_node = f"{phase}_qa"
        detail.qa_findings = []
        self._append_agent_message(
            record,
            from_agent="qa",
            to_agent="analyst_dispatch" if phase == "collect" else "comparator",
            message_type=f"{phase}_qa_result",
            payload_schema="QCIssue[]",
            payload={"phase": phase, "qa_findings": [], "mode": "demo_graph"},
        )
        detail.updated_at = datetime.utcnow()
        await self.emit(detail.id, "node_completed", "qa", phase, f"Demo {phase} QA passed.")

    async def _demo_analyst_branch_step(
        self, record: RunRecord, dimension: str, competitor: str
    ) -> None:
        detail = record.detail
        branch_id = self._analyst_branch_id(dimension, competitor)
        detail.current_node = "analyst"
        source_ids = [
            source.id
            for source in detail.raw_sources
            if source.dimension == dimension and self._source_matches_competitor(source, competitor)
        ]
        source_suffix = f" [source:{source_ids[0]}]" if source_ids else ""
        self._merge_kb_slice(
            detail,
            dimension,
            {competitor: [f"Demo {dimension} finding for {competitor}.{source_suffix}"]},
        )
        self._append_agent_message(
            record,
            from_agent="analyst",
            to_agent="analyst_join",
            message_type="competitor_knowledge_slice",
            payload_schema="CompetitorKnowledge",
            payload={
                "competitor": competitor,
                "dimension": dimension,
                "source_ids": source_ids,
                "mode": "demo_graph",
            },
        )
        detail.updated_at = datetime.utcnow()
        await self.emit(
            detail.id,
            "node_completed",
            "analyst",
            branch_id,
            f"Demo analyst completed {competitor} / {dimension}.",
        )

    async def _demo_comparator_step(self, record: RunRecord) -> None:
        detail = record.detail
        detail.current_node = "comparator"
        detail.comparison_matrix = self._build_comparison_matrix(
            detail,
            {
                "matrix_summary": ["Demo comparison matrix generated through graph."],
                "winner_by_dimension": {},
            },
        )
        detail.updated_at = datetime.utcnow()
        await self.emit(
            detail.id, "node_completed", "comparator", None, "Demo comparator completed."
        )

    async def _demo_reflector_step(self, record: RunRecord) -> None:
        detail = record.detail
        detail.current_node = "reflector"
        detail.reflections.append(ReflectionRecord(iteration=len(detail.reflections) + 1))
        detail.updated_at = datetime.utcnow()
        await self.emit(detail.id, "node_completed", "reflector", None, "Demo reflector completed.")

    async def _demo_writer_step(self, record: RunRecord) -> None:
        detail = record.detail
        detail.current_node = "writer"
        detail.report_md = self._demo_report(detail)
        detail.updated_at = datetime.utcnow()
        projection = self._sync_enterprise_projection(record)
        await self.emit(
            detail.id,
            "report_updated",
            "writer",
            None,
            "Report markdown updated.",
            {
                "report_md": detail.report_md,
                **self._enterprise_projection_payload(projection),
            },
        )
        await self.emit(
            detail.id,
            "node_completed",
            "writer",
            None,
            "Demo writer completed.",
            self._enterprise_projection_payload(projection),
        )

    async def _demo_qa_step(self, record: RunRecord) -> None:
        detail = record.detail
        detail.current_node = "qa"
        detail.qa_findings = []
        self._append_agent_message(
            record,
            from_agent="qa",
            to_agent="orchestrator",
            message_type="final_qa_result",
            payload_schema="QCIssue[]",
            payload={"qa_findings": [], "mode": "demo_graph"},
        )
        detail.updated_at = datetime.utcnow()
        await self.emit(detail.id, "node_completed", "qa", None, "Demo QA passed.")

    async def _maybe_run_auto_redo(self, record: RunRecord) -> bool:
        detail = record.detail
        if detail.hitl_enabled or not self._settings.auto_redo_enabled:
            return False
        redo_issues = [
            issue
            for issue in detail.qa_findings
            if issue.severity == "blocker"
            or (detail.auto_redo_warn_enabled and issue.severity == "warn")
        ]
        if not redo_issues or self._redo_limit_reached(detail):
            return False
        issue_label = "QA" if detail.auto_redo_warn_enabled else "blocker QA"
        await self.emit(
            detail.id,
            "node_started",
            "orchestrator",
            "auto_redo",
            f"Auto scoped redo triggered for {len(redo_issues)} {issue_label} issue(s).",
            {
                "issue_ids": [issue.id for issue in redo_issues],
                "include_warn": detail.auto_redo_warn_enabled,
                "remaining_iterations": detail.max_iterations - len(detail.revisions),
            },
        )
        await self.run_scoped_redo(detail.id, auto_continue=True)
        return True

    async def _get_real_graph(self):
        if self._real_graph is None:
            checkpointer = await self._graph_checkpointer.open()
            self._real_graph = build_real_analysis_graph(self, checkpointer)
        return self._real_graph

    async def _get_demo_graph(self):
        if self._demo_graph is None:
            checkpointer = await self._graph_checkpointer.open()
            self._demo_graph = build_demo_analysis_graph(self, checkpointer)
        return self._demo_graph

    async def _get_scoped_redo_graph(self):
        if self._scoped_redo_graph is None:
            checkpointer = await self._graph_checkpointer.open()
            self._scoped_redo_graph = build_scoped_redo_graph(self, checkpointer)
        return self._scoped_redo_graph

    async def _maybe_interrupt(
        self,
        record: RunRecord,
        *,
        stage: str,
        message: str,
        payload: dict[str, object],
    ) -> HitlResumeRequest:
        detail = record.detail
        if not detail.hitl_enabled:
            return HitlResumeRequest(decision="accept")
        interrupt_node = f"{stage}_hitl" if stage in {"planner", "qa"} else stage
        if stage not in record.pending_interrupts:
            detail.status = "interrupted"
            detail.current_node = interrupt_node
            detail.updated_at = datetime.utcnow()
            record.pending_interrupts[stage] = {
                "stage": stage,
                "graph_kind": record.active_graph_kind,
                "thread_id": record.active_thread_id,
                "interrupt_node": interrupt_node,
            }
            self._persist_run(detail.id)
            await self.emit(
                detail.id,
                "interrupt",
                "hitl",
                stage,
                message,
                {
                    **payload,
                    "stage": stage,
                    "interrupt_node": interrupt_node,
                    "interrupt_protocol": "langgraph_interrupt_command_resume",
                    "resume_command": "Command(resume=HitlResumeRequest)",
                    "timeout_seconds": self._settings.hitl_timeout_seconds,
                    "run": detail.model_dump(mode="json"),
                },
            )
            self._schedule_hitl_timeout(record, stage)
        resumed = interrupt(
            {
                **payload,
                "stage": stage,
                "interrupt_node": interrupt_node,
                "interrupt_protocol": "langgraph_interrupt_command_resume",
                "run_id": detail.id,
            }
        )
        record.pending_interrupts.pop(stage, None)
        self._cancel_hitl_timeout(record, stage)
        if isinstance(resumed, HitlResumeRequest):
            return resumed
        if isinstance(resumed, dict):
            decision = HitlResumeRequest.model_validate(resumed)
        else:
            decision = HitlResumeRequest(decision="accept")
        if decision.dimensions:
            detail.plan.dimensions = self._normalize_requested_dimensions(
                decision.dimensions,
                require_core_schema=self._plan_requires_core_schema(detail),
            )
        return decision

    def _schedule_hitl_timeout(self, record: RunRecord, stage: str) -> None:
        seconds = self._settings.hitl_timeout_seconds
        if seconds <= 0:
            return
        existing = record.hitl_timeout_tasks.get(stage)
        if existing is not None and not existing.done():
            return

        run_id = record.detail.id

        async def auto_accept_after_timeout() -> None:
            await asyncio.sleep(seconds)
            current = self._runs.get(run_id)
            if current is None:
                return
            pending = current.pending_interrupts.get(stage)
            if not pending or current.detail.status != "interrupted":
                return
            await self.emit(
                run_id,
                "node_completed",
                "hitl",
                stage,
                f"HITL timeout reached after {seconds:g}s; auto-accepted.",
                {"stage": stage, "timeout_seconds": seconds, "decision": "accept"},
            )
            await self.resume(
                run_id,
                HitlResumeRequest(
                    decision="accept",
                    note=f"Auto-accepted after HITL timeout ({seconds:g}s).",
                ),
            )

        task = asyncio.create_task(auto_accept_after_timeout())
        record.hitl_timeout_tasks[stage] = task

        def cleanup(completed: asyncio.Task[None]) -> None:
            current = self._runs.get(run_id)
            if current is not None and current.hitl_timeout_tasks.get(stage) is completed:
                current.hitl_timeout_tasks.pop(stage, None)

        task.add_done_callback(cleanup)

    def _cancel_hitl_timeout(self, record: RunRecord, stage: str | None = None) -> None:
        current_task = asyncio.current_task()
        stages = [stage] if stage is not None else list(record.hitl_timeout_tasks)
        for item in stages:
            task = record.hitl_timeout_tasks.pop(item, None)
            if task is None or task.done() or task is current_task:
                continue
            task.cancel()

    async def _run_real_scoped_redo(self, record: RunRecord, scope: RedoScope) -> None:
        detail = record.detail
        dimensions, target_competitors = self._prepare_redo_scope_inputs(detail, scope)
        completed = await self._invoke_graph(
            record,
            kind="scoped_redo",
            thread_id=f"{detail.id}:redo:{len(detail.revisions) + 1}",
            graph_input={
                "run_id": detail.id,
                "dimensions": dimensions,
                "target_competitors": target_competitors,
                "current_node": "redo_router",
                "redo_kind": scope.kind,
                "collect_qa_attempts": 0,
                "analyst_qa_attempts": 0,
            },
        )
        if not completed:
            return

    def _prepare_redo_scope_inputs(
        self, detail: RunDetail, scope: RedoScope
    ) -> tuple[list[str], list[str]]:
        dimensions = list(detail.plan.dimensions)
        target_competitors: list[str] = []
        if scope.kind in {"analyst", "collector"}:
            dimension = scope.target_subagent or (
                detail.plan.dimensions[0] if detail.plan.dimensions else None
            )
            if dimension is None:
                raise ValueError("Cannot redo analyst/collector scope without a target dimension.")
            dimensions = [dimension]
            scoped_competitors = scope.target_competitors or (
                [scope.target_competitor] if scope.target_competitor else []
            )
            if scope.kind == "collector":
                if scoped_competitors:
                    target_competitors = scoped_competitors
                    detail.raw_sources = [
                        source
                        for source in detail.raw_sources
                        if not (
                            source.dimension == dimension
                            and any(
                                self._source_matches_competitor(source, competitor)
                                for competitor in scoped_competitors
                            )
                        )
                    ]
                    for competitor in scoped_competitors:
                        self._clear_competitor_dimension_output(detail, competitor, dimension)
                else:
                    detail.raw_sources = [
                        source for source in detail.raw_sources if source.dimension != dimension
                    ]
                    self._clear_dimension_outputs(detail, dimension)
            elif scoped_competitors:
                target_competitors = scoped_competitors
                for competitor in scoped_competitors:
                    self._clear_competitor_dimension_output(detail, competitor, dimension)
            else:
                self._clear_dimension_outputs(detail, dimension)
        elif scope.kind == "full":
            detail.raw_sources = []
            detail.competitor_kbs = {}
            detail.competitor_knowledge = {}
            detail.comparison_matrix = None
            detail.reflections = []
            detail.qa_findings = []
            detail.report_md = ""

        if scope.kind in {"collector", "analyst", "comparator", "full"}:
            detail.comparison_matrix = None
            detail.reflections = []
        detail.updated_at = datetime.utcnow()
        self._persist_run(detail.id)
        return dimensions, target_competitors

    async def _prepare_graph_redo_from_qa(self, record: RunRecord) -> dict[str, object]:
        detail = record.detail
        if not detail.qa_findings:
            await self.emit(detail.id, "node_completed", "hitl", "qa", "No QA findings to redo.")
            return {"redo_kind": "end"}
        if self._redo_limit_reached(detail):
            detail.status = "failed"
            detail.current_node = "qa_hitl"
            detail.updated_at = datetime.utcnow()
            self._persist_run(detail.id)
            await self.emit(
                detail.id,
                "run_failed",
                "qa",
                None,
                f"Maximum redo iterations reached ({detail.max_iterations}).",
                {"max_iterations": detail.max_iterations},
            )
            return {"redo_kind": "end"}

        issues = self._select_redo_issues(detail)
        scope = self._merge_redo_scopes(issues)
        before_report = detail.report_md
        before_issue_ids = [item.id for item in detail.qa_findings]
        selected_issue_ids = [item.id for item in issues]
        revision_iteration = len(detail.revisions) + 1
        record.pending_graph_redo = PendingGraphRedo(
            iteration=revision_iteration,
            stage=scope.kind,
            redo_scope=scope,
            redo_scopes=[item.redo_scope for item in issues],
            before_md=before_report,
            issue_ids=selected_issue_ids,
            qa_issue_ids_before=before_issue_ids,
            issue_count_before=len(detail.qa_findings),
        )
        self._append_agent_message(
            record,
            from_agent="qa",
            to_agent=scope.kind
            if scope.kind in {"collector", "analyst", "comparator", "writer_only"}
            else "orchestrator",
            message_type="redo_request",
            payload_schema="RedoRequestPayload",
            payload={
                "redo_scope": scope.model_dump(mode="json"),
                "issues": [item.model_dump(mode="json") for item in issues],
                "issue_ids": selected_issue_ids,
                "routing": "graph_conditional_edge",
            },
        )
        dimensions, target_competitors = self._prepare_redo_scope_inputs(detail, scope)
        await self.emit(
            detail.id,
            "node_started",
            "orchestrator",
            scope.target_subagent,
            f"QA routed graph redo through DAG edge: {scope.kind}.",
            {
                "redo_scope": scope.model_dump(mode="json"),
                "dimensions": dimensions,
                "target_competitors": target_competitors,
            },
        )
        return {
            "redo_kind": scope.kind,
            "dimensions": dimensions,
            "target_competitors": target_competitors,
            "collect_qa_attempts": 0,
            "analyst_qa_attempts": 0,
        }

    async def emit(
        self,
        run_id: str,
        event_type: str,
        agent: str | None,
        subagent: str | None,
        message: str,
        payload: dict | None = None,
    ) -> None:
        record = self._runs[run_id]
        event = build_run_event(
            event_id=len(record.events) + 1,
            run_id=run_id,
            event_type=event_type,
            agent=agent,
            subagent=subagent,
            message=message,
            payload=payload or {},
        )
        record.events.append(event)
        self._persist_run(run_id)
        if self._journal is not None:
            self._journal.append_event(event)
        for queue in list(record.subscribers):
            await queue.put(event)

    def _append_agent_message(
        self,
        record: RunRecord,
        *,
        from_agent: str,
        to_agent: str,
        message_type: str,
        payload_schema: str,
        payload: dict[str, Any] | None = None,
        source_message_ids: list[str] | None = None,
        trace_span_ids: list[str] | None = None,
    ) -> AgentMessage:
        message = AgentMessage(
            id=f"msg-{len(record.detail.agent_messages) + 1}",
            run_id=record.detail.id,
            from_agent=from_agent,
            to_agent=to_agent,
            message_type=message_type,
            payload_schema=payload_schema,
            payload=payload or {},
            source_message_ids=source_message_ids or [],
            trace_span_ids=trace_span_ids or [],
        )
        record.detail.agent_messages.append(message)
        if trace_span_ids is None:
            message.trace_span_ids = [self._append_agent_message_trace_span(record, message)]
        if self._trace_store is not None:
            self._trace_store.append_agent_message(message)
        record.detail.updated_at = datetime.utcnow()
        self._persist_run(record.detail.id)
        return message

    def _consume_agent_message(
        self,
        record: RunRecord,
        message: AgentMessage,
        *,
        consumer_agent: str,
        context: SubagentContext | None = None,
    ) -> AgentMessage:
        if message.status == "consumed":
            return message
        message.status = "consumed"
        message.consumed_by = consumer_agent
        message.consumed_at = datetime.utcnow()
        message.consumer_context_id = context.context_id if context is not None else None
        if context is not None:
            context.add_message(
                "agent_message",
                json.dumps(
                    self._agent_message_context_payload(message),
                    ensure_ascii=False,
                    default=str,
                ),
            )
        input_text = json.dumps(message.model_dump(mode="json"), ensure_ascii=False, default=str)
        output_text = json.dumps(
            {
                "message_id": message.id,
                "consumed_by": consumer_agent,
                "consumer_context_id": message.consumer_context_id,
            },
            ensure_ascii=False,
        )
        self._append_trace_span(
            record,
            kind="tool",
            agent=consumer_agent,
            subagent=self._agent_message_subagent(message),
            name=f"agent_message_consumed:{message.message_type}",
            status="ok",
            started=time.perf_counter(),
            input_text=input_text,
            output_text=output_text,
            metadata=self._trace_metadata(
                context,
                {
                    "message_id": message.id,
                    "from_agent": message.from_agent,
                    "to_agent": message.to_agent,
                    "payload_schema": message.payload_schema,
                    "message_status": message.status,
                },
            ),
            source_message_id=message.id,
        )
        if self._trace_store is not None:
            self._trace_store.append_agent_message(message)
        record.detail.updated_at = datetime.utcnow()
        self._persist_run(record.detail.id)
        return message

    def _agent_message_context_payload(self, message: AgentMessage) -> dict[str, Any]:
        payload = message.payload
        compact_payload: dict[str, Any] = {}
        for key in (
            "topic",
            "competitor",
            "dimension",
            "source_ids",
            "claim_ids",
            "qa_feedback",
            "redo_scope",
            "branch_count",
            "count",
        ):
            if key in payload:
                compact_payload[key] = payload[key]
        return {
            "id": message.id,
            "from": message.from_agent,
            "to": message.to_agent,
            "message_type": message.message_type,
            "payload_schema": message.payload_schema,
            "payload": compact_payload,
        }

    def _consume_queued_agent_messages(
        self,
        record: RunRecord,
        *,
        to_agent: str,
        consumer_agent: str | None = None,
        message_types: set[str] | None = None,
        dimension: str | None = None,
        competitor: str | None = None,
        context: SubagentContext | None = None,
    ) -> list[AgentMessage]:
        consumed: list[AgentMessage] = []
        for message in record.detail.agent_messages:
            if message.status != "queued" or message.to_agent != to_agent:
                continue
            if message_types is not None and message.message_type not in message_types:
                continue
            if dimension is not None and message.payload.get("dimension") not in {None, dimension}:
                continue
            if competitor is not None and message.payload.get("competitor") not in {
                None,
                competitor,
            }:
                continue
            consumed.append(
                self._consume_agent_message(
                    record,
                    message,
                    consumer_agent=consumer_agent or to_agent,
                    context=context,
                )
            )
        return consumed

    def _append_agent_message_trace_span(self, record: RunRecord, message: AgentMessage) -> str:
        input_text = json.dumps(
            {
                "from_agent": message.from_agent,
                "to_agent": message.to_agent,
                "message_type": message.message_type,
                "payload_schema": message.payload_schema,
                "payload": message.payload,
                "source_message_ids": message.source_message_ids,
            },
            ensure_ascii=False,
            default=str,
        )
        output_text = json.dumps(
            {
                "message_id": message.id,
                "traceable": True,
                "payload_schema": message.payload_schema,
            },
            ensure_ascii=False,
        )
        redacted_input_text, redacted_output_text, redaction_metadata = self._redact_trace_texts(
            input_text,
            output_text,
        )
        span_id = f"span-{len(record.detail.trace_spans) + 1}"
        trace_id = trace_id_for_run(record.detail.id)
        otel_span_id = otel_span_id_for_span(record.detail.id, span_id)
        traceparent = traceparent_for_span(trace_id, otel_span_id)
        span = TraceSpan(
            id=span_id,
            trace_id=trace_id,
            otel_span_id=otel_span_id,
            traceparent=traceparent,
            kind="tool",
            agent=message.from_agent,
            subagent=self._agent_message_subagent(message),
            name=f"agent_message:{message.message_type}",
            status="ok",
            duration_ms=0,
            input_chars=len(input_text),
            output_chars=len(output_text),
            input_tokens_estimate=self._estimate_tokens(input_text),
            output_tokens_estimate=self._estimate_tokens(output_text),
            input_preview=self._preview(redacted_input_text),
            output_preview=self._preview(redacted_output_text),
            full_input=redacted_input_text,
            full_output=redacted_output_text,
            metadata={
                "message_id": message.id,
                "to_agent": message.to_agent,
                "message_type": message.message_type,
                "payload_schema": message.payload_schema,
                "source_message_count": len(message.source_message_ids),
                "trace_id": trace_id,
                "otel_span_id": otel_span_id,
                "traceparent": traceparent,
                **redaction_metadata,
            },
        )
        record.detail.trace_spans.append(span)
        if self._trace_store is not None:
            self._trace_store.append_span(record.detail.id, span)
        if self._langfuse.enabled:
            self._langfuse.mirror_span(record.detail.id, span)
        self._rebuild_metrics(record.detail)
        return span_id

    def _agent_message_subagent(self, message: AgentMessage) -> str | None:
        payload = message.payload
        dimension = payload.get("dimension")
        competitor = payload.get("competitor")
        if isinstance(payload.get("redo_scope"), dict):
            redo_scope = payload["redo_scope"]
            dimension = redo_scope.get("target_subagent") or dimension
            competitor = redo_scope.get("target_competitor") or competitor
        if isinstance(dimension, str) and isinstance(competitor, str):
            return self._analyst_branch_id(dimension, competitor)
        if isinstance(dimension, str):
            return dimension
        return None

    def _append_tool_call_message(
        self,
        record: RunRecord,
        *,
        agent: str,
        subagent: str | None,
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        status: Literal["ok", "error"],
        trace_span_id: str | None,
        source_message_id: str | None = None,
    ) -> ToolCallMessage:
        message = ToolCallMessage(
            id=f"tool-{len(record.detail.tool_call_messages) + 1}",
            run_id=record.detail.id,
            agent=agent,
            subagent=subagent,
            tool_name=tool_name,
            arguments=arguments,
            result=result,
            status=status,
            trace_span_id=trace_span_id,
            source_message_id=source_message_id,
        )
        record.detail.tool_call_messages.append(message)
        if self._trace_store is not None:
            self._trace_store.append_tool_call_message(message)
        record.detail.updated_at = datetime.utcnow()
        self._persist_run(record.detail.id)
        return message

    async def _emit_quality_decision_events(
        self,
        record: RunRecord,
        projection: EnterpriseRunProjection | None,
        gate: ReportReleaseGate | None,
    ) -> None:
        detail = record.detail
        if projection is not None:
            validation = validate_project_claims(
                project_id=projection.project_id,
                claims=projection.claim_records,
                evidence=projection.evidence_records,
            )
            await self.emit(
                detail.id,
                "claim.validated",
                "quality",
                None,
                (
                    f"Validated {len(projection.claim_records)} claim(s) against "
                    f"{len(projection.evidence_records)} evidence record(s)."
                ),
                {
                    "claim_ids": [claim.id for claim in projection.claim_records],
                    "evidence_ids": [evidence.id for evidence in projection.evidence_records],
                    "claim_validation": validation.model_dump(mode="json"),
                    "claim_status_counts": {
                        "supported": validation.supported_count,
                        "weak": validation.weak_count,
                        "unsupported": validation.unsupported_count,
                        "blocked": validation.blocked_count,
                    },
                    "report_version_id": projection.report_version.id,
                    "release_gate": gate.model_dump(mode="json") if gate is not None else None,
                },
            )
            await self.emit(
                detail.id,
                "self_consistency.sampled",
                "quality",
                None,
                "Self-consistency sampled text support, evidence quality, and triangulation.",
                {
                    "claim_ids": [claim.id for claim in projection.claim_records],
                    "evidence_ids": [evidence.id for evidence in projection.evidence_records],
                    "self_consistency_score": validation.self_consistency_score,
                    "validation_sample_count": sum(
                        len(result.validation_samples) for result in validation.results
                    ),
                    "validation_samples": _claim_validation_sample_payload(validation),
                    "sample_dimensions": [
                        "text_support",
                        "evidence_quality",
                        "triangulation",
                    ],
                    "consistency_votes": _aggregate_consistency_votes(validation),
                    "low_consistency_count": validation.low_consistency_count,
                    "claim_validation_issue_count": validation.issue_count,
                    "reason": "Derived from claim validator and release-gate evidence checks.",
                },
            )
        await self.emit(
            detail.id,
            "benchmark.scored",
            "observability",
            None,
            "Run metrics were scored for replay and quality review.",
            {"metrics": detail.metrics.model_dump(mode="json")},
        )

    def _sync_enterprise_projection(
        self,
        record: RunRecord,
        *,
        notify_release_gate: bool = False,
    ) -> EnterpriseRunProjection | None:
        if self._enterprise_store is None:
            return None

        detail = record.detail
        context = self._enterprise_store.start_run(
            detail,
            workspace_id=detail.workspace_id,
            project_id=detail.project_id,
        )
        detail.workspace_id = context.workspace_id
        detail.project_id = context.project_id
        competitor_set_hash = compute_competitor_set_hash(context.competitor_ids)
        topic_normalized = compute_topic_normalized(detail.topic)
        existing_projection = self._enterprise_store.get_run_projection(detail.id)
        if existing_projection is not None:
            version_number = existing_projection.report_version.version_number
        else:
            version_number = self._enterprise_store.next_report_version_number(
                project_id=context.project_id,
                topic_normalized=topic_normalized,
                competitor_layer=detail.plan.competitor_layer,
                competitor_set_hash=competitor_set_hash,
            )
        projection = build_enterprise_projection(
            detail,
            workspace_id=context.workspace_id,
            project_id=context.project_id,
            version_number=version_number,
            competitor_layer=detail.plan.competitor_layer,
            competitor_id_map=context.competitor_id_map,
        )
        self._enterprise_store.save_projection(projection)
        gate = self._evaluate_report_release_gate(projection)
        if notify_release_gate:
            self._record_release_gate_notification(projection, gate)
        self._record_usage_governance_notification(context.workspace_id, detail.id)
        return projection

    def get_enterprise_projection(self, run_id: str) -> EnterpriseRunProjection | None:
        if self._enterprise_store is None:
            return None
        return self._enterprise_store.get_run_projection(run_id)

    def _enterprise_projection_payload(
        self,
        projection: EnterpriseRunProjection | None,
    ) -> dict[str, Any]:
        if projection is None:
            return {}
        return {
            "enterprise_projection": {
                "project_id": projection.project_id,
                "evidence_count": len(projection.evidence_records),
                "claim_count": len(projection.claim_records),
                "report_version_id": projection.report_version.id,
                **self._release_gate_payload(projection),
            }
        }

    def _evaluate_report_release_gate(
        self,
        projection: EnterpriseRunProjection,
    ) -> ReportReleaseGate | None:
        if self._enterprise_store is None:
            return None
        project = self._enterprise_store.get_project(projection.project_id)
        if project is None:
            return None
        return evaluate_report_release_gate(
            project=project,
            report_version=projection.report_version,
            competitors=self._enterprise_store.list_competitors(project_id=project.id),
            evidence=self._enterprise_store.list_evidence(project_id=project.id),
            claims=self._enterprise_store.list_claims(project_id=project.id),
        )

    def _release_gate_payload(self, projection: EnterpriseRunProjection) -> dict[str, Any]:
        gate = self._evaluate_report_release_gate(projection)
        if gate is None:
            return {}
        return {
            "release_gate": {
                "allowed": gate.allowed,
                "status": gate.status,
                "readiness_score": gate.readiness.score,
                "readiness_risk_level": gate.readiness.risk_level,
                "qa_finding_count": gate.qa_evaluation.finding_count,
                "blocker_count": gate.blocker_count,
                "warn_count": gate.warn_count,
                "issue_count": gate.issue_count,
                "top_issues": [
                    {
                        "rule_id": issue.rule_id,
                        "message": issue.message,
                        "recommendation": issue.recommendation,
                    }
                    for issue in gate.issues[:3]
                ],
            }
        }

    def _apply_release_gate_run_status(
        self,
        record: RunRecord,
        projection: EnterpriseRunProjection | None,
    ) -> ReportReleaseGate | None:
        if projection is None or record.detail.status != "completed":
            return None
        gate = self._evaluate_report_release_gate(projection)
        if gate is None or gate.allowed:
            return gate
        record.detail.status = "completed_with_blockers"
        record.detail.updated_at = datetime.utcnow()
        return gate

    def _run_completed_message(self, status: str, base_message: str) -> str:
        if status == "completed_with_blockers":
            return f"{base_message} Release gate blocked the report for review."
        return base_message

    def _ensure_workspace_quota_allows_run(self, workspace_id: str) -> None:
        if self._enterprise_store is None:
            return
        decision = self._enterprise_store.check_workspace_quota(workspace_id)
        if not decision.allowed:
            raise WorkspaceQuotaExceededError(decision)

    def _record_usage_governance_notification(
        self,
        workspace_id: str,
        run_id: str,
    ) -> None:
        if self._enterprise_store is None:
            return
        decision = self._enterprise_store.check_workspace_quota(workspace_id)
        if decision.status == "ok":
            return
        usage = decision.usage
        period_key = usage.period_start.strftime("%Y%m")
        notification = NotificationRecord(
            id=f"quota-{workspace_id}-{period_key}",
            workspace_id=workspace_id,
            notification_type="quota_warning",
            severity="critical" if decision.status == "exceeded" else "warning",
            status="queued",
            title="Workspace quota needs attention",
            body=decision.reason,
            resource_type="workspace_usage",
            resource_id=workspace_id,
            created_by="system-user",
            metadata={
                "run_id": run_id,
                "period_start": usage.period_start.isoformat(),
                "period_end": usage.period_end.isoformat(),
                "run_usage_ratio": usage.run_usage_ratio,
                "token_usage_ratio": usage.token_usage_ratio,
                "cost_usage_ratio": usage.cost_usage_ratio,
                "cost_estimate_usd": usage.cost_estimate_usd,
                "total_tokens_estimate": usage.total_tokens_estimate,
                "enforcement": decision.enforcement,
            },
        )
        self._enterprise_store.upsert_notification(notification)

    def _record_release_gate_notification(
        self,
        projection: EnterpriseRunProjection,
        gate: ReportReleaseGate | None,
    ) -> None:
        if self._enterprise_store is None or gate is None or gate.allowed:
            return
        top_issue_messages = [issue.message for issue in gate.issues[:3]]
        notification = NotificationRecord(
            id=f"release-gate-{projection.report_version.id}",
            workspace_id=projection.workspace_id,
            project_id=projection.project_id,
            notification_type="release_gate_blocked",
            severity="critical",
            status="queued",
            title="Report blocked by release gate",
            body="; ".join(top_issue_messages)
            or "Report is not ready for enterprise approval.",
            resource_type="report_version",
            resource_id=projection.report_version.id,
            created_by="system-user",
            metadata={
                "run_id": projection.run_id,
                "report_version_id": projection.report_version.id,
                "readiness_score": gate.readiness.score,
                "readiness_risk_level": gate.readiness.risk_level,
                "qa_finding_count": gate.qa_evaluation.finding_count,
                "blocker_count": gate.blocker_count,
                "warn_count": gate.warn_count,
                "issue_count": gate.issue_count,
                "issues": [issue.model_dump(mode="json") for issue in gate.issues[:5]],
            },
        )
        self._enterprise_store.upsert_notification(notification)

    def _hydrate_runs(self) -> None:
        if self._journal is None:
            return
        for detail in self._journal.load_runs():
            self._runs[detail.id] = RunRecord(
                detail=detail,
                events=self._journal.load_events(detail.id),
            )

    def _refresh_runs_from_journal(self) -> None:
        if self._journal is None:
            return
        for detail in self._journal.load_runs():
            self._upsert_journal_run(detail)

    def _load_run_record(self, run_id: str) -> RunRecord | None:
        record = self._runs.get(run_id)
        if self._journal is None:
            return record
        detail = self._journal.load_run(run_id)
        if detail is None:
            return record
        return self._upsert_journal_run(detail)

    def _upsert_journal_run(self, detail: RunDetail) -> RunRecord:
        events = self._journal.load_events(detail.id) if self._journal is not None else []
        record = self._runs.get(detail.id)
        if record is None:
            record = RunRecord(detail=detail, events=events)
            self._runs[detail.id] = record
            return record
        record.detail = detail
        record.events = events
        return record

    def _persist_run(self, run_id: str) -> None:
        if self._journal is None:
            return
        record = self._runs.get(run_id)
        if record is not None:
            self._journal.save_run(record.detail)

    async def _record_revision(
        self,
        record: RunRecord,
        *,
        iteration: int,
        stage: str,
        redo_scope: RedoScope,
        redo_scopes: list[RedoScope],
        before_md: str,
        issue_ids: list[str],
        qa_issue_ids_before: list[str],
        issue_count_before: int,
    ) -> None:
        detail = record.detail
        revision = build_revision_record(
            detail,
            iteration=iteration,
            stage=stage,
            redo_scope=redo_scope,
            redo_scopes=redo_scopes,
            before_md=before_md,
            issue_ids=issue_ids,
            qa_issue_ids_before=qa_issue_ids_before,
            issue_count_before=issue_count_before,
        )
        detail.revisions.append(revision)
        detail.updated_at = datetime.utcnow()
        self._refresh_quality_metrics(detail)
        await self.emit(
            detail.id,
            "revision_recorded",
            "orchestrator",
            None,
            (
                f"Revision {iteration} recorded with convergence ratio "
                f"{revision.convergence_ratio:.2f}."
            ),
            {"revision": revision.model_dump(mode="json")},
        )

    async def _record_pending_graph_redo(self, record: RunRecord) -> None:
        pending = record.pending_graph_redo
        if pending is None:
            return
        record.pending_graph_redo = None
        await self._record_revision(
            record,
            iteration=pending.iteration,
            stage=pending.stage,
            redo_scope=pending.redo_scope,
            redo_scopes=pending.redo_scopes,
            before_md=pending.before_md,
            issue_ids=pending.issue_ids,
            qa_issue_ids_before=pending.qa_issue_ids_before,
            issue_count_before=pending.issue_count_before,
        )

    def _convergence_ratio(self, issue_count_before: int, issue_count_after: int) -> float:
        return convergence_ratio(issue_count_before, issue_count_after)

    def _select_redo_issue(self, detail: RunDetail) -> QCIssue:
        issue_attempts: dict[str, int] = {}
        scope_attempts: dict[str, int] = {}
        for revision in detail.revisions:
            for issue_id in revision.issue_ids:
                issue_attempts[issue_id] = issue_attempts.get(issue_id, 0) + 1
            for scope in revision.redo_scopes:
                scope_key = self._redo_scope_key(scope)
                scope_attempts[scope_key] = scope_attempts.get(scope_key, 0) + 1

        def rank(issue: QCIssue) -> tuple[int, int, int, int, int, str]:
            scope = issue.redo_scope
            scope_key = self._redo_scope_key(scope)
            kind_rank = {
                "collector": 0,
                "analyst": 1,
                "comparator": 2,
                "writer_only": 3,
                "full": 4,
            }.get(scope.kind, 5)
            return (
                {"blocker": 0, "warn": 1, "info": 2}.get(issue.severity, 3),
                issue_attempts.get(issue.id, 0) + scope_attempts.get(scope_key, 0),
                0 if scope.target_competitor else 1,
                kind_rank,
                0 if issue.detected_by in {"schema", "citation", "coverage"} else 1,
                issue.id,
            )

        return sorted(detail.qa_findings, key=rank)[0]

    def _select_redo_issues(self, detail: RunDetail) -> list[QCIssue]:
        clustered = self._select_largest_batchable_redo_cluster(detail)
        if clustered:
            return clustered

        primary = self._select_redo_issue(detail)
        primary_scope = primary.redo_scope
        if primary_scope.kind not in {"collector", "analyst"} or not primary_scope.target_subagent:
            return [primary]

        selected = [primary]
        selected_ids = {primary.id}
        selected_competitors = {
            competitor
            for competitor in [primary_scope.target_competitor, *primary_scope.target_competitors]
            if competitor
        }
        for candidate in sorted(detail.qa_findings, key=lambda issue: issue.id):
            if candidate.id in selected_ids:
                continue
            scope = candidate.redo_scope
            if (
                scope.kind != primary_scope.kind
                or scope.target_subagent != primary_scope.target_subagent
            ):
                continue
            candidate_competitors = {
                competitor
                for competitor in [scope.target_competitor, *scope.target_competitors]
                if competitor
            }
            if not candidate_competitors:
                continue
            if candidate_competitors & selected_competitors:
                continue
            selected.append(candidate)
            selected_ids.add(candidate.id)
            selected_competitors.update(candidate_competitors)
            if len(selected) >= 3:
                break
        return selected

    def _select_largest_batchable_redo_cluster(self, detail: RunDetail) -> list[QCIssue]:
        if not detail.qa_findings:
            return []
        severity_rank = {"blocker": 0, "warn": 1, "info": 2}
        best_severity = min(severity_rank.get(issue.severity, 3) for issue in detail.qa_findings)
        groups: dict[tuple[str, str], list[QCIssue]] = {}
        for issue in detail.qa_findings:
            if severity_rank.get(issue.severity, 3) != best_severity:
                continue
            scope = issue.redo_scope
            if scope.kind not in {"collector", "analyst"} or not scope.target_subagent:
                continue
            competitors = [scope.target_competitor, *scope.target_competitors]
            if not any(competitor for competitor in competitors):
                continue
            groups.setdefault((scope.kind, scope.target_subagent), []).append(issue)

        candidates: list[tuple[int, str, str, list[QCIssue]]] = []
        for (kind, subagent), issues in groups.items():
            competitor_count = len(
                {
                    competitor
                    for issue in issues
                    for competitor in [
                        issue.redo_scope.target_competitor,
                        *issue.redo_scope.target_competitors,
                    ]
                    if competitor
                }
            )
            if competitor_count >= 2:
                candidates.append((competitor_count, kind, subagent, issues))
        if not candidates:
            return []

        _, _, _, selected_group = sorted(
            candidates,
            key=lambda item: (-item[0], item[1], item[2]),
        )[0]
        selected: list[QCIssue] = []
        selected_competitors: set[str] = set()
        for issue in sorted(selected_group, key=lambda item: item.id):
            competitors = [
                competitor
                for competitor in [
                    issue.redo_scope.target_competitor,
                    *issue.redo_scope.target_competitors,
                ]
                if competitor
            ]
            if any(competitor in selected_competitors for competitor in competitors):
                continue
            selected.append(issue)
            selected_competitors.update(competitors)
            if len(selected) >= 3:
                break
        return selected

    def _merge_redo_scopes(self, issues: list[QCIssue]) -> RedoScope:
        primary = issues[0].redo_scope
        if len(issues) == 1:
            return primary
        competitors = sorted(
            {
                competitor
                for issue in issues
                for competitor in [
                    issue.redo_scope.target_competitor,
                    *issue.redo_scope.target_competitors,
                ]
                if competitor
            }
        )
        return RedoScope(
            kind=primary.kind,
            target_subagent=primary.target_subagent,
            target_competitor=competitors[0] if len(competitors) == 1 else None,
            target_competitors=competitors,
            rationale=(
                f"Batch redo for {len(issues)} {primary.kind} issue(s) in "
                f"{primary.target_subagent or 'all'}: "
                + "; ".join(issue.problem for issue in issues[:3])
            ),
        )

    def _redo_scope_key(self, scope: RedoScope) -> str:
        competitors = (
            ",".join(scope.target_competitors)
            if scope.target_competitors
            else scope.target_competitor or "*"
        )
        return f"{scope.kind}:{competitors}:{scope.target_subagent or '*'}"

    async def _trace_llm_json(
        self,
        record: RunRecord,
        *,
        agent: str,
        subagent: str | None,
        name: str,
        system: str,
        user: str,
        schema_hint: str,
        context: SubagentContext | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        input_text = f"{system}\n\n{user}\n\nSchema: {schema_hint}"
        if context is not None:
            context.add_message("system", system)
            context.add_message("user", user)
        try:
            payload = await self._llm.complete_json(
                system=system, user=user, schema_hint=schema_hint
            )
        except Exception as exc:
            self._append_trace_span(
                record,
                kind="llm",
                agent=agent,
                subagent=subagent,
                name=name,
                status="error",
                started=started,
                input_text=input_text,
                output_text=str(exc),
                metadata=self._trace_metadata(context, {"error": str(exc)}),
            )
            raise
        usage = self._consume_llm_usage()
        output_text = json.dumps(payload, ensure_ascii=False)
        if context is not None:
            context.add_message("assistant", output_text)
        self._append_trace_span(
            record,
            kind="llm",
            agent=agent,
            subagent=subagent,
            name=name,
            status="ok",
            started=started,
            input_text=input_text,
            output_text=output_text,
            metadata=self._trace_metadata(
                context, {"response_format": "json", **self._llm_usage_metadata(usage)}
            ),
            token_usage=usage,
        )
        return payload

    async def _trace_llm_text(
        self,
        record: RunRecord,
        *,
        agent: str,
        subagent: str | None,
        name: str,
        system: str,
        user: str,
        context: SubagentContext | None = None,
    ) -> str:
        started = time.perf_counter()
        input_text = f"{system}\n\n{user}"
        if context is not None:
            context.add_message("system", system)
            context.add_message("user", user)
        try:
            output = await self._llm.complete_text(system=system, user=user)
        except Exception as exc:
            self._append_trace_span(
                record,
                kind="llm",
                agent=agent,
                subagent=subagent,
                name=name,
                status="error",
                started=started,
                input_text=input_text,
                output_text=str(exc),
                metadata=self._trace_metadata(context, {"error": str(exc)}),
            )
            raise
        usage = self._consume_llm_usage()
        if context is not None:
            context.add_message("assistant", output)
        self._append_trace_span(
            record,
            kind="llm",
            agent=agent,
            subagent=subagent,
            name=name,
            status="ok",
            started=started,
            input_text=input_text,
            output_text=output,
            metadata=self._trace_metadata(
                context, {"response_format": "text", **self._llm_usage_metadata(usage)}
            ),
            token_usage=usage,
        )
        return output

    async def _trace_search(
        self,
        record: RunRecord,
        *,
        agent: str,
        subagent: str | None,
        query: str,
        max_results: int,
        context: SubagentContext | None = None,
    ) -> list[SearchResult]:
        started = time.perf_counter()
        if context is not None:
            context.add_tool_call("web_search", query)
        try:
            results = await web_search(
                self._search,
                WebSearchRequest(query=query, max_results=max_results),
            )
        except Exception as exc:
            self._append_trace_span(
                record,
                kind="search",
                agent=agent,
                subagent=subagent,
                name="web_search",
                status="error",
                started=started,
                input_text=query,
                output_text=str(exc),
                metadata=self._trace_metadata(
                    context,
                    {"provider": self._settings.web_search_provider, "error": str(exc)},
                ),
            )
            raise
        output_text = json.dumps([result.__dict__ for result in results], ensure_ascii=False)
        span_id = self._append_trace_span(
            record,
            kind="search",
            agent=agent,
            subagent=subagent,
            name="web_search",
            status="ok",
            started=started,
            input_text=query,
            output_text=output_text,
            metadata=self._trace_metadata(
                context,
                {
                    "provider": self._settings.web_search_provider,
                    "result_count": len(results),
                    "max_results": max_results,
                },
            ),
        )
        await self.emit(
            record.detail.id,
            "tool.called",
            agent,
            subagent,
            f"web_search returned {len(results)} result(s).",
            {
                "tool": "web_search",
                "query": query,
                "result_count": len(results),
                "related_span_ids": [span_id],
                "input": query,
                "output": f"{len(results)} result(s)",
            },
        )
        await self.emit(
            record.detail.id,
            "rag.retrieved",
            agent,
            subagent,
            f"Retrieved {len(results)} search candidate(s) for RAG grounding.",
            {
                "query": query,
                "result_count": len(results),
                "candidate_urls": [result.url for result in results[:5]],
                "related_span_ids": [span_id],
                "reason": "Search candidates provide online evidence candidates for collectors.",
            },
        )
        return results

    async def _trace_fetch(
        self,
        record: RunRecord,
        agent: str,
        subagent: str | None,
        url: str,
        context: SubagentContext | None = None,
    ):
        robots_result = await self._trace_robots(record, agent, subagent, url, context)
        if not robots_result.allowed:
            from packages.tools import FetchPageResult

            return FetchPageResult(
                url=url,
                ok=False,
                title="",
                text="",
                content_hash=hashlib.sha256(f"robots:{url}".encode()).hexdigest()[:16],
                error=f"Blocked by robots.txt at {robots_result.robots_url}",
            )
        started = time.perf_counter()
        if context is not None:
            context.add_tool_call("fetch_page", url)
        result = await fetch_page(url)
        metadata: dict[str, str | int | float | bool | None] = {
            "url": result.url,
            "ok": result.ok,
            "status_code": result.status_code,
            "error": result.error,
        }
        span_id = self._append_trace_span(
            record,
            kind="fetch",
            agent=agent,
            subagent=subagent,
            name="fetch_page",
            status="ok" if result.ok else "error",
            started=started,
            input_text=url,
            output_text=result.snippet or result.error or result.title,
            metadata=self._trace_metadata(context, metadata),
        )
        await self.emit(
            record.detail.id,
            "tool.called",
            agent,
            subagent,
            "fetch_page completed.",
            {
                "tool": "fetch_page",
                "input": url,
                "output": result.snippet or result.error or result.title,
                "related_span_ids": [span_id],
                "result_count": 1 if result.ok else 0,
                "source_ids": [result.url] if result.url else [],
            },
        )
        return result

    async def _trace_robots(
        self,
        record: RunRecord,
        agent: str,
        subagent: str | None,
        url: str,
        context: SubagentContext | None = None,
    ):
        started = time.perf_counter()
        if context is not None:
            context.add_tool_call("robots_check", url)
        result = await robots_check(
            url, timeout_seconds=min(4.0, self._settings.llm_timeout_seconds)
        )
        output_text = json.dumps(
            {
                "robots_url": result.robots_url,
                "allowed": result.allowed,
                "checked": result.checked,
                "status_code": result.status_code,
                "error": result.error,
            },
            ensure_ascii=False,
        )
        self._append_trace_span(
            record,
            kind="tool",
            agent=agent,
            subagent=subagent,
            name="robots_check",
            status="ok" if result.allowed else "error",
            started=started,
            input_text=url,
            output_text=output_text,
            metadata=self._trace_metadata(
                context,
                {
                    "url": url,
                    "robots_url": result.robots_url,
                    "allowed": result.allowed,
                    "checked": result.checked,
                    "status_code": result.status_code,
                    "error": result.error,
                },
            ),
        )
        return result

    def _trace_local_tool(
        self,
        record: RunRecord,
        *,
        agent: str,
        subagent: str | None,
        name: str,
        input_text: str,
        output_text: str,
        context: SubagentContext | None = None,
        metadata: dict[str, str | int | float | bool | None] | None = None,
    ) -> None:
        started = time.perf_counter()
        if context is not None:
            context.add_tool_call(name, input_text)
        self._append_trace_span(
            record,
            kind="tool",
            agent=agent,
            subagent=subagent,
            name=name,
            status="ok",
            started=started,
            input_text=input_text,
            output_text=output_text,
            metadata=self._trace_metadata(context, metadata or {}),
        )

    def _trace_metadata(
        self,
        context: SubagentContext | None,
        metadata: dict[str, str | int | float | bool | None],
    ) -> dict[str, str | int | float | bool | None]:
        if context is None:
            return metadata
        return {**metadata, **context.metadata()}

    def _consume_llm_usage(self) -> Any | None:
        consume = getattr(self._llm, "consume_last_usage", None)
        if not callable(consume):
            return None
        return consume()

    def _llm_usage_metadata(self, usage: Any | None) -> dict[str, int | str]:
        provider = self._last_llm_provider()
        model = self._last_llm_model()
        if usage is None:
            metadata: dict[str, int | str] = {"token_usage_source": "estimate"}
            if provider:
                metadata["llm_provider"] = provider
            if model:
                metadata["llm_model"] = model
            return metadata
        metadata = {"token_usage_source": "provider"}
        if provider:
            metadata["llm_provider"] = provider
        if model:
            metadata["llm_model"] = model
        prompt_tokens = getattr(usage, "prompt_tokens", None)
        completion_tokens = getattr(usage, "completion_tokens", None)
        total_tokens = getattr(usage, "total_tokens", None)
        if prompt_tokens is not None:
            metadata["prompt_tokens"] = int(prompt_tokens)
        if completion_tokens is not None:
            metadata["completion_tokens"] = int(completion_tokens)
        if total_tokens is not None:
            metadata["total_tokens"] = int(total_tokens)
        return metadata

    def _redact_trace_texts(
        self,
        input_text: str,
        output_text: str,
    ) -> tuple[str, str, dict[str, str | int | float | bool | None]]:
        policy = compliance_policy_from_settings(self._settings)
        input_redaction = redact_text(input_text, policy=policy)
        output_redaction = redact_text(output_text, policy=policy)
        policy_metadata: dict[str, str | int | float | bool | None] = {
            "compliance_redaction_enabled": policy.redaction_enabled,
            "compliance_redact_api_keys": policy.redact_api_keys,
            "compliance_redact_emails": policy.redact_emails,
            "compliance_redact_phones": policy.redact_phones,
        }
        if input_redaction.total_count == 0 and output_redaction.total_count == 0:
            return input_text, output_text, policy_metadata
        return (
            input_redaction.text,
            output_redaction.text,
            {
                **policy_metadata,
                "pii_redacted": True,
                "input_redaction_count": input_redaction.total_count,
                "output_redaction_count": output_redaction.total_count,
            },
        )

    def _append_trace_span(
        self,
        record: RunRecord,
        *,
        kind: Literal["llm", "search", "fetch", "tool"],
        agent: str,
        subagent: str | None,
        name: str,
        status: Literal["ok", "error"],
        started: float,
        input_text: str,
        output_text: str,
        metadata: dict[str, str | int | float | bool | None] | None = None,
        source_message_id: str | None = None,
        token_usage: Any | None = None,
    ) -> str:
        duration_ms = max(0, int((time.perf_counter() - started) * 1000))
        input_chars = len(input_text)
        output_chars = len(output_text)
        input_tokens = self._usage_prompt_tokens(token_usage) or self._estimate_tokens(input_text)
        output_tokens = self._usage_completion_tokens(token_usage) or self._estimate_tokens(
            output_text
        )
        redacted_input_text, redacted_output_text, redaction_metadata = self._redact_trace_texts(
            input_text,
            output_text,
        )
        span_metadata = {**(metadata or {}), **redaction_metadata}
        span_id = f"span-{len(record.detail.trace_spans) + 1}"
        trace_id = trace_id_for_run(record.detail.id)
        otel_span_id = otel_span_id_for_span(record.detail.id, span_id)
        parent_span_id = self._parent_otel_span_id(record, source_message_id)
        traceparent = traceparent_for_span(trace_id, otel_span_id)
        span_metadata = {
            **span_metadata,
            "trace_id": trace_id,
            "otel_span_id": otel_span_id,
            "traceparent": traceparent,
        }
        if parent_span_id is not None:
            span_metadata["parent_span_id"] = parent_span_id
        span = TraceSpan(
            id=span_id,
            trace_id=trace_id,
            otel_span_id=otel_span_id,
            parent_span_id=parent_span_id,
            traceparent=traceparent,
            kind=kind,
            agent=agent,
            subagent=subagent,
            name=name,
            status=status,
            model=self._last_llm_model() if kind == "llm" else None,
            provider=self._last_llm_provider()
            if kind == "llm"
            else self._settings.web_search_provider
            if kind == "search"
            else None,
            duration_ms=duration_ms,
            input_chars=input_chars,
            output_chars=output_chars,
            input_tokens_estimate=input_tokens,
            output_tokens_estimate=output_tokens,
            cost_estimate_usd=self._estimate_span_cost_usd(kind, input_tokens, output_tokens),
            input_preview=self._preview(redacted_input_text),
            output_preview=self._preview(redacted_output_text),
            full_input=redacted_input_text,
            full_output=redacted_output_text,
            metadata=span_metadata,
        )
        record.detail.trace_spans.append(span)
        if self._trace_store is not None:
            self._trace_store.append_span(record.detail.id, span)
        if self._langfuse.enabled:
            self._langfuse.mirror_span(record.detail.id, span)
        if kind in {"search", "fetch", "tool"}:
            self._append_tool_call_message(
                record,
                agent=agent,
                subagent=subagent,
                tool_name=name,
                arguments={"input": redacted_input_text},
                result={"output": redacted_output_text, "metadata": span_metadata},
                status=status,
                trace_span_id=span_id,
                source_message_id=source_message_id,
            )
        self._rebuild_metrics(record.detail)
        record.detail.updated_at = datetime.utcnow()
        return span_id

    def _parent_otel_span_id(
        self,
        record: RunRecord,
        source_message_id: str | None,
    ) -> str | None:
        if not source_message_id:
            return None
        for message in record.detail.agent_messages:
            if message.id == source_message_id and message.trace_span_ids:
                return otel_span_id_for_span(record.detail.id, message.trace_span_ids[-1])
        return None

    def _usage_prompt_tokens(self, usage: Any | None) -> int | None:
        value = getattr(usage, "prompt_tokens", None)
        return int(value) if isinstance(value, int) and value >= 0 else None

    def _usage_completion_tokens(self, usage: Any | None) -> int | None:
        value = getattr(usage, "completion_tokens", None)
        return int(value) if isinstance(value, int) and value >= 0 else None

    def _rebuild_metrics(self, detail: RunDetail) -> None:
        detail.metrics = self._build_metrics(detail.trace_spans)
        self._refresh_quality_metrics(detail)

    def _build_metrics(self, spans: list[TraceSpan]) -> RunMetrics:
        return RunMetrics(
            total_spans=len(spans),
            total_duration_ms=sum(span.duration_ms for span in spans),
            llm_calls=sum(1 for span in spans if span.kind == "llm"),
            search_calls=sum(1 for span in spans if span.kind == "search"),
            fetch_calls=sum(1 for span in spans if span.kind == "fetch"),
            input_tokens_estimate=sum(span.input_tokens_estimate for span in spans),
            output_tokens_estimate=sum(span.output_tokens_estimate for span in spans),
            cost_estimate_usd=round(sum(span.cost_estimate_usd for span in spans), 6),
            compliance_redaction_count=sum(_span_redaction_count(span) for span in spans),
        )

    def _refresh_quality_metrics(self, detail: RunDetail) -> None:
        metrics = detail.metrics
        expected_pairs = {
            (competitor, dimension)
            for competitor in detail.plan.competitors
            for dimension in detail.plan.dimensions
        }
        covered_pairs = {
            (competitor, source.dimension)
            for source in detail.raw_sources
            for competitor in detail.plan.competitors
            if self._source_matches_competitor(source, competitor)
        }
        all_claims = [
            claim
            for knowledge in detail.competitor_knowledge.values()
            for dimension in detail.plan.dimensions
            for claim in self._structured_claims_for_dimension(knowledge, dimension)
        ]
        metrics.source_coverage_rate = (
            round(len(covered_pairs & expected_pairs) / len(expected_pairs), 3)
            if expected_pairs
            else 0.0
        )
        metrics.verified_source_rate = (
            round(
                sum(1 for source in detail.raw_sources if source.source_type == "webpage_verified")
                / len(detail.raw_sources),
                3,
            )
            if detail.raw_sources
            else 0.0
        )
        metrics.claim_citation_rate = (
            round(sum(1 for claim in all_claims if claim.source_ids) / len(all_claims), 3)
            if all_claims
            else 0.0
        )
        metrics.qa_issue_count = len(detail.qa_findings)
        metrics.revision_count = len(detail.revisions)
        schema_issue_count = sum(1 for issue in detail.qa_findings if issue.detected_by == "schema")
        metrics.schema_pass_rate = 0.0 if schema_issue_count else 1.0
        hitl_override_count = _hitl_override_count(detail)
        human_override_count = len(detail.revisions) + hitl_override_count
        human_override_denominator = max(
            len(detail.qa_findings),
            _hitl_review_decision_count(detail),
            1,
        )
        metrics.human_override_rate = (
            round(min(1.0, human_override_count / human_override_denominator), 3)
            if human_override_count
            else 0.0
        )
        blocker_count = sum(1 for issue in detail.qa_findings if issue.severity == "blocker")
        metrics.acceptance_rate = 0.0 if blocker_count else 1.0
        detail.metrics = metrics

    def _estimate_tokens(self, text: str) -> int:
        return max(0, (len(text) + 3) // 4)

    def _estimate_span_cost_usd(
        self,
        kind: Literal["llm", "search", "fetch", "tool"],
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        if kind != "llm":
            return 0.0
        # A conservative generic estimate so cost panels are traceable even when
        # the provider SDK does not return exact billing usage.
        return round((input_tokens * 0.0000003) + (output_tokens * 0.0000006), 6)

    def _last_llm_provider(self) -> str | None:
        getter = getattr(self._llm, "last_provider", None)
        if callable(getter):
            value = getter()
            if isinstance(value, str) and value:
                return value
        if self._settings.has_primary_llm_credentials:
            return "doubao"
        if self._settings.has_backup_llm_credentials:
            return "backup"
        return None

    def _last_llm_model(self) -> str | None:
        getter = getattr(self._llm, "last_model", None)
        if callable(getter):
            value = getter()
            if isinstance(value, str) and value:
                return value
        return self._settings.ark_model or self._settings.backup_llm_model

    def _preview(self, text: str, limit: int = 420) -> str:
        cleaned = re.sub(r"\s+", " ", text).strip()
        if len(cleaned) <= limit:
            return cleaned
        return f"{cleaned[: limit - 3]}..."

    def _new_source_id(self, dimension: str) -> str:
        return f"{dimension}-{uuid4().hex[:8]}"

    def _demo_source(
        self, detail: RunDetail, dimension: str, competitor: str | None = None
    ) -> RawSource:
        competitor = competitor or detail.plan.competitors[0]
        source_id = f"{dimension}-{len(detail.raw_sources) + 1}"
        content_hash = hashlib.sha256(f"{detail.id}:{source_id}".encode()).hexdigest()[:16]
        return RawSource(
            id=source_id,
            competitor=competitor,
            covered_competitors=[competitor],
            dimension=dimension,
            source_type="webpage_verified",
            title=f"{competitor} {dimension} evidence fixture",
            url=f"https://example.com/{self._issue_id_fragment(competitor)}/{dimension}",
            snippet=(
                f"Demo evidence fixture for {competitor} {dimension} "
                "with a concrete structured claim."
            ),
            content_hash=content_hash,
            confidence=0.82,
        )

    def _demo_reflection(self, dimension: str) -> ReflectionRecord:
        return ReflectionRecord(
            iteration=1,
            coverage_gaps=[
                f"Only the first competitor has {dimension} evidence in this demo slice."
            ],
            confidence_outliers=[],
            cross_competitor_gaps=[
                f"{dimension.title()} comparison needs another source before final scoring."
            ],
            suggested_redos=[
                RedoScope(
                    kind="collector",
                    target_subagent=dimension,
                    rationale=f"{dimension.title()} evidence coverage is incomplete.",
                )
            ],
        )

    def _demo_issue(self, dimension: str) -> QCIssue:
        scope = RedoScope(
            kind="collector",
            target_subagent=dimension,
            rationale=f"{dimension.title()} evidence coverage is incomplete.",
        )
        return QCIssue(
            id=f"demo-{dimension}-coverage",
            severity="warn",
            detected_by="coverage",
            target_agent="collector",
            target_subagent=dimension,
            field_path=f"raw_sources[{dimension}]",
            problem=f"{dimension.title()} collector returned evidence for only one competitor.",
            redo_scope=scope,
            self_found=True,
        )

    def _demo_report(self, detail: RunDetail) -> str:
        competitors = ", ".join(detail.plan.competitors)
        dimensions = ", ".join(detail.plan.dimensions)
        source_refs = self._format_source_refs([source.id for source in detail.raw_sources[:4]])
        if not source_refs:
            source_refs = ""
        memory_section = self._demo_memory_section(detail)
        return (
            f"# {detail.plan.topic}\n\n"
            "## Executive Summary\n"
            f"This demo run covers {competitors} across {dimensions} and proves that "
            "events, sources, reflections, QA findings, and report markdown flow through "
            f"structured DTOs.{source_refs}\n\n"
            "## Source Quality & Coverage\n"
            "Demo evidence is projected into the enterprise EvidenceRecord model with source "
            f"IDs preserved for release-gate and report-view traceability.{source_refs}\n\n"
            f"{memory_section}"
            "## Side-by-Side Decision Matrix\n"
            "| Dimension | Competitors |\n"
            "| --- | --- |\n"
            f"| {dimensions} | {competitors} {source_refs} |\n\n"
            "## Battlecard\n"
            "Use this demo report as a direct battlecard scaffold: verify pricing, feature, "
            f"and persona claims before using it as a publishable recommendation.{source_refs}\n\n"
            "## Next Collection / Verification Plan\n"
            "Replace demo evidence with current official webpages, then rerun claim validation "
            f"and release gate review before publication.{source_refs}\n\n"
            "## Evidence Appendix\n"
            + "\n".join(
                f"- {source.id}: {source.title} / {source.source_type} [source:{source.id}]"
                for source in detail.raw_sources[:8]
            )
            + "\n\n"
            "This demo run proves the contract: events, sources, reflections, QA findings, "
            "and report markdown all flow through structured DTOs."
        )

    def _demo_memory_section(self, detail: RunDetail) -> str:
        if not detail.plan.memory_prompt_context:
            return ""
        candidate_ids = ", ".join(detail.plan.memory_candidate_ids) or "none"
        lines = [
            "## Memory Context",
            (
                "Confirmed MemoryAgent preferences were used as writing and planning "
                "guidance, not as factual evidence."
            ),
            f"- Candidate IDs: {candidate_ids}",
            f"- Recall score: {detail.plan.memory_recall_score}/100",
        ]
        lines.extend(
            f"- Preference: {item}" for item in detail.plan.memory_prompt_context[:6]
        )
        return "\n".join(lines) + "\n\n"

    def _resolve_execution_mode(self, requested: str) -> str:
        if requested == "demo":
            return "demo"
        model_policy = build_model_policy_report(self._settings)
        if requested == "real":
            if not model_policy.real_execution_allowed:
                raise ValueError(model_policy_block_message(model_policy))
            return "real"
        if self._settings.default_execution_mode == "real":
            return "real" if model_policy.real_execution_allowed else "demo"
        return "demo"

    def _normalize_competitor_names(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        names: list[str] = []
        seen: set[str] = set()
        for item in value:
            name = str(item).strip()
            if not name:
                continue
            key = name.casefold()
            if key in seen:
                continue
            seen.add(key)
            names.append(name)
            if len(names) >= 8:
                break
        return names

    def _normalize_requested_dimensions(
        self,
        dimensions: list[str],
        *,
        require_core_schema: bool,
    ) -> list[str]:
        available = self._skill_registry.names()
        seen: set[str] = set()
        normalized = [
            dimension
            for dimension in dimensions
            if dimension in available and not (dimension in seen or seen.add(dimension))
        ]
        if not normalized:
            normalized = [
                dimension for dimension in CORE_SCHEMA_DIMENSIONS if dimension in available
            ]
        if require_core_schema:
            for dimension in CORE_SCHEMA_DIMENSIONS:
                if dimension in available and dimension not in normalized:
                    normalized.append(dimension)
        return normalized

    def _apply_memory_dimension_preferences(
        self,
        dimensions: list[str],
        prompt_context: list[str],
        candidate_tags: list[str],
    ) -> list[str]:
        if not prompt_context and not candidate_tags:
            return dimensions
        available = set(self._skill_registry.names())
        seen = set(dimensions)
        merged = list(dimensions)
        for tag in candidate_tags:
            if tag in available and tag not in seen:
                seen.add(tag)
                merged.append(tag)
        return merged

    def _capture_hitl_memory_feedback(
        self,
        record: RunRecord,
        request: HitlResumeRequest,
    ) -> dict[str, object] | None:
        detail = record.detail
        if self._preference_memory is None or not detail.project_id:
            return None
        note = (request.note or "").strip()
        if note.startswith("Auto-accepted after HITL timeout"):
            return None
        dimensions = [
            dimension.strip()
            for dimension in (request.dimensions or [])
            if dimension.strip()
        ]
        if request.decision == "accept" and not note and not dimensions:
            return None
        feedback_type = (
            "approval"
            if request.decision in {"accept", "force_pass"}
            else "correction"
        )
        target_type = "dimension" if dimensions else "project"
        target_id = ",".join(dimensions) if dimensions else detail.project_id
        message_parts = [f"HITL decision: {request.decision}."]
        if note:
            message_parts.append(note)
        if dimensions:
            message_parts.append(
                "Reviewer adjusted dimensions to " + ", ".join(dimensions) + "."
            )
        feedback = self._preference_memory.add_feedback(
            UserFeedbackRecord(
                id="",
                workspace_id=detail.workspace_id,
                project_id=detail.project_id,
                user_id="hitl-reviewer",
                feedback_type=feedback_type,
                target_type=target_type,
                target_id=target_id,
                run_id=detail.id,
                message=" ".join(message_parts),
                tags=["hitl", request.decision, *dimensions],
                metadata={
                    "source": "hitl_resume",
                    "decision": request.decision,
                    "dimensions": dimensions,
                },
            ),
            policy=compliance_policy_from_settings(self._settings),
        )
        candidates = [
            self._preference_memory.upsert_candidate(candidate)
            for candidate in self._preference_memory.extract_candidates(feedback)
        ]
        payload: dict[str, object] = {
            "feedback_id": feedback.id,
            "feedback_type": feedback.feedback_type,
            "target_type": feedback.target_type,
            "target_id": feedback.target_id,
            "decision": request.decision,
            "has_note": bool(note),
            "dimensions": dimensions,
            "candidate_ids": [candidate.id for candidate in candidates],
            "candidate_count": len(candidates),
        }
        self._append_agent_message(
            record,
            from_agent="hitl",
            to_agent="memory",
            message_type="hitl_memory_feedback_captured",
            payload_schema="HitlMemoryFeedbackPayload",
            payload=payload,
        )
        return payload

    def _plan_requires_core_schema(self, detail: RunDetail) -> bool:
        available_core = [
            dimension
            for dimension in CORE_SCHEMA_DIMENSIONS
            if dimension in self._skill_registry.names()
        ]
        return bool(available_core) and all(
            dimension in detail.plan.dimensions for dimension in available_core
        )

    def _redo_limit_reached(self, detail: RunDetail) -> bool:
        return len(detail.revisions) >= detail.max_iterations

    def _qa_feedback_for_branch(
        self,
        detail: RunDetail,
        agent: str,
        dimension: str,
        competitor: str,
    ) -> list[dict[str, str | bool | None]]:
        feedback: list[dict[str, str | bool | None]] = []
        for issue in detail.qa_findings:
            if issue.target_agent != agent:
                continue
            if issue.target_subagent and issue.target_subagent != dimension:
                continue
            if issue.target_competitor and issue.target_competitor != competitor:
                continue
            feedback.append(
                {
                    "id": issue.id,
                    "severity": issue.severity,
                    "field_path": issue.field_path,
                    "problem": issue.problem,
                    "redo_kind": issue.redo_scope.kind,
                    "target_subagent": issue.target_subagent,
                    "target_competitor": issue.target_competitor,
                    "self_found": issue.self_found,
                }
            )
        return feedback

    def _issue_id_fragment(self, value: str) -> str:
        fragment = re.sub(r"[^A-Za-z0-9_.:-]+", "-", value.strip().lower()).strip("-")
        return fragment or "unknown"

    def _competitor_label_matches(self, source_competitor: str, competitor: str) -> bool:
        source_competitor = source_competitor.strip()
        source_key = source_competitor.casefold()
        competitor_key = competitor.strip().casefold()
        if source_key == competitor_key:
            return True
        if self._competitor_label_means_all(source_key):
            return True
        parts = [
            part.strip().casefold()
            for part in re.split(r",|;|/|\||\s+and\s+|\s*&\s*", source_competitor)
            if part.strip()
        ]
        if competitor_key in parts:
            return True
        return competitor_key in source_key

    def _competitor_label_means_all(self, source_key: str) -> bool:
        return bool(
            source_key.startswith("all ")
            or "all target" in source_key
            or "all competitors" in source_key
            or "all models" in source_key
            or "cross-model all" in source_key
            or "cross model all" in source_key
            or re.search(r"\ball\s+\d+\s+(?:target\s+)?(?:models|competitors|llms)\b", source_key)
        )

    def _source_matches_competitor(self, source: RawSource, competitor: str) -> bool:
        if source.covered_competitors:
            return competitor in source.covered_competitors
        return self._competitor_label_matches(source.competitor, competitor)

    def _analyst_branch_id(self, dimension: str, competitor: str) -> str:
        return f"{dimension}::{competitor}"

    def _coerce_confidence(self, value: object, default: float) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = default
        return min(1.0, max(0.0, number))

    def _string_list(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if str(item).strip()]


def _run_id_for_idempotency_key(idempotency_key: str | None) -> str | None:
    if not idempotency_key:
        return None
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:32]
    return f"run-{digest}"


def _span_redaction_count(span: TraceSpan) -> int:
    return _metadata_int(span.metadata.get("input_redaction_count")) + _metadata_int(
        span.metadata.get("output_redaction_count")
    )


def _hitl_review_decision_count(detail: RunDetail) -> int:
    return len(_hitl_review_messages(detail))


def _hitl_override_count(detail: RunDetail) -> int:
    count = 0
    for message in _hitl_review_messages(detail):
        decision = str(message.payload.get("decision") or "")
        dimensions = message.payload.get("dimensions")
        has_dimensions = isinstance(dimensions, list) and bool(dimensions)
        has_note = message.payload.get("has_note") is True
        if decision in {"modify_plan", "force_pass", "redo"} or has_dimensions or has_note:
            count += 1
    return count


def _hitl_review_messages(detail: RunDetail) -> list[AgentMessage]:
    return [
        message
        for message in detail.agent_messages
        if message.message_type == "hitl_memory_feedback_captured"
    ]


def _metadata_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    return 0
