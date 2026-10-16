"""One substantive contract for the compact dimension report route."""
from __future__ import annotations

import re


def dimension_report_profile(plan, *, topic, partial_evidence=False):
    from packages.research.evidence.operations import required_operations
    brief = getattr(plan, 'decision_brief', None)
    explicit_questions = bool(brief and brief.decision_question.strip())
    return partial_evidence or ('feature' in plan.dimensions and explicit_questions) or (
        plan.research_depth == 'quick' and len(plan.dimensions) > 1) or (
        'feature' in plan.dimensions and bool(required_operations(
            topic, plan.target_product.use_cases if plan.target_product else ())))


def compact_report_checks(markdown, *, output_language='zh-CN', allow_evidence_gaps=False):
    from packages.agents.writer.segment_contract import heading_key_for
    matches = list(re.finditer(r'(?m)^##\s+(.+?)\s*$', markdown))
    sections = {}
    for index, match in enumerate(matches):
        key = heading_key_for(match.group(1).strip(), output_language)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        sections.setdefault(key, []).append(markdown[match.end():end].strip())
    def body(*keys):
        return '\n'.join(text for key in keys for text in sections.get(key, []))
    def prose(text):
        text = re.sub(r'\[source:[^\]]+\]', '', text)
        text = re.sub(r'(?m)^\s*#{1,6}.*$', '', text)
        return re.sub(r'[\s|#*\-:：]+', '', text)
    summary = body('executive_summary', 'executive_takeaway', 'executive_overview')
    findings = body('competitive_findings')
    # Pricing is an H2 within the renderer's observation area.
    from packages.agents.writer.segment_contract import SUPPORT_HEADING_KEYS
    start = next((i for i, match in enumerate(matches)
                  if heading_key_for(match.group(1).strip(), output_language) == 'competitive_findings'), None)
    if start is not None:
        end = next((match.start() for match in matches[start + 1:]
                    if heading_key_for(match.group(1).strip(), output_language) in SUPPORT_HEADING_KEYS), len(markdown))
        findings = markdown[matches[start].end():end]
    sources = body('evidence_appendix')
    risk = body('confidence_notes')
    citation = re.compile(r'\[source:[^\]\s]+\]')
    return [
        ('executive_summary', len(prose(summary)) >= 12),
        ('competitive_findings', (allow_evidence_gaps or bool(citation.search(findings))) and len(prose(findings)) >= 20),
        ('evidence_appendix', (allow_evidence_gaps or bool(citation.search(sources))) and len(prose(sources)) >= 3),
        ('confidence_notes', len(prose(risk)) >= 24
            and bool(re.search(r'审核|风险|限制|audit|review|risk|limitation', risk, re.I))
            and bool(re.search(r'下一步|验证|核验|next|verif', risk, re.I))),
    ]
