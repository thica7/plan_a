"""Selected support boundaries; forced verdicts test gates, not model entailment."""

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from claim_review_fixture import expand_prompt_payload, supported_review
from test_literal_non_operation import candidates, draft, fact
from test_question_retrieval import research_case
from test_source_span_binding import spans
from test_writer_question_delivery import service_for

from packages.agents.qa.evidence_alignment import audit_dimension_claims
from packages.agents.writer.dimension_writer import parse_claim_drafts, render_dimension_report, review_payload
from packages.research.evidence.report_claims import (
    AuditedReportClaim, ReportClaim, ReportDimensionAudit, audit_report_claims,
)
from packages.research.evidence.snapshot import seal_snapshot
from packages.schema.models import DecisionBrief


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    import socket
    def denied(*args, **kwargs):
        raise AssertionError('network is forbidden in selected-support tests')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)
    monkeypatch.setattr('packages.agents.writer.question_retrieval.get_local_provider_from_env', lambda *_: None)

SHARE = 'Guests can share vaults after accepting the invitation.'
MANAGE = 'Guests can manage access to vaults.'
C180_FIXTURE = Path(__file__).with_name('fixtures') / 'bound_claim_support_c180.json'


def bound_claim(original, text, operation='share'):
    binding = next(row for row in candidates(original).values() if row['operation'] == operation)
    claims, gaps = parse_claim_drafts(json.dumps({'claims': [draft(original, text,
        observation_id=binding['observation_id'])]}), candidates(original), {original.id}, 'bound-use',
        source_facts=[original], span_candidates={})
    assert len(claims) == 1 and not gaps
    return claims[0]


def force_supported(claim, view):
    return supported_review(review_payload([claim], view, review_version=3)['claims'][0])


def replay(claim, original, *, version=3):
    view = SimpleNamespace(facts=[original], sources=[])
    review = supported_review(review_payload([claim], view, review_version=version)['claims'][0])
    return audit_report_claims([claim], [review], view,
        [SimpleNamespace(allowed_fact_ids=[original.id])], review_version=version)[0]


@pytest.mark.parametrize('path', ['replay', 'final_qa'])
def test_actual_c180_saved_full_supported_review_is_rejected_by_replay_and_final_qa(path):
    from packages.research.evidence.snapshot_models import EvidenceFact
    fixture = json.loads(C180_FIXTURE.read_text())
    saved = AuditedReportClaim.model_validate(fixture['audited_claim'])
    original = EvidenceFact.model_validate(fixture['fact'])
    assert saved.claim.id == 'claim-c1806d32c0c66ae561d3'
    view = SimpleNamespace(facts=[original], sources=[])
    result = audit_report_claims([saved.claim], [saved.review], view,
        [SimpleNamespace(allowed_fact_ids=[original.id])], review_version=3)[0]
    if path == 'replay':
        assert result.status == 'rejected'
        assert 'operation_assertion_outside_binding' in result.rule_reasons
        return
    from packages.research.evidence.answer_models import AnswerBoundary
    from test_question_retrieval import replace_snapshot
    # Rebuild only the producer/consumption envelope. The captured claim,
    # binding, source fact and false-supported review remain byte-exact data.
    detail, snapshot = prepared_detail(original.quote)
    detail.plan.competitors = [original.competitor]
    detail.plan.decision_brief = DecisionBrief(decision_question='1Password: can guests share a vault?')
    source = snapshot.sources[0].model_copy(update=fixture['source_identity'])
    snapshot = replace_snapshot(detail, snapshot, facts=(original,), sources=(source,),
        competitors=(original.competitor,))
    service, record = service_for(detail)
    view, use = service._begin_evidence_use(record, agent='writer', competitor=original.competitor,
        dimension='feature', fact_ids=[original.id])
    segment = service._writer_segment_context(record, dict(segment_name='dimension:1Password:feature',
        segment_competitor=original.competitor, dimension='feature'), view, use)
    detail.report_answer_boundaries = [AnswerBoundary.model_validate(row) for row in segment['answer_boundaries']]
    audit = ReportDimensionAudit(competitor=original.competitor, dimension='feature', consumption_id=use.id,
        claims=[saved], claim_review_version=3)
    detail.report_dimension_audits = [ReportDimensionAudit.model_validate_json(audit.model_dump_json())]
    detail.report_md = render_dimension_report(detail, detail.report_dimension_audits, snapshot=snapshot)
    service._record_evidence_artifact(record, kind='writer', uses=[use],
        payload=service._writer_evidence_artifact_payload(detail))
    assert any(issue.metadata.get('claim_audit_reason') == 'claim_review_replay_failed'
               for issue in audit_dimension_claims(service, record, snapshot, producer_verified=True))


@pytest.mark.parametrize('text', [
    SHARE + ' ' + MANAGE,
    '访客接受邀请后可以分享保险库。确认后，可像对待其他成员一样将其加入保险库并管理其访问权限。',
    'Guests can share vaults after accepting the invitation; they cannot manage access to vaults.',
    'Guests can share vaults and manage access to vaults after accepting the invitation.',
    'Guests can share vaults after accepting the invitation, and they can manage access to vaults.',
    'Only after accepting the invitation can guests share vaults and manage access to vaults.',
    '只有接受邀请后访客才可以分享保险库并管理其访问权限。',
])
def test_v3_full_supported_review_cannot_authorize_extra_independent_action(text):
    original = fact(quote=SHARE + ' ' + MANAGE, value=[SHARE, MANAGE])
    result = replay(bound_claim(original, text), original)
    assert result.status == 'rejected'
    assert 'operation_assertion_outside_binding' in result.rule_reasons


@pytest.mark.parametrize('source,text,operation', [
    (SHARE, SHARE, 'share'),
    (SHARE, 'Only after accepting the invitation can guests share vaults.', 'share'),
    (SHARE, '只有接受邀请后访客才可以分享保险库。', 'share'),
    ('Guests can share documents only after successful identity verification.',
     'Guests can share documents only after successful identity verification.', 'share'),
    (MANAGE, MANAGE, 'manage_access'),
    ('Guests can share vaults.', '访客可共享保险库。', 'share'),
    ('Members can edit documents after signing in and accepting the invitation.',
     'Members can edit documents after signing in and accepting the invitation.', 'edit'),
    ('Only members with permission to manage access can edit documents.',
     'Only members with permission to manage access can edit documents.', 'edit'),
    ('Only members with permission to manage access can edit documents.',
     '拥有管理访问权限的成员可以编辑文档。', 'edit'),
    ('Members can edit documents only after an admin manages access to the workspace.',
     'Members can edit documents only after an admin manages access to the workspace.', 'edit'),
    ('Members can edit documents if an admin manages access to the workspace.',
     'If an admin manages access to the workspace, members can edit documents.', 'edit'),
    ('Members cannot share documents.', 'Members cannot share documents.', 'share'),
    ('Members with Can manage access can edit documents.',
     'Members with Can manage access can edit documents.', 'edit'),
    ('Members can edit documents if admins can manage access.',
     'If admins can manage access, members can edit documents.', 'edit'),
    ('Members can edit documents only when admins can manage access.',
     'Only when admins can manage access can members edit documents.', 'edit'),
    ('Members can edit documents provided that admins can manage access.',
     'Members can edit documents provided that admins can manage access.', 'edit'),
    ('You can choose Can edit, Can comment or Can view for Anyone with the link.',
     'You can choose Can edit, Can comment or Can view for Anyone with the link.', 'manage_access'),
])
def test_v3_preserves_complete_single_action_and_non_action_mentions(source, text, operation):
    original = fact(quote=source)
    result = replay(bound_claim(original, text, operation), original)
    assert result.status == 'supported', result.rule_reasons


def test_legacy_review_does_not_gain_the_v3_extra_action_gate():
    original = fact(quote=SHARE + ' ' + MANAGE, value=[SHARE, MANAGE])
    assert replay(bound_claim(original, SHARE + ' ' + MANAGE), original, version=None).status == 'supported'


def test_v3_support_does_not_include_parent_sibling_value_or_quote():
    original = fact(quote=SHARE + ' ' + MANAGE, value=[SHARE, MANAGE])
    claim = bound_claim(original, SHARE)
    payload = review_payload([claim], SimpleNamespace(facts=[original], sources=[]), review_version=3)
    assert payload['claims'][0]['support_quotes'] == [claim.operation_binding.operation_quote]
    assert MANAGE not in json.dumps(payload['facts'])
    assert not any(MANAGE in row['text'] for row in payload['quotes'])
    legacy = review_payload([claim], SimpleNamespace(facts=[original], sources=[]))
    assert any(MANAGE in row['text'] for row in legacy['quotes'])


def test_v3_exact_span_keeps_only_selected_support_and_complete_parent_constraints():
    selected = 'Organizations own collections.'
    sibling = 'A separate user keeps a private copy.'
    original = fact(quote=selected + ' ' + sibling, value=[selected, sibling])
    from packages.research.evidence.snapshot_models import canonical_json
    original = original.model_copy(update={'qualifiers_json': canonical_json({'source_condition_links': [dict(
        kind='plan_dependency', quote='Depending on the subscription plan, organizations can own collections.',
        object_scope=None)]})})
    span = next(row for row in spans(original) if row['quote'] == selected)
    claim = ReportClaim(id='selected', **draft(original, selected), source_span_bindings=[span])
    payload = review_payload([claim], SimpleNamespace(facts=[original], sources=[]), review_version=3)
    assert payload['claims'][0]['support_quotes'] == [selected]
    assert sibling not in json.dumps(payload['facts'])
    assert not any(sibling in row['text'] for row in payload['quotes'])
    assert payload['constraint_context'][0]['qualifiers'] == original.qualifiers
    assert 'source_plan_condition_omitted_or_changed' in replay(claim, original).rule_reasons


def prepared_detail(source):
    from pydantic import HttpUrl, TypeAdapter
    question = 'Example Product: can guests share a vault?'
    detail, _ = research_case([source], question=question)
    detail.created_at = detail.updated_at = datetime.now(UTC)
    detail.plan.competitors = ['Example Product']
    detail.plan.dimensions = ['feature']
    detail.plan.decision_brief = DecisionBrief(decision_question=question)
    for row in detail.raw_sources:
        row.url = TypeAdapter(HttpUrl).validate_python(row.url)
    return detail, seal_snapshot(detail, phase='analysis', canonical_documents={})


@pytest.mark.parametrize('text', [SHARE + ' ' + MANAGE,
    '访客接受邀请后可以分享保险库；确认后，可像对待其他成员一样将其加入保险库并管理其访问权限。'])
def test_final_qa_replays_extra_action_gate_even_for_saved_full_supported_status(text):
    from packages.research.evidence.answer_models import AnswerBoundary
    detail, snapshot = prepared_detail(SHARE + ' ' + MANAGE)
    service, record = service_for(detail)
    original = next(row for row in snapshot.facts if row.field == 'evidence_terms')
    view, use = service._begin_evidence_use(record, agent='writer', competitor='Example Product',
        dimension='feature', fact_ids=[original.id])
    segment = service._writer_segment_context(record, dict(segment_name='dimension:Example Product:feature',
        segment_competitor='Example Product', dimension='feature'), view, use)
    detail.report_answer_boundaries = [AnswerBoundary.model_validate(row) for row in segment['answer_boundaries']]
    claim = bound_claim(original, text)
    saved = AuditedReportClaim(claim=claim, status='supported', review=force_supported(claim, view))
    audit = ReportDimensionAudit(competitor='Example Product', dimension='feature', consumption_id=use.id,
        claims=[saved], claim_review_version=3)
    detail.report_dimension_audits = [ReportDimensionAudit.model_validate_json(audit.model_dump_json())]
    detail.report_md = render_dimension_report(detail, detail.report_dimension_audits, snapshot=snapshot)
    service._record_evidence_artifact(record, kind='writer', uses=[use],
        payload=service._writer_evidence_artifact_payload(detail))
    issues = audit_dimension_claims(service, record, snapshot, producer_verified=True)
    assert any(issue.metadata.get('claim_audit_reason') == 'claim_review_replay_failed' for issue in issues)


@pytest.mark.asyncio
async def test_real_v3_writer_reviews_each_atom_with_only_its_selected_support(monkeypatch):
    detail, _ = prepared_detail(SHARE + ' ' + MANAGE)
    service, record = service_for(detail)
    reviews = []

    async def model(_record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs['user'].split('\nJSON:\n', 1)[1]))
        if kwargs['name'] == 'dimension_claim_writer':
            row = next(row for row in payload['evidence_view']['facts'] if row['field'] == 'evidence_terms')
            atoms = [dict(text=choice['operation_quote'], kind='fact', competitor='Example Product', dimension='feature',
                fact_ids=[row['id']], source_ids=[row['source_id']], observation_id=choice['observation_id'])
                for choice in row['operation_observations'] if choice['operation'] in {'share', 'manage_access'}]
            return json.dumps({'question_plans': [dict(question_id=q['question_id'], atoms=atoms, missing_fields=[])
                                                   for q in payload['questions']]})
        if kwargs['name'] == 'dimension_claim_review':
            reviews.append(payload)
            assert len(payload['claims']) == 1
            atom = payload['claims'][0]
            assert 'Without source_span_bindings audit the original quote' not in kwargs['system']
            assert '800' in kwargs['system']
            opposite = MANAGE if atom['operation_binding']['operation'] == 'share' else SHARE
            assert not any(opposite in row['text'] for row in payload['quotes'])
            assert opposite not in json.dumps(payload['facts'])
            return json.dumps({'reviews': [supported_review(atom)]})
        return json.dumps({'version': 3, 'answers': [dict(question_id=q['question_id'], status='unverified',
            resolution='unresolved', conclusion='unknown', claim_ids=[], missing_fields=[], reason='No answer selected.')
            for q in payload['questions']]})

    monkeypatch.setattr(service, '_trace_llm_text', model)
    await service._real_writer_step(record)
    assert len(reviews) == 2
    assert len([item for item in detail.report_dimension_audits[0].claims if item.status == 'supported']) == 2


def test_v3_extra_action_gate_also_runs_without_prerequisites():
    original = fact(quote='Guests can share documents. Guests can manage access to documents.',
        value=['Guests can share documents.', 'Guests can manage access to documents.'])
    claim = bound_claim(original, original.quote)
    assert not claim.operation_binding.prerequisites
    assert 'operation_assertion_outside_binding' in replay(claim, original).rule_reasons


def test_v3_does_not_reintroduce_siblings_through_parent_qualifiers():
    from packages.research.evidence.snapshot_models import canonical_json
    original = fact(quote=SHARE + ' ' + MANAGE, value=[SHARE, MANAGE])
    claim = bound_claim(original, SHARE)
    original = original.model_copy(update={'qualifiers_json': canonical_json({
        'quote': original.quote, 'evidence_terms': [SHARE, MANAGE],
        'operations': list(candidates(original).values())})})
    payload = review_payload([claim], SimpleNamespace(facts=[original], sources=[]), review_version=3)
    assert MANAGE not in json.dumps(payload)


@pytest.mark.parametrize('condition', [
    'Access is contingent on a successful eligibility check.',
    'Sharing is available only after successful identity verification.',
    'Sharing is contingent on admins being able to manage access.',
])
def test_v3_unreconstructed_necessary_condition_stays_unverified_even_if_model_supports(condition):
    source = 'Guests can share documents.'
    original = fact(quote=source, value=[source, condition])
    claim = bound_claim(original, source)
    assert condition in claim.operation_binding.condition_evidence
    assert not claim.operation_binding.prerequisites
    result = replay(claim, original)
    assert result.status != 'supported'
    assert 'operation_condition_support_unresolved' in result.rule_reasons


@pytest.mark.asyncio
@pytest.mark.parametrize('limit', [None, 'calls', 'tokens', 'long_reason'])
async def test_real_provider_adapter_keeps_review_budget_and_unverified_failures(monkeypatch, limit):
    import httpx
    from test_execution_limits import _service
    service, record = await _service(run_llm_max_calls=24, run_llm_max_tokens=80000, llm_max_retries=0)
    detail, _ = prepared_detail(SHARE + ' ' + MANAGE)
    detail.execution_mode = 'real'
    record.detail = detail
    service._runs[detail.id] = record
    budget = service._run_llm_budget(record)
    for phase in list(budget.delivery_reserves):
        if not phase.startswith(('writer:', 'qa:')):
            budget.finish_delivery(phase)
    if limit == 'calls':
        budget.calls = 22
    elif limit == 'tokens':
        budget.tokens_used = 79000
    requests = []

    async def post(url, payload, headers):
        data = expand_prompt_payload(json.loads(payload['messages'][1]['content'].split('\nJSON:\n', 1)[1]))
        requests.append(data)
        assert payload['max_tokens'] == 1600
        if 'evidence_view' in data:
            row = next(row for row in data['evidence_view']['facts'] if row['field'] == 'evidence_terms')
            atoms = [dict(text=choice['operation_quote'], kind='fact', competitor='Example Product', dimension='feature',
                fact_ids=[row['id']], source_ids=[row['source_id']], observation_id=choice['observation_id'])
                for choice in row['operation_observations'] if choice['operation'] in {'share', 'manage_access'}]
            content = {'question_plans': [dict(question_id=q['question_id'], atoms=atoms, missing_fields=[])
                                           for q in data['questions']]}
        elif 'atom_review_policy' in data:
            assert len(data['claims']) == 1
            content = {'reviews': [supported_review(data['claims'][0], reason='x' * 801 if limit == 'long_reason'
                else 'The selected complete action is supported.')]}
        else:
            content = {'version': 3, 'answers': [dict(question_id=q['question_id'], status='unverified',
                resolution='unresolved', conclusion='unknown', claim_ids=[], missing_fields=[], reason='No answer selected.')
                for q in data['questions']]}
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(content)}}],
            'usage': {'prompt_tokens': 200, 'completion_tokens': 100}})

    monkeypatch.setattr(service._llm, '_post_chat_completion', post)
    await service._real_writer_step(record)
    audit = detail.report_dimension_audits[0]
    published = [item for item in audit.claims if item.status == 'supported']
    if limit is None:
        assert len(published) == 2
        assert len([row for row in requests if 'atom_review_policy' in row]) == 2
    elif limit == 'calls':
        assert len(published) == 1
        assert len([item for item in audit.claims if item.status == 'unreviewed']) == 1
        assert budget.calls == 24 and len(requests) == 2
        assert 'claim_execution_budget_exceeded' in audit.gaps
    elif limit == 'tokens':
        assert not published and not requests
        assert 'claim_execution_budget_exceeded' in audit.gaps
    else:
        assert not published and all(item.status == 'unreviewed' for item in audit.claims)
        assert 'claim_review_invalid' in audit.gaps
        assert len([row for row in requests if 'atom_review_policy' in row]) == 2
    assert all(answer.status == 'unverified' for answer in audit.answer_coverage)
    assert (budget.max_calls, budget.max_tokens) == (24, 80000)
    assert budget.calls <= 24 and budget.tokens_used <= 80000 and budget.repairs == 0
    assert budget.tokens_reserved == 0


@pytest.mark.parametrize('condition', [
    'Members must sign in to edit documents.',
    'Editing documents is contingent on admins being able to manage access.',
])
def test_v3_explicit_other_operation_dependency_does_not_constrain_bound_share(condition):
    source = 'Guests can share documents.'
    original = fact(quote=source, value=[source, condition])
    assert replay(bound_claim(original, source), original).status == 'supported'
