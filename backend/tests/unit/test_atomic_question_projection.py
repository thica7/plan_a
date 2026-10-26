"""Offline checks for the current-question generation projection and replay."""

import json

import pytest
from test_question_atomic_delivery import atomic_case, execute

from packages.agents.writer.question_atomic_delivery import (
    GENERATION_NAME,
    atomic_question_context,
    atomic_system,
    parse_atomic_generation,
    replay_atomic_delivery,
)


def context(case):
    service, record, _, _, view, use, packets, _, allowed = case
    return atomic_question_context(
        service, record, view, packets, packets[0]["questions"][0], allowed, use
    )


def response(payload, atoms):
    return json.dumps(
        dict(
            question_plans=[
                dict(
                    question_id=payload["questions"][0]["question_id"],
                    missing_fields=payload["question_plan_missing_fields"][0]["missing_fields"],
                    atoms=atoms,
                )
            ]
        )
    )


@pytest.mark.asyncio
async def test_generation_has_server_tasks_and_independent_system_identity():
    case = await atomic_case(
        ["Observers may vote if voting is enabled."],
        question="Example Product: Can observers vote on boards A and B?",
    )
    payload = context(case)
    assert payload.get("generation_projection_version") == 2
    tasks = payload.get("generation_tasks", [])
    assert {t["focus"] for t in tasks} == {"rule_vote", "vote"}
    assert {t.get("resource") for t in tasks if t["focus"] == "vote"} == {"A", "B"}
    assert all(t["task_id"] and t["question_quote"] for t in tasks)
    assert "COMPLETE original question" not in atomic_system(GENERATION_NAME, "en")
    assert "server-owned" in atomic_system(GENERATION_NAME, "en")


@pytest.mark.asyncio
async def test_people_and_containers_have_separate_finite_request_tasks():
    case = await atomic_case(
        [
            "Free organizations may have up to two users.",
            "Free organizations may have up to two collections.",
        ],
        question="Example Product：免费组织最多几名用户、几个容器？",
    )
    tasks = context(case).get("generation_tasks", [])
    assert {t.get("request_property") for t in tasks} >= {"people_limit", "container_limit"}


@pytest.mark.asyncio
async def test_complete_core_original_is_packed_before_short_zero_score_background():
    from test_writer_question_delivery import billing_original

    quote, conditions, table = billing_original()
    core = quote
    retained = conditions + ["Complete retained billing context. " * 140]
    case = await atomic_case(
        ["Administrators may change settings.", core],
        question="Example Product Compute Paid Standard 本月有2300万次请求，账单准确是多少美元？",
        source_qualifiers=[{}, dict(condition_evidence=retained, table_context=table[:1])],
    )
    case = (*case[:5], case[5].model_copy(update={"max_bytes": 8600}), *case[6:])
    packets = case[6]
    # The verified question pool records core membership independently of length.
    pool = packets[0]["retrieval"]["evidence_pool"]["questions"][0]
    core_id = next(f.id for f in case[4].facts if f.quote == core and f.field == "evidence_terms")
    assert core_id in pool["core_fact_ids"], pool
    legacy = atomic_question_context(
        case[0],
        case[1],
        case[4],
        packets,
        packets[0]["questions"][0],
        case[8],
        case[5],
        generation_projection_version=1,
    )
    assert core_id not in {r["id"] for r in legacy["evidence_view"]["facts"]}
    payload = context(case)
    assert core_id in {r["id"] for r in payload["evidence_view"]["facts"]}
    assert next(r for r in payload["evidence_view"]["facts"] if r["id"] == core_id)["quote"] == core
    assert core_id not in payload.get("missing_core_fact_ids", [])


@pytest.mark.asyncio
async def test_finite_property_task_rejects_sibling_rule_and_keeps_peer():
    case = await atomic_case(
        [
            "Free organizations may have up to two users.",
            "Free organizations may have up to two collections.",
        ],
        question="Example Product：3个人用3个collections，免费组织能满足吗？",
    )
    payload = context(case)
    tasks = {t["request_property"]: t for t in payload["generation_tasks"]}
    container = tasks["container_limit"]
    atom = dict(
        task_id=container["task_id"],
        text="Free organizations may have up to two collections.",
        kind="fact",
        support_refs=container["support_refs"][:1],
    )
    wrong = dict(atom, task_id=tasks["people_limit"]["task_id"])
    claims, _, plans = parse_atomic_generation(
        response(payload, [wrong, atom]), payload, case[4], case[5]
    )
    assert len(claims) == 1
    outcomes = {t["task_id"]: t for t in plans[0]["task_results"]}
    assert outcomes[tasks["people_limit"]["task_id"]]["state"] == "rejected"
    assert outcomes[container["task_id"]]["claim_ids"] == [claims[0].id]


@pytest.mark.asyncio
async def test_generic_rules_are_bounded_and_do_not_displace_explicit_task():
    quotes = [f"Guests have a limit of {i + 1} items in category {i}." for i in range(9)]
    case = await atomic_case(
        [*quotes, "Guests can download attachments."],
        question="Example Product: What are guest limits; can guests download attachments?",
    )
    payload = context(case)
    tasks = {t["focus"]: t for t in payload["generation_tasks"]}
    generic, download = tasks["source_rule"], tasks["download"]
    assert 1 <= generic["max_claims"] <= 3
    spans = {
        span["quote"]: span["support_ref"]
        for row in payload["evidence_view"]["facts"]
        for span in row["source_span_candidates"]
    }
    atoms = [
        dict(task_id=generic["task_id"], text=quote, kind="fact", support_refs=[spans[quote]])
        for quote in quotes
    ]
    atoms.append(
        dict(
            task_id=download["task_id"],
            text="Guests can download attachments.",
            kind="fact",
            support_refs=download["support_refs"][:1],
        )
    )
    claims, _, plans = parse_atomic_generation(response(payload, atoms), payload, case[4], case[5])
    assert len(claims) == generic["max_claims"] + 1
    assert any(c.text == "Guests can download attachments." for c in claims)
    assert (
        next(t for t in plans[0]["task_results"] if t["task_id"] == generic["task_id"])[
            "deferred_atom_count"
        ]
        == 6
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "Example Product：3个人用3个collections，免费组织能满足吗？",
        "Example Product: Can 3 people share 3 collections on a free organization?",
    ],
)
async def test_numeric_people_and_containers_are_independent_tasks(question):
    case = await atomic_case(
        [
            "Free organizations may have up to two users.",
            "Free organizations may have up to two collections.",
        ],
        question=question,
    )
    assert {t.get("request_property") for t in context(case)["generation_tasks"]} >= {
        "people_limit",
        "container_limit",
    }


@pytest.mark.asyncio
async def test_catalogued_operation_task_hints_match_operation():
    case = await atomic_case(
        ["Guests can read boards.", "Guests can edit boards."],
        question="Example Product: Can guests read boards and edit boards?",
    )
    payload = context(case)
    tasks = payload["generation_tasks"]
    assert {t["focus"] for t in tasks} == {"read", "edit"}
    catalog = {
        ref: op["operation"]
        for row in payload["evidence_view"]["facts"]
        for ref, op in zip(
            row["operation_support_refs"], row["operation_observations"], strict=True
        )
    }
    for task in tasks:
        assert task["support_refs"]
        assert all(catalog[ref] == task["focus"] for ref in task["support_refs"])


@pytest.mark.asyncio
async def test_invalid_support_never_marks_task_generated():
    case = await atomic_case(["Guests have no personal area."])
    payload = context(case)
    task = payload["generation_tasks"][0]
    atom = dict(
        task_id=task["task_id"],
        text="Guests have no personal area.",
        kind="fact",
        support_refs=["s999"],
    )
    claims, _, plans = parse_atomic_generation(response(payload, [atom]), payload, case[4], case[5])
    assert claims == []
    assert all(t["state"] != "generated" for t in plans[0]["task_results"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "quote",
    [
        "Because Observer is not a membership type, changing the role does not affect billing.",
        "If X and Y then guests may export unless Z.",
    ],
)
async def test_complete_causal_and_unpunctuated_conditional_clauses_remain(quote):
    case = await atomic_case([quote])
    assert [
        s["quote"] for s in context(case)["evidence_view"]["facts"][0]["source_span_candidates"]
    ] == [quote]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad", ["Workers", "Because guests are not a membership", "| Plan | Users |\n| Free | 2 |"]
)
async def test_incomplete_legal_candidates_are_not_generation_support(bad):
    case = await atomic_case([bad], question="Example Product: What are the guest rules?")
    payload = context(case)
    assert payload["evidence_view"]["facts"][0]["source_span_candidates"] == []
    assert payload.get("generation_support_gaps")


@pytest.mark.asyncio
async def test_complete_and_or_and_exception_group_is_preserved_exactly():
    quote = "Observers may vote if X and Y or W are enabled, unless Z applies."
    case = await atomic_case([quote], question="Example Product: Can observers vote?")
    payload = context(case)
    assert [s["quote"] for s in payload["evidence_view"]["facts"][0]["source_span_candidates"]] == [
        quote
    ]
    refs = {
        s["support_ref"]
        for r in payload["evidence_view"]["facts"]
        for s in r["source_span_candidates"]
    }
    assert refs == {
        ref for task in payload.get("generation_tasks", []) for ref in task["support_refs"]
    }


@pytest.mark.asyncio
async def test_unknown_and_duplicate_task_atoms_do_not_consume_peer_capacity():
    case = await atomic_case(
        ["Observers can download attachments.", "Observers can export boards."],
        question="Example Product: Can observers download attachments and export boards?",
    )
    payload = context(case)
    tasks = payload.get("generation_tasks", [])
    assert tasks
    download = next(t for t in tasks if t["focus"] == "download")
    export = next(t for t in tasks if t["focus"] == "export")

    def atom(task, text):
        return dict(
            task_id=task["task_id"], text=text, kind="fact", support_refs=task["support_refs"][:1]
        )

    duplicate = atom(download, "Observers can download attachments.")
    peer = atom(export, "Observers can export boards.")
    bad = [dict(peer, task_id=f"unknown-{i}") for i in range(9)]
    claims, gaps, plans = parse_atomic_generation(
        response(payload, [*bad, duplicate, duplicate, peer]), payload, case[4], case[5]
    )
    assert [c.text for c in claims] == [peer["text"]]
    assert "generation_task_invalid" in gaps
    assert plans[0]["task_results"]


@pytest.mark.asyncio
async def test_replay_exposes_question_local_actual_originals(monkeypatch):
    case = await atomic_case(
        ["Guests have no personal area."],
        question="Example Product: Do guests have a personal area?",
    )
    result, _ = await execute(case, monkeypatch)
    use = next(u for u in case[1].detail.evidence_consumptions if u.id == case[5].id)
    replay = replay_atomic_delivery(case[0], case[1].detail, case[2], use, case[4])
    qid = case[6][0]["questions"][0]["question_id"]
    assert replay.get("facts_by_question", {}).get(qid) == replay["facts"]
    assert result["compact"].get("generation_projection_version") == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("version", [True, False, 0, 4, "2", None])
async def test_generation_version_is_exact_and_rejects_unknown_receipt_values(monkeypatch, version):
    case = await atomic_case(["Guests have no personal area."])
    await execute(case, monkeypatch)
    receipt = next(s for s in case[1].detail.trace_spans if s.name == "question_atomic_delivery")
    body = json.loads(receipt.full_output)
    body["generation_projection_version"] = version
    receipt.full_output = json.dumps(body)
    use = next(u for u in case[1].detail.evidence_consumptions if u.id == case[5].id)
    with pytest.raises(ValueError):
        replay_atomic_delivery(case[0], case[1].detail, case[2], use, case[4])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "delete_version",
        "downgrade",
        "tasks",
        "core",
        "refs",
        "quote",
        "unused_table",
        "nested_table",
        "duplicate_json",
    ],
)
async def test_v2_actual_generation_encoding_and_receipt_cannot_be_rewritten(monkeypatch, change):
    from packages.agents.writer.question_atomic_delivery import digest

    case = await atomic_case(["Guests have no personal area."])
    await execute(case, monkeypatch)
    receipt_span = next(
        s for s in case[1].detail.trace_spans if s.name == "question_atomic_delivery"
    )
    receipt = json.loads(receipt_span.full_output)
    dispatch = next(d for d in receipt["dispatches"] if d["name"] == GENERATION_NAME)
    span = next(s for s in case[1].detail.trace_spans if s.id == dispatch["span_id"])
    system, raw = span.full_input.split("\nJSON:\n", 1)
    body = json.loads(raw)
    if change == "delete_version":
        receipt.pop("generation_projection_version")
    elif change == "downgrade":
        receipt["generation_projection_version"] = 1
    else:
        if change == "tasks":
            body["generation_tasks"][0]["question_quote"] = "Invented task."
        elif change == "core":
            body["missing_core_fact_ids"] = ["invented-core"]
        elif change == "refs":
            body["generation_tasks"][0]["support_refs"] = ["s999"]
        elif change == "quote":
            body["evidence_view"]["facts"][0]["quote"] = "Invented original."
        elif change == "unused_table":
            body.setdefault("text_sets", {})["unused"] = "Hidden sibling permission."
        elif change == "nested_table":
            body["evidence_view"]["text_sets"] = {"unused": "Hidden sibling permission."}
        raw = json.dumps(body)
        if change == "duplicate_json":
            raw = '{"generation_projection_version":1,' + raw[1:]
        span.full_input = system + "\nJSON:\n" + raw
        dispatch["full_input_sha256"] = digest(span.full_input)
    receipt_span.full_output = json.dumps(receipt)
    use = next(u for u in case[1].detail.evidence_consumptions if u.id == case[5].id)
    with pytest.raises(ValueError):
        replay_atomic_delivery(case[0], case[1].detail, case[2], use, case[4])


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_version", [False, True])
async def test_legacy_generation_replays_its_actual_old_system_catalog_and_parser(missing_version):
    from claim_review_fixture import question_plan_response
    from test_task_support_selection import append_response

    from packages.agents.writer.dimension_writer import compact_prompt_json
    from packages.agents.writer.question_atomic_delivery import dispatch_row, save_atomic_receipt

    case = await atomic_case()
    service, record, snapshot, _, view, use, packets, _, allowed = case
    payload = atomic_question_context(
        service,
        record,
        view,
        packets,
        packets[0]["questions"][0],
        allowed,
        use,
        generation_projection_version=1,
    )
    assert "generation_tasks" not in payload and "generation_projection_version" not in payload
    system = atomic_system(
        GENERATION_NAME, record.detail.output_language, generation_projection_version=1
    )
    assert "COMPLETE original question" in system
    atoms = [
        dict(text=s["quote"], kind="fact", support_refs=[s["support_ref"]])
        for row in payload["evidence_view"]["facts"]
        for s in row["source_span_candidates"]
    ]
    output = question_plan_response(payload, atoms)
    append_response(
        service,
        record,
        dict(
            name=GENERATION_NAME,
            agent="writer",
            subagent=f"{view.competitor}/{view.dimension}",
            system=system,
            user="\nJSON:\n" + compact_prompt_json(payload),
        ),
        output,
    )
    service._validate_evidence_use(record, use)
    claims, _, plans = parse_atomic_generation(output, payload, view, use)
    assert len(claims) == 3 and "task_results" not in plans[0]
    span = record.detail.trace_spans[-1]
    compact = dict(
        review_projection_version=1,
        generation_projection_version=1,
        question_answer_plans=plans,
        dispatches=[
            dispatch_row(
                span,
                question_ids=[payload["questions"][0]["question_id"]],
                claim_ids=[c.id for c in claims],
                fact_ids={r["id"] for r in payload["evidence_view"]["facts"]},
            )
        ],
    )
    save_atomic_receipt(service, record, compact, view, use, packets)
    if missing_version:
        receipt_span = next(
            s for s in record.detail.trace_spans if s.name == "question_atomic_delivery"
        )
        receipt = json.loads(receipt_span.full_output)
        receipt.pop("generation_projection_version")
        receipt.pop("review_projection_version")
        receipt_span.full_output = json.dumps(receipt)
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    assert replay_atomic_delivery(service, record.detail, snapshot, use, view)["claims"] == claims


@pytest.mark.asyncio
async def test_unsent_question_does_not_borrow_another_questions_actual_originals(monkeypatch):
    from test_question_atomic_delivery import atomic_model

    question = (
        "Example Product: Do guests have a personal area?\n"
        "Example Product: Do guests require an invitation?"
    )
    case = await atomic_case(
        ["Guests have no personal area.", "Guests require an invitation."], question=question
    )
    service, record, snapshot, _, view, _, packets, _, _ = case
    base_model = atomic_model(service, {})
    count = 0

    async def model(record, **kwargs):
        nonlocal count
        result = await base_model(record, **kwargs)
        if kwargs["name"] == GENERATION_NAME:
            count += 1
            if count == 2:
                record.detail.trace_spans[-1].metadata["llm_transport_attempts"] = 0
        return result

    monkeypatch.setattr(service, "_trace_llm_text", model)
    from packages.agents.writer.question_atomic_delivery import execute_question_atomic_delivery

    await execute_question_atomic_delivery(
        service,
        record,
        case[3],
        view,
        case[5],
        packets[0]["questions"],
        packets,
        case[8],
        case[7],
        (),
    )
    use = next(u for u in record.detail.evidence_consumptions if u.id == case[5].id)
    replay = replay_atomic_delivery(service, record.detail, snapshot, use, view)
    first, second = [q["question_id"] for q in packets[0]["questions"]]
    assert replay["facts"] and replay["facts_by_question"][first]
    assert replay["facts_by_question"][second] == []


@pytest.mark.asyncio
async def test_parent_multi_operation_premises_do_not_expand_current_vote_tasks():
    parent = (
        "Example Product: An observer is on boards A and B. "
        "Can the observer vote on boards A and B? Can the observer download attachments? "
        "Can the observer export boards? Does permission imply obligation?"
    )
    case = await atomic_case(["Observers may vote if voting is enabled."], question=parent)
    payload = context(case)
    assert {task["focus"] for task in payload["generation_tasks"]} == {"rule_vote", "vote"}
    assert payload["request_context"]["parents"][0]["text"] == parent


@pytest.mark.asyncio
async def test_filtered_alias_gaps_and_equal_quotes_keep_distinct_verified_refs():
    from packages.agents.writer.readable_support import support_ref_catalog

    vote = "Observers may vote on cards."
    case = await atomic_case(
        ["Workers\n\n" + vote, vote], question="Example Product: Can observers vote?"
    )
    payload = context(case)
    refs = [
        s["support_ref"]
        for row in payload["evidence_view"]["facts"]
        for s in row["source_span_candidates"]
    ]
    assert "s1" not in refs and len(refs) == len(set(refs)) == 2
    catalog = support_ref_catalog(
        payload, case[4].facts, {r["id"] for r in payload["evidence_view"]["facts"]}
    )
    assert set(refs) == set(catalog)
    assert {ref for task in payload["generation_tasks"] for ref in task["support_refs"]} == set(
        refs
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("table", [{"header": "bad"}, True, 7, "header", [True], [None]])
async def test_bad_table_context_only_drops_its_candidate_and_keeps_peer(table):
    case = await atomic_case(
        ["| Free | 2 |", "Guests have no personal area."],
        source_qualifiers=[dict(table_context=table), {}],
    )
    payload = context(case)
    rows = payload["evidence_view"]["facts"]
    bad = next(row for row in rows if row["quote"].startswith("|"))
    assert bad["source_span_candidates"] == []
    assert any(row["source_span_candidates"] for row in rows)


@pytest.mark.asyncio
async def test_invalid_generation_still_records_each_missing_task(monkeypatch):
    from test_task_support_selection import append_response

    case = await atomic_case(["Guests have no personal area."])
    service, record, snapshot, _, view, _, _, _, _ = case

    async def model(record, **kwargs):
        assert kwargs["name"] == GENERATION_NAME
        return append_response(service, record, kwargs, "not JSON")

    monkeypatch.setattr(service, "_trace_llm_text", model)
    from packages.agents.writer.question_atomic_delivery import execute_question_atomic_delivery

    result = await execute_question_atomic_delivery(
        service,
        record,
        case[3],
        view,
        case[5],
        case[6][0]["questions"],
        case[6],
        case[8],
        case[7],
        (),
    )
    expected = {t["task_id"] for t in context(case)["generation_tasks"]}
    outcomes = result["compact"]["question_answer_plans"][0].get("task_results", [])
    assert {t["task_id"] for t in outcomes} == expected
    use = next(u for u in record.detail.evidence_consumptions if u.id == case[5].id)
    assert replay_atomic_delivery(service, record.detail, snapshot, use, view)["claims"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("hiding_place", ["unused_table", "nested_table"])
async def test_v2_answer_actual_encoding_rejects_unused_support_pool(monkeypatch, hiding_place):
    from claim_review_fixture import answer_response, expand_prompt_payload
    from test_task_support_selection import append_response

    from packages.agents.writer.question_atomic_delivery import (
        ANSWER_NAME,
        atomic_answer_coverage,
        digest,
    )
    from packages.research.evidence.report_claims import audit_report_claims

    case = await atomic_case(
        ["Guests have no personal area."],
        question="Example Product: Do guests have a personal area?",
    )
    service, record, snapshot, _, view, _, packets, boundaries, _ = case
    record.detail.report_answer_boundaries = boundaries
    result, _ = await execute(case, monkeypatch)
    audited = audit_report_claims(
        result["claims"],
        result["reviews"],
        view,
        boundaries,
        available_facts=view.facts,
        review_version=3,
    )
    supported = [row.claim for row in audited if row.status == "supported"]

    async def model(record, **kwargs):
        assert kwargs["name"] == ANSWER_NAME
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        output = answer_response(
            payload,
            dict(
                version=3,
                answers=[
                    dict(
                        question_id=payload["questions"][0]["question_id"],
                        status="answered",
                        claim_ids=[claim.id for claim in supported],
                        resolution="direct",
                        conclusion="no",
                        missing_fields=[],
                        reason="The reviewed source denies a personal area.",
                    )
                ],
            ),
            relation="explicit_negative",
        )
        return append_response(service, record, kwargs, output)

    monkeypatch.setattr(service, "_trace_llm_text", model)
    use = next(u for u in record.detail.evidence_consumptions if u.id == case[5].id)
    await atomic_answer_coverage(
        service, record, packets[0]["questions"], result["compact"], supported, view, use, ()
    )
    receipt_span = next(
        s for s in record.detail.trace_spans if s.name == "question_atomic_delivery"
    )
    receipt = json.loads(receipt_span.full_output)
    dispatch = next(d for d in receipt["dispatches"] if d["name"] == ANSWER_NAME)
    span = next(s for s in record.detail.trace_spans if s.id == dispatch["span_id"])
    system, raw = span.full_input.split("\nJSON:\n", 1)
    body = json.loads(raw)
    if hiding_place == "unused_table":
        body.setdefault("text_sets", {})["unused"] = "Unselected sibling permission."
    else:
        body["claims"][0]["text_sets"] = {"unused": "Unselected sibling permission."}
    span.full_input = system + "\nJSON:\n" + json.dumps(body)
    dispatch["full_input_sha256"] = digest(span.full_input)
    receipt_span.full_output = json.dumps(receipt)
    with pytest.raises(ValueError):
        replay_atomic_delivery(service, record.detail, snapshot, use, view)


@pytest.mark.asyncio
@pytest.mark.parametrize("quote", ["Guests can edit documents", "Guests have no personal area"])
async def test_complete_unpunctuated_source_predicates_remain_available(quote):
    case = await atomic_case([quote])
    payload = context(case)
    assert [
        s["quote"]
        for row in payload["evidence_view"]["facts"]
        for s in row["source_span_candidates"]
    ] == [quote]


@pytest.mark.asyncio
async def test_generic_role_question_does_not_plan_six_unrequested_operations():
    case = await atomic_case(
        ["Guest roles have a collection limit."], question="Example Product: What are guest roles?"
    )
    assert {t["focus"] for t in context(case)["generation_tasks"]} == {"source_rule"}


@pytest.mark.asyncio
async def test_scope_assignment_task_remains_a_source_rule():
    question = (
        "Example Product：同事只被授予 example.com 的 Cache Domain Purge 角色，"
        "没有任何其他角色。他能清除 other.example 的缓存吗？"
    )
    case = await atomic_case(
        ["Roles apply to the scope where they are assigned."], question=question
    )
    tasks = context(case)["generation_tasks"]
    assert any(task["focus"] == "source_rule" for task in tasks)
    assert not {"read", "comment", "edit", "create", "share", "manage_access"} & {
        task["focus"] for task in tasks
    }


@pytest.mark.asyncio
async def test_catalogued_operation_resources_get_independent_rule_and_outcomes():
    case = await atomic_case(
        ["Guests can read boards shared with them."],
        question="Example Product: Can guests read boards A and B?",
    )
    tasks = context(case)["generation_tasks"]
    assert {task["focus"] for task in tasks} == {"rule_read", "read"}
    assert {task.get("resource") for task in tasks if task["focus"] == "read"} == {"A", "B"}


@pytest.mark.asyncio
async def test_task_beyond_eight_remains_explicitly_deferred_even_if_model_outputs_it():
    question = (
        "Example Product: " + "; ".join(f"How many items in category {i}" for i in range(9)) + "?"
    )
    case = await atomic_case(["Guests have a limit of two items."], question=question)
    payload = context(case)
    tasks = payload["generation_tasks"]
    assert len(tasks) == 9 and tasks[-1]["state"] == "deferred"
    span = payload["evidence_view"]["facts"][0]["source_span_candidates"][0]
    atom = dict(
        task_id=tasks[-1]["task_id"],
        text=span["quote"],
        kind="fact",
        support_refs=[span["support_ref"]],
    )
    claims, _, plans = parse_atomic_generation(response(payload, [atom]), payload, case[4], case[5])
    assert claims == []
    assert plans[0]["task_results"][-1]["state"] == "deferred"
    assert plans[0]["task_results"][-1]["reason"] == "task_capacity_exceeded"


@pytest.mark.asyncio
async def test_complete_cpu_support_does_not_require_future_whole_row_to_be_one_predicate(
    monkeypatch,
):
    from test_writer_question_delivery import billing_original

    quote, conditions, table = billing_original()
    quote = quote[:-1] + " Max of 5 minutes per invocation (default: 30 seconds) |"
    case = await atomic_case(
        [quote],
        question="Example Product Compute Paid Standard 本月账单准确是多少美元？",
        source_qualifiers=[dict(condition_evidence=conditions, table_context=table[:1])],
    )
    _, seen = await execute(case, monkeypatch)
    assert len(seen.get(GENERATION_NAME, [])) == 1
    assert seen[GENERATION_NAME][0]["evidence_view"]["facts"][0]["quote"] == quote


@pytest.mark.asyncio
async def test_empty_semantic_forecast_cannot_veto_current_transport_or_charge_budget(monkeypatch):
    from test_question_atomic_delivery import (
        test_live_checkpoint_current_requests_run_despite_nonbinding_future_forecast as exercise,
    )

    from packages.agents.writer import question_atomic_delivery as atomic

    original = atomic.parse_atomic_generation

    def parse(response, payload, view, use, *, _forecast=False):
        if _forecast:
            return (
                [],
                set(),
                [
                    dict(
                        question_id=payload["questions"][0]["question_id"],
                        claim_ids=[],
                        missing_fields=payload["question_plan_missing_fields"][0]["missing_fields"],
                    )
                ],
            )
        return original(response, payload, view, use)

    monkeypatch.setattr(atomic, "parse_atomic_generation", parse)
    # This exercises three actual HTTP-stub transports and exact call/token/
    # reserve accounting, with a rejected whole future-chain forecast.
    await exercise(monkeypatch, 6, 22848, 5)


@pytest.mark.asyncio
async def test_identical_predicate_with_distinct_verified_refs_cannot_spend_two_slots():
    quote = "Guests have no personal area."
    peer = "Guests require an invitation."
    case = await atomic_case([quote, quote, peer])
    payload = context(case)
    task = payload["generation_tasks"][0]
    atoms = [
        dict(
            task_id=task["task_id"],
            text=span["quote"],
            kind="fact",
            support_refs=[span["support_ref"]],
        )
        for row in payload["evidence_view"]["facts"]
        for span in row["source_span_candidates"]
    ]
    claims, _, _ = parse_atomic_generation(response(payload, atoms), payload, case[4], case[5])
    assert [claim.text for claim in claims] == [peer]


@pytest.mark.asyncio
async def test_domain_outcome_task_targets_the_requested_domain_not_assignment_premise():
    question = (
        "Example Product：同事只被授予 example.com 的 Cache Domain Purge 角色，"
        "没有任何其他角色。他能因此清除同一账户里 other.example 的边缘缓存吗？"
    )
    permission = "The Cache Domain Purge role permits purging the cache for example.com."
    case = await atomic_case([permission], question=question)
    payload = context(case)
    task = next(t for t in payload["generation_tasks"] if t["focus"] == "purge_cache")
    span = payload["evidence_view"]["facts"][0]["source_span_candidates"][0]
    atom = dict(
        task_id=task["task_id"], text=permission, kind="fact", support_refs=[span["support_ref"]]
    )
    claims, _, plans = parse_atomic_generation(response(payload, [atom]), payload, case[4], case[5])
    assert claims == []
    assert task.get("resource") == "other.example"
    assert "example.com" not in task["question_quote"]
    assert task.get("hypothesis_quotes")
    assert all(row["state"] != "generated" for row in plans[0]["task_results"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question,quote",
    [
        (
            "Example Product: Do guest users have private vaults?",
            "Guest users have no private vaults.",
        ),
        (
            "Example Product: Must users authenticate before accessing vaults?",
            "Users must authenticate before accessing vaults.",
        ),
    ],
)
async def test_unquantified_people_and_vaults_preserve_the_actual_request(
    monkeypatch, question, quote
):
    case = await atomic_case([quote], question=question)
    result, seen = await execute(case, monkeypatch)
    assert len(result["claims"]) == len(result["reviews"]) == 1
    assert all("request_property" not in t for t in seen[GENERATION_NAME][0]["generation_tasks"])
    assert all(
        t["question_quote"] in question for t in seen[GENERATION_NAME][0]["generation_tasks"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "quote",
    [
        "If voting is enabled, then",
        "Because observers are not a membership type, then",
    ],
)
async def test_dangling_consequence_cannot_be_dispatched_or_published(monkeypatch, quote):
    case = await atomic_case([quote], question="Example Product: Can observers vote on cards?")
    result, seen = await execute(case, monkeypatch)
    assert not result["claims"] and not result["reviews"]
    assert GENERATION_NAME not in seen
    assert context(case)["generation_support_gaps"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "quote,question",
    [
        ("Guests need an invitation", "Example Product: Do guests need an invitation?"),
        ("Observers vote on cards", "Example Product: Can observers vote on cards?"),
    ],
)
async def test_complete_unpunctuated_need_and_vote_reach_real_generation(
    monkeypatch, quote, question
):
    case = await atomic_case([quote], question=question)
    result, seen = await execute(case, monkeypatch)
    assert len(seen.get(GENERATION_NAME, [])) == 1
    assert len(result["claims"]) == len(result["reviews"]) == 1
    assert result["claims"][0].source_span_bindings[0].quote == quote


@pytest.mark.asyncio
async def test_one_object_quantity_does_not_turn_the_actor_into_a_people_limit(monkeypatch):
    question = "Example Product: Can users access 3 vaults?"
    case = await atomic_case(["Users may access up to three vaults."], question=question)
    result, seen = await execute(case, monkeypatch)
    tasks = seen[GENERATION_NAME][0]["generation_tasks"]
    assert all("request_property" not in task for task in tasks)
    assert any(task["question_quote"] == question for task in tasks)
    assert len(result["claims"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "quote",
    [
        "When voting is enabled observers may vote on cards",
        "If voting is enabled observers may vote on cards",
        "Unless voting is disabled observers may vote on cards",
    ],
)
async def test_complete_unpunctuated_condition_does_not_require_a_comma(monkeypatch, quote):
    case = await atomic_case([quote], question="Example Product: Can observers vote on cards?")
    result, seen = await execute(case, monkeypatch)
    assert len(seen.get(GENERATION_NAME, [])) == 1
    assert len(result["claims"]) == len(result["reviews"]) == 1
    assert result["claims"][0].source_span_bindings[0].quote == quote
