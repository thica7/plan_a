"""Replayable complete members of admitted source facts, never model-selected substrings."""

from __future__ import annotations

import hashlib
import re

from pydantic import BaseModel, ConfigDict, Field

from packages.research.evidence.snapshot_models import canonical_json


class ReportSourceSpanBinding(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    span_id: str
    fact_id: str
    source_id: str
    fact_hash: str
    source_path: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1)


def _members(fact):
    yield 'quote', fact.quote
    value = fact.value
    if isinstance(value, str):
        yield 'value', value
    elif isinstance(value, (list, tuple)):
        for index, text in enumerate(value):
            if isinstance(text, str):
                yield f'value/{index}', text


def source_span_candidates(fact):
    """Offer whole members/paragraphs, keeping conditional lists and context intact.

    IDs bind the complete immutable fact (including scope and item identity),
    exact member path and offsets. Shorter copies of an admitted exception group
    cannot be selected to hide its remaining conditions.
    """
    if fact.field != 'evidence_terms' or fact.status != 'supported':
        return ()
    from packages.research.evidence.source_exceptions import MAX_RULE_CHARS, complete_rule_blocks
    members = list(_members(fact))
    groups = [block for _, text in members for block in complete_rule_blocks(text, max_chars=None)]
    digest = hashlib.sha256(canonical_json(fact.model_dump(mode='json')).encode()).hexdigest()
    result, seen = [], set()
    for path, original in members:
        choices = []
        for paragraph in re.split(r'\n\s*\n', original):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            # A standalone optional-example lead-in does not qualify the
            # preceding completed rule. Keep that whole prefix, with its
            # original negations/conditions and offsets; required list headers
            # are deliberately absent from this finite boundary vocabulary.
            optional = re.search(
                r'(?<=[.!?。！？])\s*'
                r'(?:Consider inviting|For example|Examples include|例如)\s*[:：]$',
                paragraph, re.I)
            if optional:
                prefix = paragraph[:optional.start()].rstrip()
                lines = prefix.splitlines()
                # Check every forward reference. A later complete sentence
                # cannot resolve an earlier missing list. Only a list already
                # present immediately after its own header closes that pointer.
                if any((pointer := re.search(
                            r'\b(?:following|below|these)\b|以下|下列|这些', line, re.I))
                       and not (line.rstrip().endswith((':', '：')) and index + 1 < len(lines)
                                and not re.search(r'[.!?。！？]', line[pointer.end():])
                                and re.match(r'^\s*[-*]\s+\S', lines[index + 1]))
                       for index, line in enumerate(lines)):
                    continue
                choices.append(prefix)
                continue
            # Lists and their explanations remain one complete group. Wrapped
            # text remains one sentence until terminal punctuation, never one
            # candidate per physical line.
            if re.search(r'[:：]\s*\n|^\s*[-*]\s', paragraph, re.M):
                block = max((group for group in groups if group in paragraph), key=len, default=None)
                if block:
                    choices.append(block)
                elif re.match(r'[^\n]+[:：]\s*\n', paragraph):
                    choices.append(paragraph)
            elif '\n' in paragraph:
                choices.extend(part.strip() for part in re.split(
                    r'(?<=[.!?。！？])\s+(?=[A-Z\u4e00-\u9fff])', paragraph) if part.strip())
            else:
                choices.append(paragraph)
        for text in choices:
            if (not text or text in seen or len(text) > MAX_RULE_CHARS
                    or text.endswith((':', '：'))
                    or any(text != group and text in group for group in groups)):
                continue
            start = original.index(text)
            values = dict(fact_id=fact.id, source_id=fact.source_id, fact_hash=digest,
                          source_path=path, start=start, end=start + len(text), quote=text)
            span_id = 'source-span-' + hashlib.sha256(canonical_json(values).encode()).hexdigest()[:24]
            result.append(dict(span_id=span_id, **values))
            seen.add(text)
    return tuple(result)


def projected_source_facts(claim, facts):
    """Validate persisted identity, then expose only the bound support text.

    Callers retain original parent facts separately as limiting context.
    """
    bindings = getattr(claim, 'source_span_bindings', ())
    if not bindings:
        return tuple(facts), ()
    by_id = {fact.id: fact for fact in facts}
    projected = []
    if (len(bindings) != len(claim.fact_ids)
            or {binding.fact_id for binding in bindings} != set(claim.fact_ids)):
        return (), ('source_span_binding_mismatch',)
    for binding in bindings:
        fact = by_id.get(binding.fact_id)
        if fact is None or binding.model_dump(mode='json') not in source_span_candidates(fact):
            return (), ('source_span_binding_mismatch',)
        projected.append(fact.model_copy(update={'quote': binding.quote,
            'value_json': canonical_json([binding.quote])}))
    return tuple(projected), ()


def source_span_exception_bindings(facts, sent_span_ids):
    """Offer cross-source pairs only from exact support members already sent."""
    from packages.research.evidence.source_exceptions import _cross_source_exception_rows
    variants = [(fact.model_copy(update={'quote': span['quote'],
                 'value_json': canonical_json([span['quote']])}), span)
                for fact in facts for span in source_span_candidates(fact)
                if span['span_id'] in sent_span_ids]
    result = []
    for fact, span in variants:
        for other, other_span in variants:
            if fact.id == other.id:
                continue
            rows = _cross_source_exception_rows(fact, other)
            if not rows:
                continue
            pair = dict(fact_ids=[fact.id, other.id], source_ids=[fact.source_id, other.source_id],
                        source_span_ids=[span['span_id'], other_span['span_id']], source_exceptions=list(rows))
            identity = hashlib.sha256(canonical_json(pair).encode()).hexdigest()[:20]
            result.append(dict(id='exception-binding-' + identity, **pair))
    return tuple(sorted(result, key=lambda row: row['id']))
