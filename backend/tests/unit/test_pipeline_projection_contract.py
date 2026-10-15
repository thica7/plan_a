"""Live boundary regressions: producer coverage, compact reports and review input."""
import json
from types import SimpleNamespace

import pytest
from test_operation_coverage import four_branch_service
from test_writer_artifact_consumption import writer_fixture, bound_model
from test_capability_alignment import fact
from packages.agents.writer.dimension_writer import compact_prompt_json, encoded, render_dimension_report, review_payload
from packages.agents.writer.quality_preflight import run_writer_quality_preflight
from packages.business_intel.release_gate import _report_structure_issues, _report_depth_issues, _report_richness_issues
from packages.research.evidence.report_claims import ReportClaim
from packages.schema.enterprise import ReportVersionRecord
from packages.schema.models import ComparisonAssessment, ComparisonCell, ComparisonMatrix


def expand_text_refs(payload):
    texts = payload.get('text_sets', {})
    def expand(value):
        if isinstance(value, dict):
            if set(value) == {'text_ref'}:
                return texts[value['text_ref']]
            return {k: expand(v) for k, v in value.items() if k != 'text_sets'}
        if isinstance(value, list):
            return [expand(v) for v in value]
        return value
    return expand(payload)


def recorded_matrix(service, record):
    detail = record.detail
    detail.comparison_matrix = ComparisonMatrix(competitors=detail.plan.competitors, dimensions=['feature'],
        cells=[ComparisonCell(competitor=p, dimension='feature', value='Producer analysis with full original conditions.',
            source_ids=['source-'+p], confidence=.9) for p in detail.plan.competitors])
    _, use = service._begin_evidence_use(record, agent='comparator')
    service._validate_evidence_use(record, use)
    service._record_evidence_artifact(record, kind='comparator', uses=[use],
        payload=service._comparator_evidence_artifact_payload(detail))


@pytest.mark.asyncio
@pytest.mark.parametrize('tamper', [None, 'analyst', 'comparator', 'source'])
async def test_real_reflector_consumes_bounded_valid_producer_coverage(monkeypatch, tamper):
    service, record = four_branch_service()
    recorded_matrix(service, record)
    from dataclasses import replace
    service._settings = replace(service._settings, run_llm_max_tokens=200000)
    snapshot = service._current_evidence_snapshot(record)
    assert sum(len(f.model_dump_json().encode()) for f in snapshot.facts) > 18000
    if tamper in {'analyst', 'comparator'}:
        record.detail.evidence_artifact_dependencies = [d.model_copy(update={'payload_hash': 'tampered'})
            if d.kind == tamper and (tamper != 'analyst' or d.competitor == 'A') else d
            for d in record.detail.evidence_artifact_dependencies]
    elif tamper == 'source':
        record.detail.raw_sources[0].content_hash = 'tampered-body'
        from packages.research.evidence.snapshot import seal_snapshot
        seal_snapshot(record.detail, phase='analysis', canonical_documents={})
    sent = []
    async def model(record, **kwargs):
        sent.append(kwargs)
        return {'coverage_gaps': [], 'gate_status': 'pass'}
    monkeypatch.setattr(service, '_trace_llm_json', model)
    await service._real_reflector_step(record)
    user = sent[0]['user']
    coverage = json.loads(user.split('Comparison Matrix JSON: ')[1].split('\nEvidence View JSON: ')[0])
    view = json.loads(user.split('\nEvidence View JSON: ')[1].split('\nAnalysis dependency gaps: ')[0])
    assert len(encoded(coverage).encode()) + len(encoded(view).encode()) <= record.detail.evidence_consumptions[-1].max_bytes
    if tamper is None:
        assert {c['competitor'] for c in coverage['cells']} == {'A', 'B', 'C', 'D'}
        assert coverage['producer_hash']
        assert any(c['omitted_fact_count'] > 0 for c in coverage['analysts'])
        assert not any('value' in c for c in coverage['cells'])  # Coverage is not unsent original fact text.
        assert record.detail.reflections[-1].gate_status == 'pass'
        assert not service._build_reflector_qa_issues(record.detail)
    else:
        assert not coverage['cells'] or 'A' not in {c['competitor'] for c in coverage['cells']}
        assert record.detail.reflections[-1].gate_status == 'block'


def test_summary_uses_chinese_structured_status_without_internal_diagnostics(monkeypatch):
    service, record = writer_fixture(monkeypatch)
    detail = record.detail
    diagnostics = [f"Not comparable: feature / operation.{i}; insufficient_evidence; {{'A': 'unknown'}}." for i in range(9)]
    assessment = ComparisonAssessment(status='insufficient_evidence', rationale='Comparison withheld: '+'; '.join(diagnostics), gaps=diagnostics)
    detail.comparison_matrix = ComparisonMatrix(competitors=['Notion'], dimensions=['feature'], operation_alignment=[
        {'operation': 'comment', 'comparison_status': 'insufficient_evidence', 'missing_products': ['Notion']}])
    report = render_dimension_report(detail, [], comparison_assessments={'feature': assessment})
    summary = report.split('## 执行摘要')[1].split('## 竞争发现')[0]
    assert '尚不能同口径比较' in summary and '评论' in summary
    assert len(summary) < 400
    assert 'Not comparable' not in report and 'Comparison withheld' not in report and '&#x27;' not in report
    assert assessment.gaps == diagnostics  # Complete diagnostics remain in the audit artifact.


def version(detail, markdown):
    return ReportVersionRecord(id='v', workspace_id='w', project_id='p', version_number=1,
        topic_normalized=detail.topic, competitor_set_hash='set', report_md=markdown,
        quality_metadata={'analysis_plan': detail.plan.model_dump(mode='json'), 'execution_mode': detail.execution_mode})


@pytest.mark.asyncio
async def test_dimension_preflight_and_release_share_substantive_contract(monkeypatch):
    service, record = writer_fixture(monkeypatch)
    monkeypatch.setattr(service, '_trace_llm_text', bound_model([]))
    report = await service._writer_dimension_report(record, 20)
    detail = record.detail
    assert run_writer_quality_preflight(detail, report).passed
    assert not _report_structure_issues(version(detail, report))
    assert not _report_depth_issues(version(detail, report))
    assert not _report_richness_issues(version(detail, report), competitors=[SimpleNamespace(), SimpleNamespace()], evidence=[], dimensions=['feature'])
    risk_heading = '## 置信度说明'
    no_risk = report.split(risk_heading)[0] + '\n## 证据附录\n- 官方文档 [source:source-Notion-feature]'
    no_sources = report.replace('[source:source-Notion-feature]', '')
    source_only = '## 执行摘要\n[source:x]\n## 竞争发现\n[source:x]\n## 置信度说明\n[source:x]\n## 证据附录\n[source:x]'
    for broken in ('', no_risk, no_sources, source_only):
        assert not run_writer_quality_preflight(detail, broken).passed
        assert _report_structure_issues(version(detail, broken))
    enterprise = version(detail, report).model_copy(update={'quality_metadata': {}})
    assert _report_structure_issues(enterprise)  # Full enterprise structure remains required.


def test_review_shared_references_losslessly_preserve_original_and_condition_groups():
    # Saved official-text excerpt; anonymous objects prevent product-specific shortcuts.
    quote = "If you're on a Team/Business or Enterprise plan, you can invite external users to your folders. You must have Can manage access to invite anyone, including external users."
    original = fact('Product A', quote, slot='review', qualifiers={'conditions': [quote]*8,
        'condition_groups': [{'operator': 'any_of', 'members': [quote, quote+' Parent access is also required.']}]})
    original = original.model_copy(update={'value_json': encoded([quote]*6)})
    claim = ReportClaim(id='review-c', text='外部用户访问文件夹需满足记录的套餐及权限前提。', kind='fact',
        competitor='Product A', dimension='feature', fact_ids=[original.id], source_ids=[original.source_id])
    payload = review_payload([claim], SimpleNamespace(facts=[original], sources=[]))
    full = encoded(payload)
    shared = compact_prompt_json(payload)
    assert len(shared.encode()) < len(full.encode()) * .55
    assert expand_text_refs(json.loads(shared)) == payload
    assert quote in shared


@pytest.mark.asyncio
async def test_four_product_first_review_uses_shared_complete_input_with_hard_budget(monkeypatch):
    from dataclasses import replace
    from packages.llm.doubao_client import LLMUsage
    from packages.research.evidence.snapshot import seal_snapshot
    service, record = four_branch_service()
    service._settings = replace(service._settings, run_llm_max_tokens=200000, run_llm_max_calls=60)
    record.detail.topic = record.detail.plan.topic = '比较四家产品的阅读、评论、编辑和分享权限操作'
    # Anonymous complete observation, with a large repeated captured condition.
    quote = 'Members on all plans can view documents. Members on all plans can comment on documents. Members on all plans can edit documents. Members on all plans can share documents. Only invited members with parent page access may use these permissions.'
    context = quote + ' The parent page remains restricted to invited workspace members.' * 16
    for source in record.detail.raw_sources:
        source.metadata['source_material_level'] = 'full_source'
        source.metadata['normalized_fields'] = [dict(kind='feature', competitor=source.competitor,
            dimension='feature', slot='edit', support_level='documented', evidence_quote=quote,
            evidence_terms=[quote, context], evidence_item_ids=['captured-'+source.id],
            qualifiers={'captured_conditions': [context]*6}, confidence=.9)]
    seal_snapshot(record.detail, phase='analysis', canonical_documents={})
    sent, unshared = [], []
    async def complete_text(*, system, user):
        payload = json.loads(user.split('\nJSON:\n')[1]); sent.append((system, payload))
        decoded = expand_text_refs(payload)
        if 'claims' in payload:
            assert 'Resolve every {text_ref: id} through text_sets' in system
            assert context in decoded['facts'][0]['value']
            assert decoded['facts'][0]['qualifiers']['captured_conditions'] == [context]*6
            unshared.append(len(encoded(decoded).encode()))
            return json.dumps({'reviews': [{'claim_id': c['id'], 'verdict': 'supported',
                'reason': 'The original edit operation and every parent access condition are preserved.'} for c in payload['claims']]})
        original = decoded['evidence_view']['facts'][0]
        names = {'read': '阅读', 'comment': '评论', 'edit': '编辑', 'share': '分享'}
        return json.dumps({'claims': [dict(text=f"所有套餐的成员获得父级页面访问后可{names[binding['operation']]}文档；父级页面仅限受邀工作区成员访问。",
            kind='fact', competitor=original['competitor'], dimension='feature', fact_ids=[original['id']],
            source_ids=[original['source_id']], observation_id=binding['observation_id'])
            for binding in original['operation_observations'] if binding['operation'] in names]})
    monkeypatch.setattr(service._llm, 'complete_text', complete_text)
    monkeypatch.setattr(service._llm, 'consume_last_usage', lambda: LLMUsage(prompt_tokens=1000, completion_tokens=200, total_tokens=1200))
    report = await service._writer_dimension_report(record, 20)
    assert len(sent) == 8
    reviews = [(system, payload) for system, payload in sent if 'claims' in payload]
    assert len(reviews) == 4 and all(size > 20000 for size in unshared), unshared
    assert all(len(encoded(payload).encode()) < original_size * .6
               for (_, payload), original_size in zip(reviews, unshared))
    assert all(any(c.status == 'supported' for c in audit.claims) for audit in record.detail.report_dimension_audits)
    budget = service._run_llm_budget(record)
    assert budget.max_tokens == 200000 and budget.max_calls <= 60 and budget.calls == 8
    assert budget.tokens_used == 9600
    assert all(budget.delivery_reserves[f'{agent}:{product}/feature'] > 0
               for product in record.detail.plan.competitors for agent in ('collector', 'analyst', 'writer', 'qa'))
    assert budget.delivery_reserves['comparator:run'] > 0 and budget.delivery_reserves['reflector:run'] > 0
    assert '父级页面仅限受邀工作区成员访问' in report


@pytest.mark.asyncio
async def test_reflector_rechecks_producer_credentials_after_model(monkeypatch):
    from dataclasses import replace
    from packages.orchestrator.evidence_context import EvidenceUseRejectedError
    service, record = four_branch_service()
    recorded_matrix(service, record)
    service._settings = replace(service._settings, run_llm_max_tokens=200000)
    async def model(record, **kwargs):
        record.detail.evidence_artifact_dependencies = [d.model_copy(update={'payload_hash': 'changed-during-model'})
            if d.kind == 'analyst' and d.competitor == 'A' else d for d in record.detail.evidence_artifact_dependencies]
        return {'coverage_gaps': [], 'gate_status': 'pass'}
    monkeypatch.setattr(service, '_trace_llm_json', model)
    with pytest.raises(EvidenceUseRejectedError, match='producer coverage changed'):
        await service._real_reflector_step(record)
    assert not record.detail.reflections


@pytest.mark.asyncio
async def test_coverage_digest_capacity_is_not_a_missing_matrix_or_collection_redo(monkeypatch):
    from dataclasses import replace
    service, record = four_branch_service()
    recorded_matrix(service, record)
    service._settings = replace(service._settings, run_llm_max_tokens=200000)
    original = service._producer_coverage_digest
    monkeypatch.setattr(service, '_producer_coverage_digest', lambda record, view, **kw: original(record, view, max_bytes=256))
    async def model(record, **kwargs):
        return {'coverage_gaps': [], 'gate_status': 'pass'}
    monkeypatch.setattr(service, '_trace_llm_json', model)
    await service._real_reflector_step(record)
    assert record.detail.reflections[-1].gate_status == 'warn'
    assert not service._build_reflector_qa_issues(record.detail)
    assert any('capacity' in text for text in record.detail.reflections[-1].writer_constraints)


@pytest.mark.asyncio
async def test_writer_cannot_cite_authorized_but_unsent_original_fact(monkeypatch):
    import packages.agents.writer.dimension_writer as writer
    service, record = writer_fixture(monkeypatch)
    original = next(f for f in service._current_evidence_snapshot(record).facts if f.field == 'evidence_terms')
    select = writer.compact_dimension_context
    def omit(*args, **kwargs):
        payload, _ = select(*args, **kwargs)
        payload['evidence_view']['facts'] = []
        payload.pop('requested_operations', None)
        return payload, True
    monkeypatch.setattr(writer, 'compact_dimension_context', omit)
    calls = []
    async def model(record, **kwargs):
        calls.append(kwargs)
        assert not json.loads(kwargs['user'].split('\nJSON:\n')[1])['evidence_view']['facts']
        return json.dumps({'claims': [dict(text='成员可以评论页面。', kind='fact', competitor='Notion',
            dimension='feature', fact_ids=[original.id], source_ids=[original.source_id])]})
    monkeypatch.setattr(service, '_trace_llm_text', model)
    report = await service._writer_dimension_report(record, 20)
    assert len(calls) == 1 and '成员可以评论页面。' not in report
    assert 'claim_candidate_invalid' in record.detail.report_dimension_audits[0].gaps
    assert 'claim_generation_unavailable' not in record.detail.report_dimension_audits[0].gaps
    audit_trace = next(s for s in record.detail.trace_spans if s.name == 'dimension_claim_audit')
    assert json.loads(audit_trace.metadata['writer_fact_ids_json']) == []
    assert audit_trace.metadata['writer_context_bytes'] > 0
    assert audit_trace.metadata['evidence_view_bytes'] > audit_trace.metadata['writer_context_bytes']


def test_coverage_reference_cannot_cross_product_source_scope():
    from dataclasses import replace
    service, record = four_branch_service()
    recorded_matrix(service, record)
    record.detail.comparison_matrix.cells[0].source_ids = ['source-B']
    _, use = service._begin_evidence_use(record, agent='comparator')
    service._validate_evidence_use(record, use)
    service._record_evidence_artifact(record, kind='comparator', uses=[use],
        payload=service._comparator_evidence_artifact_payload(record.detail))
    service._settings = replace(service._settings, run_llm_max_tokens=200000)
    view, use = service._begin_evidence_use(record, agent='reflector')
    digest = service._producer_coverage_digest(record, view, max_bytes=8000)
    assert 'A' not in {cell['competitor'] for cell in digest['cells']}


@pytest.mark.asyncio
@pytest.mark.parametrize('broken', ['missing_cell', 'uncited_cell'])
async def test_digest_capacity_keeps_real_matrix_coverage_failures(monkeypatch, broken):
    from dataclasses import replace
    service, record = four_branch_service()
    recorded_matrix(service, record)
    if broken == 'missing_cell':
        record.detail.comparison_matrix.cells.pop()
    else:
        record.detail.comparison_matrix.cells[-1].source_ids = []
    _, use = service._begin_evidence_use(record, agent='comparator')
    service._validate_evidence_use(record, use)
    service._record_evidence_artifact(record, kind='comparator', uses=[use],
        payload=service._comparator_evidence_artifact_payload(record.detail))
    service._settings = replace(service._settings, run_llm_max_tokens=200000)
    original = service._producer_coverage_digest
    monkeypatch.setattr(service, '_producer_coverage_digest', lambda record, view, **kw: original(record, view, max_bytes=256))
    async def model(record, **kwargs):
        return {'coverage_gaps': [], 'gate_status': 'pass'}
    monkeypatch.setattr(service, '_trace_llm_json', model)
    await service._real_reflector_step(record)
    assert record.detail.reflections[-1].gate_status == 'block'
    assert record.detail.reflections[-1].blocking_gaps
    assert service._build_reflector_qa_issues(record.detail)


@pytest.mark.asyncio
@pytest.mark.parametrize('execution_mode', ['demo', None])
async def test_release_requires_explicit_real_mode_for_compact_contract(monkeypatch, execution_mode):
    service, record = writer_fixture(monkeypatch)
    monkeypatch.setattr(service, '_trace_llm_text', bound_model([]))
    report = await service._writer_dimension_report(record, 20)
    record.detail.plan.research_depth = 'standard'
    report_version = version(record.detail, report)
    report_version.quality_metadata['execution_mode'] = execution_mode
    assert _report_structure_issues(report_version)
    if execution_mode == 'demo':
        record.detail.execution_mode = 'demo'
        assert not run_writer_quality_preflight(record.detail, report).passed


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['low_confidence', 'fact_blocker', 'coverage_blocker', 'cross_blocker'])
async def test_digest_capacity_preserves_confidence_and_non_matrix_blockers(monkeypatch, failure):
    from dataclasses import replace
    service, record = four_branch_service()
    recorded_matrix(service, record)
    if failure == 'low_confidence':
        record.detail.comparison_matrix.cells[-1].confidence = .2
        _, use = service._begin_evidence_use(record, agent='comparator')
        service._validate_evidence_use(record, use)
        service._record_evidence_artifact(record, kind='comparator', uses=[use],
            payload=service._comparator_evidence_artifact_payload(record.detail))
    service._settings = replace(service._settings, run_llm_max_tokens=200000)
    original = service._producer_coverage_digest
    monkeypatch.setattr(service, '_producer_coverage_digest', lambda record, view, **kw: original(record, view, max_bytes=256))
    async def model(record, **kwargs):
        if failure == 'low_confidence':
            return {'coverage_gaps': [], 'gate_status': 'pass'}
        field = {'fact_blocker': 'blocking_gaps', 'coverage_blocker': 'coverage_gaps',
                 'cross_blocker': 'cross_competitor_gaps'}[failure]
        return {field: ['A captured observation has no source_ids.'],
                'gate_status': 'block' if failure == 'fact_blocker' else 'pass'}
    monkeypatch.setattr(service, '_trace_llm_json', model)
    await service._real_reflector_step(record)
    reflection = record.detail.reflections[-1]
    if failure == 'low_confidence':
        assert reflection.confidence_outliers
    else:
        assert reflection.gate_status == 'block' and reflection.blocking_gaps == ['A captured observation has no source_ids.']
    assert service._build_reflector_qa_issues(record.detail)


@pytest.mark.asyncio
@pytest.mark.parametrize('capacity', [False, True])
@pytest.mark.parametrize('receipt_scope', ['other_product_analyst', 'other_product_writer', 'same_product_writer', 'other_dimension_analyst'])
async def test_producer_digest_requires_analyst_receipt_in_its_exact_scope(monkeypatch, capacity, receipt_scope):
    from dataclasses import replace
    service, record = four_branch_service()
    recorded_matrix(service, record)
    if receipt_scope == 'other_product_analyst':
        replacement = next(d for d in record.detail.evidence_artifact_dependencies
            if d.kind == 'analyst' and d.competitor == 'B').consumption_ids
    else:
        product = 'B' if receipt_scope == 'other_product_writer' else 'A'
        agent = 'analyst' if receipt_scope == 'other_dimension_analyst' else 'writer'
        dimension = 'pricing' if receipt_scope == 'other_dimension_analyst' else 'feature'
        _, use = service._begin_evidence_use(record, agent=agent, competitor=product, dimension=dimension)
        service._validate_evidence_use(record, use)
        replacement = (use.id,)
    record.detail.evidence_artifact_dependencies = [d.model_copy(update={'consumption_ids': replacement})
        if d.kind == 'analyst' and d.competitor == 'A' else d for d in record.detail.evidence_artifact_dependencies]
    record.detail.comparison_matrix.cells[0].source_ids = ['source-B' if receipt_scope.startswith('other_product') else 'source-A']
    _, use = service._begin_evidence_use(record, agent='comparator')
    service._validate_evidence_use(record, use)
    service._record_evidence_artifact(record, kind='comparator', uses=[use],
        payload=service._comparator_evidence_artifact_payload(record.detail))
    service._settings = replace(service._settings, run_llm_max_tokens=200000)
    if capacity:
        digest = service._producer_coverage_digest
        monkeypatch.setattr(service, '_producer_coverage_digest', lambda record, view, **kw: digest(record, view, max_bytes=256))
    sent = []
    async def model(record, **kwargs):
        sent.append(kwargs['user'])
        return {'coverage_gaps': [], 'gate_status': 'pass'}
    monkeypatch.setattr(service, '_trace_llm_json', model)
    await service._real_reflector_step(record)
    coverage = json.loads(sent[0].split('Comparison Matrix JSON: ')[1].split('\nEvidence View JSON: ')[0])
    if capacity:
        assert coverage['unavailable_count'] == 1
    else:
        assert next(a for a in coverage['analysts'] if a['competitor'] == 'A')['status'] == 'dependency_unavailable'
        assert 'A' not in {c['competitor'] for c in coverage['cells']}
    assert record.detail.reflections[-1].gate_status == 'block'
    assert any(issue.severity == 'blocker' for issue in service._build_reflector_qa_issues(record.detail))


@pytest.mark.asyncio
@pytest.mark.parametrize('field', ['coverage_gaps', 'cross_competitor_gaps', None])
async def test_capacity_preserves_explicit_nonstructural_block_without_blocking_gaps(monkeypatch, field):
    from dataclasses import replace
    service, record = four_branch_service()
    recorded_matrix(service, record)
    service._settings = replace(service._settings, run_llm_max_tokens=200000)
    digest = service._producer_coverage_digest
    monkeypatch.setattr(service, '_producer_coverage_digest', lambda record, view, **kw: digest(record, view, max_bytes=256))
    async def model(record, **kwargs):
        payload = {'gate_status': 'block', 'coverage_gaps': []}
        if field:
            payload[field] = ['A source assertion requires unresolved provenance review.']
        return payload
    monkeypatch.setattr(service, '_trace_llm_json', model)
    await service._real_reflector_step(record)
    reflection = record.detail.reflections[-1]
    assert reflection.gate_status == 'block'
    assert reflection.blocking_gaps
    assert any(issue.severity == 'blocker' for issue in service._build_reflector_qa_issues(record.detail))


@pytest.mark.asyncio
async def test_capacity_never_reclassifies_an_explicit_model_matrix_block(monkeypatch):
    from dataclasses import replace
    service, record = four_branch_service()
    recorded_matrix(service, record)
    service._settings = replace(service._settings, run_llm_max_tokens=200000)
    digest = service._producer_coverage_digest
    monkeypatch.setattr(service, '_producer_coverage_digest', lambda record, view, **kw: digest(record, view, max_bytes=256))
    async def model(record, **kwargs):
        return {'coverage_gaps': ['Comparison matrix is missing before writing.'], 'gate_status': 'block'}
    monkeypatch.setattr(service, '_trace_llm_json', model)
    await service._real_reflector_step(record)
    assert record.detail.reflections[-1].gate_status == 'block'
    assert any(issue.severity == 'blocker' for issue in service._build_reflector_qa_issues(record.detail))


@pytest.mark.asyncio
async def test_capacity_local_fallback_uses_verified_counts_without_projection_gaps(monkeypatch):
    from dataclasses import replace
    service, record = four_branch_service()
    recorded_matrix(service, record)
    service._settings = replace(service._settings, run_llm_max_tokens=200000)
    digest = service._producer_coverage_digest
    monkeypatch.setattr(service, '_producer_coverage_digest', lambda record, view, **kw: digest(record, view, max_bytes=256))
    async def model(record, **kwargs):
        raise RuntimeError('offline forced fallback')
    monkeypatch.setattr(service, '_trace_llm_json', model)
    await service._real_reflector_step(record)
    assert record.detail.reflections[-1].gate_status == 'warn'
    assert not record.detail.reflections[-1].blocking_gaps
    assert not service._build_reflector_qa_issues(record.detail)
