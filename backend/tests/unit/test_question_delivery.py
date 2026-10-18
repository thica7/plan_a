"""Source-native recovery and observed delivery, with anonymous original fixtures."""
import hashlib

import pytest

import test_question_semantic_focus as source_fixtures
from test_billing_rule_context import source_table
from packages.research.extraction import semantic
from packages.research.evidence import admit_evidence_items

source = source_fixtures.source


def test_native_complete_billing_table_is_recovered_without_model_selection(source):
    from packages.research.extraction.structured_evidence import extract_structured_evidence
    body, header, row, notes = source_table()
    brief, candidate, page = source(body, questions=('What are the Usage billing rules for requests and CPU time?',))
    result = extract_structured_evidence(brief, page)
    assert result.extractor_name == 'source_structured_rules'
    assert any(quote.text == row for quote in result.quotes)
    items = admit_evidence_items([result], brief=brief, captured_pages=[page], candidates=[candidate])
    assert any(item.status == 'accepted' and item.quote == row for item in items)
    assert all(term in '\n'.join(items[0].value['evidence_terms']) for term in [header, *notes])


@pytest.mark.parametrize('change', ['missing_note', 'forged_disclosure'])
def test_native_structures_do_not_override_original_validation(source, change):
    from packages.research.extraction.structured_evidence import extract_structured_evidence
    body, _, row, notes = source_table()
    if change == 'missing_note':
        body = body.replace(notes[0] + '\n', '')
    brief, _, page = source(body, questions=('What are the Usage billing rules?',))
    if change == 'forged_disclosure':
        page.text = 'Members can view shared documents.'
        page.metadata['capture_metadata'] = {'disclosures': [{'status': 'complete', 'quote': row,
            'quote_start': 0, 'quote_hash': hashlib.sha256(row.encode()).hexdigest()[:16]}]}
    assert not extract_structured_evidence(brief, page).fields


def test_every_model_proposal_has_a_verifiable_outcome_including_capacity(source):
    good = 'Members can edit shared documents on all plans.'
    brief, _, page = source(good)
    facts = [{'quote': good}, {'quote': 'This invented content was never captured.'}, {'quote': good},
             {'quote': None}, {'quote': ''}, {'quote': 'short'}, {'quote': good}]
    result = semantic.semantic_extraction(brief, page, {'facts': facts})
    diagnostics = result.metadata.get('proposal_diagnostics', [])
    assert len(diagnostics) == len(facts)
    assert diagnostics[0]['verified_field_ids'] == list(result.fields)
    assert [row['reason'] for row in diagnostics] == [None, 'not_original', 'duplicate',
        'invalid', 'invalid', 'invalid', 'capacity']
    assert diagnostics[0]['quote_anchor']['start_offset'] == 0


def test_zero_field_semantic_result_keeps_failed_proposals(source):
    brief, _, page = source('Members can edit shared documents on all plans.')
    result = semantic.semantic_extraction(brief, page, {'facts': [{'quote': 'A complete invented statement was never captured.'}]})
    assert not result.fields
    assert result.metadata['proposal_diagnostics'][0]['reason'] == 'not_original'


@pytest.mark.asyncio
async def test_pipeline_native_recovery_runs_when_model_returns_zero_fields(source):
    from packages.research.pipeline import run_research_pipeline
    from packages.tools.evidence_fetch import EvidenceFetchResult
    body, _, row, _ = source_table()
    brief, candidate, _ = source(body, questions=('What are the Usage billing rules for requests and CPU time?',))
    brief = brief.model_copy(update={'include_trusted_sources': False, 'include_homepage_candidates': False,
        'max_repair_rounds': 0})
    async def fetch(url):
        return EvidenceFetchResult(url=url, title=candidate.title, text=body, ok=True,
            quality_score=.9, status_code=200, fetch_method='basic_httpx',
            source_material_level='full_source', content_hash=hashlib.sha256(body.encode()).hexdigest())
    async def model(active, page):
        return semantic.semantic_extraction(active, page, {'facts': [{'quote': 'Never captured fabricated complete statement.'}]})
    result = await run_research_pipeline(brief, fetch=fetch, seed_candidates=[candidate], semantic_extract=model)
    assert any(item.status == 'accepted' and item.quote == row for item in result.evidence_items)
    assert any(not item.fields and item.metadata.get('proposal_diagnostics') for item in result.extractions)


def test_complete_disclosure_is_only_a_proposal_and_requires_exact_body_anchor(source):
    from packages.research.extraction.structured_evidence import extract_structured_evidence
    quote = 'Can members edit shared pages?\nMembers can edit shared pages only on the Summit plan.'
    brief, _, page = source(quote)
    page.metadata['capture_metadata'] = {'disclosures': [{'status': 'complete', 'quote': quote,
        'quote_start': 0, 'quote_hash': hashlib.sha256(quote.encode()).hexdigest()[:16]}]}
    assert extract_structured_evidence(brief, page).fields
    page.metadata['capture_metadata']['disclosures'][0]['quote_start'] = 1
    assert not extract_structured_evidence(brief, page).fields


def delivery_fixture(source):
    from types import SimpleNamespace
    from packages.research.models import ResearchResult
    from packages.research.evidence.normalization import normalized_fields_from_evidence_items
    from packages.research.evidence.admission import raw_sources_from_research_result
    body, _, row, _ = source_table()
    brief, candidate, page = source(body, questions=('What are the Usage billing rules for requests and CPU time?',))
    extraction = semantic.semantic_extraction(brief, page, {'facts': [{'quote': row}]})
    items = admit_evidence_items([extraction], brief=brief, captured_pages=[page], candidates=[candidate])
    result = ResearchResult(brief=brief, candidates=[candidate], captured_pages=[page], extractions=[extraction],
        evidence_items=items, normalized_fields=normalized_fields_from_evidence_items(items))
    sources = raw_sources_from_research_result(brief, result, batch_sources=[], target_source_count=1,
        requires_accepted_evidence=True, source_exists=lambda *_: False,
        confidence_for_source=lambda *_: .8, fallback_snippet=lambda p: p.text)
    detail = SimpleNamespace(id=brief.run_id, workspace_id='w', project_id='p', topic=brief.topic,
                             raw_sources=sources, trace_spans=[],
                             plan=SimpleNamespace(competitors=[brief.competitor], dimensions=[brief.dimension]))
    return detail, brief, result, sources


def test_capsule_is_compact_and_keeps_actual_items_and_conversion_missing(source):
    from packages.research.question_delivery import _build_question_delivery
    detail, brief, result, sources = delivery_fixture(source)
    capsule = _build_question_delivery(detail, brief, result, sources, [])
    assert capsule['questions'][0]['question'] == brief.questions[0].question
    assert capsule['items'][0]['value'] == result.evidence_items[0].value
    assert capsule['raw_sources'][0]['normalized_fields'] == sources[0].metadata['normalized_fields']
    assert result.captured_pages[0].text not in str(capsule)
    missing = _build_question_delivery(detail, brief, result, [], [{'reason': 'source_capacity',
        'candidate_id': result.captured_pages[0].candidate_id}])
    assert missing['questions'][0]['next_action'] == 'resolve_conversion_missing'
    assert missing['conversion_missing'][0]['reason'] == 'source_capacity'


@pytest.mark.parametrize('change', ['none', 'missing', 'body', 'scope', 'item_id', 'normalized', 'version', 'prior_run', 'plan_scope', 'historical', 'summary', 'report', 'raw_summary'])
def test_replay_uses_actual_canonical_body_and_recomputes_ids(source, change):
    from packages.research.question_delivery import _build_question_delivery, _replay_question_delivery
    from packages.knowledge.models import KnowledgeDocument
    detail, brief, result, sources = delivery_fixture(source)
    page = result.captured_pages[0]
    doc = KnowledgeDocument(id='doc', source_type='webpage_verified', title=page.title, url=page.final_url, text=page.text,
        content_hash=hashlib.sha256(page.text.encode()).hexdigest()[:16], fetched_at=page.captured_at,
        workspace_id='w', project_id='p', competitor=brief.competitor, dimension='feature',
        metadata={**sources[0].metadata, 'run_id': detail.id, 'raw_source_id': sources[0].id})
    sources[0].metadata.update(kb_document_id=doc.id, kb_document_version=doc.version,
        kb_document_content_hash=doc.content_hash)
    capsule = _build_question_delivery(detail, brief, result, sources, [])
    if change == 'body': doc.text += '\nAltered material.'
    if change == 'scope': doc.project_id = 'other'
    if change == 'item_id': capsule['items'][0]['id'] = 'invented-id'
    if change == 'normalized': sources[0].metadata['normalized_fields'][0]['evidence_terms'] = ['invented']
    if change == 'version': doc.version += 1
    if change == 'prior_run':
        doc.metadata.update(run_id='previous-run', raw_source_id='previous-raw-source')
    if change == 'plan_scope': detail.plan.competitors = ['Different Product']
    if change == 'historical': doc.source_role = 'historical_report'
    if change == 'summary': doc.metadata['source_material_level'] = 'summary'
    if change == 'report': doc.source_type = 'report'
    if change == 'raw_summary': sources[0].metadata['source_material_level'] = 'summary'
    reseal_receipt(capsule)
    replay = _replay_question_delivery(detail, capsule, {} if change == 'missing' else {'doc': doc}, authorized_brief=brief)
    assert bool(replay['verified_item_ids']) == (change in {'none', 'prior_run'}), replay['item_results']
    assert all(item['status'] == ('ready' if change in {'none', 'prior_run'} else 'partial') for item in replay['item_results'])


def test_native_disclosure_reads_actual_capture_adapter_metadata(source):
    from packages.research.extraction.structured_evidence import extract_structured_evidence
    quote = 'Can members edit shared pages?\nMembers can edit shared pages only on the Summit plan.'
    brief, _, page = source(quote)
    page.metadata['disclosures'] = [{'status': 'complete', 'quote': quote, 'quote_start': 0,
        'quote_hash': hashlib.sha256(quote.encode()).hexdigest()[:16]}]
    assert extract_structured_evidence(brief, page).fields


def writer_fixture():
    from types import SimpleNamespace
    from packages.research.evidence.snapshot_models import EvidenceFact
    fact = EvidenceFact(id='f', semantic_id='sf', evidence_item_ids=('item',), source_id='s',
        competitor='Example Suite', dimension='feature', field='evidence_terms',
        value_json='["Members can edit documents only with a paid account."]',
        qualifiers_json='{"source_scope":{"plan":"paid"}}',
        quote='Members can edit documents only with a paid account.', confidence=.8)
    use = SimpleNamespace(id='use', snapshot_id='snap', dependency_hash='dep', agent='writer',
                          competitor='Example Suite', dimension='feature', status='validated', validated_snapshot_id='snap')
    view = SimpleNamespace(snapshot_id='snap', dependency_hash='dep', facts=[fact])
    payload = {'evidence_view': {'facts': [dict(id=fact.id, source_id=fact.source_id,
        competitor=fact.competitor, dimension=fact.dimension, field=fact.field, value=fact.value,
        qualifiers=fact.qualifiers, quote=fact.quote)]}}
    return fact, use, view, payload


@pytest.mark.parametrize('mode,expected', [('zero', 'prepared'), ('one', 'dispatch_succeeded'),
    ('failed', 'dispatch_failed'), ('no_span', 'unverified'), ('duplicate', 'unverified'),
    ('condition_lost', 'partial'), ('ids_only', 'partial'), ('omitted', 'partial'), ('refs', 'dispatch_succeeded')])
def test_writer_observes_real_transport_and_complete_actual_prompt(mode, expected):
    import json
    from types import SimpleNamespace
    from packages.research.question_delivery import _observe_writer_dispatch
    fact, use, view, payload = writer_fixture()
    if mode == 'condition_lost': payload['evidence_view']['facts'][0]['qualifiers'] = {}
    if mode == 'ids_only': payload['evidence_view']['facts'] = [{'id': fact.id}]
    if mode == 'omitted': payload['evidence_view']['facts'] = []
    if mode == 'refs':
        payload['text_sets'] = {'t0': fact.quote}
        payload['evidence_view']['facts'][0]['quote'] = {'text_ref': 't0'}
        payload['evidence_view']['facts'][0]['value'] = [{'text_ref': 't0'}]
    prompt = json.dumps(payload)
    span = SimpleNamespace(id='llm-span', name='dimension_claim_writer', kind='llm', agent='writer',
        subagent='Example Suite/feature', full_input='SYSTEM\n\n\nJSON:\n' + prompt,
        status='error' if mode == 'failed' else 'ok',
        metadata={'llm_transport_attempts': 0 if mode == 'zero' else 1})
    detail = SimpleNamespace(trace_spans=[] if mode == 'no_span' else [span, span] if mode == 'duplicate' else [span])
    observed = _observe_writer_dispatch(detail, view, use, prompt, 0)
    assert observed['status'] == expected
    assert observed['dispatch_attempted'] == (mode not in {'zero', 'no_span', 'duplicate'})
    assert observed['content_dispatched'] == (expected in {'dispatch_succeeded', 'dispatch_failed'})
    if mode == 'omitted': assert observed['omitted_fact_ids'] == ['f']
    if mode == 'condition_lost':
        from packages.research.evidence.snapshot_models import canonical_json
        assert observed['content_observed'][0]['content_sha256'] == hashlib.sha256(
            canonical_json(payload['evidence_view']['facts'][0]).encode()).hexdigest()


def test_view_observation_is_distinct_from_dispatch_and_rejects_other_snapshot():
    from packages.research.question_delivery import _observe_question_view
    fact, use, view, _ = writer_fixture()
    replay = dict(snapshot_id='snap', verified_item_ids=['item'], item_results=[
        dict(item_id='item', status='ready', fact_ids=['f'], content_fact_ids=['f'])])
    observed = _observe_question_view(view, use, replay)
    assert observed['status'] == 'view_selected'
    assert observed['dispatch_status'] == 'unverified'
    assert observed['content_observed'][0]['evidence_item_ids'] == ['item']
    use.validated_snapshot_id = 'other'
    assert _observe_question_view(view, use, replay)['status'] == 'unverified'


@pytest.mark.asyncio
async def test_actual_fetch_pipeline_sqlite_seal_views_and_restored_receipt(source, tmp_path, monkeypatch):
    import json
    from test_collector_knowledge_scope import service_and_detail
    from packages.agents import SubagentContext
    from packages.orchestrator.service import RunRecord
    from packages.tools.evidence_fetch import EvidenceFetchResult
    from packages.memory.run_journal import RunJournal
    from packages.research.question_delivery import _question_delivery_capsules
    body, header, row, notes = source_table()
    brief, candidate, _ = source(body, questions=('What are the Usage billing rules for requests and CPU time?',))
    service, detail = service_and_detail()
    detail.id, detail.topic = brief.run_id, brief.topic
    detail.plan.competitors = [brief.competitor]
    detail.plan.target_product.name = brief.competitor
    monkeypatch.setenv('KB_DB_PATH', str(tmp_path / 'actual.db'))
    monkeypatch.setenv('KB_SEMANTIC_INDEXING', 'false')
    monkeypatch.setattr(service, '_research_brief', lambda *_: brief)
    calls = []
    async def fetch(*args, **kwargs):
        calls.append(args[3])
        return EvidenceFetchResult(url=candidate.url, title=candidate.title, text=body,
            ok=True, status_code=200, quality_score=.9, content_hash=hashlib.sha256(body.encode()).hexdigest(),
            source_material_level='full_source', fetch_method='basic_httpx')
    async def model(_record, active, page, _context):
        return semantic.semantic_extraction(active, page, {'facts': []})
    async def review(*_):
        return {'_question_stop_reason': 'unverified'}
    monkeypatch.setattr(service, '_trace_fetch', fetch)
    monkeypatch.setattr(service, '_collector_semantic_extract', model)
    monkeypatch.setattr(service, '_collector_question_review', review)
    record = RunRecord(detail=detail)
    service._runs[detail.id] = record
    sources = await service._collect_competitor_with_research_pipeline(record, detail, 'feature', brief.competitor,
        SubagentContext(run_id=detail.id, agent='collector', subagent=f'{brief.competitor}/feature'),
        batch_sources=[], target_source_count=1, include_official=False, seed_candidates=[candidate],
        enable_search=False, enable_repair=False)
    assert calls == [candidate.url]
    assert sources and sources[0].metadata.get('kb_document_id')
    detail.raw_sources = sources
    capsule = next(_question_delivery_capsules(detail))
    snapshot = await service._prepare_evidence_snapshot(record, phase='analysis')
    replays = [json.loads(span.full_output) for span in detail.trace_spans if span.name == 'question_delivery_replay']
    assert replays and replays[-1]['verified_item_ids'], replays
    assert replays[-1]['snapshot_id'] == snapshot.id
    content = [fact for fact in snapshot.facts if fact.field == 'evidence_terms' and fact.quote == row]
    assert content and all(term in '\n'.join(content[0].value) for term in [header, *notes])
    for agent in ['analyst', 'analyst_qa', 'comparator', 'reflector', 'writer', 'qa']:
        view, use = service._begin_evidence_use(record, agent=agent, competitor=brief.competitor, dimension='feature')
        service._validate_evidence_use(record, use)
        service._validate_evidence_use(record, use)
    views = [json.loads(span.full_output) for span in detail.trace_spans if span.name == 'question_delivery_view']
    assert len(views) == 6
    assert all(event['status'] == 'view_selected' and event['dispatch_status'] == 'unverified' for event in views)
    assert all(any(item['evidence_item_ids'] for item in event['content_observed']) for event in views)
    journal = RunJournal(tmp_path / 'runs.db')
    journal.save_run(detail)
    restored = journal.load_run(detail.id)
    assert next(_question_delivery_capsules(restored)) == capsule
    record.detail = restored
    await service._prepare_evidence_snapshot(record, phase='analysis')
    assert len([span for span in restored.trace_spans if span.name == 'question_delivery_replay']) == 1
    # A no-progress redo must finalize the actual retained baseline as well.
    restored.trace_spans = [span for span in restored.trace_spans if span.name != 'question_delivery_replay']
    record.collector_redo_snapshot_id = snapshot.id
    monkeypatch.setattr(service, '_collector_redo_producers_valid', lambda *_: True)
    retained = await service._prepare_evidence_snapshot(record, phase='analysis')
    assert record.collector_redo_no_new_evidence and retained.id == snapshot.id
    final_replay = next(json.loads(span.full_output) for span in restored.trace_spans
                        if span.name == 'question_delivery_replay')
    assert final_replay['snapshot_id'] == retained.id and final_replay['verified_item_ids']


@pytest.mark.parametrize('change', ['question', 'focus', 'offset', 'field_id', 'qualifiers'])
def test_canonical_replay_rejects_forged_request_or_recipe(source, change):
    from packages.research.question_delivery import _build_question_delivery, _replay_question_delivery
    from packages.knowledge.models import KnowledgeDocument
    detail, brief, result, sources = delivery_fixture(source)
    page = result.captured_pages[0]
    document = KnowledgeDocument(id='doc', source_type='webpage_verified', title=page.title, url=page.final_url,
        text=page.text, content_hash=hashlib.sha256(page.text.encode()).hexdigest()[:16], fetched_at=page.captured_at,
        workspace_id='w', project_id='p', competitor=brief.competitor, dimension=brief.dimension,
        metadata={**sources[0].metadata, 'run_id': detail.id, 'raw_source_id': sources[0].id})
    sources[0].metadata.update(kb_document_id=document.id, kb_document_version=document.version,
        kb_document_content_hash=document.content_hash)
    capsule = _build_question_delivery(detail, brief, result, sources, [])
    if change == 'question':
        capsule['questions'][0]['question'] = 'An invented authorized question?'
        capsule['recipes'][0]['brief']['questions'][0]['question'] = 'An invented authorized question?'
    if change == 'focus': capsule['recipes'][0]['brief']['metadata']['active_question_ids'] = ['unauthorized']
    if change == 'offset': capsule['recipes'][0]['quotes'][0]['start_offset'] += 1
    if change == 'field_id': capsule['items'][0]['field'] = 'forged'
    if change == 'qualifiers': capsule['items'][0]['value']['conditions'] = []
    reseal_receipt(capsule)
    replay = _replay_question_delivery(detail, capsule, {'doc': document}, authorized_brief=brief)
    assert not replay['verified_item_ids']


def reseal_receipt(capsule):
    from packages.research.evidence.snapshot_models import canonical_json
    capsule['id'] = 'question-delivery-' + hashlib.sha256(canonical_json(
        {key: value for key, value in capsule.items() if key != 'id'}).encode()).hexdigest()[:24]


def test_actual_source_capacity_rejection_is_explained_without_dropping_accepted_item(source):
    from packages.research.evidence.admission import raw_sources_from_research_result
    from packages.research.question_delivery import _build_question_delivery
    detail, brief, result, sources = delivery_fixture(source)
    diagnostics = []
    converted = raw_sources_from_research_result(brief, result, batch_sources=sources, target_source_count=1,
        requires_accepted_evidence=True, source_exists=lambda *_: False,
        confidence_for_source=lambda *_: .8, fallback_snippet=lambda p: p.text,
        rejection_diagnostics=diagnostics)
    assert not converted and diagnostics[0]['reason'] == 'source_capacity'
    capsule = _build_question_delivery(detail, brief, result, converted, diagnostics)
    assert capsule['items'][0]['status'] == 'accepted'
    assert capsule['conversion_missing'][0]['reason'] == 'source_capacity'


def test_persistence_failure_retains_actual_reason_in_receipt(source):
    import json
    from types import SimpleNamespace
    from packages.research.question_delivery import _build_question_delivery
    detail, brief, result, sources = delivery_fixture(source)
    sources[0].metadata['kb_full_source_ingest_status'] = 'failed'
    detail.trace_spans = [SimpleNamespace(name='kb_ingest_captured_sources', full_output=json.dumps(
        {'results': [{'source_id': sources[0].id, 'error': 'SQLite fixture write failure'}]}))]
    capsule = _build_question_delivery(detail, brief, result, sources, [])
    assert capsule['raw_sources'][0]['persistence_error'] == 'SQLite fixture write failure'
    assert capsule['questions'][0]['next_action'] == 'retry_canonical_persistence'


@pytest.mark.asyncio
@pytest.mark.parametrize('attempts', [0, 1])
async def test_writer_production_hook_matches_actual_llm_span_and_prompt(source, monkeypatch, attempts):
    import json
    from test_collector_knowledge_scope import service_and_detail
    from packages.orchestrator.service import RunRecord
    from packages.research.evidence.snapshot import seal_snapshot
    from packages.research.question_delivery import _build_question_delivery
    from packages.llm.execution_budget import current_llm_execution
    from packages.llm.doubao_client import LLMUsage
    from packages.schema.models import TargetProduct
    detail_stub, brief, result, sources = delivery_fixture(source)
    service, detail = service_and_detail()
    detail.id, detail.topic = brief.run_id, brief.topic
    detail.plan.competitors = [brief.competitor]
    detail.plan.target_product = TargetProduct(name=brief.competitor, category='documents')
    detail.raw_sources = sources
    record = RunRecord(detail=detail)
    service._runs[detail.id] = record
    capsule = _build_question_delivery(detail, brief, result, sources, [])
    service._trace_local_tool(record, agent='collector', subagent='fixture', name='clean_research_pipeline',
        input_text='{}', output_text=json.dumps({'question_delivery_v1': capsule}))
    seal_snapshot(detail, phase='analysis', canonical_documents={})
    calls = []
    async def provider(*, system, user):
        calls.append(user)
        if attempts:
            current_llm_execution.get().reserve_transport()
        return '{"claims":[]}'
    monkeypatch.setattr(service._llm, 'complete_text', provider)
    monkeypatch.setattr(service._llm, 'consume_last_usage', lambda: LLMUsage(prompt_tokens=100, completion_tokens=10, total_tokens=110))
    await service._writer_dimension_report_inner(record)
    observed = [json.loads(span.full_output) for span in detail.trace_spans
                if span.name == 'question_delivery_writer_dispatch']
    assert calls and observed
    event = observed[0]
    assert event['status'] == ('dispatch_succeeded' if attempts else 'prepared'), event
    matched = next(span for span in detail.trace_spans if span.id == event['span_id'])
    assert matched.kind == 'llm' and matched.name == 'dimension_claim_writer'
    assert matched.full_input.endswith(calls[0])
    assert event['transport_attempts'] == attempts
    assert event['content_observed'] and not event['omitted_fact_ids']


@pytest.mark.asyncio
async def test_same_body_second_sqlite_ingest_preserves_new_legal_observation(source, tmp_path, monkeypatch):
    from datetime import UTC, datetime
    from test_collector_knowledge_scope import service_and_detail
    from packages.orchestrator.service import RunRecord
    from packages.research.models import ResearchResult
    from packages.research.evidence.admission import raw_sources_from_research_result
    from packages.research.evidence.normalization import normalized_fields_from_evidence_items
    from packages.research.question_delivery import _build_question_delivery, _replay_question_delivery
    from packages.knowledge.models import KnowledgeScope
    from packages.knowledge.repository import KnowledgeRepository
    first = 'Members can edit shared documents only with a paid account.'
    additional = 'Guests can view shared documents only when directly invited.'
    body = first + '\n\n' + additional
    brief, candidate, page = source(body, questions=('What rules apply to members and guests?',))
    monkeypatch.setenv('KB_DB_PATH', str(tmp_path / 'same-body.db'))
    monkeypatch.setenv('KB_SEMANTIC_INDEXING', 'false')
    service, detail = service_and_detail()
    detail.plan.competitors = [brief.competitor]
    detail.topic = brief.topic
    documents = []
    for index, quotes in enumerate(([first], [first, additional])):
        detail.id = f'actual-ingest-{index}'
        active = brief.model_copy(update={'run_id': detail.id})
        page.captured_at = datetime.now(UTC)
        from packages.research.capture.official import verify_registered_capture
        page.metadata['official_source_verification'] = verify_registered_capture(brief.competitor, page)
        extraction = semantic.semantic_extraction(active, page, {'facts': [{'quote': quote} for quote in quotes]})
        items = admit_evidence_items([extraction], brief=active, captured_pages=[page], candidates=[candidate])
        assert len(items) == len(quotes) and all(item.status == 'accepted' for item in items)
        result = ResearchResult(brief=active, candidates=[candidate], captured_pages=[page], extractions=[extraction],
            evidence_items=items, normalized_fields=normalized_fields_from_evidence_items(items))
        sources = raw_sources_from_research_result(active, result, batch_sources=[], target_source_count=1,
            requires_accepted_evidence=True, source_exists=lambda *_: False,
            confidence_for_source=lambda *_: .8, fallback_snippet=lambda p: p.text)
        assert sources
        record = RunRecord(detail=detail)
        service._runs[detail.id] = record
        await service._persist_captured_sources_to_kb(record, detail, sources, result)
        detail.raw_sources = sources
        async with KnowledgeRepository() as repo:
            document = await repo.get_document(sources[0].metadata['kb_document_id'],
                scope=KnowledgeScope(workspace_id=detail.workspace_id, project_id=detail.project_id))
        documents.append(document)
        if index == 1:
            capsule = _build_question_delivery(detail, active, result, sources, [])
            replay = _replay_question_delivery(detail, capsule, {document.id: document}, authorized_brief=active)
            new_id = next(item.id for item in items if item.quote == additional)
            actual_ids = {eid for row in document.metadata.get('normalized_fields', []) for eid in row['evidence_item_ids']}
            assert new_id not in actual_ids, 'Fixture must exercise legitimate reuse of older canonical annotations.'
            snapshot = await service._prepare_evidence_snapshot(record, phase='analysis')
            assert any(new_id in fact.evidence_item_ids and fact.quote == additional
                       for fact in snapshot.facts), 'Current RawSource observation failed to reach actual sealed snapshot.'
            assert new_id in replay['verified_item_ids'], replay['item_results']
            assert replay['canonical_annotations'] == 'not_authoritative'
            diagnostic = next(row for row in replay['item_results'] if row['item_id'] == new_id)
            assert diagnostic['canonical_annotation_status'] == 'not_represented'
    assert documents[0].text == documents[1].text == body


def question_association_fixture(source):
    from datetime import UTC, datetime
    from packages.knowledge.models import KnowledgeDocument
    from packages.research.models import ResearchQuestion
    from packages.research.evidence.snapshot import seal_snapshot
    from packages.research.question_delivery import _build_question_delivery
    from packages.schema.api_dto import RunDetail
    from packages.schema.models import AnalysisPlan
    stub, brief, result, sources = delivery_fixture(source)
    brief = brief.model_copy(update={'questions': [*brief.questions,
        ResearchQuestion(question_id='q1', question='Can guests edit shared documents?')]})
    result.brief = brief
    page = result.captured_pages[0]
    document = KnowledgeDocument(id='association-doc', source_type='webpage_verified', title=page.title,
        url=page.final_url, text=page.text, content_hash=hashlib.sha256(page.text.encode()).hexdigest()[:16],
        fetched_at=page.captured_at, workspace_id=stub.workspace_id, project_id=stub.project_id,
        competitor=brief.competitor, dimension=brief.dimension, metadata={**sources[0].metadata,
            'run_id': stub.id, 'raw_source_id': sources[0].id})
    sources[0].metadata.update(kb_document_id=document.id, kb_document_version=document.version,
        kb_document_content_hash=document.content_hash)
    now = datetime.now(UTC)
    detail = RunDetail(id=stub.id, topic=brief.topic, workspace_id=stub.workspace_id,
        project_id=stub.project_id, status='running', execution_mode='real', created_at=now, updated_at=now,
        raw_sources=sources, plan=AnalysisPlan(topic=brief.topic, competitors=[brief.competitor], dimensions=[brief.dimension]))
    capsule = _build_question_delivery(detail, brief, result, sources, [])
    snapshot = seal_snapshot(detail, phase='analysis', canonical_documents={document.id: document})
    return detail, brief, capsule, document, snapshot


@pytest.mark.parametrize('association', ['item_ids', 'recipe_ids', 'capture_ids'])
def test_question_association_cannot_borrow_another_question_producer_after_rehash(source, association):
    from packages.research.question_delivery import _seal_question_delivery
    detail, brief, capsule, document, snapshot = question_association_fixture(source)
    q0, q1 = capsule['questions']
    assert q0['item_ids'] and q0['recipe_ids'] and not q1['item_ids'] and not q1['recipe_ids']
    q1[association] = list(q0[association])
    reseal_receipt(capsule)
    replay = _seal_question_delivery(detail, capsule, {document.id: document}, snapshot, authorized_brief=brief)
    observed = next(row for row in replay['questions'] if row['question_id'] == 'q1')
    assert not observed['ready_item_ids'], observed
    assert observed['association_status'] == 'partial', observed
    assert observed['semantic_status'] == 'unverified'
    assert observed['next_action'] == 'resolve_delivery_gaps'


def test_rehashed_paired_producer_identity_forgery_does_not_replay_as_actual_producer(source):
    from packages.research.question_delivery import _seal_question_delivery
    detail, brief, capsule, document, snapshot = question_association_fixture(source)
    forged = 'extraction-invented-producer'
    capsule['recipes'][0]['id'] = forged
    capsule['items'][0]['metadata']['extraction_id'] = forged
    capsule['questions'][0]['recipe_ids'] = [forged]
    reseal_receipt(capsule)
    replay = _seal_question_delivery(detail, capsule, {document.id: document}, snapshot, authorized_brief=brief)
    assert not replay['verified_item_ids'], replay
    assert any('recipe_identity_mismatch' in row['reasons'] for row in replay['item_results'])
    assert all(not row['ready_item_ids'] and row['semantic_status'] == 'unverified' for row in replay['questions'])


def test_question_associations_come_from_successfully_replayed_focus_and_producer(source):
    from packages.research.question_delivery import _seal_question_delivery
    detail, brief, capsule, document, snapshot = question_association_fixture(source)
    replay = _seal_question_delivery(detail, capsule, {document.id: document}, snapshot, authorized_brief=brief)
    q0, q1 = replay['questions']
    assert q0['ready_item_ids'] == capsule['questions'][0]['item_ids']
    assert q0['recipe_ids'] == capsule['questions'][0]['recipe_ids']
    assert q0['capture_ids'] == capsule['questions'][0]['capture_ids']
    assert not q1['item_ids'] and not q1['ready_item_ids']
    assert all(row['association_status'] == 'verified' and row['semantic_status'] == 'unverified'
               for row in replay['questions'])
    missing = _seal_question_delivery(detail, capsule, {}, snapshot, authorized_brief=brief)
    assert not missing['verified_item_ids']
    assert all(not row['ready_item_ids'] and row['semantic_status'] == 'unverified' for row in missing['questions'])


def test_unknown_claimed_question_producer_is_a_partial_association_after_rehash(source):
    from packages.research.question_delivery import _seal_question_delivery
    detail, brief, capsule, document, snapshot = question_association_fixture(source)
    capsule['questions'][1]['recipe_ids'] = ['extraction-unregistered-producer']
    reseal_receipt(capsule)
    replay = _seal_question_delivery(detail, capsule, {document.id: document}, snapshot, authorized_brief=brief)
    q1 = next(row for row in replay['questions'] if row['question_id'] == 'q1')
    assert q1['association_status'] == 'partial'
    assert not q1['ready_item_ids'] and q1['semantic_status'] == 'unverified'
