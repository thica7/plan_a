"""GEN5 task repair uses real transport, independent review and authenticated replay."""

import hashlib
import inspect
import json
from pathlib import Path

import pytest
from claim_review_fixture import answer_response, expand_prompt_payload
from test_atomic_delivery_v4 import run
from test_question_atomic_delivery import atomic_case, supported_review
from test_task_support_selection import append_response

from packages.agents.writer import question_atomic_delivery as atomic


def output(payload, atoms):
    return json.dumps({"question_plans": [{
        "question_id": payload["questions"][0]["question_id"],
        "missing_fields": payload["question_plan_missing_fields"][0]["missing_fields"],
        "atoms": atoms,
    }]})


def atom(payload, task, text, *, ref=None, kind="fact"):
    if ref is None:
        ref = next(span["support_ref"] for row in payload["evidence_view"]["facts"]
                   for span in row["source_span_candidates"] if span["quote"] == text)
    return dict(task_id=task["task_id"], text=text, kind=kind, support_refs=[ref])


def test_gen5_default_and_explicit_identity_preserve_all_old_system_bytes():
    assert inspect.signature(atomic.execute_question_atomic_delivery).parameters[
        "generation_projection_version"].default == 5
    expected = ["a5c0d0a58490b2a65494742306bc22aa173ffee78c41cda973a9c1d6747016ee",
                "f337f7bbe7480f57c8aa5a7d825b44ff8fcd057c5acc1188131d69154ca4c74a",
                "a5ecc77aaf4df96f6d5c5fca7fe71b993220da0d848970b27454aec906f26ddb",
                "1dd6aade1842c5b47cd6148668154535140fb4d68563b78be7383be4a8a90a91"]
    for version, digest in enumerate(expected, 1):
        system = atomic.atomic_system(atomic.GENERATION_NAME, "en",
            generation_projection_version=version,
            review_projection_version=3 if version >= 3 else 2)
        assert hashlib.sha256(system.encode()).hexdigest() == digest
    assert atomic.atomic_system(atomic.GENERATION_NAME, "en", generation_projection_version=5,
        review_projection_version=3).startswith("Server current-question atomic generation v5.")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing", "candidate", "rule", "review", "malformed_review"])
async def test_gen5_once_repairs_only_failed_tasks_and_preserves_successful_claims(
    monkeypatch, failure,
):
    texts = ["Guests have no personal area.", "Guests require an account invitation."]
    case = await atomic_case(
        texts, question="Example Product：访客是否有私人区域；是否需要账户邀请？")
    service, record, snapshot, _, view, use, packets, boundaries, _ = case
    record.detail.report_answer_boundaries = boundaries
    seen, first_ids, first_texts = [], [], []

    async def model(record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        seen.append((kwargs["name"], payload))
        if kwargs["name"] == atomic.GENERATION_NAME:
            tasks = payload["generation_tasks"]
            if "generation_repair" not in payload:
                first, second = tasks
                atoms = [atom(payload, first, texts[0])]
                if failure != "missing":
                    atoms.append(atom(payload, second,
                        "The supplied page does not specify the invitation requirement."
                        if failure == "rule" else texts[1],
                        ref="s999" if failure == "candidate" else None
                        if failure != "rule" else next(s["support_ref"] for r in payload[
                            "evidence_view"]["facts"] for s in r["source_span_candidates"])))
                result = output(payload, atoms)
                current, _, _ = atomic.parse_atomic_generation(result, payload, view, use)
                first_ids.extend(c.id for c in current[:1])
                first_texts.extend(c.text for c in current[:1])
            else:
                assert payload["generation_projection_version"] == 5
                assert payload["projection_identity"] == "atomic-generation-v5-review-v3"
                assert len(tasks) == 1 and tasks[0]["task_id"] != first_task_id[0]
                assert payload["generation_repair"]["attempt"] == 1
                assert payload["generation_repair"]["retained_claim_ids"] == first_ids
                result = output(payload, [atom(payload, tasks[0], texts[1])])
            if "generation_repair" not in payload:
                first_task_id.append(tasks[0]["task_id"])
        elif kwargs["name"] == atomic.REVIEW_NAME:
            claim = payload["claims"][0]
            row = supported_review(claim)
            if (claim["text"] == texts[1]
                    and len([p for n, p in seen if n == atomic.GENERATION_NAME]) == 1):
                if failure == "review":
                    row["verdict"] = "unsupported"
                elif failure == "malformed_review":
                    row["checks"] = []
            result = json.dumps({"reviews": [row]})
        else:
            result = answer_response(payload, {"version": 3, "answers": [{
                "question_id": payload["questions"][0]["question_id"], "status": "partial",
                "resolution": "direct", "conclusion": "unknown", "missing_fields": [],
                "claim_ids": [c["id"] for c in payload["claims"]], "reason": "Known rules.",
            }]})
        return append_response(service, record, kwargs, result)

    first_task_id = []
    result = await run(case, monkeypatch, model, generation_projection_version=5)
    gens = [p for n, p in seen if n == atomic.GENERATION_NAME]
    assert len(gens) == 2
    from packages.research.evidence.report_claims import ReportDimensionAudit, audit_report_claims
    audited = audit_report_claims(result["claims"], result["reviews"], view, boundaries,
                                 available_facts=view.facts, review_version=3)
    supported = [r.claim for r in audited if r.status == "supported"]
    assert {c.text for c in supported} == set(texts), (audited, result["gaps"],
        [(n, p.get("generation_repair"), p.get("generation_tasks")) for n, p in seen],
        [(s.name, s.full_output) for s in record.detail.trace_spans if s.status != "ok"])
    assert supported[0].id == first_ids[0] and supported[0].text == first_texts[0]
    assert len({c.id for c in result["claims"]}) == len(result["claims"])
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    answers, _, _ = await atomic.atomic_answer_coverage(
        service, record, packets[0]["questions"], result["compact"], supported, view, use, ())
    from packages.agents.writer.dimension_writer import render_dimension_report
    audit = ReportDimensionAudit(competitor=view.competitor, dimension=view.dimension,
        consumption_id=use.id, claims=audited, answer_coverage=answers, answer_binding_version=3,
        claim_review_version=3, answer_review_contract="subquestion-premises-v1",
        question_atomic_contract=atomic.CONTRACT,
        question_atomic_receipt_digest=result["compact"]["question_atomic_receipt_digest"])
    record.detail.report_dimension_audits = [audit]
    rendered = render_dimension_report(record.detail, [audit], snapshot=snapshot)
    assert all(text in rendered for text in texts)
    replay = atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view)
    assert replay["claims"] == result["claims"] and replay["reviews"] == result["reviews"]
    dispatches = result["compact"]["dispatches"]
    assert [d["attempt"] for d in dispatches if d["name"] == atomic.GENERATION_NAME] == [0, 1]
    if failure == "missing":
        retry = next(d for d in dispatches if d["name"] == atomic.GENERATION_NAME and d["attempt"])
        span = next(s for s in record.detail.trace_spans if s.id == retry["span_id"])
        original_input, original_hash = span.full_input, retry["full_input_sha256"]
        system, raw = span.full_input.split("\nJSON:\n", 1)
        for tid in (first_task_id[0], "foreign-task"):
            raw_payload = json.loads(raw)
            raw_payload["generation_repair"]["target_task_ids"] = [tid]
            span.full_input = system + "\nJSON:\n" + json.dumps(raw_payload)
            retry["full_input_sha256"] = atomic.digest(span.full_input)
            receipt_span = next(s for s in record.detail.trace_spans
                                if s.name == "question_atomic_delivery")
            receipt = json.loads(receipt_span.full_output)
            receipt["dispatches"] = dispatches
            receipt_span.full_output = json.dumps(receipt)
            with pytest.raises(ValueError):
                atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view)
        span.full_input, retry["full_input_sha256"] = original_input, original_hash


@pytest.mark.asyncio
@pytest.mark.parametrize("text,blocked", [
    ("官方页面仅明确许可投票，在前提条件已经满足且管理员开放投票功能的情景下，"
     "其列举的能力是许可性质而非义务性质，并未规定每张卡片都必须投票。", True),
    ("The supplied document discusses permission in the complete hypothetical scenario, "
     "including the role, board and administrator setting, but has not specified any obligation.",
     True),
    ("Permission to vote does not entail an obligation to vote on every card.", False),
    ("Observers cannot edit cards.", False),
])
async def test_gen5_source_absence_candidate_guard_preserves_finite_product_negatives(
    text, blocked,
):
    case = await atomic_case(
        ["Observers may vote when voting is enabled by administrators."],
        question="Example Product: Does permission to vote imply a duty to vote?")
    service, record, _, _, view, use, packets, _, allowed = case
    payload = atomic.atomic_question_context(service, record, view, packets,
        packets[0]["questions"][0], allowed, use, generation_projection_version=5)
    task = payload["generation_tasks"][0]
    claims, gaps, _ = atomic.parse_atomic_generation(output(payload, [atom(payload, task, text,
        ref=payload["evidence_view"]["facts"][0]["source_span_candidates"][0]["support_ref"],
        kind="inference")]), payload, view, use)
    assert ("source_document_absence_unverified" in gaps) == blocked
    if blocked:
        assert not claims


@pytest.mark.asyncio
async def test_gen5_real_trello_failed_billing_task_reprojects_complete_authorized_fact():
    from test_writer_question_delivery import service_for

    from packages.agents.qa.question_context import _observations
    from packages.agents.writer.dimension_writer import _support_ref_catalog, compact_prompt_json
    from packages.research.evidence.views import select_evidence_view
    from packages.schema.api_dto import RunDetail

    old = (Path(__file__).resolve().parents[3] / "data/artifacts"
           / "answer-guard-repair-2026-10-27/live-trello-verified/execution")
    detail = RunDetail.model_validate_json((old / "run.exact.json").read_text())
    service, record = service_for(detail, task_execution=True)
    snapshot = service._current_evidence_snapshot(record)
    receipt = next(json.loads(s.full_output) for s in detail.trace_spans
                   if s.name == "question_atomic_delivery")
    use = next(u for u in detail.evidence_consumptions if u.id == receipt["consumption_id"])
    view = select_evidence_view(snapshot, agent=use.agent, competitor=use.competitor,
        dimension=use.dimension, max_bytes=use.view_max_bytes or use.max_bytes,
        fact_ids=use.fact_ids)
    packets = _observations(detail, "question_evidence_selection", use.id)["packets"]
    question = packets[0]["questions"][-1]
    fid = "evidence-fact-record-7d3f7d5e51ba5c1b992cc06ba2dbfe506cc232d9cdd0091d43ee07bc58303675"
    initial = atomic.atomic_question_context(service, record, view, packets, question,
        set(view.fact_ids), use, generation_projection_version=5)
    assert fid in view.fact_ids and fid not in {r["id"] for r in initial["evidence_view"]["facts"]}
    task = next(t for t in initial["generation_tasks"] if "免费" in t["question_quote"])
    repair = dict(attempt=1, target_task_ids=[task["task_id"]], diagnostics=[dict(
        task_id=task["task_id"], reasons=["source_document_absence_unverified"])],
        prior_failed_claim_ids=[], retained_claim_ids=[], repair_namespace=atomic.digest([
            use.id, question["question_id"], "atomic-generation-v5", 1]),
        claim_limit=8, task_claim_limits={task["task_id"]: 3})
    payload = atomic.atomic_question_context(service, record, view, packets, question,
        set(view.fact_ids), use, generation_projection_version=5, generation_repair=repair)
    assert payload["questions"] == initial["questions"]
    assert payload["request_context"] == initial["request_context"]
    assert [t["task_id"] for t in payload["generation_tasks"]] == [task["task_id"]]
    wire = expand_prompt_payload(json.loads(compact_prompt_json(payload)))
    full = next(f for f in view.facts if f.id == fid)
    sent = {r["id"] for r in wire["evidence_view"]["facts"]}
    assert fid in sent
    catalog = _support_ref_catalog(wire, view.facts, sent)
    span = next(span for row in wire["evidence_view"]["facts"] if row["id"] == fid
                for span in row["source_span_candidates"] if span["quote"] == full.quote)
    assert catalog[span["support_ref"]]["fact_ids"] == [fid]
    assert len(("\nJSON:\n" + compact_prompt_json(payload)).encode()) <= 14000
    assert all(term in full.quote for term in (
        "billable", "Workspace", "multi-board", "non-billable", "single-board"))


@pytest.mark.asyncio
async def test_gen5_billing_reprojection_prefers_long_complete_condition_to_short_notice():
    complete = ("Billing depends on membership: verified organization members are billable, "
                "while single-project guests are non-billable only after the administrator "
                "has confirmed their external status and completed the required verification.")
    case = await atomic_case(["Billing notice applies.", complete],
                            question="Example Product: Is this role billable or free?")
    service, record, _, _, view, use, packets, _, allowed = case
    initial = atomic.atomic_question_context(service, record, view, packets,
        packets[0]["questions"][0], allowed, use, generation_projection_version=5)
    task = initial["generation_tasks"][0]
    repair = dict(attempt=1, target_task_ids=[task["task_id"]], claim_limit=8,
                  task_claim_limits={task["task_id"]: 3})
    payload = atomic.atomic_question_context(service, record, view, packets,
        packets[0]["questions"][0], allowed, use, generation_projection_version=5,
        generation_repair=repair)
    assert payload["evidence_view"]["facts"][0]["quote"] == complete


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["empty", "invalid", "budget", "transport"])
async def test_gen5_repair_stops_once_and_does_not_retry_budget_or_transport(monkeypatch, failure):
    case = await atomic_case(["Guests require an account invitation."],
                            question="Example Product: Do guests require an invitation?")
    service, record, snapshot, _, view, use, _, _, _ = case
    service._run_llm_budget(record).max_repairs = 0
    calls = []

    async def model(record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        assert kwargs["name"] == atomic.GENERATION_NAME
        calls.append(payload)
        if failure == "budget":
            budget = service._run_llm_budget(record)
            budget.calls = budget.max_calls
        atoms = ([atom(payload, payload["generation_tasks"][0],
                       "Unsent invented predicate.", ref="s999")]
                 if failure == "invalid" and len(calls) == 2 else [])
        return append_response(service, record, kwargs, output(payload, atoms),
                               attempts=0 if failure == "transport" else 1)

    result = await run(case, monkeypatch, model, generation_projection_version=5)
    assert len(calls) == (1 if failure in {"budget", "transport"} else 2)
    assert not result["claims"] and not result["reviews"]
    assert service._run_llm_budget(record).max_repairs == 0
    if failure != "transport":
        use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
        replay = atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view)
        assert not replay["claims"]


@pytest.mark.asyncio
@pytest.mark.parametrize("resubmission", ["duplicate_only", "rate_only", "duplicate_and_rate"])
async def test_gen5_same_task_partial_success_keeps_text_and_rejects_duplicate_resubmission(
    monkeypatch, resubmission,
):
    from dataclasses import replace

    import httpx

    from packages.llm import DoubaoClient
    from packages.research.evidence.report_claims import audit_report_claims

    texts = ["The subscription includes 10 units each month.", "Each additional unit costs $0.02."]
    case = await atomic_case(texts, question="Example Product: What is the exact bill this month?")
    service, record, snapshot, selected, view, use, packets, boundaries, allowed = case
    record.detail.report_answer_boundaries = boundaries
    service._settings = replace(service._settings, run_llm_max_repairs=0)
    budget = service._run_llm_budget(record)
    service._llm = DoubaoClient(replace(service._settings, demo_mode=False,
        ark_api_key="offline-test", ark_model="offline-test", ark_base_url="https://example.invalid",
        llm_max_retries=0))
    seen = []

    async def post(url, wire, headers):
        system, user = [row["content"] for row in wire["messages"]]
        payload = expand_prompt_payload(json.loads(user.split("\nJSON:\n", 1)[1]))
        name = atomic.GENERATION_NAME if system.startswith(
            "Server current-question atomic generation") else atomic.REVIEW_NAME
        seen.append((name, payload))
        if name == atomic.GENERATION_NAME:
            task = payload["generation_tasks"][0]
            chosen = (texts if "generation_repair" not in payload else
                      texts[:1] if resubmission == "duplicate_only" else
                      texts[1:] if resubmission == "rate_only" else texts)
            response = output(payload, [atom(payload, task, text) for text in chosen])
        else:
            claim = payload["claims"][0]
            review = supported_review(claim)
            if claim["text"] == texts[1] and not any(
                "generation_repair" in body for _, body in seen
            ):
                review["verdict"] = "unsupported"
            response = json.dumps({"reviews": [review]})
        return httpx.Response(200, json={"choices": [{"message": {"content": response}}],
            "usage": {"prompt_tokens": 500, "completion_tokens": 50}})

    monkeypatch.setattr(service._llm, "_post_chat_completion", post)
    result = await atomic.execute_question_atomic_delivery(service, record, selected, view, use,
        packets[0]["questions"], packets, allowed, boundaries, (), generation_projection_version=5)
    repair_payload = next(body for name, body in seen if name == atomic.GENERATION_NAME
                          and "generation_repair" in body)
    repair = repair_payload["generation_repair"]
    tid = repair_payload["generation_tasks"][0]["task_id"]
    first_claim, failed_claim = result["claims"][:2]
    audited = audit_report_claims(result["claims"], result["reviews"], view, boundaries,
                                 available_facts=view.facts, review_version=3)
    kept = [row.claim for row in audited if row.status == "supported"]
    assert [claim.text for claim in kept] == (
        texts[:1] if resubmission == "duplicate_only" else texts)
    assert kept[0] == first_claim
    assert repair["diagnostic_scope"] == "prior_claim_text_is_not_evidence"
    assert repair["retained_claims"] == [dict(task_id=tid, claim_id=first_claim.id, text=texts[0])]
    assert repair["failed_claims"] == [dict(task_id=tid, claim_id=failed_claim.id, text=texts[1])]
    if resubmission != "rate_only":
        assert "retained_claim_duplicate" in result["gaps"]
    assert [name for name, _ in seen].count(atomic.GENERATION_NAME) == 2
    assert budget.calls == (4 if resubmission == "duplicate_only" else 5)
    assert budget.repairs == budget.max_repairs == 0
    use = next(row for row in record.detail.evidence_consumptions if row.id == use.id)
    replay = atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view)
    assert replay["claims"] == result["claims"] and replay["reviews"] == result["reviews"]
    assert next(row for row in replay["reviews"] if row.claim_id == first_claim.id) == (
        result["reviews"][0])
    if resubmission == "rate_only":
        receipt_span = next(s for s in record.detail.trace_spans
                            if s.name == "question_atomic_delivery")
        receipt = json.loads(receipt_span.full_output)
        dispatch = next(row for row in receipt["dispatches"]
                        if row["name"] == atomic.GENERATION_NAME and row["attempt"] == 1)
        span = next(s for s in record.detail.trace_spans if s.id == dispatch["span_id"])
        system, raw = span.full_input.split("\nJSON:\n", 1)
        payload = json.loads(raw)
        payload["generation_repair"]["retained_claims"][0]["text"] = "Altered prior text."
        span.full_input = system + "\nJSON:\n" + json.dumps(payload)
        dispatch["full_input_sha256"] = atomic.digest(span.full_input)
        receipt_span.full_output = json.dumps(receipt)
        with pytest.raises(ValueError):
            atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view)


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_first", [False, True])
@pytest.mark.parametrize("failure", ["support_ref", "shape"])
async def test_gen5_same_task_partial_parser_failure_still_repairs_in_either_order(
    monkeypatch, invalid_first, failure,
):
    from packages.research.evidence.report_claims import audit_report_claims

    texts = ["The subscription includes 10 units each month.", "Each additional unit costs $0.02."]
    case = await atomic_case(texts, question="Example Product: What is the exact bill this month?")
    service, record, snapshot, _, view, use, _, boundaries, _ = case
    record.detail.report_answer_boundaries = boundaries
    seen, initial = [], []

    async def model(record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        seen.append((kwargs["name"], payload))
        if kwargs["name"] == atomic.GENERATION_NAME:
            task = payload["generation_tasks"][0]
            if "generation_repair" not in payload:
                bad = (atom(payload, task, texts[1], ref="s999") if failure == "support_ref"
                       else dict(atom(payload, task, texts[1]), unexpected="invalid field"))
                atoms = [atom(payload, task, texts[0]), bad]
                if invalid_first:
                    atoms.reverse()
                response = output(payload, atoms)
                parsed, _, _ = atomic.parse_atomic_generation(response, payload, view, use)
                initial.extend(parsed)
            else:
                expected_reason = ("claim_candidate_invalid" if failure == "support_ref"
                                   else "generation_task_invalid")
                assert expected_reason in payload["generation_repair"]["diagnostics"][0]["reasons"]
                assert payload["generation_repair"]["retained_claims"] == [dict(
                    task_id=task["task_id"], claim_id=initial[0].id, text=texts[0])]
                response = output(payload, [atom(payload, task, texts[1])])
        else:
            assert kwargs["name"] == atomic.REVIEW_NAME
            response = json.dumps({"reviews": [supported_review(payload["claims"][0])]})
        return append_response(service, record, kwargs, response)

    result = await run(case, monkeypatch, model, generation_projection_version=5)
    assert [name for name, _ in seen].count(atomic.GENERATION_NAME) == 2
    audited = audit_report_claims(result["claims"], result["reviews"], view, boundaries,
                                 available_facts=view.facts, review_version=3)
    assert [row.claim.text for row in audited if row.status == "supported"] == texts
    assert result["claims"][0] == initial[0]
    plan = result["compact"]["question_answer_plans"][0]
    assert plan["generation_attempts"][0]["task_results"][0]["diagnostic"] == [
        "claim_candidate_invalid" if failure == "support_ref" else "generation_task_invalid"]
    assert plan["task_results"][0]["state"] == "generated"
    use = next(row for row in record.detail.evidence_consumptions if row.id == use.id)
    replay = atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view)
    assert replay["claims"] == result["claims"] and replay["reviews"] == result["reviews"]
