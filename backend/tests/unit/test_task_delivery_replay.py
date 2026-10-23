"""QA replays transported task originals, never model task outcome labels."""

import copy
import hashlib
import json

import pytest
from test_question_context_qa import CLARIFY, CORE, EXCEPTION, case

from packages.agents.qa.question_context import _question_replays, question_context_blocks
from packages.agents.writer.dimension_writer import compact_prompt_json
from packages.agents.writer.task_protocol import CONTRACT, parse_tasks
from packages.orchestrator.question_packets import (
    packet_id,
    prompt_packets,
    receipt_hash,
    selection_receipt,
)
from packages.research.evidence.snapshot_models import canonical_json
from packages.research.evidence.views import select_evidence_view
from packages.schema.models import TraceSpan


def delivery_case():
    service, record, snapshot = case(factual=True, include_operation=True)
    detail = record.detail
    use = detail.evidence_consumptions[0]
    view = select_evidence_view(
        snapshot,
        agent=use.agent,
        competitor=use.competitor,
        dimension=use.dimension,
        source_ids=use.requested_source_ids,
        fact_ids=use.requested_fact_ids,
        max_bytes=use.view_max_bytes or use.max_bytes,
    )
    selection, old_writer, _ = detail.trace_spans[:3]
    selected = json.loads(selection.full_output)
    packet = selected["packets"][0]
    # Both real batches are needed to close the factual question's core obligation.
    packet["retrieval"]["questions"][0]["core_fact_ids"] = list(use.requested_fact_ids)
    packet["packet_id"] = packet_id(packet)
    selected["receipt"] = selection_receipt(detail, [packet], use.requested_fact_ids)
    use = use.model_copy(
        update={"id": use.id.rsplit("-", 1)[0] + "-" + receipt_hash(selected["receipt"])}
    )
    detail.evidence_consumptions = [use]
    selected["consumption_id"] = use.id
    selection.full_output = canonical_json(selected)
    questions = packet["questions"]
    plan = [
        dict(question_id=questions[0]["question_id"], question_quote=quote, focus="source_rule")
        for quote in ("Can Basic", "support", "3 users?")
    ]
    plan.append(
        dict(question_id=questions[-1]["question_id"], question_quote=CLARIFY, focus="source_rule")
    )
    tasks = parse_tasks(json.dumps(dict(tasks=plan)), questions, "Example Product/feature")
    pending = []
    for task in tasks:
        if task["question_id"] == questions[-1]["question_id"]:
            task.update(state="server_clarification", reason="request_only_clarification")
        else:
            pending.append(task)
    original_payload = json.loads(old_writer.full_input.split("\nJSON:\n", 1)[1])
    originals = sorted(
        (
            row
            for row in original_payload["evidence_view"]["facts"]
            if row["id"] in use.requested_fact_ids
        ),
        key=lambda row: bool(row.get("operation_observations")),
    )
    dispatches = []
    detail.trace_spans = [selection]
    for index, batch in enumerate((pending[:2], pending[2:])):
        payload = copy.deepcopy(original_payload)
        payload["evidence_view"]["facts"] = originals[index : index + 1]
        payload["question_evidence_packets"] = prompt_packets(
            [packet], snapshot, payload["evidence_view"]["facts"]
        )
        payload["tasks"] = [
            {k: v for k, v in task.items() if k not in {"state", "reason"}} for task in batch
        ]
        full_input = "SYSTEM\nJSON:\n" + compact_prompt_json(payload)
        span = TraceSpan(
            id=f"task-generation-{index}",
            kind="llm",
            agent="writer",
            subagent="Example Product/feature",
            name="dimension_task_generation",
            status="ok",
            duration_ms=0,
            full_input=full_input,
            metadata={"llm_transport_attempts": 1},
        )
        detail.trace_spans.append(span)
        dispatches.append(
            dict(
                span_id=span.id,
                full_input_sha256=hashlib.sha256(full_input.encode()).hexdigest(),
                task_ids=[task["task_id"] for task in batch],
                fact_ids=sorted(row["id"] for row in payload["evidence_view"]["facts"]),
            )
        )
    for task in pending:
        task.update(
            state="supported", reason="independent_task_and_source_review", claim_id="display-claim"
        )
    receipt = dict(
        contract=CONTRACT,
        consumption_id=use.id,
        snapshot_id=snapshot.id,
        packet_ids=[packet["packet_id"]],
        question_ids=[q["question_id"] for q in questions],
        planning="model_request_plan",
        tasks=tasks,
        dispatches=dispatches,
    )
    detail.trace_spans.append(
        TraceSpan(
            id="task-delivery",
            kind="tool",
            agent="writer",
            subagent="Example Product/feature",
            name="question_task_delivery",
            status="ok",
            duration_ms=0,
            full_output=canonical_json(receipt),
        )
    )
    return service, detail, snapshot, use, view, receipt


def save_receipt(detail, receipt):
    detail.trace_spans[-1].full_output = canonical_json(receipt)


def blocks(args, gaps=(CORE,)):
    service, detail, snapshot, use, view, _ = args
    request_only = {
        q["question_id"]
        for q in json.loads(detail.trace_spans[0].full_output)["packets"][0]["questions"]
        if q["question"] == CLARIFY
    }
    return question_context_blocks(service, detail, snapshot, use, view, gaps, request_only)


def rewrite_payload(args, mutate, index=1):
    _, detail, _, _, _, receipt = args
    span = detail.trace_spans[index]
    from packages.research.question_delivery import _expand_text_refs

    payload = _expand_text_refs(json.loads(span.full_input.split("\nJSON:\n", 1)[1]))
    mutate(payload)
    span.full_input = "SYSTEM\nJSON:\n" + compact_prompt_json(payload)
    receipt["dispatches"][index - 1]["full_input_sha256"] = hashlib.sha256(
        span.full_input.encode()
    ).hexdigest()
    save_receipt(detail, receipt)


def test_multiple_verified_task_dispatches_reconcile_their_union_before_request_only_waiver():
    args = delivery_case()
    replays = _question_replays(*args[:5])
    assert set(replays[1]["sent_fact_ids"]) == set(args[3].requested_fact_ids)
    assert not replays[1]["questions"][0]["evidence_gaps"]
    assert replays[1]["questions"][-1]["evidence_gaps"] == [CORE]
    assert not blocks(args)


@pytest.mark.parametrize("label", ["supported", "insufficient_evidence", "deferred", "rejected"])
def test_task_outcome_labels_never_replace_transport_or_reconciliation(label):
    args = delivery_case()
    _, detail, _, _, _, receipt = args
    receipt["tasks"][0]["state"] = label
    receipt["tasks"][0]["reason"] = "display_only"
    save_receipt(detail, receipt)
    assert not blocks(args)
    receipt["dispatches"] = receipt["dispatches"][:1]
    save_receipt(detail, receipt)
    assert blocks(args)


@pytest.mark.parametrize(
    "mutation",
    [
        "contract",
        "snapshot",
        "packet",
        "questions",
        "planning",
        "duplicate_receipt",
        "receipt_kind",
        "receipt_agent",
        "receipt_status",
        "receipt_scope",
        "duplicate_task",
        "task_alias",
        "task_quote",
        "task_question",
        "task_resource",
        "task_focus",
        "duplicate_span",
        "span_alias",
        "span_missing",
        "span_kind",
        "span_name",
        "span_agent",
        "span_scope",
        "span_status",
        "attempts",
        "attempts_bool",
        "span_hash",
        "dispatch_task",
        "dispatch_task_duplicate",
        "dispatch_fact",
        "duplicate_batch_task",
    ],
)
def test_task_delivery_identity_and_transport_tampering_keeps_context_gap_blocking(mutation):
    args = delivery_case()
    _, detail, _, _, _, receipt = args
    span, batch = detail.trace_spans[1], receipt["dispatches"][0]
    if mutation in {"contract", "snapshot", "packet", "questions", "planning"}:
        key = dict(snapshot="snapshot_id", packet="packet_ids", questions="question_ids").get(
            mutation, mutation
        )
        receipt[key] = ["forged"] if key.endswith("_ids") else "forged"
    elif mutation == "duplicate_receipt":
        detail.trace_spans.insert(
            -1, detail.trace_spans[-1].model_copy(update={"id": "receipt-copy"})
        )
    elif mutation.startswith("receipt_"):
        key = mutation.removeprefix("receipt_")
        setattr(
            detail.trace_spans[-1],
            "subagent" if key == "scope" else key,
            dict(kind="llm", agent="qa", status="error", scope="Other/feature")[key],
        )
    elif mutation == "duplicate_task":
        receipt["tasks"].append(dict(receipt["tasks"][0]))
    elif mutation in {"task_alias", "task_quote", "task_question", "task_resource", "task_focus"}:
        key = dict(
            task_alias="task_id",
            task_quote="question_quote",
            task_question="question_id",
            task_resource="resource",
            task_focus="focus",
        )[mutation]
        receipt["tasks"][0][key] = "forged"
    elif mutation == "duplicate_span":
        receipt["dispatches"].append(dict(batch))
    elif mutation == "span_alias":
        detail.trace_spans.insert(1, span.model_copy())
    elif mutation == "span_missing":
        detail.trace_spans.remove(span)
    elif mutation in {"span_kind", "span_name", "span_agent", "span_scope", "span_status"}:
        key = mutation.removeprefix("span_")
        setattr(
            span,
            "subagent" if key == "scope" else key,
            dict(
                kind="tool",
                name="dimension_claim_writer",
                agent="qa",
                scope="Other/feature",
                status="error",
            )[key],
        )
    elif mutation in {"attempts", "attempts_bool"}:
        span.metadata["llm_transport_attempts"] = 0 if mutation == "attempts" else True
    elif mutation == "span_hash":
        span.full_input += " changed"
    elif mutation in {"dispatch_task", "dispatch_task_duplicate"}:
        batch["task_ids"] = (
            ["forged"] if mutation == "dispatch_task" else [batch["task_ids"][0]] * 2
        )
    elif mutation == "dispatch_fact":
        batch["fact_ids"] = ["forged"]
    elif mutation == "duplicate_batch_task":
        receipt["dispatches"][1]["task_ids"] = list(batch["task_ids"])
    save_receipt(detail, receipt)
    assert blocks(args)


@pytest.mark.parametrize(
    "mutation",
    [
        "scope",
        "questions",
        "packet",
        "task",
        "fact_quote",
        "fact_value",
        "fact_foreign",
        "fact_duplicate",
        "operation",
        "operation_removed",
        "operation_ref",
        "spans_removed",
        "span_quote",
    ],
)
def test_rehashed_task_payload_requires_original_requests_facts_and_supports(mutation):
    args = delivery_case()

    def change(payload):
        row = payload["evidence_view"]["facts"][0]
        if mutation == "scope":
            payload["segment_competitor"] = "Other"
        elif mutation == "questions":
            payload["questions"][0]["question"] = "Can Basic?"
        elif mutation == "packet":
            payload["question_evidence_packets"][0]["questions"][0]["fact_ids"] = []
        elif mutation == "task":
            payload["tasks"][0]["question_quote"] = "rewritten"
        elif mutation.startswith("fact_"):
            if mutation == "fact_duplicate":
                payload["evidence_view"]["facts"].append(dict(row))
            else:
                row[dict(fact_quote="quote", fact_value="value", fact_foreign="id")[mutation]] = (
                    "forged"
                )
        elif mutation == "operation":
            row["operation_observations"][0]["prerequisites"] = []
        elif mutation == "operation_removed":
            row["operation_observations"] = []
        elif mutation == "operation_ref":
            row["operation_support_refs"][0] = "s999"
        elif mutation == "spans_removed":
            row["source_span_candidates"] = []
        elif mutation == "span_quote":
            row["source_span_candidates"][0]["quote"] = "forged"

    rewrite_payload(args, change, index=2 if mutation.startswith("operation") else 1)
    assert blocks(args)


@pytest.mark.parametrize("gaps", [(EXCEPTION,), (CORE, "question_dispatch_unverified")])
def test_task_replay_keeps_exception_and_unknown_gaps_blocking(gaps):
    assert blocks(delivery_case(), gaps=gaps)


def test_a_canonical_snapshot_original_outside_current_generation_view_is_rejected():
    args = delivery_case()
    _, _, snapshot, _, view, _ = args
    foreign = next(fact for fact in snapshot.facts if fact.id not in view.fact_ids)

    def change(payload):
        payload["evidence_view"]["facts"] = [
            dict(
                id=foreign.id,
                source_id=foreign.source_id,
                competitor=foreign.competitor,
                dimension=foreign.dimension,
                field=foreign.field,
                quote=foreign.quote,
                value=foreign.value,
                qualifiers={k: v for k, v in foreign.qualifiers.items() if k != "operations"},
            )
        ]

    rewrite_payload(args, change)
    assert blocks(args)


def test_task_replay_keeps_the_original_context_byte_budget():
    args = list(delivery_case())
    args[3] = args[3].model_copy(update={"max_bytes": 1})
    assert blocks(args)


def test_pure_server_clarification_labels_do_not_invent_a_transport():
    args = delivery_case()
    _, detail, _, _, _, receipt = args
    receipt["dispatches"] = []
    for task in receipt["tasks"]:
        task.update(state="server_clarification", reason="request_only_clarification")
    save_receipt(detail, receipt)
    assert blocks(args)


def test_task_diagnostics_are_observations_and_do_not_change_dispatched_identity():
    args = delivery_case()
    _, detail, _, _, _, receipt = args
    receipt["tasks"][0]["diagnostic"] = "source binding failed after transport"
    save_receipt(detail, receipt)
    assert not blocks(args)
