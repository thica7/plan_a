"""Offline v4 advisory selection, exact publication and version authentication."""

import hashlib
import inspect
import json

import pytest
from claim_review_fixture import answer_response, expand_prompt_payload, question_plan_response
from test_question_atomic_delivery import atomic_case, supported_review
from test_task_support_selection import append_response

from packages.agents.writer import question_atomic_delivery as atomic


def context(case, version=4):
    service, record, _, _, view, use, packets, _, allowed = case
    return atomic.atomic_question_context(
        service, record, view, packets, packets[0]["questions"][0], allowed, use,
        generation_projection_version=version,
    )


async def run(case, monkeypatch, model, **versions):
    service, record, _, selected, view, use, packets, boundaries, allowed = case
    monkeypatch.setattr(service, "_trace_llm_text", model)
    versions.setdefault("generation_projection_version", 4)
    return await atomic.execute_question_atomic_delivery(
        service, record, selected, view, use, packets[0]["questions"], packets,
        allowed, boundaries, (), **versions,
    )


def test_v4_is_only_the_new_execute_default_and_legacy_systems_are_frozen():
    parameters = inspect.signature(atomic.execute_question_atomic_delivery).parameters
    assert parameters["generation_projection_version"].default == 5
    assert parameters["review_projection_version"].default == 3
    assert inspect.signature(atomic.atomic_question_context).parameters[
        "generation_projection_version"
    ].default == 2
    # Fixed d8c9bb63 SYS digests: (phase, generation version, review version, SHA256).
    # These preserve the original nine freeze calls plus the actual review-v1 call.
    frozen = (
        ("gen", 1, 2, "a5c0d0a58490b2a65494742306bc22aa173ffee78c41cda973a9c1d6747016ee"),
        ("gen", 2, 2, "f337f7bbe7480f57c8aa5a7d825b44ff8fcd057c5acc1188131d69154ca4c74a"),
        ("gen", 3, 3, "a5ecc77aaf4df96f6d5c5fca7fe71b993220da0d848970b27454aec906f26ddb"),
        ("review", 1, 2, "75a369e718209b7f3d61c94ddc7e8f6b4b11ca55e58278e6af0858ce45d5302b"),
        ("review", 2, 2, "75a369e718209b7f3d61c94ddc7e8f6b4b11ca55e58278e6af0858ce45d5302b"),
        ("review", 3, 3, "c8d5ba6d11c63ae6665abc87351074f720eccacff3ff4c216d0631416cfdf0db"),
        ("answer", 1, 2, "c748279d051b65201cb022c8ef4b31f74458999a2f8938cbc3b5312504cbf2bb"),
        ("answer", 2, 2, "c748279d051b65201cb022c8ef4b31f74458999a2f8938cbc3b5312504cbf2bb"),
        ("answer", 3, 3, "c748279d051b65201cb022c8ef4b31f74458999a2f8938cbc3b5312504cbf2bb"),
        ("review", 1, 1, "d2cc6a3cfb400e7e0c0bbfde891d9abe29180386f6b8141ce2f853a74f8dab24"),
    )
    names = {"gen": atomic.GENERATION_NAME, "review": atomic.REVIEW_NAME,
             "answer": atomic.ANSWER_NAME}
    for prefix, generation, review, expected in frozen:
        system = atomic.atomic_system(names[prefix], "zh-CN",
            generation_projection_version=generation, review_projection_version=review)
        assert hashlib.sha256(system.encode()).hexdigest() == expected
    system = atomic.atomic_system(atomic.GENERATION_NAME, "zh-CN",
                                  generation_projection_version=4, review_projection_version=3)
    assert system.startswith("Server current-question atomic generation v4.")
    assert "advisory_support_refs" in system and "not a whitelist" in system
    assert "support_catalog" in system and "source_exception_bindings" in system
    assert "support_ref_options" not in system


@pytest.mark.asyncio
async def test_v4_distinguishes_full_catalog_from_advisory_top_three():
    texts = ["Billing notice applies.", "Billing inputs vary.", "Billing depends on usage.",
             "For the Metered plan, CPU time includes 40 million milliseconds monthly; "
             "each additional million CPU milliseconds costs $0.03."]
    case = await atomic_case(texts, question="Example Product: What is the exact bill this month?")
    payload = context(case)
    task = payload["generation_tasks"][0]
    assert task["focus"] == "billing_inputs" and task["max_claims"] == 3
    assert "support_refs" not in task and "support_ref_options" not in task
    assert len(task["advisory_support_refs"]) == 3
    from packages.agents.writer.dimension_writer import _support_ref_catalog
    catalog = _support_ref_catalog(payload, case[4].facts, case[8])
    assert set(payload["support_catalog"]["support_refs"]) == set(catalog)
    assert payload["support_catalog"]["task_hints_are_advisory"] is True
    target = next(s["support_ref"] for row in payload["evidence_view"]["facts"]
                  for s in row["source_span_candidates"] if "40 million" in s["quote"])
    assert target in catalog and target not in task["advisory_support_refs"]
    legacy = context(case, 3)
    assert "support_refs" in legacy["generation_tasks"][0]
    assert "support_ref_options" in legacy["generation_tasks"][0]
    assert "support_catalog" not in legacy


@pytest.mark.asyncio
async def test_v4_hint_outside_cpu_rule_publishes_through_answer_render_and_replay(monkeypatch):
    from packages.agents.writer.dimension_writer import render_dimension_report
    from packages.research.evidence.report_claims import ReportDimensionAudit, audit_report_claims

    texts = ["Billing notice applies.", "Billing inputs vary.", "Billing depends on usage.",
             "For the Metered plan, CPU time includes 40 million milliseconds monthly; "
             "each additional million CPU milliseconds costs $0.03."]
    case = await atomic_case(texts, question="Example Product: What is the exact bill this month?")
    service, record, snapshot, _, view, use, packets, boundaries, _ = case
    record.detail.report_answer_boundaries = boundaries
    seen = []

    async def model(record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        seen.append((kwargs["name"], payload))
        if kwargs["name"] == atomic.GENERATION_NAME:
            assert payload["generation_projection_version"] == 4
            task = payload["generation_tasks"][0]
            span = next(s for row in payload["evidence_view"]["facts"]
                        for s in row["source_span_candidates"] if s["quote"] == texts[-1])
            assert span["support_ref"] not in task["advisory_support_refs"]
            output = json.dumps({"question_plans": [{"question_id": task["question_id"],
                "missing_fields": payload["question_plan_missing_fields"][0]["missing_fields"],
                "atoms": [{"task_id": task["task_id"], "text": texts[-1], "kind": "fact",
                           "support_refs": [span["support_ref"]]}]}]})
        elif kwargs["name"] == atomic.REVIEW_NAME:
            assert payload["review_projection_version"] == 3
            assert payload["claims"][0]["support_quotes"] == [texts[-1]]
            output = json.dumps({"reviews": [supported_review(payload["claims"][0])]})
        else:
            assert kwargs["name"] == atomic.ANSWER_NAME
            output = answer_response(payload, {"version": 3, "answers": [{
                "question_id": payload["questions"][0]["question_id"], "status": "partial",
                "resolution": "direct", "conclusion": "unknown", "missing_fields": [],
                "claim_ids": [c["id"] for c in payload["claims"]],
                "reason": "Known CPU component is stated; total usage is unknown."}]})
        return append_response(service, record, kwargs, output)

    result = await run(case, monkeypatch, model)
    audited = audit_report_claims(result["claims"], result["reviews"], view, boundaries,
                                  available_facts=view.facts, review_version=3)
    assert len(audited) == 1 and audited[0].status == "supported", audited
    claim = audited[0].claim
    assert claim.text == texts[-1] and len(claim.fact_ids) == 1
    assert [s.quote for s in claim.source_span_bindings] == [texts[-1]]
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    answers, gaps, _ = await atomic.atomic_answer_coverage(
        service, record, packets[0]["questions"], result["compact"], [claim], view, use, (),
    )
    assert answers[0].status == "partial" and texts[-1] in answers[0].answer, (answers, gaps)
    audit = ReportDimensionAudit(competitor=view.competitor, dimension=view.dimension,
        consumption_id=use.id, claims=audited, answer_coverage=answers, answer_binding_version=3,
        claim_review_version=3, answer_review_contract="subquestion-premises-v1",
        question_atomic_contract=atomic.CONTRACT,
        question_atomic_receipt_digest=result["compact"]["question_atomic_receipt_digest"])
    record.detail.report_dimension_audits = [audit]
    record.detail.report_md = render_dimension_report(record.detail, [audit], snapshot=snapshot)
    assert texts[-1] in record.detail.report_md
    replay = atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view, audit=audit)
    assert replay["claims"] == result["claims"] and replay["reviews"] == result["reviews"]
    assert tuple(replay["answers"].values()) == answers
    with pytest.raises(ValueError, match="audit receipt binding"):
        atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view,
            audit=audit.model_copy(update={"question_atomic_receipt_digest": "0" * 64}))
    assert [name for name, _ in seen] == [atomic.GENERATION_NAME, atomic.REVIEW_NAME,
                                        atomic.ANSWER_NAME]
    receipt = json.loads(next(s.full_output for s in record.detail.trace_spans
                             if s.name == "question_atomic_delivery"))
    assert receipt["projection_identity"] == "atomic-generation-v4-review-v3"


@pytest.mark.asyncio
@pytest.mark.parametrize("generation,review", [(4, 1), (4, 2), (3, 2), (2, 3), (1, 3),
                                               (True, 3), (4.0, 3), ("4", 3), (4, True)])
async def test_v4_rejects_mixed_or_bad_protocols_before_dispatch(monkeypatch, generation, review):
    case = await atomic_case(["Guests require approval."])

    async def never(*args, **kwargs):
        raise AssertionError("Invalid versions reached a model dispatch")

    with pytest.raises(ValueError):
        await run(case, monkeypatch, never, generation_projection_version=generation,
                  review_projection_version=review)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["delete", "downgrade", "downgrade_identity", "bool",
                                    "dispatch_version", "dispatch_system"])
async def test_v4_replay_rejects_identity_and_dispatch_downgrade(monkeypatch, change):
    case = await atomic_case(["Guests require approval."])
    service, record, snapshot, _, view, use, _, _, _ = case

    async def model(record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        return append_response(service, record, kwargs, question_plan_response(payload, []))

    await run(case, monkeypatch, model)
    receipt_span = next(s for s in record.detail.trace_spans
                        if s.name == "question_atomic_delivery")
    receipt = json.loads(receipt_span.full_output)
    if change == "delete":
        receipt.pop("generation_projection_version")
    elif change == "bool":
        receipt["generation_projection_version"] = True
    elif change.startswith("downgrade"):
        receipt["generation_projection_version"] = 3
        if change == "downgrade_identity":
            receipt["projection_identity"] = "atomic-generation-v3-review-v3"
    else:
        dispatch = next(d for d in receipt["dispatches"] if d["name"] == atomic.GENERATION_NAME)
        span = next(s for s in record.detail.trace_spans if s.id == dispatch["span_id"])
        system, raw = span.full_input.split("\nJSON:\n", 1)
        if change == "dispatch_version":
            body = json.loads(raw)
            body["generation_projection_version"] = 3
            raw = json.dumps(body)
        else:
            system = atomic.atomic_system(
                atomic.GENERATION_NAME, record.detail.output_language,
                generation_projection_version=3, review_projection_version=3,
            )
        span.full_input = system + "\nJSON:\n" + raw
        dispatch["full_input_sha256"] = hashlib.sha256(span.full_input.encode()).hexdigest()
    receipt_span.full_output = json.dumps(receipt)
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    with pytest.raises((ValueError, RuntimeError)):
        atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view)


@pytest.mark.asyncio
async def test_v4_metadata_is_measured_before_14k_assembly():
    from packages.agents.writer.dimension_writer import compact_prompt_json

    text = "Guests require an invitation. Supporting context " + "x" * 5660 + "."
    case = await atomic_case([text], question="Example Product: Do guests require an invitation?")
    for limit in (14000, 5500):
        limited = (*case[:5], case[5].model_copy(update={"max_bytes": limit}), *case[6:])
        payload = context(limited)
        assert len(("\nJSON:\n" + compact_prompt_json(payload)).encode()) <= limit
        assert "support_catalog" in payload


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["outside_question", "unsent", "ambiguous", "combined"])
async def test_v4_catalog_guidance_does_not_authorize_invalid_support(change):
    from copy import deepcopy

    quote = "Observers may vote on cards if voting is enabled for the board."
    case = await atomic_case([quote, quote], question="Example Product: May Observers vote?",
                             source_qualifiers=[{"plan": "Premium"}, {"plan": "Enterprise"}])
    payload = context(case)
    task = payload["generation_tasks"][0]
    refs = [s["support_ref"] for row in payload["evidence_view"]["facts"]
            for s in row["source_span_candidates"] if s["quote"] == quote]
    selected = refs[:1]
    question_id = task["question_id"]
    if change == "outside_question":
        question_id = "foreign-question"
    elif change == "unsent":
        payload["evidence_view"]["facts"] = payload["evidence_view"]["facts"][1:]
    elif change == "ambiguous":
        payload["evidence_view"]["facts"].append(deepcopy(payload["evidence_view"]["facts"][0]))
    else:
        selected = refs
    response = json.dumps({"question_plans": [{"question_id": question_id,
        "missing_fields": payload["question_plan_missing_fields"][0]["missing_fields"],
        "atoms": [{"task_id": task["task_id"], "text": quote, "kind": "fact",
                   "support_refs": selected}]}]})
    if change == "outside_question":
        with pytest.raises(ValueError, match="unexpected question plan"):
            atomic.parse_atomic_generation(response, payload, case[4], case[5])
        return
    claims, gaps, _ = atomic.parse_atomic_generation(response, payload, case[4], case[5])
    assert not claims and gaps


@pytest.mark.asyncio
async def test_v4_selected_wrong_condition_still_requires_independent_review(monkeypatch):
    from packages.research.evidence.report_claims import audit_report_claims

    source = "Observers may vote on cards if voting is enabled for the board."
    case = await atomic_case([source], question="Example Product: May Observers vote?")
    service = case[0]
    reviewed = []

    async def model(record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        if kwargs["name"] == atomic.GENERATION_NAME:
            ref = payload["support_catalog"]["support_refs"][0]
            output = question_plan_response(payload, [dict(
                text="Observers may always vote on cards.", kind="fact", support_refs=[ref])])
        else:
            reviewed.append(payload)
            claim = payload["claims"][0]
            assert claim["support_quotes"] == [source]
            output = json.dumps({"reviews": [{"claim_id": claim["id"], "verdict": "unsupported",
                "checks": [], "reason": "The selected source requires voting to be enabled."}]})
        return append_response(service, record, kwargs, output)

    result = await run(case, monkeypatch, model)
    audited = audit_report_claims(result["claims"], result["reviews"], case[4], case[7],
                                  available_facts=case[4].facts, review_version=3)
    assert reviewed and audited and all(row.status != "supported" for row in audited)


@pytest.mark.asyncio
async def test_v4_preserves_quantity_billing_capacity_and_fair_eight_atom_order():
    from packages.agents.writer.atomic_question_projection import scoped_generation_response

    case = await atomic_case(["Guests require approval."],
                             question="Example Product: What rules apply?")
    payload = context(case)
    base = payload["generation_tasks"][0]
    payload["generation_tasks"] = [
        dict(base, task_id="rules", focus="source_rule", max_claims=3),
        dict(base, task_id="bill", focus="billing_inputs", max_claims=3),
        dict(base, task_id="people", focus="source_rule", request_property="people_limit",
             max_claims=2),
        dict(base, task_id="containers", focus="source_rule", request_property="container_limit",
             max_claims=2),
    ]
    atoms = [dict(task_id=task["task_id"], text=f"Predicate {task['task_id']} {i}.", kind="fact",
                  support_refs=payload["support_catalog"]["support_refs"][:1])
             for task in payload["generation_tasks"] for i in range(task["max_claims"])]
    response = json.dumps({"question_plans": [{
        "question_id": base["question_id"], "missing_fields": [], "atoms": atoms}]})
    raw, gaps, _, bindings = scoped_generation_response(response, payload, forecast=True)
    assert not gaps
    assert [b["task_id"] for b in bindings] == [
        "rules", "bill", "people", "containers", "rules", "bill", "people", "containers",
        "rules", "bill",
    ]
    # The unchanged strict plan parser owns the final total cap of eight.
    assert len(json.loads(raw)["question_plans"][0]["atoms"]) == 10
    claims, _, plans = atomic.parse_atomic_generation(response, payload, case[4], case[5],
                                                     _forecast=True)
    assert len(claims) == 8
    assert {row["task_id"]: len(row.get("claim_ids", []))
            for row in plans[0]["task_results"]} == {
        "rules": 2, "bill": 2, "people": 2, "containers": 2,
    }


@pytest.mark.asyncio
async def test_v4_retains_dangling_modal_filter_and_separate_fact_conditions():
    from packages.agents.writer.atomic_question_projection import advisory_generation_projection

    complete = "Observers may vote if voting is enabled."
    payload = {"evidence_view": {"facts": [
        {"id": "first", "qualifiers": {"plan": "Premium"}, "source_span_candidates": [
            {"support_ref": "s1", "quote": "Observers may"},
            {"support_ref": "s2", "quote": complete}]},
        {"id": "second", "qualifiers": {"plan": "Enterprise"}, "source_span_candidates": [
            {"support_ref": "s3", "quote": complete}]},
    ]}, "generation_tasks": [{"task_id": "t", "focus": "source_rule", "state": "planned",
                               "support_refs": ["s1", "s2", "s3"]}]}
    projected = advisory_generation_projection(payload)
    assert projected["support_catalog"]["support_refs"] == ["s2", "s3"]
    assert projected["generation_tasks"][0]["advisory_support_refs"] == ["s2", "s3"]
    assert len(projected["evidence_view"]["facts"]) == 2
    assert payload["generation_tasks"][0]["support_refs"] == ["s1", "s2", "s3"]


@pytest.mark.asyncio
@pytest.mark.parametrize("property_name,question,source,inference", [
    ("people_limit", "Example Product: Can I use three people and four vaults?",
     "The Free plan supports up to two people.",
     "Given three people, the Free plan's maximum of two people cannot meet that requirement."),
    ("container_limit", "Example Product: Can I use three people and four vaults?",
     "The Free plan supports up to two vaults.",
     "Given three vaults, the Free plan's maximum of two vaults cannot meet that requirement."),
])
async def test_v4_real_quantity_task_accepts_fact_and_separate_conditional_application(
        property_name, question, source, inference):
    case = await atomic_case([source], question=question)
    payload = context(case)
    task = next(t for t in payload["generation_tasks"]
                if t.get("request_property") == property_name)
    assert task["max_claims"] == 2
    ref = task["advisory_support_refs"][0]
    response = json.dumps({"question_plans": [{"question_id": task["question_id"],
        "missing_fields": [], "atoms": [dict(task_id=task["task_id"], text=text, kind=kind,
            support_refs=[ref]) for text, kind in ((source, "fact"), (inference, "inference"))]}]})
    claims, gaps, _ = atomic.parse_atomic_generation(response, payload, case[4], case[5])
    assert [claim.text for claim in claims] == [source, inference], gaps


@pytest.mark.asyncio
@pytest.mark.parametrize("shortfall", [0, 1])
async def test_v4_exact_actual_envelope_budget_boundary_dispatches_only_when_affordable(
        monkeypatch, shortfall):
    from dataclasses import replace

    import httpx
    from test_question_atomic_delivery import active_atomic_budget

    from packages.agents.writer.dimension_writer import compact_prompt_json
    from packages.llm import DoubaoClient

    case = await atomic_case(["Guests require approval."],
                             question="Example Product: Do guests require approval?")
    service, record, _, selected, view, use, packets, boundaries, allowed = case
    budget = active_atomic_budget(service, record)
    system = atomic.atomic_system(atomic.GENERATION_NAME, record.detail.output_language,
                                  generation_projection_version=4, review_projection_version=3)
    user = "\nJSON:\n" + compact_prompt_json(context(case))
    full, input_tokens, output_tokens = service._llm_request_envelope(
        system=system, user=user, max_output_tokens=1600,
    )
    phase = service._llm_phase("writer", f"{view.competitor}/{view.dimension}",
                               name=atomic.GENERATION_NAME, record=record)
    protected = budget.protected_tokens(phase)
    budget.tokens_used = budget.max_tokens - protected - input_tokens - output_tokens + shortfall
    before_calls = budget.calls
    transported = []
    service._llm = DoubaoClient(replace(service._settings, demo_mode=False,
        ark_api_key="offline-test", ark_model="offline-test", ark_base_url="https://example.invalid",
        llm_max_retries=0))

    async def post(url, payload, headers):
        assert [row["content"] for row in payload["messages"]] == [system, user]
        transported.append(payload)
        return httpx.Response(200, json={"choices": [{"message": {
            "content": question_plan_response(context(case), [])}}],
            "usage": {"prompt_tokens": 500, "completion_tokens": 50}})

    monkeypatch.setattr(service._llm, "_post_chat_completion", post)
    result = await atomic.execute_question_atomic_delivery(
        service, record, selected, view, use, packets[0]["questions"], packets,
        allowed, boundaries, (), generation_projection_version=4,
    )
    assert len(transported) == int(shortfall == 0)
    assert budget.calls == before_calls + int(shortfall == 0)
    assert budget.tokens_reserved == 0
    preflight = next(json.loads(s.full_output) for s in record.detail.trace_spans
                     if s.name == "question_atomic_budget_preflight")
    current = preflight["current_request"]
    assert current["full_input_sha256"] == hashlib.sha256(full.encode()).hexdigest()
    assert current["system_bytes"] == len(system.encode())
    assert current["user_bytes"] == len(user.encode())
    assert current["input_tokens"] == input_tokens
    assert current["admitted"] is (shortfall == 0)
    assert current["reason"] == ("run_llm_budget_reserved_for_delivery" if shortfall else None)
    if shortfall:
        assert result["compact"]["question_answer_plans"][0]["reason"] == (
            "question_delivery_budget_unavailable")
        assert not result["compact"]["dispatches"]
