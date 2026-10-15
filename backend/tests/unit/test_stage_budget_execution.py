"""Stage admission replay uses the real provider adapter with offline transport."""
import asyncio
import json
from datetime import UTC, datetime

import httpx
import pytest

from packages.memory import KBCache
from packages.llm.errors import LLMExecutionLimitError

from packages.llm.execution_budget import LLMCallExecution
from packages.schema.models import RawSource
from test_execution_limits import _service


async def stage_service():
    service, record = await _service(run_llm_max_tokens=200000, run_llm_max_calls=60,
        analyst_react_enabled=False, llm_max_retries=0)
    service._kb_cache = KBCache.in_memory()
    detail = record.detail
    detail.topic = '比较四家产品的访客权限、评论与编辑操作'
    detail.plan.topic = detail.topic
    detail.plan.research_depth = 'standard'
    detail.plan.dimensions = ['feature']
    detail.plan.competitors = ['Notion', 'Confluence', 'Coda', 'Nuclino']
    now = datetime.now(UTC)
    for product in ['Notion', 'Confluence', 'Nuclino']:
        quote = 'Guests can comment on a document only after access to its parent page is granted on the Team plan.'
        detail.raw_sources.append(RawSource(id=f'source-{product}', competitor=product,
            dimension='feature', source_type='official_docs', title=f'{product} permissions',
            url=f'https://{product.lower()}.example/permissions', snippet=quote,
            content_hash=f'hash-{product}', confidence=.95, extracted_at=now,
            metadata={'last_verified_at': now.isoformat(), 'normalized_fields': [
                {'kind':'feature', 'competitor': product, 'dimension':'feature',
                 'feature_name': f'Document comments {i}', 'slot': f'comments.{i}',
                 'support_level': True, 'evidence_terms': [quote], 'evidence_quote': quote,
                 'confidence': .95, 'qualifiers': {'role':'guest','plan':'Team',
                    'operation_object':'document','prerequisites':[quote]}}
                for i in range(12)]}))
    return service, record


def provider(service):
    requests = []
    async def post(url, payload, headers):
        user = payload['messages'][1]['content']
        requests.append(user)
        if 'Competitor: ' in user:
            product = user.split('Competitor: ')[1].splitlines()[0]
            content = {'feature_tree': {'summary_claims': [{'claim': f'{product} has conditional document comments',
                'source_ids': [f'source-{product}'], 'confidence': .9}]}}
        elif 'Comparison Matrix JSON:' in user:
            content = {'coverage_gaps': [], 'gate_status':'pass'}
        else:
            content = {'matrix_summary':['Compare the captured conditional permissions.'], 'winner_by_dimension':{}}
        return httpx.Response(200, json={'choices':[{'message':{'content':json.dumps(content)}}],
            'usage':{'prompt_tokens':800,'completion_tokens':100}})
    service._llm._post_chat_completion = post
    return requests


@pytest.mark.asyncio
async def test_four_product_core_stages_reach_transport_and_keep_delivery():
    service, record = await stage_service()
    requests = provider(service)
    # Replay costly acquisition before analysis without exceeding the unchanged cap.
    for index in range(4):
        await service._trace_llm_text(record, agent='collector', subagent=f'feature::{record.detail.plan.competitors[index]}',
            name='acquisition', system='test', user='x' * 25000)
    await asyncio.gather(*(service._real_analyst_branch_step(record, 'feature', p)
        for p in record.detail.plan.competitors))
    await service._real_comparator_step(record)
    await service._real_reflector_step(record)
    spans = record.detail.trace_spans
    for product in ['Notion','Confluence','Nuclino']:
        assert any(s.agent == 'analyst' and s.subagent == f'feature::{product}'
            and s.metadata.get('llm_transport_attempts', 0) > 0 for s in spans)
    for agent in ['comparator','reflector']:
        assert any(s.agent == agent and s.metadata.get('llm_transport_attempts', 0) > 0 for s in spans)
    skipped = [e for e in record.events if e.type == 'node_completed' and e.agent == 'analyst'
        and e.subagent == 'feature::Coda']
    assert skipped[-1].payload['module_status'] == 'skipped'
    b = service._run_llm_budget(record)
    for p in record.detail.plan.competitors:
        for agent in ['writer','qa']:
            c = LLMCallExecution(b, False, phase=f'{agent}:{p}/feature', input_tokens=16000, max_output_tokens=1600)
            c.reserve(); c.settle(prompt_tokens=4000, completion_tokens=600)
            service._finish_delivery_phase(record, agent, f'{p}/feature')
    assert len(requests) >= 9 and b.tokens_used <= 200000 and b.calls <= 60
    assert b.protected_tokens(None) == 0


@pytest.mark.asyncio
async def test_analyst_cache_and_skip_release_stage_allowance():
    service, record = await stage_service()
    provider(service)
    await service._real_analyst_branch_step(record, 'feature', 'Notion')
    await service._real_analyst_branch_step(record, 'feature', 'Notion')
    await service._real_analyst_branch_step(record, 'feature', 'Coda')
    b = service._run_llm_budget(record)
    events = [e for e in record.events if e.type == 'node_completed' and e.agent == 'analyst']
    assert [e.payload['module_status'] for e in events] == ['llm','cache','skipped']
    assert {'analyst:Notion/feature','analyst:Coda/feature'} <= b.delivery_finished


@pytest.mark.asyncio
async def test_local_comparator_budget_refusal_has_no_blind_retries():
    service, record = await stage_service()
    provider(service)
    b = service._run_llm_budget(record)
    b.calls = b.max_calls
    await service._real_comparator_step(record)
    spans = [s for s in record.detail.trace_spans if s.agent == 'comparator' and s.kind == 'llm']
    assert len(spans) == 1
    assert spans[0].metadata['llm_admission_status'] == 'rejected'
    assert spans[0].metadata['llm_transport_attempts'] == 0
    event = next(e for e in reversed(record.events) if e.type == 'node_completed' and e.agent == 'comparator')
    assert event.payload['module_status'] == 'fallback'
    assert event.payload['fallback']['reason'] == 'run_llm_call_budget_exhausted'


@pytest.mark.asyncio
async def test_invalid_successful_analyst_payload_is_visible_as_fallback():
    service, record = await stage_service()
    async def invalid(url, payload, headers):
        return httpx.Response(200, json={'choices':[{'message':{'content':'{}'}}],
            'usage':{'prompt_tokens':10,'completion_tokens':2}})
    service._llm._post_chat_completion = invalid
    await service._real_analyst_branch_step(record, 'feature', 'Notion')
    event = next(e for e in reversed(record.events) if e.type == 'node_completed' and e.agent == 'analyst')
    assert event.payload['module_status'] == 'fallback'
    assert event.payload['fallback']['used'] is True


@pytest.mark.asyncio
async def test_small_scope_has_room_for_its_first_transport():
    service, record = await stage_service()
    record.detail.plan.competitors = ['Notion']
    object.__setattr__(service._settings, "run_llm_max_calls", 8)
    object.__setattr__(service._settings, "run_llm_max_tokens", 2000)
    requests = provider(service)
    await service._trace_llm_text(record, agent='analyst', subagent='feature::Notion',
        name='feature_notion_analyst', system='test', user='small', max_output_tokens=128)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_acquisition_ceiling_keeps_v7_sized_analysis_transport_possible():
    service, record = await stage_service()
    requests = provider(service)
    b = service._run_llm_budget(record)
    for p in record.detail.plan.competitors:
        service._finish_delivery_phase(record, 'collector', f'{p}/feature')
    # Acquisition may spend the unprotected pool, but not the shared core envelope.
    ceiling = b.max_tokens - b.protected_tokens(None)
    b.tokens_used = ceiling
    assert ceiling == 68000
    with pytest.raises(LLMExecutionLimitError, match='reserved_for_delivery'):
        b.reserve(is_repair=False, input_tokens=1, phase='collector:Notion/feature')
    await asyncio.gather(*(service._real_analyst_branch_step(record, 'feature', p)
        for p in record.detail.plan.competitors))
    await service._real_comparator_step(record)
    await service._real_reflector_step(record)
    assert len(requests) == 5
    assert all(s.metadata['llm_transport_attempts'] == 1 for s in record.detail.trace_spans if s.kind == 'llm')
    assert b.tokens_used <= 200000 and b.calls == 5


@pytest.mark.asyncio
async def test_impossible_scope_reports_explicit_call_requirement():
    service, record = await stage_service()
    object.__setattr__(service._settings, 'run_llm_max_calls', 10)
    requests = provider(service)
    with pytest.raises(LLMExecutionLimitError, match='scope_budget_insufficient:required_calls=18,limit=10'):
        await service._trace_llm_text(record, agent='analyst', subagent='feature::Notion',
            name='first', system='test', user='test', max_output_tokens=128)
    assert not requests and record.llm_budget.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('limit', ['tokens', 'cost', 'calls'])
async def test_true_budget_failures_never_transport_and_are_visible(limit):
    service, record = await stage_service()
    b = service._run_llm_budget(record)
    if limit == 'tokens': b.tokens_used = b.max_tokens
    if limit == 'cost': b.max_cost_usd = .000001
    if limit == 'calls': b.calls = b.max_calls
    requests = provider(service)
    with pytest.raises(LLMExecutionLimitError):
        await service._trace_llm_text(record, agent='writer', subagent='Notion/feature',
            name='dimension_claim_writer', system='test', user='test', max_output_tokens=128)
    assert not requests
    metadata = record.detail.trace_spans[-1].metadata
    assert metadata['llm_transport_attempts'] == 0
    assert metadata['llm_admission_status'] == 'rejected'
    assert metadata['llm_tokens_charged'] == 0


@pytest.mark.asyncio
async def test_core_pending_checkpoint_restores_only_unspent_stage_floors():
    service, record = await stage_service()
    b = service._run_llm_budget(record)
    call = LLMCallExecution(b, False, input_tokens=10000, max_output_tokens=1000,
        phase='analyst:Notion/feature')
    call.checkpoint = lambda: service._checkpoint_llm_budget(record, b)
    call.reserve()
    service._finish_delivery_phase(record, 'analyst', 'feature::Coda')
    before = b.protected_tokens(None)
    record.llm_budget = None
    restored = service._run_llm_budget(record)
    assert restored.tokens_used == 11000 and restored.tokens_reserved == 0
    assert restored.protected_tokens(None) == before
    assert restored.delivery_charged['analyst:Notion/feature'] == 11000
    assert restored.delivery_calls['analyst:Notion/feature'] == 1
    assert 'analyst:Coda/feature' in restored.delivery_finished


@pytest.mark.asyncio
async def test_reflector_invalid_structure_is_fallback_after_successful_transport():
    service, record = await stage_service()
    async def invalid(url, payload, headers):
        return httpx.Response(200, json={'choices':[{'message':{'content':'{"gate_status":"invented"}'}}],
            'usage':{'prompt_tokens':10,'completion_tokens':2}})
    service._llm._post_chat_completion = invalid
    await service._real_reflector_step(record)
    event = next(e for e in reversed(record.events) if e.type == 'node_completed' and e.agent == 'reflector')
    assert event.payload['module_status'] == 'fallback'
    assert event.payload['fallback']['reason'] == 'invalid_structured_payload'
    llm_span = next(s for s in record.detail.trace_spans if s.kind == 'llm' and s.agent == 'reflector')
    assert llm_span.metadata['llm_transport_attempts'] == 1


@pytest.mark.asyncio
async def test_non_dimension_standard_scope_protects_core_and_legacy_writer():
    service, record = await _service(run_llm_max_tokens=200000, run_llm_max_calls=60)
    record.detail.plan.research_depth = 'standard'
    record.detail.plan.dimensions = ['pricing']
    record.detail.plan.competitors = ['A','B']
    b = service._run_llm_budget(record)
    assert {'analyst:A/pricing','analyst:B/pricing','comparator:run','reflector:run','writer:run'} <= b.delivery_reserves.keys()
    assert not any(p.startswith('qa:') for p in b.delivery_reserves)  # This path audits locally.
    requests = provider(service)
    await service._trace_llm_text(record, agent='analyst', subagent='pricing::A', name='pricing_a_analyst',
        system='test',user='test',max_output_tokens=128)
    for phase in list(b.delivery_reserves):
        if phase != 'writer:run': b.finish_delivery(phase)
    await service._trace_llm_text(record,agent='writer',subagent=None,name='report_writer',
        system='test',user='x'*25000,max_output_tokens=1600)
    assert len(requests) == 2
    assert record.detail.trace_spans[-1].metadata['llm_phase'] == 'writer:run'


@pytest.mark.asyncio
async def test_default_depth_real_pricing_cannot_spend_core_stage_allowances():
    service, record = await _service(run_llm_max_tokens=200000, run_llm_max_calls=60,
        llm_max_retries=0, analyst_react_enabled=False)
    assert record.detail.plan.research_depth is None
    quote = 'The Team plan costs 10 USD per user per month, billed monthly. Tax excluded.'
    record.detail.raw_sources.append(RawSource(id='official-A', competitor='A', dimension='pricing',
        source_type='official_docs', title='A pricing', url='https://a.example/pricing',
        snippet=quote, confidence=.95, content_hash='official-A-hash'))
    requests = []
    async def post(url, payload, headers):
        requests.append(payload['messages'][1]['content'])
        result = {'pricing_model': {'notes':[{'claim':quote,'source_ids':['official-A'],'confidence':.9}]}}
        return httpx.Response(200, json={'choices':[{'message':{'content':json.dumps(result)}}],
            'usage':{'prompt_tokens':800,'completion_tokens':100}})
    service._llm._post_chat_completion = post
    # The review probe spent 195100 tokens here and left the Analyst at transport 0.
    with pytest.raises(LLMExecutionLimitError, match='reserved_for_delivery'):
        await service._trace_llm_text(record, agent='collector', subagent='pricing::A',
            name='collection', system='test', user='x' * 195000)
    b = service._run_llm_budget(record)
    assert not requests and b.tokens_used == 0 and b.calls == 0
    assert {'collector:A/pricing','analyst:A/pricing','comparator:run','reflector:run','writer:run'} <= b.delivery_reserves.keys()
    await service._real_analyst_branch_step(record, 'pricing', 'A')
    span = next(s for s in record.detail.trace_spans if s.kind == 'llm' and s.agent == 'analyst')
    assert span.metadata['llm_transport_attempts'] == 1
    assert len(requests) == 1 and b.tokens_used == 900
    use = next(use for use in record.detail.evidence_consumptions if use.agent == 'analyst')
    assert use.max_bytes == 12000
    event = next(e for e in reversed(record.events) if e.type == 'node_completed' and e.agent == 'analyst')
    assert event.payload['module_status'] == 'llm'


@pytest.mark.asyncio
@pytest.mark.parametrize('depth', [None, 'standard'])
async def test_no_token_cap_keeps_legacy_non_dimension_budget_contract(depth):
    service, record = await _service(run_llm_max_tokens=0)
    record.detail.plan.research_depth = depth
    assert service._run_llm_budget(record).delivery_reserves == {}
