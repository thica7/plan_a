"""Offline production GEN5→REVIEW3→ANSWER6 and authenticated consumers."""
import json
from copy import deepcopy

import pytest
from claim_review_fixture import expand_prompt_payload, question_plan_response
from test_question_atomic_delivery import atomic_case, supported_review
from test_task_decision_witnesses import (
    INFERENCE,
    QUESTION,
    RESOURCE_INFERENCE,
    RESOURCE_QUESTION,
    RESOURCE_SOURCE,
    SOURCE,
)
from test_task_support_selection import append_response

from packages.agents.writer import question_atomic_delivery as atomic
from packages.agents.writer.answer_presentation import question_coverage_lines
from packages.agents.writer.dimension_writer import render_dimension_report
from packages.research.evidence.report_claims import ReportDimensionAudit, audit_report_claims

V6 = 'subquestion-premises-v6'
CORE_POLICY = 'approved_quantity_core-v1'


async def delivered(monkeypatch, *, resource=False, decision_change=None, upstream=False,
                    extra_inference=False, answer_change=None, trailing_format=False,
                    resource_labels=None, invalid_peer_review=False, invalid_peer_generation=False,
                    selection_policy='current'):
    if selection_policy != 'current':
        builder = atomic.atomic_answer_payload

        def selected_builder(*args, **kwargs):
            kwargs['decision_selection_policy'] = selection_policy
            return builder(*args, **kwargs)

        monkeypatch.setattr(atomic, 'atomic_answer_payload', selected_builder)
    source, question, text = ((RESOURCE_SOURCE, RESOURCE_QUESTION, RESOURCE_INFERENCE)
                             if resource else (SOURCE, QUESTION, INFERENCE))
    question = question.replace('Trello' if resource else 'Bitwarden', 'Example Product')
    if resource_labels:
        for old, new in zip(('A', 'B'), resource_labels, strict=True):
            question, text = question.replace(old, new), text.replace(old, new)
    if trailing_format:
        question += '请使用表格作答。'
    if invalid_peer_generation:
        question += '\nExample Product：本月账单准确是多少美元？'
    case = await atomic_case([source], question=question)
    service, record, snapshot, selected, view, use, packets, boundaries, allowed = case
    record.detail.report_answer_boundaries = boundaries
    if upstream:
        from test_writer_artifact_consumption import record_upstream
        record_upstream(service, record)
    seen = []

    async def model(record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs['user'].split('\nJSON:\n', 1)[1]))
        seen.append((kwargs, payload))
        if kwargs['name'] == atomic.GENERATION_NAME:
            if (invalid_peer_generation
                    and payload['questions'][0]['question_id']
                    != packets[0]['questions'][0]['question_id']):
                return append_response(service, record, kwargs, '{}')
            span = next(s for f in payload['evidence_view']['facts']
                        for s in f['source_span_candidates'] if s['quote'] == source)
            task = next(t for t in payload['generation_tasks'] if (
                t.get('request_property') == 'container_limit' if not resource else
                '自动决定' in t['question_quote']))
            atom = dict(task_id=task['task_id'], text=text, kind='inference',
                        support_refs=[span['support_ref']])
            atoms = [atom]
            if extra_inference:
                extra = next(t for t in payload['generation_tasks'] if (
                    t.get('request_property') == 'people_limit' if not resource else
                    '免费' in t['question_quote']))
                atoms.append(dict(task_id=extra['task_id'], kind='inference',
                    text=('仅凭 A 上的 Observer 标签不能确定小周一定免费或一定计费。'
                          if resource else
                          'Free organization 无法满足题设 3 个人共享密码的需求。'),
                    support_refs=[span['support_ref']]))
            response = question_plan_response(payload, atoms)
        elif kwargs['name'] == atomic.REVIEW_NAME:
            response = ('{}' if invalid_peer_review and '免费或一定计费'
                        in payload['claims'][0]['text'] else json.dumps(dict(
                            reviews=[supported_review(c) for c in payload['claims']])))
        else:
            assert payload['answer_review_contract'] == V6
            candidates = payload['decision_candidates']
            assert len(candidates) == 1
            c = candidates[0]
            assert payload['decision_source_context'][c['sources'][0]['fact_id']]['quote'] == source
            q = payload['questions'][0]
            ids = [c['claim_id']]
            branches = [dict(question_quote=q['question'], claim_ids=ids, conclusion='no',
                             relation='explicit_negative' if resource else 'upper_bound')]
            if resource:
                first, second = q['question'].split('；', 1)
                branches = [dict(branches[0], question_quote=first+'；'),
                            dict(question_quote=second, claim_ids=[], conclusion='unknown',
                                 relation='unresolved')]
            row = dict(candidate_ref=c['candidate_ref'], task_fulfilled=True,
                       target_grounding='supported', conclusion='no',
                       evidence_refs=c['evidence_refs'], scenario_refs=c['scenario_refs'])
            decisions = [row]
            if decision_change:
                decisions = decision_change(deepcopy(decisions))
            data = dict(version=3, task_decisions=decisions, answers=[dict(
                question_id=q['question_id'], status='partial' if resource else 'answered',
                resolution='conditional' if resource else 'direct',
                conclusion='depends' if resource else 'no', claim_ids=ids, missing_fields=[],
                reason='Independent task review', subquestions=branches)])
            if answer_change:
                answer_change(data, payload)
            response = json.dumps(data)
        return append_response(service, record, kwargs, response)

    monkeypatch.setattr(service, '_trace_llm_text', model)
    result = await atomic.execute_question_atomic_delivery(service, record, selected, view, use,
        packets[0]['questions'], packets, allowed, boundaries, (), answer_review_contract=V6)
    audited = audit_report_claims(result['claims'], result['reviews'], view, boundaries,
        available_facts=view.facts, review_version=3)
    if invalid_peer_review:
        assert [a.status for a in audited] == ['supported', 'unreviewed'], audited
    else:
        assert audited and all(a.status == 'supported' for a in audited), audited
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    answers, _, _ = await service._dimension_question_coverage(record, packets[0]['questions'],
        result['compact'], audited, view, use, ())
    audit = ReportDimensionAudit(competitor=view.competitor, dimension=view.dimension,
        consumption_id=use.id, claims=audited, answer_coverage=answers, answer_binding_version=3,
        claim_review_version=3, answer_review_contract=V6, question_atomic_contract=atomic.CONTRACT,
        question_atomic_receipt_digest=result['compact']['question_atomic_receipt_digest'])
    record.detail.report_dimension_audits = [audit]
    return case, result, audit, seen


@pytest.mark.asyncio
@pytest.mark.parametrize('resource', [False, True])
async def test_v6_inference_reaches_actual_answer_render_replay_and_qa(monkeypatch, resource):
    from packages.agents.qa.question_reconciliation import _answer_support
    case, result, audit, seen = await delivered(monkeypatch, resource=resource)
    service, record, snapshot, _, view, use, packets, _, _ = case
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    answer = audit.answer_coverage[0]
    assert (answer.status, answer.conclusion) == (
        ('partial', 'depends') if resource else ('answered', 'no')), answer
    assert answer.decision_credentials
    record.detail.report_md = render_dimension_report(record.detail, [audit], snapshot=snapshot)
    assert (RESOURCE_INFERENCE if resource else INFERENCE) in record.detail.report_md
    assert '结论：否' in record.detail.report_md
    assert _answer_support(record.detail, snapshot, audit, answer, packets[0]['questions'][0])
    replay = atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view, audit=audit)
    assert replay['answers'][answer.question_id] == answer
    assert replay['decision_review']
    assert '结论：否' not in '\n'.join(question_coverage_lines(audit, 'zh-CN'))
    assert [kw['name'] for kw, _ in seen].count(atomic.ANSWER_NAME) == 1


@pytest.mark.asyncio
async def test_current_answer_projection_reuses_claims_and_preserves_full_material(monkeypatch):
    from packages.agents.writer.dimension_writer import compact_prompt_json
    case, result, audit, seen = await delivered(monkeypatch, upstream=True)
    service, record, _, _, view, use, packets, *_ = case
    kwargs, payload = next((kw, p) for kw, p in seen if kw['name'] == atomic.ANSWER_NAME)
    assert payload['decision_candidate_projection_version'] == 2
    legacy = atomic.atomic_answer_payload(service, record, packets[0]['questions'],
        [a.claim for a in audit.claims if a.status == 'supported'], view, use, result['compact'],
        answer_review_contract=V6)
    assert 'decision_candidate_projection_version' not in legacy
    assert payload['decision_selection_policy'] == CORE_POLICY
    assert 'decision_selection_policy' not in legacy
    assert {k: v for k, v in payload.items() if k not in {
        'decision_candidates', 'decision_candidate_projection_version',
        'decision_selection_policy'}} == {
        k: v for k, v in legacy.items() if k != 'decision_candidates'}
    for compact, full in zip(payload['decision_candidates'], legacy['decision_candidates'],
                             strict=True):
        assert compact['task'] == full['task']
        assert compact['witness'] == full['witness']
        assert 'claim' not in compact
        assert next(c for c in payload['claims'] if c['id'] == compact['claim_id']) == {
            k: full['claim'][k] for k in ('id', 'text', 'kind')}
        assert all(set(s) == {'source_ref', 'fact_id', 'source_id', 'quote'}
                   for s in compact['sources'])
    assert len(kwargs['user'].encode()) < len(('\nJSON:\n' + compact_prompt_json(legacy)).encode())


@pytest.mark.asyncio
async def test_old_nonempty_v6_transport_keeps_legacy_replay(monkeypatch):
    builder = atomic.atomic_answer_payload

    def legacy_builder(*args, **kwargs):
        kwargs['decision_candidate_projection_version'] = 1
        kwargs['decision_selection_policy'] = None
        return builder(*args, **kwargs)

    monkeypatch.setattr(atomic, 'atomic_answer_payload', legacy_builder)
    case, _, audit, seen = await delivered(monkeypatch)
    service, record, snapshot, _, view, use, *_ = case
    payload = next(p for kw, p in seen if kw['name'] == atomic.ANSWER_NAME)
    assert 'decision_candidate_projection_version' not in payload
    assert payload['decision_candidates'][0]['claim']['kind'] == 'inference'
    monkeypatch.setattr(atomic, 'atomic_answer_payload', builder)
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    replay = atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view, audit=audit)
    assert replay['answers'][audit.answer_coverage[0].question_id] == audit.answer_coverage[0]


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['missing', 'duplicate', 'foreign', 'unfulfilled'])
async def test_v6_unissued_or_invalid_decisions_never_publish(monkeypatch, change):
    def mutate(rows):
        if change == 'missing':
            return []
        if change == 'duplicate':
            return rows * 2
        if change == 'foreign':
            rows[0]['candidate_ref'] = 'invented'
        if change == 'unfulfilled':
            rows[0]['task_fulfilled'] = False
        return rows
    case, _, audit, _ = await delivered(monkeypatch, decision_change=mutate)
    assert audit.answer_coverage[0].status == 'unverified'
    assert '结论：否' not in render_dimension_report(case[1].detail, [audit], snapshot=case[2])


def test_v6_system_is_independent_of_fact_only_legacy_systems():
    system = atomic.atomic_system(atomic.ANSWER_NAME, 'zh-CN', answer_review_contract=V6)
    assert 'Inference does not establish a numeric cap.' not in system
    assert 'not an inference' not in system
    assert atomic.answer_contract_from_system(system, 'zh-CN') == V6


@pytest.mark.asyncio
async def test_uncertified_people_inference_cannot_ride_the_collections_decision(monkeypatch):
    def carry(data, payload):
        ids = [c['id'] for c in payload['claims']]
        data['answers'][0]['claim_ids'] = ids
        data['answers'][0]['subquestions'][0]['claim_ids'] = ids
    _, _, audit, _ = await delivered(monkeypatch, extra_inference=True, answer_change=carry,
                                    selection_policy=None)
    assert len(audit.claims) == 2 and all(c.status == 'supported' for c in audit.claims)
    assert audit.answer_coverage[0].status == 'unverified'


def carry_all_claims(data, payload):
    ids = [c['id'] for c in payload['claims']]
    data['answers'][0]['claim_ids'] = ids
    data['answers'][0]['subquestions'][0]['claim_ids'] = ids


@pytest.mark.asyncio
async def test_explicit_quantity_core_delivers_only_the_original_approved_inference(monkeypatch):
    from packages.agents.qa.question_reconciliation import _answer_support
    from packages.agents.writer.answer_presentation import question_coverage_matches

    case, result, audit, seen = await delivered(
        monkeypatch, extra_inference=True, answer_change=carry_all_claims)
    service, record, snapshot, _, view, use, packets, *_ = case
    answer = audit.answer_coverage[0]
    assert (answer.status, answer.resolution, answer.conclusion) == ('answered', 'direct', 'no')
    assert answer.answer == INFERENCE
    assert len(answer.claim_ids) == len(answer.decision_credentials) == 1
    assert len(audit.claims) == 2
    span = next(s for s in record.detail.trace_spans if s.name == atomic.ANSWER_NAME)
    original = span.full_output
    raw = json.loads(original)['answers'][0]
    assert len(raw['claim_ids']) == len(raw['subquestions'][0]['claim_ids']) == 2
    dispatch = next(d for d in result['compact']['dispatches'] if d['span_id'] == span.id)
    adjustment = dispatch['answer_validation'][0]['adjustments'][0]
    assert adjustment == dict(kind='approved_quantity_core_selected', policy=CORE_POLICY,
        branch_index=0, original_claim_ids=raw['subquestions'][0]['claim_ids'],
        retained_claim_ids=list(answer.claim_ids), excluded_claim_ids=[
            cid for cid in raw['subquestions'][0]['claim_ids'] if cid not in answer.claim_ids])
    record.detail.report_md = render_dimension_report(record.detail, [audit], snapshot=snapshot)
    assert INFERENCE in record.detail.report_md and '结论：否' in record.detail.report_md
    assert 'Free organization 无法满足题设 3 个人共享密码的需求。' not in record.detail.report_md
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    replay = atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view, audit=audit)
    assert replay['answers'][answer.question_id] == answer
    assert question_coverage_matches(record.detail.report_md, audit, 'zh-CN', audits=[audit],
        detail=record.detail, decision_reviews=replay['decision_review'])
    assert _answer_support(record.detail, snapshot, audit, answer, packets[0]['questions'][0])
    assert span.full_output == original
    assert [kw['name'] for kw, _ in seen].count(atomic.ANSWER_NAME) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['status', 'resolution', 'conclusion', 'unknown_peer',
                                  'unselected', 'foreign', 'duplicate'])
async def test_quantity_core_cannot_promote_a_partial_or_invalid_original_choice(
    monkeypatch, change,
):
    def changed(data, payload):
        carry_all_claims(data, payload)
        row = data['answers'][0]
        if change == 'status':
            row['status'] = 'partial'
        elif change == 'resolution':
            row['resolution'] = 'conditional'
        elif change == 'conclusion':
            row['conclusion'] = 'depends'
        elif change == 'unknown_peer':
            question = payload['questions'][0]['question']
            first, second = question.split('。', 1)
            row['subquestions'][0]['question_quote'] = first + '。'
            row['subquestions'].append(dict(question_quote=second, claim_ids=[],
                conclusion='unknown', relation='unresolved'))
        elif change == 'unselected':
            core = payload['decision_candidates'][0]['claim_id']
            row['claim_ids'] = [cid for cid in row['claim_ids'] if cid != core]
            row['subquestions'][0]['claim_ids'] = row['claim_ids']
        else:
            ids = [*row['claim_ids'], 'foreign' if change == 'foreign' else row['claim_ids'][0]]
            row['claim_ids'] = row['subquestions'][0]['claim_ids'] = ids
    _, _, audit, _ = await delivered(monkeypatch, extra_inference=True, answer_change=changed)
    assert audit.answer_coverage[0].status == 'unverified'


@pytest.mark.asyncio
async def test_no_policy_mixed_choice_replays_without_receiving_a_new_qualification(monkeypatch):
    builder = atomic.atomic_answer_payload
    case, _, audit, seen = await delivered(monkeypatch, extra_inference=True,
        answer_change=carry_all_claims, selection_policy=None)
    monkeypatch.setattr(atomic, 'atomic_answer_payload', builder)
    service, record, snapshot, _, view, use, *_ = case
    assert 'decision_selection_policy' not in next(
        p for kw, p in seen if kw['name'] == atomic.ANSWER_NAME)
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    replay = atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view, audit=audit)
    assert replay['answers'][audit.answer_coverage[0].question_id] == audit.answer_coverage[0]
    assert audit.answer_coverage[0].status == 'unverified'


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['marker', 'missing_marker', 'null_marker',
                                  'original_claim_ids', 'retained_claim_ids', 'excluded_claim_ids'])
async def test_quantity_core_replay_recomputes_policy_and_selection(monkeypatch, change):
    case, _, audit, _ = await delivered(monkeypatch, extra_inference=True,
                                      answer_change=carry_all_claims)
    service, record, snapshot, _, view, use, *_ = case
    receipt_span = next(s for s in record.detail.trace_spans
                        if s.name == 'question_atomic_delivery')
    receipt = json.loads(receipt_span.full_output)
    span = next(s for s in record.detail.trace_spans if s.name == atomic.ANSWER_NAME)
    dispatch = next(d for d in receipt['dispatches'] if d['span_id'] == span.id)
    if change in {'marker', 'missing_marker', 'null_marker'}:
        system, raw = span.full_input.split('\nJSON:\n', 1)
        payload = expand_prompt_payload(json.loads(raw))
        if change == 'missing_marker':
            payload.pop('decision_selection_policy')
        else:
            payload['decision_selection_policy'] = (
                None if change == 'null_marker' else 'approved_quantity_core-v2')
        span.full_input = system + '\nJSON:\n' + json.dumps(payload)
        dispatch['full_input_sha256'] = atomic.digest(span.full_input)
    else:
        dispatch['answer_validation'][0]['adjustments'][0][change] = []
    receipt_span.full_output = json.dumps(receipt)
    audit = audit.model_copy(update={'question_atomic_receipt_digest': atomic.digest(receipt)})
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    with pytest.raises(ValueError):
        atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view, audit=audit)


@pytest.mark.asyncio
async def test_quantity_core_still_sends_the_complete_question_to_independent_qa_and_keeps_gaps(
    monkeypatch,
):
    from question_review_fixture import review_payload
    from test_final_question_reconciliation import reviewed
    from test_independent_final_question_qa import traced_model_double

    from packages.agents.qa.question_reconciliation import reconcile_question_findings

    case, _, audit, _ = await delivered(monkeypatch, upstream=True, extra_inference=True,
                                       answer_change=carry_all_claims)
    service, record, snapshot, _, _, use, packets, *_ = case
    record.detail.report_md = render_dimension_report(record.detail, [audit], snapshot=snapshot)
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    service._record_evidence_artifact(record, kind='writer', uses=[use],
        payload=service._writer_evidence_artifact_payload(record.detail))
    assert service._final_qa_producer_verified(record, snapshot)
    observed = []

    async def review(record, **kwargs):
        assert kwargs['name'] == 'final_question_reconciliation'
        payload = review_payload(kwargs['user'].split('\nJSON:\n', 1)[1])
        observed.append(payload)
        row = payload['findings'][0]
        context = payload.get('question_contexts', {}).get(row.get('context_id'), row)
        assert context['question'] == packets[0]['questions'][0]['question']
        assert context['answer']['answer'] == INFERENCE
        assert context['answer']['claim_ids'] == list(audit.answer_coverage[0].claim_ids)
        response = json.loads(reviewed(payload, 'keep'))
        response['reviews'][0].update(finding_fully_addressed=False,
            remaining_gaps=['The complete current question still requires semantic review.'])
        return json.dumps(response)

    traced_model_double(monkeypatch, service, review)
    issues = await reconcile_question_findings(service, record, [], evidence_issues=[])
    assert len(observed) == len(issues) == 1
    assert issues[0].metadata['issue_kind'] == 'independent_final_question'
    assert 'complete current question' in issues[0].problem


@pytest.mark.asyncio
@pytest.mark.parametrize('conclusion', ['no', 'yes', 'not_applicable'])
async def test_quantity_intent_cannot_bypass_missing_decision_with_relation_or_conclusion(
    monkeypatch, conclusion,
):
    def change(data, payload):
        data['task_decisions'] = []
        row = data['answers'][0]
        row['conclusion'] = conclusion
        row['subquestions'][0].update(conclusion=conclusion, relation='explicit_negative')
    _, _, audit, _ = await delivered(monkeypatch, answer_change=change)
    assert audit.answer_coverage[0].status == 'unverified'


@pytest.mark.asyncio
async def test_billing_claim_cannot_reenter_as_not_applicable_format_branch(monkeypatch):
    def reenter(data, payload):
        row = data['answers'][0]
        billing = next(r for r in payload['question_task_claims']
                       if '免费或一定计费' in r['question_quote'])
        billing_id = billing['claim_ids'][0]
        all_ids = [c['id'] for c in payload['claims']]
        row['claim_ids'] = all_ids
        # The actual billing request remains unknown while a formatting tail
        # tries to select the very same ungrounded billing inference.
        second = row['subquestions'][1]
        second['question_quote'] = second['question_quote'].removesuffix('请使用表格作答。')
        row['subquestions'].append(dict(question_quote='请使用表格作答。',
            claim_ids=[billing_id], conclusion='not_applicable', relation='direct'))
    case, _, audit, _ = await delivered(monkeypatch, resource=True, extra_inference=True,
        answer_change=reenter, trailing_format=True)
    answer = audit.answer_coverage[0]
    assert len(audit.claims) == 2
    assert answer.status == 'partial'
    assert answer.subquestion_bindings[-1].conclusion == 'unknown'
    assert len(answer.claim_ids) == 1
    rendered = render_dimension_report(case[1].detail, [audit], snapshot=case[2])
    assert RESOURCE_INFERENCE in rendered
    assert '仅凭 A 上的 Observer 标签不能确定小周一定免费或一定计费。' not in rendered


@pytest.mark.asyncio
async def test_resource_credential_cannot_answer_an_unselected_billing_sibling(monkeypatch):
    def collapse(data, payload):
        row = data['answers'][0]
        row.update(status='answered', resolution='direct', conclusion='no')
        row['subquestions'] = [dict(row['subquestions'][0],
            question_quote=payload['questions'][0]['question'])]
    _, _, audit, _ = await delivered(monkeypatch, resource=True, answer_change=collapse)
    assert audit.answer_coverage[0].status == 'unverified'


@pytest.mark.asyncio
async def test_v6_preserves_the_helpers_existing_numbered_resource_identity(monkeypatch):
    _, _, audit, _ = await delivered(monkeypatch, resource=True, resource_labels=('A1', 'B2'))
    answer = audit.answer_coverage[0]
    assert (answer.status, answer.conclusion) == ('partial', 'depends')
    assert answer.decision_credentials[0].witness_kind == 'resource_non_entailment'


@pytest.mark.asyncio
@pytest.mark.parametrize('phase', ['review', 'generation'])
async def test_unrelated_actual_parser_failure_keeps_the_reviewed_resource_peer(monkeypatch, phase):
    from packages.agents.qa.question_reconciliation import _answer_support

    case, _, audit, seen = await delivered(monkeypatch, resource=True,
        extra_inference=phase == 'review', invalid_peer_review=phase == 'review',
        invalid_peer_generation=phase == 'generation')
    service, record, snapshot, _, view, use, packets, _, _ = case
    answer = audit.answer_coverage[0]
    assert (answer.status, answer.conclusion) == ('partial', 'depends'), answer
    assert answer.subquestion_bindings[0].conclusion == 'no'
    assert answer.subquestion_bindings[1].conclusion == 'unknown'
    assert len(answer.decision_credentials) == 1
    payload = next(p for kw, p in seen if kw['name'] == atomic.ANSWER_NAME)
    assert len(payload['decision_candidates']) == 1
    assert len(payload['question_task_claims']) == (2 if phase == 'review' else 1)
    record.detail.report_md = render_dimension_report(record.detail, [audit], snapshot=snapshot)
    assert RESOURCE_INFERENCE in record.detail.report_md
    assert _answer_support(record.detail, snapshot, audit, answer, packets[0]['questions'][0])
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    assert atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view,
        audit=audit)['answers'][answer.question_id] == answer


@pytest.mark.asyncio
async def test_invalid_review_peer_transport_still_revokes_authentication(monkeypatch):
    from packages.agents.writer.question_atomic_delivery import replay_decision_reviews

    case, _, audit, _ = await delivered(monkeypatch, resource=True,
        extra_inference=True, invalid_peer_review=True)
    span = next(s for s in case[1].detail.trace_spans
                if s.name == atomic.REVIEW_NAME and s.full_output == '{}')
    span.metadata['llm_transport_attempts'] = 0
    with pytest.raises(ValueError):
        replay_decision_reviews(case[1].detail, audit)
    assert '结论：否' not in '\n'.join(question_coverage_lines(
        audit, 'zh-CN', detail=case[1].detail))


@pytest.mark.asyncio
async def test_actual_final_evidence_audit_accepts_authenticated_v6_answer(monkeypatch):
    from packages.agents.qa.evidence_alignment import audit_dimension_claims
    from packages.agents.qa.question_context import question_delivery_complete
    case, _, audit, _ = await delivered(monkeypatch)
    service, record, snapshot, _, _, use, packets, _, _ = case
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    record.detail.report_md = render_dimension_report(record.detail, [audit], snapshot=snapshot)
    service._record_evidence_artifact(record, kind='writer', uses=[use],
        payload=service._writer_evidence_artifact_payload(record.detail))
    issues = audit_dimension_claims(service, record, snapshot, producer_verified=True)
    assert not issues, [(i.metadata, i.problem) for i in issues]
    assert question_delivery_complete(service, record.detail, snapshot, audit,
                                      packets[0]['questions'][0])


@pytest.mark.asyncio
async def test_render_with_real_upstream_validators_never_mutates_live_detail(monkeypatch):
    case, _, audit, seen = await delivered(monkeypatch, upstream=True)
    _, record, snapshot, *_ = case
    answer_payload = next(p for kw, p in seen if kw['name'] == atomic.ANSWER_NAME)
    assert all(answer_payload.get(k) for k in (
        'upstream_analysis', 'comparison_assessment', 'reflection_constraints'))
    before = record.detail.model_dump(mode='json')
    rendered = render_dimension_report(record.detail, [audit], snapshot=snapshot)
    assert INFERENCE in rendered and '结论：否' in rendered
    assert before == record.detail.model_dump(mode='json')
    dependency = next(d for d in record.detail.evidence_artifact_dependencies
                      if d.kind == 'analyst')
    record.detail.evidence_artifact_dependencies = [
        d.model_copy(update={'payload_hash': 'tampered'}) if d == dependency else d
        for d in record.detail.evidence_artifact_dependencies]
    before = record.detail.model_dump(mode='json')
    assert '结论：否' not in render_dimension_report(record.detail, [audit], snapshot=snapshot)
    assert before == record.detail.model_dump(mode='json')


@pytest.mark.asyncio
@pytest.mark.parametrize('changed', ['parent', 'task', 'source', 'claim', 'fact', 'missing_fact',
                                    'selected_span', 'review', 'answer', 'credential'])
async def test_authenticated_persisted_consumers_reject_changed_inputs(monkeypatch, changed):
    from packages.agents.qa.question_reconciliation import _answer_support
    case, _, audit, _ = await delivered(monkeypatch)
    service, record, snapshot, _, view, use, packets, _, _ = case
    detail = record.detail
    use = next(u for u in detail.evidence_consumptions if u.id == use.id)
    detail.report_md = render_dimension_report(detail, [audit], snapshot=snapshot)
    receipt_span = next(s for s in detail.trace_spans if s.name == 'question_atomic_delivery')
    receipt = json.loads(receipt_span.full_output)
    if changed in {'parent', 'task', 'source', 'review', 'answer'}:
        name = atomic.REVIEW_NAME if changed == 'review' else (
            atomic.ANSWER_NAME if changed in {'parent', 'answer'} else atomic.GENERATION_NAME)
        span = next(s for s in detail.trace_spans if s.name == name)
        dispatch = next(d for d in receipt['dispatches'] if d['span_id'] == span.id)
        if changed in {'parent', 'task', 'source'}:
            system, raw = span.full_input.split('\nJSON:\n', 1)
            payload = expand_prompt_payload(json.loads(raw))
            if changed == 'parent':
                payload['request_context']['parents'][0]['text'] += ' changed'
            elif changed == 'task':
                payload['generation_tasks'][0]['question_quote'] = 'wrong predicate'
            else:
                payload['evidence_view']['facts'][0]['source_id'] = 'foreign-source'
            span.full_input = system + '\nJSON:\n' + json.dumps(payload)
            dispatch['full_input_sha256'] = atomic.digest(span.full_input)
        else:
            span.full_output = '{}'
            dispatch['full_output_sha256'] = atomic.digest(span.full_output)
        receipt_span.full_output = json.dumps(receipt)
        audit = audit.model_copy(update={'question_atomic_receipt_digest': atomic.digest(receipt)})
    elif changed in {'fact', 'missing_fact'}:
        fact = snapshot.facts[0].model_copy(update={'quote': 'Changed original'})
        snapshot = snapshot.model_copy(update={
            'facts': () if changed == 'missing_fact' else (fact,)})
        detail.evidence_snapshots = [snapshot]
    elif changed in {'claim', 'selected_span'}:
        item = audit.claims[0]
        updates = {'text': 'Changed deduction'} if changed == 'claim' else {
            'source_span_bindings': (item.claim.source_span_bindings[0].model_copy(
                update={'end': item.claim.source_span_bindings[0].end + 1}),)}
        audit = audit.model_copy(update={'claims': (item.model_copy(update={
            'claim': item.claim.model_copy(update=updates)}),)})
    else:
        answer = audit.answer_coverage[0]
        credential = answer.decision_credentials[0].model_copy(update={'binding_sha256': '0' * 64})
        answer = answer.model_copy(update={'decision_credentials': (credential,)})
        audit = audit.model_copy(update={'answer_coverage': (answer,)})
    detail.report_dimension_audits = [audit]
    with pytest.raises((ValueError, RuntimeError)):
        atomic.replay_atomic_delivery(service, detail, snapshot, use, view, audit=audit)
    assert '结论：否' not in '\n'.join(question_coverage_lines(audit, 'zh-CN', detail=detail))
    assert _answer_support(detail, snapshot, audit, audit.answer_coverage[0],
                           packets[0]['questions'][0]) is None


@pytest.mark.asyncio
async def test_authenticated_context_does_not_excuse_missing_consumer_originals(monkeypatch):
    from packages.agents.writer.answer_coverage import coverage_resolution_reasons
    case, _, audit, _ = await delivered(monkeypatch)
    service, record, snapshot, _, view, use, *_ = case
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    answer = audit.answer_coverage[0]
    replay = atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view, audit=audit)
    review = replay['decision_review'][answer.question_id]
    claims = [c.claim.model_dump(mode='json') for c in audit.claims]
    assert coverage_resolution_reasons(answer, claims, facts=(),
        answer_review_contract=V6, require_subquestions=True, decision_review=review)
