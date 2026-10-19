from __future__ import annotations

import asyncio
import hashlib
import html
import re
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from io import BytesIO
from typing import Any
from urllib.parse import urljoin

import httpx
from lxml.etree import ParserError
from lxml.html import HTMLParser, document_fromstring, tostring
from pypdf import PdfReader
from trafilatura import extract as trafilatura_extract
from trafilatura.settings import use_config

from packages.crawler.policy import SSRFError, SSRFGuard

_MAX_REDIRECTS = 8
_DEFAULT_MAX_BYTES = 2_000_000
_HIDDEN_CLASSES = {'hidden', 'tw:hidden'}
# Keep short specification tables out of trafilatura's unstructured baseline rescue.
_HTML_TEXT_CONFIG = use_config()
_HTML_TEXT_CONFIG.set("DEFAULT", "MIN_EXTRACTED_SIZE", "0")


@dataclass(frozen=True)
class FetchPageResult:
    url: str
    ok: bool
    title: str
    text: str
    content_hash: str
    status_code: int | None = None
    error: str | None = None
    content_type: str = ""
    document_headings: tuple[tuple[int, str], ...] = ()
    pricing_controls: tuple[dict, ...] = ()
    pricing_offer_json: tuple[str, ...] = ()
    capture_metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def snippet(self) -> str:
        return self.text[:700]


async def fetch_page(
    url: str,
    timeout_seconds: float = 12.0,
    *,
    guard: SSRFGuard | None = None,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FetchPageResult:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; CompetiscopeBot/0.1; +https://example.local/competiscope)"
        )
    }
    ssrf_guard = guard or SSRFGuard()
    try:
        response = None
        current_url = url
        expected_addresses = await ssrf_guard.validate_url(current_url)
        async with httpx.AsyncClient(
            timeout=timeout_seconds,
            follow_redirects=False,
            headers=headers,
            transport=transport,
        ) as client:
            for _ in range(_MAX_REDIRECTS + 1):
                response = await client.get(current_url)
                if not response.is_redirect:
                    await ssrf_guard.validate_rebinding(str(response.url), expected_addresses)
                    break
                location = response.headers.get("location")
                if not location:
                    break
                current_url = urljoin(str(response.url), location)
                expected_addresses = await ssrf_guard.validate_url(current_url)
            else:
                raise httpx.TooManyRedirects("Exceeded maximum redirects")
        if response is None:
            raise httpx.HTTPError("No response returned")
        response.raise_for_status()
    except (Exception, SSRFError) as exc:  # noqa: BLE001 - fetch failure is data, not a pipeline failure.
        return FetchPageResult(
            url=url,
            ok=False,
            title="",
            text="",
            content_hash=_hash_text(f"{url}:{exc}"),
            status_code=getattr(getattr(exc, "response", None), "status_code", None),
            error=str(exc),
        )

    body = response.content[: max(0, max_bytes)].decode(
        response.encoding or "utf-8", errors="replace",
    )
    content_type = response.headers.get("content-type", "").split(";", 1)[0].casefold().strip()
    if content_type == "application/pdf":
        try:
            text = await asyncio.to_thread(_extract_pdf_text, response.content[:max(0, max_bytes)])
        except Exception as exc:
            return FetchPageResult(
                url=str(response.url), ok=False, title="", text="",
                content_hash=_hash_text(str(response.url)), status_code=response.status_code,
                error=f"PDF extraction failed: {exc}", content_type=content_type,
            )
        return FetchPageResult(
            url=str(response.url), ok=bool(text), title=str(response.url.path.rsplit("/", 1)[-1]),
            text=text, content_hash=_hash_text(text or str(response.url)),
            status_code=response.status_code,
            error=None if text else "PDF has no extractable text; OCR is required",
            content_type=content_type,
        )
    if content_type.startswith(("image/", "audio/", "video/")) or content_type == "application/octet-stream":
        return FetchPageResult(
            url=str(response.url), ok=False, title="", text="",
            content_hash=_hash_text(str(response.url)), status_code=response.status_code,
            error=f"Unsupported content type: {content_type}", content_type=content_type,
        )
    title = _extract_title(body)
    text, headings, capture_metadata = await asyncio.to_thread(_capture_html, body)
    if len(response.content) > max(0, max_bytes):
        capture_metadata["capture_incomplete"] = True
        capture_metadata["capture_gaps"].append("response_body_truncated")
    return FetchPageResult(
        url=str(response.url),
        ok=bool(text),
        title=title,
        text=text,
        content_hash=_hash_text(text or body),
        status_code=response.status_code,
        content_type=content_type,
        document_headings=headings,
        pricing_controls=_pricing_controls(body),
        pricing_offer_json=_pricing_offer_json(body),
        capture_metadata=capture_metadata,
    )


def _pricing_controls(body: str) -> tuple[dict, ...]:
    try:
        tree = document_fromstring(body)
    except (ParserError, ValueError):
        return ()
    for node in tree.xpath('//script|//template|//noscript'):
        node.drop_tree()
    controls = []
    for node in tree.xpath('//input[@name="billingInterval"][@checked]|//input[@name="billing"][@checked]|//input[@id="unit-count"]')[:16]:
        if any(parent.get('hidden') is not None or parent.get('aria-hidden') == 'true'
               or re.search(r'display\s*:\s*none|visibility\s*:\s*hidden', parent.get('style', ''), re.I)
               for parent in [node, *node.iterancestors()]):
            continue
        interval = ({'year': 'annual', 'month': 'monthly'}.get(node.get('value'))
                    if node.get('name') == 'billingInterval' else
                    {'ANNUAL': 'annual', 'MONTHLY': 'monthly'}.get(node.get('id')))
        if interval and node.get('disabled') is None:
            controls.append({'name': node.get('name'), 'value': node.get('value'),
                             'checked': True, 'interval': interval,
                             'html': tostring(node, encoding='unicode', with_tail=False)})
        elif node.get('id') == 'unit-count' and re.fullmatch(r'[1-9]\d{0,6}', node.get('value', '')):
            controls.append({'name': 'unit-count', 'count': int(node.get('value')),
                             'html': tostring(node, encoding='unicode', with_tail=False)})
    return tuple(controls)


def _pricing_offer_json(body: str) -> tuple[str, ...]:
    try:
        tree = document_fromstring(body)
    except (ParserError, ValueError):
        return ()
    return tuple(node.text for node in tree.xpath('//script[@type="application/ld+json"]')[:16]
                 if node.text and len(node.text) <= 20000)


def _extract_pdf_text(payload: bytes) -> str:
    reader = PdfReader(BytesIO(payload), strict=False)
    if reader.is_encrypted:
        return ""
    return "\n\n".join(
        (page.extract_text() or "").strip()
        for page in reader.pages[:20]
    ).strip()[:100_000]


def _extract_title(body: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", body, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return _collapse_space(html.unescape(match.group(1)))


def _document_headings(body: str) -> tuple[tuple[int, str], ...]:
    return _capture_html(body)[1]


def _heading_block_visible(node) -> bool:
    return all(_node_visible(parent) for parent in [node, *node.iterancestors()])


def _html_to_text(body: str) -> str:
    return _capture_html(body)[0]


def _capture_html(body: str) -> tuple[str, tuple[tuple[int, str], ...], dict[str, Any]]:
    """Extract one source scope and restore only explicit, verifiable disclosures."""
    metadata: dict[str, Any] = {"capture_structure_version": 1, "content_root": "body",
                              "capture_incomplete": False, "capture_gaps": [], "disclosures": []}
    try:
        parser = HTMLParser(encoding="utf-8", huge_tree=True, remove_comments=True)
        tree = document_fromstring(body.encode("utf-8"), parser=parser)
    except (ParserError, ValueError):
        metadata.update(capture_incomplete=True, capture_gaps=["html_parse_failed"])
        return "", (), metadata
    for node in tree.xpath('//script|//style|//noscript|//template|//svg'):
        if node.getparent() is not None:
            node.drop_tree()
    # ID ambiguity is document wide, even when the duplicate is outside the content root.
    ids: dict[str, list] = {}
    for node in tree.xpath('//*[@id]'):
        ids.setdefault(node.get('id'), []).append(node)
    controls: dict[str, list] = {}
    for node in tree.xpath('//button[@aria-controls]'):
        if _effective_disclosure_button(node):
            controls.setdefault(node.get('aria-controls'), []).append(node)
    for node in tree.xpath('//nav|//footer'):
        if node.getparent() is not None:
            node.drop_tree()
    mains = [node for node in tree.xpath('//main') if _heading_block_visible(node)]
    articles = [node for node in tree.xpath('//article') if _heading_block_visible(node)]
    roots = mains or articles
    if len(roots) == 1:
        root = roots[0]
    else:
        root = tree.find('body')
        if root is None:
            root = tree
        if roots:
            metadata["capture_gaps"].append("ambiguous_content_root")
    metadata["content_root"] = root.tag
    if not _heading_block_visible(root):
        metadata.update(capture_incomplete=True, capture_gaps=['hidden_content_root'])
        return '', (), metadata
    members = set(root.iter())
    disclosures = []
    revealed = set()
    for node in root.iter():
        if node.tag == 'details' and _heading_block_visible(node):
            summaries = node.findall('summary')
            if len(summaries) != 1 or not _heading_block_visible(summaries[0]):
                continue
            summary = summaries[0]
            answer_node = deepcopy(node)
            for child in answer_node.findall('summary'):
                child.drop_tree()
            answer = _disclosure_answer(answer_node)
            question = _visible_source_text(summary)
            record = _disclosure_record('details', question, answer)
            record['source_path'] = tree.getroottree().getpath(node)
            if node.get('id') and len(ids.get(node.get('id'), [])) == 1:
                record['element_id'] = node.get('id')
            disclosures.append((node, record))
        elif node.tag == 'button' and node.get('aria-controls') and _effective_disclosure_button(node):
            question = _visible_source_text(node)
            targets = node.get('aria-controls', '').split()
            panels = ids.get(targets[0], []) if len(targets) == 1 else []
            panel = panels[0] if len(panels) == 1 else None
            reason = None
            if len(controls.get(node.get('aria-controls'), [])) != 1 or (node.get('id') and len(ids[node.get('id')]) != 1):
                reason = 'ambiguous_disclosure_control'
            elif panel is None:
                reason = 'ambiguous_disclosure_panel' if panels else 'missing_disclosure_panel'
            elif panel not in members or node in panel.iter() or panel in node.iter():
                reason = 'disclosure_panel_outside_scope'
            elif any(not _node_visible(parent) for parent in panel.iterancestors()):
                reason = 'hidden_disclosure_ancestor'
            if reason:
                record = _disclosure_record('aria_controls', question, '')
                record.update(reason=reason, panel_id=targets[0] if len(targets) == 1 else '')
            else:
                revealed.add(panel)
                record = _disclosure_record('aria_controls', question,
                                            _disclosure_answer(panel, reveal=True))
            record.update(control_id=node.get('id', ''), source_path=tree.getroottree().getpath(node))
            if panel is not None:
                record['panel_id'] = panel.get('id', '')
            disclosures.append((node, record))
    # The only hidden content admitted is the exact panel of an effective disclosure.
    clone = deepcopy(root)
    copies = dict(zip(root.iter(), clone.iter(), strict=True))
    for node in revealed:
        _reveal_node(copies[node])
    _drop_hidden(clone)
    headings = tuple((int(node.tag[1]), _collapse_space(node.text_content()))
                     for node in clone.xpath('.//h1|.//h2|.//h3|.//h4|.//h5|.//h6')
                     if node.text_content().strip())
    text = trafilatura_extract(
        deepcopy(clone),
        include_comments=False,
        include_tables=True,
        favor_recall=True,
        config=_HTML_TEXT_CONFIG,
    )
    text = (text or '').strip()
    fallback = not text or 'ambiguous_content_root' in metadata['capture_gaps']
    if fallback:
        text = '\n'.join(part.strip() for part in clone.itertext() if part.strip())
    disclosure_texts = [record[key] for _, record in disclosures if record['status'] == 'complete'
                        for key in ('question', 'answer')]
    disclosure_nodes = [*revealed, *(node for node, record in disclosures
                                    if node.tag == 'details' and record['status'] == 'complete')]
    disclosure_paths = {clone.getroottree().getpath(copies[node]) for node in disclosure_nodes}
    text, heading_records, heading_gap = _capture_heading_positions(
        clone, text, fallback=fallback, disclosure_texts=disclosure_texts, disclosure_paths=disclosure_paths,
    )
    if heading_gap:
        metadata['capture_gaps'].append(heading_gap)
    protected_quotes = []
    for node, record in disclosures:
        if record['status'] == 'complete':
            quote = record['quote']
            record['recovered'] = quote not in text
            if quote not in text:
                text = _insert_disclosure(clone, copies[node], text, record, protected_quotes)
            protected_quotes.append(quote)
        else:
            metadata['capture_gaps'].append(record['reason'])
        metadata['disclosures'].append(record)
    if heading_gap:
        text = _restore_headings(clone, text)
    text, anchors = _finish_heading_positions(text, heading_records)
    metadata['document_heading_anchors'] = anchors
    if len(anchors) != len(headings):
        metadata['capture_gaps'].append('heading_identity_not_captured')
    for record in metadata['disclosures']:
        if record['status'] == 'complete':
            record['quote_start'] = text.find(record['quote'])
            if record['quote_start'] < 0:
                record.update(status='incomplete', reason='disclosure_quote_not_captured')
                metadata['capture_gaps'].append(record['reason'])
            else:
                record['quote_hash'] = _hash_text(record['quote'])
    metadata['capture_gaps'] = list(dict.fromkeys(metadata['capture_gaps']))
    metadata['capture_incomplete'] = bool(metadata['capture_gaps'])
    return text, headings, metadata


def _capture_heading_positions(root, baseline: str, *, fallback=False, disclosure_texts=(), disclosure_paths=()):
    """Carry DOM block identities through extraction, without matching title text."""
    if not root.xpath('.//h1|.//h2|.//h3|.//h4|.//h5|.//h6'):
        return baseline, [], None
    marked = deepcopy(root)
    prefix = 'Cdx' + hashlib.sha256(tostring(root)).hexdigest()[:16] + 'B'
    while prefix in root.text_content():
        prefix += 'Z'
    blocks = [node for node in marked.iterdescendants()
              if re.fullmatch(r'h[1-6]', node.tag) or node.tag in {'p', 'li', 'blockquote', 'table'}
              or marked.getroottree().getpath(node) in disclosure_paths]
    records, tokens = [], []
    for index, node in enumerate(blocks):
        token = f'{prefix}{index}Z'
        tokens.append(token)
        if re.fullmatch(r'h[1-6]', node.tag) and (title := _collapse_space(node.text_content())):
            records.append(dict(level=int(node.tag[1]), title=title, token=token,
                                source_path=marked.getroottree().getpath(node), ordinal=index))
        cells = node.xpath('.//th|.//td') if node.tag == 'table' else []
        target = cells[0] if cells else node
        target.text = token + (target.text or '')
    # Text outside marked blocks may survive extraction too. It cannot be
    # crossed when placing an omitted heading at a later retained block.
    boundary = re.compile(re.escape(prefix) + r'(\d+)Z')
    block_nodes, unbound, ordinal = set(blocks), [], -1
    for value in marked.xpath('.//text()'):
        for match in boundary.finditer(str(value)):
            ordinal = int(match[1])
        owner = value.getparent()
        owner = owner.getparent() if value.is_tail else owner
        ancestors = [owner, *owner.iterancestors()] if owner is not None else []
        if (not any(node in block_nodes or node.tag == 'summary' for node in ancestors)
                and (text := _collapse_space(str(value)))):
            unbound.append((ordinal, text))
    extracted = ('\n'.join(part.strip() for part in marked.itertext() if part.strip()) if fallback else
                 trafilatura_extract(marked, include_comments=False, include_tables=True,
                                     favor_recall=True, config=_HTML_TEXT_CONFIG) or '').strip()
    clean = extracted
    for token in tokens:
        clean = clean.replace(token, '')
    if _collapse_space(clean) != _collapse_space(baseline):
        # Markers can prevent deduplication of explicit disclosure answers.
        # Permit only additional whole source blocks, within their DOM counts.
        before, after = [[_collapse_space(line) for line in value.splitlines() if line.strip()]
                         for value in (baseline, clean)]
        remaining = Counter(_collapse_space(value) for value in disclosure_texts)
        for kind, _, _, left, right in SequenceMatcher(None, before, after, autojunk=False).get_opcodes():
            if kind == 'equal':
                continue
            added = after[left:right]
            if kind != 'insert':
                return baseline, [], 'heading_markers_changed_capture'
            while added:
                count = next((size for size in range(1, len(added) + 1)
                              if remaining[' '.join(added[:size])] > 0), None)
                if count is None:
                    return baseline, [], 'heading_markers_changed_capture'
                remaining[' '.join(added[:count])] -= 1
                added = added[count:]
    emitted = [(index, extracted.find(token)) for index, token in enumerate(tokens) if token in extracted]
    if (any(extracted.count(tokens[index]) != 1 for index, _ in emitted)
            or [position for _, position in emitted] != sorted(position for _, position in emitted)):
        return baseline, [], 'heading_block_identity_ambiguous'
    insertions = {}
    for record in records:
        if record['token'] in extracted:
            continue
        following_index, following = next(((index, position) for index, position in emitted
                                           if index > record['ordinal']), (len(blocks), len(extracted)))
        if any(record['ordinal'] <= index < following_index and value in _collapse_space(clean)
               for index, value in unbound):
            return baseline, [], 'heading_source_boundary_unbound'
        position = extracted.rfind('\n', 0, following) + 1 if following < len(extracted) else len(extracted)
        insertions.setdefault(position, []).append(record['token'])
    for position in sorted(insertions, reverse=True):
        prefix_line = '\n' if position and extracted[position - 1] != '\n' else ''
        extracted = extracted[:position] + prefix_line + '\n'.join(insertions[position]) + '\n' + extracted[position:]
    for record in records:
        position = extracted.index(record['token'])
        left = extracted.rfind('\n', 0, position) + 1
        right = extracted.find('\n', position)
        right = len(extracted) if right < 0 else right
        if _collapse_space(extracted[left:right].replace(record['token'], '')) not in {'', record['title']}:
            return baseline, [], 'heading_line_identity_ambiguous'
        # A summary must not reuse an identical heading as its question.
        extracted = extracted[:left] + record['token'] + extracted[right:]
    heading_tokens = {record['token'] for record in records}
    for token in tokens:
        if token not in heading_tokens:
            extracted = extracted.replace(token, '')
    return extracted.strip(), records, None


def _finish_heading_positions(text, records):
    """Resolve surviving markers only after disclosure insertion has moved offsets."""
    anchors, occurrences, adjustment = [], {}, 0
    valid, previous = True, -1
    for record in records:
        token = record['token']
        position = text.find(token)
        start = position + adjustment
        adjustment += len(record['title']) - len(token)
        valid = valid and text.count(token) == 1 and position > previous
        previous = position
        occurrence = occurrences.get(record['title'], 0) + 1
        occurrences[record['title']] = occurrence
        anchors.append(dict(level=record['level'], title=record['title'], start=start,
                            end=start + len(record['title']), occurrence=occurrence,
                            source_path=record['source_path']))
    for record in records:
        text = text.replace(record['token'], record['title'])
    digest = hashlib.sha256(text.encode()).hexdigest()
    for anchor in anchors:
        start, end = anchor['start'], anchor['end']
        valid = valid and text[start:end] == anchor['title'] and (start == 0 or text[start - 1] == '\n')
        line_end = text.find('\n', end)
        valid = valid and not text[end:len(text) if line_end < 0 else line_end].strip()
        anchor['content_sha256'] = digest
    return text, anchors if valid else []


def _node_visible(node) -> bool:
    return not (node.get('hidden') is not None or node.get('aria-hidden', '').casefold() == 'true'
                or _HIDDEN_CLASSES.intersection(node.get('class', '').split())
                or re.search(r'display\s*:\s*none|visibility\s*:\s*hidden', node.get('style', ''), re.I))


def _effective_disclosure_button(node) -> bool:
    return (_heading_block_visible(node) and node.get('aria-expanded') in {'true', 'false'}
            and node.get('role', 'button') == 'button'
            and not any(parent.get('disabled') is not None or parent.get('aria-disabled') == 'true'
                        for parent in [node, *node.iterancestors()]))


def _reveal_node(node) -> None:
    node.attrib.pop('hidden', None)
    node.attrib.pop('aria-hidden', None)
    node.attrib.pop('style', None)
    if node.get('class'):
        node.set('class', ' '.join(value for value in node.get('class').split() if value not in _HIDDEN_CLASSES))


def _drop_hidden(root) -> None:
    for node in list(root.iterdescendants()):
        if not _node_visible(node) and node.getparent() is not None:
            node.drop_tree()


def _visible_source_text(node, *, reveal=False) -> str:
    clone = deepcopy(node)
    if reveal:
        _reveal_node(clone)
    elif not _node_visible(clone):
        return ''
    _drop_hidden(clone)
    return _collapse_space(' '.join(clone.itertext()))


def _disclosure_answer(node, *, reveal=False) -> str:
    """Headings and nested summaries alone do not constitute an answer."""
    if re.fullmatch(r'h[1-6]|summary', node.tag):
        return ''
    clone = deepcopy(node)
    if reveal:
        _reveal_node(clone)
    _drop_hidden(clone)
    answer = _visible_source_text(clone)
    for heading in clone.xpath('.//h1|.//h2|.//h3|.//h4|.//h5|.//h6|.//summary'):
        heading.drop_tree()
    return answer if _visible_source_text(clone) else ''


def _disclosure_record(kind: str, question: str, answer: str) -> dict[str, Any]:
    if answer == question:
        answer = ''
    complete = bool(question and answer)
    record = {'kind': kind, 'question': question, 'answer': answer,
              'quote': f'{question}\n{answer}' if complete else '',
              'status': 'complete' if complete else 'incomplete', 'recovered': False}
    if not complete:
        record['reason'] = 'empty_disclosure_panel' if question else 'empty_disclosure_question'
    return record


def _source_match(value: str, text: str, protected=()):
    matches = list(re.finditer(r'\s+'.join(map(re.escape, value.split())), text))
    matches = [match for match in matches
               if not any(match.start() < end and start < match.end() for start, end in protected)]
    return matches[0] if len(matches) == 1 else None


def _insert_disclosure(root, node, text: str, record: dict[str, Any], protected_quotes=()) -> str:
    protected = [match.span() for quote in protected_quotes for match in re.finditer(re.escape(quote), text)]
    question = _source_match(record['question'], text, protected)
    answer = _source_match(record['answer'], text, protected)
    if question and answer and question.end() <= answer.start() and not text[question.end():answer.start()].strip():
        return text[:question.start()] + record['quote'] + text[answer.end():]
    match = question or answer
    if match:
        return text[:match.start()] + record['quote'] + text[match.end():]
    # Locate the first later captured block; never move a disclosure past a later section.
    seen = False
    for block in root.iter():
        if block is node:
            seen = True
        if not seen or block is node or block.tag not in {'p', 'li', 'table', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}:
            continue
        anchor = _collapse_space(block.text_content())
        if len(anchor) >= 16 and (match := _source_match(anchor, text, protected)):
            return text[:match.start()] + record['quote'] + '\n' + text[match.start():]
    return f"{text}\n{record['quote']}".strip()


def _restore_headings(tree, text: str) -> str:
    """Restore omitted headings only at unique captured original block anchors."""
    nodes = [node for node in tree.xpath('//h1 | //h2 | //h3 | //h4 | //h5 | //h6 | //p | //li | //blockquote | //table')
             if _heading_block_visible(node)]
    source_text = _collapse_space(tree.text_content())
    insertions = {}
    for index, node in enumerate(nodes):
        if not re.fullmatch(r'h[1-6]', node.tag):
            continue
        heading = _collapse_space(node.text_content())
        if not heading or re.search(r'(?m)^\s*' + re.escape(heading) + r'\s*$', text):
            continue
        for block in nodes[index + 1:index + 13]:
            if re.fullmatch(r'h[1-6]', block.tag):
                break
            anchor = _collapse_space(block.text_content())
            if len(anchor) < 16:
                continue
            matches = list(re.finditer(r'\s+'.join(map(re.escape, anchor.split())), text))
            if not matches:
                continue
            if len(matches) == 1 and source_text.count(anchor) == 1:
                position = matches[0].start()
                insertions.setdefault(position, []).append(heading)
            # A repeated first content block does not locate this section.
            break
    for position in sorted(insertions, reverse=True):
        prefix = '\n' if position and text[position - 1] != '\n' else ''
        text = text[:position] + prefix + '\n'.join(insertions[position]) + '\n' + text[position:]
    return text


def _collapse_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16]
