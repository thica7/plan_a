"""Server-owned task targets and conservative evidence applicability guards.

These restrictions do not establish entailment. Complete source bindings and
independent source/task reviews remain mandatory after an applicable SELECT.
"""

import hashlib
import json
import re
from copy import deepcopy

CONTRACT = "semantic-target-clauses-v2"
_INVITATION = re.compile(r"\binvit(?:e[ds]?|ation)s?\b|邀请", re.I)
_ACCESS = re.compile(r"\baccess\b|\bjoin\b|同时.{0,15}(?:加入|保险库|容器)|持续访问|访问", re.I)
_CURRENT_ACCESS = re.compile(
    r"\b(?:have|has|retain|keep)\s+access\b|"
    r"\b(?:can|may)\s+(?:only\s+)?access\b|(?:只能|可以|能够|可)?访问",
    re.I,
)
_CONFIRMED = re.compile(r"\bconfirmed\b|(?:被|已|经)?确认", re.I)
_ACCEPTED = re.compile(r"\baccepted\b|已接受|接受了", re.I)
MAX_REPAIR_DIRECTIVE_BYTES = 1600


def _requested_action(text, *, lifecycle_given):
    """Ignore the completed acceptance event in an internal analysis copy only."""
    return (
        re.sub(
            r"\baccepted\s+(?:(?:an?|the)\s+)?invitations?\b|接受(?:了)?邀请",
            "", text, flags=re.I,
        )
        if lifecycle_given else text
    )


def semantic_target(task, request_context):
    """Bind the exact local predicate to at most one complete parent request."""
    bindings = [
        b
        for b in request_context.get("bindings", ())
        if b.get("question_id") == task["question_id"]
    ]
    parents = [
        p
        for p in request_context.get("parents", ())
        if len(bindings) == 1 and p.get("parent_id") == bindings[0].get("parent_id")
    ]
    parent = parents[0] if len(parents) == 1 else None
    local = task["question_quote"]
    # Given scenario sentences restrict the question; they are not its requested action.
    asked = re.split(r"[。.!]\s*", local)[-1]
    shared = parent["text"] if parent else local
    lifecycle_given = bool(_CONFIRMED.search(shared) and _ACCEPTED.search(shared))
    # An accepted invitation is an object of the given past event, including
    # inside a relative clause. Keep any separate invite/be-invited request.
    requested_action = _requested_action(asked, lifecycle_given=lifecycle_given)
    relation = task["focus"]
    if task.get("selection_target") == "applicable_sourced_cpu_billing_dependency":
        relation = "cpu_billing_dependency"
    elif re.search(
        r"\b(?:non[- ]?billable|billable)\b|一定免费|一定计费|免费或|计费身份|收费状态", asked, re.I
    ):
        relation = "billability"
    elif _INVITATION.search(requested_action):
        relation = "invitation"
    elif _ACCESS.search(requested_action) and lifecycle_given:
        relation = "current_access"
    elif re.search(
        r"(?:Workspace|工作区).{0,12}(?:层级|级别|level)|(?:层级|级别).{0,12}(?:Workspace|工作区)",
        asked,
        re.I,
    ):
        relation = "role_scope_level"
    elif re.search(
        r"跨.{0,8}(?:看板|board)|自动.{0,18}(?:应用|生效|同步|继承|决定)|"
        r"\b(?:propagate|inherit|automatically)\b",
        asked,
        re.I,
    ):
        relation = "resource_propagation"
    target = dict(
        task_id=task["task_id"],
        question_id=task["question_id"],
        question_quote=local,
        focus=task["focus"],
        relation=relation,
        request_binding=None,
    )
    if parent:
        target["request_binding"] = dict(
            parent_id=parent["parent_id"],
            text_sha256=hashlib.sha256(parent["text"].encode()).hexdigest(),
        )
    return target


def applicability(target, choices):
    """Describe eligibility within this task's own dispatched reference catalog."""
    rows = []
    for ref, choice in choices.items():
        text = choice.get("quote", choice.get("operation_binding", {}).get("operation_quote", ""))
        reasons = []
        if (
            target["relation"] == "current_access"
            and _INVITATION.search(text)
            and not _CURRENT_ACCESS.search(text)
        ):
            reasons.append("invitation_does_not_establish_current_access")
        if target["relation"] == "billability" and _billability_navigation_only(text):
            reasons.append("navigation_does_not_establish_billability")
        rows.append(dict(support_ref=ref, applicable=not reasons, reason_codes=reasons))
    return rows


def _billability_navigation_only(text):
    """A pointer to another page is not a status rule; a co-located rule survives."""
    if not re.search(
        r"\b(?:check out|see|refer to|visit|read|learn more)\b|查看|参阅|阅读", text, re.I
    ):
        return False
    for sentence in re.split(r"[;；。!?！？\n]|\.(?=\s|$)", text):
        if re.match(
            r"\s*(?:To (?:understand|find out|learn)|Learn more|See\b|Check\b|"
            r"要了解|如需了解|请?查看|请?参阅)",
            sentence,
            re.I,
        ):
            continue
        pointer = re.search(
            r"\b(?:check out|see|refer to|visit|read|learn more)\b|查看|参阅|阅读", sentence, re.I
        )
        assertion = sentence[: pointer.start()] if pointer else sentence
        if re.search(
            r"\b(?:can be|may be|is|are|counts? as)\s+(?:an?\s+)?"
            r"(?:not\s+)?(?:non[- ]?billable|billable|billed|charged)\b"
            r"|(?:可|可能)?是.{0,15}(?:计费|免费|收费)",
            assertion,
            re.I,
        ):
            return False
    return True


def selection_reasons(target, refs, choices):
    rows = {r["support_ref"]: r for r in applicability(target, choices)}
    return (
        ("task_support_semantic_mismatch",)
        if any(ref not in rows or not rows[ref]["applicable"] for ref in refs)
        else ()
    )


def assertion_reasons(target, text):
    """Reject extra published relations before the generic selected-target gate."""
    if target.get("relation") == "cpu_billing_dependency":
        # A missing-input dependency is one relation, not a rate/allowance or a runtime list.
        if re.search(
            r"[$€£¥￥]|runtime|invocation|execution|运行时|调用|执行|费率|配额|"
            r"\d[\d.,]*\s*(?:per\b|milliseconds?\b|seconds?\b|minutes?\b|毫秒|秒|分钟|元)|"
            r"\b(?:rates?|allowances?|quotas?|includes?)\b.{0,40}\d",
            text,
            re.I,
        ):
            return ("task_contains_sibling_predicate",)
        cpu = re.search(r"(?<![A-Za-z0-9_])CPU(?![A-Za-z0-9_])", text, re.I)
        billing = re.search(
            r"\bbill(?:ing|ed|s)?\b|\b(?:charged?|costs?|fees?)\b|账单|计费|收费", text, re.I
        )
        dependency = re.search(
            r"\b(?:depends? on|based on|needs?|requires?|required|needed|necessary|"
            r"billed|charged)\b"
            r"|取决于|依赖|需要|必要|必需|计费|收费",
            text,
            re.I,
        )
        denied = re.search(
            r"不(?:需要|依赖|是|计费|收费)|无须|无需|无关|免费|\b(?:not|never|no)\b", text, re.I
        )
        if not (cpu and billing and dependency) or denied:
            return ("task_selected_target_mismatch",)
    if target.get("relation") == "current_access":
        # current_access already binds the accepted/confirmed lifecycle from
        # the complete request. Reject explicit invitation actions only; actor
        # and past-event wording still require the independent source review.
        action = _requested_action(text, lifecycle_given=True)
        if re.search(
            r"\b(?:can|cannot|may|could|will|would|must|should)\s+"
            r"(?:(?:only|not|also|again|then)\s+){0,2}(?:be\s+)?invit(?:e|ed)\b|"
            r"\bonly\s+be\s+invited\b|\b(?:is|are)\s+(?:only\s+)?invited\b|"
            r"(?:可以|只能|能够|还能|允许|必须|应当|不得|不能|不可|可|能)"
            r"(?:再|再次|又)?(?:被)?邀请|(?:再|再次|又)(?:被)?邀请",
            action, re.I,
        ):
            return ("task_selected_target_mismatch",)
    return ()


def repair_directive(task, reason_codes, failed_text="", *, clause_failure=None):
    from packages.agents.writer.task_clauses import clause_inventory

    invalid_text_type = None
    if not isinstance(failed_text, str):
        invalid_text_type = type(failed_text).__name__
        failed_text = ""
    reselect = any(
        "support_semantic" in c
        or c in {"no_complete_task_support", "task_generation_insufficient_evidence"}
        or c.startswith("claim_review_unsupported")
        or c.startswith("claim_review_uncertain")
        for c in reason_codes
    )
    action = "reselect" if reselect else "rewrite"
    target = task.get("semantic_target", {})
    relation = target.get("relation", task["focus"])
    try:
        clauses = clause_inventory(failed_text) if failed_text else []
    except ValueError:
        clauses = [
            dict(clause_id="unpartitioned", start=0, end=len(failed_text), quote=failed_text)
        ]
    offending = (
        [
            c
            for c in clauses
            if "task_contains_sibling_predicate" in assertion_reasons(target, c["quote"])
        ]
        if target
        else []
    )
    failed_ids = set(clause_failure.get("clause_ids", ())) if clause_failure else set()
    selected = ([c for c in clauses if c["clause_id"] in failed_ids]
                if failed_ids else offending or clauses)[:2 if failed_ids else 1]
    fragments = [
        dict(
            clause_id=c["clause_id"],
            start=c["start"],
            end=c["end"],
            quote_excerpt=_utf8_excerpt(c["quote"], 120),
            quote_sha256=hashlib.sha256(c["quote"].encode()).hexdigest(),
            excerpt_truncated=len(c["quote"].encode()) > 120,
        )
        for c in selected
    ]
    reselect_instruction = {
        "current_access": "Reselect an explicit current-access rule; an invitation cap does not "
        "establish ongoing access.",
        "billability": "Reselect an explicit billable/non-billable status rule; a navigation "
        "pointer does not establish billability.",
        "cpu_billing_dependency": "Reselect the complete applicable CPU billing dependency; "
        "request-count pricing does not fulfill this target.",
    }.get(
        relation,
        "Reselect complete source support for this task's exact requested relation, "
        "with all applicable conditions and exceptions.",
    )
    result = dict(
        action=action,
        failed_predicate=_utf8_excerpt(task["question_quote"], 160),
        failed_predicate_truncated=len(task["question_quote"].encode()) > 160,
        failed_text_sha256=hashlib.sha256(failed_text.encode()).hexdigest(),
        failed_text_bytes=len(failed_text.encode()),
        failed_clauses=fragments,
        instruction=(
            reselect_instruction
            if reselect
            else "Rewrite only this task relation. Remove sibling rules and numeric rate/runtime "
            "lists; keep necessary conditions/exceptions. Do not copy the paragraph."
        ),
    )
    if clause_failure:
        code = clause_failure["reason_code"]
        result["failure_reason"] = code
        result["instruction"] = (
            f"{code}: Rewrite only {relation}. Correct the identified clauses; keep exactly "
            "one requested assertion, with necessary conditions/exceptions. Remove separate "
            "product-rule restatements and additional capabilities. Reclassifying an "
            "independent rule as premise/connector cannot repair it."
        )
    elif not reselect and relation == "cpu_billing_dependency":
        result["instruction"] = (
            "Rewrite only the CPU-usage dependency needed for the complete bill because "
            "cpu_usage is missing. Remove allowance, rate, cache/runtime and request-count "
            "rules; keep necessary source scope. Do not recite the pricing paragraph."
        )
    if invalid_text_type is not None:
        result.update(
            failed_text_type=invalid_text_type,
            failed_text_sha256=None,
            failed_text_bytes=None,
        )
    while len(json.dumps(result, ensure_ascii=False).encode()) > MAX_REPAIR_DIRECTIVE_BYTES:
        result["failed_clauses"].pop()
    return result


def _utf8_excerpt(text, max_bytes):
    return text.encode()[:max_bytes].decode("utf-8", errors="ignore")


def classify_obligations(tasks):
    """A generated shared rule is a dependency only for its explicit resource peers."""
    result = deepcopy(tasks)
    for task in result:
        dependencies = [
            r["task_id"]
            for r in result
            if task.get("resource")
            and r["question_id"] == task["question_id"]
            and r["focus"] == "rule_" + task["focus"]
            and not r.get("resource")
        ]
        task.update(obligation_role="request", dependency_task_ids=dependencies)
    for task in result:
        if any(task["task_id"] in r["dependency_task_ids"] for r in result):
            task["obligation_role"] = "support_dependency"
    return result


def source_scopes(sources):
    """Only authenticated Source metadata; no product assertion or support ref."""
    return {
        s.id: dict(title=s.title, url=s.url, purpose="restriction_only_not_evidence")
        for s in sources
    }
