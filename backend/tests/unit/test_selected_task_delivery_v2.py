"""Second policy keeps old transcripts intact while fixing mechanical delivery failures."""

import json
from copy import deepcopy

import pytest
from test_question_atomic_delivery import atomic_case
from test_selected_task_delivery import run_tasks
from test_writer_question_delivery import billing_original

V2 = "selected-task-atoms-v2"


@pytest.mark.asyncio
async def test_v2_failed_task_repair_carries_bound_actual_parser_feedback(monkeypatch):
    from packages.agents.writer.question_atomic_delivery import digest, replay_atomic_delivery

    _, first, _ = await run_tasks(monkeypatch)
    tid = first["compact"]["question_answer_plans"][0]["task_results"][0]["task_id"]
    case, result, seen = await run_tasks(monkeypatch, bad_task=tid, execution_policy=V2)
    repairs = [p for name, p in seen if p.get("task_attempt") == 1]
    assert len(repairs) == 2
    feedback = repairs[0]["repair_feedback"]
    assert repairs[1]["repair_feedback"] == feedback
    assert feedback["task_id"] == tid and feedback["prior_attempt"] == 0
    assert feedback["question_id"] == repairs[0]["questions"][0]["question_id"]
    assert "task_atomic_claim_count_invalid" in feedback["reason_codes"]
    prior = feedback["prior_transports"]
    spans = {s.id: s for s in case[1].detail.trace_spans}
    assert len(prior) == 2
    assert all(digest(spans[t["span_id"]].full_output) == t["full_output_sha256"] for t in prior)
    assert all(len(json.dumps(p, ensure_ascii=False).encode()) <= 14000 for p in repairs)
    assert len(result["claims"]) == len(result["reviews"]) == 1
    assert all("repair_feedback" not in p for _, p in seen if p.get("task_attempt") == 0)
    use = next(u for u in case[1].detail.evidence_consumptions if u.id == case[5].id)
    replayed = replay_atomic_delivery(case[0], case[1].detail, case[2], use, case[4])
    assert replayed["claims"] == result["claims"]


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["missing", "code", "task", "prior_transport"])
@pytest.mark.parametrize("stage", ["selection", "generation"])
async def test_v2_rebuild_rejects_repair_feedback_tampering_even_with_rehashed_wire(
    monkeypatch, fault, stage
):
    from types import SimpleNamespace

    from packages.agents.writer.dimension_writer import compact_prompt_json
    from packages.agents.writer.question_atomic_delivery import digest
    from packages.agents.writer.selected_task_delivery import rebuild

    _, first, _ = await run_tasks(monkeypatch)
    tid = first["compact"]["question_answer_plans"][0]["task_results"][0]["task_id"]
    case, result, _ = await run_tasks(monkeypatch, bad_task=tid, execution_policy=V2)
    compact = deepcopy(result["compact"])
    dispatch = next(
        d for d in compact["dispatches"]
        if d["attempt"] == 1 and d["name"].endswith(
            "support_selection" if stage == "selection" else "atomic_generation"
        )
    )
    system, payload = compact["_decision_expected_inputs"][dispatch["span_id"]]
    if fault == "missing":
        payload.pop("repair_feedback", None)
    elif fault == "code":
        payload["repair_feedback"]["reason_codes"] = ["foreign_reason"]
    elif fault == "task":
        payload["repair_feedback"]["task_id"] = "foreign_task"
    else:
        payload["repair_feedback"]["prior_transports"][0]["full_output_sha256"] = "foreign_hash"
    spans = deepcopy(case[1].detail.trace_spans)
    span = next(s for s in spans if s.id == dispatch["span_id"])
    span.full_input = system + "\n\n\nJSON:\n" + compact_prompt_json(payload)
    dispatch["full_input_sha256"] = digest(span.full_input)
    context = SimpleNamespace(
        compact=compact,
        expected_inputs=compact["_decision_expected_inputs"],
        trace_spans=spans,
        facts=case[4].facts,
        questions=case[6][0]["questions"],
        consumption_id=case[5].id,
        snapshot_id=case[2].id,
        competitor=case[4].competitor,
        dimension=case[4].dimension,
        audited_claims=(),
    )
    with pytest.raises(ValueError, match="feedback"):
        rebuild(context)


@pytest.mark.asyncio
async def test_v2_repair_feedback_uses_bounded_actual_review_reason(monkeypatch):
    from packages.agents.writer.question_atomic_delivery import replay_atomic_delivery

    _, first, _ = await run_tasks(monkeypatch)
    tid = first["compact"]["question_answer_plans"][0]["task_results"][0]["task_id"]
    case, result, seen = await run_tasks(monkeypatch, unsupported_task=tid, execution_policy=V2)
    feedback = next(p["repair_feedback"] for _, p in seen if p.get("task_attempt") == 1)
    assert feedback["review"] == dict(
        verdict="unsupported", reason=("Actual source condition omitted. " * 15)[:240],
        reason_truncated=True,
    )
    assert "claim_review_unsupported" in feedback["reason_codes"]
    assert len(feedback["prior_transports"]) == 3
    use = next(u for u in case[1].detail.evidence_consumptions if u.id == case[5].id)
    replayed = replay_atomic_delivery(case[0], case[1].detail, case[2], use, case[4])
    assert replayed["reviews"] == result["reviews"]


@pytest.mark.asyncio
async def test_v2_model_can_repair_only_failed_task_using_actual_feedback(monkeypatch):
    from packages.agents.writer.question_atomic_delivery import replay_atomic_delivery

    _, first, _ = await run_tasks(monkeypatch)
    tid = first["compact"]["question_answer_plans"][0]["task_results"][0]["task_id"]
    case, result, seen = await run_tasks(
        monkeypatch, bad_task=tid, repair_with_feedback=True, execution_policy=V2
    )
    generations = [p for name, p in seen if name == "dimension_question_atomic_generation"]
    assert [p["task_attempt"] for p in generations] == [0, 0, 1]
    assert generations[-1]["generation_tasks"][0]["task_id"] == tid
    assert len(result["claims"]) == len(result["reviews"]) == 2
    assert result["claims"][0].text == first["claims"][1].text
    use = next(u for u in case[1].detail.evidence_consumptions if u.id == case[5].id)
    replayed = replay_atomic_delivery(case[0], case[1].detail, case[2], use, case[4])
    assert replayed["claims"] == result["claims"]


@pytest.mark.asyncio
async def test_v2_last_successful_repair_protects_complete_real_answer_envelope(monkeypatch):
    from test_selected_task_delivery import reviewed_scenario

    case, result, audit, seen, _ = await reviewed_scenario(
        monkeypatch, execution_policy=V2, repair=True
    )
    generations = [p for name, p in seen if name == "dimension_question_atomic_generation"]
    assert [p["task_attempt"] for p in generations] == [0, 0, 1]
    assert sum(row.status == "supported" for row in audit.claims) == 2
    answer = next(
        s for s in case[1].detail.trace_spans if s.name == "dimension_question_atomic_answer_review"
    )
    system, _, raw = answer.full_input.partition("\nJSON:\n")
    _, prompt, output = case[0]._llm_request_envelope(
        system=system.rstrip("\n"), user="\nJSON:\n" + raw, max_output_tokens=1600
    )
    assert case[1].llm_budget.delivery_reserves["answer:Example Product/feature"] >= prompt + output
    assert audit.answer_coverage[0].status == "answered"


@pytest.mark.asyncio
async def test_v2_optional_repair_defers_before_spending_peer_answer_and_qa_tail(monkeypatch):
    from test_selected_task_delivery import reviewed_scenario

    case, result, audit, seen, _ = await reviewed_scenario(
        monkeypatch, execution_policy=V2, repair=True, tight_budget=True
    )
    assert not any(p.get("task_attempt") == 1 for _, p in seen)
    assert sum(row.status == "supported" for row in audit.claims) == 1
    assert any(name == "dimension_question_atomic_answer_review" for name, _ in seen)
    assert "task_repair_budget_deferred" in result["gaps"]
    service, record = case[:2]
    answer = next(
        s for s in record.detail.trace_spans if s.name == "dimension_question_atomic_answer_review"
    )
    system, _, raw = answer.full_input.partition("\nJSON:\n")
    _, prompt, output = service._llm_request_envelope(
        system=system.rstrip("\n"), user="\nJSON:\n" + raw, max_output_tokens=1600
    )
    async def offline_text(**kwargs):
        return '{"gate_status":"keep"}'

    monkeypatch.setattr(service._llm, "complete_text", offline_text)
    for name, agent, subagent, actual_system, actual_user in [
        ("dimension_question_atomic_answer_review", "qa", "Example Product/feature",
         system.rstrip("\n"), "\nJSON:\n" + raw),
        ("final_report_qa", "qa", None, "Independent final QA", "Review published record."),
    ]:
        assert await service._trace_budgeted_llm(
            record, agent=agent, subagent=subagent, name=name,
            system=actual_system, user=actual_user, schema_hint=None, context=None,
            is_repair=False, timeout_seconds=None, max_output_tokens=1600,
        )
        if subagent:
            record.llm_budget.finish_delivery("answer:Example Product/feature")
    assert record.llm_budget.calls == 2
    assert any(s.name == "final_report_qa" and s.status == "ok" for s in record.detail.trace_spans)


@pytest.mark.asyncio
async def test_v2_keeps_generation_result_when_repair_generation_is_budget_deferred(monkeypatch):
    from packages.agents.writer.question_atomic_delivery import replay_atomic_delivery

    _, initial, _ = await run_tasks(monkeypatch)
    tid = initial["compact"]["question_answer_plans"][0]["task_results"][0]["task_id"]
    case, result, seen = await run_tasks(
        monkeypatch, bad_task=tid, execution_policy=V2, deny_repair_generation=True
    )
    assert len(result["claims"]) == len(result["reviews"]) == 1
    failed = next(
        r
        for p in result["compact"]["question_answer_plans"]
        for r in p["task_results"]
        if r["task_id"] == tid
    )
    assert failed["state"] == "rejected"
    use = next(u for u in case[1].detail.evidence_consumptions if u.id == case[5].id)
    assert (
        replay_atomic_delivery(case[0], case[1].detail, case[2], use, case[4])["claims"]
        == result["claims"]
    )


@pytest.mark.asyncio
async def test_v2_uses_actual_selection_wire_and_keeps_full_cpu_parent_applicability():
    from packages.agents.writer.atomic_question_projection import generation_tasks
    from packages.agents.writer.selected_task_delivery import candidate_context, selection_context

    quote, conditions, table = billing_original()
    # This fixture has no numbered footnote marker; retain the valid header
    # rather than presenting its legacy free-text note as parsed table context.
    table = table[:1]
    case = await atomic_case(
        [quote],
        question="Example Product Compute Paid Standard 本月有2300万次请求，账单准确是多少美元？",
        source_qualifiers=[dict(condition_evidence=conditions, table_context=table)],
    )
    q = case[6][0]["questions"][0]
    t = generation_tasks(q, "Example Product/feature")[0]
    p = candidate_context(
        case[0], case[1], case[4], case[6], q, case[8], case[5], t["task_id"], execution_policy=V2
    )
    selector, _ = selection_context(p, case[4])
    assert selector["task_predicates"][0]["required_support_refs"]
    assert quote in [
        s["quote"] for f in selector["evidence_view"]["facts"] for s in f["source_span_candidates"]
    ]


@pytest.mark.asyncio
async def test_v2_advertises_kind_and_does_not_duplicate_answer_candidate_projection(monkeypatch):
    from packages.agents.writer.question_atomic_delivery import atomic_answer_payload
    from packages.research.evidence.report_claims import audit_report_claims

    case, result, seen = await run_tasks(monkeypatch, execution_policy=V2)
    assert all(
        "required_kind" in p["generation_tasks"][0]
        for name, p in seen
        if name == "dimension_question_atomic_generation"
    )
    audits = audit_report_claims(
        result["claims"],
        result["reviews"],
        case[4],
        case[7],
        available_facts=case[4].facts,
        review_version=3,
    )
    compact = dict(result["compact"], _decision_audited=audits)
    payload = atomic_answer_payload(
        case[0],
        case[1],
        case[6][0]["questions"],
        [a.claim for a in audits if a.status == "supported"],
        case[4],
        case[5],
        compact,
        answer_review_contract="subquestion-premises-v6",
    )
    assert "task_answer_candidates" not in payload
    assert payload["question_task_claims"]


def test_v2_complete_answer_floor_blocks_optional_repair_and_preserves_restored_floor():
    from packages.agents.writer.selected_task_delivery import reserve_answer_tail
    from packages.llm.execution_budget import RunLLMBudget

    phase = "answer:Example/feature"
    budget = RunLLMBudget(
        max_calls=48,
        max_repairs=1,
        max_tokens=160000,
        calls=39,
        tokens_used=114024,
        delivery_reserves={phase: 12000, "final_qa:run": 19702},
    )
    reserve_answer_tail(budget, phase, 25666, fresh=True)
    assert budget.delivery_reserves[phase] == 25666
    assert budget.admission_error(
        is_repair=False, phase="writer:Example/feature", input_tokens=6648, max_output_tokens=600
    )
    assert not budget.admission_error(
        is_repair=False, phase=phase, input_tokens=24066, max_output_tokens=1600
    )
    old = deepcopy(budget)
    reserve_answer_tail(old, phase, 35000, fresh=False)
    assert old.delivery_reserves == budget.delivery_reserves


def test_v2_authority_prefix_is_bound_to_product_and_complete_closed_role_list():
    from packages.agents.writer.selected_task_delivery import normalized_authority_text

    source = (
        "Please note that only Workspace admins and board admins can change "
        "a board member’s status to observer."
    )
    text = (
        "在 Example Product 中，只有 Workspace 管理员和看板管理员"
        "才能把看板现有成员的权限状态改为 Observer。"
    )
    assert normalized_authority_text(text, [source], "Example Product").startswith("只有")
    assert normalized_authority_text(text, [source], "Other Product") == text
    assert normalized_authority_text(
        text.replace("Workspace 管理员和", ""), [source], "Example Product"
    ) == text.replace("Workspace 管理员和", "")


@pytest.mark.asyncio
async def test_v2_live_answer_envelope_is_protected_and_replayable(monkeypatch):
    from test_selected_task_delivery import reviewed_scenario

    from packages.agents.writer.question_atomic_delivery import replay_atomic_delivery

    case, result, audit, seen, use = await reviewed_scenario(monkeypatch, execution_policy=V2)
    assert audit.answer_coverage[0].status == "answered"
    service, record = case[:2]
    answer = next(
        s for s in record.detail.trace_spans if s.name == "dimension_question_atomic_answer_review"
    )
    system, _, raw = answer.full_input.partition("\nJSON:\n")
    _, prompt, output = service._llm_request_envelope(
        system=system.rstrip("\n"), user="\nJSON:\n" + raw, max_output_tokens=1600
    )
    assert record.llm_budget.delivery_reserves["answer:Example Product/feature"] >= prompt + output
    assert replay_atomic_delivery(service, record.detail, case[2], use, case[4], audit=audit)[
        "answers"
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_scope", [False, True])
async def test_v2_cpu_target_rejects_cache_footnote_and_wrong_sku(bad_scope):
    from packages.agents.writer.atomic_question_projection import generation_tasks
    from packages.agents.writer.selected_task_delivery import (
        candidate_context,
        generation_context,
        selection_context,
    )

    quote, conditions, table = billing_original()
    if bad_scope:
        conditions = [s.replace("Compute Paid", "Other Paid") for s in conditions]
    footnote = "CPU time is only billed when the function runs."
    case = await atomic_case(
        [quote, footnote],
        question="Example Product Compute Paid Standard 本月有2300万次请求，账单准确是多少美元？",
        source_qualifiers=[dict(condition_evidence=conditions, table_context=table[:1]), {}],
    )
    q = case[6][0]["questions"][0]
    t = generation_tasks(q, "Example Product/feature")[0]
    payload = candidate_context(
        case[0], case[1], case[4], case[6], q, case[8], case[5], t["task_id"], execution_policy=V2
    )
    _, choices = selection_context(payload, case[4])
    required = payload["task_predicates"][0].get("required_support_refs", [])
    if bad_scope:
        assert not required
    else:
        ref = next(ref for ref, c in choices.items() if c.get("quote") == footnote)
        with pytest.raises(ValueError, match="billing dependency"):
            generation_context(
                payload,
                {t["task_id"]: dict(state="selected", binding_kind="span", support_refs=[ref])},
                choices,
                case[0],
                case[1],
                case[6],
            )


@pytest.mark.asyncio
async def test_v2_fresh_budget_factory_and_process_restore_do_not_reset_charges():
    from dataclasses import replace

    from packages.agents.writer.selected_task_delivery import reserve_answer_tail

    case = await atomic_case()
    service, record = case[:2]
    service._settings = replace(
        service._settings,
        writer_question_atomic_enabled=True,
        run_llm_max_calls=48,
        run_llm_max_tokens=160000,
    )
    record.llm_budget = None
    record.detail.llm_budget_checkpoint = {}
    budget = service._run_llm_budget(record)
    assert budget._fresh_selected_task_budget
    phase = "answer:Example Product/feature"
    budget.delivery_charged[phase] = 123
    reserve_answer_tail(budget, phase, 25666, fresh=budget._fresh_selected_task_budget)
    service._checkpoint_llm_budget(record, budget)
    record.llm_budget = None
    restored = service._run_llm_budget(record)
    assert not restored._fresh_selected_task_budget
    reserve_answer_tail(restored, phase, 35000, fresh=restored._fresh_selected_task_budget)
    assert restored.delivery_reserves[phase] == budget.delivery_reserves[phase]
    assert restored.delivery_charged[phase] == 123


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["none", "foreign_product", "missing_role"])
async def test_v2_bound_authority_prefix_reaches_strict_parser_only_with_complete_roles(change):
    from packages.agents.writer.atomic_question_projection import generation_tasks
    from packages.agents.writer.question_atomic_delivery import authority_task_claim_ids
    from packages.agents.writer.selected_task_delivery import (
        candidate_context,
        generation_context,
        parse_generation,
        selection_context,
    )
    from packages.research.evidence.report_claims import current_feature_binding_reasons

    source = (
        "Please note that only Workspace admins and board admins can change "
        "a board member’s status to observer."
    )
    case = await atomic_case(
        [source], question="Example Product：谁有权把看板现有成员改为 Observer？"
    )
    q = case[6][0]["questions"][0]
    t = generation_tasks(q, "Example Product/feature")[0]
    candidate = candidate_context(
        case[0], case[1], case[4], case[6], q, case[8], case[5], t["task_id"], execution_policy=V2
    )
    _, choices = selection_context(candidate, case[4])
    ref = next(ref for ref, c in choices.items() if c.get("quote") == source)
    p = generation_context(
        candidate,
        {t["task_id"]: dict(state="selected", binding_kind="span", support_refs=[ref])},
        choices,
        case[0],
        case[1],
        case[6],
    )
    text = (
        "在 Example Product 中，只有 Workspace 管理员和看板管理员"
        "才能把看板现有成员的权限状态改为 Observer。"
    )
    if change == "foreign_product":
        text = text.replace("Example Product", "Other Product")
    if change == "missing_role":
        text = text.replace("Workspace 管理员和", "")
    response = json.dumps(
        dict(
            question_plans=[
                dict(
                    question_id=q["question_id"],
                    missing_fields=[],
                    atoms=[dict(task_id=t["task_id"], text=text, kind="fact", support_refs=[ref])],
                )
            ]
        )
    )
    claims, _, plans = parse_generation(response, p, case[4], case[5])
    if change == "none":
        assert len(claims) == 1
        ids = authority_task_claim_ids(p, claims, plans)
        assert claims[0].id in ids
        assert not current_feature_binding_reasons(claims[0], authority_rule=True)
    else:
        assert not claims
