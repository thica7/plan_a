"""Task identities constrain both generation and independent review."""

import json

import pytest


def protocol():
    from packages.agents.writer import task_protocol

    return task_protocol


def test_obligation_focus_cannot_replace_an_ordinary_scoped_permission_request():
    question = dict(question_id="q", question="仅有域名 A 的清缓存角色，能清除 B 的缓存吗？")
    with pytest.raises(ValueError):
        protocol().parse_tasks(
            json.dumps(
                dict(
                    tasks=[
                        dict(
                            question_id="q",
                            question_quote="能清除 B 的缓存吗？",
                            focus="permission_not_obligation",
                        )
                    ]
                )
            ),
            [question],
            "scope",
        )


def test_action_task_rejects_a_compound_sibling_before_expensive_review():
    task = dict(focus="download")
    assert protocol().task_atom_reasons(task, "Observer 可以下载附件并导出看板。")
    assert not protocol().task_atom_reasons(task, "Observer 可以下载附件。")
    assert protocol().task_atom_reasons(task, "Observer 可以导出看板。")
    assert not protocol().task_atom_reasons(task, "只有编辑并投票之后才能下载附件。")
    assert not protocol().task_atom_reasons(
        task, "Observers can download attachments after voting."
    )


def test_server_task_ids_are_stable_and_bind_question_quote_and_scope():
    questions = [dict(question_id="q", question="能下载附件并导出看板吗？")]
    raw = json.dumps(
        {
            "tasks": [
                dict(question_id="q", question_quote="下载附件", focus="download"),
                dict(question_id="q", question_quote="导出看板", focus="export"),
            ]
        }
    )
    tasks = protocol().parse_tasks(raw, questions, "Acme/feature")
    assert tasks == protocol().parse_tasks(raw, questions, "Acme/feature")
    assert len({t["task_id"] for t in tasks}) == 2
    assert (
        tasks[0]["task_id"] != protocol().parse_tasks(raw, questions, "Other/feature")[0]["task_id"]
    )


@pytest.mark.parametrize(
    "row",
    [
        dict(question_id="foreign", question_quote="下载", focus="download"),
        dict(question_id="q", question_quote="管理员可下载", focus="download"),
        dict(question_id="q", question_quote="下载", focus="download", answer="yes"),
    ],
)
def test_planner_cannot_add_foreign_questions_or_fact_fields(row):
    with pytest.raises(ValueError):
        protocol().parse_tasks(
            json.dumps({"tasks": [row]}),
            [dict(question_id="q", question="能下载吗？")],
            "Acme/feature",
        )


def test_overflow_remains_explicit_and_each_question_gets_a_turn():
    questions = [dict(question_id=str(i), question=f"能下载文件{i}吗？") for i in range(14)]
    tasks = protocol().parse_tasks(
        json.dumps(
            {
                "tasks": [
                    dict(
                        question_id=q["question_id"], question_quote=q["question"], focus="download"
                    )
                    for q in questions
                ]
            }
        ),
        questions,
        "scope",
    )
    assert len(tasks) == 14
    assert sum(t["state"] == "deferred" for t in tasks) == 2


def test_one_malformed_or_duplicate_result_does_not_discard_another_task():
    tasks = [dict(task_id="a"), dict(task_id="b")]
    good = dict(
        task_id="b",
        status="generated",
        atom=dict(text="可导出。", kind="fact", support_refs=["s1"]),
    )
    bad = dict(task_id="a", status="generated", atom=[good["atom"], good["atom"]])
    parsed = protocol().parse_results(json.dumps({"results": [bad, good]}), tasks)
    assert parsed["a"]["state"] == "rejected"
    assert parsed["b"]["state"] == "generated"
    parsed = protocol().parse_results(json.dumps({"results": [good, good]}), tasks)
    assert parsed["b"]["state"] == "rejected"
    assert parsed["a"]["state"] == "deferred"


@pytest.mark.parametrize("quote", ["能在看板 A、B 投票吗？", "看板 A、B 投票"])
def test_named_resources_split_only_the_requested_action(quote):
    question = dict(
        question_id="q", question="看板A关闭投票，B启用。能在看板 A、B 投票吗？是否必须投票？"
    )
    tasks = protocol().parse_tasks(
        json.dumps(
            {
                "tasks": [
                    dict(question_id="q", question_quote=quote, focus="vote"),
                    dict(
                        question_id="q",
                        question_quote="是否必须投票？",
                        focus="permission_not_obligation",
                    ),
                ]
            }
        ),
        [question],
        "scope",
    )
    assert [(t["focus"], t.get("resource")) for t in tasks] == [
        ("rule_vote", None),
        ("vote", "A"),
        ("vote", "B"),
        ("permission_not_obligation", None),
    ]


def test_task_windows_reserve_each_predicate_and_keep_four_complete_originals():
    from types import SimpleNamespace

    from test_literal_non_operation import fact

    from packages.agents.writer.task_execution import task_context

    quotes = [
        "Permissions are set individually, never automatically at Workspace level.",
        "A permission change does not automatically change another board.",
        "Members can export boards.",
        "Export requires signing in to the account.",
    ]
    facts = [fact(quote=quote).model_copy(update={"id": str(i)}) for i, quote in enumerate(quotes)]
    view = SimpleNamespace(facts=facts, competitor=facts[0].competitor, dimension="feature")
    questions = [dict(question_id="q", question="权限层级能否统一自动设置；能否导出？")]
    tasks = [
        dict(
            task_id="a",
            question_id="q",
            question_quote="权限层级能否统一自动设置",
            focus="source_rule",
        ),
        dict(task_id="b", question_id="q", question_quote="能否导出？", focus="export"),
    ]
    service = SimpleNamespace(_question_packet_prompt=lambda *args: [])
    packed = task_context(
        service,
        None,
        dict(segment_competitor=view.competitor, dimension="feature"),
        view,
        {f.id for f in facts},
        questions,
        [],
        tasks,
        SimpleNamespace(max_bytes=14000),
    )
    assert {row["id"] for row in packed["evidence_view"]["facts"]} == {"0", "1", "2", "3"}
    assert "2" in [row["id"] for row in packed["evidence_view"]["facts"][:2]]
    assert packed["questions"] == questions


def test_task_bill_window_reserves_the_cpu_row_from_full_question_scope():
    from types import SimpleNamespace

    from test_answer_publication_recovery import QUESTION, table_case

    from packages.agents.writer.task_execution import task_context
    from packages.research.evidence.snapshot_models import canonical_json

    _, snapshot = table_case()
    original = snapshot.facts[0].model_copy(update={"dimension": "feature"})
    noise = []
    for index in range(5):
        text = f"Compute Paid Standard 本月动态请求准确美元账单 {index}"
        noise.append(
            original.model_copy(
                update={
                    "id": str(index),
                    "quote": text,
                    "value_json": canonical_json([text]),
                    "qualifiers_json": canonical_json({}),
                }
            )
        )
    view = SimpleNamespace(
        facts=[*noise, original], competitor="Example Product", dimension="feature"
    )
    question = dict(question_id="q", question=QUESTION)
    task = dict(task_id="task", question_id="q", question_quote="账单", focus="billing_inputs")
    context = task_context(
        SimpleNamespace(_question_packet_prompt=lambda *args: []),
        None,
        dict(segment_competitor=view.competitor, dimension="feature"),
        view,
        {f.id for f in view.facts},
        [question],
        [],
        [task],
        SimpleNamespace(max_bytes=14000),
    )
    rows = context["evidence_view"]["facts"]
    assert rows[0]["id"] == original.id
    assert rows[0]["source_span_candidates"][0]["quote"] == original.quote.strip()
    assert all(len(row["source_span_candidates"]) <= 2 for row in rows)


def test_task_batch_keeps_its_whole_original_question_but_omits_unrelated_questions():
    from types import SimpleNamespace

    from test_literal_non_operation import fact

    from packages.agents.writer.task_execution import task_context

    original = fact(quote="Members can export boards after signing in.")
    questions = [
        dict(question_id="active", question="假设已经登录账号，成员可以导出看板吗？"),
        dict(question_id="other", question="另一个产品的完整账单是多少？"),
    ]
    task = dict(
        task_id="t", question_id="active", question_quote="可以导出看板吗？", focus="export"
    )
    view = SimpleNamespace(facts=[original], competitor=original.competitor, dimension="feature")
    service = SimpleNamespace(_question_packet_prompt=lambda *args: [dict(questions=questions)])
    packed = task_context(
        service,
        None,
        dict(segment_competitor=view.competitor, dimension="feature"),
        view,
        {original.id},
        questions,
        [],
        [task],
        SimpleNamespace(max_bytes=14000),
    )
    assert packed["questions"] == questions[:1]
    assert packed["question_evidence_packets"][0]["questions"] == questions[:1]


def test_each_resource_action_keeps_its_own_source_rule_identity():
    question = dict(question_id="q", question="能从看板 A、B 下载附件并导出看板吗？")
    tasks = protocol().parse_tasks(
        json.dumps(
            dict(
                tasks=[
                    dict(question_id="q", question_quote=question["question"], focus=action)
                    for action in ("download", "export")
                ]
            )
        ),
        [question],
        "scope",
    )
    assert [t["focus"] for t in tasks] == [
        "rule_download",
        "download",
        "download",
        "rule_export",
        "export",
        "export",
    ]
    assert len({t["task_id"] for t in tasks}) == 6


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failed_task", [False, "generation", "decision", "review", "duplicate_decision", "incomplete"]
)
async def test_real_writer_uses_task_ids_then_one_independent_final_review(
    monkeypatch, failed_task
):
    import time
    from datetime import UTC, datetime

    from claim_review_fixture import expand_prompt_payload, supported_review
    from pydantic import HttpUrl, TypeAdapter
    from test_question_retrieval import research_case
    from test_writer_question_delivery import service_for

    from packages.research.evidence.snapshot import seal_snapshot
    from packages.schema.models import DecisionBrief

    question = "Example Product：访客能访问两个容器，或者拥有私人区域吗？"
    texts = ["访客只能访问一个容器。", "访客没有私人区域。"]
    detail, _ = research_case(["".join(texts)], question=question)
    detail.created_at = detail.updated_at = datetime.now(UTC)
    detail.plan.competitors, detail.plan.dimensions = ["Example Product"], ["feature"]
    detail.plan.decision_brief = DecisionBrief(decision_question=question)
    for source in detail.raw_sources:
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
    seal_snapshot(detail, phase="analysis", canonical_documents={})
    service, record = service_for(detail, task_execution=True)
    calls = []

    async def model(record, **kwargs):
        name = kwargs["name"]
        calls.append(name)
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        if name == "dimension_task_plan":
            qid = payload["questions"][0]["question_id"]
            return json.dumps(
                dict(
                    tasks=[
                        dict(question_id=qid, question_quote=part, focus="source_rule")
                        for part in ["访客能访问两个容器", "拥有私人区域吗？"]
                    ]
                )
            )
        if name == "dimension_task_support_selection":
            ref = payload["evidence_view"]["facts"][0]["source_span_candidates"][0]["support_ref"]
            return json.dumps(dict(selections=[dict(task_id=t["task_id"], status="selected",
                binding_kind="span", support_refs=[ref]) for t in payload["tasks"]]))
        if name == "dimension_task_generation":
            assert payload["questions"][0]["question"] == question
            if payload.get("task_repair"):
                return json.dumps(
                    dict(
                        results=[
                            dict(task_id=t["task_id"], status="insufficient_evidence", atom=None)
                            for t in payload["tasks"]
                        ]
                    )
                )
            rows = payload["evidence_view"]["facts"]
            results = []
            for index, task in enumerate(payload["tasks"]):
                row = rows[0]
                results.append(
                    dict(
                        task_id=task["task_id"],
                        status="generated",
                        atom=dict(
                            text=texts[index],
                            kind="fact",
                            support_refs=[row["source_span_candidates"][0]["support_ref"]],
                        ),
                    )
                )
            if failed_task == "generation":
                results[1]["atom"] = [results[1]["atom"]]
            return json.dumps(dict(results=results))
        if name == "dimension_task_review":
            reviews = [supported_review(c) for c in payload["claims"]]
            decisions = [
                dict(task_id=a["task_id"], claim_id=a["claim_id"], task_fulfilled=True)
                for a in payload["task_assignments"]
            ]
            if failed_task == "decision":
                decisions[1]["task_id"] = []
            elif failed_task == "review":
                reviews[1] = {"claim_id": reviews[1]["claim_id"], "verdict": "invalid"}
            elif failed_task == "duplicate_decision":
                decisions.append(dict(decisions[1], task_fulfilled="invalid"))
            elif failed_task == "incomplete":
                decisions[1]["task_fulfilled"] = False
            return json.dumps(dict(reviews=reviews, decisions=decisions))
        assert name == "dimension_answer_review"
        assert all("source_span_bindings" not in c for c in payload["claims"])
        assert all(p["quote"] == "".join(texts) for p in payload["published_supports"])
        # An unavailable final semantic review must not turn supported tasks into
        # an automatically answered original question.
        return None

    async def traced_model(record, **kwargs):
        response = await model(record, **kwargs)
        service._append_trace_span(service._evidence_live_record(record), kind="llm",
            agent=kwargs["agent"], subagent=kwargs["subagent"], name=kwargs["name"], status="ok",
            started=time.perf_counter(), input_text=kwargs["system"] + "\n\n" + kwargs["user"],
            output_text=response or "", metadata={"llm_transport_attempts": 1})
        return response

    monkeypatch.setattr(service, "_trace_llm_text", traced_model)
    await service._real_writer_step(record)
    audit = detail.report_dimension_audits[0]
    assert sum(a.status == "supported" for a in audit.claims) == (
        1 if failed_task and failed_task != "incomplete" else 2
    ), [s.full_output for s in detail.trace_spans if s.name == "question_task_delivery"]
    assert calls == [
        "dimension_task_plan",
        "dimension_task_support_selection",
        "dimension_task_generation",
        "dimension_task_review",
        *(["dimension_task_support_selection", "dimension_task_generation"] if failed_task else []),
        "dimension_answer_review",
    ]
    assert audit.answer_coverage[0].status == "unverified"
    receipt = next(s for s in detail.trace_spans if s.name == "question_task_delivery")
    tasks = json.loads(receipt.full_output)["tasks"]
    assert [t["state"] for t in tasks] == [
        "supported",
        "partial"
        if failed_task == "incomplete"
        else "insufficient_evidence"
        if failed_task
        else "supported",
    ]
    assert all(t["task_id"].startswith("task-") for t in tasks)


@pytest.mark.parametrize(
    "text",
    [
        "Observers can download attachments when they have edited and voted.",
        "在编辑并投票后，Observer 可以下载附件。",
        "Observer 可以下载附件，前提是先编辑并投票。",
        "Observers can download attachments provided they have edited and voted.",
        "Only after editing and voting can observers download attachments.",
        "下载附件需要先编辑并投票。",
        "编辑并投票后，Observer 可以下载附件。",
        "Observer 可以在编辑并投票后下载附件。",
        "Observers who edited and voted can download attachments.",
    ],
)
def test_task_scope_checker_defers_conditional_actions_to_full_semantic_audit(text):
    assert not protocol().task_atom_reasons(dict(focus="download"), text)


@pytest.mark.parametrize(
    "focus,text",
    [
        ("download", "Observer 可以下载共享文件夹中的附件。"),
        ("export", "用户可以导出共享看板。"),
        ("download", "用户可以下载可编辑文件。"),
    ],
)
def test_task_scope_guard_does_not_promote_object_adjectives_to_actions(focus, text):
    assert not protocol().task_atom_reasons(dict(focus=focus), text)


@pytest.mark.parametrize(
    "text",
    [
        "用户可以下载附件和投票记录。",
        "用户可以下载附件和导出日志。",
        "Observers can download attachments and voting records.",
        "Observers can download a file and an export log.",
    ],
)
def test_task_scope_guard_defers_coordinated_objects_to_semantic_review(text):
    assert not protocol().task_atom_reasons(dict(focus="download"), text)


def test_final_answer_full_envelope_fits_its_protected_budget():
    from packages.agents.writer.task_execution import TASK_ANSWER_SYSTEM
    from packages.i18n.language import language_instruction

    assert (
        len((TASK_ANSWER_SYSTEM + language_instruction("zh-CN")).encode()) + 14000 + 1600 + 256 + 8
        <= 20000
    )


@pytest.mark.parametrize(
    "task,wrong,right",
    [
        ({"focus": "rule_vote"}, "inference", "fact"),
        ({"focus": "vote", "resource": "A"}, "fact", "inference"),
    ],
)
def test_resource_scenarios_cannot_be_facts_and_product_rules_cannot_borrow_scenarios(
    task, wrong, right
):
    text = "Observers can vote when voting is enabled."
    assert protocol().task_atom_reasons(task, text, kind=wrong)
    assert not protocol().task_atom_reasons(task, text, kind=right)
