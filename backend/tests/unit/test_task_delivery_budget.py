"""Offline admission replays for the task Writer's final delivery floors."""

import asyncio
import json

import httpx
import pytest
from test_execution_limits import _service

from packages.config import Settings, get_settings
from packages.llm.errors import LLMExecutionLimitError
from packages.llm.execution_budget import LLMCallExecution, RunLLMBudget
from packages.schema.models import DecisionBrief


async def task_service(**settings):
    settings.setdefault("writer_task_execution_enabled", True)
    service, record = await _service(
        run_llm_max_calls=24,
        run_llm_max_tokens=80000,
        llm_max_output_tokens=1600,
        llm_max_retries=0,
        **settings,
    )
    record.detail.topic = "Example Suite 能否让访客评论文档？"
    record.detail.plan.dimensions = ["feature"]
    record.detail.plan.competitors = ["Example Suite"]
    record.detail.plan.decision_brief = DecisionBrief(decision_question=record.detail.topic)
    return service, record


def test_task_writer_setting_defaults_off_and_env_can_opt_in(monkeypatch):
    assert getattr(Settings(), "writer_task_execution_enabled", None) is False
    monkeypatch.setenv("COMPETISCOPE_LOAD_ENV_FILES", "0")
    monkeypatch.setenv("WRITER_TASK_EXECUTION_ENABLED", "0")
    get_settings.cache_clear()
    try:
        assert get_settings().writer_task_execution_enabled is False
        monkeypatch.setenv('WRITER_TASK_EXECUTION_ENABLED', '1')
        get_settings.cache_clear()
        assert get_settings().writer_task_execution_enabled is True
        monkeypatch.setenv('WRITER_TASK_EXECUTION_ENABLED', '0')
        get_settings.cache_clear()
        assert get_settings().writer_task_execution_enabled is False
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_task_profile_keeps_separate_final_answer_and_run_review_floors():
    service, record = await task_service()
    budget = service._run_llm_budget(record)
    assert budget.delivery_reserves.get("answer:Example Suite/feature", 0) >= 18000
    assert budget.delivery_reserves.get("final_qa:run", 0) == 10000
    assert budget.delivery_call_reserves["answer:Example Suite/feature"] == 1
    assert budget.delivery_call_reserves["final_qa:run"] == 1
    assert sum(budget.delivery_reserves.values()) + budget.stage_headroom < 80000
    assert budget.max_calls == 24 and budget.max_tokens == 80000


@pytest.mark.asyncio
async def test_task_generation_and_review_share_headroom_but_keep_call_floors():
    service, record = await task_service()
    budget = service._run_llm_budget(record)
    for phase in ("writer:Example Suite/feature", "qa:Example Suite/feature"):
        assert budget.delivery_reserves[phase] == 0
        assert budget.delivery_call_reserves[phase] == 1
    assert budget.delivery_reserves["answer:Example Suite/feature"] == 20000
    assert budget.delivery_reserves["final_qa:run"] == 10000


@pytest.mark.asyncio
async def test_collector_real_request_envelopes_enter_without_spending_final_floors():
    service, record = await task_service()
    budget = service._run_llm_budget(record)
    requests = []

    async def post(url, payload, headers):
        requests.append(payload)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    service._llm._post_chat_completion = post
    # Anonymous sizes from first real Collector extract + question review.
    for name, input_tokens, output_limit in (
        ("collector_semantic_extract", 15177, 1600),
        ("collector_question_evidence_review", 13824, 700),
    ):
        system = "test"
        user = "x" * (input_tokens - len(system) - 2 - 256)
        await service._trace_llm_text(
            record,
            agent="collector",
            subagent="feature::Example Suite",
            name=name,
            system=system,
            user=user,
            max_output_tokens=output_limit,
        )
        span = record.detail.trace_spans[-1]
        assert span.metadata["llm_reserved_input_tokens"] == input_tokens
        assert span.metadata["llm_transport_attempts"] == 1
    assert len(requests) == 2
    assert budget.tokens_used == 31301 and budget.tokens_reserved == 0
    assert budget.delivery_reserves["answer:Example Suite/feature"] == 20000
    assert budget.delivery_reserves["final_qa:run"] == 10000


@pytest.mark.asyncio
async def test_reflector_twenty_k_envelope_enters_after_twenty_five_k_charged():
    service, record = await task_service()
    budget = service._run_llm_budget(record)
    for phase in list(budget.delivery_reserves):
        if phase.startswith(("collector:", "analyst:", "comparator:")):
            budget.finish_delivery(phase)
    prior = LLMCallExecution(
        budget, False, phase="analyst:Example Suite/feature", input_tokens=25000
    )
    prior.reserve()
    prior.settle()
    requests = []

    async def post(url, payload, headers):
        requests.append(payload)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    service._llm._post_chat_completion = post
    system = "test"
    user = "x" * (19447 - len(system) - 2 - 256)
    await service._trace_llm_text(
        record,
        agent="reflector",
        subagent=None,
        name="coverage_reflection",
        system=system,
        user=user,
    )
    assert len(requests) == 1
    assert record.detail.trace_spans[-1].metadata["llm_reserved_input_tokens"] == 19447
    assert budget.tokens_used == 46047 and budget.tokens_reserved == 0
    assert budget.protected_tokens("reflector:run") == 30000
    assert budget.delivery_reserves["answer:Example Suite/feature"] == 20000
    assert budget.delivery_reserves["final_qa:run"] == 10000


@pytest.mark.asyncio
async def test_real_admission_blocks_task_spending_and_admits_complete_final_payloads():
    from packages.agents.qa.question_reconciliation import SYSTEM

    service, record = await task_service()
    budget = service._run_llm_budget(record)
    for phase in list(budget.delivery_reserves):
        if not phase.startswith(("answer:", "final_qa:")):
            budget.finish_delivery(phase)
    # An anonymous task replay consumes all nonfinal token headroom.
    prior = LLMCallExecution(
        budget, False, input_tokens=50000, phase="writer:Example Suite/feature"
    )
    prior.reserve()
    prior.settle()
    requests = []

    async def post(url, payload, headers):
        requests.append(payload)
        # Missing usage must keep the complete byte-bound admission charge.
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    service._llm._post_chat_completion = post
    with pytest.raises(LLMExecutionLimitError, match="reserved_for_delivery"):
        await service._trace_llm_text(
            record,
            agent="writer",
            subagent="Example Suite/feature",
            name="dimension_task_generation",
            system="test",
            user="one more task",
        )
    assert not requests
    payload = json.dumps({"complete_exact_support": "x" * 13920})
    assert len(payload.encode()) <= 14000
    await service._trace_llm_text(
        record,
        agent="qa",
        subagent="Example Suite/feature",
        name="dimension_answer_review",
        system="s" * 1800,
        user=payload,
    )
    answer_span = record.detail.trace_spans[-1]
    assert answer_span.metadata["llm_phase"] == "answer:Example Suite/feature"
    assert answer_span.metadata["llm_transport_attempts"] == 1
    service._finish_delivery_phase(record, "answer", "Example Suite/feature")
    qa_payload = json.dumps({"complete_finding": "x" * 5900})
    assert len(qa_payload.encode()) <= 6000
    await service._trace_llm_text(
        record,
        agent="qa",
        subagent=None,
        name="final_question_reconciliation",
        system=SYSTEM,
        user=qa_payload,
    )
    assert len(requests) == 2
    assert record.detail.trace_spans[-1].metadata["llm_phase"] == "final_qa:run"
    assert budget.tokens_used <= 80000 and budget.tokens_reserved == 0
    assert budget.tokens_used > 50000 + 20000
    service._finish_delivery_phase(record, "final_qa", None)
    assert budget.protected_tokens(None) == 0


def test_multiple_reserved_calls_remain_protected_until_used_or_finished():
    budget = RunLLMBudget(
        5,
        1,
        max_tokens=1000,
        delivery_reserves={"answer:A/feature": 200, "final_qa:run": 100},
        delivery_call_reserves={"answer:A/feature": 2, "final_qa:run": 1},
    )
    first = LLMCallExecution(budget, False, phase="answer:A/feature", input_tokens=100)
    first.reserve()
    first.settle()
    assert budget.protected_calls(None) == 2
    budget.calls = 3
    with pytest.raises(LLMExecutionLimitError, match="reserved_for_delivery"):
        budget.reserve(is_repair=False)
    budget.reserve(is_repair=False, phase="answer:A/feature")
    assert budget.protected_calls(None) == 1
    budget.finish_delivery("final_qa:run")
    assert budget.protected_calls(None) == 0


@pytest.mark.asyncio
async def test_phase_routing_uses_names_only_for_new_profile():
    service, record = await task_service()
    phases = {
        "dimension_task_plan": ("writer", "Example Suite/feature", "writer:Example Suite/feature"),
        "dimension_task_generation": (
            "writer",
            "Example Suite/feature",
            "writer:Example Suite/feature",
        ),
        "dimension_task_review": ("qa", "Example Suite/feature", "qa:Example Suite/feature"),
        "dimension_answer_review": ("qa", "Example Suite/feature", "answer:Example Suite/feature"),
        "dimension_answer_coverage": (
            "writer",
            "Example Suite/feature",
            "writer:Example Suite/feature",
        ),
        "final_question_reconciliation": ("qa", None, "final_qa:run"),
    }
    for name, (agent, subagent, expected) in phases.items():
        assert service._llm_phase(agent, subagent, name=name, record=record) == expected
    object.__setattr__(service._settings, "writer_task_execution_enabled", False)
    assert (
        service._llm_phase(
            "qa", "Example Suite/feature", name="dimension_answer_review", record=record
        )
        == "qa:Example Suite/feature"
    )
    assert (
        service._llm_phase("qa", None, name="final_question_reconciliation", record=record) is None
    )


@pytest.mark.asyncio
async def test_task_profile_requires_real_explicit_scoped_feature_questions():
    service, record = await task_service(writer_task_execution_enabled=False)
    assert not any(
        p.startswith(("answer:", "final_qa:"))
        for p in service._run_llm_budget(record).delivery_reserves
    )
    object.__setattr__(service._settings, "writer_task_execution_enabled", True)
    record.llm_budget = None
    record.detail.plan.decision_brief = None
    record.detail.topic = "比较权限和评论操作"
    assert not any(
        p.startswith(("answer:", "final_qa:"))
        for p in service._run_llm_budget(record).delivery_reserves
    )
    record.llm_budget = None
    record.detail.plan.decision_brief = DecisionBrief(decision_question="Example Suite 能否评论？")
    record.detail.execution_mode = "demo"
    assert not service._run_llm_budget(record).delivery_reserves


@pytest.mark.asyncio
async def test_multi_product_floors_share_global_allocation():
    service, record = await task_service()
    one = service._run_llm_budget(record)
    record.llm_budget = None
    record.detail.plan.competitors = ["A", "B", "C", "D"]
    record.detail.plan.decision_brief = DecisionBrief(decision_question="能否让访客评论文档？")
    four = service._run_llm_budget(record)
    assert len([p for p in four.delivery_reserves if p.startswith("answer:")]) == 4
    assert sum(four.delivery_reserves.values()) <= sum(one.delivery_reserves.values())
    assert four.protected_calls(None) <= 24
    assert sum(four.delivery_reserves.values()) + four.stage_headroom < 80000


@pytest.mark.asyncio
async def test_checkpoint_replay_preserves_call_floors_unknown_charges_and_finished_answer():
    service, record = await task_service()
    budget = service._run_llm_budget(record)
    budget.delivery_call_reserves["writer:Example Suite/feature"] = 2
    call = LLMCallExecution(
        budget,
        False,
        phase="writer:Example Suite/feature",
        input_tokens=1000,
        max_output_tokens=1600,
    )
    call.checkpoint = lambda: service._checkpoint_llm_budget(record, budget)
    call.reserve()  # Crash before provider usage is known.
    service._finish_delivery_phase(record, "answer", "Example Suite/feature")
    protected, calls = budget.protected_tokens(None), budget.protected_calls(None)
    record.llm_budget = None
    restored = service._run_llm_budget(record)
    assert restored.tokens_used == 2600 and restored.tokens_reserved == 0
    assert restored.delivery_call_reserves["writer:Example Suite/feature"] == 2
    assert restored.delivery_calls["writer:Example Suite/feature"] == 1
    assert restored.protected_tokens(None) == protected
    assert restored.protected_calls(None) == calls
    assert "answer:Example Suite/feature" in restored.delivery_finished


@pytest.mark.asyncio
async def test_legacy_checkpoint_does_not_gain_final_call_floors():
    service, record = await task_service()
    record.detail.llm_budget_checkpoint = {
        "calls": 23,
        "repairs": 0,
        "tokens_charged": 75000,
        "cost_charged_usd": 0.01,
    }
    budget = service._run_llm_budget(record)
    assert budget.protected_tokens(None) <= 5000
    assert budget.protected_calls(None) <= 1


@pytest.mark.asyncio
async def test_checkpoint_preserves_explicit_call_floor_with_legacy_profile():
    service, record = await task_service(writer_task_execution_enabled=False)
    budget = service._run_llm_budget(record)
    budget.delivery_call_reserves["writer:Example Suite/feature"] = 2
    call = LLMCallExecution(budget, False, phase="writer:Example Suite/feature", input_tokens=100)
    call.reserve()
    call.settle()
    service._checkpoint_llm_budget(record, budget)
    protected = budget.protected_calls(None)
    record.llm_budget = None
    restored = service._run_llm_budget(record)
    assert restored.protected_calls(None) == protected
    assert restored.delivery_call_reserves["writer:Example Suite/feature"] == 2


@pytest.mark.asyncio
async def test_pending_unknown_task_charge_cannot_consume_final_floors():
    service, record = await task_service()
    budget = service._run_llm_budget(record)
    for phase in list(budget.delivery_reserves):
        if not phase.startswith(("answer:", "final_qa:")):
            budget.finish_delivery(phase)
    first = LLMCallExecution(
        budget, False, input_tokens=50000, phase="writer:Example Suite/feature"
    )
    first.reserve()
    blocked = LLMCallExecution(budget, False, input_tokens=1, phase="writer:Example Suite/feature")
    waiting = asyncio.create_task(service._admit_llm_call(blocked))
    await asyncio.sleep(0)
    assert not waiting.done()
    first.settle()
    with pytest.raises(LLMExecutionLimitError, match="reserved_for_delivery"):
        await waiting
    assert budget.tokens_used == 50000 and budget.calls == 1
    assert budget.protected_tokens("writer:Example Suite/feature") == 30000


@pytest.mark.asyncio
@pytest.mark.parametrize("settled", [False, True], ids=["crash_in_flight", "unknown_settled"])
@pytest.mark.parametrize(
    "qa_floor", [10000, 18000], ids=["six_k_window", "prior_fourteen_k_checkpoint"]
)
async def test_critical_checkpoint_keeps_final_floors_and_task_refusal(settled, qa_floor):
    service, record = await task_service()
    budget = service._run_llm_budget(record)
    for phase in list(budget.delivery_reserves):
        if not phase.startswith(("answer:", "final_qa:")):
            budget.finish_delivery(phase)
    budget.delivery_reserves["final_qa:run"] = qa_floor
    prior_tokens = 80000 - 20000 - qa_floor
    task = LLMCallExecution(
        budget, False, phase="writer:Example Suite/feature", input_tokens=prior_tokens
    )
    task.checkpoint = lambda: service._checkpoint_llm_budget(record, budget)
    task.reserve()
    if settled:
        task.settle()
    with pytest.raises(LLMExecutionLimitError, match="reserved_for_delivery"):
        budget.reserve(is_repair=False, phase="writer:Example Suite/feature", input_tokens=10000)
    record.llm_budget = None
    restored = service._run_llm_budget(record)
    assert restored.tokens_used == prior_tokens and restored.tokens_reserved == 0
    assert restored.delivery_reserves["answer:Example Suite/feature"] == 20000
    assert restored.delivery_reserves["final_qa:run"] == qa_floor
    assert restored.protected_tokens("writer:Example Suite/feature") == 20000 + qa_floor
    with pytest.raises(LLMExecutionLimitError, match="reserved_for_delivery"):
        restored.reserve(is_repair=False, phase="writer:Example Suite/feature", input_tokens=10000)
    answer = LLMCallExecution(
        restored,
        False,
        phase="answer:Example Suite/feature",
        input_tokens=16000,
        max_output_tokens=1600,
    )
    answer.reserve()
    answer.settle()
    service._finish_delivery_phase(record, "answer", "Example Suite/feature")
    final_qa = LLMCallExecution(
        restored, False, phase="final_qa:run", input_tokens=qa_floor - 2000, max_output_tokens=1600
    )
    final_qa.reserve()
    final_qa.settle()
    assert restored.tokens_used == 77200 and restored.max_tokens == 80000


@pytest.mark.asyncio
@pytest.mark.parametrize("restart", [False, True], ids=["live_new_scope", "restore_new_scope"])
async def test_new_scope_can_only_reserve_capacity_after_persisted_final_floors(restart):
    service, record = await task_service()
    record.detail.plan.decision_brief = DecisionBrief(decision_question="能否让访客评论文档？")
    budget = service._run_llm_budget(record)
    for phase in list(budget.delivery_reserves):
        if not phase.startswith(("answer:", "final_qa:")):
            budget.finish_delivery(phase)
    task = LLMCallExecution(budget, False, phase="writer:Example Suite/feature", input_tokens=50000)
    task.checkpoint = lambda: service._checkpoint_llm_budget(record, budget)
    task.reserve()
    task.settle()
    record.detail.plan.competitors.append("Another Suite")
    if restart:
        record.llm_budget = None
    expanded = service._run_llm_budget(record)
    assert expanded.delivery_reserves["answer:Example Suite/feature"] == 20000
    assert expanded.delivery_reserves["final_qa:run"] == 10000
    remaining = sum(
        max(0, amount - expanded.delivery_charged.get(phase, 0))
        for phase, amount in expanded.delivery_reserves.items()
        if phase not in expanded.delivery_finished
    )
    assert remaining == 30000
    assert expanded.tokens_used == 50000 and expanded.max_tokens == 80000
