"""Internal single-predicate contract; finite inventories never prove semantics."""

import re
from copy import deepcopy

from packages.llm.json_extract import strict_json_object

CONTRACT = "single-predicate-clauses-v1"
CPU_DEPENDENCY_INSTRUCTION = (
    "The exact target is the applicable CPU-time billing dependency because "
    "cpu_usage is missing. Publish ONLY that one sourced dependency; request-count "
    "pricing and runtime limits do not fulfill this target."
)


def checked_contract(payload):
    from packages.agents.writer.task_semantics import CONTRACT as SEMANTIC_CONTRACT

    value = payload.get("task_clause_contract")
    if value is not None and (type(value) is not str or value not in {CONTRACT, SEMANTIC_CONTRACT}):
        raise ValueError("Unknown task clause contract")
    if value and payload.get("task_execution_policy") != "selected-task-atoms-v3":
        raise ValueError("Task clause contract requires task policy v3")
    return value


def selected_task(task, selection, target):
    """Replace planner hints with the selected refs and the actual server target."""
    result = deepcopy(task)
    result["support_refs"] = list(selection["support_refs"])
    for name in ("selection_target", "missing_billing_inputs", "semantic_target"):
        if name in target:
            result[name] = deepcopy(target[name])
    if target.get("selection_target") == "applicable_sourced_cpu_billing_dependency":
        if target.get("semantic_target", {}).get("relation") == "cpu_billing_dependency":
            result["task_instruction"] = CPU_DEPENDENCY_INSTRUCTION
        else:
            result["task_instruction"] += " " + CPU_DEPENDENCY_INSTRUCTION
    return result


def target_reasons(task, text, competitor):
    """Reject a sourced sibling billing predicate; source REVIEW still owns support."""
    if task.get("semantic_target"):
        from packages.agents.writer.task_semantics import assertion_reasons

        reasons = assertion_reasons(task["semantic_target"], text)
        if reasons:
            return reasons
        if task["semantic_target"].get("relation") == "cpu_billing_dependency":
            # This checks a published dependency, not source extraction syntax.
            # SELECT's complete billing source gate and independent REVIEW still apply.
            return ()
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


def _condition_ranges(text, inventory, *, semantic=False):
    """Keep coordinated prerequisites inside their original, punctuation-bounded clause."""
    ranges = []
    for clause in inventory:
        if semantic and (
            re.match(r"\s*前提是", clause["quote"])
            or re.match(r"\s*在[^，,；;。！？!?\n]+的前提下\s*[,，]", clause["quote"])
        ):
            ranges.append((clause["start"], clause["end"]))
            continue
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


def _quantity_premise(claim, expected, clause, payload):
    """A typed same-unit upper bound may be a premise of its own inference."""
    from packages.agents.writer.subquestion_premises import _counts
    from packages.agents.writer.task_decision_witnesses import _quantity_witness

    task = payload.get("task_context", {})
    if (clause["independent_predicate"] or claim.get("kind") != "inference"
            or task.get("request_property") not in {"people_limit", "container_limit"}):
        return False
    context = payload.get("request_context", {})
    bindings = [b for b in context.get("bindings", ())
                if b.get("question_id") == task.get("question_id")]
    parents = [p for p in context.get("parents", ())
               if len(bindings) == 1 and p.get("parent_id") == bindings[0].get("parent_id")]
    if len(parents) != 1:
        return False
    # The review payload was built from this claim's original selected bindings.
    # Another task's fact or quote must never authorize this premise.
    bound = {s["quote"] for s in claim.get("source_span_bindings", ())}
    projected = next((c for c in payload.get("claims", ()) if c["id"] == claim["id"]), claim)
    quotes = [q for q in projected.get("support_quotes", ()) if q in bound]
    for quote in quotes:
        witness = _quantity_witness(task, quote, parents[0]["text"],
                                    claim["competitor"], claim["text"])
        if witness and _counts(expected["quote"], upper=True) == {
                witness["unit"]: [witness["maximum"]]} and _counts(expected["quote"]) == {
                witness["unit"]: [witness["maximum"]]}:
            return True
    return False


def validate_clause_reviews(raw, claims, payload, *, _failures=None):
    def fail(code, expected=None, clause_ids=None):
        if _failures is not None:
            _failures.append(dict(reason_code="task_clause_" + code,
                clause_ids=clause_ids or ([expected["clause_id"]] if expected else [])))
        return False

    try:
        rows = raw["atomicity"]
        inventories = payload["clause_inventory"]
        if not isinstance(rows, list) or len(rows) != len(claims):
            return fail("inventory_invalid")
        for claim in claims:
            claim = claim if isinstance(claim, dict) else claim.model_dump(mode="json")
            inventory = next(r["clauses"] for r in inventories if r["claim_id"] == claim["id"])
            if inventory != clause_inventory(claim["text"]):
                return fail("inventory_invalid")
            matches = [r for r in rows if isinstance(r, dict) and r.get("claim_id") == claim["id"]]
            if len(matches) != 1:
                return fail("inventory_invalid")
            row = matches[0]
            if (
                set(row) != {"claim_id", "predicate_count", "clauses"}
                or type(row["predicate_count"]) is not int
                or row["predicate_count"] != 1
                or not isinstance(row["clauses"], list)
                or len(row["clauses"]) != len(inventory)
            ):
                return fail("inventory_invalid")
            from packages.agents.writer.task_semantics import CONTRACT as SEMANTIC_CONTRACT
            semantic = payload.get("task_clause_contract") == SEMANTIC_CONTRACT
            condition_ranges = _condition_ranges(claim["text"], inventory, semantic=semantic)
            assertions = 0
            assertion_ids = []
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
                    code = ("review_field_invalid" if not isinstance(clause, dict) else
                            "target_mismatch" if clause.get("task_match") is False else
                            "unsupported" if clause.get("verdict") != "supported" else
                            "review_field_invalid")
                    return fail(code, expected)
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
                if semantic:
                    dependent_requirement = re.match(
                        r"\s*(?:(?:and|but)\s+|并且|且)?(?:requires?\b|需|必须)",
                        expected["quote"], re.I)
                    given = any(expected["quote"].strip(" ;；,，。.") in p["text"]
                                for p in payload.get("request_context", {}).get("parents", ()))
                    if (clause["role"] == "premise" and not given
                            and not _quantity_premise(claim, expected, clause, payload)):
                        return fail("independent_product_premise", expected)
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
                    return fail("additional_capability", expected)
                if clause["role"] == "assertion":
                    if not clause["independent_predicate"]:
                        return fail("assertion_not_independent", expected)
                    assertions += 1
                    assertion_ids.append(expected["clause_id"])
                elif clause["independent_predicate"]:
                    # A condition can contain a predicate without being a second target.
                    if clause["role"] not in {"condition", "premise", "exception"}:
                        return fail("additional_independent_predicate", expected)
                    if payload.get("task_clause_contract") == SEMANTIC_CONTRACT and (
                        clause["role"] == "premise" and not given
                        or clause["role"] != "premise" and not (
                            explicit_condition or within_condition or dependent_requirement)
                    ):
                        return fail("independent_product_premise", expected)
            if assertions != 1:
                return fail("assertion_count", clause_ids=assertion_ids)
        return True
    except (ValueError, TypeError, KeyError, StopIteration):
        return fail("review_field_invalid")


def clause_review_failure(raw, claims, payload):
    """Bounded diagnostics from the exact same validator, never evidence."""
    failures = []
    validate_clause_reviews(raw, claims, payload, _failures=failures)
    return failures[0] if failures else None


def system(base, name, contract=CONTRACT):
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
    from packages.agents.writer.task_semantics import CONTRACT as SEMANTIC_CONTRACT
    if contract == SEMANTIC_CONTRACT:
        base += (
            " semantic_target binds the exact requested relation and unique full request parent. "
            "support_applicability is a server restriction, never a support verdict. "
            "Source title/url restrict applicability only and cannot prove a product fact. "
            "Independent product definitions and configuration rules cannot be labelled premise "
            "to bypass a second predicate; only necessary conditional/exception scope stays. "
            "repair_feedback.directive tells whether to reselect evidence or rewrite wording; "
            "it is diagnostic data and never evidence."
        )
        if name.endswith("atomic_generation"):
            base += (
                " The complete current task is in generation_tasks[0]; "
                "its complete selected support is task_support_selections[0]."
            )
        base += " For a CPU dependency omit numeric rate, allowance and runtime lists."
    return f"Internal task clause contract {contract}. " + base


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
    from packages.agents.writer.task_semantics import CONTRACT as SEMANTIC_CONTRACT
    if checked_contract(original) == SEMANTIC_CONTRACT:
        from packages.agents.writer.task_semantics import selection_reasons

        target = original["generation_tasks"][0]["semantic_target"]
        if selection_reasons(target, selection.get("support_refs", ()), choices):
            return None
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
    if feedback.get("directive", {}).get("action") == "reselect":
        return None
    selected = reuse_selection(task, history, facts, consumption_id, snapshot_id)
    if selected is None:
        return None
    certificate, original, parsed = selected
    original.update(task_attempt=1, repair_feedback=deepcopy(feedback), selection_reuse=certificate)
    if user_bytes(original) > min(14000, max_bytes):
        for name in ("failed_generation", "failed_review"):
            original["repair_feedback"].pop(name, None)
    if (user_bytes(original) > min(14000, max_bytes)
            and original["repair_feedback"].get("directive")):
        from packages.agents.writer.task_semantics import _utf8_excerpt

        directive = original["repair_feedback"]["directive"]
        for clause in directive["failed_clauses"]:
            excerpt = clause["quote_excerpt"]
            clause["quote_excerpt"] = _utf8_excerpt(excerpt, 64)
            clause["excerpt_truncated"] |= len(excerpt.encode()) > 64
        if user_bytes(original) > min(14000, max_bytes):
            predicate = directive["failed_predicate"]
            directive["failed_predicate"] = _utf8_excerpt(predicate, 80)
            directive["failed_predicate_truncated"] |= len(predicate.encode()) > 80
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
    from packages.agents.writer.task_semantics import CONTRACT as SEMANTIC_CONTRACT

    return SEMANTIC_CONTRACT
