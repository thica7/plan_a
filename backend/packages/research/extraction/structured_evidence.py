"""Recover source-native proposals, retaining the ordinary semantic admission gates."""
from __future__ import annotations

import hashlib

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
    return semantic_extraction(brief, page, {'facts': [{'quote': quote} for quote in dict.fromkeys(candidates)]},
                               extractor_name='source_structured_rules')
