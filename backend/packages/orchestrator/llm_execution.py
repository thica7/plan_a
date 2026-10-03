from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from packages.llm.errors import LLMExecutionLimitError
from packages.llm.execution_budget import LLMCallExecution, RunLLMBudget, current_llm_execution
from packages.research.budget import research_depth_budget


class LLMExecutionMixin:
    """Admission, accounting and trace capture for all Agent LLM calls."""

    def _run_llm_budget(self, record) -> RunLLMBudget:
        if record.llm_budget is None:
            spans = [span for span in record.detail.trace_spans if span.kind == "llm"
                     or (span.kind == "search" and span.metadata.get("native_search"))]
            depth_budget = research_depth_budget(record.detail.plan.research_depth)
            max_calls = max(1, self._settings.run_llm_max_calls)
            checkpoint = record.detail.llm_budget_checkpoint
            # Trace spans are persisted with RunDetail across process recovery.
            record.llm_budget = RunLLMBudget(
                max_calls=min(
                    max_calls,
                    depth_budget.llm_max_calls if depth_budget is not None else max_calls,
                ),
                max_repairs=max(0, self._settings.run_llm_max_repairs),
                calls=int(checkpoint["calls"]) if checkpoint else sum(
                    int(span.metadata.get("llm_request_attempts", 1)) for span in spans),
                repairs=int(checkpoint["repairs"]) if checkpoint else sum(
                    int(span.metadata.get("llm_repair_attempts", 0)) for span in spans),
                max_tokens=self._settings.run_llm_max_tokens,
                max_cost_usd=self._settings.run_llm_max_cost_usd,
                tokens_used=int(checkpoint["tokens_charged"]) if checkpoint else sum(
                    int(span.metadata.get("llm_tokens_charged",
                        span.input_tokens_estimate + span.output_tokens_estimate))
                    for span in spans),
                cost_used_usd=float(checkpoint["cost_charged_usd"]) if checkpoint else sum(
                    float(span.metadata.get("llm_cost_charged_usd", span.cost_estimate_usd))
                    for span in spans),
                input_usd_per_million=self._settings.llm_input_usd_per_million,
                cache_usd_per_million=self._settings.llm_cache_usd_per_million,
                output_usd_per_million=self._settings.llm_output_usd_per_million,
            )
        return record.llm_budget

    def _checkpoint_llm_budget(self, record, budget) -> None:
        # Persist admission BEFORE transport. On crash, outstanding reservations
        # become conservative charges; they cannot disappear on process recovery.
        record.detail.llm_budget_checkpoint = {
            "calls": budget.calls, "repairs": budget.repairs,
            "tokens_charged": budget.tokens_used + budget.tokens_reserved,
            "cost_charged_usd": budget.cost_used_usd + budget.cost_reserved_usd,
        }
        self._persist_run(record.detail.id)

    async def _trace_llm_json(
        self,
        record,
        *,
        agent: str,
        subagent: str | None,
        name: str,
        system: str,
        user: str,
        schema_hint: str,
        context=None,
        is_repair: bool = False,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return await self._trace_budgeted_llm(
            record,
            agent=agent,
            subagent=subagent,
            name=name,
            system=system,
            user=user,
            schema_hint=schema_hint,
            context=context,
            is_repair=is_repair,
            timeout_seconds=timeout_seconds,
        )

    async def _trace_llm_text(
        self,
        record,
        *,
        agent: str,
        subagent: str | None,
        name: str,
        system: str,
        user: str,
        context=None,
        is_repair: bool = False,
        timeout_seconds: float | None = None,
    ) -> str:
        return await self._trace_budgeted_llm(
            record,
            agent=agent,
            subagent=subagent,
            name=name,
            system=system,
            user=user,
            schema_hint=None,
            context=context,
            is_repair=is_repair,
            timeout_seconds=timeout_seconds,
        )

    async def _trace_budgeted_llm(
        self,
        record,
        *,
        agent,
        subagent,
        name,
        system,
        user,
        schema_hint,
        context,
        is_repair,
        timeout_seconds,
    ):
        record = self._evidence_live_record(record)
        started = time.perf_counter()
        input_text = f"{system}\n\n{user}"
        if schema_hint is not None:
            input_text += f"\n\nSchema: {schema_hint}"
        if context is not None:
            context.add_message("system", system)
            context.add_message("user", user)
        execution = LLMCallExecution(
            self._run_llm_budget(record),
            is_repair=is_repair or record.pending_graph_redo is not None,
            # UTF-8 bytes bound ordinary text tokenization conservatively;
            # framing/schema instructions reserve additional room.
            input_tokens=len(input_text.encode("utf-8")) + 256,
            max_output_tokens=self._settings.llm_max_output_tokens or 4096,
        )
        execution.checkpoint = lambda: self._checkpoint_llm_budget(record, execution.budget)
        queue_wait_ms = 0
        status = "error"
        output_text = ""
        usage = None
        extra = {}
        try:
            async with self._llm_semaphore:
                queue_wait_ms = max(0, int((time.perf_counter() - started) * 1000))
                execution.reserve()
                token = current_llm_execution.set(execution)
                try:

                    async def call():
                        nonlocal extra
                        try:
                            return await invoke()
                        except BaseException:
                            # Read provenance inside the provider task before
                            # wait_for propagates cancellation to its caller.
                            extra = self._llm_usage_metadata(None)
                            raise

                    async def invoke():
                        if schema_hint is None:
                            result = await self._llm.complete_text(system=system, user=user)
                        else:
                            result = await self._llm.complete_json(
                                system=system,
                                user=user,
                                schema_hint=schema_hint,
                            )
                        usage = self._consume_llm_usage()
                        return result, usage, self._llm_usage_metadata(usage)

                    operation = call()
                    result, usage, extra = (
                        await asyncio.wait_for(operation, timeout=timeout_seconds)
                        if timeout_seconds is not None
                        else await operation
                    )
                    output_text = (
                        result if schema_hint is None else json.dumps(result, ensure_ascii=False)
                    )
                finally:
                    current_llm_execution.reset(token)
            status = "ok"
            if context is not None:
                context.add_message("assistant", output_text)
            return result
        except asyncio.CancelledError:
            output_text = "LLM call cancelled by stage timeout or pipeline cancellation"
            extra = {**extra, "degradation_reason": "llm_cancelled", "error": output_text}
            if not queue_wait_ms:
                queue_wait_ms = max(0, int((time.perf_counter() - started) * 1000))
            raise
        except Exception as exc:
            output_text = str(exc)
            extra = {**extra, "error": output_text}
            if isinstance(exc, LLMExecutionLimitError):
                extra["degradation_reason"] = str(exc)
            elif isinstance(exc, TimeoutError):
                extra["degradation_reason"] = "llm_timeout"
                extra["timeout_seconds"] = timeout_seconds
            raise
        finally:
            execution.settle(
                prompt_tokens=getattr(usage, "prompt_tokens", None),
                completion_tokens=getattr(usage, "completion_tokens", None),
                cache_hit_tokens=getattr(usage, "prompt_cache_hit_tokens", 0) or 0,
            )
            self._append_trace_span(
                record,
                kind="llm",
                agent=agent,
                subagent=subagent,
                name=name,
                status=status,
                started=started,
                input_text=input_text,
                output_text=output_text,
                metadata=self._trace_metadata(
                    context,
                    {
                        "response_format": "json" if schema_hint is not None else "text",
                        "queue_wait_ms": queue_wait_ms,
                        "cost_estimate_source": "provider_usage"
                        if usage is not None
                        else "text_estimate",
                        "price_basis": "deepseek_flash_peak_usd_2026-10-01"
                        if self._settings.llm_provider_name == "deepseek"
                        else "configured_estimate",
                        **execution.metadata(),
                        **extra,
                    },
                ),
                token_usage=usage,
            )
