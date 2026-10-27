"""Necessary request clarification needs exact publication and actual independent QA."""

import hashlib
import json
from dataclasses import replace

import pytest
from question_review_fixture import review_payload as decode_review_payload
from test_final_question_reconciliation import reviewed
from test_independent_final_question_qa import context_for, payload_from, receipt
from test_question_context_qa import CLARIFY, case, findings

from packages.agents.qa import independent_question_review as independent
from packages.agents.qa.question_reconciliation import _answer_support, reconcile_question_findings
from packages.orchestrator.evidence_context import EvidenceUseRejectedError
from packages.research.question_scope import research_questions
from packages.schema.models import QCIssue, RedoScope, TraceSpan


def qa_case(**kwargs):
    service, record, snapshot = case(**kwargs)
    service._settings = replace(service._settings, writer_task_execution_enabled=True)
    return service, record, snapshot


def clarification(record):
    audit = record.detail.report_dimension_audits[0]
    question = next(q for q in research_questions(record.detail, audit.competitor, audit.dimension)
                    if q['question'] == CLARIFY)
    return audit, question, next(a for a in audit.answer_coverage
                               if a.question_id == question['question_id'])


def append_mock_trace(record, kwargs, response, *, status='ok', transports=1, timeout_attempts=0):
    """Offline model double records the same envelope as the traced adapter."""
    record.detail.trace_spans.append(TraceSpan(
        id=f'qa-offline-{len(record.detail.trace_spans)}', kind='llm', agent='qa',
        name='final_question_reconciliation', status=status, duration_ms=0,
        full_input=kwargs['system'] + '\n\n' + kwargs['user'], full_output=response,
        metadata={'llm_transport_attempts': transports, 'llm_request_attempts': transports,
                  'llm_timeout_attempts': timeout_attempts},
    ))


def install_review(monkeypatch, service, *, mutate=None, actual=True):
    calls = []

    async def model(record, **kwargs):
        payload = payload_from(kwargs)
        calls.append(payload)
        result = json.loads(reviewed(payload, 'current_limitation'))
        if mutate:
            mutate(result)
        response = json.dumps(result)
        if actual:
            append_mock_trace(record, kwargs, response)
        return response

    monkeypatch.setattr(service, '_trace_llm_text', model)
    return calls


def test_exact_server_clarification_has_request_only_support():
    service, record, snapshot = qa_case()
    audit, question, answer = clarification(record)
    assert _answer_support(record.detail, snapshot, audit, answer, question) == []


@pytest.mark.asyncio
async def test_clarification_keeps_own_eligibility_when_another_question_has_factual_gap(
    monkeypatch,
):
    service, record, snapshot = qa_case(factual=True, missing_for='factual')
    evidence_issues = findings(service, record, snapshot)
    assert evidence_issues and service._final_qa_producer_verified(record, snapshot)
    calls = install_review(monkeypatch, service)
    result = await reconcile_question_findings(service, record, [], evidence_issues=evidence_issues)
    _, question, answer = clarification(record)
    contexts = {row['question_id']: context_for(payload, row)
                for payload in calls for row in payload['findings']}
    assert contexts[question['question_id']]['support_verified'] is True
    assert all(not c['support_verified'] for qid, c in contexts.items()
               if qid != question['question_id'])
    assert question['question_id'] in receipt(record.detail)['passed_question_ids']
    assert all(i.metadata.get('question_id') != question['question_id'] for i in result)
    assert answer.status == 'partial' and answer.resolution == 'clarification'


@pytest.mark.parametrize('mutation', ['fields', 'order', 'reason', 'answer', 'status',
    'claim', 'evidence', 'basis', 'version', 'duplicate', 'body', 'assertion', 'bullet',
    'missing_heading', 'duplicate_heading'])
def test_changed_clarification_never_has_request_only_support(mutation):
    service, record, snapshot = qa_case()
    audit, question, answer = clarification(record)
    if mutation in {'missing_heading', 'duplicate_heading'}:
        record.detail.report_md = record.detail.report_md.replace('#### 问题回答情况',
            '' if mutation == 'missing_heading' else '#### 问题回答情况\n\n#### 问题回答情况')
    elif mutation in {'body', 'assertion', 'bullet'}:
        record.detail.report_md = record.detail.report_md.replace(
            answer.answer, answer.answer + {'body': ' changed', 'assertion': '\n  数据一定会保留。',
                                           'bullet': '\n- 数据一定会保留。'}[mutation])
    elif mutation == 'duplicate':
        audit = audit.model_copy(update={'answer_coverage': [answer, answer]})
    elif mutation == 'version':
        audit = audit.model_copy(update={'claim_review_version': 2})
    else:
        updates = {
            'fields': {'missing_fields': ('actual_action',)},
            'order': {'missing_fields': tuple(reversed(answer.missing_fields))},
            'reason': {'reason': 'changed'}, 'answer': {'answer': answer.answer + ' changed'},
            'status': {'status': 'answered'}, 'claim': {'claim_ids': ('unsupported',)},
            'evidence': {'subquestion_bindings': ('forged',)},
            'basis': {'basis_snapshot_id': snapshot.id},
        }
        answer = answer.model_copy(update=updates[mutation])
        audit = audit.model_copy(update={'answer_coverage': [answer]})
    record.detail.report_dimension_audits = [audit]
    assert _answer_support(record.detail, snapshot, audit, answer, question) is None


@pytest.mark.parametrize('parent', [
    'Example Product: 我们会移除组织成员，是否可以？ ',
    'Example Product: 数据属于个人，是否可以？ ',
    'Example Product: 我们会移除组织成员，数据属于个人，是否可以？ ',
    'Example Product: 第一种情况是否可以？ ',
])
def test_parent_given_fields_or_ambiguous_binding_cannot_qualify(parent):
    service, record, snapshot = qa_case()
    audit, question, answer = clarification(record)
    text = parent + CLARIFY
    if '第一种' in parent:
        text += '\nExample Product: 第二种情况是否可以？ ' + CLARIFY
    record.detail.plan.decision_brief.decision_question = text
    assert _answer_support(record.detail, snapshot, audit, answer, question) is None


@pytest.mark.asyncio
@pytest.mark.parametrize('decision', ['false', 'gaps'])
async def test_model_negative_or_remaining_gap_is_never_overridden(monkeypatch, decision):
    service, record, _ = qa_case()
    def mutate(result):
        result['reviews'][0].update(
            finding_fully_addressed=decision != 'false',
            remaining_gaps=['Unanswered action.'] if decision == 'gaps' else [])
    install_review(monkeypatch, service, mutate=mutate)
    assert await reconcile_question_findings(service, record, [], evidence_issues=[])
    assert receipt(record.detail)['passed_question_ids'] == []


@pytest.mark.asyncio
async def test_response_without_actual_qa_trace_cannot_pass(monkeypatch):
    service, record, _ = qa_case()
    install_review(monkeypatch, service, actual=False)
    assert await reconcile_question_findings(service, record, [], evidence_issues=[])
    assert receipt(record.detail)['valid_review_issue_ids'] == []


@pytest.mark.asyncio
async def test_current_cache_needs_current_actual_qa_trace_and_hashes(monkeypatch):
    service, record, _ = qa_case()
    calls = install_review(monkeypatch, service)
    assert await reconcile_question_findings(service, record, [], evidence_issues=[]) == []
    output = receipt(record.detail)
    assert output['mode'] == 'independent_questions_v9'
    batch = output['batch_receipts'][0]
    span = next(s for s in record.detail.trace_spans if s.id == batch['span_id'])
    assert batch['full_input_sha256'] == hashlib.sha256(span.full_input.encode()).hexdigest()
    assert batch['full_output_sha256'] == hashlib.sha256(span.full_output.encode()).hexdigest()
    assert await reconcile_question_findings(service, record, [], evidence_issues=[]) == []
    assert len(calls) == 1
    record.detail.trace_spans.remove(span)
    install_review(monkeypatch, service, actual=False)
    assert await reconcile_question_findings(service, record, [], evidence_issues=[])
    assert receipt(record.detail)['valid_review_issue_ids'] == []


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', [
    'kind', 'agent', 'subagent', 'status', 'transport_zero', 'transport_bool',
    'input_hash', 'output_hash', 'system_rehashed', 'payload_rehashed',
    'identity_rehashed', 'receipt_only', 'v3', 'v4', 'v5', 'duplicate_key', 'extra_context',
])
async def test_cached_local_receipt_cannot_substitute_for_actual_review(monkeypatch, mutation):
    service, record, _ = qa_case()
    install_review(monkeypatch, service)
    assert await reconcile_question_findings(service, record, [], evidence_issues=[]) == []
    local = record.detail.trace_spans[-1]
    output = json.loads(local.full_output)
    batch = output['batch_receipts'][0]
    span = next(s for s in record.detail.trace_spans if s.id == batch['span_id'])
    if mutation == 'receipt_only':
        output['batch_receipts'] = []
    elif mutation in {'v3', 'v4', 'v5'}:
        output['mode'] = 'independent_questions_' + mutation
    elif mutation in {'kind', 'agent', 'subagent', 'status'}:
        setattr(span, mutation, {'kind': 'tool', 'agent': 'writer',
                                'subagent': 'feature', 'status': 'error'}[mutation])
    elif mutation.startswith('transport_'):
        span.metadata['llm_transport_attempts'] = 0 if mutation == 'transport_zero' else True
    elif mutation == 'input_hash':
        span.full_input += ' changed'
    elif mutation == 'output_hash':
        span.full_output += ' '
    elif mutation == 'system_rehashed':
        span.full_input = span.full_input.replace(
            independent.INDEPENDENT_SYSTEM, 'Different system')
        batch['full_input_sha256'] = hashlib.sha256(span.full_input.encode()).hexdigest()
    elif mutation in {'duplicate_key', 'extra_context'}:
        raw = span.full_input.split('\nJSON:\n', 1)[1]
        if mutation == 'duplicate_key':
            raw = raw.replace('"version":1', '"version":1,"version":1', 1)
        else:
            wire = json.loads(raw)
            wire['hidden_context'] = 'Unsent hidden condition'
            from packages.research.evidence.snapshot_models import canonical_json
            raw = canonical_json(wire)
        span.full_input = independent.INDEPENDENT_SYSTEM + '\n\n\nJSON:\n' + raw
        batch['full_input_sha256'] = hashlib.sha256(span.full_input.encode()).hexdigest()
    elif mutation == 'payload_rehashed':
        payload = decode_review_payload(span.full_input.split('\nJSON:\n', 1)[1])
        row = payload['findings'][0]
        context_for(payload, row)['visible_answer'] += ' Claimed product behavior.'
        from packages.agents.qa.question_review_transport import dumps
        span.full_input = independent.INDEPENDENT_SYSTEM + '\n\n\nJSON:\n' + dumps(payload)
        batch['full_input_sha256'] = hashlib.sha256(span.full_input.encode()).hexdigest()
    else:
        response = json.loads(span.full_output)
        response['reviews'][0]['support_digest'] = '0' * 64
        span.full_output = json.dumps(response)
        batch['full_output_sha256'] = hashlib.sha256(span.full_output.encode()).hexdigest()
    local.full_output = json.dumps(output)
    calls = install_review(monkeypatch, service, actual=False)
    assert await reconcile_question_findings(service, record, [], evidence_issues=[])
    assert len(calls) == 1
    assert receipt(record.detail)['valid_review_issue_ids'] == []


@pytest.mark.asyncio
async def test_unverified_producer_keeps_even_canonical_clarification_diagnostic(monkeypatch):
    service, record, snapshot = qa_case()
    record.detail.evidence_consumptions = []
    assert not service._final_qa_producer_verified(record, snapshot)
    calls = install_review(monkeypatch, service)
    assert await reconcile_question_findings(service, record, [], evidence_issues=[object()])
    assert calls[0]['findings'][0]['diagnostic_only'] is True
    assert receipt(record.detail)['passed_question_ids'] == []


@pytest.mark.asyncio
async def test_producer_is_rechecked_even_when_unrelated_evidence_issues_exist(monkeypatch):
    service, record, snapshot = qa_case(factual=True, missing_for='factual')
    evidence_issues = findings(service, record, snapshot)
    assert evidence_issues

    def mutate(result):
        record.detail.evidence_consumptions = [u for u in record.detail.evidence_consumptions
                                               if u.agent != 'writer']

    install_review(monkeypatch, service, mutate=mutate)
    with pytest.raises(EvidenceUseRejectedError, match='dependencies changed'):
        await reconcile_question_findings(service, record, [], evidence_issues=evidence_issues)


@pytest.mark.asyncio
async def test_clarification_delivery_cannot_downgrade_historical_fact_findings(monkeypatch):
    service, record, snapshot = qa_case(factual=True, missing_for='factual')
    audit, question, answer = clarification(record)
    issue = QCIssue(id='clarification-history', severity='blocker', detected_by='reflector',
        target_agent='writer', target_competitor=audit.competitor,
        field_path='answer_coverage', redo_scope=RedoScope(kind='writer_only', rationale='review'),
        problem=question['question_id'] + ': action and ownership need an answer.',
        metadata={'question_id': question['question_id']})
    structural = issue.model_copy(update={'id': 'structure-history',
        'problem': question['question_id']
            + ': source document missing and the action is unanswered.'})
    install_review(monkeypatch, service)
    result = await reconcile_question_findings(service, record, [issue, structural],
        evidence_issues=findings(service, record, snapshot))
    by_id = {i.id: i for i in result}
    assert by_id[issue.id].severity == 'blocker'
    assert by_id[structural.id].severity == 'blocker'
    assert answer.status == 'partial' and answer.resolution == 'clarification'
    assert receipt(record.detail)['passed_question_ids'] == [question['question_id']]


@pytest.mark.asyncio
async def test_clarification_without_model_review_keeps_pending_and_can_resume(monkeypatch):
    service, record, _ = qa_case()

    async def unsent(record, **kwargs):
        from packages.llm.errors import LLMExecutionLimitError
        raise LLMExecutionLimitError('run_llm_call_budget_exhausted')

    monkeypatch.setattr(service, '_trace_llm_text', unsent)
    assert await reconcile_question_findings(service, record, [], evidence_issues=[])
    output = receipt(record.detail)
    assert output['sent_issue_ids'] == output['valid_review_issue_ids'] == []
    assert not any(output['attempts_by_issue_id'].values())
    install_review(monkeypatch, service)
    assert await reconcile_question_findings(service, record, [], evidence_issues=[]) == []


@pytest.mark.asyncio
async def test_clarification_timeout_records_actual_span_and_resumes_once(monkeypatch):
    service, record, _ = qa_case()

    async def timeout(record, **kwargs):
        append_mock_trace(record, kwargs, 'controlled offline timeout', status='error',
                          timeout_attempts=1)
        raise TimeoutError('controlled offline timeout')

    monkeypatch.setattr(service, '_trace_llm_text', timeout)
    assert await reconcile_question_findings(service, record, [], evidence_issues=[])
    output = receipt(record.detail)
    batch = output['batch_receipts'][0]
    assert batch['status'] == 'timeout'
    span = next(s for s in record.detail.trace_spans if s.id == batch['span_id'])
    assert span.metadata['llm_timeout_attempts'] == 1
    assert batch['full_input_sha256'] == hashlib.sha256(span.full_input.encode()).hexdigest()
    assert batch['full_output_sha256'] == hashlib.sha256(span.full_output.encode()).hexdigest()
    assert output['valid_review_issue_ids'] == []
    assert set(output['attempts_by_issue_id'].values()) == {1}
    calls = install_review(monkeypatch, service)
    assert await reconcile_question_findings(service, record, [], evidence_issues=[]) == []
    assert await reconcile_question_findings(service, record, [], evidence_issues=[]) == []
    assert len(calls) == 1
    assert set(receipt(record.detail)['attempts_by_issue_id'].values()) == {2}
    assert receipt(record.detail)['timeout_issue_ids'] == output['planned_issue_ids']
