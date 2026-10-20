"""Finite contradictions in selected support, never a general entailment engine.

Only explicit familiar predicates/objects and condition forms are compared.
Unrecognized wording still needs the independent full-assertion reviewer.
"""

from __future__ import annotations

import re

from packages.research.evidence.operation_claim_checks import (
    explicit_operation_assertions, operation_review_support,
)


_ACTIONS = {
    'share': r'\bshar(?:e[ds]?|ing)\b|共享|分享',
    'edit': r'\bedit(?:s|ed|ing)?\b|编辑',
    'comment': r'\bcomment(?:s|ed|ing)?\b|评论',
    'create': r'\bcreat(?:e[ds]?|ing)\b|创建|新建',
    'read': r'\b(?:read|reads|reading|view|views|viewed|viewing)\b|阅读|查看',
    'manage_access': r'\bmanag(?:e[ds]?|ing)\s+(?:access|permissions?)\b|管理(?:其)?(?:访问|权限)',
}
_OBJECTS = {
    'document': r'\b(?:documents?|docs?|pages?)\b|文档|页面',
    'vault': r'\bvaults?\b|保险库',
    'data': r'\bdata\b|数据',
    'board': r'\bboards?\b|看板',
}
_MANAGE_OBJECTS = {key: r'\bmanag(?:e[ds]?|ing)\s+(?:access|permissions?)\s+(?:to|for)\s+(?:the\s+)?(?:' + obj +
    r')|管理(?:' + obj + r')的访问权限' for key, obj in _OBJECTS.items()}
_ACTIONS['manage_access'] += '|' + '|'.join(_MANAGE_OBJECTS.values())
_MANAGE_MENTION = r'\b(?:manag(?:e[ds]?|ing)|management)\b|管理'
_ROLES = {
    'guest': r'\bguests?\b|访客',
    'family_member': r'\bfamily\s+members?\b|家庭成员',
    'member': r'(?<!family )\bmembers?\b|(?<!家庭)成员',
    'admin': r'\b(?:admins?|administrators?)\b|管理员',
    'owner': r'\bowners?\b|所有者',
}
_PROMOTE = re.compile(r'\b(?:promote[ds]?|upgrade[ds]?)\b|升级', re.I)
_PROMOTE_MENTION = re.compile(r'\b(?:promot(?:e[ds]?|ing|ions?)|upgrad(?:e[ds]?|ing))\b|升级', re.I)
_MODAL = re.compile(r'\b(?:can|may|must|needs? to|(?:is|are) required to|have to)\b|'
                    r'必须|需要|需(?=将|把|升级)|可以|能够|可(?=将|把|升级|编辑|共享|分享)', re.I)
_STRONG = re.compile(r'\b(?:must|needs? to|(?:is|are) required to|have to)\b|必须|需要|需', re.I)
_RECIPIENT = re.compile(r'\b(?:share|sharing)\s+(?:\w+\s+){0,4}with\s+'
    r'(?:(?:one|1)\s+other|another)\s+(?:user|member|guest)\b|'
    r'(?:与|和|向)(?:另外|另)?(?:一|1)(?:名|位|个)?(?:用户|成员|访客)[^。；;，,]{0,12}(?:共享|分享)', re.I)


def _selected_support(claim, facts):
    """Identity must validate before any text becomes semantic support."""
    by_id = {fact.id: fact for fact in facts}
    if claim.operation_binding is not None:
        from packages.research.evidence.operations import bound_operation_observation
        bound = bound_operation_observation(claim, by_id)
        if bound is None:
            return ()
        projected, unresolved = operation_review_support(bound)
        if unresolved:
            return ()
        return tuple(projected['condition_evidence'])
    if not claim.source_span_bindings:
        return ()
    from packages.research.evidence.source_spans import projected_source_facts
    projected, reasons = projected_source_facts(claim, facts)
    return () if reasons else tuple(fact.quote for fact in projected)


def _predicates(text):
    """Known action/object keys and directly governing modals, per clause."""
    result = []
    for clause in re.split(r'[。；;.!?\n]|\b(?:but|however)\b|但是|然而', text, flags=re.I):
        for action, pattern in {**_ACTIONS, 'promote': _PROMOTE.pattern}.items():
            for match in re.finditer(pattern, clause, re.I):
                tail = clause[match.end():]
                if action == 'promote':
                    # Preserve the role transition, not just an arbitrary must
                    # elsewhere in the quote or another actor's upgrade.
                    before_to = re.split(r'\bto\b|为|成', tail, maxsplit=1, flags=re.I)
                    if len(before_to) != 2:
                        continue
                    origin = clause[max(0, match.start() - 20):match.start()] + before_to[0]
                    origins = [key for key, role in _ROLES.items() if re.search(role, origin, re.I)]
                    targets = [key for key, role in _ROLES.items() if re.search(role, before_to[1], re.I)]
                    if len(origins) != 1 or len(targets) != 1:
                        continue
                    key = (action, origins[0], targets[0])
                else:
                    # Management objects occur after access/permissions or
                    # inside the Chinese action. Other verbs retain immediate
                    # objects; unknown object wording stays with review.
                    if action == 'manage_access':
                        objects = [key for key, pattern in _MANAGE_OBJECTS.items()
                                   if re.match(pattern, clause[match.start():], re.I)]
                    else:
                        objects = [key for key, obj in _OBJECTS.items()
                                   if re.match(r'\s*(?:the\s+|secure\s+|安全)?(?:' + obj + ')', tail, re.I)]
                    if len(objects) != 1:
                        continue
                    actors = [(role.start(), key) for key, pattern in _ROLES.items()
                              for role in re.finditer(pattern, clause[:match.start()], re.I)]
                    actor = max(actors)[1] if actors else None
                    key = (action, objects[0], actor)
                prefix = re.split(r'[,，]', clause[:match.start()])[-1]
                modals = list(_MODAL.finditer(prefix))
                modal = modals[-1] if modals else None
                if modal is None or len(prefix[modal.end():]) > 32:
                    continue
                # Negative necessity is not positive necessity; existing
                # polarity checks and the reviewer retain that responsibility.
                if re.search(r'\b(?:not|never)\b|不|无', prefix[max(0, modal.start() - 8):], re.I):
                    continue
                result.append((key, 'necessary' if _STRONG.fullmatch(modal.group()) else 'possible'))
    return result


def _login_condition(text):
    """Compare only a single explicit if/only-if login condition.

    AND/OR groups, after/before and unknown conditions are intentionally left
    intact for the existing complete-condition checks and semantic review.
    """
    if re.search(r'\b(?:and|or|unless)\b|并且|或者|除非', text, re.I):
        return None
    links = list(re.finditer(r'\bonly if\b|\bif\b|只有|仅当|如果|若', text, re.I))
    if len(links) != 1:
        return None
    link = links[0]
    head, tail = text[:link.start()].strip(), text[link.end():].strip().rstrip('.。')
    if head:
        condition, main = tail, head
    else:
        parts = re.split(r'[,，]', tail, maxsplit=1)
        if len(parts) != 2:
            return None
        condition, main = parts
    # Do not assign a login mentioned elsewhere to this conditional link.
    actor_pattern = '|'.join(_ROLES.values()) + r'|they|you|他们|其|你'
    if not re.fullmatch(r'\s*(?:' + actor_pattern + r')\s*(?:sign\s+in|log\s+in|登录|登入)\s*', condition, re.I):
        return None
    if len(_predicates(main)) != 1:
        return None
    predicates = {key for key, _ in _predicates(text)}
    if len(predicates) != 1:
        return None
    key = next(iter(predicates))
    if key[0] == 'promote':
        return None
    actors = [role for role, pattern in _ROLES.items() if re.search(pattern, condition, re.I)]
    if len(actors) > 1:
        return None
    actor = actors[0] if actors else key[-1]
    strength = 'necessary' if re.fullmatch(r'only if|只有|仅当', link.group(), re.I) else 'sufficient'
    return key, actor, strength


def _asserted_actions(text):
    """Reuse the existing subject/condition/selector boundaries for obligations.

    This local recognition copy only makes explicit necessity visible to the
    finite action inventory. The original modal text remains the support and
    still goes through the separate strength comparison and semantic review.
    """
    def recognition_modal(match):
        # "do not need to manage" is a role condition, not a synthetic
        # "Can manage" selector. Keep relative-role and negated necessity
        # intact; "must not manage" still becomes an independent ban.
        if re.search(r"(?:\b(?:not|never|who)|n['’]t|不|无)\s*$", match.string[:match.start()], re.I):
            return match.group()
        # A complete leading Chinese "necessary ... 的 role can ..."
        # modifier qualifies the role; it is not a second main assertion.
        prefix = re.split(r'[。；;.!?，,]', match.string[:match.start()])[-1].strip()
        roles = '|'.join(pattern.rsplit('|', 1)[-1] for pattern in _ROLES.values())
        if (not match.group()[0].isascii() and prefix in {'', '只有'}
                and re.match(r'管理(?:访问权限|权限)的(?:' + roles + r')(?:才)?(?:可以|能够|可)(?=编辑|评论|查看|阅读|创建|新建|分享|共享|管理)',
                             match.string[match.end():])):
            return match.group()
        return 'can' if match.group()[0].isascii() else '可以'
    text = re.sub(r'\b(?:must|needs? to|(?:is|are) required to|have to)\b|'
        r'必须|需要|需(?=编辑|评论|查看|阅读|创建|新建|分享|共享|管理)', recognition_modal, text, flags=re.I)
    return explicit_operation_assertions(text, independent=True)


def claim_semantic_reasons(claim, facts):
    if claim.dimension != 'feature':
        return ()
    quotes = _selected_support(claim, facts)
    if not quotes:
        return ()
    support = ' '.join(quotes)
    reasons = []
    # Reject only a complete, recognized nominal provision statement. Any
    # additional clause or unknown relationship can supply recipient support;
    # a matching summary at the end cannot erase that earlier source text.
    nominal_sharing = re.fullmatch(
        r'(?:(?:a|an|the|free|basic|paid)\s+)*(?:organizations?|workspaces?|plans?|accounts?)\s+'
        r'(?:offer|offers|provide|provides|support|supports)\s+'
        r'(?:both users\s+(?:all\s+)?(?:the\s+)?core\s+'
        r'(?:tools|features(?:\s+of\s+[A-Za-z][A-Za-z ]{0,60})?)\s+and\s+)?'
        r'(?:secure\s+)?(?:data sharing|sharing data)'
        r'(?:\s+in\s+(?:up to\s+)?(?:\d+|one|two|three)\s+collections?)?\s*[.!?]?', support, re.I)
    # A structured prerequisite can mention another actor's action without
    # granting this claim a second independent operation. Source spans use
    # only recognized main assertions, never a bag of all condition verbs.
    actions = ({claim.operation_binding.operation} if claim.operation_binding else _asserted_actions(support))
    if not actions and nominal_sharing:
        actions = {'share'}
    asserted = _asserted_actions(claim.text)
    if actions and asserted - actions:
        reasons.append('claim_semantics_action_outside_support')
    if nominal_sharing and _RECIPIENT.search(claim.text) and not _RECIPIENT.search(support):
        reasons.append('claim_semantics_recipient_outside_support')
    source_predicates = _predicates(support)
    for key, strength in _predicates(claim.text):
        mention_pattern = (_PROMOTE_MENTION.pattern if key[0] == 'promote' else
                           _MANAGE_MENTION if key[0] == 'manage_access' else _ACTIONS[key[0]])
        if len(re.findall(mention_pattern, support, re.I)) != sum(
                source_key[0] == key[0] for source_key, _ in source_predicates):
            # An unparsed same-action clause may itself supply necessity (e.g.
            # "promotion/editing ... is required"). Its absence from the
            # parsed list is not proof of strengthening; defer the judgment.
            continue
        matching = {source_strength for source_key, source_strength in source_predicates if source_key == key}
        if strength == 'necessary' and matching == {'possible'}:
            reasons.append('claim_semantics_modal_strengthened')
    condition = _login_condition(claim.text)
    source_conditions = [_login_condition(quote) for quote in quotes]
    if condition and any(item and item[:2] == condition[:2] and item[2] != condition[2]
                         for item in source_conditions):
        reasons.append('claim_semantics_condition_direction_changed')
    return tuple(dict.fromkeys(reasons))
