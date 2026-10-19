"""Task 3: actual writer input, source-bound operations and scoped repair."""
import json
from types import SimpleNamespace

import pytest
from claim_review_fixture import sent_source_span_id, supported_review
from pydantic import HttpUrl, TypeAdapter
from test_capability_alignment import fact
from test_stage_evidence_views import FixedTime, distributed_detail

from packages.config import Settings
from packages.memory import KBCache, RunJournal
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunRecord, RunService
from packages.research.evidence.snapshot import seal_snapshot
from packages.research.evidence.operations import operation_observations
from packages.research.evidence.report_claims import ReportClaim, ReportDimensionAudit, AuditedReportClaim
from packages.schema.models import ComparisonMatrix, ComparisonAssessment, ReflectionRecord, CompetitorKnowledge, KnowledgeClaim, QCIssue, RedoScope
from packages.skills.registry import SkillRegistry


def writer_fixture(monkeypatch, products=('Notion',)):
    monkeypatch.setattr('packages.research.evidence.views.datetime', FixedTime)
    detail = distributed_detail(observations=1)
    detail.topic = '比较文档权限'
    detail.plan.competitors = list(products)
    detail.raw_sources = [s for s in detail.raw_sources if s.competitor in products]
    for source in detail.raw_sources:
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
    service = RunService(SkillRegistry.from_default_path(), Settings(demo_mode=True), journal=RunJournal.in_memory(), kb_cache=KBCache.in_memory(), graph_checkpointer=GraphCheckpointer.in_memory())
    record = RunRecord(detail)
    service._runs[detail.id] = record
    seal_snapshot(detail, phase='analysis', canonical_documents={})
    return service, record


def record_upstream(service, record):
    detail = record.detail
    for product in detail.plan.competitors:
        source = next(s for s in detail.raw_sources if s.competitor == product)
        detail.competitor_knowledge[product] = CompetitorKnowledge(competitor=product)
        detail.competitor_knowledge[product].feature_tree.summary_claims = [KnowledgeClaim(claim='Analysis: captured membership condition.', source_ids=[source.id], confidence=.9)]
        _, use = service._begin_evidence_use(record, agent='analyst', competitor=product, dimension='feature')
        service._validate_evidence_use(record, use)
        service._record_evidence_artifact(record, kind='analyst', competitor=product, dimension='feature', uses=[use], payload=service._analyst_evidence_artifact_payload(detail, product, 'feature'))
    detail.comparison_matrix = ComparisonMatrix(competitors=detail.plan.competitors, dimensions=['feature'], assessments={'feature': ComparisonAssessment(status='not_comparable', rationale='Different source-bound roles.', gaps=['role equivalence unverified'], source_ids=[s.id for s in detail.raw_sources])})
    _, use = service._begin_evidence_use(record, agent='comparator')
    service._validate_evidence_use(record, use)
    service._record_evidence_artifact(record, kind='comparator', uses=[use], payload=service._comparator_evidence_artifact_payload(detail))
    detail.reflections = [ReflectionRecord(iteration=1, writer_constraints=['Preserve membership prerequisites.'])]
    _, use = service._begin_evidence_use(record, agent='reflector')
    service._validate_evidence_use(record, use)
    service._record_evidence_artifact(record, kind='reflector', uses=[use], payload=detail.reflections[-1].model_dump(mode='json'))


@pytest.mark.asyncio
@pytest.mark.parametrize('stale', [None, 'analyst', 'comparator', 'reflector', 'snapshot'])
async def test_actual_dimension_writer_consumes_only_valid_upstream_artifacts(monkeypatch, stale):
    service, record = writer_fixture(monkeypatch)
    record_upstream(service, record)
    if stale == 'snapshot':
        record.detail.raw_sources[0].content_hash = 'new-accepted-body'
        seal_snapshot(record.detail, phase='analysis', canonical_documents={})
    elif stale:
        record.detail.evidence_artifact_dependencies = [d.model_copy(update={'payload_hash': 'stale'}) if d.kind == stale else d for d in record.detail.evidence_artifact_dependencies]
    inputs = []
    async def complete_text(*, system, user):
        inputs.append(json.loads(user.split('\nJSON:\n')[1]))
        return '{"claims":[]}'
    monkeypatch.setattr(service._llm, 'complete_text', complete_text)
    await service._writer_dimension_report(record, 20)
    assert len(inputs) == 1
    payload = inputs[0]
    audit = record.detail.report_dimension_audits[0]
    assert audit.upstream_dependencies is not None
    assert {edge.kind for edge in audit.upstream_dependencies} == {
        kind for kind, key in [('analyst', 'upstream_analysis'), ('comparator', 'comparison_assessment'),
                              ('reflector', 'reflection_constraints')] if payload.get(key)}
    assert all(edge in record.detail.evidence_artifact_dependencies for edge in audit.upstream_dependencies)
    for kind, key in [('analyst', 'upstream_analysis'), ('comparator', 'comparison_assessment'), ('reflector', 'reflection_constraints')]:
        assert bool(payload.get(key)) == (stale not in {kind, 'snapshot'})
    assert len(json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode()) <= 8192
    if stale is None:
        assert 'membership condition' in json.dumps(payload['upstream_analysis'])
        assert 'Different source-bound roles.' in json.dumps(payload['comparison_assessment'])
        assert 'Preserve membership prerequisites.' in json.dumps(payload['reflection_constraints'])


@pytest.mark.asyncio
async def test_writer_with_unavailable_transport_records_no_advisory_use(monkeypatch):
    from packages.llm.errors import LLMExecutionLimitError

    service, record = writer_fixture(monkeypatch)
    record_upstream(service, record)
    async def unavailable(*, system, user):
        assert 'upstream_analysis' in user
        raise LLMExecutionLimitError('No paid request admitted.')
    monkeypatch.setattr(service._llm, 'complete_text', unavailable)
    await service._writer_dimension_report(record, 20)
    audit = record.detail.report_dimension_audits[0]
    assert audit.upstream_dependencies == ()
    assert audit.model_dump(mode='json')['upstream_dependencies'] == []


def test_bound_operations_project_translations_without_verb_matching():
    from packages.agents.writer.dimension_writer import render_operation_comparison, operation_claim_selection
    from packages.research.evidence.operations import operation_binding
    cases = [('Confluence', 'read', 'Viewer can view pages on all plans.', 'Viewer 可浏览页面，适用于全部套餐。'),
             ('Confluence', 'share', 'Members on all plans can share pages.', '所有套餐的 Members 均可将页面提供给他人。'),
             ('Nuclino', 'comment', 'Members on all plans can comment on items.', '所有套餐的 Members 均可在条目下留言。'),
             ('Nuclino', 'create', 'Only workspace members with full access can create items.', '仅完整访问权限的工作区成员可新建条目。')]
    originals, audits, claims = [], [], []
    for index, (product, operation, quote, translation) in enumerate(cases):
        original = fact(product, quote, slot=str(index))
        row = next(r for r in operation_observations(original) if r['operation'] == operation)
        claim = ReportClaim(id=str(index), text=translation, kind='fact', competitor=product, dimension='feature', fact_ids=[original.id], source_ids=[original.source_id], operation_binding=operation_binding(row))
        originals.append(original); claims.append(claim)
        audits.append(ReportDimensionAudit(competitor=product, dimension='feature', consumption_id='use', claims=[AuditedReportClaim(claim=claim, status='supported')]))
    view = SimpleNamespace(facts=originals, source_ids=[f.source_id for f in originals])
    selected = operation_claim_selection(claims, view, ['read', 'share', 'comment', 'create'], {f.id for f in originals})
    assert len(selected) == 4
    detail = SimpleNamespace(topic='文档权限', output_language='zh-CN', plan=SimpleNamespace(competitors=['Confluence', 'Nuclino', 'Coda'], dimensions=['feature'], target_product=None))
    table = '\n'.join(render_operation_comparison(detail, audits, snapshot=view))
    for claim in claims:
        assert claim.text in table
    assert all('未取得已审核观察' in line.split('|')[-2] for line in table.splitlines() if any(line.startswith('| '+label+' |') for label in ['阅读', '评论', '创建', '分享']))


@pytest.mark.parametrize('changed', ['operation', 'fact_id', 'source_id', 'object_type', 'role', 'effect', 'plan', 'access_scope', 'prerequisites', 'condition_evidence'])
def test_explicit_binding_rejects_any_changed_source_condition(changed):
    from packages.research.evidence.operations import operation_binding
    from packages.research.evidence.report_claims import claim_rule_reasons
    original = fact('Nuclino', 'Members on Business plan can comment on items only if invited.', slot='binding')
    row = next(r for r in operation_observations(original) if r['operation'] == 'comment')
    binding = operation_binding(row)
    binding[changed] = [] if changed in {'prerequisites', 'condition_evidence'} else 'forged'
    claim = ReportClaim(id='bound', text='受邀的 Business Members 可在条目下留言。', kind='fact', competitor='Nuclino', dimension='feature', fact_ids=[original.id], source_ids=[original.source_id], operation_binding=binding)
    view = SimpleNamespace(facts=[original])
    boundaries = [SimpleNamespace(allowed_fact_ids=[original.id])]
    assert 'operation_binding_mismatch' in claim_rule_reasons(claim, view, boundaries)


def test_legacy_report_claim_serialization_does_not_change_hash():
    payload = dict(id='old', text='Old reviewed observation.', kind='fact', competitor='Notion', dimension='feature', fact_ids=['f'], source_ids=['s'])
    claim = ReportClaim.model_validate(payload)
    assert claim.model_dump(mode='json') == payload
    assert json.loads(claim.model_dump_json()) == payload


def bound_model(inputs):
    async def model(record, **kwargs):
        from packages.agents.writer.dimension_writer import parse_json
        payload = parse_json(kwargs['user'].split('\nJSON:\n')[1])
        inputs.append((kwargs['name'], kwargs['subagent'], payload))
        if kwargs['name'] == 'dimension_claim_review':
            return json.dumps({'reviews': [supported_review(c, 'All original object and membership conditions preserved.') for c in payload['claims']]})
        claims = []
        for original in payload['evidence_view']['facts']:
            for binding in original.get('operation_observations', []):
                if any(c['operation_binding']['operation'] == binding['operation'] for c in claims):
                    continue
                claims.append(dict(text='支持对共享页面进行评论，需成为工作区成员。', kind='fact', competitor=original['competitor'], dimension='feature', fact_ids=[original['id']], source_ids=[original['source_id']], operation_binding=binding))
        return json.dumps({'claims': claims})
    return model


@pytest.mark.asyncio
@pytest.mark.parametrize('invalidate', [None, 'producer', 'snapshot', 'manual_revision'])
async def test_scoped_dimension_repair_retains_only_valid_unaffected_audits(monkeypatch, invalidate):
    service, record = writer_fixture(monkeypatch, products=('Notion', 'Confluence'))
    calls = []
    monkeypatch.setattr(service, '_trace_llm_text', bound_model(calls))
    await service._real_writer_step(record)
    assert len(calls) == 4
    previous = next(a for a in record.detail.report_dimension_audits if a.competitor == 'Confluence')
    if invalidate == 'producer':
        record.detail.evidence_artifact_dependencies = [d.model_copy(update={'payload_hash': 'stale'}) if d.kind == 'writer' else d for d in record.detail.evidence_artifact_dependencies]
    elif invalidate == 'snapshot':
        record.detail.raw_sources[0].content_hash = 'new-accepted-body'
        seal_snapshot(record.detail, phase='analysis', canonical_documents={})
    elif invalidate == 'manual_revision':
        record.detail.report_md += '\nUnreviewed manual capability assertion.'
    scope = RedoScope(kind='writer_only', target_competitor='Notion', target_subagent='feature', rationale='Recheck the comment observation.')
    issue = QCIssue(id='repair-comments', severity='warn', detected_by='coverage', target_agent='writer', target_competitor='Notion', target_subagent='feature', field_path='report.feature.operation.comment', problem='Review the comment observation.', redo_scope=scope, metadata={'operation': 'comment'})
    service._append_agent_message(record, from_agent='qa', to_agent='writer', message_type='redo_request', payload_schema='RedoRequestPayload', payload={'issues': [issue.model_dump(mode='json')], 'issue_ids': [issue.id], 'redo_scope': scope.model_dump(mode='json')})
    calls.clear()
    await service._real_writer_step(record)
    assert len(calls) == (2 if invalidate is None else 4)
    repair_event = next(message for message in reversed(record.detail.agent_messages) if 'writer_repair_mode' in message.payload)
    assert repair_event.payload['writer_repair_mode'] == ('section' if invalidate is None else 'full')
    current = next(a for a in record.detail.report_dimension_audits if a.competitor == 'Confluence')
    assert (current == previous) == (invalidate is None)
    from packages.agents.qa.evidence_alignment import audit_dimension_claims
    snapshot = service._current_evidence_snapshot(record)
    assert service._final_qa_producer_verified(record, snapshot)
    assert not audit_dimension_claims(service, record, snapshot, producer_verified=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('status,winner', [('comparable', 'Notion'), ('not_comparable', None)])
async def test_report_uses_validated_comparison_and_omits_unrequested_bill(monkeypatch, status, winner):
    service, record = writer_fixture(monkeypatch)
    record_upstream(service, record)
    record.detail.comparison_matrix.assessments['feature'] = ComparisonAssessment(status=status, winner=winner, rationale='源观察按同一角色核验。', scenario='共同维护页面', source_ids=[record.detail.raw_sources[0].id])
    _, use = service._begin_evidence_use(record, agent='comparator')
    service._validate_evidence_use(record, use)
    service._record_evidence_artifact(record, kind='comparator', uses=[use], payload=service._comparator_evidence_artifact_payload(record.detail))
    monkeypatch.setattr(service, '_trace_llm_text', bound_model([]))
    report = await service._writer_dimension_report(record, 20)
    assert '完整账单' not in report
    assert '源观察按同一角色核验。' in report
    assert ('优选 Notion' in report) == (status == 'comparable')


@pytest.mark.asyncio
@pytest.mark.parametrize('wrong_text', ['所有用户均可编辑所有页面。', '任何访客均可留言。', '成员不得发表评论。'])
async def test_valid_operation_identity_does_not_replace_semantic_review(monkeypatch, wrong_text):
    service, record = writer_fixture(monkeypatch)
    calls = []
    async def model(record, **kwargs):
        payload = json.loads(kwargs['user'].split('\nJSON:\n')[1])
        calls.append(kwargs)
        if kwargs['name'] == 'dimension_claim_writer':
            f = payload['evidence_view']['facts'][0]
            binding = f['operation_observations'][0]
            return json.dumps({'claims': [dict(text=wrong_text, kind='fact', competitor=f['competitor'], dimension='feature', fact_ids=[f['id']], source_ids=[f['source_id']], operation_binding=binding)]})
        assert payload['claims'][0]['operation_binding']
        assert 'exactly that operation, object, actor role, effect and every prerequisite' in kwargs['system']
        return json.dumps({'reviews': [{'claim_id': c['id'], 'verdict': 'unsupported', 'reason': 'Claim changes the bound operation, role or denial.'} for c in payload['claims']]})
    monkeypatch.setattr(service, '_trace_llm_text', model)
    report = await service._writer_dimension_report(record, 20)
    assert len(calls) == 2
    assert wrong_text not in report
    assert record.detail.report_dimension_audits[0].claims[0].status == 'rejected'


@pytest.mark.asyncio
@pytest.mark.parametrize('explicit_region', [False, True])
async def test_directory_market_does_not_block_recorded_feature_or_authorize_region(monkeypatch, explicit_region):
    from packages.research.evidence.answer_models import AnswerRequirement
    service, record = writer_fixture(monkeypatch)
    record.detail.raw_sources[0].metadata['market'] = 'US'
    if explicit_region:
        record.detail.plan.answer_requirements = [AnswerRequirement(competitor='Notion', dimension='feature', intent='facts', market='US', as_of=record.detail.created_at.date())]
    snapshot = seal_snapshot(record.detail, phase='analysis', canonical_documents={})
    assert all(f.market is None for f in snapshot.facts)
    calls = []
    monkeypatch.setattr(service, '_trace_llm_text', bound_model(calls))
    report = await service._writer_dimension_report(record, 20)
    assert len(calls) == (0 if explicit_region else 2)
    assert ('支持对共享页面进行评论，需成为工作区成员。' in report) == (not explicit_region)
    assert not any('美国' in c.claim.text or 'US' in c.claim.text for a in record.detail.report_dimension_audits for c in a.claims)
    for boundary in record.detail.report_answer_boundaries:
        assert boundary.requirement.market == ('US' if explicit_region else None)
        if explicit_region:
            assert not boundary.allowed_fact_ids


@pytest.mark.asyncio
async def test_four_recorded_operations_reach_real_writer_review_and_report_without_coda_fill(monkeypatch):
    service, record = writer_fixture(monkeypatch, products=('Confluence', 'Notion'))
    detail = record.detail
    detail.plan.competitors = ['Confluence', 'Nuclino', 'Coda']
    nuclino = detail.raw_sources.pop().model_copy(deep=True)
    nuclino.id = 'source-Nuclino-feature'
    nuclino.competitor = 'Nuclino'
    nuclino.covered_competitors = ['Nuclino']
    detail.raw_sources.append(nuclino)
    quotes = {'Confluence': [('read', 'Viewer can view pages on all plans.'), ('share', 'Members on all plans can share pages.')],
              'Nuclino': [('comment', 'Members on all plans can comment on items.'), ('create', 'Only workspace members with full access can create items.')]}
    translations = {'read': 'Viewer 可浏览页面，适用于全部套餐。', 'share': '所有套餐的 Members 均可将页面提供给他人。', 'comment': '所有套餐的 Members 均可在条目下留言。', 'create': '仅完整访问权限的工作区成员可新建条目。'}
    for source in detail.raw_sources:
        source.metadata['normalized_fields'] = [dict(kind='feature', dimension='feature', competitor=source.competitor, slot=operation, support_level='documented', evidence_terms=[quote], evidence_quote=quote, evidence_item_ids=[source.id + operation], confidence=.9) for operation, quote in quotes[source.competitor]]
    seal_snapshot(detail, phase='analysis', canonical_documents={})
    inputs = []
    async def complete_text(*, system, user):
        payload = json.loads(user.split('\nJSON:\n')[1]); inputs.append(payload)
        if 'claims' in payload:
            assert all(c['operation_binding'] for c in payload['claims'])
            return json.dumps({'reviews': [supported_review(c, 'All bound operation, actor and object restrictions preserved.') for c in payload['claims']]})
        claims = []
        for f in payload['evidence_view']['facts']:
            for binding in f['operation_observations']:
                claims.append(dict(text=translations[binding['operation']], kind='fact', competitor=f['competitor'], dimension='feature', fact_ids=[f['id']], source_ids=[f['source_id']], observation_id=binding['observation_id']))
        return json.dumps({'claims': claims})
    monkeypatch.setattr(service._llm, 'complete_text', complete_text)
    await service._real_writer_step(record)
    assert len(inputs) == 4
    for text in translations.values():
        assert text in detail.report_md
    published = [c for a in detail.report_dimension_audits for c in a.claims if c.status == 'supported']
    assert len(published) == 4
    assert all(c.claim.operation_binding for c in published)
    assert not any(a.claims for a in detail.report_dimension_audits if a.competitor == 'Coda')


@pytest.mark.asyncio
async def test_operation_repair_retains_other_claim_and_review_inside_same_dimension(monkeypatch):
    service, record = writer_fixture(monkeypatch)
    row = record.detail.raw_sources[0].metadata['normalized_fields'][0].copy()
    quote = 'Members on all plans can view pages.'
    row.update(slot='read', evidence_terms=[quote], evidence_quote=quote, evidence_item_ids=['read-observation'])
    record.detail.raw_sources[0].metadata['normalized_fields'] = [record.detail.raw_sources[0].metadata['normalized_fields'][0], row]
    seal_snapshot(record.detail, phase='analysis', canonical_documents={})
    inputs = []
    base = bound_model(inputs)
    async def model(record, **kwargs):
        response = await base(record, **kwargs)
        if kwargs['name'] == 'dimension_claim_writer':
            data = json.loads(response)
            for claim in data['claims']:
                if claim['operation_binding']['operation'] == 'read':
                    claim['text'] = '所有套餐的 Members 均可浏览页面。'
            return json.dumps(data)
        return response
    monkeypatch.setattr(service, '_trace_llm_text', model)
    await service._real_writer_step(record)
    old_read = next(c for c in record.detail.report_dimension_audits[0].claims if c.claim.operation_binding.operation == 'read')
    scope = RedoScope(kind='writer_only', target_competitor='Notion', target_subagent='feature', rationale='Recheck comments only.')
    issue = QCIssue(id='comment-only', severity='warn', detected_by='coverage', target_agent='writer', target_competitor='Notion', target_subagent='feature', field_path='report.feature.operation.comment', problem='Recheck comments only.', redo_scope=scope, metadata={'operation': 'comment'})
    service._append_agent_message(record, from_agent='qa', to_agent='writer', message_type='redo_request', payload_schema='RedoRequestPayload', payload={'issues': [issue.model_dump(mode='json')], 'issue_ids': [issue.id], 'redo_scope': scope.model_dump(mode='json')})
    inputs.clear()
    await service._real_writer_step(record)
    assert len(inputs) == 2
    assert inputs[0][2]['requested_operations'] == ['comment']
    assert len(inputs[1][2]['claims']) == 1
    assert inputs[1][2]['claims'][0]['operation_binding']['operation'] == 'comment'
    new_read = next(c for c in record.detail.report_dimension_audits[0].claims if c.claim.operation_binding.operation == 'read')
    assert new_read == old_read
    from packages.agents.qa.evidence_alignment import audit_dimension_claims
    assert not audit_dimension_claims(service, record, service._current_evidence_snapshot(record), producer_verified=True)


@pytest.mark.asyncio
async def test_large_valid_analysis_keeps_complete_bounded_claims_in_actual_writer_input(monkeypatch):
    service, record = writer_fixture(monkeypatch)
    record_upstream(service, record)
    knowledge = record.detail.competitor_knowledge['Notion']
    knowledge.feature_tree.summary_claims = [KnowledgeClaim(claim=f'Analysis observation {index}: ' + 'Preserve the captured membership prerequisite. ' * 4, source_ids=[record.detail.raw_sources[0].id], confidence=.9) for index in range(30)]
    _, use = service._begin_evidence_use(record, agent='analyst', competitor='Notion', dimension='feature')
    service._validate_evidence_use(record, use)
    original = service._analyst_evidence_artifact_payload(record.detail, 'Notion', 'feature')
    service._record_evidence_artifact(record, kind='analyst', competitor='Notion', dimension='feature', uses=[use], payload=original)
    inputs = []
    async def complete_text(*, system, user):
        inputs.append(json.loads(user.split('\nJSON:\n')[1])); return '{"claims":[]}'
    monkeypatch.setattr(service._llm, 'complete_text', complete_text)
    await service._writer_dimension_report(record, 20)
    context = inputs[0]['upstream_analysis']
    assert context['producer_hash'] == service._evidence_artifact_hash(original)
    assert 'Analysis observation' in json.dumps(context['content'])
    assert len(json.dumps(inputs[0], ensure_ascii=False, separators=(',', ':')).encode()) <= 8192


@pytest.mark.asyncio
async def test_comparison_winner_requires_published_audited_product_observations(monkeypatch):
    service, record = writer_fixture(monkeypatch)
    record_upstream(service, record)
    record.detail.comparison_matrix.assessments['feature'] = ComparisonAssessment(status='comparable', winner='Notion', rationale='同口径观察。', scenario='共同维护页面', source_ids=[record.detail.raw_sources[0].id])
    _, use = service._begin_evidence_use(record, agent='comparator')
    service._validate_evidence_use(record, use)
    service._record_evidence_artifact(record, kind='comparator', uses=[use], payload=service._comparator_evidence_artifact_payload(record.detail))
    async def unavailable_claims(record, **kwargs):
        return '{"claims":[]}'
    monkeypatch.setattr(service, '_trace_llm_text', unavailable_claims)
    report = await service._writer_dimension_report(record, 20)
    assert '优选 Notion' not in report
    assert '尚不能同口径比较' in report


@pytest.mark.asyncio
@pytest.mark.parametrize('select_observation', [False, True])
async def test_generic_quick_writer_offers_and_requires_operation_identity(monkeypatch, select_observation):
    service, record = writer_fixture(monkeypatch)
    record.detail.topic = '比较协作文档工具'
    record.detail.plan.dimensions = ['feature', 'persona']
    inputs = []
    text = '支持对共享页面进行评论，需成为工作区成员。'
    async def complete_text(*, system, user):
        payload = json.loads(user.split('\nJSON:\n')[1]); inputs.append(payload)
        if 'claims' in payload:
            return json.dumps({'reviews': [supported_review(c, 'All original membership conditions preserved.') for c in payload['claims']]})
        original = payload['evidence_view']['facts'][0]
        claim = dict(text=text, kind='fact', competitor=original['competitor'], dimension=original['dimension'], fact_ids=[original['id']], source_ids=[original['source_id']])
        candidates = original.get('operation_observations', [])
        if select_observation and candidates:
            claim['observation_id'] = candidates[0]['observation_id']
        return json.dumps({'claims': [claim]})
    monkeypatch.setattr(service._llm, 'complete_text', complete_text)
    if select_observation:
        await service._real_writer_step(record)
    else:
        report = await service._writer_dimension_report(record, 20)
        from packages.agents.writer.quality_preflight import run_writer_quality_preflight
        assert not run_writer_quality_preflight(record.detail, report).passed
    assert not inputs[0].get('requested_operations')
    assert any(f.get('operation_observations') for f in inputs[0]['evidence_view']['facts'])
    published = [c for a in record.detail.report_dimension_audits for c in a.claims if c.status == 'supported']
    assert len(published) == int(select_observation)
    assert all(c.claim.operation_binding is not None for c in published)
    assert (text in record.detail.report_md) == select_observation
    if not select_observation:
        assert any('operation_binding_required' in a.gaps for a in record.detail.report_dimension_audits)
        assert not service._final_qa_producer_verified(record, service._current_evidence_snapshot(record))
        return
    from packages.agents.qa.evidence_alignment import audit_dimension_claims
    snapshot = service._current_evidence_snapshot(record)
    assert service._final_qa_producer_verified(record, snapshot)
    assert not audit_dimension_claims(service, record, snapshot, producer_verified=True)


@pytest.mark.asyncio
async def test_generic_non_operation_fact_can_publish_without_an_operation_identity(monkeypatch):
    service, record = writer_fixture(monkeypatch)
    detail = record.detail
    detail.topic = '比较硬件规格'
    detail.plan.dimensions = ['feature', 'persona']
    quote = 'The battery capacity is 5000 mAh.'
    row = detail.raw_sources[0].metadata['normalized_fields'][0].copy()
    row.update(slot='battery', evidence_terms=[quote], evidence_quote=quote, evidence_item_ids=['battery-only'])
    detail.raw_sources[0].metadata['normalized_fields'] = [row]
    seal_snapshot(detail, phase='analysis', canonical_documents={})
    inputs = []
    async def complete_text(*, system, user):
        payload = json.loads(user.split('\nJSON:\n')[1]); inputs.append(payload)
        if 'claims' in payload:
            return json.dumps({'reviews': [supported_review(c, 'Exact battery specification preserved.') for c in payload['claims']]})
        assert not any(f.get('operation_observations') for f in payload['evidence_view']['facts'])
        assert 'For facts without operation candidates, omit observation_id' in system
        original = payload['evidence_view']['facts'][0]
        return json.dumps({'claims': [dict(text='电池容量为 5000 mAh。', kind='fact', competitor=original['competitor'], dimension='feature', fact_ids=[original['id']], source_ids=[original['source_id']],
            source_span_ids=[sent_source_span_id(original)])]})
    monkeypatch.setattr(service._llm, 'complete_text', complete_text)
    await service._real_writer_step(record)
    assert len(inputs) == 2
    published = [c for a in detail.report_dimension_audits for c in a.claims if c.status == 'supported']
    assert len(published) == 1 and published[0].claim.operation_binding is None
    assert '电池容量为 5000 mAh。' in detail.report_md


@pytest.mark.asyncio
@pytest.mark.parametrize('invalidate', [None, 'producer', 'snapshot', 'manual_revision'])
async def test_operation_repair_keeps_audited_non_operation_fact_and_rechecks_invalid_producers(monkeypatch, invalidate):
    service, record = writer_fixture(monkeypatch)
    detail = record.detail
    detail.topic = '比较协作文档工具'
    detail.plan.dimensions = ['feature', 'persona']
    comment = detail.raw_sources[0].metadata['normalized_fields'][0]
    limit = {**comment, 'slot': 'attachment_limit', 'evidence_terms': ['The maximum attachment size is 5 MB.'],
             'evidence_quote': 'The maximum attachment size is 5 MB.', 'evidence_item_ids': ['attachment-limit']}
    detail.raw_sources[0].metadata['normalized_fields'] = [comment, limit]
    seal_snapshot(detail, phase='analysis', canonical_documents={})
    attachment_text = '附件大小上限为 5 MB。'
    inputs = []
    async def complete_text(*, system, user):
        payload = json.loads(user.split('\nJSON:\n')[1]); inputs.append(payload)
        if 'claims' in payload:
            return json.dumps({'reviews': [supported_review(c, 'Exact source observation and all original conditions preserved.') for c in payload['claims']]})
        claims = []
        for original in payload['evidence_view']['facts']:
            candidates = original.get('operation_observations', [])
            claim = dict(text='支持对共享页面进行评论，需成为工作区成员。' if candidates else attachment_text,
                         kind='fact', competitor=original['competitor'], dimension=original['dimension'],
                         fact_ids=[original['id']], source_ids=[original['source_id']])
            if candidates:
                claim['observation_id'] = candidates[0]['observation_id']
            else:
                claim['source_span_ids'] = [sent_source_span_id(original)]
            claims.append(claim)
        return json.dumps({'claims': claims})
    monkeypatch.setattr(service._llm, 'complete_text', complete_text)
    await service._real_writer_step(record)
    old_attachment = next(c for a in detail.report_dimension_audits for c in a.claims if c.claim.text == attachment_text)
    assert old_attachment.status == 'supported' and old_attachment.claim.operation_binding is None
    if invalidate == 'producer':
        detail.evidence_artifact_dependencies = [d.model_copy(update={'payload_hash': 'stale'}) if d.kind == 'writer' else d for d in detail.evidence_artifact_dependencies]
    elif invalidate == 'snapshot':
        detail.raw_sources[0].content_hash = 'new-accepted-body'
        seal_snapshot(detail, phase='analysis', canonical_documents={})
    elif invalidate == 'manual_revision':
        detail.report_md += '\nUnreviewed manual assertion.'
    scope = RedoScope(kind='writer_only', target_competitor='Notion', target_subagent='feature', rationale='Recheck comment only.')
    issue = QCIssue(id='comment-keep-limit', severity='warn', detected_by='coverage', target_agent='writer',
        target_competitor='Notion', target_subagent='feature', field_path='report.feature.operation.comment',
        problem='Recheck comment only.', redo_scope=scope, metadata={'operation': 'comment'})
    service._append_agent_message(record, from_agent='qa', to_agent='writer', message_type='redo_request',
        payload_schema='RedoRequestPayload', payload={'issues': [issue.model_dump(mode='json')], 'issue_ids': [issue.id], 'redo_scope': scope.model_dump(mode='json')})
    inputs.clear()
    await service._real_writer_step(record)
    assert len(inputs) == 2
    assert len(inputs[1]['claims']) == (1 if invalidate is None else 2)
    assert attachment_text in detail.report_md
    current_attachment = next(c for a in detail.report_dimension_audits for c in a.claims if c.claim.text == attachment_text)
    assert current_attachment.status == 'supported' and current_attachment.claim.operation_binding is None
    assert (current_attachment == old_attachment) == (invalidate is None)
    from packages.agents.qa.evidence_alignment import audit_dimension_claims
    snapshot = service._current_evidence_snapshot(record)
    assert service._final_qa_producer_verified(record, snapshot)
    assert not audit_dimension_claims(service, record, snapshot, producer_verified=True)
