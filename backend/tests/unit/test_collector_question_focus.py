import json

import pytest
from test_execution_limits import _service

from packages.agents import SubagentContext
from packages.research.models import CapturedPage, EvidenceItem, ResearchBrief
from packages.schema.models import DecisionBrief


@pytest.mark.asyncio
async def test_collector_receives_scoped_questions_as_request_data():
    service, record = await _service()
    detail = record.detail
    detail.plan.competitors = ['Example Suite', 'Other Suite']
    detail.topic = '权限研究'
    detail.plan.decision_brief = DecisionBrief(decision_question=(
        'Example Suite Guest 需要登录吗？\nOther Suite Starter 支持聊天侧栏吗？'))
    brief = service._research_brief(detail, 'Example Suite', 'feature')
    assert len(brief.questions) == 1
    assert brief.questions[0].question == 'Example Suite Guest 需要登录吗？'
    assert brief.topic == '权限研究'


def brief():
    return ResearchBrief(run_id='unit', topic='权限研究', competitor='Example Suite',
        dimension='feature', product_name='Example Suite', questions=[
            dict(question_id='q-login', question='Example Suite Guest 需要登录吗？'),
            dict(question_id='q-plan', question='Example Suite Starter 支持聊天侧栏吗？')])


def page():
    return CapturedPage(candidate_id='original', requested_url='https://example.invalid/help',
        final_url='https://example.invalid/help', status='ok', title='Example Suite guide',
        text='Members must sign in before accessing documents.', content_hash='original', quality_score=1)


@pytest.mark.asyncio
async def test_same_body_different_focus_is_not_served_from_the_old_cache(monkeypatch):
    service, record = await _service()
    context = SubagentContext(run_id=record.detail.id, agent='collector', subagent='feature::Example Suite')
    monkeypatch.setattr('packages.agents.collectors.logic.semantic_page_allowed', lambda *_: True)
    calls = []

    async def model(_record, **kwargs):
        calls.append(json.loads(kwargs['user']))
        return {'facts': []}

    monkeypatch.setattr(service, '_trace_llm_json', model)
    first = brief().model_copy(update={'metadata': {'active_question_ids': ['q-login']}})
    second = brief().model_copy(update={'metadata': {'active_question_ids': ['q-plan']}})
    await service._collector_semantic_extract(record, first, page(), context)
    await service._collector_semantic_extract(record, second, page(), context)
    await service._collector_semantic_extract(record, second, page(), context)
    assert len(calls) == 2
    assert calls[0]['research_focus']['questions'][0]['question_id'] == 'q-login'
    assert calls[1]['research_focus']['questions'][0]['question_id'] == 'q-plan'


@pytest.mark.asyncio
async def test_question_review_only_routes_admitted_observations_and_has_a_small_output_cap(monkeypatch):
    service, record = await _service()
    context = SubagentContext(run_id=record.detail.id, agent='collector', subagent='feature::Example Suite')
    accepted = EvidenceItem(id='accepted', competitor='Example Suite', dimension='feature',
        source_candidate_id='candidate', captured_page_id='page', field='semantic_capability_1',
        value={'status': 'documented', 'evidence_terms': ['Guests must sign in.']},
        quote='Guests must sign in.', status='accepted')
    rejected = accepted.model_copy(update={'id': 'rejected', 'status': 'rejected'})
    calls = []

    async def model(_record, **kwargs):
        calls.append(kwargs)
        return {'questions': []}

    monkeypatch.setattr(service, '_trace_llm_json', model)
    await service._collector_question_review(record, brief(), [accepted, rejected], context)
    payload = json.loads(calls[0]['user'])
    assert {item['id'] for item in payload['evidence']} == {'accepted'}
    assert calls[0]['max_output_tokens'] <= 700
    assert record.detail.raw_sources == []


@pytest.mark.asyncio
async def test_question_review_preserves_capacity_stop_when_whole_evidence_cannot_fit(monkeypatch):
    service, record = await _service()
    context = SubagentContext(run_id=record.detail.id, agent='collector', subagent='feature::Example Suite')
    accepted = EvidenceItem(id='large', competitor='Example Suite', dimension='feature',
        source_candidate_id='candidate', captured_page_id='page', field='evidence_terms',
        value=['Guests must sign in. ' * 800], quote='Guests must sign in. ' * 800,
        status='accepted')

    async def unexpected_model(*args, **kwargs):
        pytest.fail('An empty capacity-limited payload must not call the model')

    monkeypatch.setattr(service, '_trace_llm_json', unexpected_model)
    assessment = await service._collector_question_review(record, brief(), [accepted], context)
    assert assessment['_question_stop_reason'] == 'capacity_exceeded'
    assert assessment['_question_review_metadata']['eligible_evidence_count'] == 1
    assert assessment['_question_review_metadata']['omitted_evidence_count'] == 1
    assert all(row['status'] == 'unverified' for row in assessment['questions'])


@pytest.mark.asyncio
async def test_question_review_propagates_evidence_dependency_rejection(monkeypatch):
    from packages.orchestrator.evidence_context import EvidenceUseRejectedError

    service, record = await _service()
    context = SubagentContext(run_id=record.detail.id, agent='collector', subagent='feature::Example Suite')
    accepted = EvidenceItem(id='accepted', competitor='Example Suite', dimension='feature',
        source_candidate_id='candidate', captured_page_id='page', field='evidence_terms',
        value=['Guests must sign in.'], quote='Guests must sign in.', status='accepted')

    async def rejected_model(*args, **kwargs):
        raise EvidenceUseRejectedError('Original source dependency is no longer current.')

    monkeypatch.setattr(service, '_trace_llm_json', rejected_model)
    with pytest.raises(EvidenceUseRejectedError):
        await service._collector_question_review(record, brief(), [accepted], context)


@pytest.mark.asyncio
async def test_question_review_does_not_claim_absence_when_some_originals_were_omitted(monkeypatch):
    service, record = await _service()
    context = SubagentContext(run_id=record.detail.id, agent='collector', subagent='feature::Example Suite')
    small = EvidenceItem(id='small', competitor='Example Suite', dimension='feature',
        source_candidate_id='candidate', captured_page_id='page', field='evidence_terms',
        value=['Owners can rename a board.'], quote='Owners can rename a board.', status='accepted')
    large = small.model_copy(update={'id': 'large', 'quote': 'Guests must sign in. ' * 800,
                                   'value': ['Guests must sign in. ' * 800]})

    async def model(*args, **kwargs):
        return {'questions': [dict(question_id=question.question_id, status='missing',
            evidence_ids=[], missing_fields=['role'], reason='No role evidence is provided.')
            for question in brief().questions]}

    monkeypatch.setattr(service, '_trace_llm_json', model)
    assessment = await service._collector_question_review(record, brief(), [small, large], context)
    assert assessment['_question_review_metadata']['omitted_evidence_count'] == 1
    assert assessment['_question_stop_reason'] == 'capacity_exceeded'
    assert all(row['status'] == 'unverified' and 'review_capacity' in row['missing_fields']
               for row in assessment['questions'])


@pytest.mark.asyncio
async def test_question_semantic_extraction_propagates_evidence_dependency_rejection(monkeypatch):
    from packages.orchestrator.evidence_context import EvidenceUseRejectedError

    service, record = await _service()
    context = SubagentContext(run_id=record.detail.id, agent='collector', subagent='feature::Example Suite')
    monkeypatch.setattr('packages.agents.collectors.logic.semantic_page_allowed', lambda *_: True)

    async def rejected_model(*args, **kwargs):
        raise EvidenceUseRejectedError('Original source dependency is no longer current.')

    monkeypatch.setattr(service, '_trace_llm_json', rejected_model)
    with pytest.raises(EvidenceUseRejectedError):
        await service._collector_semantic_extract(record, brief(), page(), context)
