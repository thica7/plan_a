"""Exact sent source spans; transport fixtures do not measure semantic accuracy."""

import importlib
import json
from types import SimpleNamespace

import pytest
from test_literal_non_operation import candidates, draft, fact
from test_question_retrieval import research_case
from test_source_exception_closure import ACCESS, AUTH, facts, item

from packages.agents.writer.dimension_writer import parse_claim_drafts, review_payload
from packages.agents.writer.question_retrieval import retrieve_question_facts
from packages.research.evidence.report_claims import audit_report_claims, claim_rule_reasons
from packages.research.evidence.snapshot_models import canonical_json


def spans(original):
    module = importlib.import_module('packages.research.evidence.source_spans')
    return module.source_span_candidates(original)


def parse_bound(original, text, selected=None, *, originals=None, sent=None):
    selected = selected if selected is not None else spans(original)[:1]
    row = draft(original, text, source_span_ids=[span['span_id'] for span in selected])
    return parse_claim_drafts(json.dumps({'claims': [row]}), candidates(original),
        sent or {original.id}, 'span-use', source_facts=originals or [original],
        span_candidates={span['span_id']: span for span in selected})


@pytest.mark.asyncio
@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('competition', ['count', 'bytes'])
async def test_each_question_keeps_a_complete_original_under_other_question_pressure(reverse, competition):
    quota = 'Basic organizations support five members and four collections.'
    padding = ' Independent source condition remains applicable.' * (25 if competition == 'bytes' else 0)
    lifecycle = [f'Organizations own all collections. Removal condition {index}.' + padding
                 for index in range(9)]
    questions = ['Example Product: Can Basic support seven members and six collections?',
                 'Example Product: If we remove a coworker, will saved passwords remain?']
    detail, snap = research_case([quota, *lifecycle], question='\n'.join(questions[::-1] if reverse else questions))
    selected, diagnostic = await retrieve_question_facts(detail, snap, 'Example Product', 'feature', mode='lexical')
    quota_id = next(f.id for f in snap.facts if f.field == 'evidence_terms' and f.quote == quota)
    assert quota_id in selected
    assert all(row['selected_fact_ids'] for row in diagnostic['questions'])
    assert len(selected) <= 8 and diagnostic['selected_original_bytes'] <= 14000
    assert any(row['missing_core_fact_ids'] for row in diagnostic['questions'])


def test_chinese_non_operation_translation_uses_an_exact_sent_span_and_normal_review():
    original = fact(quote='Members can edit documents. Organizations own all collections.',
                    value=['Organizations own all collections.'])
    selected = [span for span in spans(original) if span['quote'] == 'Organizations own all collections.'][:1]
    claims, gaps = parse_bound(original, '组织拥有所有集合。', selected)
    assert len(claims) == 1 and not gaps
    claim = claims[0]
    assert claim.source_span_bindings[0].quote == selected[0]['quote']
    view = SimpleNamespace(facts=[original], sources=[])
    boundary = [SimpleNamespace(allowed_fact_ids=[original.id])]
    assert audit_report_claims(claims, [], view, boundary)[0].status == 'unreviewed'
    assert audit_report_claims(claims, [dict(claim_id=claim.id, verdict='uncertain', reason='Unknown.')], view, boundary)[0].status == 'rejected'
    payload = review_payload(claims, view)
    assert payload['claims'][0]['source_span_bindings'][0]['quote'] == selected[0]['quote']
    assert type(claim).model_validate_json(claim.model_dump_json()) == claim


def test_span_ids_cannot_be_forged_or_borrowed_from_an_unsent_value():
    original, other = fact(), fact('other')
    selected = spans(other)[:1]
    claims, gaps = parse_bound(original, '组织拥有所有集合。', selected)
    assert not claims and 'claim_candidate_invalid' in gaps
    own = spans(original)[0]
    forged = {**own, 'quote': 'Administrators own all documents.'}
    claims, gaps = parse_bound(original, '管理员拥有全部文档。', [forged])
    assert not claims and 'claim_candidate_invalid' in gaps


def test_complete_conditional_group_has_no_cut_sentence_candidate():
    original = facts(item(AUTH))[0]
    choices = spans(original)
    assert any(row['quote'] == AUTH for row in choices)
    assert not any(row['quote'].startswith('- Removing') for row in choices)
    assert not any(row['quote'].endswith('account recovery') for row in choices)


@pytest.mark.parametrize('text', ['成员可以编辑文档。', '成员可以分享文档。'])
def test_non_operation_span_never_replaces_an_operation_observation(text):
    original = fact()
    claims, gaps = parse_bound(original, text)
    assert not claims and 'operation_binding_required' in gaps


def scoped(original, page):
    qualifiers = original.qualifiers | {'source_scope': dict(captured_page_id=page,
        source_url='https://example.test/' + page, raw_source_id=original.source_id,
        context={'role': None, 'plan': None}, operations=[])}
    return original.model_copy(update={'qualifiers_json': canonical_json(qualifiers)})


def test_value_login_span_discovers_unsent_exception_instead_of_using_unrelated_delete_quote():
    deletion = 'Deleting an account is permanent and deletes all vault data.'
    base, auth = facts(item(deletion, value={'status': 'documented', 'evidence_terms': [deletion, ACCESS]}), item(AUTH, 'auth'))
    base = scoped(base.model_copy(update={'source_id': 'general'}), 'general')
    auth = scoped(auth.model_copy(update={'source_id': 'specific'}), 'specific')
    selected = [row for row in spans(base) if row['quote'] == ACCESS][:1]
    claims, gaps = parse_bound(base, ACCESS, selected)
    assert claims and not gaps
    view = SimpleNamespace(facts=[base, auth])
    reasons = claim_rule_reasons(claims[0], view, [SimpleNamespace(allowed_fact_ids=[base.id])])
    assert 'source_exception_unresolved' in reasons
    # A genuine bound deletion observation does not inherit a sibling login rule.
    selected = [row for row in spans(base) if row['quote'] == deletion][:1]
    safe, _ = parse_bound(base, deletion, selected)
    assert 'source_exception_unresolved' not in claim_rule_reasons(safe[0], view,
        [SimpleNamespace(allowed_fact_ids=[base.id])])


@pytest.mark.parametrize('choice', ['omitted', 'empty', 'forged'])
def test_current_transport_cannot_fall_back_to_a_parent_value_when_span_selection_is_absent(choice):
    deletion = 'Deleting an account is permanent and deletes all vault data.'
    original = fact(quote=deletion, value=[deletion, ACCESS])
    row = draft(original, ACCESS)
    if choice != 'omitted':
        row['source_span_ids'] = [] if choice == 'empty' else ['source-span-forged']
    claims, gaps = parse_claim_drafts(json.dumps({'claims': [row]}), {}, {original.id}, 'current-transport',
        source_facts=[original], span_candidates={span['span_id']: span for span in spans(original)})
    assert not claims and 'claim_candidate_invalid' in gaps


@pytest.mark.parametrize('text', [
    '组织不拥有集合。', '管理员拥有所有集合。', '组织拥有所有文档。',
    '组织拥有所有集合，而且成员保留所有个人密码。',
])
def test_semantic_review_can_reject_a_valid_span_with_wrong_translation_or_added_subclaim(text):
    original = fact(quote='Members can edit documents. Organizations own all collections.',
                    value=['Organizations own all collections.'])
    selected = [span for span in spans(original) if span['quote'] == 'Organizations own all collections.'][:1]
    claims, gaps = parse_bound(original, text, selected)
    assert claims and not gaps
    audited = audit_report_claims(claims, [dict(claim_id=claims[0].id,
        verdict='unsupported', reason='The bound support member does not support this assertion.')],
        SimpleNamespace(facts=[original]), [SimpleNamespace(allowed_fact_ids=[original.id])])
    assert audited[0].status == 'rejected'


@pytest.mark.parametrize('changed', [
    AUTH.replace('account recovery and', 'account recovery or'),
    AUTH.replace('using account recovery and ', ''),
    AUTH.replace('before being removed', 'after being removed'),
    AUTH.replace('member accounts', 'administrator accounts'),
])
def test_actual_bound_auth_group_keeps_and_timing_recovery_and_actor_guards(changed):
    original = facts(item(AUTH))[0]
    claims, gaps = parse_bound(original, ' '.join(changed.split()))
    assert claims and not gaps
    assert claim_rule_reasons(claims[0], SimpleNamespace(facts=[original]),
        [SimpleNamespace(allowed_fact_ids=[original.id])])


def test_complete_bound_auth_group_passes_while_arbitrary_two_fact_binding_is_rejected():
    original = facts(item(AUTH))[0]
    claims, gaps = parse_bound(original, ' '.join(AUTH.split()))
    assert claims and not gaps
    assert not claim_rule_reasons(claims[0], SimpleNamespace(facts=[original]),
        [SimpleNamespace(allowed_fact_ids=[original.id])])
    unrelated = fact('unrelated', quote='Organizations own all collections.')
    bindings = [spans(original)[0], spans(unrelated)[0]]
    row = draft(original, ' '.join(AUTH.split()), fact_ids=[original.id, unrelated.id],
        source_ids=[original.source_id, unrelated.source_id], source_span_ids=[x['span_id'] for x in bindings])
    claims, gaps = parse_claim_drafts(json.dumps({'claims': [row]}), {},
        {original.id, unrelated.id}, 'two-facts', source_facts=[original, unrelated],
        span_candidates={span['span_id']: span for span in bindings})
    assert not claims and 'claim_candidate_invalid' in gaps


@pytest.mark.asyncio
@pytest.mark.parametrize('qa_mutation', [None, 'answer', 'missing_span', 'missing_v2', 'missing_rule', 'ordinary_partial', 'core_gap', 'body', 'actual_core'])
async def test_real_writer_transport_reviews_and_persists_chinese_rule_and_clarification(monkeypatch, qa_mutation):
    from datetime import UTC, datetime
    from pydantic import HttpUrl, TypeAdapter
    from claim_review_fixture import supported_review
    from test_writer_question_delivery import service_for
    from packages.research.evidence.snapshot import seal_snapshot
    from packages.schema.models import DecisionBrief

    original = ('Items saved in a personal vault are owned by the individual user. '
                'When a member is removed from an organization, the user keeps all items in their personal vault.')
    question = 'Example Product：把离职同事删掉后，他保存的密码还会留下吗？'
    quotes = ([original + '\n\nMembers can create documents and edit documents and share documents and view documents. '
               + f'Organization-owned records are preserved for {i + 1} years under legal hold condition {i}.'
               for i in range(8)] if qa_mutation == 'actual_core' else [original])
    detail, _ = research_case(quotes, question=question)
    detail.created_at = detail.updated_at = datetime.now(UTC)
    detail.plan.competitors = ['Example Product']
    detail.plan.dimensions = ['feature']
    detail.plan.decision_brief = DecisionBrief(decision_question=question)
    for source in detail.raw_sources:
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
    seal_snapshot(detail, phase='analysis', canonical_documents={})
    service, record = service_for(detail)
    calls = []
    text = ('个人保险库中的条目归个人用户所有；成员被移出组织后保留其个人保险库中的全部条目。'
            '请确认具体操作、数据归属、是否保留副本以及访问路径？')

    async def model(record, **kwargs):
        payload = json.loads(kwargs['user'].split('\nJSON:\n', 1)[1])
        def resolve(value):
            if isinstance(value, dict):
                if set(value) == {'text_ref'}:
                    return payload['text_sets'][value['text_ref']]
                return {key: resolve(child) for key, child in value.items()}
            if isinstance(value, list):
                return [resolve(child) for child in value]
            return value
        payload = resolve(payload)
        calls.append((kwargs['name'], payload))
        if kwargs['name'] == 'dimension_claim_writer':
            source = payload['evidence_view']['facts'][0]
            assert source['source_span_candidates']
            return json.dumps({'claims': [dict(text=text, kind='fact', competitor='Example Product',
                dimension='feature', fact_ids=[source['id']], source_ids=[source['source_id']],
                source_span_ids=[source['source_span_candidates'][0]['span_id']])]})
        if kwargs['name'] == 'dimension_claim_review':
            assert payload['claims'][0]['source_span_bindings'][0]['quote'] == original
            return json.dumps({'reviews': [supported_review(row) for row in payload['claims']]})
        assert kwargs['name'] in {'dimension_answer_coverage', 'dimension_answer_review'}
        assert payload['claims'][0]['source_span_bindings']
        return json.dumps({'version': 2, 'answers': [dict(question_id=q['question_id'], status='partial',
            claim_ids=[payload['claims'][0]['id']], resolution='clarification', conclusion='depends',
            missing_fields=['actual_action', 'data_ownership'], reason='The action and ownership need confirmation.')
            for q in payload['questions']]})

    monkeypatch.setattr(service, '_trace_llm_text', model)
    monkeypatch.setattr('packages.agents.writer.question_retrieval.get_local_provider_from_env', lambda *_: None)
    diagnostics = []
    if qa_mutation == 'actual_core':
        from packages.agents.writer import question_retrieval
        retrieve = question_retrieval.retrieve_question_facts
        async def lexical(*args, **kwargs):
            selected, diagnostic = await retrieve(*args, **{**kwargs, 'mode': 'lexical'})
            diagnostics.append(diagnostic)
            return selected, diagnostic
        monkeypatch.setattr(question_retrieval, 'retrieve_question_facts', lexical)
    await service._real_writer_step(record)
    audit = detail.report_dimension_audits[0]
    assert audit.claims[0].status == 'supported', audit.claims[0]
    assert audit.answer_coverage[0].status == 'partial', audit.answer_coverage[0].reason
    assert audit.answer_coverage[0].answer == text
    assert text in detail.report_md
    assert type(audit).model_validate_json(audit.model_dump_json()) == audit
    assert any(name == 'dimension_answer_review' for name, _ in calls)
    if qa_mutation == 'actual_core':
        diagnostic = diagnostics[0]
        assert len(diagnostic['selected_fact_ids']) == 8 and diagnostic['selected_original_bytes'] <= 14000
        assert not diagnostic['questions'][0]['missing_core_fact_ids']
        actual = next(payload for name, payload in calls if name == 'dimension_claim_writer')
        actual_ids = {row['id'] for row in actual['evidence_view']['facts']}
        assert set(diagnostic['questions'][0]['core_fact_ids']) - actual_ids
        assert 'question_core_context_budget_exceeded' in audit.gaps
    coverage = audit.answer_coverage[0]
    audited_claim = audit.claims[0]
    if qa_mutation == 'answer':
        coverage = coverage.model_copy(update={'answer': coverage.answer + ' Changed.'})
    elif qa_mutation == 'missing_span':
        audited_claim = audited_claim.model_copy(update={'claim': audited_claim.claim.model_copy(
            update={'source_span_bindings': ()})})
    elif qa_mutation == 'missing_v2':
        coverage = coverage.model_copy(update={'binding_version': None})
    elif qa_mutation == 'missing_rule':
        clarification = text.split('。', 1)[1]
        audited_claim = audited_claim.model_copy(update={'claim': audited_claim.claim.model_copy(
            update={'text': clarification})})
        coverage = coverage.model_copy(update={'answer': clarification, 'evidence_spans': (
            coverage.evidence_spans[0].model_copy(update={'quote': clarification}),)})
        detail.report_md = detail.report_md.replace(text, clarification)
    elif qa_mutation == 'ordinary_partial':
        coverage = coverage.model_copy(update={'resolution': 'conditional'})
    elif qa_mutation == 'body':
        detail.report_md = detail.report_md.replace(text, '请稍后补充资料。')
    gaps = audit.gaps + (('question_core_context_budget_exceeded',) if qa_mutation == 'core_gap' else ())
    detail.report_dimension_audits = [audit.model_copy(update={'claims': (audited_claim,),
        'answer_coverage': (coverage,), 'gaps': gaps})]
    # Rebind the deliberately changed producer so these negatives exercise the
    # final rule replay, rather than succeeding solely on stale artifact hashes.
    service._record_evidence_artifact(record, kind='writer', uses=detail.evidence_consumptions,
        payload=service._writer_evidence_artifact_payload(detail))
    _, issues, _ = await service._final_qa_evidence(record)
    blocked = any(issue.metadata.get('claim_audit_reason') in {
        'answer_coverage_incomplete', 'published_answer_missing_or_changed',
        'published_claim_missing_or_changed', 'claim_review_replay_failed'} for issue in issues)
    assert blocked == (qa_mutation is not None), issues
    if qa_mutation is None:
        assert not issues
    await service._real_qa_step(record)
    blocked = any(issue.metadata.get('claim_audit_reason') in {
        'answer_coverage_incomplete', 'published_answer_missing_or_changed',
        'published_claim_missing_or_changed', 'claim_review_replay_failed'} for issue in detail.qa_findings)
    assert blocked == (qa_mutation is not None), detail.qa_findings


def test_candidates_do_not_turn_unrelated_paragraphs_or_oversized_context_into_support():
    ownership = 'Organizations own all collections.'
    login = 'Removed members can still access personal items.'
    original = fact(quote=ownership, value=[ownership + '\n\n' + login])
    choices = spans(original)
    assert not any(ownership in row['quote'] and login in row['quote'] for row in choices)
    assert any(row['quote'] == login for row in choices)
    huge = fact(quote='Organizations own all collections. ' * 65)
    assert not spans(huge)


def test_wrapped_sentence_and_if_continuation_are_never_split_into_unconditional_candidates():
    wrapped = 'Organizations keep member data\nonly while the workspace remains active.'
    conditional = 'If a member is removed,\norganizations keep data only while the workspace remains active.'
    original = fact(quote=wrapped, value=[wrapped, conditional])
    choices = spans(original)
    assert any(row['quote'] == wrapped for row in choices)
    assert any(row['quote'] == conditional for row in choices)
    assert not any(row['quote'] in {'Organizations keep member data', 'If a member is removed,'}
                   for row in choices)


def test_a_supported_review_cannot_publish_a_bound_deletion_with_a_sibling_login_assertion():
    deletion = 'Deleting an account is permanent and deletes all vault data.'
    original = fact(quote=deletion, value=[deletion, ACCESS])
    selected = [row for row in spans(original) if row['quote'] == deletion][:1]
    claims, gaps = parse_bound(original, deletion + ' ' + ACCESS, selected)
    assert claims and not gaps
    audited = audit_report_claims(claims, [dict(claim_id=claims[0].id, verdict='supported',
        reason='Fixture deliberately overclaims support.')], SimpleNamespace(facts=[original]),
        [SimpleNamespace(allowed_fact_ids=[original.id])])
    assert audited[0].status == 'rejected'
    assert 'source_span_assertion_outside_support' in audited[0].rule_reasons


@pytest.mark.parametrize('wrong_scope', [None, 'plan', 'actor'])
def test_exact_value_span_can_bind_a_complete_specific_auth_exception_only_in_its_own_scope(wrong_scope):
    from packages.agents.writer.dimension_writer import operation_claim_selection
    deletion = 'Deleting an account is permanent and deletes all vault data.'
    base, auth = facts(item(deletion, value={'status': 'documented', 'evidence_terms': [deletion, ACCESS]}), item(AUTH, 'auth'))
    base = scoped(base.model_copy(update={'source_id': 'general'}), 'general')
    auth = scoped(auth.model_copy(update={'source_id': 'specific'}), 'specific')
    if wrong_scope == 'plan':
        qualifiers = auth.qualifiers
        qualifiers['source_scope']['context']['plan'] = 'Different plan'
        auth = auth.model_copy(update={'qualifiers_json': canonical_json(qualifiers)})
    elif wrong_scope == 'actor':
        auth = auth.model_copy(update={'quote': AUTH.replace('member accounts', 'editor accounts'),
            'value_json': canonical_json([AUTH.replace('member accounts', 'editor accounts')])})
    selected = [next(row for row in spans(base) if row['quote'] == ACCESS), spans(auth)[0]]
    text = ' '.join((ACCESS + ' ' + AUTH).split())
    row = draft(base, text, fact_ids=[base.id, auth.id], source_ids=[base.source_id, auth.source_id],
        source_span_ids=[span['span_id'] for span in selected])
    claims, gaps = parse_claim_drafts(json.dumps({'claims': [row]}), {}, {base.id, auth.id},
        'exact-pair', source_facts=[base, auth], span_candidates={x['span_id']: x for x in selected})
    if wrong_scope:
        assert not claims and 'claim_candidate_invalid' in gaps
        return
    assert claims and not gaps
    view = SimpleNamespace(facts=[base, auth], sources=[])
    assert not claim_rule_reasons(claims[0], view, [SimpleNamespace(allowed_fact_ids=[base.id, auth.id])])
    assert operation_claim_selection(claims, view, ('read',), {base.id, auth.id}) == claims


@pytest.mark.parametrize('field,value', [('source_id', 'different-source'), ('quote', 'Different original.'),
                                       ('evidence_item_ids', ('different-item',))])
def test_persisted_span_replays_its_full_original_identity(field, value):
    original = fact(quote='Organizations own all collections.')
    claims, gaps = parse_bound(original, '组织拥有所有集合。')
    assert claims and not gaps
    changed = original.model_copy(update={field: value})
    reasons = claim_rule_reasons(claims[0], SimpleNamespace(facts=[changed]),
        [SimpleNamespace(allowed_fact_ids=[original.id])])
    assert 'source_span_binding_mismatch' in reasons


def test_writer_offers_a_value_exception_pair_only_when_both_exact_span_ids_were_sent():
    from packages.agents.writer.dimension_writer import compact_dimension_context
    deletion = 'Deleting an account is permanent and deletes all vault data.'
    base, auth = facts(item(deletion, value={'status': 'documented', 'evidence_terms': [deletion, ACCESS]}), item(AUTH, 'auth'))
    base = scoped(base.model_copy(update={'source_id': 'general'}), 'general')
    auth = scoped(auth.model_copy(update={'source_id': 'specific'}), 'specific')
    view = SimpleNamespace(facts=[base, auth])
    payload, _ = compact_dimension_context({'segment_competitor': 'Example Product', 'dimension': 'feature'},
        view, {base.id, auth.id}, questions=[{'question_id': 'q', 'question': 'Can removed members log in?'}])
    sent_ids = {span['span_id'] for row in payload['evidence_view']['facts'] for span in row.get('source_span_candidates', [])}
    pairs = [row for row in payload.get('source_exception_bindings', []) if row.get('source_span_ids')]
    assert pairs and all(set(row['source_span_ids']) <= sent_ids for row in pairs)
    smaller, _ = compact_dimension_context({'segment_competitor': 'Example Product', 'dimension': 'feature'},
        SimpleNamespace(facts=[base]), {base.id}, questions=[{'question_id': 'q', 'question': 'Can removed members log in?'}])
    assert not smaller.get('source_exception_bindings')


def test_a_short_quote_cannot_hide_the_longer_complete_exception_member_in_its_own_value():
    extended = AUTH + '\n- Revoking access still locks members out until organization access is restored.'
    original = fact(quote=AUTH, value=[AUTH, extended])
    choices = spans(original)
    assert any(row['quote'] == extended for row in choices)
    assert not any(row['quote'] == AUTH for row in choices)


@pytest.mark.asyncio
async def test_question_plan_quote_beats_other_plans_sharing_the_same_parent_context():
    from packages.agents.writer.dimension_writer import compact_dimension_context, compact_prompt_json
    from packages.agents.writer.answer_coverage import research_questions
    from packages.research.evidence.views import select_evidence_view
    from test_question_retrieval import replace_snapshot
    quotes = ['Start a Household organization for six users and unlimited collections.',
              'Basic organizations support five members and four collections.',
              'Unlike Basic organizations, Enterprise organizations offer unlimited users.']
    question = ('Example Product: Can Basic organizations support seven members and six collections?\n'
                'Example Product: If we remove a coworker, will saved passwords remain?')
    detail, snap = research_case([*quotes, *[f'Organizations own all collections. Removal condition {i}.' for i in range(9)]], question=question)
    context = '\n'.join(quotes)
    originals = tuple(f.model_copy(update={'value_json': canonical_json([context])})
                      if f.field == 'evidence_terms' and f.quote in quotes else f for f in snap.facts)
    snap = replace_snapshot(detail, snap, facts=originals)
    selected, _ = await retrieve_question_facts(detail, snap, 'Example Product', 'feature', mode='lexical')
    target = next(f.id for f in snap.facts if f.field == 'evidence_terms' and f.quote == quotes[1])
    view = select_evidence_view(snap, agent='writer', competitor='Example Product', dimension='feature',
        fact_ids=selected, max_bytes=14000)
    payload, _ = compact_dimension_context({'segment_competitor': 'Example Product', 'dimension': 'feature'},
        view, set(selected), max_bytes=12000, questions=research_questions(detail, 'Example Product', 'feature'))
    assert target in {row['id'] for row in payload['evidence_view']['facts']}
    assert len(compact_prompt_json(payload).encode()) <= 12000


def test_discovery_of_same_source_unsent_auth_cannot_grant_support_even_if_claim_copies_it():
    base, auth = facts(item(ACCESS), item(AUTH, 'auth'))
    selected = [row for row in spans(base) if row['quote'] == ACCESS][:1]
    claims, gaps = parse_bound(base, ' '.join((ACCESS + ' ' + AUTH).split()), selected)
    assert claims and not gaps
    reasons = claim_rule_reasons(claims[0], SimpleNamespace(facts=[base]),
        [SimpleNamespace(allowed_fact_ids=[base.id])], available_facts=[base, auth])
    assert 'source_exception_unresolved' in reasons


@pytest.mark.asyncio
async def test_empty_question_exception_selection_does_not_certify_a_new_login_claim():
    from test_question_retrieval import replace_snapshot
    deletion = 'Deleting an account is permanent and deletes all vault data.'
    detail, snap = research_case([deletion, AUTH],
        question='Example Product: If we remove a coworker, will saved passwords remain?')
    base, auth = [row for quote in (deletion, AUTH) for row in snap.facts
                  if row.field == 'evidence_terms' and row.quote == quote]
    base = scoped(base.model_copy(update={'value_json': canonical_json([deletion, ACCESS])}), 'general')
    auth = scoped(auth, 'specific')
    snap = replace_snapshot(detail, snap, facts=(base, auth))
    _, diagnostic = await retrieve_question_facts(detail, snap, 'Example Product', 'feature', mode='lexical')
    assert diagnostic['exception_closure_scope'] == 'question_selection_only'
    assert diagnostic['exception_closure_status'] == 'not_identified'
    assert diagnostic['published_claim_closure_status'] == 'not_evaluated'
    selected = [row for row in spans(base) if row['quote'] == ACCESS][:1]
    claims, gaps = parse_bound(base, ACCESS, selected)
    assert claims and not gaps
    assert 'source_exception_unresolved' in claim_rule_reasons(claims[0], SimpleNamespace(facts=[base]),
        [SimpleNamespace(allowed_fact_ids=[base.id])], available_facts=[base, auth])


def test_a_clarification_suffix_cannot_hide_an_added_factual_access_assertion():
    deletion = 'Deleting an account is permanent and deletes all vault data.'
    original = fact(quote=deletion, value=[deletion, ACCESS])
    selected = [row for row in spans(original) if row['quote'] == deletion][:1]
    text = 'Removed members can still access personally-owned items, please confirm which action?'
    claims, gaps = parse_bound(original, text, selected)
    assert claims and not gaps
    assert 'source_span_assertion_outside_support' in claim_rule_reasons(claims[0],
        SimpleNamespace(facts=[original]), [SimpleNamespace(allowed_fact_ids=[original.id])])


@pytest.mark.asyncio
async def test_required_exception_budget_gap_blocks_a_qualified_clarification_in_final_qa(monkeypatch):
    from datetime import UTC, datetime
    from pydantic import HttpUrl, TypeAdapter
    from claim_review_fixture import sent_source_span_id, supported_review
    from test_source_exception_closure import COPY, LINK
    from test_writer_question_delivery import service_for
    from packages.agents.writer import question_retrieval
    from packages.research.evidence.snapshot import seal_snapshot
    from packages.schema.models import DecisionBrief

    question = 'Example Product：把文件夹取消共享后，其他成员还能访问或保留副本吗？'
    detail, _ = research_case([LINK, *[COPY + f' Independent condition {i}.' for i in range(9)]], question=question)
    detail.created_at = detail.updated_at = datetime.now(UTC)
    detail.plan.competitors = ['Example Product']
    detail.plan.dimensions = ['feature']
    detail.plan.decision_brief = DecisionBrief(decision_question=question)
    for source in detail.raw_sources:
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
    seal_snapshot(detail, phase='analysis', canonical_documents={})
    service, record = service_for(detail)
    retrieve = question_retrieval.retrieve_question_facts
    diagnostics = []

    async def lexical(*args, **kwargs):
        selected, diagnostic = await retrieve(*args, **{**kwargs, 'mode': 'lexical'})
        diagnostics.append(diagnostic)
        return selected, diagnostic

    async def model(record, **kwargs):
        from test_pipeline_projection_contract import expand_text_refs
        payload = expand_text_refs(json.loads(kwargs['user'].split('\nJSON:\n', 1)[1]))
        if kwargs['name'] == 'dimension_claim_writer':
            row = next(row for row in payload['evidence_view']['facts'] if COPY in row['quote'])
            text = row['quote'] + 'Please confirm actual action, data ownership, retained copy choice and access path?'
            return json.dumps({'claims': [dict(text=text, kind='fact', competitor='Example Product',
                dimension='feature', fact_ids=[row['id']], source_ids=[row['source_id']],
                source_span_ids=[sent_source_span_id(row)])]})
        if kwargs['name'] == 'dimension_claim_review':
            return json.dumps({'reviews': [supported_review(row) for row in payload['claims']]})
        assert kwargs['name'] in {'dimension_answer_coverage', 'dimension_answer_review'}
        return json.dumps({'version': 2, 'answers': [dict(question_id=q['question_id'], status='partial',
            claim_ids=[payload['claims'][0]['id']], resolution='clarification', conclusion='depends',
            missing_fields=['actual_action', 'data_ownership', 'retained_copy', 'access_path'],
            reason='The source rule still requires input clarification.') for q in payload['questions']]})

    monkeypatch.setattr(question_retrieval, 'retrieve_question_facts', lexical)
    monkeypatch.setattr(service, '_trace_llm_text', model)
    await service._real_writer_step(record)
    diagnostic = diagnostics[0]['questions'][0]
    assert diagnostic['missing_exception_fact_ids'] and not diagnostic['missing_core_fact_ids']
    audit = detail.report_dimension_audits[0]
    assert audit.claims[0].status == 'supported'
    assert audit.answer_coverage[0].status == 'partial'
    assert 'question_exception_context_budget_exceeded' in audit.gaps
    _, issues, _ = await service._final_qa_evidence(record)
    assert any(issue.severity == 'blocker' and issue.metadata.get('claim_audit_reason') ==
               'answer_coverage_incomplete' for issue in issues)
    await service._real_qa_step(record)
    assert any(issue.severity == 'blocker' and issue.metadata.get('claim_audit_reason') ==
               'answer_coverage_incomplete' for issue in detail.qa_findings)


@pytest.mark.parametrize('separator', [' ', '  ', '\t'])
def test_source_bound_clarification_is_invariant_to_internal_sentence_whitespace(separator):
    original = fact(quote='Organizations own all collections.')
    text = '组织拥有所有集合。' + separator + '请确认具体操作、数据归属、是否保留副本以及访问路径？'
    claims, gaps = parse_bound(original, text)
    assert claims and not gaps
    reasons = claim_rule_reasons(claims[0], SimpleNamespace(facts=[original]),
        [SimpleNamespace(allowed_fact_ids=[original.id])])
    assert not reasons


def test_optional_source_span_schema_matches_legacy_runtime_omission():
    from packages.research.evidence.report_claims import ReportClaim
    schema = ReportClaim.model_json_schema()
    assert 'source_span_bindings' not in schema['required']
    assert 'default' not in schema['properties']['source_span_bindings']
    legacy = ReportClaim(id='legacy', text='原有主张。', kind='fact', competitor='Example Product',
        dimension='feature', fact_ids=['f1'], source_ids=['s1'])
    assert legacy.source_span_bindings == ()
    assert 'source_span_bindings' not in legacy.model_dump(mode='json')


@pytest.mark.parametrize('requirement,gap', [
    ('core_fact_ids', 'question_core_context_budget_exceeded'),
    ('required_exception_fact_ids', 'question_exception_context_budget_exceeded'),
])
@pytest.mark.parametrize('change', ['equivalent', 'quote', 'value', 'qualifiers', 'metadata_only'])
def test_actual_required_original_reconciliation_uses_complete_content_not_ids(requirement, gap, change):
    from test_literal_non_operation import sent_row
    from packages.agents.writer import question_retrieval
    reconcile = getattr(question_retrieval, '_reconcile_question_originals', None)
    assert callable(reconcile), 'Actual core and exception originals need one reconciliation path.'
    original = fact(quote='Organizations own all collections.')
    alias = original.model_copy(update={'id': 'equivalent-sent', 'semantic_id': 'alias'})
    if change == 'quote':
        alias = alias.model_copy(update={'quote': original.quote + ' A legal hold delays removal.'})
    elif change == 'value':
        alias = alias.model_copy(update={'value_json': canonical_json([original.quote, 'A separate condition.'])})
    elif change == 'qualifiers':
        alias = alias.model_copy(update={'qualifiers_json': canonical_json({'plan': 'Different plan'})})
    row = sent_row(alias)
    if change == 'metadata_only':
        row = {'id': original.id, 'source_id': original.source_id}
    retrieval = {'questions': [{'question_id': 'q', 'fact_ids': [original.id], requirement: [original.id],
        'minimum_evidence_missing': False}]}
    report = reconcile(retrieval, [original, alias], [row])
    missing_key = 'missing_core_fact_ids' if requirement == 'core_fact_ids' else 'missing_exception_fact_ids'
    if change == 'equivalent':
        assert gap not in report['gaps']
        assert not report['questions'][0][missing_key]
        assert report['sent_fact_ids'] == [alias.id]
        assert original.id not in report['sent_fact_ids']
    else:
        assert gap in report['gaps']
        assert report['questions'][0][missing_key] == [original.id]


def test_actual_required_original_reconciliation_rejects_an_id_with_changed_sent_content():
    from test_literal_non_operation import sent_row
    from packages.agents.writer import question_retrieval
    reconcile = getattr(question_retrieval, '_reconcile_question_originals', None)
    assert callable(reconcile), 'Actual originals must be checked after compaction.'
    original = fact(quote='Organizations own all collections.')
    row = sent_row(original)
    row['value'] = ['A different unbound assertion.']
    report = reconcile({'questions': [{'question_id': 'q', 'fact_ids': [original.id],
        'core_fact_ids': [original.id], 'required_exception_fact_ids': [original.id]}]}, [original], [row])
    assert set(report['gaps']) == {'question_core_context_budget_exceeded',
                                  'question_exception_context_budget_exceeded'}
    assert not report['sent_fact_ids']
