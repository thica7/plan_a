import pytest

from packages.llm.errors import LLMExecutionLimitError
from packages.llm.execution_budget import LLMCallExecution, RunLLMBudget


def test_token_reservations_prevent_concurrent_overspend():
    budget = RunLLMBudget(max_calls=10, max_repairs=4, max_tokens=100)
    first = LLMCallExecution(budget, False, input_tokens=20, max_output_tokens=40)
    second = LLMCallExecution(budget, False, input_tokens=20, max_output_tokens=40)
    first.reserve()
    with pytest.raises(LLMExecutionLimitError, match='token_budget'):
        second.reserve()
    assert budget.calls == 1
    first.settle(prompt_tokens=20, completion_tokens=5, cache_hit_tokens=0)
    second.reserve()
    assert budget.tokens_used == 25
    assert budget.tokens_reserved == 60


def test_retry_without_usage_keeps_conservative_reservation():
    budget = RunLLMBudget(5, 3, max_tokens=130)
    call = LLMCallExecution(budget, False, input_tokens=20, max_output_tokens=40)
    call.reserve()
    call.reserve_transport()
    call.reserve_transport()
    call.settle(prompt_tokens=20, completion_tokens=5, cache_hit_tokens=0)
    assert budget.tokens_used == 85
    assert budget.tokens_reserved == 0
    assert call.metadata()['llm_tokens_charged'] == 85


def test_cost_budget_and_cache_usage_settlement():
    budget = RunLLMBudget(5, 3, max_cost_usd=0.001,
                          input_usd_per_million=2, output_usd_per_million=4,
                          cache_usd_per_million=0.02)
    call = LLMCallExecution(budget, False, input_tokens=100, max_output_tokens=100)
    call.reserve()
    call.settle(prompt_tokens=100, completion_tokens=10, cache_hit_tokens=80)
    assert budget.cost_used_usd == pytest.approx(0.0000816)
    assert budget.cost_reserved_usd == 0
    costly = LLMCallExecution(budget, False, input_tokens=1000, max_output_tokens=100)
    with pytest.raises(LLMExecutionLimitError, match='cost_budget'):
        costly.reserve()


def test_failed_or_cancelled_call_retains_unknown_usage_cost():
    budget = RunLLMBudget(3, 1, max_tokens=100)
    call = LLMCallExecution(budget, False, input_tokens=30, max_output_tokens=40)
    call.reserve()
    call.settle()
    call.settle()  # Idempotent finalizers cannot double count.
    assert budget.tokens_used == 70
    assert budget.tokens_reserved == 0


def test_usage_larger_than_estimate_is_counted_and_blocks_next_request():
    budget = RunLLMBudget(3, 1, max_tokens=100)
    call = LLMCallExecution(budget, False, input_tokens=10, max_output_tokens=20)
    call.reserve()
    call.settle(prompt_tokens=90, completion_tokens=20, cache_hit_tokens=0)
    with pytest.raises(LLMExecutionLimitError, match='token_budget'):
        LLMCallExecution(budget, False, input_tokens=1, max_output_tokens=1).reserve()
