"""Bounded quantity conjunction delivery with original real BW transports."""
import json
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_task_decision_witnesses import (
    QUESTION,
    make_case,
    quantity_core_case,
    with_unclaimed_task,
)

from packages.agents.writer import question_atomic_delivery as atomic
from packages.agents.writer.answer_coverage import parse_answer_coverage

POLICY = 'reviewed_quantity_conjunction-v1'
V6 = 'subquestion-premises-v6'


def partial_answer(output, payload):
    row = output['answers'][0]
    row.update(status='partial', resolution='clarification', conclusion='depends')
    row['subquestions'][0]['conclusion'] = 'depends'
    payload['delivery_policy'] = 'complete-predicates-v1'


def synthetic_review(*, question=QUESTION, policy=POLICY, change=None, context_change=None):
    context = with_unclaimed_task(make_case(question=question))
    if context_change:
        context = context_change(context)

    def mutate(output, payload):
        partial_answer(output, payload)
        if change:
            change(output, payload)

    review, _, _ = quantity_core_case(context, policy=policy, change=mutate)
    review.context.compact['delivery_policy'] = 'complete-predicates-v1'
    if policy != 'absent':
        review.context.compact['decision_selection_policy'] = policy
    return review


def parsed(review):
    span = next(s for s in review.context.trace_spans
                if s.id == review.answer_dispatch['span_id'])
    claims = [a.claim.model_dump(mode='json') for a in review.context.audited_claims
              if a.status == 'supported']
    diagnostics = []
    rows = parse_answer_coverage(span.full_output, list(review.context.questions),
        {c['id'] for c in claims}, claims=claims, required_binding_version=3,
        require_subquestions=True, facts=review.context.facts,
        answer_review_contract=V6, decision_review=review, diagnostics=diagnostics)
    return rows[0], diagnostics






def test_partial_quantity_conjunction_projects_server_no_and_keeps_original_diagnostic():
    review = synthetic_review()
    raw = review.context.trace_spans[-1].full_output
    answer, diagnostics = parsed(review)
    assert (answer.status, answer.resolution, answer.conclusion) == ('answered', 'direct', 'no')
    assert answer.answer == review.context.audited_claims[0].claim.text
    assert answer.decision_credentials
    adjustment, = diagnostics[0]['adjustments']
    assert adjustment['kind'] == 'quantity_conjunction_aggregated'
    assert adjustment['policy'] == POLICY
    assert adjustment['original_answer'] == json.loads(raw)['answers'][0]
    assert review.context.trace_spans[-1].full_output == raw


@pytest.mark.parametrize('policy', ['absent', 'approved_quantity_core-v1'])
def test_old_selection_policies_do_not_aggregate_partial_quantity_answers(policy):
    answer, _ = parsed(synthetic_review(policy=policy))
    assert answer.status == 'unverified'


@pytest.mark.parametrize('change', ['yes', 'unknown', 'branch_yes', 'clarification',
    'no_decision', 'wrong_decision', 'foreign_claim', 'split_branch'])
def test_partial_projection_preserves_unapproved_or_required_unknowns(change):
    def mutate(output, payload):
        row = output['answers'][0]
        if change in {'yes', 'unknown'}:
            row['conclusion'] = change
        elif change == 'branch_yes':
            row['subquestions'][0]['conclusion'] = 'yes'
        elif change == 'clarification':
            row['missing_fields'] = ['role']
        elif change == 'no_decision':
            output['task_decisions'] = []
        elif change == 'wrong_decision':
            output['task_decisions'][0]['target_grounding'] = 'unknown'
        elif change == 'foreign_claim':
            row['claim_ids'] = ['foreign']
        else:
            row['subquestions'].append(deepcopy(row['subquestions'][0]))
    answer, diagnostics = parsed(synthetic_review(change=mutate))
    assert answer.status != 'answered' or answer.conclusion != 'no'
    assert not any(a['kind'] == 'quantity_conjunction_aggregated'
                   for a in diagnostics[0]['adjustments'])


@pytest.mark.parametrize('suffix', [
    '请分别回答人数和集合是否满足。', '还要导出全部密码，能满足吗？',
    '如果管理员批准才能共享，能满足吗？'])
def test_or_independent_mixed_and_conditional_requests_are_not_aggregated(suffix):
    answer, diagnostics = parsed(synthetic_review(question=QUESTION + suffix))
    assert answer.status != 'answered' or answer.conclusion != 'no'
    assert not any(a['kind'] == 'quantity_conjunction_aggregated'
                   for a in diagnostics[0]['adjustments'])


@pytest.mark.parametrize('suffix', [
    '或者只要 3 个人满足即可。', ' Either requirement is sufficient.'])
def test_or_requests_do_not_issue_a_decisive_quantity_credential(suffix):
    from packages.agents.writer.task_decision_witnesses import build_decision_candidates
    context = with_unclaimed_task(make_case(question=QUESTION + suffix))
    assert build_decision_candidates(context) == ()


@pytest.mark.parametrize('prop,quote,focus', [
    ('people_limit', '多少人', 'source_rule'),
    ('people_limit', '3 个 collections', 'source_rule'),
    ('price', '账单是多少', 'billing_inputs'),
    ('people_limit', '3 个人', 'edit'),
])
def test_every_real_quantity_task_must_have_the_exact_known_unit(prop, quote, focus):
    def context_change(context):
        from packages.agents.writer.dimension_writer import compact_prompt_json
        span = context.trace_spans[0]
        system, payload = context.expected_inputs[span.id]
        task = next(t for t in payload['generation_tasks'] if t['task_id'] == 'unclaimed')
        task.update(request_property=prop, question_quote=quote, focus=focus)
        span.full_input = system + '\nJSON:\n' + compact_prompt_json(payload)
        context.compact['dispatches'][0]['full_input_sha256'] = atomic.digest(span.full_input)
        _, _, plans = atomic.parse_atomic_generation(span.full_output, payload,
            SimpleNamespace(facts=context.facts), SimpleNamespace(id=context.consumption_id))
        plan = {}
        atomic.merge_generation_plan(plan, plans[0], attempt=0)
        context.compact['question_answer_plans'] = [plan]
        return context
    answer, diagnostics = parsed(synthetic_review(context_change=context_change))
    assert answer.status != 'answered' or answer.conclusion != 'no'
    assert not any(a['kind'] == 'quantity_conjunction_aggregated'
                   for a in diagnostics[0]['adjustments'])


@pytest.mark.parametrize('change', ['missing_receipt_policy', 'missing_delivery_policy',
    'wrong_scope', 'unreviewed', 'wrong_source_unit'])
def test_new_policy_cannot_self_authorize_or_borrow_a_changed_producer(change):
    review = synthetic_review()
    if change == 'missing_receipt_policy':
        review.context.compact.pop('decision_selection_policy')
    elif change == 'missing_delivery_policy':
        review.context.compact.pop('delivery_policy')
    elif change == 'wrong_scope':
        review.answer_dispatch['question_ids'] = ['another-question']
    elif change == 'unreviewed':
        review = replace(review, context=replace(review.context, audited_claims=tuple(
            a.model_copy(update={'status': 'unreviewed', 'review': None})
            for a in review.context.audited_claims)))
    else:
        review = replace(review, context=replace(review.context, facts=tuple(
            f.model_copy(update={'quote': f.quote.replace('collections', 'vaults')})
            for f in review.context.facts)))
    answer, diagnostics = parsed(review)
    assert answer.status != 'answered' or answer.conclusion != 'no'
    assert not any(a['kind'] == 'quantity_conjunction_aggregated'
                   for a in diagnostics[0]['adjustments'])


async def production_conjunction(monkeypatch):
    from test_task_decision_integration import delivered
    execute = atomic.execute_question_atomic_delivery

    async def complete(*args, **kwargs):
        kwargs['delivery_policy'] = 'complete-predicates-v1'
        return await execute(*args, **kwargs)

    monkeypatch.setattr(atomic, 'execute_question_atomic_delivery', complete)
    return await delivered(monkeypatch, answer_change=partial_answer)


@pytest.mark.asyncio
async def test_production_renders_server_no_and_authenticates_qa_replay(monkeypatch):
    from packages.agents.qa.question_reconciliation import _answer_support
    from packages.agents.writer.dimension_writer import render_dimension_report
    case, result, audit, seen = await production_conjunction(monkeypatch)
    service, record, snapshot, _, view, use, packets, *_ = case
    answer = audit.answer_coverage[0]
    assert (answer.status, answer.resolution, answer.conclusion) == ('answered', 'direct', 'no')
    payload = next(p for kw, p in seen if kw['name'] == atomic.ANSWER_NAME)
    assert payload['decision_selection_policy'] == POLICY
    receipt_span = next(s for s in record.detail.trace_spans
                        if s.name == 'question_atomic_delivery')
    assert json.loads(receipt_span.full_output)['decision_selection_policy'] == POLICY
    span = next(s for s in record.detail.trace_spans if s.name == atomic.ANSWER_NAME)
    assert json.loads(span.full_output)['answers'][0]['conclusion'] == 'depends'
    adjustment, = next(d for d in result['compact']['dispatches']
        if d['span_id'] == span.id)['answer_validation'][0]['adjustments']
    assert adjustment['original_answer']['status'] == 'partial'
    record.detail.report_md = render_dimension_report(record.detail, [audit], snapshot=snapshot)
    assert answer.answer in record.detail.report_md and '结论：否' in record.detail.report_md
    assert _answer_support(record.detail, snapshot, audit, answer, packets[0]['questions'][0])
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    replay = atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view, audit=audit)
    assert replay['answers'][answer.question_id] == answer


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['receipt_policy', 'payload_policy', 'diagnostic'])
async def test_replay_binds_new_policy_and_original_diagnostic(monkeypatch, change):
    from packages.agents.writer.dimension_writer import compact_prompt_json
    from packages.research.question_delivery import _expand_text_refs
    case, _, audit, _ = await production_conjunction(monkeypatch)
    service, record, snapshot, _, view, use, *_ = case
    receipt_span = next(s for s in record.detail.trace_spans
                        if s.name == 'question_atomic_delivery')
    receipt = json.loads(receipt_span.full_output)
    span = next(s for s in record.detail.trace_spans if s.name == atomic.ANSWER_NAME)
    dispatch = next(d for d in receipt['dispatches'] if d['span_id'] == span.id)
    if change == 'receipt_policy':
        receipt.pop('decision_selection_policy')
    elif change == 'payload_policy':
        system, raw = span.full_input.split('\nJSON:\n', 1)
        payload = _expand_text_refs(json.loads(raw))
        payload.pop('decision_selection_policy')
        span.full_input = system + '\nJSON:\n' + compact_prompt_json(payload)
        dispatch['full_input_sha256'] = atomic.digest(span.full_input)
    else:
        dispatch['answer_validation'][0]['adjustments'][0]['original_answer']['conclusion'] = 'yes'
    receipt_span.full_output = json.dumps(receipt)
    audit = audit.model_copy(update={'question_atomic_receipt_digest': atomic.digest(receipt)})
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    with pytest.raises(ValueError):
        atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view, audit=audit)
