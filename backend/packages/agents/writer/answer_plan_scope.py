"""Conservative check for a newly asserted exclusive or mandatory named plan.

This checks explicit plan operators, not general semantic entailment. Unknown
plan names remain unverified; a positive inclusion never proves exclusivity.
"""

import re

_OPERATOR = re.compile(
    r'(?<!not )\bonly\b|\bexclusively\b|\b(?:must|need(?:s)? to)\s+(?:upgrade|switch)\b'
    r'|(?<!不)仅|(?<!不)只|(?:需要|必须|需)(?:升级|改用|切换)', re.I)
_PLAN = re.compile(
    r'([A-Za-z][A-Za-z0-9_+-]*(?:\s+[A-Za-z][A-Za-z0-9_+-]*){0,4})'
    r'\s*(?:套餐|方案|计划|版|\bplans?\b|\btiers?\b)')
_STOP = {'only', 'the', 'on', 'in', 'and', 'or', 'must', 'no', 'available', 'included',
         'supports', 'support', 'is', 'are', 'with', 'for', 'to', 'exclusively'}


def _scopes(text):
    for operator in _OPERATOR.finditer(text):
        if re.search(r'\b(?:not|never|no)\s+$|不(?:必|用)?$|(?:无需|无须|并非)$',
                     text[:operator.start()], re.I):
            continue
        after = re.split(r'[.!?;。！？；\n]', text[operator.start():operator.end() + 120])[0]
        plans = list(_PLAN.finditer(after))
        if not plans:
            before = re.split(r'[.!?;。！？；\n]', text[max(0, operator.start() - 120):operator.start()])[-1]
            plans = list(_PLAN.finditer(before))
        if plans:
            yield {word.casefold() for plan in plans for word in re.findall(r'[A-Za-z0-9_+-]+', plan[1])
                   if word.casefold() not in _STOP}
        else:
            tail = text[operator.end():operator.end() + 120]
            tail = re.sub(r'^(?:\s*(?:限于|限|有|对|包含在?|支持|在|升级到?|改用|切换到?|the\b|to\b))+', '', tail)
            bare = re.match(r'\s*([A-Z][A-Za-z0-9_+-]*(?:\s+(?:and|or)\s+[A-Z][A-Za-z0-9_+-]*)*)', tail)
            if bare:
                yield {word.casefold() for word in re.findall(r'[A-Za-z0-9_+-]+', bare[1])
                       if word.casefold() not in _STOP}
            elif re.search(r'套餐|方案|计划|版|可用|提供|包含|升级|\b(?:plans?|tiers?|available|included|upgrade)\b', after, re.I):
                yield set()


def plan_exclusivity_reasons(record, claims):
    if record.status not in {'answered', 'partial'} or record.resolution not in {'direct', 'conditional'}:
        return ()
    from packages.agents.writer.answer_resolution import _span_contexts

    published = {claim['id']: claim['text'] for claim in claims}
    grounded = [scope for span in record.evidence_spans
                if span.claim_id in record.claim_ids and span.claim_id in published
                for context in _span_contexts(span.quote, published[span.claim_id])
                for scope in _scopes(context) if scope]
    if any(not scope or not any(scope == original for original in grounded)
           for scope in _scopes(record.answer)):
        return ('answer_plan_exclusivity_unverified',)
    return ()
