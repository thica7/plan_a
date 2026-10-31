"""Fresh semantic contract repairs preserve complete evidence and legacy gates."""

import hashlib

import pytest

from packages.agents.writer import task_clauses

SEMANTIC = "semantic-target-clauses-v2"


def clause_case(text, roles, *, source="Guests can vote if voting is enabled.", task=None):
    inventory = task_clauses.clause_inventory(text)
    claim = dict(id="c", text=text, kind="inference", competitor="Example",
                 support_quotes=[source], source_span_bindings=[dict(quote=source)])
    payload = dict(task_clause_contract=SEMANTIC, claims=[claim],
        task_context=task or dict(task_id="t", question_id="q", focus="vote"),
        request_context=dict(parents=[dict(parent_id="p", text="Can guests vote?")],
                             bindings=[dict(question_id="q", parent_id="p")]),
        clause_inventory=[dict(claim_id="c", clauses=inventory)], clause_support_refs=["s"])
    assert len(inventory) == len(roles)
    raw = dict(atomicity=[dict(claim_id="c", predicate_count=1, clauses=[dict(
        clause_id=c["clause_id"], role=role, independent_predicate=role == "assertion",
        task_match=True, verdict="supported", support_refs=["s"])
        for c, role in zip(inventory, roles, strict=True)])])
    return claim, payload, raw


def quantity_case():
    source = "Free organizations support secure data sharing in up to two collections."
    text = ("Free organization 最多支持两个 collections 的安全数据共享，"
            "因此 3 个 collections 超出该上限，无法满足。")
    task = dict(task_id="t", question_id="q", focus="source_rule",
                question_quote="3 个 collections", request_property="container_limit")
    claim, payload, raw = clause_case(text, ["premise", "assertion", "connector"],
                                     source=source, task=task)
    payload["request_context"]["parents"][0]["text"] = (
        "Example：我们都在2026年新建账户，并建立一个 Free organization，"
        "想让3个人用3个 collections共享密码。这个免费组织能满足吗？")
    return claim, payload, raw


def test_new_cpu_task_replaces_the_conflicting_allowance_instruction_only_for_semantic():
    original = dict(task_id="t", question_id="q", focus="billing_inputs",
        task_instruction=("Publish only the applicable billing allowance/rate "
                          "and complete conditions."))
    selection = dict(support_refs=["s"])
    target = dict(selection_target="applicable_sourced_cpu_billing_dependency",
                  missing_billing_inputs=["cpu_usage"],
                  semantic_target=dict(relation="cpu_billing_dependency"))
    result = task_clauses.selected_task(original, selection, target)
    assert "allowance/rate" not in result["task_instruction"]
    assert "cpu_usage" in result["task_instruction"]
    assert "dependency" in result["task_instruction"]
    assert original["task_instruction"].startswith("Publish only the applicable billing")
    legacy_target = {k: v for k, v in target.items() if k != "semantic_target"}
    legacy_instruction = task_clauses.selected_task(original, selection, legacy_target)[
        "task_instruction"]
    assert legacy_instruction.startswith(original["task_instruction"])


@pytest.mark.asyncio
async def test_cpu_selection_and_generation_use_the_same_single_relation_instruction():
    from test_task_target_delivery import target_case

    _, candidate, generated = await target_case(semantic_contract=True)
    instruction = generated["generation_tasks"][0]["task_instruction"]
    assert candidate["generation_tasks"][0]["task_instruction"] == instruction
    assert candidate["task_predicates"][0]["instruction"] == instruction
    assert "allowance/rate" not in instruction and "cpu_usage" in instruction


def test_typed_same_unit_quantity_premise_with_own_source_is_reviewable():
    claim, payload, raw = quantity_case()
    assert task_clauses.validate_clause_reviews(raw, [claim], payload)
    legacy = dict(payload, task_clause_contract=task_clauses.CONTRACT)
    assert task_clauses.validate_clause_reviews(raw, [claim], legacy)


@pytest.mark.parametrize("fault", ["or", "unknown_condition", "wrong_unit", "untyped",
                                   "foreign_parent", "ambiguous_parent", "unbound_quote",
                                   "independent", "unrelated_premise"])
def test_quantity_premise_permission_is_narrow(fault):
    claim, payload, raw = quantity_case()
    if fault == "or":
        payload["request_context"]["parents"][0]["text"] += " Or another plan?"
    elif fault == "unknown_condition":
        claim["support_quotes"][0] += " If approved by support."
        claim["source_span_bindings"][0]["quote"] = claim["support_quotes"][0]
    elif fault == "wrong_unit":
        payload["task_context"]["request_property"] = "people_limit"
    elif fault == "untyped":
        payload["task_context"].pop("request_property")
    elif fault == "foreign_parent":
        payload["request_context"]["bindings"][0]["question_id"] = "foreign"
    elif fault == "ambiguous_parent":
        payload["request_context"]["bindings"].append(dict(question_id="q", parent_id="other"))
    elif fault == "unbound_quote":
        claim["source_span_bindings"] = []
    elif fault == "independent":
        raw["atomicity"][0]["clauses"][0]["independent_predicate"] = True
    else:
        request_context = payload["request_context"]
        other, payload, raw = clause_case(
            "Guests are members; 3 collections exceed the maximum.",
            ["premise", "assertion"], source=claim["support_quotes"][0],
            task=payload["task_context"])
        payload["request_context"] = request_context
        claim = other
    assert not task_clauses.validate_clause_reviews(raw, [claim], payload)


@pytest.mark.parametrize("text,roles", [
    ("访客可以给卡片投票，前提是该看板已启用投票功能。", ["assertion", "condition"]),
    ("在看板 B 已启用卡片投票且允许该访客投票的前提下，小林可以给 B 的卡片投票。",
     ["condition", "assertion"]),
])
def test_new_chinese_condition_scope_is_bounded_and_legacy_unchanged(text, roles):
    claim, payload, raw = clause_case(text, roles)
    assert task_clauses.validate_clause_reviews(raw, [claim], payload)
    legacy = dict(payload, task_clause_contract=task_clauses.CONTRACT)
    assert not task_clauses.validate_clause_reviews(raw, [claim], legacy)


@pytest.mark.parametrize("text,roles", [
    ("在看板已启用投票的前提下，访客可以投票，并允许导出卡片。",
     ["condition", "assertion", "condition"]),
    ("在看板允许导出卡片，访客可以投票。", ["condition", "assertion"]),
])
def test_chinese_condition_cannot_hide_an_operation_after_closure_or_without_marker(text, roles):
    claim, payload, raw = clause_case(text, roles)
    assert not task_clauses.validate_clause_reviews(raw, [claim], payload)


@pytest.mark.parametrize("fault,code,offending", [
    ("capability", "task_clause_additional_capability", "clause-2"),
    ("mismatch", "task_clause_target_mismatch", "clause-2"),
    ("assertions", "task_clause_assertion_count", "clause-2"),
])
def test_review_diagnostics_identify_the_actual_failed_clause(fault, code, offending):
    claim, payload, raw = clause_case("Guests can vote, and can export cards.",
                                     ["assertion", "connector"])
    second = raw["atomicity"][0]["clauses"][1]
    if fault == "mismatch":
        second["task_match"] = False
    elif fault == "assertions":
        second.update(role="assertion", independent_predicate=True)
    failure = task_clauses.clause_review_failure(raw, [claim], payload)
    assert failure["reason_code"] == code
    assert offending in failure["clause_ids"]
    from packages.agents.writer.task_semantics import repair_directive
    directive = repair_directive(dict(payload["task_context"], question_quote="Can guests vote?"),
        ["claim_review_invalid", code], claim["text"], clause_failure=failure)
    assert directive["failure_reason"] == code
    assert any(c["clause_id"] == offending for c in directive["failed_clauses"])
    fragment = next(c for c in directive["failed_clauses"] if c["clause_id"] == offending)
    original = claim["text"][fragment["start"]:fragment["end"]]
    assert fragment["quote_sha256"] == hashlib.sha256(original.encode()).hexdigest()
    assert code in directive["instruction"]


@pytest.mark.asyncio
async def test_actual_review_failure_feedback_and_repair_keep_the_successful_peer(monkeypatch):
    import json

    import test_task_support_selection as fixtures
    from claim_review_fixture import expand_prompt_payload
    from test_task_clauses import clause_run

    from packages.agents.writer.question_atomic_delivery import replay_atomic_delivery

    original = fixtures.append_response
    failed = False

    def append(service, record, kwargs, response):
        nonlocal failed
        p = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        if (kwargs["name"].endswith("atomic_review") and not failed
                and "personal" in p["claims"][0]["text"]):
            data = json.loads(response)
            data["atomicity"][0]["clauses"][0]["task_match"] = False
            response = json.dumps(data)
            failed = True
        return original(service, record, kwargs, response)

    monkeypatch.setattr(fixtures, "append_response", append)
    case, result, seen = await clause_run(monkeypatch, task_clause_contract=SEMANTIC)
    # Keep the first failed claim in trace; only the repaired claim and peer
    # have eligible independent reviews.
    assert len(result["claims"]) == 3 and len(result["reviews"]) == 2
    repairs = [p for n, p in seen if n.endswith("atomic_generation") and p["task_attempt"]]
    assert len(repairs) == 1
    feedback = repairs[0]["repair_feedback"]
    assert "task_clause_target_mismatch" in feedback["reason_codes"]
    assert feedback["directive"]["failure_reason"] == "task_clause_target_mismatch"
    assert feedback["directive"]["failed_clauses"][0]["clause_id"] == "clause-1"
    assert any(t["name"].endswith("atomic_review") and t["full_output_sha256"]
               for t in feedback["prior_transports"])
    repair_id = repairs[0]["generation_tasks"][0]["task_id"]
    assert sum(n.endswith("atomic_generation") and p["generation_tasks"][0]["task_id"] != repair_id
               for n, p in seen) == 1
    use = next(u for u in case[1].detail.evidence_consumptions if u.id == case[5].id)
    replay = replay_atomic_delivery(case[0], case[1].detail, case[2], use, case[4])
    assert replay["claims"] == result["claims"] and replay["reviews"] == result["reviews"]
