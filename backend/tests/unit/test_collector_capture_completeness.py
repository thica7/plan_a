from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path

import httpx
import pytest

import packages.tools.evidence_fetch as evidence_fetch
from packages.crawler.policy import SSRFGuard
from packages.research.capture.webfetch_adapter import fetch_candidate_page
from packages.research.models import SourceCandidate
from packages.tools.fetch_page import fetch_page

URL = "https://example.com/guide"
COPY = "Shared documents provide comments and controlled access for every project. " * 8
QUESTION = "Can a guest collaborate?"
ANSWER = "Guests can comment only when an owner grants comment access."


def _document(content: str, *, outside: str = "") -> str:
    return f"<html><head><title>Collaboration guide</title></head><body><main><h1>Guide</h1><p>{COPY}</p>{content}</main>{outside}</body></html>"


def _accordion(answer: str = ANSWER) -> str:
    return f'<h2><button id="guest-q" aria-expanded="false" aria-controls="guest-a">{QUESTION}</button></h2><div id="guest-a" role="region" aria-labelledby="guest-q" aria-hidden="true">{answer}</div>'


async def _capture(monkeypatch, body: str, *, allow_advanced=False, browser_body=None, browser_failure=None,
                   url=URL, competitor=""):
    requests = []
    browser_calls = []

    def resolver(_host, port, *_args, **_kwargs):
        return [(2, 1, 6, "", ("93.184.215.14", port))]

    def http_handler(request):
        requests.append(str(request.url))
        return httpx.Response(200, text=body, headers={"Content-Type": "text/html"})

    async def basic(url, **kwargs):
        return await fetch_page(url, **kwargs, guard=SSRFGuard(resolver=resolver),
                                transport=httpx.MockTransport(http_handler))

    class Process:
        returncode = 0

        async def communicate(self):
            if browser_failure:
                payload = {"ok": False, "diagnostics": {"failure_reason": browser_failure}}
            else:
                from webfetch_v2.extract import extract_best_content
                extraction = extract_best_content(browser_body, "Collaboration guide", status_code=200)
                # Deliberately model the browser inner_text result without a closed panel.
                payload = {"url": url, "final_url": url, "ok": True, "fetch_method": "browser",
                           "title": "Collaboration guide", "text": COPY,
                           "status_code": 200, "content_type": "text/html",
                           "quality": {"score": .95, "text_length": len(COPY)},
                           "extraction": asdict(extraction.extraction)}
            return json.dumps(payload).encode(), b""

    async def subprocess(*args, **_kwargs):
        browser_calls.append(args[args.index("--mode") + 1])
        if browser_body is None and not browser_failure:
            raise AssertionError("Unexpected advanced fetch")
        return Process()

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "third_party" / "webfetch_v2"))
    monkeypatch.setattr(evidence_fetch, "fetch_page", basic)
    monkeypatch.setattr("packages.tools.advanced_fetch.asyncio.create_subprocess_exec", subprocess)
    result = await evidence_fetch._fetch_evidence_page(url, allow_advanced=allow_advanced)
    page = await fetch_candidate_page(SourceCandidate(title="Guide", url=url, competitor=competitor, origin="web_search"),
                                      lambda _url: _return(result))
    assert requests == [url]
    if page.text:
        assert page.content_hash == hashlib.sha256(page.text.encode()).hexdigest()[:16]
    return result, page, browser_calls


async def _return(value):
    return value


@pytest.mark.asyncio
async def test_plain_page_uses_same_content_root_for_text_and_headings(monkeypatch):
    result, page, calls = await _capture(monkeypatch, _document(
        "<h2>Access</h2><p>Owners grant access to documents for their team.</p>",
        outside="<aside><h2>Help</h2><p>Unrelated help directory.</p></aside><nav><h2>Menu</h2></nav><footer><h2>Legal</h2></footer>"))
    assert "Help" not in [heading[1] for heading in page.metadata["document_headings"]]
    assert "Unrelated help directory" not in page.text
    assert page.metadata["content_root"] == "main"
    assert page.metadata["capture_incomplete"] is False
    assert result.source_material_level == "full_source"
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("markup,kind", [
    (_accordion(), "aria_controls"),
    (f"<details><summary>{QUESTION}</summary><p>{ANSWER}</p></details>", "details"),
])
async def test_restores_complete_source_disclosure_and_persists_diagnostic(monkeypatch, markup, kind):
    result, page, calls = await _capture(monkeypatch, _document(markup))
    assert QUESTION in page.text and ANSWER in page.text
    disclosure = next(item for item in page.metadata["disclosures"] if item["kind"] == kind)
    assert disclosure["question"] == QUESTION
    assert disclosure["answer"] == ANSWER
    assert disclosure["status"] == "complete"
    assert disclosure["quote"] in page.text
    assert page.metadata["capture_incomplete"] is False
    assert result.source_material_level == "full_source"
    assert calls == []


@pytest.mark.asyncio
async def test_empty_panel_retains_partial_capture_when_browser_budget_disallows(monkeypatch):
    result, page, calls = await _capture(monkeypatch, _document(_accordion("")))
    assert len(page.text) > 120
    assert ANSWER not in page.text
    assert page.metadata["capture_incomplete"] is True
    assert page.metadata["disclosures"][0]["reason"] == "empty_disclosure_panel"
    assert result.source_material_level == page.source_material_level == "full_source"
    assert result.advanced_fetch_attempted is False
    assert calls == []


@pytest.mark.asyncio
async def test_long_partial_capture_forces_one_browser_attempt_and_reparses_rendered_html(monkeypatch):
    result, page, calls = await _capture(monkeypatch, _document(_accordion("")),
        allow_advanced=True, browser_body=_document(_accordion()))
    assert calls == ["browser"]
    assert ANSWER in page.text
    assert page.metadata["capture_incomplete"] is False
    assert result.source_material_level == "full_source"
    assert result.text_length == len(result.text)
    assert "source_html" not in json.dumps(page.metadata)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "playwright_not_available"])
async def test_browser_still_empty_or_unavailable_keeps_gap(monkeypatch, failure):
    result, page, calls = await _capture(monkeypatch, _document(_accordion("")),
        allow_advanced=True, browser_body=_document(_accordion("")), browser_failure=failure)
    assert calls == ["browser"]
    assert page.metadata["capture_incomplete"] is True
    assert ANSWER not in page.text
    assert result.source_material_level == "full_source"
    assert result.advanced_fetch_attempted is True


@pytest.mark.asyncio
async def test_unknown_real_peer_heading_in_main_is_preserved(monkeypatch):
    _, page, _ = await _capture(monkeypatch, _document(
        "<h2>Collaboration</h2><p>Owners can invite guests to comment on shared documents.</p>"
        "<h2>Asterism rules</h2><p>Invitations expire when the team owner removes access.</p>"))
    assert (2, "Asterism rules") in page.metadata["document_headings"]
    assert "Asterism rules" in page.text


@pytest.mark.asyncio
@pytest.mark.parametrize("markup,outside", [
    (_accordion() + f'<div id="guest-a" hidden>{ANSWER}</div>', ""),
    (_accordion().replace('id="guest-q"', 'id="guest-q" hidden'), ""),
    (_accordion().replace('id="guest-q"', 'id="guest-q" disabled'), ""),
    (_accordion().replace('id="guest-q"', 'id="guest-q" aria-disabled="true"'), ""),
    (_accordion(""), f'<div id="guest-a" hidden>{ANSWER}</div>'),
    (_accordion().split('<div id="guest-a"')[0], f'<div id="guest-a" hidden>{ANSWER}</div>'),
    (_accordion(), '<nav><div id="guest-a" hidden>Duplicate navigation ID.</div></nav>'),
    (_accordion().replace('aria-expanded="false"', 'role="switch"'), ""),
    (f'<template>{_accordion()}</template><script type="text/html">{_accordion()}</script>', ""),
])
async def test_rejects_ambiguous_hidden_disabled_cross_root_or_non_disclosure_controls(monkeypatch, markup, outside):
    _, page, calls = await _capture(monkeypatch, _document(markup, outside=outside))
    assert ANSWER not in page.text
    assert calls == []


@pytest.mark.asyncio
async def test_disclosure_does_not_restore_unrelated_hidden_price_switch(monkeypatch):
    markup = _accordion(f'<p>{ANSWER}</p><div hidden><p>Alternate price is $999 per month.</p></div>')
    _, page, _ = await _capture(monkeypatch, _document(markup))
    assert ANSWER in page.text
    assert "999" not in page.text


@pytest.mark.asyncio
async def test_multiple_main_roots_remain_explicitly_ambiguous(monkeypatch):
    body = _document("").replace("</body>", "<main><h2>Second guide</h2><p>Second real content.</p></main></body>")
    result, page, _ = await _capture(monkeypatch, body)
    assert "Second real content" in page.text
    assert page.metadata["capture_incomplete"] is True
    assert "ambiguous_content_root" in page.metadata["capture_gaps"]
    assert result.source_material_level == "full_source"


@pytest.mark.asyncio
@pytest.mark.parametrize("extra", [
    '<span id="guest-q">An ambiguous duplicate control ID.</span>',
    f'<button aria-expanded="false" aria-controls="guest-a">{QUESTION}</button>',
])
async def test_duplicate_control_identity_or_relationship_cannot_reveal_hidden_panel(monkeypatch, extra):
    _, page, _ = await _capture(monkeypatch, _document(_accordion() + extra))
    assert ANSWER not in page.text
    assert page.metadata["capture_incomplete"] is True


@pytest.mark.asyncio
async def test_browser_cannot_erase_known_empty_disclosure_by_omitting_it(monkeypatch):
    result, page, calls = await _capture(monkeypatch, _document(_accordion("")),
        allow_advanced=True, browser_body=_document(""))
    assert calls == ["browser"]
    assert page.metadata["capture_incomplete"] is True
    assert result.source_material_level == "full_source"


@pytest.mark.asyncio
async def test_response_byte_limit_is_an_explicit_capture_gap(monkeypatch):
    transport = httpx.MockTransport(lambda request: httpx.Response(200,
        text=_document("") + " " * 300, headers={"Content-Type": "text/html"}))
    guard = SSRFGuard(resolver=lambda _host, port, *_a, **_k: [(2, 1, 6, "", ("93.184.215.14", port))])
    result = await fetch_page(URL, max_bytes=500, transport=transport, guard=guard)
    assert result.capture_metadata["capture_incomplete"] is True
    assert "response_body_truncated" in result.capture_metadata["capture_gaps"]


@pytest.mark.asyncio
async def test_source_html_is_transient_and_absent_from_default_serialization(monkeypatch):
    await _capture(monkeypatch, _document(_accordion("")),
                   allow_advanced=True, browser_body=_document(_accordion()))
    from webfetch_v2.extract import extract_best_content
    from webfetch_v2.fetcher import _failed_result
    extracted = extract_best_content(_document(_accordion()), "Guide", status_code=200)
    result = replace(_failed_result(url=URL, final_url=URL, method="browser", elapsed_ms=0,
                                   reason="test"), extraction=extracted.extraction)
    assert "source_html" not in result.to_dict()["extraction"]
    assert result.to_dict(include_source_html=True)["extraction"]["source_html"] == _document(_accordion())


@pytest.mark.asyncio
async def test_second_folded_faq_is_restored_with_first_faq_and_section_order(monkeypatch):
    first = '<details open><summary>Who grants access?</summary><p>Only the owner can grant access.</p></details>'
    _, page, _ = await _capture(monkeypatch, _document(first + _accordion() +
        '<h2>Retention rules</h2><p>Document retention starts after the team closes the project.</p>'))
    assert "Only the owner can grant access." in page.text
    assert page.text.index(ANSWER) < page.text.index("Retention rules")
    assert len(page.metadata["disclosures"]) == 2


@pytest.mark.asyncio
async def test_cli_opt_in_transports_html_but_cache_never_persists_it(monkeypatch, tmp_path):
    await _capture(monkeypatch, _document(_accordion("")),
                   allow_advanced=True, browser_body=_document(_accordion()))
    from webfetch_v2 import cli
    from webfetch_v2.extract import extract_best_content
    from webfetch_v2.fetcher import _failed_result
    extraction = extract_best_content(_document(_accordion()), "Guide", status_code=200).extraction
    result = replace(_failed_result(url=URL, final_url=URL, method="browser", elapsed_ms=0,
                                   reason="test"), extraction=extraction)
    payloads = []

    async def fake_fetch(*_a, **_k):
        return result

    monkeypatch.setattr(cli, 'fetch_url', fake_fetch)
    monkeypatch.setattr(cli, '_print_json', lambda payload, **_k: payloads.append(payload))
    args = cli.build_parser().parse_args(['fetch', URL, '--include-source-html', '--cache', '--cache-dir', str(tmp_path)])
    await cli.run_fetch(args)
    assert payloads[0]['extraction']['source_html'] == _document(_accordion())
    cached = json.loads(Path(payloads[0]['cache']['result_path']).read_text())
    assert 'source_html' not in cached['extraction']


@pytest.mark.asyncio
async def test_html_transport_limit_counts_bytes_and_records_truncation(monkeypatch):
    await _capture(monkeypatch, _document(_accordion("")),
                   allow_advanced=True, browser_body=_document(_accordion()))
    from webfetch_v2.extract import extract_best_content
    monkeypatch.setattr('webfetch_v2.extract._optional_trafilatura_candidate', lambda _body: [])
    extraction = extract_best_content('<main>' + '界' * 700_000 + '</main>', 'Guide').extraction
    assert len(extraction.source_html.encode()) <= 2_000_000
    assert extraction.source_html_truncated is True


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['details', 'aria_controls'])
@pytest.mark.parametrize('heading', [QUESTION, 'More information'])
async def test_heading_only_disclosure_has_no_answer_or_complete_quote(monkeypatch, kind, heading):
    markup = (f'<details><summary>{QUESTION}</summary><h3>{heading}</h3></details>'
              if kind == 'details' else _accordion(f'<h3>{heading}</h3>'))
    _, page, _ = await _capture(monkeypatch, _document(markup))
    disclosure = page.metadata['disclosures'][0]
    assert disclosure['status'] == 'incomplete'
    assert disclosure['answer'] == disclosure['quote'] == ''
    assert page.metadata['capture_incomplete'] is True


@pytest.mark.asyncio
@pytest.mark.parametrize('attribute', ['hidden', 'aria-hidden="true"', 'style="display:none"',
                                      'class="hidden"', 'class="tw:hidden"'])
async def test_hidden_body_root_exposes_no_text_or_headings(monkeypatch, attribute):
    body = _document('').replace('<body>', f'<body {attribute}>')
    result, page, _ = await _capture(monkeypatch, body)
    assert page.text == ''
    assert page.metadata['document_headings'] == []
    assert result.ok is False


@pytest.mark.asyncio
@pytest.mark.parametrize('css_class', ['hidden', 'tw:hidden'])
async def test_known_hidden_control_class_cannot_reveal_panel(monkeypatch, css_class):
    markup = _accordion().replace('id="guest-q"', f'id="guest-q" class="{css_class}"')
    _, page, _ = await _capture(monkeypatch, _document(markup))
    assert ANSWER not in page.text
    assert not any(item['status'] == 'complete' for item in page.metadata['disclosures'])


@pytest.mark.asyncio
async def test_unrelated_empty_faq_keeps_registered_original_page_material_eligible(monkeypatch):
    from packages.business_intel.official_registry import registered_product
    document = registered_product('Miro').documents[0]
    body = _document(_accordion('')).replace('Collaboration guide', 'Miro guide')
    result, page, _ = await _capture(monkeypatch, body, url=document.url, competitor='Miro')
    assert result.source_material_level == page.source_material_level == 'full_source'
    assert page.status == 'ok'
    assert page.metadata['official_source_verification']['status'] == 'verified'
    assert page.metadata['capture_incomplete'] is True
    assert page.metadata['disclosures'][0]['status'] == 'incomplete'


@pytest.mark.asyncio
async def test_browser_cannot_close_second_same_question_gap_with_first_panel(monkeypatch):
    second = _accordion('').replace('guest-q', 'other-q').replace('guest-a', 'other-a')
    _, page, calls = await _capture(monkeypatch, _document(_accordion() + second),
        allow_advanced=True, browser_body=_document(_accordion()))
    assert calls == ['browser']
    assert page.metadata['capture_incomplete'] is True
    assert any(item.get('panel_id') == 'other-a' and item['status'] == 'incomplete'
               for item in page.metadata['disclosures'])


@pytest.mark.asyncio
async def test_disclosure_heading_with_real_body_retains_full_answer(monkeypatch):
    markup = _accordion(f'<h3>Comment access</h3><p>{ANSWER}</p>').replace(
        'aria-hidden="true"', 'aria-hidden="true" class="tw:hidden"')
    _, page, _ = await _capture(monkeypatch, _document(markup))
    disclosure = page.metadata['disclosures'][0]
    assert disclosure['status'] == 'complete'
    assert disclosure['answer'] == f'Comment access {ANSWER}'
    assert ANSWER in page.text


@pytest.mark.asyncio
async def test_second_same_question_native_details_gap_is_not_closed_by_first(monkeypatch):
    first = f'<details><summary>{QUESTION}</summary><p>{ANSWER}</p></details>'
    second = f'<details><summary>{QUESTION}</summary></details>'
    _, page, _ = await _capture(monkeypatch, _document(first + second), allow_advanced=True,
                              browser_body=_document(first))
    assert page.metadata['capture_incomplete'] is True
    assert any(item['status'] == 'incomplete' for item in page.metadata['disclosures'])


@pytest.mark.asyncio
async def test_shifted_native_details_path_cannot_close_missing_first_gap(monkeypatch):
    empty = f'<details><summary>{QUESTION}</summary></details>'
    full = f'<details><summary>{QUESTION}</summary><p>{ANSWER}</p></details>'
    other = '<details><summary>Who grants access?</summary><p>Only the owner can grant access.</p></details>'
    _, page, _ = await _capture(monkeypatch, _document(empty + full + other), allow_advanced=True,
                              browser_body=_document(full + other))
    assert page.metadata['capture_incomplete'] is True
    assert any(item['status'] == 'incomplete' for item in page.metadata['disclosures'])


@pytest.mark.asyncio
@pytest.mark.parametrize('structure_id,duplicate_basic,duplicate_browser,expected_incomplete', [
    ('', False, False, True), ('guest-details', False, False, False),
    ('guest-details', True, False, True), ('guest-details', False, True, True),
])
async def test_native_details_browser_resolution_requires_unique_structure_id(
        monkeypatch, structure_id, duplicate_basic, duplicate_browser, expected_incomplete):
    attribute = f' id="{structure_id}"' if structure_id else ''
    empty = f'<details{attribute}><summary>{QUESTION}</summary></details>'
    full = f'<details{attribute}><summary>{QUESTION}</summary><p>{ANSWER}</p></details>'
    duplicate = f'<span id="{structure_id}">Another element uses this ID.</span>'
    empty += duplicate if duplicate_basic else ''
    full += duplicate if duplicate_browser else ''
    _, page, _ = await _capture(monkeypatch, _document(empty), allow_advanced=True,
                              browser_body=_document(full))
    assert page.metadata['capture_incomplete'] is expected_incomplete
    assert ANSWER in page.text


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['details', 'aria_controls'])
async def test_distinct_questions_with_source_repeated_answers_keep_each_complete_pair(monkeypatch, kind):
    questions = ['Who grants a guest access?', 'Who grants an editor access?']
    answer = 'Only an owner can grant access to the shared workspace.'
    if kind == 'details':
        markup = ''.join(f'<details id="faq-{index}"><summary>{question}</summary><p>{answer}</p></details>'
                         for index, question in enumerate(questions))
    else:
        markup = ''.join(f'<h2><button id="q-{index}" aria-expanded="false" aria-controls="a-{index}">{question}</button></h2>'
                         f'<div id="a-{index}" role="region" aria-hidden="true"><p>{answer}</p></div>'
                         for index, question in enumerate(questions))
    _, page, _ = await _capture(monkeypatch, _document(markup))
    assert len(page.metadata['disclosures']) == 2
    for disclosure in page.metadata['disclosures']:
        assert disclosure['status'] == 'complete'
        quote = disclosure['quote']
        assert quote in page.text
        assert disclosure['quote_start'] >= 0
        assert page.text[disclosure['quote_start']:disclosure['quote_start'] + len(quote)] == quote
    assert page.metadata['capture_incomplete'] is False
