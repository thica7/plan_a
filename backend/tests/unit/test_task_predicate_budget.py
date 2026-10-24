"""Task targets stay narrower than their complete source supports."""

import json
from types import SimpleNamespace

import pytest

from packages.agents.writer.task_protocol import task_atom_reasons


@pytest.mark.parametrize(
    "question_quote,text",
    [
        ("访客有自己的私人保险库吗？", "访客没有自己的私人保险库，且只能访问一个共享保险库。"),
        (
            "能同时加入两个共享保险库吗？",
            "Guests have no personal area and can access only one shared vault.",
        ),
        (
            "3 个人使用 3 个 collections 能满足吗？",
            "免费组织可与另外一名用户共享数据，为两位用户提供全部核心功能，"
            "并支持最多两个 collections。",
        ),
        (
            "最多支持多少 collections？",
            "免费组织可与另外一名用户共享数据，并支持最多两个 collections。",
        ),
        (
            "How many collections does the free organization support?",
            "Free organizations can share data with one other user "
            "and support up to two collections.",
        ),
        (
            "免费组织提供哪些核心功能？",
            "免费组织可与另外一名用户共享数据，并为两位用户提供全部核心功能。",
        ),
        (
            "Which core features does the free organization provide?",
            "Free organizations can share data with one other user and provide all core features.",
        ),
        (
            "本月账单准确是多少？",
            "每月包含 3000 万 CPU 毫秒，超额每百万 CPU 毫秒 $0.02；每次调用最多 5 分钟 CPU 时间。",
        ),
        (
            "What is the monthly bill?",
            "CPU usage costs $0.02 per million CPU milliseconds; "
            "each invocation has a 5 minute CPU limit.",
        ),
        (
            "能否在 Workspace 层级统一设置角色？",
            "无法在 Workspace 层级统一设置该角色；每位成员需按成员、按看板单独设置。",
        ),
    ],
)
def test_complete_support_does_not_license_sibling_property_assertions(question_quote, text):
    assert task_atom_reasons(dict(focus="source_rule", question_quote=question_quote), text) == (
        "task_contains_sibling_predicate",
    )


@pytest.mark.parametrize(
    "text",
    [
        "访客在邀请被接受并由管理员确认后，只能访问一个共享保险库。",
        "Guests can access only one shared vault after accepting an invitation "
        "and administrator confirmation.",
        "免费组织最多支持两个 collections，"
        "因此题设 3 个人使用 3 个 collections 的整体请求不能满足。",
        "每月包含 3000 万 CPU 毫秒，超额按每百万 CPU 毫秒 $0.02 计费。",
        "只有管理员和所有者在验证并登录后才能更改权限。",
        "在付费 Workspace 中，管理员只能逐人逐板设置访客角色。",
        "无法在 Workspace 层级统一设置该角色，除非管理员逐人逐板确认权限。",
        "免费组织最多支持两个 collections，"
        "因此题设我与另外一名用户使用三个 collections 的请求不能满足。",
        "The free plan supports at most two collections, so the requested "
        "three collections with one other user cannot be accommodated.",
        "题设我与另外一名用户使用三个 collections，免费组织最多支持两个 collections，"
        "因此该请求不能满足。",
        "For the requested three collections with one other user, "
        "the free plan's limit of at most two collections cannot satisfy that request.",
        "免费组织最多支持两个 collections，前提是可与另外一名用户共享数据。",
        "若免费组织可与另外一名用户共享数据，则最多支持两个 collections。",
        "Free organizations support up to two collections provided "
        "they can share data with one other user.",
        "If free organizations can share data with one other user, "
        "they support up to two collections.",
        "免费组织提供全部核心功能，前提是可与另外一名用户共享数据。",
        "若免费组织可与另外一名用户共享数据，则提供全部核心功能。",
        "Free organizations provide all core features provided "
        "they can share data with one other user.",
        "If free organizations can share data with one other user, they provide all core features.",
    ],
)
def test_one_predicate_keeps_all_conditions_and_can_deny_a_conjunctive_request(text):
    assert not task_atom_reasons(dict(focus="source_rule"), text, kind="inference")


@pytest.mark.parametrize(
    "text",
    [
        "免费组织最多支持两名用户，并且最多支持两个 collections。",
        "The free plan supports at most two users and up to two collections.",
    ],
)
def test_two_explicit_product_limits_remain_sibling_predicates(text):
    assert task_atom_reasons(dict(focus="source_rule"), text) == (
        "task_contains_sibling_predicate",
    )


def selection_case():
    from test_literal_non_operation import fact

    from packages.agents.writer.task_execution import task_context

    originals = [
        fact(quote="Only admins can manage document permissions after verification and sign-in."),
        fact(quote="Guests have no personal area.").model_copy(update={"id": "unselected"}),
    ]
    questions = [dict(question_id="q", question="已完成验证并登录，谁能更改权限？")]
    tasks = [
        dict(task_id="t", question_id="q", question_quote="谁能更改权限？", focus="source_rule")
    ]
    payload = task_context(
        SimpleNamespace(_question_packet_prompt=lambda *args: []),
        None,
        dict(segment_competitor=originals[0].competitor, dimension="feature"),
        SimpleNamespace(facts=originals, competitor=originals[0].competitor, dimension="feature"),
        {f.id for f in originals},
        questions,
        [],
        tasks,
        SimpleNamespace(max_bytes=14000),
    )
    return payload, originals


def test_selection_uses_verified_complete_choices_without_canonical_metadata_duplicates():
    from packages.agents.writer import task_support_selection
    from packages.agents.writer.dimension_writer import compact_prompt_json
    from packages.agents.writer.readable_support import dispatched_support_choices

    payload, originals = selection_case()
    choices = dispatched_support_choices(payload, originals, {f.id for f in originals})
    compact = task_support_selection.support_selection_context(payload, choices)
    assert compact["questions"] == payload["questions"]
    assert compact["tasks"] == payload["tasks"]
    assert "question_evidence_packets" not in compact
    assert "task_predicates" not in compact
    assert all(
        "value" not in row and "qualifiers" not in row for row in compact["evidence_view"]["facts"]
    )
    operations = [
        o
        for row in compact["evidence_view"]["facts"]
        for o in row.get("operation_observations", [])
    ]
    expected = [
        c["operation_binding"] for c in choices.values() if c["binding_kind"] == "operation"
    ]
    assert operations == expected
    assert len(compact_prompt_json(compact).encode()) < len(compact_prompt_json(payload).encode())
    # Tampered aliases never enter the model's choices.
    allowed = {ref: choice for ref, choice in choices.items() if choice["binding_kind"] == "span"}
    restricted = task_support_selection.support_selection_context(payload, allowed)
    assert not any(
        row.get("operation_observations") for row in restricted["evidence_view"]["facts"]
    )


def test_generation_keeps_selected_canonical_rows_and_rebuilds_packets_without_renumbering_refs():
    from packages.agents.writer.readable_support import dispatched_support_choices
    from packages.agents.writer.task_support_selection import selected_generation_context

    payload, originals = selection_case()
    choices = dispatched_support_choices(payload, originals, {f.id for f in originals})
    ref = next(ref for ref, choice in choices.items() if choice["binding_kind"] == "operation")
    calls = []

    def packets(rows):
        calls.append(rows)
        return [dict(questions=payload["questions"], actual_ids=[row["id"] for row in rows])]

    result = selected_generation_context(
        payload,
        {"t": dict(state="selected", binding_kind="operation", support_refs=[ref])},
        choices,
        packet_builder=packets,
    )
    expected = [
        row for row in payload["evidence_view"]["facts"] if row.get("operation_support_refs")
    ]
    assert calls == [expected]
    assert result["evidence_view"]["facts"] == expected
    assert result["question_evidence_packets"][0]["actual_ids"] == [row["id"] for row in expected]
    assert result["task_support_selections"][0]["support_refs"] == [ref]


def test_new_scope_rule_is_explicit_and_leaves_old_task_reconstruction_unchanged():
    from packages.agents.writer import task_protocol

    question = (
        "同事只被授予 alpha.example 的 Domain Purge 角色，没有任何其他角色。"
        "他能清除同一账户里 beta.example 的缓存吗？"
    )
    questions = [dict(question_id="q", question=question)]
    plan = dict(
        tasks=[
            dict(
                question_id="q",
                question_quote="他能清除同一账户里 beta.example 的缓存吗？",
                focus="purge_cache",
            )
        ]
    )
    old = task_protocol.parse_tasks(json.dumps(plan), questions, "Example/feature")
    new = task_protocol.with_scope_rule_tasks(old, questions, "Example/feature")
    assert old[0] in new
    rules = [t for t in new if t["focus"] == "source_rule"]
    assert len(rules) == 1 and rules[0]["question_quote"] in question
    for rows, expected in (
        (plan["tasks"], old),
        ([{k: t[k] for k in ("question_id", "question_quote", "focus")} for t in new], new),
    ):
        assert (
            task_protocol.parse_tasks(json.dumps(dict(tasks=rows)), questions, "Example/feature")
            == expected
        )


def test_scope_dependency_outranks_unrelated_billing_for_scope_rule():
    from packages.agents.writer.question_allocation import task_support_score

    task = dict(focus="source_rule", request="只被授予 alpha.example 的 Domain Purge 角色")
    question = task["request"] + "，能清除同一账户里 beta.example 的缓存吗？"
    scope = (
        "Roles can only ever be assigned to their given scope "
        "and multiple roles can be assigned to a given policy."
    )
    billing = "Paid accounts include CPU milliseconds."
    assert task_support_score(task, scope, question, "Example") >= 20
    assert task_support_score(task, scope, question, "Example") > task_support_score(
        task, billing, question, "Example"
    )


def test_single_domain_assignment_does_not_add_a_cross_resource_scope_task():
    from packages.agents.writer.task_protocol import parse_tasks, with_scope_rule_tasks

    question = "同事只被授予 alpha.example 的 Domain Purge 角色。他能清除 alpha.example 的缓存吗？"
    questions = [dict(question_id="q", question=question)]
    plan = dict(
        tasks=[
            dict(
                question_id="q",
                question_quote="他能清除 alpha.example 的缓存吗？",
                focus="purge_cache",
            )
        ]
    )
    old = parse_tasks(json.dumps(plan), questions, "Example/feature")
    assert with_scope_rule_tasks(old, questions, "Example/feature") == old


@pytest.mark.parametrize("add_scope", [False, True])
def test_scope_supplement_preserves_unplanned_and_capacity_deferred_tasks(add_scope):
    from packages.agents.writer.task_protocol import (
        fallback_tasks,
        parse_tasks,
        with_scope_rule_tasks,
    )

    questions = [dict(question_id="unplanned", question="请解释未说明的新条件？")]
    questions.extend(dict(question_id=f"q{i}", question=f"能下载文件{i}吗？") for i in range(13))
    if add_scope:
        questions.append(
            dict(
                question_id="scope",
                question=(
                    "同事只被授予 alpha.example 的 Domain Purge 角色。"
                    "他能清除 beta.example 的缓存吗？"
                ),
            )
        )
    rows = [
        {"question_id": q["question_id"], "question_quote": q["question"], "focus": "download"}
        for q in questions
        if q["question_id"].startswith("q")
    ]
    if add_scope:
        rows.append(
            dict(
                question_id="scope",
                question_quote="他能清除 beta.example 的缓存吗？",
                focus="purge_cache",
            )
        )
    before = parse_tasks(json.dumps(dict(tasks=rows)), questions, "Example/feature")
    assert before[0]["reason"] == "request_not_planned"
    after = with_scope_rule_tasks(before, questions, "Example/feature")
    original_ids = {task["task_id"] for task in before}
    assert {task["task_id"]: task for task in before} == {
        task["task_id"]: task for task in after if task["task_id"] in original_ids
    }
    assert sum(task["state"] == "planned" for task in after) == 12
    assert all(
        task["state"] == "deferred" and task["reason"] == "task_capacity_exceeded"
        for task in after
        if task["task_id"] not in original_ids
    )
    # Server-discovered tasks may exceed the model's 48-row plan envelope.
    expanded = fallback_tasks(
        [dict(question_id="q", question="".join(f"能下载文件{i}吗？" for i in range(49)))],
        "Example/feature",
    )
    assert len(expanded) == 49
    assert (
        with_scope_rule_tasks(
            expanded,
            [dict(question_id="q", question="".join(f"能下载文件{i}吗？" for i in range(49)))],
            "Example/feature",
        )
        == expanded
    )


@pytest.mark.parametrize("add_scope", [False, True])
def test_scope_supplement_accepts_server_expansion_beyond_model_row_limit(add_scope):
    from packages.agents.writer.task_protocol import fallback_tasks, with_scope_rule_tasks

    questions = [dict(question_id="q", question="".join(f"能下载文件{i}吗？" for i in range(49)))]
    if add_scope:
        questions.append(
            dict(
                question_id="scope",
                question=(
                    "同事只被授予 alpha.example 的 Domain Purge 角色。"
                    "他能清除 beta.example 的缓存吗？"
                ),
            )
        )
    before = fallback_tasks(questions, "Example/feature")
    assert len(before) > 48
    after = with_scope_rule_tasks(before, questions, "Example/feature")
    assert sum(task["state"] == "planned" for task in after) == 12
    assert all(task in after for task in before)
    assert after is before


@pytest.mark.parametrize("row_count", [47, 48])
def test_scope_supplement_stays_in_the_existing_qa_plan_replay_envelope(row_count):
    import copy
    import hashlib

    from test_task_delivery_replay import delivery_case

    from packages.agents.qa.question_context import _task_delivery_originals
    from packages.agents.writer.dimension_writer import compact_prompt_json
    from packages.agents.writer.task_protocol import parse_tasks, with_scope_rule_tasks
    from packages.orchestrator.question_packets import prompt_packets
    from packages.research.question_delivery import _expand_text_refs

    _, detail, snapshot, use, view, receipt = delivery_case()
    packet = copy.deepcopy(json.loads(detail.trace_spans[0].full_output)["packets"][0])
    qid = packet["questions"][0]["question_id"]
    downloads = [f"能下载文件{i}吗？" for i in range(row_count - 1)]
    scope = "同事只被授予 alpha.example 的 Domain Purge 角色。他能清除 beta.example 的缓存吗？"
    questions = [dict(question_id=qid, question="".join(downloads) + scope)]
    packet["questions"] = questions
    packet["retrieval"]["questions"] = packet["retrieval"]["questions"][:1]
    rows = [dict(question_id=qid, question_quote=quote, focus="download") for quote in downloads]
    rows.append(
        dict(
            question_id=qid, question_quote="他能清除 beta.example 的缓存吗？", focus="purge_cache"
        )
    )
    before = parse_tasks(json.dumps(dict(tasks=rows)), questions, "Example Product/feature")
    assert len(before) == row_count
    after = with_scope_rule_tasks(before, questions, "Example Product/feature")
    span = detail.trace_spans[1]
    payload = _expand_text_refs(json.loads(span.full_input.split("\nJSON:\n", 1)[1]))
    payload["questions"] = questions
    payload["tasks"] = [
        {k: v for k, v in task.items() if k not in {"state", "reason"}} for task in after[:3]
    ]
    payload["question_evidence_packets"] = prompt_packets(
        [packet], snapshot, payload["evidence_view"]["facts"]
    )
    span.full_input = "SYSTEM\nJSON:\n" + compact_prompt_json(payload)
    receipt.update(
        tasks=after,
        question_ids=[qid],
        dispatches=[
            dict(
                receipt["dispatches"][0],
                task_ids=[task["task_id"] for task in after[:3]],
                full_input_sha256=hashlib.sha256(span.full_input.encode()).hexdigest(),
            )
        ],
    )
    assert _task_delivery_originals(detail, snapshot, use, view, [packet], receipt)
    assert len(after) == 48
    assert all(task in after for task in before)
    if row_count == 48:
        assert after is before


def test_multiple_scope_supplements_share_the_remaining_plan_capacity():
    from packages.agents.writer.task_protocol import parse_tasks, with_scope_rule_tasks

    questions, rows = [], []
    for index, count in enumerate((23, 22)):
        qid = f"q{index}"
        downloads = [f"能下载文件{i}吗？" for i in range(count)]
        scope = "同事只被授予 alpha.example 的 Domain Purge 角色。他能清除 beta.example 的缓存吗？"
        questions.append(dict(question_id=qid, question="".join(downloads) + scope))
        rows.extend(
            dict(question_id=qid, question_quote=quote, focus="download") for quote in downloads
        )
        rows.append(
            dict(
                question_id=qid,
                question_quote="他能清除 beta.example 的缓存吗？",
                focus="purge_cache",
            )
        )
    before = parse_tasks(json.dumps(dict(tasks=rows)), questions, "Example/feature")
    assert len(before) == 47
    after = with_scope_rule_tasks(before, questions, "Example/feature")
    assert len(after) == 48
    assert all(task in after for task in before)


@pytest.mark.asyncio
async def test_scope_dependency_crosses_actual_selection_use_generation_and_qa_replay(monkeypatch):
    from datetime import UTC, datetime

    from claim_review_fixture import expand_prompt_payload, supported_review
    from pydantic import HttpUrl, TypeAdapter
    from test_question_retrieval import research_case
    from test_task_support_selection import append_response, selection_row
    from test_writer_question_delivery import service_for

    from packages.agents.qa.question_context import _question_replays
    from packages.agents.writer import question_retrieval
    from packages.research.evidence.snapshot import current_snapshot, seal_snapshot
    from packages.research.evidence.views import select_evidence_view
    from packages.schema.models import DecisionBrief

    question = (
        "Example Product：同事只被授予 alpha.example 的 Domain Purge 角色，没有其他角色。"
        "他能清除同一账户里 beta.example 的缓存吗？"
    )
    main = "Domain Purge grants permission to purge the edge cache for a specific domain."
    scope_rule = "Roles can only ever be assigned to their given scope."
    distractors = [
        f"Cache settings for Domain Purge roles in the same account {i}." for i in range(6)
    ]
    detail, _ = research_case([main, scope_rule, *distractors], question=question)
    fields = [s.metadata["normalized_fields"][0] for s in detail.raw_sources]
    detail.raw_sources = detail.raw_sources[:1]
    detail.raw_sources[0].metadata["normalized_fields"] = fields
    detail.created_at = detail.updated_at = datetime.now(UTC)
    detail.plan.competitors, detail.plan.dimensions = ["Example Product"], ["feature"]
    detail.plan.decision_brief = DecisionBrief(decision_question=question)
    for source in detail.raw_sources:
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
    snapshot = seal_snapshot(detail, phase="analysis", canonical_documents={})
    target = next(
        f.id for f in snapshot.facts if f.field == "evidence_terms" and f.quote == scope_rule
    )
    monkeypatch.setattr(question_retrieval, "get_local_provider_from_env", lambda *_: None)
    service, record = service_for(detail, task_execution=True)
    seen_generation = set()

    async def model(record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        name = kwargs["name"]
        if name == "dimension_task_plan":
            result = dict(
                tasks=[
                    dict(
                        question_id=payload["questions"][0]["question_id"],
                        question_quote="他能清除同一账户里 beta.example 的缓存吗？",
                        focus="purge_cache",
                    )
                ]
            )
        elif name == "dimension_task_support_selection":
            spans = [
                s
                for row in payload["evidence_view"]["facts"]
                for s in row.get("source_span_candidates", [])
            ]
            assert scope_rule in {s["quote"] for s in spans}
            result = dict(
                selections=[
                    selection_row(
                        t["task_id"],
                        [
                            next(
                                s["support_ref"]
                                for s in spans
                                if s["quote"]
                                == (scope_rule if t["focus"] == "source_rule" else main)
                            )
                        ],
                    )
                    for t in payload["tasks"]
                ]
            )
        elif name == "dimension_task_generation":
            seen_generation.update(row["id"] for row in payload["evidence_view"]["facts"])
            selections = {s["task_id"]: s for s in payload["task_support_selections"]}
            result = dict(
                results=[
                    dict(
                        task_id=t["task_id"],
                        status="generated",
                        atom=dict(
                            text=scope_rule
                            if t["focus"] == "source_rule"
                            else "仅获 alpha.example 角色的同事不能清除 beta.example 的缓存。",
                            kind="fact" if t["focus"] == "source_rule" else "inference",
                            support_refs=selections[t["task_id"]]["support_refs"],
                        ),
                    )
                    for t in payload["tasks"]
                ]
            )
        elif name == "dimension_task_review":
            result = dict(
                reviews=[supported_review(c) for c in payload["claims"]],
                decisions=[
                    dict(
                        task_id=a["task_id"],
                        claim_id=a["claim_id"],
                        task_fulfilled=True,
                        conclusion="no",
                        relation="direct",
                    )
                    for a in payload["task_assignments"]
                ],
            )
        else:
            assert name == "dimension_answer_review"
            return append_response(service, record, kwargs, None)
        return append_response(service, record, kwargs, json.dumps(result))

    monkeypatch.setattr(service, "_trace_llm_text", model)
    await service._real_writer_step(record)
    receipt = json.loads(
        next(s.full_output for s in detail.trace_spans if s.name == "question_task_delivery")
    )
    use = next(u for u in detail.evidence_consumptions if u.id == receipt["consumption_id"])
    assert target in use.requested_fact_ids and target in use.fact_ids
    assert target in seen_generation, (
        [(t["state"], t.get("reason")) for t in receipt["tasks"]],
        receipt["support_selections"],
    )
    selection = json.loads(
        next(s.full_output for s in detail.trace_spans if s.name == "question_evidence_selection")
    )
    assert target in selection["packets"][0]["retrieval"]["questions"][0]["core_fact_ids"]
    snapshot = current_snapshot(detail)
    view = select_evidence_view(
        snapshot,
        agent=use.agent,
        competitor=use.competitor,
        dimension=use.dimension,
        source_ids=use.requested_source_ids,
        fact_ids=use.requested_fact_ids,
        max_bytes=use.view_max_bytes or use.max_bytes,
    )
    assert target in _question_replays(service, detail, snapshot, use, view)[1]["sent_fact_ids"]


def test_generation_retains_complete_exception_partner_even_when_only_main_ref_selected():
    from packages.agents.writer.readable_support import dispatched_support_choices
    from packages.agents.writer.task_support_selection import selected_generation_context

    payload, originals = selection_case()
    rows = payload["evidence_view"]["facts"]
    payload["source_exception_bindings"] = [dict(fact_ids=[row["id"] for row in rows])]
    choices = dispatched_support_choices(payload, originals, {f.id for f in originals})
    ref = next(ref for ref, choice in choices.items() if choice["binding_kind"] == "operation")
    result = selected_generation_context(
        payload,
        {"t": dict(state="selected", binding_kind="operation", support_refs=[ref])},
        choices,
    )
    assert result["evidence_view"]["facts"] == rows
    assert result["source_exception_bindings"] == payload["source_exception_bindings"]


@pytest.mark.asyncio
async def test_compact_selector_enters_real_adapter_inside_original_final_delivery_floors():
    import httpx
    from test_task_delivery_budget import task_service

    from packages.agents.writer.dimension_writer import compact_prompt_json
    from packages.agents.writer.readable_support import dispatched_support_choices
    from packages.agents.writer.task_support_selection import (
        SELECT_SYSTEM,
        support_selection_context,
    )
    from packages.llm.errors import LLMExecutionLimitError

    payload, originals = selection_case()
    # Large canonical values are replay material, not another selectable quote.
    metadata = "canonical metadata " * 450
    for row in payload["evidence_view"]["facts"]:
        row["value"] = metadata
    originals = [fact.model_copy(update={"value_json": json.dumps(metadata)}) for fact in originals]
    choices = dispatched_support_choices(payload, originals, {f.id for f in originals})
    assert choices
    old_prompt = compact_prompt_json(payload)
    prompt = compact_prompt_json(support_selection_context(payload, choices))
    assert len(prompt.encode()) < len(old_prompt.encode())
    service, record = await task_service()
    budget = service._run_llm_budget(record)
    for phase in list(budget.delivery_reserves):
        if not phase.startswith(("answer:", "final_qa:")):
            budget.finish_delivery(phase)
    budget.tokens_used = 46055
    budget.delivery_reserves["final_qa:run"] = 11000
    requests = []

    async def post(url, body, headers):
        requests.append(body)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"selections":[]}'}}]}
        )

    service._llm._post_chat_completion = post
    # The full original selector is refused before transport at the observed
    # late-stage usage; the compact selector uses the same real admission path.
    with pytest.raises(LLMExecutionLimitError):
        await service._trace_llm_text(
            record,
            agent="writer",
            subagent="Example Suite/feature",
            name="dimension_task_support_selection",
            system=SELECT_SYSTEM,
            user="\nJSON:\n" + old_prompt,
            max_output_tokens=600,
            max_request_attempts=1,
        )
    assert not requests
    await service._trace_llm_text(
        record,
        agent="writer",
        subagent="Example Suite/feature",
        name="dimension_task_support_selection",
        system=SELECT_SYSTEM,
        user="\nJSON:\n" + prompt,
        max_output_tokens=600,
        max_request_attempts=1,
    )
    span = record.detail.trace_spans[-1]
    assert len(requests) == 1
    assert span.metadata["llm_transport_attempts"] == 1
    assert span.full_input == SELECT_SYSTEM + "\n\n\nJSON:\n" + prompt
    assert span.metadata["llm_reserved_input_tokens"] < 8000
    assert budget.protected_tokens("writer:Example Suite/feature") == 23000
    assert budget.max_tokens == 80000 and budget.max_calls == 24


@pytest.mark.asyncio
@pytest.mark.parametrize("improved", [False, True])
async def test_partial_repair_publishes_one_task_atom_and_preserves_its_successful_peer(
    monkeypatch, improved
):
    from claim_review_fixture import expand_prompt_payload, supported_review
    from test_task_support_selection import append_response, selection_row, writer_case

    service, record, parts, texts = writer_case()
    original_ids = {}

    async def model(record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        name = kwargs["name"]
        if name == "dimension_task_plan":
            result = dict(
                tasks=[
                    dict(
                        question_id=next(
                            q["question_id"] for q in payload["questions"] if part in q["question"]
                        ),
                        question_quote=part,
                        focus="source_rule",
                    )
                    for part in parts
                ]
            )
        elif name == "dimension_task_support_selection":
            spans = [
                s
                for row in payload["evidence_view"]["facts"]
                for s in row.get("source_span_candidates", [])
            ]
            result = dict(
                selections=[
                    selection_row(
                        t["task_id"],
                        [
                            next(
                                s["support_ref"]
                                for s in spans
                                if s["quote"] == texts[parts.index(t["question_quote"])]
                            )
                        ],
                    )
                    for t in payload["tasks"]
                ]
            )
        elif name == "dimension_task_generation":
            selections = {s["task_id"]: s for s in payload["task_support_selections"]}
            result = dict(
                results=[
                    dict(
                        task_id=t["task_id"],
                        status="generated",
                        atom=dict(
                            text=texts[parts.index(t["question_quote"])],
                            kind="fact",
                            support_refs=selections[t["task_id"]]["support_refs"],
                        ),
                    )
                    for t in payload["tasks"]
                ]
            )
        elif name == "dimension_task_review":
            decisions = []
            for assignment in payload["task_assignments"]:
                first = assignment["question_quote"] == parts[0]
                repairing = first and parts[0] in original_ids
                if not repairing:
                    original_ids[assignment["question_quote"]] = assignment["claim_id"]
                decisions.append(
                    dict(
                        task_id=assignment["task_id"],
                        claim_id=assignment["claim_id"],
                        task_fulfilled=not first or repairing and improved,
                        conclusion="no",
                        relation="direct",
                    )
                )
            result = dict(
                reviews=[supported_review(c) for c in payload["claims"]], decisions=decisions
            )
        else:
            assert name == "dimension_answer_review"
            return append_response(service, record, kwargs, None)
        return append_response(service, record, kwargs, json.dumps(result))

    monkeypatch.setattr(service, "_trace_llm_text", model)
    await service._real_writer_step(record)
    audit = record.detail.report_dimension_audits[0]
    supported = [a.claim for a in audit.claims if a.status == "supported"]
    assert len(supported) == 2, [
        s.full_output for s in record.detail.trace_spans if s.name == "question_task_delivery"
    ]
    assert len([c for c in supported if c.text == texts[0]]) == 1
    assert original_ids[parts[1]] in {c.id for c in supported}
    first = next(c for c in supported if c.text == texts[0])
    assert (first.id != original_ids[parts[0]]) is improved
    from packages.agents.qa.question_context import _question_replays
    from packages.research.evidence.snapshot import current_snapshot
    from packages.research.evidence.views import select_evidence_view

    receipt = json.loads(
        next(s.full_output for s in record.detail.trace_spans if s.name == "question_task_delivery")
    )
    use = next(u for u in record.detail.evidence_consumptions if u.id == receipt["consumption_id"])
    snapshot = current_snapshot(record.detail)
    view = select_evidence_view(
        snapshot,
        agent=use.agent,
        competitor=use.competitor,
        dimension=use.dimension,
        source_ids=use.requested_source_ids,
        fact_ids=use.requested_fact_ids,
        max_bytes=use.view_max_bytes or use.max_bytes,
    )
    replay = _question_replays(service, record.detail, snapshot, use, view)
    assert set(replay[1]["sent_fact_ids"]) == {
        fid for dispatch in receipt["dispatches"] for fid in dispatch["fact_ids"]
    }
    assert [len(d["fact_ids"]) for d in receipt["dispatches"]] == [2, 1]
