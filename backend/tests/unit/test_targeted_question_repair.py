"""Targeted recovery uses current dispatched evidence, never answer-review prose."""

import asyncio
import json
from datetime import UTC, datetime

import pytest
from claim_review_fixture import (
    answer_response,
    expand_prompt_payload,
    question_plan_response,
    sent_source_atom,
    supported_review,
)
from pydantic import HttpUrl, TypeAdapter
from test_question_retrieval import research_case
from test_writer_question_delivery import service_for

from packages.agents.qa.evidence_alignment import audit_dimension_claims
from packages.agents.writer.answer_coverage import (
    coverage_resolution_reasons,
    parse_answer_coverage,
)
from packages.llm.doubao_client import LLMUsage
from packages.llm.errors import LLMExecutionLimitError
from packages.llm.execution_budget import current_llm_execution
from packages.orchestrator.evidence_context import EvidenceUseRejectedError
from packages.research.evidence.snapshot import current_snapshot, seal_snapshot
from packages.schema.models import DecisionBrief


def resource_answer(
    texts, *, question="A 的投票已关闭，B 已开启投票。观察者能在看板 A、B 上分别投票吗？"
):
    claims = [dict(id=f"c{i}", kind=kind, text=text) for i, (kind, text) in enumerate(texts)]
    ids = [c["id"] for c in claims]
    row = dict(
        question_id="q",
        status="answered",
        claim_ids=ids,
        resolution="conditional",
        conclusion="depends",
        missing_fields=[],
        reason="Reviewed.",
        subquestions=[
            dict(question_quote=question, claim_ids=ids, conclusion="depends", relation="direct")
        ],
    )
    return parse_answer_coverage(
        json.dumps({"version": 3, "answers": [row]}),
        [dict(question_id="q", question=question)],
        set(ids),
        claims=claims,
        required_binding_version=3,
        require_subquestions=True,
    )[0], claims


@pytest.mark.parametrize(
    "question",
    [
        "A 的投票已关闭，B 已开启投票。观察者能在看板 A、B 上分别投票吗？",
        "Voting is disabled on A and enabled on B. Can observers vote on boards A and B?",
    ],
)
def test_named_resource_request_rejects_generic_rule_and_depends(question):
    result, _ = resource_answer(
        [("fact", "Observers can vote when voting is enabled on a board.")], question=question
    )
    assert result.status == "unverified"
    assert "answer_named_resource_outcome_missing" in result.reason


@pytest.mark.parametrize(
    "text",
    [
        "在看板 B 已开启投票而看板 A 关闭投票的题设下，观察者不能在看板 A 上投票。",
        "在与看板 A、B 的设置无关时，观察者可以在开启投票的看板上投票。",
    ],
)
def test_resource_labels_in_scenario_do_not_supply_missing_item_outcomes(text):
    result, _ = resource_answer([("inference", text)])
    assert result.status == "unverified"
    assert "answer_named_resource_outcome_missing" in result.reason


def test_resource_list_in_background_does_not_expand_single_resource_request():
    question = "看板 A、B 是归档看板。观察者可以在看板 C 上投票吗？"
    result, _ = resource_answer(
        [("inference", "在题设看板 C 已开启投票的条件下，观察者可以在看板 C 上投票。")],
        question=question,
    )
    assert result.status == "answered", result.reason


@pytest.mark.parametrize("missing", ["A", "B", None])
def test_named_resources_need_visible_published_outcome_for_each_item(missing):
    texts = [("fact", "Observers can vote when voting is enabled on a board.")]
    if missing != "A":
        texts.append(("inference", "在题设 A 关闭投票的条件下，观察者不能在看板 A 上投票。"))
    if missing != "B":
        texts.append(("inference", "在题设 B 开启投票的条件下，观察者可以在看板 B 上投票。"))
    result, claims = resource_answer(texts)
    assert result.status == ("answered" if missing is None else "unverified"), result.reason
    if missing is None:
        restored = type(result).model_validate_json(result.model_dump_json())
        assert not coverage_resolution_reasons(restored, claims, require_subquestions=True)
        changed = [row for row in claims if "看板 B" not in row["text"]]
        assert coverage_resolution_reasons(restored, changed, require_subquestions=True)


def repair_case():
    question = (
        "Example Product: Do visitors have a personal compartment?\n"
        "Do members have a personal compartment?"
    )
    quotes = [
        "Visitors may be invited by members.",
        "Visitors cannot have a personal compartment.",
        "Members can have a personal compartment.",
    ]
    detail, _ = research_case(quotes, question=question)
    detail.created_at = detail.updated_at = datetime.now(UTC)
    detail.plan.competitors = ["Example Product"]
    detail.plan.dimensions = ["feature"]
    detail.plan.decision_brief = DecisionBrief(decision_question=question)
    for source in detail.raw_sources:
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
    seal_snapshot(detail, phase="analysis", canonical_documents={})
    return detail, *service_for(detail)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode",
    [
        "valid",
        "actual_transport",
        "missing_rule",
        "no_answer_selected",
        "context_budget",
        "bad_model",
        "unknown_ref",
        "cross_fact",
        "other_question",
        "too_many",
        "bad_review",
        "unsupported_review",
        "budget",
        "review_budget",
        "changed",
        "cancelled",
    ],
)
async def test_wrong_support_is_reselected_for_only_failed_question_then_saved_and_qa_replayed(
    monkeypatch, mode
):
    detail, service, record = repair_case()
    calls, retained = [], []
    if mode == "context_budget":
        from packages.agents.writer import question_repair

        original_context = question_repair.question_repair_context

        def tiny_context(*args, **kwargs):
            return original_context(*args, **{**kwargs, "max_bytes": 1})

        monkeypatch.setattr(question_repair, "question_repair_context", tiny_context)

    async def model(record, **kwargs):
        calls.append(kwargs["name"])
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        if kwargs["name"] == "dimension_claim_writer":
            rows = payload["evidence_view"]["facts"]
            invite = next(row for row in rows if row["quote"].startswith("Visitors may"))
            member = next(row for row in rows if row["quote"].startswith("Members can"))
            return json.dumps(
                {
                    "question_plans": [
                        dict(
                            question_id=q["question_id"],
                            missing_fields=[],
                            atoms=[]
                            if mode in {"missing_rule", "no_answer_selected"} and index == 0
                            else [
                                sent_source_atom(
                                    invite, "Visitors cannot have a personal compartment."
                                )
                                if index == 0
                                else sent_source_atom(member, member["quote"])
                            ],
                        )
                        for index, q in enumerate(payload["questions"])
                    ]
                }
            )
        if kwargs["name"] == "dimension_claim_review":
            reviews = []
            for claim in payload["claims"]:
                review = supported_review(claim)
                if claim["text"].startswith("Visitors"):
                    review.update(
                        verdict="unsupported",
                        reason=(
                            "The selected quote only supports invitation, "
                            "not personal compartment denial."
                        ),
                    )
                    for check in review["checks"]:
                        check["verdict"] = "unsupported"
                else:
                    retained.append(claim["id"])
                reviews.append(review)
            return json.dumps({"reviews": reviews})
        if kwargs["name"] == "dimension_question_repair":
            assert kwargs["max_output_tokens"] == 1600
            if mode == "no_answer_selected":
                return question_plan_response(payload, [])
            assert (
                len(payload["questions"]) == 1 and "visitors" in payload["questions"][0]["question"]
            )
            assert {row["id"] for row in payload["retained_supported_claims"]} == set(retained)
            assert ("not published" if mode == "missing_rule" else "invitation") in json.dumps(
                payload["repair_targets"]
            )
            if mode == "bad_model":
                return "not JSON"
            if mode == "budget":
                raise LLMExecutionLimitError("run_llm_token_budget_exceeded")
            if mode == "cancelled":
                raise asyncio.CancelledError("cancel targeted repair")
            if mode == "changed":
                record.detail.raw_sources[0].content_hash = "changed-during-targeted-repair"
                seal_snapshot(record.detail, phase="analysis", canonical_documents={})
            fact = next(
                row
                for row in payload["evidence_view"]["facts"]
                if row["quote"].startswith("Visitors cannot")
            )
            atom = sent_source_atom(fact, fact["quote"])
            if mode == "unknown_ref":
                atom["support_refs"] = ["s999999"]
            if mode == "cross_fact":
                other = next(
                    row for row in payload["evidence_view"]["facts"] if row["id"] != fact["id"]
                )
                atom["support_refs"].extend(sent_source_atom(other, other["quote"])["support_refs"])
            response = json.loads(
                question_plan_response(payload, [atom] * (5 if mode == "too_many" else 1))
            )
            if mode == "other_question":
                response["question_plans"][0]["question_id"] = "previously-completed-question"
            return json.dumps(response)
        if kwargs["name"] == "dimension_question_repair_review":
            assert kwargs["max_output_tokens"] == 2048
            if mode == "bad_review":
                return "not JSON"
            if mode == "review_budget":
                raise LLMExecutionLimitError("run_llm_token_budget_exceeded")
            reviews = [supported_review(claim) for claim in payload["claims"]]
            if mode == "unsupported_review":
                for review in reviews:
                    review["verdict"] = "unsupported"
                    for check in review["checks"]:
                        check["verdict"] = "unsupported"
            return json.dumps({"reviews": reviews})
        assert kwargs["name"] in {"dimension_answer_coverage", "dimension_answer_review"}
        rows = []
        for question in payload["questions"]:
            visitor = "visitors" in question["question"]
            chosen = [
                c["id"]
                for c in payload["claims"]
                if c["text"].startswith("Visitors" if visitor else "Members")
            ]
            rows.append(
                dict(
                    question_id=question["question_id"],
                    status="answered" if chosen else "unverified",
                    claim_ids=chosen,
                    resolution="direct" if chosen else "unresolved",
                    conclusion=("no" if visitor else "yes") if chosen else "unknown",
                    missing_fields=[],
                    reason=(
                        "No answer selected."
                        if mode == "no_answer_selected"
                        else "The personal compartment rule is not published."
                    )
                    if not chosen
                    else "Reviewed.",
                )
            )
        return answer_response(
            payload,
            {"version": 3, "answers": rows},
            relation="explicit_negative" if len(rows) == 1 else "direct",
        )

    if mode == "actual_transport":

        async def complete_text(*, system, user):
            current_llm_execution.get().reserve_transport()
            payload = expand_prompt_payload(json.loads(user.split("\nJSON:\n", 1)[1]))
            if "repair_targets" in payload:
                name = "dimension_question_repair"
            elif "evidence_view" in payload:
                name = "dimension_claim_writer"
            elif "proposed_answers" in payload:
                name = "dimension_answer_review"
            elif "questions" in payload:
                name = "dimension_answer_coverage"
            else:
                name = (
                    "dimension_question_repair_review"
                    if "dimension_question_repair" in calls
                    else "dimension_claim_review"
                )
            return await model(
                record,
                name=name,
                user=user,
                max_output_tokens=1600 if name == "dimension_question_repair" else 2048,
            )

        monkeypatch.setattr(service._llm, "complete_text", complete_text)
        monkeypatch.setattr(
            service._llm,
            "consume_last_usage",
            lambda: LLMUsage(prompt_tokens=12, completion_tokens=8, total_tokens=20),
        )
    else:
        monkeypatch.setattr(service, "_trace_llm_text", model)
    if mode in {"changed", "cancelled"}:
        with pytest.raises(
            EvidenceUseRejectedError if mode == "changed" else asyncio.CancelledError
        ):
            await service._writer_dimension_report(record, 20)
        assert not detail.report_dimension_audits and not detail.report_md
        return
    await service._real_writer_step(record)
    audit = detail.report_dimension_audits[0]
    assert calls.count("dimension_question_repair") == (
        0 if mode in {"context_budget", "no_answer_selected"} else 1
    )
    if mode not in {"valid", "actual_transport", "missing_rule"}:
        assert audit.answer_coverage[0].status == "unverified"
        assert audit.answer_coverage[1].status == "answered"
        assert set(retained) == {row.claim.id for row in audit.claims if row.status == "supported"}
        assert "Visitors cannot have a personal compartment." not in detail.report_md
        assert len(calls) <= 7
        return
    assert all(answer.status == "answered" for answer in audit.answer_coverage), (
        audit.model_dump_json()
    )
    assert set(retained) <= {row.claim.id for row in audit.claims if row.status == "supported"}
    saved = type(audit).model_validate_json(audit.model_dump_json())
    assert saved == audit
    assert not audit_dimension_claims(
        service, record, current_snapshot(detail), producer_verified=True
    )
    assert (
        len(calls) <= 10
    )  # Initial five calls plus one Writer, two reviewers and two answers at most.
    if mode == "actual_transport":
        receipt = next(
            span for span in detail.trace_spans if span.name == "question_repair_dispatch"
        )
        writer_span = next(
            span for span in detail.trace_spans if span.name == "dimension_question_repair"
        )
        assert writer_span.metadata["llm_max_output_tokens"] == 1600
        assert json.loads(receipt.full_output)["dispatch_verified"], json.dumps(
            [
                span.model_dump(mode="json", include={"name", "kind", "status", "metadata"})
                for span in detail.trace_spans
                if "repair" in span.name
            ]
        )
        assert detail.llm_budget_checkpoint["calls"] == len(calls)
        assert detail.llm_budget_checkpoint["tokens_charged"] == 20 * len(calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("initial_cpu_rule", [False, True])
async def test_cpu_question_publishes_missing_positive_rule_through_repair_without_computing_bill(
    monkeypatch, initial_cpu_rule
):
    from test_answer_publication_recovery import INTRO, TABLE_HEADER, TABLE_ROW

    quote, conditions, table = TABLE_ROW, [INTRO], [TABLE_HEADER]
    question = "Example Product：Compute Paid Standard 本月有2300万次请求，账单准确是多少美元？"
    detail, _ = research_case([quote], question=question)
    detail.created_at = detail.updated_at = datetime.now(UTC)
    detail.plan.competitors, detail.plan.dimensions = ["Example Product"], ["feature"]
    detail.plan.decision_brief = DecisionBrief(decision_question=question)
    source = detail.raw_sources[0]
    source.url = TypeAdapter(HttpUrl).validate_python(source.url)
    source.metadata["normalized_fields"][0].update(
        evidence_terms=[quote, *conditions, *table],
        qualifiers={"conditions": conditions, "table_context": table},
    )
    seal_snapshot(detail, phase="analysis", canonical_documents={})
    service, record = service_for(detail)
    calls = []
    text = "Standard usage model CPU time is billed."

    async def model(record, **kwargs):
        calls.append(kwargs["name"])
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        if kwargs["name"] == "dimension_claim_writer":
            atoms = (
                [sent_source_atom(payload["evidence_view"]["facts"][0], text, support_text=quote)]
                if initial_cpu_rule
                else []
            )
            return question_plan_response(payload, atoms)
        if kwargs["name"] == "dimension_question_repair":
            assert "cpu_usage" in payload["repair_targets"][0]["missing_fields"]
            fact = next(row for row in payload["evidence_view"]["facts"] if row["quote"] == quote)
            return question_plan_response(
                payload, [sent_source_atom(fact, text, support_text=quote)]
            )
        assert kwargs["name"] in {"dimension_claim_review", "dimension_question_repair_review"}
        return json.dumps({"reviews": [supported_review(claim) for claim in payload["claims"]]})

    monkeypatch.setattr(service, "_trace_llm_text", model)
    await service._real_writer_step(record)
    audit = detail.report_dimension_audits[0]
    answer = audit.answer_coverage[0]
    assert answer.status == "partial" and answer.resolution == "insufficient"
    assert "cpu_usage" in answer.missing_fields and text in answer.answer
    assert answer.claim_ids and text in detail.report_md
    assert calls == (
        ["dimension_claim_writer", "dimension_claim_review"]
        if initial_cpu_rule
        else [
            "dimension_claim_writer",
            "dimension_question_repair",
            "dimension_question_repair_review",
        ]
    )
    assert not any(
        issue.metadata.get("claim_audit_reason") == "price_answer_changed"
        for issue in audit_dimension_claims(
            service, record, current_snapshot(detail), producer_verified=True
        )
    )


def test_repair_batches_bound_explicit_checks_and_two_review_calls():
    from packages.agents.writer.dimension_writer import compact_prompt_json
    from packages.agents.writer.question_repair import repair_review_batches
    from packages.research.evidence.report_claims import ReportClaim
    from packages.research.evidence.source_spans import (
        ReportSourceSpanBinding,
        source_span_candidates,
    )

    detail, service, record = repair_case()
    view, use = service._begin_evidence_use(
        record, agent="writer", competitor="Example Product", dimension="feature"
    )
    fact = next(fact for fact in view.facts if fact.field == "evidence_terms")
    claims = [
        ReportClaim(
            id=f"new-{i}",
            text=fact.quote,
            kind="fact",
            competitor=fact.competitor,
            dimension=fact.dimension,
            fact_ids=(fact.id,),
            source_ids=(fact.source_id,),
            source_span_bindings=(ReportSourceSpanBinding(**source_span_candidates(fact)[0]),),
        )
        for i in range(5)
    ]
    batches, omitted = repair_review_batches(claims, view, [], max_bytes=use.max_bytes)
    assert len(batches) == 2 and omitted
    assert sum(len(batch["claims"]) for batch in batches) == 4
    assert all(
        sum(len(claim["required_checks"]) for claim in batch["claims"]) <= 10 for batch in batches
    )
    assert all(len(compact_prompt_json(batch).encode()) <= use.max_bytes for batch in batches)
    assert repair_review_batches(claims, view, [], max_bytes=8) == ([], True)


@pytest.mark.parametrize(
    "reason",
    [
        "Answer coverage could not be verified.",
        "Answer semantic review was not completed.",
        "Answer coverage response was missing or invalid: missing or duplicate coverage",
        "Answer coverage response was missing or invalid: invalid claim selection row",
        "Answer coverage response was missing or invalid: coverage cites unpublished claims",
    ],
)
def test_unavailable_or_malformed_coverage_does_not_blindly_retry_rejected_drafts(reason):
    from types import SimpleNamespace

    from packages.agents.writer.question_repair import question_repair_targets
    from packages.research.evidence.answer_coverage_models import ReportAnswerCoverage

    question = dict(question_id="q", question="Can a visitor have a compartment?")
    answer = ReportAnswerCoverage(**question, status="unverified", reason=reason)
    rejected = SimpleNamespace(
        status="rejected",
        claim=SimpleNamespace(id="bad", text="Unsupported."),
        rule_reasons=("claim_check_not_supported",),
        review=SimpleNamespace(verdict="unsupported", reason="Wrong support."),
    )
    assert (
        question_repair_targets(
            [question], [answer], [rejected], [dict(question_id="q", claim_ids=["bad"])]
        )
        == []
    )


def test_repair_supports_are_grouped_in_original_question_order_without_changing_originals():
    from packages.agents.writer.answer_coverage import research_questions
    from packages.agents.writer.dimension_writer import _support_ref_catalog, compact_prompt_json
    from packages.agents.writer.question_repair import question_repair_context

    detail, service, record = repair_case()
    view, _ = service._begin_evidence_use(
        record, agent="writer", competitor="Example Product", dimension="feature"
    )
    questions = research_questions(detail, "Example Product", "feature")
    context, _ = question_repair_context(
        view, set(view.fact_ids), questions, [], [], max_bytes=14000
    )
    groups = context["question_support_order"]
    assert [row["question_id"] for row in groups] == [row["question_id"] for row in questions]
    catalog = _support_ref_catalog(context, view.facts, set(view.fact_ids))
    assert all(set(row["support_refs"]) <= catalog.keys() for row in groups)
    first = catalog[groups[0]["support_refs"][0]]["fact_ids"][0]
    assert next(fact for fact in view.facts if fact.id == first).quote.startswith("Visitors cannot")
    assert len(compact_prompt_json(context).encode()) <= 14000


def test_rejected_missing_predicate_guides_support_order_without_changing_source_aliases():
    from packages.agents.writer.dimension_writer import _support_ref_catalog
    from packages.agents.writer.question_repair import question_repair_context

    question = {
        "question_id": "q",
        "question": "The invited visitor has accepted the invitation and "
        "been confirmed by a member. Can this confirmed invited visitor own a private compartment?",
    }
    invitation = "A visitor must accept the invitation and be confirmed by a member."
    key_rule = "Visitors cannot own a private compartment."
    detail, _ = research_case([invitation, key_rule])
    service, record = service_for(detail)
    view, _ = service._begin_evidence_use(
        record, agent="writer", competitor="Example Product", dimension="feature"
    )
    base, _ = question_repair_context(view, set(view.fact_ids), [question], [], [], max_bytes=14000)
    targets = [
        dict(
            **question,
            rejected_claims=[dict(text=key_rule)],
            coverage_failure="Missing private compartment rule.",
        )
    ]
    focused, _ = question_repair_context(
        view, set(view.fact_ids), [question], targets, [], max_bytes=14000
    )
    catalog = _support_ref_catalog(base, view.facts, set(view.fact_ids))
    assert catalog == _support_ref_catalog(focused, view.facts, set(view.fact_ids))
    original_by_id = {fact.id: fact.quote for fact in view.facts}

    def first_quote(context):
        ref = context["question_support_order"][0]["support_refs"][0]
        return original_by_id[catalog[ref]["fact_ids"][0]]

    assert first_quote(base) == invitation
    assert first_quote(focused) == key_rule


def test_review_transport_keeps_full_claim_and_required_claim_spans_literal():
    from packages.agents.writer.dimension_writer import compact_prompt_json, parse_claim_reviews

    text = "Basic workspace permits only two members under the documented account scope and "
    text += "the standard per-workspace membership limit, including the workspace owner."
    payload = dict(
        claims=[
            dict(
                id="c",
                text=text,
                required_checks=[
                    dict(check_id=kind, kind=kind, claim_span=text)
                    for kind in ("full_assertion_support", "atomicity")
                ],
            )
        ],
        restriction_context=dict(previous_text=text),
    )
    raw = json.loads(compact_prompt_json(payload))
    assert raw["claims"][0]["text"] == text
    assert all(check["claim_span"] == text for check in raw["claims"][0]["required_checks"])
    # A model-returned reference remains an invalid response, even when that
    # reference would have named the current input text. No schema is relaxed.
    reviews, invalid = parse_claim_reviews(
        json.dumps(
            {
                "reviews": [
                    dict(
                        claim_id="c",
                        verdict="supported",
                        reason="Reviewed.",
                        checks=[
                            dict(
                                check_id="full_assertion_support",
                                verdict="supported",
                                claim_span={"text_ref": "t0"},
                            )
                        ],
                    )
                ]
            }
        ),
        {"c"},
    )
    assert invalid and not reviews


@pytest.mark.asyncio
async def test_actual_long_claim_review_transport_keeps_original_premise_and_literal_text(
    monkeypatch,
):
    text = (
        "Basic workspace permits only two members under the documented account scope and "
        "the standard per-workspace membership limit, including the workspace owner."
    )
    question = "Example Product: What is the Basic workspace capacity?"
    detail, _ = research_case([text], question=question)
    detail.created_at = detail.updated_at = datetime.now(UTC)
    detail.plan.competitors, detail.plan.dimensions = ["Example Product"], ["feature"]
    detail.plan.decision_brief = DecisionBrief(decision_question=question)
    detail.raw_sources[0].url = TypeAdapter(HttpUrl).validate_python(detail.raw_sources[0].url)
    seal_snapshot(detail, phase="analysis", canonical_documents={})
    service, record = service_for(detail)
    calls = []

    async def complete_text(*, system, user):
        current_llm_execution.get().reserve_transport()
        raw = json.loads(user.split("\nJSON:\n", 1)[1])
        payload = expand_prompt_payload(raw)
        if "evidence_view" in payload:
            return question_plan_response(
                payload, [sent_source_atom(payload["evidence_view"]["facts"][0], text)]
            )
        if "atom_review_policy" in payload:
            calls.append("review")
            assert raw["claims"][0]["text"] == text
            assert all(
                check["claim_span"] == text
                for check in raw["claims"][0]["required_checks"]
                if check["kind"] in {"full_assertion_support", "atomicity"}
            )
            assert payload["claims"][0]["support_quotes"] == [text]
            return json.dumps({"reviews": [supported_review(claim) for claim in payload["claims"]]})
        return answer_response(
            payload,
            {
                "version": 3,
                "answers": [
                    dict(
                        question_id=q["question_id"],
                        status="unverified",
                        resolution="unresolved",
                        conclusion="unknown",
                        claim_ids=[],
                        missing_fields=[],
                        reason="No answer selected.",
                    )
                    for q in payload["questions"]
                ],
            },
        )

    monkeypatch.setattr(service._llm, "complete_text", complete_text)
    monkeypatch.setattr(
        service._llm,
        "consume_last_usage",
        lambda: LLMUsage(prompt_tokens=12, completion_tokens=8, total_tokens=20),
    )
    monkeypatch.setattr(
        "packages.agents.writer.question_retrieval.get_local_provider_from_env", lambda *_: None
    )
    await service._real_writer_step(record)
    supported = [
        item.claim
        for item in detail.report_dimension_audits[0].claims
        if item.status == "supported"
    ]
    assert calls == ["review"] and len(supported) == 1
    assert supported[0].text == supported[0].source_span_bindings[0].quote == text
    assert all(use.estimated_bytes <= use.max_bytes for use in detail.evidence_consumptions)


def test_repair_focus_is_forwarded_before_canonical_span_windowing(monkeypatch):
    from packages.agents.writer import dimension_writer
    from packages.agents.writer.question_repair import question_repair_context

    detail, service, record = repair_case()
    view, _ = service._begin_evidence_use(
        record, agent="writer", competitor="Example Product", dimension="feature"
    )
    question = {"question_id": "q", "question": "Can visitors own a private compartment?"}
    missing = "Visitors cannot own a private compartment."
    observed = []
    original = dimension_writer.compact_dimension_context

    def compact(*args, **kwargs):
        observed.extend(kwargs.get("support_focus", ()))
        return original(*args, **kwargs)

    monkeypatch.setattr(dimension_writer, "compact_dimension_context", compact)
    question_repair_context(
        view,
        set(view.fact_ids),
        [question],
        [
            dict(
                **question,
                rejected_claims=[dict(text=missing)],
                coverage_failure="Missing original private rule.",
            )
        ],
        [],
        max_bytes=14000,
    )
    assert missing in observed and "Missing original private rule." in observed


def refill_case():
    from types import SimpleNamespace

    from test_literal_non_operation import fact

    scope = (
        "The Basic membership allowance includes exactly two visitors "
        "under the individual workspace scope. "
    )
    quote = (
        scope
        + "This allowance applies to the documented Basic account "
        "and its recorded membership conditions."
    )
    other = (
        "The Standard membership allowance includes exactly four visitors "
        "under the individual workspace scope. "
        "This allowance applies to the documented Standard account "
        "and its recorded membership conditions."
    )
    originals = [
        fact("a", quote=quote, value=[quote, other]),
        fact("b", quote=other, value=[other, quote]),
    ]
    view = SimpleNamespace(competitor="Example Product", dimension="feature", facts=originals)
    question = dict(question_id="q", question="What is the Basic workspace membership allowance?")
    targets = [dict(**question, rejected_claims=[dict(text=quote)], coverage_failure=other)]
    return view, question, targets


def test_repair_refills_actual_merged_slack_with_complete_canonical_support(monkeypatch):
    from packages.agents.writer import dimension_writer
    from packages.agents.writer.question_repair import question_repair_context
    from packages.agents.writer.readable_support import dispatched_span_candidates
    from packages.research.evidence.source_spans import source_span_candidates

    view, question, targets = refill_case()
    original = dimension_writer.compact_dimension_context
    attempts = []

    def compact(*args, **kwargs):
        result = original(*args, **kwargs)
        attempts.append(result[0])
        return result

    monkeypatch.setattr(dimension_writer, "compact_dimension_context", compact)
    improved = False
    for budget in range(1800, 5001, 100):
        attempts.clear()
        context, _ = question_repair_context(
            view, {"a", "b"}, [question], targets, [], max_bytes=budget
        )
        assert len(dimension_writer.compact_prompt_json(context).encode()) <= budget
        assert context["questions"] == [question] and context["repair_targets"] == targets
        assert len(attempts) <= 3

        def sent(payload):
            return {row["id"] for row in payload["evidence_view"]["facts"]}

        first = dispatched_span_candidates(attempts[0], view.facts, sent(attempts[0]))
        final = dispatched_span_candidates(context, view.facts, sent(context))
        if len(final) > len(first):
            assert all(
                span["quote"]
                in [item["quote"] for fact in view.facts for item in source_span_candidates(fact)]
                for span in final.values()
            )
            improved = True
            break
    assert improved, (
        "Separate metadata reservation left actual capacity unused instead of refilling it."
    )


def test_over_budget_refill_is_rejected_without_dropping_original_metadata(monkeypatch):
    from packages.agents.writer import dimension_writer
    from packages.agents.writer.question_repair import question_repair_context

    view, question, targets = refill_case()
    original = dimension_writer.compact_dimension_context
    calls = []

    def compact(*args, **kwargs):
        result, omitted = original(*args, **kwargs)
        calls.append(kwargs["max_bytes"])
        if len(calls) > 1:
            result["diagnostic_padding"] = "x" * 8000
        return result, omitted

    monkeypatch.setattr(dimension_writer, "compact_dimension_context", compact)
    context, _ = question_repair_context(view, {"a", "b"}, [question], targets, [], max_bytes=4000)
    assert len(calls) > 1
    assert "diagnostic_padding" not in context
    assert context["questions"] == [question] and context["repair_targets"] == targets
    assert context["retained_supported_claims"] == [] and context["max_new_atoms"] == 4
    assert len(dimension_writer.compact_prompt_json(context).encode()) <= 4000
