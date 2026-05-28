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
from packages.agents.writer.logic import WriterAgentMixin
from packages.business_intel import build_business_intel_plan
from packages.config import Settings
from packages.enterprise import EnterpriseStore, build_enterprise_projection
from packages.identity import compute_competitor_set_hash, compute_topic_normalized
from packages.llm import DoubaoClient
from packages.memory import KBCache, RunJournal
from packages.observability import LangfuseAdapter, LangfuseConfig, TraceStore, build_run_event
from packages.orchestrator.audit import build_revision_record, convergence_ratio
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.graph import (
    build_demo_analysis_graph,
    build_real_analysis_graph,
    build_scoped_redo_graph,
)
from packages.schema.api_dto import HitlResumeRequest, RunCreateRequest, RunDetail, RunSummary
from packages.schema.enterprise import EnterpriseRunProjection
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
        execution_mode = self._resolve_execution_mode(request.execution_mode)
        competitors = self._normalize_competitor_names(request.competitors)
        valid_dimensions = self._normalize_requested_dimensions(
            request.dimensions,
            require_core_schema=not competitors,
        )
        business_plan = build_business_intel_plan(
            topic=request.topic,
            competitors=competitors,
            dimensions=valid_dimensions,
            requested_layer=request.competitor_layer,
            requested_scenario_id=request.scenario_id,
        )
        now = datetime.utcnow()
        run_id = str(uuid4())
        plan = AnalysisPlan(
            topic=request.topic,
            competitors=competitors,
            dimensions=valid_dimensions,
            complexity="medium",
            competitor_layer=business_plan.competitor_layer.layer,
            scenario_id=business_plan.scenario_pack.id,
            scenario_recommended_dimensions=business_plan.recommended_dimensions,
            qa_rule_ids=[rule.id for rule in business_plan.qa_rules],
            homepage_hints={
                name: f"https://www.google.com/search?q={name}" for name in competitors
            },
        )
        detail = RunDetail(
            id=run_id,
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
            {"plan": plan.model_dump(mode="json")},
        )
        return detail

    def list_runs(self) -> list[RunSummary]:
        return [
            RunSummary(
                id=record.detail.id,
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
        record = self._runs.get(run_id)
        return record.detail if record else None

    def get_trace(self, run_id: str) -> list[RunEvent] | None:
        record = self._runs.get(run_id)
        return record.events if record else None

    def get_trace_spans(self, run_id: str) -> list[TraceSpan] | None:
        record = self._runs.get(run_id)
        if record is not None:
            return record.detail.trace_spans
        if self._trace_store is not None:
            spans = self._trace_store.list_spans(run_id)
            return spans or None
        return None

    def get_agent_messages(self, run_id: str) -> list[AgentMessage] | None:
        record = self._runs.get(run_id)
        if record is not None:
            return record.detail.agent_messages
        if self._trace_store is not None:
            messages = self._trace_store.list_agent_messages(run_id)
            return messages or None
        return None

    def get_tool_call_messages(self, run_id: str) -> list[ToolCallMessage] | None:
        record = self._runs.get(run_id)
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

    async def run_pipeline(self, run_id: str) -> None:
        record = self._runs.get(run_id)
        if record is None:
            return
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
        projection = self._sync_enterprise_projection(record)
        await self.emit(
            record.detail.id,
            "run_completed",
            "orchestrator",
            None,
            "Real API run completed.",
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
        projection = self._sync_enterprise_projection(record)
        await self.emit(
            detail.id,
            "run_completed",
            "orchestrator",
            None,
            f"Scoped redo completed: {pending.stage if pending else 'redo'}.",
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
        projection = self._sync_enterprise_projection(record)
        await self.emit(
            record.detail.id,
            "run_completed",
            "orchestrator",
            None,
            "Demo graph run completed.",
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
        if self._settings.hitl_enabled or not self._settings.auto_redo_enabled:
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
        if not self._settings.hitl_enabled:
            return HitlResumeRequest(decision="accept")
        detail = record.detail
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
        span_id = f"span-{len(record.detail.trace_spans) + 1}"
        span = TraceSpan(
            id=span_id,
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
            input_preview=self._preview(input_text),
            output_preview=self._preview(output_text),
            full_input=input_text,
            full_output=output_text,
            metadata={
                "message_id": message.id,
                "to_agent": message.to_agent,
                "message_type": message.message_type,
                "payload_schema": message.payload_schema,
                "source_message_count": len(message.source_message_ids),
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

    def _sync_enterprise_projection(self, record: RunRecord) -> EnterpriseRunProjection | None:
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
        return projection

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
            }
        }

    def _hydrate_runs(self) -> None:
        if self._journal is None:
            return
        for detail in self._journal.load_runs():
            self._runs[detail.id] = RunRecord(
                detail=detail,
                events=self._journal.load_events(detail.id),
            )

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
        self._append_trace_span(
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
        self._append_trace_span(
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
        if usage is None:
            return {"token_usage_source": "estimate"}
        metadata: dict[str, int | str] = {"token_usage_source": "provider"}
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
        span_id = f"span-{len(record.detail.trace_spans) + 1}"
        span = TraceSpan(
            id=span_id,
            kind=kind,
            agent=agent,
            subagent=subagent,
            name=name,
            status=status,
            model=self._settings.ark_model if kind == "llm" else None,
            provider="doubao"
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
            input_preview=self._preview(input_text),
            output_preview=self._preview(output_text),
            full_input=input_text,
            full_output=output_text,
            metadata=metadata or {},
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
                arguments={"input": input_text},
                result={"output": output_text, "metadata": metadata or {}},
                status=status,
                trace_span_id=span_id,
                source_message_id=source_message_id,
            )
        self._rebuild_metrics(record.detail)
        record.detail.updated_at = datetime.utcnow()
        return span_id

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
        metrics.human_override_rate = (
            round(len(detail.revisions) / len(detail.qa_findings), 3) if detail.qa_findings else 0.0
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
            confidence=0.72,
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
        return (
            f"# {detail.plan.topic}\n\n"
            f"Competitors: {competitors}\n\n"
            f"Dimensions in scope: {dimensions}\n\n"
            "This demo run proves the contract: events, sources, reflections, QA findings, "
            "and report markdown all flow through structured DTOs."
        )

    def _resolve_execution_mode(self, requested: str) -> str:
        if requested == "demo":
            return "demo"
        if requested == "real":
            if not self._settings.has_llm_credentials:
                raise ValueError(
                    "Real mode requires ARK_API_KEY and ARK_MODEL in backend environment or .env."
                )
            return "real"
        return self._settings.default_execution_mode

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
