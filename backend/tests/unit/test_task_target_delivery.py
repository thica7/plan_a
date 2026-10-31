"""Selected task refs and typed billing targets survive GEN and REVIEW unchanged."""

import json
from copy import deepcopy

import pytest
from test_question_atomic_delivery import atomic_case, supported_review
from test_task_clauses import clause_wire_response
from test_writer_question_delivery import billing_original


async def target_case(*, new_contract=True, semantic_contract=False):
    from packages.agents.writer.atomic_question_projection import generation_tasks
    from packages.agents.writer.selected_task_delivery import (
        candidate_context,
        generation_context,
        selection_context,
    )
    from packages.agents.writer.task_clauses import CONTRACT
    if semantic_contract:
        from packages.agents.writer.task_semantics import CONTRACT

    quote, conditions, table = billing_original()
    case = await atomic_case(
        [quote],
        question="Example Product Compute Paid Standard 本月有2300万次请求，账单准确是多少美元？",
        source_qualifiers=[dict(condition_evidence=conditions, table_context=table[:1])],
    )
    question = case[6][0]["questions"][0]
    task = generation_tasks(question, "Example Product/feature")[0]
    p = candidate_context(
        case[0],
        case[1],
        case[4],
        case[6],
        question,
        case[8],
        case[5],
        task["task_id"],
        execution_policy="selected-task-atoms-v3",
        task_clause_contract=CONTRACT if new_contract else None,
    )
    p = deepcopy(p)
    p["generation_tasks"][0]["support_refs"] = ["planner-only"]
    _, choices = selection_context(p, case[4])
    selected_ref = p["task_predicates"][0]["required_support_refs"][0]
    selections = {
        task["task_id"]: dict(state="selected", binding_kind="span", support_refs=[selected_ref])
    }
    gen = generation_context(p, selections, choices, case[0], case[1], case[6])
    return case, p, gen


@pytest.mark.asyncio
async def test_selected_refs_and_cpu_target_are_one_task_in_generation_and_review():
    from packages.agents.writer.question_atomic_delivery import handoff_context
    from packages.agents.writer.selected_task_delivery import parse_generation, review_context
    from packages.agents.writer.task_clauses import CONTRACT

    case, _, gen = await target_case()
    task = gen["current_task"]
    selected = gen["selected_support"]
    assert task["support_refs"] == selected["support_refs"]
    assert gen["generation_tasks"][0] == task
    assert task["selection_target"] == "applicable_sourced_cpu_billing_dependency"
    assert task["missing_billing_inputs"] == ["cpu_usage"]
    assert "CPU" in task["task_instruction"] and "cpu_usage" in task["task_instruction"]
    assert gen["task_predicates"][0]["instruction"] == task["task_instruction"]
    raw = json.dumps(
        dict(
            version=1,
            task_id=task["task_id"],
            status="generated",
            atom=dict(
                text="Standard usage model CPU time is billed separately.",
                kind="fact",
                support_refs=selected["support_refs"],
            ),
        )
    )
    claims, _, plans = parse_generation(raw, gen, case[4], case[5])
    assert len(claims) == 1
    batch = review_context(
        claims,
        case[4],
        case[6][0]["questions"][0],
        plans[0],
        handoff_context(case[0], case[1], case[4], case[6][0]["questions"], case[5]),
        task,
        execution_policy="selected-task-atoms-v3",
        task_clause_contract=CONTRACT,
        support_refs=selected["support_refs"],
    )
    assert batch["task_context"] == task
    assert batch["clause_support_refs"] == task["support_refs"]
    assert selected["supports"][0]["quote"] in batch["claims"][0]["support_quotes"]


@pytest.mark.asyncio
async def test_sourced_request_price_is_not_the_requested_cpu_billing_target():
    from packages.agents.writer.selected_task_delivery import generation_outcome

    case, _, gen = await target_case()
    task = gen["generation_tasks"][0]
    raw = json.dumps(
        dict(
            version=1,
            task_id=task["task_id"],
            status="generated",
            atom=dict(
                text="Standard includes 12 million requests per month.",
                kind="fact",
                support_refs=gen["selected_support"]["support_refs"],
            ),
        )
    )
    claims, reasons, plans = generation_outcome(raw, gen, case[4].facts, case[5].id)
    assert not claims
    assert "task_selected_target_mismatch" in reasons
    assert plans[0]["task_results"][0]["reason"] == "task_selected_target_mismatch"


@pytest.mark.asyncio
async def test_review_cannot_attest_task_match_for_sourced_sibling_request_price():
    from packages.agents.writer.question_atomic_delivery import handoff_context
    from packages.agents.writer.selected_task_delivery import (
        parse_generation,
        parse_task_claim_reviews,
        review_context,
    )
    from packages.agents.writer.task_clauses import CONTRACT

    case, _, gen = await target_case()
    task = gen["generation_tasks"][0]
    raw = json.dumps(
        dict(
            version=1,
            task_id=task["task_id"],
            status="generated",
            atom=dict(
                text="Standard usage model CPU time is billed separately.",
                kind="fact",
                support_refs=gen["selected_support"]["support_refs"],
            ),
        )
    )
    claims, _, plans = parse_generation(raw, gen, case[4], case[5])
    claims = [
        claims[0].model_copy(update={"text": "Standard includes 12 million requests per month."})
    ]
    batch = review_context(
        claims,
        case[4],
        case[6][0]["questions"][0],
        plans[0],
        handoff_context(case[0], case[1], case[4], case[6][0]["questions"], case[5]),
        task,
        execution_policy="selected-task-atoms-v3",
        task_clause_contract=CONTRACT,
        support_refs=gen["selected_support"]["support_refs"],
    )
    response = clause_wire_response(
        batch,
        dict(
            reviews=[supported_review(c) for c in batch["claims"]],
            atomicity=[dict(claim_id=claims[0].id, predicate_count=1, clauses=[])],
        ),
    )
    with pytest.raises(ValueError, match="task_selected_target_mismatch"):
        parse_task_claim_reviews(json.dumps(response), claims, batch)


@pytest.mark.asyncio
async def test_unmarked_old_task_projection_keeps_planner_metadata():
    _, p, gen = await target_case(new_contract=False)
    assert gen["generation_tasks"][0]["support_refs"] == ["planner-only"]
    assert "selection_target" not in gen["generation_tasks"][0]
    assert (
        p["task_predicates"][0]["selection_target"] == "applicable_sourced_cpu_billing_dependency"
    )


def test_actual_single_vault_review_cannot_hide_second_action_as_connector():
    from packages.agents.writer.task_clauses import clause_inventory, validate_clause_reviews

    text = "访客一次只能被邀请加入一个保险库，但可将其从一个保险库移除后再加入另一个保险库。"
    inventory = clause_inventory(text)
    claim = dict(id="c", text=text)
    payload = dict(
        clause_inventory=[dict(claim_id="c", clauses=inventory)], clause_support_refs=["s42"]
    )
    review = dict(
        atomicity=[
            dict(
                claim_id="c",
                predicate_count=1,
                clauses=[
                    dict(
                        clause_id=c["clause_id"],
                        role="assertion" if i == 0 else "connector",
                        independent_predicate=i == 0,
                        task_match=True,
                        verdict="supported",
                        support_refs=["s42"],
                    )
                    for i, c in enumerate(inventory)
                ],
            )
        ]
    )
    assert not validate_clause_reviews(review, [claim], payload)


@pytest.mark.parametrize("conjunction", ["但", "但是", "不过"])
@pytest.mark.parametrize("role", ["connector", "exception"])
@pytest.mark.parametrize("subject", ["", "用户", " 用户 ", "甲" * 35, "甲" * 36, "甲" * 80])
def test_generic_chinese_adversative_cannot_hide_extra_capability(conjunction, role, subject):
    from packages.agents.writer.task_clauses import clause_inventory, validate_clause_reviews

    text = f"用户可以清除记录{conjunction}{subject}可读取设置。"
    inventory = clause_inventory(text)
    claim = dict(id="c", text=text)
    payload = dict(
        clause_inventory=[dict(claim_id="c", clauses=inventory)], clause_support_refs=["selected"]
    )
    review = dict(
        atomicity=[
            dict(
                claim_id="c",
                predicate_count=1,
                clauses=[
                    dict(
                        clause_id=c["clause_id"],
                        role="assertion" if i == 0 else role,
                        independent_predicate=i == 0,
                        task_match=True,
                        verdict="supported",
                        support_refs=["selected"],
                    )
                    for i, c in enumerate(inventory)
                ],
            )
        ]
    )
    assert not validate_clause_reviews(review, [claim], payload)


@pytest.mark.parametrize(
    "text",
    [
        "用户可以清除记录，但仅当能够访问设置时。",
        "用户可以清除记录，但是除非已经锁定记录。",
        "用户可以清除记录，不过如果能够访问设置时。",
        "Users can clear records, but only when users can access settings.",
        "Users can clear records unless they can view locked records.",
    ],
)
def test_actual_conditions_remain_conditions_after_adversative_fix(text):
    from packages.agents.writer.task_clauses import clause_inventory, validate_clause_reviews

    inventory = clause_inventory(text)
    claim = dict(id="c", text=text)
    payload = dict(
        clause_inventory=[dict(claim_id="c", clauses=inventory)], clause_support_refs=["selected"]
    )
    review = dict(
        atomicity=[
            dict(
                claim_id="c",
                predicate_count=1,
                clauses=[
                    dict(
                        clause_id=c["clause_id"],
                        role="assertion" if i == 0 else "condition",
                        independent_predicate=i == 0,
                        task_match=True,
                        verdict="supported",
                        support_refs=["selected"],
                    )
                    for i, c in enumerate(inventory)
                ],
            )
        ]
    )
    assert validate_clause_reviews(review, [claim], payload)


@pytest.mark.asyncio
async def test_cpu_target_actual_trace_receipt_and_replay_keep_one_selected_contract(monkeypatch):
    from claim_review_fixture import expand_prompt_payload
    from test_task_support_selection import append_response

    from packages.agents.writer.question_atomic_delivery import (
        execute_question_atomic_delivery,
        replay_atomic_delivery,
    )
    from packages.agents.writer.task_clauses import CONTRACT

    case, _, _ = await target_case()
    service, record, snapshot, selected, view, use, packets, boundaries, allowed = case
    seen = []

    async def model(record, **kwargs):
        p = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        seen.append((kwargs["name"], p))
        if kwargs["name"].endswith("support_selection"):
            task = p["tasks"][0]
            ref = p["task_predicates"][0]["required_support_refs"][0]
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
            assert task["support_refs"] == p["selected_support"]["support_refs"]
            assert task["missing_billing_inputs"] == ["cpu_usage"]
            response = dict(
                version=1,
                task_id=task["task_id"],
                status="generated",
                atom=dict(
                    text="Standard usage model CPU time is billed separately.",
                    kind="fact",
                    support_refs=task["support_refs"],
                ),
            )
        else:
            assert (
                p["task_context"]["selection_target"] == "applicable_sourced_cpu_billing_dependency"
            )
            assert p["task_context"]["support_refs"] == p["clause_support_refs"]
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
    assert len(result["claims"]) == len(result["reviews"]) == 1
    assert len(seen) == 3
    current_use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    replayed = replay_atomic_delivery(service, record.detail, snapshot, current_use, view)
    assert replayed["claims"] == result["claims"] and replayed["reviews"] == result["reviews"]


@pytest.mark.parametrize("conjunction", ["但", "但是", "不过"])
def test_long_conditional_subject_is_still_a_premise(conjunction):
    from packages.agents.writer.task_clauses import clause_inventory, validate_clause_reviews

    text = f"用户可以清除记录，{conjunction} 仅当{'甲' * 80}能够访问设置时。"
    inventory = clause_inventory(text)
    claim = dict(id="c", text=text)
    payload = dict(
        clause_inventory=[dict(claim_id="c", clauses=inventory)], clause_support_refs=["selected"]
    )
    review = dict(
        atomicity=[
            dict(
                claim_id="c",
                predicate_count=1,
                clauses=[
                    dict(
                        clause_id=c["clause_id"],
                        role="assertion" if i == 0 else "condition",
                        independent_predicate=i == 0,
                        task_match=True,
                        verdict="supported",
                        support_refs=["selected"],
                    )
                    for i, c in enumerate(inventory)
                ],
            )
        ]
    )
    assert validate_clause_reviews(review, [claim], payload)


@pytest.mark.parametrize("conjunction", ["但", "但是", "不过"])
@pytest.mark.parametrize("opening", ["如果", "仅当", "只有在"])
def test_coordinated_condition_after_adversative_keeps_full_subject_scope(conjunction, opening):
    from test_task_clauses import review_fixture

    from packages.agents.writer.task_clauses import validate_clause_reviews

    text = f"用户可以清除记录，{conjunction}{opening}用户可以访问设置并且该用户能够查看记录时。"
    claim, payload, raw = review_fixture(text)
    assert len(payload["clause_inventory"][0]["clauses"]) == 3
    for i, clause in enumerate(raw["atomicity"][0]["clauses"]):
        clause.update(role="assertion" if i == 0 else "condition", independent_predicate=i == 0)
    assert validate_clause_reviews(raw, [claim], payload)


@pytest.mark.parametrize("opening", ["but if", "but only when"])
def test_english_adversative_condition_also_retains_coordinated_prerequisite(opening):
    from test_task_clauses import review_fixture

    from packages.agents.writer.task_clauses import validate_clause_reviews

    text = (
        f"Users can clear records, {opening} users can access settings and users can view records."
    )
    claim, payload, raw = review_fixture(text)
    assert len(payload["clause_inventory"][0]["clauses"]) == 3
    for i, clause in enumerate(raw["atomicity"][0]["clauses"]):
        clause.update(role="assertion" if i == 0 else "condition", independent_predicate=i == 0)
    assert validate_clause_reviews(raw, [claim], payload)
