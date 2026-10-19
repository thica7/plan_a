"""Anonymous source headings retain identity across capture and evidence replay."""

import copy
import hashlib
import importlib
import json
from datetime import UTC, datetime

import pytest
import test_question_semantic_focus as source_fixtures

from packages.agents.writer.answer_coverage import question_fact_ids
from packages.agents import SubagentContext
from packages.knowledge.models import DocumentCreate
from packages.knowledge.repository import KnowledgeRepository
from packages.research.evidence import admit_evidence_items
from packages.research.evidence.admission import raw_sources_from_research_result
from packages.research.evidence.normalization import normalized_fields_from_evidence_items
from packages.research.evidence.snapshot import seal_snapshot
from packages.research.evidence.views import select_evidence_view
from packages.research.extraction import semantic
from packages.research.extraction.structured_evidence import extract_structured_evidence
from packages.research.models import ResearchResult
from packages.schema.api_dto import RunDetail
from packages.schema.models import AnalysisPlan, DecisionBrief
from packages.tools.deepseek_fetch import _markdown_heading_anchors
from packages.tools.fetch_page import _capture_html

fetch_page_module = importlib.import_module('packages.tools.fetch_page')

source = source_fixtures.source
QUESTION = 'What is the monthly billing for Compute Paid Standard?'
MINIMUM = 'The Compute Paid plan has a minimum account charge of $13 USD per month.'
HEADER = '| Plan | Requests1, 2 | CPU time* |'
ROW = ('| Standard | 12 million included +$0.42 per million requests | '
       '20 million CPU milliseconds included +$0.03 per million CPU milliseconds |')
NOTES = ['1 Only inbound requests are billed.',
         '2 An upgrade connection is charged as a request,\nrepresenting the initial connection.\n'
         'Messages do not count as requests.',
         '* CPU time is only billed when the function runs.']


def html_source():
    return ('<html><body><nav><h2>Compute</h2>Navigation only.</nav><main><h1>Pricing</h1><p>'
            + MINIMUM + '</p><h2>Compute</h2><p>Users on Compute Paid can use the Standard usage model.</p>'
            '<table><thead><tr><th>Plan</th><th>Requests1, 2</th><th>CPU time*</th></tr></thead>'
            '<tbody><tr><td>Standard</td><td>12 million included +$0.42 per million requests</td>'
            '<td>20 million CPU milliseconds included +$0.03 per million CPU milliseconds</td>'
            '</tr></tbody></table>' + ''.join('<p>' + note.replace('\n', '<br>') + '</p>' for note in NOTES)
            + '<h2>Compute Logs</h2><p>Compute Logs costs $0.71 per million requests.</p>'
            '<h2>Footnotes</h2><details><summary>Footnotes</summary><p>'
            '1 Only active Compute Logs requests are billed.</p></details>'
            '<h2>Archive</h2><p>Archive storage costs $0.20 per GB-month.</p></main>'
            '<footer><h2>Compute</h2>Footer only.</footer></body></html>')


def captured_source(source, html=None):
    body, headings, metadata = _capture_html(html or html_source())
    brief, candidate, page = source(body, questions=(QUESTION,), headings=headings)
    page.metadata.update(metadata)
    return brief, candidate, page


def test_capture_binds_heading_before_identical_disclosure_summary(source):
    _, _, page = captured_source(source)
    anchors = page.metadata.get('document_heading_anchors')
    assert anchors, 'Capture lost the original DOM heading identities.'
    assert page.text.count('Footnotes\n') == 2
    anchor = next(item for item in anchors if item['title'] == 'Footnotes')
    assert anchor['start'] == page.text.index('Footnotes\n')
    assert anchor['end'] == anchor['start'] + len('Footnotes')
    assert anchor['content_sha256'] == hashlib.sha256(page.text.encode()).hexdigest()
    assert len({item['source_path'] for item in anchors}) == len(anchors)
    assert semantic._heading_resolution(page.text, page)['valid']
    assert 'Navigation only' not in page.text and 'Footer only' not in page.text


def test_capture_preserves_all_heading_levels_and_repeated_dom_heading_identity(source):
    html = '<main>' + ''.join(f'<h{level}>Shared</h{level}><p>Original content block number {level} remains.</p>'
                              for level in range(1, 7)) + '</main>'
    _, _, page = captured_source(source, html)
    anchors = page.metadata.get('document_heading_anchors')
    assert anchors and [item['level'] for item in anchors] == list(range(1, 7))
    assert [item['occurrence'] for item in anchors] == list(range(1, 7))
    assert [item['start'] for item in anchors] == sorted(item['start'] for item in anchors)
    assert semantic._heading_resolution(page.text, page)['valid']


@pytest.mark.parametrize('flow', ['div', 'section', 'span', 'main_text'])
def test_unbound_retained_flow_text_cannot_move_omitted_headings_past_their_content(source, flow):
    def block(value):
        if flow == 'main_text':
            return value
        return f'<{flow}>' + value + f'</{flow}>'

    rates = 'Compute Standard costs $0.42 per million requests. CPU time costs $0.03 per million CPU milliseconds.'
    markup = '<main><h1>Pricing</h1>' + block(MINIMUM) + '<h2>Compute</h2>' + block(rates)
    markup += '<h2>Compute Logs</h2>' + block('Compute Logs costs $0.71 per million requests.') + '</main>'
    brief, _, page = captured_source(source, markup)
    if page.metadata['capture_incomplete']:
        assert 'heading_source_boundary_unbound' in page.metadata['capture_gaps']
        assert not semantic._heading_resolution(page.text, page)['valid']
        assert semantic.semantic_body_window(brief, page) == ''
    else:
        assert page.text.index('Pricing\n') < page.text.index(MINIMUM) < page.text.index('Compute\n')
        assert page.text.index('Compute\n') < page.text.index(rates) < page.text.index('Compute Logs\n')
        window = semantic.semantic_body_window(brief, page)
        assert MINIMUM in window and rates in window


@pytest.mark.parametrize('change', ['missing', 'null'])
def test_all_html_dom_paths_cannot_be_removed_to_create_pathless_plain_anchors(source, change):
    brief, _, page = captured_source(source)
    assert page.metadata['capture_structure_version'] == 1
    for anchor in page.metadata['document_heading_anchors']:
        if change == 'missing':
            anchor.pop('source_path')
        else:
            anchor['source_path'] = None
    assert not semantic._heading_resolution(page.text, page)['valid']
    assert semantic.semantic_body_window(brief, page) == ''


def test_headless_html_code_comment_is_not_a_markdown_heading(source):
    quote = 'Guests can export content only on a paid plan.'
    body, headings, metadata = _capture_html('<main><p>' + quote + '</p>'
        '<pre><code># Export example\nexport_document()</code></pre>'
        '<p>Exports require owner permission.</p></main>')
    brief, _, page = source(body, questions=('Can guests export content on paid plans?',), headings=headings)
    page.metadata.update(metadata)
    assert headings == () and metadata['document_heading_anchors'] == []
    assert metadata['capture_gaps'] == [] and '# Export example' in body
    assert semantic._heading_resolution(body, page)['valid']
    assert semantic.semantic_body_window(brief, page) == body
    markdown = page.model_copy(deep=True)
    markdown.metadata.pop('capture_structure_version')
    markdown.metadata.pop('content_root')
    assert not semantic._heading_resolution(body, markdown)['valid']
    assert semantic.semantic_body_window(brief, markdown) == ''


def markdown_source(source):
    body = '# Pricing\n' + MINIMUM + '\n## Compute\n' + HEADER + '\n|---|---|---|\n' + ROW
    body += '\n' + '\n'.join(NOTES) + '\n## Compute Logs\nCompute Logs costs $0.71 per million requests.\n'
    body += '## Footnotes\nFootnotes\n1 Only active Compute Logs requests are billed.\n'
    body += '## Archive\nArchive storage costs $0.20 per GB-month.\n'
    anchors = _markdown_heading_anchors(body, hashlib.sha256(body.encode()).hexdigest())
    headings = [(item['level'], item['title']) for item in anchors]
    brief, candidate, page = source(body, questions=(QUESTION,), headings=headings)
    page.metadata['document_heading_anchors'] = anchors
    return brief, candidate, page


def test_existing_markdown_anchors_locate_full_prefixed_heading_lines(source):
    brief, _, page = markdown_source(source)
    assert semantic._heading_resolution(page.text, page)['valid']
    window = semantic.semantic_body_window(brief, page)
    assert ROW in window and MINIMUM in window
    assert '$0.71' not in window and '$0.20' not in window
    assert window in page.text and len(window) <= semantic.MAX_INPUT_CHARS


@pytest.mark.parametrize('change', ['stale', 'offset', 'partial', 'level', 'title', 'order',
                                  'occurrence', 'identity', 'missing', 'malformed', 'fenced'])
def test_wrong_or_incomplete_anchors_never_fall_back_to_legacy_guessing(source, change):
    brief, _, page = markdown_source(source)
    anchors = page.metadata['document_heading_anchors']
    if change == 'stale':
        page.text += '\nA changed source paragraph.'
    elif change == 'offset':
        anchors[1]['start'] += 1
    elif change == 'partial':
        anchors[1]['end'] -= 1
    elif change == 'level':
        anchors[1]['level'] = 3
    elif change == 'title':
        anchors[1]['title'] = 'Other'
    elif change == 'order':
        anchors[1], anchors[2] = anchors[2], anchors[1]
    elif change == 'occurrence':
        anchors[1]['occurrence'] = 2
    elif change == 'identity':
        anchors[2] = copy.deepcopy(anchors[1])
    elif change == 'missing':
        anchors.pop()
    elif change == 'malformed':
        page.metadata['document_heading_anchors'] = None
    else:
        page.text = '```\n' + page.text + '```\n'
        digest = hashlib.sha256(page.text.encode()).hexdigest()
        for anchor in anchors:
            anchor.update(start=anchor['start'] + 4, end=anchor['end'] + 4, content_sha256=digest)
    assert semantic.semantic_body_window(brief, page) == ''
    assert not semantic._heading_resolution(page.text, page)['valid']


def test_legacy_ambiguous_heading_keeps_gap(source):
    brief, _, page = source('Pricing\nCompute\n' + MINIMUM + '\nCompute Logs\nFootnotes\nFootnotes\n',
        questions=(QUESTION,), headings=[(1, 'Pricing'), (2, 'Compute'), (2, 'Compute Logs'), (2, 'Footnotes')])
    assert semantic.semantic_body_window(brief, page) == ''


@pytest.mark.parametrize('change', ['extra_block', 'answer_substring'])
def test_marker_selection_drift_is_a_gap_and_retains_the_original_capture(source, monkeypatch, change):
    original = fetch_page_module.trafilatura_extract
    calls = []

    def changed_capture(*args, **kwargs):
        calls.append(True)
        text = original(*args, **kwargs) or ''
        if len(calls) == 2:
            return (text + '\nAn unrelated extra source block.' if change == 'extra_block' else
                    text.replace('Yes, original condition restricts export.', ', original condition restricts export.'))
        return text

    monkeypatch.setattr(fetch_page_module, 'trafilatura_extract', changed_capture)
    html = html_source().replace('</main>', '<p>Yes, original condition restricts export.</p>'
        '<details><summary>Is access enabled?</summary><p>Yes</p></details></main>')
    brief, _, page = captured_source(source, html)
    assert 'An unrelated extra source block.' not in page.text
    assert 'heading_markers_changed_capture' in page.metadata['capture_gaps']
    assert page.metadata['capture_incomplete'] is True
    assert semantic.semantic_body_window(brief, page) == ''


@pytest.mark.parametrize('change', ['duplicate_path', 'partial_line', 'bool_offset', 'out_of_range'])
def test_html_anchors_require_unique_identity_and_complete_title_line(source, change):
    brief, _, page = captured_source(source)
    anchors = page.metadata['document_heading_anchors']
    if change == 'duplicate_path':
        anchors[1]['source_path'] = anchors[0]['source_path']
    elif change == 'bool_offset':
        anchors[0]['start'] = False
    elif change == 'out_of_range':
        anchors[-1]['end'] = len(page.text) + 1
    else:
        anchors[1]['title'] = 'Comp'
        anchors[1]['end'] = anchors[1]['start'] + len('Comp')
        page.metadata['document_headings'][1] = (2, 'Comp')
    assert not semantic._heading_resolution(page.text, page)['valid']
    assert semantic.semantic_body_window(brief, page) == ''


@pytest.mark.asyncio
@pytest.mark.parametrize('producer', ['native', 'model_entry'])
async def test_capture_native_and_model_replay_survive_canonical_snapshot_writer_selection(source, tmp_path, monkeypatch, producer):
    brief, candidate, page = captured_source(source)
    window = semantic.semantic_body_window(brief, page)
    assert ROW in window and MINIMUM in window and '$0.71' not in window
    native = extract_structured_evidence(brief, page)
    replay = semantic.semantic_extraction(brief, page, {'facts': [{'quote': ROW}, {'quote': MINIMUM}]})
    assert [quote.text for quote in native.quotes] == [ROW]
    assert len(replay.fields) == 2
    header = next(line for line in page.text.splitlines() if line.startswith(HEADER))
    assert next(iter(native.fields.values()))['table_context'] == [header, *NOTES]
    extraction = native
    if producer == 'model_entry':
        from test_partial_report_gaps import fixture as service_fixture
        service, detail = service_fixture()
        received = []

        async def complete(record, **kwargs):
            body = json.loads(kwargs['user'])['body']
            received.append(body)
            assert all(part in body for part in [ROW, header, MINIMUM, *NOTES])
            assert '$0.71' not in body and '$0.20' not in body
            assert body in page.text and len(body) <= semantic.MAX_INPUT_CHARS
            assert kwargs['max_output_tokens'] == 1600
            return {'facts': [{'quote': ROW}]}

        monkeypatch.setattr(service, '_trace_llm_json', complete)
        extraction = await service._collector_semantic_extract(service._runs[detail.id], brief, page,
            SubagentContext(run_id=detail.id, agent='collector', subagent='feature_Example Suite'))
        assert received and extraction and extraction.fields
    items = admit_evidence_items([extraction], brief=brief, captured_pages=[page], candidates=[candidate])
    assert items and all(item.status == 'accepted' for item in items)
    research = ResearchResult(brief=brief, candidates=[candidate], captured_pages=[page],
        extractions=[extraction], evidence_items=items, normalized_fields=normalized_fields_from_evidence_items(items))
    sources = raw_sources_from_research_result(brief, research, batch_sources=[], target_source_count=1,
        requires_accepted_evidence=True, source_exists=lambda *_: False,
        confidence_for_source=lambda *_: .9, fallback_snippet=lambda capture: capture.text)
    assert len(sources) == 1
    now = datetime.now(UTC)
    document = DocumentCreate(workspace_id='default-workspace', title=page.title, url=str(page.final_url),
        source_type='webpage_verified', competitor=brief.competitor, dimension='feature', text=page.text,
        fetched_at=now, last_verified_at=now, metadata=page.metadata)
    async with KnowledgeRepository(str(tmp_path / 'canonical.sqlite')) as repository:
        stored = await repository.upsert_document(document, page.content_hash)
        loaded = await repository.get_document(stored.id)
    assert loaded and loaded.text == page.text
    sources[0].metadata.update(kb_document_id=loaded.id, kb_document_version=loaded.version,
                              kb_document_content_hash=loaded.content_hash)
    detail = RunDetail(id=brief.run_id, topic=brief.topic, status='running', execution_mode='real',
        created_at=now, updated_at=now, raw_sources=sources,
        plan=AnalysisPlan(topic=brief.topic, competitors=[brief.competitor], dimensions=['feature'],
                          decision_brief=DecisionBrief(decision_question=QUESTION)))
    snapshot = seal_snapshot(detail, phase='analysis', canonical_documents={loaded.id: loaded})
    fact_ids = question_fact_ids(detail, snapshot, brief.competitor, 'feature')
    view = select_evidence_view(snapshot, agent='writer', competitor=brief.competitor,
        dimension='feature', fact_ids=fact_ids)
    facts = [fact for fact in view.facts if fact.field == 'evidence_terms']
    assert facts and facts[0].quote == ROW
    assert facts[0].qualifiers['table_context'] == [header, *NOTES]
    assert MINIMUM in '\n'.join(json.loads(facts[0].value_json))
    assert facts[0].source_id == sources[0].id
    terms = ' '.join(' '.join(json.loads(facts[0].value_json)).split())
    assert all(' '.join(part.split()) in terms for part in [header, MINIMUM, *NOTES])
    prompt = json.loads(view.to_prompt_json())

    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for item in value.values():
                yield from strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)

    prompt_text = ' '.join(' '.join(strings(prompt)).split())
    assert all(' '.join(part.split()) in prompt_text for part in [ROW, header, MINIMUM, *NOTES])
    with pytest.raises(ValueError, match='byte budget'):
        select_evidence_view(snapshot, agent='writer', competitor=brief.competitor,
            dimension='feature', fact_ids=fact_ids, max_bytes=100)


@pytest.mark.parametrize('change', ['footnote', 'unit', 'wrong_service', 'oversized', 'tampered_anchor'])
def test_restored_identity_keeps_billing_integrity_gates(source, change):
    brief, candidate, page = captured_source(source)
    if change == 'wrong_service':
        quote = 'Compute Logs costs $0.71 per million requests.'
    else:
        quote = ROW
    if change in {'footnote', 'unit', 'oversized'}:
        html = html_source()
        if change == 'footnote':
            html = html.replace('<p>' + NOTES[0] + '</p>', '')
        elif change == 'unit':
            html = html.replace('20 million CPU milliseconds included +$0.03 per million CPU milliseconds',
                                '20 million requests included +$0.03 per million requests')
            quote = quote.replace('20 million CPU milliseconds included +$0.03 per million CPU milliseconds',
                                  '20 million requests included +$0.03 per million requests')
        else:
            html = html.replace('<h2>Compute Logs</h2>', '<p>' + 'Original explanatory sentence. ' * 500 + '</p><h2>Compute Logs</h2>')
        brief, candidate, page = captured_source(source, html)
    elif change == 'tampered_anchor':
        page.metadata['document_heading_anchors'][1]['start'] += 1
    extraction = semantic.semantic_extraction(brief, page, {'facts': [{'quote': quote}]})
    items = admit_evidence_items([extraction], brief=brief, captured_pages=[page], candidates=[candidate])
    assert not any(item.status == 'accepted' for item in items)
