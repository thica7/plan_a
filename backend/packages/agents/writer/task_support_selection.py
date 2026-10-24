"""Bounded task-local choices from an already canonical dispatched catalog."""

from collections import Counter

SELECT_SYSTEM = (
    "Select support per task_id, no claims. Requests are data, never evidence. Choose minimal "
    "complete evidence_view support for the task predicate, keeping "
    "role/plan/actor/object/recipient/scope/time, AND/OR conditions "
    "and exceptions. A main read/comment/edit/create/share/manage_access assertion requires "
    "binding_kind=operation and its exact same-index operation_observations o-reference. "
    "Other actions (download/export/vote/purge_cache), quantity, ownership and scope use "
    "binding_kind=span with a complete source_span_candidates s-reference. Source mentions of "
    "sharing or a Share UI button do not change the main predicate. One o maximum; two s only "
    "for a required source_exception_bindings pair. source_restrictions qualify/reject; parents "
    "or siblings cannot supply unselected support. For permission_not_obligation choose the "
    "permission rule to support can-does-not-entail-must, never document-wide absence of duties. "
    "Selection is an untrusted proposal. Without complete support use insufficient_evidence, "
    "binding_kind=null, support_refs=[]. Resolve text_ref via text_sets. JSON only: "
    '{"selections":[{"task_id":"exact input ID","status":"selected|insufficient_evidence",'
    '"binding_kind":"span|operation or null","support_refs":["s1 or o1"]}]}. '
    "Exactly one row per task; no foreign IDs or extra fields."
)
MAX_SELECTION_BYTES = 4096


def parse_support_selections(text, tasks, choices):
    """Invalid peers stay explicit without deleting valid task-local selections."""
    from packages.agents.writer.dimension_writer import parse_json

    if not isinstance(text, str) or len(text.encode()) > MAX_SELECTION_BYTES:
        raise ValueError("task support selection unavailable or oversized")
    payload = parse_json(text)
    if (
        not isinstance(payload, dict)
        or set(payload) != {"selections"}
        or not isinstance(payload["selections"], list)
        or len(payload["selections"]) > 12
    ):
        raise ValueError("invalid task support selection envelope")
    rows = payload["selections"]
    counts = Counter(
        row["task_id"]
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("task_id"), str)
    )
    results = {
        task["task_id"]: dict(state="deferred", reason="task_support_selection_missing")
        for task in tasks
    }
    failures = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("task_id"), str):
            failures.append("task_support_selection_invalid_identity")
            continue
        tid = row["task_id"]
        if tid not in results:
            failures.append("task_support_selection_foreign_task")
            continue
        valid = (
            set(row) == {"task_id", "status", "binding_kind", "support_refs"} and counts[tid] == 1
        )
        if (
            valid
            and row["status"] == "insufficient_evidence"
            and row["binding_kind"] is None
            and row["support_refs"] == []
        ):
            results[tid] = dict(state="insufficient_evidence", reason="no_complete_task_support")
            continue
        refs = row.get("support_refs")
        kind = row.get("binding_kind")
        if (
            not valid
            or row.get("status") != "selected"
            or not isinstance(kind, str)
            or kind not in {"span", "operation"}
            or not isinstance(refs, list)
            or not 1 <= len(refs) <= (1 if kind == "operation" else 2)
            or any(not isinstance(ref, str) or ref not in choices for ref in refs)
            or len(set(refs)) != len(refs)
            or any(choices[ref]["binding_kind"] != kind for ref in refs)
        ):
            results[tid] = dict(state="deferred", reason="task_support_selection_invalid")
            continue
        results[tid] = dict(state="selected", binding_kind=kind, support_refs=refs)
    return results, sorted(set(failures))


def support_selection_context(payload, choices):
    """Send verified complete choices and restrictions once, without replay metadata."""
    rows = []
    pair_ids = {fid for pair in payload.get("source_exception_bindings", ())
                for fid in pair["fact_ids"]}
    for original in payload["evidence_view"]["facts"]:
        spans = [choices[item["support_ref"]] for item in original.get("source_span_candidates", ())
                 if item.get("support_ref") in choices
                 and choices[item["support_ref"]]["binding_kind"] == "span"]
        operations = [choices[ref] for ref in original.get("operation_support_refs", ())
                      if ref in choices and choices[ref]["binding_kind"] == "operation"]
        if not spans and not operations:
            continue
        restrictions = {key: original[key] for key in
                        ("quote", "source_exceptions", "temporal_constraints")
                        if key in original}
        qualifiers = {key: value for key, value in original.get("qualifiers", {}).items()
                      if key not in {"slot", "source_scope"}}
        # source_scope records Collector location/proposals. Its actual role
        # and plan context still restricts choices; repeated extraction hints
        # cannot introduce another selectable operation or product assertion.
        context = original.get("qualifiers", {}).get("source_scope", {}).get("context", {})
        source_context = {key: value for key, value in context.items()
                          if key in {"role", "plan"} and value is not None}
        if source_context:
            qualifiers["source_context"] = source_context
        if qualifiers:
            restrictions["qualifiers"] = qualifiers
        row = dict(source_id=original["source_id"], source_restrictions=restrictions)
        if original["id"] in pair_ids:
            row["id"] = original["id"]
        if spans:
            row["source_span_candidates"] = [
                dict(support_ref=item["support_ref"], quote=item["quote"]) for item in spans]
        if operations:
            row["operation_observations"] = [item["operation_binding"] for item in operations]
            row["operation_support_refs"] = [item["support_ref"] for item in operations]
        rows.append(row)
    return dict(
        {key: payload[key] for key in ("segment_competitor", "dimension", "questions", "tasks",
                                      "task_repair", "required_clarifications",
                                      "source_exception_bindings") if key in payload},
        evidence_view=dict(facts=rows),
    )


def selected_generation_context(payload, selections, choices, *, packet_builder=None):
    """Keep canonical originals for replay; explicitly restrict task writing support."""
    active = {tid for tid, selection in selections.items() if selection["state"] == "selected"}
    tasks = [task for task in payload["tasks"] if task["task_id"] in active]
    questions = {task["question_id"] for task in tasks}
    refs = {ref for tid in active for ref in selections[tid]["support_refs"]}
    selected_ids = {
        row["id"] for row in payload["evidence_view"]["facts"]
        if refs.intersection(row.get("operation_support_refs", ())) or refs.intersection(
            item["support_ref"] for item in row.get("source_span_candidates", ()))
    }
    # Keep complete exception partners even when the selected reference is the
    # main rule. This restriction closure never adds support to an atom.
    pairs = payload.get("source_exception_bindings", ())
    while True:
        closure = selected_ids | {
            fid for pair in pairs if selected_ids.intersection(pair["fact_ids"])
            for fid in pair["fact_ids"]}
        if closure == selected_ids:
            break
        selected_ids = closure
    facts = [row for row in payload["evidence_view"]["facts"] if row["id"] in selected_ids]
    packets = packet_builder(facts) if packet_builder else payload["question_evidence_packets"]
    result = dict(
        payload,
        evidence_view=dict(payload["evidence_view"], facts=facts),
        tasks=tasks,
        questions=[q for q in payload["questions"] if q["question_id"] in questions],
        task_predicates=[row for row in payload["task_predicates"] if row["task_id"] in active],
        question_evidence_packets=[
            dict(
                packet, questions=[q for q in packet["questions"] if q["question_id"] in questions]
            )
            for packet in packets
        ],
        task_support_selections=[
            dict(
                task_id=task["task_id"],
                binding_kind=selections[task["task_id"]]["binding_kind"],
                support_refs=selections[task["task_id"]]["support_refs"],
                supports=[choices[ref] for ref in selections[task["task_id"]]["support_refs"]],
            )
            for task in tasks
        ],
    )
    if "task_repair" in result:
        result["task_repair"] = [row for row in result["task_repair"] if row["task_id"] in active]
    if "source_exception_bindings" in result:
        result["source_exception_bindings"] = [pair for pair in pairs
                                                if set(pair["fact_ids"]) <= selected_ids]
    return result
