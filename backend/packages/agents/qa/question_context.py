"""Replay ownership of context omissions from the current Writer credential."""

from __future__ import annotations

import hashlib
import json

from packages.orchestrator.question_packets import (
    prompt_packets,
    reconcile_packet_originals,
    selection_receipt,
    validate_packets,
)
from packages.research.question_delivery import _expand_text_refs

CORE_GAP = "question_core_context_budget_exceeded"
EXCEPTION_GAP = "question_exception_context_budget_exceeded"


def _observations(detail, name, consumption_id, *, optional=False, scope=None):
    result = []
    for span in detail.trace_spans:
        if span.name == name:
            value = json.loads(span.full_output)
            if value.get("consumption_id") == consumption_id:
                if (
                    span.kind != "tool"
                    or span.agent != "writer"
                    or span.status != "ok"
                    or scope is not None
                    and span.subagent != scope
                ):
                    raise ValueError("question observation producer changed")
                result.append(value)
    if optional and not result:
        return None
    if len(result) != 1:
        raise ValueError("question observation missing or ambiguous")
    return result[0]


def _validate_dispatched_support(payload, originals, sent_ids):
    """Every dispatched operation/alias/span must retain its canonical support.

    Compact requests may select a bounded subset of legal candidates, but may
    not erase an existing operation or the reserved complete source member.
    """
    from packages.agents.writer.readable_support import support_ref_catalog
    from packages.research.evidence.operations import operation_binding, operation_observations
    from packages.research.evidence.source_spans import source_span_candidates

    catalog = support_ref_catalog(payload, originals, set(sent_ids))
    known = {fact.id: fact for fact in originals}
    refs = []
    for row in payload["evidence_view"]["facts"]:
        original = known[row["id"]]
        legal = [operation_binding(op) for op in operation_observations(original)]
        observed = row.get("operation_observations", [])
        targets = row.get("operation_targets", [])
        operation_refs = row.get("operation_support_refs", [])
        spans = row.get("source_span_candidates", [])
        if (
            not all(isinstance(items, list) for items in (observed, targets, operation_refs, spans))
            or legal
            and not observed
            or any(item not in legal for item in observed)
            or len(targets) != len(set(targets))
            or set(targets) != {item["operation"] for item in observed}
            or len(operation_refs) != len(observed)
            or source_span_candidates(original)
            and not spans
        ):
            raise ValueError(
                "question dispatched operation conditions or support missing or changed"
            )
        refs.extend(operation_refs)
        refs.extend(span["support_ref"] for span in spans)
    if len(refs) != len(set(refs)) or set(refs) != set(catalog):
        raise ValueError("question dispatched support catalog missing or changed")


def _dispatched_originals(detail, snapshot, use, view, packets, dispatch, name, *,
                          service=None, handoff_version=None):
    """Validate one actual transport with the existing original/support contract."""
    packet = packets[0]
    spans = [span for span in detail.trace_spans if span.id == dispatch["span_id"]]
    if len(spans) != 1:
        raise ValueError("question dispatch span missing or ambiguous")
    span = spans[0]
    attempts = span.metadata.get("llm_transport_attempts")
    if (
        span.kind != "llm"
        or span.name != name
        or span.agent != "writer"
        or span.subagent != f"{use.competitor}/{use.dimension}"
        or span.status != "ok"
        or type(attempts) is not int
        or attempts <= 0
        or hashlib.sha256(span.full_input.encode()).hexdigest() != dispatch["full_input_sha256"]
    ):
        raise ValueError("question transport unverified")
    raw = span.full_input.split("\nJSON:\n", 1)[1]
    if len(raw.encode()) + len("\nJSON:\n") > use.max_bytes:
        raise ValueError("question dispatch context exceeded")
    payload = _expand_text_refs(json.loads(raw))
    from packages.agents.writer.task_execution import has_task_handoff_system
    if (has_task_handoff_system(span.full_input) or handoff_version is not None
            or 'task_handoff_version' in payload or 'request_context' in payload):
        from types import SimpleNamespace

        from packages.agents.writer.task_execution import (
            ADVISORY_PROJECTION_SYSTEM_IDENTITY,
            HANDOFF_VERSION,
            task_request_context_version,
            validate_task_handoff,
        )
        if (type(handoff_version) is not int or handoff_version != HANDOFF_VERSION
                or service is None):
            raise ValueError('question task handoff version changed')
        system = span.full_input.split('\nJSON:\n', 1)[0]
        validate_task_handoff(service, SimpleNamespace(detail=detail, evidence_origin=None),
                              payload, view, projection_version=(
                                  2 if ADVISORY_PROJECTION_SYSTEM_IDENTITY in system else 1),
                              request_context_version=task_request_context_version(span.full_input))
    facts = payload["evidence_view"]["facts"]
    expected_questions = packet["questions"]
    if name == "dimension_task_generation":
        active_ids = {task["question_id"] for task in payload["tasks"]}
        narrowed = [q for q in packet["questions"] if q["question_id"] in active_ids]
        if payload["questions"] == narrowed:
            expected_questions = narrowed
    if (
        payload["segment_competitor"] != use.competitor
        or payload["dimension"] != use.dimension
        or payload["questions"] != expected_questions
        or not isinstance(facts, list)
    ):
        raise ValueError("question dispatched scope changed")
    sent_ids = [fact["id"] for fact in facts]
    if len(sent_ids) != len(set(sent_ids)) or not set(sent_ids) <= set(view.fact_ids):
        raise ValueError("question dispatched originals not in the generation view")
    actual = reconcile_packet_originals(packet, snapshot, facts)
    expected_packets = prompt_packets(packets, snapshot, facts)
    if expected_questions != packet["questions"]:
        active_ids = {q["question_id"] for q in expected_questions}
        expected_packets = [
            dict(p, questions=[q for q in p["questions"] if q["question_id"] in active_ids])
            for p in expected_packets
        ]
    if (
        set(actual["sent_fact_ids"]) != set(sent_ids)
        or payload["question_evidence_packets"] != expected_packets
    ):
        raise ValueError("question dispatched originals or packet content changed")
    _validate_dispatched_support(payload, view.facts, sent_ids)
    return facts


def _task_delivery_originals(detail, snapshot, use, view, packets, receipt, *, service=None):
    from packages.agents.writer.task_execution import (
        HANDOFF_VERSION,
        has_two_phase_generation_system,
        task_request_context_version,
    )
    from packages.agents.writer.task_protocol import CONTRACT, parse_tasks

    packet = packets[0]
    if 'advisory_delivery' in receipt and (
            type(receipt.get('task_handoff_version')) is not int
            or receipt['task_handoff_version'] != HANDOFF_VERSION):
        raise ValueError('question task handoff version missing or changed')
    tasks, dispatches = receipt["tasks"], receipt["dispatches"]
    if (
        receipt["contract"] != CONTRACT
        or receipt["snapshot_id"] != snapshot.id
        or receipt["packet_ids"] != [packet["packet_id"]]
        or receipt["question_ids"] != [q["question_id"] for q in packet["questions"]]
        or receipt["planning"] not in {"model_request_plan", "bounded_request_fallback"}
        or not isinstance(tasks, list)
        or not tasks
        or not isinstance(dispatches, list)
        or not dispatches
        or any(not isinstance(task, dict) for task in tasks)
    ):
        raise ValueError("question task receipt identity changed")
    # Outcome labels are display observations. Rebuild identities from the exact
    # request fragments, including the server's named-resource expansion.
    observed = [
        {
            key: value
            for key, value in task.items()
            if key
            not in {
                "state",
                "reason",
                "claim_id",
                "diagnostic",
                "decision",
                "claim_digest",
                "review_span_id",
                "review_input_sha256",
                "repair_attempted",
            }
            | {"repair_prior_state", "repair_prior_claim_id", "repair_outcome"}
        }
        for task in tasks
    ]
    plan = []
    for task in tasks:
        row = {key: task[key] for key in ("question_id", "question_quote", "focus")}
        if row not in plan:
            plan.append(row)
    canonical = parse_tasks(
        json.dumps({"tasks": plan}), packet["questions"], f"{use.competitor}/{use.dimension}"
    )
    expected = [
        {key: value for key, value in task.items() if key not in {"state", "reason"}}
        for task in canonical
    ]
    if observed != expected:
        raise ValueError("question task identities changed")
    known = {task["task_id"]: task for task in observed}
    if len(known) != len(observed):
        raise ValueError("question task identity ambiguous")
    sent, seen_spans, seen_tasks, repaired = {}, set(), set(), False
    two_phase_tasks = set()
    parent_v2_tasks = set()
    for dispatch in dispatches:
        ids = dispatch["task_ids"]
        attempt = dispatch.get("attempt", 0)
        if (
            not isinstance(ids, list)
            or not ids
            or len(ids) > 3
            or len(ids) != len(set(ids))
            or not set(ids) <= known.keys()
            or type(attempt) is not int
            or attempt not in (0, 1)
            or (attempt == 0 and bool(seen_tasks.intersection(ids)))
            or (attempt == 1 and (repaired or len(ids) > 2 or not set(ids) <= seen_tasks))
            or dispatch["span_id"] in seen_spans
        ):
            raise ValueError("question task dispatch identity ambiguous")
        facts = _dispatched_originals(
            detail, snapshot, use, view, packets, dispatch, "dimension_task_generation",
            service=service, handoff_version=receipt.get('task_handoff_version'),
        )
        span = next(span for span in detail.trace_spans if span.id == dispatch["span_id"])
        if has_two_phase_generation_system(span.full_input):
            two_phase_tasks.update(ids)
        if task_request_context_version(span.full_input) == 2:
            parent_v2_tasks.update(ids)
        payload = _expand_text_refs(json.loads(span.full_input.split("\nJSON:\n", 1)[1]))
        if attempt == 1:
            repairs = payload.get("task_repair", [])
            if len(repairs) != len(ids) or {r["task_id"] for r in repairs} != set(ids):
                raise ValueError("question repair does not bind the original tasks")
            repaired = True
        if payload["tasks"] != [known[tid] for tid in ids] or dispatch["fact_ids"] != sorted(
            fact["id"] for fact in facts
        ):
            raise ValueError("question task batch or originals changed")
        seen_spans.add(dispatch["span_id"])
        seen_tasks.update(ids)
        sent.update((fact["id"], fact) for fact in facts)
    from packages.agents.writer.task_execution import (
        ADVISORY_REVIEW_SYSTEM_IDENTITY,
        HANDOFF_SYSTEM_IDENTITY,
        validate_task_handoff,
    )
    review_ids = {task.get('review_span_id') for task in tasks}
    for task in tasks:
        if task['task_id'] not in two_phase_tasks or not task.get('review_span_id'):
            continue
        matches = [span for span in detail.trace_spans if span.id == task['review_span_id']]
        if len(matches) != 1 or not matches[0].full_input.startswith(
                HANDOFF_SYSTEM_IDENTITY + ADVISORY_REVIEW_SYSTEM_IDENTITY) or (
                task['task_id'] in parent_v2_tasks
                and task_request_context_version(matches[0].full_input) != 2):
            raise ValueError('question task advisory review phase changed')
    for span in detail.trace_spans:
        if span.id not in review_ids or not span.full_input.startswith(
                HANDOFF_SYSTEM_IDENTITY + ADVISORY_REVIEW_SYSTEM_IDENTITY):
            continue
        from types import SimpleNamespace
        if service is None:
            raise ValueError('question task advisory review cannot be rebuilt')
        payload = _expand_text_refs(json.loads(span.full_input.split('\nJSON:\n', 1)[1]))
        validate_task_handoff(service, SimpleNamespace(detail=detail, evidence_origin=None),
                              payload, view,
                              request_context_version=task_request_context_version(span.full_input))
    return list(sent.values())


def _question_replays(service, detail, snapshot, use, view):
    """Rebuild from immutable packet content and the actual transported originals.

    Display diagnostics and old dispatch status are observations, not authority.
    A dispatch may have been recorded before the current use was validated.
    """
    if (
        not use.id.startswith("question-evidence-use-")
        or use.agent != "writer"
        or use.status not in {"validated", "reused"}
        or (use.run_id, use.workspace_id, use.project_id)
        != (detail.id, detail.workspace_id, detail.project_id)
        or use.snapshot_id != snapshot.id
        or use.validated_snapshot_id != snapshot.id
        or use.snapshot_version != snapshot.version
        or view.dependency_hash != use.dependency_hash
        or view.fact_ids != use.fact_ids
        or view.source_ids != use.source_ids
    ):
        raise ValueError("question generation use unverified")
    service._validate_question_selection_receipt(detail, snapshot, use)
    selection = _observations(detail, "question_evidence_selection", use.id)
    packets = selection["packets"]
    validate_packets(detail, snapshot, packets)
    if (
        len(packets) != 1
        or (packets[0]["competitor"], packets[0]["dimension"]) != (use.competitor, use.dimension)
        or selection["receipt"] != selection_receipt(detail, packets, use.requested_fact_ids)
    ):
        raise ValueError("question packet differs from the bound selection receipt")
    packet = packets[0]
    expected_ids = {q["question_id"] for q in packet["questions"]}
    diagnostics = packet["retrieval"]["questions"]
    row_ids = [row["question_id"] for row in diagnostics]
    if len(row_ids) != len(set(row_ids)) or not set(row_ids) <= expected_ids:
        raise ValueError("question diagnostic identity changed")
    from packages.agents.writer.question_retrieval import _eligible_facts

    eligible = {f.id for f in _eligible_facts(snapshot, use.competitor, use.dimension)}
    for row in diagnostics:
        for key in (
            "fact_ids",
            "core_fact_ids",
            "missing_core_fact_ids",
            "required_exception_fact_ids",
            "missing_exception_fact_ids",
        ):
            ids = row.get(key, ())
            if not isinstance(ids, (list, tuple)) or any(fid not in eligible for fid in ids):
                raise ValueError("question obligation original unverified")
    receipt = _observations(
        detail,
        "question_task_delivery",
        use.id,
        optional=True,
        scope=f"{use.competitor}/{use.dimension}",
    )
    if receipt is not None:
        facts = _task_delivery_originals(
            detail, snapshot, use, view, packets, receipt, service=service)
    else:
        dispatch = _observations(detail, "question_evidence_dispatch", use.id)
        if dispatch["snapshot_id"] != snapshot.id or dispatch["packet_ids"] != [
            packet["packet_id"]
        ]:
            raise ValueError("question dispatch packet changed")
        facts = _dispatched_originals(
            detail, snapshot, use, view, packets, dispatch, "dimension_claim_writer"
        )
    actual = reconcile_packet_originals(packet, snapshot, facts)
    return (reconcile_packet_originals(packet, snapshot, view.facts), actual)


def question_context_blocks(service, detail, snapshot, use, view, gaps, request_only_ids):
    """Only attributable core omissions for exact request-only answers may pass."""
    context_gaps = {CORE_GAP, EXCEPTION_GAP} & set(gaps)
    if not context_gaps:
        return False
    if (
        EXCEPTION_GAP in context_gaps
        or not request_only_ids
        or any(gap.startswith("question_") and gap != CORE_GAP for gap in gaps)
    ):
        return True
    try:
        replays = _question_replays(service, detail, snapshot, use, view)
        attributable = False
        for replay in replays:
            for row in replay["questions"]:
                row_gaps = set(row["evidence_gaps"])
                if row_gaps - {CORE_GAP}:
                    return True
                if CORE_GAP in row_gaps:
                    attributable = True
                    if row["question_id"] not in request_only_ids:
                        return True
        return not attributable
    except (ValueError, KeyError, TypeError, AttributeError, IndexError):
        # Legacy/redacted/unknown provenance retains the previous blocking gate.
        return True
