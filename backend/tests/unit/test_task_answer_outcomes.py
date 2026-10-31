"""A task verdict has one authority; parent metadata is never model-authored."""

import json

import pytest


def payload():
    return dict(
        task_outcome_contract="task-outcomes-v1",
        tasks=[
            dict(
                task_id="a",
                question_id="q",
                allowed_missing_fields=[],
                support_choices=[dict(ref="a1", claim_id="ca", primary=True, quote_refs=["qa"])],
            ),
            dict(
                task_id="b",
                question_id="q",
                allowed_missing_fields=[],
                support_choices=[dict(ref="b1", claim_id="cb", primary=True, quote_refs=["qb"])],
            ),
        ],
    )


def row(tid="a", **changes):
    return (
        dict(
            task_id=tid,
            outcome="no",
            support_refs=[tid + "1"],
            missing_fields=[],
            reason="Independently reviewed.",
        )
        | changes
    )


def test_cross_task_refs_and_foreign_clarification_do_not_delete_valid_peer():
    from packages.agents.writer.task_answer_outcomes import parse_task_reviews

    raw = json.dumps(dict(version=1, task_reviews=[row(support_refs=["b1"]), row("b")]))
    accepted, failures = parse_task_reviews(raw, payload())
    assert list(accepted) == ["b"] and "a" in failures


def test_foreign_task_row_is_rejected_without_erasing_a_valid_current_peer():
    from packages.agents.writer.task_answer_outcomes import parse_task_reviews

    accepted, failures = parse_task_reviews(
        json.dumps(dict(version=1, task_reviews=[row("foreign"), row("b")])), payload()
    )
    assert list(accepted) == ["b"] and "a" in failures
    raw = json.dumps(
        dict(version=1, task_reviews=[row(missing_fields=["data_ownership"]), row("b")])
    )
    accepted, failures = parse_task_reviews(raw, payload())
    assert list(accepted) == ["b"] and "a" in failures


@pytest.mark.parametrize("fault", ["duplicate", "missing", "source", "old_raw"])
def test_task_review_rejects_duplicate_missing_unreviewed_and_old_contract(fault):
    from packages.agents.writer.task_answer_outcomes import parse_task_reviews

    rows = [row(), row("b")]
    if fault == "duplicate":
        rows.append(row())
    elif fault == "missing":
        rows.pop(0)
    elif fault == "source":
        rows[0]["support_refs"] = ["raw-source-quote"]
    raw = (
        json.dumps(dict(version=3, answers=[], task_decisions=[]))
        if fault == "old_raw"
        else json.dumps(dict(version=1, task_reviews=rows))
    )
    accepted, failures = parse_task_reviews(raw, payload())
    assert "a" in failures
    assert "a" not in accepted


def test_explicit_two_predicates_remains_rejected_even_when_review_says_supported():
    from packages.agents.writer.task_answer_outcomes import validate_atomicity

    claim = dict(id="c", text="Guests have no private vault and can access one vault.")
    raw = json.dumps(
        dict(
            atomicity=[
                dict(
                    claim_id="c",
                    predicate_count=2,
                    clauses=[dict(quote=claim["text"], predicate="source_rule", task_match=True)],
                )
            ]
        )
    )
    assert not validate_atomicity(raw, [claim], dict(focus="source_rule"))


@pytest.mark.asyncio
@pytest.mark.parametrize("quantity", [False, True])
async def test_v3_actual_task_answer_render_replay_and_qa_share_one_authority(
    monkeypatch, quantity
):
    from test_selected_task_delivery import reviewed_scenario

    from packages.agents.qa.question_reconciliation import _answer_support
    from packages.agents.writer.question_atomic_delivery import replay_atomic_delivery

    case, result, audit, seen, use = await reviewed_scenario(
        monkeypatch, execution_policy="selected-task-atoms-v3", quantity=quantity
    )
    assert audit.answer_review_contract == "task-outcomes-v1"
    answer = audit.answer_coverage[0]
    assert (answer.status, answer.conclusion) == ("answered", "no")
    assert _answer_support(case[1].detail, case[2], audit, answer, case[6][0]["questions"][0])
    replayed = replay_atomic_delivery(case[0], case[1].detail, case[2], use, case[4], audit=audit)
    assert replayed["answers"][answer.question_id] == answer
    if quantity:
        assert answer.decision_credentials
    for name, p in seen:
        if name == "dimension_question_atomic_answer_review":
            assert "answers" not in p and p["task_outcome_contract"] == "task-outcomes-v1"


@pytest.mark.asyncio
async def test_v3_production_named_resource_outcomes_do_not_depend_on_modal_wording(monkeypatch):
    from dataclasses import replace

    from claim_review_fixture import expand_prompt_payload
    from test_question_atomic_delivery import atomic_case, supported_review
    from test_task_support_selection import append_response

    from packages.agents.qa.evidence_alignment import audit_dimension_claims
    from packages.agents.qa.question_reconciliation import _answer_support
    from packages.agents.writer.answer_action_scope import _ACTIONS
    from packages.agents.writer.subquestion_premises import _named_action_outcomes

    case = await atomic_case(
        ["Observers can vote on cards if card voting is enabled."],
        question="Example Product：小林在看板 A 和 B 都是 Observer；A 未启用投票，B 已启用投票。"
        "分别判断他能在 A、B 投票吗？",
    )
    service, record, snapshot = case[:3]
    service._settings = replace(service._settings, writer_question_atomic_enabled=True)

    async def model(record, **kwargs):
        p = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        name = kwargs["name"]
        if name.endswith("support_selection"):
            data = dict(
                selections=[
                    dict(
                        task_id=t["task_id"],
                        status="selected",
                        binding_kind="span",
                        support_refs=[
                            p["evidence_view"]["facts"][0]["source_span_candidates"][0][
                                "support_ref"
                            ]
                        ],
                    )
                    for t in p["tasks"]
                ]
            )
        elif name.endswith("atomic_generation"):
            t = p["generation_tasks"][0]
            text = (
                "看板 A 未启用卡片投票，因此小林在 A 上不能投票。"
                if t.get("resource") == "A"
                else "小林作为看板 B 的 Observer，因 B 已启用卡片投票，故可对 B 的卡片投票。"
                if t.get("resource") == "B"
                else p["task_support_selections"][0]["supports"][0]["quote"]
            )
            data = dict(
                question_plans=[
                    dict(
                        question_id=t["question_id"],
                        missing_fields=[],
                        atoms=[
                            dict(
                                task_id=t["task_id"],
                                text=text,
                                kind="inference" if t.get("resource") else "fact",
                                support_refs=p["task_support_selections"][0]["support_refs"],
                            )
                        ],
                    )
                ]
            )
        elif name.endswith("atomic_review"):
            data = dict(
                reviews=[supported_review(c) for c in p["claims"]],
                atomicity=[
                    dict(
                        claim_id=c["id"],
                        predicate_count=1,
                        clauses=[
                            dict(
                                quote=c["text"],
                                predicate=p["task_context"]["focus"],
                                task_match=True,
                            )
                        ],
                    )
                    for c in p["claims"]
                ],
            )
        else:
            data = dict(
                version=1,
                task_reviews=[
                    dict(
                        task_id=t["task_id"],
                        outcome="no"
                        if t.get("resource") == "A"
                        else "yes"
                        if t.get("resource")
                        else "rule",
                        support_refs=[c["ref"] for c in t["support_choices"] if c["primary"]],
                        missing_fields=[],
                        reason="Independent task outcome review.",
                    )
                    for t in p["tasks"]
                ],
            )
        return append_response(service, record, kwargs, json.dumps(data))

    monkeypatch.setattr(service, "_trace_llm_text", model)
    record.detail.report_md = await service._writer_dimension_report(record, 60)
    uses = [
        u
        for u in record.detail.evidence_consumptions
        if u.agent == "writer" and u.status in {"validated", "reused"}
    ]
    service._record_evidence_artifact(
        record,
        kind="writer",
        uses=uses,
        payload=service._writer_evidence_artifact_payload(record.detail),
    )
    audit = record.detail.report_dimension_audits[0]
    answer = audit.answer_coverage[0]
    assert (answer.status, answer.conclusion) == ("answered", "depends")
    b = next(c.claim for c in audit.claims if "故可" in c.claim.text)
    assert not _named_action_outcomes(b.text, ("A", "B"), _ACTIONS["vote"])
    assert b.id in answer.claim_ids and b.text in record.detail.report_md
    assert _answer_support(record.detail, snapshot, audit, answer, case[6][0]["questions"][0])
    assert service._final_qa_producer_verified(record, snapshot)
    assert not audit_dimension_claims(service, record, snapshot, producer_verified=True)
    from packages.agents.qa.question_context import question_context_blocks
    from packages.research.evidence.views import select_evidence_view

    use = next(u for u in record.detail.evidence_consumptions if u.id == audit.consumption_id)
    view = select_evidence_view(
        snapshot,
        agent="writer",
        competitor=use.competitor,
        dimension=use.dimension,
        source_ids=use.requested_source_ids,
        fact_ids=use.requested_fact_ids,
        max_bytes=use.view_max_bytes or use.max_bytes,
    )
    core = "question_core_context_budget_exceeded"
    assert not question_context_blocks(service, record.detail, snapshot, use, view, (core,), set())
    for replacement in ("", b.text.replace("故可", "故不可")):
        altered = record.detail.model_copy(deep=True)
        altered.report_md = altered.report_md.replace(b.text, replacement)
        assert _answer_support(altered, snapshot, audit, answer, case[6][0]["questions"][0]) is None
        assert question_context_blocks(service, altered, snapshot, use, view, (core,), set())
    assert question_context_blocks(
        service,
        record.detail,
        snapshot,
        use,
        view,
        (core, "question_exception_context_budget_exceeded"),
        set(),
    )
    for fault in ("partial", "native", "legacy"):
        altered = record.detail.model_copy(deep=True)
        if fault == "partial":
            altered.report_dimension_audits = [
                audit.model_copy(
                    update={"answer_coverage": (answer.model_copy(update={"status": "partial"}),)}
                )
            ]
        elif fault == "native":
            span = next(s for s in altered.trace_spans if s.name.endswith("atomic_answer_review"))
            span.metadata["response_format"] = "text"
        else:
            span = next(s for s in altered.trace_spans if s.name == "question_atomic_delivery")
            receipt = json.loads(span.full_output)
            receipt["task_execution_policy"] = "selected-task-atoms-v2"
            span.full_output = json.dumps(receipt)
        assert question_context_blocks(service, altered, snapshot, use, view, (core,), set())


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["mode", "contract", "cache_identity", "old_raw", "audit_label"])
async def test_native_task_replay_rejects_transport_and_contract_tampering(monkeypatch, fault):
    from test_selected_task_delivery import reviewed_scenario

    from packages.agents.writer.question_atomic_delivery import digest, replay_atomic_delivery

    case, _, audit, _, use = await reviewed_scenario(
        monkeypatch, execution_policy="selected-task-atoms-v3"
    )
    detail = case[1].detail.model_copy(deep=True)
    span = next(s for s in detail.trace_spans if s.name.endswith("atomic_answer_review"))
    if fault in {"mode", "contract", "cache_identity"}:
        key = {
            "mode": "response_format",
            "contract": "response_contract",
            "cache_identity": "response_transport_identity",
        }[fault]
        span.metadata[key] = "foreign"
    elif fault == "old_raw":
        span.full_output = '{"version":3,"answers":[],"task_decisions":[]}'
        receipt_span = next(s for s in detail.trace_spans if s.name == "question_atomic_delivery")
        receipt = json.loads(receipt_span.full_output)
        dispatch = next(d for d in receipt["dispatches"] if d["span_id"] == span.id)
        dispatch["full_output_sha256"] = digest(span.full_output)
        receipt_span.full_output = json.dumps(receipt)
    else:
        audit = audit.model_copy(update={"answer_review_contract": "subquestion-premises-v6"})
    with pytest.raises(ValueError):
        replay_atomic_delivery(
            case[0], detail, case[2], use, case[4], audit=audit if fault == "audit_label" else None
        )


def test_quantity_and_qualification_excludes_or_and_foreign_units():
    from packages.agents.writer.atomic_question_projection import generation_tasks
    from packages.agents.writer.task_answer_outcomes import quantity_and_eligible

    q = dict(
        question_id="q",
        question="Example：3 个人用 3 个 collections 共享密码。这个免费组织能满足吗？",
    )
    tasks = generation_tasks(q, "Example/feature")
    assert quantity_and_eligible(q["question"], tasks)
    assert not quantity_and_eligible(q["question"].replace("用", "或用"), tasks)
    assert not quantity_and_eligible(q["question"].replace("collections", "vaults"), tasks)


def test_typed_positive_cannot_override_explicit_negative_primary_claim():
    from packages.agents.writer.task_answer_outcomes import parse_task_reviews

    p = payload()
    p["tasks"][0]["support_choices"][0]["claim"] = dict(
        id="ca", text="Guests cannot vote on board A.", kind="inference"
    )
    accepted, failures = parse_task_reviews(
        json.dumps(dict(version=1, task_reviews=[row(outcome="yes"), row("b")])), p
    )
    assert "a" not in accepted and "b" in accepted
    assert failures["a"] == "task_review_polarity_conflict"


def test_answer_capacity_defers_only_overflowing_task_instead_of_erasing_peer():
    from types import SimpleNamespace

    from packages.agents.writer.task_answer_outcomes import aggregate

    tasks = [dict(task_id=t, question_id="q", question_quote=t, focus="source_rule") for t in "abc"]
    accepted = {t: dict(task_id=t, outcome="rule", claim_ids=[t]) for t in "abc"}
    claims = [SimpleNamespace(id=t, text=t * 600) for t in "abc"]
    answer = aggregate(
        [dict(question_id="q", question="Explain a, b and c.")], tasks, accepted, claims
    )["q"]
    assert answer.status == "partial" and answer.claim_ids == ("a",)
    assert answer.answer == "a" * 600


def test_a_generic_rule_verdict_cannot_complete_a_server_binary_task():
    from packages.agents.writer.task_answer_outcomes import parse_task_reviews

    p = payload()
    p["tasks"][0]["allowed_outcomes"] = ["yes", "no", "unknown"]
    accepted, failures = parse_task_reviews(
        json.dumps(dict(version=1, task_reviews=[row(outcome="rule"), row("b")])), p
    )
    assert "a" not in accepted and "b" in accepted and "a" in failures


@pytest.mark.asyncio
@pytest.mark.parametrize("predicate_count,actual_grant", [(1, False), (2, False), (1, True)])
async def test_capability_fallback_requires_actual_atomic_review_and_keeps_real_operation_gate(
    monkeypatch, predicate_count, actual_grant
):
    from claim_review_fixture import expand_prompt_payload
    from test_question_atomic_delivery import atomic_case, supported_review
    from test_task_support_selection import append_response

    from packages.agents.writer.question_atomic_delivery import (
        execute_question_atomic_delivery,
        replay_atomic_delivery,
    )
    from packages.research.evidence.report_claims import audit_report_claims

    source = "Scope Purge role grants access to purge the edge cache for a specific domain."
    case = await atomic_case(
        [source],
        question=(
            "Example Product：同事仅有 example.com 的 Scope Purge 角色，没有其他角色。"
            "他能因此清除 other.example 的边缘缓存吗？"
        ),
    )
    service, record, snapshot, selected, view, use, packets, boundaries, allowed = case

    async def model(record, **kwargs):
        p = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        if kwargs["name"].endswith("support_selection"):
            t = p["tasks"][0]
            data = dict(
                selections=[
                    dict(
                        task_id=t["task_id"],
                        status="selected",
                        binding_kind="span",
                        support_refs=[
                            p["evidence_view"]["facts"][0]["source_span_candidates"][0][
                                "support_ref"
                            ]
                        ],
                    )
                ]
            )
        elif kwargs["name"].endswith("atomic_generation"):
            t = p["generation_tasks"][0]
            text = (
                "Scope Purge 角色仅授予清除特定域边缘缓存的权限，因此仅有 example.com 的该角色"
                "并不能据此清除 other.example 的边缘缓存。"
                if t.get("resource")
                else "Scope Purge 角色允许清除特定域的边缘缓存。"
            )
            if actual_grant and t.get("resource"):
                text = "管理员可以授予小林管理 other.example 的访问权限。"
            data = dict(
                question_plans=[
                    dict(
                        question_id=t["question_id"],
                        missing_fields=[],
                        atoms=[
                            dict(
                                task_id=t["task_id"],
                                text=text,
                                kind="inference" if t.get("resource") else "fact",
                                support_refs=p["task_support_selections"][0]["support_refs"],
                            )
                        ],
                    )
                ]
            )
        else:
            count = predicate_count if p["task_context"].get("resource") else 1
            data = dict(
                reviews=[supported_review(c) for c in p["claims"]],
                atomicity=[
                    dict(
                        claim_id=c["id"],
                        predicate_count=count,
                        clauses=[
                            dict(
                                quote=c["text"],
                                predicate=p["task_context"]["focus"],
                                task_match=True,
                            )
                        ],
                    )
                    for c in p["claims"]
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
        answer_review_contract="task-outcomes-v1",
    )
    audits = audit_report_claims(
        result["claims"],
        result["reviews"],
        view,
        boundaries,
        available_facts=view.facts,
        review_version=3,
        capability_claim_ids=result["capability_claim_ids"],
    )
    eligible = [
        r
        for r in audits
        if r.claim.id in result["capability_claim_ids"] and r.status == "supported"
    ]
    assert bool(eligible) is (predicate_count == 1 and not actual_grant)
    if eligible:
        assert all(
            r.status != "supported"
            for r in audit_report_claims(
                [eligible[0].claim], [eligible[0].review], view, boundaries, review_version=3
            )
        )
    stored = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    assert (
        replay_atomic_delivery(service, record.detail, snapshot, stored, view)["claims"]
        == result["claims"]
    )


def test_role_actor_performing_grant_is_not_a_capability_description():
    from types import SimpleNamespace

    from packages.agents.writer.task_answer_outcomes import capability_candidate

    claim = SimpleNamespace(
        operation_binding=None,
        kind="inference",
        source_span_bindings=[{}],
        text="Scope Purge 角色的管理员授予小林对 other.example 的访问权限。",
    )
    assert not capability_candidate(claim, dict(resource="other.example", focus="purge_cache"))


@pytest.mark.asyncio
async def test_answer_repairs_only_invalid_task_row_and_retains_successful_peer(monkeypatch):
    from test_selected_task_delivery import reviewed_scenario

    from packages.agents.writer.question_atomic_delivery import replay_atomic_delivery

    case, result, audit, seen, use = await reviewed_scenario(
        monkeypatch, execution_policy="selected-task-atoms-v3", bad_task_review=True
    )
    answers = [p for n, p in seen if n.endswith("atomic_answer_review")]
    assert [len(p["tasks"]) for p in answers] == [2, 1]
    assert (
        answers[1]["repair_feedback"]["task_failures"][0]["task_id"]
        == answers[0]["tasks"][0]["task_id"]
    )
    assert answers[1]["tasks"][0]["task_id"] != answers[0]["tasks"][1]["task_id"]
    assert audit.answer_coverage[0].status == "answered"
    assert len(audit.answer_coverage[0].claim_ids) == 2
    assert (
        replay_atomic_delivery(case[0], case[1].detail, case[2], use, case[4], audit=audit)[
            "answers"
        ][audit.answer_coverage[0].question_id]
        == audit.answer_coverage[0]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("restored", [False, True])
async def test_same_question_four_complete_task_envelopes_split_and_replay_without_losing_peers(
    monkeypatch,
    restored,
):
    from dataclasses import replace

    from claim_review_fixture import expand_prompt_payload
    from test_question_atomic_delivery import atomic_case, supported_review
    from test_task_support_selection import append_response

    from packages.agents.writer.question_atomic_delivery import replay_atomic_delivery

    texts = [
        "Observer cannot be set at Workspace level.",
        "Each observer is set individually per member per board.",
        "Only board admins and Workspace admins can change a board member's status to Observer.",
        "An observer can be a billable Workspace member, or multi-board guest, "
        "or a non-billable single-board guest.",
    ]
    question = (
        "Example Product：假设 Workspace 已订阅 Premium，成员在 A 上是 Observer。"
        "能否在 Workspace 层级统一设置 Observer，A 上这次改权是否自动决定 B 的权限；"
        "谁有权把 A 的现有成员改为 Observer；只凭 Observer 标签能否确定他一定免费或一定计费？"
    )
    case = await atomic_case(
        texts,
        question=question,
        source_qualifiers=[
            dict(source_scope=dict(raw_source_id=(f"scope-{i}-" * 500))) for i in range(4)
        ],
    )
    service, record, snapshot = case[:3]
    service._settings = replace(service._settings, writer_question_atomic_enabled=True)
    sent = []

    budget = service._run_llm_budget(record)
    budget.calls = 6
    budget.tokens_used = 1000
    assert budget._fresh_selected_task_budget
    service._checkpoint_llm_budget(record, budget)
    prior_calls = dict(budget.delivery_call_reserves)
    prior_tokens = dict(budget.delivery_reserves)
    if restored:
        record.llm_budget = None
        budget = service._run_llm_budget(record)
        assert not budget._fresh_selected_task_budget

    async def model(record, **kwargs):
        p = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        name = kwargs["name"]
        if name.endswith("support_selection"):
            t = p["tasks"][0]
            request = t["question_quote"]
            term = (
                "Workspace level"
                if "层级" in request
                else "individually"
                if "自动" in request
                else "Only"
                if "谁" in request
                else "billable"
            )
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
        elif name.endswith("atomic_generation"):
            t = p["generation_tasks"][0]
            text = p["task_support_selections"][0]["supports"][0]["quote"]
            scenario = "自动" in t["question_quote"]
            if scenario:
                text = (
                    "根据每个 Observer 按成员、按看板独立设置的规则，"
                    "A 上的 Observer 权限并不自动决定 B 的权限。"
                )
            data = dict(
                question_plans=[
                    dict(
                        question_id=t["question_id"],
                        missing_fields=[],
                        atoms=[
                            dict(
                                task_id=t["task_id"],
                                text=text,
                                kind="inference" if scenario else "fact",
                                support_refs=p["task_support_selections"][0]["support_refs"],
                            )
                        ],
                    )
                ]
            )
        elif name.endswith("atomic_review"):
            data = dict(
                reviews=[supported_review(c) for c in p["claims"]],
                atomicity=[
                    dict(
                        claim_id=c["id"],
                        predicate_count=1,
                        clauses=[
                            dict(
                                quote=c["text"],
                                predicate=p["task_context"]["focus"],
                                task_match=True,
                            )
                        ],
                    )
                    for c in p["claims"]
                ],
            )
        else:
            sent.append((kwargs, p))
            data = dict(
                version=1,
                task_reviews=[
                    dict(
                        task_id=t["task_id"],
                        outcome="rule" if "谁" in t["question_quote"] else "no",
                        support_refs=[c["ref"] for c in t["support_choices"] if c["primary"]],
                        missing_fields=[],
                        reason="Independent local task audit.",
                    )
                    for t in p["tasks"]
                ],
            )
        return append_response(service, record, kwargs, json.dumps(data))

    monkeypatch.setattr(service, "_trace_llm_text", model)
    record.detail.report_md = await service._writer_dimension_report(record, 60)
    audit = record.detail.report_dimension_audits[0]
    assert sum(c.status == "supported" for c in audit.claims) == 4
    assert len(sent) >= 2
    assert all(len(k["user"].encode()) <= 14000 for k, _ in sent)
    task_ids = [t["task_id"] for _, p in sent for t in p["tasks"]]
    assert len(task_ids) == len(set(task_ids)) == 4
    assert all(len(p["required_task_ids"][0]["task_ids"]) == 4 for _, p in sent)
    assert audit.answer_coverage[0].status == "answered"
    phase = "answer:Example Product/feature"
    if restored:
        assert record.llm_budget.delivery_call_reserves[phase] == prior_calls[phase]
        assert record.llm_budget.delivery_reserves[phase] == prior_tokens[phase]
    else:
        assert record.llm_budget.delivery_call_reserves[phase] >= len(sent)
    cost = sum(
        sum(
            service._llm_request_envelope(
                system=k["system"], user=k["user"], max_output_tokens=1600
            )[1:]
        )
        for k, _ in sent
    )
    if not restored:
        assert record.llm_budget.delivery_reserves[phase] >= cost
    use = next(u for u in record.detail.evidence_consumptions if u.id == audit.consumption_id)
    view = case[4]
    replay = replay_atomic_delivery(service, record.detail, snapshot, use, view, audit=audit)
    assert replay["answers"][audit.answer_coverage[0].question_id] == audit.answer_coverage[0]


def scoped_outcome_payload(monkeypatch, question, quote, **task_fields):
    """Exercise the production payload projection without live evidence/artifacts."""
    from types import SimpleNamespace

    from packages.agents.writer import atomic_question_projection as projection
    from packages.agents.writer import question_atomic_delivery as atomic
    from packages.agents.writer import selected_task_delivery as delivery
    from packages.agents.writer import task_decision_witnesses as witnesses
    from packages.agents.writer.task_answer_outcomes import build_payload

    task = dict(task_id="a", question_id="q", question_quote=quote, focus="source_rule")
    task.update(task_fields)
    monkeypatch.setattr(projection, "generation_tasks", lambda *args: [task])
    monkeypatch.setattr(atomic, "atomic_decision_context", lambda *args: None)
    monkeypatch.setattr(atomic, "handoff_context", lambda *args: {})
    monkeypatch.setattr(delivery, "rebuild", lambda *args: ({}, {}, {}))
    monkeypatch.setattr(witnesses, "build_decision_candidates", lambda *args: [])
    return build_payload(
        None, None, [dict(question_id="q", question=question)], [],
        SimpleNamespace(competitor="Example", dimension="feature", facts=[]), None, {},
    )


@pytest.mark.parametrize(
    "question,quote,fields,binary",
    [
        (
            "只被授予 example.com 的 Cache Domain Purge 角色。他能清除 other.example 的缓存吗？",
            "只被授予 example.com 的 Cache Domain Purge 角色", {}, False,
        ),
        (
            "只被授予 example.com 的角色。他能清除 other.example 的缓存吗？",
            "他能清除 other.example 的缓存吗？", {"resource": "other.example"}, True,
        ),
        ("能否在 Workspace 层级统一设置？其他权限是否改变？",
         "能否在 Workspace 层级统一设置", {}, True),
        ("谁有权改权；A 上这次改权是否自动决定他在 B 的权限？",
         "A 上这次改权是否自动决定他在 B 的权限", {}, True),
        (
            "1Password: 在 Families 中，访客已接受邀请并被确认。他能同时加入两个共享保险库，"
            "或者拥有自己的 Private vault 吗？",
            "1Password: 在 Families 中，访客已接受邀请并被确认。他能同时加入两个共享保险库",
            {}, True,
        ),
        (
            "他能同时加入两个共享保险库，或者拥有自己的 Private vault 吗？",
            "或者拥有自己的 Private vault 吗？", {}, True,
        ),
        ("请说明角色规则；他能清除 other.example 的缓存吗？", "请说明角色规则", {}, False),
        ("What does the role grant? Can it purge other.example?",
         "What does the role grant?", {}, False),
    ],
)
def test_task_outcome_polarity_belongs_to_current_request(
    monkeypatch, question, quote, fields, binary
):
    from packages.agents.writer.task_answer_outcomes import parse_task_reviews

    current = scoped_outcome_payload(monkeypatch, question, quote, **fields)
    task = current["tasks"][0]
    expected = ["yes", "no", "unknown", "clarification"] if binary else [
        "rule", "unknown", "clarification"
    ]
    assert task["allowed_outcomes"] == expected
    task["support_choices"] = [dict(ref="a1", claim_id="ca", primary=True)]
    for outcome in ("yes", "no"):
        accepted, failures = parse_task_reviews(
            json.dumps(dict(version=1, task_reviews=[row(outcome=outcome)])), current
        )
        assert ("a" in accepted) is binary
        assert ("a" in failures) is not binary


def test_old_v3_parent_polarity_wire_cannot_replay_as_corrected_scope(monkeypatch):
    from copy import deepcopy

    from packages.agents.writer.atomic_claim_review import validated_review_payload
    from packages.agents.writer.dimension_writer import compact_prompt_json

    current = scoped_outcome_payload(
        monkeypatch,
        "只被授予 example.com 的角色。他能清除 other.example 的缓存吗？",
        "只被授予 example.com 的角色",
    )
    old = deepcopy(current)
    old["tasks"][0]["allowed_outcomes"] = ["yes", "no", "unknown", "clarification"]
    with pytest.raises(ValueError, match="encoding closure changed"):
        validated_review_payload(compact_prompt_json(old), current)
