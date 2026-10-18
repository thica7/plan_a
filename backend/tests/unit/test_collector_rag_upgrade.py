"""A verified, empty RAG warm start can yield its slot to current captured facts."""
import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

import test_question_semantic_focus as source_fixtures
from test_billing_rule_context import source_table
from test_collector_knowledge_scope import service_and_detail
from packages.agents import SubagentContext
from packages.knowledge.repository import KnowledgeRepository
from packages.orchestrator.service import RunRecord
from packages.research.capture.official import verify_registered_capture
from packages.research.evidence.admission import admit_evidence_items, raw_sources_from_research_result
from packages.research.evidence.normalization import normalized_fields_from_evidence_items
from packages.research.extraction.semantic import semantic_extraction
from packages.research.models import ResearchResult
from packages.tools import rag_retrieve
from packages.tools.evidence_fetch import EvidenceFetchResult

source = source_fixtures.source


def result_for(brief, candidate, page, quotes):
    extraction = semantic_extraction(brief, page, {'facts': [{'quote': q} for q in quotes]})
    items = admit_evidence_items([extraction], brief=brief, captured_pages=[page], candidates=[candidate])
    assert len(items) == len(quotes) and all(item.status == 'accepted' for item in items)
    return ResearchResult(brief=brief, candidates=[candidate], captured_pages=[page],
        extractions=[extraction], evidence_items=items, normalized_fields=normalized_fields_from_evidence_items(items))


def convert(brief, result, batch=(), target=1, **kwargs):
    return raw_sources_from_research_result(brief, result, batch_sources=list(batch),
        target_source_count=target, requires_accepted_evidence=True,
        source_exists=lambda *_: False, confidence_for_source=lambda *_: .9,
        fallback_snippet=lambda p: p.text, **kwargs)


@pytest.fixture
async def upgrade(source, tmp_path, monkeypatch, request):
    table, header, row, notes = source_table()
    first = 'Members can edit shared documents on all plans.'
    body = first + '\n' + table
    brief, candidate, page = source(body, questions=('Can members edit documents, and what are the Usage billing rules for requests and CPU time?',))
    candidate.title += getattr(request, 'param', '')
    page.title = candidate.title
    page.metadata['official_source_verification'] = verify_registered_capture(brief.competitor, page)
    service, detail = service_and_detail(market='')
    detail.id, detail.topic = brief.run_id, brief.topic
    detail.plan.competitors = [brief.competitor]
    detail.plan.target_product.name = brief.competitor
    monkeypatch.setenv('KB_DB_PATH', str(tmp_path / 'upgrade.db'))
    monkeypatch.setenv('KB_SEMANTIC_INDEXING', 'false')
    monkeypatch.setattr(service, '_research_brief', lambda *_: brief)
    record = RunRecord(detail=detail)
    service._runs[detail.id] = record
    context = SubagentContext(run_id=detail.id, agent='collector', subagent=f'{brief.competitor}/feature')
    initial = result_for(brief, candidate, page, [first])
    previous = convert(brief, initial)[0]
    await service._persist_captured_sources_to_kb(record, detail, [previous], initial, context)
    assert previous.metadata['kb_full_source_ingest_status'] == 'stored'
    async with KnowledgeRepository() as repo:
        doc = await repo.get_document(previous.metadata['kb_document_id'])
        chunks = await repo.get_chunks_for_document(doc.id)
    hit = dict(document_id=doc.id, chunk_id=chunks[0].id, text=doc.text, url=doc.url,
        title=doc.title, source_type=doc.source_type, content_hash=doc.content_hash,
        document_version=doc.version, workspace_id=doc.workspace_id, project_id=doc.project_id,
        competitor=doc.competitor, dimension=doc.dimension, market=doc.market,
        source_role=doc.source_role, fetched_at=doc.fetched_at.isoformat(), metadata=doc.metadata,
        score=.9, status='active')
    class Hits:
        async def ainvoke(self, request):
            return [hit]
    monkeypatch.setattr(rag_retrieve, 'rag_retrieve_tool', Hits())
    warm = (await service._collect_competitor_from_kb(record, detail, 'feature', brief.competitor,
        context, target_source_count=1))[0]
    assert not warm.metadata.get('normalized_fields')
    detail.raw_sources = [warm]
    calls = []
    async def fetch(*args, **kwargs):
        calls.append(args[3])
        return EvidenceFetchResult(url=candidate.url, title=candidate.title, text=body,
            ok=True, status_code=200, quality_score=.9, content_hash=page.content_hash,
            source_material_level='full_source', fetch_method='basic_httpx')
    async def model(_record, active, captured, _context):
        return semantic_extraction(active, captured, {'facts': [{'quote': first}, {'quote': row}]})
    async def review(*_):
        return {'_question_stop_reason': 'unverified'}
    monkeypatch.setattr(service, '_trace_fetch', fetch)
    monkeypatch.setattr(service, '_collector_semantic_extract', model)
    monkeypatch.setattr(service, '_collector_question_review', review)
    return dict(service=service, detail=detail, record=record, context=context, brief=brief,
        candidate=candidate, page=page, warm=warm, old=previous, old_document=doc,
        first=first, row=row, conditions=[header, *notes], calls=calls,
        result=result_for(brief, candidate, page, [first, row]))


async def pipeline(fixture, *, target=1):
    f = fixture
    return await f['service']._collect_competitor_with_research_pipeline(f['record'], f['detail'],
        'feature', f['brief'].competitor, f['context'], batch_sources=[f['warm']],
        target_source_count=target, include_official=False, seed_candidates=[f['candidate']],
        enable_search=False, enable_repair=False)


@pytest.mark.asyncio
@pytest.mark.parametrize('target', [1, 2])
async def test_actual_kb_hit_http_pipeline_sqlite_extend_join_snapshot_and_view(upgrade, target):
    f = upgrade
    obtained = await pipeline(f, target=target)
    assert f['calls'] == [f['candidate'].url]
    assert len(obtained) == 1, 'Accepted current facts must replace the empty warm start.'
    fresh = obtained[0]
    assert fresh.id != f['warm'].id
    assert fresh.metadata['kb_full_source_ingest_status'] == 'stored'
    async with KnowledgeRepository() as repo:
        doc = await repo.get_document(fresh.metadata['kb_document_id'])
    assert doc.id == f['old_document'].id and doc.version == f['old_document'].version
    assert doc.metadata['normalized_fields'] == f['old_document'].metadata['normalized_fields']
    assert len(fresh.metadata['normalized_fields']) > len(doc.metadata['normalized_fields'])
    batch = [f['warm']]
    f['service']._extend_source_batch(batch, obtained, target)
    assert [s.id for s in batch] == [fresh.id]
    f['detail'].raw_sources.extend(batch)
    f['detail'].raw_sources = f['service']._normalize_collected_sources(f['detail'], ['feature'])
    assert [s.id for s in f['detail'].raw_sources] == [fresh.id]
    snapshot = await f['service']._prepare_evidence_snapshot(f['record'], phase='analysis')
    content = [fact for fact in snapshot.facts if fact.field == 'evidence_terms' and fact.quote == f['row']]
    assert content and all(term in '\n'.join(content[0].value) for term in f['conditions'])
    replays = [json.loads(s.full_output) for s in f['detail'].trace_spans if s.name == 'question_delivery_replay']
    assert replays[-1]['snapshot_id'] == snapshot.id
    assert any(r['canonical_annotation_status'] == 'not_represented' and r['status'] == 'ready'
        for r in replays[-1]['item_results'])
    view, use = f['service']._begin_evidence_use(f['record'], agent='analyst',
        competitor=f['brief'].competitor, dimension='feature')
    f['service']._validate_evidence_use(f['record'], use)
    events = [json.loads(s.full_output) for s in f['detail'].trace_spans if s.name == 'question_delivery_view']
    assert events[-1]['status'] == 'view_selected'
    assert any(content[0].id == item['fact_id'] for item in events[-1]['content_observed'])


@pytest.mark.asyncio
async def test_admission_capacity_skips_unrelated_page_but_allows_later_upgrade(upgrade):
    f = upgrade
    unrelated = f['result'].model_copy(deep=True)
    unrelated.captured_pages[0].final_url += '/other'
    unrelated.captured_pages[0].quality_score = 1
    unrelated.captured_pages[0].id += '-other'
    for item in unrelated.evidence_items:
        item.captured_page_id = unrelated.captured_pages[0].id
        item.confidence = 1
    combined = f['result'].model_copy(deep=True)
    combined.captured_pages = unrelated.captured_pages + combined.captured_pages
    combined.evidence_items = unrelated.evidence_items + combined.evidence_items
    diagnostics = []
    obtained = convert(f['brief'], combined, [f['warm']], target=1,
        _replaceable_rag_source_ids=frozenset({f['warm'].id}), rejection_diagnostics=diagnostics)
    assert len(obtained) == 1 and str(obtained[0].url) == str(f['warm'].url)
    assert diagnostics[0]['reason'] == 'source_capacity'


@pytest.mark.asyncio
async def test_upgrade_credit_keeps_independent_sources_within_capacity(upgrade):
    f = upgrade
    combined = f['result'].model_copy(deep=True)
    for index in range(3):
        page = f['page'].model_copy(deep=True)
        page.id += f'-{index}'
        page.final_url += f'/independent-{index}'
        page.content_hash += f'-{index}'
        page.quality_score = 1
        combined.captured_pages.insert(0, page)
        for original in f['result'].evidence_items:
            item = original.model_copy(deep=True)
            item.captured_page_id = page.id
            item.confidence = 1
            combined.evidence_items.append(item)
    obtained = convert(f['brief'], combined, [f['warm']], target=2,
        _replaceable_rag_source_ids=frozenset({f['warm'].id}), source_is_usable=lambda _: True)
    assert len(obtained) == 2
    assert sum(str(s.url) == str(f['warm'].url) for s in obtained) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['live', 'manual', 'history', 'facts', 'flag_only', 'origin_only',
    'different_product', 'different_dimension', 'different_url', 'different_coverage'])
async def test_unqualified_source_cannot_receive_admission_credit(upgrade, change):
    f = upgrade
    warm = f['warm'].model_copy(deep=True)
    if change == 'live': warm.candidate_origin, warm.fetch_method = 'web_search', 'basic_httpx'
    if change == 'manual': warm.source_type = 'manual_note'
    if change == 'history': warm.metadata['history_report_id'] = 'report'
    if change == 'facts': warm.metadata['normalized_fields'] = f['old'].metadata['normalized_fields']
    if change == 'flag_only': warm.candidate_origin, warm.fetch_method = 'web_search', 'basic_httpx'
    if change == 'origin_only': warm.metadata.pop('kb_retrieved')
    if change == 'different_product': warm.competitor = 'Other Product'
    if change == 'different_dimension': warm.dimension = 'pricing'
    if change == 'different_url': warm.url = 'https://docs.example-suite.test/access'
    if change == 'different_coverage': warm.covered_competitors = ['Other Product']
    assert not convert(f['brief'], f['result'], [warm], target=1,
        _replaceable_rag_source_ids=frozenset({warm.id}))


@pytest.mark.asyncio
async def test_credit_does_not_ignore_ordinary_url_or_hash_duplicates(upgrade):
    f = upgrade
    live = f['old'].model_copy(deep=True)
    for change in ('url', 'hash'):
        if change == 'hash': live.url = 'https://docs.example-suite.test/access'
        assert not convert(f['brief'], f['result'], [f['warm'], live], target=3,
            _replaceable_rag_source_ids=frozenset({f['warm'].id}))


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['no_registration', 'wrong_scope', 'wrong_role', 'wrong_version',
    'wrong_hash', 'wrong_canonical_url', 'wrong_reference_workspace', 'wrong_reference_project'])
async def test_wrapper_requires_real_retrieval_and_valid_canonical_reference(upgrade, change):
    f = upgrade
    warm = f['warm']
    if change == 'no_registration': f['record']._kb_retrieved_source_keys.clear()
    elif change == 'wrong_scope': f['detail'].workspace_id = 'another-workspace'
    elif change == 'wrong_reference_workspace': warm.metadata['kb_document_workspace_id'] = 'other-workspace'
    elif change == 'wrong_reference_project': warm.metadata['kb_document_project_id'] = 'other-project'
    elif change in {'wrong_role', 'wrong_canonical_url'}:
        async with KnowledgeRepository() as repo:
            if change == 'wrong_role':
                await repo._db.execute("UPDATE documents SET source_role = 'historical_report'")
            else:
                await repo._db.execute("UPDATE documents SET url = 'https://other.example/page'")
            await repo._db.commit()
    else:
        warm.metadata['kb_document_version' if change == 'wrong_version' else 'kb_document_content_hash'] = 'wrong'
        f['record']._kb_retrieved_source_keys = {f['service']._kb_retrieved_source_key(warm)}
    assert not await pipeline(f)


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['failed_capture', 'zero_accepted', 'unusable', 'persist_failed'])
@pytest.mark.parametrize('target', [1, 2])
async def test_unsuccessful_current_source_keeps_warmstart(upgrade, monkeypatch, change, target):
    f = upgrade
    result = f['result'].model_copy(deep=True)
    if change == 'failed_capture': result.captured_pages[0].status = 'failed'
    if change == 'zero_accepted': result.evidence_items = []
    if change == 'unusable': monkeypatch.setattr(f['service'], '_research_source_is_usable', lambda _: False)
    async def run(*_, **__): return result
    monkeypatch.setattr('packages.agents.collectors.logic.run_research_pipeline', run)
    if change == 'persist_failed':
        async def fail(**_): raise RuntimeError('SQLite write failed')
        monkeypatch.setattr('packages.tools.ingest_document.ingest_document_reference', fail)
    obtained = await pipeline(f, target=target)
    batch = [f['warm']]
    f['service']._extend_source_batch(batch, obtained, target)
    assert [s.id for s in batch] == [f['warm'].id]


@pytest.mark.asyncio
async def test_changed_body_replaces_without_old_fields_dates_or_refs_and_join_order(upgrade, monkeypatch):
    f = upgrade
    fresh_page = f['page'].model_copy(deep=True)
    quote = 'Reviewers can comment on shared documents only on the Summit plan.'
    fresh_page.text = quote
    fresh_page.content_hash = hashlib.sha256(quote.encode()).hexdigest()
    fresh_page.captured_at = datetime.now(UTC)
    fresh_page.metadata['official_source_verification'] = verify_registered_capture(f['brief'].competitor, fresh_page)
    current = result_for(f['brief'], f['candidate'], fresh_page, [quote])
    f['warm'].metadata.update(source_published_at='2024-01-01', source_updated_at='2024-02-01')
    async def run(*_, **__): return current
    monkeypatch.setattr('packages.agents.collectors.logic.run_research_pipeline', run)
    fresh = (await pipeline(f))[0]
    assert fresh.metadata['kb_document_version'] == f['warm'].metadata['kb_document_version'] + 1
    assert fresh.extracted_at == fresh_page.captured_at
    assert not fresh.metadata.get('source_published_at') and not fresh.metadata.get('source_updated_at')
    assert fresh.metadata['kb_document_content_hash'] != f['warm'].metadata['kb_document_content_hash']
    assert f['first'] not in str(fresh.metadata['normalized_fields'])
    for values in ([f['warm'], fresh], [fresh, f['warm']]):
        f['detail'].raw_sources = [s.model_copy(deep=True) for s in values]
        joined = f['service']._normalize_collected_sources(f['detail'], ['feature'])
        assert len(joined) == 1 and joined[0].model_dump() == fresh.model_copy(
            update={'covered_competitors': [fresh.competitor]}).model_dump()
    ordinary = fresh.model_copy(deep=True, update={'id': 'unrelated', 'url': 'https://docs.example-suite.test/access'})
    batch = [f['warm']]
    f['service']._extend_source_batch(batch, [ordinary, fresh], 1)
    assert [s.id for s in batch] == [fresh.id]


@pytest.mark.asyncio
async def test_full_source_metadata_alone_cannot_replace_warmstart(upgrade):
    f = upgrade
    fresh = convert(f['brief'], f['result'])[0]
    fresh.metadata.update(f['old'].metadata)
    batch = [f['warm']]
    f['service']._extend_source_batch(batch, [fresh], 1)
    assert batch == [f['warm']]


@pytest.mark.asyncio
@pytest.mark.parametrize('order', ['warm_first', 'fresh_first'])
@pytest.mark.parametrize('body', ['same', 'changed'])
async def test_journal_restored_production_join_revalidates_upgrade(upgrade, tmp_path, monkeypatch, order, body):
    from packages.memory.run_journal import RunJournal
    f = upgrade
    if body == 'changed':
        page = f['page'].model_copy(deep=True)
        page.text += '\nReviewers can comment on shared documents only on the Summit plan.'
        page.content_hash = hashlib.sha256(page.text.encode()).hexdigest()
        page.metadata['official_source_verification'] = verify_registered_capture(f['brief'].competitor, page)
        current = result_for(f['brief'], f['candidate'], page, [f['first'], f['row']])
        async def run(*_, **__): return current
        monkeypatch.setattr('packages.agents.collectors.logic.run_research_pipeline', run)
    fresh = (await pipeline(f))[0]
    f['detail'].raw_sources = [f['warm'], fresh] if order == 'warm_first' else [fresh, f['warm']]
    journal = RunJournal(tmp_path / 'runs.db')
    journal.save_run(f['detail'])
    restored_service, _ = service_and_detail(market='')
    restored = RunRecord(detail=journal.load_run(f['detail'].id))
    restored_service._runs[restored.detail.id] = restored
    assert not getattr(restored_service, '_collector_rag_upgrades', {})
    async def no_cross(*_): return None
    monkeypatch.setattr(restored_service, '_collect_cross_competitor_evidence', no_cross)
    await restored_service._real_collect_join_step(restored, ['feature'])
    assert [s.id for s in restored.detail.raw_sources] == [fresh.id]
    snapshot = await restored_service._prepare_evidence_snapshot(restored, phase='analysis')
    assert any(fact.quote == f['row'] for fact in snapshot.facts)


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['scope', 'reference', 'current_fields', 'no_receipt'])
async def test_restored_receipt_cannot_replace_without_exact_current_inputs(upgrade, monkeypatch, change):
    f = upgrade
    fresh = (await pipeline(f))[0]
    f['detail'].raw_sources = [f['warm'], fresh]
    service, _ = service_and_detail(market='')
    if change == 'scope': f['detail'].workspace_id = 'other-workspace'
    if change == 'reference': fresh.metadata['kb_document_version'] += 1
    if change == 'current_fields': fresh.metadata['normalized_fields'][0]['evidence_terms'] = ['changed']
    if change == 'no_receipt':
        f['detail'].trace_spans = [s for s in f['detail'].trace_spans if s.name != 'clean_research_pipeline']
    await service._restore_verified_rag_upgrades(f['detail'])
    assert not service._is_verified_rag_upgrade(f['warm'], fresh, f['detail'])


@pytest.mark.asyncio
async def test_join_revalidation_revokes_runtime_pair_if_canonical_becomes_invalid(upgrade):
    f = upgrade
    fresh = (await pipeline(f))[0]
    f['detail'].raw_sources = [f['warm'], fresh]
    assert f['service']._is_verified_rag_upgrade(f['warm'], fresh, f['detail'])
    async with KnowledgeRepository() as repo:
        await repo._db.execute("UPDATE documents SET source_role = 'historical_report'")
        await repo._db.commit()
    await f['service']._restore_verified_rag_upgrades(f['detail'])
    assert not f['service']._is_verified_rag_upgrade(f['warm'], fresh, f['detail'])


@pytest.mark.asyncio
@pytest.mark.parametrize('days,usable', [(29, True), (31, False), (-1, False)])
async def test_restored_join_uses_existing_canonical_freshness_policy(upgrade, tmp_path, monkeypatch, days, usable):
    from packages.memory.run_journal import RunJournal
    f = upgrade
    fresh = (await pipeline(f))[0]
    f['detail'].raw_sources = [f['warm'], fresh]
    journal = RunJournal(tmp_path / 'freshness-runs.db')
    journal.save_run(f['detail'])
    service, _ = service_and_detail(market='')
    restored = RunRecord(detail=journal.load_run(f['detail'].id))
    service._runs[restored.detail.id] = restored
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return (f['old_document'].fetched_at + timedelta(days=days)).astimezone(tz or UTC)
    monkeypatch.setattr('packages.agents.collectors.kb_bridge.datetime', Clock)
    async def no_cross(*_): return None
    monkeypatch.setattr(service, '_collect_cross_competitor_evidence', no_cross)
    await service._real_collect_join_step(restored, ['feature'])
    actual = next(s for s in restored.detail.raw_sources if s.id == fresh.id)
    assert service._is_verified_rag_upgrade(f['warm'], actual, restored.detail) is usable
    assert (f['warm'].id not in {s.id for s in restored.detail.raw_sources}) is usable


@pytest.mark.asyncio
@pytest.mark.parametrize('days', [-31, 1])
async def test_initial_upgrade_checks_actual_canonical_time_after_persistence(upgrade, monkeypatch, days):
    f = upgrade
    persist = f['service']._persist_captured_sources_to_kb
    async def write_then_change_time(*args, **kwargs):
        await persist(*args, **kwargs)
        observed = (datetime.now(UTC) + timedelta(days=days)).isoformat()
        async with KnowledgeRepository() as repo:
            await repo._db.execute('UPDATE documents SET last_verified_at = ?', (observed,))
            await repo._db.commit()
    monkeypatch.setattr(f['service'], '_persist_captured_sources_to_kb', write_then_change_time)
    obtained = await pipeline(f)
    assert obtained and obtained[0].metadata['kb_full_source_ingest_status'] == 'stored'
    batch = [f['warm']]
    f['service']._extend_source_batch(batch, obtained, 1)
    assert [s.id for s in batch] == [f['warm'].id]


@pytest.mark.asyncio
@pytest.mark.parametrize('upgrade', [' support@example-suite.test'], indirect=True)
async def test_redacted_title_does_not_break_journal_restored_upgrade(upgrade, tmp_path, monkeypatch):
    from packages.memory.run_journal import RunJournal
    f = upgrade
    fresh = (await pipeline(f))[0]
    assert 'support@example-suite.test' in fresh.title
    span = next(s for s in f['detail'].trace_spans if s.name == 'clean_research_pipeline')
    assert 'support@example-suite.test' not in span.full_output
    assert '[redacted:email]' in span.full_output
    f['detail'].raw_sources = [f['warm'], fresh]
    journal = RunJournal(tmp_path / 'redacted-title-runs.db')
    journal.save_run(f['detail'])
    service, _ = service_and_detail(market='')
    restored = RunRecord(detail=journal.load_run(f['detail'].id))
    service._runs[restored.detail.id] = restored
    async def no_cross(*_): return None
    monkeypatch.setattr(service, '_collect_cross_competitor_evidence', no_cross)
    await service._real_collect_join_step(restored, ['feature'])
    assert [s.id for s in restored.detail.raw_sources] == [fresh.id]
    assert 'support@example-suite.test' in restored.detail.raw_sources[0].title


@pytest.mark.asyncio
async def test_upgrade_audit_descriptor_does_not_duplicate_source_prose(upgrade):
    f = upgrade
    await pipeline(f)
    span = next(s for s in f['detail'].trace_spans if s.name == 'clean_research_pipeline')
    receipts = json.loads(span.full_output)['rag_warm_start_upgrades']
    audit = json.dumps(receipts)
    assert len(audit) < 3000
    assert all(term not in audit for term in [f['row'], f['first'], 'snippet', 'normalized_fields', 'title'])
