"""Internal single-predicate contract; finite inventories never prove semantics."""

import re
from copy import deepcopy

from packages.llm.json_extract import strict_json_object

CONTRACT = "single-predicate-clauses-v1"


def checked_contract(payload):
    value = payload.get("task_clause_contract")
    if value is not None and (type(value) is not str or value != CONTRACT):
        raise ValueError("Unknown task clause contract")
    if value and payload.get("task_execution_policy") != "selected-task-atoms-v3":
        raise ValueError("Task clause contract requires task policy v3")
    return value


def selected_task(task, selection, target):
    """Replace planner hints with the selected refs and the actual server target."""
    result = deepcopy(task)
    result["support_refs"] = list(selection["support_refs"])
    for name in ("selection_target", "missing_billing_inputs"):
        if name in target:
            result[name] = deepcopy(target[name])
    if target.get("selection_target") == "applicable_sourced_cpu_billing_dependency":
        result["task_instruction"] += (
            " The exact target is the applicable CPU-time billing dependency because "
            "cpu_usage is missing. Publish ONLY that one sourced dependency; request-count "
            "pricing and runtime limits do not fulfill this target."
        )
    return result


def target_reasons(task, text, competitor):
    """Reject a sourced sibling billing predicate; source REVIEW still owns support."""
    target = task.get("selection_target")
    if target is None:
        return ()
    from types import SimpleNamespace

    from packages.agents.writer.price_answers import _BILLING_NAME, _cpu_billing_dependency

    if (
        target != "applicable_sourced_cpu_billing_dependency"
        or task["focus"] != "billing_inputs"
        or "cpu_usage" not in task.get("missing_billing_inputs", ())
    ):
        return ("task_selected_target_mismatch",)
    # Use the same claim-text normalization and predicate classifier as published CPU premises.
    assertion_text = re.sub(
        r"(?<![A-Za-z0-9_+-])(" + _BILLING_NAME + r")\s*用量模式",
        lambda match: match[1] + " usage model ",
        text,
    )
    assertion = SimpleNamespace(quote=assertion_text, value=[assertion_text], qualifiers={})
    return (
        ()
        if _cpu_billing_dependency(assertion, task["question_quote"], competitor)
        else ("task_selected_target_mismatch",)
    )


def generation_plan(response, task, support_refs, missing_fields):
    raw = strict_json_object(response)
    if (
        set(raw) != {"version", "task_id", "status", "atom"}
        or type(raw["version"]) is not int
        or raw["version"] != 1
        or raw["task_id"] != task["task_id"]
        or raw["status"] not in {"generated", "insufficient_evidence"}
    ):
        raise ValueError("task_clause_generation_envelope_invalid")
    atom = raw["atom"]
    if raw["status"] == "insufficient_evidence":
        if atom is not None:
            raise ValueError("task_clause_generation_status_invalid")
        atoms = []
    else:
        kinds = task["required_kind"]
        kinds = kinds if isinstance(kinds, list) else [kinds]
        if (
            not isinstance(atom, dict)
            or set(atom) != {"text", "kind", "support_refs"}
            or not isinstance(atom["text"], str)
            or not atom["text"].strip()
            or atom["kind"] not in kinds
            or atom["support_refs"] != support_refs
        ):
            raise ValueError("task_clause_atom_or_support_invalid")
        clause_inventory(atom["text"])
        atoms = [dict(deepcopy(atom), task_id=task["task_id"])]
    return dict(
        question_plans=[
            dict(question_id=task["question_id"], missing_fields=missing_fields, atoms=atoms)
        ]
    )


def clause_inventory(text):
    """Partition at bounded punctuation/connectors, retaining every original character."""
    if not isinstance(text, str) or not text:
        raise ValueError("task_clause_text_invalid")
    # Periods inside domains and decimal numbers are not sentence boundaries.
    boundary = re.compile(
        r"[，,；;。！？!?\n]+|(?<![\w])\.(?=\s|$)|"
        r"(?<=[A-Za-z0-9])\.(?=\s|$)|"
        r"\b(?:and|or|but|unless|except|provided|therefore)\b|"
        r"并且|而且|但是|但|不过|除非|除外|因此|所以",
        re.I,
    )
    cuts = {0, len(text)}
    for match in boundary.finditer(text):
        if match.group().strip("，,；;。！？!?\n."):
            if match.start():
                cuts.add(match.start())
        else:
            cuts.add(match.end())
    positions = sorted(cuts)
    parts = []
    start = 0
    for end in positions[1:]:
        if text[start:end].strip():
            parts.append((start, end))
            start = end
    if len(parts) > 16:
        raise ValueError("task_clause_limit_exceeded")
    # Attach a trailing whitespace-only remainder instead of dropping it.
    if parts and parts[-1][1] != len(text):
        parts[-1] = (parts[-1][0], len(text))
    return [
        dict(clause_id=f"clause-{i + 1}", start=a, end=b, quote=text[a:b])
        for i, (a, b) in enumerate(parts)
    ]


def _condition_ranges(text, inventory):
    """Keep coordinated prerequisites inside their original, punctuation-bounded clause."""
    ranges = []
    for clause in inventory:
        opening = re.match(
            r"\s*(?:but\s+|(?:但是|但|不过)\s*)?"
            r"(?:(?:only\s+)?(?:if|when)\b|(?:如果|若|仅当|只有))",
            clause["quote"],
            re.I,
        )
        if not opening:
            continue
        start = clause["start"]
        for boundary in re.finditer(r"[,，;；。！？!?\n]|\.(?=\s|$)", text[start:]):
            end = start + boundary.end()
            # Chinese prerequisites may coordinate across a comma before their
            # closing 时. A closing conditional marker ends scope even before 且.
            coordinated = re.match(r"\s*(?:而且|并且|且)", text[end:])
            closed = re.search(r"(?:时|情况下|条件下)\s*[,，]$", text[start:end])
            if boundary.group() in {",", "，"} and coordinated and not closed:
                continue
            ranges.append((start, end))
            break
    return ranges


def validate_clause_reviews(raw, claims, payload):
    try:
        rows = raw["atomicity"]
        inventories = payload["clause_inventory"]
        if not isinstance(rows, list) or len(rows) != len(claims):
            return False
        for claim in claims:
            claim = claim if isinstance(claim, dict) else claim.model_dump(mode="json")
            inventory = next(r["clauses"] for r in inventories if r["claim_id"] == claim["id"])
            if inventory != clause_inventory(claim["text"]):
                return False
            matches = [r for r in rows if isinstance(r, dict) and r.get("claim_id") == claim["id"]]
            if len(matches) != 1:
                return False
            row = matches[0]
            if (
                set(row) != {"claim_id", "predicate_count", "clauses"}
                or type(row["predicate_count"]) is not int
                or row["predicate_count"] != 1
                or not isinstance(row["clauses"], list)
                or len(row["clauses"]) != len(inventory)
            ):
                return False
            condition_ranges = _condition_ranges(claim["text"], inventory)
            assertions = 0
            for expected, clause in zip(inventory, row["clauses"], strict=True):
                if (
                    not isinstance(clause, dict)
                    or set(clause)
                    != {
                        "clause_id",
                        "role",
                        "independent_predicate",
                        "task_match",
                        "verdict",
                        "support_refs",
                    }
                    or clause["clause_id"] != expected["clause_id"]
                    or clause["role"]
                    not in {"assertion", "condition", "premise", "exception", "connector"}
                    or type(clause["independent_predicate"]) is not bool
                    or clause["task_match"] is not True
                    or clause["verdict"] != "supported"
                    or not isinstance(clause["support_refs"], list)
                    or any(not isinstance(ref, str) for ref in clause["support_refs"])
                    or len(set(clause["support_refs"])) != len(clause["support_refs"])
                    or not set(clause["support_refs"]) <= set(payload["clause_support_refs"])
                    or clause["role"] != "connector"
                    and not clause["support_refs"]
                ):
                    return False
                # Explicit additional capability syntax cannot be relabelled as a premise.
                # Requirement/conditional syntax stays with independent semantic review.
                explicit_condition = re.match(
                    r"\s*(?:(?:and|or|but)\s+)?(?:if\b|when\b|only if\b|only when\b|"
                    r"unless\b|provided\b|except\b)"
                    r"|\s*(?:且|并且|但是|但|不过)?\s*(?:如果|若|仅当|只有|除非|除外|例外)",
                    expected["quote"],
                    re.I,
                )
                within_condition = any(
                    start <= expected["start"] and expected["end"] <= end
                    for start, end in condition_ranges
                )
                if (
                    clause["role"] != "assertion"
                    and not (explicit_condition or within_condition)
                    and re.match(
                        r"\s*(?:(?:and|or|but)\b\s*|并且?|而且|且|但是|但|不过)?\s*"
                        r"(?:(?:[A-Za-z][A-Za-z -]{0,35})\s+|"
                        r"[\u3400-\u9fff][\u3400-\u9fffA-Za-z0-9_· \t-]*?)?"
                        r"(?:can\b|may\b|allows?\b|is allowed\b|允许|可以|能够|可(?!以外)|能)",
                        expected["quote"],
                        re.I,
                    )
                ):
                    return False
                if clause["role"] == "assertion":
                    if not clause["independent_predicate"]:
                        return False
                    assertions += 1
                elif clause["independent_predicate"]:
                    # A condition can contain a predicate without being a second target.
                    if clause["role"] not in {"condition", "premise", "exception"}:
                        return False
            if assertions != 1:
                return False
        return True
    except (ValueError, TypeError, KeyError, StopIteration):
        return False


def system(base, name):
    if name.endswith("atomic_generation"):
        # Replace the legacy output schema, not the binding and guard instructions.
        replacement = (
            " Output only the requested single predicate. Parent context and canonical "
            "facts only restrict; never add an unselected assertion. For a who-can role "
            "rule, state the generic complete authorized role list; keep named resource "
            "labels in request premises and never assert an executed access change. JSON only: "
            '{"version":1,"task_id":"server ID","status":"generated|insufficient_evidence",'
            '"atom":{"text":"one predicate","kind":"fact|inference",'
            '"support_refs":["selected ref"]}}. Use atom:null for insufficient_evidence. '
        )
        old_schema = (
            "Copy question_plan_missing_fields. JSON only: "
            '{"question_plans":[{"question_id":"server ID","missing_fields":[],"atoms":'
            '[{"task_id":"server ID","text":"one complete predicate","kind":"fact|inference",'
            '"support_refs":["selected ref"]}]}]}. '
        )
        if base.count(old_schema) != 1:
            raise ValueError("Task clause generation SYSTEM schema changed")
        base = base.replace(old_schema, replacement, 1)
    elif name.endswith("atomic_review"):
        base = base.split(" JSON reviews retain their existing exact checks.", 1)[0]
        base += (
            " Retain the existing full source reviews. Independently audit EVERY server "
            "clause_inventory entry in exact order; no whole-sentence replacement. "
            "Return atomicity:[{claim_id,predicate_count:1,clauses:[{clause_id,"
            'role:"assertion|condition|premise|exception|connector",independent_predicate:true,'
            'task_match:true,verdict:"supported|unsupported|uncertain",support_refs:[] }]}]. '
            "Use only clause_support_refs. Exactly one substantive target assertion may pass. "
            "Count every independent action even when sourced; retain and review all "
            "conditions, AND premises, exceptions, roles and objects. Finite segmentation "
            "does not prove meaning. Reject multiple target actions."
        )
    return f"Internal task clause contract {CONTRACT}. " + base


def reuse_selection(task, history, facts, consumption_id, snapshot_id):
    """Reconstruct a certificate from the authentic first SELECT and full GEN input."""
    from packages.agents.writer.question_atomic_delivery import GENERATION_NAME, digest
    from packages.agents.writer.readable_support import dispatched_support_choices
    from packages.agents.writer.task_support_selection import parse_support_selections

    prior = [
        (d, span, p)
        for d, span, p in history
        if d.get("task_id") == task["task_id"] and d.get("attempt") == 0
    ]
    selected = [r for r in prior if r[0]["name"].endswith("support_selection")]
    generated = [r for r in prior if r[0]["name"] == GENERATION_NAME]
    if len(selected) != 1 or len(generated) != 1:
        return None
    dispatch, span, selection_payload = selected[0]
    original = generated[0][2]
    if (
        not checked_contract(original)
        or span.status != "ok"
        or digest(span.full_input) != dispatch["full_input_sha256"]
        or digest(span.full_output) != dispatch["full_output_sha256"]
        or original["consumption_id"] != consumption_id
        or original["snapshot_id"] != snapshot_id
        or selection_payload["consumption_id"] != consumption_id
        or selection_payload["snapshot_id"] != snapshot_id
    ):
        raise ValueError("task_selection_reuse_identity_changed")
    choices = dispatched_support_choices(
        original, facts, {r["id"] for r in original["evidence_view"]["facts"]}
    )
    parsed, _ = parse_support_selections(span.full_output, [task], choices)
    selection = parsed[task["task_id"]]
    if (
        selection["state"] != "selected"
        or original["task_support_selections"][0]["support_refs"] != selection["support_refs"]
    ):
        raise ValueError("task_selection_reuse_support_changed")
    certificate = dict(
        task_id=task["task_id"],
        question_id=task["question_id"],
        consumption_id=consumption_id,
        snapshot_id=snapshot_id,
        source_attempt=0,
        support_refs=selection["support_refs"],
        **{k: dispatch[k] for k in ("span_id", "full_input_sha256", "full_output_sha256")},
    )
    return certificate, deepcopy(original), parsed


def user_bytes(payload):
    """Measure the actual complete user wire, including UTF-8 and JSON framing."""
    from packages.agents.writer.dimension_writer import compact_prompt_json

    return len(("\nJSON:\n" + compact_prompt_json(payload)).encode())


def reused_generation(
    task, history, facts, consumption_id, snapshot_id, feedback, *, max_bytes=14000
):
    selected = reuse_selection(task, history, facts, consumption_id, snapshot_id)
    if selected is None:
        return None
    certificate, original, parsed = selected
    original.update(task_attempt=1, repair_feedback=deepcopy(feedback), selection_reuse=certificate)
    if user_bytes(original) > min(14000, max_bytes):
        for name in ("failed_generation", "failed_review"):
            original["repair_feedback"].pop(name, None)
    return original, parsed


def fresh_contract(detail, scope):
    """An upstream checkpoint is fresh; an existing Writer stage keeps its contract."""
    for span in detail.trace_spans:
        if span.subagent != scope:
            continue
        if span.name == "question_atomic_delivery":
            try:
                import json

                return checked_contract(json.loads(span.full_output))
            except (ValueError, TypeError):
                return None
        if span.name in {
            "dimension_question_task_support_selection",
            "dimension_question_atomic_generation",
            "dimension_question_atomic_review",
        }:
            import json

            _, separator, raw = span.full_input.partition("\nJSON:\n")
            try:
                return checked_contract(json.loads(raw)) if separator else None
            except (ValueError, TypeError):
                return None
    return CONTRACT
