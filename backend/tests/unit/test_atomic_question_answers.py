"""Atomic transport and strict v3 replay; stubs do not prove model entailment."""

import json
from types import SimpleNamespace

import pytest
from test_literal_non_operation import candidates, draft, fact
from test_source_span_binding import spans

from packages.agents.writer.answer_coverage import coverage_resolution_reasons, parse_answer_coverage
from packages.agents.writer.dimension_writer import parse_claim_drafts, review_payload
from packages.research.evidence.report_claims import audit_report_claims

FIELDS = ['actual_action', 'data_ownership', 'retained_copy', 'access_path']
QUESTION = {'question_id': 'anonymous', 'question': '把离职同事删掉后，他保存的密码还会留下吗？'}


def review_for(claim, *, span=None):
    payload = review_payload([claim], SimpleNamespace(facts=[], sources=[]), review_version=3)
    return dict(claim_id=claim.id, verdict='supported', reason='Bound half only.', checks=[
        dict(check_id=row['check_id'], verdict='supported', claim_span=span or claim.text)
        for row in payload['claims'][0]['required_checks']])


@pytest.mark.parametrize('mode', ['ownership_retention', 'share_manage'])
def test_half_supported_compound_cannot_publish_under_current_atomic_contract(mode):
    if mode == 'ownership_retention':
        ownership = 'Items in a personal vault are owned by the individual user.'
        retention = 'When a member is removed, the user keeps personal vault items.'
        original = fact(quote=ownership + ' ' + retention, value=[ownership, retention])
        span = next(row for row in spans(original) if row['quote'] == retention)
        row = draft(original, ownership + ' ' + retention, source_span_ids=[span['span_id']])
        choices = {span['span_id']: span}
    else:
        share = 'Guests can share vaults after accepting the invitation.'
        original = fact(quote=share, value=[share, 'Guests can manage access to vaults.'])
        binding = next(row for row in candidates(original).values() if row['operation'] == 'share')
        row = draft(original, share + ' Guests can manage access to vaults.', observation_id=binding['observation_id'])
        span, choices = {'quote': share}, {}
    claims, gaps = parse_claim_drafts(json.dumps({'claims': [row]}), candidates(original), {original.id},
        'anonymous-use', source_facts=[original], span_candidates=choices)
    assert claims and not gaps
    # An apparently supported review of only the first/retention assertion is
    # the historical bug. New exact-full-assertion checks must reject it.
    review = dict(claim_id=claims[0].id, verdict='supported', reason='Only the bound half is supported.', checks=[
        dict(check_id=item['check_id'], verdict='supported', claim_span=span['quote'])
        for item in review_payload(claims, SimpleNamespace(facts=[original], sources=[]), review_version=3)['claims'][0]['required_checks']])
    audited = audit_report_claims(claims, [review], SimpleNamespace(facts=[original]),
        [SimpleNamespace(allowed_fact_ids=[original.id])], review_version=3)
    assert audited[0].status != 'supported'


def selection(**updates):
    row = dict(question_id=QUESTION['question_id'], status='partial', claim_ids=['rule'],
               resolution='clarification', conclusion='depends', missing_fields=FIELDS,
               reason='Untrusted prose says an unpublished capability exists.')
    return row | updates


def rule_claim():
    original = fact(quote='Members permanently deleting their personal account lose all vault data.')
    span = spans(original)[0]
    from packages.research.evidence.report_claims import ReportClaim
    claim = ReportClaim(id='rule', **draft(original, original.quote), source_span_bindings=[span])
    return original, claim.model_dump(mode='json')


def parse3(row=None, claims=None, facts=None, **kwargs):
    original, claim = rule_claim()
    return parse_answer_coverage(json.dumps({'version': 3, 'answers': [row or selection()]}), [QUESTION],
        {c['id'] for c in (claims or [claim])}, claims=claims or [claim], facts=facts or [original], **kwargs)[0]


def test_v3_materializes_full_fact_and_four_fixed_questions_without_fake_source_spans():
    original, claim = rule_claim()
    record = parse3()
    assert record.status == 'partial', record.reason
    assert record.binding_version == 3
    assert record.answer.startswith(claim['text'] + '\n')
    assert '请确认具体操作' in record.answer and '数据归属' in record.answer
    assert '保留副本' in record.answer and '访问路径' in record.answer
    assert [(s.claim_id, s.quote) for s in record.evidence_spans] == [('rule', claim['text'])]
    assert 'unpublished' not in record.reason
    assert '依据1条已发表主张' in record.reason and '部分回答' in record.reason
    assert '需澄清' in record.reason and all(label in record.reason for label in ['具体操作', '数据归属', '保留副本', '访问路径'])
    assert 'rule' not in record.reason and 'status=' not in record.reason
    assert not coverage_resolution_reasons(record, [claim], required_binding_version=3, facts=[original])


@pytest.mark.parametrize('updates', [
    {'missing_fields': FIELDS[:-1]}, {'missing_fields': FIELDS + ['invented']},
    {'missing_fields': FIELDS + [FIELDS[0]]}, {'claim_ids': []},
    {'answer': 'Please confirm inputs. Users keep all data.'}, {'question': 'changed'},
    {'resolution': 'direct'}, {'resolution': 'conditional'}, {'status': 'answered'},
])
def test_v3_rejects_missing_inputs_free_facts_and_non_clarification_shortcuts(updates):
    assert parse3(selection(**updates)).status == 'unverified'


@pytest.mark.parametrize('change', ['answer', 'spans', 'fields', 'version'])
def test_v3_replay_rejects_materialized_record_tampering(change):
    original, claim = rule_claim()
    record = parse3()
    assert record.status == 'partial'
    updates = {'answer': record.answer + ' Another fact.'} if change == 'answer' else (
        {'evidence_spans': ()} if change == 'spans' else (
            {'missing_fields': tuple(FIELDS[:-1])} if change == 'fields' else {'binding_version': 2}))
    assert coverage_resolution_reasons(record.model_copy(update=updates), [claim],
        required_binding_version=3, facts=[original])


def test_precise_missing_quote_branches_are_partial_and_snapshot_bound():
    from test_missing_price_answers import answer, price_case
    from test_incomplete_quote_answers import usage_case
    detail, snapshot, _ = price_case(money=False)
    current = answer(detail, snapshot)['q-price']
    detail, usage = usage_case()
    targeted = answer(detail, usage, 'Example Product Usage plan 本月2300万次请求，账单准确是多少美元？')['q-price']
    assert current['status'] == targeted['status'] == 'partial'
    assert all(row['resolution'] == 'insufficient' and row['conclusion'] == 'unknown'
               and row['basis_snapshot_id'] for row in [current, targeted])


@pytest.mark.parametrize('punctuation', ['; ', '，', ' and '])
def test_explicit_question_plans_flatten_atoms_without_splitting_on_punctuation(punctuation):
    from packages.agents.writer.dimension_writer import parse_question_claim_plans
    texts = ['Organizations own collections' + punctuation + 'including archived collections.',
             'After removal, personal vault items remain with the user.']
    original = fact(quote=' '.join(texts), value=texts)
    choices = {row['span_id']: row for row in spans(original)}
    rows = [draft(original, text, source_span_ids=[next(row['span_id'] for row in choices.values()
            if row['quote'] == text)]) for text in texts]
    response = json.dumps({'question_plans': [dict(question_id=QUESTION['question_id'],
                          atoms=rows, missing_fields=FIELDS)]})
    claims, gaps, plans = parse_question_claim_plans(response, [QUESTION], candidates(original),
        {original.id}, 'plan-use', source_facts=[original], span_candidates=choices)
    assert [claim.text for claim in claims] == texts and not gaps
    assert plans[0]['claim_ids'] == [claim.id for claim in claims]
    assert plans[0]['missing_fields'] == FIELDS


def test_invalid_atom_and_repeated_background_do_not_consume_other_question_capacity():
    from packages.agents.writer.dimension_writer import parse_question_claim_plans
    original = fact(quote='Organizations own collections.')
    span = spans(original)[0]
    row = draft(original, original.quote, source_span_ids=[span['span_id']])
    other = fact('other', quote='Basic supports five members.')
    other_span = spans(other)[0]
    second = draft(other, other.quote, source_span_ids=[other_span['span_id']])
    questions = [dict(question_id='one', question='Who owns collections?'),
                 dict(question_id='two', question='How many members?')]
    response = json.dumps({'question_plans': [dict(question_id='one', atoms=[row] * 8 + [dict(row, text='')], missing_fields=[]),
        dict(question_id='two', atoms=[second], missing_fields=[])]})
    claims, gaps, plans = parse_question_claim_plans(response, questions, {}, {original.id, other.id}, 'plan-use',
        source_facts=[original, other], span_candidates={span['span_id']: span, other_span['span_id']: other_span})
    assert len(claims) == 2 and {claim.text for claim in claims} == {original.quote, other.quote}
    assert 'claim_candidate_invalid' in gaps and all(plan['claim_ids'] for plan in plans)


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', [None, 'partial_check', 'drop_check', 'drop_policy', 'audit_version', 'record_version', 'append_fact', 'reason_only'])
async def test_real_writer_review_save_and_final_qa_replay_atomic_clarification(monkeypatch, mutation):
    from datetime import UTC, datetime
    from pydantic import HttpUrl, TypeAdapter
    from claim_review_fixture import expand_prompt_payload, supported_review, sent_source_span_id
    from test_question_retrieval import research_case
    from test_writer_question_delivery import service_for
    from packages.agents.qa.evidence_alignment import audit_dimension_claims
    from packages.agents.writer.dimension_writer import render_dimension_report
    from packages.research.evidence.snapshot import seal_snapshot
    from packages.schema.models import DecisionBrief

    ownership = 'Items saved in a personal vault are owned by the individual user.'
    retention = 'When a member is removed from an organization, the user keeps all items in their personal vault.'
    question = 'Example Product：把离职同事删掉后，他保存的密码还会留下吗？'
    detail, _ = research_case([ownership, retention], question=question)
    detail.created_at = detail.updated_at = datetime.now(UTC)
    detail.plan.competitors = ['Example Product']
    detail.plan.dimensions = ['feature']
    detail.plan.decision_brief = DecisionBrief(decision_question=question)
    for source in detail.raw_sources:
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
    snapshot = seal_snapshot(detail, phase='analysis', canonical_documents={})
    service, record = service_for(detail)
    calls = []
    malicious = 'The unpublished role definition grants access to all resources.'

    async def model(_record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs['user'].split('\nJSON:\n', 1)[1]))
        calls.append((kwargs['name'], payload))
        if kwargs['name'] == 'dimension_claim_writer':
            assert payload['required_clarifications'][0]['missing_fields'] == FIELDS
            atoms = [dict(text=row['quote'], kind='fact', competitor='Example Product', dimension='feature',
                fact_ids=[row['id']], source_ids=[row['source_id']], source_span_ids=[sent_source_span_id(row)])
                for row in payload['evidence_view']['facts']]
            return json.dumps({'question_plans': [dict(question_id=q['question_id'], atoms=atoms,
                               missing_fields=FIELDS) for q in payload['questions']]})
        if kwargs['name'] == 'dimension_claim_review':
            assert 'parent facts' in payload['support_policy']
            assert 'atomicity' in payload['atom_review_policy']
            reviews = []
            for atom in payload['claims']:
                assert len(atom['source_span_bindings']) == 1 and '请确认' not in atom['text']
                assert atom['support_quotes'] == [atom['source_span_bindings'][0]['quote']]
                assert {row['kind'] for row in atom['required_checks']} == {'full_assertion_support', 'atomicity'}
                reviews.append(supported_review(atom))
            return json.dumps({'reviews': reviews})
        assert kwargs['name'] in {'dimension_answer_coverage', 'dimension_answer_review'}
        if kwargs['name'] == 'dimension_answer_review':
            proposal = payload['proposed_answers'][0]
            assert proposal['proposed_reason'] == malicious
            assert '请确认' in proposal['answer']
            assert len(proposal['evidence_spans']) == 2
        return json.dumps({'version': 3, 'answers': [dict(question_id=q['question_id'], status='partial',
            resolution='clarification', conclusion='depends', missing_fields=FIELDS,
            claim_ids=[c['id'] for c in payload['claims']], reason=malicious) for q in payload['questions']]})

    monkeypatch.setattr(service, '_trace_llm_text', model)
    monkeypatch.setattr('packages.agents.writer.question_retrieval.get_local_provider_from_env', lambda *_: None)
    await service._real_writer_step(record)
    assert [name for name, _ in calls] == ['dimension_claim_writer', 'dimension_claim_review',
        'dimension_claim_review', 'dimension_answer_coverage', 'dimension_answer_review']
    assert all(len(payload['claims']) == 1 for name, payload in calls if name == 'dimension_claim_review')
    audit = detail.report_dimension_audits[0]
    assert audit.claim_review_version == audit.answer_binding_version == 3
    assert len(audit.claims) == 2 and all(row.status == 'supported' for row in audit.claims)
    answer = audit.answer_coverage[0]
    assert answer.status == 'partial', answer.reason
    assert '请确认' in answer.answer and malicious not in answer.reason
    assert '依据2条已发表主张' in answer.reason and '部分回答' in answer.reason
    assert all(cid not in answer.reason for cid in answer.claim_ids)
    assert len(answer.evidence_spans) == 2 and '请确认' not in ''.join(s.quote for s in answer.evidence_spans)
    audit = type(audit).model_validate_json(audit.model_dump_json())
    if mutation in {'partial_check', 'drop_check'}:
        item = audit.claims[0]
        checks = item.review.checks
        checks = checks[:-1] if mutation == 'drop_check' else (
            checks[0].model_copy(update={'claim_span': item.claim.text[:12]}), *checks[1:])
        item = item.model_copy(update={'review': item.review.model_copy(update={'checks': checks})})
        audit = audit.model_copy(update={'claims': (item, *audit.claims[1:])})
    elif mutation == 'drop_policy':
        audit = audit.model_copy(update={'claim_review_version': None})
    elif mutation == 'audit_version':
        audit = audit.model_copy(update={'answer_binding_version': 2})
    elif mutation == 'record_version':
        answer = answer.model_copy(update={'binding_version': 2})
    elif mutation == 'append_fact':
        answer = answer.model_copy(update={'answer': answer.answer + ' All accounts can manage access.'})
    elif mutation == 'reason_only':
        answer = answer.model_copy(update={'answer': '\n'.join(s.quote for s in answer.evidence_spans),
                                         'reason': '请确认具体操作、数据归属、是否保留副本、访问路径？'})
    audit = audit.model_copy(update={'answer_coverage': (answer,)})
    detail.report_dimension_audits = [audit]
    detail.report_md = render_dimension_report(detail, [audit], snapshot=snapshot)
    issues = audit_dimension_claims(service, record, snapshot, producer_verified=True)
    assert bool(issues) == (mutation is not None), issues


@pytest.mark.parametrize('version', [True, 3.0, '3', 999])
def test_live_v3_requires_exact_integer_version(version):
    original, claim = rule_claim()
    result = parse_answer_coverage(json.dumps({'version': version, 'answers': [selection()]}), [QUESTION],
        {'rule'}, claims=[claim], facts=[original], required_binding_version=3)[0]
    assert result.status == 'unverified'


def test_v2_historical_review_is_not_retroactively_required_to_have_v3_checks():
    original, row = rule_claim()
    from packages.research.evidence.report_claims import ReportClaim
    claim = ReportClaim.model_validate(row)
    review = dict(claim_id=claim.id, verdict='supported', reason='Historical review.')
    view, boundaries = SimpleNamespace(facts=[original]), [SimpleNamespace(allowed_fact_ids=[original.id])]
    assert audit_report_claims([claim], [review], view, boundaries)[0].status == 'supported'
    assert audit_report_claims([claim], [review], view, boundaries, review_version=3)[0].status == 'rejected'


def test_v3_does_not_extract_free_date_questions_but_can_select_complete_source_date_rules():
    from packages.research.evidence.source_exceptions import _missing_question_inputs
    assert not _missing_question_inputs('Can a guest access a workspace created before January 2020?')
    claims = [dict(id='dated', text='Guests can access workspaces created before January 2020; later workspaces require a paid plan.')]
    row = dict(question_id='date', status='answered', resolution='conditional', conclusion='depends',
               claim_ids=['dated'], missing_fields=[], reason='Preserves both dated source branches.')
    question = [dict(question_id='date', question='Can guests access a workspace?')]
    answer = parse_answer_coverage(json.dumps({'version': 3, 'answers': [row]}), question, {'dated'}, claims=claims)[0]
    assert answer.status == 'answered' and answer.answer == claims[0]['text']
    row.update(status='partial', resolution='clarification', missing_fields=['creation_date'])
    assert parse_answer_coverage(json.dumps({'version': 3, 'answers': [row]}), question, {'dated'}, claims=claims)[0].status == 'unverified'


def test_saved_v3_reason_cannot_gain_unpublished_product_facts_on_replay():
    original, claim = rule_claim()
    record = parse3()
    changed = record.model_copy(update={'reason': 'An unpublished role can manage all accounts.'})
    assert 'answer_reason_changed' in coverage_resolution_reasons(changed, [claim], facts=[original])


@pytest.mark.parametrize('version', [None, 2, 3.0, True, 999])
def test_explicit_v3_requirement_cannot_fall_back_to_legacy(version):
    original, claim = rule_claim()
    record = parse3().model_copy(update={'binding_version': version})
    assert coverage_resolution_reasons(record, [claim], required_binding_version=3, facts=[original])


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'wrong', 'field', 'malformed_id'])
def test_question_plans_reject_missing_duplicate_wrong_question_and_unknown_fields(mutation):
    from packages.agents.writer.dimension_writer import parse_question_claim_plans
    original, claim = rule_claim()
    span = spans(original)[0]
    plan = dict(question_id=QUESTION['question_id'], atoms=[draft(original, original.quote, source_span_ids=[span['span_id']])],
                missing_fields=FIELDS)
    rows = [] if mutation == 'missing' else [plan]
    if mutation == 'duplicate':
        rows *= 2
    elif mutation == 'wrong':
        plan['question_id'] = 'not-current'
    elif mutation == 'malformed_id':
        plan['question_id'] = []
    elif mutation == 'field':
        plan['missing_fields'] = FIELDS + ['new_product_fact']
    try:
        claims, gaps, _ = parse_question_claim_plans(json.dumps({'question_plans': rows}), [QUESTION], {},
            {original.id}, 'use', source_facts=[original], span_candidates={span['span_id']: span})
    except ValueError:
        return
    assert not claims and gaps


def test_operation_atoms_keep_original_checks_in_addition_to_complete_assertion_checks():
    original = fact(quote='Guests can share documents only after signing in and accepting the invitation.')
    binding = next(row for row in candidates(original).values() if row['operation'] == 'share')
    claims, gaps = parse_claim_drafts(json.dumps({'claims': [draft(original, original.quote,
        observation_id=binding['observation_id'])]}), candidates(original), {original.id}, 'use', source_facts=[original])
    assert len(claims) == 1 and not gaps
    payload = review_payload(claims, SimpleNamespace(facts=[original], sources=[]), review_version=3)
    checks = payload['claims'][0]['required_checks']
    assert {'atomicity', 'full_assertion_support', 'prerequisite', 'operation'} <= {r['kind'] for r in checks}
    from claim_review_fixture import supported_review
    review = supported_review(payload['claims'][0])
    view, boundaries = SimpleNamespace(facts=[original]), [SimpleNamespace(allowed_fact_ids=[original.id])]
    assert audit_report_claims(claims, [review], view, boundaries, review_version=3)[0].status == 'supported'
    prerequisite = next(r['check_id'] for r in checks if r['kind'] == 'prerequisite')
    review['checks'] = [row for row in review['checks'] if row['check_id'] != prerequisite]
    rejected = audit_report_claims(claims, [review], view, boundaries, review_version=3)[0]
    assert rejected.status == 'rejected' and 'operation_checks_incomplete' in rejected.rule_reasons


def test_no_manage_observation_cannot_be_changed_into_a_non_operation_source_span():
    share = 'Guests can share vaults after accepting the invitation.'
    manage = 'Guests can manage access to vaults.'
    original = fact(quote=share, value=[share, manage])
    span = next(row for row in spans(original) if row['quote'] == manage)
    claims, gaps = parse_claim_drafts(json.dumps({'claims': [draft(original, manage,
        source_span_ids=[span['span_id']])]}), candidates(original), {original.id}, 'use',
        source_facts=[original], span_candidates={span['span_id']: span})
    assert not claims and 'operation_binding_required' in gaps


def test_v3_clarification_counts_fixed_questions_against_the_1200_character_limit():
    original, claim = rule_claim()
    claims = [claim | {'id': str(index), 'text': claim['text'] + 'x' * (590 - len(claim['text']))} for index in range(2)]
    answer = parse3(selection(claim_ids=['0', '1']), claims=claims, facts=[original])
    assert answer.status == 'unverified' and not answer.answer


def test_v3_can_deliver_a_genuine_operation_rule_with_server_clarification():
    from packages.agents.writer.answer_coverage import is_qualified_partial_clarification
    original = fact(quote='Guests can share documents only after signing in.')
    bound = next(row for row in candidates(original).values() if row['operation'] == 'share')
    claims, _ = parse_claim_drafts(json.dumps({'claims': [draft(original, original.quote,
        observation_id=bound['observation_id'])]}), candidates(original), {original.id}, 'operation-use', source_facts=[original])
    question = dict(question_id='operation-question', question='Example Product：把访客删掉后，还能分享文档吗？')
    row = selection(question_id=question['question_id'], claim_ids=[claims[0].id],
                    missing_fields=['actual_action', 'data_ownership', 'retained_copy', 'access_path'])
    # This question asks an outcome without the finite ownership/copy/path words,
    # so its current conservative contract requires only the concrete action.
    from packages.research.evidence.source_exceptions import _missing_question_inputs
    row['missing_fields'] = _missing_question_inputs(question['question'])
    published = [claims[0].model_dump(mode='json')]
    record = parse_answer_coverage(json.dumps({'version': 3, 'answers': [row]}), [question], {claims[0].id},
        claims=published, facts=[original], required_binding_version=3)[0]
    assert record.status == 'partial', record.reason
    assert is_qualified_partial_clarification(record, published, facts=[original])


def test_readiness_export_really_preserves_v3_in_both_version_fields(tmp_path):
    from test_agent_readiness_export import artifact, api
    folder = artifact(tmp_path)
    path = folder / 'run.json'
    run = json.loads(path.read_text())
    audit = run['report_dimension_audits'][0]
    audit['answer_binding_version'] = 3
    audit['claim_review_version'] = 3
    audit['answer_coverage'][0]['binding_version'] = 3
    path.write_text(json.dumps(run))
    episode = api().prepare_readiness([folder], workspace='w')['episodes'][0]
    assert episode['answer_binding_version'] == episode['coverage_binding_version'] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize('first', [None, '{"version":3,"answers":[null]}', '{"version":3,"answers":[5]}'])
async def test_unavailable_first_coverage_response_does_not_crash_independent_review(monkeypatch, first):
    from test_answer_semantic_review import check, selected
    reviewer, (answers, _, _) = await check(monkeypatch, [first, selected(conclusion='no')])
    assert len(reviewer.calls) == 2 and answers[0].status == 'answered'
    payload = json.loads(reviewer.calls[1]['user'].split('\nJSON:\n', 1)[1])
    assert payload['proposed_answers'][0]['status'] == 'unverified'


@pytest.mark.parametrize('field', ['binding_version', 'answer_binding_version', 'claim_review_version'])
@pytest.mark.parametrize('version', [True, 3.0, '3', 999])
def test_persisted_version_fields_do_not_coerce_invalid_json_values(field, version):
    from pydantic import ValidationError
    from packages.research.evidence.answer_coverage_models import ReportAnswerCoverage
    from packages.research.evidence.report_claims import ReportDimensionAudit
    if field == 'binding_version':
        model = ReportAnswerCoverage
        row = dict(QUESTION, status='unverified', reason='No published source rule.', binding_version=version)
    else:
        model = ReportDimensionAudit
        row = dict(competitor='Example Product', dimension='feature', consumption_id='use', **{field: version})
    with pytest.raises(ValidationError):
        model.model_validate_json(json.dumps(row))


@pytest.mark.asyncio
async def test_real_writer_bad_atom_keeps_the_other_questions_valid_published_plan(monkeypatch):
    from datetime import UTC, datetime
    from pydantic import HttpUrl, TypeAdapter
    from claim_review_fixture import expand_prompt_payload, sent_source_span_id, supported_review
    from test_question_retrieval import research_case
    from test_writer_question_delivery import service_for
    from packages.research.evidence.snapshot import seal_snapshot
    from packages.schema.models import DecisionBrief
    ownership = 'Organizations own collections.'
    limit = 'Basic workspace has a maximum of 5 members.'
    question = 'Example Product: Who owns collections?\nExample Product: What is the Basic workspace capacity?'
    detail, _ = research_case([ownership, limit], question=question)
    detail.created_at = detail.updated_at = datetime.now(UTC)
    detail.plan.competitors = ['Example Product']
    detail.plan.dimensions = ['feature']
    detail.plan.decision_brief = DecisionBrief(decision_question=question)
    for source in detail.raw_sources:
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
    seal_snapshot(detail, phase='analysis', canonical_documents={})
    service, record = service_for(detail)
    async def model(_record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs['user'].split('\nJSON:\n', 1)[1]))
        if kwargs['name'] == 'dimension_claim_writer':
            rows = {row['quote']: row for row in payload['evidence_view']['facts']}
            atoms = [dict(text=text, kind='fact', competitor='Example Product', dimension='feature',
                fact_ids=[rows[text]['id']], source_ids=[rows[text]['source_id']],
                source_span_ids=[sent_source_span_id(rows[text])]) for text in [ownership, limit]]
            atoms[0]['fact_ids'] = ['not-sent']
            return json.dumps({'question_plans': [dict(question_id=q['question_id'], atoms=[atom], missing_fields=[])
                for q, atom in zip(payload['questions'], atoms)]})
        if kwargs['name'] == 'dimension_claim_review':
            assert [atom['text'] for atom in payload['claims']] == [limit]
            return json.dumps({'reviews': [supported_review(atom) for atom in payload['claims']]})
        assert kwargs['name'] in {'dimension_answer_coverage', 'dimension_answer_review'}
        return json.dumps({'version': 3, 'answers': [dict(question_id=q['question_id'],
            status='answered' if index else 'unverified', resolution='direct' if index else 'unresolved',
            conclusion='not_applicable' if index else 'unknown', missing_fields=[],
            claim_ids=[payload['claims'][0]['id']] if index else [], reason='The published rule or source gap.')
            for index, q in enumerate(payload['questions'])]})
    monkeypatch.setattr(service, '_trace_llm_text', model)
    monkeypatch.setattr('packages.agents.writer.question_retrieval.get_local_provider_from_env', lambda *_: None)
    await service._real_writer_step(record)
    audit = detail.report_dimension_audits[0]
    assert len(audit.claims) == 1 and audit.claims[0].status == 'supported'
    first, second = audit.answer_coverage
    assert first.status == 'unverified' and not first.claim_ids
    assert second.status == 'answered' and second.answer == limit, second.reason
    assert limit in detail.report_md and 'claim_candidate_invalid' in audit.gaps


@pytest.mark.parametrize('mode', ['operation_as_span', 'unbound_feature', 'matching_operation', 'ordinary_non_operation', 'implicit_main_quote'])
def test_persisted_v3_final_qa_replays_the_same_required_fact_binding_as_live_parser(mode):
    """Exact whole-claim reviews cannot substitute for a legal source binding."""
    from datetime import UTC, datetime
    from claim_review_fixture import supported_review
    from test_question_retrieval import research_case
    from test_writer_question_delivery import service_for
    from packages.agents.qa.evidence_alignment import audit_dimension_claims
    from packages.agents.writer.answer_coverage import research_questions
    from packages.agents.writer.dimension_writer import render_dimension_report
    from packages.research.evidence.answer_models import AnswerBoundary
    from packages.research.evidence.report_claims import AuditedReportClaim, ReportClaim, ReportDimensionAudit
    from packages.research.evidence.snapshot import seal_snapshot
    from packages.schema.models import DecisionBrief

    share = 'Guests can share vaults after accepting the invitation.'
    manage = 'Guests can manage access to vaults.'
    ownership = 'Organizations own collections.'
    is_operation = mode in {'operation_as_span', 'matching_operation'}
    text = manage if is_operation else ownership
    quote = share if mode == 'operation_as_span' else (
        ownership + ' General source background.' if mode == 'unbound_feature' else text)
    question = ('Example Product: Can Guests manage access to vaults?' if is_operation else
                'Example Product: What entity owns collections?')
    detail, _ = research_case([quote], question=question)
    detail.created_at = detail.updated_at = datetime.now(UTC)
    detail.plan.competitors = ['Example Product']
    detail.plan.dimensions = ['feature']
    detail.plan.decision_brief = DecisionBrief(decision_question=question)
    detail.raw_sources[0].metadata['normalized_fields'][0]['evidence_terms'] = [quote, text]
    snapshot = seal_snapshot(detail, phase='analysis', canonical_documents={})
    service, record = service_for(detail)
    original = next(row for row in snapshot.facts if row.field == 'evidence_terms')
    view, use = service._begin_evidence_use(record, agent='writer', competitor='Example Product',
        dimension='feature', fact_ids=[original.id])
    segment = service._writer_segment_context(record, dict(segment_name='dimension:Example Product:feature',
        segment_competitor='Example Product', dimension='feature'), view, use)
    boundaries = [AnswerBoundary.model_validate(row) for row in segment['answer_boundaries']]
    detail.report_answer_boundaries = boundaries
    span = next(row for row in spans(original) if row['quote'] == text)
    row = draft(original, text)
    choices = candidates(original)
    if mode == 'matching_operation':
        binding = next(choice for choice in choices.values() if choice['operation'] == 'manage_access')
        row['observation_id'] = binding['observation_id']
    elif mode not in {'unbound_feature', 'implicit_main_quote'}:
        row['source_span_ids'] = [span['span_id']]
    parsed, gaps = parse_claim_drafts(json.dumps({'claims': [row]}), choices, {original.id}, use.id,
        source_facts=[original], span_candidates={span['span_id']: span})
    invalid = mode in {'operation_as_span', 'unbound_feature'}
    assert bool(parsed) != invalid, gaps
    if mode == 'implicit_main_quote':
        assert parsed[0].source_span_bindings
    if mode == 'operation_as_span':
        assert {candidate['operation'] for candidate in choices.values()} == {'share'}
        assert 'operation_binding_required' in gaps
    row.pop('observation_id', None)
    row.pop('source_span_ids', None)
    if mode == 'matching_operation':
        row['operation_binding'] = binding
    elif mode != 'unbound_feature':
        row['source_span_bindings'] = [span]
    claim = ReportClaim(id='restored-claim', **row)
    payload = review_payload([claim], view, review_version=3)
    review = supported_review(payload['claims'][0])
    # A saved supported status is untrusted. Replay must validate its bindings
    # independently, after the actual JSON and artifact-dependency boundaries.
    published = AuditedReportClaim(claim=claim, status='supported', review=review)
    questions = research_questions(detail, 'Example Product', 'feature')
    coverage = parse_answer_coverage(json.dumps({'version': 3, 'answers': [dict(
        question_id=questions[0]['question_id'], status='answered', resolution='direct',
        conclusion='yes' if is_operation else 'not_applicable', claim_ids=[claim.id], missing_fields=[],
        reason='A complete exact selected source rule.')] }), questions, {claim.id},
        claims=[claim.model_dump(mode='json')], required_binding_version=3, facts=view.facts)
    assert coverage[0].status == 'answered', coverage[0].reason
    audit = ReportDimensionAudit(competitor='Example Product', dimension='feature', consumption_id=use.id,
        claims=[published], answer_coverage=coverage, answer_binding_version=3, claim_review_version=3)
    audit = ReportDimensionAudit.model_validate_json(audit.model_dump_json())
    detail.report_dimension_audits = [audit]
    detail.report_md = render_dimension_report(detail, [audit], snapshot=snapshot)
    service._validate_evidence_use(record, use)
    service._record_evidence_artifact(record, kind='writer', uses=[use],
        payload=service._writer_evidence_artifact_payload(detail))
    issues = audit_dimension_claims(service, record, snapshot, producer_verified=True)
    assert any(issue.metadata.get('claim_audit_reason') == 'claim_review_replay_failed' for issue in issues) == invalid, issues
    if not invalid:
        assert not issues


def test_recorded_price_generator_remains_valid_without_feature_span_under_v3_review():
    from claim_review_fixture import supported_review
    from test_missing_price_answers import price_case
    from packages.agents.writer.dimension_writer import recorded_price_claims
    from packages.research.evidence.answer_guard import evaluate_answer_boundary
    from packages.research.evidence.answer_models import AnswerRequirement
    from packages.research.evidence.views import select_evidence_view
    detail, snapshot, price = price_case()
    view = select_evidence_view(snapshot, agent='writer', competitor=price.competitor, dimension='pricing')
    boundary = evaluate_answer_boundary(view, AnswerRequirement(competitor=price.competitor,
        dimension='pricing', intent='recorded_price', as_of=detail.created_at.date()))
    claims = recorded_price_claims(view, [boundary], 'recorded-price-use', 'en')
    assert claims and not claims[0].source_span_bindings and claims[0].operation_binding is None
    payload = review_payload(claims, view, review_version=3)
    audited = audit_report_claims(claims, [supported_review(row) for row in payload['claims']],
                                  view, [boundary], review_version=3)
    assert all(item.status == 'supported' for item in audited), audited
