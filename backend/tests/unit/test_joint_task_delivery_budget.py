"""Complete task answer and independent QA windows share the unchanged hard budget."""

import asyncio
import copy
import importlib
import json
from types import SimpleNamespace

import httpx
import pytest
from test_task_delivery_budget import task_service

from packages.agents.qa.question_reconciliation import final_review_batches
from packages.agents.writer.dimension_writer import compact_prompt_json
from packages.agents.writer.task_answers import task_answer_plan
from packages.agents.writer.task_execution import TASK_ANSWER_SYSTEM
from packages.llm.errors import LLMExecutionLimitError
from packages.llm.execution_budget import RunLLMBudget
from packages.research.evidence.report_claims import ReportClaim
from packages.research.question_delivery import _expand_text_refs
from packages.research.question_scope import research_questions


def decoded_findings(batches):
    return [
        {**row, **batch.get("question_contexts", {}).get(row.get("context_id"), {})}
        for batch in batches
        for row in batch["findings"]
    ]


def qa_candidates():
    contexts = [
        dict(
            question_id=f"q{i}",
            question=f"Question {i}?",
            request_context=dict(parent=f"Parent {i}: " + "shared hypothetical scenario. " * 35),
            answer=dict(claim_ids=[f"c{i}"], answer="answer " * 80),
            claims=[dict(id=f"c{i}", text=f"Complete rule {i}: " + "condition " * 130)],
            visible_answer="Visible answer " * 30,
            task_answers=[],
            task_support_claim_ids=[f"c{i}"],
            publication_matches=True,
            support_verified=True,
        )
        for i in range(4)
    ]
    return [
        dict(
            copy.deepcopy(contexts[i]),
            issue_id=f"issue-{n}",
            finding="Review every requested branch. " * 6,
            independent_question_check=n < 4,
            diagnostic_only=False,
            expected_claim_ids=[f"c{i}"],
            support_digest=str(n) * 64,
        )
        for n, i in enumerate([0, 1, 2, 3, 0, 1, 2, 3, 0])
    ]


def test_nine_qa_findings_share_complete_context_in_four_lossless_windows():
    candidates = qa_candidates()
    batches, omitted = final_review_batches(candidates, "basis", max_bytes=6000, max_batches=6)
    assert not omitted
    assert len(batches) == 4
    assert all(
        len(
            (
                "\nJSON:\n"
                + json.dumps(b, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            ).encode()
        )
        <= 6000
        for b in batches
    )
    decoded = {row["issue_id"]: row for row in decoded_findings(batches)}
    for expected in candidates:
        assert {key: decoded[expected["issue_id"]][key] for key in expected} == expected
    assert {row["issue_id"] for row in decoded.values()} == {row["issue_id"] for row in candidates}


def test_same_question_with_different_complete_parent_is_never_shared():
    candidates = [copy.deepcopy(qa_candidates()[0]) for _ in range(2)]
    candidates[1].update(issue_id="other", request_context=dict(parent="different" * 150))
    batches, omitted = final_review_batches(candidates, "basis", max_bytes=6000, max_batches=6)
    assert not omitted
    for original in candidates:
        actual = next(
            row for row in decoded_findings(batches) if row["issue_id"] == original["issue_id"]
        )
        assert actual["request_context"] == original["request_context"]
    for batch in batches:
        if len(batch["findings"]) == 2 and "question_contexts" in batch:
            assert len({row["context_id"] for row in batch["findings"]}) == 2


def answer_payload():
    questions = [
        dict(question_id=f"q{i}", question=f"Assume plan {i}. Can A export? Can B vote?")
        for i in range(4)
    ]
    tasks, claims, supports = [], [], []
    for i, question in enumerate(questions):
        for j, quote in enumerate(["Can A export?", "Can B vote?"]):
            cid = f"c{i}-{j}"
            text = f"Complete rule {i}-{j}: " + (chr(65 + i) + " condition ") * 65
            claims.append(dict(id=cid, text=text, kind="fact"))
            supports.append(dict(claim_id=cid, fact_id=f"f{i}-{j}", source_id=f"s{i}", quote=text))
            tasks.append(
                dict(
                    task_id=f"t{i}-{j}",
                    question_id=question["question_id"],
                    question_quote=quote,
                    focus="source_rule",
                    state="supported",
                    claim_id=cid,
                    decision=dict(conclusion="yes", relation="direct"),
                )
            )
    payload = dict(
        questions=questions,
        claims=claims,
        published_supports=supports,
        restrictive_source_context=[
            dict(fact_id=f"f{i}-0", source_exceptions=[dict(quote=f"Exception {i} in full.")])
            for i in range(4)
        ],
        required_clarifications=[],
        competitor="Example Suite",
        request_context=dict(
            version=2,
            purpose="request_only_not_evidence",
            parents=[
                dict(parent_id=f"p{i}", text=q["question"] + " Complete parent assumptions.")
                for i, q in enumerate(questions)
            ],
            bindings=[dict(question_id=f"q{i}", parent_id=f"p{i}") for i in range(4)],
            unbound_question_ids=[],
        ),
        proposed_answers=[
            dict(
                question_id=q["question_id"],
                claim_ids=[t["claim_id"] for t in tasks if t["question_id"] == q["question_id"]],
            )
            for q in questions
        ],
        reviewed_task_decisions=[
            dict(
                task_id=t["task_id"],
                question_id=t["question_id"],
                question_quote=t["question_quote"],
                **t["decision"],
            )
            for t in tasks
        ],
        server_partition=task_answer_plan(questions, tasks, {c["id"] for c in claims}),
        answer_review_contract="subquestion-premises-v1",
    )
    return payload, tasks


def test_answer_windows_keep_each_question_parent_all_ledger_claims_and_exceptions():
    payload, tasks = answer_payload()
    assert (
        len((TASK_ANSWER_SYSTEM + "\n\n\nJSON:\n" + compact_prompt_json(payload)).encode()) > 10000
    )
    windows_module = importlib.import_module("packages.agents.writer.task_answers")
    build = getattr(windows_module, "task_answer_review_windows", None)
    assert callable(build), "Task answer review must window complete per-question support"
    original = copy.deepcopy(payload)
    windows, omitted = build(
        payload, tasks, system=TASK_ANSWER_SYSTEM, max_bytes=10000, max_user_bytes=14000
    )
    assert not omitted and len(windows) > 1
    seen = []
    for window in windows:
        assert (
            len((TASK_ANSWER_SYSTEM + "\n\n\nJSON:\n" + compact_prompt_json(window)).encode())
            <= 10000
        )
        decoded = _expand_text_refs(json.loads(compact_prompt_json(window)))
        ids = {q["question_id"] for q in decoded["questions"]}
        seen.extend(ids)
        expected_ids = {t["claim_id"] for t in tasks if t["question_id"] in ids}
        assert {c["id"] for c in decoded["claims"]} == expected_ids
        assert {c["claim_id"] for c in decoded["published_supports"]} == expected_ids
        assert all(
            row["question_id"] in ids
            for key in ("proposed_answers", "server_partition", "reviewed_task_decisions")
            for row in decoded[key]
        )
        assert len(decoded["request_context"]["parents"]) == len(ids)
        assert len(decoded["restrictive_source_context"]) == len(ids)
    assert sorted(seen) == ["q0", "q1", "q2", "q3"]
    assert payload == original


def test_answer_window_retains_source_supported_partial_fact_without_approving_its_task():
    from packages.agents.writer.task_answers import task_answer_review_windows

    payload, tasks = answer_payload()
    partial = tasks[0]
    partial.update(state="partial")
    partial.pop("decision")
    payload["reviewed_task_decisions"] = [
        row for row in payload["reviewed_task_decisions"] if row["task_id"] != partial["task_id"]
    ]
    payload["proposed_answers"][0]["claim_ids"].remove(partial["claim_id"])
    payload["server_partition"] = task_answer_plan(
        payload["questions"], tasks, {claim["id"] for claim in payload["claims"]}
    )
    tasks.append(dict(partial, task_id="rejected", claim_id="not-published"))
    windows, omitted = task_answer_review_windows(payload, tasks, system=TASK_ANSWER_SYSTEM)
    assert not omitted
    window = next(w for w in windows if any(q["question_id"] == "q0" for q in w["questions"]))
    assert partial["claim_id"] in {claim["id"] for claim in window["claims"]}
    assert partial["claim_id"] in {row["claim_id"] for row in window["published_supports"]}
    assert "not-published" not in {claim["id"] for claim in window["claims"]}
    segment = window["server_partition"][0]["subquestions"][0]
    assert segment["claim_ids"] == [] and segment["conclusion"] == "unknown"
    assert segment["relation"] == "unresolved"
    assert partial["task_id"] not in {row["task_id"] for row in window["reviewed_task_decisions"]}


def test_budget_preflight_matches_reservation_without_mutating_any_account():
    budget = RunLLMBudget(
        max_calls=24,
        max_repairs=2,
        max_tokens=80000,
        tokens_used=45682,
        delivery_reserves={"answer:A/feature": 12000, "final_qa:run": 11000},
    )
    before = copy.deepcopy({k: v for k, v in vars(budget).items() if k != "reservation_settled"})
    check = getattr(budget, "admission_error", None)
    assert callable(check), "Real admission checks need a side-effect-free preflight"
    kwargs = dict(
        is_repair=False, phase="writer:A/feature", input_tokens=16585, max_output_tokens=1600
    )
    assert check(**kwargs) == "run_llm_budget_reserved_for_delivery"
    assert {k: v for k, v in vars(budget).items() if k != "reservation_settled"} == before
    with pytest.raises(LLMExecutionLimitError, match=check(**kwargs)):
        budget.reserve(**kwargs)
    assert {k: v for k, v in vars(budget).items() if k != "reservation_settled"} == before


async def real_answer_case(monkeypatch):
    service, record = await task_service()
    record.detail.plan.decision_brief.decision_question = "\n".join(
        f"Example Suite plan {i}: Can A export?" for i in range(4)
    )
    questions = research_questions(record.detail, "Example Suite", "feature")
    tasks, audited = [], []
    for i, q in enumerate(questions):
        cid = f"c{i}"
        claim = ReportClaim(
            id=cid,
            text=f"Rule {i}: " + "完整条件" * 100,
            kind="fact",
            competitor="Example Suite",
            dimension="feature",
            fact_ids=[f"f{i}"],
            source_ids=[f"s{i}"],
        )
        audited.append(SimpleNamespace(claim=claim, status="supported"))
        tasks.append(
            dict(
                task_id=f"t{i}",
                question_id=q["question_id"],
                question_quote=q["question"],
                focus="source_rule",
                state="supported",
                claim_id=cid,
                decision=dict(conclusion="yes", relation="direct"),
            )
        )
    monkeypatch.setattr(service, "_current_evidence_snapshot", lambda _: object())
    monkeypatch.setattr(service, "_validate_evidence_use", lambda *a: None)
    monkeypatch.setattr(service, "_validate_dimension_upstream", lambda *a: None)
    monkeypatch.setattr(
        "packages.agents.writer.price_answers.server_missing_price_answers", lambda *a, **kw: {}
    )
    budget = service._run_llm_budget(record)
    for phase in budget.delivery_reserves:
        if not phase.startswith(("answer:", "final_qa:")):
            budget.finish_delivery(phase)
    return (
        service,
        record,
        questions,
        dict(question_task_ledger=tasks),
        audited,
        SimpleNamespace(competitor="Example Suite", dimension="feature", facts=()),
        SimpleNamespace(max_bytes=14000),
    )


@pytest.mark.asyncio
async def test_real_answer_dispatch_windows_finish_only_after_last_and_resume_cancelled(
    monkeypatch,
):
    service, record, questions, compact, audited, view, use = await real_answer_case(monkeypatch)
    requests = []
    phase = "answer:Example Suite/feature"

    async def post(url, payload, headers):
        assert phase not in service._run_llm_budget(record).delivery_finished
        system, user = (message["content"] for message in payload["messages"])
        assert len((system + "\n\n" + user).encode()) <= 10000
        batch = _expand_text_refs(json.loads(user.split("\nJSON:\n", 1)[1]))
        requests.append(batch)
        if len(requests) == 2:
            raise asyncio.CancelledError()
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                dict(
                                    version=3,
                                    answers=[
                                        dict(
                                            question_id=q["question_id"],
                                            status="unverified",
                                            claim_ids=[],
                                            resolution="unresolved",
                                            conclusion="unknown",
                                            missing_fields=[],
                                            reason="Unresolved.",
                                            subquestions=[
                                                dict(
                                                    segment_id=s["segment_id"],
                                                    claim_ids=[],
                                                    conclusion="unknown",
                                                    relation="unresolved",
                                                )
                                                for p in batch["server_partition"]
                                                if p["question_id"] == q["question_id"]
                                                for s in p["subquestions"]
                                            ],
                                        )
                                        for q in batch["questions"]
                                    ],
                                )
                            )
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(service._llm, "_post_chat_completion", post)
    with pytest.raises(asyncio.CancelledError):
        await service._dimension_question_coverage(
            record, questions, compact, audited, view, use, ()
        )
    assert phase not in service._run_llm_budget(record).delivery_finished
    charged = record.detail.llm_budget_checkpoint["tokens_charged"]
    assert charged > 0 and len(requests) == 2
    record.llm_budget = None
    coverage, _, _ = await service._dimension_question_coverage(
        record, questions, compact, audited, view, use, ()
    )
    assert len(coverage) == 4 and all(c.status == "unverified" for c in coverage)
    assert phase in service._run_llm_budget(record).delivery_finished
    assert service._run_llm_budget(record).tokens_used >= charged
    assert {q["question_id"] for r in requests for q in r["questions"]} == {
        q["question_id"] for q in questions
    }
    assert (
        sum(
            q["question_id"] == questions[0]["question_id"]
            for r in requests
            for q in r["questions"]
        )
        == 1
    )


@pytest.mark.asyncio
async def test_real_request_preflight_has_identical_utf8_framing_output_and_zero_rejected_transport(
    monkeypatch,
):
    service, record = await task_service()
    budget = service._run_llm_budget(record)
    for phase in budget.delivery_reserves:
        if not phase.startswith(("answer:", "final_qa:")):
            budget.finish_delivery(phase)
    budget.tokens_used = 45682
    kwargs = dict(
        agent="writer",
        subagent="Example Suite/feature",
        name="dimension_task_generation",
        system="完整系统。",
        user="原始条件。" * 1000,
        max_output_tokens=2300,
    )
    check = getattr(service, "_llm_request_admission_error", None)
    assert callable(check), "Scheduling and real transport must use identical request envelopes"
    before = copy.deepcopy(record.detail.llm_budget_checkpoint)
    requests = []

    async def post(url, payload, headers):
        requests.append(payload)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    monkeypatch.setattr(service._llm, "_post_chat_completion", post)
    error = check(record, **kwargs)
    assert error == "run_llm_budget_reserved_for_delivery"
    assert record.detail.llm_budget_checkpoint == before
    assert budget.calls == 0 and budget.tokens_used == 45682 and budget.tokens_reserved == 0
    with pytest.raises(LLMExecutionLimitError, match=error):
        await service._trace_llm_text(record, **kwargs)
    span = record.detail.trace_spans[-1]
    assert (
        span.metadata["llm_reserved_input_tokens"]
        == len((kwargs["system"] + "\n\n" + kwargs["user"]).encode()) + 256
    )
    assert span.metadata["llm_max_output_tokens"] == 1600
    assert span.metadata["llm_transport_attempts"] == span.metadata["llm_tokens_charged"] == 0
    assert not requests


@pytest.mark.asyncio
async def test_selector_is_unsent_when_even_empty_generation_envelope_cannot_advance(monkeypatch):
    from test_execution_limits import _service
    from test_task_context_handoff import handoff_case, offline_model

    from packages.agents.writer.task_execution import GENERATE_SYSTEM, PLAN_SYSTEM
    from packages.agents.writer.task_support_selection import SELECT_SYSTEM

    _, record, parts, texts = handoff_case()
    service, _ = await _service(
        writer_task_execution_enabled=True,
        run_llm_max_calls=24,
        run_llm_max_tokens=80000,
        llm_max_output_tokens=1600,
        llm_max_retries=0,
    )
    service._runs[record.detail.id] = record
    budget = service._run_llm_budget(record)
    for phase in budget.delivery_reserves:
        if phase.startswith(("collector:", "analyst:", "comparator:", "reflector:")):
            budget.finish_delivery(phase)
    model = offline_model(service, record, parts, texts, {}, trace=False)
    systems = []

    async def post(url, payload, headers):
        system, user = [message["content"] for message in payload["messages"]]
        systems.append(system)
        if system.startswith(PLAN_SYSTEM):
            # Leave enough for a cheap selector, but not even the generation
            # SYSTEM + empty JSON + effective output under the delivery floors.
            budget.tokens_used = (
                80000 - budget.protected_tokens("writer:Example Product/feature") - 5600
            )
            response = await model(record, name="dimension_task_plan", system=system, user=user)
        elif system.startswith(SELECT_SYSTEM):
            response = await model(
                record, name="dimension_task_support_selection", system=system, user=user
            )
        else:
            response = "{}"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": response}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    monkeypatch.setattr(service._llm, "_post_chat_completion", post)
    await service._real_writer_step(record)
    assert any(system.startswith(PLAN_SYSTEM) for system in systems)
    assert not any(system.startswith((SELECT_SYSTEM, GENERATE_SYSTEM)) for system in systems)
    receipt = json.loads(
        next(s.full_output for s in record.detail.trace_spans if s.name == "question_task_delivery")
    )
    assert all(t["state"] == "deferred" for t in receipt["tasks"])
    assert all("budget" in t["reason"] for t in receipt["tasks"])


@pytest.mark.asyncio
@pytest.mark.parametrize("old_mode", ["independent_questions_v2", "independent_questions_v5",
                                     "independent_questions_v6", "independent_questions_v7",
                                     "independent_questions_v8"])
async def test_real_independent_qa_sends_nine_complete_findings_and_rejects_old_receipt(
    monkeypatch, old_mode,
):
    from dataclasses import replace

    from question_review_fixture import review_payload as decode_review_payload
    from test_final_question_reconciliation import reviewed, scope_case
    from test_independent_final_question_qa import receipt

    from packages.agents.qa import independent_question_review as qa
    from packages.orchestrator.llm_execution import LLMExecutionMixin

    detail, service, record = await scope_case(monkeypatch)
    provider, _ = await task_service()
    service._llm = provider._llm
    service._settings = replace(
        service._settings,
        writer_task_execution_enabled=True,
        run_llm_max_calls=24,
        run_llm_max_tokens=80000,
        llm_max_output_tokens=1600,
    )
    detail.plan.decision_brief.decision_question = "\n".join(
        f"Example Product scenario {i}: can it export?" for i in range(4)
    )
    questions = research_questions(detail, "Example Product", "feature")
    original = service._build_reflector_qa_issues(detail)[0]
    historical = [
        original.model_copy(
            update=dict(
                id=f"old-{n}",
                problem=questions[i]["question_id"] + ": " + "Review every requested branch. " * 6,
                metadata=dict(question_id=questions[i]["question_id"]),
            )
        )
        for n, i in enumerate([0, 1, 2, 3, 0])
    ]
    claim = detail.report_dimension_audits[0].claims[0].claim
    contexts = {}
    for i, question in enumerate(questions):
        context = copy.deepcopy(qa_candidates()[i])
        context.update(question_id=question["question_id"], question=question["question"])
        context["claims"][0].update(
            fact_ids=list(claim.fact_ids), source_ids=list(claim.source_ids)
        )
        for key in (
            "issue_id",
            "finding",
            "independent_question_check",
            "diagnostic_only",
            "expected_claim_ids",
            "support_digest",
        ):
            context.pop(key)
        contexts[question["question_id"]] = context
    monkeypatch.setattr(
        qa,
        "_question_context",
        lambda *args, **kwargs: copy.deepcopy(contexts[args[3]["question_id"]]),
    )
    monkeypatch.setattr(
        service, "_trace_llm_text", LLMExecutionMixin._trace_llm_text.__get__(service)
    )
    record.llm_budget = None
    detail.llm_budget_checkpoint = {}
    budget = service._run_llm_budget(record)
    for phase in budget.delivery_reserves:
        if phase != "final_qa:run":
            budget.finish_delivery(phase)
    requests = []

    async def post(url, payload, headers):
        system, user = [message["content"] for message in payload["messages"]]
        assert system == qa.INDEPENDENT_SYSTEM
        assert len(user.encode()) <= qa.review_byte_limit(qa.PROTOCOL) == 14000
        batch = decode_review_payload(user.split("\nJSON:\n", 1)[1])
        requests.append(batch)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": reviewed(batch)}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            },
        )

    monkeypatch.setattr(service._llm, "_post_chat_completion", post)
    await qa.review_current_questions(service, record, historical, evidence_issues=[])
    output = receipt(detail)
    assert len(requests) == 4
    assert len(output["planned_issue_ids"]) == 9
    assert (
        output["planned_issue_ids"] == output["sent_issue_ids"] == output["valid_review_issue_ids"]
    )
    assert output["omitted_issue_ids"] == output["unsent_issue_ids"] == []
    for row in decoded_findings(requests):
        expected = contexts[row["question_id"]]
        assert {key: row[key] for key in expected} == expected
        assert row["expected_claim_ids"] == expected["answer"]["claim_ids"]
    assert budget.calls == 4 and budget.tokens_used == 600
    # An old semantic identity cannot approve these requests under the new
    # assumption rules. Its already charged work stays in the same hard account.
    span = next(s for s in reversed(detail.trace_spans) if s.name == qa.RECEIPT_NAME)
    old_receipt = json.loads(span.full_output)
    old_receipt["mode"] = old_mode
    span.full_output = json.dumps(old_receipt)
    await qa.review_current_questions(service, record, historical, evidence_issues=[])
    assert len(requests) == 8 and budget.calls == 8 and budget.tokens_used == 1200
    assert receipt(detail)["mode"] == qa.PROTOCOL == "independent_questions_v9"
    assert (budget.max_calls, budget.max_tokens) == (24, 80000)


@pytest.mark.asyncio
async def test_unseen_history_cannot_take_the_only_window_from_a_resumable_original(monkeypatch):
    from dataclasses import replace

    from test_final_question_reconciliation import reviewed, scope_case
    from test_independent_final_question_qa import payload_from, receipt

    from packages.agents.qa import independent_question_review as qa
    from packages.agents.qa import question_reconciliation

    detail, service, record = await scope_case(monkeypatch)
    service._settings = replace(service._settings, writer_task_execution_enabled=True)
    historical = service._build_reflector_qa_issues(detail)
    monkeypatch.setattr(qa, "MAX_REVIEW_BATCHES", 1)
    monkeypatch.setattr(question_reconciliation, "MAX_FINDINGS", 1)
    calls = []

    async def model(record, **kwargs):
        batch = payload_from(kwargs)
        calls.append(batch)
        return "{}" if len(calls) == 1 else reviewed(batch)

    monkeypatch.setattr(service, "_trace_llm_text", model)
    await qa.review_current_questions(service, record, historical, evidence_issues=[])
    await qa.review_current_questions(service, record, historical, evidence_issues=[])
    assert [batch["findings"][0]["issue_id"] for batch in calls] == [
        receipt(detail)["planned_issue_ids"][0]
    ] * 2
    assert calls[1]["findings"][0]["independent_question_check"] is True


@pytest.mark.asyncio
async def test_preflight_resolves_live_origin_before_repair_and_phase_checks(monkeypatch):
    service, record = await task_service()
    budget = service._run_llm_budget(record)
    budget.max_repairs = 0
    origin = copy.copy(record)
    origin.evidence_origin = record
    origin.pending_graph_redo = object()
    kwargs = dict(
        agent="qa",
        subagent="Example Suite/feature",
        name="dimension_answer_review",
        system="Complete system",
        user="Complete request",
        max_output_tokens=100,
    )
    assert service._llm_request_admission_error(origin, **kwargs) is None

    async def post(url, payload, headers):
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    monkeypatch.setattr(service._llm, "_post_chat_completion", post)
    await service._trace_llm_text(origin, **kwargs)
    assert record.detail.trace_spans[-1].metadata["is_repair"] is False
    assert budget.repairs == 0 and budget.calls == 1


@pytest.mark.asyncio
async def test_same_window_cannot_borrow_a_sibling_questions_claim_but_keeps_valid_peer(
    monkeypatch,
):
    service, record, questions, compact, audited, view, use = await real_answer_case(monkeypatch)
    for row in audited:
        row.claim = row.claim.model_copy(update=dict(text="Only two guests may use the service."))
    requests = []

    async def post(url, payload, headers):
        batch = _expand_text_refs(
            json.loads(payload["messages"][1]["content"].split("\nJSON:\n", 1)[1])
        )
        requests.append(batch)
        answers = []
        for i, q in enumerate(batch["questions"]):
            cid = "c1" if i == 0 else f"c{i}"
            answers.append(
                dict(
                    question_id=q["question_id"],
                    status="unverified",
                    claim_ids=[cid],
                    resolution="unresolved",
                    conclusion="unknown",
                    missing_fields=[],
                    reason="Local gap.",
                    subquestions=[
                        dict(
                            segment_id=s["segment_id"],
                            claim_ids=[cid],
                            conclusion="unknown",
                            relation="unresolved",
                        )
                        for p in batch["server_partition"]
                        if p["question_id"] == q["question_id"]
                        for s in p["subquestions"]
                    ],
                )
            )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(dict(version=3, answers=answers))}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    monkeypatch.setattr(service._llm, "_post_chat_completion", post)
    coverage, _, _ = await service._dimension_question_coverage(
        record, questions, compact, audited, view, use, ()
    )
    assert len(requests) == 1 and len(requests[0]["questions"]) == 4
    assert coverage[0].status == "unverified" and coverage[0].claim_ids == ()
    assert coverage[1].claim_ids == ("c1",) and coverage[1].binding_version == 3
