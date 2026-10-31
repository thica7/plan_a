"""Published task decisions and current question obligations share one scope."""

from types import SimpleNamespace

import pytest


def test_only_explicit_auxiliary_tasks_leave_user_obligation_denominator():
    from packages.agents.writer.task_answer_outcomes import aggregate

    q = dict(question_id="q", question="Can a guest vote on A and B?")
    tasks = [
        dict(task_id=t, question_id="q", question_quote=t, focus="vote", obligation_role=role)
        for t, role in [("a", "request"), ("b", "request"), ("rule", "support_dependency")]
    ]
    claims = [SimpleNamespace(id=t, text=f"Guest may vote on {t}.") for t in ("a", "b")]
    rows = {t: dict(outcome="yes", claim_ids=[t]) for t in ("a", "b")}
    answer = aggregate([q], tasks, rows, claims)["q"]
    assert answer.status == "answered" and len(answer.subquestion_bindings) == 2
    tasks[-1].pop("obligation_role")
    assert aggregate([q], tasks, rows, claims)["q"].status == "partial"


def test_auxiliary_role_is_derived_from_resource_dependency_not_focus_prefix():
    from packages.agents.writer.task_semantics import classify_obligations

    tasks = [
        dict(task_id="r", question_id="q", focus="rule_vote"),
        dict(task_id="a", question_id="q", focus="vote", resource="A"),
        dict(task_id="b", question_id="q", focus="vote", resource="B"),
    ]
    classified = classify_obligations(tasks)
    assert classified[0]["obligation_role"] == "support_dependency"
    assert classified[1]["dependency_task_ids"] == ["r"]
    assert classify_obligations(tasks[:1])[0]["obligation_role"] == "request"


def test_authenticated_selected_inference_is_visible_in_observations(monkeypatch):
    from packages.agents.writer.answer_presentation import observation_claims
    from packages.agents.writer.task_answer_outcomes import TaskOutcomeAuthority

    answer = SimpleNamespace(
        status="answered", answer="A bounded no.", claim_ids=["c"], question_id="q"
    )
    item = SimpleNamespace(status="supported", claim=SimpleNamespace(id="c", kind="inference"))
    audit = SimpleNamespace(
        claims=[item],
        answer_coverage=[answer],
        answer_review_contract="task-outcomes-v1",
        claim_review_version=0,
    )
    context = SimpleNamespace(compact=dict(task_clause_contract="semantic-target-clauses-v2"))
    monkeypatch.setattr(
        "packages.agents.writer.question_atomic_delivery.replay_decision_reviews",
        lambda *a: {"q": TaskOutcomeAuthority(answer, context)},
    )
    assert observation_claims(SimpleNamespace(), audit) == (item,)
    monkeypatch.setattr(
        "packages.agents.writer.question_atomic_delivery.replay_decision_reviews", lambda *a: {}
    )
    assert observation_claims(SimpleNamespace(), audit) == ()


def test_authenticated_and_counterexample_has_one_shared_qa_coverage_contract():
    from packages.agents.writer.atomic_question_projection import generation_tasks
    from packages.agents.writer.task_answer_outcomes import conjunction_coverage

    q = dict(
        question_id="q",
        question="Example：3 个人用 3 个 collections 共享密码。这个免费组织能满足吗？",
    )
    tasks = generation_tasks(q, "Example/feature")
    credential = SimpleNamespace(
        witness_kind="quantity_excess",
        conclusion="no",
        claim_id="c",
        task_id=tasks[-1]["task_id"],
        question_id="q",
        binding_sha256="verified",
    )
    answer = SimpleNamespace(
        question=q["question"],
        status="answered",
        conclusion="no",
        question_id="q",
        claim_ids=["c"],
        decision_credentials=[credential],
    )
    projection = conjunction_coverage(answer, tasks)
    assert projection["kind"] == "pure_quantity_conjunction_counterexample"
    assert projection["covered_task_ids"] == [t["task_id"] for t in tasks]
    assert projection["witness_claim_id"] == "c"
    answer.question = q["question"].replace("用", "或用")
    assert conjunction_coverage(answer, tasks) is None


def test_qa_semantic_system_preserves_legacy_identity_and_explicit_counterexample_scope():
    from packages.agents.qa.independent_question_review import (
        INDEPENDENT_SYSTEM,
        final_review_system,
    )

    assert final_review_system(dict(findings=[dict(question_id="q")])) == INDEPENDENT_SYSTEM
    system = final_review_system(dict(question_contexts=dict(current=dict(
        task_semantic_contract="semantic-target-clauses-v2"))))
    assert "pure AND" in system and "independent requests" in system
    assert "never a source verdict" in system
    assert len(system.encode()) <= len(INDEPENDENT_SYSTEM.encode())


@pytest.mark.asyncio
async def test_fresh_clarification_replay_has_canonical_empty_fact_entry(monkeypatch):
    from test_question_atomic_delivery import atomic_case

    from packages.agents.writer.question_atomic_delivery import (
        execute_question_atomic_delivery,
        replay_atomic_delivery,
    )

    case = await atomic_case(
        ["Deleting an account permanently deletes all vault data."],
        question="Example Product：我们准备把离职同事删掉，他保存的密码之后还会留下吗？",
    )

    async def forbidden(*args, **kwargs):
        pytest.fail("A server-only clarification must not call generation")

    monkeypatch.setattr(case[0], "_trace_llm_text", forbidden)
    await execute_question_atomic_delivery(
        case[0],
        case[1],
        case[3],
        case[4],
        case[5],
        case[6][0]["questions"],
        case[6],
        case[8],
        case[7],
        (),
        task_execution_policy="selected-task-atoms-v3",
        task_clause_contract="semantic-target-clauses-v2",
        answer_review_contract="task-outcomes-v1",
    )
    case[0]._validate_evidence_use(case[1], case[5])
    use = next(u for u in case[1].detail.evidence_consumptions if u.id == case[5].id)
    replay = replay_atomic_delivery(case[0], case[1].detail, case[2], use, case[4])
    assert replay["facts_by_question"] == {q["question_id"]: [] for q in case[6][0]["questions"]}
