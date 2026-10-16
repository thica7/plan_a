"""Conservative boundaries for a separately reviewed answer resolution.

These checks establish structure and exact claim excerpts. The small object and
role vocabulary detects explicit scope conflicts; it does not establish textual
entailment, a role hierarchy, or completeness of an otherwise accepted answer.
Unknown objects and unrecognised subjects remain for the semantic reviewer.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

_OBJECT = re.compile(
    r"(?P<message>\b(?:(?:private|direct|instant)\s+)?messages?\b|私信|私聊|消息)"
    r"|(?P<folder>\bfolders?\b|文件夹)"
    r"|(?P<board>\bboards?\b|看板|白板)"
    r"|(?P<document>\b(?:documents?|docs?)\b|文档)"
    r"|(?P<page>\bpages?\b|页面)"
    r"|(?P<task>\btasks?\b|任务)",
    re.I,
)
_SUBJECT = re.compile(
    r"(?P<workspace_admin>\bworkspace\s+(?:admins?|administrators?)\b|工作区管理员)"
    r"|(?P<guest>\bguests?\b|访客|来宾)"
    r"|(?P<visitor>\bvisitors?\b|游客)"
    r"|(?P<editor>\beditors?\b|编辑者)"
    r"|(?P<viewer>\bviewers?\b|查看者)"
    r"|(?P<admin>\b(?:admins?|administrators?)\b|管理员)"
    r"|(?P<owner>\bowners?\b|所有者)"
    r"|(?P<member>\bmembers?\b|成员)"
    r"|(?P<collaborator>\bcollaborators?\b|协作者)"
    r"|(?P<generic>\b(?:people|users?|you)\b|用户|人们|你们?)",
    re.I,
)
_PREDICATE = re.compile(
    r"\b(?:can(?:not)?|may|must|needs?|requires?|has|have|is|are|access|edit|"
    r"modify|send|view|read|create|invite|share|sign|become)\b"
    r"|可以|能够|可(?=编辑|查看|访问|创建|发送)|不能|无法|必须|需要|需(?=登录)|"
    r"访问|编辑|发送|查看|阅读|创建|邀请|分享|登录|成为|是",
    re.I,
)
_SUBJECT_MODAL = re.compile(
    r"\b(?:can(?:not)?|could|may|must|needs?|requires?|has|have|is|are)\b"
    r"|可以|能够|可(?=编辑|查看|访问|创建|发送)|不能|无法|必须|需要|需(?=登录)|是",
    re.I,
)
_RECIPIENT_PREFIX = re.compile(
    r"\b(?:to|for|by|with|from|except|excluding|without|inviting|invite)"
    r"\s+(?:(?:the|a|an|non[- ]|team|workspace)\s*)*$|(?:给|向|由|为|除)\s*$",
    re.I,
)
_OPEN_QUESTION = re.compile(
    r"\b(?:how|which|what|when|where|why|explain|describe|list)\b"
    r"|如何|怎样|什么|哪些|多少|何时|哪里|为何|说明|解释|列出",
    re.I,
)
_CLOSED_QUESTION = re.compile(
    r"(?:^|[:：,，]\s*)(?:can|could|does|do|did|is|are|must|may|will|would|has|have)\b"
    r"|是否|能否|可否|是不是|吗[？?]?",
    re.I,
)
_ANSWER_ASSERTION = re.compile(
    r"\b(?:yes|no|can(?:not)?|can['’]t|may|must|requires?|required|needs?|allowed|"
    r"permitted|supported|unsupported|available|unavailable|limited|restricted|depends|"
    r"access|edit|modify|send|view|read|create|invite|share|sign|become)\b"
    r"|\b(?:has|have)\s+access\b|(?:^|[，,。；;]\s*)(?:是|否|能)(?=[，,。；;\s]|$)"
    r"|可以|能够|不能|无法|不允许|允许|支持|不支持|需要|必须|仅限|取决于",
    re.I,
)
_USER_CATEGORY = re.compile(
    r"\buser\s+(?:categor(?:y|ies)|types?)\b"
    r"|\b(?:types?|categor(?:y|ies))\s+of\s+(?:(?:external|internal)\s+)?users?\b"
    r"|(?:用户|账号)(?:类型|类别)",
    re.I,
)
_SCOPE_UNIT = re.compile(r"[^。；;.!?？\n]+[。；;.!?？\n]?")
_CLAUSE_BOUNDARY = re.compile(
    r"[,，]\s*(?:(?:and|while|but|whereas)\s+|而|但是|但)?"
    r"|\b(?:and|while|but|whereas)\s+",
    re.I,
)
_CLARIFICATION = re.compile(
    r"\b(?:which|what|when|where|who|how)\b[^.!。]*[?？]"
    r"|\b(?:please|could you|can you)\s+(?:provide|specify|confirm|clarify|tell)\b"
    r"|\b(?:need to know|need (?:the|your)|missing (?:the|your))\b"
    r"|请(?:提供|说明|确认|告知|补充)|(?:需要|缺少|尚缺|待确认)[^。.!]{1,60}"
    r"|(?:何时|哪个|哪些|什么|多少|是否)[^。.!]*[？?]",
    re.I,
)


def _objects(text: str) -> set[str]:
    return {match.lastgroup for match in _OBJECT.finditer(text)}


def _subjects(text: str) -> tuple[set[str], bool]:
    """Recognise simple subjects, excluding recipients and comma conditions."""
    text = re.sub(r",\s*including\s+([^,]+),\s*", r" and \1 ", text, flags=re.I)
    text = re.sub(
        r",\s*(?:after|before|when|once|if)\b[^,]*,\s*"
        r"(?=(?:can|cannot|could|may|must)\b)",
        " ", text, flags=re.I,
    )
    subjects, found = set(), False
    clauses = re.split(r"[。；;.!?？\n,，]", text)
    object_clauses = [clause for clause in clauses if _objects(clause)]
    for clause in object_clauses or clauses:
        predicate = _SUBJECT_MODAL.search(clause) or _PREDICATE.search(clause)
        if not predicate:
            continue
        prefix = clause[: predicate.start()]
        # Inverted questions put the subject after their initial modal verb.
        if not _SUBJECT.search(prefix) and predicate.group().casefold() in {
            "can", "could", "is", "are", "must", "may", "will", "would",
        }:
            following = clause[predicate.end() :]
            next_predicate = _PREDICATE.search(following)
            prefix = following[: next_predicate.start()] if next_predicate else following
        previous_end = None
        for match in _SUBJECT.finditer(prefix):
            if _RECIPIENT_PREFIX.search(prefix[: match.start()]):
                continue
            if previous_end is not None and not re.fullmatch(
                r"\s*(?:and|or|&|和|或|、|及)\s*", prefix[previous_end : match.start()], re.I
            ):
                break
            found = True
            if match.lastgroup != "generic":
                subjects.add(match.lastgroup)
            previous_end = match.end()
    return subjects, found


def _span_contexts(quote: str, claim_text: str) -> list[str]:
    """Preserve the source sentence of a fragment, never another sentence."""
    units = list(_SCOPE_UNIT.finditer(claim_text))
    contexts = []
    for occurrence in re.finditer(re.escape(quote), claim_text):
        contexts.extend(
            unit.group().strip()
            for unit in units
            if unit.start() < occurrence.end() and occurrence.start() < unit.end()
        )
    return list(dict.fromkeys(contexts))


def _independent_contexts(text: str) -> list[str]:
    """Split explicit actor/object assertions, preserving subject conjunctions."""
    contexts, start = [], 0
    for boundary in _CLAUSE_BOUNDARY.finditer(text):
        left, right = text[start : boundary.start()], text[boundary.end() :]
        if _objects(left) and _objects(right) and _subjects(left)[1] and _subjects(right)[1]:
            contexts.append(left)
            start = boundary.end()
    contexts.append(text[start:])
    return contexts


def resolution_reasons(
    answer: dict, question: str, claims: Iterable[dict]
) -> tuple[str, ...]:
    """Return deterministic rejection reasons; an empty tuple is not NLI proof.

    The caller validates the DTO and limits claims to the published evidence.
    ``reason`` is deliberately never used as the visible answer or as evidence.
    Pricing arithmetic and source date exceptions have separate validators.
    """
    reasons = []
    body = answer.get("answer", "").strip()
    resolution = answer.get("resolution")
    conclusion = answer.get("conclusion")

    if resolution == "clarification":
        if not body or not _CLARIFICATION.search(body):
            reasons.append("clarification_missing")
        return tuple(reasons)
    if resolution == "insufficient":
        if conclusion != "unknown":
            reasons.append("insufficient_conclusion_invalid")
        if not any(str(field).strip() for field in answer.get("missing_fields", [])):
            reasons.append("insufficient_fields_missing")
        return tuple(reasons)
    if answer.get("status") not in {"answered", "partial"} or resolution not in {
        "direct", "conditional",
    }:
        return ()

    open_question = bool(_OPEN_QUESTION.search(question)) and not _CLOSED_QUESTION.search(question)
    if not body:
        reasons.append("answer_body_missing")
    elif (
        not open_question
        and _CLOSED_QUESTION.search(question)
        and not _ANSWER_ASSERTION.search(body)
    ):
        reasons.append("answer_body_unresolved")
    if conclusion == "unknown" or conclusion == "not_applicable" and not open_question:
        reasons.append("answer_conclusion_missing")

    published = {row["id"]: row["text"] for row in claims}
    claim_ids = answer.get("claim_ids", [])
    valid_spans = []
    covered = set()
    for span in answer.get("evidence_spans", []):
        claim_id, quote = span.get("claim_id"), span.get("quote")
        if (
            claim_id not in claim_ids
            or claim_id not in published
            or not isinstance(quote, str)
            or not re.search(r"\w", quote)
            or quote not in published[claim_id]
        ):
            reasons.append("evidence_span_invalid")
            continue
        covered.add(claim_id)
        valid_spans.append((quote, published[claim_id]))
    if not claim_ids or set(claim_ids) - covered:
        reasons.append("claim_evidence_missing")

    question_objects = _objects(question)
    body_objects = _objects(body)
    if question_objects and body_objects and question_objects.isdisjoint(body_objects):
        reasons.append("answer_object_mismatch")

    # A short excerpt cannot erase its sentence's object/subject, and separate
    # source sentences cannot supply each other's subjects and objects.
    scopes = []
    for quote, claim_text in valid_spans:
        contexts = [
            clause
            for sentence in _span_contexts(quote, claim_text)
            for clause in _independent_contexts(sentence)
        ]
        for context in contexts:
            objects = _objects(context)
            subjects, _ = _subjects(context)
            definition_only = not objects and bool(_USER_CATEGORY.search(context))
            scopes.append((objects, subjects, definition_only))
    relevant = [
        (objects, subjects)
        for objects, subjects, definition_only in scopes
        if not question_objects
        or not definition_only and (not objects or not question_objects.isdisjoint(objects))
    ]
    if scopes and not relevant:
        reasons.append(
            "question_scope_not_grounded"
            if any(definition_only for _, _, definition_only in scopes)
            else "question_object_mismatch"
        )
    question_subjects, _ = _subjects(question)
    body_subjects, _ = _subjects(body)
    if question_subjects and body_subjects and question_subjects.isdisjoint(body_subjects):
        reasons.append("answer_role_mismatch")
    if question_subjects and relevant:
        grounded_subjects = set().union(*(subjects for _, subjects in relevant))
        if question_subjects.isdisjoint(grounded_subjects):
            reasons.append(
                "question_role_mismatch" if grounded_subjects else "question_role_not_grounded"
            )
    return tuple(dict.fromkeys(reasons))
