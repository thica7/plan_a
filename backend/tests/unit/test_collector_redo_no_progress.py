"""Collector refresh must prove progress before discarding accepted producer work."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_writer_artifact_consumption import writer_fixture, record_upstream
from test_run_service import _segmented_writer_service, _segmented_writer_record

from packages.orchestrator.graph import build_scoped_redo_graph
from packages.research.evidence.snapshot import current_snapshot
from packages.schema.models import RedoScope, DecisionBrief, QCIssue


def accepted_report(monkeypatch):
    service, record = writer_fixture(monkeypatch)
    record_upstream(service, record)
    record.detail.report_md = 'Accepted reviewed report with original conditions.'
    record.detail.qa_findings = [QCIssue(id='missing-coda', severity='blocker',
        detected_by='coverage', target_agent='collector', field_path='coverage',
        problem='Coda operation remains unverified.', redo_scope=RedoScope(kind='collector',
            target_subagent='feature', target_competitors=['Coda'], rationale='Missing evidence.'))]
    _, use = service._begin_evidence_use(record, agent='writer')
    service._validate_evidence_use(record, use)
    service._record_evidence_artifact(record, kind='writer', uses=[use],
        payload=service._writer_evidence_artifact_payload(record.detail))
    return service, record


def prepare(service, record):
    return service._prepare_redo_scope_inputs(record.detail, RedoScope(
        kind='collector', target_subagent='feature', target_competitors=['Notion'],
        rationale='Find missing permission evidence.'))


def test_redo_preparation_keeps_accepted_sources_and_producers(monkeypatch):
    service, record = accepted_report(monkeypatch)
    before = record.detail.model_copy(deep=True)
    prepare(service, record)
    for key in ('raw_sources', 'evidence_retired_source_ids', 'competitor_knowledge',
                'comparison_matrix', 'reflections', 'report_md', 'evidence_artifact_dependencies'):
        assert getattr(record.detail, key) == getattr(before, key), key


@pytest.mark.asyncio
async def test_noop_collector_graph_preserves_facts_report_and_skips_paid_downstream(monkeypatch):
    service, record = accepted_report(monkeypatch)
    before = current_snapshot(record.detail)
    report = record.detail.report_md
    dependencies = list(record.detail.evidence_artifact_dependencies)
    blockers = list(record.detail.qa_findings)
    prepare(service, record)
    async def nothing(*args, **kwargs): pass
    async def phase_qa(*args, **kwargs): record.detail.qa_findings = []
    async def collect(*args, **kwargs):
        source = record.detail.raw_sources[0].model_copy(deep=True)
        source.id = 'new-capture-id'
        record.detail.raw_sources.append(source)
    async def join(*args, **kwargs):
        record.detail.raw_sources = service._normalize_collected_sources(record.detail, ['feature'])
    async def forbidden(*args, **kwargs): raise AssertionError('No-progress redo spent downstream work')
    for name in ('_real_collector_dispatch_step', '_run_survey_interview_enrichment'):
        monkeypatch.setattr(service, name, nothing)
    monkeypatch.setattr(service, '_real_phase_qa_step', phase_qa)
    monkeypatch.setattr(service, '_real_collector_branch_step', collect)
    monkeypatch.setattr(service, '_real_collect_join_step', join)
    for name in ('_real_analyst_dispatch_step', '_real_analyst_branch_step', '_real_comparator_step',
                 '_real_reflector_step', '_real_writer_step', '_real_qa_step'):
        monkeypatch.setattr(service, name, forbidden)
    record.detail.plan.collaboration_mode = 'ai'
    record.detail.hitl_enabled = False
    await build_scoped_redo_graph(service).ainvoke({'run_id': record.detail.id,
        'dimensions': ['feature'], 'target_competitors': ['Notion'], 'redo_kind': 'collector'})
    assert current_snapshot(record.detail) == before
    assert current_snapshot(record.detail).facts == before.facts
    assert record.detail.report_md == report
    assert record.detail.qa_findings == blockers
    assert not record.pending_interrupts
    assert record.detail.evidence_artifact_dependencies == dependencies
    assert any(e.payload.get('outcome') == 'no_new_evidence' for e in record.events)
    assert service._evidence_artifact_valid(record, kind='writer',
        payload=service._writer_evidence_artifact_payload(record.detail))
    await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['content_hash', 'role', 'version', 'scope', 'retired', 'producer'])
async def test_changed_evidence_or_invalid_producer_cannot_take_noop(monkeypatch, change):
    service, record = accepted_report(monkeypatch)
    before = current_snapshot(record.detail)
    prepare(service, record)
    source = record.detail.raw_sources[0]
    if change == 'content_hash': source.content_hash = 'corrected-body'
    elif change == 'role': source.source_type = 'report'
    elif change == 'version': source.metadata['kb_document_version'] = 99
    elif change == 'scope': source.competitor = 'Unplanned Product'
    elif change == 'retired': record.detail.evidence_retired_source_ids.append(source.id)
    else:
        record.detail.evidence_artifact_dependencies = [d.model_copy(update={'payload_hash': 'invalid'})
            if d.kind == 'writer' else d for d in record.detail.evidence_artifact_dependencies]
    await service._prepare_evidence_snapshot(record, phase='collect')
    await service._prepare_evidence_snapshot(record, phase='analysis')
    assert not getattr(record, 'collector_redo_no_new_evidence', False)
    if change != 'producer': assert current_snapshot(record.detail).id != before.id
    await service._graph_checkpointer.aclose()


def test_retired_duplicate_cannot_win_over_new_active_source(monkeypatch):
    service, record = accepted_report(monkeypatch)
    old = record.detail.raw_sources[0]
    record.detail.evidence_retired_source_ids.append(old.id)
    new = old.model_copy(update={'id': 'new-admitted-source'})
    record.detail.raw_sources.append(new)
    normalized = service._normalize_collected_sources(record.detail, ['feature'])
    assert new.id in {s.id for s in normalized}
    assert old.id in record.detail.evidence_retired_source_ids


@pytest.mark.asyncio
async def test_saved_hardware_contract_retry_uses_validated_opportunity_hypothesis(monkeypatch):
    fixture = json.loads((Path(__file__).parents[1] / 'fixtures/hardware_product_opportunities_retry.json').read_text())
    service = _segmented_writer_service()
    record = _segmented_writer_record(service, competitors=fixture['competitors'])
    record.detail.topic = fixture['topic']
    record.detail.output_language = fixture['output_language']
    record.detail.plan.decision_brief = DecisionBrief.model_validate(fixture['decision_brief'])
    outputs = iter(fixture['outputs'])
    async def generate(*args, **kwargs): return next(outputs)
    monkeypatch.setattr(service, '_writer_segment_markdown', generate)
    monkeypatch.setattr(service, '_sanitize_writer_segment_citations', lambda pack, markdown, **kwargs: markdown)
    pack = SimpleNamespace(validate_segment_citations=lambda *args, **kwargs: [])
    markdown, contract = await service._writer_validated_segment_markdown(record,
        evidence_pack_result=pack, segment={'segment_name': 'product_opportunities',
            'section_id': 'product_opportunities', 'segment_kind': 'section_fragment',
            'output_language': fixture['output_language'], 'researched_competitors': fixture['competitors'],
            'allowed_source_ids': []}, timeout_seconds=10, language_guidance='', memory_context='',
        layer_context='', required_sections='')
    from packages.agents.writer.segment_contract import validate_segment_contract
    assert markdown == '\n'.join(service._backfill_product_opportunities_section(record.detail)).strip()
    assert validate_segment_contract(markdown, contract).status == 'pass'
    assert not service._writer_segment_publication_hygiene_errors(markdown)
    assert not service._writer_segment_truncation_error(markdown)


def test_failed_refresh_cannot_raise_freshness(monkeypatch):
    service, record = accepted_report(monkeypatch)
    old = record.detail.raw_sources[0]
    old.metadata['fetched_at'] = '2026-10-03T00:00:00Z'
    failed = old.model_copy(deep=True)
    failed.id = 'failed-refresh'
    failed.failure_reason = 'timeout'
    failed.metadata['fetched_at'] = '2026-10-05T00:00:00Z'
    record.detail.evidence_refresh_active = True
    record.detail.raw_sources.append(failed)
    normalized = service._normalize_collected_sources(record.detail, ['feature'])
    assert normalized[0].metadata['fetched_at'] == '2026-10-03T00:00:00Z'


@pytest.mark.asyncio
async def test_new_admitted_body_supersedes_old_facts(monkeypatch):
    service, record = accepted_report(monkeypatch)
    before = current_snapshot(record.detail)
    prepare(service, record)
    old = record.detail.raw_sources[0]
    new = old.model_copy(deep=True)
    new.id = 'corrected-captured-source'
    new.content_hash = 'corrected-content-hash'
    new.fetch_method = 'basic_httpx'
    new.metadata.update(captured_page_id='capture-corrected', capture_content_hash='captured-body-hash',
                        fetched_at='2026-10-03T00:01:00Z')
    for row in new.metadata['normalized_fields']:
        row['evidence_quote'] = row['evidence_terms'][0] = 'Only workspace administrators can comment.'
    record.detail.raw_sources.append(new)
    record.detail.evidence_inputs_dirty = True
    await service._prepare_evidence_snapshot(record, phase='collect')
    after = await service._prepare_evidence_snapshot(record, phase='analysis')
    assert old.id not in {fact.source_id for fact in after.facts}
    assert new.id in {fact.source_id for fact in after.facts}
    assert old.id in record.detail.evidence_retired_source_ids
    assert not record.collector_redo_no_new_evidence
    assert record.detail.evidence_writer_rewrite_required
    assert before.facts
    await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('canonical_change', [None, 'archived', 'version', 'role', 'scope', 'hash'])
async def test_kb_alias_requires_current_canonical_record(tmp_path, monkeypatch, canonical_change):
    from test_evidence_snapshot_scope import seed_reference, attach
    from packages.knowledge.repository import KnowledgeRepository
    service, record = writer_fixture(monkeypatch)
    source = record.detail.raw_sources[0]
    doc = await seed_reference(tmp_path, monkeypatch, overrides={
        'competitor': source.competitor, 'dimension': source.dimension,
        'url': str(source.url), 'content_hash': source.content_hash,
        'metadata': {'source_material_level': 'full_source'},
    })
    attach(record.detail, doc)
    source.metadata.update(kb_document_workspace_id=doc.workspace_id,
                           kb_document_project_id=doc.project_id)
    await service._prepare_evidence_snapshot(record, phase='analysis')
    record_upstream(service, record)
    record.detail.report_md = 'Accepted canonical report.'
    _, use = service._begin_evidence_use(record, agent='writer')
    service._validate_evidence_use(record, use)
    service._record_evidence_artifact(record, kind='writer', uses=[use],
        payload=service._writer_evidence_artifact_payload(record.detail))
    before = current_snapshot(record.detail)
    prepare(service, record)
    retrieved = source.model_copy(deep=True)
    retrieved.id = 'kb-retrieved-chunk-alias'
    retrieved.covered_competitors = []
    retrieved.confidence = .5
    retrieved.snippet = 'Short KB chunk with no normalized extraction.'
    retrieved.candidate_origin = 'rag_kb'
    retrieved.fetch_method = 'rag_kb_retrieve'
    retrieved.metadata.pop('normalized_fields')
    retrieved.metadata.update(kb_retrieved=True, source_material_level='kb_retrieval_chunk',
                              kb_document_status='active', kb_source_role='source')
    record.detail.raw_sources.append(retrieved)
    record.detail.raw_sources = service._normalize_collected_sources(record.detail, ['feature'])
    assert record.detail.raw_sources == [source]
    # Mutate the actual canonical SQLite record after retrieval; no stubs bypass
    # repository access, scope filtering, version/hash/status or chunk validation.
    if canonical_change:
        updates = {'archived': ("status = 'archived', is_active = 0", []),
            'version': ('version = version + 1', []),
            'role': ("source_role = 'historical_report'", []),
            'scope': ("workspace_id = 'different-workspace'", []),
            'hash': ("content_hash = 'corrected-canonical-hash'", [])}
        sql, values = updates[canonical_change]
        async with KnowledgeRepository() as repo:
            await repo._db.execute(f'UPDATE documents SET {sql} WHERE id = ?', [*values, doc.id])
            await repo._db.commit()
    await service._prepare_evidence_snapshot(record, phase='collect')
    after = await service._prepare_evidence_snapshot(record, phase='analysis')
    assert record.collector_redo_no_new_evidence is (canonical_change is None)
    if canonical_change is None:
        assert after == before
        assert service._evidence_artifact_valid(record, kind='writer',
            payload=service._writer_evidence_artifact_payload(record.detail))
    else:
        assert after.id != before.id
        assert record.detail.evidence_writer_rewrite_required
    await service._graph_checkpointer.aclose()


def test_collect_phase_retry_keeps_accepted_producers_until_sealing(monkeypatch):
    service, record = accepted_report(monkeypatch)
    prepare(service, record)
    before = record.detail.model_copy(deep=True)
    assert service._route_phase_qa({'run_id': record.detail.id, 'collect_qa_attempts': 0}, 'collect') == 'retry'
    for key in ('raw_sources', 'competitor_knowledge', 'comparison_matrix', 'reflections'):
        assert getattr(record.detail, key) == getattr(before, key), key


@pytest.mark.asyncio
async def test_missing_analyst_producer_cannot_take_noop(monkeypatch):
    service, record = accepted_report(monkeypatch)
    prepare(service, record)
    record.detail.evidence_artifact_dependencies = [d for d in record.detail.evidence_artifact_dependencies if d.kind != 'analyst']
    await service._prepare_evidence_snapshot(record, phase='collect')
    await service._prepare_evidence_snapshot(record, phase='analysis')
    assert not record.collector_redo_no_new_evidence
    await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('section', ['decision_summary', 'competitor_deep_dives'])
async def test_other_invalid_writer_sections_still_fail_closed(monkeypatch, section):
    service = _segmented_writer_service()
    record = _segmented_writer_record(service)
    async def generate(*args, **kwargs): return '## Unrelated section\nThis content cannot satisfy the requested section.'
    monkeypatch.setattr(service, '_writer_segment_markdown', generate)
    pack = SimpleNamespace(validate_segment_citations=lambda *args, **kwargs: [])
    with pytest.raises(RuntimeError, match='heading contract after retry'):
        await service._writer_validated_segment_markdown(record, evidence_pack_result=pack,
            segment={'segment_name': section, 'section_id': section, 'segment_kind': 'section_fragment',
                'output_language': 'en-US', 'allowed_source_ids': []}, timeout_seconds=10,
            language_guidance='', memory_context='', layer_context='', required_sections='')


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['heading', 'citation', 'hygiene', 'truncation'])
async def test_opportunity_fallback_keeps_all_validation_gates(monkeypatch, failure):
    fixture = json.loads((Path(__file__).parents[1] / 'fixtures/hardware_product_opportunities_retry.json').read_text())
    service = _segmented_writer_service()
    record = _segmented_writer_record(service, competitors=fixture['competitors'])
    record.detail.output_language = fixture['output_language']
    record.detail.plan.decision_brief = DecisionBrief.model_validate(fixture['decision_brief'])
    outputs = iter(fixture['outputs'])
    async def generate(*args, **kwargs): return next(outputs)
    monkeypatch.setattr(service, '_writer_segment_markdown', generate)
    monkeypatch.setattr(service, '_sanitize_writer_segment_citations', lambda pack, markdown, **kwargs: markdown)
    good = '\n'.join(service._backfill_product_opportunities_section(record.detail)).strip()
    fallback = {'heading': '## Unrelated\nMissing opportunity contract.',
        'citation': good + ' [source:unallowed]', 'hygiene': good + '\nSegment Evidence Pack JSON',
        'truncation': good + '\n| incomplete |'}[failure]
    monkeypatch.setattr(service, '_backfill_product_opportunities_section', lambda detail: [fallback])
    original_truncation = service._writer_segment_truncation_error
    if failure == 'truncation':
        monkeypatch.setattr(service, '_writer_segment_truncation_error',
            lambda markdown: 'incomplete test fallback' if markdown == fallback else original_truncation(markdown))
    pack = SimpleNamespace(validate_segment_citations=lambda markdown, **kwargs:
        ['unallowed'] if '[source:unallowed]' in markdown else [])
    with pytest.raises(RuntimeError, match='heading contract after retry'):
        await service._writer_validated_segment_markdown(record, evidence_pack_result=pack,
            segment={'segment_name': 'product_opportunities', 'section_id': 'product_opportunities',
                'segment_kind': 'section_fragment', 'output_language': fixture['output_language'],
                'researched_competitors': fixture['competitors'], 'allowed_source_ids': []},
            timeout_seconds=10, language_guidance='', memory_context='', layer_context='', required_sections='')


@pytest.mark.asyncio
async def test_noop_retains_actual_validated_claim_audits(monkeypatch):
    from test_writer_artifact_consumption import bound_model
    service, record = writer_fixture(monkeypatch)
    record_upstream(service, record)
    calls = []
    monkeypatch.setattr(service, '_trace_llm_text', bound_model(calls))
    await service._real_writer_step(record)
    assert record.detail.report_dimension_audits
    assert any(item.status == 'supported' for audit in record.detail.report_dimension_audits for item in audit.claims)
    report = record.detail.report_md
    audits = list(record.detail.report_dimension_audits)
    paid_before = len(calls)
    snapshot = current_snapshot(record.detail)
    prepare(service, record)
    record.detail.raw_sources.append(record.detail.raw_sources[0].model_copy(update={'id': 'same-body-capture'}))
    record.detail.raw_sources = service._normalize_collected_sources(record.detail, ['feature'])
    await service._prepare_evidence_snapshot(record, phase='collect')
    after = await service._prepare_evidence_snapshot(record, phase='analysis')
    assert record.collector_redo_no_new_evidence
    assert after == snapshot
    assert record.detail.report_dimension_audits == audits
    assert record.detail.report_md == report
    assert len(calls) == paid_before
    await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_noop_marker_is_not_reused_without_a_new_proof(monkeypatch):
    service, record = accepted_report(monkeypatch)
    prepare(service, record)
    await service._prepare_evidence_snapshot(record, phase='collect')
    await service._prepare_evidence_snapshot(record, phase='analysis')
    assert record.collector_redo_no_new_evidence
    assert record.collector_redo_snapshot_id is None
    await service._prepare_evidence_snapshot(record, phase='analysis')
    assert not record.collector_redo_no_new_evidence
    await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_historical_report_cannot_retire_valid_primary(monkeypatch):
    service, record = accepted_report(monkeypatch)
    old = record.detail.raw_sources[0]
    prepare(service, record)
    new = old.model_copy(deep=True)
    new.id = 'new-historical-report-same-url'
    new.content_hash = 'historical-report-body'
    new.source_type = 'report'
    new.fetch_method = 'basic_httpx'
    new.metadata.update(captured_page_id='capture-history', capture_content_hash='history-body',
                        fetched_at='2026-10-03T00:01:00Z', source_material_level='historical_report')
    record.detail.raw_sources.append(new)
    await service._prepare_evidence_snapshot(record, phase='collect')
    after = await service._prepare_evidence_snapshot(record, phase='analysis')
    await service._graph_checkpointer.aclose()
    assert old.id not in record.detail.evidence_retired_source_ids
    assert old.id in {s.id for s in after.sources}

@pytest.mark.asyncio
async def test_canonical_historical_report_cannot_retire_primary(monkeypatch, tmp_path):
    from test_evidence_snapshot_scope import seed_reference
    service, record = accepted_report(monkeypatch)
    old = record.detail.raw_sources[0]
    doc = await seed_reference(tmp_path, monkeypatch, overrides={
        'competitor': old.competitor, 'dimension': old.dimension,
        'url': str(old.url), 'content_hash': 'historical-canonical-hash',
        'source_role': 'historical_report', 'source_type': 'report',
        'workspace_id': record.detail.workspace_id, 'project_id': record.detail.project_id,
        'metadata': {'source_material_level': 'historical_report'},
    })
    prepare(service, record)
    new = old.model_copy(deep=True)
    new.id = 'canonical-historical-report-same-url'
    new.content_hash = doc.content_hash
    new.source_type = 'report'
    new.candidate_origin = 'rag_kb'
    new.fetch_method = 'rag_kb_retrieve'
    new.metadata.update(kb_document_id=doc.id, kb_document_version=doc.version,
        kb_document_content_hash=doc.content_hash, kb_source_role='historical_report',
        kb_retrieved=True, source_material_level='historical_report')
    record.detail.raw_sources.append(new)
    record.detail.raw_sources = service._normalize_collected_sources(record.detail, ['feature'])
    await service._prepare_evidence_snapshot(record, phase='collect')
    after = await service._prepare_evidence_snapshot(record, phase='analysis')
    await service._graph_checkpointer.aclose()
    assert old.id not in record.detail.evidence_retired_source_ids
    assert old.id in {s.id for s in after.sources}
