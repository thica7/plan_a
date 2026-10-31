"""Task-local selection and generation use real, replayable transports."""

import json

import pytest
from claim_review_fixture import expand_prompt_payload
from test_question_atomic_delivery import atomic_case, supported_review
from test_task_support_selection import append_response

POLICY = "selected-task-atoms-v1"
SELECT = "dimension_question_task_support_selection"


async def run_tasks(
    monkeypatch,
    *,
    bad_task=None,
    texts=None,
    question=None,
    first_selection_transport_error=False,
    execution_policy=POLICY,
    deny_repair_generation=False,
    repair_with_feedback=False,
    unsupported_task=None,
):
    from packages.agents.writer.question_atomic_delivery import execute_question_atomic_delivery
    from packages.research.question_scope import research_questions

    case = await atomic_case(
        texts
        or ["Guests have no personal area.", "Guests may access only one collection at a time."],
        question=question or "Example Product：访客有私人区域吗？访客能同时加入两个容器吗？",
    )
    service, record, _, selected, view, use, packets, boundaries, allowed = case
    seen = []
    admission = service._llm_request_admission_error

    def checked_admission(record, **kwargs):
        if deny_repair_generation and kwargs["name"] == "dimension_question_atomic_generation":
            proposal = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
            if proposal.get("task_attempt") == 1:
                return "run_llm_budget_reserved_for_delivery"
        return admission(record, **kwargs)

    monkeypatch.setattr(service, "_llm_request_admission_error", checked_admission)

    async def model(record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        seen.append((kwargs["name"], payload))
        if kwargs["name"] == SELECT:
            task = payload["tasks"][0]
            request = task["question_quote"]
            term = (
                ("personal" if "私人" in request else "collection")
                if texts is None
                else (
                    "Workspace level"
                    if "层级" in request
                    else "individually"
                    if "自动" in request
                    else "Only"
                    if "谁" in request
                    else "billable"
                )
            )
            ref = next(
                s["support_ref"]
                for f in payload["evidence_view"]["facts"]
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
        elif kwargs["name"] == "dimension_question_atomic_generation":
            (task,) = payload["generation_tasks"]
            (selection,) = payload["task_support_selections"]
            quote = selection["supports"][0]["quote"]
            atoms = [
                dict(
                    task_id=task["task_id"],
                    text=quote,
                    kind="fact",
                    support_refs=selection["support_refs"],
                )
            ]
            if bad_task == task["task_id"] and not (
                repair_with_feedback and payload.get("repair_feedback")
            ):
                atoms.append(dict(atoms[0], text="Guests can export all data."))
            response = dict(
                question_plans=[
                    dict(question_id=task["question_id"], missing_fields=[], atoms=atoms)
                ]
            )
        elif kwargs["name"] == "dimension_question_atomic_review":
            response = dict(reviews=[supported_review(c) for c in payload["claims"]])
            if payload["task_context"]["task_id"] == unsupported_task and not any(
                p.get("task_attempt") == 1
                and p["generation_tasks"][0]["task_id"] == unsupported_task
                for name, p in seen if name == "dimension_question_atomic_generation"
            ):
                for row in response["reviews"]:
                    row.update(
                        verdict="unsupported", reason="Actual source condition omitted. " * 15
                    )
        else:
            raise AssertionError(kwargs["name"])
        answer = append_response(service, record, kwargs, json.dumps(response))
        if (
            first_selection_transport_error
            and kwargs["name"] == SELECT
            and sum(name == SELECT for name, _ in seen) == 1
        ):
            record.detail.trace_spans[-1].status = "error"
        return answer

    monkeypatch.setattr(service, "_trace_llm_text", model)
    result = await execute_question_atomic_delivery(
        service,
        record,
        selected,
        view,
        use,
        research_questions(record.detail, view.competitor, view.dimension),
        packets,
        allowed,
        boundaries,
        (),
        generation_projection_version=5,
        review_projection_version=3,
        delivery_policy="complete-predicates-v1",
        task_execution_policy=execution_policy,
    )
    return case, result, seen


@pytest.mark.asyncio
async def test_each_task_selects_before_one_claim_generation_and_replays(monkeypatch):
    from packages.agents.writer.question_atomic_delivery import replay_atomic_delivery

    case, result, seen = await run_tasks(monkeypatch)
    assert result["compact"]["task_execution_policy"] == POLICY
    gens = [p for name, p in seen if name == "dimension_question_atomic_generation"]
    assert len(gens) == 2
    assert len(result["claims"]) == len(result["reviews"]) == 2
    assert len({c.id for c in result["claims"]}) == 2
    assert all(len(p["generation_tasks"]) == 1 for p in gens)
    assert all(len(p["task_support_selections"]) == 1 for p in gens)
    use = next(u for u in case[1].detail.evidence_consumptions if u.id == case[5].id)
    replayed = replay_atomic_delivery(case[0], case[1].detail, case[2], use, case[4])
    assert replayed["claims"] == result["claims"]
    assert replayed["reviews"] == result["reviews"]


@pytest.mark.asyncio
async def test_unknown_policy_fails_without_any_transport(monkeypatch):
    from packages.agents.writer.question_atomic_delivery import execute_question_atomic_delivery

    case = await atomic_case()
    with pytest.raises(ValueError, match="policy"):
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
            task_execution_policy="foreign",
        )


def test_numeric_rule_uses_shared_single_unit_semantics_only_for_new_policy():
    from packages.agents.writer.selected_task_delivery import numeric_restriction_reasons

    assert not numeric_restriction_reasons(
        "访客只能访问一个保险库。", ["A guest can access only a single vault at a time."]
    )
    assert not numeric_restriction_reasons(
        "访客只能访问一个保险库。",
        [
            "They don't have their own private vaults and only have access to a single vault, "
            "which you choose."
        ],
    )
    assert numeric_restriction_reasons("最多两名用户。", ["Share with one other user."])
    assert numeric_restriction_reasons(
        "访客只能访问一个保险库。",
        ["After verification a guest can access only a single vault at a time."],
    )


@pytest.mark.asyncio
async def test_one_canonical_question_dispatches_all_four_independent_tasks(monkeypatch):
    from packages.agents.writer.question_atomic_delivery import replay_atomic_delivery

    texts = [
        "Observer cannot be set at Workspace level.",
        "An observer is set individually per member per board.",
        "Only board admins and Workspace admins can change a board member's status to Observer.",
        "An observer can be a billable Workspace member, or multi-board guest, "
        "or a non-billable single-board guest.",
    ]
    question = (
        "Example Product：假设 Workspace 已订阅 Premium，成员在 A 上是 Observer。"
        "能否在 Workspace 层级统一设置 Observer，A 上这次改权是否自动决定 B 的权限；"
        "谁有权把 A 的现有成员改为 Observer；只凭 Observer 标签能否确定他一定免费或一定计费？"
    )
    case, result, seen = await run_tasks(monkeypatch, texts=texts, question=question)
    assert len(case[6][0]["questions"]) == 1
    generations = [p for name, p in seen if name == "dimension_question_atomic_generation"]
    assert len(generations) == 4
    assert len({p["generation_tasks"][0]["task_id"] for p in generations}) == 4
    assert len({p["questions"][0]["question_id"] for p in generations}) == 1
    assert all(len(json.dumps(p, ensure_ascii=False).encode()) < 14000 for p in generations)
    assert len(result["claims"]) == len(result["reviews"]) == 4
    use = next(u for u in case[1].detail.evidence_consumptions if u.id == case[5].id)
    assert (
        replay_atomic_delivery(case[0], case[1].detail, case[2], use, case[4])["claims"]
        == result["claims"]
    )


@pytest.mark.asyncio
async def test_failed_task_repairs_locally_after_peer_first_attempt_and_preserves_peer(monkeypatch):
    _, initial, _ = await run_tasks(monkeypatch)
    failed = initial["compact"]["question_answer_plans"][0]["task_results"][0]["task_id"]
    case, result, seen = await run_tasks(monkeypatch, bad_task=failed)
    gens = [p for name, p in seen if name == "dimension_question_atomic_generation"]
    assert [p["task_attempt"] for p in gens] == [0, 0, 1]
    assert gens[-1]["generation_tasks"][0]["task_id"] == failed
    assert len(result["claims"]) == len(result["reviews"]) == 1
    assert (
        result["claims"][0].id == initial["claims"][1].id
        or result["claims"][0].text == initial["claims"][1].text
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["task", "ref", "transport", "policy"])
async def test_task_delivery_replay_rejects_changed_identity_and_transport(monkeypatch, fault):
    from packages.agents.writer.question_atomic_delivery import replay_atomic_delivery

    case, _, _ = await run_tasks(monkeypatch)
    span = next(
        s for s in case[1].detail.trace_spans if s.name == "dimension_question_atomic_generation"
    )
    if fault == "transport":
        span.full_output += " "
    elif fault == "policy":
        receipt = next(
            s for s in case[1].detail.trace_spans if s.name == "question_atomic_delivery"
        )
        payload = json.loads(receipt.full_output)
        payload["task_execution_policy"] = "foreign"
        receipt.full_output = json.dumps(payload)
    else:
        prefix, raw = span.full_input.split("\nJSON:\n", 1)
        payload = expand_prompt_payload(json.loads(raw))
        if fault == "task":
            payload["generation_tasks"][0]["task_id"] = "foreign"
        else:
            payload["task_support_selections"][0]["support_refs"] = ["s999"]
        span.full_input = prefix + "\nJSON:\n" + json.dumps(payload)
    use = next(u for u in case[1].detail.evidence_consumptions if u.id == case[5].id)
    with pytest.raises(ValueError):
        replay_atomic_delivery(case[0], case[1].detail, case[2], use, case[4])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "Workers Standard includes 30 million CPU milliseconds monthly "
        "and each invocation has a 5 minute limit.",
        "Workers Paid has a $5 monthly minimum and all included usage resets monthly.",
    ],
)
async def test_billing_task_rejects_independent_runtime_or_unselected_universal_rule(
    monkeypatch, text
):
    from packages.agents.writer.selected_task_delivery import task_predicate_reasons

    assert task_predicate_reasons(
        dict(focus="billing_inputs"), text, ["Workers Paid has a $5 monthly minimum."]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("applicable", [True, False])
async def test_bill_selection_targets_only_an_admitted_applicable_missing_cpu_dependency(
    applicable,
):
    from test_writer_question_delivery import billing_original

    from packages.agents.writer.atomic_question_projection import generation_tasks
    from packages.agents.writer.selected_task_delivery import candidate_context, selection_context

    quote, conditions, table = billing_original()
    if not applicable:
        conditions = [c.replace("Compute Paid", "Other Paid") for c in conditions]
    case = await atomic_case(
        [quote],
        question="Example Product Compute Paid Standard 本月有2300万次请求，账单准确是多少美元？",
        source_qualifiers=[dict(condition_evidence=conditions, table_context=table)],
    )
    question = case[6][0]["questions"][0]
    task = generation_tasks(question, "Example Product/feature")[0]
    payload = candidate_context(
        case[0], case[1], case[4], case[6], question, case[8], case[5], task["task_id"]
    )
    selector, _ = selection_context(payload, case[4])
    gaps = selector["task_predicates"][0].get("missing_billing_inputs", [])
    assert gaps == (["cpu_usage"] if applicable else [])
    if applicable:
        assert selector["task_predicates"][0]["required_support_refs"]


def test_invocation_limit_keeps_all_same_unit_alternatives_in_the_selected_rule():
    from packages.agents.writer.selected_task_delivery import task_predicate_reasons

    quote = (
        "The maximum CPU time per invocation is 5 minutes (default: 30 seconds); "
        "Cron or Queue invocations have a maximum of 15 minutes."
    )
    task = dict(focus="source_rule")
    assert task_predicate_reasons(task, "单次调用 CPU 时间上限为5分钟。", [quote])
    assert not task_predicate_reasons(
        task, "单次调用 CPU 时间上限为5分钟（默认30秒），Cron或Queue调用上限为15分钟。", [quote]
    )


async def reviewed_scenario(
    monkeypatch, *, quantity=False, execution_policy=POLICY, repair=False, tight_budget=False,
    bad_task_review=False,
):
    from test_task_decision_witnesses import INFERENCE, QUESTION, SOURCE

    from packages.agents.writer import question_atomic_delivery as atomic
    from packages.agents.writer.dimension_writer import render_dimension_report
    from packages.research.evidence.report_claims import ReportDimensionAudit, audit_report_claims

    texts = (
        [SOURCE]
        if quantity
        else [
            "A guest can only be invited to a single vault at a time, but you can remove them "
            "from one vault, then add them to a different one.",
            "They don't have their own private vaults and only have access to a single vault, "
            "which you choose.",
        ]
    )
    question = (
        QUESTION.replace("Bitwarden", "Example Product")
        if quantity
        else (
            "Example Product：在 Families 中，访客已接受邀请并被确认。"
            "他能同时加入两个共享保险库，或者拥有自己的 Private vault 吗？"
        )
    )
    case = await atomic_case(texts, question=question)
    service, record, snapshot, selected, view, use, packets, boundaries, allowed = case
    record.detail.report_answer_boundaries = boundaries
    seen = []
    first_task = None

    async def model(record, **kwargs):
        nonlocal first_task
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        seen.append((kwargs["name"], payload))
        if kwargs["name"] == SELECT:
            task = payload["tasks"][0]
            if quantity and task.get("request_property") == "people_limit":
                data = dict(
                    selections=[
                        dict(
                            task_id=task["task_id"],
                            status="insufficient_evidence",
                            binding_kind=None,
                            support_refs=[],
                        )
                    ]
                )
            else:
                desired = (
                    SOURCE if quantity else texts[1 if "Private" in task["question_quote"] else 0]
                )
                ref = next(
                    s["support_ref"]
                    for row in payload["evidence_view"]["facts"]
                    for s in row["source_span_candidates"]
                    if s["quote"] == desired
                )
                data = dict(
                    selections=[
                        dict(
                            task_id=task["task_id"],
                            status="selected",
                            binding_kind="span",
                            support_refs=[ref],
                        )
                    ]
                )
        elif kwargs["name"] == atomic.GENERATION_NAME:
            task = payload["generation_tasks"][0]
            first_task = first_task or task["task_id"]
            text = (
                INFERENCE
                if quantity
                else (
                    "访客没有自己的 Private vault。"
                    if "Private" in task["question_quote"]
                    else "访客一次只能被邀请加入一个保险库。"
                )
            )
            data = dict(
                question_plans=[
                    dict(
                        question_id=task["question_id"],
                        missing_fields=[],
                        atoms=[
                            dict(
                                task_id=task["task_id"],
                                text=text,
                                kind="inference" if quantity else "fact",
                                support_refs=payload["task_support_selections"][0]["support_refs"],
                            )
                        ],
                    )
                ]
            )
            if repair and task["task_id"] == first_task and payload["task_attempt"] == 0:
                data["question_plans"][0]["atoms"] *= 2
        elif kwargs["name"] == atomic.REVIEW_NAME:
            data = dict(reviews=[supported_review(c) for c in payload["claims"]])
            if payload.get("task_execution_policy") == "selected-task-atoms-v3":
                data["atomicity"] = [dict(
                    claim_id=c["id"], predicate_count=1, clauses=[dict(
                        quote=c["text"], predicate=payload["task_context"]["focus"],
                        task_match=True,
                    )],
                ) for c in payload["claims"]]
            if tight_budget:
                budget = service._run_llm_budget(record)
                budget.max_calls = 48
                budget.max_tokens = 160000
                budget.tokens_used = 120000
                budget.delivery_reserves["final_qa:run"] = 12000
                for phase, amount in budget.delivery_reserves.items():
                    if phase not in {"answer:Example Product/feature", "final_qa:run"}:
                        budget.delivery_charged[phase] = amount
        else:
            assert kwargs["name"] == atomic.ANSWER_NAME
            if payload.get("task_outcome_contract") == "task-outcomes-v1":
                data = dict(version=1, task_reviews=[dict(
                    task_id=t["task_id"], outcome="no" if t["support_choices"] else "unknown",
                    support_refs=[r["ref"] for r in t["support_choices"] if r["primary"]],
                    missing_fields=[], reason="Independent complete task review.",
                ) for t in payload["tasks"]])
                if bad_task_review and not payload.get("repair_feedback"):
                    data["task_reviews"][0]["missing_fields"] = ["data_ownership"]
                return append_response(service, record, kwargs, json.dumps(data))
            q = payload["questions"][0]
            ids = [c["id"] for c in payload["claims"]]
            if quantity:
                data = dict(
                    version=3,
                    answers=[
                        dict(
                            question_id=q["question_id"],
                            status="partial",
                            resolution="conditional",
                            conclusion="depends",
                            claim_ids=ids,
                            missing_fields=[],
                            reason=(
                                "The separately reviewed quantity bound denies the joint request."
                            ),
                            subquestions=[
                                dict(
                                    question_quote=q["question"],
                                    claim_ids=ids,
                                    conclusion="depends",
                                    relation="upper_bound",
                                )
                            ],
                        )
                    ],
                    task_decisions=[
                        dict(
                            candidate_ref=c["candidate_ref"],
                            task_fulfilled=True,
                            target_grounding="supported",
                            conclusion="no",
                            evidence_refs=c["evidence_refs"],
                            scenario_refs=c["scenario_refs"],
                        )
                        for c in payload["decision_candidates"]
                    ],
                )
            else:
                first, second = q["question"].split("或者", 1)
                container = [c["id"] for c in payload["claims"] if "一次" in c["text"]]
                private = [c["id"] for c in payload["claims"] if "Private" in c["text"]]
                data = dict(
                    version=3,
                    answers=[
                        dict(
                            question_id=q["question_id"],
                            status="answered",
                            resolution="direct",
                            conclusion="no",
                            claim_ids=ids,
                            missing_fields=[],
                            reason=(
                                "Both independently reviewed rules deny the corresponding request."
                            ),
                            subquestions=[
                                dict(
                                    question_quote=first,
                                    claim_ids=container,
                                    conclusion="no",
                                    relation="upper_bound",
                                ),
                                dict(
                                    question_quote="或者" + second,
                                    claim_ids=private,
                                    conclusion="no",
                                    relation="explicit_negative",
                                ),
                            ],
                        )
                    ],
                    task_decisions=[],
                )
        return append_response(service, record, kwargs, json.dumps(data))

    monkeypatch.setattr(service, "_trace_llm_text", model)
    result = await atomic.execute_question_atomic_delivery(
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
        answer_review_contract=("task-outcomes-v1" if execution_policy == "selected-task-atoms-v3"
                                else "subquestion-premises-v6"),
        delivery_policy="complete-predicates-v1",
        task_execution_policy=execution_policy,
    )
    audited = audit_report_claims(
        result["claims"],
        result["reviews"],
        view,
        boundaries,
        available_facts=view.facts,
        review_version=3,
    )
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    answers, _, _ = await service._dimension_question_coverage(
        record, packets[0]["questions"], result["compact"], audited, view, use, ()
    )
    audit = ReportDimensionAudit(
        competitor=view.competitor,
        dimension=view.dimension,
        consumption_id=use.id,
        claims=audited,
        answer_coverage=answers,
        answer_binding_version=3,
        claim_review_version=3,
        answer_review_contract=("task-outcomes-v1" if execution_policy == "selected-task-atoms-v3"
                                else "subquestion-premises-v6"),
        question_atomic_contract=atomic.CONTRACT,
        question_atomic_receipt_digest=result["compact"]["question_atomic_receipt_digest"],
    )
    record.detail.report_dimension_audits = [audit]
    record.detail.report_md = render_dimension_report(record.detail, [audit], snapshot=snapshot)
    return case, result, audit, seen, use


@pytest.mark.asyncio
@pytest.mark.parametrize("quantity", [False, True])
async def test_reviewed_task_results_reach_answer_render_replay_and_qa(monkeypatch, quantity):
    from packages.agents.qa.question_reconciliation import _answer_support
    from packages.agents.writer.question_atomic_delivery import replay_atomic_delivery

    case, result, audit, seen, use = await reviewed_scenario(monkeypatch, quantity=quantity)
    answer = audit.answer_coverage[0]
    assert (answer.status, answer.conclusion) == ("answered", "no"), answer
    assert all(row.status == "supported" for row in audit.claims)
    if quantity:
        assert answer.decision_credentials
        assert result["compact"]["decision_selection_policy"] == "reviewed_quantity_conjunction-v1"
    else:
        assert len(answer.subquestion_bindings) == 2
        assert all(b.conclusion == "no" for b in answer.subquestion_bindings)
        assert len(answer.claim_ids) == 2
    assert "结论：否" in case[1].detail.report_md
    assert _answer_support(case[1].detail, case[2], audit, answer, case[6][0]["questions"][0])
    replayed = replay_atomic_delivery(case[0], case[1].detail, case[2], use, case[4], audit=audit)
    assert replayed["answers"][answer.question_id] == answer


@pytest.mark.parametrize(
    "checkpoint,expected",
    [({}, 4), ({"calls": 6}, 1), ({"delivery_call_limit:answer:Example Product/feature": 1}, 1)],
)
def test_new_answer_call_floor_protects_all_questions_without_upgrading_checkpoints(
    checkpoint, expected
):
    from packages.agents.writer.selected_task_delivery import protect_answer_calls
    from packages.llm.execution_budget import RunLLMBudget

    phase = "answer:Example Product/feature"
    budget = RunLLMBudget(
        max_calls=48,
        max_repairs=1,
        calls=41,
        delivery_reserves={phase: 12000, "final_qa:run": 12000},
        delivery_call_reserves={phase: 1, "final_qa:run": 5},
        delivery_charged={phase: 123},
        delivery_calls={phase: 0},
    )
    protect_answer_calls(budget, checkpoint, phase, 4)
    assert budget.delivery_call_reserves[phase] == expected
    assert budget.delivery_charged[phase] == 123
    if not checkpoint:
        assert budget.admission_error(is_repair=False, phase="writer:Example Product/feature")


@pytest.mark.asyncio
@pytest.mark.parametrize("execution_policy", [POLICY, "selected-task-atoms-v2"])
async def test_successfully_reviewed_task_cannot_acquire_a_repair_transport(
    monkeypatch, execution_policy
):
    from copy import deepcopy
    from types import SimpleNamespace

    from packages.agents.writer.dimension_writer import compact_prompt_json
    from packages.agents.writer.question_atomic_delivery import digest
    from packages.agents.writer.selected_task_delivery import rebuild

    case, result, _ = await run_tasks(monkeypatch, execution_policy=execution_policy)
    compact = deepcopy(result["compact"])
    original = compact["dispatches"][0]
    system, payload = deepcopy(compact["_decision_expected_inputs"][original["span_id"]])
    payload["task_attempt"] = 1
    span = next(s for s in case[1].detail.trace_spans if s.id == original["span_id"]).model_copy(
        update={
            "id": "extra-repair",
            "full_input": system + "\n\n\nJSON:\n" + compact_prompt_json(payload),
        }
    )
    dispatch = dict(
        original,
        span_id=span.id,
        attempt=1,
        full_input_sha256=digest(span.full_input),
        full_output_sha256=digest(span.full_output),
    )
    compact["dispatches"].append(dispatch)
    compact["_decision_expected_inputs"][span.id] = system, payload
    context = SimpleNamespace(
        compact=compact,
        expected_inputs=compact["_decision_expected_inputs"],
        trace_spans=[*case[1].detail.trace_spans, span],
        facts=case[4].facts,
        questions=case[6][0]["questions"],
        consumption_id=case[5].id,
        snapshot_id=case[2].id,
        competitor=case[4].competitor,
        dimension=case[4].dimension,
        audited_claims=(),
    )
    with pytest.raises(ValueError, match="repair"):
        rebuild(context)


@pytest.mark.asyncio
async def test_unverified_first_selection_stays_deferred_while_peer_delivers_and_replays(
    monkeypatch,
):
    from packages.agents.writer.question_atomic_delivery import replay_atomic_delivery

    case, result, seen = await run_tasks(monkeypatch, first_selection_transport_error=True)
    assert len(result["claims"]) == len(result["reviews"]) == 1
    assert all(d["attempt"] == 0 for d in result["compact"]["dispatches"])
    assert sum(name == SELECT for name, _ in seen) == 2
    first_task = result["compact"]["question_answer_plans"][0]["task_results"][0]
    assert first_task["state"] == "deferred"
    use = next(u for u in case[1].detail.evidence_consumptions if u.id == case[5].id)
    replayed = replay_atomic_delivery(case[0], case[1].detail, case[2], use, case[4])
    assert replayed["claims"] == result["claims"]
