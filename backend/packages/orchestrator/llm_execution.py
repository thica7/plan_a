from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any

from packages.agents.prompt_contract import prompt_trace_metadata
from packages.llm.errors import LLMExecutionLimitError
from packages.llm.execution_budget import LLMCallExecution, RunLLMBudget, current_llm_execution
from packages.research.budget import research_depth_budget


class LLMExecutionMixin:
    """Admission, accounting and trace capture for all Agent LLM calls."""

    def _llm_request_envelope(self, *, system, user, schema_hint=None, max_output_tokens=None):
        input_text = f"{system}\n\n{user}"
        if schema_hint is not None:
            input_text += f"\n\nSchema: {schema_hint}"
        output = self._settings.llm_max_output_tokens or 4096
        if max_output_tokens:
            output = min(output, max_output_tokens)
        return input_text, len(input_text.encode('utf-8')) + 256, output

    def _llm_request_admission_error(self, record, *, agent, subagent, name, system, user,
                                     schema_hint=None, max_output_tokens=None, is_repair=False):
        record = self._evidence_live_record(record)
        _, input_tokens, output_tokens = self._llm_request_envelope(system=system, user=user,
            schema_hint=schema_hint, max_output_tokens=max_output_tokens)
        return self._run_llm_budget(record).admission_error(
            is_repair=is_repair or record.pending_graph_redo is not None,
            input_tokens=input_tokens, max_output_tokens=output_tokens,
            phase=self._llm_phase(agent, subagent, name=name, record=record))

    async def _admit_llm_call(self, execution):
        while True:
            try:
                execution.reserve()
                return
            except LLMExecutionLimitError as exc:
                budget = execution.budget
                tokens = execution.input_tokens + execution.max_output_tokens
                cost = budget.cost(execution.input_tokens, execution.max_output_tokens)
                transient = (
                    str(exc) == 'run_llm_token_budget_exhausted'
                    and budget.max_tokens and budget.tokens_used + tokens <= budget.max_tokens
                ) or (
                    str(exc) == 'run_llm_cost_budget_exhausted'
                    and budget.max_cost_usd and budget.cost_used_usd + cost <= budget.max_cost_usd
                )
                if str(exc) == 'run_llm_budget_reserved_for_delivery':
                    protected = budget.protected_tokens(execution.phase)
                    transient = (
                        (not budget.max_tokens or budget.tokens_used + tokens + protected <= budget.max_tokens)
                        and budget.calls + 1 + budget.protected_calls(execution.phase) <= budget.max_calls
                        and (not budget.max_cost_usd or budget.cost_used_usd + cost + protected * max(
                            budget.input_usd_per_million, budget.output_usd_per_million) / 1_000_000 <= budget.max_cost_usd)
                    )
                if not transient or not budget.tokens_reserved:
                    raise
                budget.reservation_settled.clear()
                await budget.reservation_settled.wait()

    def _run_llm_budget(self, record) -> RunLLMBudget:
        record = self._evidence_live_record(record)
        restoring = record.llm_budget is None
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
            record.llm_budget._fresh_selected_task_budget = not checkpoint and not spans
        budget = record.llm_budget
        from packages.agents.writer.dimension_writer import dimension_writing_enabled
        dimension_mode = dimension_writing_enabled(record.detail)
        task_segments = self._task_delivery_segments(record, dimension_mode=dimension_mode)
        if dimension_mode or (record.detail.execution_mode == 'real' and budget.max_tokens):
            products = list(record.detail.plan.competitors)
            target = record.detail.plan.target_product
            if target and target.name not in products:
                products.append(target.name)
            segments = [f"{p}/{d}" for d in record.detail.plan.dimensions for p in products]
            phases = ([f"{agent}:{segment}" for segment in segments for agent in ('writer', 'qa')]
                      if dimension_mode else ['writer:run'])
            phases += [f'collector:{segment}' for segment in segments]
            phases += [f'analyst:{segment}' for segment in segments]
            phases += ['comparator:run', 'reflector:run']
            if task_segments:
                phases += [f'answer:{segment}' for segment in task_segments]
                phases += ['final_qa:run']
            # Leave acquisition room and a shared conservative request envelope.
            # Only core stages may borrow the envelope; actual/unknown usage is
            # still charged against the same global hard cap.
            fractions = {'collector': .10, 'analyst': .16, 'comparator': .10,
                         'reflector': .06, 'writer': .16 if dimension_mode else .28, 'qa': .12}
            if task_segments:
                # Final answer and final QA both receive complete request
                # envelopes, independent of task drafting/review. Earlier
                # acquisition/analysis share 23%; task drafting/review use
                # shared headroom while keeping their independent call floors.
                fractions = {'collector': .06, 'analyst': .10, 'comparator': .04,
                             'reflector': .03, 'writer': .0, 'qa': .0}
            checkpoint = record.detail.llm_budget_checkpoint
            budget.stage_headroom = min(12000, int(budget.max_tokens * (.04 if task_segments else .06))) if budget.max_tokens else 0
            adding_phases = any(phase not in budget.delivery_reserves for phase in phases)
            persisted_phases = {phase for phase in phases
                                if task_segments and f'delivery_limit:{phase}' in checkpoint}
            final_review_calls = 1
            if task_segments:
                from packages.research.question_scope import research_questions
                # Protect question checks plus one historical window. Extra
                # dispatches still use only the unchanged global allowance.
                final_review_calls = min(6, 1 + sum(
                    len(research_questions(record.detail, scope.rsplit('/', 1)[0], 'feature'))
                    for scope in task_segments
                ))
            for phase in phases:
                agent = phase.split(':', 1)[0]
                count = 1 if agent in {'comparator', 'reflector'} or (agent == 'writer' and not dimension_mode) else max(1, len(segments))
                if agent == 'answer':
                    from packages.agents.writer.task_answers import TASK_ANSWER_RESERVE
                    desired = min(TASK_ANSWER_RESERVE, int(budget.max_tokens * .15)) if budget.max_tokens else TASK_ANSWER_RESERVE
                    desired //= len(task_segments)
                elif agent == 'final_qa':
                    from packages.agents.qa.independent_question_review import (
                        FINAL_QA_REQUEST_RESERVE,
                    )

                    # Protect the real complete system/user/output envelope.
                    desired = FINAL_QA_REQUEST_RESERVE
                else:
                    desired = min(32000, int(budget.max_tokens * fractions[agent] / count)) if budget.max_tokens else 32000
                if phase in budget.delivery_reserves:
                    if adding_phases and phase not in persisted_phases:
                        budget.delivery_reserves[phase] = min(budget.delivery_reserves[phase], desired)
                    continue
                budget.delivery_reserves[phase] = int(checkpoint.get(f'delivery_limit:{phase}', desired))
                budget.delivery_charged[phase] = int(checkpoint.get(f'delivery_charged:{phase}', 0))
                budget.delivery_calls[phase] = int(checkpoint.get(f'delivery_calls:{phase}', 0))
                # A legacy checkpoint cannot gain the task profile's new
                # call floors; explicitly persisted floors survive rollback.
                default_calls = budget.delivery_calls[phase] if task_segments and restoring and checkpoint else 1
                if agent == 'final_qa' and not (task_segments and restoring and checkpoint):
                    default_calls = final_review_calls
                elif (agent == 'answer' and self._settings.writer_question_atomic_enabled
                        and not (restoring and checkpoint)):
                    from packages.research.question_scope import research_questions
                    product = phase.split(':', 1)[1].rsplit('/', 1)[0]
                    default_calls = max(
                        1, len(research_questions(record.detail, product, 'feature')))
                budget.delivery_call_reserves[phase] = int(checkpoint.get(
                    f'delivery_call_limit:{phase}', default_calls))
                if checkpoint.get(f'delivery_finished:{phase}'):
                    budget.delivery_finished.add(phase)
            for phase in budget.delivery_reserves.keys() - set(phases):
                budget.finish_delivery(phase)
            if task_segments and adding_phases and 'final_qa:run' not in persisted_phases:
                phase = 'final_qa:run'
                other_calls = sum(
                    max(0, amount - budget.delivery_calls.get(key, 0))
                    for key, amount in budget.delivery_call_reserves.items()
                    if key != phase and key not in budget.delivery_finished
                )
                available_calls = max(0, budget.max_calls - budget.calls - other_calls)
                budget.delivery_call_reserves[phase] = min(
                    budget.delivery_call_reserves[phase],
                    budget.delivery_calls.get(phase, 0) + available_calls,
                )
            # Legacy checkpoints did not preserve phase allowances. Recovery
            # must protect only what is still available, not recreate a full
            # allowance on top of charges that already consumed it.
            protected = sum(max(0, amount - budget.delivery_charged.get(phase, 0))
                            for phase, amount in budget.delivery_reserves.items()
                            if phase not in budget.delivery_finished)
            available = max(0, budget.max_tokens - budget.tokens_used - budget.tokens_reserved) if budget.max_tokens else protected
            if budget.max_cost_usd:
                remaining_cost = max(0, budget.max_cost_usd - budget.cost_used_usd - budget.cost_reserved_usd)
                rate = max(budget.input_usd_per_million, budget.output_usd_per_million)
                if rate > 0:
                    available = min(available, int(remaining_cost * 1_000_000 / rate))
            available = max(0, available - budget.stage_headroom)
            adjustable = {phase for phase in budget.delivery_reserves
                          if phase not in budget.delivery_finished and phase not in persisted_phases}
            adjustable_protected = sum(max(0, budget.delivery_reserves[phase] - budget.delivery_charged.get(phase, 0))
                                       for phase in adjustable)
            # Persisted task allowances already survived admission. Recovery
            # must not turn them into headroom that earlier tasks can spend.
            available = max(0, available - (protected - adjustable_protected))
            if adjustable_protected > available and (restoring or adding_phases):
                available = int(available * .70)
                for phase in adjustable:
                    amount = budget.delivery_reserves[phase]
                    charged = budget.delivery_charged.get(phase, 0)
                    budget.delivery_reserves[phase] = charged + int(max(0, amount - charged) * available / adjustable_protected)
        return budget

    def _task_delivery_segments(self, record, *, dimension_mode=None):
        if (record is None or not self._settings.writer_task_execution_enabled
                or record.detail.execution_mode != 'real'):
            return []
        if dimension_mode is None:
            from packages.agents.writer.dimension_writer import dimension_writing_enabled
            dimension_mode = dimension_writing_enabled(record.detail)
        if not dimension_mode or 'feature' not in record.detail.plan.dimensions:
            return []
        from packages.research.question_scope import research_questions
        products = list(record.detail.plan.competitors)
        target = record.detail.plan.target_product
        if target and target.name not in products:
            products.append(target.name)
        return [f'{product}/feature' for product in products
                if research_questions(record.detail, product, 'feature')]

    def _llm_phase(self, agent, subagent, *, name=None, record=None):
        if name is not None:
            task_segments = self._task_delivery_segments(record)
            if task_segments:
                if agent == 'qa' and name == 'final_question_reconciliation' and subagent is None:
                    return 'final_qa:run'
                if subagent in task_segments:
                    if name in {
                            'dimension_task_plan', 'dimension_task_generation',
                            'dimension_question_atomic_generation'}:
                        return f'writer:{subagent}'
                    if name in {'dimension_task_review', 'dimension_question_atomic_review'}:
                        return f'qa:{subagent}'
                    if name in {
                            'dimension_answer_review', 'dimension_question_atomic_answer_review'}:
                        return f'answer:{subagent}'
        if agent in {'comparator', 'reflector'} or (agent == 'writer' and not subagent):
            return f'{agent}:run'
        if agent in {'collector', 'analyst'} and subagent and '::' in subagent:
            dimension, product = subagent.split('::', 1)
            return f'{agent}:{product}/{dimension}'
        return f'{agent}:{subagent}' if subagent else None

    def _finish_delivery_phase(self, record, agent, subagent):
        budget = self._run_llm_budget(record)
        budget.finish_delivery(self._llm_phase(agent, subagent) or f'{agent}:run')
        self._checkpoint_llm_budget(record, budget)

    def _checkpoint_llm_budget(self, record, budget) -> None:
        record = self._evidence_live_record(record)
        # Persist admission BEFORE transport. On crash, outstanding reservations
        # become conservative charges; they cannot disappear on process recovery.
        record.detail.llm_budget_checkpoint = {
            "calls": budget.calls, "repairs": budget.repairs,
            "tokens_charged": budget.tokens_used + budget.tokens_reserved,
            "cost_charged_usd": budget.cost_used_usd + budget.cost_reserved_usd,
        }
        for phase, amount in budget.delivery_reserves.items():
            record.detail.llm_budget_checkpoint.update({
                f'delivery_limit:{phase}': amount,
                f'delivery_charged:{phase}': budget.delivery_charged.get(phase, 0),
                f'delivery_calls:{phase}': budget.delivery_calls.get(phase, 0),
                f'delivery_call_limit:{phase}': budget.delivery_call_reserves.get(phase, 1),
                f'delivery_finished:{phase}': int(phase in budget.delivery_finished),
            })
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
        max_output_tokens: int | None = None,
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
            max_output_tokens=max_output_tokens,
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
        max_output_tokens: int | None = None,
        max_request_attempts: int | None = None,
        response_format=None,
        response_contract=None,
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
            max_output_tokens=max_output_tokens,
            max_request_attempts=max_request_attempts,
            response_format=response_format,
            response_contract=response_contract,
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
        max_output_tokens=None,
        max_request_attempts=None,
        response_format=None,
        response_contract=None,
    ):
        record = self._evidence_live_record(record)
        started = time.perf_counter()
        input_text, input_tokens, output_tokens = self._llm_request_envelope(
            system=system, user=user, schema_hint=schema_hint, max_output_tokens=max_output_tokens)
        if context is not None:
            context.add_message("system", system)
            context.add_message("user", user)
        execution = LLMCallExecution(
            self._run_llm_budget(record),
            is_repair=is_repair or record.pending_graph_redo is not None,
            phase=self._llm_phase(agent, subagent, name=name, record=record),
            # UTF-8 bytes bound ordinary text tokenization conservatively;
            # framing/schema instructions reserve additional room.
            input_tokens=input_tokens,
            max_output_tokens=output_tokens,
            max_attempts=max_request_attempts,
        )
        execution.checkpoint = lambda: self._checkpoint_llm_budget(record, execution.budget)
        queue_wait_ms = 0
        status = "error"
        output_text = ""
        usage = None
        extra = {}
        try:
            async with self._llm_semaphore:
                await self._admit_llm_call(execution)
                queue_wait_ms = max(0, int((time.perf_counter() - started) * 1000))
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
                            if response_format and hasattr(self._llm, 'last_raw_response'):
                                extra['_native_raw_response'] = self._llm.last_raw_response()
                            raise

                    async def invoke():
                        if schema_hint is None:
                            result = await self._llm.complete_text(system=system, user=user,
                                **({"response_format": response_format} if response_format else {}))
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
            if response_format and hasattr(self._llm, "last_raw_response"):
                raw = extra.pop('_native_raw_response', self._llm.last_raw_response())
                if raw is not None:
                    output_text = raw
            if isinstance(exc, LLMExecutionLimitError):
                extra["degradation_reason"] = str(exc)
            elif isinstance(exc, TimeoutError):
                if execution.transport_attempts > execution.timeout_attempts:
                    execution.timeout_attempts += 1
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
                        **prompt_trace_metadata(agent, name, system, user, schema_hint),
                        "response_format": response_format or (
                            "json" if schema_hint is not None else "text"),
                        **({"response_contract": response_contract,
                            "response_transport_identity": hashlib.sha256(
                                json.dumps([system, user, response_format, response_contract],
                                    ensure_ascii=False).encode()).hexdigest()}
                           if response_format else {}),
                        "queue_wait_ms": queue_wait_ms,
                        "cost_estimate_source": "provider_usage"
                        if usage is not None
                        else "text_estimate",
                        "price_basis": "deepseek_flash_peak_usd_2026-10-01"
                        if self._settings.llm_provider_name == "deepseek"
                        else "configured_estimate",
                        **execution.metadata(),
                        "llm_execution_status": "succeeded" if status == "ok" else (
                            "error" if execution.transport_attempts else "rejected"),
                        **extra,
                    },
                ),
                token_usage=usage,
            )
