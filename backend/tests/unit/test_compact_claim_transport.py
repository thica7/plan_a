"""Short Writer references are transport only; model stubs do not prove accuracy."""

import asyncio
import copy
import json
from claim_review_fixture import answer_response
from types import SimpleNamespace

import pytest
from claim_review_fixture import expand_prompt_payload, supported_review
from test_literal_non_operation import candidates, draft, fact
from test_source_span_binding import spans

from packages.agents.writer import dimension_writer as writer


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    import socket
    def denied(*args, **kwargs):
        raise AssertionError('Network is forbidden in compact Writer transport tests')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)
    monkeypatch.setattr('packages.agents.writer.question_retrieval.get_local_provider_from_env', lambda *_: None)


def context(originals, *, questions=None, max_bytes=14000):
    questions = questions or [dict(question_id='q', question='Who owns collections?')]
    selected = dict(segment_competitor='Example Product', dimension='feature')
    payload, omitted = writer.compact_dimension_context(selected, SimpleNamespace(facts=originals),
        {row.id for row in originals}, questions=questions, max_bytes=max_bytes)
    return payload, omitted


def parse(payload, atoms, originals, *, questions=None):
    questions = questions or [dict(question_id='q', question='Who owns collections?')]
    rows = payload['evidence_view']['facts']
    ops = {op['observation_id']: {k: v for k, v in op.items() if k != 'support_ref'}
           for row in rows for op in row.get('operation_observations', [])}
    sent = {row['id'] for row in rows}
    from packages.agents.writer.readable_support import dispatched_span_candidates
    choices = dispatched_span_candidates(payload, originals, sent)
    assert hasattr(writer, '_support_ref_catalog'), 'Writer needs a catalog from its actual prompt'
    refs = writer._support_ref_catalog(payload, originals, sent)
    plans = atoms if isinstance(atoms, list) and atoms and 'question_id' in atoms[0] else [
        dict(question_id='q', atoms=atoms, missing_fields=[])]
    return writer.parse_question_claim_plans(json.dumps({'question_plans': plans}), questions, ops,
        sent, 'current-use', source_facts=originals, span_candidates=choices, support_refs=refs)


def span_atom(row, text):
    span = next(candidate for candidate in row['source_span_candidates']
                if candidate['quote'] == row['quote'])
    assert 'support_ref' in span, 'Actual sent source spans need short references'
    return dict(text=text, kind='fact', support_refs=[span['support_ref']])


def test_compact_non_operation_round_trip_keeps_exact_original_binding():
    original = fact(quote='Organizations own all collections.')
    payload, _ = context([original])
    atom = span_atom(payload['evidence_view']['facts'][0], original.quote)
    claims, gaps, plans = parse(payload, [atom], [original])
    assert len(claims) == 1 and not gaps
    claim = claims[0]
    assert list(claim.fact_ids) == [original.id] and list(claim.source_ids) == [original.source_id]
    assert claim.source_span_bindings[0].model_dump(mode='json') == spans(original)[0]
    assert plans[0]['claim_ids'] == [claim.id]
    assert 'support_ref' not in claim.model_dump_json()


def test_compact_operation_round_trip_strips_transport_annotation():
    original = fact(quote='Members can edit documents after accepting the invitation.')
    payload, _ = context([original])
    row = payload['evidence_view']['facts'][0]
    op = row['operation_observations'][0]
    assert row.get('operation_support_refs'), 'Actual sent operations need short references'
    claims, gaps, _ = parse(payload, [dict(text=original.quote, kind='fact',
        support_refs=[row['operation_support_refs'][0]])], [original])
    assert len(claims) == 1 and not gaps
    assert claims[0].operation_binding.model_dump(mode='json') == candidates(original)[op['observation_id']]


@pytest.mark.parametrize('change', ['unknown', 'duplicate', 'mixed', 'two_operations', 'extra',
    'legacy_mix', 'empty', 'three_spans', 'two_same_fact', 'unrelated_pair', 'cross_product',
    'null', 'string', 'number', 'nested'])
def test_invalid_compact_atom_does_not_hide_another_questions_valid_atom(change):
    original = fact(quote='Organizations own all collections.', value=[
        'Organizations own all collections.', 'Organizations own archived collections.'])
    other = fact('other', quote='Members can edit documents and share documents.')
    third = fact('third', quote='Basic supports five members.')
    if change == 'cross_product':
        third = third.model_copy(update={'competitor': 'Other Product'})
    originals = [original, other, third]
    questions = [dict(question_id='bad', question='What is supported?'),
                 dict(question_id='good', question='Who owns collections?')]
    payload, _ = context(originals, questions=questions)
    by_id = {row['id']: row for row in payload['evidence_view']['facts']}
    good = span_atom(by_id[original.id], original.quote)
    bad = dict(good, support_refs=list(good['support_refs']))
    ops = by_id[other.id]['operation_support_refs']
    extra_span = by_id[third.id]['source_span_candidates'][0]
    own_spans = by_id[original.id]['source_span_candidates']
    if change == 'unknown': bad['support_refs'] = ['s999999']
    elif change == 'duplicate': bad['support_refs'] *= 2
    elif change == 'mixed': bad['support_refs'] += [ops[0]]
    elif change == 'two_operations': bad['support_refs'] = ops[:2]
    elif change == 'extra': bad['invented'] = True
    elif change == 'legacy_mix': bad['fact_ids'] = [original.id]
    elif change == 'empty': bad['support_refs'] = []
    elif change == 'null': bad['support_refs'] = None
    elif change == 'string': bad['support_refs'] = good['support_refs'][0]
    elif change == 'number': bad['support_refs'] = [1]
    elif change == 'nested': bad['support_refs'] = [[good['support_refs'][0]]]
    elif change == 'three_spans': bad['support_refs'] += [extra_span['support_ref'], 's9999']
    elif change == 'two_same_fact': bad['support_refs'] = [row['support_ref'] for row in own_spans[:2]]
    else: bad['support_refs'] = [extra_span['support_ref']] if change == 'cross_product' else [
        good['support_refs'][0], extra_span['support_ref']]
    response = [dict(question_id='bad', atoms=[bad], missing_fields=[]),
                dict(question_id='good', atoms=[good], missing_fields=[])]
    claims, gaps, plans = parse(payload, response, originals, questions=questions)
    assert len(claims) == 1 and claims[0].text == original.quote
    assert gaps and not plans[0]['claim_ids'] and plans[1]['claim_ids']


@pytest.mark.parametrize('change', ['operation', 'span', 'identity', 'duplicate_ref', 'unsent', 'unequal_refs'])
def test_catalog_checks_actual_candidate_against_full_canonical_original(change):
    original = fact(quote='Members can edit documents.')
    payload, _ = context([original])
    row = payload['evidence_view']['facts'][0]
    op_ref, span_ref = row['operation_support_refs'][0], row['source_span_candidates'][0]['support_ref']
    sent = {original.id}
    if change == 'operation': row['operation_observations'][0]['operation_quote'] = 'Anyone can edit documents.'
    elif change == 'span': row['source_span_candidates'][0]['quote'] += ' Altered.'
    elif change == 'identity': row['source_id'] = 'another-source'
    elif change == 'duplicate_ref': row['source_span_candidates'].append(dict(row['source_span_candidates'][0]))
    elif change == 'unsent': sent = set()
    else: row['operation_support_refs'].append('o2')
    catalog = writer._support_ref_catalog(payload, [original], sent)
    assert (op_ref not in catalog if change in {'operation', 'identity', 'unsent', 'unequal_refs'}
            else span_ref not in catalog)


@pytest.mark.parametrize('change', ['quote_and_value', 'missing_quote', 'missing_value', 'qualifiers', 'duplicate_fact_rows'])
def test_catalog_requires_complete_unambiguous_actual_fact_row(change):
    from packages.agents.writer.question_retrieval import _reconcile_question_originals
    from packages.research.evidence.snapshot_models import canonical_json
    original = fact(quote='Organizations own all collections.', value=['Members retain personal vault items.'])
    original = original.model_copy(update={'qualifiers_json': canonical_json(dict(source_scope=dict(
        context=dict(role='owner', plan='Enterprise'))))})
    payload, _ = context([original])
    sent = set(_reconcile_question_originals({}, [original], payload['evidence_view']['facts'])['sent_fact_ids'])
    row = payload['evidence_view']['facts'][0]
    if change == 'quote_and_value': row['quote'], row['value'] = 'Members own their private records.', []
    elif change == 'missing_quote': row.pop('quote')
    elif change == 'missing_value': row.pop('value')
    elif change == 'qualifiers': row['qualifiers'] = {}
    else:
        duplicate = copy.deepcopy(row)
        for span in duplicate['source_span_candidates']:
            span['support_ref'] = 's' + str(int(span['support_ref'][1:]) + 100)
        payload['evidence_view']['facts'].append(duplicate)
    assert not writer._support_ref_catalog(payload, [original], sent)


@pytest.mark.parametrize('same_alias', [False, True])
def test_duplicate_fact_identity_invalidates_every_span_and_operation_alias(same_alias):
    original = fact(quote='Members can edit documents.')
    other = fact('independent', quote='Organizations own collections.')
    payload, _ = context([original, other])
    row = next(row for row in payload['evidence_view']['facts'] if row['id'] == original.id)
    duplicate = copy.deepcopy(row)
    if not same_alias:
        duplicate['operation_support_refs'] = ['o101']
        for span in duplicate['source_span_candidates']:
            span['support_ref'] = 's' + str(int(span['support_ref'][1:]) + 100)
    payload['evidence_view']['facts'].append(duplicate)
    catalog = writer._support_ref_catalog(payload, [original, other], {original.id, other.id})
    assert catalog and all(binding['fact_ids'] == [other.id] for binding in catalog.values())


@pytest.mark.parametrize('change', ['field_missing', 'field_type', 'qualifiers_type', 'quote_type', 'value_type',
    'source_missing', 'id_type', 'row_type', 'span_type', 'span_id_type', 'operation_type',
    'operation_refs_type', 'operation_id_type', 'facts_type', 'view_type', 'payload_type'])
def test_malformed_actual_catalog_input_safely_produces_no_unverified_binding(change):
    original = fact(quote='Members can edit documents.')
    payload, _ = context([original])
    row = payload['evidence_view']['facts'][0]
    if change == 'field_missing': row.pop('field')
    elif change == 'field_type': row['field'] = ['evidence_terms']
    elif change == 'qualifiers_type': row['qualifiers'] = []
    elif change == 'quote_type': row['quote'] = {'text': original.quote}
    elif change == 'value_type': row['value'] = {'value': original.value}
    elif change == 'source_missing': row.pop('source_id')
    elif change == 'id_type': row['id'] = [original.id]
    elif change == 'row_type': payload['evidence_view']['facts'] = [None]
    elif change == 'span_type': row['source_span_candidates'] = None; row['operation_support_refs'] = []
    elif change == 'span_id_type':
        row['source_span_candidates'][0]['span_id'] = []; row['operation_support_refs'] = []
    elif change == 'operation_type': row['operation_observations'] = [None]; row['source_span_candidates'] = []
    elif change == 'operation_refs_type': row['operation_support_refs'] = None; row['source_span_candidates'] = []
    elif change == 'operation_id_type':
        row['operation_observations'][0]['observation_id'] = []; row['source_span_candidates'] = []
    elif change == 'facts_type': payload['evidence_view']['facts'] = None
    elif change == 'view_type': payload['evidence_view'] = None
    else: payload = None
    assert not writer._support_ref_catalog(payload, [original], {original.id})


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['quote_and_value', 'missing_quote', 'missing_value', 'qualifiers', 'duplicate_fact_rows'])
async def test_last_serialized_prompt_fault_cannot_restore_unverified_support(monkeypatch, change):
    import httpx
    from test_bound_claim_support import prepared_detail
    from test_execution_limits import _service
    from packages.research.evidence.snapshot import seal_snapshot
    original_text, value_text = 'Organizations own all collections.', 'Members retain personal vault items.'
    detail, _ = prepared_detail(original_text)
    row = detail.raw_sources[0].metadata['normalized_fields'][0]
    row['evidence_terms'] = [value_text]
    row['qualifiers'] = dict(source_scope=dict(context=dict(role='owner', plan='Enterprise')))
    detail.execution_mode = 'real'
    seal_snapshot(detail, phase='analysis', canonical_documents={})
    service, record = await _service(run_llm_max_calls=24, run_llm_max_tokens=80000, llm_max_retries=0)
    record.detail = detail
    service._runs[detail.id] = record
    budget = service._run_llm_budget(record)
    for phase in list(budget.delivery_reserves):
        if not phase.startswith(('writer:', 'qa:')): budget.finish_delivery(phase)
    serializer, expected = writer.compact_prompt_json, {}

    def faulty_final_serializer(payload):
        if 'evidence_view' not in payload or 'questions' not in payload:
            return serializer(payload)
        changed = copy.deepcopy(payload)
        row = changed['evidence_view']['facts'][0]
        expected_quote = value_text if change == 'missing_value' else original_text
        expected['ref'] = next(span['support_ref'] for span in row['source_span_candidates']
                               if span['quote'] == expected_quote)
        expected['text'] = value_text if change == 'missing_value' else original_text
        if change == 'quote_and_value': row['quote'], row['value'] = 'Members own private records.', []
        elif change == 'missing_quote': row.pop('quote')
        elif change == 'missing_value': row.pop('value')
        elif change == 'qualifiers': row['qualifiers'] = {}
        else:
            duplicate = copy.deepcopy(row)
            for span in duplicate['source_span_candidates']:
                span['support_ref'] = 's' + str(int(span['support_ref'][1:]) + 100)
            changed['evidence_view']['facts'].append(duplicate)
        return serializer(changed)

    requests = []
    async def post(url, payload, headers):
        assert payload['max_tokens'] == 1600
        user = payload['messages'][1]['content']
        data = expand_prompt_payload(json.loads(user.split('\nJSON:\n', 1)[1]))
        requests.append(data)
        if 'evidence_view' in data:
            if change == 'quote_and_value':
                assert data['evidence_view']['facts'][0]['quote'] != expected['text']
            elif change == 'missing_quote':
                assert 'quote' not in data['evidence_view']['facts'][0]
            elif change == 'missing_value':
                assert 'value' not in data['evidence_view']['facts'][0]
            content = {'question_plans': [dict(question_id=q['question_id'], atoms=[dict(text=expected['text'],
                kind='fact', support_refs=[expected['ref']])], missing_fields=[]) for q in data['questions']]}
        elif 'atom_review_policy' in data:
            content = {'reviews': [supported_review(claim) for claim in data['claims']]}
        else:
            content = {'version': 3, 'answers': [dict(question_id=q['question_id'], status='unverified',
                claim_ids=[], resolution='unresolved', conclusion='unknown', missing_fields=[],
                reason='No published answer selected.') for q in data['questions']]}
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(content)}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 200, 'completion_tokens': 100}})

    monkeypatch.setattr(writer, 'compact_prompt_json', faulty_final_serializer)
    monkeypatch.setattr(service._llm, '_post_chat_completion', post)
    result = await service._writer_dimension_report(record, 20)
    assert len(requests) == 1
    assert not detail.report_dimension_audits[0].claims
    assert expected['text'] not in result and not detail.report_md
    assert budget.calls == 1 and budget.repairs == 0


def test_compact_pair_preserves_exact_two_fact_exception_rule():
    from test_source_exception_closure import ACCESS, AUTH, facts, item
    from test_source_span_binding import scoped
    from packages.research.evidence.report_claims import claim_rule_reasons
    deletion = 'Deleting an account is permanent and deletes all vault data.'
    base, auth = facts(item(deletion, value={'status': 'documented', 'evidence_terms': [deletion, ACCESS]}),
                       item(AUTH, 'auth'))
    base = scoped(base.model_copy(update={'source_id': 'general'}), 'general')
    auth = scoped(auth.model_copy(update={'source_id': 'specific'}), 'specific')
    payload, _ = context([base, auth])
    selected = {next(span['span_id'] for span in spans(base) if span['quote'] == ACCESS), spans(auth)[0]['span_id']}
    refs = [ref for ref, binding in writer._support_ref_catalog(payload, [base, auth], {base.id, auth.id}).items()
            if set(binding.get('source_span_ids', ())) & selected]
    assert len(refs) == 2
    text = ' '.join((ACCESS + ' ' + AUTH).split())
    claims, gaps, _ = parse(payload, [dict(text=text, kind='fact', support_refs=refs)], [base, auth])
    assert len(claims) == 1 and not gaps
    assert set(claims[0].fact_ids) == {base.id, auth.id}
    assert set(claims[0].source_ids) == {'general', 'specific'}
    assert {span.span_id for span in claims[0].source_span_bindings} == selected
    assert not claim_rule_reasons(claims[0], SimpleNamespace(facts=[base, auth]),
        [SimpleNamespace(allowed_fact_ids=[base.id, auth.id])])


def test_legacy_verbose_plans_and_no_question_claims_keep_the_original_contract():
    original = fact(quote='Organizations own all collections.')
    payload, _ = context([original])
    span = spans(original)[0]
    legacy = draft(original, original.quote, source_span_ids=[span['span_id']])
    claims, gaps, _ = parse(payload, [legacy], [original])
    assert claims and not gaps
    row = payload['evidence_view']['facts'][0]
    mixed = dict(legacy, support_refs=[row['source_span_candidates'][0]['support_ref']])
    assert not parse(payload, [mixed], [original])[0]
    legacy_payload, _ = writer.compact_dimension_context(dict(segment_competitor='Example Product', dimension='feature'),
        SimpleNamespace(facts=[original]), {original.id})
    assert not any('support_ref' in span for row in legacy_payload['evidence_view']['facts']
                   for span in row['source_span_candidates'])
    claims, gaps = writer.parse_claim_drafts(json.dumps({'claims': [legacy]}), {}, {original.id}, 'legacy',
        source_facts=[original], span_candidates={span['span_id']: span})
    assert claims and not gaps


def test_other_dimension_questions_keep_legacy_context():
    original = fact(quote='The product is used by project managers.', field='role').model_copy(
        update={'dimension': 'persona'})
    payload, _ = writer.compact_dimension_context(dict(segment_competitor='Example Product', dimension='persona'),
        SimpleNamespace(facts=[original]), {original.id}, questions=[dict(question_id='q', question='Who uses it?')])
    assert payload['evidence_view']['facts']
    assert 'support_ref' not in writer.encoded(payload)


def test_more_than_eight_unique_atoms_still_allocates_other_question_first():
    texts = [f'Organizations own collection group {index}.' for index in range(10)]
    original = fact(quote=texts[0], value=texts)
    payload, _ = context([original])
    row = payload['evidence_view']['facts'][0]
    refs = {span['quote']: span['support_ref'] for span in row['source_span_candidates']}
    atoms = [dict(text=text, kind='fact', support_refs=[refs[text]]) for text in texts]
    questions = [dict(question_id='one', question='Who owns collections?'),
                 dict(question_id='two', question='Who owns other collections?')]
    response = [dict(question_id='one', atoms=atoms[:-1], missing_fields=[]),
                dict(question_id='two', atoms=atoms[-1:], missing_fields=[])]
    claims, gaps, plans = parse(payload, response, [original], questions=questions)
    assert len(claims) == 8 and 'claim_count_limit_exceeded' in gaps
    assert plans[1]['claim_ids'] == [claims[1].id] and claims[1].text == texts[-1]


@pytest.mark.parametrize('mixed', [False, True])
def test_same_eight_atoms_and_bindings_need_less_response_transport(mixed):
    texts = [('Members can edit documents after accepting the invitation.' if mixed and index >= 4 else
              f'Organizations own collection group {index}.') for index in range(8)]
    originals = [fact('fact-' + str(index) + '-' + 'a' * 64, quote=text) for index, text in enumerate(texts)]
    payload, _ = context(originals)
    rows = payload['evidence_view']['facts']
    by_id = {original.id: original for original in originals}
    compact, legacy = [], []
    for row in rows:
        if row.get('operation_support_refs'):
            compact.append(dict(text=row['quote'], kind='fact', support_refs=[row['operation_support_refs'][0]]))
            legacy.append(draft(by_id[row['id']], row['quote'],
                observation_id=row['operation_observations'][0]['observation_id']))
        else:
            compact.append(span_atom(row, row['quote']))
            legacy.append(draft(by_id[row['id']], row['quote'], source_span_ids=[
                next(span['span_id'] for span in spans(by_id[row['id']]) if span['quote'] == row['quote'])]))
    short_claims, short_gaps, _ = parse(payload, compact, originals)
    long_claims, long_gaps, _ = parse(payload, legacy, originals)
    assert not short_gaps and not long_gaps
    assert [claim.model_dump(exclude={'id'}) for claim in short_claims] == [claim.model_dump(exclude={'id'}) for claim in long_claims]
    envelope = lambda atoms: writer.encoded({'question_plans': [dict(question_id='q', atoms=atoms, missing_fields=[])]})
    short, long = envelope(compact), envelope(legacy)
    assert len(short) < len(long) * .55
    assert len(short.encode()) < len(long.encode())


@pytest.mark.parametrize('change', [None, 'must', 'condition', 'sibling'])
def test_compact_transport_cannot_weaken_modality_conditions_or_atomicity(change):
    from test_bound_claim_support import replay
    text = 'Members can edit documents after signing in and accepting the invitation.'
    original = fact(quote=text)
    payload, _ = context([original])
    row = payload['evidence_view']['facts'][0]
    if change == 'must': text = text.replace('can', 'must')
    elif change == 'condition': text = text.replace('signing in and ', '')
    elif change == 'sibling': text += ' Members can share documents.'
    claims, gaps, _ = parse(payload, [dict(text=text, kind='fact',
        support_refs=[row['operation_support_refs'][0]])], [original])
    assert claims and not gaps
    canonical_quote = row['operation_observations'][0]['operation_quote']
    assert claims[0].operation_binding.operation_quote == canonical_quote
    assert canonical_quote == original.quote.rstrip('.')
    if change == 'condition':
        # Arbitrary paraphrase omissions require the independent reviewer. Its
        # complete original and prerequisite checks must survive short refs.
        from packages.research.evidence.report_claims import audit_report_claims
        view = SimpleNamespace(facts=[original], sources=[])
        proposal = writer.review_payload(claims, view, review_version=3)['claims'][0]
        assert proposal['support_quotes'] == [canonical_quote]
        assert any('signing in and accepting the invitation' in check['quote']
                   for check in proposal['required_checks'] if check['kind'] == 'prerequisite')
        review = supported_review(proposal)
        review['verdict'] = 'unsupported'
        review['reason'] = 'The full source requires signing in and accepting the invitation.'
        assert audit_report_claims(claims, [review], view,
            [SimpleNamespace(allowed_fact_ids=[original.id])], review_version=3)[0].status == 'rejected'
    else:
        assert (replay(claims[0], original).status == 'supported') == (change is None)


@pytest.mark.asyncio
@pytest.mark.parametrize('limit', [None, 'calls', 'tokens', 'length', 'incomplete', 'stale', 'cancel', 'credential'])
async def test_actual_provider_boundary_keeps_dispatch_credential_and_execution_limits(monkeypatch, limit):
    import httpx
    from test_execution_limits import _service
    from test_bound_claim_support import SHARE, MANAGE, prepared_detail
    from packages.orchestrator.evidence_context import EvidenceUseRejectedError
    from packages.research.evidence.snapshot import seal_snapshot
    service, record = await _service(run_llm_max_calls=24, run_llm_max_tokens=80000, llm_max_retries=0)
    detail, _ = prepared_detail(SHARE + ' ' + MANAGE)
    detail.execution_mode = 'real'
    record.detail = detail
    service._runs[detail.id] = record
    budget = service._run_llm_budget(record)
    for phase in list(budget.delivery_reserves):
        if not phase.startswith(('writer:', 'qa:')):
            budget.finish_delivery(phase)
    if limit == 'calls': budget.calls = 22
    elif limit == 'tokens': budget.tokens_used = 79000
    requests = []

    async def post(url, payload, headers):
        data = expand_prompt_payload(json.loads(payload['messages'][1]['content'].split('\nJSON:\n', 1)[1]))
        requests.append(data)
        assert payload['max_tokens'] == 1600
        finish_reason = 'stop'
        if 'evidence_view' in data:
            row = data['evidence_view']['facts'][0]
            refs = row['operation_support_refs']
            assert len(refs) == len(row['operation_observations'])
            atoms = [dict(text=choice['operation_quote'], kind='fact', support_refs=[ref])
                for ref, choice in zip(refs, row['operation_observations'], strict=True)]
            content = json.dumps({'question_plans': [dict(question_id=q['question_id'], atoms=atoms,
                missing_fields=[]) for q in data['questions']]})
            if limit == 'length': finish_reason = 'length'
            elif limit == 'incomplete': content = content[:-4]
            elif limit == 'stale':
                detail.raw_sources[0].content_hash = 'changed-during-compact-await'
                seal_snapshot(detail, phase='analysis', canonical_documents={})
            elif limit == 'credential':
                use = detail.evidence_consumptions[-1]
                detail.evidence_consumptions[-1] = use.model_copy(update={'dependency_hash': 'replayed-credential'})
            elif limit == 'cancel': raise asyncio.CancelledError('Cancelled compact Writer')
        elif 'atom_review_policy' in data:
            assert len(data['claims']) == 1
            content = json.dumps({'reviews': [supported_review(data['claims'][0])]})
        else:
            content = json.dumps({'version': 3, 'answers': [dict(question_id=q['question_id'],
                status='unverified', resolution='unresolved', conclusion='unknown', claim_ids=[], missing_fields=[],
                reason='No answer selected.') for q in data['questions']]})
        return httpx.Response(200, json={'choices': [{'message': {'content': content}, 'finish_reason': finish_reason}],
            'usage': {'prompt_tokens': 200, 'completion_tokens': 100}})

    monkeypatch.setattr(service._llm, '_post_chat_completion', post)
    if limit in {'stale', 'credential', 'cancel'}:
        with pytest.raises(asyncio.CancelledError if limit == 'cancel' else EvidenceUseRejectedError):
            await service._writer_dimension_report(record, 20)
        assert not detail.report_dimension_audits and not detail.report_md
    else:
        await service._writer_dimension_report(record, 20)
        audit = detail.report_dimension_audits[0]
        published = [row for row in audit.claims if row.status == 'supported']
        if limit is None:
            assert len(published) == 2 and len(requests) == 5
        elif limit == 'calls':
            assert len(published) == 1 and len(requests) == 2 and budget.calls == 24
            assert 'claim_execution_budget_exceeded' in audit.gaps
        else:
            assert not audit.claims and len(requests) == (0 if limit == 'tokens' else 1)
            assert 'claim_generation_unavailable' in audit.gaps
        if limit != 'tokens':
            from packages.research.question_delivery import _observe_writer_dispatch
            from packages.research.evidence.views import select_evidence_view
            use = next(use for use in detail.evidence_consumptions if use.agent == 'writer')
            snapshot = service._current_evidence_snapshot(record)
            view = select_evidence_view(snapshot, agent=use.agent, competitor=use.competitor,
                dimension=use.dimension, source_ids=use.requested_source_ids,
                fact_ids=use.requested_fact_ids, max_bytes=use.view_max_bytes or use.max_bytes)
            span = next(span for span in detail.trace_spans if span.name == 'dimension_claim_writer')
            prompt = span.full_input.split('\nJSON:\n', 1)[1]
            observed = _observe_writer_dispatch(detail, view, use, prompt, 0)
            assert observed['content_dispatched']
            assert all(row['status'] == 'complete' for row in observed['content_observed'])
        for use in detail.evidence_consumptions:
            if use.agent == 'writer': service._validate_evidence_use(record, use)
    assert (budget.max_calls, budget.max_tokens) == (24, 80000)
    assert budget.calls <= 24 and budget.tokens_used <= 80000 and budget.repairs == 0
    assert budget.tokens_reserved == 0


def test_two_questions_share_eight_atom_capacity_fairly():
    texts = [f'Organizations own collection group {index}.' for index in range(10)]
    originals = [fact(str(index), quote=text) for index, text in enumerate(texts)]
    questions = [dict(question_id='one', question='Who owns collections?'),
                 dict(question_id='two', question='Who owns the other collections?')]
    payload, _ = context(originals, questions=questions)
    rows = payload['evidence_view']['facts']
    first = [span_atom(row, row['quote']) for row in rows[:-1]]
    second = span_atom(rows[-1], rows[-1]['quote'])
    # Eight unique atoms were actually sent; repetition cannot starve question two.
    response = [dict(question_id='one', atoms=first + first, missing_fields=[]),
                dict(question_id='two', atoms=[second], missing_fields=[])]
    claims, gaps, plans = parse(payload, response, originals, questions=questions)
    assert len(claims) == 8 and not gaps and plans[1]['claim_ids'] == [claims[1].id]


def test_annotations_are_budgeted_and_unsent_span_cannot_acquire_reference():
    original = fact(quote='Organizations own all collections.',
                    value=['Organizations own all collections.', 'Members retain private items.'])
    full, _ = context([original])
    assert all('support_ref' in span for span in full['evidence_view']['facts'][0]['source_span_candidates'])
    # Optional task-reference hints can shrink before any source is omitted.
    without_hints = copy.deepcopy(full)
    for task in without_hints.get('atom_tasks', ()):
        task.pop('support_refs', None)
    budget = len(writer.compact_prompt_json(without_hints).encode()) - 1
    bounded, _ = context([original], max_bytes=budget)
    assert len(writer.compact_prompt_json(bounded).encode()) <= budget
    sent = {row['id'] for row in bounded['evidence_view']['facts']}
    catalog = writer._support_ref_catalog(bounded, [original], sent)
    actual_refs = {span['support_ref'] for row in bounded['evidence_view']['facts']
                   for span in row.get('source_span_candidates', [])}
    assert set(catalog) == actual_refs
    assert len(catalog) < len(full['evidence_view']['facts'][0]['source_span_candidates'])


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['non_operation', 'operation', 'exception_pair'])
async def test_real_writer_compact_review_save_reload_and_final_qa(monkeypatch, mode):
    from datetime import UTC, datetime
    from pydantic import HttpUrl, TypeAdapter
    from test_question_retrieval import research_case
    from test_writer_question_delivery import service_for
    from packages.agents.qa.evidence_alignment import audit_dimension_claims
    from packages.research.evidence.snapshot import seal_snapshot
    from packages.schema.models import DecisionBrief

    texts = (['Items in a personal vault are owned by the individual user.',
              'When a member is removed from an organization, the user keeps personal vault items.']
             if mode == 'non_operation' else ['Members can edit documents after accepting the invitation.'])
    question = ('Example Product：把离职同事删掉后，他保存的密码还会留下吗？'
                if mode == 'non_operation' else 'Example Product: Can members edit documents?')
    if mode == 'exception_pair':
        from test_source_exception_closure import ACCESS, AUTH
        texts, question = [ACCESS, AUTH], 'Example Product: Can removed members log in?'
    detail, _ = research_case(texts, question=question)
    detail.created_at = detail.updated_at = datetime.now(UTC)
    detail.plan.competitors, detail.plan.dimensions = ['Example Product'], ['feature']
    detail.plan.decision_brief = DecisionBrief(decision_question=question)
    for source in detail.raw_sources:
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
        if mode == 'exception_pair':
            source.metadata['normalized_fields'][0]['qualifiers'] = dict(source_scope=dict(
                captured_page_id=source.id, source_url=str(source.url), raw_source_id=source.id,
                context={'role': None, 'plan': None}, operations=[]))
    snapshot = seal_snapshot(detail, phase='analysis', canonical_documents={})
    service, record = service_for(detail)
    calls, expected_bindings = [], []

    async def model(_record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs['user'].split('\nJSON:\n', 1)[1]))
        calls.append(kwargs['name'])
        assert kwargs['max_output_tokens'] == 1600
        if kwargs['name'] == 'dimension_claim_writer':
            assert 'support_refs' in kwargs['system']
            assert ('Write edit and comment permission rules as separate claims, each with its own matching '
                'o-reference and complete source-bound prerequisites.' in kwargs['system'])
            assert '"competitor":"..."' not in kwargs['system']
            assert 'Cite only supplied source IDs.' not in kwargs['system']
            assert 'Without questions return JSON' not in kwargs['system']
            assert not any(field in kwargs['system'] for field in ('observation_id', 'source_span_ids',
                '"fact_ids"', '"source_ids"'))
            atoms = []
            for row in payload['evidence_view']['facts']:
                if mode == 'operation':
                    op = row['operation_observations'][0]
                    assert row.get('operation_support_refs')
                    atoms.append(dict(text=row['quote'], kind='fact', support_refs=[row['operation_support_refs'][0]]))
                    expected_bindings.append(op)
                else:
                    assert all(set(span) == {'support_ref', 'quote'}
                               for span in row['source_span_candidates'])
                    atoms.append(span_atom(row, row['quote']))
                    expected_bindings.append((row['id'], row['source_id'], row['quote']))
            if mode == 'exception_pair':
                assert payload['source_exception_bindings']
                atoms = [dict(text=' '.join(' '.join(texts).split()), kind='fact',
                    support_refs=[atom['support_refs'][0] for atom in atoms])]
            fields = payload.get('required_clarifications', [{}])[0].get('missing_fields', [])
            return json.dumps({'question_plans': [dict(question_id=q['question_id'], atoms=atoms,
                missing_fields=fields) for q in payload['questions']]})
        if kwargs['name'] == 'dimension_claim_review':
            assert len(payload['claims']) == 1
            assert {check['kind'] for check in payload['claims'][0]['required_checks']} >= {
                'full_assertion_support', 'atomicity'}
            return json.dumps({'reviews': [supported_review(row) for row in payload['claims']]})
        fields = ['actual_action', 'data_ownership', 'retained_copy', 'access_path'] if mode == 'non_operation' else []
        return answer_response(payload, {'version': 3, 'answers': [dict(question_id=q['question_id'],
            status='partial' if fields else 'answered', claim_ids=[c['id'] for c in payload['claims']],
            resolution='clarification' if fields else ('conditional' if mode == 'exception_pair' else 'direct'),
            conclusion='depends' if fields or mode == 'exception_pair' else 'yes',
            missing_fields=fields, reason='The selected complete source assertions answer the question.')
            for q in payload['questions']]})

    monkeypatch.setattr(service, '_trace_llm_text', model)
    monkeypatch.setattr('packages.agents.writer.question_retrieval.get_local_provider_from_env', lambda *_: None)
    await service._real_writer_step(record)
    atom_count = 1 if mode == 'exception_pair' else len(texts)
    assert calls == ['dimension_claim_writer'] + ['dimension_claim_review'] * atom_count + [
        'dimension_answer_coverage', 'dimension_answer_review']
    audit = detail.report_dimension_audits[0]
    assert all(row.status == 'supported' for row in audit.claims)
    assert len(audit.claims) == atom_count
    if mode == 'exception_pair':
        claim = audit.claims[0].claim
        assert {(span.fact_id, span.source_id, span.quote) for span in claim.source_span_bindings} == set(expected_bindings)
        assert claim.text == ' '.join(' '.join(texts).split())
    for item, expected in zip(audit.claims if mode != 'exception_pair' else [],
                              expected_bindings if mode != 'exception_pair' else [], strict=True):
        if mode == 'operation':
            assert item.claim.operation_binding.model_dump(mode='json') == expected
        else:
            assert (item.claim.fact_ids[0], item.claim.source_ids[0], item.claim.source_span_bindings[0].quote) == expected
        assert item.claim.text in texts
    restored = type(audit).model_validate_json(audit.model_dump_json())
    detail.report_dimension_audits = [restored]
    assert restored.claim_review_version == restored.answer_binding_version == 3
    issues = audit_dimension_claims(service, record, snapshot, producer_verified=True)
    assert not issues, [issue.metadata for issue in issues]
    # Final QA still rejects a persisted source identity or prose alteration.
    item = restored.claims[0]
    changed = item.model_copy(update={'claim': item.claim.model_copy(update={'text': item.claim.text + ' All users must pay.'})})
    detail.report_dimension_audits = [restored.model_copy(update={'claims': (changed, *restored.claims[1:])})]
    assert audit_dimension_claims(service, record, snapshot, producer_verified=True)
