"""Recover source-native proposals, retaining the ordinary semantic admission gates."""
from __future__ import annotations

import hashlib
import re

from packages.research.extraction.billing_rules import billing_rule_text_signal
from packages.research.extraction.semantic import semantic_body_window, semantic_extraction
from packages.research.models import CapturedPage, ExtractionResult, ResearchBrief


def extract_structured_evidence(brief: ResearchBrief, page: CapturedPage) -> ExtractionResult:
    body = page.text or page.markdown or page.snippet
    window = semantic_body_window(brief, page)
    candidates = [line.strip() for line in window.splitlines()
                  if line.strip().startswith('|') and line.strip().endswith('|')
                  and billing_rule_text_signal(line)]
    capture = page.metadata.get('capture_metadata', page.metadata)
    disclosures = capture.get('disclosures', []) if isinstance(capture, dict) else []
    for record in disclosures if isinstance(disclosures, list) else []:
        if not isinstance(record, dict) or record.get('status') != 'complete':
            continue
        quote, start = record.get('quote'), record.get('quote_start')
        if (not isinstance(quote, str) or type(start) is not int or start < 0
                or body.count(quote) != 1 or window.count(quote) != 1
                or body[start:start + len(quote)] != quote
                or record.get('quote_hash') != hashlib.sha256(quote.encode()).hexdigest()[:16]):
            continue
        candidates.append(quote)
    disclosure_quotes = [row.get('quote') for row in disclosures if isinstance(row, dict)
                         and isinstance(row.get('quote'), str)] if isinstance(disclosures, list) else []
    candidates.extend(quote for quote in _question_rule_candidates(brief, page)
                      if not any(quote in block or block in quote for block in disclosure_quotes))
    return semantic_extraction(brief, page, {'facts': [{'quote': quote} for quote in dict.fromkeys(candidates)]},
                               extractor_name='source_structured_rules')


def _question_rule_candidates(brief, page):
    """Recall exact complete rule paragraphs; never synthesize from a question."""
    from packages.knowledge.lexical import query_terms
    from packages.research.extraction.semantic import _active_questions

    questions = _active_questions(brief)
    if brief.dimension != "feature" or not questions:
        return []
    from packages.research.extraction.native_question_rules import native_question_blocks

    def terms(text):
        concepts, literals = query_terms(text, [brief.competitor])
        return set(concepts) | {term.casefold() for term in literals}

    blocks = native_question_blocks(brief, page)
    rules = [
        part
        for part in dict.fromkeys(blocks)
        if 18 <= len(part) <= 1600
        and "?" not in part
        and "？" not in part
        and re.search(
            r"\b(?:can(?:not)?|can['’]t|may|must|only|able|permission|billable|(?:not|isn['’]t)(?:\s+currently)?\s+possible)\b"
            r"|允许|必须|仅限|不能|权限|计费",
            part,
            re.I,
        )
    ]
    hints = {rule: terms(rule) for rule in rules}
    rankings = [
        sorted(
            [rule for rule in rules if terms(q.question) & hints[rule]],
            key=lambda rule: (-len(terms(q.question) & hints[rule]), len(rule), rule),
        )
        for q in questions
    ]
    selected = []
    for index in range(max((len(row) for row in rankings), default=0)):
        for row in rankings:
            if index < len(row) and row[index] not in selected:
                selected.append(row[index])
            if len(selected) == 6:
                return selected
    return selected
