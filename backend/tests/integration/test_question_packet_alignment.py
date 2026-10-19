"""Anonymous transport replay: prepared selections are not delivery evidence."""
from __future__ import annotations

import json
import time
from datetime import UTC, datetime

import pytest
from pydantic import HttpUrl, TypeAdapter
from test_agent_evidence_alignment import InputReplay
from test_question_retrieval import research_case

from packages.orchestrator.service import RunRecord
from packages.research.evidence.snapshot import current_snapshot, seal_snapshot
from packages.research.question_delivery import _expand_text_refs
from packages.research.question_scope import research_questions
from packages.schema.models import DecisionBrief


CASES = [
    (
        "Example Product：Free 能保存密码吗？\nExample Product：Families 的密码属于谁？",
        ["Free plan users can store passwords.",
         "Families plan members retain ownership of personally-owned passwords."],
    ),
    (
        "Example Product：CacheDomainPurge 角色可以访问另一个域名的缓存吗？\nExample Product：缓存清除请求的计费费率有哪些条件？",
        ["CacheDomainPurge role can purge cache only in the domain assigned by the account owner.",
         "Cache purge requests cost 0.02 USD per request; billing excludes tax."],
    ),
]


def question_detail(case=0):
    question, quotes = CASES[case]
    detail, _ = research_case([*[f'Editors can edit document style {i}. ' + 'General editing background. ' * 12
                                 for i in range(22)], *quotes], question=question)
    detail.created_at = detail.updated_at = datetime.now(UTC)
    detail.plan.competitors = ["Example Product"]
    detail.plan.dimensions = ["feature"]
    detail.plan.decision_brief = DecisionBrief(decision_question=question)
    for source in detail.raw_sources:
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
    seal_snapshot(detail, phase="analysis", canonical_documents={})
    return detail


class QuestionReplay(InputReplay):
    def __init__(self, tmp_path, case=0):
        super().__init__(tmp_path)
        self.record = RunRecord(question_detail(case))
        self._runs[self.record.detail.id] = self.record

    async def _trace_llm_json(self, record, **kwargs):
        self.inputs.append(kwargs)
        if kwargs['agent'] == 'analyst':
            return {'feature_tree': {'summary_claims': []}}
        if kwargs['agent'] == 'comparator':
            return {'matrix_summary': ['Question-scoped evidence captured'], 'winner_by_dimension': {}}
        return {'coverage_gaps': [], 'gate_status': 'pass'}

    async def _trace_llm_text(self, record, **kwargs):
        self.inputs.append(kwargs)
        if kwargs['name'] == 'dimension_claim_writer':
            return '{"claims":[]}'
        if kwargs['name'] == 'dimension_claim_review':
            return '{"reviews":[]}'
        return '{"version":2,"answers":[]}'


def input_payload(call):
    user = call['user']
    if call['agent'] == 'writer':
        payload = _expand_text_refs(json.loads(user.split('\nJSON:\n', 1)[1]))
        return payload['question_evidence_packets'], payload['evidence_view']['facts']
    assert 'Question evidence packets JSON: ' in user, f"{call['agent']} did not receive question selection identities"
    packets = json.JSONDecoder().raw_decode(user.split('Question evidence packets JSON: ', 1)[1])[0]
    view = json.JSONDecoder().raw_decode(user.split('Evidence View JSON: ', 1)[1])[0]
    def expand(value):
        if isinstance(value, dict):
            if set(value) == {'quote_ref'}:
                return view['quoted_evidence'][value['quote_ref']]
            return {key: expand(item) for key, item in value.items()}
        return [expand(item) for item in value] if isinstance(value, list) else value
    facts = []
    for row in view['facts']:
        row = expand(row)
        if 'quote_ref' in row:
            row['quote'] = view['quoted_evidence'][row.pop('quote_ref')]
        if 'qualifiers_ref' in row:
            row['qualifiers'] = view['qualifier_sets'][row.pop('qualifiers_ref')]
        facts.append(row)
    return packets, facts


@pytest.mark.asyncio
@pytest.mark.parametrize('case', [0, 1])
async def test_four_actual_agent_inputs_share_question_originals(tmp_path, case):
    service = QuestionReplay(tmp_path, case)
    record = service.record
    await service._real_analyst_branch_step(record, 'feature', 'Example Product')
    await service._real_comparator_step(record)
    await service._real_reflector_step(record)
    await service._real_writer_step(record)
    calls = [call for call in service.inputs if call['agent'] in {'analyst', 'comparator', 'reflector'}
             or call['name'] == 'dimension_claim_writer']
    assert {call['agent'] for call in calls} == {'analyst', 'comparator', 'reflector', 'writer'}
    ids = []
    snapshot = current_snapshot(record.detail)
    expected = {fact.id: fact for fact in snapshot.facts
                if fact.field == 'evidence_terms' and fact.quote in CASES[case][1]}
    questions = research_questions(record.detail, 'Example Product', 'feature')
    for call in calls:
        # Assert the observed failure before testing the new identity contract.
        for quote in CASES[case][1]:
            assert quote in call['user'], f"{call['agent']} omitted the question original: {quote}"
        packets, facts = input_payload(call)
        assert len(packets) == 1
        packet = packets[0]
        ids.append(packet['packet_id'])
        assert packet['snapshot_id'] == snapshot.id
        assert [row['question_id'] for row in packet['questions']] == [q['question_id'] for q in questions]
        actual = {row['id']: row for row in facts}
        assert set(expected) <= set(actual)
        for fid, fact in expected.items():
            assert actual[fid]['quote'] == fact.quote
            assert actual[fid]['value'] == fact.value
            assert actual[fid]['qualifiers'] == {k: v for k, v in fact.qualifiers.items() if k != 'operations'}
        assert all(set(row['fact_ids']) <= set(actual) for row in packet['questions'])
    assert len(set(ids)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['workspace', 'project', 'snapshot', 'query', 'selection_trace'])
async def test_question_credential_replays_current_identity(tmp_path, change):
    from packages.orchestrator.evidence_context import EvidenceUseRejectedError
    service = QuestionReplay(tmp_path)
    record = service.record
    _, use, _ = await service._begin_question_evidence_use(
        record, agent='analyst', competitor='Example Product', dimension='feature')
    if change == 'workspace':
        record.detail.workspace_id = 'other-workspace'
    elif change == 'project':
        record.detail.project_id = 'other-project'
    elif change == 'snapshot':
        record.detail.evidence_inputs_dirty = True
    elif change == 'query':
        record.detail.plan.decision_brief.decision_question += '\nExample Product：还有其他条件吗？'
    else:
        record.detail.trace_spans = [span for span in record.detail.trace_spans
                                     if span.name != 'question_evidence_selection']
    with pytest.raises(EvidenceUseRejectedError):
        service._validate_evidence_use(record, use)


@pytest.mark.asyncio
async def test_lexical_degradation_preserves_zero_recall_as_unverified(tmp_path, monkeypatch):
    from packages.agents.writer import question_retrieval
    from packages.orchestrator.question_packets import prompt_packets
    service = QuestionReplay(tmp_path, 1)
    detail = service.record.detail
    detail.plan.decision_brief.decision_question = 'Example Product：访客可以访问另一个域名的缓存吗？'
    source = detail.raw_sources[-2]
    source.metadata['normalized_fields'][0]['evidence_terms'] = ['Visitors may only purge their assigned domain.']
    source.metadata['normalized_fields'][0]['evidence_quote'] = 'Visitors may only purge their assigned domain.'
    detail.raw_sources = [source]
    seal_snapshot(detail, phase='analysis', canonical_documents={})
    monkeypatch.setattr(question_retrieval, 'get_local_provider_from_env', lambda kind: None)
    view, use, packets = await service._begin_question_evidence_use(
        service.record, agent='analyst', competitor='Example Product', dimension='feature')
    row = prompt_packets(packets, current_snapshot(detail), view.facts)[0]['questions'][0]
    assert not use.fact_ids and row['minimum_evidence_missing']
    assert row['evidence_gap'] == 'no_relevant_original'
    assert packets[0]['retrieval']['mode'] == 'degraded_lexical'
    assert any(fact.quote.startswith('Visitors') for fact in current_snapshot(detail).facts)
    await service._trace_question_llm_json(service.record, evidence_view=view, evidence_use=use,
        question_packets=packets, agent='analyst', subagent='feature/Example Product', name='zero_recall',
        system='Review evidence.', user='Evidence View JSON: ' + view.to_prompt_json(), schema_hint='{}')
    receipt = next(json.loads(span.full_output) for span in detail.trace_spans
                   if span.name == 'question_evidence_dispatch')
    assert receipt['actual'][0]['questions'][0]['evidence_gap'] == 'dispatch_unverified'
    assert receipt['actual'][0]['gaps'] == ['question_dispatch_unverified', 'question_no_relevant_original']
    assert receipt['prepared'][0]['gaps'] == ['question_no_relevant_original']


@pytest.mark.asyncio
async def test_explicit_selection_does_not_authorize_incomplete_producer(tmp_path):
    service = QuestionReplay(tmp_path)
    record = service.record
    await service._real_analyst_branch_step(record, 'feature', 'Example Product')
    snapshot = current_snapshot(record.detail)
    target = next(fact for fact in snapshot.facts if fact.quote == CASES[0][1][0])
    view, _ = service._begin_evidence_use(record, agent='comparator', fact_ids=[target.id])
    assert target.id in view.fact_ids
    _, gaps = service._project_evidence_detail(record, [view])
    assert any(gap.startswith('Analysis context omitted:') for gap in gaps)
    producer = record.detail.evidence_artifact_dependencies[0]
    record.detail.evidence_artifact_dependencies[0] = producer.model_copy(update={'payload_hash': 'tampered'})
    _, gaps = service._project_evidence_detail(record, [view])
    assert any(gap.startswith('Analysis dependency unavailable:') for gap in gaps)


@pytest.mark.asyncio
async def test_no_questions_retains_legacy_view_and_budget(tmp_path):
    service = QuestionReplay(tmp_path)
    record = service.record
    record.detail.topic = record.detail.plan.topic = 'Product research'
    record.detail.plan.decision_brief = None
    expected, old_use = service._begin_evidence_use(record, agent='analyst', competitor='Example Product', dimension='feature')
    actual, use, packets = await service._begin_question_evidence_use(record, agent='analyst', competitor='Example Product', dimension='feature')
    assert not packets and actual == expected
    assert use.max_bytes == old_use.max_bytes and use.view_max_bytes == old_use.view_max_bytes


@pytest.mark.asyncio
async def test_actual_budget_omissions_are_question_context_gaps(tmp_path, monkeypatch):
    from packages.orchestrator import evidence_context
    monkeypatch.setitem(evidence_context._DEPTH_BYTES, 'quick', 1600)
    service = QuestionReplay(tmp_path)
    view, use, packets = await service._begin_question_evidence_use(
        service.record, agent='analyst', competitor='Example Product', dimension='feature')
    rows = service._question_packet_prompt(service.record, packets, view.facts)[0]['questions']
    assert use.max_bytes == 3200
    assert use.view_max_bytes < use.max_bytes
    assert not view.fact_ids
    assert all(row['minimum_evidence_missing'] and row['evidence_gap'] == 'context_budget_exceeded' for row in rows)
    assert packets[0]['selected_fact_ids']
    assert all(fact.quote in CASES[0][1] for fact in view.facts)


@pytest.mark.asyncio
@pytest.mark.parametrize('reason', ['stale_evidence', 'source_inactive'])
async def test_unavailable_original_never_enters_packet_sent_facts(tmp_path, reason):
    from datetime import timedelta
    from test_question_retrieval import replace_snapshot
    service = QuestionReplay(tmp_path)
    detail = service.record.detail
    snapshot = current_snapshot(detail)
    changed = [source.model_copy(update=(
        {'last_verified_at': datetime.now(UTC) - timedelta(days=90)} if reason == 'stale_evidence'
        else {'status': 'withdrawn'})) for source in snapshot.sources]
    replace_snapshot(detail, snapshot, sources=tuple(changed))
    view, use, packets = await service._begin_question_evidence_use(
        service.record, agent='analyst', competitor='Example Product', dimension='feature')
    assert not view.fact_ids and not packets[0]['selected_fact_ids']
    assert all(row['minimum_evidence_missing'] for row in
               service._question_packet_prompt(service.record, packets, view.facts)[0]['questions'])
    await service._trace_question_llm_json(service.record, evidence_view=view, evidence_use=use,
        question_packets=packets, agent='analyst', subagent='feature/Example Product', name='no_eligible',
        system='Review evidence.', user='Evidence View JSON: ' + view.to_prompt_json(), schema_hint='{}')
    receipt = next(json.loads(span.full_output) for span in detail.trace_spans
                   if span.name == 'question_evidence_dispatch')
    assert receipt['actual'][0]['gaps'] == ['question_dispatch_unverified', 'question_no_eligible_original']
    assert receipt['prepared'][0]['gaps'] == ['question_no_eligible_original']


@pytest.mark.asyncio
async def test_dispatch_receipt_requires_real_matching_span_and_transport(tmp_path, monkeypatch):
    import time
    service = QuestionReplay(tmp_path)
    original = service._trace_llm_json

    async def traced(record, **kwargs):
        result = await original(record, **kwargs)
        full_input = kwargs['system'] + '\n\n' + kwargs['user'] + '\n\nSchema: ' + kwargs['schema_hint']
        service._append_trace_span(record, kind='llm', agent=kwargs['agent'], subagent=kwargs['subagent'],
            name=kwargs['name'], status='ok', started=time.perf_counter(), input_text=full_input,
            output_text=json.dumps(result), metadata={'llm_transport_attempts': 1})
        return result

    monkeypatch.setattr(service, '_trace_llm_json', traced)
    await service._real_analyst_branch_step(service.record, 'feature', 'Example Product')
    receipts = [json.loads(span.full_output) for span in service.record.detail.trace_spans
                if span.name == 'question_evidence_dispatch']
    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt['status'] == 'dispatch_succeeded' and receipt['transport_attempts'] == 1
    span = next(span for span in service.record.detail.trace_spans if span.id == receipt['span_id'])
    import hashlib
    assert receipt['full_input_sha256'] == hashlib.sha256(span.full_input.encode()).hexdigest()
    expected = {fact.id for fact in current_snapshot(service.record.detail).facts
                if fact.quote in CASES[0][1] and fact.field == 'evidence_terms'}
    assert expected <= set(receipt['actual'][0]['sent_fact_ids'])
    assert not receipt['actual'][0]['gaps']


@pytest.mark.asyncio
async def test_scopes_share_logical_packets_without_cross_product_credentials(tmp_path):
    service = QuestionReplay(tmp_path)
    detail = service.record.detail
    detail.plan.competitors.append('Other Suite')
    detail.plan.decision_brief.decision_question += '\nOther Suite：Free 能保存密码吗？'
    source = detail.raw_sources[-2].model_copy(deep=True)
    source.id = 'other-source'
    source.competitor = 'Other Suite'
    source.covered_competitors = ['Other Suite']
    for field in source.metadata['normalized_fields']:
        field['competitor'] = 'Other Suite'
    detail.raw_sources.append(source)
    seal_snapshot(detail, phase='analysis', canonical_documents={})
    selected = []
    for product in detail.plan.competitors:
        _, _, packets = await service._begin_question_evidence_use(
            service.record, agent='analyst', competitor=product, dimension='feature')
        selected.extend(packets)
    _, _, combined = await service._begin_question_evidence_use(service.record, agent='reflector')
    assert [packet['packet_id'] for packet in selected] == [packet['packet_id'] for packet in combined]
    from packages.orchestrator.question_packets import selected_packet_ids
    ranked = selected_packet_ids(combined)
    assert ranked[:2] == tuple(packet['selected_fact_ids'][0] for packet in combined)
    facts = {fact.id: fact for fact in current_snapshot(detail).facts}
    for packet in combined:
        assert all(facts[fid].competitor == packet['competitor'] for fid in packet['selected_fact_ids'])
    from packages.agents.reflector.logic import _question_delivery_scope
    assert _question_delivery_scope(detail)['requires_comparison']


@pytest.mark.asyncio
async def test_same_source_condition_branches_remain_distinct_complete_originals(tmp_path):
    service = QuestionReplay(tmp_path)
    detail = service.record.detail
    source = detail.raw_sources[-2]
    other = detail.raw_sources[-1]
    quote = "Families plan members retain ownership only when items are personally-owned."
    other.metadata['normalized_fields'][0]['evidence_quote'] = quote
    other.metadata['normalized_fields'][0]['evidence_terms'] = [quote]
    other.metadata['normalized_fields'][0]['qualifiers'] = {'account_type': 'member', 'condition': 'personally-owned'}
    source.metadata['normalized_fields'] += other.metadata['normalized_fields']
    detail.raw_sources = [source]
    seal_snapshot(detail, phase='analysis', canonical_documents={})
    view, _, packets = await service._begin_question_evidence_use(
        service.record, agent='analyst', competitor='Example Product', dimension='feature')
    originals = [fact for fact in view.facts if fact.field == 'evidence_terms']
    assert {fact.quote for fact in originals} == {CASES[0][1][0], quote}
    assert len({fact.source_id for fact in originals}) == 1
    bound = next(fact for fact in originals if fact.quote == quote)
    assert bound.qualifiers['account_type'] == 'member' and bound.qualifiers['condition'] == 'personally-owned'
    assert bound.id in packets[0]['selected_fact_ids']


@pytest.mark.asyncio
async def test_actual_dispatch_without_verified_transport_stays_unverified(tmp_path):
    service = QuestionReplay(tmp_path)
    await service._real_analyst_branch_step(service.record, 'feature', 'Example Product')
    receipts = [json.loads(span.full_output) for span in service.record.detail.trace_spans
                if span.name == 'question_evidence_dispatch']
    assert receipts and all(row['status'] == 'unverified' and row['span_id'] is None for row in receipts)


@pytest.mark.asyncio
async def test_oversized_question_metadata_records_omission_without_expanding_budget(tmp_path):
    from packages.llm.errors import LLMExecutionLimitError
    service = QuestionReplay(tmp_path)
    service.record.detail.plan.decision_brief.decision_question = 'Example Product：Free ' + 'very ' * 6000 + '?'
    view, use, packets = await service._begin_question_evidence_use(
        service.record, agent='analyst', competitor='Example Product', dimension='feature')
    assert use.max_bytes == 16384
    with pytest.raises(LLMExecutionLimitError, match='question_context_budget_exceeded'):
        await service._trace_question_llm_json(service.record, evidence_view=view, evidence_use=use,
            question_packets=packets, agent='analyst', subagent='feature/Example Product', name='oversized',
            system='Review evidence.', user='Evidence View JSON: ' + view.to_prompt_json(), schema_hint='{}')
    assert not service.inputs
    receipt = next(json.loads(span.full_output) for span in service.record.detail.trace_spans
                   if span.name == 'question_evidence_dispatch')
    assert receipt['status'] == 'unverified'
    assert receipt['actual'][0]['sent_fact_ids'] == []
    assert receipt['dispatch_cause'] == 'context_budget_exceeded'
    assert all(row['evidence_gap'] == 'context_budget_exceeded' for row in receipt['actual'][0]['questions'])
    assert 'question_context_budget_exceeded' in receipt['actual'][0]['gaps']


@pytest.mark.asyncio
async def test_question_scope_keeps_legacy_producer_facts_for_unqueried_dimensions(tmp_path):
    service = InputReplay(tmp_path)
    detail = service.record.detail
    detail.plan.decision_brief = DecisionBrief(decision_question='Phone X：Free 能保存密码吗？')
    await service._real_analyst_branch_step(service.record, 'pricing', 'Phone X')
    producer = next(use for use in detail.evidence_consumptions
                    if use.agent == 'analyst' and use.dimension == 'pricing')
    view, _, packets = await service._begin_question_evidence_use(service.record, agent='comparator')
    assert packets and all(packet['dimension'] == 'feature' for packet in packets)
    assert set(producer.fact_ids) <= set(view.fact_ids)
    _, gaps = service._project_evidence_detail(service.record, [view])
    assert not any(gap.startswith('Analysis context omitted: Phone X / pricing') for gap in gaps)


@pytest.mark.asyncio
async def test_required_core_omission_reaches_reflector_result(tmp_path, monkeypatch):
    from packages.agents.writer import question_retrieval
    monkeypatch.setattr(question_retrieval, 'get_local_provider_from_env', lambda *_: None)
    conclusion = ('Deleting an account will delete all associated vault data. '
                  'Members cannot retain their personal vault items after account deletion.')
    rule = ("Organizations own all collections. Personally-owned items remain in a member's personal vault. "
            'Administrators centralize organization ownership when selected items are transferred from a member. '
            + conclusion + ' ')
    quote = rule + '\n\n' + 'Background policy details. ' * 80
    extra = ' Account deletion is delayed for 30 days when a legal hold is active.'
    question = 'Example Product：把自己的账户永久删掉后，之前保存的密码还会留下吗？'
    detail, _ = research_case([quote, quote, quote + extra], question=question)
    detail.created_at = detail.updated_at = datetime.now(UTC)
    detail.plan.competitors = ['Example Product']
    detail.plan.dimensions = ['feature']
    detail.plan.decision_brief = DecisionBrief(decision_question=question)
    for index, source in enumerate(detail.raw_sources):
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
        source.metadata['normalized_fields'][0]['slot'] = f'distinct-original-{index}'
    seal_snapshot(detail, phase='analysis', canonical_documents={})
    service = QuestionReplay(tmp_path)
    service.record = RunRecord(detail)
    service._runs[detail.id] = service.record
    await service._real_analyst_branch_step(service.record, 'feature', 'Example Product')
    await service._real_comparator_step(service.record)
    await service._real_reflector_step(service.record)
    selection = next(json.loads(span.full_output) for span in detail.trace_spans
                     if span.name == 'question_evidence_selection' and span.agent == 'reflector')
    row = selection['view'][0]['questions'][0]
    reflection = detail.reflections[-1]
    print('PARTIAL_CORE_ROW', json.dumps(row, ensure_ascii=False))
    print('REFLECTION', reflection.model_dump_json())
    assert row['missing_core_fact_ids'], 'Fixture must expose a genuinely omitted required original.'
    assert not row['minimum_evidence_missing'], 'This reproduces partial, rather than total, omission.'
    assert row['evidence_gap'] == 'context_budget_exceeded'
    assert 'question_core_context_budget_exceeded' in row['evidence_gaps']
    assert reflection.gate_status in {'warn', 'block'}
    assert any(row['question_id'] in constraint for constraint in reflection.writer_constraints)
    assert any('context' in gap.casefold() for gap in reflection.coverage_gaps)
    dispatch = next(json.loads(span.full_output) for span in detail.trace_spans
                    if span.name == 'question_evidence_dispatch' and span.agent == 'reflector')
    assert dispatch['actual'][0]['questions'][0]['evidence_gap'] == 'dispatch_unverified'
    assert 'question_core_context_budget_exceeded' in dispatch['actual'][0]['gaps']
    assert 'question_dispatch_unverified' in dispatch['actual'][0]['gaps']
    assert dispatch['prepared'][0]['questions'][0]['missing_core_fact_ids'] == row['missing_core_fact_ids']


@pytest.mark.asyncio
async def test_no_eligible_original_is_not_complete_dispatch(tmp_path, monkeypatch):
    from packages.agents.writer import question_retrieval
    from test_question_retrieval import replace_snapshot
    monkeypatch.setattr(question_retrieval, 'get_local_provider_from_env', lambda *_: None)
    service = QuestionReplay(tmp_path)
    detail = service.record.detail
    snapshot = current_snapshot(detail)
    replace_snapshot(detail, snapshot, sources=tuple(source.model_copy(update={'status': 'withdrawn'})
                                                    for source in snapshot.sources))
    original = service._trace_llm_json

    async def traced(record, **kwargs):
        result = await original(record, **kwargs)
        full_input = kwargs['system'] + '\n\n' + kwargs['user']
        if kwargs.get('schema_hint') is not None:
            full_input += '\n\nSchema: ' + kwargs['schema_hint']
        service._append_trace_span(record, kind='llm', agent=kwargs['agent'],
                                  subagent=kwargs.get('subagent'), name=kwargs['name'], status='ok',
                                  started=time.perf_counter(), input_text=full_input,
                                  output_text=json.dumps(result), metadata={'llm_transport_attempts': 1})
        return result

    monkeypatch.setattr(service, '_trace_llm_json', traced)
    await service._real_comparator_step(service.record)
    selection = next(json.loads(span.full_output) for span in detail.trace_spans
                     if span.name == 'question_evidence_selection')
    receipt = next(json.loads(span.full_output) for span in detail.trace_spans
                   if span.name == 'question_evidence_dispatch')
    print('RETRIEVAL', json.dumps(selection['packets'][0]['retrieval'], ensure_ascii=False))
    print('RECEIPT', json.dumps(receipt, ensure_ascii=False))
    assert selection['packets'][0]['retrieval']['mode'] == 'no_candidates'
    assert receipt['status'] == 'dispatch_succeeded'
    assert receipt['actual'][0]['sent_fact_ids'] == []
    assert all(row['minimum_evidence_missing'] for row in receipt['question_views'][0]['questions'])
    assert receipt['content_status'] != 'complete'
    assert len(receipt['actual'][0]['questions']) == len(receipt['question_views'][0]['questions'])
    assert all(row['evidence_gap'] == 'no_eligible_original'
               for row in receipt['question_views'][0]['questions'])
    assert all(row['evidence_gap'] == 'no_eligible_original'
               for row in receipt['actual'][0]['questions'])
    assert receipt['actual'][0]['gaps'] == ['question_no_eligible_original']
    assert any(gap['reason'] == 'source_inactive' for gap in receipt['view_gaps'])


@pytest.mark.asyncio
@pytest.mark.parametrize('restore', ['live', 'json', 'journal'])
async def test_question_identity_survives_default_trace_redaction(tmp_path, restore):
    service = QuestionReplay(tmp_path)
    record = service.record
    record.detail.plan.decision_brief.decision_question = 'Example Product：Free 能保存 alice@example.com 的密码吗？'
    _, use, _ = await service._begin_question_evidence_use(
        record, agent='analyst', competitor='Example Product', dimension='feature')
    trace = next(span for span in record.detail.trace_spans if span.name == 'question_evidence_selection')
    assert service._settings.compliance_redaction_enabled and trace.metadata.get('pii_redacted')
    assert 'alice@example.com' not in trace.full_output
    assert 'alice@example.com' not in json.dumps(trace.metadata)
    assert 'alice@example.com' not in json.dumps(json.loads(trace.full_output)['receipt'])
    if restore == 'journal':
        service._journal.save_run(record.detail)
        record.detail = service._journal.load_run(record.detail.id)
        assert any(item.id == use.id for item in record.detail.evidence_consumptions)
    elif restore == 'json':
        record.detail = type(record.detail).model_validate_json(record.detail.model_dump_json())
    if restore != 'live':
        use = next(item for item in record.detail.evidence_consumptions if item.id == use.id)
    service._validate_evidence_use(record, use)
    record.detail.plan.decision_brief.decision_question = 'Example Product：Free 能保存 bob@example.com 的密码吗？'
    from packages.orchestrator.evidence_context import EvidenceUseRejectedError
    with pytest.raises(EvidenceUseRejectedError):
        service._validate_evidence_use(record, use)


@pytest.mark.asyncio
async def test_missing_product_original_remains_partial_in_real_reflector_dispatch(tmp_path, monkeypatch):
    service = QuestionReplay(tmp_path)
    detail = service.record.detail
    source = detail.raw_sources[-2]
    quote = 'Free plan users can store passwords. ' + 'General policy text. ' * 100
    source.metadata['normalized_fields'][0]['evidence_quote'] = quote
    source.metadata['normalized_fields'][0]['evidence_terms'] = [quote]
    detail.raw_sources = [source]
    detail.plan.competitors.append('Other Suite')
    detail.plan.decision_brief.decision_question = 'Example Product：Free 能保存密码吗？\nOther Suite：Free 能保存密码吗？'
    other = source.model_copy(deep=True)
    other.id = 'other-source'
    other.competitor = 'Other Suite'
    other.covered_competitors = ['Other Suite']
    for row in other.metadata['normalized_fields']:
        row['competitor'] = 'Other Suite'
    detail.raw_sources.append(other)
    snapshot = seal_snapshot(detail, phase='analysis', canonical_documents={})
    original = service._trace_llm_json
    async def traced(record, **kwargs):
        result = await original(record, **kwargs)
        full_input = kwargs['system'] + '\n\n' + kwargs['user']
        if kwargs.get('schema_hint') is not None:
            full_input += '\n\nSchema: ' + kwargs['schema_hint']
        service._append_trace_span(record, kind='llm', agent=kwargs['agent'], subagent=kwargs.get('subagent'),
            name=kwargs['name'], status='ok', started=time.perf_counter(), input_text=full_input,
            output_text=json.dumps(result), metadata={'llm_transport_attempts': 1})
        return result
    monkeypatch.setattr(service, '_trace_llm_json', traced)
    await service._real_reflector_step(service.record)
    selection = next(json.loads(span.full_output) for span in detail.trace_spans if span.name == 'question_evidence_selection')
    receipt = next(json.loads(span.full_output) for span in detail.trace_spans if span.name == 'question_evidence_dispatch')
    sent = set(receipt['actual'][0]['sent_fact_ids'])
    print('ACTUAL_PRODUCTS', sorted({fact.competitor for fact in snapshot.facts if fact.id in sent}))
    print('SELECTION_VIEW', json.dumps(selection['view'], ensure_ascii=False))
    print('DISPATCH_RECEIPT', json.dumps(receipt, ensure_ascii=False))
    print('REFLECTION_GAPS', json.dumps(detail.reflections[-1].coverage_gaps, ensure_ascii=False))
    assert receipt['status'] == 'dispatch_succeeded'
    assert receipt['content_status'] == 'partial'
    missing = selection['view'][1]['questions'][0]
    assert not missing['fact_ids'] and missing['minimum_evidence_missing']
    assert missing['evidence_gap'] == 'context_budget_exceeded'
    assert receipt['actual'][1]['sent_fact_ids'] == []
    assert receipt['actual'][1]['questions'][0]['minimum_evidence_missing']
    assert any(missing['question_id'] in gap and 'context omitted' in gap
               for gap in detail.reflections[-1].coverage_gaps)


@pytest.mark.asyncio
async def test_same_scope_identical_originals_keep_legal_equivalence(tmp_path):
    service = QuestionReplay(tmp_path)
    detail = service.record.detail
    source = detail.raw_sources[-2]
    quote = ('Organizations own all collections. Personally-owned items remain in a personal vault. '
             'Deleting an account will delete all associated vault data.')
    source.metadata['normalized_fields'][0]['evidence_quote'] = quote
    source.metadata['normalized_fields'][0]['evidence_terms'] = [quote]
    other = source.model_copy(deep=True)
    other.id = 'equivalent-source'
    detail.raw_sources = [source, other]
    detail.plan.decision_brief.decision_question = 'Example Product：永久删除账户后，保存的密码还会留下吗？'
    seal_snapshot(detail, phase='analysis', canonical_documents={})
    view, _, packets = await service._begin_question_evidence_use(
        service.record, agent='analyst', competitor='Example Product', dimension='feature')
    core = packets[0]['retrieval']['questions'][0]['core_fact_ids']
    assert len(core) == 2 and len(packets[0]['selected_fact_ids']) == 1
    row = service._question_packet_prompt(service.record, packets, view.facts)[0]['questions'][0]
    assert not row['missing_core_fact_ids'] and not row['minimum_evidence_missing']
    assert not row['evidence_gaps']


@pytest.mark.asyncio
@pytest.mark.parametrize('field', ['questions_sha256', 'scope_sha256', 'snapshot_content_hash',
                                  'selection_config', 'retrieval_identity_sha256', 'selected_fact_ids', 'missing', 'invalid'])
async def test_redaction_safe_selection_receipt_rejects_tampering(tmp_path, field):
    from packages.orchestrator.evidence_context import EvidenceUseRejectedError
    service = QuestionReplay(tmp_path)
    record = service.record
    _, use, _ = await service._begin_question_evidence_use(
        record, agent='analyst', competitor='Example Product', dimension='feature')
    trace = next(span for span in record.detail.trace_spans if span.name == 'question_evidence_selection')
    selection = json.loads(trace.full_output)
    if field == 'invalid':
        selection['receipt'] = None
    elif field == 'missing':
        selection.pop('receipt')
    else:
        selection['receipt']['packets'][0][field] = [] if field == 'selected_fact_ids' else 'changed'
    trace.full_output = json.dumps(selection)
    with pytest.raises(EvidenceUseRejectedError):
        service._validate_evidence_use(record, use)


@pytest.mark.asyncio
async def test_redacted_model_input_cannot_be_reported_as_verified_actual(tmp_path, monkeypatch):
    service = QuestionReplay(tmp_path)
    record = service.record
    record.detail.plan.decision_brief.decision_question = 'Example Product：Free 能保存 alice@example.com 的密码吗？'
    original = service._trace_llm_json

    async def traced(record, **kwargs):
        result = await original(record, **kwargs)
        full_input = kwargs['system'] + '\n\n' + kwargs['user'] + '\n\nSchema: ' + kwargs['schema_hint']
        service._append_trace_span(record, kind='llm', agent=kwargs['agent'], subagent=kwargs['subagent'],
            name=kwargs['name'], status='ok', started=time.perf_counter(), input_text=full_input,
            output_text=json.dumps(result), metadata={'llm_transport_attempts': 1})
        return result

    monkeypatch.setattr(service, '_trace_llm_json', traced)
    await service._real_analyst_branch_step(record, 'feature', 'Example Product')
    receipt = next(json.loads(span.full_output) for span in record.detail.trace_spans
                   if span.name == 'question_evidence_dispatch')
    assert receipt['status'] == receipt['content_status'] == 'unverified'
    assert receipt['actual'][0]['sent_fact_ids'] == []
    assert len(service.inputs[0]['user'].encode()) < next(
        use.max_bytes for use in record.detail.evidence_consumptions if use.id == receipt['consumption_id'])
    assert receipt['view_gaps'] == []
    assert receipt['actual'][0]['questions'][0]['evidence_gap'] == 'dispatch_unverified'
    assert receipt['actual'][0]['gaps'] == ['question_dispatch_unverified']
    assert receipt['question_views'][0]['questions'][0]['evidence_gap'] == 'dispatch_unverified'
    assert service.inputs and any('alice@example.com' in call['user'] for call in service.inputs)
    for span in record.detail.trace_spans:
        assert 'alice@example.com' not in span.full_input + span.full_output + json.dumps(span.metadata)
