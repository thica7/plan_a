"""Server-owned task identities. Planning describes requests, never source facts."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter

from packages.agents.writer.answer_action_scope import _ACTIONS
from packages.agents.writer.subquestion_premises import named_resource_items

CONTRACT = "question-tasks-v1"
FOCUSES = {
    *_ACTIONS,
    *(f"rule_{action}" for action in _ACTIONS),
    "source_rule",
    "permission_not_obligation",
    "billing_inputs",
}
MAX_TASKS = 12


def _json(text):
    from packages.agents.writer.dimension_writer import parse_json

    return parse_json(text)


def parse_tasks(text, questions, scope):
    payload = _json(text)
    if (
        not isinstance(payload, dict)
        or set(payload) != {"tasks"}
        or not isinstance(payload["tasks"], list)
        or len(payload["tasks"]) > 48
    ):
        raise ValueError("invalid task plan envelope")
    known = {q["question_id"]: q["question"] for q in questions}
    groups = {qid: [] for qid in known}
    for row in payload["tasks"]:
        if (
            not isinstance(row, dict)
            or set(row) != {"question_id", "question_quote", "focus"}
            or not all(isinstance(value, str) for value in row.values())
            or row["question_id"] not in known
            or row["focus"] not in FOCUSES
            or not row["question_quote"].strip()
            or row["question_quote"] not in known[row["question_id"]]
        ):
            raise ValueError("task plan is not an exact request fragment")
        if row["focus"] == "permission_not_obligation" and not re.search(
            r"必须|义务|强制|\b(?:must|obligation|obliged|mandatory)\b",
            known[row["question_id"]],
            re.I,
        ):
            raise ValueError("obligation task requires an explicit obligation request")
        resources = named_resource_items(row["question_quote"]) if row["focus"] in _ACTIONS else ()
        if row["focus"] in _ACTIONS and not resources:
            # Exact request excerpts may omit their question mark or noun.
            resources = tuple(
                name
                for name in named_resource_items(known[row["question_id"]])
                if re.search(
                    rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", row["question_quote"]
                )
            )
        if resources:
            # Scoped decisions need their own publishable product rule.
            rule = dict(row, focus=f"rule_{row['focus']}")
            if rule not in groups[row["question_id"]]:
                groups[row["question_id"]].append(rule)
        for resource in resources or (None,):
            task = dict(row, **({"resource": resource} if resource else {}))
            group = groups[row["question_id"]]
            if task not in group:
                group.append(task)
    for qid, group in groups.items():
        if not group:
            group.append(
                dict(
                    question_id=qid,
                    question_quote=known[qid],
                    focus="source_rule",
                    state="deferred",
                    reason="request_not_planned",
                )
            )
    ordered = [
        group[index]
        for index in range(max(map(len, groups.values()), default=0))
        for group in groups.values()
        if index < len(group)
    ]
    active = 0
    for task in ordered:
        identity = [
            CONTRACT,
            scope,
            task["question_id"],
            task["question_quote"],
            task["focus"],
            task.get("resource"),
        ]
        task["task_id"] = (
            "task-"
            + hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()[:20]
        )
        if "state" not in task:
            task["state"] = "planned" if active < MAX_TASKS else "deferred"
            if active >= MAX_TASKS:
                task["reason"] = "task_capacity_exceeded"
            active += 1
    return ordered


def fallback_tasks(questions, scope):
    from packages.agents.writer.question_allocation import question_atom_tasks

    by_id = {q["question_id"]: q["question"] for q in questions}
    rows = [
        dict(
            question_id=t["question_id"],
            question_quote=t.get("request", by_id[t["question_id"]]),
            focus=t["focus"],
        )
        for t in question_atom_tasks(questions, max_atoms=48)
    ]
    return parse_tasks(json.dumps({"tasks": rows}), questions, scope)


def parse_results(text, tasks):
    payload = _json(text)
    if (
        not isinstance(payload, dict)
        or set(payload) != {"results"}
        or not isinstance(payload["results"], list)
    ):
        raise ValueError("invalid task result envelope")
    expected = {t["task_id"] for t in tasks}
    rows = [
        r for r in payload["results"] if isinstance(r, dict) and isinstance(r.get("task_id"), str)
    ]
    counts = Counter(r["task_id"] for r in rows)
    result = {tid: dict(state="deferred", reason="task_result_missing") for tid in expected}
    for row in rows:
        tid = row["task_id"]
        if tid not in expected:
            continue
        valid = set(row) == {"task_id", "status", "atom"} and counts[tid] == 1
        if valid and row["status"] == "insufficient_evidence" and row["atom"] is None:
            result[tid] = dict(state="insufficient_evidence", reason="no_supported_atom")
            continue
        atom = row.get("atom")
        if (
            not valid
            or row.get("status") != "generated"
            or not isinstance(atom, dict)
            or set(atom) != {"text", "kind", "support_refs"}
            or not isinstance(atom["text"], str)
            or not atom["text"].strip()
            or not isinstance(atom["kind"], str)
            or atom["kind"] not in {"fact", "inference"}
            or not isinstance(atom["support_refs"], list)
            or not 1 <= len(atom["support_refs"]) <= 2
            or any(not isinstance(ref, str) for ref in atom["support_refs"])
        ):
            result[tid] = dict(state="rejected", reason="task_result_invalid")
        else:
            result[tid] = dict(state="generated", atom=atom)
    return result


def task_atom_reasons(task, text, *, kind=None):
    """Reject known sibling action assertions; absence is not semantic proof."""
    focus = task["focus"].removeprefix("rule_")
    if kind is not None and (
        task["focus"].startswith("rule_")
        and kind != "fact"
        or task.get("resource")
        and kind != "inference"
    ):
        return ("task_assertion_kind_mismatch",)
    if focus not in _ACTIONS:
        return ()
    if not re.search(_ACTIONS[focus], text, re.I):
        return ("task_predicate_not_addressed",)
    from packages.agents.writer.answer_action_scope import _LEADING_CONTEXT, _TRAILING_CONTEXT

    for part in re.split(r"[。；;.!?]", text):
        assertion = _LEADING_CONTEXT.sub("", part).strip()
        assertion = re.sub(r"^在[^，,。；]{1,100}(?:后|前)[，,]\s*", "", assertion)
        assertion = re.sub(r"^(?:只有|仅当)[^，。；]{1,100}?(?:才能|才可)", "可以", assertion)
        context = re.search(
            r"\b(?:when|provided(?:\s+that)?|unless|until)\b|前提是|条件是", assertion, re.I
        )
        context = context or _TRAILING_CONTEXT.search(assertion)
        assertion = assertion[: context.start()] if context else assertion
        # Unknown condition grammar stays with the independent semantic audit.
        if re.search(
            r"\b(?:if|when|after|before|unless|provided|requires?|who|that)\b"
            r"|如果|若|只有|仅当|前提|需要|前|后",
            assertion,
            re.I,
        ):
            continue
        sibling = any(
            re.search(
                r"(?:并(?:且)?(?:可以|能够|不能|无法|可|能)?|还可|还能|"
                r"\band\s+(?:can|cannot|may|must|could))\s*(?:" + pattern + ")",
                assertion,
                re.I,
            )
            for key, pattern in _ACTIONS.items()
            if key != focus
        )
        if sibling:
            return ("task_contains_sibling_predicate",)
    return ()
