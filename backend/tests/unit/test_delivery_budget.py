import pytest
from packages.llm.errors import LLMExecutionLimitError
from packages.llm.execution_budget import LLMCallExecution, RunLLMBudget


def budget(**kwargs):
    return RunLLMBudget(max_calls=6, max_repairs=2, max_tokens=1000,
        delivery_reserves={'writer:A/feature': 200, 'qa:A/feature': 200}, **kwargs)


def test_upstream_cannot_take_delivery_tokens_or_calls():
    b = budget()
    with pytest.raises(LLMExecutionLimitError, match='reserved_for_delivery'):
        b.reserve(is_repair=False, input_tokens=601)
    b.reserve(is_repair=False, input_tokens=600)
    assert b.calls == 1
    b = budget(calls=4)
    with pytest.raises(LLMExecutionLimitError, match='reserved_for_delivery'):
        b.reserve(is_repair=False, input_tokens=1)


def test_delivery_uses_own_reserve_and_keeps_review_reserve():
    b = budget(tokens_used=600)
    call = LLMCallExecution(b, False, input_tokens=180, phase='writer:A/feature')
    call.reserve()
    call.settle(prompt_tokens=40, completion_tokens=10)
    assert b.protected_tokens(None) == 350
    b.finish_delivery('writer:A/feature')
    assert b.protected_tokens(None) == 200
    review = LLMCallExecution(b, False, input_tokens=350, phase='qa:A/feature')
    review.reserve()
    review.settle()
    b.finish_delivery('qa:A/feature')
    assert b.tokens_used == 1000 and b.tokens_reserved == 0


def test_unknown_usage_and_retry_do_not_hide_charges():
    b = budget(tokens_used=600)
    call = LLMCallExecution(b, False, input_tokens=150, phase='writer:A/feature')
    call.reserve(); call.reserve_transport()
    call.settle()
    with pytest.raises(LLMExecutionLimitError, match='reserved_for_delivery'):
        call.reserve_transport()
    assert b.tokens_used == 750 and b.calls == 1


def test_pending_other_call_counts_only_once_towards_protected_floor():
    b = budget()
    writer = LLMCallExecution(b, False, input_tokens=200, phase='writer:A/feature')
    writer.reserve()
    assert b.protected_tokens(None) == 200
    b.reserve(is_repair=False, input_tokens=600)
    assert b.tokens_reserved == 800
    writer.settle(prompt_tokens=30, completion_tokens=10)
    assert b.protected_tokens(None) == 360


def test_configured_cost_also_protects_delivery():
    b = budget(max_cost_usd=.0003)
    with pytest.raises(LLMExecutionLimitError, match='reserved_for_delivery'):
        b.reserve(is_repair=False, input_tokens=600)


def test_compact_writer_keeps_complete_scoped_evidence_and_restrictions():
    from types import SimpleNamespace
    from test_capability_alignment import fact
    from packages.agents.writer.dimension_writer import compact_dimension_context, review_payload
    from packages.research.evidence.report_claims import ReportClaim
    f = fact('Notion', 'Guests can edit documents only after access to the parent page is granted.', slot='edit')
    view = SimpleNamespace(facts=(f, f.model_copy(update={'id': 'slot-only', 'field': 'slot'})))
    selected = {'segment_competitor': 'Notion', 'dimension': 'feature', 'matrix': 'x' * 20000}
    payload, omitted = compact_dimension_context(selected, view, {f.id}, max_bytes=3000)
    assert payload['evidence_view']['facts'][0]['quote'] == f.quote
    assert 'matrix' not in payload and not omitted
    claim = ReportClaim(id='claim-test', text='访客获得父级页面访问后可编辑文档。', kind='fact',
        competitor='Notion', dimension='feature', fact_ids=[f.id], source_ids=[f.source_id])
    view.sources = ()
    assert [row['id'] for row in review_payload([claim], view)['facts']] == [f.id]
    payload, omitted = compact_dimension_context(selected, view, {f.id}, max_bytes=50)
    assert not payload['evidence_view']['facts'] and omitted


@pytest.mark.asyncio
async def test_delivery_checkpoint_restores_pending_charges_and_finished_phases():
    from test_execution_limits import _service
    service, record = await _service(run_llm_max_tokens=200000)
    record.detail.topic = '比较权限和评论操作'
    record.detail.plan.dimensions = ['feature']
    record.detail.plan.competitors = ['A', 'B']
    b = service._run_llm_budget(record)
    call = LLMCallExecution(b, False, input_tokens=1000, phase='writer:A/feature')
    call.checkpoint = lambda: service._checkpoint_llm_budget(record, b)
    call.reserve()
    service._finish_delivery_phase(record, 'writer', 'B/feature')
    protected = b.protected_tokens(None)
    record.llm_budget = None  # Process restart with outstanding transport unknown.
    restored = service._run_llm_budget(record)
    assert restored.tokens_used == 1000 and restored.tokens_reserved == 0
    assert restored.protected_tokens(None) == protected
    assert 'writer:B/feature' in restored.delivery_finished
    assert restored.delivery_calls['writer:A/feature'] == 1


@pytest.mark.asyncio
async def test_protected_search_skips_transport_and_keeps_writer_eligible(monkeypatch):
    from test_deepseek_search_runtime import make_service
    service, record = await make_service(run_llm_max_tokens=200000)
    record.detail.execution_mode = 'real'
    record.detail.topic = '比较权限操作'
    record.detail.plan.dimensions = ['feature']
    record.detail.plan.competitors = ['Notion', 'Confluence', 'Coda', 'Nuclino']
    b = service._run_llm_budget(record)
    b.tokens_used = 70000
    async def forbidden(*args, **kwargs):
        raise AssertionError('protected search must not start transport')
    monkeypatch.setattr(service._search, 'search', forbidden)
    assert await service._trace_search(record, agent='collector', subagent='Notion/feature',
                                          query='permissions', max_results=3) == []
    assert b.calls == 0 and b.tokens_used == 70000
    assert record.detail.trace_spans[-1].metadata['degradation_reason'] == 'run_llm_budget_reserved_for_delivery'
    for phase in list(b.delivery_reserves):
        if not phase.startswith(('writer:', 'qa:')):
            b.finish_delivery(phase)
    call = LLMCallExecution(b, False, input_tokens=12000, phase='writer:Notion/feature')
    call.reserve()


@pytest.mark.asyncio
async def test_target_product_is_protected_before_planner_adds_it_to_competitors():
    from test_execution_limits import _service
    from packages.schema.models import TargetProduct
    service, record = await _service(run_llm_max_tokens=200000)
    record.detail.topic = '权限比较'
    record.detail.plan.dimensions = ['feature']
    record.detail.plan.competitors = ['Confluence', 'Coda', 'Nuclino']
    record.detail.plan.target_product = TargetProduct(name='Notion')
    b = service._run_llm_budget(record)
    assert b.protected_tokens(None) == 152000 and b.protected_calls(None) == 18
    assert b.delivery_reserves['writer:Notion/feature'] == 8000
    record.detail.plan.competitors.insert(0, 'Notion')
    assert service._run_llm_budget(record) is b and len(b.delivery_reserves) == 18


@pytest.mark.asyncio
async def test_new_product_does_not_expand_total_allocation_above_policy():
    from test_execution_limits import _service
    service, record = await _service(run_llm_max_tokens=200000)
    record.detail.topic = '权限比较'
    record.detail.plan.dimensions = ['feature']
    record.detail.plan.competitors = ['A', 'B', 'C', 'D']
    b = service._run_llm_budget(record)
    record.detail.plan.competitors.append('E')
    assert service._run_llm_budget(record).protected_tokens(None) <= 160000
    assert len(b.delivery_reserves) == 22


@pytest.mark.asyncio
async def test_legacy_recovery_protects_only_actual_remaining_budget():
    from test_execution_limits import _service
    service, record = await _service(run_llm_max_tokens=200000)
    record.detail.topic = '权限比较'
    record.detail.plan.dimensions = ['feature']
    record.detail.plan.competitors = ['A', 'B', 'C', 'D']
    record.detail.llm_budget_checkpoint = dict(calls=10, repairs=0, tokens_charged=150000, cost_charged_usd=.05)
    record.llm_budget = None
    b = service._run_llm_budget(record)
    assert b.protected_tokens(None) <= 50000
    call = LLMCallExecution(b, False, input_tokens=2000, max_output_tokens=1600, phase='writer:A/feature')
    call.reserve()
    assert b.calls == 11
