"""Shared billing signals and exact, contiguous source-table context.

A signal is terminology for extraction, never an applicable price or invoice.
Source authority, active questions and admission replay remain separate gates.
"""

from __future__ import annotations

import re

_QUESTION = re.compile(
    r'\b(?:pric(?:e|ing)|bill(?:ing)?|costs?|fees?|tax(?:es)?|invoice)\b|'
    r'\b(?:sales|custom)\s+quot(?:e|ation)\b|账单|计费|价格|定价|费用|报价|含税|总价', re.I,
)
_INCIDENTAL_OBJECT = re.compile(
    r'\b(?:pric(?:e|ing)|bill(?:ing)?|costs?|fees?|tax(?:es)?|invoices?)\s+'
    r'(?:pages?|screens?|settings?|documents?|guides?)\b|'
    r'(?:账单|计费|价格|定价|费用|报价|含税|总价)(?:页面|界面|文档|设置)', re.I,
)
_RULE = re.compile(
    r'\bminimum\s+(?:account\s+)?(?:charge|fee)\b|'
    r'\b(?:bill(?:ing)?|pricing)\b[^.!?\n]{0,160}\b(?:depends?|includes?|based|tailored|custom|charges?)\b|'
    r'\bcontact\b[^.!?\n]{0,80}\bsales\b|'
    r'最低.{0,20}(?:费用|收费)|(?:计费|账单).{0,60}(?:取决于|包括|根据)|联系.{0,20}销售', re.I,
)
_UNIT = re.compile(
    r'\b(?:requests?(?:\d+(?:\s*,\s*\d+)*)?|CPU\s+(?:time|milliseconds?|usage)|'
    r'storage|egress|bandwidth|per\s+(?:month|year|account|request|million)|'
    r'monthly\s+(?:costs?|fees?|charges?))\b|请求|CPU\s*(?:时间|毫秒|用量)|存储|流量', re.I,
)
_CHARGE = re.compile(r'\b(?:billed|charged|charges?|costs?|fees?|free|unlimited)\b|计费|收费|免费', re.I)
_RATE = re.compile(r'(?:[$€¥]\s*\d|\b(?:USD|EUR|CNY)\s*\d|\d+(?:\.\d+)?\s*(?:USD|EUR|CNY))', re.I)
_NOTE = re.compile(r'^\s*(\d+|[*†‡])(?:[.)]\s*|\s+)(.+)$')
_UNSUPPORTED_NOTE = re.compile(
    r'<\s*/?\s*sup\b|[⁰¹²³⁴⁵⁶⁷⁸⁹]|\[\^[^\]]+\]|[\[({]\s*\d+(?:\s*[,;]\s*\d+)*\s*[\])}]', re.I,
)


def is_billing_question(text: str) -> bool:
    # A document's subject is not a request for its billing rules. Other money
    # clauses in the same question remain eligible after this object is removed.
    return bool(_QUESTION.search(_INCIDENTAL_OBJECT.sub('', text)))


def billing_rule_text_signal(text: str) -> bool:
    return bool(_RULE.search(text) or _UNIT.search(text) and (_CHARGE.search(text) or _RATE.search(text)))


def _cells(line):
    line = line.strip()
    if not line.startswith('|') or not line.endswith('|') or '\\|' in line:
        return None
    return [cell.strip() for cell in line[1:-1].split('|')]


def _conflicting_unit(header, value):
    header = re.sub(r'(?<=[A-Za-z])\d+(?:\s*,\s*\d+)*', '', header)
    header_cpu, value_cpu = re.search(r'\bCPU\b', header, re.I), re.search(r'\bCPU\b', value, re.I)
    duration = re.search(r'(?<![A-Za-z])(?:milliseconds?|ms|seconds?)\b', value, re.I)
    if (re.search(r'\bRequests?\b', header, re.I) and not header_cpu and value_cpu
            or header_cpu and not value_cpu and not duration and re.search(r'\brequests?\b', value, re.I)):
        return True
    units = []
    for cell in (header, value):
        match = (re.search(r'(?<![A-Za-z])(milliseconds?|ms|seconds?|s)\b', cell, re.I)
                 if header_cpu else None)
        units.append(('ms' if match[1].casefold().startswith(('millisecond', 'ms')) else 's')
                     if match else None)
    return bool(all(units) and units[0] != units[1])


def billing_table_context(body: str, start: int, end: int, bounds=None) -> list[str]:
    """Return the exact header and all referenced complete footnotes, or nothing."""
    lower, upper = bounds if bounds is not None else (0, len(body))
    if not 0 <= lower <= start < end <= upper <= len(body):
        return []
    rows, offset = [], 0
    for line in body.splitlines(keepends=True):
        rows.append((offset, offset + len(line), line.rstrip('\r\n')))
        offset += len(line)
    index = next((i for i, (left, right, _) in enumerate(rows) if left <= start < right), None)
    if index is None or body[start:end].strip() != rows[index][2].strip():
        return []
    selected = _cells(rows[index][2])
    if selected is None:
        return []
    separator = index - 1
    while separator >= 0:
        cells = _cells(rows[separator][2])
        if cells is None or len(cells) != len(selected) or rows[separator][0] < lower:
            return []
        if cells and all(re.fullmatch(r':?-{3,}:?', cell) for cell in cells):
            break
        separator -= 1
    if separator < 1 or rows[separator - 1][0] < lower:
        return []
    header = rows[separator - 1][2]
    names, divider = _cells(header), _cells(rows[separator][2])
    if (not names or not divider or len(names) < 2 or len(names) != len(selected)
            or len(names) != len(divider) or not _UNIT.search(header)
            or not billing_rule_text_signal(header + '\n' + rows[index][2])
            or any(_conflicting_unit(name, value) for name, value in zip(names, selected, strict=True))):
        return []
    table_end = index + 1
    while table_end < len(rows) and _cells(rows[table_end][2]) is not None:
        if len(_cells(rows[table_end][2])) != len(names) or rows[table_end][1] > upper:
            return []
        table_end += 1
    references = set()
    for cell in [*names, *selected]:
        if _UNSUPPORTED_NOTE.search(cell):
            return []
        for match in re.finditer(r'(?<=[A-Za-z])(\d+(?:\s*,\s*\d+)*)|([*†‡])', cell):
            references.update(re.findall(r'\d+|[*†‡]', match.group()))
    if not references:
        return [header]
    notes, current, lines = {}, None, []
    for left, right, line in rows[table_end:]:
        if left >= upper or right > upper or not line.strip():
            break
        match = _NOTE.match(line)
        if match:
            if current is not None:
                notes[current] = '\n'.join(lines)
            if match[1] not in references or match[1] in notes:
                return []
            current, lines = match[1], [line]
        elif current is not None:
            if re.match(r'^\s*#|^(?:Example|示例)\s*\d|^[A-Z][A-Za-z0-9 &()/+-]{0,79}$', line):
                break
            lines.append(line)
        else:
            return []
    if current is not None:
        notes[current] = '\n'.join(lines)
    if set(notes) != references or sum(map(len, notes.values())) > 4096:
        return []
    return [header, *notes.values()]
