import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from app.events import RunEvent
from packages.agents import SubagentContext
from packages.config import Settings
from packages.llm import DoubaoClient
from packages.memory import RunJournal
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.graph import build_real_analysis_graph, build_scoped_redo_graph
from packages.observability import build_run_event
from packages.orchestrator.scoping import assign_redo_scope
from packages.search import PerplexitySearchClient, SearchResult
from packages.schema.api_dto import HitlResumeRequest, RunCreateRequest, RunDetail, RunSummary
from packages.schema.models import (
    AnalysisPlan,
    ComparisonCell,
    ComparisonMatrix,
    CompetitorCandidate,
    CompetitorDiscovery,
    CompetitorKB,
    QCIssue,
    RawSource,
    RedoScope,
    ReflectionRecord,
    RevisionRecord,
    RunMetrics,
    TraceSpan,
)
from packages.skills.registry import SkillRegistry
from packages.tools import fetch_page


@dataclass
class RunRecord:
    detail: RunDetail
    events: list[RunEvent] = field(default_factory=list)
    subscribers: list[asyncio.Queue[RunEvent]] = field(default_factory=list)
    resume_waiters: dict[str, asyncio.Future[HitlResumeRequest]] = field(default_factory=dict)
    redo_after_interrupt: bool = False


class RunService:
    def __init__(
        self,
        skill_registry: SkillRegistry,
        settings: Settings,
        journal: RunJournal | None = None,
        graph_checkpointer: GraphCheckpointer | None = None,
    ) -> None:
        self._skill_registry = skill_registry
        self._settings = settings
        self._llm = DoubaoClient(settings)
        self._search = PerplexitySearchClient(settings)
        self._journal = journal
        self._graph_checkpointer = graph_checkpointer or GraphCheckpointer.from_default_path()
        self._real_graph = None
        self._scoped_redo_graph = None
        self._runs: dict[str, RunRecord] = {}
        self._lock = asyncio.Lock()
        self._hydrate_runs()

    async def create_run(self, request: RunCreateRequest) -> RunDetail:
        valid_dimensions = [dim for dim in request.dimensions if dim in self._skill_registry.names()]
        if not valid_dimensions:
            valid_dimensions = self._skill_registry.names()[:2]
        execution_mode = self._resolve_execution_mode(request.execution_mode)
        competitors = self._normalize_competitor_names(request.competitors)
        now = datetime.utcnow()
        run_id = str(uuid4())
        plan = AnalysisPlan(
            topic=request.topic,
            competitors=competitors,
            dimensions=valid_dimensions,
            complexity="medium",
            homepage_hints={name: f"https://www.google.com/search?q={name}" for name in competitors},
        )
        detail = RunDetail(
            id=run_id,
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

    def can_start_redo(self, run_id: str) -> bool:
        record = self._runs.get(run_id)
        return bool(record and record.detail.qa_findings and not self._redo_limit_reached(record.detail))

    def has_pending_interrupt(self, run_id: str) -> bool:
        record = self._runs.get(run_id)
        return bool(record and record.resume_waiters)

    async def resume(self, run_id: str, request: HitlResumeRequest) -> RunDetail | None:
        record = self._runs.get(run_id)
        if record is None:
            return None
        if record.resume_waiters:
            if request.dimensions:
                record.detail.plan.dimensions = request.dimensions
            record.detail.status = "running"
            record.detail.updated_at = datetime.utcnow()
            self._persist_run(run_id)
            for future in list(record.resume_waiters.values()):
                if not future.done():
                    future.set_result(request)
            record.resume_waiters.clear()
            await self.emit(
                run_id,
                "node_completed",
                "hitl",
                None,
                f"HITL decision received: {request.decision}",
                request.model_dump(exclude_none=True),
            )
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
            record.detail.plan.dimensions = request.dimensions
        record.detail.status = "running"
        record.detail.updated_at = datetime.utcnow()
        self._persist_run(run_id)
        for future in list(record.resume_waiters.values()):
            if not future.done():
                future.set_result(request)
        record.resume_waiters.clear()
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

        issue = sorted(
            detail.qa_findings,
            key=lambda item: {"blocker": 0, "warn": 1, "info": 2}.get(item.severity, 3),
        )[0]
        scope = issue.redo_scope
        before_report = detail.report_md
        before_issue_count = len(detail.qa_findings)
        before_issue_ids = [item.id for item in detail.qa_findings]
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
            {"redo_scope": scope.model_dump(mode="json"), "issue": issue.model_dump(mode="json")},
        )

        try:
            if detail.execution_mode == "demo":
                await self._run_demo_pipeline(run_id)
                await self._record_revision(
                    record,
                    iteration=revision_iteration,
                    stage=scope.kind,
                    before_md=before_report,
                    issue_ids=before_issue_ids,
                    issue_count_before=before_issue_count,
                )
                return

            await self._run_real_scoped_redo(record, scope)

            detail.status = "completed"
            detail.current_node = None
            detail.updated_at = datetime.utcnow()
            await self._record_revision(
                record,
                iteration=revision_iteration,
                stage=scope.kind,
                before_md=before_report,
                issue_ids=before_issue_ids,
                issue_count_before=before_issue_count,
            )
            if auto_continue and await self._maybe_run_auto_redo(record):
                return
            await self.emit(
                run_id,
                "run_completed",
                "orchestrator",
                None,
                f"Scoped redo completed: {scope.kind}.",
                {"redo_scope": scope.model_dump(mode="json")},
            )
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
                await self._run_demo_pipeline(run_id)
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

    async def _run_demo_pipeline(self, run_id: str) -> None:
        record = self._runs.get(run_id)
        if record is None:
            return
        record.detail.status = "running"
        if not record.detail.plan.competitors:
            record.detail.plan.competitors = ["Demo Alpha", "Demo Beta", "Demo Gamma"]
            record.detail.plan.homepage_hints = {
                competitor: f"https://www.google.com/search?q={competitor}"
                for competitor in record.detail.plan.competitors
            }
            record.detail.competitor_discovery = CompetitorDiscovery(
                query=f"{record.detail.topic} competitors",
                selected_competitors=record.detail.plan.competitors,
                rationale="Demo topic-only run uses stable fixture competitors.",
                candidates=[
                    CompetitorCandidate(
                        name=competitor,
                        rank=index + 1,
                        selected=True,
                        rationale="Demo fixture competitor.",
                        confidence=0.75,
                    )
                    for index, competitor in enumerate(record.detail.plan.competitors)
                ],
            )
            await self.emit(
                run_id,
                "node_completed",
                "planner",
                None,
                "Demo competitors selected for topic-only run.",
                {"competitor_discovery": record.detail.competitor_discovery.model_dump(mode="json")},
            )
        dimensions = record.detail.plan.dimensions
        focus_dimension = dimensions[0] if dimensions else "feature"
        steps = [("planner", None, "Validated competitors and selected dimensions.")]
        steps.extend(
            ("collector", dimension, f"Collected {dimension} source candidates.")
            for dimension in dimensions
        )
        steps.extend(
            ("analyst", dimension, f"Normalized {dimension} slice into KB.")
            for dimension in dimensions
        )
        steps.extend(
            [
                ("comparator", None, "Built initial comparison matrix."),
                ("reflector", None, "Found one coverage gap before QA."),
                ("writer", None, "Rendered report draft."),
                ("qa", None, "Assigned scoped redo recommendation."),
            ]
        )
        for agent, subagent, message in steps:
            record.detail.current_node = agent
            await self.emit(run_id, "node_started", agent, subagent, f"{message} Starting.")
            await asyncio.sleep(0.2)
            if agent == "collector":
                record.detail.raw_sources.append(self._demo_source(record.detail, subagent or "feature"))
                await self._real_collect_join_step(record, [subagent or "feature"])
            if agent == "analyst":
                self._merge_kb_slice(
                    record.detail,
                    subagent or "feature",
                    {
                        competitor: [
                            f"Demo {subagent or 'feature'} finding for {competitor}."
                        ]
                        for competitor in record.detail.plan.competitors
                    },
                )
            if agent == "comparator":
                record.detail.comparison_matrix = self._build_comparison_matrix(
                    record.detail,
                    {"matrix_summary": [message], "winner_by_dimension": {}},
                )
            if agent == "reflector":
                record.detail.reflections.append(self._demo_reflection(focus_dimension))
            if agent == "writer":
                record.detail.report_md = self._demo_report(record.detail)
                await self.emit(
                    run_id,
                    "report_updated",
                    "writer",
                    None,
                    "Report markdown updated.",
                    {"report_md": record.detail.report_md},
                )
            if agent == "qa":
                issue = self._demo_issue(focus_dimension)
                record.detail.qa_findings = [issue]
                await self.emit(
                    run_id,
                    "qa_issue",
                    "qa",
                    None,
                    "QA produced a scoped redo suggestion.",
                    {"issue": issue.model_dump(mode="json")},
                )
            await self.emit(run_id, "node_completed", agent, subagent, message)
            record.detail.updated_at = datetime.utcnow()

        record.detail.status = "completed"
        record.detail.current_node = None
        record.detail.updated_at = datetime.utcnow()
        await self.emit(run_id, "run_completed", "orchestrator", None, "Demo run completed.")

    async def _run_real_pipeline(self, run_id: str) -> None:
        record = self._runs.get(run_id)
        if record is None:
            return
        record.detail.status = "running"
        graph = await self._get_real_graph()
        await graph.ainvoke(
            {
                "run_id": run_id,
                "dimensions": list(record.detail.plan.dimensions),
                "current_node": "planner",
                "redo_kind": None,
                "collect_qa_attempts": 0,
                "analyst_qa_attempts": 0,
            },
            config={"configurable": {"thread_id": run_id}},
        )
        if record.detail.status == "failed":
            return
        if record.redo_after_interrupt:
            record.redo_after_interrupt = False
            await self.run_scoped_redo(run_id)
            return
        if await self._maybe_run_auto_redo(record):
            return

        record.detail.status = "completed"
        record.detail.current_node = None
        record.detail.updated_at = datetime.utcnow()
        await self.emit(record.detail.id, "run_completed", "orchestrator", None, "Real API run completed.")

    async def _maybe_run_auto_redo(self, record: RunRecord) -> bool:
        detail = record.detail
        if self._settings.hitl_enabled or not self._settings.auto_redo_enabled:
            return False
        redo_issues = [
            issue
            for issue in detail.qa_findings
            if issue.severity == "blocker" or (detail.auto_redo_warn_enabled and issue.severity == "warn")
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
        detail.status = "interrupted"
        detail.current_node = stage
        detail.updated_at = datetime.utcnow()
        self._persist_run(detail.id)
        future: asyncio.Future[HitlResumeRequest] = asyncio.get_running_loop().create_future()
        record.resume_waiters[stage] = future
        await self.emit(
            detail.id,
            "interrupt",
            "hitl",
            stage,
            message,
            {
                **payload,
                "stage": stage,
                "timeout_seconds": self._settings.hitl_timeout_seconds,
                "run": detail.model_dump(mode="json"),
            },
        )
        try:
            return await asyncio.wait_for(future, timeout=self._settings.hitl_timeout_seconds)
        except asyncio.TimeoutError:
            record.resume_waiters.pop(stage, None)
            detail.status = "running"
            detail.updated_at = datetime.utcnow()
            self._persist_run(detail.id)
            await self.emit(
                detail.id,
                "node_completed",
                "hitl",
                stage,
                f"HITL timeout after {self._settings.hitl_timeout_seconds:.0f}s; accepted default.",
                {"stage": stage, "decision": "accept"},
            )
            return HitlResumeRequest(decision="accept")

    async def _run_real_scoped_redo(self, record: RunRecord, scope: RedoScope) -> None:
        detail = record.detail
        dimensions = list(detail.plan.dimensions)
        if scope.kind in {"analyst", "collector"}:
            dimension = scope.target_subagent or (detail.plan.dimensions[0] if detail.plan.dimensions else None)
            if dimension is None:
                raise ValueError("Cannot redo analyst/collector scope without a target dimension.")
            dimensions = [dimension]
            if scope.kind == "collector":
                detail.raw_sources = [
                    source for source in detail.raw_sources if source.dimension != dimension
                ]
                self._clear_dimension_outputs(detail, dimension)
        elif scope.kind == "full":
            detail.raw_sources = []
            detail.competitor_kbs = {}
            detail.comparison_matrix = None
            detail.reflections = []
            detail.qa_findings = []
            detail.report_md = ""

        graph = await self._get_scoped_redo_graph()
        await graph.ainvoke(
            {
                "run_id": detail.id,
                "dimensions": dimensions,
                "current_node": "redo_router",
                "redo_kind": scope.kind,
                "collect_qa_attempts": 0,
                "analyst_qa_attempts": 0,
            },
            config={"configurable": {"thread_id": f"{detail.id}:redo:{len(detail.revisions) + 1}"}},
        )

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
        before_md: str,
        issue_ids: list[str],
        issue_count_before: int,
    ) -> None:
        detail = record.detail
        revision = RevisionRecord(
            id=f"rev-{iteration}",
            iteration=iteration,
            stage=stage,
            before_md=before_md,
            after_md=detail.report_md,
            issue_ids=issue_ids,
            issue_count_before=issue_count_before,
            issue_count_after=len(detail.qa_findings),
            convergence_ratio=self._convergence_ratio(issue_count_before, len(detail.qa_findings)),
        )
        detail.revisions.append(revision)
        detail.updated_at = datetime.utcnow()
        await self.emit(
            detail.id,
            "revision_recorded",
            "orchestrator",
            None,
            f"Revision {iteration} recorded with convergence ratio {revision.convergence_ratio:.2f}.",
            {"revision": revision.model_dump(mode="json")},
        )

    def _convergence_ratio(self, issue_count_before: int, issue_count_after: int) -> float:
        return round(issue_count_after / max(1, issue_count_before), 3)

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
            payload = await self._llm.complete_json(system=system, user=user, schema_hint=schema_hint)
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
            metadata=self._trace_metadata(context, {"response_format": "json"}),
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
            metadata=self._trace_metadata(context, {"response_format": "text"}),
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
            results = await self._search.search(query, max_results=max_results)
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
    ) -> None:
        duration_ms = max(0, int((time.perf_counter() - started) * 1000))
        input_chars = len(input_text)
        output_chars = len(output_text)
        span = TraceSpan(
            id=f"span-{len(record.detail.trace_spans) + 1}",
            kind=kind,
            agent=agent,
            subagent=subagent,
            name=name,
            status=status,
            model=self._settings.ark_model if kind == "llm" else None,
            provider="doubao" if kind == "llm" else self._settings.web_search_provider if kind == "search" else None,
            duration_ms=duration_ms,
            input_chars=input_chars,
            output_chars=output_chars,
            input_tokens_estimate=self._estimate_tokens(input_text),
            output_tokens_estimate=self._estimate_tokens(output_text),
            input_preview=self._preview(input_text),
            output_preview=self._preview(output_text),
            metadata=metadata or {},
        )
        record.detail.trace_spans.append(span)
        record.detail.metrics = self._build_metrics(record.detail.trace_spans)
        record.detail.updated_at = datetime.utcnow()

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

    def _estimate_tokens(self, text: str) -> int:
        return max(0, (len(text) + 3) // 4)

    def _preview(self, text: str, limit: int = 420) -> str:
        cleaned = re.sub(r"\s+", " ", text).strip()
        if len(cleaned) <= limit:
            return cleaned
        return f"{cleaned[:limit - 3]}..."

    def _new_source_id(self, dimension: str) -> str:
        return f"{dimension}-{uuid4().hex[:8]}"

    def _demo_source(self, detail: RunDetail, dimension: str) -> RawSource:
        competitor = detail.plan.competitors[0]
        source_id = f"{dimension}-{len(detail.raw_sources) + 1}"
        content_hash = hashlib.sha256(f"{detail.id}:{source_id}".encode()).hexdigest()[:16]
        return RawSource(
            id=source_id,
            competitor=competitor,
            dimension=dimension,
            source_type="demo",
            title=f"{competitor} {dimension} evidence fixture",
            url=None,
            snippet=f"Demo evidence fixture for {competitor} {dimension}.",
            content_hash=content_hash,
            confidence=0.72,
        )

    def _demo_reflection(self, dimension: str) -> ReflectionRecord:
        return ReflectionRecord(
            iteration=1,
            coverage_gaps=[f"Only the first competitor has {dimension} evidence in this demo slice."],
            confidence_outliers=[],
            cross_competitor_gaps=[f"{dimension.title()} comparison needs another source before final scoring."],
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
                raise ValueError("Real mode requires ARK_API_KEY and ARK_MODEL in backend environment or .env.")
            return "real"
        return self._settings.default_execution_mode

    async def _real_planner_step(self, record: RunRecord) -> None:
        detail = record.detail
        detail.current_node = "planner"
        await self.emit(detail.id, "node_started", "planner", None, "Calling LLM planner.")
        discovery_payload: dict[str, object] = {}
        if not detail.plan.competitors:
            discovery = await self._discover_competitors(record)
            discovered = discovery.selected_competitors
            if not discovered:
                raise ValueError("Unable to discover competitors for this topic. Add competitors manually and retry.")
            detail.plan.competitors = discovered
            detail.competitor_discovery = discovery
            detail.plan.homepage_hints = {
                name: f"https://www.google.com/search?q={name}" for name in discovered
            }
            discovery_payload = {"competitor_discovery": discovery.model_dump(mode="json")}
            await self.emit(
                detail.id,
                "node_completed",
                "planner",
                None,
                f"Discovered {len(discovered)} competitors for topic-only run.",
                discovery_payload,
            )
        payload = await self._trace_llm_json(
            record,
            agent="planner",
            subagent=None,
            name="planner_scope",
            system="You are a competitive intelligence planner. Validate the user scope and keep outputs concise.",
            user=(
                f"Topic: {detail.topic}\n"
                f"Competitors: {', '.join(detail.plan.competitors)}\n"
                f"Requested dimensions: {', '.join(detail.plan.dimensions)}\n\n"
                "Return homepage hints if you know official domains. Do not invent certainty."
            ),
            schema_hint='{"complexity":"low|medium|high","homepage_hints":{"competitor":"https://..."},'
            '"planning_notes":["short note"]}',
        )
        complexity = payload.get("complexity")
        if complexity in {"low", "medium", "high"}:
            detail.plan.complexity = complexity
        hints = payload.get("homepage_hints")
        if isinstance(hints, dict):
            detail.plan.homepage_hints.update({str(key): str(value) for key, value in hints.items()})
        detail.updated_at = datetime.utcnow()
        await self.emit(
            detail.id,
            "node_completed",
            "planner",
            None,
            "LLM planner completed.",
            {"planner": payload, "competitor_discovery": discovery_payload},
        )
        await self._maybe_interrupt(
            record,
            stage="planner",
            message="Planner is ready for review.",
            payload={"plan": detail.plan.model_dump(mode="json"), "planner": payload},
        )

    async def _discover_competitors(self, record: RunRecord) -> CompetitorDiscovery:
        detail = record.detail
        query = f"{detail.topic} competitors alternatives market leaders official"
        search_results: list[SearchResult] = []
        if self._search.is_enabled:
            search_results = await self._trace_search(
                record,
                agent="planner",
                subagent="discovery",
                query=query,
                max_results=6,
            )
        search_context = [
            result.__dict__
            for result in search_results
        ]
        payload = await self._trace_llm_json(
            record,
            agent="planner",
            subagent="discovery",
            name="competitor_discovery",
            system=(
                "You are a competitive intelligence scoping agent. "
                "Identify direct competitors worth comparing for the given topic."
            ),
            user=(
                f"Topic: {detail.topic}\n"
                f"Search results JSON: {json.dumps(search_context, ensure_ascii=False)}\n\n"
                "Return 3 to 5 direct competitors. Prefer product or company names, not article titles. "
                "If search results are provided, use them as evidence. Keep names short."
            ),
            schema_hint=(
                '{"candidates":[{"name":"name","rationale":"why direct","confidence":0.0}],'
                '"selected_competitors":["name"],"rationale":"short reason"}'
            ),
        )
        selected = self._normalize_competitor_names(
            payload.get("selected_competitors") or payload.get("competitors")
        )[:5]
        candidate_names = self._candidate_names(payload, selected)
        selected_set = {name.casefold() for name in selected}
        candidates = [
            CompetitorCandidate(
                name=name,
                rank=index + 1,
                selected=name.casefold() in selected_set,
                rationale=self._candidate_rationale(payload, name),
                evidence_titles=[result.title for result in self._candidate_evidence(name, search_results)],
                evidence_urls=[result.url for result in self._candidate_evidence(name, search_results)],
                confidence=self._candidate_confidence(payload, name),
            )
            for index, name in enumerate(candidate_names)
        ]
        return CompetitorDiscovery(
            query=query,
            candidates=candidates,
            selected_competitors=selected,
            rationale=str(payload.get("rationale") or ""),
        )

    def _candidate_names(self, payload: dict, selected: list[str]) -> list[str]:
        names: list[str] = []
        raw_candidates = payload.get("candidates")
        if isinstance(raw_candidates, list):
            for item in raw_candidates:
                if isinstance(item, dict):
                    names.append(str(item.get("name") or ""))
                else:
                    names.append(str(item))
        names.extend(selected)
        return self._normalize_competitor_names(names)

    def _candidate_rationale(self, payload: dict, name: str) -> str:
        raw_candidates = payload.get("candidates")
        if not isinstance(raw_candidates, list):
            return ""
        for item in raw_candidates:
            if not isinstance(item, dict):
                continue
            if str(item.get("name") or "").strip().casefold() == name.casefold():
                return str(item.get("rationale") or "")
        return ""

    def _candidate_confidence(self, payload: dict, name: str) -> float:
        raw_candidates = payload.get("candidates")
        if not isinstance(raw_candidates, list):
            return 0.65
        for item in raw_candidates:
            if not isinstance(item, dict):
                continue
            if str(item.get("name") or "").strip().casefold() == name.casefold():
                return self._coerce_confidence(item.get("confidence"), default=0.65)
        return 0.65

    def _candidate_evidence(self, name: str, results: list[SearchResult]) -> list[SearchResult]:
        key = name.casefold()
        matched = [
            result
            for result in results
            if key in f"{result.title} {result.snippet} {result.url}".casefold()
        ]
        return (matched or results)[:2]

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

    async def _run_collector_react(
        self,
        record: RunRecord,
        dimension: str,
        context: SubagentContext,
    ) -> int:
        detail = record.detail
        skill = self._skill_registry.get(dimension)
        observations: list[dict[str, object]] = []
        fetched_by_url: dict[str, Any] = {}
        added = 0
        for turn in range(1, self._settings.collector_react_max_turns + 1):
            payload = await self._trace_llm_json(
                record,
                agent="collector",
                subagent=dimension,
                name=f"{dimension}_react_turn_{turn}",
                system=(
                    "You are a bounded collector ReAct runner. Decide exactly one next action. "
                    "Allowed actions are web_search, fetch_page, finish. "
                    "Use web_search to find evidence, fetch_page to inspect promising URLs, "
                    "and finish only when you can output structured sources."
                ),
                user=(
                    f"Topic: {detail.topic}\n"
                    f"Dimension: {dimension}\n"
                    f"Dimension description: {skill.description if skill else dimension}\n"
                    f"Competitors: {', '.join(detail.plan.competitors)}\n"
                    f"Observations JSON: {json.dumps(observations, ensure_ascii=False)}\n\n"
                    "Return one action. For finish, include sources with competitor, title, url, summary, confidence."
                ),
                schema_hint=(
                    '{"action":"web_search|fetch_page|finish","query":"query or null",'
                    '"url":"https://... or null","rationale":"short reason",'
                    '"sources":[{"competitor":"name","title":"title","url":"https://... or null",'
                    '"summary":"summary","confidence":0.0}]}'
                ),
                context=context,
            )
            action = str(payload.get("action") or "").strip().lower()
            if action == "web_search":
                query = str(payload.get("query") or self._web_search_query(detail, detail.plan.competitors[0], dimension))
                results = await self._trace_search(
                    record,
                    agent="collector",
                    subagent=dimension,
                    query=query,
                    max_results=3,
                    context=context,
                )
                observations.append(
                    {
                        "turn": turn,
                        "action": action,
                        "query": query,
                        "results": [result.__dict__ for result in results[:3]],
                    }
                )
                continue
            if action == "fetch_page":
                url = str(payload.get("url") or "")
                if not url.startswith(("http://", "https://")):
                    observations.append({"turn": turn, "action": action, "error": "invalid_url", "url": url})
                    continue
                fetched = await self._trace_fetch(record, "collector", dimension, url, context)
                fetched_by_url[fetched.url] = fetched
                observations.append(
                    {
                        "turn": turn,
                        "action": action,
                        "url": fetched.url,
                        "ok": fetched.ok,
                        "title": fetched.title,
                        "snippet": fetched.snippet,
                        "content_hash": fetched.content_hash,
                    }
                )
                continue
            if action == "finish":
                sources = await self._sources_from_react_finish(
                    record,
                    detail,
                    dimension,
                    payload,
                    context,
                    fetched_by_url,
                )
                detail.raw_sources.extend(sources)
                added += len(sources)
                break
            observations.append({"turn": turn, "action": action or "unknown", "error": "unsupported_action"})
        return added

    async def _sources_from_react_finish(
        self,
        record: RunRecord,
        detail: RunDetail,
        dimension: str,
        payload: dict[str, Any],
        context: SubagentContext,
        fetched_by_url: dict[str, Any],
    ) -> list[RawSource]:
        raw_sources = payload.get("sources")
        if not isinstance(raw_sources, list):
            return []
        sources: list[RawSource] = []
        for item in raw_sources:
            if not isinstance(item, dict):
                continue
            competitor = str(item.get("competitor") or detail.plan.competitors[0])
            title = str(item.get("title") or f"{competitor} {dimension} evidence")
            summary = str(item.get("summary") or title)
            url_value = item.get("url")
            if not isinstance(url_value, str) or not url_value.startswith(("http://", "https://")):
                url_value = None
            content_basis = f"{competitor}:{dimension}:{title}:{url_value or ''}:{summary}"
            fetched = None
            if url_value:
                fetched = fetched_by_url.get(url_value)
                if fetched is None:
                    fetched = await self._trace_fetch(record, "collector", dimension, url_value, context)
                    fetched_by_url[fetched.url] = fetched
            verified = fetched is not None and fetched.ok
            sources.append(
                RawSource(
                    id=self._new_source_id(dimension),
                    competitor=competitor,
                    dimension=dimension,
                    source_type=(
                        "webpage_verified"
                        if verified
                        else "web_search_result"
                        if url_value
                        else "llm_public_knowledge"
                    ),
                    title=fetched.title if verified and fetched.title else title,
                    url=fetched.url if fetched is not None else url_value,
                    snippet=fetched.snippet if verified else summary,
                    content_hash=(
                        fetched.content_hash
                        if fetched is not None
                        else hashlib.sha256(content_basis.encode()).hexdigest()[:16]
                    ),
                    confidence=(
                        min(1.0, self._coerce_confidence(item.get("confidence"), default=0.7) + 0.03)
                        if verified
                        else self._coerce_confidence(item.get("confidence"), default=0.7)
                    ),
                )
            )
        return sources

    async def _collect_with_web_search(
        self,
        record: RunRecord,
        dimension: str,
        context: SubagentContext,
    ) -> int:
        detail = record.detail
        skill = self._skill_registry.get(dimension)
        added = 0
        for competitor in detail.plan.competitors:
            query = self._web_search_query(detail, competitor, dimension)
            competitor_added = 0
            results = await self._trace_search(
                record,
                agent="collector",
                subagent=dimension,
                query=query,
                max_results=3,
                context=context,
            )
            for result in results:
                source = await self._source_from_search_result(
                    detail,
                    competitor,
                    dimension,
                    result,
                    record,
                    context,
                )
                if source is None:
                    continue
                detail.raw_sources.append(source)
                added += 1
                competitor_added += 1
                break
            if competitor_added == 0 and skill is not None:
                fallback_query = f"{competitor} {skill.description}"
                results = await self._trace_search(
                    record,
                    agent="collector",
                    subagent=dimension,
                    query=fallback_query,
                    max_results=3,
                    context=context,
                )
                for result in results:
                    source = await self._source_from_search_result(
                        detail,
                        competitor,
                        dimension,
                        result,
                        record,
                        context,
                    )
                    if source is None:
                        continue
                    detail.raw_sources.append(source)
                    added += 1
                    competitor_added += 1
                    break
        return added

    def _web_search_query(self, detail: RunDetail, competitor: str, dimension: str) -> str:
        skill = self._skill_registry.get(dimension)
        if skill and skill.query_templates:
            template = skill.query_templates[0]
            query = template.format(competitor=competitor)
        else:
            query = f"{competitor} {dimension}"
        return f"{query} {detail.topic} official source"

    async def _source_from_search_result(
        self,
        detail: RunDetail,
        competitor: str,
        dimension: str,
        result: SearchResult,
        record: RunRecord | None = None,
        context: SubagentContext | None = None,
    ) -> RawSource | None:
        if any(source.url and str(source.url) == result.url for source in detail.raw_sources):
            return None
        source_id = self._new_source_id(dimension)
        fetched = (
            await self._trace_fetch(record, "collector", dimension, result.url, context)
            if record is not None
            else await fetch_page(result.url)
        )
        verified = fetched is not None and fetched.ok
        snippet = fetched.snippet if verified else result.snippet
        content_basis = snippet or result.title or result.url
        return RawSource(
            id=source_id,
            competitor=competitor,
            dimension=dimension,
            source_type="webpage_verified" if verified else "web_search_result",
            title=(fetched.title if verified and fetched.title else result.title),
            url=(fetched.url if verified else result.url),
            snippet=snippet,
            content_hash=(
                fetched.content_hash
                if fetched is not None
                else hashlib.sha256(content_basis.encode()).hexdigest()[:16]
            ),
            confidence=0.84 if verified else 0.68,
        )

    async def _real_collector_step(self, record: RunRecord, dimension: str) -> None:
        detail = record.detail
        skill = self._skill_registry.get(dimension)
        context = SubagentContext(run_id=detail.id, agent="collector", subagent=dimension)
        detail.current_node = "collector"
        await self.emit(
            detail.id,
            "node_started",
            "collector",
            dimension,
            f"Calling {dimension} collector.",
            {"context": context.metadata()},
        )
        web_payload: dict[str, object] = {"provider": self._settings.web_search_provider, "results": []}
        if self._settings.collector_react_enabled and self._search.is_enabled:
            try:
                added = await self._run_collector_react(record, dimension, context)
                web_payload["react_added"] = added
                if added > 0:
                    detail.updated_at = datetime.utcnow()
                    await self.emit(
                        detail.id,
                        "node_completed",
                        "collector",
                        dimension,
                        f"ReAct collector returned {added} {dimension} evidence source(s).",
                        {"react": web_payload, "context": context.metadata()},
                    )
                    return
            except Exception as exc:  # noqa: BLE001 - bounded ReAct falls back to deterministic collection.
                web_payload["react_error"] = str(exc)

        if self._search.is_enabled:
            try:
                added = await self._collect_with_web_search(record, dimension, context)
                web_payload["added"] = added
                if added > 0:
                    detail.updated_at = datetime.utcnow()
                    await self.emit(
                        detail.id,
                        "node_completed",
                            "collector",
                            dimension,
                            f"Perplexity web_search returned {added} {dimension} evidence source(s).",
                            {"web_search": web_payload, "context": context.metadata()},
                        )
                    return
            except Exception as exc:  # noqa: BLE001 - web search is best effort; LLM fallback continues.
                web_payload["error"] = str(exc)

        payload = await self._trace_llm_json(
            record,
            agent="collector",
            subagent=dimension,
            name=f"{dimension}_collector",
            system=(
                "You are a collector subagent. Produce compact evidence candidates for competitive analysis. "
                "Use public knowledge only and mark confidence lower when evidence is uncertain."
            ),
            user=(
                f"Topic: {detail.topic}\n"
                f"Dimension: {dimension}\n"
                f"Dimension description: {skill.description if skill else dimension}\n"
                f"Competitors: {', '.join(detail.plan.competitors)}\n\n"
                "For each competitor return one concise evidence candidate. Prefer official URLs when known."
            ),
            schema_hint='{"sources":[{"competitor":"name","title":"evidence title","url":"https://... or null",'
            '"summary":"short factual summary","confidence":0.0}]}',
            context=context,
        )
        sources = payload.get("sources", [])
        if not isinstance(sources, list):
            sources = []
        added = 0
        for item in sources:
            if not isinstance(item, dict):
                continue
            competitor = str(item.get("competitor") or detail.plan.competitors[0])
            title = str(item.get("title") or f"{competitor} {dimension} evidence")
            summary = str(item.get("summary") or title)
            source_id = self._new_source_id(dimension)
            url_value = item.get("url")
            if not isinstance(url_value, str) or not url_value.startswith(("http://", "https://")):
                url_value = None
            confidence = self._coerce_confidence(item.get("confidence"), default=0.62)
            fetched = await self._trace_fetch(record, "collector", dimension, url_value, context) if url_value else None
            verified = fetched is not None and fetched.ok
            snippet = fetched.snippet if verified else summary
            source_title = fetched.title if verified and fetched.title else title
            source_url = fetched.url if fetched is not None and fetched.ok else url_value
            content_hash = fetched.content_hash if fetched is not None else hashlib.sha256(summary.encode()).hexdigest()[:16]
            detail.raw_sources.append(
                RawSource(
                    id=source_id,
                    competitor=competitor,
                    dimension=dimension,
                    source_type="webpage_verified" if verified else "llm_public_knowledge",
                    title=source_title,
                    url=source_url,
                    snippet=snippet,
                    content_hash=content_hash,
                    confidence=min(1.0, confidence + 0.03) if verified else confidence,
                )
            )
            added += 1
        detail.updated_at = datetime.utcnow()
        await self.emit(
            detail.id,
            "node_completed",
            "collector",
            dimension,
            f"Collector returned {added} {dimension} evidence candidates.",
            {"collector": payload, "web_search": web_payload, "context": context.metadata()},
        )

    async def _real_collect_join_step(self, record: RunRecord, dimensions: list[str]) -> None:
        detail = record.detail
        before_count = len(detail.raw_sources)
        detail.current_node = "collector"
        await self.emit(
            detail.id,
            "node_started",
            "collector",
            "collect_join",
            "Normalizing collected evidence sources.",
        )
        detail.raw_sources = self._normalize_collected_sources(detail, dimensions)
        normalized_count = len(detail.raw_sources)
        detail.updated_at = datetime.utcnow()
        await self.emit(
            detail.id,
            "node_completed",
            "collector",
            "collect_join",
            f"Collect join normalized {normalized_count} source(s).",
            {
                "collect_join": {
                    "before_count": before_count,
                    "after_count": normalized_count,
                    "dimensions": dimensions,
                }
            },
        )

    def _normalize_collected_sources(self, detail: RunDetail, dimensions: list[str]) -> list[RawSource]:
        scoped_dimensions = set(dimensions)
        normalized: list[RawSource] = []
        seen: set[tuple[str, str, str, str, str]] = set()
        for source in detail.raw_sources:
            if scoped_dimensions and source.dimension not in scoped_dimensions:
                normalized.append(source)
                continue
            covered_competitors = self._normalize_covered_competitors(detail, source.competitor)
            url_key = str(source.url) if source.url else ""
            key = (
                source.dimension,
                url_key,
                source.content_hash,
                source.title.strip().casefold(),
                "|".join(covered_competitors),
            )
            if key in seen:
                continue
            seen.add(key)
            normalized.append(source.model_copy(update={"covered_competitors": covered_competitors}))
        return normalized

    def _normalize_covered_competitors(self, detail: RunDetail, source_competitor: str) -> list[str]:
        source_key = source_competitor.strip().casefold()
        if self._competitor_label_means_all(source_key):
            return list(detail.plan.competitors)
        matched = [
            competitor
            for competitor in detail.plan.competitors
            if self._competitor_label_matches(source_competitor, competitor)
        ]
        if matched:
            return matched
        cleaned = source_competitor.strip()
        return [cleaned] if cleaned else []

    async def _run_analyst_react(
        self,
        record: RunRecord,
        dimension: str,
        context: SubagentContext,
        dimension_sources: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        detail = record.detail
        observations: list[dict[str, object]] = []
        inspected = False
        validated_source_ids: set[str] = set()
        for turn in range(1, self._settings.analyst_react_max_turns + 1):
            payload = await self._trace_llm_json(
                record,
                agent="analyst",
                subagent=dimension,
                name=f"{dimension}_analyst_react_turn_{turn}",
                system=(
                    "You are a bounded analyst ReAct runner. Decide exactly one next action. "
                    "Allowed actions are inspect_sources, validate_citations, finish. "
                    "Use only the provided RawSource JSON. Do not invent facts. "
                    "Finish only when findings are grouped by competitor and cite source IDs when possible."
                ),
                user=(
                    f"Topic: {detail.topic}\n"
                    f"Dimension: {dimension}\n"
                    f"Competitors: {', '.join(detail.plan.competitors)}\n"
                    f"Sources JSON: {json.dumps(dimension_sources, ensure_ascii=False)}\n"
                    f"Observations JSON: {json.dumps(observations, ensure_ascii=False)}\n\n"
                    "Return one action. For finish, include competitor_findings, source_ids_used, and caveats."
                ),
                schema_hint=(
                    '{"action":"inspect_sources|validate_citations|finish",'
                    '"source_ids":["source-id"],"rationale":"short reason",'
                    '"competitor_findings":{"competitor":["finding with source id"]},'
                    '"source_ids_used":["source-id"],"caveats":["caveat"]}'
                ),
                context=context,
            )
            action = str(payload.get("action") or "").strip().lower()
            if action == "inspect_sources":
                observation = self._inspect_sources_tool(record, dimension, context, dimension_sources)
                inspected = True
                observations.append({"turn": turn, "action": action, "observation": observation})
                continue
            if action == "validate_citations":
                requested_source_ids = self._string_list(
                    payload.get("source_ids") or payload.get("source_ids_used")
                )
                observation = self._validate_source_ids_tool(
                    record,
                    dimension,
                    context,
                    dimension_sources,
                    requested_source_ids,
                )
                validated_source_ids.update(str(source_id) for source_id in observation["valid_source_ids"])
                observations.append({"turn": turn, "action": action, "observation": observation})
                continue
            if action == "finish":
                normalized = self._normalize_competitor_findings(detail, payload)
                if not any(findings for findings in normalized.values()):
                    observations.append({"turn": turn, "action": action, "error": "empty_findings"})
                    continue
                if not inspected:
                    observation = self._inspect_sources_tool(record, dimension, context, dimension_sources)
                    inspected = True
                    observations.append(
                        {
                            "turn": turn,
                            "action": "inspect_sources",
                            "observation": observation,
                            "reason": "required_before_finish",
                        }
                    )
                used_source_ids = self._source_ids_from_analyst_payload(payload, dimension_sources)
                unvalidated_source_ids = [source_id for source_id in used_source_ids if source_id not in validated_source_ids]
                if used_source_ids and unvalidated_source_ids:
                    observation = self._validate_source_ids_tool(
                        record,
                        dimension,
                        context,
                        dimension_sources,
                        unvalidated_source_ids,
                    )
                    validated_source_ids.update(str(source_id) for source_id in observation["valid_source_ids"])
                    observations.append(
                        {
                            "turn": turn,
                            "action": "validate_citations",
                            "observation": observation,
                            "reason": "required_before_finish",
                        }
                    )
                    if observation["unknown_source_ids"] and turn < self._settings.analyst_react_max_turns:
                        continue
                return self._ensure_analyst_citations(detail, dimension, payload, normalized)
            observations.append({"turn": turn, "action": action or "unknown", "error": "unsupported_action"})
        return None

    def _source_ids_from_analyst_payload(
        self,
        payload: dict[str, Any],
        dimension_sources: list[dict[str, Any]],
    ) -> list[str]:
        known_source_ids = [
            str(source.get("id") or "")
            for source in dimension_sources
            if str(source.get("id") or "").strip()
        ]
        explicit_ids = self._string_list(payload.get("source_ids_used") or payload.get("source_ids"))
        payload_text = json.dumps(payload, ensure_ascii=False)
        found_ids: list[str] = []
        seen: set[str] = set()
        for source_id in [*explicit_ids, *known_source_ids]:
            if not source_id or source_id in seen:
                continue
            if source_id in explicit_ids or source_id in payload_text:
                found_ids.append(source_id)
                seen.add(source_id)
        return found_ids

    def _ensure_analyst_citations(
        self,
        detail: RunDetail,
        dimension: str,
        payload: dict[str, Any],
        normalized: dict[str, list[str]],
    ) -> dict[str, Any]:
        source_ids_by_competitor: dict[str, list[str]] = {
            competitor: [
                source.id
                for source in detail.raw_sources
                if source.dimension == dimension and self._source_matches_competitor(source, competitor)
            ]
            for competitor in detail.plan.competitors
        }
        competitor_findings: dict[str, list[str]] = {}
        changed = False
        for competitor in detail.plan.competitors:
            competitor_source_ids = source_ids_by_competitor.get(competitor, [])
            findings: list[str] = []
            for finding in normalized.get(competitor, []):
                has_known_citation = any(source_id in finding for source_id in competitor_source_ids)
                if not has_known_citation and competitor_source_ids:
                    finding = f"{finding} [source:{competitor_source_ids[0]}]"
                    changed = True
                findings.append(finding)
            competitor_findings[competitor] = findings
        if not changed:
            return payload
        enriched = dict(payload)
        enriched["competitor_findings"] = competitor_findings
        enriched["source_ids_used"] = sorted(
            {
                source_id
                for source_ids in source_ids_by_competitor.values()
                for source_id in source_ids
                if any(
                    source_id in finding
                    for findings in competitor_findings.values()
                    for finding in findings
                )
            }
        )
        return enriched

    def _inspect_sources_tool(
        self,
        record: RunRecord,
        dimension: str,
        context: SubagentContext,
        dimension_sources: list[dict[str, Any]],
    ) -> dict[str, object]:
        detail = record.detail
        by_competitor = {
            competitor: sum(
                1
                for source in dimension_sources
                if self._source_dict_matches_competitor(source, competitor)
            )
            for competitor in detail.plan.competitors
        }
        cards = [
            {
                "id": str(source.get("id") or ""),
                "competitor": str(source.get("competitor") or ""),
                "title": str(source.get("title") or ""),
                "url": str(source.get("url") or ""),
                "snippet": self._preview(str(source.get("snippet") or ""), 180),
                "confidence": source.get("confidence"),
            }
            for source in dimension_sources[:12]
        ]
        output: dict[str, object] = {
            "dimension": dimension,
            "source_count": len(dimension_sources),
            "by_competitor": by_competitor,
            "missing_competitors": [
                competitor for competitor, count in by_competitor.items() if count == 0
            ],
            "source_cards": cards,
        }
        self._trace_local_tool(
            record,
            agent="analyst",
            subagent=dimension,
            name="inspect_sources",
            input_text=json.dumps({"dimension": dimension}, ensure_ascii=False),
            output_text=json.dumps(output, ensure_ascii=False),
            context=context,
            metadata={
                "source_count": len(dimension_sources),
                "missing_competitor_count": sum(1 for count in by_competitor.values() if count == 0),
            },
        )
        return output

    def _source_dict_matches_competitor(self, source: dict[str, Any], competitor: str) -> bool:
        covered = source.get("covered_competitors")
        if isinstance(covered, list):
            return competitor in [str(value) for value in covered]
        return self._competitor_label_matches(str(source.get("competitor") or ""), competitor)

    def _validate_source_ids_tool(
        self,
        record: RunRecord,
        dimension: str,
        context: SubagentContext,
        dimension_sources: list[dict[str, Any]],
        requested_source_ids: list[str],
    ) -> dict[str, object]:
        known_source_ids = {
            str(source.get("id") or "")
            for source in dimension_sources
            if str(source.get("id") or "").strip()
        }
        valid_source_ids = [source_id for source_id in requested_source_ids if source_id in known_source_ids]
        unknown_source_ids = [source_id for source_id in requested_source_ids if source_id not in known_source_ids]
        output: dict[str, object] = {
            "dimension": dimension,
            "requested_source_ids": requested_source_ids,
            "valid_source_ids": valid_source_ids,
            "unknown_source_ids": unknown_source_ids,
            "known_source_count": len(known_source_ids),
        }
        self._trace_local_tool(
            record,
            agent="analyst",
            subagent=dimension,
            name="validate_citations",
            input_text=json.dumps({"source_ids": requested_source_ids}, ensure_ascii=False),
            output_text=json.dumps(output, ensure_ascii=False),
            context=context,
            metadata={
                "requested_count": len(requested_source_ids),
                "valid_count": len(valid_source_ids),
                "unknown_count": len(unknown_source_ids),
            },
        )
        return output

    async def _real_analyst_step(self, record: RunRecord, dimension: str) -> None:
        detail = record.detail
        context = SubagentContext(run_id=detail.id, agent="analyst", subagent=dimension)
        detail.current_node = "analyst"
        await self.emit(
            detail.id,
            "node_started",
            "analyst",
            dimension,
            f"Calling {dimension} analyst.",
            {"context": context.metadata()},
        )
        dimension_sources = [
            source.model_dump(mode="json")
            for source in detail.raw_sources
            if source.dimension == dimension
        ]
        react_payload: dict[str, object] = {}
        if self._settings.analyst_react_enabled:
            try:
                payload = await self._run_analyst_react(record, dimension, context, dimension_sources)
                if payload is not None:
                    self._merge_kb_slice(detail, dimension, self._normalize_competitor_findings(detail, payload))
                    detail.updated_at = datetime.utcnow()
                    await self.emit(
                        detail.id,
                        "node_completed",
                        "analyst",
                        dimension,
                        f"ReAct analyst completed {dimension} slice.",
                        {"analysis": payload, "context": context.metadata()},
                    )
                    return
            except Exception as exc:  # noqa: BLE001 - bounded ReAct falls back to one-shot analysis.
                react_payload["react_error"] = str(exc)

        payload = await self._trace_llm_json(
            record,
            agent="analyst",
            subagent=dimension,
            name=f"{dimension}_analyst",
            system="You are an analyst subagent. Convert source candidates into comparison-ready findings.",
            user=(
                f"Topic: {detail.topic}\n"
                f"Dimension: {dimension}\n"
                f"Sources JSON: {json.dumps(dimension_sources, ensure_ascii=False)}\n\n"
                "Return concise findings grouped by competitor. Use only the provided sources."
            ),
            schema_hint='{"competitor_findings":{"competitor":["finding"]},"caveats":["caveat"]}',
            context=context,
        )
        self._merge_kb_slice(detail, dimension, self._normalize_competitor_findings(detail, payload))
        detail.updated_at = datetime.utcnow()
        await self.emit(
            detail.id,
            "node_completed",
            "analyst",
            dimension,
            f"Analyst completed {dimension} slice.",
            {"analysis": payload, "react": react_payload, "context": context.metadata()},
        )

    async def _real_comparator_step(self, record: RunRecord) -> None:
        detail = record.detail
        detail.current_node = "comparator"
        await self.emit(detail.id, "node_started", "comparator", None, "Calling comparator.")
        payload = await self._trace_llm_json(
            record,
            agent="comparator",
            subagent=None,
            name="comparison_matrix",
            system="You are a comparator. Build a compact cross-competitor matrix summary.",
            user=(
                f"Topic: {detail.topic}\n"
                f"Competitors: {', '.join(detail.plan.competitors)}\n"
                f"Dimensions: {', '.join(detail.plan.dimensions)}\n"
                f"Competitor KB JSON: {json.dumps({k: v.model_dump(mode='json') for k, v in detail.competitor_kbs.items()}, ensure_ascii=False)}\n"
                f"Source digest JSON: {json.dumps(self._source_digest(detail.raw_sources), ensure_ascii=False)}"
            ),
            schema_hint='{"matrix_summary":["row"],"winner_by_dimension":{"dimension":"competitor or tie"}}',
        )
        detail.comparison_matrix = self._build_comparison_matrix(detail, payload)
        detail.updated_at = datetime.utcnow()
        await self.emit(detail.id, "node_completed", "comparator", None, "Comparator completed.", {"matrix": payload})

    async def _real_reflector_step(self, record: RunRecord) -> None:
        detail = record.detail
        detail.current_node = "reflector"
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
                f"Source digest JSON: {json.dumps(self._source_digest(detail.raw_sources), ensure_ascii=False)}"
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
        detail.updated_at = datetime.utcnow()
        await self.emit(
            detail.id,
            "node_completed",
            "reflector",
            None,
            "Reflector completed.",
            {"reflection": payload},
        )

    async def _real_writer_step(self, record: RunRecord) -> None:
        detail = record.detail
        detail.current_node = "writer"
        await self.emit(detail.id, "node_started", "writer", None, "Calling report writer.")
        detail.report_md = await self._trace_llm_text(
            record,
            agent="writer",
            subagent=None,
            name="report_writer",
            system=(
                "You are a competitive analysis report writer. Produce markdown. "
                "Keep it concise, evidence-aware, and include a Confidence Notes section. "
                "Cite factual claims with existing source IDs using [source:ID]. Do not invent source IDs."
            ),
            user=(
                f"Topic: {detail.topic}\n"
                f"Competitors: {', '.join(detail.plan.competitors)}\n"
                f"Dimensions: {', '.join(detail.plan.dimensions)}\n"
                f"Competitor KB JSON: {json.dumps({k: v.model_dump(mode='json') for k, v in detail.competitor_kbs.items()}, ensure_ascii=False)}\n"
                f"Comparison Matrix JSON: {json.dumps(detail.comparison_matrix.model_dump(mode='json') if detail.comparison_matrix else {}, ensure_ascii=False)}\n"
                f"Source digest JSON: {json.dumps(self._source_digest(detail.raw_sources), ensure_ascii=False)}\n"
                f"Reflections JSON: {json.dumps([r.model_dump(mode='json') for r in detail.reflections], ensure_ascii=False)}"
            ),
        )
        detail.updated_at = datetime.utcnow()
        await self.emit(
            detail.id,
            "report_updated",
            "writer",
            None,
            "Report markdown updated from real LLM call.",
            {"report_md": detail.report_md},
        )
        await self.emit(detail.id, "node_completed", "writer", None, "Writer completed.")

    async def _real_phase_qa_step(self, record: RunRecord, phase: Literal["collect", "analyst"]) -> None:
        detail = record.detail
        detail.current_node = "qa"
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

    def _route_phase_qa(self, state: dict[str, object], phase: Literal["collect", "analyst"]) -> str:
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
        if phase == "collect":
            detail.raw_sources = [
                source for source in detail.raw_sources if source.dimension not in dimensions
            ]
        for dimension in dimensions:
            self._clear_dimension_outputs(detail, dimension)
        detail.comparison_matrix = None
        detail.reflections = []
        detail.report_md = ""
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

    async def _real_qa_step(self, record: RunRecord) -> None:
        detail = record.detail
        detail.current_node = "qa"
        await self.emit(detail.id, "node_started", "qa", None, "Running deterministic QA.")
        issues = self._build_qa_issues(detail)
        detail.qa_findings = issues
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
        decision = await self._maybe_interrupt(
            record,
            stage="qa",
            message="QA findings are ready for review.",
            payload={"qa_findings": [issue.model_dump(mode="json") for issue in issues]},
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
        elif decision.decision == "redo":
            record.redo_after_interrupt = True

    def _build_qa_issues(self, detail: RunDetail) -> list[QCIssue]:
        missing_dimensions = self._missing_dimensions(detail)
        issues = self._build_collect_qa_issues(detail)
        issues.extend(self._build_analyst_qa_issues(detail, missing_dimensions))
        issues.extend(self._build_phantom_citation_issues(detail))
        issues.extend(self._build_matrix_consistency_issues(detail))
        return issues

    def _missing_dimensions(self, detail: RunDetail) -> list[str]:
        return [
            dimension
            for dimension in detail.plan.dimensions
            if not any(source.dimension == dimension for source in detail.raw_sources)
        ]

    def _build_collect_qa_issues(self, detail: RunDetail) -> list[QCIssue]:
        issues: list[QCIssue] = []
        missing_dimensions = self._missing_dimensions(detail)
        unverified_dimensions = sorted(
            {
                source.dimension
                for source in detail.raw_sources
                if source.source_type != "webpage_verified" and source.url is not None
            }
        )

        for dimension in missing_dimensions:
            scope = RedoScope(
                kind="collector",
                target_subagent=dimension,
                rationale=f"No sources collected for {dimension}.",
            )
            issues.append(
                QCIssue(
                    id=f"missing-{dimension}",
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

        for dimension in unverified_dimensions:
            if dimension in missing_dimensions:
                continue
            scope = RedoScope(
                kind="collector",
                target_subagent=dimension,
                rationale=f"Some {dimension} URLs could not be fetched and verified.",
            )
            issues.append(
                QCIssue(
                    id=f"unverified-{dimension}",
                    severity="warn",
                    detected_by="coverage",
                    target_agent="collector",
                    target_subagent=dimension,
                    field_path=f"raw_sources[{dimension}].source_type",
                    problem=(
                        f"At least one {dimension} source is still LLM public knowledge "
                        "rather than fetched webpage evidence."
                    ),
                    redo_scope=scope,
                    self_found=False,
                )
            )

        issues.extend(self._build_source_coverage_issues(detail, missing_dimensions))
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
            covered = source.covered_competitors or self._normalize_covered_competitors(detail, source.competitor)
            unknown = sorted(value for value in covered if value not in expected_competitors)
            if not covered or unknown:
                issue_id = f"invalid-source-coverage-{self._issue_id_fragment(source.id)}"
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
                            rationale=f"Source {source.id} needs competitor coverage normalization.",
                        ),
                        self_found=False,
                    )
                )

        for dimension in detail.plan.dimensions:
            if dimension in missing_dimensions:
                continue
            for competitor in detail.plan.competitors:
                if any(
                    source.dimension == dimension and self._source_matches_competitor(source, competitor)
                    for source in detail.raw_sources
                ):
                    continue
                issues.append(
                    QCIssue(
                        id=f"missing-source-{dimension}-{self._issue_id_fragment(competitor)}",
                        severity="blocker",
                        detected_by="coverage",
                        target_agent="collector",
                        target_subagent=dimension,
                        field_path=f"raw_sources[{dimension}][{competitor}]",
                        problem=f"No {dimension} source covers {competitor}.",
                        redo_scope=RedoScope(
                            kind="collector",
                            target_subagent=dimension,
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
        issues = self._build_empty_analyst_issues(detail, missing_dimensions)
        issues.extend(self._build_kb_citation_issues(detail))
        return issues

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
                    source.dimension == dimension and self._source_matches_competitor(source, competitor)
                    for source in detail.raw_sources
                )
                kb = detail.competitor_kbs.get(competitor)
                has_findings = bool(kb and kb.slices.get(dimension))
                if not has_sources or has_findings:
                    continue
                issue = QCIssue(
                    id=f"empty-analyst-{dimension}-{self._issue_id_fragment(competitor)}",
                    severity="warn",
                    detected_by="schema",
                    target_agent="analyst",
                    target_subagent=dimension,
                    field_path=f"competitor_kbs[{competitor}].slices[{dimension}]",
                    problem=f"{dimension.title()} analyst did not produce structured findings for {competitor}.",
                    redo_scope=RedoScope(kind="full", rationale="placeholder"),
                    self_found=False,
                )
                issue.redo_scope = assign_redo_scope(issue)
                issues.append(issue)
        return issues

    def _build_kb_citation_issues(self, detail: RunDetail) -> list[QCIssue]:
        known_source_ids = {source.id for source in detail.raw_sources}
        issues: list[QCIssue] = []
        for competitor, kb in detail.competitor_kbs.items():
            for dimension, findings in kb.slices.items():
                for cited_id in sorted(
                    cited_id
                    for finding in findings
                    for cited_id in self._extract_cited_source_ids(finding)
                    if cited_id not in known_source_ids
                ):
                    issue = QCIssue(
                        id=(
                            f"kb-unknown-source-{self._issue_id_fragment(competitor)}-"
                            f"{self._issue_id_fragment(dimension)}-{self._issue_id_fragment(cited_id)}"
                        ),
                        severity="blocker",
                        detected_by="citation",
                        target_agent="analyst",
                        target_subagent=dimension,
                        field_path=f"competitor_kbs[{competitor}].slices[{dimension}]",
                        problem=f"{dimension.title()} analyst cites unknown source id {cited_id} for {competitor}.",
                        redo_scope=RedoScope(kind="full", rationale="placeholder"),
                        self_found=False,
                    )
                    issue.redo_scope = assign_redo_scope(issue)
                    issues.append(issue)
        return issues

    def _build_phantom_citation_issues(self, detail: RunDetail) -> list[QCIssue]:
        known_source_ids = {source.id for source in detail.raw_sources}
        cited_ids = self._extract_cited_source_ids(detail.report_md)
        phantom_ids = sorted(cited_id for cited_id in cited_ids if cited_id not in known_source_ids)
        issues: list[QCIssue] = []
        for cited_id in phantom_ids:
            issue = QCIssue(
                id=f"phantom-citation-{self._issue_id_fragment(cited_id)}",
                severity="blocker",
                detected_by="citation",
                target_agent="writer",
                field_path="report_md",
                problem=f"Report cites unknown source id {cited_id}.",
                redo_scope=RedoScope(kind="full", rationale="placeholder"),
                self_found=False,
            )
            issue.redo_scope = assign_redo_scope(issue)
            issues.append(issue)
        return issues

    def _build_matrix_consistency_issues(self, detail: RunDetail) -> list[QCIssue]:
        if detail.comparison_matrix is None:
            if detail.competitor_kbs and detail.report_md:
                issue = QCIssue(
                    id="matrix-missing",
                    severity="blocker",
                    detected_by="consistency",
                    target_agent="comparator",
                    field_path="comparison_matrix",
                    problem="Comparison matrix is missing even though structured KB data exists.",
                    redo_scope=RedoScope(kind="full", rationale="placeholder"),
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
        known_source_ids = {source.id for source in detail.raw_sources}
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
                        f"Comparison matrix contains a duplicate cell for {cell.competitor} / {cell.dimension}.",
                    )
                )
            seen_cells.add(cell_key)

            if cell.competitor not in expected_competitors or cell.dimension not in expected_dimensions:
                issues.append(
                    self._matrix_issue(
                        f"matrix-extra-cell-{cell_id}",
                        "warn",
                        f"comparison_matrix.cells[{cell.competitor},{cell.dimension}]",
                        f"Comparison matrix contains a cell outside the analysis plan: {cell.competitor} / {cell.dimension}.",
                    )
                )
            for source_id in cell.source_ids:
                if source_id not in known_source_ids:
                    issues.append(
                        self._matrix_issue(
                            f"matrix-unknown-source-{self._issue_id_fragment(source_id)}",
                            "blocker",
                            "comparison_matrix.cells[].source_ids",
                            f"Comparison matrix references unknown source id {source_id}.",
                        )
                    )
            for cited_id in self._extract_cited_source_ids(cell.value):
                if cited_id in known_source_ids and cited_id not in cell.source_ids:
                    issues.append(
                        self._matrix_issue(
                            f"matrix-missing-cited-source-{self._issue_id_fragment(cell.competitor)}-"
                            f"{self._issue_id_fragment(cell.dimension)}-{self._issue_id_fragment(cited_id)}",
                            "blocker",
                            f"comparison_matrix.cells[{cell.competitor},{cell.dimension}].source_ids",
                            (
                                f"Comparison matrix cell for {cell.competitor} / {cell.dimension} cites "
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

    def _matrix_issue(
        self,
        issue_id: str,
        severity: Literal["info", "warn", "blocker"],
        field_path: str,
        problem: str,
    ) -> QCIssue:
        issue = QCIssue(
            id=issue_id,
            severity=severity,
            detected_by="consistency",
            target_agent="comparator",
            field_path=field_path,
            problem=problem,
            redo_scope=RedoScope(kind="full", rationale="placeholder"),
            self_found=False,
        )
        issue.redo_scope = assign_redo_scope(issue)
        return issue

    def _redo_limit_reached(self, detail: RunDetail) -> bool:
        return len(detail.revisions) >= detail.max_iterations

    def _extract_cited_source_ids(self, report_md: str) -> set[str]:
        patterns = [
            r"\bsource(?:\s+id)?\s*:\s*([A-Za-z0-9_.:-]+)",
            r"\[source(?:\s+id)?\s+([A-Za-z0-9_.:-]+)\]",
        ]
        cited: set[str] = set()
        for pattern in patterns:
            cited.update(re.findall(pattern, report_md, flags=re.IGNORECASE))
        return cited

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

    def _sources_for_competitor_dimension(
        self,
        detail: RunDetail,
        competitor: str,
        dimension: str,
    ) -> list[RawSource]:
        return [
            source
            for source in detail.raw_sources
            if source.dimension == dimension and self._source_matches_competitor(source, competitor)
        ]

    def _merge_kb_slice(
        self,
        detail: RunDetail,
        dimension: str,
        competitor_findings: dict[str, list[str]],
    ) -> None:
        for competitor in detail.plan.competitors:
            findings = [finding for finding in competitor_findings.get(competitor, []) if finding.strip()]
            if not findings:
                findings = [
                    source.snippet or source.title
                    for source in self._sources_for_competitor_dimension(detail, competitor, dimension)
                ][:3]
            kb = detail.competitor_kbs.get(competitor) or CompetitorKB(competitor=competitor)
            kb.slices[dimension] = findings
            source_ids = [
                source.id
                for source in self._sources_for_competitor_dimension(detail, competitor, dimension)
            ]
            kb.sources = sorted(set(kb.sources + source_ids))
            source_confidences = [
                source.confidence
                for source in detail.raw_sources
                if self._source_matches_competitor(source, competitor)
            ]
            kb.confidence = (
                sum(source_confidences) / len(source_confidences)
                if source_confidences
                else kb.confidence
            )
            detail.competitor_kbs[competitor] = kb

    def _clear_dimension_outputs(self, detail: RunDetail, dimension: str) -> None:
        for kb in detail.competitor_kbs.values():
            kb.slices.pop(dimension, None)
            valid_source_ids = {
                source.id
                for source in detail.raw_sources
                if self._source_matches_competitor(source, kb.competitor)
            }
            kb.sources = [source_id for source_id in kb.sources if source_id in valid_source_ids]
        if detail.comparison_matrix is not None:
            detail.comparison_matrix = self._build_comparison_matrix(
                detail,
                {
                    "matrix_summary": detail.comparison_matrix.summary,
                    "winner_by_dimension": detail.comparison_matrix.winner_by_dimension,
                },
            )

    def _normalize_competitor_findings(self, detail: RunDetail, payload: dict) -> dict[str, list[str]]:
        raw = payload.get("competitor_findings")
        if isinstance(raw, dict):
            normalized: dict[str, list[str]] = {}
            for competitor in detail.plan.competitors:
                values = raw.get(competitor) or raw.get(competitor.lower()) or []
                if isinstance(values, list):
                    normalized[competitor] = [str(value) for value in values if str(value).strip()]
                elif values:
                    normalized[competitor] = [str(values)]
            return normalized

        findings = self._string_list(payload.get("findings"))
        return {competitor: findings for competitor in detail.plan.competitors}

    def _build_comparison_matrix(self, detail: RunDetail, payload: dict) -> ComparisonMatrix:
        cells: list[ComparisonCell] = []
        for dimension in detail.plan.dimensions:
            for competitor in detail.plan.competitors:
                kb = detail.competitor_kbs.get(competitor)
                findings = kb.slices.get(dimension, []) if kb else []
                related_sources = [
                    source for source in self._sources_for_competitor_dimension(detail, competitor, dimension)
                ]
                value = "; ".join(findings[:2])
                if not value and related_sources:
                    value = related_sources[0].snippet or related_sources[0].title
                cells.append(
                    ComparisonCell(
                        competitor=competitor,
                        dimension=dimension,
                        value=value or "No structured finding available.",
                        source_ids=[source.id for source in related_sources],
                        confidence=(
                            sum(source.confidence for source in related_sources) / len(related_sources)
                            if related_sources
                            else 0.0
                        ),
                    )
                )

        winners = payload.get("winner_by_dimension")
        if not isinstance(winners, dict):
            winners = {}
        return ComparisonMatrix(
            competitors=detail.plan.competitors,
            dimensions=detail.plan.dimensions,
            cells=cells,
            winner_by_dimension={str(key): str(value) for key, value in winners.items()},
            summary=self._string_list(payload.get("matrix_summary")),
        )

    def _source_digest(self, sources: list[RawSource]) -> list[dict[str, object]]:
        return [
            {
                "id": source.id,
                "competitor": source.competitor,
                "covered_competitors": source.covered_competitors,
                "dimension": source.dimension,
                "source_type": source.source_type,
                "title": source.title[:160],
                "url": str(source.url) if source.url else None,
                "snippet": source.snippet[:420],
                "confidence": source.confidence,
            }
            for source in sources
        ]

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
