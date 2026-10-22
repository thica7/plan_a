"""Real local stages with anonymous offline transport, never a semantic review claim."""

import json
from claim_review_fixture import answer_response
from datetime import UTC, datetime

import pytest
from claim_review_fixture import question_plan_response, sent_source_atom, supported_review
from test_billing_components import CPU, MINIMUM, RATE
from test_question_reflection_scope import COMPARISON_GAPS
from test_writer_question_delivery import service_for

from packages.research.evidence.snapshot import seal_snapshot
from packages.schema.api_dto import RunDetail
from packages.schema.models import (
    AnalysisPlan, ComparisonCell, ComparisonMatrix, CompetitorKB, DecisionBrief, RawSource,
)


def stage_case():
    now = datetime.now(UTC)
    detail = RunDetail(id='anonymous-billing-stages', workspace_id='fixture-workspace',
        project_id='fixture-project', topic='ExampleCompute 条件研究', status='running',
        execution_mode='real', created_at=now, updated_at=now,
        plan=AnalysisPlan(topic='ExampleCompute 条件研究', competitors=['ExampleCompute'],
            dimensions=['feature'], research_depth='quick', decision_brief=DecisionBrief(
                decision_question='ExampleCompute: What is the documented Plus plan monthly request rate?\n'
                'ExampleCompute: What is the documented Compute Paid account monthly minimum?')))
    detail.raw_sources = [RawSource(id='example-billing-source', competitor='ExampleCompute',
        covered_competitors=['ExampleCompute'], dimension='feature', source_type='webpage_verified',
        title='ExampleCompute billing', url='https://example.invalid/billing', snippet=RATE,
        content_hash='new-anonymous-billing-source', confidence=.9, extracted_at=now,
        metadata={'last_verified_at': now.isoformat(), 'source_material_level': 'full_source',
            'normalized_fields': [dict(kind='feature', competitor='ExampleCompute', dimension='feature',
                confidence=.9, support_level='documented', slot=f'billing-component-{index}',
                evidence_item_ids=[f'billing-original-{index}'], evidence_quote=text,
                evidence_terms=[text]) for index, text in enumerate((RATE, CPU, MINIMUM))]})]
    detail.comparison_matrix = ComparisonMatrix(competitors=['ExampleCompute'], dimensions=['feature'],
        cells=[ComparisonCell(competitor='ExampleCompute', dimension='feature', value='Documented components',
                              source_ids=['example-billing-source'], confidence=.9)])
    snapshot = seal_snapshot(detail, phase='analysis', canonical_documents={})
    service, record = service_for(detail)
    _, analyst_use = service._begin_evidence_use(record, agent='analyst',
        competitor='ExampleCompute', dimension='feature')
    detail.competitor_kbs['ExampleCompute'] = CompetitorKB(competitor='ExampleCompute',
        slices={'feature': [RATE + ' [source:example-billing-source]']},
        sources=['example-billing-source'], confidence=.9)
    service._ensure_structured_knowledge(detail)
    service._validate_evidence_use(record, analyst_use)
    service._record_evidence_artifact(record, kind='analyst', competitor='ExampleCompute',
        dimension='feature', payload=service._analyst_evidence_artifact_payload(detail, 'ExampleCompute', 'feature'),
        uses=[analyst_use])
    _, comparator_use = service._begin_evidence_use(record, agent='comparator')
    service._validate_evidence_use(record, comparator_use)
    service._record_evidence_artifact(record, kind='comparator',
        payload=service._comparator_evidence_artifact_payload(detail), uses=[comparator_use])
    return detail, snapshot, service, record


def resolved_payload(raw):
    payload = json.loads(raw.split('\nJSON:\n', 1)[1])
    def resolve(value):
        if isinstance(value, dict):
            if set(value) == {'text_ref'}:
                return payload['text_sets'][value['text_ref']]
            return {key: resolve(item) for key, item in value.items()}
        if isinstance(value, list):
            return [resolve(item) for item in value]
        return value
    return resolve(payload)


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', [None, 'unit', 'plan', 'currency', 'minimum_total',
                                     'minimum_resource', 'final_bill', 'derived', 'two_bad'])
async def test_actual_writer_final_evidence_and_qa_replay_component_bindings(monkeypatch, mutation):
    detail, snapshot, service, record = stage_case()
    calls = []
    async def offline_transport(record, **kwargs):
        calls.append(kwargs['name'])
        payload = resolved_payload(kwargs['user'])
        if kwargs['name'] == 'dimension_claim_writer':
            claims = []
            for row in payload['evidence_view']['facts']:
                if row['field'] != 'evidence_terms':
                    continue
                text = row['quote']
                if text == RATE:
                    if mutation == 'unit':
                        text = text.replace('million requests', 'request')
                    elif mutation == 'plan':
                        text = text.replace('Plus', 'Ultra')
                    elif mutation == 'currency':
                        text = text.replace('$0.47', '€0.47')
                    elif mutation == 'derived':
                        text = 'Plus plan monthly request overage component is $1.88, based on 15 million minus 11 million requests.'
                    elif mutation == 'final_bill':
                        text = text.removesuffix('.') + ', which is our final monthly bill.'
                    elif mutation == 'two_bad':
                        text += ' Actual total is $99 and tax is $3.'
                elif text == MINIMUM and mutation == 'minimum_total':
                    text = 'Compute Paid plan actual complete monthly bill for an account is $17 USD.'
                elif text == MINIMUM and mutation == 'minimum_resource':
                    text = text.replace('for an account', 'for each project in an account')
                claims.append(sent_source_atom(row, text))
            return question_plan_response(payload, claims)
        if kwargs['name'] == 'dimension_claim_review':
            return json.dumps({'reviews': [supported_review(row,
                'Anonymous offline transport fixture, not a semantic accuracy verdict.') for row in payload['claims']]})
        assert kwargs['name'] in {'dimension_answer_coverage', 'dimension_answer_review'}
        return answer_response(payload, {'version': 3, 'answers': [dict(question_id=q['question_id'], status='answered',
            claim_ids=[next(c['id'] for c in payload['claims']
                            if ('minimum' in c['text']) == ('minimum' in q['question']))],
            resolution='direct', conclusion='yes', missing_fields=[],
            reason='Anonymous transport fixture selects the documented component.') for q in payload['questions']]})
    async def forbidden(*args, **kwargs):
        pytest.fail('Unexpected model/network request in offline stage fixture')
    monkeypatch.setattr(service, '_trace_llm_text', offline_transport)
    monkeypatch.setattr(service, '_trace_llm_json', forbidden)
    await service._real_writer_step(record)
    assert service._final_qa_producer_verified(record, snapshot)
    published = [item.claim for audit in detail.report_dimension_audits
                 for item in audit.claims if item.status == 'supported']
    assert len(published) == 3 and all(claim.source_span_bindings for claim in published)
    _, issues, _ = await service._final_qa_evidence(record)
    amount_issues = [i for i in issues if i.metadata.get('answer_guard_reason') == 'withheld_or_unsupported_amount']
    assert bool(amount_issues) == (mutation is not None), issues
    await service._real_qa_step(record)
    final = [i for i in detail.qa_findings if i.metadata.get('answer_guard_reason') == 'withheld_or_unsupported_amount']
    assert bool(final) == (mutation is not None), detail.qa_findings
    if mutation == 'two_bad':
        assert {i.metadata['amount'] for i in final} == {'99', '3'}
        assert len({i.id for i in final}) == len(final)
        by_line = {i.field_path for i in final}
        assert all({i.metadata['amount'] for i in final if i.field_path == line} == {'99', '3'}
                   for line in by_line)
    if mutation is None:
        assert not [i for i in detail.qa_findings if i.severity == 'blocker'], json.dumps({
            'reasons': [i.metadata for i in detail.qa_findings],
            'coverage': [answer.model_dump() for audit in detail.report_dimension_audits
                         for answer in audit.answer_coverage]}, ensure_ascii=False)
    assert {'dimension_claim_writer', 'dimension_claim_review'} <= set(calls)


@pytest.mark.asyncio
@pytest.mark.parametrize('expanded_request', [None,
    'ExampleCompute: 请完整分析 ExampleCompute 的权限与计费能力？',
    'ExampleCompute: Is ExampleCompute better than OtherCompute for role permissions?',
])
async def test_real_reflector_receives_brief_scope_and_server_rechecks_its_block(monkeypatch, expanded_request):
    detail, _, service, record = stage_case()
    question = ('ExampleCompute: Can this role clear another domain?\n'
                'ExampleCompute: Does 15 million requests determine our exact monthly bill?')
    question = expanded_request or question
    detail.plan.decision_brief = DecisionBrief(decision_question=question)
    prompts = []
    async def offline_reflector(record, **kwargs):
        assert kwargs['name'] == 'coverage_reflection'
        prompts.append(kwargs['user'])
        return dict(coverage_gaps=[], confidence_outliers=[], cross_competitor_gaps=[],
                    gate_status='block', blocking_gaps=COMPARISON_GAPS, writer_constraints=[])
    monkeypatch.setattr(service, '_trace_llm_json', offline_reflector)
    await service._real_reflector_step(record)
    assert len(prompts) == 1
    assert question.replace('\n', ' ') in prompts[0]
    if expanded_request:
        assert '"mode": "comparison"' in prompts[0]
        assert detail.reflections[-1].gate_status == 'block'
        actual = detail.reflections[-1].blocking_gaps
        assert actual[:len(COMPARISON_GAPS)] == COMPARISON_GAPS
        extras = actual[len(COMPARISON_GAPS):]
        from packages.research.question_scope import research_questions
        expected = research_questions(detail, 'ExampleCompute', 'feature')
        assert extras == [
            f"Question evidence unverified: ExampleCompute / feature / {row['question_id']}; "
            'question_no_relevant_original; missing_core_fact_ids=[]; missing_exception_fact_ids=[].'
            for row in expected]
        assert any(i.severity == 'blocker' for i in service._build_reflector_qa_issues(detail))
    else:
        assert 'single_product_questions' in prompts[0]
        assert detail.reflections[-1].gate_status == 'block'
        from packages.research.question_scope import research_questions
        role_question = next(row for row in research_questions(detail, 'ExampleCompute', 'feature')
                             if 'clear another domain' in row['question'])
        assert detail.reflections[-1].blocking_gaps == [
            f"Question evidence unverified: ExampleCompute / feature / {role_question['question_id']}; "
            'question_no_relevant_original; missing_core_fact_ids=[]; missing_exception_fact_ids=[].']
