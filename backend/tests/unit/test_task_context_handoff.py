"""Offline production-entry checks for task advisory and request handoffs."""

import copy
import hashlib
import json

import pytest
from claim_review_fixture import expand_prompt_payload, supported_review
from test_task_support_selection import append_response, selection_row, writer_case
from test_writer_artifact_consumption import record_upstream

from packages.research.question_scope import research_questions
from packages.schema.models import DecisionBrief

ADVISORIES = ("upstream_analysis", "comparison_assessment", "reflection_constraints")
PARENT = (
    "Example Product：在付费 Workspace 中，外部同事仅被设为看板 A 的 Observer，"
    "看板 B 未邀请。访客有私人区域吗？他能同时加入两个容器吗？"
)
PRESENTATION = '请将可以执行的操作、启用条件与是否存在强制义务分别说明。'


def handoff_case():
    service, record, parts, texts = writer_case()
    record.detail.plan.decision_brief = DecisionBrief(decision_question=PARENT)
    return service, record, parts, texts


def add_capacity_pressure(record, *, terms=70):
    from packages.research.evidence.snapshot import seal_snapshot

    record.detail.plan.decision_brief = DecisionBrief(decision_question=(
        'Example Product：' + '完整共享前提。' * 35
        + '访客有私人区域吗？他能同时加入两个容器吗？'))
    for source in record.detail.raw_sources:
        source.metadata['normalized_fields'][0]['evidence_terms'].append(
            'Canonical retained background. ' * terms)
    seal_snapshot(record.detail, phase='analysis', canonical_documents={})


def restore_historical_parent_context(detail, receipt):
    from packages.agents.writer.task_execution import (
        REQUEST_CONTEXT_SYSTEM_IDENTITY,
        TASK_INSTRUCTION_SYSTEM_IDENTITY,
    )
    from packages.research.question_scope import question_request_context

    for span in detail.trace_spans:
        if span.name not in {'dimension_task_generation', 'dimension_task_review'}:
            continue
        system, raw = span.full_input.split('\nJSON:\n', 1)
        payload = expand_prompt_payload(json.loads(raw))
        payload['request_context'] = question_request_context(
            detail, detail.plan.competitors[0], 'feature', payload['questions'], version=1)
        for assignment in payload.get('task_assignments', ()):
            assignment.pop('instruction', None)
        system = system.replace(TASK_INSTRUCTION_SYSTEM_IDENTITY, '')
        span.full_input = (system.replace(REQUEST_CONTEXT_SYSTEM_IDENTITY, '')
                           + '\nJSON:\n' + json.dumps(payload, ensure_ascii=False))
        digest = hashlib.sha256(span.full_input.encode()).hexdigest()
        for dispatch in receipt['dispatches']:
            if dispatch['span_id'] == span.id:
                dispatch['full_input_sha256'] = digest
        for task in receipt['tasks']:
            if task.get('review_span_id') == span.id:
                task['review_input_sha256'] = digest


def record_large_upstream(service, record):
    """Valid producer sizes exceeding the observed Trello assessment/reflection."""
    from packages.schema.report_artifact import DecisionCard, DecisionCardBundle

    record_upstream(service, record)
    assessment = record.detail.comparison_matrix.assessments['feature']
    assessment.rationale = 'Complete rationale with inseparable conditions. ' * 100
    assessment.gaps = [
        'Example Product: preserve the complete membership prerequisite.',
        *[f'Example Product additional complete comparison gap {i}.' for i in range(24)],
    ]
    reflection = record.detail.reflections[-1]
    reflection.gate_status = 'block'
    reflection.writer_constraints = [
        'An indivisible oversized constraint with all conditions. ' * 100,
        'Example Product: retain the full request role and plan as hypothetical inputs.',
        *[f'Example Product complete advisory constraint {i}.' for i in range(24)],
    ]
    reflection.blocking_gaps = ['Example Product: unresolved evidence is not a denial.']
    card = DecisionCard(id='complete-decision', run_id=record.detail.id,
        decision_type='risk_adjusted_recommendation', subject='feature',
        recommendation='Example Product: preserve the request role and plan.',
        posture='tentative',
        rationale='The complete role condition still needs independent review.',
        claim_card_ids=['analyst-card'], source_ids=[record.detail.raw_sources[0].id],
        evidence_strength='moderate', confidence=.8)
    record.detail.decision_card_bundle = DecisionCardBundle(run_id=record.detail.id, cards=[
        card, card.model_copy(update={'id': 'oversized-decision',
                                     'rationale': 'Indivisible decision rationale. ' * 200})])
    for kind, payload in (
        ('comparator', service._comparator_evidence_artifact_payload(record.detail)),
        ('reflector', reflection.model_dump(mode='json')),
    ):
        _, use = service._begin_evidence_use(record, agent=kind)
        service._validate_evidence_use(record, use)
        service._record_evidence_artifact(record, kind=kind, uses=[use], payload=payload)


def offline_model(service, record, parts, texts, seen, *, attempts=1, trace=True):
    async def model(record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        name = kwargs["name"]
        seen.setdefault(name, []).append(payload)
        if name == "dimension_task_plan":
            result = dict(tasks=[dict(question_id=q["question_id"],
                question_quote=part, focus="source_rule")
                for q in payload["questions"]
                for part in ("访客有私人区域吗？", "他能同时加入两个容器吗？")
                if part in q["question"]])
        elif name == "dimension_task_support_selection":
            spans = [s for row in payload["evidence_view"]["facts"]
                     for s in row.get("source_span_candidates", [])]
            result = dict(selections=[selection_row(t["task_id"], [next(
                s["support_ref"] for s in spans if s["quote"] == texts[
                    int("两个" in t["question_quote"])])]) for t in payload["tasks"]])
        elif name == "dimension_task_generation":
            selections = {s["task_id"]: s for s in payload["task_support_selections"]}
            result = dict(results=[dict(task_id=t["task_id"], status="generated",
                atom=dict(text=texts[int("两个" in t["question_quote"])], kind="fact",
                          support_refs=selections[t["task_id"]]["support_refs"]))
                for t in payload["tasks"]])
        elif name == "dimension_task_review":
            result = dict(reviews=[supported_review(c) for c in payload["claims"]],
                decisions=[dict(task_id=a["task_id"], claim_id=a["claim_id"],
                    task_fulfilled=True, conclusion="no", relation="direct")
                    for a in payload["task_assignments"]])
        else:
            assert name == "dimension_answer_review"
            if not trace:
                return '{}'
            return append_response(service, record, kwargs, None)
        if not trace:
            return json.dumps(result)
        return append_response(service, record, kwargs, json.dumps(result),
            attempts=attempts if name == "dimension_task_generation" else 1)
    return model


@pytest.mark.asyncio
@pytest.mark.parametrize("attempts", [0, 1])
async def test_actual_task_generation_receives_advisories_and_records_only_sent_use(
    monkeypatch, attempts):
    service, record, parts, texts = handoff_case()
    record_upstream(service, record)
    seen = {}
    monkeypatch.setattr(service, "_trace_llm_text", offline_model(
        service, record, parts, texts, seen, attempts=attempts))
    await service._real_writer_step(record)
    payload = seen["dimension_task_generation"][0]
    assert all(payload.get(key) for key in ADVISORIES)
    audit = record.detail.report_dimension_audits[0]
    assert {edge.kind for edge in audit.upstream_dependencies} == (
        {"analyst", "comparator", "reflector"} if attempts else set())


@pytest.mark.asyncio
@pytest.mark.parametrize('attempts', [0, 1])
async def test_large_valid_producers_send_complete_bounded_entries_and_actual_consumption(
    monkeypatch, attempts
):
    from packages.agents.writer.dimension_writer import encoded

    service, record, parts, texts = handoff_case()
    record_large_upstream(service, record)
    seen = {}
    monkeypatch.setattr(service, '_trace_llm_text', offline_model(
        service, record, parts, texts, seen, attempts=attempts))
    await service._real_writer_step(record)
    payload = seen['dimension_task_generation'][0]
    assert all(payload.get(key) for key in ADVISORIES)
    assert payload['upstream_projection_version'] == 2
    assert {'comparator_advisory_entries_omitted', 'reflector_advisory_entries_omitted'} <= set(
        payload['upstream_context_gaps'])
    comparison = payload['comparison_assessment']
    reflection = payload['reflection_constraints']
    assert len(encoded(comparison).encode()) <= 1800
    assert len(encoded(reflection).encode()) <= 1600
    projected = comparison['content']
    original = record.detail.comparison_matrix.assessments['feature']
    assert projected['assessment']['status'] == original.status
    assert projected['omitted_entries']['assessment.rationale'] == 1
    assert 'rationale' not in projected['assessment']
    assert projected['assessment']['gaps']
    assert all(entry in original.gaps for entry in projected['assessment']['gaps'])
    assert projected['omitted_entries']['assessment.gaps'] == (
        len(original.gaps) - len(projected['assessment']['gaps']))
    assert projected['decision_cards'] == [
        record.detail.decision_card_bundle.cards[0].model_dump(mode='json')]
    assert projected['omitted_entries']['decision_cards'] == 1
    projected = reflection['content']
    original = record.detail.reflections[-1]
    assert projected['gate_status'] == 'block'
    assert projected['writer_constraints']
    assert all(entry in original.writer_constraints for entry in projected['writer_constraints'])
    assert original.writer_constraints[0] not in projected['writer_constraints']
    assert projected['omitted_entries']['writer_constraints'] == (
        len(original.writer_constraints) - len(projected['writer_constraints']))
    assert projected['omission_reason'] == 'context_budget_exceeded'
    assert {edge.kind for edge
            in record.detail.report_dimension_audits[0].upstream_dependencies} == (
        {'analyst', 'comparator', 'reflector'} if attempts else set())
    if attempts:
        assert replay(service, record.detail)[1]['sent_fact_ids']


@pytest.mark.asyncio
@pytest.mark.parametrize('change', [
    'content', 'omitted', 'scope', 'missing_version', 'legacy_version'])
async def test_large_projection_replay_rejects_rehashed_content_scope_count_or_version_changes(
    monkeypatch, change
):
    service, record, parts, texts = handoff_case()
    record_large_upstream(service, record)
    monkeypatch.setattr(
        service, '_trace_llm_text', offline_model(service, record, parts, texts, {}))
    await service._real_writer_step(record)
    detail = copy.deepcopy(record.detail)
    receipt_span = next(s for s in detail.trace_spans if s.name == 'question_task_delivery')
    receipt = json.loads(receipt_span.full_output)
    for dispatch in receipt['dispatches']:
        span = next(s for s in detail.trace_spans if s.id == dispatch['span_id'])
        system, raw = span.full_input.split('\nJSON:\n', 1)
        payload = expand_prompt_payload(json.loads(raw))
        content = payload['comparison_assessment']['content']
        if change == 'content':
            content['assessment']['gaps'][0] = 'An invented unrestricted conclusion.'
        elif change == 'omitted':
            content['omitted_entries']['assessment.gaps'] += 1
        elif change == 'scope':
            content['for_competitor'] = 'Other Product'
        else:
            payload.pop('upstream_projection_version')
            payload.pop('comparison_assessment')
            payload.pop('reflection_constraints')
            if change == 'legacy_version':
                payload['upstream_projection_version'] = 1
        span.full_input = system + '\nJSON:\n' + json.dumps(payload, ensure_ascii=False)
        dispatch['full_input_sha256'] = hashlib.sha256(span.full_input.encode()).hexdigest()
    receipt_span.full_output = json.dumps(receipt)
    with pytest.raises(ValueError):
        replay(service, detail)


@pytest.mark.asyncio
async def test_historical_v1_large_producer_payload_keeps_its_original_projection_replay(
    monkeypatch):
    from packages.agents.writer.task_execution import ADVISORY_PROJECTION_SYSTEM_IDENTITY
    from packages.research.evidence.snapshot import current_snapshot
    from packages.research.evidence.views import select_evidence_view

    service, record, parts, texts = handoff_case()
    record_large_upstream(service, record)
    monkeypatch.setattr(
        service, '_trace_llm_text', offline_model(service, record, parts, texts, {}))
    await service._real_writer_step(record)
    detail = copy.deepcopy(record.detail)
    receipt_span = next(s for s in detail.trace_spans if s.name == 'question_task_delivery')
    receipt = json.loads(receipt_span.full_output)
    use = next(u for u in detail.evidence_consumptions if u.id == receipt['consumption_id'])
    view = select_evidence_view(current_snapshot(detail), agent=use.agent,
        competitor=use.competitor, dimension=use.dimension, source_ids=use.requested_source_ids,
        fact_ids=use.requested_fact_ids, max_bytes=use.view_max_bytes or use.max_bytes)
    historical = service._dimension_upstream_context(record, view, projection_version=1)
    assert not any(key in historical for key in ADVISORIES[1:])
    for dispatch in receipt['dispatches']:
        span = next(s for s in detail.trace_spans if s.id == dispatch['span_id'])
        system, raw = span.full_input.split('\nJSON:\n', 1)
        payload = expand_prompt_payload(json.loads(raw))
        for key in (*ADVISORIES, 'upstream_projection_version'):
            payload.pop(key, None)
        payload.update(historical)
        span.full_input = (system.replace(ADVISORY_PROJECTION_SYSTEM_IDENTITY, '')
                           + '\nJSON:\n' + json.dumps(payload, ensure_ascii=False))
        dispatch['full_input_sha256'] = hashlib.sha256(span.full_input.encode()).hexdigest()
    restore_historical_parent_context(detail, receipt)
    receipt_span.full_output = json.dumps(receipt)
    assert replay(service, detail)[1]['sent_fact_ids']


@pytest.mark.asyncio
@pytest.mark.parametrize('presentation', ['', PRESENTATION])
async def test_same_complete_parent_reaches_selection_generation_task_review_answer_and_final_qa(
    monkeypatch, presentation):
    from packages.agents.qa.independent_question_review import _question_context
    from packages.research.evidence.snapshot import current_snapshot

    service, record, parts, texts = handoff_case()
    parent = PARENT + presentation
    record.detail.plan.decision_brief = DecisionBrief(decision_question=parent)
    original = research_questions(record.detail, "Example Product", "feature")
    seen = {}
    monkeypatch.setattr(
        service, "_trace_llm_text", offline_model(service, record, parts, texts, seen))
    await service._real_writer_step(record)
    for name in ("dimension_task_support_selection", "dimension_task_generation",
                 "dimension_task_review", "dimension_answer_review"):
        for payload in seen[name]:
            context = payload['request_context']
            assert [p['text'] for p in context['parents']] == [parent]
            assert {b['question_id'] for b in context['bindings']} == {
                q['question_id'] for q in payload['questions']}
            assert not context['unbound_question_ids']
    audit = record.detail.report_dimension_audits[0]
    for question in original:
        final = _question_context(service, record, current_snapshot(record.detail), question,
                                  audit, verified=False, producer_verified=False)
        assert final['request_context']['parents'][0]['text'] == parent
        assert final['request_context']['bindings'][0]['question_id'] == question['question_id']
    assert research_questions(record.detail, "Example Product", "feature") == original


def test_trello_duty_child_keeps_its_exact_public_identity_and_binds_server_grouping():
    from packages.research.question_scope import question_request_context

    _, record, _, _ = handoff_case()
    parent = (
        'Trello: 假设 Trello Workspace 已订阅 Premium，小林已分别被设为看板 A 和 B 的 Observer；'
        'A 未启用卡片投票，B 已启用且允许该 Observer 投票。仅依据所给官方页面，逐项判断：'
        '小林能在 A、B 投票吗？他能下载 A 的卡片附件并导出 A 吗？'
        'B 允许投票，是否意味着他必须给每张卡片投票？' + PRESENTATION)
    record.detail.plan.competitors = ['Trello']
    record.detail.plan.decision_brief = DecisionBrief(decision_question=parent)
    question = research_questions(record.detail, 'Trello', 'feature')[-1]
    assert question == dict(question_id='question-1305198ad16f108bf375', question=(
        'B 允许投票，是否意味着他必须给每张卡片投票？ ' + PRESENTATION))
    assert question['question'] not in parent
    context = question_request_context(record.detail, 'Trello', 'feature', [question])
    assert not context['unbound_question_ids']
    assert context['parents'][0]['text'] == parent
    assert context['bindings'] == [dict(question_id=question['question_id'],
                                      parent_id=context['parents'][0]['parent_id'])]
    legacy = question_request_context(record.detail, 'Trello', 'feature', [question], version=1)
    assert legacy['version'] == 1 and legacy['unbound_question_ids'] == [question['question_id']]


@pytest.mark.parametrize('space', ['', ' ', '   '])
def test_parent_grouping_preserves_exact_original_separator_whitespace(space):
    from packages.research.question_scope import question_request_context

    _, record, _, _ = handoff_case()
    parent = PARENT + space + PRESENTATION
    record.detail.plan.decision_brief = DecisionBrief(decision_question=parent)
    question = research_questions(record.detail, 'Example Product', 'feature')[-1]
    assert question['question'] == '他能同时加入两个容器吗？ ' + PRESENTATION
    context = question_request_context(record.detail, 'Example Product', 'feature', [question])
    assert context['version'] == 2 and not context['unbound_question_ids']
    assert context['parents'][0]['text'] == parent


@pytest.mark.parametrize('case', ['cross_line', 'ambiguous', 'other_product', 'inner_space'])
def test_parent_grouping_never_normalizes_other_request_content_or_crosses_original_lines(case):
    from packages.research.question_scope import question_request_context

    _, record, _, _ = handoff_case()
    parent = PARENT + PRESENTATION
    record.detail.plan.decision_brief = DecisionBrief(decision_question=parent)
    question = research_questions(record.detail, 'Example Product', 'feature')[-1]
    if case == 'cross_line':
        parent = PARENT + '\n' + PRESENTATION
    elif case == 'ambiguous':
        parent += ('\nExample Product：另一套前提。访客有私人区域吗？他能同时加入两个容器吗？'
                   + PRESENTATION)
    elif case == 'other_product':
        record.detail.plan.competitors.append('Other Product')
        parent = parent.replace('Example Product', 'Other Product')
    else:
        parent = parent.replace('两个容器', '两个 容器')
    record.detail.plan.decision_brief = DecisionBrief(decision_question=parent)
    context = question_request_context(record.detail, 'Example Product', 'feature', [question])
    assert not context['parents'] and not context['bindings']
    assert context['unbound_question_ids'] == [question['question_id']]


@pytest.mark.parametrize("kind", ["other_product", "other_request", "ambiguous"])
def test_parent_context_never_borrows_a_different_or_ambiguous_parent(kind):
    from packages.research.question_scope import question_request_context

    service, record, _, _ = handoff_case()
    q = research_questions(record.detail, "Example Product", "feature")[-1]
    record.detail.plan.competitors.append("Other")
    text = ("Other：管理员已获看板 B 访问。他能同时加入两个容器吗？" if kind == "other_product"
            else "Example Product：管理员已获看板 B 访问。他能下载数据吗？"
            if kind == "other_request"
            else PARENT + "\nExample Product：管理员已获看板 B 访问。他能同时加入两个容器吗？")
    record.detail.plan.decision_brief = DecisionBrief(decision_question=text)
    context = question_request_context(record.detail, "Example Product", "feature", [q])
    assert context["parents"] == [] and context["bindings"] == []


def replay(service, detail):
    from packages.agents.qa.question_context import _question_replays
    from packages.research.evidence.snapshot import current_snapshot
    from packages.research.evidence.views import select_evidence_view

    receipt = json.loads(next(s.full_output for s in detail.trace_spans
                             if s.name == "question_task_delivery"))
    use = next(u for u in detail.evidence_consumptions if u.id == receipt["consumption_id"])
    snapshot = current_snapshot(detail)
    view = select_evidence_view(snapshot, agent=use.agent, competitor=use.competitor,
        dimension=use.dimension, source_ids=use.requested_source_ids,
        fact_ids=use.requested_fact_ids, max_bytes=use.view_max_bytes or use.max_bytes)
    return _question_replays(service, detail, snapshot, use, view)


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["request_context", "upstream_analysis", 'missing_advisory',
                                    'missing_version', 'remove_all_handoff_fields'])
async def test_qa_rebuild_rejects_new_context_tampering_even_with_rehashed_transport(
    monkeypatch, target):
    service, record, parts, texts = handoff_case()
    record_upstream(service, record)
    seen = {}
    monkeypatch.setattr(
        service, "_trace_llm_text", offline_model(service, record, parts, texts, seen))
    await service._real_writer_step(record)
    assert replay(service, record.detail)[1]["sent_fact_ids"]
    detail = copy.deepcopy(record.detail)
    generation = next(s for s in detail.trace_spans if s.name == "dimension_task_generation")
    prefix, raw = generation.full_input.split("\nJSON:\n", 1)
    payload = json.loads(raw)
    if target == 'remove_all_handoff_fields':
        for key in ('task_handoff_version', 'request_context', *ADVISORIES):
            payload.pop(key)
    elif target == 'missing_advisory':
        payload.pop('upstream_analysis')
    elif target == 'missing_version':
        payload.pop('task_handoff_version')
    elif target == "request_context":
        payload[target]["parents"][0]["text"] = "Example Product：管理员可以访问全部看板。"
    else:
        payload[target]["content"] = {"claims": [{"claim": "Invented unrestricted access."}]}
    generation.full_input = prefix + "\nJSON:\n" + json.dumps(payload, ensure_ascii=False)
    receipt_span = next(s for s in detail.trace_spans if s.name == "question_task_delivery")
    receipt = json.loads(receipt_span.full_output)
    if target in {'missing_version', 'remove_all_handoff_fields'}:
        receipt.pop('task_handoff_version')
    if target == 'remove_all_handoff_fields':
        receipt.pop('advisory_delivery')
    receipt["dispatches"][0]["full_input_sha256"] = hashlib.sha256(
        generation.full_input.encode()).hexdigest()
    receipt_span.full_output = json.dumps(receipt)
    with pytest.raises(ValueError):
        replay(service, detail)


@pytest.mark.asyncio
async def test_new_task_review_parent_binding_survives_persistence_and_rejects_rehashed_change(
    monkeypatch):
    from packages.agents.writer.task_projection import reviewed_task_results
    service, record, parts, texts = handoff_case()
    monkeypatch.setattr(
        service, '_trace_llm_text', offline_model(service, record, parts, texts, {}))
    await service._real_writer_step(record)
    audit = record.detail.report_dimension_audits[0]
    detail = type(record.detail).model_validate_json(record.detail.model_dump_json())
    assert reviewed_task_results(detail, audit)
    span = next(s for s in detail.trace_spans if s.name == 'dimension_task_review')
    prefix, raw = span.full_input.split('\nJSON:\n', 1)
    payload = json.loads(raw)
    payload['request_context']['parents'][0]['text'] = 'A different parent request.'
    span.full_input = prefix + '\nJSON:\n' + json.dumps(payload)
    receipt_span = next(s for s in detail.trace_spans if s.name == 'question_task_delivery')
    receipt = json.loads(receipt_span.full_output)
    for task in receipt['tasks']:
        if task.get('review_span_id') == span.id:
            task['review_input_sha256'] = hashlib.sha256(span.full_input.encode()).hexdigest()
    receipt_span.full_output = json.dumps(receipt)
    assert not reviewed_task_results(detail, audit)


@pytest.mark.asyncio
async def test_new_review_cannot_downgrade_to_legacy_by_removing_all_handoff_fields(monkeypatch):
    from packages.agents.writer.task_projection import reviewed_task_results

    service, record, parts, texts = handoff_case()
    record_upstream(service, record)
    monkeypatch.setattr(
        service, '_trace_llm_text', offline_model(service, record, parts, texts, {}))
    await service._real_writer_step(record)
    audit = record.detail.report_dimension_audits[0]
    detail = type(record.detail).model_validate_json(record.detail.model_dump_json())
    assert len(reviewed_task_results(detail, audit)) == 2
    receipt_span = next(s for s in detail.trace_spans if s.name == 'question_task_delivery')
    receipt = json.loads(receipt_span.full_output)
    receipt.pop('task_handoff_version')
    for span in detail.trace_spans:
        if span.name != 'dimension_task_review':
            continue
        system, raw = span.full_input.split('\nJSON:\n', 1)
        payload = json.loads(raw)
        payload.pop('task_handoff_version')
        payload.pop('request_context')
        span.full_input = system + '\nJSON:\n' + json.dumps(payload)
        for task in receipt['tasks']:
            if task.get('review_span_id') == span.id:
                task['review_input_sha256'] = hashlib.sha256(span.full_input.encode()).hexdigest()
    receipt_span.full_output = json.dumps(receipt)
    assert not reviewed_task_results(detail, audit)


@pytest.mark.asyncio
@pytest.mark.parametrize('change', [
    'content', 'missing_advisories', 'legacy_version', 'system_marker'])
async def test_advisory_review_replay_rejects_rehashed_changes(monkeypatch, change):
    from packages.agents.writer.task_execution import ADVISORY_REVIEW_SYSTEM_IDENTITY
    from packages.agents.writer.task_projection import reviewed_task_results

    service, record, parts, texts = handoff_case()
    record_large_upstream(service, record)
    monkeypatch.setattr(service, '_trace_llm_text', offline_model(
        service, record, parts, texts, {}))
    await service._real_writer_step(record)
    detail = copy.deepcopy(record.detail)
    audit = detail.report_dimension_audits[0]
    assert len(reviewed_task_results(detail, audit)) == 2
    assert replay(service, detail)[1]['sent_fact_ids']
    receipt_span = next(s for s in detail.trace_spans if s.name == 'question_task_delivery')
    receipt = json.loads(receipt_span.full_output)
    for span in detail.trace_spans:
        if span.name != 'dimension_task_review':
            continue
        system, raw = span.full_input.split('\nJSON:\n', 1)
        payload = expand_prompt_payload(json.loads(raw))
        if change == 'content':
            payload['comparison_assessment']['content']['assessment']['gaps'][0] = 'Invented.'
        elif change in {'missing_advisories', 'system_marker'}:
            for key in (*ADVISORIES, 'upstream_projection_version'):
                payload.pop(key)
            if change == 'system_marker':
                system = system.replace(ADVISORY_REVIEW_SYSTEM_IDENTITY, '')
        else:
            payload['upstream_projection_version'] = 1
            payload.pop('comparison_assessment')
            payload.pop('reflection_constraints')
        span.full_input = system + '\nJSON:\n' + json.dumps(payload, ensure_ascii=False)
        for task in receipt['tasks']:
            if task.get('review_span_id') == span.id:
                task['review_input_sha256'] = hashlib.sha256(span.full_input.encode()).hexdigest()
    receipt_span.full_output = json.dumps(receipt)
    assert not reviewed_task_results(detail, audit)
    with pytest.raises(ValueError):
        replay(service, detail)


@pytest.mark.asyncio
async def test_historical_task_review_without_advisory_phase_keeps_replaying(monkeypatch):
    from packages.agents.writer.task_execution import (
        ADVISORY_REVIEW_SYSTEM_IDENTITY,
        TASK_PHASE_SYSTEM_IDENTITY,
    )
    from packages.agents.writer.task_projection import reviewed_task_results

    service, record, parts, texts = handoff_case()
    record_large_upstream(service, record)
    monkeypatch.setattr(service, '_trace_llm_text', offline_model(
        service, record, parts, texts, {}))
    await service._real_writer_step(record)
    detail = copy.deepcopy(record.detail)
    receipt_span = next(s for s in detail.trace_spans if s.name == 'question_task_delivery')
    receipt = json.loads(receipt_span.full_output)
    for dispatch in receipt['dispatches']:
        span = next(s for s in detail.trace_spans if s.id == dispatch['span_id'])
        span.full_input = span.full_input.replace(TASK_PHASE_SYSTEM_IDENTITY, '')
        dispatch['full_input_sha256'] = hashlib.sha256(span.full_input.encode()).hexdigest()
    for span in detail.trace_spans:
        if span.name != 'dimension_task_review':
            continue
        system, raw = span.full_input.split('\nJSON:\n', 1)
        payload = expand_prompt_payload(json.loads(raw))
        for key in (*ADVISORIES, 'upstream_projection_version', 'upstream_context_gaps',
                    'segment_competitor', 'dimension'):
            payload.pop(key)
        span.full_input = (system.replace(ADVISORY_REVIEW_SYSTEM_IDENTITY, '')
                           + '\nJSON:\n' + json.dumps(payload, ensure_ascii=False))
        for task in receipt['tasks']:
            if task.get('review_span_id') == span.id:
                task['review_input_sha256'] = hashlib.sha256(span.full_input.encode()).hexdigest()
    restore_historical_parent_context(detail, receipt)
    receipt_span.full_output = json.dumps(receipt)
    assert len(reviewed_task_results(detail, detail.report_dimension_audits[0])) == 2
    assert replay(service, detail)[1]['sent_fact_ids']


@pytest.mark.asyncio
async def test_historical_release_parent_unbound_receipt_keeps_exact_v1_replay(monkeypatch):
    from packages.agents.writer.task_projection import reviewed_task_results

    service, record, parts, texts = handoff_case()
    record.detail.plan.decision_brief = DecisionBrief(decision_question=PARENT + PRESENTATION)
    record_upstream(service, record)
    monkeypatch.setattr(service, '_trace_llm_text', offline_model(
        service, record, parts, texts, {}))
    await service._real_writer_step(record)
    detail = copy.deepcopy(record.detail)
    receipt_span = next(s for s in detail.trace_spans if s.name == 'question_task_delivery')
    receipt = json.loads(receipt_span.full_output)
    restore_historical_parent_context(detail, receipt)
    receipt_span.full_output = json.dumps(receipt)
    generation = next(s for s in detail.trace_spans if s.name == 'dimension_task_generation')
    context = json.loads(generation.full_input.split('\nJSON:\n', 1)[1])['request_context']
    child = research_questions(detail, 'Example Product', 'feature')[-1]
    assert context['unbound_question_ids'] == [child['question_id']]
    assert replay(service, detail)[1]['sent_fact_ids']
    assert len(reviewed_task_results(detail, detail.report_dimension_audits[0])) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('target,change', [
    ('generation', 'legacy'), ('generation', 'missing'),
    ('review', 'legacy'), ('review', 'missing'), ('review', 'system_marker')])
async def test_new_parent_protocol_rejects_legacy_json_or_removed_review_marker(
    monkeypatch, target, change
):
    from packages.agents.writer.task_execution import REQUEST_CONTEXT_SYSTEM_IDENTITY
    from packages.agents.writer.task_projection import reviewed_task_results
    from packages.research.question_scope import question_request_context

    service, record, parts, texts = handoff_case()
    record.detail.plan.decision_brief = DecisionBrief(decision_question=PARENT + PRESENTATION)
    record_upstream(service, record)
    monkeypatch.setattr(service, '_trace_llm_text', offline_model(
        service, record, parts, texts, {}))
    await service._real_writer_step(record)
    detail = copy.deepcopy(record.detail)
    receipt_span = next(s for s in detail.trace_spans if s.name == 'question_task_delivery')
    receipt = json.loads(receipt_span.full_output)
    for span in detail.trace_spans:
        if span.name != 'dimension_task_' + target:
            continue
        system, raw = span.full_input.split('\nJSON:\n', 1)
        payload = expand_prompt_payload(json.loads(raw))
        payload['request_context'] = question_request_context(
            detail, 'Example Product', 'feature', payload['questions'], version=1)
        if change == 'missing':
            payload['request_context'].pop('version')
        elif change == 'system_marker':
            system = system.replace(REQUEST_CONTEXT_SYSTEM_IDENTITY, '')
        span.full_input = system + '\nJSON:\n' + json.dumps(payload, ensure_ascii=False)
        digest = hashlib.sha256(span.full_input.encode()).hexdigest()
        for dispatch in receipt['dispatches']:
            if dispatch['span_id'] == span.id:
                dispatch['full_input_sha256'] = digest
        for task in receipt['tasks']:
            if task.get('review_span_id') == span.id:
                task['review_input_sha256'] = digest
    receipt_span.full_output = json.dumps(receipt)
    with pytest.raises(ValueError):
        replay(service, detail)
    if target == 'review':
        assert not reviewed_task_results(detail, detail.report_dimension_audits[0])


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['question_text', 'duplicate_question'])
async def test_new_review_requires_canonical_child_questions_before_rebuilding_parent(
    monkeypatch, change):
    from packages.agents.writer.task_projection import reviewed_task_results
    from packages.research.question_scope import question_request_context

    service, record, parts, texts = handoff_case()
    monkeypatch.setattr(
        service, '_trace_llm_text', offline_model(service, record, parts, texts, {}))
    await service._real_writer_step(record)
    detail = copy.deepcopy(record.detail)
    audit = detail.report_dimension_audits[0]
    assert len(reviewed_task_results(detail, audit)) == 2
    receipt_span = next(s for s in detail.trace_spans if s.name == 'question_task_delivery')
    receipt = json.loads(receipt_span.full_output)
    for span in detail.trace_spans:
        if span.name != 'dimension_task_review':
            continue
        system, raw = span.full_input.split('\nJSON:\n', 1)
        payload = json.loads(raw)
        if change == 'question_text':
            for question in payload['questions']:
                question['question'] = 'This is an unrelated request without the original scenario.'
        else:
            payload['questions'].append(dict(payload['questions'][0]))
        payload['request_context'] = question_request_context(
            detail, audit.competitor, audit.dimension, payload['questions'])
        span.full_input = system + '\nJSON:\n' + json.dumps(payload)
        for task in receipt['tasks']:
            if task.get('review_span_id') == span.id:
                task['review_input_sha256'] = hashlib.sha256(span.full_input.encode()).hexdigest()
    receipt_span.full_output = json.dumps(receipt)
    assert not reviewed_task_results(detail, audit)


@pytest.mark.asyncio
async def test_writer_rejects_noncanonical_child_text_before_generation_transport(monkeypatch):
    from packages.agents.writer import task_support_selection
    from packages.orchestrator.evidence_context import EvidenceUseRejectedError
    from packages.research.question_scope import question_request_context

    service, record, parts, texts = handoff_case()
    original = task_support_selection.selected_generation_context
    def changed(*args, **kwargs):
        payload = original(*args, **kwargs)
        for question in payload['questions']:
            question['question'] = 'This is an unrelated request without the original scenario.'
        payload['request_context'] = question_request_context(
            record.detail, 'Example Product', 'feature', payload['questions'])
        return payload
    seen = {}
    monkeypatch.setattr(task_support_selection, 'selected_generation_context', changed)
    monkeypatch.setattr(
        service, '_trace_llm_text', offline_model(service, record, parts, texts, seen))
    with pytest.raises(EvidenceUseRejectedError):
        await service._real_writer_step(record)
    assert 'dimension_task_generation' not in seen


def test_legacy_replay_does_not_treat_handoff_identity_in_request_data_as_server_system():
    from test_task_delivery_replay import delivery_case, save_receipt
    from test_task_projection import projected_case

    from packages.agents.writer.task_execution import HANDOFF_SYSTEM_IDENTITY
    from packages.agents.writer.task_projection import reviewed_task_results

    service, detail, _, _, _, receipt = delivery_case()
    for dispatch in receipt['dispatches']:
        span = next(s for s in detail.trace_spans if s.id == dispatch['span_id'])
        system, raw = span.full_input.split('\nJSON:\n', 1)
        payload = json.loads(raw)
        payload['untrusted_request_note'] = HANDOFF_SYSTEM_IDENTITY
        span.full_input = system + '\nJSON:\n' + json.dumps(payload)
        dispatch['full_input_sha256'] = hashlib.sha256(span.full_input.encode()).hexdigest()
    save_receipt(detail, receipt)
    assert replay(service, detail)[1]['sent_fact_ids']

    record, audit, receipt_span, receipt = projected_case()
    for task in receipt['tasks']:
        span = next(s for s in record.detail.trace_spans if s.id == task['review_span_id'])
        system, raw = span.full_input.split('\nJSON:\n', 1)
        payload = json.loads(raw)
        payload['untrusted_request_note'] = HANDOFF_SYSTEM_IDENTITY
        span.full_input = system + '\nJSON:\n' + json.dumps(payload)
        task['review_input_sha256'] = hashlib.sha256(span.full_input.encode()).hexdigest()
    receipt_span.full_output = json.dumps(receipt)
    assert reviewed_task_results(record.detail, audit)


@pytest.mark.asyncio
async def test_complete_parent_is_used_for_retrieval_without_changing_question_ids():
    from test_question_retrieval import research_case

    from packages.agents.writer.question_retrieval import retrieve_question_facts
    from packages.research.evidence.snapshot import seal_snapshot

    text = 'Example Product：付费 Workspace 中仅持 Observer 角色。能下载文件吗？他也可以吗？'
    detail, _ = research_case(
        ['Observers on paid Workspaces may download attachments.'], question=text)
    detail.plan.competitors = ['Example Product']
    detail.plan.decision_brief = DecisionBrief(decision_question=text)
    snapshot = seal_snapshot(detail, phase='analysis', canonical_documents={})
    questions = research_questions(detail, 'Example Product', 'feature')
    selected, diagnostic = await retrieve_question_facts(detail, snapshot, 'Example Product',
                                                        'feature', mode='lexical')
    child = next(row for row in diagnostic['questions']
                 if row['question_id'] == questions[-1]['question_id'])
    assert child['fact_ids'] and selected
    assert research_questions(detail, 'Example Product', 'feature') == questions


@pytest.mark.asyncio
async def test_shared_parent_does_not_replace_each_child_retrieval_intent_or_add_sibling_core():
    from test_question_retrieval import research_case

    from packages.agents.writer.question_retrieval import retrieve_question_facts
    from packages.research.evidence.snapshot import seal_snapshot

    text = ('Example Product：付费 Workspace 中仅持 Observer 角色。能下载附件吗？'
            '他能导出看板吗？他能投票吗？角色能否在 Workspace 层级统一设置？')
    quotes = ['Observers on paid Workspaces can download attachments.',
              'Observers on paid Workspaces can export boards.',
              'Observers on paid Workspaces can vote on cards when voting is enabled.',
              'Roles can only ever be assigned to their given scope.']
    detail, _ = research_case(quotes, question=text)
    detail.plan.competitors = ['Example Product']
    detail.plan.decision_brief = DecisionBrief(decision_question=text)
    snapshot = seal_snapshot(detail, phase='analysis', canonical_documents={})
    _, diagnostic = await retrieve_question_facts(detail, snapshot, 'Example Product',
                                                'feature', mode='lexical')
    facts = {f.id: f.quote for f in snapshot.facts}
    for row, expected in zip(diagnostic['questions'][:3], quotes[:3], strict=True):
        assert facts[row['fact_ids'][0]] == expected
        assert row['core_fact_ids'] == []


@pytest.mark.asyncio
@pytest.mark.parametrize('large', [False, True])
@pytest.mark.parametrize('capacity_pressure', [False, True])
async def test_offline_actual_adapter_transport_keeps_advisories_inside_original_limits(
    monkeypatch, large, capacity_pressure):
    import httpx
    from test_execution_limits import _service

    from packages.agents.writer.task_execution import GENERATE_SYSTEM, PLAN_SYSTEM
    from packages.agents.writer.task_support_selection import SELECT_SYSTEM

    _, fixture, parts, texts = handoff_case()
    service, _ = await _service(writer_task_execution_enabled=True, run_llm_max_calls=24,
                              run_llm_max_tokens=80000, llm_max_output_tokens=1600)
    record = fixture
    service._runs[record.detail.id] = record
    if capacity_pressure:
        add_capacity_pressure(record)
    (record_large_upstream if large else record_upstream)(service, record)
    for phase in list(service._run_llm_budget(record).delivery_reserves):
        if phase.startswith(('collector:', 'analyst:', 'comparator:', 'reflector:')):
            service._run_llm_budget(record).finish_delivery(phase)
    seen, requests = {}, []
    model = offline_model(service, record, parts, texts, seen, trace=False)
    async def post(url, body, headers):
        requests.append(body)
        system, user = [m['content'] for m in body['messages']]
        name = ('dimension_task_plan' if system.startswith(PLAN_SYSTEM)
                else 'dimension_task_support_selection' if system.startswith(SELECT_SYSTEM)
                else 'dimension_task_generation' if system.startswith(GENERATE_SYSTEM)
                else 'dimension_task_review' if 'task_assignment' in system
                else 'dimension_answer_review')
        response = await model(record, name=name, system=system, user=user)
        return httpx.Response(200, json={'choices': [{'message': {'content': response}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 50}})
    monkeypatch.setattr(service._llm, '_post_chat_completion', post)
    await service._real_writer_step(record)
    generation = [s for s in record.detail.trace_spans if s.name == 'dimension_task_generation']
    assert generation and requests
    for span in generation:
        assert span.metadata['llm_transport_attempts'] == 1
        raw = span.full_input.split('\nJSON:\n', 1)[1]
        assert len(('\nJSON:\n' + raw).encode()) <= 14000
        payload = expand_prompt_payload(json.loads(raw))
        assert all(payload.get(key) for key in ADVISORIES)
        assert payload['request_context']['parents'][0]['text'] == (
            record.detail.plan.decision_brief.decision_question)
    assert seen['dimension_task_support_selection']
    for payload in seen['dimension_task_support_selection']:
        assert not any(key in payload for key in ADVISORIES)
        assert payload['evidence_view']['facts']
    assert seen['dimension_task_review']
    for payload in seen['dimension_task_review']:
        assert all(payload.get(key) for key in ADVISORIES)
        assert payload['request_context']['parents'][0]['text'] == (
            record.detail.plan.decision_brief.decision_question)
    assert {edge.kind for edge
            in record.detail.report_dimension_audits[0].upstream_dependencies} == {
        'analyst', 'comparator', 'reflector'}


@pytest.mark.asyncio
async def test_synthesized_oversize_selected_payload_defers_without_generation_or_consumption(
    monkeypatch):
    from packages.agents.writer import task_support_selection
    from packages.agents.writer.dimension_writer import compact_prompt_json
    original_context = task_support_selection.selected_generation_context
    selected_bytes = []
    def measured_context(*args, **kwargs):
        payload = original_context(*args, **kwargs)
        # Synthetic final-envelope boundary; the original terms=150 input is
        # separately retained below as a naturally admitted positive case.
        payload['selected_context_diagnostic'] = 'Complete selected phase metadata. ' * 100
        selected_bytes.append(len(('\nJSON:\n' + compact_prompt_json(payload)).encode()))
        return payload
    monkeypatch.setattr(task_support_selection, 'selected_generation_context', measured_context)
    service, record, parts, texts = handoff_case()
    add_capacity_pressure(record, terms=150)
    record_large_upstream(service, record)
    seen = {}
    monkeypatch.setattr(service, '_trace_llm_text', offline_model(
        service, record, parts, texts, seen))
    await service._real_writer_step(record)
    assert seen.get('dimension_task_support_selection')
    assert selected_bytes and all(size > 14000 for size in selected_bytes)
    assert not seen.get('dimension_task_generation')
    assert record.detail.report_dimension_audits[0].upstream_dependencies == ()
    receipt = json.loads(next(s.full_output for s in record.detail.trace_spans
                             if s.name == 'question_task_delivery'))
    assert receipt['tasks']
    assert all(task['state'] == 'deferred' and task['reason'] == (
        'task_selected_support_context_budget_exceeded') for task in receipt['tasks'])
    assert not any(row['sent'] for row in receipt['advisory_delivery'].values())


@pytest.mark.asyncio
@pytest.mark.parametrize('case', [
    'outer_limit', 'omitted_originals', 'no_originals', 'no_legal_support'])
async def test_candidate_budget_is_distinct_from_missing_or_unusable_originals(monkeypatch, case):
    from packages.agents.writer import task_execution
    from packages.research.evidence.operations import operation_observations
    from packages.research.evidence.source_spans import source_span_candidates

    service, record, parts, texts = handoff_case()
    if case == 'outer_limit':
        add_capacity_pressure(record)
    elif case in {'omitted_originals', 'no_legal_support'}:
        add_capacity_pressure(record, terms=240)
    if case == 'no_legal_support':
        monkeypatch.setattr('packages.research.evidence.source_spans.source_span_candidates',
                            lambda fact: ())
        monkeypatch.setattr('packages.research.evidence.operations.operation_observations',
                            lambda fact, *args: ())
    record_large_upstream(service, record)
    original = task_execution.task_context
    allowed_originals = []
    built = []
    def capture(service, record, selected, view, allowed, *args, **kwargs):
        allowed = set() if case == 'no_originals' else allowed
        allowed_originals.extend(f for f in view.facts if f.id in allowed)
        payload = original(service, record, selected, view, allowed, *args, **kwargs)
        if case == 'outer_limit':
            # Exercise the final envelope gate while retaining complete legal originals.
            payload['candidate_diagnostic'] = 'Complete request metadata. ' * 600
        built.append(payload)
        return payload
    monkeypatch.setattr(task_execution, 'task_context', capture)
    seen = {}
    monkeypatch.setattr(service, '_trace_llm_text', offline_model(
        service, record, parts, texts, seen))
    await service._real_writer_step(record)
    assert not seen.get('dimension_task_support_selection')
    assert not seen.get('dimension_task_generation')
    assert record.detail.report_dimension_audits[0].upstream_dependencies == ()
    if case == 'no_originals':
        assert not allowed_originals
    elif case == 'no_legal_support':
        assert allowed_originals
        from packages.research.evidence import operations, source_spans
        assert not any(source_spans.source_span_candidates(f)
                       or operations.operation_observations(f)
                       for f in allowed_originals)
    else:
        assert any(source_span_candidates(f) or operation_observations(f)
                   for f in allowed_originals)
        assert built and all(payload['request_context']['parents'][0]['text'] == (
            record.detail.plan.decision_brief.decision_question) for payload in built)
        if case == 'outer_limit':
            assert built[0]['evidence_view']['facts']
            assert len(json.dumps(built[0], ensure_ascii=False).encode()) > 14000
        else:
            assert not built[0]['evidence_view']['facts']
    receipt = json.loads(next(s.full_output for s in record.detail.trace_spans
                             if s.name == 'question_task_delivery'))
    expected = (('deferred', 'candidate_context_budget_exceeded')
                if case in {'outer_limit', 'omitted_originals'} else
                ('insufficient_evidence', 'task_evidence_unavailable'))
    assert receipt['tasks']
    assert {(task['state'], task['reason']) for task in receipt['tasks']} == {expected}


@pytest.mark.asyncio
@pytest.mark.parametrize('large', [False, True])
@pytest.mark.parametrize('stale', ['analyst', 'comparator', 'reflector', 'snapshot',
                                 'wrong_product', 'wrong_dimension'])
async def test_task_generation_excludes_stale_or_wrong_scope_advisories(monkeypatch, stale, large):
    from packages.research.evidence.snapshot import seal_snapshot
    service, record, parts, texts = handoff_case()
    (record_large_upstream if large else record_upstream)(service, record)
    if stale == 'snapshot':
        record.detail.raw_sources[0].content_hash = 'new-accepted-offline-original'
        seal_snapshot(record.detail, phase='analysis', canonical_documents={})
    else:
        record.detail.evidence_artifact_dependencies = [
            dep.model_copy(update=({'competitor': 'Other'} if stale == 'wrong_product' else
                                   {'dimension': 'pricing'} if stale == 'wrong_dimension' else
                                   {'payload_hash': 'stale'}))
            if dep.kind == (stale if stale in {'analyst', 'comparator', 'reflector'} else 'analyst')
            else dep for dep in record.detail.evidence_artifact_dependencies]
    seen = {}
    monkeypatch.setattr(
        service, '_trace_llm_text', offline_model(service, record, parts, texts, seen))
    await service._real_writer_step(record)
    payload = seen['dimension_task_generation'][0]
    missing = ({'analyst', 'comparator', 'reflector'} if stale == 'snapshot' else
               {'analyst' if stale.startswith('wrong_') else stale})
    for kind, key in zip(('analyst', 'comparator', 'reflector'), ADVISORIES, strict=True):
        assert bool(payload.get(key)) == (kind not in missing)
    assert {d.kind for d in record.detail.report_dimension_audits[0].upstream_dependencies} == (
        {'analyst', 'comparator', 'reflector'} - missing)


@pytest.mark.asyncio
@pytest.mark.parametrize('target', ['request_context', 'upstream_analysis'])
async def test_writer_rejects_changed_new_context_before_generation_transport(monkeypatch, target):
    from packages.agents.writer import task_support_selection
    from packages.orchestrator.evidence_context import EvidenceUseRejectedError
    service, record, parts, texts = handoff_case()
    record_upstream(service, record)
    original = task_support_selection.selected_generation_context
    def changed(*args, **kwargs):
        payload = original(*args, **kwargs)
        if target == 'request_context':
            payload[target]['parents'][0]['text'] = 'Different original request.'
        else:
            payload[target]['content'] = {'claims': [{'claim': 'Invented conclusion.'}]}
        return payload
    seen = {}
    monkeypatch.setattr(task_support_selection, 'selected_generation_context', changed)
    monkeypatch.setattr(
        service, '_trace_llm_text', offline_model(service, record, parts, texts, seen))
    with pytest.raises(EvidenceUseRejectedError):
        await service._real_writer_step(record)
    assert 'dimension_task_generation' not in seen


@pytest.mark.asyncio
async def test_long_complete_parent_is_bounded_without_slicing_conditions_or_claiming_advisory_use(
    monkeypatch):
    from types import SimpleNamespace

    from packages.agents.writer import task_execution
    service, record, parts, texts = handoff_case()
    record.detail.plan.decision_brief = DecisionBrief(decision_question=(
        PARENT + (' 共享前提必须完整保留。' * 30)))
    record_upstream(service, record)
    original = task_execution.task_context
    built = []
    def bounded(service, record, selected, view, allowed, questions, packets, tasks, use, **kwargs):
        context = original(service, record, selected, view, allowed, questions, packets,
                           tasks, SimpleNamespace(max_bytes=1800), **kwargs)
        built.append(context)
        return context
    monkeypatch.setattr(task_execution, 'task_context', bounded)
    seen = {}
    monkeypatch.setattr(
        service, '_trace_llm_text', offline_model(service, record, parts, texts, seen))
    await service._real_writer_step(record)
    assert 'dimension_task_generation' not in seen
    assert all(context['request_context']['parents'][0]['text'] ==
               record.detail.plan.decision_brief.decision_question for context in built)
    assert record.detail.report_dimension_audits[0].upstream_dependencies == ()
    receipt = json.loads(next(s.full_output for s in record.detail.trace_spans
                             if s.name == 'question_task_delivery'))
    assert not any(row['sent'] for row in receipt['advisory_delivery'].values())


@pytest.mark.asyncio
async def test_original_selected_context_pressure_is_admitted_when_actual_user_fits(monkeypatch):
    service, record, parts, texts = handoff_case()
    add_capacity_pressure(record, terms=150)
    record_large_upstream(service, record)
    seen = {}
    monkeypatch.setattr(service, '_trace_llm_text', offline_model(
        service, record, parts, texts, seen))
    await service._real_writer_step(record)
    spans = [s for s in record.detail.trace_spans if s.name == 'dimension_task_generation']
    assert spans
    assert all(len(('\nJSON:\n' + s.full_input.split('\nJSON:\n', 1)[1]).encode()) <= 14000
        for s in spans)
