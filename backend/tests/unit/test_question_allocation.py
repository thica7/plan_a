"""Question-scoped task allocation is guidance, never product evidence."""

import importlib

import pytest


def api():
    return importlib.import_module("packages.agents.writer.question_allocation")


def test_download_and_export_have_separate_predicate_tasks():
    tasks = api().question_atom_tasks(
        [dict(question_id="q", question="他能下载附件并导出看板吗？")]
    )
    assert {task["focus"] for task in tasks} == {"download", "export"}
    assert all(task["question_id"] == "q" for task in tasks)


def test_each_explicit_named_resource_has_its_own_action_task():
    tasks = api().question_atom_tasks(
        [
            dict(
                question_id="q",
                question="看板 A 关闭投票，B 已启用。请分别判断：能在看板 A、B 投票吗？",
            )
        ]
    )
    assert {(task["focus"], task.get("resource")) for task in tasks} == {
        ("vote", "A"),
        ("vote", "B"),
    }


def test_resource_names_survive_a_split_that_omits_the_resource_noun():
    tasks = api().question_atom_tasks(
        [
            dict(
                question_id="q",
                question=("看板 A 未启用投票，B 已启用。请逐项判断：小林能在 A、B 投票吗？"),
            )
        ]
    )
    assert {(task["focus"], task.get("resource")) for task in tasks} == {
        ("vote", "A"),
        ("vote", "B"),
    }


def test_permission_context_survives_question_unit_split():
    tasks = api().question_atom_tasks(
        [
            dict(
                question_id="q",
                question=(
                    "B 允许投票，是否意味着他必须给每张卡片投票？"
                    "请将可以执行的操作、启用条件与是否存在强制义务分别说明。"
                ),
            )
        ]
    )
    assert tasks == [
        dict(
            question_id="q",
            focus="permission_not_obligation",
            request="是否意味着他必须给每张卡片投票？",
        )
    ]


def test_complete_scope_original_precedes_repeated_role_background():
    from types import SimpleNamespace

    from test_literal_non_operation import fact

    from packages.agents.writer.dimension_writer import compact_dimension_context

    background = fact(quote="Workspace administrators can invite workspace members.")
    scope = fact(
        quote="Each observer is set individually per member per board, not at Workspace level."
    )
    scope = scope.model_copy(update={"id": "scope-original"})
    view = SimpleNamespace(
        facts=[background, scope], competitor=scope.competitor, dimension="feature"
    )
    question = dict(
        question_id="q",
        question=(
            "Workspace 管理员把 A 成员改为 Observer。请逐项回答："
            "能否在 Workspace 层级统一设置 Observer；A 改权是否自动决定 B 的权限？"
        ),
    )
    packed, _ = compact_dimension_context(
        dict(segment_competitor=view.competitor, dimension="feature"),
        view,
        {background.id, scope.id},
        questions=[question],
    )
    assert packed["evidence_view"]["facts"][0]["id"] == scope.id


def test_repair_quota_is_reserved_across_questions_before_extra_actions():
    questions = [dict(question_id=str(index), question="能下载并导出吗？") for index in range(4)]
    tasks = api().question_atom_tasks(questions, max_atoms=4)
    assert len(tasks) == 4 and {task["question_id"] for task in tasks} == {"0", "1", "2", "3"}
    assert questions[0]["question"] == "能下载并导出吗？"


def test_permission_does_not_create_a_document_absence_task():
    tasks = api().question_atom_tasks(
        [dict(question_id="q", question="允许投票是否意味着必须给每张卡片投票？")]
    )
    assert len(tasks) == 1 and tasks[0]["focus"] == "permission_not_obligation"


def test_cpu_task_is_distinct_from_exact_bill_calculation():
    tasks = api().question_atom_tasks(
        [dict(question_id="q", question="Standard 用量模式有1500万请求，本月账单准确是多少美元？")]
    )
    assert [task["focus"] for task in tasks] == ["billing_inputs"]


def test_compact_repair_diagnostics_keep_rejected_text_and_failed_checks():
    target = dict(
        question_id="q",
        question="Can guests export?",
        missing_fields=[],
        coverage_failure="Missing export answer.",
        rejected_claims=[
            dict(
                claim_id="c",
                text="Guests can download and export.",
                rule_reasons=["claim_check_not_supported"],
                review_reason="A lengthy private review diagnostic. " * 90,
                failed_checks=["atomicity"],
            )
        ],
    )
    compact = api().compact_repair_targets([target])
    assert compact[0]["rejected_claims"][0]["text"] == target["rejected_claims"][0]["text"]
    assert compact[0]["rejected_claims"][0]["failed_checks"] == ["atomicity"]
    assert "review_reason" not in compact[0]["rejected_claims"][0]
    assert len(target["rejected_claims"][0]["review_reason"]) > 1000


@pytest.mark.parametrize(
    "text",
    [
        "所给页面未记载 Observer 必须投票。",
        "The documentation does not state that users must export.",
        "是否存在强制投票义务在所给页面中无依据。",
        "所给页面中不存在任何强制投票义务。",
        "The documentation contains no requirement to vote.",
    ],
)
def test_excerpt_silence_cannot_establish_whole_document_absence(text):
    assert api().document_absence_claim(text)


@pytest.mark.parametrize(
    "text",
    [
        "仅依据允许投票，不能推断每张卡片必须投票。",
        "Guests cannot edit a page.",
        "The source states that guests cannot export documents.",
        "导出的文档不包含评论。",
        "共享文档不包含私人笔记。",
        "The exported document does not include comments.",
    ],
)
def test_scoped_negative_or_non_entailment_is_not_document_absence(text):
    assert not api().document_absence_claim(text)


@pytest.mark.asyncio
async def test_complete_cpu_row_is_reserved_before_lexical_billing_background():
    from test_answer_publication_recovery import QUESTION, table_case
    from test_question_retrieval import replace_snapshot

    from packages.agents.writer.question_retrieval import retrieve_question_facts
    from packages.research.evidence.snapshot_models import canonical_json

    detail, snapshot = table_case()
    detail.topic = detail.plan.topic = QUESTION
    detail.plan.dimensions = ["feature"]
    original = snapshot.facts[0].model_copy(update={"dimension": "feature"})
    noise = []
    for index in range(10):
        text = f"Compute Paid Standard 用量模式本月1500万动态请求，准确美元账单须查看账户 {index}。"
        noise.append(
            original.model_copy(
                update={
                    "id": f"background-{index}",
                    "semantic_id": f"background-{index}",
                    "quote": text,
                    "value_json": canonical_json([text]),
                    "qualifiers_json": canonical_json({}),
                }
            )
        )
    snapshot = replace_snapshot(
        detail,
        snapshot,
        facts=(*noise, original),
        sources=tuple(
            source.model_copy(update={"dimension": "feature"}) for source in snapshot.sources
        ),
    )
    selected, diagnostic = await retrieve_question_facts(
        detail, snapshot, "Example Product", "feature", mode="lexical"
    )
    assert original.id in selected
    assert original.id in diagnostic["questions"][0]["core_fact_ids"]
    assert not diagnostic["questions"][0]["missing_core_fact_ids"]
    from types import SimpleNamespace

    from packages.agents.writer.dimension_writer import compact_dimension_context

    view = SimpleNamespace(facts=snapshot.facts, competitor="Example Product", dimension="feature")
    context, _ = compact_dimension_context(
        dict(segment_competitor=view.competitor, dimension=view.dimension),
        view,
        set(selected),
        questions=[dict(question_id="q", question=QUESTION)],
    )
    row = context["evidence_view"]["facts"][0]
    assert row["id"] == original.id
    assert row["source_span_candidates"][0]["quote"] == original.quote.strip()


def test_reference_hints_are_derived_only_from_verified_dispatched_originals():
    from copy import deepcopy

    from test_literal_non_operation import fact
    from test_readable_support_transport import payload_for

    original = fact(quote="Observers can download attachments and export a board.")
    payload = payload_for([original])
    questions = [dict(question_id="q", question="能下载附件并导出看板吗？")]
    tasks = api().question_support_tasks(payload, questions, [original])
    assert all(task["support_refs"] == ["s1"] for task in tasks)
    changed = deepcopy(payload)
    changed["evidence_view"]["facts"][0]["source_span_candidates"][0]["quote"] = "Forged."
    assert all(
        not task["support_refs"]
        for task in api().question_support_tasks(changed, questions, [original])
    )


def test_resource_outcome_recognizes_absence_of_capability_without_borrowing_background():
    from packages.agents.writer.answer_action_scope import _ACTIONS
    from packages.agents.writer.subquestion_premises import _named_action_outcomes

    text = "看板 A 未启用投票时，小林在 A 上不具备投票能力。"
    assert _named_action_outcomes(text, ["A", "B"], _ACTIONS["vote"]) == {"A"}
    background = "看板 B 已启用且允许投票时，小林在 A 上不具备投票能力。"
    assert _named_action_outcomes(background, ["A", "B"], _ACTIONS["vote"]) == {"A"}


def test_whole_document_absence_is_rejected_even_if_a_reviewer_would_support_it():
    from types import SimpleNamespace

    from test_literal_non_operation import fact

    from packages.research.evidence.report_claims import ReportClaim, claim_rule_reasons
    from packages.research.evidence.source_spans import (
        ReportSourceSpanBinding,
        source_span_candidates,
    )

    original = fact(quote="Observers can vote when voting is enabled on the board.")
    claim = ReportClaim(
        id="absence",
        text="所给页面未记载投票属于强制义务。",
        kind="fact",
        competitor=original.competitor,
        dimension="feature",
        fact_ids=[original.id],
        source_ids=[original.source_id],
        source_span_bindings=[ReportSourceSpanBinding(**source_span_candidates(original)[0])],
    )
    reasons = claim_rule_reasons(
        claim, SimpleNamespace(facts=[original]), [SimpleNamespace(allowed_fact_ids=[original.id])]
    )
    assert "source_document_absence_unverified" in reasons


def test_repair_context_reserves_source_before_repeated_review_prose():
    from types import SimpleNamespace

    from test_literal_non_operation import fact

    from packages.agents.writer.dimension_writer import compact_prompt_json
    from packages.agents.writer.question_repair import question_repair_context

    original = fact(quote="Observers can download attachments and export a board.")
    view = SimpleNamespace(facts=[original], competitor=original.competitor, dimension="feature")
    question = dict(question_id="q", question="能下载附件并导出看板吗？")
    targets = [
        dict(
            **question,
            missing_fields=[],
            coverage_failure="Missing separate actions.",
            rejected_claims=[
                dict(
                    claim_id="c",
                    text="Can download and export.",
                    rule_reasons=["claim_check_not_supported"],
                    failed_checks=["atomicity"],
                    review_reason="This long reviewer explanation remains in the formal audit. "
                    * 100,
                )
            ],
        )
    ]
    context, _ = question_repair_context(
        view, {original.id}, [question], targets, [], max_bytes=3000
    )
    assert len(compact_prompt_json(context).encode()) <= 3000
    assert context["evidence_view"]["facts"]
    assert "review_reason" not in context["repair_targets"][0]["rejected_claims"][0]
    assert {task["focus"] for task in context["atom_tasks"]} == {"download", "export"}


def test_repair_metadata_and_originals_share_one_exact_budget():
    from types import SimpleNamespace

    from test_literal_non_operation import fact

    from packages.agents.writer.dimension_writer import compact_prompt_json
    from packages.agents.writer.question_repair import question_repair_context

    originals = [fact(quote="Observers can export the board.")]
    originals.append(
        fact(quote="Observers are set individually per board.").model_copy(update={"id": "scope"})
    )
    view = SimpleNamespace(facts=originals, competitor=originals[0].competitor, dimension="feature")
    question = dict(
        question_id="q", question="请分别回答：他能导出吗；能否在 Workspace 层级统一设置？"
    )
    targets = [
        dict(
            **question,
            coverage_failure="Both requested predicates need an answer.",
            missing_fields=[],
            rejected_claims=[],
        )
    ]
    context, _ = question_repair_context(
        view, {f.id for f in originals}, [question], targets, [], max_bytes=2200
    )
    assert len(compact_prompt_json(context).encode()) <= 2200
    assert {row["id"] for row in context["evidence_view"]["facts"]} == {f.id for f in originals}


def test_invoice_answer_gaps_are_not_request_clarification_plan_fields():
    from types import SimpleNamespace

    from test_literal_non_operation import fact

    from packages.agents.writer.question_repair import question_repair_context

    original = fact(quote="Standard CPU time is billed per million milliseconds.")
    view = SimpleNamespace(facts=[original], competitor=original.competitor, dimension="feature")
    question = dict(question_id="q", question="Standard 模式准确账单是多少美元？")
    targets = [
        dict(
            **question,
            missing_fields=["cpu_usage", "tax_scope"],
            coverage_failure="Missing CPU billing rule.",
            rejected_claims=[],
        )
    ]
    context, _ = question_repair_context(
        view, {original.id}, [question], targets, [], max_bytes=14000
    )
    assert context["question_plan_missing_fields"] == [dict(question_id="q", missing_fields=[])]
    assert context["repair_targets"][0]["missing_fields"] == ["cpu_usage", "tax_scope"]


def test_scenario_context_is_bound_to_inference_plan_and_never_fact_support():
    from types import SimpleNamespace

    from test_literal_non_operation import fact

    from packages.agents.writer.dimension_writer import review_payload
    from packages.research.evidence.report_claims import ReportClaim
    from packages.research.evidence.source_spans import source_span_candidates

    original = fact(quote="Observers can download attachments.")
    inference = ReportClaim(
        id="i",
        text="题设小林作为 A 的 Observer 时可以下载 A 附件。",
        kind="inference",
        competitor=original.competitor,
        dimension="feature",
        fact_ids=[original.id],
        source_ids=[original.source_id],
        source_span_bindings=[source_span_candidates(original)[0]],
    )
    factual = inference.model_copy(update={"id": "f", "kind": "fact", "text": original.quote})
    questions = [
        dict(question_id="q", question="假设小林是 A 的 Observer，能下载附件吗？"),
        dict(question_id="other", question="假设其他用户是管理员，能导出吗？"),
    ]
    payload = review_payload(
        [inference, factual],
        SimpleNamespace(facts=[original], sources=[]),
        review_version=3,
        questions=questions,
        plans=[dict(question_id="q", claim_ids=["i", "f"])],
    )
    assert payload["scenario_claim_questions"] == {"i": ["q"]}
    assert payload["scenario_questions"] == [questions[0]]
    assert all(
        "假设" not in quote for claim in payload["claims"] for quote in claim["support_quotes"]
    )
    unbound = review_payload(
        [inference],
        SimpleNamespace(facts=[original], sources=[]),
        review_version=3,
        questions=questions,
        plans=[],
    )
    assert "scenario_questions" not in unbound


@pytest.mark.asyncio
async def test_metadata_alone_cannot_cross_writer_14kb_dispatch_gate(monkeypatch):
    from datetime import UTC, datetime

    from pydantic import HttpUrl, TypeAdapter
    from test_question_retrieval import research_case
    from test_writer_question_delivery import service_for

    from packages.research.evidence.snapshot import seal_snapshot

    questions = [
        "Example Product："
        + "".join(chr(0x4E00 + index * 751 + offset) for offset in range(750))
        + " Guests能否download附件？"
        for index in range(8)
    ]
    detail, _ = research_case(["Guests can download attachments."], question="\n".join(questions))
    detail.created_at = detail.updated_at = datetime.now(UTC)
    detail.plan.competitors = ["Example Product"]
    detail.plan.dimensions = ["feature"]
    detail.plan.decision_brief = None
    for source in detail.raw_sources:
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
    seal_snapshot(detail, phase="analysis", canonical_documents={})
    service, record = service_for(detail)

    async def forbidden(*args, **kwargs):
        pytest.fail("Oversized request metadata must not reach a provider or dispatch receipt.")

    monkeypatch.setattr(service, "_trace_llm_text", forbidden)
    await service._writer_dimension_report(record, 20)
    assert any(
        "question_context_budget_exceeded" in audit.gaps for audit in detail.report_dimension_audits
    )
    assert not any(span.name == "question_evidence_dispatch" for span in detail.trace_spans)
