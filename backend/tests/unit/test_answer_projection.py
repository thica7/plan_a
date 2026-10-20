"""Finite answer projection, with exact original Bitwarden cap atoms."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from packages.agents.writer.answer_coverage import (
    coverage_resolution_reasons, is_qualified_partial_clarification,
    parse_answer_coverage, selection_answer,
)
from packages.agents.writer.answer_resolution import _quantity_cap_asserts
from packages.research.evidence.answer_coverage_models import ReportAnswerCoverage
from packages.research.evidence.snapshot_models import EvidenceFact

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/answer_projection_bitwarden.json').read_text())
Q1, Q2 = FIXTURE['questions']


def pure(question=Q2):
    # Local import makes RED behavioral failures visible alongside the missing helper.
    from packages.agents.writer.request_clarification import server_clarification_answer
    return server_clarification_answer(question)


@pytest.mark.parametrize('proposal', FIXTURE['proposals'])
def test_original_bitwarden_cap_selection_keeps_exact_atoms_and_negative_conclusion(proposal):
    claims = FIXTURE['claims']
    facts = [EvidenceFact.model_validate(f) for f in FIXTURE['facts']]
    row = proposal['answers'][0]
    record = parse_answer_coverage(json.dumps(dict(version=3, answers=[row])), [Q1],
        {c['id'] for c in claims}, claims=claims, required_binding_version=3, facts=facts)[0]
    assert record.status == 'answered', record.reason
    assert record.conclusion == 'no' and record.claim_ids == tuple(row['claim_ids'])
    assert record.answer == '\n'.join(c['text'] for c in claims[:2])
    assert [(s.claim_id, s.quote) for s in record.evidence_spans] == [(c['id'], c['text']) for c in claims[:2]]


@pytest.mark.parametrize('text', [
    'Free organization 提供最多两个 collections 的安全数据共享。',
    '套餐最多 2 个共享密码集合。',
    'The plan includes up to 2 shared password collections.',
    'Plan has a maximum of 2 users.',
    '名称为“示例”。套餐最多 2 个共享集合。',
    '名称为“最多两个集合”；套餐最多 2 个共享集合。',
])
def test_complete_quantity_caps_are_formats_not_decision_engines(text):
    assert _quantity_cap_asserts(text)


@pytest.mark.parametrize('text', [
    '例如，套餐最多 2 个共享集合。', '建议套餐最多 2 个共享集合。',
    '假设套餐最多 2 个共享集合。', '如果套餐最多 2 个共享集合。',
    '若套餐最多 2 个共享集合。', 'Provided the plan includes up to 2 collections.',
    '请解释“套餐最多 2 个共享集合”的含义。', '“套餐最多 2 个共享集合”。',
    'Example: the plan includes up to 2 collections.',
    'Example. The plan includes up to 2 collections.',
    '假设如下。套餐最多 2 个共享集合。',
    '例如：Basic 最多两个 collections。Pro 最多五个 collections。',
    '假设以下数字用于讨论。Basic 最多两个 collections。',
    '示例：\nBasic 最多两个 collections。\nPro 最多五个 collections。',
    'Suppose the plan includes up to 2 collections.',
    'If the plan includes up to 2 collections.',
    'The phrase "the plan includes up to 2 collections" is quoted.',
])
def test_quantity_examples_quotes_recommendations_and_incomplete_conditions_are_not_assertions(text):
    assert not _quantity_cap_asserts(text)


def test_original_lifecycle_request_gets_only_concrete_action_and_ownership_questions():
    record = pure()
    assert record is not None
    assert record.status == 'partial' and record.resolution == 'clarification' and record.conclusion == 'depends'
    assert record.binding_version == 3 and record.question_id == Q2['question_id'] and record.question == Q2['question']
    assert record.missing_fields == ('actual_action', 'data_ownership')
    assert not record.claim_ids and not record.evidence_spans and record.basis_snapshot_id is None
    assert '移除成员' in record.answer and '永久删除账户' in record.answer
    assert '个人' in record.answer and '组织' in record.answer
    assert '副本' not in record.answer and '访问路径' not in record.answer
    assert not coverage_resolution_reasons(record, [], required_binding_version=3)
    assert selection_answer(record, []) == (record.answer, ())
    assert is_qualified_partial_clarification(record, [], report_md=record.answer)
    assert ReportAnswerCoverage.model_validate_json(record.model_dump_json()) == record


@pytest.mark.parametrize('question', [
    Q1['question'], '请解释字符串“删掉”和“留下”的拼写。',
    '请把“删掉”两个字改成红色，之后还会留下吗？',
    '请翻译“删除用户后密码还会留下吗？”',
    '讨论引文“把离职同事删掉后密码会留下吗”的修辞。',
    'What is the spelling of "delete" and "remain"?',
    'Translate "delete a member, will their passwords remain?"',
    'Example Product: 删除用户后怎么办？',
    'Example Product: 怎么删除个人保险库的密码？',
    'Example Product: How do I delete vault passwords?',
    'Example Product: 删除密码是什么意思？',
    'Example Product: Remove member；密码归组织拥有，之后还会留下吗？',
    'Example Product: 永久删除个人账户和数据，个人密码还会留下吗？',
])
def test_unrelated_metalinguistic_unknown_and_fully_specified_requests_cannot_authorize_pure_clarification(question):
    assert pure(dict(question_id='q', question=question)) is None


@pytest.mark.parametrize('question,fields', [
    ('Example Product: 执行 Remove member 后，密码会留下吗？', ('data_ownership',)),
    ('Example Product: 移除成员后，他的密码还会留下吗？', ('data_ownership',)),
    ('Example Product: After removing a member, will their passwords remain?', ('data_ownership',)),
    ('Example Product: 使用 Delete account 后，组织拥有的密码会留下吗？', ()),
    ('Example Product: 从组织中移除成员后，我个人的文件还会留下吗？', ()),
    ('Example Product: 移除组织成员后，文档属于组织，还能访问吗？', ()),
    ('Example Product: 把同事删掉后，个人保险库的密码会留下吗？', ('actual_action',)),
    ('Example Product: We will "delete" a colleague. Will their passwords remain?', ('actual_action', 'data_ownership')),
    ('Example Product: 删除同事后，产品是否保留密码副本？', ('actual_action', 'data_ownership')),
    ('Example Product: Remove member 后，个人密码通过哪个共享链接仍可访问？', ()),
    ('Example Product: Remove member 后，个人密码能保留吗？我是否允许保留副本？', ()),
    ('Example Product: 把同事删掉后密码留下吗？用户是否选择保留副本已经确定为不允许，访问路径已经确定为账户。',
     ('actual_action', 'data_ownership')),
    ('Example Product: 把同事删掉后能访问密码吗？用户是否选择保留副本、使用哪条共享链接尚未确定。',
     ('actual_action', 'data_ownership', 'retained_copy', 'access_path')),
])
def test_only_explicitly_missing_request_inputs_are_asked(question, fields):
    record = pure(dict(question_id='q', question=question))
    assert (record.missing_fields if record else ()) == fields


@pytest.mark.parametrize('updates', [
    {'answer': '请确认具体操作？数据一定保留。'}, {'reason': 'Data remains.'},
    {'missing_fields': ('actual_action',)},
    {'missing_fields': ('actual_action', 'data_ownership', 'retained_copy')},
    {'missing_fields': ('actual_action', 'data_ownership', 'data_ownership')},
    {'missing_fields': ('data_ownership', 'actual_action')},
    {'status': 'answered'}, {'conclusion': 'yes'}, {'resolution': 'direct'},
    {'binding_version': 2}, {'basis_snapshot_id': 'fabricated'},
    {'claim_ids': ('invented',)},
    {'evidence_spans': (SimpleNamespace(claim_id='fake', quote='Data remains.'),)},
    {'question': Q1['question']},
])
def test_pure_record_replay_rejects_any_materialized_tampering(updates):
    record = pure().model_copy(update=updates)
    assert coverage_resolution_reasons(record, [], required_binding_version=3)
    assert not is_qualified_partial_clarification(record, [])


def test_model_empty_selection_and_reason_cannot_authorize_pure_request():
    record = pure()
    row = dict(question_id=Q2['question_id'], status='partial', resolution='clarification',
        conclusion='depends', claim_ids=[], missing_fields=list(record.missing_fields), reason=record.reason)
    parsed = parse_answer_coverage(json.dumps(dict(version=3, answers=[row])), [Q2], set(),
        claims=[], required_binding_version=3)[0]
    assert parsed.status == 'unverified'


@pytest.mark.parametrize('index', [0, 2])
def test_bound_free_organization_caps_and_plan_owner_rules_are_not_lifecycle_rules(index):
    claim = FIXTURE['claims'][index]
    row = dict(question_id=Q2['question_id'], status='partial', resolution='clarification',
        conclusion='depends', claim_ids=[claim['id']],
        missing_fields=['actual_action', 'data_ownership', 'retained_copy', 'access_path'], reason='Untrusted.')
    facts = [EvidenceFact.model_validate(f) for f in FIXTURE['facts']]
    record = parse_answer_coverage(json.dumps(dict(version=3, answers=[row])), [Q2], {claim['id']},
        claims=[claim], required_binding_version=3, facts=facts)[0]
    assert not is_qualified_partial_clarification(record, [claim], facts=facts)


@pytest.mark.asyncio
async def test_zero_supported_writer_routes_pure_clarification_without_model_and_keeps_real_gaps(monkeypatch):
    from test_writer_question_delivery import lifecycle_case, service_for
    from packages.agents.writer.answer_coverage import research_questions
    detail, _ = lifecycle_case()
    service, run = service_for(detail)
    questions = research_questions(detail, 'Example Product', 'feature')[1:]
    view, use = service._begin_evidence_use(run, agent='writer', competitor='Example Product', dimension='feature')
    monkeypatch.setattr(service, '_dimension_call_with_gaps', lambda *a, **kw: pytest.fail('pure clarification called a model'))
    coverage, gaps, sizes = await service._dimension_question_coverage(run, questions, {}, [], view, use,
        ('question_core_context_budget_exceeded', 'source_exception_unresolved'))
    assert coverage == (pure(questions[0]),)
    assert not sizes and 'answer_coverage_incomplete' not in gaps
    assert set(gaps) == {'question_core_context_budget_exceeded', 'source_exception_unresolved'}


@pytest.mark.asyncio
@pytest.mark.parametrize('question', [
    'Example Product: 如何移除成员对密码的访问？',
    "Example Product: How do I remove a member's access to passwords?",
    'Example Product: What does "remove member access to data" mean?',
    'Example Product: 离职之后，如何移除成员对密码的访问？',
    "Example Product: After offboarding, how do I remove a member's access to passwords?",
    'Example Product: 移除成员后，如何移除他对密码的访问？',
    'Example Product: After removing a member, how do I remove their access to passwords?',
])
async def test_instruction_or_definition_request_stays_on_research_path_without_pure_delivery(monkeypatch, question):
    from test_writer_question_delivery import lifecycle_case, service_for
    from packages.agents.qa.evidence_alignment import audit_dimension_claims
    from packages.agents.writer.answer_coverage import research_questions
    from packages.agents.writer.dimension_writer import render_dimension_report
    from packages.research.evidence.report_claims import ReportDimensionAudit
    from packages.research.evidence.snapshot import current_snapshot
    assert pure(dict(question_id='q', question=question)) is None
    detail, _ = lifecycle_case()
    detail.plan.decision_brief.decision_question = question
    service, run = service_for(detail)
    view, use = service._begin_evidence_use(run, agent='writer', competitor='Example Product', dimension='feature')
    monkeypatch.setattr(service, '_dimension_call_with_gaps', lambda *a, **kw: pytest.fail('zero supported research called a model'))
    questions = research_questions(detail, 'Example Product', 'feature')
    coverage, gaps, sizes = await service._dimension_question_coverage(run, questions, {}, [], view, use, ())
    assert coverage[0].status == 'unverified' and coverage[0].resolution == 'unresolved'
    assert not coverage[0].answer and not is_qualified_partial_clarification(coverage[0], [])
    assert not sizes and 'answer_coverage_incomplete' in gaps
    audit = ReportDimensionAudit(competitor='Example Product', dimension='feature', consumption_id=use.id,
        claims=[], answer_coverage=coverage, answer_binding_version=3, claim_review_version=3, gaps=gaps)
    detail.report_dimension_audits = [audit]
    snapshot = current_snapshot(detail)
    detail.report_md = render_dimension_report(detail, [audit], snapshot=snapshot)
    service._record_evidence_artifact(run, kind='writer', uses=[use], payload=service._writer_evidence_artifact_payload(detail))
    run.detail = type(detail).model_validate_json(detail.model_dump_json())
    issues = audit_dimension_claims(service, run, snapshot, producer_verified=True)
    assert any(issue.metadata.get('claim_audit_reason') == 'answer_coverage_incomplete' for issue in issues)


@pytest.mark.asyncio
@pytest.mark.parametrize('question,statuses', [
    ('Example Product: 移除成员后，他的密码还会留下，以及 Free 套餐能否让 3 人共享 3 个 collections？', ['unverified']),
    ('Example Product: After removing a member, will their passwords remain, and does Free allow sharing 3 collections with 3 people?', ['unverified']),
    ('Example Product: 移除成员后，他的密码还会留下吗？Free 套餐能否让 3 人共享 3 个 collections？', ['partial', 'unverified']),
    ('Example Product: 我们准备把离职同事“删掉”，他保存的那些密码之后还会留下吗？', ['partial']),
    ('Example Product: After removing a member, will their passwords remain?', ['partial']),
])
async def test_pure_delivery_cannot_swallow_independent_subquestion_in_actual_writer(monkeypatch, question, statuses):
    from claim_review_fixture import expand_prompt_payload, question_plan_response
    from test_writer_question_delivery import lifecycle_case, service_for
    from packages.agents.qa.evidence_alignment import audit_dimension_claims
    from packages.agents.writer.answer_coverage import research_questions
    from packages.research.evidence.snapshot import current_snapshot
    from packages.schema.decision_brief import safe_decision_brief_text
    detail, _ = lifecycle_case()
    detail.plan.decision_brief.decision_question = question
    service, run = service_for(detail)
    assert len(research_questions(detail, 'Example Product', 'feature')) == len(statuses)
    calls = []

    async def model(_run, **kwargs):
        calls.append(kwargs['name'])
        assert kwargs['name'] == 'dimension_claim_writer'
        payload = expand_prompt_payload(json.loads(kwargs['user'].split('\nJSON:\n', 1)[1]))
        return question_plan_response(payload, [])

    monkeypatch.setattr(service, '_trace_llm_text', model)
    monkeypatch.setattr('packages.agents.writer.question_retrieval.get_local_provider_from_env', lambda *_: None)
    await service._real_writer_step(run)
    run.detail = type(detail).model_validate_json(run.detail.model_dump_json())
    audit = run.detail.report_dimension_audits[0]
    assert [row.status for row in audit.answer_coverage] == statuses
    assert calls == ['dimension_claim_writer']
    assert service._evidence_artifact_valid(run, kind='writer', payload=service._writer_evidence_artifact_payload(run.detail))
    for row in audit.answer_coverage:
        assert not row.claim_ids and not row.evidence_spans
        if row.status == 'partial':
            assert row == pure(dict(question_id=row.question_id, question=row.question))
            assert safe_decision_brief_text(row.answer) in run.detail.report_md
        else:
            assert not row.answer and not is_qualified_partial_clarification(row, [])
    incomplete = 'unverified' in statuses
    assert ('answer_coverage_incomplete' in audit.gaps) == incomplete
    issues = audit_dimension_claims(service, run, current_snapshot(run.detail), producer_verified=True)
    assert any(issue.metadata.get('claim_audit_reason') == 'answer_coverage_incomplete' for issue in issues) == incomplete


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['free_cap', 'ownership_only', 'unusable_source_proposal'])
async def test_unrelated_or_incomplete_source_result_cannot_suppress_request_only_delivery(monkeypatch, mode):
    from test_atomic_question_answers import rule_claim
    from test_writer_question_delivery import lifecycle_case, service_for
    from test_literal_non_operation import draft, fact
    from test_source_span_binding import spans
    from packages.agents.writer.answer_coverage import research_questions
    from packages.research.evidence.report_claims import ReportClaim
    detail, _ = lifecycle_case()
    service, run = service_for(detail)
    question = research_questions(detail, 'Example Product', 'feature')[1]
    if mode == 'free_cap':
        claim = ReportClaim.model_validate(FIXTURE['claims'][0])
    elif mode == 'ownership_only':
        original = fact(quote='Organizations own all collections.')
        claim = ReportClaim(id='ownership-only', **draft(original, original.quote), source_span_bindings=[spans(original)[0]])
    else:
        _, row = rule_claim()
        claim = ReportClaim.model_validate(row)
    view, use = service._begin_evidence_use(run, agent='writer', competitor='Example Product', dimension='feature')
    calls = []

    async def model(_run, gaps, **kwargs):
        calls.append(kwargs['name'])
        return json.dumps(dict(version=3, answers=[])), gaps

    monkeypatch.setattr(service, '_dimension_call_with_gaps', model)
    coverage, gaps, _ = await service._dimension_question_coverage(run, [question], {},
        [SimpleNamespace(status='supported', claim=claim)], view, use, ('source_exception_unresolved',))
    assert coverage == (pure(question),)
    assert gaps == ('source_exception_unresolved',)
    assert calls == (['dimension_answer_coverage', 'dimension_answer_review'] if mode == 'unusable_source_proposal' else [])


@pytest.mark.asyncio
@pytest.mark.parametrize('question', [
    'Example Product: Can Basic share passwords with 3 people?',
    'Example Product: Can Basic store 3 GB of data?',
    'Example Product: Is the minimum 3 people?',
    'Example Product: Can I add two groups of 2 users?',
    'Example Product: Does a 2026 account get the same limit?',
    'Example Product: Can 3 people share 3 collections?',
])
async def test_quantity_format_never_skips_independent_numeric_scope_date_or_multi_question_review(monkeypatch, question):
    from test_writer_question_delivery import lifecycle_case, service_for
    from test_literal_non_operation import draft, fact
    from test_source_span_binding import spans
    from packages.research.evidence.report_claims import ReportClaim
    detail, _ = lifecycle_case()
    service, run = service_for(detail)
    original = fact(quote='Basic includes up to 2 users.')
    claim = ReportClaim(id='cap', **draft(original, original.quote), source_span_bindings=[spans(original)[0]])
    view, use = service._begin_evidence_use(run, agent='writer', competitor='Example Product', dimension='feature')
    calls = []

    async def model(_run, gaps, **kwargs):
        calls.append(kwargs['name'])
        row = dict(question_id='numeric', status='answered', resolution='direct', conclusion='no',
            claim_ids=['cap'], missing_fields=[], reason='Proposal needs independent verification.')
        if kwargs['name'] == 'dimension_answer_review':
            assert original.quote in kwargs['user']
            row.update(status='unverified', resolution='unresolved', conclusion='unknown', claim_ids=[],
                       reason='The selected rule does not establish this scenario.')
        return json.dumps(dict(version=3, answers=[row])), gaps

    monkeypatch.setattr(service, '_dimension_call_with_gaps', model)
    coverage, gaps, _ = await service._dimension_question_coverage(run, [dict(question_id='numeric', question=question)], {},
        [SimpleNamespace(status='supported', claim=claim)], view, use, ())
    assert calls == ['dimension_answer_coverage', 'dimension_answer_review']
    assert coverage[0].status == 'unverified' and not coverage[0].claim_ids
    assert 'answer_coverage_incomplete' in gaps


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', [None, 'question', 'id', 'body', 'reason', 'fields', 'claims', 'status', 'gap', 'report'])
async def test_saved_pure_record_renderer_and_final_qa_reconstruct_exact_current_question(monkeypatch, mutation):
    from test_writer_question_delivery import lifecycle_case, service_for
    from packages.agents.qa.evidence_alignment import audit_dimension_claims
    from packages.agents.writer.answer_coverage import research_questions
    from packages.agents.writer.dimension_writer import render_dimension_report
    from packages.research.evidence.report_claims import ReportDimensionAudit
    from packages.research.evidence.snapshot import current_snapshot
    detail, _ = lifecycle_case()
    detail.plan.decision_brief.decision_question = detail.plan.decision_brief.decision_question.split('\n')[1]
    service, run = service_for(detail)
    view, use = service._begin_evidence_use(run, agent='writer', competitor='Example Product', dimension='feature')
    question = research_questions(detail, 'Example Product', 'feature')[0]
    answer = pure(question)
    if mutation in {'body', 'reason', 'fields', 'claims', 'status', 'id', 'question'}:
        changes = {'body': {'answer': answer.answer + ' 数据保留。'}, 'reason': {'reason': 'Changed.'},
            'fields': {'missing_fields': ('actual_action',)}, 'claims': {'claim_ids': ('fake',)},
            'status': {'status': 'answered'}, 'id': {'question_id': 'changed'}, 'question': {'question': Q1['question']}}
        answer = answer.model_copy(update=changes[mutation])
    audit = ReportDimensionAudit(competitor='Example Product', dimension='feature', consumption_id=use.id,
        claims=[], answer_coverage=[answer], answer_binding_version=3, claim_review_version=3,
        gaps=['question_core_context_budget_exceeded'] if mutation == 'gap' else [])
    detail.report_dimension_audits = [audit]
    snapshot = current_snapshot(detail)
    detail.report_md = render_dimension_report(detail, [audit], snapshot=snapshot)
    if mutation == 'report':
        detail.report_md = detail.report_md.replace(answer.answer, 'Changed.')
    service._record_evidence_artifact(run, kind='writer', uses=[use], payload=service._writer_evidence_artifact_payload(detail))
    run.detail = type(detail).model_validate_json(detail.model_dump_json())
    issues = audit_dimension_claims(service, run, snapshot, producer_verified=True)
    assert bool(issues) == (mutation is not None), issues
    if mutation is None:
        assert answer.answer in detail.report_md
