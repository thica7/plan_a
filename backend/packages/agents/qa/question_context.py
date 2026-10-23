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


def _observations(detail, name, consumption_id):
    result = []
    for span in detail.trace_spans:
        if span.name == name:
            value = json.loads(span.full_output)
            if value.get("consumption_id") == consumption_id:
                if span.kind != "tool" or span.agent != "writer" or span.status != "ok":
                    raise ValueError("question observation producer changed")
                result.append(value)
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
    dispatch = _observations(detail, "question_evidence_dispatch", use.id)
    if dispatch["snapshot_id"] != snapshot.id or dispatch["packet_ids"] != [packet["packet_id"]]:
        raise ValueError("question dispatch packet changed")
    spans = [span for span in detail.trace_spans if span.id == dispatch["span_id"]]
    if len(spans) != 1:
        raise ValueError("question dispatch span missing or ambiguous")
    span = spans[0]
    attempts = span.metadata.get("llm_transport_attempts")
    if (
        span.kind != "llm"
        or span.name != "dimension_claim_writer"
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
    facts = payload["evidence_view"]["facts"]
    if (
        payload["segment_competitor"] != use.competitor
        or payload["dimension"] != use.dimension
        or payload["questions"] != packet["questions"]
        or not isinstance(facts, list)
    ):
        raise ValueError("question dispatched scope changed")
    sent_ids = [fact["id"] for fact in facts]
    if len(sent_ids) != len(set(sent_ids)) or not set(sent_ids) <= set(view.fact_ids):
        raise ValueError("question dispatched originals not in the generation view")
    actual = reconcile_packet_originals(packet, snapshot, facts)
    if set(actual["sent_fact_ids"]) != set(sent_ids) or payload[
        "question_evidence_packets"
    ] != prompt_packets(packets, snapshot, facts):
        raise ValueError("question dispatched originals or packet content changed")
    _validate_dispatched_support(payload, view.facts, sent_ids)
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
