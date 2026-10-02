from __future__ import annotations

import asyncio
import json
import time

from packages.llm.doubao_client import LLMUsage
from packages.llm.errors import LLMExecutionLimitError
from packages.llm.execution_budget import LLMCallExecution, current_llm_execution
from packages.search import SearchFilters, SearchResult
from packages.search.deepseek_client import SEARCH_INPUT_RESERVE_PER_USE
from packages.tools.web_search import WebSearchRequest, web_search


class SearchExecutionMixin:
    """Run-scoped search reuse, native model admission and trace accounting."""

    async def _trace_search(
        self,
        record,
        *,
        agent: str,
        subagent: str | None,
        query: str,
        max_results: int,
        context=None,
        filters: SearchFilters | None = None,
    ) -> list[SearchResult]:
        started = time.perf_counter()
        native = self._settings.web_search_provider == "deepseek" and self._search.is_enabled
        cache_key = json.dumps(
            [query, max_results, filters.payload() if filters else {}],
            ensure_ascii=False,
            sort_keys=True,
        )
        metadata = {
            "provider": self._settings.web_search_provider,
            "filters": json.dumps(filters.payload(), ensure_ascii=False) if filters else "",
            "max_results": max_results,
        }
        execution, usage = None, None
        status, output, results = "error", "", []
        if context is not None:
            context.add_tool_call("web_search", query)
        # Locks are kept for the bounded lifetime of a run, including waiters.
        lock = (
            record.search_locks.setdefault(cache_key, asyncio.Lock()) if native else asyncio.Lock()
        )
        try:
            async with lock:
                if native and record.detail.evidence_refresh_active:
                    record.search_cache.pop(cache_key, None)
                cached = record.search_cache.get(cache_key) if native else None
                if (
                    cached is not None
                    and time.monotonic() - cached[0] < 300
                    and not record.detail.evidence_refresh_active
                ):
                    results = list(cached[1])
                    metadata.update(
                        search_cache_hit=True,
                        llm_request_attempts=0,
                        llm_tokens_charged=0,
                        llm_cost_charged_usd=0.0,
                    )
                else:
                    collector_budget = self._collector_research_budget_usage(
                        record, agent, subagent, context
                    )
                    if collector_budget is not None:
                        usage_counter, budget = collector_budget
                        if usage_counter.search_calls >= budget.max_search_queries:
                            output = "collector_search_budget_exhausted"
                            metadata["budget_exhausted"] = True
                            return []
                        usage_counter.search_calls += 1
                    if native:
                        filter_text = (
                            json.dumps(filters.payload(), ensure_ascii=False) if filters else ""
                        )
                        execution = LLMCallExecution(
                            self._run_llm_budget(record),
                            is_repair=record.pending_graph_redo is not None,
                            input_tokens=len((query + filter_text).encode("utf-8"))
                            + 512
                            + SEARCH_INPUT_RESERVE_PER_USE
                            * self._settings.deepseek_search_max_uses,
                            max_output_tokens=self._settings.deepseek_search_max_tokens,
                        )
                        execution.checkpoint = lambda: self._checkpoint_llm_budget(
                            record, execution.budget
                        )
                        metadata.update(
                            search_cache_hit=False,
                            native_search=True,
                            llm_provider="deepseek",
                            llm_model=self._settings.deepseek_search_model,
                            price_basis="configured_estimate",
                            filter_mode="prompt_preferences_and_domain_postfilter",
                        )
                        async with self._llm_semaphore:
                            execution.reserve()
                            token = current_llm_execution.set(execution)
                            try:
                                results = await web_search(
                                    self._search, WebSearchRequest(query, max_results, filters)
                                )
                            finally:
                                usage = self._search.consume_last_usage()
                                metadata.update(self._search.consume_last_metadata())
                                current_llm_execution.reset(token)
                        record.search_cache[cache_key] = (time.monotonic(), list(results))
                    else:
                        results = await web_search(
                            self._search, WebSearchRequest(query, max_results, filters)
                        )
                metadata["result_count"] = len(results)
                output = json.dumps([result.__dict__ for result in results], ensure_ascii=False)
                status = "ok"
            return results
        except asyncio.CancelledError:
            output = "搜索已取消"
            metadata["degradation_reason"] = "search_cancelled"
            raise
        except Exception as exc:
            output = str(exc)
            metadata["error"] = output
            if isinstance(exc, LLMExecutionLimitError):
                metadata["degradation_reason"] = str(exc)
            raise
        finally:
            if execution is not None:
                execution.settle(
                    prompt_tokens=getattr(usage, "prompt_tokens", None),
                    completion_tokens=getattr(usage, "completion_tokens", None),
                    cache_hit_tokens=getattr(usage, "prompt_cache_hit_tokens", 0) or 0,
                )
                metadata.update(
                    execution.metadata(), token_usage_source="provider" if usage else "estimate"
                )
                if usage is not None:
                    metadata.update(
                        {
                            field: getattr(usage, field)
                            for field in (
                                "prompt_tokens",
                                "completion_tokens",
                                "total_tokens",
                                "prompt_cache_hit_tokens",
                                "prompt_cache_miss_tokens",
                            )
                            if getattr(usage, field) is not None
                        }
                    )
                self._checkpoint_llm_budget(record, execution.budget)
            estimated_usage = (
                LLMUsage(
                    prompt_tokens=execution.input_tokens,
                    completion_tokens=execution.max_output_tokens,
                )
                if execution is not None and execution.attempts
                else None
            )
            span_id = self._append_trace_span(
                record,
                kind="search",
                agent=agent,
                subagent=subagent,
                name="web_search",
                status=status,
                started=started,
                input_text=query,
                output_text=output,
                metadata=self._trace_metadata(context, metadata),
                token_usage=usage or estimated_usage,
            )
            if status == "ok":
                await self.emit(
                    record.detail.id,
                    "tool.called",
                    agent,
                    subagent,
                    f"网页搜索返回 {len(results)} 条候选。",
                    {
                        "tool": "web_search",
                        "query": query,
                        "result_count": len(results),
                        "filters": filters.payload() if filters else {},
                        "related_span_ids": [span_id],
                        "input": query,
                        "output": f"{len(results)} 条候选",
                        "search_cache_hit": metadata.get("search_cache_hit", False),
                    },
                )
                await self.emit(
                    record.detail.id,
                    "rag.retrieved",
                    agent,
                    subagent,
                    f"取得 {len(results)} 条联网证据候选。",
                    {
                        "query": query,
                        "result_count": len(results),
                        "candidate_urls": [result.url for result in results[:5]],
                        "related_span_ids": [span_id],
                        "reason": "搜索结果需要抓取正文并核验后才能用于报告。",
                    },
                )
