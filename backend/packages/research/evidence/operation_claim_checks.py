"""Explicit source-condition review, plus bounded recognizers for known risks.

These rules reject recognizable omissions/contradictions. Passing them is not a
general semantic proof: the separate reviewer must still check each source span.
"""

from __future__ import annotations

import hashlib
import re

from packages.research.evidence.snapshot_models import canonical_json


def _values(binding):
    return binding.model_dump(mode="json") if hasattr(binding, "model_dump") else binding


def required_operation_checks(binding):
    bound = _values(binding)
    if not bound or not any(
        bound.get(key) for key in ("prerequisites", "recipient_quote", "excluded_roles")
    ):
        return []
    rows = [
        (key, bound.get(field))
        for key, field in (
            ("operation", "operation_quote"),
            ("role", "role"),
            ("object", "object_quote"),
            ("effect", "effect"),
            ("recipient", "recipient_quote"),
        )
        if bound.get(field)
    ]
    rows.extend(("exclusion", role) for role in bound.get("excluded_roles", ()))
    rows.extend(("prerequisite", item["quote"]) for item in bound["prerequisites"])
    return [
        {
            "check_id": "operation-check-"
            + hashlib.sha256(
                canonical_json(
                    {"observation_id": bound["observation_id"], "kind": kind, "quote": quote}
                ).encode()
            ).hexdigest()[:24],
            "kind": kind,
            "quote": quote,
        }
        for kind, quote in dict.fromkeys(rows)
    ]


def operation_review_reasons(claim, review):
    required = required_operation_checks(claim.operation_binding)
    if not required:
        return []
    checks = review.checks
    expected = {item["check_id"] for item in required}
    identifiers = [item.check_id for item in checks]
    reasons = []
    if set(identifiers) != expected or len(identifiers) != len(expected):
        reasons.append("operation_checks_incomplete")
    if any(check.verdict != "supported" for check in checks):
        reasons.append("operation_check_not_supported")
    if any(not check.claim_span.strip() or check.claim_span not in claim.text for check in checks):
        reasons.append("operation_check_span_invalid")
    return reasons


_LOGIN = re.compile(
    r"\b(?:sign(?:ed|ing)?\s+in(?:to)?|log(?:ged|ging)?\s+in(?:to)?)\b|登录|登入", re.I
)
_NO_LOGIN = re.compile(
    r"\b(?:without|no need to|need not|not (?:need|required) to|do(?:es)? not (?:need|have) to)\b[^.;，。；]{0,32}\b(?:sign|log)|免登[录入]|(?:无需|不必|不需要)[^。；，]{0,8}(?:登录|登入)",
    re.I,
)
_PLAN_TOKENS = {
    "paid": r"\bpaid\b|付费",
    "education": r"\beducation\b|教育",
    "starter": r"\bstarter\b",
    "free": r"\bfree\b|免费",
    "enterprise": r"\benterprise\b|企业版",
    "business": r"\bbusiness\b",
    "professional": r"\bprofessional\b",
    "standard": r"\bstandard\b",
    "premium": r"\bpremium\b",
    "pro": r"\bpro\b",
}


def explicit_operation_assertions(text, *, independent=False):
    """Recognize a small set of asserted verbs, excluding subject/condition mentions.

    This is only an extra-action guard. Unknown verbs and same-action object
    changes still require the independent, selected-support semantic review.
    """
    from packages.research.evidence.operations import OPERATIONS, ROLE_LABELS, _ACTOR, _PERMISSION_SELECTION, operation_matches_text, permission_selector_context

    actions = set()
    parts = re.split(r"[。；;.!?]|\b(?:while|but|however)\b|但是|然而", text, flags=re.I)
    if independent:
        # A later explicit subject/modal assertion is independent of a preceding
        # trailing condition. Keep it outside operation_matches_text's cutoff.
        parts = [clause for part in parts for clause in re.sub(
            r'[,，]\s*and\s+(?=(?:(?:' + _ACTOR.pattern + r'|they|it)\s+)?(?:can|cannot|may)\b)',
            "\n", part, flags=re.I).splitlines()]
    for part in parts:
        if re.match(r"\s*(?:前提|条件|requires?\b|provided\b|subject to\b)", part, re.I):
            continue
        if permission_selector_context(part):
            actions.add("manage_access")
        if independent:
            part = _PERMISSION_SELECTION.sub("", part)
            part = re.sub(r"[\"'“‘](?:" + ROLE_LABELS + r")[\"'”’]", "§role§", part, flags=re.I)
            part = re.sub(r"((?:拥有|具有|持有|\bwith|\bhas|\bhave)\s+)(?:" + ROLE_LABELS + r")",
                          r"\1§role§", part, flags=re.I)
            if re.match(r'^\s*(?:(?:only\s+)?(?:if|when|after|before)\b|只有|仅当|如果|若)', part, re.I):
                condition = re.split(r'[,，]|\bthen\b', part, maxsplit=1, flags=re.I)
                if len(condition) == 2:
                    part = condition[1]
                elif main := re.search(r'\b(?:can|cannot|may)\s+(?:' + _ACTOR.pattern +
                        r')\s+(?:edit|comment|create|read|view|share|manage)\b', part, re.I):
                    # The inverted modal+actor begins the main clause; an
                    # earlier actor+modal belongs to the front prerequisite.
                    part = part[main.start():]
                # Inverted 'Only after X can guests share' and Chinese 才可以
                # still have an explicit main predicate without a comma. Keep
                # scanning it; an unknown split must not hide asserted verbs.
        pattern = (
            r"\b(?:can|cannot|may|supports?)\s+(?:(?:only|also)\s+)?(?:edit|comment|create|read|view|share|manage)\b|"
            r"(?:不能|可以|能够|支持|可)(?:编辑|评论|查看|阅读|创建|新建|分享|管理)(?!权限|级别|选项)"
        )
        if independent:
            pattern = (
                r"\b(?:can|cannot|may|supports?)\s+(?:(?:only|also|not)\s+)?"
                r"(?:(?:" + _ACTOR.pattern + r")\s+)?(?:edit|comment|create|read|view|share|manage)\b|"
                r"(?:不能|无法|不得|可以|能够|有权|支持|可)[^。；;.!?，,\n]{0,48}?"
                r"(?:编辑|评论|查看|阅读|创建|新建|分享|共享|管理)(?!级别|选项)"
            )
        assertion = re.search(pattern, part, re.I)
        if not assertion:
            continue
        predicate = part[assertion.start():]
        if independent:
            predicate = re.split(r'前提(?:是|为)|条件(?:是|为)|\b(?:provided that|subject to|on condition that)\b',
                                 predicate, maxsplit=1, flags=re.I)[0]
        # "manage access to documents" is not an independent read action.
        read_predicate = re.sub(OPERATIONS['manage_access'][1], '', predicate, flags=re.I) if independent else predicate
        actions.update(operation for operation in OPERATIONS
                       if operation_matches_text(operation, read_predicate if operation == 'read' else predicate))
        if independent and operation_matches_text('share', predicate.replace('共享', '分享')):
            actions.add('share')
    return actions


def operation_review_support(binding):
    """Project true structured conditions; condition_evidence also contains hints.

    Retain the original saved binding for identity/check hashes. This projection
    is only the semantic review input; an unrepresented explicit dependency
    fails closed during the same v3 replay as the independent-action guard.
    """
    from packages.research.evidence.operations import OPERATIONS, condition_operations

    bound = dict(_values(binding))
    selected = list(dict.fromkeys([bound['operation_quote'],
        *(item['quote'] for item in bound.get('prerequisites', ())),
        *(option for group in bound.get('condition_groups', ()) for option in group['options'])]))
    normalize = lambda text: text.strip().rstrip(' .。;；\\').casefold()
    unresolved = False
    for quote in bound.get('condition_evidence', ()):
        if any(normalize(quote) in normalize(item) for item in selected):
            continue
        dependency = re.search(r'\b(?:contingent on|subject to|conditional on|provided that|only\s+(?:after|before|if|when)|requires?|must|needs? to|prerequisites?)\b|前提|取决于|需要|必须|除非', quote, re.I)
        if not dependency:
            continue
        # Associate the dependency with its governed assertion. A condition's
        # internal action (e.g. admins manage access) is not the target action.
        head = quote[:dependency.start()]
        actions = explicit_operation_assertions(head if head.strip() else quote, independent=True)
        if not actions and head.strip():
            # Nominalized known actions such as Sharing/Editing name the target
            # without asserting that the condition's actor can perform them.
            read_head = re.sub(OPERATIONS['manage_access'][1], '', head, flags=re.I)
            actions = {operation for operation in OPERATIONS if re.search(OPERATIONS[operation][1],
                read_head if operation == 'read' else head, re.I)}
        if not actions and re.fullmatch(r'must|needs? to|需要|必须', dependency.group(), re.I):
            # 'Members must sign in to edit' puts the governed action after
            # the modal. Its explicit edit restriction remains local to edit.
            actions = condition_operations(quote)
        if not actions or bound['operation'] in actions:
            unresolved = True
    bound['condition_evidence'] = selected
    return bound, ('operation_condition_support_unresolved',) if unresolved else ()


def independent_operation_reasons(claim):
    """v3-only replay gate for explicit actions beyond the selected observation."""
    if claim.operation_binding is None:
        return ()
    _, reasons = operation_review_support(claim.operation_binding)
    actions = explicit_operation_assertions(claim.text, independent=True)
    if actions - {claim.operation_binding.operation}:
        return (*reasons, 'operation_assertion_outside_binding')
    return reasons


def operation_condition_reasons(claim, bound):
    """Conservative checks of explicit forms; unknown phrasing stays with QA."""
    from packages.research.evidence.operations import (
        acting_role_match,
        role_key,
        operation_matches_text,
        _plan_from_text,
        _ROLE,
        ROLE_LABELS,
        permission_selector_context,
        condition_operations,
    )

    text, reasons = claim.text, []
    parts = re.split(r"[。；;.!?]|\b(?:while|but|however)\b|但是|然而", text, flags=re.I)
    actors = []
    for part in parts:
        if not operation_matches_text(bound["operation"], part):
            continue
        if (bound.get("role", "") or "").casefold().startswith("can ") and re.search(
            re.escape(bound["role"]), part, re.I
        ):
            actors.append(role_key(bound["role"]))
        elif actor := acting_role_match(part):
            actors.append(role_key(actor.group()))
    if bound["effect"] == "allowed" and not bound.get("role"):
        specific_actor = any(
            re.match(
                r"\s*(?:(?:角色|用户)\s*)?(?:\b(?:can|cannot|may|is allowed to|are allowed to)\b|可以|能够|有权|可(?=编辑|评论|查看|阅读|创建|新建|分享|管理))",
                part[role.end() :],
                re.I,
            )
            for part in parts
            for role in _ROLE.finditer(part)
            if not role.group().casefold().startswith("can ")
        )
        universal = re.search(
            r"\b(?:all|any|every)\s+(?:users?|people|members?|guests?)\b|\beveryone\b|(?:所有|全部|任何)(?:用户|成员|访客|人)",
            text,
            re.I,
        )
        selector = re.search(
            r"\b(?:select|choose|set)\s+(?:" + ROLE_LABELS + r")", bound["operation_quote"], re.I
        )
        if specific_actor or universal or selector:
            reasons.append("operation_required_scope_unknown")
    if actors and bound.get("role") and role_key(bound["role"]) not in actors:
        reasons.append("operation_role_mismatch")
    if not bound.get("prerequisites"):
        return reasons
    if (
        any(item["kind"] == "role_scoped" for item in bound["prerequisites"])
        and bound["effect"] == "allowed"
    ):
        reasons.append("operation_condition_scope_unresolved")
    # A finite verb matcher may miss a legitimate translation. Only an
    # explicitly recognized different assertion supplies a deterministic block.
    explicit_actions = explicit_operation_assertions(text)
    if explicit_actions and bound["operation"] not in explicit_actions:
        reasons.append("operation_assertion_mismatch")
    if (
        bound.get("object_type") == "board"
        and re.search(r"\b(?:documents?|docs?|pages?)\b|页面|文档", text, re.I)
        and not re.search(r"\bboards?\b|看板", text, re.I)
    ):
        reasons.append("operation_object_mismatch")
    for item in bound["prerequisites"]:
        quote = item["quote"]
        if item["kind"] == "permission_option":
            claimed_actions = condition_operations(text) | permission_selector_context(text).get("operations", set())
            if not claimed_actions & set(item["operations"].split(",")):
                continue
        login_required = (
            _LOGIN.search(quote)
            and re.search(
                r"\b(?:must|need(?:s)? to|(?:is|are) required to|have to)\b|需要|必须", quote, re.I
            )
            and not _NO_LOGIN.search(quote)
        )
        if login_required and (not _LOGIN.search(text) or _NO_LOGIN.search(text)):
            reasons.append("operation_login_condition_omitted_or_changed")
        direct_invitation = re.search(
            r"\bonly\b[^.;\n]*\baccess\b[^.;\n]*\bdirectly invited\b", quote, re.I
        ) or re.search(r"只能[^。；]*直接(?:受邀|邀请)", quote)
        if direct_invitation:
            preserved = re.search(
                r"\bonly\b[^.;\n]*\b(?:directly invited|direct invitation)\b|(?:只能|仅能|仅限)[^。；]{0,60}直接(?:受邀|邀请)",
                text,
                re.I,
            )
            widened = re.search(
                r"\b(?:all|every|any)\s+(?:the\s+)?boards?\b|(?:所有|全部|任意)(?:团队)?看板",
                text,
                re.I,
            )
            if not preserved or widened:
                reasons.append("operation_invitation_scope_omitted_or_changed")
        plan = _plan_from_text(quote)
        if plan and re.search(r"\bonly\b|\brequires?\b|仅限|才能", quote, re.I):
            required = {
                name for name, pattern in _PLAN_TOKENS.items() if re.search(pattern, plan, re.I)
            }
            stated = {
                name for name, pattern in _PLAN_TOKENS.items() if re.search(pattern, text, re.I)
            }
            universal = re.search(
                r"\b(?:all|any|every) plans?\b|(?:所有|全部|任意)套餐", text, re.I
            )
            if required and (not required <= stated or universal):
                reasons.append("operation_plan_condition_omitted_or_changed")
    return list(dict.fromkeys(reasons))
