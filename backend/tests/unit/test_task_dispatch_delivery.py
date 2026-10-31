"""Retry diagnostics fit the real UTF-8 wire cap without changing selected evidence."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from test_task_clauses import clause_run


def user(payload):
    from packages.agents.writer.dimension_writer import compact_prompt_json

    return "\nJSON:\n" + compact_prompt_json(payload)


async def failed_history(monkeypatch):
    from packages.agents.writer.selected_task_delivery import failure_feedback

    case, result, _ = await clause_run(monkeypatch, fail_first=True)
    history = [
        (
            d,
            next(s for s in case[1].detail.trace_spans if s.id == d["span_id"]),
            result["compact"]["_decision_expected_inputs"][d["span_id"]][1],
        )
        for d in result["compact"]["dispatches"]
        if d.get("task_id") and d["attempt"] == 0
    ]
    d, span, payload = next(r for r in history if r[0]["name"].endswith("atomic_generation"))
    task = payload["generation_tasks"][0]
    feedback = failure_feedback(task, history, case[4].facts, case[5].id)
    return case, result, history, task, feedback


@pytest.mark.asyncio
async def test_only_optional_failed_raw_is_removed_when_actual_utf8_wire_exceeds_server_cap(
    monkeypatch,
):
    from packages.agents.writer.task_clauses import reused_generation

    case, _, history, task, feedback = await failed_history(monkeypatch)
    feedback = deepcopy(feedback)
    feedback["failed_generation"]["raw"] = "诊断" * 500
    full, _ = reused_generation(task, history, case[4].facts, case[5].id, case[2].id, feedback)
    minimal = deepcopy(full)
    minimal["repair_feedback"].pop("failed_generation")
    cap = max(len(user(minimal).encode()), len(user(full))) + 1
    assert cap < 14000 < case[5].max_bytes
    assert len(user(full)) < cap < len(user(full).encode())
    compact, _ = reused_generation(
        task, history, case[4].facts, case[5].id, case[2].id, feedback, max_bytes=cap
    )
    assert compact == minimal
    assert len(user(compact).encode()) <= cap
    assert {k: v for k, v in compact.items() if k != "repair_feedback"} == {
        k: v for k, v in full.items() if k != "repair_feedback"
    }
    assert feedback["failed_generation"]["raw"] == "诊断" * 500


@pytest.mark.asyncio
async def test_feedback_is_byte_identical_if_full_wire_already_fits(monkeypatch):
    from packages.agents.writer.task_clauses import reused_generation

    case, _, history, task, feedback = await failed_history(monkeypatch)
    full, _ = reused_generation(task, history, case[4].facts, case[5].id, case[2].id, feedback)
    same, _ = reused_generation(
        task,
        history,
        case[4].facts,
        case[5].id,
        case[2].id,
        feedback,
        max_bytes=len(user(full).encode()),
    )
    assert user(same) == user(full) and same["repair_feedback"] == feedback


@pytest.mark.asyncio
async def test_actual_oversized_repair_preflight_refuses_wire_before_budget_forecast(monkeypatch):
    from packages.agents.writer.selected_task_delivery import repair_admitted
    from packages.agents.writer.task_clauses import reused_generation

    case, _, history, task, feedback = await failed_history(monkeypatch)
    payload, _ = reused_generation(task, history, case[4].facts, case[5].id, case[2].id, feedback)
    limit = len(user(payload).encode()) - 1
    service, record = case[:2]
    calls = service._run_llm_budget(record).calls
    assert not repair_admitted(
        service,
        record,
        "Example Product/feature",
        payload,
        SimpleNamespace(max_bytes=limit),
        1,
        "task-outcomes-v1",
    )
    preflight = next(
        s for s in reversed(record.detail.trace_spans) if s.name == "question_task_repair_preflight"
    )
    result = json.loads(preflight.full_output)
    assert result["reason"] == "task_context_deferred"
    assert result["user_bytes"] == limit + 1 and result["max_user_bytes"] == limit
    assert service._run_llm_budget(record).calls == calls


async def dispatch_case(monkeypatch, cap, *, padding=0):
    from claim_review_fixture import expand_prompt_payload
    from test_question_atomic_delivery import atomic_case, supported_review
    from test_task_clauses import clause_wire_response
    from test_task_support_selection import append_response

    from packages.agents.writer.question_atomic_delivery import execute_question_atomic_delivery
    from packages.agents.writer.task_clauses import CONTRACT
    from packages.orchestrator import evidence_context

    case = await atomic_case(
        ["Guests have no personal area.", "Guests may access only one collection at a time."],
        question="Example Product：访客有私人区域吗？访客能同时加入两个容器吗？",
        source_qualifiers=[dict(background_note="完整来源上下文" + "x" * padding), {}],
    )
    service, record, snapshot, selected, _, _, packets, boundaries, allowed = case
    monkeypatch.setitem(evidence_context._DEPTH_BYTES, record.detail.plan.research_depth, cap // 4)
    view, use, packets = await service._begin_question_pool_evidence_use(record, packet=packets[0])
    assert use.max_bytes == cap
    assert {
        "Guests have no personal area.",
        "Guests may access only one collection at a time.",
    } <= {f.quote for f in view.facts}
    seen = []

    async def model(record, **kwargs):
        p = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        seen.append((kwargs["name"], p))
        if kwargs["name"].endswith("support_selection"):
            task = p["tasks"][0]
            term = "personal" if "私人" in task["question_quote"] else "collection"
            ref = next(
                s["support_ref"]
                for f in p["evidence_view"]["facts"]
                for s in f["source_span_candidates"]
                if term in s["quote"]
            )
            response = dict(
                selections=[
                    dict(
                        task_id=task["task_id"],
                        status="selected",
                        binding_kind="span",
                        support_refs=[ref],
                    )
                ]
            )
        elif kwargs["name"].endswith("atomic_generation"):
            task = p["current_task"]
            selection = p["selected_support"]
            if "私人" in task["question_quote"] and p["task_attempt"] == 0:
                return append_response(
                    service,
                    record,
                    kwargs,
                    json.dumps(dict(invalid_diagnostic="诊断" * 550), ensure_ascii=False),
                )
            response = dict(
                version=1,
                task_id=task["task_id"],
                status="generated",
                atom=dict(
                    text=selection["supports"][0]["quote"],
                    kind="fact",
                    support_refs=selection["support_refs"],
                ),
            )
        else:
            response = clause_wire_response(
                p,
                dict(
                    reviews=[supported_review(c) for c in p["claims"]],
                    atomicity=[
                        dict(claim_id=c["id"], predicate_count=1, clauses=[]) for c in p["claims"]
                    ],
                ),
            )
        return append_response(service, record, kwargs, json.dumps(response))

    monkeypatch.setattr(service, "_trace_llm_text", model)
    result = await execute_question_atomic_delivery(
        service,
        record,
        selected,
        view,
        use,
        packets[0]["questions"],
        packets,
        allowed,
        boundaries,
        (),
        task_execution_policy="selected-task-atoms-v3",
        task_clause_contract=CONTRACT,
        answer_review_contract="task-outcomes-v1",
    )
    return (
        (service, record, snapshot, selected, view, use, packets, boundaries, allowed),
        result,
        seen,
    )


@pytest.mark.asyncio
async def test_compacted_repair_really_dispatches_gen_review_and_replays_with_small_server_cap(
    monkeypatch,
):
    from packages.agents.writer.question_atomic_delivery import replay_atomic_delivery

    case, result, seen = await dispatch_case(monkeypatch, 8000)
    repairs = [
        p for name, p in seen if name.endswith("atomic_generation") and p["task_attempt"] == 1
    ]
    assert len(repairs) == 1 and "failed_generation" not in repairs[0]["repair_feedback"]
    assert len(result["reviews"]) == 2
    assert sum(name.endswith("support_selection") for name, _ in seen) == 2
    assert all(len(user(p).encode()) <= 8000 for _, p in seen)
    use = next(u for u in case[1].detail.evidence_consumptions if u.id == case[5].id)
    replayed = replay_atomic_delivery(case[0], case[1].detail, case[2], use, case[4])
    assert replayed["claims"] == result["claims"] and replayed["reviews"] == result["reviews"]


@pytest.mark.asyncio
async def test_still_oversized_repair_has_real_context_deferral_but_no_fake_dispatch(monkeypatch):
    from packages.agents.writer.question_atomic_delivery import replay_atomic_delivery

    case, result, seen = await dispatch_case(monkeypatch, 32768, padding=9500)
    assert "task_context_deferred" in result["gaps"]
    assert not any(
        p.get("task_attempt") == 1 for name, p in seen if name.endswith("atomic_generation")
    )
    refusals = [s for s in case[1].detail.trace_spans if s.name == "question_task_context_rejected"]
    assert refusals
    event = next(s for s in refusals if json.loads(s.full_input)["attempt"] == 1)
    outcome = json.loads(event.full_output)
    assert outcome["user_bytes"] > outcome["max_user_bytes"] == 14000
    row = next(
        r
        for p in result["compact"]["question_answer_plans"]
        for r in p["task_results"]
        if r["task_id"] == json.loads(event.full_input)["task_id"]
    )
    assert row["state"] == "deferred" and row["reason"] == "task_context_deferred"
    assert all(d["span_id"] != event.id for d in result["compact"]["dispatches"])
    use = next(u for u in case[1].detail.evidence_consumptions if u.id == case[5].id)
    replayed = replay_atomic_delivery(case[0], case[1].detail, case[2], use, case[4])
    assert replayed["claims"] == result["claims"]


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["optional_raw", "reason_codes"])
async def test_resigned_compacted_feedback_tampering_stays_rejected(monkeypatch, fault):
    from packages.agents.writer.question_atomic_delivery import digest, replay_atomic_delivery
    from packages.agents.writer.task_answer_outcomes import bind_transport, transport_identity
    from packages.research.question_delivery import _expand_text_refs

    case, _, _ = await dispatch_case(monkeypatch, 8000)
    record = case[1]
    receipt_span = next(
        s for s in record.detail.trace_spans if s.name == "question_atomic_delivery"
    )
    receipt = json.loads(receipt_span.full_output)
    dispatch = next(
        d
        for d in receipt["dispatches"]
        if d["name"].endswith("atomic_generation") and d["attempt"] == 1
    )
    span = next(s for s in record.detail.trace_spans if s.id == dispatch["span_id"])
    system, _, raw = span.full_input.partition("\nJSON:\n")
    system = system.rstrip("\n")
    payload = _expand_text_refs(json.loads(raw))
    if fault == "optional_raw":
        payload["repair_feedback"]["failed_generation"] = dict(raw="forged")
    else:
        payload["repair_feedback"]["reason_codes"] = ["foreign_reason"]
    proposal = user(payload)
    span.full_input = system + "\n\n" + proposal
    span.metadata["response_transport_identity"] = transport_identity(system, proposal)
    dispatch["full_input_sha256"] = digest(span.full_input)
    bind_transport(dispatch, span)
    receipt_span.full_output = json.dumps(receipt)
    use = next(u for u in record.detail.evidence_consumptions if u.id == case[5].id)
    with pytest.raises(ValueError):
        replay_atomic_delivery(case[0], record.detail, case[2], use, case[4])


@pytest.mark.asyncio
async def test_local_context_refusal_cannot_launder_its_size_proof(monkeypatch):
    from packages.agents.writer.question_atomic_delivery import replay_atomic_delivery

    case, result, _ = await dispatch_case(monkeypatch, 32768, padding=9500)
    assert len(result["reviews"]) == 1
    refusal = next(
        s
        for s in case[1].detail.trace_spans
        if s.name == "question_task_context_rejected" and json.loads(s.full_input)["attempt"] == 1
    )
    outcome = json.loads(refusal.full_output)
    outcome["user_bytes"] -= 1
    refusal.full_output = json.dumps(outcome)
    use = next(u for u in case[1].detail.evidence_consumptions if u.id == case[5].id)
    with pytest.raises(ValueError, match="deferral proof"):
        replay_atomic_delivery(case[0], case[1].detail, case[2], use, case[4])
