"""Reject finite, explicit operation omissions in published question answers.

This is a negative check, not an entailment engine: a matching verb does not
prove actor, object, polarity or prerequisites. The semantic review still owns
those checks. Source text and review reasons cannot complete published claims.
"""

import re

_ACTIONS = {
    "download": r"\bdownload(?:s|ed|ing)?\b|下载",
    "export": r"\bexport(?:s|ed|ing)?\b|导出",
    "import": r"\bimport(?:s|ed|ing)?\b|导入",
    "vote": r"\b(?:vot(?:e[ds]?|ing)|cast\s+(?:a\s+)?votes?)\b|投票",
    "purge_cache": r"\b(?:purge|purging|invalidate|invalidating|clear|clearing)\b"
    r"[^?？。;；]{0,60}\bcache\b"
    r"|(?:清除|清空|失效)[^?？。;；]{0,60}缓存",
}
_REQUEST = re.compile(
    r"\b(?:can|could|must|may|does|do|is|are|should|how|which|what)\b"
    r"|是否|能否|可否|能不能|可不可以|如何|哪些|(?:他|她|它|用户|成员)(?:们)?能|可以|必须",
    re.I,
)
_QUESTION = re.compile(
    r"[?？]|吗(?=[？?。；;\s]|$)|是否|能否|可否|如何|哪些|\b(?:how|which|what)\b", re.I
)
_INVERTED = re.compile(r"^\s*(?:can|could|must|may|does|do|is|are|should)\b", re.I)
_LEADING_CONTEXT = re.compile(
    r"^\s*(?:if|when|after|before|once|assuming)\b[^,]*,\s*"
    r"|^\s*(?:如果|若|假设)[^，,]*[，,]\s*"
    r"|^\s*在[^，,]*(?:之后|之前|时|上|下|中|内)[，,]\s*",
    re.I,
)
_TRAILING_CONTEXT = re.compile(r"\b(?:after|before|once|only if|if|provided that)\b", re.I)
_NEW_REQUEST = r"(?:can|could|must|may|does|do|is|are|should)\b|是否|能否|可否"
_INSERTED_CONTEXT = re.compile(r",\s*(?:after|before|once|if|when)\b[^,]+,", re.I)


def requested_answer_actions(question):
    """Recognize explicit requests, keeping preceding scenario prose out.

    Only a finite verb vocabulary is used. Open-ended descriptions, unknown
    verbs and implicit references remain the independent reviewer's task.
    """
    result = set()
    # Wrapped lines and semicolons can continue one compound request. Only
    # sentence endings split it; a missing question mark does not drop a
    # complete inverted English question.
    # A separator followed by a new explicit question ends preceding scenario
    # prose; a conjunction after the separator continues the same request.
    text = re.sub(r"(?:[;；]|\n)\s*(?=" + _NEW_REQUEST + ")", "。 ", question, flags=re.I)
    for unit in re.split(r"(?<=[?？。！!])|(?<=\.)\s+(?=[A-Z])", " ".join(text.split())):
        # "Can observers, after voting, download?" keeps the main predicate.
        unit = _INSERTED_CONTEXT.sub(" ", unit)
        unit = _LEADING_CONTEXT.sub("", unit).strip()
        if not _QUESTION.search(unit) and not _INVERTED.match(unit):
            continue
        request = _REQUEST.search(unit)
        text = unit[request.start() :] if request else unit
        context = _TRAILING_CONTEXT.search(text)
        if context:
            # Only the main request supplies operation targets. This omission
            # check does not verify the adjacent scenario/condition itself.
            text = text[: context.start()]
        result.update(key for key, pattern in _ACTIONS.items() if re.search(pattern, text, re.I))
    return result


def answer_action_scope_reasons(record, claims):
    if record.resolution not in {"direct", "conditional"} or record.status not in {
        "answered",
        "partial",
    }:
        return ()
    # A qualified partial answer may state the known subset. It cannot use a
    # definite yes/no to settle other requested operations that remain absent.
    if record.status == "partial" and record.conclusion not in {"yes", "no"}:
        return ()
    requested = requested_answer_actions(record.question)
    selected = [row["text"] for row in claims if row["id"] in record.claim_ids]
    missing = {
        action
        for action in requested
        if not any(re.search(_ACTIONS[action], text, re.I) for text in selected)
    }
    return ("answer_operation_not_grounded",) if missing else ()
