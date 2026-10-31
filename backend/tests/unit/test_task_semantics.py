"""Fresh task semantics constrain selection; they never certify source support."""

from copy import deepcopy
from types import SimpleNamespace

import pytest


def context(text):
    return dict(
        parents=[dict(parent_id="p", text=text)], bindings=[dict(question_id="q", parent_id="p")]
    )


def task(quote="Can the guest access two shared vaults simultaneously?", **changes):
    return dict(task_id="t", question_id="q", focus="source_rule", question_quote=quote, **changes)


def test_fresh_contract_is_distinct_and_old_identity_is_still_accepted():
    from packages.agents.writer import task_clauses

    semantic = "semantic-target-clauses-v2"
    assert (
        task_clauses.fresh_contract(SimpleNamespace(trace_spans=[]), "Example/feature") == semantic
    )
    for value in (semantic, "single-predicate-clauses-v1", None):
        assert (
            task_clauses.checked_contract(
                dict(task_clause_contract=value, task_execution_policy="selected-task-atoms-v3")
            )
            == value
        )


@pytest.mark.parametrize(
    "parent",
    [
        "Example: the guest has accepted the invitation and been confirmed.",
        "Example：访客已接受邀请并被确认。",
    ],
)
def test_confirmed_current_access_rejects_invitation_only_without_borrowing_peer(parent):
    from packages.agents.writer.task_semantics import selection_reasons, semantic_target

    target = semantic_target(task(), context(parent))
    assert target["relation"] == "current_access"
    invite = dict(s=dict(binding_kind="span", quote="A guest can only be invited to one vault."))
    access = dict(s=dict(binding_kind="span", quote="Guests only have access to one vault."))
    assert selection_reasons(target, ["s"], invite) == ("task_support_semantic_mismatch",)
    assert not selection_reasons(target, ["s"], access)
    assert "own" not in target  # No peer claim or peer reference can be an authority.


def test_invitation_task_still_accepts_invitation_evidence():
    from packages.agents.writer.task_semantics import selection_reasons, semantic_target

    target = semantic_target(
        task("How many vaults may a guest be invited to?"),
        context("Example: the guest has accepted and been confirmed."),
    )
    assert target["relation"] == "invitation"
    assert not selection_reasons(
        target,
        ["s"],
        dict(s=dict(binding_kind="span", quote="A guest may be invited to only one vault.")),
    )


@pytest.mark.parametrize(
    "question",
    [
        "已接受邀请并被确认的访客能同时访问两个共享保险库吗？",
        "Can a guest who has accepted the invitation and been confirmed access two shared "
        "vaults simultaneously?",
    ],
)
def test_same_sentence_accepted_invitation_is_a_premise_not_the_requested_action(question):
    from packages.agents.writer.task_semantics import selection_reasons, semantic_target

    target = semantic_target(task(question), {})
    assert target["relation"] == "current_access"
    assert target["question_quote"] == question
    invitation = dict(s=dict(quote="Guests can only be invited to join one shared vault."))
    assert selection_reasons(target, ["s"], invitation) == ("task_support_semantic_mismatch",)
    assert not selection_reasons(
        target, ["s"], dict(s=dict(quote="Guests only have access to one shared vault."))
    )


@pytest.mark.parametrize(
    "question",
    [
        "已接受邀请并被确认后，他还能再邀请两人加入吗？",
        "已接受/确认后还能再邀请两人吗？",
        "Can a guest who has accepted the invitation and been confirmed invite two more "
        "people to join?",
        "Can a guest who has accepted the invitation and been confirmed be invited to join "
        "two shared vaults?",
        "已接受邀请并被确认的访客还能被邀请同时加入两个共享保险库吗？",
    ],
)
def test_same_sentence_confirmation_does_not_change_a_real_invitation_request(question):
    from packages.agents.writer.task_semantics import selection_reasons, semantic_target

    target = semantic_target(task(question), {})
    assert target["relation"] == "invitation"
    assert not selection_reasons(
        target, ["s"], dict(s=dict(quote="Guests can only be invited to join one shared vault."))
    )


@pytest.mark.parametrize("text", [
    "已接受邀请并被确认的访客不能同时加入两个共享保险库。",
    "A guest who has accepted the invitation and been confirmed cannot join two shared "
    "vaults simultaneously.",
    "已接受邀请并被确认的访客只能访问由邀请方选择的一个保险库。",
])
def test_current_access_assertion_ignores_only_the_completed_accepted_invitation(text):
    from packages.agents.writer.task_clauses import target_reasons
    from packages.agents.writer.task_semantics import semantic_target

    question = "Can the confirmed guest who accepted the invitation access two shared vaults?"
    target = semantic_target(task(question), {})
    assert target["relation"] == "current_access"
    assert not target_reasons(dict(semantic_target=target), text, "Example")
    assert target["question_quote"] == question


@pytest.mark.parametrize("text", [
    "访客只能被邀请加入一个共享保险库。",
    "Guests can only be invited to join one shared vault.",
    "已接受邀请并被确认的访客还能再被邀请加入两个共享保险库。",
    "A guest who has accepted the invitation and been confirmed can be invited again "
    "to join two shared vaults.",
    "已接受邀请并被确认的访客只能访问一个保险库，还能再被邀请加入两个共享保险库。",
    "A guest who has accepted the invitation and been confirmed can only access one vault "
    "and can be invited again to join two shared vaults.",
])
def test_current_access_assertion_still_rejects_a_new_invitation_action(text):
    from packages.agents.writer.task_semantics import assertion_reasons, selection_reasons

    target = dict(relation="current_access")
    assert assertion_reasons(target, text) == ("task_selected_target_mismatch",)
    invitation = dict(s=dict(quote="Guests can only be invited to join one shared vault."))
    assert selection_reasons(target, ["s"], invitation) == ("task_support_semantic_mismatch",)


@pytest.mark.parametrize("text", [
    "A confirmed guest can access only the vault chosen by the person who invited them.",
    "已接受邀请并被确认的访客只能访问由邀请者选择的一个保险库。",
    "A guest who was invited by an organizer cannot join two shared vaults simultaneously.",
    "曾被邀请的访客不能同时加入两个共享保险库。",
    "The invitation arrangement determines the guest's ongoing access.",
])
def test_actor_past_relationship_and_unknown_wording_reach_independent_review(text):
    from packages.agents.writer.task_semantics import assertion_reasons

    assert not assertion_reasons(dict(relation="current_access"), text)


@pytest.mark.asyncio
@pytest.mark.parametrize("source,source_supported", [
    ("Guests only have access to one vault chosen by the person who invited them.", True),
    ("访客只能访问由邀请者选择的一个保险库。", True),
    ("访客只能访问由邀请方选择的一个保险库。", True),
    ("访客只能访问由邀请方选择的一个保险库。", False),
])
async def test_actor_relation_uses_full_select_gen_source_review_and_replay(
    monkeypatch, source, source_supported,
):
    import json

    from claim_review_fixture import expand_prompt_payload
    from test_question_atomic_delivery import atomic_case, supported_review
    from test_task_support_selection import append_response

    from packages.agents.writer.question_atomic_delivery import (
        execute_question_atomic_delivery,
        replay_atomic_delivery,
    )
    from packages.research.evidence.report_claims import audit_report_claims

    case = await atomic_case([source], question=(
        "Example Product：访客已接受邀请并被确认。他能同时加入两个共享保险库吗？"))
    service, record, _, selected, view, use, packets, boundaries, allowed = case
    seen = []

    async def model(record, **kwargs):
        p = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        name = kwargs["name"]
        seen.append((name, p))
        if name.endswith("support_selection"):
            ref = next(s["support_ref"] for f in p["evidence_view"]["facts"]
                       for s in f.get("source_span_candidates", ()))
            data = dict(selections=[dict(task_id=p["tasks"][0]["task_id"], status="selected",
                binding_kind="span", support_refs=[ref])])
        elif name.endswith("atomic_generation"):
            task = p["generation_tasks"][0]
            kinds = task["required_kind"]
            data = dict(version=1, task_id=task["task_id"], status="generated", atom=dict(
                text=source, kind=kinds[0] if isinstance(kinds, list) else kinds,
                support_refs=p["task_support_selections"][0]["support_refs"]))
        else:
            assert name.endswith("atomic_review")
            verdict = "supported" if source_supported else "unsupported"
            data = dict(reviews=[dict(supported_review(c), verdict=verdict) for c in p["claims"]],
                atomicity=[dict(claim_id=c["id"], predicate_count=1, clauses=[dict(
                    clause_id=x["clause_id"], role="assertion", independent_predicate=True,
                    task_match=True, verdict=verdict, support_refs=p["clause_support_refs"])
                    for x in p["clause_inventory"][i]["clauses"]])
                    for i, c in enumerate(p["claims"])])
        return append_response(service, record, kwargs, json.dumps(data))

    monkeypatch.setattr(service, "_trace_llm_text", model)
    result = await execute_question_atomic_delivery(service, record, selected, view, use,
        packets[0]["questions"], packets, allowed, boundaries, (),
        task_execution_policy="selected-task-atoms-v3",
        task_clause_contract="semantic-target-clauses-v2")
    assert any(n.endswith("atomic_review") for n, _ in seen)
    if source_supported:
        assert len(result["claims"]) == len(result["reviews"]) == 1
        assert sum(n.endswith("atomic_generation") for n, _ in seen) == 1
    audit = audit_report_claims(result["claims"], result["reviews"], view, boundaries,
                              available_facts=view.facts, review_version=3)
    assert any(a.status == "supported" for a in audit) is source_supported
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    replay = replay_atomic_delivery(service, record.detail, case[2], use, view)
    assert replay["claims"] == result["claims"] and replay["reviews"] == result["reviews"]


def test_ambiguous_parent_is_not_inherited():
    from packages.agents.writer.task_semantics import semantic_target

    ctx = context("Guest confirmed.")
    ctx["bindings"].append(dict(question_id="q", parent_id="other"))
    ctx["parents"].append(dict(parent_id="other", text="Guest not confirmed."))
    assert semantic_target(task(), ctx)["request_binding"] is None


def test_cpu_sibling_failure_is_concrete_before_target_mismatch():
    from packages.agents.writer.task_semantics import assertion_reasons

    target = dict(relation="cpu_billing_dependency")
    assert assertion_reasons(
        target, "CPU time is billed; each invocation has a 20 second limit."
    ) == ("task_contains_sibling_predicate",)
    assert assertion_reasons(
        target, "CPU time is billed at $0.02 per million CPU milliseconds."
    ) == ("task_contains_sibling_predicate",)
    assert not assertion_reasons(target, "Billing depends on the CPU time consumed.")


@pytest.mark.parametrize(
    "text",
    [
        "Standard 用量模式的完整账单还需要 CPU 用量这一输入。",
        "CPU 用量是 Standard 模式完整账单的必要输入。",
        "The Standard bill depends on CPU usage.",
        "Standard CPU time is billed separately.",
    ],
)
def test_fresh_cpu_target_accepts_dependency_relation_in_either_language_order(text):
    from packages.agents.writer.task_clauses import target_reasons

    task = dict(
        focus="billing_inputs",
        question_quote="Standard 用量模式的完整账单是多少？",
        selection_target="applicable_sourced_cpu_billing_dependency",
        missing_billing_inputs=["cpu_usage"],
        semantic_target=dict(relation="cpu_billing_dependency"),
    )
    assert not target_reasons(task, text, "Example")
    if "必要输入" in text or "还需要" in text:
        task.pop("semantic_target")
        assert target_reasons(task, text, "Example") == ("task_selected_target_mismatch",)


@pytest.mark.parametrize(
    "text",
    [
        "Standard 的完整账单只取决于请求次数。",
        "Standard 的账单不需要 CPU 用量。",
        "CPU 用量不是完整账单的必要输入。",
        "CPU usage is not required for the Standard bill.",
    ],
)
def test_cpu_dependency_does_not_accept_request_count_or_unsupported_denial(text):
    from packages.agents.writer.task_semantics import assertion_reasons

    assert assertion_reasons(dict(relation="cpu_billing_dependency"), text) == (
        "task_selected_target_mismatch",
    )


def test_independent_product_premise_cannot_hide_behind_count_one():
    from test_task_clauses import review_fixture

    from packages.agents.writer.task_clauses import validate_clause_reviews

    claim, payload, raw = review_fixture(
        "Observers are board members; Workspace has no Observer role; access does not propagate."
    )
    payload["task_clause_contract"] = "semantic-target-clauses-v2"
    for i, clause in enumerate(raw["atomicity"][0]["clauses"]):
        clause.update(role="assertion" if i == 2 else "premise", independent_predicate=True)
    assert not validate_clause_reviews(raw, [claim], payload)
    legacy = deepcopy(payload)
    legacy["task_clause_contract"] = "single-predicate-clauses-v1"
    assert validate_clause_reviews(raw, [claim], legacy)


def test_complete_coordinated_condition_remains_reviewable():
    from test_task_clauses import review_fixture

    from packages.agents.writer.task_clauses import validate_clause_reviews

    claim, payload, raw = review_fixture(
        "If A and B hold, guests can vote; except on archived boards."
    )
    payload["task_clause_contract"] = "semantic-target-clauses-v2"
    for clause in raw["atomicity"][0]["clauses"]:
        clause["independent_predicate"] = True
    assert validate_clause_reviews(raw, [claim], payload)


def test_semantic_feedback_distinguishes_reselect_from_rewrite():
    from packages.agents.writer.task_semantics import repair_directive

    for code, action in [
        ("task_support_semantic_mismatch", "reselect"),
        ("no_complete_task_support", "reselect"),
        ("task_generation_insufficient_evidence", "reselect"),
        ("task_contains_sibling_predicate", "rewrite"),
    ]:
        result = repair_directive(task(), [code], "CPU billing; runtime limit.")
        assert result["action"] == action and result["instruction"]
        assert result["failed_predicate"] == task()["question_quote"]
        assert result["failed_clauses"]


@pytest.mark.asyncio
async def test_real_transports_reselect_semantic_failure_and_preserve_private_peer(monkeypatch):
    import json

    from claim_review_fixture import expand_prompt_payload
    from test_question_atomic_delivery import atomic_case, supported_review
    from test_task_support_selection import append_response

    from packages.agents.writer.question_atomic_delivery import (
        execute_question_atomic_delivery,
        replay_atomic_delivery,
    )

    case = await atomic_case(
        [
            "Guests can only be invited to one vault at a time.",
            "Guests only have access to one vault at a time.",
            "Guests have no personal area.",
        ],
        question=(
            "Example Product：访客已接受邀请并被确认。他能同时加入两个共享保险库吗？"
            "访客有私人区域吗？"
        ),
    )
    service, record, _, selected, view, use, packets, boundaries, allowed = case
    seen = []

    async def model(record, **kwargs):
        p = expand_prompt_payload(json.loads(kwargs["user"].partition("\nJSON:\n")[2]))
        name = kwargs["name"]
        seen.append((name, p))
        if name.endswith("support_selection"):
            t = p["tasks"][0]
            access = "共享" in t["question_quote"]
            term = "access" if access else "personal"
            ref = next(
                s["support_ref"]
                for f in p["evidence_view"]["facts"]
                for s in f["source_span_candidates"]
                if term in s["quote"]
            )
            if access and p["task_attempt"] == 0:
                # Deliberately propose a server-blocked reference even when it
                # is absent from the real selectable catalog.
                ref = next(c["support_ref"] for group in p["support_applicability"]
                           for c in group["candidates"] if not c["applicable"])
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
        elif name.endswith("atomic_generation"):
            t = p["generation_tasks"][0]
            selected_support = p["task_support_selections"][0]
            data = dict(
                version=1,
                task_id=t["task_id"],
                status="generated",
                atom=dict(
                    text=selected_support["supports"][0]["quote"],
                    kind="fact",
                    support_refs=selected_support["support_refs"],
                ),
            )
        else:
            data = dict(
                reviews=[supported_review(c) for c in p["claims"]],
                atomicity=[
                    dict(
                        claim_id=c["id"],
                        predicate_count=1,
                        clauses=[
                            dict(
                                clause_id=x["clause_id"],
                                role="assertion",
                                independent_predicate=True,
                                task_match=True,
                                verdict="supported",
                                support_refs=p["clause_support_refs"],
                            )
                            for x in p["clause_inventory"][i]["clauses"]
                        ],
                    )
                    for i, c in enumerate(p["claims"])
                ],
            )
        return append_response(service, record, kwargs, json.dumps(data))

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
        task_clause_contract="semantic-target-clauses-v2",
        answer_review_contract="task-outcomes-v1",
    )
    selections = [p for n, p in seen if n.endswith("support_selection")]
    for p in selections:
        if p["task_predicates"][0]["semantic_target"]["relation"] == "current_access":
            candidates = [s for f in p["evidence_view"]["facts"]
                          for s in f.get("source_span_candidates", ())]
            assert not any("invited" in s["quote"] for s in candidates)
            assert any("invited" in str(f["source_restrictions"])
                       for f in p["evidence_view"]["facts"])
    repairs = [p for p in selections if p["task_attempt"] == 1]
    assert len(selections) == 3 and len(repairs) == 1
    assert repairs[0]["repair_feedback"]["directive"]["action"] == "reselect"
    assert repairs[0]["repair_feedback"]["prior_transports"][0]["full_output_sha256"]
    assert not any("selection_reuse" in p for _, p in seen)
    assert len(result["reviews"]) == 2
    assert all("source_scopes" in p for _, p in seen if p.get("evidence_view"))
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    replay = replay_atomic_delivery(service, record.detail, case[2], use, view)
    assert replay["claims"] == result["claims"]


@pytest.mark.parametrize(
    "question",
    [
        "能否确定他一定免费或一定计费？",
        "Does this role determine whether the member is billable?",
    ],
)
def test_billability_target_rejects_navigation_but_retains_rule_plus_navigation(question):
    from packages.agents.writer.task_semantics import selection_reasons, semantic_target

    target = semantic_target(task(question), {})
    navigation = "To understand if a reader is billable, check out the page on billable members."
    rule = "A reader can be a billable workspace member, or a non-billable single-project guest."
    assert target["relation"] == "billability"
    for quote in (
        navigation,
        "要了解该角色是否计费，请查看计费成员页面。",
        "For details, see whether a member is billable in the billing guide.",
    ):
        assert selection_reasons(target, ["s"], dict(s=dict(quote=quote))) == (
            "task_support_semantic_mismatch",
        )
    for quote in (rule, rule + " " + navigation, rule + ", see the billing guide for details."):
        assert not selection_reasons(target, ["s"], dict(s=dict(quote=quote)))


def test_reselect_directive_uses_current_semantic_target():
    from packages.agents.writer.task_semantics import repair_directive

    result = repair_directive(
        dict(task(), semantic_target=dict(relation="billability")),
        ["task_support_semantic_mismatch"],
    )
    assert "billab" in result["instruction"].casefold()
    assert "invitation" not in result["instruction"].casefold()


def test_invitation_to_join_is_not_current_access_state():
    from packages.agents.writer.task_semantics import selection_reasons

    choices = dict(s=dict(quote="Guests can only be invited to join one shared resource."))
    assert selection_reasons(dict(relation="current_access"), ["s"], choices) == (
        "task_support_semantic_mismatch",
    )
    assert not selection_reasons(dict(relation="invitation"), ["s"], choices)
    choices["s"]["quote"] += " Confirmed guests only have access to one shared resource."
    assert not selection_reasons(dict(relation="current_access"), ["s"], choices)


def test_requested_cross_resource_automatic_decision_is_propagation_target():
    from packages.agents.writer.task_semantics import semantic_target

    assert semantic_target(task("A 上这次改权是否自动决定他在 B 的权限？"), {})["relation"] == (
        "resource_propagation"
    )


def test_repair_diagnostics_are_utf8_bounded_and_retain_failed_text_identity():
    import hashlib
    import json

    from packages.agents.writer.task_semantics import repair_directive

    text = "CPU计费依赖；" + "额外运行时清单每次调用限制20秒" * 3000
    result = repair_directive(
        dict(task(), semantic_target=dict(relation="cpu_billing_dependency")),
        ["task_contains_sibling_predicate"],
        text,
    )
    assert len(json.dumps(result, ensure_ascii=False).encode()) <= 1600
    assert result["failed_text_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert result["failed_text_bytes"] == len(text.encode())
    assert result["instruction"] and result["failed_clauses"]
    for clause in result["failed_clauses"]:
        original = text[clause["start"] : clause["end"]]
        assert clause["quote_sha256"] == hashlib.sha256(original.encode()).hexdigest()
        assert clause["quote_excerpt"] in original


def test_cpu_scope_version_number_is_not_a_rate_or_runtime_list():
    from packages.agents.writer.task_clauses import target_reasons

    task = dict(
        focus="billing_inputs",
        question_quote="Compute 2 Standard 的完整账单？",
        selection_target="applicable_sourced_cpu_billing_dependency",
        missing_billing_inputs=["cpu_usage"],
        semantic_target=dict(relation="cpu_billing_dependency"),
    )
    assert not target_reasons(task, "Compute 2 Standard 的账单还需要 CPU 用量输入。", "Example")


@pytest.mark.parametrize(
    "text",
    [
        "Compute Standard CPU time is billed at 0.02 per million milliseconds.",
        "Compute Standard includes 100 CPU milliseconds as its monthly allowance.",
        "CPU billing depends on usage; each invocation is limited to 20 seconds.",
    ],
)
def test_cpu_target_still_rejects_numeric_rates_allowances_and_runtime(text):
    from packages.agents.writer.task_semantics import assertion_reasons

    assert assertion_reasons(dict(relation="cpu_billing_dependency"), text) == (
        "task_contains_sibling_predicate",
    )


@pytest.mark.asyncio
async def test_fresh_generation_keeps_one_complete_task_and_selected_support_projection():
    from test_task_target_delivery import target_case

    case, _, gen = await target_case(semantic_contract=True)
    assert not {"current_task", "selected_support", "task_predicates"} & gen.keys()
    task = gen["generation_tasks"][0]
    selection = gen["task_support_selections"][0]
    assert task["semantic_target"]["relation"] == "cpu_billing_dependency"
    assert task["support_refs"] == selection["support_refs"]
    assert task["question_quote"] == case[6][0]["questions"][0]["question"]
    source_ids = {f["source_id"] for f in gen["evidence_view"]["facts"]}
    assert set(gen["source_scopes"]) == source_ids
    assert all(s["quote"] for s in selection["supports"])


@pytest.mark.asyncio
async def test_large_utf8_failed_draft_repairs_with_complete_task_quote_scope_and_replays(
    monkeypatch,
):
    import json

    from test_task_clauses import clause_run

    from packages.agents.writer.question_atomic_delivery import replay_atomic_delivery
    from packages.agents.writer.task_clauses import user_bytes

    failed = (
        "Guests have no personal area and may access only one collection. "
        + "额外运行时清单" * 3000
    )
    case, result, seen = await clause_run(
        monkeypatch,
        fail_first=True,
        task_clause_contract="semantic-target-clauses-v2",
        failed_first_text=failed,
    )
    repairs = [p for n, p in seen if n.endswith("atomic_generation") and p["task_attempt"]]
    assert len(repairs) == 1 and user_bytes(repairs[0]) <= 14000
    repair = repairs[0]
    original = next(
        p
        for n, p in seen
        if n.endswith("atomic_generation")
        and not p["task_attempt"]
        and p["generation_tasks"][0]["task_id"] == repair["generation_tasks"][0]["task_id"]
    )
    for key in (
        "generation_tasks",
        "evidence_view",
        "source_scopes",
        "request_context",
        "task_support_selections",
    ):
        assert repair[key] == original[key]
    assert (
        len(json.dumps(repair["repair_feedback"]["directive"], ensure_ascii=False).encode()) <= 1600
    )
    assert any(
        json.loads(s.full_output).get("atom", {}).get("text") == failed
        for s in case[1].detail.trace_spans
        if s.name.endswith("atomic_generation")
    )
    assert len(result["reviews"]) == 2
    use = next(u for u in case[1].detail.evidence_consumptions if u.id == case[5].id)
    replay = replay_atomic_delivery(case[0], case[1].detail, case[2], use, case[4])
    assert replay["claims"] == result["claims"]
