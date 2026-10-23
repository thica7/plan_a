"""Scope syntax and transport replay; fixed reviews do not prove semantic accuracy."""

import json
import socket
from datetime import UTC, datetime
from pathlib import Path

import pytest
from claim_review_fixture import (
    answer_response, expand_prompt_payload, question_plan_response, sent_source_atom, supported_review,
)
from pydantic import HttpUrl, TypeAdapter
from test_question_retrieval import research_case
from test_writer_question_delivery import service_for

from packages.agents.qa.evidence_alignment import audit_dimension_claims
from packages.agents.writer import answer_resolution as guards
from packages.agents.writer.answer_coverage import (
    ANSWER_COVERAGE_SYSTEM, ANSWER_REVIEW_SYSTEM, coverage_resolution_reasons, parse_answer_coverage,
)
from packages.research.evidence.snapshot import current_snapshot, seal_snapshot
from packages.research.evidence.snapshot_models import EvidenceFact
from packages.schema.decision_brief import safe_decision_brief_text
from packages.schema.models import DecisionBrief

CAPTURED = Path(__file__).with_name('fixtures') / 'scope_rule_projection_v33.json'
SCOPE = '资源级角色仅适用于所分配的某个资源。'
ACTION = '资源级清理角色可清除指定资源的边缘缓存。'
QUESTION = '同事只被授予甲资源的资源级清理角色，没有任何其他授权。他能清除乙资源的边缘缓存吗？'


@pytest.fixture(autouse=True)
def no_network_or_local_models(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Scope replay must not use network or load a model')
    for name in ('create_connection', 'getaddrinfo'):
        monkeypatch.setattr(socket, name, forbidden)
    for name in ('connect', 'connect_ex'):
        monkeypatch.setattr(socket.socket, name, forbidden)
    monkeypatch.setattr('packages.agents.writer.question_retrieval.get_local_provider_from_env',
                        lambda kind: None)
    monkeypatch.setattr('packages.knowledge.local_models._load_sentence_transformer', forbidden)


def selection(question_id='q', *, ids=('scope',), conclusion='no', status='answered',
              resolution='direct', reason='Only complete published rules support this decision.'):
    return json.dumps({'version': 3, 'answers': [dict(question_id=question_id, status=status,
        claim_ids=list(ids), resolution=resolution, conclusion=conclusion, missing_fields=[], reason=reason)]})


def parse_scope(text, *, question='资源级角色是否适用于任意资源？', conclusion='no'):
    # Isolate the scope-syntax guard. A purge decision additionally requires a
    # published purge rule (covered by writer_replay and answer_action_v35).
    claims = [{'id': 'scope', 'text': text}]
    assert guards._CLOSED_QUESTION.search(question), 'Exercise the closed-question guard'
    result = parse_answer_coverage(selection(conclusion=conclusion),
        [{'question_id': 'q', 'question': question}], {'scope'}, claims=claims,
        required_binding_version=3)[0]
    return result, claims


def original_replay(response):
    saved = json.loads(CAPTURED.read_text())
    claims = saved['published_claims']
    result = parse_answer_coverage(saved[response], saved['questions'], {c['id'] for c in claims},
        claims=claims, required_binding_version=3,
        facts=tuple(EvidenceFact.model_validate(f) for f in saved['facts']))[0]
    return saved, result


def test_exact_span56_still_rejects_unrequired_lifecycle_clarifications():
    saved, result = original_replay('initial_response')
    assert saved['required_clarifications'] == []
    assert result.status == 'unverified' and not result.claim_ids
    assert result.reason.endswith('incomplete clarification selection')


def test_exact_span57_keeps_scope_and_operation_failures_separate(monkeypatch):
    monkeypatch.setattr(guards, '_chinese_scope_asserts', lambda text: False, raising=False)
    saved, result = original_replay('review_response')
    assert guards._CLOSED_QUESTION.search(saved['questions'][0]['question'])
    assert result.status == 'unverified' and not result.answer and not result.claim_ids
    assert 'answer_body_unresolved' in result.reason
    assert 'answer_operation_not_grounded' in result.reason


def test_exact_span57_cannot_project_no_without_a_published_operation_rule():
    saved, result = original_replay('review_response')
    claim = next(c for c in saved['published_claims'] if c['id'] == saved['scope_claim_id'])
    assert (result.status, result.resolution, result.conclusion) == ('unverified', 'unresolved', 'unknown')
    assert not result.answer and not result.claim_ids and not result.evidence_spans
    assert 'answer_operation_not_grounded' in result.reason
    assert claim['source_span_bindings'][0]['quote'] == (
        'Domain-scoped roles apply for a given domain within an account.')
    # The capture and reference labels remain unchanged; a legal scope quote
    # no longer supplies the absent Cache Domain Purge action by itself.
    assert claim['text']


@pytest.mark.parametrize('text', [
    SCOPE, '项目级角色只适用于指定项目。', '邀请规则仅适用于指定资源。',
    '申请规则只适用于指定项目。', '资源级角色仅适用于授权范围内的某个资源',
    '在校角色仅适用于指定校园。', '在场角色只适用于指定场地。',
    '只读角色仅适用于指定资源。',
])
def test_complete_scope_assertions_unlock_only_the_body_guard(text):
    assert not guards._ANSWER_ASSERTION.search(text)
    assert not guards._chinese_condition_asserts(text) and not guards._quantity_cap_asserts(text)
    result, claims = parse_scope(text)
    assert result.status == 'answered', result.reason
    assert result.answer == text and result.conclusion == 'no'
    assert not coverage_resolution_reasons(result, claims, required_binding_version=3)


@pytest.mark.parametrize('text', [
    '仅适用于指定资源。', '   只适用于指定项目。', '资源级角色仅适用于。',
    '仅仅适用于指定资源。', '仅仅只适用于指定资源。',
    '资源级角色只适用于   。', '资源级角色仅适用于指定资源吗？',
    '难道资源级角色仅适用于指定资源？', '资源级角色是否仅适用于指定资源。',
    '资源级角色能否只适用于指定资源。', '资源级角色仅适用于指定资源呢。',
    '资源级角色仅适用于指定资源吧。', '莫非资源级角色仅适用于指定资源。',
    '请确认资源级角色仅适用于指定资源。', '建议资源级角色仅适用于指定资源。',
    '建议：\n资源级角色仅适用于指定资源。', '推荐。\n资源级角色仅适用于指定资源。',
    '例如，资源级角色仅适用于指定资源。', '假设资源级角色仅适用于指定资源。',
    '如果资源级角色仅适用于指定资源。', '若资源级角色仅适用于指定资源。',
    '除非资源级角色仅适用于指定资源。', '仅当资源级角色仅适用于指定资源。',
    '当资源级角色仅适用于指定资源时。', '在资源级角色仅适用于指定资源的情况下。',
    '在资源级角色仅适用于指定资源时。', '资源级角色仅适用于指定资源的前提下。',
    '只有资源级角色仅适用于指定资源。', '假定资源级角色仅适用于指定资源。',
    '举例：资源级角色仅适用于指定资源。',
    '“资源级角色仅适用于指定资源。”', '「资源级角色仅适用于指定资源。」',
    '“背景。\n资源级角色仅适用于指定资源。”', '范围：\n资源级角色仅适用于指定资源。',
    '资源级角色\n仅适用于指定资源。', '资源级角色仅适用于\n指定资源。',
    '资源级角色仅适用于指定资源。\n以上仅为示例。',
    '资源级角色仅适用于指定资源。\n以上仅供参考。',
    '资源级角色仅适用于指定资源。\n以上不构成正式产品规则。',
    '资源级角色仅适用于指定资源。\n该说法尚未证实。',
])
def test_nonasserting_or_incomplete_blocks_do_not_unlock_the_body_guard(text):
    result, _ = parse_scope(text)
    assert result.status == 'unverified' and not result.answer
    assert result.reason.endswith('answer_body_unresolved')


@pytest.mark.parametrize('conclusion', ['yes', 'no'])
@pytest.mark.parametrize('other_grants', [True, False])
def test_scope_syntax_never_decides_polarity_or_proves_person_wide_authorization(conclusion, other_grants):
    question = '同事只被授予甲资源的资源级角色，没有任何其他授权。此角色是否适用于乙资源？'
    if not other_grants:
        question = question.replace('，没有任何其他授权', '')
    result, _ = parse_scope(SCOPE, question=question, conclusion=conclusion)
    assert result.status == 'answered' and result.conclusion == conclusion


async def writer_replay(monkeypatch, *, case='complete', review='no'):
    question = QUESTION
    rules = [ACTION, SCOPE]
    published = list(rules)
    if case == 'missing_action':
        published = [SCOPE]  # The raw operation fact is visible only for auditing.
    elif case == 'missing_category':
        rules[0] = published[0] = '清理角色可清除指定资源的边缘缓存。'
    elif case == 'other_grants_unknown':
        question = question.replace('，没有任何其他授权', '')
    elif case == 'same_resource':
        question = question.replace('乙资源', '甲资源')
    elif case == 'account_wide':
        rules = published = ['全账户清理角色可以清除账户内全部资源的边缘缓存。']
    elif case == 'enumeration':
        rules[1] = published[1] = '资源级角色适用于甲资源及其他已配置资源。'
    elif case == 'exception':
        rules.append('额外共享授权允许清除共享资源的边缘缓存。')
        published = list(rules)
    detail, _ = research_case(rules, question='Example Product：' + question)
    detail.created_at = detail.updated_at = datetime.now(UTC)
    detail.plan.competitors = ['Example Product']
    detail.plan.dimensions = ['feature']
    detail.plan.decision_brief = DecisionBrief(decision_question='Example Product：' + question)
    for source in detail.raw_sources:
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
    seal_snapshot(detail, phase='analysis', canonical_documents={})
    service, record = service_for(detail)
    calls = []

    async def model(_record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs['user'].split('\nJSON:\n', 1)[1]))
        calls.append((kwargs['name'], payload))
        if kwargs['name'] == 'dimension_claim_writer':
            facts = payload['evidence_view']['facts']
            atoms = [sent_source_atom(f, f['quote'], support_text=f['quote'])
                     for f in facts if f['quote'] in published]
            return question_plan_response(payload, atoms)
        if kwargs['name'] == 'dimension_claim_review':
            return json.dumps({'reviews': [supported_review(c) for c in payload['claims']]})
        if kwargs['name'] == 'dimension_question_repair':
            # Keep this missing-premise fixture incomplete after its bounded
            # repair attempt; the original publication assertions still apply.
            return question_plan_response(payload, [])
        assert kwargs['name'] in {'dimension_answer_coverage', 'dimension_answer_review'}
        assert payload['required_clarifications'] == []
        assert guards._CLOSED_QUESTION.search(payload['questions'][0]['question'])
        if kwargs['name'] == 'dimension_answer_review':
            assert {c['text'] for c in payload['claims']} == set(published)
            assert set(published) <= {f['quote'] for f in payload['published_supports']}
            if review == 'missing':
                return None
            if review == 'invalid':
                return '{invalid'
            if review == 'unpublished':
                return selection(payload['questions'][0]['question_id'], ids=['unpublished-raw-fact'])
            if review == 'reject':
                return selection(payload['questions'][0]['question_id'], ids=[], status='unverified',
                    resolution='unresolved', conclusion='unknown', reason='Raw facts or reason cannot fill missing published premises.')
        decision = review if kwargs['name'] == 'dimension_answer_review' else 'yes'
        response = json.loads(selection(payload['questions'][0]['question_id'], ids=[c['id'] for c in payload['claims']],
            conclusion=decision, resolution='conditional' if decision == 'depends' else 'direct',
            reason='A model reason must not add product rules, resource names, or other grants.'))
        return answer_response(payload, response, relation='resource_scope' if decision == 'no' else 'direct')

    monkeypatch.setattr(service, '_trace_llm_text', model)
    await service._real_writer_step(record)
    service._journal.save_run(record.detail)
    record.detail = service._journal.load_run(record.detail.id)
    assert record.detail is not None
    assert [name for name, _ in calls].count('dimension_answer_review') == 1
    assert [name for name, _ in calls].count('dimension_answer_coverage') == 1
    audit = record.detail.report_dimension_audits[0]
    result = audit.answer_coverage[0]
    supported = [c.claim for c in audit.claims if c.status == 'supported']
    assert {c.text for c in supported} == set(published)
    snapshot = current_snapshot(record.detail)
    assert service._final_qa_producer_verified(record, snapshot)
    replay = audit_dimension_claims(service, record, snapshot, producer_verified=True)
    _, final_issues, _ = await service._final_qa_evidence(record)
    return record, result, supported, calls, replay, final_issues


@pytest.mark.asyncio
@pytest.mark.parametrize('case,decision', [
    ('complete', 'no'), ('same_resource', 'yes'), ('account_wide', 'yes'), ('exception', 'depends'),
])
async def test_writer_review_renderer_journal_and_final_qa_keep_only_the_reviewed_projection(monkeypatch, case, decision):
    record, result, claims, calls, replay, final = await writer_replay(monkeypatch, case=case, review=decision)
    assert (result.status, result.conclusion, result.binding_version) == ('answered', decision, 3), result.reason
    assert result.answer == '\n'.join(c.text for c in claims)
    assert [(s.claim_id, s.quote) for s in result.evidence_spans] == [(c.id, c.text) for c in claims]
    labels = {'no': '结论：否', 'yes': '结论：是', 'depends': '结论：需按条件判断'}
    assert labels[decision] in record.detail.report_md
    assert safe_decision_brief_text(result.answer) in record.detail.report_md
    assert 'A model reason' not in result.reason
    assert not replay
    assert not [i for i in final if i.metadata.get('claim_audit_reason')]
    if case == 'complete':
        proposal = next(p for name, p in calls if name == 'dimension_answer_review')['proposed_answers'][0]
        assert proposal['conclusion'] == 'yes' and proposal['status'] == 'answered'
        assert result.reason == '依据2条已发表主张；已回答，直接回答。'


@pytest.mark.asyncio
@pytest.mark.parametrize('case,review', [
    ('complete', 'missing'), ('complete', 'invalid'), ('complete', 'unpublished'), ('complete', 'reject'),
    ('missing_action', 'reject'), ('missing_category', 'reject'),
    ('other_grants_unknown', 'reject'), ('enumeration', 'reject'),
])
async def test_actual_independent_review_failure_or_rejection_drops_the_proposal(monkeypatch, case, review):
    record, result, _, _, replay, final = await writer_replay(monkeypatch, case=case, review=review)
    assert result.status == 'unverified' and not result.answer and not result.claim_ids
    assert '结论：否' not in record.detail.report_md
    assert any(i.metadata.get('claim_audit_reason') == 'answer_coverage_incomplete' for i in replay)
    assert any(i.metadata.get('claim_audit_reason') == 'answer_coverage_incomplete' for i in final)


def test_scope_prompts_distinguish_published_product_rules_from_request_inputs():
    for prompt in (ANSWER_COVERAGE_SYSTEM, ANSWER_REVIEW_SYSTEM):
        assert 'no-other-grants premise' in prompt
        assert 'scenario' in prompt
        assert 'role category' in prompt and 'requested operation' in prompt
        assert 'request inputs' in prompt
        assert 'non-exclusive list' in prompt
