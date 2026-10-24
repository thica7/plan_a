"""Task selection is bounded transport, never a substitute for claim review."""

import hashlib
import json
import time
from datetime import UTC, datetime

import pytest
from claim_review_fixture import expand_prompt_payload, supported_review
from pydantic import HttpUrl, TypeAdapter
from test_question_retrieval import research_case
from test_writer_question_delivery import service_for

from packages.research.evidence.snapshot import seal_snapshot
from packages.schema.models import DecisionBrief


def writer_case():
    question = "Example Product：访客有私人区域吗？访客能同时加入两个容器吗？"
    parts = ["访客有私人区域吗？", "访客能同时加入两个容器吗？"]
    texts = ["Guests have no personal area.", "Guests are invited to one collection at a time."]
    detail, _ = research_case(texts, question=question)
    detail.created_at = detail.updated_at = datetime.now(UTC)
    detail.plan.competitors, detail.plan.dimensions = ["Example Product"], ["feature"]
    detail.plan.decision_brief = DecisionBrief(decision_question=question)
    for source in detail.raw_sources:
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
    seal_snapshot(detail, phase="analysis", canonical_documents={})
    service, record = service_for(detail, task_execution=True)
    return service, record, parts, texts


def selection_row(task_id="a", refs=None, **updates):
    return (
        dict(
            task_id=task_id,
            status="selected",
            binding_kind="span",
            support_refs=refs if refs is not None else ["s1"],
        )
        | updates
    )


@pytest.mark.parametrize(
    "change",
    [
        "foreign_ref",
        "duplicate_ref",
        "duplicate_task",
        "missing",
        "operation_as_span",
        "span_as_operation",
        "mixed",
        "extra_field",
        "invalid_kind",
        "unhashable_ref",
        "unhashable_kind",
        "two_operations",
    ],
)
def test_bad_selection_is_explicit_without_discarding_a_valid_peer(change):
    from packages.agents.writer.task_support_selection import parse_support_selections

    choices = {
        "s1": dict(binding_kind="span"),
        "s2": dict(binding_kind="span"),
        "o1": dict(binding_kind="operation"),
        "o2": dict(binding_kind="operation"),
    }
    good, bad = selection_row(), selection_row("b", ["s2"])
    if change == "foreign_ref":
        bad["support_refs"] = ["s999"]
    elif change == "duplicate_ref":
        bad["support_refs"] = ["s2", "s2"]
    elif change == "operation_as_span":
        bad["support_refs"] = ["o1"]
    elif change == "span_as_operation":
        bad["binding_kind"] = "operation"
    elif change == "mixed":
        bad["support_refs"] = ["s2", "o1"]
    elif change == "extra_field":
        bad["text"] = "invented claim"
    elif change == "invalid_kind":
        bad["binding_kind"] = "fact"
    elif change == "unhashable_ref":
        bad["support_refs"] = [[]]
    elif change == "unhashable_kind":
        bad["binding_kind"] = []
    elif change == "two_operations":
        bad.update(binding_kind="operation", support_refs=["o1", "o2"])
    rows = [good] if change == "missing" else [good, bad]
    if change == "duplicate_task":
        rows.append(dict(bad))
    parsed, failures = parse_support_selections(
        json.dumps(dict(selections=rows)), [dict(task_id="a"), dict(task_id="b")], choices
    )
    assert parsed["a"] == dict(state="selected", binding_kind="span", support_refs=["s1"])
    assert parsed["b"]["state"] == "deferred"
    assert parsed["b"]["reason"] == (
        "task_support_selection_missing"
        if change == "missing"
        else "task_support_selection_invalid"
    )
    assert not failures


def test_foreign_task_and_malformed_identity_remain_explicit_beside_a_valid_peer():
    from packages.agents.writer.task_support_selection import parse_support_selections

    parsed, failures = parse_support_selections(
        json.dumps(
            dict(
                selections=[
                    selection_row(),
                    selection_row("foreign"),
                    dict(task_id=[], support_refs=["s1"]),
                ]
            )
        ),
        [dict(task_id="a")],
        {"s1": dict(binding_kind="span")},
    )
    assert parsed["a"]["state"] == "selected"
    assert failures == [
        "task_support_selection_foreign_task",
        "task_support_selection_invalid_identity",
    ]


def test_readable_choices_preserve_the_actual_operation_identity_and_complete_source_conditions():
    from types import SimpleNamespace

    from test_literal_non_operation import fact

    from packages.agents.writer.readable_support import dispatched_support_choices
    from packages.agents.writer.task_execution import task_context
    from packages.agents.writer.task_support_selection import selected_generation_context

    quote = "Only admins can manage document permissions after verification and sign-in."
    original = fact(quote=quote)
    task = dict(task_id="a", question_id="q", question_quote="谁能更改权限？", focus="source_rule")
    payload = task_context(
        SimpleNamespace(_question_packet_prompt=lambda *args: []),
        None,
        dict(segment_competitor=original.competitor, dimension="feature"),
        SimpleNamespace(facts=[original], competitor=original.competitor, dimension="feature"),
        {original.id},
        [dict(question_id="q", question="已完成验证并登录，谁能更改权限？")],
        [],
        [task],
        SimpleNamespace(max_bytes=14000),
    )
    choices = dispatched_support_choices(payload, [original], {original.id})
    operation_ref = next(
        ref for ref, choice in choices.items() if choice["binding_kind"] == "operation"
    )
    operation = choices[operation_ref]["operation_binding"]
    assert operation == payload["evidence_view"]["facts"][0]["operation_observations"][0]
    assert operation["observation_id"].startswith("operation-")
    assert operation["prerequisites"]
    assert "verification and sign-in" in operation["operation_quote"]
    selected = selected_generation_context(
        payload,
        {"a": dict(state="selected", binding_kind="operation", support_refs=[operation_ref])},
        choices,
    )
    assert selected["task_support_selections"][0]["supports"] == [choices[operation_ref]]
    assert selected["questions"] == payload["questions"]
    # An ignored foreign row cannot shadow the readable identity of a valid ref.
    foreign = dict(payload["evidence_view"]["facts"][0], id="foreign")
    foreign["operation_observations"] = [dict(operation, role="Guests")]
    foreign["operation_support_refs"] = ["o999"]
    foreign["source_span_candidates"] = []
    payload["evidence_view"]["facts"].append(foreign)
    assert (
        dispatched_support_choices(payload, [original], {original.id})[operation_ref]
        == choices[operation_ref]
    )
    payload["evidence_view"]["facts"].pop()
    # An invalid operation appended inside the canonical row cannot shadow o1.
    row = payload["evidence_view"]["facts"][0]
    row["operation_observations"].append(dict(operation, role="Guests"))
    row["operation_support_refs"].append("o999")
    assert (
        dispatched_support_choices(payload, [original], {original.id})[operation_ref]
        == choices[operation_ref]
    )
    row["operation_observations"].pop()
    row["operation_support_refs"].pop()
    # Tampering with a sent identity cannot create a usable operation choice.
    payload["evidence_view"]["facts"][0]["operation_observations"][0]["role"] = "Guests"
    assert operation_ref not in dispatched_support_choices(payload, [original], {original.id})


def append_response(service, record, kwargs, response, *, attempts=1):
    service._append_trace_span(
        service._evidence_live_record(record),
        kind="llm",
        agent=kwargs["agent"],
        subagent=kwargs["subagent"],
        name=kwargs["name"],
        status="ok",
        started=time.perf_counter(),
        input_text=kwargs["system"] + "\n\n" + kwargs["user"],
        output_text=response or "",
        metadata={"llm_transport_attempts": attempts},
    )
    return response


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "generation_fault",
    [
        None,
        "missing_selection",
        "changed_output",
        "changed_system",
        "zero_attempts",
        "foreign_scope",
        "foreign_agent",
        "duplicate",
        "duplicate_foreign",
    ],
)
async def test_real_writer_selects_complete_support_for_each_task_before_generation(
    monkeypatch, generation_fault
):
    service, record, parts, texts = writer_case()
    calls, selected_refs = [], {}

    async def model(record, **kwargs):
        name = kwargs["name"]
        calls.append(name)
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        if name == "dimension_task_plan":
            response = dict(
                tasks=[
                    dict(
                        question_id=next(
                            q["question_id"] for q in payload["questions"] if part in q["question"]
                        ),
                        question_quote=part,
                        focus="source_rule",
                    )
                    for part in parts
                ]
            )
        elif name == "dimension_task_support_selection":
            assert all(any(part in q["question"] for q in payload["questions"]) for part in parts)
            choices = [
                span
                for row in payload["evidence_view"]["facts"]
                for span in row["source_span_candidates"]
            ]
            selections = []
            for task in payload["tasks"]:
                quote = texts[parts.index(task["question_quote"])]
                ref = next(span["support_ref"] for span in choices if span["quote"] == quote)
                selected_refs[task["task_id"]] = ref
                selections.append(
                    dict(
                        task_id=task["task_id"],
                        status="selected",
                        binding_kind="span",
                        support_refs=[ref],
                    )
                )
            response = dict(selections=selections)
        elif name == "dimension_task_generation":
            assert "task_support_selections" in payload, (
                "Writer generated before task support selection"
            )
            bindings = {row["task_id"]: row for row in payload["task_support_selections"]}
            results = []
            for task in payload["tasks"]:
                binding = bindings[task["task_id"]]
                quote = texts[parts.index(task["question_quote"])]
                assert binding["binding_kind"] == "span"
                assert binding["support_refs"] == [selected_refs[task["task_id"]]]
                assert binding["supports"][0]["quote"] == quote
                results.append(
                    dict(
                        task_id=task["task_id"],
                        status="generated",
                        atom=dict(text=quote, kind="fact", support_refs=binding["support_refs"]),
                    )
                )
            response = dict(results=results)
        elif name == "dimension_task_review":
            response = dict(
                reviews=[supported_review(c) for c in payload["claims"]],
                decisions=[
                    dict(
                        task_id=a["task_id"],
                        claim_id=a["claim_id"],
                        task_fulfilled=True,
                        conclusion="no",
                        relation="direct",
                    )
                    for a in payload["task_assignments"]
                ],
            )
        else:
            assert name == "dimension_answer_review"
            return append_response(service, record, kwargs, None)
        returned = json.dumps(response)
        if name == "dimension_task_generation" and generation_fault:
            trace_kwargs, trace_output, attempts = kwargs, returned, 1
            if generation_fault == "missing_selection":
                del payload["task_support_selections"]
                trace_kwargs = dict(kwargs, user="\nJSON:\n" + json.dumps(payload))
            elif generation_fault == "changed_output":
                trace_output = json.dumps(dict(results=[]))
            elif generation_fault == "changed_system":
                trace_kwargs = dict(kwargs, system="Untrusted replacement instructions")
            elif generation_fault == "zero_attempts":
                attempts = 0
            elif generation_fault == "foreign_scope":
                trace_kwargs = dict(kwargs, subagent="Other/feature")
            elif generation_fault == "foreign_agent":
                trace_kwargs = dict(kwargs, agent="qa")
            append_response(service, record, trace_kwargs, trace_output, attempts=attempts)
            if generation_fault in {"duplicate", "duplicate_foreign"}:
                duplicate_kwargs = (
                    dict(kwargs, subagent="Other/feature")
                    if generation_fault == "duplicate_foreign"
                    else kwargs
                )
                append_response(service, record, duplicate_kwargs, returned)
            return returned
        return append_response(service, record, kwargs, returned)

    monkeypatch.setattr(service, "_trace_llm_text", model)
    await service._real_writer_step(record)
    assert calls[:3] == [
        "dimension_task_plan",
        "dimension_task_support_selection",
        "dimension_task_generation",
    ]
    receipt = json.loads(
        next(s.full_output for s in record.detail.trace_spans if s.name == "question_task_delivery")
    )
    if generation_fault:
        assert all(
            task["state"] == "deferred" and task["reason"] == "task_generation_transport_unverified"
            for task in receipt["tasks"]
        )
        assert not receipt["dispatches"]
        assert "dimension_task_review" not in calls
        assert not record.detail.report_dimension_audits[0].claims
        return
    assert (
        sum(c.status == "supported" for c in record.detail.report_dimension_audits[0].claims) == 2
    )
    selection = receipt["support_selections"][0]
    span = next(s for s in record.detail.trace_spans if s.id == selection["span_id"])
    assert selection["full_input_sha256"] == hashlib.sha256(span.full_input.encode()).hexdigest()
    assert selection["transport_verified"] is True
    assert {row["state"] for row in selection["results"].values()} == {"selected"}
    # Existing canonical generation dispatches remain replayable by final QA.
    from packages.agents.qa.question_context import _question_replays
    from packages.research.evidence.snapshot import current_snapshot
    from packages.research.evidence.views import select_evidence_view

    snapshot = current_snapshot(record.detail)
    assert service._final_qa_producer_verified(record, snapshot)
    use = next(u for u in record.detail.evidence_consumptions if u.id == receipt["consumption_id"])
    view = select_evidence_view(
        snapshot,
        agent=use.agent,
        competitor=use.competitor,
        dimension=use.dimension,
        source_ids=use.requested_source_ids,
        fact_ids=use.requested_fact_ids,
        max_bytes=use.view_max_bytes or use.max_bytes,
    )
    replay = _question_replays(service, record.detail, snapshot, use, view)
    assert set(replay[1]["sent_fact_ids"]) == set(receipt["dispatches"][0]["fact_ids"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        "budget",
        "zero_attempts",
        "wrong_transport",
        "changed_input",
        "changed_system",
        "oversized",
        "missing",
        "duplicate",
        "foreign_ref",
        "unselected_ref",
        "review_rejected",
    ],
)
async def test_real_selection_failures_keep_the_valid_peer_and_never_supply_default_support(
    monkeypatch, failure
):
    from packages.llm.errors import LLMExecutionLimitError

    service, record, parts, texts = writer_case()
    generation_ids, selection_calls = [], []

    async def model(record, **kwargs):
        name = kwargs["name"]
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        if name == "dimension_task_plan":
            response = dict(
                tasks=[
                    dict(
                        question_id=next(
                            q["question_id"] for q in payload["questions"] if part in q["question"]
                        ),
                        question_quote=part,
                        focus="source_rule",
                    )
                    for part in parts
                ]
            )
        elif name == "dimension_task_support_selection":
            selection_calls.append(kwargs)
            if failure == "budget":
                raise LLMExecutionLimitError("llm_budget_reserved_for_delivery")
            choices = [
                span
                for row in payload["evidence_view"]["facts"]
                for span in row["source_span_candidates"]
            ]
            rows = [
                selection_row(
                    task["task_id"],
                    [
                        next(
                            span["support_ref"]
                            for span in choices
                            if span["quote"] == texts[parts.index(task["question_quote"])]
                        )
                    ],
                )
                for task in payload["tasks"]
            ]
            if failure == "missing":
                rows.pop()
            elif failure == "duplicate":
                rows.append(dict(rows[-1]))
            elif failure == "foreign_ref":
                rows[-1]["support_refs"] = ["s999"]
            response = json.dumps(dict(selections=rows))
            if failure == "oversized":
                response += " " * 4096
            if failure == "wrong_transport":
                kwargs = dict(kwargs, subagent="Other/feature")
            elif failure == "changed_input":
                kwargs = dict(kwargs, user=kwargs["user"] + " ")
            elif failure == "changed_system":
                kwargs = dict(kwargs, system="Untrusted replacement instructions")
            return append_response(
                service, record, kwargs, response, attempts=0 if failure == "zero_attempts" else 1
            )
        elif name == "dimension_task_generation":
            generation_ids.append([task["task_id"] for task in payload["tasks"]])
            selections = {row["task_id"]: row for row in payload["task_support_selections"]}
            results = []
            for task in payload["tasks"]:
                if payload.get("task_repair"):
                    results.append(
                        dict(task_id=task["task_id"], status="insufficient_evidence", atom=None)
                    )
                    continue
                refs = selections[task["task_id"]]["support_refs"]
                if failure == "unselected_ref" and task["question_quote"] == parts[1]:
                    refs = next(
                        row["support_refs"]
                        for row in payload["task_support_selections"]
                        if row["task_id"] != task["task_id"]
                    )
                results.append(
                    dict(
                        task_id=task["task_id"],
                        status="generated",
                        atom=dict(
                            text=texts[parts.index(task["question_quote"])],
                            kind="fact",
                            support_refs=refs,
                        ),
                    )
                )
            response = dict(results=results)
        elif name == "dimension_task_review":
            reviews = [supported_review(c) for c in payload["claims"]]
            if failure == "review_rejected":
                rejected = next(
                    row
                    for row, claim in zip(reviews, payload["claims"], strict=True)
                    if claim["text"] == texts[1]
                )
                rejected["verdict"] = "unsupported"
                for check in rejected["checks"]:
                    check["verdict"] = "unsupported"
            response = dict(
                reviews=reviews,
                decisions=[
                    dict(task_id=a["task_id"], claim_id=a["claim_id"], task_fulfilled=True)
                    for a in payload["task_assignments"]
                ],
            )
        else:
            assert name == "dimension_answer_review"
            return append_response(service, record, kwargs, None)
        return append_response(service, record, kwargs, json.dumps(response))

    monkeypatch.setattr(service, "_trace_llm_text", model)
    await service._real_writer_step(record)
    receipt = json.loads(
        next(s.full_output for s in record.detail.trace_spans if s.name == "question_task_delivery")
    )
    tasks = receipt["tasks"]
    if failure in {
        "budget",
        "zero_attempts",
        "wrong_transport",
        "changed_input",
        "changed_system",
        "oversized",
    }:
        assert not generation_ids
        assert all(
            t["state"] == "deferred" and t["reason"] == "task_support_selection_unavailable"
            for t in tasks
        )
        assert receipt["support_selections"][0]["failures"] == [
            "task_support_selection_unavailable"
        ]
    else:
        assert tasks[0]["state"] == "supported"
        assert tasks[1]["state"] != "supported"
        if failure in {"missing", "duplicate", "foreign_ref"}:
            assert generation_ids == [[tasks[0]["task_id"]]]
            assert tasks[1]["reason"].startswith("task_support_selection_")
        else:
            assert generation_ids[-1] == [tasks[1]["task_id"]]
            assert len(generation_ids) == len(selection_calls) == 2
            if failure == "unselected_ref":
                assert tasks[1]["diagnostic"] == "task_selected_support_mismatch"
    assert all(call["max_output_tokens"] == 600 for call in selection_calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("binding_kind", ["operation", "span"])
async def test_real_authority_task_needs_its_selected_operation_identity(monkeypatch, binding_kind):
    quote = "Only admins can manage document permissions after verification and sign-in."
    question = "Example Product：谁有权管理文档权限？"
    detail, _ = research_case([quote], question=question)
    detail.created_at = detail.updated_at = datetime.now(UTC)
    detail.plan.competitors, detail.plan.dimensions = ["Example Product"], ["feature"]
    detail.plan.decision_brief = DecisionBrief(decision_question=question)
    for source in detail.raw_sources:
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
    seal_snapshot(detail, phase="analysis", canonical_documents={})
    service, record = service_for(detail, task_execution=True)
    sent_operation_ids = []

    async def model(record, **kwargs):
        name = kwargs["name"]
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        if name == "dimension_task_plan":
            response = dict(
                tasks=[
                    dict(
                        question_id=payload["questions"][0]["question_id"],
                        question_quote="谁有权管理文档权限？",
                        focus="source_rule",
                    )
                ]
            )
        elif name == "dimension_task_support_selection":
            row = payload["evidence_view"]["facts"][0]
            ref = (
                row["operation_support_refs"][0]
                if binding_kind == "operation"
                else row["source_span_candidates"][0]["support_ref"]
            )
            sent_operation_ids.append(row["operation_observations"][0]["observation_id"])
            response = dict(
                selections=[
                    selection_row(payload["tasks"][0]["task_id"], [ref], binding_kind=binding_kind)
                ]
            )
        elif name == "dimension_task_generation":
            task = payload["tasks"][0]
            selected = payload["task_support_selections"][0]
            if binding_kind == "operation":
                assert (
                    selected["supports"][0]["operation_binding"]["observation_id"]
                    == sent_operation_ids[-1]
                )
            response = dict(
                results=[
                    dict(
                        task_id=task["task_id"],
                        status="insufficient_evidence"
                        if payload.get("task_repair")
                        else "generated",
                        atom=None
                        if payload.get("task_repair")
                        else dict(text=quote, kind="fact", support_refs=selected["support_refs"]),
                    )
                ]
            )
        elif name == "dimension_task_review":
            assert binding_kind == "operation"
            assert (
                payload["claims"][0]["operation_binding"]["observation_id"]
                == sent_operation_ids[-1]
            )
            response = dict(
                reviews=[supported_review(c) for c in payload["claims"]],
                decisions=[
                    dict(task_id=a["task_id"], claim_id=a["claim_id"], task_fulfilled=True)
                    for a in payload["task_assignments"]
                ],
            )
        else:
            assert name == "dimension_answer_review"
            return append_response(service, record, kwargs, None)
        return append_response(service, record, kwargs, json.dumps(response))

    monkeypatch.setattr(service, "_trace_llm_text", model)
    await service._real_writer_step(record)
    receipt = json.loads(
        next(s.full_output for s in record.detail.trace_spans if s.name == "question_task_delivery")
    )
    task = receipt["tasks"][0]
    if binding_kind == "operation":
        assert task["state"] == "supported"
    else:
        assert task["state"] != "supported"
        assert "operation_binding_required" in task["diagnostic"]
