"""Task-local evidence windows and server instructions survive real dispatch and replay."""

import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from claim_review_fixture import expand_prompt_payload
from pydantic import HttpUrl, TypeAdapter
from test_question_retrieval import research_case
from test_task_context_handoff import handoff_case, offline_model
from test_task_support_selection import append_response, selection_row
from test_writer_question_delivery import service_for

from packages.agents.writer.task_execution import task_context, task_instruction
from packages.research.evidence.snapshot import seal_snapshot
from packages.schema.models import DecisionBrief


@pytest.mark.parametrize("stage", ["dimension_task_support_selection", "dimension_task_review"])
@pytest.mark.asyncio
async def test_server_task_instruction_reaches_actual_selector_writer_and_review(
    monkeypatch, stage
):
    service, record, parts, texts = handoff_case()
    seen = {}
    original = offline_model(service, record, parts, texts, seen)

    async def model(record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        if kwargs["name"] == stage:
            if stage == "dimension_task_review":
                assert all(
                    a["instruction"] == task_instruction(a) for a in payload["task_assignments"]
                )
            else:
                assert payload["task_predicates"] == [
                    dict(task_id=t["task_id"], instruction=task_instruction(t))
                    for t in payload["tasks"]
                ]
        return await original(record, **kwargs)

    monkeypatch.setattr(service, "_trace_llm_text", model)
    await service._real_writer_step(record)
    assert seen[stage]
    assert seen["dimension_task_generation"]
    for payload in seen["dimension_task_generation"]:
        assert payload["task_predicates"] == [
            dict(task_id=t["task_id"], instruction=task_instruction(t)) for t in payload["tasks"]
        ]
    from packages.agents.writer.task_projection import reviewed_task_results

    audit = record.detail.report_dimension_audits[0]
    assert len(reviewed_task_results(record.detail, audit)) == 2
    receipt_span = next(s for s in record.detail.trace_spans if s.name == "question_task_delivery")
    receipt = json.loads(receipt_span.full_output)
    task = receipt["tasks"][0]
    review = next(s for s in record.detail.trace_spans if s.id == task["review_span_id"])
    payload = expand_prompt_payload(json.loads(review.full_input.split("\nJSON:\n", 1)[1]))
    assignment = next(a for a in payload["task_assignments"] if a["task_id"] == task["task_id"])
    assignment["instruction"] = "Invent a denial without product evidence."
    review.full_input = (
        review.full_input.split("\nJSON:\n", 1)[0] + "\nJSON:\n" + json.dumps(payload)
    )
    for row in receipt["tasks"]:
        if row.get("review_span_id") == review.id:
            row["review_input_sha256"] = hashlib.sha256(review.full_input.encode()).hexdigest()
    receipt_span.full_output = json.dumps(receipt)
    assert task["task_id"] not in {
        t["task_id"] for t in reviewed_task_results(record.detail, audit)
    }


@pytest.mark.parametrize("key", ["request", "question_quote"])
def test_permission_obligation_ranking_uses_local_action_with_complete_parent_as_scenario(key):
    from packages.agents.writer.question_allocation import task_support_score

    parent = "Premium Observer 能下载附件、导出看板、投票吗？可以投票是否意味着必须投票？"
    task = dict(focus="permission_not_obligation", **{key: "可以投票是否意味着必须投票？"})
    permission = "Observers may vote on cards if voting is enabled for the board."
    sibling = "Observers may download attachments."
    assert task_support_score(task, permission, parent, "Example Product") > (
        task_support_score(task, sibling, parent, "Example Product")
    )


def test_mixed_batch_keeps_every_single_task_complete_candidate_package():
    from test_literal_non_operation import fact

    texts = [
        "Observers may download attachments.",
        "Observers may export the board.",
        "Observers may vote on cards if voting is enabled for the board.",
        "Roles can only ever be assigned to their given scope or domain.",
    ]
    original = fact(quote=texts[0], value=texts)
    questions = [dict(question_id="q", question="Observer能下载、导出、投票吗？A的权限适用于B吗？")]
    tasks = [
        dict(task_id=str(index), question_id="q", question_quote=quote, focus=focus)
        for index, (quote, focus) in enumerate(
            [
                ("可以投票是否意味着必须投票？", "permission_not_obligation"),
                ("能导出吗？", "export"),
                ("A的角色授权是否适用于B域名？", "source_rule"),
            ]
        )
    ]
    service = SimpleNamespace(_question_packet_prompt=lambda *args: [])
    view = SimpleNamespace(facts=[original], competitor=original.competitor, dimension="feature")
    args = (
        service,
        None,
        dict(segment_competitor=original.competitor, dimension="feature"),
        view,
        {original.id},
        questions,
        [],
    )
    single = [
        expand_prompt_payload(task_context(*args, [task], SimpleNamespace(max_bytes=14000)))
        for task in tasks
    ]
    batch = expand_prompt_payload(task_context(*args, tasks, SimpleNamespace(max_bytes=14000)))
    sent = {
        (row["id"], span["quote"])
        for row in batch["evidence_view"]["facts"]
        for span in row.get("source_span_candidates", [])
    }
    for context in single:
        expected = {
            (row["id"], span["quote"])
            for row in context["evidence_view"]["facts"]
            for span in row.get("source_span_candidates", [])
        }
        assert expected <= sent


@pytest.mark.parametrize("large", [False, True])
@pytest.mark.asyncio
async def test_actual_dispatch_splits_only_conflicting_complete_candidate_packages(
    monkeypatch, large
):
    parts = ["能下载附件吗？", "能导出看板吗？", "能投票吗？"]
    focuses = ["download", "export", "vote"]
    texts = []
    expected = {}
    for index, action in enumerate(focuses):
        quotes = [
            f"Observers may {action} on the board if the administrator enables setting {n}."
            + (f" Complete prerequisite {index}-{n}." * 30 if large else "")
            for n in range(2)
        ]
        expected[action] = quotes
        texts.extend(quotes)
    parent = "Example Product：Premium Workspace 中为Observer。" + "".join(parts)
    detail, _ = research_case(texts, question=parent)
    detail.created_at = detail.updated_at = datetime.now(UTC)
    detail.plan.competitors, detail.plan.dimensions = ["Example Product"], ["feature"]
    detail.plan.decision_brief = DecisionBrief(decision_question=parent)
    for source in detail.raw_sources:
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
    seal_snapshot(detail, phase="analysis", canonical_documents={})
    service, record = service_for(detail, task_execution=True)
    seen = []

    async def model(record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        name = kwargs["name"]
        if name == "dimension_task_plan":
            response = dict(
                tasks=[
                    dict(
                        question_id=next(
                            q["question_id"] for q in payload["questions"] if part in q["question"]
                        ),
                        question_quote=part,
                        focus=focus,
                    )
                    for part, focus in zip(parts, focuses, strict=True)
                ]
            )
        elif name == "dimension_task_support_selection":
            seen.append(payload)
            spans = [
                s
                for row in payload["evidence_view"]["facts"]
                for s in row.get("source_span_candidates", [])
            ]
            rows = []
            for task in payload["tasks"]:
                assert set(expected[task["focus"]]) <= {s["quote"] for s in spans}
                ref = next(
                    s["support_ref"] for s in spans if s["quote"] == expected[task["focus"]][0]
                )
                rows.append(selection_row(task["task_id"], [ref]))
            response = dict(selections=rows)
        elif name == "dimension_task_generation":
            response = dict(
                results=[
                    dict(task_id=t["task_id"], status="insufficient_evidence", atom=None)
                    for t in payload["tasks"]
                ]
            )
        else:
            assert name == "dimension_answer_review"
            return append_response(service, record, kwargs, None)
        return append_response(service, record, kwargs, json.dumps(response))

    monkeypatch.setattr(service, "_trace_llm_text", model)
    await service._real_writer_step(record)
    assert len(seen) > 1 if large else len(seen) == 1
    assert {t["focus"] for payload in seen for t in payload["tasks"]} == set(focuses)
    assert all(len(payload["tasks"]) <= 3 for payload in seen)
    assert all(payload["request_context"]["parents"][0]["text"] == parent for payload in seen)


def test_legacy_review_replays_original_assignment_without_new_instruction():
    from test_task_projection import projected_case

    from packages.agents.writer.task_projection import reviewed_task_results

    record, audit, _, _ = projected_case()
    original = record.detail.model_dump_json()
    assert reviewed_task_results(record.detail, audit)
    assert record.detail.model_dump_json() == original


def test_shared_operation_fact_keeps_literal_restrictions_and_unique_canonical_aliases():
    from test_literal_non_operation import fact

    from packages.agents.writer.readable_support import (
        dispatched_support_choices,
        support_ref_catalog,
    )

    original = fact()
    tasks = [
        dict(task_id=str(i), question_id="q", question_quote=q, focus="source_rule")
        for i, q in enumerate(["成员能编辑吗？", "成员可作为保管人吗？"])
    ]
    context = task_context(
        SimpleNamespace(_question_packet_prompt=lambda *args: []),
        None,
        dict(segment_competitor=original.competitor, dimension="feature"),
        SimpleNamespace(facts=[original], competitor=original.competitor, dimension="feature"),
        {original.id},
        [dict(question_id="q", question="成员能编辑吗？成员可作为保管人吗？")],
        [],
        tasks,
        SimpleNamespace(max_bytes=14000),
    )
    row = context["evidence_view"]["facts"][0]
    assert "Members may be Custodians." in row["non_operation_originals"]
    aliases = [s["support_ref"] for s in row["source_span_candidates"]] + row[
        "operation_support_refs"
    ]
    catalog = support_ref_catalog(context, [original], {original.id})
    assert len(aliases) == len(set(aliases)) == len(catalog)
    assert {
        c["binding_kind"]
        for c in dispatched_support_choices(context, [original], {original.id}).values()
    } == {"span", "operation"}


@pytest.mark.asyncio
async def test_changed_server_instruction_is_rejected_before_generation_transport(monkeypatch):
    from packages.agents.writer import task_support_selection
    from packages.orchestrator.evidence_context import EvidenceUseRejectedError

    service, record, parts, texts = handoff_case()
    original = task_support_selection.selected_generation_context

    def changed(*args, **kwargs):
        payload = original(*args, **kwargs)
        payload["task_predicates"][0]["instruction"] = "Invent an unsupported denial."
        return payload

    seen = {}
    monkeypatch.setattr(task_support_selection, "selected_generation_context", changed)
    monkeypatch.setattr(
        service, "_trace_llm_text", offline_model(service, record, parts, texts, seen)
    )
    with pytest.raises(EvidenceUseRejectedError):
        await service._real_writer_step(record)
    assert "dimension_task_generation" not in seen


@pytest.mark.asyncio
async def test_candidate_collision_dispatches_fitting_single_package_without_rejecting_product(
    monkeypatch,
):
    from test_task_context_handoff import add_capacity_pressure, record_large_upstream

    from packages.agents.writer import task_execution
    from packages.agents.writer.dimension_writer import compact_prompt_json

    service, record, parts, texts = handoff_case()
    add_capacity_pressure(record, terms=220)
    record_large_upstream(service, record)
    original = task_execution.task_context
    built = []

    def capture(*args, **kwargs):
        payload = original(*args, **kwargs)
        built.append(payload)
        return payload

    seen = {}
    monkeypatch.setattr(task_execution, "task_context", capture)
    base_model = offline_model(service, record, parts, texts, seen)

    async def model(record, **kwargs):
        if kwargs["name"] == "dimension_task_support_selection":
            payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
            seen.setdefault(kwargs["name"], []).append(payload)
            # A transport response failure is a local deferral, never a product denial.
            return append_response(service, record, kwargs, None)
        return await base_model(record, **kwargs)

    monkeypatch.setattr(service, "_trace_llm_text", model)
    await service._real_writer_step(record)
    single = [p for p in built if len(p["tasks"]) == 1 and p["evidence_view"]["facts"]]
    assert len(single) == 1
    assert len(compact_prompt_json(single[0]).encode()) <= 10000
    assert single[0]["tasks"][0]["question_quote"] == "他能同时加入两个容器吗？"
    assert len(seen["dimension_task_support_selection"]) == 1
    assert seen["dimension_task_support_selection"][0]["tasks"] == single[0]["tasks"]
    assert any(
        "Canonical retained background. " * 220 in value
        for row in single[0]["evidence_view"]["facts"]
        for value in row["value"]
    )
    expected_quotes = {
        span["quote"]
        for row in single[0]["evidence_view"]["facts"]
        for span in row["source_span_candidates"]
    }
    assert expected_quotes == {
        span["quote"]
        for row in seen["dimension_task_support_selection"][0]["evidence_view"]["facts"]
        for span in row["source_span_candidates"]
    }
    assert any(
        span.name == "dimension_task_support_selection"
        and span.metadata.get("llm_transport_attempts") == 1
        for span in record.detail.trace_spans
    )
    receipt = json.loads(
        next(s.full_output for s in record.detail.trace_spans if s.name == "question_task_delivery")
    )
    assert not any(t["state"] == "insufficient_evidence" for t in receipt["tasks"])


def test_exception_closure_larger_than_fact_row_cap_defers_the_entire_candidate_package(
    monkeypatch,
):
    from test_literal_non_operation import fact

    from packages.research.evidence import source_exceptions

    originals = [
        fact(fact_id=str(i), quote=f"Members may download attachment {i}.") for i in range(10)
    ]
    pairs = [dict(id=f"pair-{i}", fact_ids=[str(i), str(i + 1)]) for i in range(9)]
    monkeypatch.setattr(source_exceptions, "source_exception_bindings", lambda facts: pairs)
    task = dict(task_id="task", question_id="q", question_quote="能下载附件吗？", focus="download")
    context = task_context(
        SimpleNamespace(_question_packet_prompt=lambda *args: []),
        None,
        dict(segment_competitor="Example Product", dimension="feature"),
        SimpleNamespace(facts=originals, competitor="Example Product", dimension="feature"),
        {f.id for f in originals},
        [dict(question_id="q", question="能下载附件吗？")],
        [],
        [task],
        SimpleNamespace(max_bytes=14000),
    )
    assert context.get("candidate_context_budget_exceeded") is True
    assert context["evidence_view"]["facts"] == []


@pytest.mark.parametrize(
    "question_text,focus,quote,text,kind,conclusion,relation",
    [
        (
            "允许投票是否意味着必须投票？",
            "permission_not_obligation",
            "An Observer can vote on cards if voting is enabled for the board.",
            "题设的 Observer 在该看板允许投票，不意味着他必须投票。",
            "inference",
            "no",
            "permission_entailment",
        ),
        (
            "A 上这次改权是否自动决定他在 B 的权限？",
            "source_rule",
            "An observer is set individually per member per board.",
            "Observer 按成员逐看板设置，因此题设 A 的设置不推出 B 的设置。",
            "inference",
            "no",
            "direct",
        ),
        (
            "只凭 Observer 标签能否确定一定免费或一定计费？",
            "billing_inputs",
            "Whether a guest is billable depends on Workspace membership "
            "and the number of boards joined.",
            "Guest billing depends on Workspace membership and the number of boards joined.",
            "fact",
            "depends",
            "direct",
        ),
    ],
)
@pytest.mark.asyncio
async def test_reasonable_conditionals_bind_selected_canonical_support_through_task_qa(
    monkeypatch,
    question_text,
    focus,
    quote,
    text,
    kind,
    conclusion,
    relation,
):
    from claim_review_fixture import supported_review

    from packages.agents.writer.task_projection import reviewed_task_results

    parent = (
        "Example Product：假设 Workspace 已订阅 Premium，该成员在 A 上为 Observer。" + question_text
    )
    detail, _ = research_case([quote], question=parent)
    detail.created_at = detail.updated_at = datetime.now(UTC)
    detail.plan.competitors, detail.plan.dimensions = ["Example Product"], ["feature"]
    detail.plan.decision_brief = DecisionBrief(decision_question=parent)
    for source in detail.raw_sources:
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
    seal_snapshot(detail, phase="analysis", canonical_documents={})
    service, record = service_for(detail, task_execution=True)
    seen = {}

    async def model(record, **kwargs):
        name = kwargs["name"]
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        seen[name] = payload
        if name == "dimension_task_plan":
            response = dict(
                tasks=[
                    dict(
                        question_id=payload["questions"][0]["question_id"],
                        question_quote=question_text,
                        focus=focus,
                    )
                ]
            )
        elif name == "dimension_task_support_selection":
            assert payload["request_context"]["parents"][0]["text"] == parent
            assert payload["task_predicates"] == [
                dict(task_id=t["task_id"], instruction=task_instruction(t))
                for t in payload["tasks"]
            ]
            span = next(
                s
                for row in payload["evidence_view"]["facts"]
                for s in row["source_span_candidates"]
                if s["quote"] == quote
            )
            response = dict(
                selections=[
                    selection_row(t["task_id"], [span["support_ref"]]) for t in payload["tasks"]
                ]
            )
        elif name == "dimension_task_generation":
            response = dict(
                results=[
                    dict(
                        task_id=t["task_id"],
                        status="generated",
                        atom=dict(text=text, kind=kind, support_refs=selection["support_refs"]),
                    )
                    for t, selection in zip(
                        payload["tasks"], payload["task_support_selections"], strict=True
                    )
                ]
            )
        elif name == "dimension_task_review":
            assert all(a["instruction"] == task_instruction(a) for a in payload["task_assignments"])
            response = dict(
                reviews=[supported_review(c) for c in payload["claims"]],
                decisions=[
                    dict(
                        task_id=a["task_id"],
                        claim_id=a["claim_id"],
                        task_fulfilled=True,
                        conclusion=conclusion,
                        relation=relation,
                    )
                    for a in payload["task_assignments"]
                ],
            )
        else:
            assert name == "dimension_answer_review"
            return append_response(service, record, kwargs, None)
        return append_response(service, record, kwargs, json.dumps(response))

    monkeypatch.setattr(service, "_trace_llm_text", model)
    await service._real_writer_step(record)
    rows = reviewed_task_results(record.detail, record.detail.report_dimension_audits[0])
    receipts = [s for s in record.detail.trace_spans if s.name == "question_task_delivery"]
    assert receipts, json.dumps(
        dict(
            seen=list(seen),
            traces=[(s.name, s.full_output[:1200]) for s in record.detail.trace_spans],
        ),
        ensure_ascii=False,
    )
    receipt = json.loads(receipts[0].full_output)
    assert rows and all(row["decision"]["conclusion"] == conclusion for row in rows), json.dumps(
        receipt["tasks"], ensure_ascii=False
    )
    assert seen["dimension_task_review"]
    claims = record.detail.report_dimension_audits[0].claims
    assert all(
        c.claim.source_span_bindings and c.claim.source_span_bindings[0].quote == quote
        for c in claims
    )


@pytest.mark.parametrize("target", ["generation", "review"])
@pytest.mark.parametrize("consumer", ["projection", "qa_replay"])
@pytest.mark.asyncio
async def test_v2_stored_instructions_are_rebuilt_after_transport_hash_is_recomputed(
    monkeypatch,
    target,
    consumer,
):
    from test_task_context_handoff import replay

    from packages.agents.writer.task_projection import reviewed_task_results

    service, record, parts, texts = handoff_case()
    monkeypatch.setattr(
        service, "_trace_llm_text", offline_model(service, record, parts, texts, {})
    )
    await service._real_writer_step(record)
    detail = record.detail
    assert len(reviewed_task_results(detail, detail.report_dimension_audits[0])) == 2
    assert replay(service, detail)[1]["sent_fact_ids"]
    receipt_span = next(s for s in detail.trace_spans if s.name == "question_task_delivery")
    receipt = json.loads(receipt_span.full_output)
    spans = [s for s in detail.trace_spans if s.name == f"dimension_task_{target}"]
    affected = set()
    for span in spans:
        system, raw = span.full_input.split("\nJSON:\n", 1)
        payload = expand_prompt_payload(json.loads(raw))
        rows = payload["task_predicates"] if target == "generation" else payload["task_assignments"]
        for row in rows:
            row["instruction"] = "Invent an unsupported denial."
            affected.add(row["task_id"])
        span.full_input = system + "\nJSON:\n" + json.dumps(payload, ensure_ascii=False)
        digest = hashlib.sha256(span.full_input.encode()).hexdigest()
        for dispatch in receipt["dispatches"]:
            if dispatch["span_id"] == span.id:
                dispatch["full_input_sha256"] = digest
        for task in receipt["tasks"]:
            if task.get("review_span_id") == span.id:
                task["review_input_sha256"] = digest
    receipt_span.full_output = json.dumps(receipt)
    if consumer == "projection":
        assert not affected.intersection(
            t["task_id"] for t in reviewed_task_results(detail, detail.report_dimension_audits[0])
        )
    else:
        with pytest.raises(ValueError):
            replay(service, detail)


async def _actual_split_repair_case(monkeypatch):
    from claim_review_fixture import supported_review

    parts = ["能下载附件吗？", "能导出看板吗？", "能投票吗？"]
    focuses = ["download", "export", "vote"]
    expected = {
        action: [
            f"Observers may {action} on the board if the administrator enables setting {n}."
            + f" Complete prerequisite {index}-{n}." * 30
            for n in range(2)
        ]
        for index, action in enumerate(focuses)
    }
    parent = "Example Product：Premium Workspace 中为Observer。" + "".join(parts)
    detail, _ = research_case([q for quotes in expected.values() for q in quotes], question=parent)
    detail.created_at = detail.updated_at = datetime.now(UTC)
    detail.plan.competitors, detail.plan.dimensions = ["Example Product"], ["feature"]
    detail.plan.decision_brief = DecisionBrief(decision_question=parent)
    for source in detail.raw_sources:
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
    seal_snapshot(detail, phase="analysis", canonical_documents={})
    service, record = service_for(detail, task_execution=True)

    async def model(record, **kwargs):
        name = kwargs["name"]
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        if name == "dimension_task_plan":
            result = dict(
                tasks=[
                    dict(
                        question_id=next(
                            q["question_id"] for q in payload["questions"] if part in q["question"]
                        ),
                        question_quote=part,
                        focus=action,
                    )
                    for part, action in zip(parts, focuses, strict=True)
                ]
            )
        elif name == "dimension_task_support_selection":
            spans = [
                s
                for row in payload["evidence_view"]["facts"]
                for s in row.get("source_span_candidates", [])
            ]
            result = dict(
                selections=[
                    selection_row(
                        t["task_id"],
                        [
                            next(
                                s["support_ref"]
                                for s in spans
                                if s["quote"] == expected[t["focus"]][0]
                            )
                        ],
                    )
                    for t in payload["tasks"]
                ]
            )
        elif name == "dimension_task_generation":
            selections = {s["task_id"]: s for s in payload["task_support_selections"]}
            result = dict(
                results=[
                    dict(
                        task_id=t["task_id"],
                        status="generated",
                        atom=dict(
                            text=expected[t["focus"]][0],
                            kind="fact",
                            support_refs=selections[t["task_id"]]["support_refs"],
                        ),
                    )
                    for t in payload["tasks"]
                ]
            )
        elif name == "dimension_task_review":
            result = dict(
                reviews=[supported_review(c) for c in payload["claims"]],
                decisions=[
                    dict(
                        task_id=a["task_id"],
                        claim_id=a["claim_id"],
                        task_fulfilled=False,
                        conclusion="unknown",
                        relation="unresolved",
                    )
                    for a in payload["task_assignments"]
                ],
            )
        else:
            assert name == "dimension_answer_review"
            return append_response(service, record, kwargs, None)
        return append_response(service, record, kwargs, json.dumps(result))

    monkeypatch.setattr(service, "_trace_llm_text", model)
    await service._real_writer_step(record)
    receipt_span = next(s for s in detail.trace_spans if s.name == "question_task_delivery")
    receipt = json.loads(receipt_span.full_output)
    assert [d["attempt"] for d in receipt["dispatches"]] == [0, 0, 0, 1, 1]
    return service, record, receipt_span, receipt


@pytest.mark.parametrize(
    "mutation",
    [
        None,
        "duplicate_repair",
        "third_repair_task",
        "initial_after_repair",
        "extra_round",
        "foreign_task",
        "legacy_split_repair",
    ],
)
@pytest.mark.asyncio
async def test_one_v2_repair_round_replays_split_batches_with_two_unique_tasks_maximum(
    monkeypatch,
    mutation,
):
    from copy import deepcopy

    from test_task_context_handoff import replay

    from packages.agents.writer.task_execution import TASK_INSTRUCTION_SYSTEM_IDENTITY

    service, record, receipt_span, receipt = await _actual_split_repair_case(monkeypatch)
    detail = record.detail
    if mutation in {"duplicate_repair", "third_repair_task"}:
        original = receipt["dispatches"][3 if mutation == "duplicate_repair" else 2]
        original_span = next(s for s in detail.trace_spans if s.id == original["span_id"])
        duplicate = original_span.model_copy(deep=True, update={"id": "extra-repair-dispatch"})
        payload = expand_prompt_payload(json.loads(duplicate.full_input.split("\nJSON:\n", 1)[1]))
        payload["task_repair"] = [
            dict(task_id=t["task_id"], diagnostic="binding rejected") for t in payload["tasks"]
        ]
        duplicate.full_input = (
            duplicate.full_input.split("\nJSON:\n", 1)[0] + "\nJSON:\n" + json.dumps(payload)
        )
        detail.trace_spans.append(duplicate)
        receipt["dispatches"].append(
            dict(
                deepcopy(original),
                span_id=duplicate.id,
                attempt=1,
                full_input_sha256=hashlib.sha256(duplicate.full_input.encode()).hexdigest(),
            )
        )
    elif mutation == "initial_after_repair":
        receipt["dispatches"].insert(3, receipt["dispatches"].pop(2))
    elif mutation == "extra_round":
        receipt["dispatches"][-1]["attempt"] = 2
    elif mutation == "foreign_task":
        receipt["dispatches"][-1]["task_ids"] = ["foreign-task"]
    elif mutation == "legacy_split_repair":
        for dispatch in receipt["dispatches"]:
            span = next(s for s in detail.trace_spans if s.id == dispatch["span_id"])
            span.full_input = span.full_input.replace(TASK_INSTRUCTION_SYSTEM_IDENTITY, "")
            dispatch["full_input_sha256"] = hashlib.sha256(span.full_input.encode()).hexdigest()
    receipt_span.full_output = json.dumps(receipt)
    if mutation:
        with pytest.raises(ValueError):
            replay(service, detail)
    else:
        assert replay(service, detail)[1]["sent_fact_ids"]


@pytest.mark.asyncio
async def test_consistent_generation_focus_and_instruction_tampering_cannot_change_canonical_task(
    monkeypatch,
):
    from packages.agents.writer.task_projection import reviewed_task_results

    service, record, parts, texts = handoff_case()
    monkeypatch.setattr(
        service, "_trace_llm_text", offline_model(service, record, parts, texts, {})
    )
    await service._real_writer_step(record)
    detail = record.detail
    audit = detail.report_dimension_audits[0]
    original_ids = {row["task_id"] for row in reviewed_task_results(detail, audit)}
    assert len(original_ids) == 2
    receipt_span = next(s for s in detail.trace_spans if s.name == "question_task_delivery")
    receipt = json.loads(receipt_span.full_output)
    dispatch = receipt["dispatches"][0]
    generation = next(s for s in detail.trace_spans if s.id == dispatch["span_id"])
    system, raw = generation.full_input.split("\nJSON:\n", 1)
    payload = expand_prompt_payload(json.loads(raw))
    changed = payload["tasks"][0]
    changed["focus"] = "billing_inputs"
    predicate = next(
        row for row in payload["task_predicates"] if row["task_id"] == changed["task_id"]
    )
    predicate["instruction"] = task_instruction(changed)
    generation.full_input = system + "\nJSON:\n" + json.dumps(payload, ensure_ascii=False)
    dispatch["full_input_sha256"] = hashlib.sha256(generation.full_input.encode()).hexdigest()
    receipt_span.full_output = json.dumps(receipt)
    projected_ids = {row["task_id"] for row in reviewed_task_results(detail, audit)}
    assert changed["task_id"] not in projected_ids
    assert projected_ids == original_ids - {changed["task_id"]}
