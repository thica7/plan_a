"""Publication uses sent originals, complete answers and source-bound billing axes."""

import json
from types import SimpleNamespace

import pytest
from claim_review_fixture import supported_review
from test_exception_recovery import ACCESS, AUTH, scoped_pair
from test_literal_non_operation import candidates, draft, fact
from test_missing_price_answers import answer, price_case
from test_pipeline_projection_contract import expand_text_refs
from test_question_retrieval import replace_snapshot, research_case

from packages.agents.writer.answer_coverage import coverage_resolution_reasons, parse_answer_coverage
from packages.agents.writer.dimension_writer import (
    DimensionWriterMixin, compact_dimension_context, compact_prompt_json,
    operation_claim_selection, parse_claim_drafts, review_payload,
)
from packages.research.evidence.operations import operation_binding, operation_observations
from packages.research.evidence.report_claims import ReportClaim, audit_report_claims, claim_rule_reasons
from packages.research.evidence.snapshot_models import canonical_json
from packages.research.evidence.source_exceptions import source_exception_bindings


def pair(*, operation=False):
    originals = scoped_pair(captured_page_id='specific-capture',
                            source_url='https://example.test/help/specific')
    if operation:
        base = originals[0]
        quote = base.quote + ' Members cannot edit documents.'
        originals[0] = base.model_copy(update={
            'quote': quote, 'value_json': canonical_json([quote]),
            'qualifiers_json': canonical_json({k: v for k, v in base.qualifiers.items()
                                                if k != 'operations'}),
        })
    return originals


def pair_draft(originals, **updates):
    row = dict(text=' '.join(' '.join(f.quote for f in originals).split()), kind='fact',
               competitor='Example Product', dimension='feature',
               fact_ids=[f.id for f in originals], source_ids=[f.source_id for f in originals])
    row.update(updates)
    return row


def compact(originals, **kwargs):
    return compact_dimension_context(
        {'segment_competitor': 'Example Product', 'dimension': 'feature'},
        SimpleNamespace(facts=originals), {f.id for f in originals}, **kwargs,
    )


def test_compact_exposes_only_complete_sent_exception_pairs_within_unchanged_budget():
    originals = pair()
    payload, _ = compact(originals)
    assert payload['source_exception_bindings'] == list(source_exception_bindings(originals))
    assert payload['source_exception_bindings'][0]['source_exceptions'][0]['quote'] == AUTH
    assert len(compact_prompt_json(payload).encode()) <= 14000
    smaller, _ = compact(originals[:1])
    assert not smaller.get('source_exception_bindings')


def test_valid_exception_pair_survives_parser_selection_and_bound_review():
    originals = pair()
    claims, gaps = parse_claim_drafts(json.dumps({'claims': [pair_draft(originals)]}), {},
                                      {f.id for f in originals}, 'pair-use', source_facts=originals)
    assert len(claims) == 1 and not gaps
    chosen = operation_claim_selection(claims, SimpleNamespace(facts=originals),
                                       ('read',), {f.id for f in originals})
    assert chosen == claims
    view = SimpleNamespace(facts=originals, sources=[])
    boundaries = [SimpleNamespace(allowed_fact_ids=[f.id for f in originals])]
    assert not claim_rule_reasons(claims[0], view, boundaries)
    published = audit_report_claims(claims, [supported_review(claims[0].model_dump(mode='json'))],
                                     view, boundaries)
    assert published[0].status == 'supported'
    review = expand_text_refs(json.loads(compact_prompt_json(review_payload(claims, view))))
    assert {r['id'] for r in review['facts']} == {f.id for f in originals}
    assert AUTH in {r['text'] for r in review['quotes']}
    question = {'question_id': 'q', 'question': 'Can removed members still access their account?'}
    response = selection(question, [claims[0].id], conclusion='depends', resolution='conditional')
    rows = parse_answer_coverage(response, [question], {claims[0].id},
                                  claims=[claims[0].model_dump(mode='json')], require_v2=True,
                                  facts=originals)
    assert rows[0].status == 'answered'
    assert not coverage_resolution_reasons(rows[0], [claims[0].model_dump(mode='json')],
                                           require_v2=True, facts=originals)


@pytest.mark.parametrize('change', ['unrelated', 'source', 'condition', 'unsent', 'actor'])
def test_parser_rejects_unverified_multiple_facts(change):
    originals = pair()
    row = pair_draft(originals)
    if change == 'unrelated':
        originals[1] = fact('other', quote='Members may be Custodians.').model_copy(
            update={'source_id': originals[1].source_id})
        row['fact_ids'] = [f.id for f in originals]
    elif change == 'source':
        row['source_ids'] = [originals[0].source_id]
    elif change == 'condition':
        row['text'] = ACCESS
    elif change == 'actor':
        other = originals[1]
        originals[1] = other.model_copy(update={'quote': other.quote.replace('member accounts', 'editor accounts')})
    sent = {f.id for f in originals} if change != 'unsent' else {originals[0].id}
    claims, gaps = parse_claim_drafts(json.dumps({'claims': [row]}), {}, sent, 'bad-pair',
                                      source_facts=originals)
    assert not claims and gaps


def test_exception_pair_keeps_original_six_operation_binding():
    originals = pair(operation=True)
    binding = operation_binding(operation_observations(originals[0])[0])
    row = pair_draft(originals, observation_id=binding['observation_id'])
    sent = {f.id for f in originals}
    claims, gaps = parse_claim_drafts(json.dumps({'claims': [row]}), {binding['observation_id']: binding},
                                      sent, 'operation-pair', source_facts=originals)
    assert len(claims) == 1 and not gaps
    chosen = operation_claim_selection(claims, SimpleNamespace(facts=originals), ('edit',), sent)
    assert chosen == claims
    boundaries = [SimpleNamespace(allowed_fact_ids=sent)]
    assert not claim_rule_reasons(claims[0], SimpleNamespace(facts=originals), boundaries)
    row.pop('observation_id')
    claims, gaps = parse_claim_drafts(json.dumps({'claims': [row]}), {binding['observation_id']: binding},
                                      sent, 'unbound-operation-pair', source_facts=originals)
    assert not claims and 'operation_binding_required' in gaps


def test_mixed_fact_context_offers_complete_original_non_operation_rules():
    restriction = 'Guests do not have private vaults and may belong to one vault at a time.'
    original = fact(quote='Members can edit documents. ' + restriction)
    payload, _ = compact([original], questions=[{'question_id': 'q',
        'question': 'Can Guests have a private vault or belong to two vaults?'}])
    sent = payload['evidence_view']['facts'][0]
    assert restriction in sent['non_operation_originals']
    claims, gaps = parse_claim_drafts(json.dumps({'claims': [draft(original, restriction)]}),
                                      candidates(original), {original.id}, 'literal', source_facts=[original])
    assert claims and not gaps
    assert not claim_rule_reasons(claims[0], SimpleNamespace(facts=[original]),
                                  [SimpleNamespace(allowed_fact_ids=[original.id])])
    chinese = draft(original, '访客没有自己的 Private vault，一次只能加入一个保险库。')
    claims, gaps = parse_claim_drafts(json.dumps({'claims': [chinese]}), candidates(original),
                                      {original.id}, 'translated', source_facts=[original])
    assert not claims and 'operation_binding_required' in gaps


def selection(question, ids, *, conclusion='no', resolution='direct', reason='Published rule applies.'):
    return json.dumps({'version': 2, 'answers': [{'question_id': question['question_id'],
        'status': 'answered', 'claim_ids': ids, 'resolution': resolution, 'conclusion': conclusion,
        'missing_fields': [], 'reason': reason}]})


@pytest.mark.asyncio
async def test_actual_coverage_initially_sees_published_claims_and_final_review_sees_complete_answer():
    quote = 'A resource-scoped role grants permission only within its assigned resource.'
    detail, snapshot = research_case([quote])
    original = next(f for f in snapshot.facts if f.field == 'evidence_terms')
    claim = ReportClaim(id='published-scope', text=quote, kind='fact', competitor='Example Product',
                         dimension='feature', fact_ids=[original.id], source_ids=[original.source_id])
    question = {'question_id': 'q', 'question': 'Only the role on alpha.test is granted, with no other grants. '
                'Can it grant access to beta.test?'}
    calls = []
    class Harness:
        def _evidence_live_record(self, record): return record
        def _current_evidence_snapshot(self, record): return snapshot
        def _validate_evidence_use(self, *args): pass
        def _validate_dimension_upstream(self, *args): pass
        async def _dimension_call_with_gaps(self, record, gaps, **kwargs):
            payload = expand_text_refs(json.loads(kwargs['user'].split('\nJSON:\n')[1]))
            calls.append((kwargs['name'], payload))
            return selection(question, [claim.id]), gaps
    view = SimpleNamespace(facts=[original], competitor='Example Product', dimension='feature')
    rows, gaps, _ = await DimensionWriterMixin._dimension_question_coverage(
        Harness(), SimpleNamespace(detail=detail), [question],
        {'evidence_view': {'facts': [{'id': original.id}]}},
        [SimpleNamespace(claim=claim, status='supported')], view, SimpleNamespace(max_bytes=14000), ())
    assert rows[0].status == 'answered' and not gaps
    assert 'facts' not in calls[0][1]
    proposal = calls[1][1]['proposed_answers'][0]
    assert proposal['answer'] == claim.text
    assert proposal['evidence_spans'] == [{'claim_id': claim.id, 'quote': claim.text}]
    assert calls[1][1]['facts'][0]['quote'] == quote


def test_collection_absence_cannot_be_a_product_fact_bound_to_a_role_page():
    original = fact(quote='The Resource Purge role can clear the cache of its assigned domain.')
    candidate = ReportClaim(id='collection-state', **draft(original,
        '关于精确账单金额：所捕获资料未包含该用量模式定价或计费规则，无法给出准确美元金额。'))
    assert 'collection_status_requires_server_receipt' in claim_rule_reasons(
        candidate, SimpleNamespace(facts=[original]),
        [SimpleNamespace(allowed_fact_ids=[original.id])])


TABLE_HEADER = '| Usage model | Requests | Duration | CPU time |'
TABLE_ROW = ('| Standard | 12 million included +$0.42 per million requests | No charge for duration | '
             '20 million CPU milliseconds included +$0.03 per additional million CPU milliseconds |')
INTRO = 'Users on the Compute Paid plan have access to the Standard usage model.'
QUESTION = 'Example Product Compute Paid 的 Standard 用量模式本月1500万动态请求，准确美元账单是多少？'


def table_case(*, row=TABLE_ROW, intro=INTRO):
    detail, snapshot, _ = price_case(money=False)
    original = fact(quote=row).model_copy(update={
        'source_id': snapshot.sources[0].id, 'dimension': 'pricing',
        'value_json': canonical_json([row, TABLE_HEADER, intro]),
        'qualifiers_json': canonical_json({'table_context': [TABLE_HEADER]}),
    })
    return detail, replace_snapshot(detail, snapshot, facts=(original,))


def test_paid_plan_and_usage_model_from_one_applicable_source_preserve_known_request_axes():
    detail, snapshot = table_case()
    row = answer(detail, snapshot, QUESTION)['q-price']
    assert row['resolution'] == 'insufficient' and row['conclusion'] == 'unknown'
    assert {'cpu_usage', 'usage_inputs', 'market', 'tax_scope'} <= set(row['missing_fields'])
    assert not {'plan', 'usage_model', 'currency', 'billing_interval'} & set(row['missing_fields'])
    assert 'CPU' in row['answer'] and '套餐' not in row['answer']
    assert '$' not in row['answer'] and '1500' not in row['answer']


@pytest.mark.parametrize('row,intro,question', [
    (TABLE_ROW.replace('+$0.03 per additional million CPU milliseconds', 'No charge for CPU time'), INTRO, QUESTION),
    (TABLE_ROW.replace('+$0.03 per additional million CPU milliseconds', '+$0.03 per million requests'), INTRO, QUESTION),
    (TABLE_ROW.replace('| Standard |', '| Legacy |'), INTRO.replace('Standard', 'Legacy'), QUESTION),
    (TABLE_ROW, INTRO.replace('Compute Paid', 'Archive Paid'), QUESTION),
])
def test_cpu_total_requires_positive_current_cpu_time_column_and_matching_scope(row, intro, question):
    detail, snapshot = table_case(row=row, intro=intro)
    result = answer(detail, snapshot, question)['q-price']
    assert 'cpu_usage' not in result['missing_fields']
    assert 'usage_inputs' in result['missing_fields']


def test_context_keeps_both_explicit_request_axes_without_asserting_them_as_product_facts():
    from packages.agents.writer.price_answers import _request
    detail, snapshot = table_case()
    _, _, context = _request(detail, {'question': QUESTION}, 'Example Product', source_facts=snapshot.facts)
    assert context['plan'] == 'Compute Paid' and context['usage_model'] == 'Standard'
    assert context['currency'] == 'USD' and context['billing_interval'] == 'monthly'


def test_cpu_time_unit_can_be_supplied_by_its_own_header():
    detail, snapshot = table_case(row=TABLE_ROW.replace('+$0.03 per additional million CPU milliseconds',
                                                       '+$0.03 per additional million'))
    original = snapshot.facts[0]
    header = TABLE_HEADER.replace('CPU time', 'CPU time (milliseconds)')
    original = original.model_copy(update={
        'qualifiers_json': canonical_json({'table_context': [header]}),
        'value_json': canonical_json([original.quote, header, INTRO]),
    })
    snapshot = replace_snapshot(detail, snapshot, facts=(original,))
    row = answer(detail, snapshot, QUESTION)['q-price']
    assert 'cpu_usage' in row['missing_fields']


def test_cpu_mode_and_plan_cannot_be_joined_across_different_source_sentences():
    intro = ('Users on the Compute Free plan have access to the Standard usage model. '
             'Users on the Compute Paid plan have access to the Legacy usage model.')
    detail, snapshot = table_case(intro=intro)
    assert 'cpu_usage' not in answer(detail, snapshot, QUESTION)['q-price']['missing_fields']


@pytest.mark.parametrize('rate', ['$0 per million CPU milliseconds', '-$0.03 per million CPU milliseconds'])
def test_non_positive_cpu_rate_does_not_require_total_cpu_time(rate):
    detail, snapshot = table_case(row=TABLE_ROW.replace('+$0.03 per additional million CPU milliseconds', rate))
    assert 'cpu_usage' not in answer(detail, snapshot, QUESTION)['q-price']['missing_fields']


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['literal', 'pair', 'pair_operation'])
async def test_real_writer_claim_review_answer_and_final_qa_replay_the_same_originals(monkeypatch, path):
    from packages.agents.qa.evidence_alignment import audit_dimension_claims
    from packages.agents.writer import question_retrieval
    from packages.config import Settings
    from packages.memory import KBCache, RunJournal
    from packages.orchestrator.checkpointer import GraphCheckpointer
    from packages.orchestrator.service import RunRecord, RunService
    from packages.research.evidence.snapshot import seal_snapshot
    from packages.skills.registry import SkillRegistry

    restriction = 'Guests do not have private vaults and may belong to one vault at a time.'
    originals = ([fact(quote='Members can edit documents. ' + restriction)] if path == 'literal'
                 else pair(operation=path == 'pair_operation'))
    question_text = ('Example Product: Can Guests have private vaults or belong to two vaults?'
                     if path == 'literal' else 'Example Product: Can removed members still access their account?')
    detail, _ = research_case([f.quote for f in originals], question=question_text)
    from datetime import UTC, datetime
    detail.created_at = datetime.now(UTC)
    detail.plan.competitors = ['Example Product']
    detail.plan.dimensions = ['feature']
    for source, original in zip(detail.raw_sources, originals, strict=True):
        source.id = original.source_id
        source.metadata['normalized_fields'] = [{
            'kind': 'feature', 'dimension': 'feature', 'competitor': original.competitor,
            'slot': original.id, 'support_level': 'documented', 'evidence_terms': original.value,
            'evidence_quote': original.quote, 'confidence': .9,
            'evidence_item_ids': list(original.evidence_item_ids) or [original.id],
            'qualifiers': original.qualifiers,
        }]
    snapshot = seal_snapshot(detail, phase='analysis', canonical_documents={})
    service = RunService(SkillRegistry.from_default_path(), Settings(demo_mode=True),
                         journal=RunJournal.in_memory(), kb_cache=KBCache.in_memory(),
                         graph_checkpointer=GraphCheckpointer.in_memory())
    record = RunRecord(detail)
    service._runs[detail.id] = record
    retrieve = question_retrieval.retrieve_question_facts
    async def lexical(*args, **kwargs):
        return await retrieve(*args, **{**kwargs, 'mode': 'lexical'})
    monkeypatch.setattr(question_retrieval, 'retrieve_question_facts', lexical)
    calls = []
    async def model(record, **kwargs):
        payload = expand_text_refs(json.loads(kwargs['user'].split('\nJSON:\n')[1]))
        calls.append((kwargs['name'], payload))
        if kwargs['name'] == 'dimension_claim_writer':
            sent = payload['evidence_view']['facts']
            if path == 'literal':
                original = sent[0]
                assert restriction in original['non_operation_originals']
                row = dict(text=restriction, kind='fact', competitor=original['competitor'],
                           dimension='feature', fact_ids=[original['id']], source_ids=[original['source_id']])
            else:
                group = payload['source_exception_bindings'][0]
                by_id = {f['id']: f for f in sent}
                row = dict(text=' '.join(' '.join(by_id[fid]['quote'] for fid in group['fact_ids']).split()),
                           kind='fact', competitor='Example Product', dimension='feature',
                           fact_ids=group['fact_ids'], source_ids=group['source_ids'])
                if path == 'pair_operation':
                    row['observation_id'] = next(candidate['observation_id'] for f in sent
                        for candidate in f.get('operation_observations', []) if candidate['operation'] == 'edit')
            return json.dumps({'claims': [row]})
        if kwargs['name'] == 'dimension_claim_review':
            return json.dumps({'reviews': [supported_review(c) for c in payload['claims']]})
        return selection(payload['questions'][0], [c['id'] for c in payload['claims']],
                         conclusion='no' if path == 'literal' else 'depends',
                         resolution='direct' if path == 'literal' else 'conditional')
    monkeypatch.setattr(service, '_trace_llm_text', model)
    detail.report_md = await service._writer_dimension_report(record, 20)
    uses = [u for u in detail.evidence_consumptions if u.agent == 'writer']
    service._record_evidence_artifact(record, kind='writer', uses=uses,
                                    payload=service._writer_evidence_artifact_payload(detail))
    audit = detail.report_dimension_audits[0]
    assert len(audit.claims) == 1 and audit.claims[0].status == 'supported', (audit.gaps, calls)
    assert audit.answer_coverage[0].status == 'answered'
    assert audit.answer_coverage[0].answer == audit.claims[0].claim.text
    assert not audit_dimension_claims(service, record, snapshot, producer_verified=True)
    assert [name for name, _ in calls] == ['dimension_claim_writer', 'dimension_claim_review',
                                         'dimension_answer_coverage', 'dimension_answer_review']
    if path != 'literal':
        assert len(audit.claims[0].claim.fact_ids) == len(audit.claims[0].claim.source_ids) == 2
        assert 'at least once before being removed' in audit.claims[0].claim.text


def test_missing_sent_operation_candidate_cannot_make_a_pair_operation_unbound():
    originals = pair(operation=True)
    claims, gaps = parse_claim_drafts(json.dumps({'claims': [pair_draft(originals)]}), {},
                                      {f.id for f in originals}, 'no-operation-candidate', source_facts=originals)
    assert not claims and 'operation_binding_required' in gaps


def test_pair_with_no_operation_targets_cannot_bypass_selection_operation_binding():
    originals = pair(operation=True)
    candidate = ReportClaim(id='unbound-pair', **pair_draft(originals))
    assert not operation_claim_selection([candidate], SimpleNamespace(facts=originals), ('edit',),
                                         {f.id for f in originals}, fact_targets={})


def test_unknown_lowercase_plan_scope_cannot_lend_a_cpu_rule_to_another_plan():
    from test_incomplete_quote_answers import rule_case
    detail, snapshot = rule_case('The premium plan bill depends on CPU time.')
    row = answer(detail, snapshot,
                 'Example Product Free plan 本月有1500万次请求，账单准确是多少美元？')['q-price']
    assert 'cpu_usage' not in row['missing_fields']


@pytest.mark.parametrize('quote', [
    'CPU is charged at $0.03 per million requests.',
    'CPU time is billed at $0.03 per million requests.',
    'CPU 按请求计费，每百万次请求收费 $0.03。',
])
def test_non_table_cpu_charge_per_request_does_not_require_cpu_time_total(quote):
    from test_incomplete_quote_answers import rule_case
    detail, snapshot = rule_case(quote)
    row = answer(detail, snapshot, QUESTION)['q-price']
    assert 'cpu_usage' not in row['missing_fields']


def test_optional_literal_candidates_never_displace_a_complete_mixed_fact():
    original = fact(quote='Members can edit documents. Guests do not have private vaults '
                          'and may belong to one vault at a time.')
    questions = [{'question_id': 'q', 'question': 'Can Guests have a private vault or join two vaults?'}]
    full, _ = compact([original], questions=questions)
    assert full['evidence_view']['facts'][0].pop('non_operation_originals')
    original_budget = len(compact_prompt_json(full).encode())
    bounded, omitted = compact([original], questions=questions, max_bytes=original_budget)
    assert len(bounded['evidence_view']['facts']) == 1
    assert bounded['evidence_view']['facts'][0]['quote'] == original.quote
    assert len(compact_prompt_json(bounded).encode()) <= original_budget
    assert not omitted


def test_unknown_lowercase_usage_model_cannot_lend_cpu_time_to_another_model():
    from test_incomplete_quote_answers import rule_case
    detail, snapshot = rule_case('The legacy usage model bill depends on CPU time.')
    row = answer(detail, snapshot, QUESTION)['q-price']
    assert 'cpu_usage' not in row['missing_fields']


@pytest.mark.parametrize('quote', [
    'CPU time is billed at -$0.03 per million CPU milliseconds.',
    'CPU time is billed at $0 per million CPU milliseconds.',
    'CPU fees are $0.03 per million requests.',
])
def test_prose_non_positive_or_request_rate_does_not_require_cpu_time_total(quote):
    from test_incomplete_quote_answers import rule_case
    detail, snapshot = rule_case(quote)
    row = answer(detail, snapshot, QUESTION)['q-price']
    assert 'cpu_usage' not in row['missing_fields']


@pytest.mark.parametrize('quote', [
    'CPU time is billed.',
    'The bill depends on CPU time.',
    'CPU time is billed at $0.03 per million CPU milliseconds.',
])
def test_prose_affirmative_cpu_time_dependency_preserves_the_missing_total(quote):
    from test_incomplete_quote_answers import rule_case
    detail, snapshot = rule_case(quote)
    row = answer(detail, snapshot, QUESTION)['q-price']
    assert 'cpu_usage' in row['missing_fields']


def test_optional_hints_are_added_after_all_complete_facts_fit():
    originals = [
        fact('one', quote='Members can edit documents. Guests do not have private vaults.'),
        fact('two', quote='Members can edit documents. Visitors may belong to one vault at a time.'),
    ]
    questions = [{'question_id': 'q', 'question': 'Can Guests or Visitors have private vaults or two vaults?'}]
    full, _ = compact(originals, questions=questions)
    assert all(row.pop('non_operation_originals') for row in full['evidence_view']['facts'])
    original_budget = len(compact_prompt_json(full).encode())
    bounded, omitted = compact(originals, questions=questions, max_bytes=original_budget)
    assert {row['id'] for row in bounded['evidence_view']['facts']} == {f.id for f in originals}
    assert len(compact_prompt_json(bounded).encode()) <= original_budget
    assert not omitted


@pytest.mark.parametrize('scope', ['premium plans', 'premium tiers', 'legacy usage models'])
def test_unknown_plural_billing_scope_cannot_lend_cpu_time_to_requested_scope(scope):
    from test_incomplete_quote_answers import rule_case
    detail, snapshot = rule_case(f'The bill depends on CPU time for {scope}.')
    row = answer(detail, snapshot, QUESTION)['q-price']
    assert 'cpu_usage' not in row['missing_fields']


@pytest.mark.parametrize('scope', ['Compute Paid plans', 'Standard usage models'])
def test_recognized_plural_billing_scope_preserves_cpu_time_dependency(scope):
    from test_incomplete_quote_answers import rule_case
    detail, snapshot = rule_case(f'The bill depends on CPU time for {scope}.')
    row = answer(detail, snapshot, QUESTION)['q-price']
    assert 'cpu_usage' in row['missing_fields']


@pytest.mark.parametrize('parent,scope,question', [
    ('The Free plan includes one million requests.', 'premium plans',
     'Example Product Free plan 本月有1500万次请求，账单准确是多少美元？'),
    ('The Free plan includes one million requests.', 'Premium plans',
     'Example Product Free plan 本月有1500万次请求，账单准确是多少美元？'),
    ('The Free plan has access to the Standard usage model.', 'legacy usage models',
     'Example Product Free plan 的 Standard 用量模式本月有1500万次请求，账单准确是多少美元？'),
    ('The Free plan has access to the Standard usage model.', 'Legacy usage models',
     'Example Product Free plan 的 Standard 用量模式本月有1500万次请求，账单准确是多少美元？'),
])
def test_cpu_sentence_cannot_borrow_parent_scope_over_an_explicit_other_or_unknown_scope(parent, scope, question):
    from test_incomplete_quote_answers import rule_case
    detail, snapshot = rule_case(f'{parent} The bill depends on CPU time for {scope}.')
    row = answer(detail, snapshot, question)['q-price']
    assert 'cpu_usage' not in row['missing_fields']


@pytest.mark.parametrize('parent,scope,question', [
    ('The Free plan includes one million requests.', '',
     'Example Product Free plan 本月有1500万次请求，账单准确是多少美元？'),
    ('The Compute Paid plan includes one million requests.', ' for Compute Paid plans', QUESTION),
    ('The Free plan has access to the Standard usage model.', '',
     'Example Product Free plan 的 Standard 用量模式本月有1500万次请求，账单准确是多少美元？'),
    ('The Free plan has access to the Standard usage model.', ' for Standard usage models',
     'Example Product Free plan 的 Standard 用量模式本月有1500万次请求，账单准确是多少美元？'),
])
def test_cpu_sentence_preserves_verified_parent_scope_or_matching_local_scope(parent, scope, question):
    from test_incomplete_quote_answers import rule_case
    detail, snapshot = rule_case(f'{parent} The bill depends on CPU time{scope}.')
    row = answer(detail, snapshot, question)['q-price']
    assert 'cpu_usage' in row['missing_fields']


@pytest.mark.parametrize('quote', [
    'The Compute Paid plan includes requests, while the bill depends on CPU time for premium plans.',
    'The Compute Paid plan has access to the Standard usage model, while the bill depends on CPU time for legacy usage models.',
    'The bill depends on CPU time for Compute Paid plans and premium tiers.',
    'The Compute Paid plan has access to Standard usage models and legacy usage models; the bill depends on CPU time.',
])
def test_every_explicit_cpu_scope_mention_requires_a_recognized_complete_name(quote):
    from test_incomplete_quote_answers import rule_case
    detail, snapshot = rule_case(quote)
    assert 'cpu_usage' not in answer(detail, snapshot, QUESTION)['q-price']['missing_fields']


@pytest.mark.parametrize('quote', [
    'The Compute Paid plan includes requests, while the bill depends on CPU time for Compute Paid plans.',
    'The Compute Paid plan has access to the Standard usage model, while the bill depends on CPU time for Standard usage models.',
    'The Compute Paid plan includes requests. The bill depends on CPU time.',
    'The Compute Paid plan has access to the Standard usage model. The bill depends on CPU time.',
])
def test_recognized_repeated_scopes_and_verified_parent_scope_preserve_cpu_dependency(quote):
    from test_incomplete_quote_answers import rule_case
    detail, snapshot = rule_case(quote)
    assert 'cpu_usage' in answer(detail, snapshot, QUESTION)['q-price']['missing_fields']


def test_structured_cpu_table_keeps_its_applicable_rule_despite_other_plan_background():
    background = 'Enterprise accounts are billed based on the usage model specified in their contract.'
    detail, snapshot = table_case(intro=INTRO + ' ' + background)
    before = snapshot.model_dump_json()
    row = answer(detail, snapshot, QUESTION)['q-price']
    assert 'cpu_usage' in row['missing_fields']
    assert snapshot.model_dump_json() == before
    assert background in '\n'.join(snapshot.facts[0].value)


@pytest.mark.parametrize('row,intro', [
    (TABLE_ROW.replace('20 million CPU', 'For premium plans, 20 million CPU'), INTRO),
    (TABLE_ROW.replace('12 million included', 'For legacy usage models, 12 million included'), INTRO),
    (TABLE_ROW.replace('20 million CPU', 'For Legacy usage models, 20 million CPU'), INTRO),
    (TABLE_ROW, 'The Compute Paid plan includes requests.'),
    (TABLE_ROW, 'The Standard usage model includes requests.'),
    (TABLE_ROW, INTRO.replace('Compute Paid', 'Archive Paid')),
    (TABLE_ROW.replace('| Standard |', '| Legacy |'), INTRO),
])
def test_structured_cpu_table_requires_current_row_and_complete_matching_applicability(row, intro):
    detail, snapshot = table_case(row=row, intro=intro)
    assert 'cpu_usage' not in answer(detail, snapshot, QUESTION)['q-price']['missing_fields']


@pytest.mark.parametrize('quote', [
    'The Compute Paid plan includes requests, while the bill depends on CPU time for Premium plans.',
    'The Compute Paid plan has access to the Standard usage model, while the bill depends on CPU time for Legacy usage models.',
])
def test_compound_cpu_rule_cannot_mix_another_recognized_name_on_the_same_axis(quote):
    from test_incomplete_quote_answers import rule_case
    detail, snapshot = rule_case(quote)
    assert 'cpu_usage' not in answer(detail, snapshot, QUESTION)['q-price']['missing_fields']


@pytest.mark.parametrize('scope', ['premium plans', 'Legacy usage models'])
def test_current_cpu_column_header_cannot_introduce_another_scope(scope):
    detail, snapshot = table_case()
    original = snapshot.facts[0]
    header = TABLE_HEADER.replace('CPU time', f'CPU time for {scope}')
    original = original.model_copy(update={
        'qualifiers_json': canonical_json({'table_context': [header]}),
        'value_json': canonical_json([original.quote, header, INTRO]),
    })
    snapshot = replace_snapshot(detail, snapshot, facts=(original,))
    assert 'cpu_usage' not in answer(detail, snapshot, QUESTION)['q-price']['missing_fields']


@pytest.mark.parametrize('intro', [
    'Users on the Compute Paid plan do not have access to the Standard usage model.',
    'The Compute Paid plan and the Standard usage model are listed in the billing guide.',
    'Users on the Compute Paid plan have access to the Standard usage model unless approval is missing.',
    'If approved, users on the Compute Paid plan have access to the Standard usage model.',
    '"Users on the Compute Paid plan have access to the Standard usage model."',
    INTRO + ' The Standard usage model is available only with the Enterprise plan.',
    INTRO + ' The Standard usage model is not available for premium plans.',
    'The Standard usage model is available only with the Enterprise plan.',
])
def test_table_applicability_requires_a_complete_affirmative_relation_not_name_cooccurrence(intro):
    detail, snapshot = table_case(intro=intro)
    assert 'cpu_usage' not in answer(detail, snapshot, QUESTION)['q-price']['missing_fields']


@pytest.mark.parametrize('intro', [
    INTRO,
    'The Compute Paid plan has access to the Standard usage model.',
])
def test_table_applicability_accepts_complete_source_affirmative_access_sentences(intro):
    detail, snapshot = table_case(intro=intro)
    assert 'cpu_usage' in answer(detail, snapshot, QUESTION)['q-price']['missing_fields']
