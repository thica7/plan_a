"""Source-local plan dependencies for repeated, lexically bound capabilities.

Only explicit normalization of admitted items creates links. Reading an old
normalized record never repairs it or searches another source for conditions.
Unrecognized predicates remain separate observations for normal semantic review.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping

_DEPENDENCY = re.compile(
    r"\bdepending on\s+[^,.!?;\n]{0,100}\b(?:plans?|subscriptions?|tiers?|licen[cs]es?)\b", re.I
)
_CAN = re.compile(r"(?P<actor>[a-z][a-z -]{0,60}?)\s+can\s+(?:also\s+)?(?P<tail>[^.!?;\n]+)$", re.I)
_DETERMINER = r"(?:(?:your|the|a|an|their)\s+)?"
_MECHANISM_SET = re.compile(
    r"^(?:enhance|improve) security by (?:setting|adding|enabling)\s+"
    + _DETERMINER
    + r"(?P<mechanism>[a-z][a-z -]{0,40}?)\s+for\s+"
    + _DETERMINER
    + r"(?P<object>[a-z][a-z -]{0,40})$",
    re.I,
)
_DIRECT = re.compile(
    r"^(?P<action>[a-z]+)\s+"
    + _DETERMINER
    + r"(?P<object>[a-z][a-z -]{0,40}?)"
    + r"(?:\s+with\s+"
    + _DETERMINER
    + r"(?P<mechanism>[a-z][a-z -]{0,40}))?$",
    re.I,
)
_PUBLIC = re.compile(r"\bpublic\b|公开", re.I)
_PLAN_DEPENDENCY_CLAIM = re.compile(
    r"\bdepending on\b[^.!?;\n]{0,100}\b(?:plans?|subscriptions?|tiers?|licen[cs]es?)\b|"
    r"\b(?:depends?|dependent) on\b[^.!?;\n]{0,100}"
    r"\b(?:plans?|subscriptions?|tiers?|licen[cs]es?)\b|"
    r"(?:取决于|依赖于?|受制于|视)[^。；\n]{0,24}(?:套餐|订阅|许可)|"
    r"(?:套餐|订阅|许可)[^。；\n]{0,16}(?:决定|有关|而定)",
    re.I,
)
_ASSERTION = re.compile(
    r"\b(?:can|may|might|could|must|allow|allows|supports?|able to)\b|可以|能够|允许|支持|可为",
    re.I,
)
_DEPENDENCY_DENIED = re.compile(
    r"\bnot\s+(?:depend\w*|dependent)\b|\b(?:all|any|every)\s+plans?\b|"
    r"\bregardless of\b[^.;\n]{0,50}\bplans?\b|不取决于|无论[^。；]{0,12}套餐|所有套餐|任何套餐",
    re.I,
)
_SOURCE_TIER_CLARIFICATION = re.compile(
    r"the source does not (?:name|specify|list) a specific (?:plan|tier)|"
    r"原文(?:未|没有)(?:列出|指定|给出)具体套餐",
    re.I,
)


def _words(text):
    return tuple(re.findall(r"[a-z]+", text.casefold()))


def _singular(word):
    return word[:-1] if word.endswith("s") and not word.endswith(("ss", "as", "is", "us")) else word


def _signature(quote):
    """Read an explicit actor/action/object, never a bag of matching nouns.

    A source's 'enhance security by setting X for Y' and 'protect Y with X'
    describe the same protection mechanism. X and Y are arbitrary source terms;
    no product, plan name or mechanism name is supplied by this module.
    """
    text = quote.strip().rstrip(".!?")
    dependency = _DEPENDENCY.search(text)
    if dependency:
        text = text[dependency.end() :].lstrip(" ,")
    match = _CAN.fullmatch(text)
    if match is None:
        return None
    actor, tail = _words(match["actor"]), match["tail"]
    mechanism = _MECHANISM_SET.fullmatch(tail)
    direct = _DIRECT.fullmatch(tail)
    if mechanism:
        action = "protect"
        obj, instrument = _words(mechanism["object"]), _words(mechanism["mechanism"])
    elif direct:
        action = direct["action"].casefold()
        action = "protect" if action in {"protect", "secure", "safeguard"} else action
        obj, instrument = _words(direct["object"]), _words(direct["mechanism"] or "")
    else:
        return None
    if not obj or any(
        word in {"and", "or", "can", "not", "without", "unless"}
        for word in (*actor, *obj, *instrument)
    ):
        return None
    return actor, action, (*obj[:-1], _singular(obj[-1])), instrument


def _compatible(left, right):
    if left is None or right is None or left[:2] != right[:2] or left[3] != right[3]:
        return False
    # An unqualified repeated object may inherit the explicit source scope.
    # A different object or a contrary object modifier cannot inherit it.
    original, repeated = left[2], right[2]
    return original[-1] == repeated[-1] and set(repeated[:-1]) <= set(original[:-1])


def _same_context(left, right):
    if (
        left.competitor != right.competitor
        or left.dimension != right.dimension
        or not left.source_url
        or left.source_url != right.source_url
        or not left.captured_page_id
        or left.captured_page_id != right.captured_page_id
        or left.raw_source_id != right.raw_source_id
    ):
        return False
    # Preserve explicit context when a producer retained it. Missing HTML
    # headings cannot manufacture a section identity or an action match.
    for key in ("document_section", "section_path", "plan", "role"):
        if left.metadata.get(key) != right.metadata.get(key):
            return False
    for key in ("table_context", "plan", "role"):
        if left.value.get(key) != right.value.get(key):
            return False
    contexts = []
    for value in (left.value, right.value):
        rows = value.get("operations", [])
        if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
            return False
        try:
            # Each complete branch keeps its actor, plan, action and conditions
            # paired. Comparing columns separately could swap their meaning.
            contexts.append(
                tuple(
                    sorted(json.dumps(dict(row), sort_keys=True, allow_nan=False) for row in rows)
                )
            )
        except (TypeError, ValueError):
            return False
    return contexts[0] == contexts[1]


def source_condition_links(item, accepted_items):
    """Return complete original constraints with their admitted item identity."""
    if (
        item.status != "accepted"
        or item.dimension != "feature"
        or not isinstance(item.value, Mapping)
    ):
        return []
    signature = _signature(item.quote)
    result = []
    for source in accepted_items:
        if (
            source.status != "accepted"
            or not isinstance(source.value, Mapping)
            or not _same_context(source, item)
            or not _DEPENDENCY.search(source.quote)
            or source.value.get("status") not in {"supported", "documented"}
        ):
            continue
        original = _signature(source.quote)
        if not _compatible(original, signature):
            continue
        result.append(
            dict(
                kind="plan_dependency",
                quote=source.quote,
                evidence_item_id=source.id,
                captured_page_id=source.captured_page_id,
                source_url=source.source_url,
                competitor=source.competitor,
                object_scope="public" if "public" in original[2][:-1] else None,
            )
        )
    return sorted(result, key=lambda row: (row["evidence_item_id"], row["quote"]))


def _named_plans(text):
    # Generic dependency mentions are not named tiers. Any actual tier assertion
    # must already occur in the source; an unknown source tier stays unknown.
    values = set()
    for match in re.finditer(
        r"\b([a-z][\w+-]*)\s+(?:plans?|subscriptions?|tiers?|licen[cs]es?)\b|"
        r"([a-z][\w+-]*)\s*套餐",
        text,
        re.I,
    ):
        name = (match[1] or match[2]).casefold()
        if name not in {"your", "the", "a", "any", "all", "each", "specific", "their", "our", "my"}:
            values.add(name)
    for match in re.finditer(
        r"(?:取决于|依赖于?|受制于|视)([^，。；,.;]{0,40}?)(?:套餐|订阅|许可)", text
    ):
        name = re.sub(r"你(?:的)?|所用|所选|当前|具体|使用的|团队的|的", "", match[1]).strip()
        if name:
            values.add(name.casefold())
    for match in re.finditer(r"(免费|付费|收费)\s*(?:版)?\s*(?:套餐|订阅|许可)", text):
        values.add("free" if match[1] == "免费" else "paid")
    return values


def _assertion_conditions(text):
    """Retain every substantive clause, even without a recognized modal."""
    result = []
    for sentence in re.split(r"[.!?。；;\n]|\bbut\b|但是|然而", text, flags=re.I):
        pending = ""
        clauses = [part.strip() for part in re.split(r"[,，]", sentence) if part.strip()]
        for part in clauses:
            if _SOURCE_TIER_CLARIFICATION.fullmatch(part):
                # This exact provenance clarification asserts no capability.
                # A following clause still undergoes the ordinary checks.
                pending = ""
            elif not _ASSERTION.search(part) and _PLAN_DEPENDENCY_CLAIM.fullmatch(part):
                # Only a complete condition-only prefix scopes the next clause.
                pending = (pending + " " + part).strip()
            else:
                result.append((pending + " " + part).strip())
                pending = ""
        if pending:
            result.append(pending)
    return result


def claim_source_condition_reasons(claim, facts):
    """Replay new condition receipts against this claim's own assertions.

    These checks only reject identifiable loss of scope. Semantic entailment
    and unrelated capabilities continue through the existing model review.
    """
    reasons = []
    for fact in facts:
        links = fact.qualifiers.get("source_condition_links", [])
        if not isinstance(links, list):
            continue
        for link in links:
            if (
                not isinstance(link, dict)
                or link.get("kind") != "plan_dependency"
                or not isinstance(link.get("quote"), str)
                or not _DEPENDENCY.search(link["quote"])
            ):
                continue
            assertions = _assertion_conditions(claim.text)
            if (
                not all(_PLAN_DEPENDENCY_CLAIM.search(part) for part in assertions)
                or _named_plans(claim.text) - _named_plans(link["quote"])
                or _DEPENDENCY_DENIED.search(claim.text)
            ):
                reasons.append("source_plan_condition_omitted_or_changed")
            if link.get("object_scope") == "public" and not all(
                _PUBLIC.search(part) for part in assertions
            ):
                reasons.append("source_public_scope_omitted_or_changed")
    return tuple(dict.fromkeys(reasons))
