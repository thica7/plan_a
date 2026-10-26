"""Formatting-only witness recovery and local single-reference choices."""

import json
from types import SimpleNamespace

import pytest
from claim_review_fixture import supported_review
from test_atomic_claim_review import selected_payload
from test_question_atomic_delivery import atomic_case


def test_v2_remains_exact_and_v3_recovers_only_whitespace_witness():
    from packages.agents.writer.question_atomic_delivery import parse_atomic_reviews

    original = 'Observers may\u00a0download attachments after approval.'
    payload = selected_payload([original])
    row = supported_review(payload['claims'][0])
    row['support_witnesses'] = [{'support_index': 0, 'quote': original.replace('\u00a0', ' ')}]
    response = json.dumps({'reviews': [row]})
    claim = SimpleNamespace(id='download')
    assert parse_atomic_reviews(
        response, [claim], payload=payload, review_projection_version=2
    ) == []
    payload['review_projection_version'] = 3
    assert len(parse_atomic_reviews(
        response, [claim], payload=payload, review_projection_version=3
    )) == 1
    assert json.loads(response)['reviews'][0]['support_witnesses'][0]['quote'] != original


@pytest.mark.parametrize('selected,witness', [
    ('may\u00a0download may\tdownload', 'may download'),
    ('may\u00a0download', 'MAY download'),
    ('may\u00a0download.', 'may download!'),
    ('may not\u00a0download', 'may download'),
    ('download\u00a0after approval', 'download before approval'),
    ('download\u00a0after approval', 'downloadafter approval'),
])
def test_v3_cannot_restore_ambiguous_or_non_whitespace_change(selected, witness):
    from packages.agents.writer.question_atomic_delivery import parse_atomic_reviews

    payload = selected_payload([selected])
    payload['review_projection_version'] = 3
    row = supported_review(payload['claims'][0])
    row['support_witnesses'] = [{'support_index': 0, 'quote': witness}]
    assert parse_atomic_reviews(json.dumps({'reviews': [row]}), [SimpleNamespace(id='download')],
                                payload=payload, review_projection_version=3) == []


@pytest.mark.asyncio
async def test_actual_v3_preserves_model_response_and_authenticates_restoration(monkeypatch):
    from test_question_atomic_delivery import atomic_model

    from packages.agents.writer import question_atomic_delivery as atomic

    case = await atomic_case(['Guests require\u00a0an account invitation.'],
                             question='Example Product: Do guests require an account invitation?')
    service, record, snapshot, selected, view, use, packets, boundaries, allowed = case
    normal = atomic_model(service, {})
    raw_reviews = []

    async def model(record, **kwargs):
        response = await normal(record, **kwargs)
        if kwargs['name'] == atomic.REVIEW_NAME:
            raw = json.loads(response)
            raw['reviews'][0]['support_witnesses'][0]['quote'] = (
                raw['reviews'][0]['support_witnesses'][0]['quote'].replace('\u00a0', ' ')
            )
            response = json.dumps(raw)
            record.detail.trace_spans[-1].full_output = response
            raw_reviews.append(response)
        return response

    monkeypatch.setattr(service, '_trace_llm_text', model)
    result = await atomic.execute_question_atomic_delivery(service, record, selected, view, use,
                       packets[0]['questions'], packets, allowed, boundaries, ())
    assert len(result['reviews']) == 1
    assert result['compact']['review_projection_version'] == 3
    receipt_span = next(
        s for s in record.detail.trace_spans if s.name == 'question_atomic_delivery'
    )
    receipt = json.loads(receipt_span.full_output)
    dispatch = next(d for d in receipt['dispatches'] if d['name'] == atomic.REVIEW_NAME)
    span = next(s for s in record.detail.trace_spans if s.id == dispatch['span_id'])
    assert span.full_output == raw_reviews[0]
    restoration = dispatch['support_witness_restorations'][0]
    assert restoration['quote'] == 'Guests require\u00a0an account invitation.'
    assert restoration['model_quote'] == 'Guests require an account invitation.'
    assert len(restoration['selected_support_sha256']) == 64
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    assert (
        atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view)['reviews']
        == result['reviews']
    )
    dispatch['support_witness_restorations'][0]['quote'] = 'Guests may bypass invitations.'
    receipt_span.full_output = json.dumps(receipt)
    with pytest.raises((ValueError, RuntimeError)):
        atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view)


def test_same_quote_different_facts_remain_separate_single_reference_options():
    from packages.agents.writer.readable_support import single_reference_tasks

    quote = 'Observers may download attachments after approval.'
    payload = {'evidence_view': {'facts': [
        {'id': 'first', 'value': [quote], 'qualifiers': {'plan': 'Premium'},
         'source_span_candidates': [{'support_ref': 's12', 'quote': quote}]},
        {'id': 'second', 'value': [quote, 'different context'],
         'qualifiers': {'plan': 'Enterprise'},
         'source_span_candidates': [{'support_ref': 's7', 'quote': quote}]},
    ]}, 'generation_tasks': [{'task_id': 't', 'support_refs': ['s12', 's7']}]}
    projected = single_reference_tasks(payload)
    assert projected['generation_tasks'][0]['support_refs'] == ['s12', 's7']
    assert projected['generation_tasks'][0]['support_ref_options'] == [['s12'], ['s7']]
    assert projected['evidence_view'] == payload['evidence_view']
    assert payload['generation_tasks'][0]['support_refs'] == ['s12', 's7']


@pytest.mark.asyncio
@pytest.mark.parametrize('multiple', [False, True])
@pytest.mark.parametrize('version', [2, 3])
async def test_actual_single_ref_choices_keep_facts_separate_and_multi_ref_rejected(
        monkeypatch, multiple, version):
    from claim_review_fixture import expand_prompt_payload, question_plan_response
    from test_question_atomic_delivery import supported_review as review_row
    from test_task_support_selection import append_response

    from packages.agents.writer import question_atomic_delivery as atomic

    quote = 'Observers may\u00a0vote on cards if voting is enabled for the board.'
    case = await atomic_case(
        [quote, quote], question='Example Product: May Observers vote on cards?',
        source_qualifiers=[{'plan': 'Premium'}, {'plan': 'Enterprise'}],
    )
    service, record, snapshot, selected, view, use, packets, boundaries, allowed = case
    seen = []

    async def model(record, **kwargs):
        body = expand_prompt_payload(json.loads(kwargs['user'].split('\nJSON:\n', 1)[1]))
        if kwargs['name'] == atomic.GENERATION_NAME:
            seen.append(body)
            refs = [span['support_ref'] for fact in body['evidence_view']['facts']
                    for span in fact['source_span_candidates'] if span['quote'] == quote]
            assert len(refs) == 2
            if version == 3:
                assert kwargs['system'].startswith('Server current-question atomic generation v3.')
                task = body['generation_tasks'][0]
                assert all(len(option) == 1 for option in task['support_ref_options'])
            response = question_plan_response(body, [dict(text=quote.replace('\u00a0', ' '),
                                  kind='fact', support_refs=refs if multiple else refs[:1])])
        else:
            assert kwargs['name'] == atomic.REVIEW_NAME
            row = review_row(body['claims'][0])
            row['support_witnesses'][0]['quote'] = quote.replace('\u00a0', ' ')
            response = json.dumps({'reviews': [row]})
        return append_response(service, record, kwargs, response)

    monkeypatch.setattr(service, '_trace_llm_text', model)
    result = await atomic.execute_question_atomic_delivery(service, record, selected, view, use,
                    packets[0]['questions'], packets, allowed, boundaries, (),
                    review_projection_version=version, generation_projection_version=version)
    assert len(result['claims']) == int(not multiple)
    assert len(result['reviews']) == int(not multiple and version == 3)
    assert len(seen[0]['evidence_view']['facts']) == 2
    assert {fact['qualifiers']['plan'] for fact in seen[0]['evidence_view']['facts']} == {
        'Premium', 'Enterprise',
    }
    if not multiple:
        assert len(result['claims'][0].fact_ids) == 1
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    replay = atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view)
    assert replay['reviews'] == result['reviews']


@pytest.mark.parametrize('tail', [
    'After confirmation, you can',
    'Once approved, they may.',
    'Approval is required. Users can not',
    '经确认后，你可以',
])
def test_v3_does_not_offer_dangling_modal_but_keeps_complete_original(tail):
    from packages.agents.writer.readable_support import single_reference_tasks

    complete = 'After confirmation, you can add a vault.'
    payload = {'generation_projection_version': 2, 'evidence_view': {'facts': [
        {'id': 'first', 'quote': tail, 'value': [tail], 'qualifiers': {},
         'source_span_candidates': [{'support_ref': 's1', 'quote': tail},
                                    {'support_ref': 's2', 'quote': complete}]},
    ]}, 'generation_tasks': [{'task_id': 't', 'state': 'planned', 'support_refs': ['s1', 's2']}]}
    projected = single_reference_tasks(payload)
    assert projected['evidence_view']['facts'][0]['source_span_candidates'] == [
        {'support_ref': 's2', 'quote': complete}]
    assert projected['generation_tasks'][0]['support_refs'] == ['s2']
    assert payload['generation_projection_version'] == 2
    assert len(payload['evidence_view']['facts'][0]['source_span_candidates']) == 2


def test_fenced_model_json_keeps_the_same_verifiable_restoration():
    from packages.agents.writer.atomic_claim_review import review_witness_restorations

    payload = selected_payload(['Guests require\u00a0approval.'])
    row = supported_review(payload['claims'][0])
    row['support_witnesses'] = [{'support_index': 0, 'quote': 'Guests require approval.'}]
    response = json.dumps({'reviews': [row]})
    expected = review_witness_restorations(response, payload)
    assert expected
    assert review_witness_restorations('```json\n' + response + '\n```', payload) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['delete', 'downgrade', 'downgrade_identity'])
async def test_v3_review_version_cannot_be_removed_when_no_claim_reaches_review(
        monkeypatch, change):
    from claim_review_fixture import expand_prompt_payload, question_plan_response
    from test_task_support_selection import append_response

    from packages.agents.writer import question_atomic_delivery as atomic

    case = await atomic_case(['Guests have no personal area.'])
    service, record, snapshot, selected, view, use, packets, boundaries, allowed = case

    async def model(record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs['user'].split('\nJSON:\n', 1)[1]))
        return append_response(service, record, kwargs, question_plan_response(payload, []))

    monkeypatch.setattr(service, '_trace_llm_text', model)
    result = await atomic.execute_question_atomic_delivery(service, record, selected, view, use,
                       packets[0]['questions'], packets, allowed, boundaries, ())
    assert not result['claims'] and not result['reviews']
    receipt_span = next(
        s for s in record.detail.trace_spans if s.name == 'question_atomic_delivery'
    )
    receipt = json.loads(receipt_span.full_output)
    if change == 'delete':
        receipt.pop('review_projection_version')
    else:
        receipt['review_projection_version'] = 2
        if change == 'downgrade_identity':
            receipt['projection_identity'] = 'atomic-generation-v3-review-v2'
    receipt_span.full_output = json.dumps(receipt)
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    with pytest.raises((ValueError, RuntimeError)):
        atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view)


def test_v3_cannot_restore_when_whitespace_matches_overlap():
    from packages.agents.writer.atomic_claim_review import restored_support_witness

    restored, receipt = restored_support_witness(
        {'support_index': 0, 'quote': 'may may'}, ['may\u00a0may\u00a0may'])
    assert restored is None and receipt is None


@pytest.mark.parametrize('text,incomplete', [
    ('Observers may.', True),
    ('Approved board reviewers may', True),
    ('Updated in May.', False),
    ('This change took effect on 15 May.', False),
])
def test_v3_dangling_may_is_not_limited_to_subject_whitelist_or_confused_with_month(
        text, incomplete):
    from packages.agents.writer.readable_support import single_reference_tasks

    payload = {'evidence_view': {'facts': [{'id': 'f', 'source_span_candidates': [
        {'support_ref': 's1', 'quote': text}]}]},
        'generation_tasks': [{'task_id': 't', 'state': 'planned', 'support_refs': ['s1']}]}
    projected = single_reference_tasks(payload)
    assert bool(projected['evidence_view']['facts'][0]['source_span_candidates']) is not incomplete
    assert len(payload['evidence_view']['facts'][0]['source_span_candidates']) == 1


@pytest.mark.asyncio
async def test_v3_single_ref_hint_does_not_push_complete_core_payload_over_window():
    from packages.agents.writer.dimension_writer import compact_prompt_json
    from packages.agents.writer.question_atomic_delivery import atomic_question_context

    text = 'Guests require an invitation. Supporting context ' + ('x' * 5660) + '.'
    case = await atomic_case([text], question='Example Product: Do guests require an invitation?')
    service, record, _, _, view, use, packets, _, allowed = case
    args = (service, record, view, packets, packets[0]['questions'][0], allowed, use)
    legacy = atomic_question_context(*args, generation_projection_version=2)
    current = atomic_question_context(*args, generation_projection_version=3)
    legacy_bytes = len(('\nJSON:\n' + compact_prompt_json(legacy)).encode())
    current_bytes = len(('\nJSON:\n' + compact_prompt_json(current)).encode())
    assert legacy_bytes <= min(14000, use.max_bytes)
    assert current_bytes <= min(14000, use.max_bytes), (legacy_bytes, current_bytes)
    assert current['evidence_view']['facts'] == legacy['evidence_view']['facts']
    assert not current['missing_core_fact_ids']
