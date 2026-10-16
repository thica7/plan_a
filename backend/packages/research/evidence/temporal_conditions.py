"""Replayable, source-local creation-date conditions for arbitrary permissions.

This is a bounded omission guard, not a semantic entailment engine. It never
uses request dates or source verification/update timestamps as product rules.
"""

from __future__ import annotations

import re
from datetime import date


_MONTHS = ('january', 'february', 'march', 'april', 'may', 'june', 'july',
           'august', 'september', 'october', 'november', 'december')
_DATE = (r'(?:\d{4}-\d{1,2}-\d{1,2}|\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日|'
         r'(?:' + '|'.join(_MONTHS) + r')\s+\d{1,2}(?:st|nd|rd|th)?[,]?\s+\d{4})')
_CREATED_EN = re.compile(
    r'\b(?P<subject>[a-z][a-z-]*)\s+(?:(?:that\s+)?were\s+)?'
    r'(?:created|opened|established|registered)\s+'
    r'(?P<relation>on or before|on or after|before|after|since)\s+(?P<date>' + _DATE + r')', re.I)
_CREATED_ZH = re.compile(
    r'(?P<date>' + _DATE + r')\s*(?:之)?(?P<relation>前|后|之前|之后|及以后|及之前)'
    r'\s*(?:创建|开通|建立|注册)的\s*(?P<subject>账号|账户|工作区|组织|项目|文档|看板|团队|订阅)', re.I)
_SUBJECTS = {'账号': 'account', '账户': 'account', '工作区': 'workspace', '组织': 'organization',
             '项目': 'project', '文档': 'document', '看板': 'board', '团队': 'team', '订阅': 'subscription'}
_NEGATIVE = re.compile(r'\bcannot\b|\bcan[’\']t\b|\b(?:won[’\']t|will not)\s+be able to\b|'
                       r'\bnot (?:allowed|permitted|able)\b|不能|无法|不得|不允许|无权', re.I)
_ASSERTION = re.compile(r'\b(?:can|cannot|may|permissions?|rights|privileges|eligible|won[’\']t|will not)\b|'
                        r'可以|能够|不能|无法|不得|担任|成为|权限', re.I)
_SAME_RIGHTS = re.compile(r'\bsame (?:permissions|rights|privileges)\b|相同.{0,5}权限', re.I)
_ROLE_ALIASES = {'admin': 'admin', 'administrator': 'admin', '管理员': 'admin',
                 'owner': 'owner', '所有者': 'owner'}


def _singular(value):
    value = value.casefold().strip()
    return value[:-1] if value.endswith('s') and not value.endswith('ss') else value


def _normalized_date(value):
    numbers = re.findall(r'\d+', value)
    try:
        if re.match(r'\d{4}', value):
            return date(*map(int, numbers)).isoformat()
        month = next(i for i, name in enumerate(_MONTHS, 1) if value.casefold().startswith(name))
        return date(int(numbers[1]), month, int(numbers[0])).isoformat()
    except (ValueError, StopIteration, IndexError):
        return None


def _creation_dates(text):
    matches = []
    for pattern in (_CREATED_EN, _CREATED_ZH):
        for match in pattern.finditer(text):
            cutoff = _normalized_date(match['date'])
            if cutoff is None:
                continue
            relation = {'前': 'before', '之前': 'before', '后': 'after', '之后': 'after',
                        '及以后': 'on or after', '及之前': 'on or before', 'since': 'on or after'}.get(
                            match['relation'].casefold(), match['relation'].casefold())
            subject = _SUBJECTS.get(match['subject'], _singular(match['subject']))
            matches.append((match, subject, cutoff, relation))
    return sorted(matches, key=lambda item: item[0].start())


def _source_strings(fact):
    """Read source text, including retained context quotes; ignore metadata dates."""
    yield 'quote', fact.quote

    def walk(value, path):
        if isinstance(value, str):
            yield path, value
        elif isinstance(value, (list, tuple)):
            for index, child in enumerate(value):
                yield from walk(child, f'{path}.{index}')
        elif isinstance(value, dict):
            for key, child in value.items():
                if 'quote' in key or key in {'condition_evidence', 'evidence_terms', 'context'}:
                    yield from walk(child, f'{path}.{key}')

    yield from walk(fact.value, 'value')
    yield from walk(fact.qualifiers, 'qualifiers')


def _condition_quote(text, match):
    start = max((m.end() for m in re.finditer(r'[.!?。；;\n]', text[:match.start()])), default=0)
    end = re.search(r'[.!?。；;\n]', text[match.end():])
    end = match.end() + end.end() if end else len(text)
    # A directly following pronoun continuation belongs to the same named
    # subject. Do not pull a separate role or an unrelated paragraph into it.
    following = re.match(r'\s*(?:They\b|These users\b|Such users\b|他们|这些用户)[^.!?。；;\n]*[.!?。；;]?', text[end:], re.I)
    if following:
        end += following.end()
    return text[start:end].strip(), text[match.end():end]


def _actor(tail):
    tail = re.sub(r'^\s*(?:note|warning|注意|备注)\s*[:：]\s*', '', tail, flags=re.I)
    match = re.match(r'[\s,，:：]*(?P<actor>[^,.!?:;。；，\n]{1,100}?)\s+'
                     r'(?P<verb>can|cannot|may|have|has|are|is|won[’\']t|will not)\b', tail, re.I)
    if not match:
        match = re.match(r'[\s,，:：中内]*(?P<actor>[^,.!?:;。；，\n]{1,50}?)'
                         r'(?P<verb>可以|能够|不能|无法|具有|拥有)', tail)
    if not match or re.fullmatch(r'they|these users|such users|users|people|他们|这些用户', match['actor'].strip(), re.I):
        return None
    return match['actor'].strip()


def temporal_constraints(fact):
    """Return exact source quotations and date subjects, without inventing scope.

    ``actor=None`` means that the source text did not establish a named actor;
    consumers must preserve that uncertainty rather than fill it from a query.
    ``source_path`` plus ``quote`` lets a replay verify the derived condition.
    """
    if fact.dimension != 'feature' or fact.field != 'evidence_terms':
        return ()
    rows, seen = [], set()
    for path, text in _source_strings(fact):
        for match, subject, cutoff, relation in _creation_dates(text):
            quote, tail = _condition_quote(text, match)
            if not _ASSERTION.search(quote):
                continue
            actor = _actor(tail) or _actor(quote)
            key = (quote, subject, cutoff, relation, actor)
            if key in seen:
                continue
            seen.add(key)
            rows.append({'quote': quote, 'date_subject': subject, 'cutoff': cutoff,
                         'relation': relation, 'actor': actor, 'source_path': path})
    return tuple(rows)


def _contains_actor(text, actor):
    if not actor:
        return False
    tokens = re.findall(r'[a-z]+|[\u4e00-\u9fff]+', actor.casefold())
    pattern = r'\s+'.join(re.escape(_singular(token)) + r's?' for token in tokens)
    return bool(pattern and re.search(r'(?<![a-z])' + pattern + r'(?![a-z])', text, re.I))


def _general_keys(fact, constraint):
    """Only broaden 'same permissions' over the same explicit source subject."""
    actor = constraint['actor']
    for path, text in _source_strings(fact):
        if path != constraint['source_path']:
            continue
        prefix = text[:text.find(constraint['quote'])]
        heading = next((line.strip() for line in prefix.splitlines() if line.strip()), '')
        if _contains_actor(prefix, actor) and (heading.casefold() == actor.casefold()
                or _contains_actor(fact.quote, actor)):
            keys, active = set(), heading.casefold() == actor.casefold()
            for part in re.split(r'(?<=[.!?。；;])|\n', prefix):
                named = _actor(part.strip())
                if named:
                    active = _contains_actor(named, actor)
                elif _contains_actor(part, actor):
                    active = True
                if active:
                    keys.update(_predicate_keys(part, actor))
            return keys
    return set()


def _predicate_keys(text, actor=None):
    """Match lexical permission predicates without a closed set of role names."""
    if actor:
        text = re.sub(re.escape(actor), '', text, flags=re.I)
    keys = set()
    for match in re.finditer(r'\b(?:be|being|become)\s+(?:(?:made|an?|also)\s+)*'
                             r'([a-z][a-z-]*(?:\s+or\s+[a-z][a-z-]*)*)|'
                             r'(?:担任|成为)\s*([a-z][a-z-]*|[\u4e00-\u9fff]{1,12})', text, re.I):
        value = match[1] or match[2]
        keys.update('role:' + _ROLE_ALIASES.get(_singular(part), _singular(part))
                    for part in re.split(r'\s+or\s+|或|、', value, flags=re.I)
                    if part.casefold() not in {'able', 'allowed', 'permitted'})
    # Dynamic verbs keep actions outside the six-operation taxonomy visible.
    for match in re.finditer(r'\b(?:can|cannot|may|could|able to)\s+(?:also\s+|only\s+)?'
                             r'([a-z][a-z-]*)(?:\s+([^,.!?:;。；，\n]+))?', text, re.I):
        verb, obj = match[1].casefold(), match[2]
        if verb in {'be', 'become', 'have', 'see'}:
            continue
        nouns = [_singular(word) for word in re.findall(r'[a-z][a-z-]*', (obj or '').casefold())
                 if word not in {'the', 'a', 'an', 'their', 'your', 'any', 'all'}]
        keys.add(verb + ':' + (nouns[0] if nouns else '?'))
    return keys


def _unresolved_cross_language_roles(source_keys, claim_keys):
    source_roles = {key[5:] for key in source_keys if key.startswith('role:')}
    claim_roles = {key[5:] for key in claim_keys if key.startswith('role:')}
    if source_roles.intersection(claim_roles):
        return False
    # Known translations are already canonical. Unmapped CJK/Latin role names
    # cannot establish that the source and claim discuss different permissions.
    return any(bool(re.search(r'[\u4e00-\u9fff]', left)) !=
               bool(re.search(r'[\u4e00-\u9fff]', right))
               for left in source_roles for right in claim_roles)


def _clarifies_creation(text, subject):
    subject_labels = [subject + r's?'] + [re.escape(label) for label, value in _SUBJECTS.items() if value == subject]
    labels = '(?:' + '|'.join(subject_labels) + ')'
    creation = re.search(labels + r'\s+(?:creation|created)\s+(?:date|time)|' + labels + r'创建(?:日期|时间)', text, re.I)
    clarification = re.search(r'例外|需.{0,6}(?:澄清|确认|核实)|取决于|不能一概|不一定|'
                              r'\bexception\b|\bclarif\w*\b|\bdepend\w*\b|not always', text, re.I)
    return bool(creation and clarification)


def _actor_segments(text, actor):
    """Keep continuations of the same assertion; stop at another named actor."""
    parts = re.split(r'(?<=[.!?。；;])|\bbut\b|但是|然而|[,，]\s*(?=[A-Z][a-z]+\s+(?:can|cannot|have|has)\b)', text)
    selected, active = [], False
    for part in parts:
        if _contains_actor(part, actor):
            active = True
        elif (named := _actor(part.strip())) and not re.match(r'^(?:for|in|on)\b', named, re.I):
            active = False
        if active:
            selected.append(part)
    return tuple(selected)


def claim_temporal_condition_reasons(claim, facts):
    """Reject recognizable omission/change in this claim's own source condition."""
    reasons = []
    for fact in facts:
        for constraint in temporal_constraints(fact):
            actor = constraint['actor']
            if actor is None:
                if (_predicate_keys(claim.text).intersection(_predicate_keys(constraint['quote']))
                        and _ASSERTION.search(claim.text)):
                    reasons.append('source_temporal_condition_scope_unresolved')
                continue
            if not _contains_actor(claim.text, actor):
                continue
            parts = _actor_segments(claim.text, actor)
            text = ' '.join(parts)
            source_keys = _predicate_keys(constraint['quote'], actor)
            claim_keys = _predicate_keys(text, actor)
            broad = _SAME_RIGHTS.search(constraint['quote'])
            if broad:
                source_keys.update(_general_keys(fact, constraint))
            unknown_objects = {key.split(':')[0] for key in source_keys if key.endswith(':?')}
            if any(key.split(':')[0] in unknown_objects for key in claim_keys):
                reasons.append('source_temporal_condition_scope_unresolved')
                continue
            # A different explicit action or object cannot inherit this rule.
            if source_keys and claim_keys and not source_keys.intersection(claim_keys):
                if _unresolved_cross_language_roles(source_keys, claim_keys):
                    reasons.append('source_temporal_condition_scope_unresolved')
                continue
            if not source_keys and not broad:
                continue
            if not claim_keys and not _ASSERTION.search(text):
                continue
            if _clarifies_creation(text, constraint['date_subject']):
                continue
            source_denied = bool(_NEGATIVE.search(constraint['quote']))
            relation = constraint['relation']
            same = {relation}
            complement = {'before': {'after', 'on or after'}, 'after': {'before', 'on or before'},
                          'on or before': {'after'}, 'on or after': {'before'}}[relation]
            previous_dates = ()
            for part in parts:
                part_keys = _predicate_keys(part, actor)
                relevant = (part_keys.intersection(source_keys)
                            or broad and _SAME_RIGHTS.search(part)
                            or not claim_keys and _ASSERTION.search(part))
                if not relevant:
                    if _unresolved_cross_language_roles(source_keys, part_keys):
                        reasons.append('source_temporal_condition_scope_unresolved')
                    previous_dates = ()
                    continue
                # A date or a negation on another action by this same actor
                # cannot change the current source predicate's condition.
                dated = [row for row in _creation_dates(part)
                         if row[1] == constraint['date_subject'] and row[2] == constraint['cutoff']]
                if not dated and re.match(
                    r'\s*(?:They\b|These users\b|Such users\b|他们|这些用户)', part, re.I
                ):
                    dated = previous_dates
                previous_dates = dated
                denied = bool(_NEGATIVE.search(part))
                expected = complement if denied != source_denied else same
                if not dated or any(row[3] not in expected for row in dated):
                    reasons.append('source_temporal_condition_omitted_or_changed')
    return tuple(dict.fromkeys(reasons))
