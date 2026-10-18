import json
from types import SimpleNamespace

import pytest

from packages.agents.writer.dimension_writer import compact_dimension_context
from packages.research.evidence.snapshot_models import EvidenceFact


def fact(number, quote):
    return EvidenceFact(
        id=f"f{number}",
        semantic_id=f"semantic-{number}",
        source_id="source",
        competitor="Example Product",
        dimension="feature",
        field="evidence_terms",
        value_json=json.dumps([quote]),
        quote=quote,
        status="supported",
        confidence=0.8,
    )


def test_operation_context_keeps_login_answer_and_distinct_role_rules():
    facts = (
        fact(1, "Editors can edit documents on the paid plan."),
        fact(2, "Guests must sign in to access their invited documents."),
        fact(3, "Viewers cannot edit documents on the paid plan."),
    )
    payload, omitted = compact_dimension_context(
        {"segment_competitor": "Example Product", "dimension": "feature"},
        SimpleNamespace(facts=facts),
        {f.id for f in facts},
        requested_operations=("edit",),
    )
    assert {row["id"] for row in payload["evidence_view"]["facts"]} == {"f1", "f2", "f3"}
    assert not omitted


def test_explicit_question_answers_are_selected_before_eight_unrelated_operations():
    facts = [fact(i, f"Editors can edit document {i} on the paid plan.") for i in range(9)]
    login = fact(99, "Guests must sign in and can only access boards they are directly invited to.")
    facts.append(login)
    payload, _ = compact_dimension_context(
        {"segment_competitor": "Example Product", "dimension": "feature"},
        SimpleNamespace(facts=facts),
        {f.id for f in facts},
        requested_operations=("edit",),
        questions=[
            {
                "question_id": "q",
                "question": "Example Product Guest 必须登录才能访问直接邀请的看板吗？",
            }
        ],
    )
    assert login.id in {row["id"] for row in payload["evidence_view"]["facts"]}


def test_coverage_payload_preserves_bound_evidence_without_candidate_duplication():
    from packages.agents.writer.answer_coverage import answer_review_payload
    from packages.research.evidence.report_claims import ReportClaim

    original = fact(1, "Guests must sign in before accessing invited boards.")
    original = original.model_copy(
        update={
            "qualifiers_json": json.dumps(
                {
                    "operations": [{"unused_candidate": "noise" * 10000}],
                    "access": "invited boards only",
                }
            )
        }
    )
    claim = ReportClaim(
        id="c1",
        text=original.quote,
        kind="fact",
        competitor=original.competitor,
        dimension="feature",
        fact_ids=(original.id,),
        source_ids=(original.source_id,),
    )
    payload = answer_review_payload(
        [], [claim], SimpleNamespace(facts=[original], competitor=original.competitor)
    )
    assert payload["competitor"] == original.competitor
    assert payload["facts"][0]["quote"] == original.quote
    assert payload["facts"][0]["qualifiers"] == {"access": "invited boards only"}
    assert "unused_candidate" not in json.dumps(payload)


def test_extra_draft_row_does_not_discard_independently_bound_answers():
    from packages.agents.writer.dimension_writer import parse_claim_drafts

    row = dict(
        text="An original observation.",
        kind="fact",
        competitor="Example Product",
        dimension="feature",
        fact_ids=["original"],
        source_ids=["source"],
    )
    claims, gaps = parse_claim_drafts(json.dumps({"claims": [row] * 9}), {}, {"original"}, "use")
    assert len(claims) == 8
    assert "claim_count_limit_exceeded" in gaps
    invalid = dict(row, fact_ids=["not_sent"])
    claims, gaps = parse_claim_drafts(
        json.dumps({"claims": [invalid] * 8 + [row]}), {}, {"original"}, "use"
    )
    assert len(claims) == 1 and claims[0].fact_ids == ("original",)
    assert "claim_candidate_invalid" in gaps
    empty = dict(row, fact_ids=[], source_ids=[])
    claims, gaps = parse_claim_drafts(
        json.dumps({"claims": [empty] * 8 + [row]}), {}, {"original"}, "use"
    )
    assert len(claims) == 1 and claims[0].fact_ids == ("original",)


def test_questions_are_scoped_request_data_never_evidence_facts():
    from packages.agents.writer.answer_coverage import research_questions

    detail = SimpleNamespace(
        topic="Product research",
        plan=SimpleNamespace(
            competitors=["Example Product", "Other Product"],
            decision_brief=SimpleNamespace(
                decision_question=(
                    "Example Product: Do guests need to sign in?\n"
                    "Other Product: Are editors on a free plan?"
                )
            ),
        ),
    )
    questions = research_questions(detail, "Example Product", "feature")
    assert len(questions) == 1
    assert questions[0]["question"] == "Example Product: Do guests need to sign in?"
    assert set(questions[0]) == {"question_id", "question"}


def test_single_line_independent_product_questions_are_not_silently_skipped():
    from packages.agents.writer.answer_coverage import research_questions

    detail = SimpleNamespace(
        topic="research",
        plan=SimpleNamespace(
            competitors=["Example Product", "Other Product"],
            decision_brief=SimpleNamespace(
                decision_question=(
                    "Example Product 的访客必须登录吗？Other Product 的成员能访问哪些页面？"
                )
            ),
        ),
    )
    for product in detail.plan.competitors:
        questions = research_questions(detail, product, "feature")
        assert len(questions) == 1 and product in questions[0]["question"]


def test_trailing_request_constraint_stays_with_its_question():
    from packages.agents.writer.answer_coverage import research_questions

    text = "Example Product 的外部协作者一定不能担任管理员吗？我们尚未说明账号创建时间。"
    detail = SimpleNamespace(
        topic="research",
        plan=SimpleNamespace(
            competitors=["Example Product"], decision_brief=SimpleNamespace(decision_question=text)
        ),
    )
    questions = research_questions(detail, "Example Product", "feature")
    assert len(questions) == 1
    assert questions[0]["question"] == text


def test_product_names_next_to_chinese_do_not_leak_question_to_other_product():
    from packages.agents.writer.answer_coverage import research_questions

    detail = SimpleNamespace(
        topic="research",
        plan=SimpleNamespace(
            competitors=["Miro", "Airtable"],
            decision_brief=SimpleNamespace(decision_question="我们的Miro看板需要访客登录吗？"),
        ),
    )
    assert len(research_questions(detail, "Miro", "feature")) == 1
    assert research_questions(detail, "Airtable", "feature") == []


@pytest.mark.parametrize(
    "question,counts",
    [
        ("Miro 访客必须登录吗？他们能访问哪些看板？", (2, 0)),
        ("Miro 和 Airtable 的访客分别必须登录吗？", (1, 1)),
        ("需要登录吗？Miro 能评论吗？他们能编辑吗？", (3, 1)),
    ],
)
def test_followup_and_joint_questions_preserve_declared_product_scope(question, counts):
    from packages.agents.writer.answer_coverage import research_questions

    detail = SimpleNamespace(
        topic="research",
        plan=SimpleNamespace(
            competitors=["Miro", "Airtable"],
            decision_brief=SimpleNamespace(decision_question=question),
        ),
    )
    assert (
        tuple(len(research_questions(detail, p, "feature")) for p in ["Miro", "Airtable"]) == counts
    )


@pytest.mark.parametrize("depth", ["quick", "standard", "deep"])
def test_explicit_feature_questions_use_audited_route_at_every_depth(depth):
    from packages.business_intel.report_contract import dimension_report_profile

    plan = SimpleNamespace(
        research_depth=depth,
        dimensions=["feature"],
        target_product=None,
        decision_brief=SimpleNamespace(decision_question="Miro 访客必须登录吗？"),
    )
    assert dimension_report_profile(plan, topic="比较协作工具")


def test_distinct_original_limits_are_not_merged_by_operation_identity():
    from packages.agents.writer.dimension_writer import operation_claim_selection
    from packages.research.evidence.operations import operation_binding, operation_observations
    from packages.research.evidence.report_claims import ReportClaim

    facts = (
        fact(1, "Members can edit up to 5 documents on the paid plan."),
        fact(2, "Members can edit documents of up to 10 MB on the paid plan."),
    )
    claims = []
    for original in facts:
        binding = operation_binding(operation_observations(original)[0])
        claims.append(
            ReportClaim(
                id=original.id,
                text=original.quote,
                kind="fact",
                competitor=original.competitor,
                dimension="feature",
                fact_ids=(original.id,),
                source_ids=(original.source_id,),
                operation_binding=binding,
            )
        )
    selected = operation_claim_selection(
        claims, SimpleNamespace(facts=facts), ("edit",), {"f1", "f2"}
    )
    assert len(selected) == 2


def test_same_original_fact_keeps_distinct_actor_observations():
    original = fact(
        1, "Editors can edit documents on the paid plan; viewers cannot edit documents."
    )
    payload, _ = compact_dimension_context(
        {"segment_competitor": "Example Product", "dimension": "feature"},
        SimpleNamespace(facts=(original,)),
        {"f1"},
        requested_operations=("edit",),
    )
    rows = payload["evidence_view"]["facts"][0]["operation_observations"]
    assert {row["effect"] for row in rows} == {"allowed", "denied"}


def test_answer_review_cannot_claim_complete_with_rejected_or_unknown_claim_ids():
    from packages.agents.writer.answer_coverage import parse_answer_coverage

    questions = [{"question_id": "q1", "question": "Is sign-in required?"}]
    payload = json.dumps(
        {
            "answers": [
                {
                    "question_id": "q1",
                    "status": "answered",
                    "claim_ids": ["rejected"],
                    "reason": "Claimed complete.",
                }
            ]
        }
    )
    result = parse_answer_coverage(payload, questions, {"accepted"})
    assert result[0].status == "unverified"


def test_answer_review_requires_one_row_per_question_and_never_invents_answers():
    from packages.agents.writer.answer_coverage import parse_answer_coverage

    questions = [{"question_id": "q1", "question": "Is sign-in required?"}]
    for rows in (
        [],
        [
            {
                "question_id": "q1",
                "status": "answered",
                "claim_ids": ["accepted"],
                "reason": "Supported.",
            },
            {
                "question_id": "q1",
                "status": "answered",
                "claim_ids": ["accepted"],
                "reason": "Duplicate.",
            },
        ],
    ):
        result = parse_answer_coverage(json.dumps({"answers": rows}), questions, {"accepted"})
        assert len(result) == 1 and result[0].status == "unverified"
        assert not result[0].claim_ids


def test_answer_coverage_preserves_missing_and_partial_as_incomplete():
    from packages.agents.writer.answer_coverage import parse_answer_coverage

    questions = [{"question_id": "q1", "question": "Is sign-in required?"}]
    result = parse_answer_coverage(
        json.dumps(
            {
                "answers": [
                    {
                        "question_id": "q1",
                        "status": "partial",
                        "claim_ids": ["accepted"],
                        "reason": "Access scope was not answered.",
                        "answer": "Sign-in is required; the access scope is not established.",
                        "resolution": "conditional", "conclusion": "depends",
                        "evidence_spans": [{"claim_id": "accepted", "quote": "Sign-in is required."}],
                    }
                ]
            }
        ),
        questions,
        {"accepted"},
        claims=[{"id": "accepted", "text": "Sign-in is required."}],
    )
    assert result[0].status == "partial"
    assert result[0].question == questions[0]["question"]


def test_partial_report_does_not_repeat_long_request_or_empty_comparison(monkeypatch):
    from test_stage_evidence_views import distributed_detail

    from packages.agents.writer import dimension_writer

    detail = distributed_detail(observations=1)
    detail.topic = "请对产品的登录权限和访问范围进行调研，并解释每个限制条件。" * 10
    monkeypatch.setattr(dimension_writer, "partial_report_mode", lambda *args: True)
    report = dimension_writer.render_dimension_report(detail, [], snapshot=None)
    assert detail.topic not in report
    assert "同操作与条件对照" not in report
    assert len(report) < 1100


@pytest.mark.asyncio
async def test_oversized_question_set_keeps_all_tasks_without_calling_model(monkeypatch):
    from pydantic import HttpUrl, TypeAdapter
    from test_stage_evidence_views import FixedTime, distributed_detail
    from packages.config import Settings
    from packages.memory import KBCache, RunJournal
    from packages.orchestrator.checkpointer import GraphCheckpointer
    from packages.orchestrator.service import RunRecord, RunService
    from packages.research.evidence.snapshot import seal_snapshot
    from packages.schema.models import DecisionBrief
    from packages.skills.registry import SkillRegistry

    monkeypatch.setattr("packages.research.evidence.views.datetime", FixedTime)
    detail = distributed_detail(observations=1)
    detail.plan.competitors = ["Notion"]
    detail.plan.research_depth = "quick"
    detail.plan.dimensions = ["feature"]
    detail.plan.decision_brief = DecisionBrief(
        decision_question="".join(chr(0x4E00 + i) + "？" for i in range(250))
    )
    detail.raw_sources = [s for s in detail.raw_sources if s.competitor == "Notion"]
    for source in detail.raw_sources:
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
    service = RunService(
        SkillRegistry.from_default_path(),
        Settings(demo_mode=True),
        journal=RunJournal.in_memory(),
        kb_cache=KBCache.in_memory(),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    record = RunRecord(detail)
    service._runs[detail.id] = record
    seal_snapshot(detail, phase="analysis", canonical_documents={})

    async def forbidden(*args, **kwargs):
        pytest.fail("oversized complete question context must not reach a model")

    monkeypatch.setattr(service, "_trace_llm_text", forbidden)
    await service._writer_dimension_report(record, 20)
    audit = detail.report_dimension_audits[0]
    assert len(audit.answer_coverage) == 250
    assert all(row.status == "unverified" for row in audit.answer_coverage)
    assert "question_context_budget_exceeded" in audit.gaps


@pytest.mark.asyncio
@pytest.mark.parametrize("complete", [False, True])
async def test_writer_question_coverage_is_persisted_and_final_qa_blocks_omission(
    monkeypatch, complete
):
    from pydantic import HttpUrl, TypeAdapter
    from test_stage_evidence_views import FixedTime, distributed_detail

    from packages.config import Settings
    from packages.memory import KBCache, RunJournal
    from packages.orchestrator.checkpointer import GraphCheckpointer
    from packages.orchestrator.service import RunRecord, RunService
    from packages.research.evidence.snapshot import seal_snapshot
    from packages.schema.models import DecisionBrief
    from packages.skills.registry import SkillRegistry

    monkeypatch.setattr("packages.research.evidence.views.datetime", FixedTime)
    detail = distributed_detail(observations=1)
    detail.plan.competitors = ["Notion"]
    detail.plan.research_depth = "quick"
    detail.plan.dimensions = ["feature"]
    detail.plan.decision_brief = DecisionBrief(
        decision_question="Notion: Must members sign in to access documents?"
    )
    detail.topic = "Notion permission research"
    detail.execution_mode = "real"
    detail.raw_sources = [source for source in detail.raw_sources if source.competitor == "Notion"]
    source = detail.raw_sources[0]
    source.url = TypeAdapter(HttpUrl).validate_python(source.url)
    quote = "Members must sign in before accessing their own documents."
    source.metadata["normalized_fields"] = [
        {
            "kind": "feature",
            "competitor": "Notion",
            "dimension": "feature",
            "slot": "access",
            "support_level": "documented",
            "confidence": 0.8,
            "evidence_terms": [quote],
            "evidence_quote": quote,
            "evidence_item_ids": ["login-item"],
        }
    ]
    service = RunService(
        SkillRegistry.from_default_path(),
        Settings(demo_mode=True),
        journal=RunJournal.in_memory(),
        kb_cache=KBCache.in_memory(),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    record = RunRecord(detail)
    service._runs[detail.id] = record
    seal_snapshot(detail, phase="analysis", canonical_documents={})
    calls = []

    async def model(record, **kwargs):
        calls.append(kwargs["name"])
        payload = json.loads(kwargs["user"].split("\nJSON:\n", 1)[1])
        if kwargs["name"] == "dimension_claim_review":
            return json.dumps(
                {
                    "reviews": [
                        {
                            "claim_id": claim["id"],
                            "verdict": "supported",
                            "reason": "A supported atomic statement.",
                        }
                        for claim in payload["claims"]
                    ]
                }
            )
        if kwargs["name"] in {"dimension_answer_coverage", "dimension_answer_review"}:
            return json.dumps(
                {
                    "version": 2,
                    "answers": [
                        {
                            "question_id": q["question_id"],
                            "status": "answered" if complete else "partial",
                            "claim_ids": [c["id"] for c in payload["claims"]],
                            "resolution": "direct", "conclusion": "yes", "missing_fields": [],
                            "reason": "Login is answered."
                            if complete
                            else "The login answer is omitted.",
                        }
                        for q in payload["questions"]
                    ]
                }
            )
        row = payload["evidence_view"]["facts"][0]
        return json.dumps(
            {
                "claims": [
                    {
                        "text": "Members must sign in before accessing their own documents."
                        if complete
                        else "Members have documents.",
                        "kind": "fact",
                        "competitor": "Notion",
                        "dimension": "feature",
                        "fact_ids": [row["id"]],
                        "source_ids": [row["source_id"]],
                    }
                ]
            }
        )

    monkeypatch.setattr(service, "_trace_llm_text", model)
    await service._real_writer_step(record)
    assert calls.count("dimension_answer_coverage") == 1
    assert calls.count("dimension_answer_review") == 1
    coverage = detail.report_dimension_audits[0].answer_coverage
    assert len(coverage) == 1 and coverage[0].status == ("answered" if complete else "unverified")
    if not complete:
        assert "# 局部调研报告" in detail.report_md
        assert "同操作与条件对照" not in detail.report_md
    from packages.agents.qa.evidence_alignment import audit_dimension_claims

    issues = audit_dimension_claims(
        service, record, service._current_evidence_snapshot(record), producer_verified=True
    )
    coverage_issues = [
        issue
        for issue in issues
        if issue.metadata.get("claim_audit_reason") == "answer_coverage_incomplete"
    ]
    assert bool(coverage_issues) is not complete
    assert all(
        issue.severity == "blocker" and issue.redo_scope.kind == "writer_only"
        for issue in coverage_issues
    )
    if complete:
        detail.plan.decision_brief = DecisionBrief(
            decision_question="Notion: Can guests access all documents?"
        )
        changed = audit_dimension_claims(
            service, record, service._current_evidence_snapshot(record), producer_verified=True
        )
        assert any(
            issue.metadata.get("claim_audit_reason") == "answer_coverage_scope_changed"
            for issue in changed
        )
