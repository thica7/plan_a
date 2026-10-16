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
    explicit_actions = set()
    for part in parts:
        if re.match(r"\s*(?:前提|条件|requires?\b|provided\b|subject to\b)", part, re.I):
            continue
        if permission_selector_context(part):
            explicit_actions.add("manage_access")
        assertion = re.search(
            r"\b(?:can|cannot|may|supports?)\s+(?:(?:only|also)\s+)?(?:edit|comment|create|read|view|share|manage)\b|"
            r"(?:不能|可以|能够|支持|可)(?:编辑|评论|查看|阅读|创建|新建|分享|管理)(?!权限|级别|选项)",
            part,
            re.I,
        )
        if assertion:
            explicit_actions.update(
                operation
                for operation in ("read", "comment", "edit", "create", "share", "manage_access")
                if operation_matches_text(operation, part[assertion.start() :])
            )
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
