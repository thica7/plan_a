"""Conservative capability labels for selected, source-backed document facts.

Labels describe documented presence, not feature quality, absence or superiority.
The original field/slot identity remains intact for provenance and replay.
"""
from __future__ import annotations

import re
from functools import lru_cache

from packages.business_intel.entity_resolver import resolve_competitor_identity, resolve_identity_mention

_PATTERNS = {
    "shared_editing": r"(?:multiple people|team(?:mates| members)?|users|people).{0,65}(?:edit|collaborat).{0,65}(?:same|simultaneous|real.time)|edit the same page at the same time|real.time (?:co.edit|edit|collaborat)|多人.{0,20}(?:编辑|协作)|实时.{0,10}(?:编辑|协作)|同时.{0,10}编辑|共同编辑|协同编辑",
    "comments": r"\bcomments?\b|评论|批注",
    "mentions": r"\bmentions?\b|提及|@提醒",
    "permissions": r"\bpermissions?\b|access control|role.based access|(?:^|[\n.;])\s*(?:[|*-]\s*)?can (?:view|edit|comment)\s*[:|]|(?:full|view|edit|comment) access|权限|访问控制|仅查看|仅评论",
    "search": r"(?:search.{0,30}(?:pages?|documents?|content|knowledge)|(?:full.text|semantic) search)|搜索.{0,15}(?:页面|文档|内容|知识)",
    "organization": r"organize.{0,40}(?:pages?|documents?|knowledge)|(?:page|document) (?:tree|hierarchy)|组织.{0,15}(?:页面|文档|知识)|页面树",
    "automation": r"action formula|automat(?:e|ed|ion|ions)\b|自动化|动作公式",
}
_NEGATION = re.compile(r"cannot|can't|does not|doesn't|not (?:supported|available|enabled|permitted)|unavailable|unsupported|disabled|\bno\b|不支持|无法|不能|没有", re.I)
_CONDITION = re.compile(r"available (?:on|with|to)|requires?\b|\bonly\b|limited|restricted|\bsubscribers?\b|paid (?:plan|seat|workspace|user)|\bmust\b|需要|仅限|适用于|限制|付费", re.I)


def _evidence_terms(fact):
    terms = [fact.quote]
    if fact.field == "evidence_terms" and isinstance(fact.value, list):
        terms.extend(value for value in fact.value if isinstance(value, str))
    return terms


def capability_matches_text(key: str, text: str) -> bool:
    return key in _PATTERNS and bool(re.search(_PATTERNS[key], text, re.I))


def capability_keys(fact, products=()) -> tuple[str, ...]:
    # Frozen evidence plus the comparison scope is a complete cache key.
    # Candidate packing and credential replay repeatedly serialize these facts.
    return _capability_keys(fact, tuple(sorted(products)))


@lru_cache(maxsize=4096)
def _capability_keys(fact, products) -> tuple[str, ...]:
    terms = _evidence_terms(fact)
    if fact.dimension.casefold() != "feature" or fact.status != "supported":
        return ()
    # Shared/comparison passages do not establish which product owns a capability.
    # Check run-local names as well as registered identities, including aliases.
    target = resolve_competitor_identity(fact.competitor)
    target_name = target.canonical_name if target else fact.competitor
    for term in terms:
        if any(product.casefold() != fact.competitor.casefold()
               and re.search((r"(?<!\w)" + re.escape(product) + r"(?!\w)")
                             if product.isascii() else re.escape(product), term, re.I)
               for product in products):
            return ()
        for word in re.findall(r"\b[A-Za-z][A-Za-z0-9]*\b", term):
            identity = resolve_identity_mention(word, context=term)
            if identity and identity.canonical_name.casefold() != target_name.casefold():
                return ()
    # A restriction on another action (e.g. commenters cannot edit) does not
    # deny comments. Negative descriptions of this capability still deny it.
    clauses = [clause for term in terms for clause in re.split(r'[.;\n]|\bbut\b|\bhowever\b', term, flags=re.I)]
    return tuple(key for key, pattern in _PATTERNS.items()
                 if re.search(pattern, fact.quote, re.I)
                 and not any((_NEGATION.search(clause) and re.search(pattern, clause, re.I))
                             or re.search(r'\bwithout\s+(?:any\s+)?(?:' + pattern + ')', clause, re.I)
                             for clause in clauses))


def capability_conditioned(fact) -> bool:
    return bool(any(_CONDITION.search(term) or _NEGATION.search(term) for term in _evidence_terms(fact))
                or {key for key in fact.qualifiers if key not in {"slot", "operations", "source_scope"}}
                or any((row.get('role') or '').casefold() not in {'', 'you', 'users', 'people'}
                       or row.get('plan') or row.get('prerequisites')
                       for row in fact.qualifiers.get('operations', []) if isinstance(row, dict)))


def capability_alignment(view, products) -> list[dict]:
    groups = {}
    for fact in view.facts:
        if fact.source_id not in view.source_ids or fact.competitor not in products or fact.field != "evidence_terms":
            continue
        for key in capability_keys(fact, products):
            groups.setdefault(key, {}).setdefault(fact.competitor, []).append(fact)
    rows = []
    for key, evidence in sorted(groups.items()):
        statuses = {product: ("unknown" if product not in evidence else
                    "documented_with_conditions" if any(capability_conditioned(fact) for fact in evidence[product])
                    else "documented") for product in products}
        state = ("insufficient_evidence" if "unknown" in statuses.values() else
                 "needs_condition_review" if "documented_with_conditions" in statuses.values() else "comparable")
        rows.append({"capability_key": key, "comparison_status": state,
                     "product_statuses": statuses,
                     "evidence_by_product": {product: {
                         "fact_ids": sorted({fact.id for fact in facts}),
                         "source_ids": sorted({fact.source_id for fact in facts}),
                     } for product, facts in evidence.items()}})
    return rows
