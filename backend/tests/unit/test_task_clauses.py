"""Single-predicate clauses bind server inventory and current-task support."""

import json
from copy import deepcopy

import pytest


def api():
    from packages.agents.writer import task_clauses

    return task_clauses


def test_new_generation_is_strict_and_server_owns_question_identity():
    m = api()
    task = dict(task_id="t", question_id="q", required_kind="fact")
    raw = dict(
        version=1,
        task_id="t",
        status="generated",
        atom=dict(text="Guests have no private area.", kind="fact", support_refs=["s"]),
    )
    plan = m.generation_plan(json.dumps(raw), task, ["s"], [])
    assert plan["question_plans"][0]["question_id"] == "q"
    assert plan["question_plans"][0]["atoms"][0]["text"] == raw["atom"]["text"]
    for bad in [
        dict(raw, question_id="foreign"),
        dict(raw, task_id="other"),
        dict(raw, atom=dict(raw["atom"], support_refs=["foreign"])),
        dict(raw, atom=dict(raw["atom"], kind="inference")),
        dict(question_plans=plan["question_plans"]),
    ]:
        with pytest.raises(ValueError):
            m.generation_plan(json.dumps(bad), task, ["s"], [])


def test_inventory_covers_complete_conditions_domains_and_decimal_without_truncation():
    m = api()
    text = "If A and B hold, use api.example.com at 1.5 seconds; except during maintenance."
    clauses = m.clause_inventory(text)
    assert "".join(c["quote"] for c in clauses) == text
    assert [c["start"] for c in clauses] == [0] + [c["end"] for c in clauses[:-1]]
    assert all(text[c["start"] : c["end"]] == c["quote"] for c in clauses)
    assert any("api.example.com" in c["quote"] and "1.5" in c["quote"] for c in clauses)
    with pytest.raises(ValueError, match="clause_limit"):
        m.clause_inventory(";".join(["predicate"] * 18))


def review_fixture(text="If A and B hold, guests can vote; except on archived boards."):
    m = api()
    inventory = m.clause_inventory(text)
    claim = dict(id="c", text=text)
    payload = dict(
        task_context=dict(task_id="t", focus="vote"),
        clause_inventory=[dict(claim_id="c", clauses=inventory)],
        clause_support_refs=["s"],
    )
    clauses = [
        dict(
            clause_id=c["clause_id"],
            role="assertion" if "can vote" in c["quote"] else "condition",
            independent_predicate="can vote" in c["quote"],
            task_match=True,
            verdict="supported",
            support_refs=["s"],
        )
        for i, c in enumerate(inventory)
    ]
    response = dict(atomicity=[dict(claim_id="c", predicate_count=1, clauses=clauses)])
    return claim, payload, response


def test_review_requires_every_server_clause_and_one_target_assertion():
    m = api()
    claim, payload, raw = review_fixture()
    assert m.validate_clause_reviews(raw, [claim], payload)
    mutations = []
    bad = deepcopy(raw)
    bad["atomicity"][0]["clauses"].pop()
    mutations.append(bad)
    bad = deepcopy(raw)
    bad["atomicity"][0]["clauses"].append(bad["atomicity"][0]["clauses"][0])
    mutations.append(bad)
    bad = deepcopy(raw)
    bad["atomicity"][0]["clauses"][0].update(role="assertion", independent_predicate=True)
    mutations.append(bad)
    bad = deepcopy(raw)
    bad["atomicity"][0]["clauses"][0]["support_refs"] = ["foreign"]
    mutations.append(bad)
    bad = deepcopy(raw)
    bad["atomicity"][0]["clauses"][0]["verdict"] = "unsupported"
    mutations.append(bad)
    for bad in mutations:
        assert not m.validate_clause_reviews(bad, [claim], payload)


def test_multiple_actions_cannot_hide_behind_whole_sentence_count_one():
    m = api()
    claim, payload, raw = review_fixture("Guests can vote and can export cards.")
    raw["atomicity"][0]["clauses"] = [
        dict(
            clause_id="whole",
            role="assertion",
            independent_predicate=True,
            task_match=True,
            verdict="supported",
            support_refs=["s"],
        )
    ]
    assert not m.validate_clause_reviews(raw, [claim], payload)


async def clause_run(
    monkeypatch,
    *,
    fail_first=False,
    clause_fault=False,
    production=False,
    select_insufficient=False,
    tight_budget=False,
    task_clause_contract=None,
    failed_first_text=...,
):
    from claim_review_fixture import expand_prompt_payload
    from test_question_atomic_delivery import atomic_case, supported_review
    from test_task_support_selection import append_response

    from packages.agents.writer.question_atomic_delivery import execute_question_atomic_delivery

    m = api()
    case = await atomic_case(
        ["Guests have no personal area.", "Guests may access only one collection at a time."],
        question="Example Product：访客有私人区域吗？访客能同时加入两个容器吗？",
    )
    service, record, _, selected, view, use, packets, boundaries, allowed = case
    seen = []

    async def model(record, **kwargs):
        p = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        seen.append((kwargs["name"], p))
        if kwargs["name"].endswith("support_selection"):
            t = p["tasks"][0]
            term = "personal" if "私人" in t["question_quote"] else "collection"
            ref = next(
                s["support_ref"]
                for f in p["evidence_view"]["facts"]
                for s in f["source_span_candidates"]
                if term in s["quote"]
            )
            data = dict(
                selections=[
                    dict(
                        task_id=t["task_id"],
                        status="selected",
                        binding_kind="span",
                        support_refs=[ref],
                    )
                ]
            )
            if select_insufficient and term == "personal":
                data = dict(
                    selections=[
                        dict(
                            task_id=t["task_id"],
                            status="insufficient_evidence",
                            binding_kind=None,
                            support_refs=[],
                        )
                    ]
                )
        elif kwargs["name"].endswith("atomic_generation"):
            t = p["generation_tasks"][0]
            selection = p["task_support_selections"][0]
            text = selection["supports"][0]["quote"]
            if fail_first and "personal" in text and p["task_attempt"] == 0:
                text = ("Guests have no personal area and may access only one collection."
                        if failed_first_text is ... else failed_first_text)
            data = dict(
                version=1,
                task_id=t["task_id"],
                status="generated",
                atom=dict(text=text, kind="fact", support_refs=selection["support_refs"]),
            )
        elif kwargs["name"].endswith("atomic_answer_review"):
            data = dict(
                version=1,
                task_reviews=[
                    dict(
                        task_id=t["task_id"],
                        outcome="no" if t["support_choices"] else "unknown",
                        support_refs=[c["ref"] for c in t["support_choices"] if c["primary"]],
                        missing_fields=[],
                        reason="Independent requested task audit.",
                    )
                    for t in p["tasks"]
                ],
            )
        else:
            assert kwargs["name"].endswith("atomic_review")
            data = dict(
                reviews=[supported_review(c) for c in p["claims"]],
                atomicity=[
                    dict(
                        claim_id=c["id"],
                        predicate_count=1,
                        clauses=[
                            dict(
                                clause_id=x["clause_id"],
                                role="assertion" if i == 0 else "condition",
                                independent_predicate=i == 0,
                                task_match=True,
                                verdict="supported",
                                support_refs=p["clause_support_refs"],
                            )
                            for i, x in enumerate(p["clause_inventory"][0]["clauses"])
                        ],
                    )
                    for c in p["claims"]
                ],
            )
            if clause_fault:
                data["atomicity"][0]["clauses"] = []
            if tight_budget:
                budget = service._run_llm_budget(record)
                budget.max_calls = 48
                budget.max_tokens = 160000
                budget.tokens_used = 120000
                budget.delivery_reserves["final_qa:run"] = 12000
                for phase, amount in budget.delivery_reserves.items():
                    if phase not in {"answer:Example Product/feature", "final_qa:run"}:
                        budget.delivery_charged[phase] = amount
        return append_response(service, record, kwargs, json.dumps(data))

    monkeypatch.setattr(service, "_trace_llm_text", model)
    if production:
        from dataclasses import replace

        service._settings = replace(
            service._settings,
            writer_task_execution_enabled=True,
            writer_question_atomic_enabled=True,
        )
        record.detail.report_md = await service._writer_dimension_report(record, 60)
        return case, record.detail.report_dimension_audits[0], seen
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
        task_clause_contract=task_clause_contract or m.CONTRACT,
        answer_review_contract="task-outcomes-v1",
    )
    return case, result, seen


@pytest.mark.asyncio
@pytest.mark.parametrize("contract", ["single-predicate-clauses-v1", "semantic-target-clauses-v2"])
async def test_new_contract_trace_receipt_replay_preserves_raw_and_reuses_only_failed_select(
    monkeypatch, contract,
):
    from packages.agents.writer.question_atomic_delivery import replay_atomic_delivery

    case, result, seen = await clause_run(
        monkeypatch, fail_first=True, task_clause_contract=contract)
    assert len(result["claims"]) == len(result["reviews"]) == 2
    assert sum(name.endswith("support_selection") for name, _ in seen) == 2
    repairs = [
        p for name, p in seen if name.endswith("atomic_generation") and p["task_attempt"] == 1
    ]
    assert len(repairs) == 1
    assert "task_contains_sibling_predicate" in repairs[0]["repair_feedback"]["reason_codes"]
    assert repairs[0]["selection_reuse"]["source_attempt"] == 0
    receipt = next(s for s in case[1].detail.trace_spans if s.name == "question_atomic_delivery")
    assert json.loads(receipt.full_output)["task_clause_contract"] == contract
    if contract == "semantic-target-clauses-v2":
        assert repairs[0]["repair_feedback"]["directive"]["action"] == "rewrite"
    use = next(u for u in case[1].detail.evidence_consumptions if u.id == case[5].id)
    replayed = replay_atomic_delivery(case[0], case[1].detail, case[2], use, case[4])
    assert replayed["claims"] == result["claims"] and replayed["reviews"] == result["reviews"]


@pytest.mark.asyncio
async def test_new_review_missing_inventory_never_publishes_supported_claim(monkeypatch):
    case, result, _ = await clause_run(monkeypatch, clause_fault=True)
    assert result["claims"] and not result["reviews"]


@pytest.mark.asyncio
async def test_new_answer_payload_has_claim_ref_and_full_inline_quotes_without_quote_alias(
    monkeypatch,
):
    from packages.agents.writer.task_answer_outcomes import build_payload
    from packages.research.evidence.report_claims import audit_report_claims

    case, result, _ = await clause_run(monkeypatch)
    audit = audit_report_claims(
        result["claims"],
        result["reviews"],
        case[4],
        case[7],
        available_facts=case[4].facts,
        review_version=3,
    )
    result["compact"]["_decision_audited"] = tuple(audit)
    p = build_payload(
        case[0],
        case[1],
        case[6][0]["questions"],
        result["claims"],
        case[4],
        case[5],
        result["compact"],
    )
    choices = [c for t in p["tasks"] for c in t["support_choices"]]
    assert choices and all(c["quotes"] and c["ref"].startswith("reviewed-claim-") for c in choices)
    assert all("quote_refs" not in c for c in choices)


@pytest.mark.parametrize(
    "text", ["Guests can vote and can export cards.", "可清缓存，并允许读取区域设置。"]
)
def test_false_condition_label_cannot_hide_explicit_second_capability(text):
    m = api()
    claim, payload, raw = review_fixture(text)
    assert len(payload["clause_inventory"][0]["clauses"]) >= 2
    for clause in raw["atomicity"][0]["clauses"]:
        clause.update(role="condition", independent_predicate=False)
    raw["atomicity"][0]["clauses"][0].update(role="assertion", independent_predicate=True)
    assert not m.validate_clause_reviews(raw, [claim], payload)


def test_legitimate_and_seat_prerequisite_is_reviewable_without_extra_assertion():
    m = api()
    claim, payload, raw = review_fixture(
        "Guests can vote, and require a Dev seat; only when voting is enabled."
    )
    for i, clause in enumerate(raw["atomicity"][0]["clauses"]):
        clause.update(role="assertion" if i == 0 else "condition", independent_predicate=i == 0)
    assert m.validate_clause_reviews(raw, [claim], payload)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["snapshot", "span", "support", "contract", "old_raw"])
@pytest.mark.parametrize("contract", ["single-predicate-clauses-v1", "semantic-target-clauses-v2"])
async def test_replay_rejects_resigned_reuse_and_contract_mutations(monkeypatch, fault, contract):
    from packages.agents.writer.dimension_writer import compact_prompt_json
    from packages.agents.writer.question_atomic_delivery import digest, replay_atomic_delivery
    from packages.agents.writer.task_answer_outcomes import bind_transport, transport_identity

    case, result, _ = await clause_run(
        monkeypatch, fail_first=True, task_clause_contract=contract)
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
    p = json.loads(raw)
    if fault == "snapshot":
        p["selection_reuse"]["snapshot_id"] = "foreign"
    elif fault == "span":
        p["selection_reuse"]["span_id"] = "fabricated"
    elif fault == "support":
        p["selection_reuse"]["support_refs"] = ["foreign"]
    elif fault == "contract":
        p.pop("task_clause_contract")
    else:
        span.full_output = json.dumps(dict(question_plans=[]))
    span.full_input = system + "\n\n\nJSON:\n" + compact_prompt_json(p)
    span.metadata["response_transport_identity"] = transport_identity(
        system, "\nJSON:\n" + compact_prompt_json(p)
    )
    dispatch.update(
        full_input_sha256=digest(span.full_input), full_output_sha256=digest(span.full_output)
    )
    bind_transport(dispatch, span)
    receipt_span.full_output = json.dumps(receipt)
    use = next(u for u in record.detail.evidence_consumptions if u.id == case[5].id)
    with pytest.raises(ValueError):
        replay_atomic_delivery(case[0], record.detail, case[2], use, case[4])


@pytest.mark.asyncio
async def test_actual_fresh_writer_enables_clause_contract_and_finishes_citation_qa(monkeypatch):
    from packages.agents.qa.question_reconciliation import _answer_support
    from packages.agents.writer.question_atomic_delivery import replay_atomic_delivery

    case, audit, seen = await clause_run(monkeypatch, production=True)
    receipt = json.loads(
        next(
            s.full_output
            for s in case[1].detail.trace_spans
            if s.name == "question_atomic_delivery"
        )
    )
    assert receipt["task_clause_contract"] == "semantic-target-clauses-v2"
    assert all(p["task_clause_contract"] == "semantic-target-clauses-v2" for _, p in seen)
    assert all(
        "quote_refs" not in c
        for name, p in seen
        if name.endswith("atomic_answer_review")
        for t in p["tasks"]
        for c in t["support_choices"]
    )
    answer = audit.answer_coverage[0]
    assert answer.status == "answered" and "personal area" in case[1].detail.report_md
    use = next(u for u in case[1].detail.evidence_consumptions if u.id == audit.consumption_id)
    assert _answer_support(case[1].detail, case[2], audit, answer, case[6][0]["questions"][0])
    replayed = replay_atomic_delivery(case[0], case[1].detail, case[2], use, case[4], audit=audit)
    assert replayed["answers"][answer.question_id] == answer


def test_fresh_writer_contract_ignores_upstream_checkpoint_and_preserves_old_writer_stage():
    from types import SimpleNamespace

    m = api()
    detail = SimpleNamespace(llm_budget_checkpoint={"calls": 7}, trace_spans=[])
    assert m.fresh_contract(detail, "Example/feature") == "semantic-target-clauses-v2"
    detail.trace_spans = [
        SimpleNamespace(
            name="dimension_question_atomic_generation",
            subagent="Example/feature",
            full_input="Old writer SYSTEM",
            full_output="{}",
        )
    ]
    assert m.fresh_contract(detail, "Example/feature") is None
    assert m.fresh_contract(detail, "Other/feature") == "semantic-target-clauses-v2"


def test_new_answer_system_explicitly_allows_only_primary_choice_ref():
    from packages.agents.writer.task_answer_outcomes import SYSTEM, answer_system

    assert answer_system({}) == SYSTEM
    system = answer_system(
        dict(task_clause_contract=api().CONTRACT, task_execution_policy="selected-task-atoms-v3")
    )
    assert "support_choices[].ref" in system and api().CONTRACT in system


@pytest.mark.asyncio
async def test_source_insufficiency_cannot_acquire_selection_reuse(monkeypatch):
    case, result, seen = await clause_run(monkeypatch, select_insufficient=True)
    assert len(result["claims"]) == len(result["reviews"]) == 1
    assert sum(name.endswith("support_selection") for name, _ in seen) == 3
    assert not any("selection_reuse" in p for _, p in seen)


@pytest.mark.asyncio
async def test_new_repair_defers_and_preserves_supported_peer_and_qa_reserve(monkeypatch):
    case, result, seen = await clause_run(monkeypatch, fail_first=True, tight_budget=True)
    assert len(result["claims"]) == len(result["reviews"]) == 1
    assert not any(p.get("task_attempt") == 1 for _, p in seen)
    assert "task_repair_budget_deferred" in result["gaps"]
    assert case[0]._run_llm_budget(case[1]).delivery_reserves["final_qa:run"] == 12000


@pytest.mark.asyncio
@pytest.mark.parametrize("malformed", [123, ["not text"], {"nested": ["not text"]},
                                      None, 0, False, [], {}])
async def test_malformed_atom_text_keeps_peer_repair_and_authenticated_replay(
    monkeypatch, malformed,
):
    import hashlib

    from packages.agents.writer.question_atomic_delivery import replay_atomic_delivery

    case, result, seen = await clause_run(monkeypatch, fail_first=True,
        task_clause_contract="semantic-target-clauses-v2", failed_first_text=malformed)
    assert len(result["claims"]) == len(result["reviews"]) == 2
    generated = [p for n, p in seen if n.endswith("atomic_generation")]
    repairs = [p for p in generated if p["task_attempt"] == 1]
    assert len(repairs) == 1
    repair = repairs[0]
    repaired_id = repair["generation_tasks"][0]["task_id"]
    peer = [p for p in generated if p["generation_tasks"][0]["task_id"] != repaired_id]
    assert len(peer) == 1 and peer[0]["task_attempt"] == 0
    directive = repair["repair_feedback"]["directive"]
    assert directive["failed_text_type"] == type(malformed).__name__
    assert directive["failed_clauses"] == []
    assert directive["failed_text_sha256"] is None
    assert directive["failed_text_bytes"] is None
    assert directive["instruction"] and directive["action"] == "rewrite"
    assert len(json.dumps(directive, ensure_ascii=False).encode()) <= 1600
    failed_span = next(s for s in case[1].detail.trace_spans
        if s.name.endswith("atomic_generation")
        and json.loads(s.full_output)["atom"]["text"] == malformed)
    transport = next(t for t in repair["repair_feedback"]["prior_transports"]
                     if t["span_id"] == failed_span.id)
    assert transport["full_input_sha256"] == hashlib.sha256(
        failed_span.full_input.encode()).hexdigest()
    assert transport["full_output_sha256"] == hashlib.sha256(
        failed_span.full_output.encode()).hexdigest()
    use = next(u for u in case[1].detail.evidence_consumptions if u.id == case[5].id)
    replay = replay_atomic_delivery(case[0], case[1].detail, case[2], use, case[4])
    assert replay["claims"] == result["claims"] and replay["reviews"] == result["reviews"]


def test_authority_generic_role_rule_keeps_named_request_and_operation_gate():
    from packages.agents.writer.complete_predicates import authority_source_rule
    from packages.agents.writer.selected_task_delivery import task_system

    source = (
        "Please note that only Workspace admins and board admins can change "
        "a board member’s status to observer."
    )
    generic = "只有 Workspace 管理员和看板管理员才能把看板的现有成员权限改为 Observer。"
    assert authority_source_rule(generic, [source])
    assert not authority_source_rule(generic.replace("看板的现有", "看板 A 的现有"), [source])
    assert not authority_source_rule("小林现在把看板 A 的现有成员权限改为 Observer。", [source])
    assert not authority_source_rule(generic.replace("Workspace 管理员和", ""), [source])
    assert not authority_source_rule(generic.replace("把看板", "把项目"), [source])
    assert "generic complete authorized role list" in task_system(
        "dimension_question_atomic_generation", "zh-CN", "selected-task-atoms-v3", api().CONTRACT
    )


def clause_wire_response(payload, response):
    """Explicit offline fixture output for the actually requested contract."""
    if not payload.get("task_clause_contract"):
        return response
    if "question_plans" in response:
        (plan,) = response["question_plans"]
        (atom,) = plan["atoms"]
        return dict(
            version=1,
            task_id=atom["task_id"],
            status="generated",
            atom={k: atom[k] for k in ("text", "kind", "support_refs")},
        )
    if "atomicity" in response:
        import re

        result = deepcopy(response)
        for row in result["atomicity"]:
            inventory = next(
                c["clauses"]
                for c in payload["clause_inventory"]
                if c["claim_id"] == row["claim_id"]
            )
            target = next(
                (
                    i
                    for i, c in reversed(list(enumerate(inventory)))
                    if re.search(r"因此|故可|并不自动|\b(?:can|cannot)\b", c["quote"])
                ),
                0,
            )
            row["clauses"] = [
                dict(
                    clause_id=c["clause_id"],
                    role="assertion" if i == target else "condition",
                    independent_predicate=i == target,
                    task_match=True,
                    verdict="supported",
                    support_refs=payload["clause_support_refs"],
                )
                for i, c in enumerate(inventory)
            ]
        return result
    return response


def test_explicit_modal_inside_if_condition_is_not_a_second_target():
    claim, payload, raw = review_fixture(
        "If guests can access board A, they can vote on enabled cards."
    )
    for i, clause in enumerate(raw["atomicity"][0]["clauses"]):
        clause.update(role="condition" if i == 0 else "assertion", independent_predicate=True)
    assert api().validate_clause_reviews(raw, [claim], payload)


def test_new_generation_system_keeps_exact_task_kind_and_sibling_guards():
    from packages.agents.writer.selected_task_delivery import task_system

    system = task_system(
        "dimension_question_atomic_generation", "zh-CN", "selected-task-atoms-v3", api().CONTRACT
    )
    assert "task_instruction is the exact output predicate" in system
    assert "Use required_kind exactly" in system
    assert "A container cap excludes people" in system
    assert '"question_plans"' not in system
    assert '"version":1' in system


@pytest.mark.parametrize(
    "text",
    [
        "If guests can access board A and guests can view board B, they can vote on enabled cards.",
        "Only if guests can access board A and guests can view board B, "
        "they can vote on enabled cards.",
        "仅当已经启用投票，而且能够访问看板时，访客可以投票。",
    ],
)
def test_complete_and_condition_scope_survives_server_fragmentation(text):
    claim, payload, raw = review_fixture(text)
    for i, clause in enumerate(raw["atomicity"][0]["clauses"]):
        clause.update(
            role="assertion" if i == len(raw["atomicity"][0]["clauses"]) - 1 else "condition",
            independent_predicate=True,
        )
    assert api().validate_clause_reviews(raw, [claim], payload)


@pytest.mark.parametrize(
    "text",
    [
        "If guests can access board A, guests can vote and can export cards.",
        "If guests can access board A. Guests can export cards, guests can vote.",
        "If guests can access board A and guests can view board B, "
        "guests can vote and can export cards.",
        "仅当已经启用投票，而且能够访问看板时，访客可以投票，并允许导出卡片。",
    ],
)
def test_condition_scope_stops_before_a_real_second_target_despite_condition_label(text):
    claim, payload, raw = review_fixture(text)
    for expected, clause in zip(
        payload["clause_inventory"][0]["clauses"], raw["atomicity"][0]["clauses"], strict=True
    ):
        target = "guests can vote" in expected["quote"] or "访客可以投票" in expected["quote"]
        clause.update(role="assertion" if target else "condition", independent_predicate=target)
    assert not api().validate_clause_reviews(raw, [claim], payload)


async def _successful_task_history(monkeypatch, capability):
    if not capability:
        case, result, _ = await clause_run(monkeypatch)
    else:
        import test_question_atomic_delivery as cases
        import test_task_support_selection as fixtures
        from test_task_answer_outcomes import (
            test_capability_fallback_requires_actual_atomic_review_and_keeps_real_operation_gate,
        )

        from packages.agents.writer import question_atomic_delivery as delivery

        captured_cases, results = [], []
        original_case = cases.atomic_case
        original_execute = delivery.execute_question_atomic_delivery
        original_append = fixtures.append_response

        async def capture_case(*args, **kwargs):
            case = await original_case(*args, **kwargs)
            captured_cases.append(case)
            return case

        async def capture_execute(*args, **kwargs):
            result = await original_execute(
                *args, **dict(kwargs, task_clause_contract=api().CONTRACT)
            )
            results.append(result)
            return result

        def append(service, record, kwargs, response):
            p = json.loads(kwargs["user"].split("\nJSON:\n", 1)[1])
            return original_append(
                service, record, kwargs, json.dumps(clause_wire_response(p, json.loads(response)))
            )

        monkeypatch.setattr(cases, "atomic_case", capture_case)
        monkeypatch.setattr(delivery, "execute_question_atomic_delivery", capture_execute)
        monkeypatch.setattr(fixtures, "append_response", append)
        await test_capability_fallback_requires_actual_atomic_review_and_keeps_real_operation_gate(
            monkeypatch, 1, False
        )
        case, result = captured_cases[0], results[0]
    compact = result["compact"]
    history = [
        (
            d,
            next(s for s in case[1].detail.trace_spans if s.id == d["span_id"]),
            compact["_decision_expected_inputs"][d["span_id"]][1],
        )
        for d in compact["dispatches"]
        if d.get("task_id")
    ]
    cid = next(iter(result["capability_claim_ids"])) if capability else result["claims"][0].id
    dispatch, span, payload = next(
        r
        for r in history
        if cid in r[0]["claim_ids"] and r[0]["name"].endswith("atomic_generation")
    )
    return case, result, history, payload["generation_tasks"][0], dispatch, span


@pytest.mark.asyncio
@pytest.mark.parametrize("capability", [False, True])
async def test_successful_normal_and_capability_tasks_cannot_be_repaired_even_with_resigned_wire(
    monkeypatch, capability
):
    from types import SimpleNamespace

    from packages.agents.writer.dimension_writer import compact_prompt_json
    from packages.agents.writer.question_atomic_delivery import digest, replay_atomic_delivery
    from packages.agents.writer.selected_task_delivery import failure_feedback, rebuild
    from packages.agents.writer.task_answer_outcomes import bind_transport, transport_identity
    from packages.agents.writer.task_clauses import reused_generation

    case, result, history, task, original, original_span = await _successful_task_history(
        monkeypatch, capability
    )
    service, record, snapshot, _, view, use, packets, *_ = case
    with pytest.raises(ValueError, match="Successful task cannot receive repair feedback"):
        failure_feedback(task, history, view.facts, use.id)
    # A forged diagnostic hiding the real successful REVIEW must not authorize reuse.
    hidden = [r for r in history if not r[0]["name"].endswith("atomic_review")]
    feedback = failure_feedback(task, hidden, view.facts, use.id)
    reused, _ = reused_generation(task, history, view.facts, use.id, view.snapshot_id, feedback)
    compact = result["compact"]
    system = compact["_decision_expected_inputs"][original_span.id][0]
    user = "\nJSON:\n" + compact_prompt_json(reused)
    span = original_span.model_copy(deep=True)
    span.id = "signed-successful-task-extra-generation"
    span.full_input = system + "\n\n" + user
    span.full_output = json.dumps(
        dict(version=1, task_id=task["task_id"], status="insufficient_evidence", atom=None)
    )
    span.metadata["response_transport_identity"] = transport_identity(system, user)
    dispatch = dict(
        original,
        span_id=span.id,
        attempt=1,
        claim_ids=[],
        full_input_sha256=digest(span.full_input),
        full_output_sha256=digest(span.full_output),
    )
    bind_transport(dispatch, span)
    compact["dispatches"].append(dispatch)
    compact["_decision_expected_inputs"][span.id] = (system, reused)
    record.detail.trace_spans.append(span)
    context = SimpleNamespace(
        compact=compact,
        expected_inputs=compact["_decision_expected_inputs"],
        trace_spans=record.detail.trace_spans,
        facts=view.facts,
        questions=packets[0]["questions"],
        consumption_id=use.id,
        snapshot_id=snapshot.id,
        competitor=view.competitor,
        dimension=view.dimension,
        audited_claims=(),
    )
    with pytest.raises(ValueError, match="Successful task cannot receive repair feedback"):
        rebuild(context)
    receipt_span = next(
        s for s in record.detail.trace_spans if s.name == "question_atomic_delivery"
    )
    receipt = json.loads(receipt_span.full_output)
    receipt["dispatches"].append(dispatch)
    receipt_span.full_output = json.dumps(receipt)
    current_use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    with pytest.raises(ValueError, match="Successful task cannot receive repair feedback"):
        replay_atomic_delivery(service, record.detail, snapshot, current_use, view)


@pytest.mark.asyncio
async def test_failed_task_can_reuse_selection_once_but_never_acquire_attempt_two(monkeypatch):
    from packages.agents.writer.question_atomic_delivery import replay_atomic_delivery

    case, result, seen = await clause_run(monkeypatch, fail_first=True)
    assert len(result["reviews"]) == 2
    assert sum(name.endswith("support_selection") for name, _ in seen) == 2
    receipt_span = next(
        s for s in case[1].detail.trace_spans if s.name == "question_atomic_delivery"
    )
    receipt = json.loads(receipt_span.full_output)
    repair = next(d for d in receipt["dispatches"] if d["attempt"] == 1)
    repair["attempt"] = 2
    receipt_span.full_output = json.dumps(receipt)
    use = next(u for u in case[1].detail.evidence_consumptions if u.id == case[5].id)
    with pytest.raises(ValueError, match="attempt|scope"):
        replay_atomic_delivery(case[0], case[1].detail, case[2], use, case[4])


@pytest.mark.asyncio
async def test_semantic_system_field_locators_match_each_actual_stage_payload(monkeypatch):
    from claim_review_fixture import expand_prompt_payload

    from packages.agents.writer.question_atomic_delivery import GENERATION_NAME, REVIEW_NAME
    from packages.agents.writer.selected_task_delivery import SELECTION_NAME

    case, _, _ = await clause_run(monkeypatch, task_clause_contract="semantic-target-clauses-v2")
    expected = {SELECTION_NAME, GENERATION_NAME, REVIEW_NAME}
    stages = set()
    for span in case[1].detail.trace_spans:
        if span.name not in expected:
            continue
        stages.add(span.name)
        system, _, raw = span.full_input.partition("\nJSON:\n")
        payload = expand_prompt_payload(json.loads(raw))
        for locator, field in (("generation_tasks[0]", "generation_tasks"),
                               ("task_support_selections[0]", "task_support_selections")):
            assert (locator in system) == (span.name == GENERATION_NAME)
            if locator in system:
                assert payload[field] and isinstance(payload[field][0], dict)
        assert "Source title/url restrict applicability only" in system
        assert "it is diagnostic data and never evidence" in system
    assert stages == expected


@pytest.mark.parametrize("contract,name,expected", [
    ("single-predicate-clauses-v1", "dimension_question_task_support_selection",
     "fe4e2fbae7551a0b817fc61f3b7ccd8a36df00b95f586565d68a397f88822656"),
    ("single-predicate-clauses-v1", "dimension_question_atomic_generation",
     "ef548fc4d0c06f7e22e41448d3adc57910cda0228ea6f861f33b19f8e087d036"),
    ("single-predicate-clauses-v1", "dimension_question_atomic_review",
     "1b28b2e1fb58bfce3bbb510dc9bac7f7d4c716085b73b9d4e3683919e6a2acb4"),
    ("semantic-target-clauses-v2", "dimension_question_atomic_generation",
     "75409f737edd6656c91c0bca0c2d9164c5e9575cb0c03763b85e91fea73161f1"),
])
def test_legacy_system_bytes_and_semantic_generation_bytes_are_preserved(contract, name, expected):
    import hashlib

    from packages.agents.writer.selected_task_delivery import task_system

    system = task_system(name, "zh-CN", "selected-task-atoms-v3", contract)
    assert hashlib.sha256(system.encode()).hexdigest() == expected
