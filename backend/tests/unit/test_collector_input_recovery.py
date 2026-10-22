"""Anonymous DOM capture inputs retain source boundaries before semantic selection."""

import hashlib
import importlib
import json

import httpx
import pytest
import test_question_semantic_focus as source_fixtures
from test_partial_report_gaps import fixture as service_fixture

from packages.agents import SubagentContext
from packages.crawler.policy import SSRFGuard
from packages.research.extraction import semantic
from packages.tools.fetch_page import _capture_html, fetch_page


fetch_module = importlib.import_module('packages.tools.fetch_page')
source = source_fixtures.source
PREREQUISITE = 'Guests require an invitation and an active account to access boards.'
CAPABILITY = 'Reviewers can comment on cards only when comments are enabled for the board.'
RESTRICTION = 'Reviewers cannot edit cards or change the settings of a board.'


def document(flow='div', *, extra='', outside=''):
    def block(text):
        if flow == 'main_text':
            return text
        if flow == 'nested':
            return '<div><span>' + text + '</span></div>'
        return f'<{flow}>' + text + f'</{flow}>'

    return ('<html><head><title>Example Suite guest access</title></head><body>'
            '<nav><h2>Menu</h2>Navigation content must stay outside.</nav>'
            '<main><h1>Guest access</h1>' + block(PREREQUISITE)
            + '<h2>Reviewers</h2>' + block(CAPABILITY)
            + '<h2>Restrictions</h2>' + block(RESTRICTION) + extra + '</main>'
            + outside + '<footer>Footer content must stay outside.</footer></body></html>')


def captured(source, markup):
    body, headings, metadata = _capture_html(markup)
    brief, candidate, page = source(body, questions=(
        'Can reviewers comment on cards?', 'Can reviewers edit cards?'), headings=headings)
    page.metadata.update(metadata)
    return brief, candidate, page


@pytest.mark.parametrize('flow', ['div', 'nested', 'span', 'main_text'])
def test_visible_flow_capture_binds_every_original_heading_and_condition(source, flow):
    brief, _, page = captured(source, document(flow))
    assert page.metadata['capture_gaps'] == []
    assert page.metadata['capture_incomplete'] is False
    assert semantic._heading_resolution(page.text, page)['valid']
    assert semantic.semantic_body_window(brief, page) == page.text
    expected = ['Guest access', PREREQUISITE, 'Reviewers', CAPABILITY,
                'Restrictions', RESTRICTION]
    assert page.text.splitlines() == expected
    anchors = page.metadata['document_heading_anchors']
    assert [item['source_path'] for item in anchors] == ['/main/h1', '/main/h2[1]', '/main/h2[2]']
    assert all(item['content_sha256'] == hashlib.sha256(page.text.encode()).hexdigest()
               and page.text[item['start']:item['end']] == item['title'] for item in anchors)
    if flow in {'div', 'nested'}:
        assert page.metadata['heading_capture_recovery'] == 'visible_dom_replay_after_unbound_boundary'


def test_recovered_repeated_headings_keep_distinct_dom_occurrences(source):
    extra = '<h2>Reviewers</h2><div>Reviewers can download attachments when access is granted.</div>'
    brief, _, page = captured(source, document(extra=extra))
    assert page.metadata['capture_gaps'] == []
    assert semantic._heading_resolution(page.text, page)['valid']
    anchors = [item for item in page.metadata['document_heading_anchors'] if item['title'] == 'Reviewers']
    assert [item['occurrence'] for item in anchors] == [1, 2]
    assert anchors[0]['source_path'] != anchors[1]['source_path']
    assert anchors[0]['start'] < page.text.index(CAPABILITY) < anchors[1]['start']
    assert semantic.semantic_body_window(brief, page) == page.text


def test_recovery_cannot_include_hidden_navigation_or_outside_root_text(source):
    extra = ('<div hidden><h2>Hidden section</h2>Hidden permission must stay outside.</div>'
             '<div aria-hidden="true">Aria permission must stay outside.</div>'
             '<div style="display:none">Styled permission must stay outside.</div>')
    outside = '<aside><h2>Other product</h2>Outside permission must stay outside.</aside>'
    _, _, page = captured(source, document(extra=extra, outside=outside))
    assert page.metadata['capture_gaps'] == []
    assert PREREQUISITE in page.text and CAPABILITY in page.text and RESTRICTION in page.text
    assert 'stay outside' not in page.text and 'Hidden section' not in page.text
    assert 'Other product' not in page.text


def test_dom_replay_does_not_add_explicit_aria_navigation(source):
    extra = ('<div role="navigation"><h2>Navigation</h2>'
             '<a href="/other">Other product access guide</a></div>'
             '<div role="region"><h2>Download permissions</h2>'
             '<div>Only invited reviewers can download attachments.</div></div>')
    brief, _, page = captured(source, document(extra=extra))
    assert 'Other product access guide' not in page.text
    assert 'Navigation' not in [item[1] for item in page.metadata['document_headings']]
    assert page.metadata['capture_gaps'] == []
    assert semantic._heading_resolution(page.text, page)['valid']
    assert semantic.semantic_body_window(brief, page) == page.text
    assert all(part in page.text for part in (PREREQUISITE, CAPABILITY, RESTRICTION))
    assert 'Download permissions' in page.text
    assert 'Only invited reviewers can download attachments.' in page.text


@pytest.mark.asyncio
@pytest.mark.parametrize('role', [' navigation ', 'navigation\t', 'navigation banner'])
async def test_navigation_tokens_never_enter_actual_collector_body(source, monkeypatch, role):
    extra = ('<div role="' + role + '"><h2>Navigation</h2>'
             '<a href="/other">Other product access guide</a></div>')
    brief, _, page = captured(source, document(extra=extra))
    service, detail = service_fixture()
    record = service._runs[detail.id]
    context = SubagentContext(run_id=detail.id, agent='collector', subagent='feature_Example Suite')
    received = []

    async def complete(_record, **kwargs):
        received.append(json.loads(kwargs['user'])['body'])
        return {'facts': []}

    monkeypatch.setattr(service, '_trace_llm_json', complete)
    await service._collector_semantic_extract(record, brief, page, context)
    assert len(received) == 1 and received[0]
    assert 'Other product access guide' not in received[0]
    assert 'Navigation' not in [item['title'] for item in page.metadata['document_heading_anchors']]
    assert all(part in received[0] for part in (PREREQUISITE, CAPABILITY, RESTRICTION))


@pytest.mark.asyncio
@pytest.mark.parametrize('extra', [
    '<details><div>Export requires owner permission.</div></details>',
    '<details><summary hidden>Can reviewers export?</summary>'
    '<div>Export requires owner permission.</div></details>',
])
async def test_unrecorded_details_keep_actual_collector_body_empty(source, monkeypatch, extra):
    brief, _, page = captured(source, document(extra=extra))
    assert page.metadata['disclosures'] == []
    service, detail = service_fixture()
    record = service._runs[detail.id]
    context = SubagentContext(run_id=detail.id, agent='collector', subagent='feature_Example Suite')
    received = []

    async def complete(_record, **kwargs):
        received.append(json.loads(kwargs['user'])['body'])
        return {'facts': []}

    monkeypatch.setattr(service, '_trace_llm_json', complete)
    extraction = await service._collector_semantic_extract(record, brief, page, context)
    assert received == []
    assert extraction is None and record.semantic_extraction_cache == {}
    assert 'heading_capture_recovery' not in page.metadata
    assert page.metadata['capture_incomplete'] is True
    assert 'heading_source_boundary_unbound' in page.metadata['capture_gaps']
    assert page.metadata['document_heading_anchors'] == []
    assert semantic.semantic_body_window(brief, page) == ''
    assert detail.trace_spans[-1].metadata['reason'] == 'empty_semantic_body_window'


@pytest.mark.asyncio
@pytest.mark.parametrize('extra,gap', [
    ('<button aria-expanded="false" aria-controls="missing">Can reviewers export?</button>',
     'missing_disclosure_panel'),
    ('<button aria-expanded="false" aria-controls="duplicate">Can reviewers export?</button>'
     '<div id="duplicate" hidden>Export requires approval.</div>'
     '<div id="duplicate" hidden>Export is disabled.</div>', 'ambiguous_disclosure_panel'),
])
async def test_incomplete_disclosure_keeps_refusal_before_collector_model(source, monkeypatch, extra, gap):
    brief, _, page = captured(source, document(extra=extra))
    assert gap in page.metadata['capture_gaps']
    service, detail = service_fixture()
    record = service._runs[detail.id]
    context = SubagentContext(run_id=detail.id, agent='collector', subagent='feature_Example Suite')
    calls = []

    async def complete(_record, **kwargs):
        calls.append(json.loads(kwargs['user'])['body'])
        return {'facts': []}

    monkeypatch.setattr(service, '_trace_llm_json', complete)
    extraction = await service._collector_semantic_extract(record, brief, page, context)
    assert calls == []
    assert extraction is None and record.semantic_extraction_cache == {}
    assert 'heading_capture_recovery' not in page.metadata
    assert page.metadata['capture_incomplete'] is True
    assert 'heading_source_boundary_unbound' in page.metadata['capture_gaps']
    assert page.metadata['document_heading_anchors'] == []
    assert semantic.semantic_body_window(brief, page) == ''
    assert detail.trace_spans[-1].metadata['reason'] == 'empty_semantic_body_window'


def test_replay_keeps_direct_tail_conditions_and_nested_flow_in_dom_order(source):
    extra = ('<h2>Downloads</h2><div>Reviewers can download attachments.</div>'
             ' Only invited reviewers can download attachments.'
             '<div><span>Downloaded attachments retain</span> their original permissions.</div>')
    brief, _, page = captured(source, document(extra=extra))
    assert page.metadata['capture_gaps'] == []
    expected = ['Downloads', 'Reviewers can download attachments.',
                'Only invited reviewers can download attachments.',
                'Downloaded attachments retain', 'their original permissions.']
    assert page.text.splitlines()[-len(expected):] == expected
    assert semantic.semantic_body_window(brief, page) == page.text


@pytest.mark.parametrize('kind', ['details', 'aria_controls'])
def test_dom_replay_keeps_complete_disclosure_question_answer_and_offsets(source, kind):
    question = 'Can guests export cards?'
    answer = 'Guests can export cards only when the owner enables exports.'
    if kind == 'details':
        extra = ('<h2>Guest export</h2><details><summary>' + question
                 + '</summary><p>' + answer + '</p></details>')
    else:
        extra = ('<h2>Guest export</h2><button aria-expanded="false" aria-controls="export-panel">'
                 + question + '</button><div id="export-panel" hidden>' + answer + '</div>')
    brief, _, page = captured(source, document(extra=extra))
    assert page.metadata['capture_gaps'] == []
    record = page.metadata['disclosures'][0]
    assert record['status'] == 'complete'
    assert record['quote'] == question + '\n' + answer
    assert page.text[record['quote_start']:].startswith(record['quote'])
    assert record['quote_hash'] == hashlib.sha256(record['quote'].encode()).hexdigest()[:16]
    assert semantic._heading_resolution(page.text, page)['valid']
    assert record['quote'] in semantic.semantic_body_window(brief, page)


def test_ambiguous_roots_are_not_eligible_for_capture_recovery(source):
    markup = document(outside='<main><h1>Another guide</h1><div>Other source text.</div></main>')
    _, _, page = captured(source, markup)
    assert page.metadata['capture_incomplete'] is True
    assert 'ambiguous_content_root' in page.metadata['capture_gaps']
    assert 'heading_capture_recovery' not in page.metadata


def test_unbound_page_with_table_retains_original_rows_and_capture_gap(source):
    extra = ('<h2>Rates</h2><table><tr><th>Plan</th><th>Price</th></tr>'
             '<tr><td>Launch</td><td>$17 per user per month</td></tr></table>'
             '<p>Requires annual billing.</p>')
    brief, _, page = captured(source, document(extra=extra))
    assert '| Plan | Price |' in page.text
    assert '| Launch | $17 per user per month |' in page.text
    assert 'Requires annual billing.' in page.text
    assert 'heading_capture_recovery' not in page.metadata
    assert 'heading_source_boundary_unbound' in page.metadata['capture_gaps']
    assert semantic.semantic_body_window(brief, page) == ''


@pytest.mark.parametrize('change', ['source_path', 'content', 'anchor_version'])
def test_recovered_heading_identity_cannot_be_tampered_with(source, change):
    brief, _, page = captured(source, document())
    assert semantic._heading_resolution(page.text, page)['valid']
    if change == 'source_path':
        page.metadata['document_heading_anchors'][1]['source_path'] = '/main/h1'
    elif change == 'anchor_version':
        page.metadata['document_heading_anchors'][0]['content_sha256'] = 'stale-source-version'
    else:
        page.text += '\nChanged source content.'
    assert not semantic._heading_resolution(page.text, page)['valid']
    assert semantic.semantic_body_window(brief, page) == ''


def test_marker_capture_drift_does_not_trigger_dom_replay(source, monkeypatch):
    original = fetch_module.trafilatura_extract
    calls = []

    def changed_capture(*args, **kwargs):
        calls.append(True)
        value = original(*args, **kwargs) or ''
        return value + '\nUnrelated injected block.' if len(calls) == 2 else value

    monkeypatch.setattr(fetch_module, 'trafilatura_extract', changed_capture)
    brief, _, page = captured(source, document())
    assert len(calls) == 2
    assert 'Unrelated injected block.' not in page.text
    assert 'heading_markers_changed_capture' in page.metadata['capture_gaps']
    assert 'heading_capture_recovery' not in page.metadata
    assert semantic.semantic_body_window(brief, page) == ''


@pytest.mark.asyncio
async def test_actual_capture_supplies_nonempty_complete_body_to_collector(source, monkeypatch):
    def resolver(_host, port, *_args, **_kwargs):
        return [(2, 1, 6, '', ('93.184.215.14', port))]

    result = await fetch_page('https://docs.example-suite.test/access',
        guard=SSRFGuard(resolver=resolver), transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=document(), headers={'content-type': 'text/html'})))
    brief, _, page = source(result.text, questions=(
        'Can reviewers comment on cards?', 'Can reviewers edit cards?'), headings=result.document_headings)
    page.metadata.update(result.capture_metadata)
    service, detail = service_fixture()
    record = service._runs[detail.id]
    context = SubagentContext(run_id=detail.id, agent='collector', subagent='feature_Example Suite')
    received = []

    async def complete(_record, **kwargs):
        received.append(json.loads(kwargs['user'])['body'])
        return {'facts': [{'quote': CAPABILITY}]}

    monkeypatch.setattr(service, '_trace_llm_json', complete)
    extraction = await service._collector_semantic_extract(record, brief, page, context)
    assert received == [page.text] and received[0]
    assert all(part in received[0] for part in (PREREQUISITE, CAPABILITY, RESTRICTION))
    assert extraction is not None and extraction.fields


@pytest.mark.asyncio
async def test_empty_semantic_window_skips_model_without_spending_page_budget(source, monkeypatch):
    brief, _, page = captured(source, document())
    page.metadata['document_heading_anchors'] = []
    page.metadata.update(capture_incomplete=True, capture_gaps=['heading_identity_not_captured'])
    assert semantic.semantic_page_allowed(brief, page)
    assert semantic.semantic_body_window(brief, page) == ''
    service, detail = service_fixture()
    record = service._runs[detail.id]
    context = SubagentContext(run_id=detail.id, agent='collector', subagent='feature_Example Suite')
    calls = []

    async def complete(_record, **kwargs):
        calls.append(kwargs)
        return {'facts': []}

    monkeypatch.setattr(service, '_trace_llm_json', complete)
    before = list(detail.raw_sources)
    assert await service._collector_semantic_extract(record, brief, page, context) is None
    assert calls == []
    assert record.semantic_extraction_cache == {}
    assert detail.raw_sources == before
    diagnostic = detail.trace_spans[-1]
    assert diagnostic.kind == 'tool' and diagnostic.name == 'collector_semantic_extract_skipped'
    assert diagnostic.metadata['reason'] == 'empty_semantic_body_window'
    assert diagnostic.metadata['extraction_status'] == 'skipped'
    assert json.loads(diagnostic.output_preview)['capture_gaps'] == ['heading_identity_not_captured']
