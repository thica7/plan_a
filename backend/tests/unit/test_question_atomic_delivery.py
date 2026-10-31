"""Offline checks for one-question multi-atom delivery and authenticated replay."""

import hashlib
import importlib.util
import json
from datetime import UTC, datetime

import pytest
from claim_review_fixture import expand_prompt_payload, question_plan_response
from claim_review_fixture import supported_review as legacy_supported_review
from pydantic import HttpUrl, TypeAdapter
from test_question_retrieval import research_case
from test_task_support_selection import append_response
from test_writer_question_delivery import service_for

from packages.research.evidence.snapshot import seal_snapshot
from packages.research.question_scope import research_questions
from packages.schema.models import DecisionBrief

TEXTS = [
    "Guests have no personal area.",
    "Guests are invited to one collection at a time.",
    "Guests require an account invitation.",
]
QUESTION = "Example Product：访客有私人区域、能同时加入两个容器、是否需要账户邀请？"


def supported_review(claim):
    row = legacy_supported_review(claim)
    row["support_witnesses"] = [dict(support_index=index, quote=quote)
                                for index, quote in enumerate(claim["support_quotes"])]
    return row


async def atomic_case(texts=TEXTS, question=QUESTION, *, source_qualifiers=None):
    detail, _ = research_case(texts, question=question)
    detail.created_at = detail.updated_at = datetime.now(UTC)
    detail.plan.competitors, detail.plan.dimensions = ["Example Product"], ["feature"]
    detail.plan.decision_brief = DecisionBrief(decision_question=question)
    for source in detail.raw_sources:
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
    if source_qualifiers is not None:
        for source, qualifiers in zip(detail.raw_sources, source_qualifiers, strict=True):
            source.metadata["normalized_fields"][0]["qualifiers"] = qualifiers
    snapshot = seal_snapshot(detail, phase="analysis", canonical_documents={})
    service, record = service_for(detail, task_execution=True)
    _, _, packets = await service._begin_question_evidence_use(
        record, agent="writer", competitor="Example Product", dimension="feature"
    )
    view, use, packets = await service._begin_question_pool_evidence_use(record, packet=packets[0])
    selected = service._writer_segment_context(
        record,
        dict(
            segment_name="dimension:Example Product:feature",
            segment_competitor="Example Product",
            dimension="feature",
            answer_intent="facts",
        ),
        view,
        use,
    )
    from packages.research.evidence.answer_models import AnswerBoundary

    boundaries = [AnswerBoundary.model_validate(b) for b in selected["answer_boundaries"]]
    allowed = {fid for b in boundaries for fid in b.allowed_fact_ids}
    return service, record, snapshot, selected, view, use, packets, boundaries, allowed


def atomic_model(service, seen, *, bad_atom=False, bad_review=False, attempts=1):
    async def model(record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        seen.setdefault(kwargs["name"], []).append(payload)
        if kwargs["name"] == "dimension_question_task_support_selection":
            response = json.dumps(dict(selections=[dict(task_id=task['task_id'], status='selected',
                binding_kind='span', support_refs=[payload['evidence_view']['facts'][0]
                    ['source_span_candidates'][0]['support_ref']]) for task in payload['tasks']]))
        elif kwargs["name"] == "dimension_question_atomic_generation":
            atoms = [
                dict(text=s["quote"], kind="fact", support_refs=[s["support_ref"]])
                for row in payload["evidence_view"]["facts"]
                for s in row.get("source_span_candidates", ())
            ]
            if bad_atom:
                atoms.insert(1, dict(text="Invented claim.", kind="fact", support_refs=["s9999"]))
            if payload.get('task_support_selections'):
                atoms = [dict(text=row['supports'][0]['quote'], kind='fact',
                    support_refs=row['support_refs']) for row in payload['task_support_selections']]
            response = question_plan_response(payload, atoms)
        elif kwargs["name"] == "dimension_question_atomic_review":
            rows = [supported_review(c) for c in payload["claims"]]
            if bad_review and len(seen[kwargs["name"]]) == 1:
                rows[0]["checks"] = []
            reviewed = dict(reviews=rows)
            if payload.get('task_execution_policy') == 'selected-task-atoms-v3':
                reviewed['atomicity'] = [dict(claim_id=c['id'], predicate_count=1, clauses=[dict(
                    quote=c['text'], predicate=payload['task_context']['focus'], task_match=True)])
                    for c in payload['claims']]
            response = json.dumps(reviewed)
        else:
            raise AssertionError(kwargs["name"])
        if payload.get('task_clause_contract'):
            from test_task_clauses import clause_wire_response
            response = json.dumps(clause_wire_response(payload, json.loads(response)))
        return append_response(
            service,
            record,
            kwargs,
            response,
            attempts=attempts if kwargs["name"].endswith("generation") else 1,
        )

    return model


async def execute(case, monkeypatch, *, review_projection_version=3,
                  generation_projection_version=3, **model_options):
    from packages.agents.writer.question_atomic_delivery import execute_question_atomic_delivery

    service, record, _, selected, view, use, packets, boundaries, allowed = case
    seen = {}
    monkeypatch.setattr(service, "_trace_llm_text", atomic_model(service, seen, **model_options))
    result = await execute_question_atomic_delivery(
        service,
        record,
        selected,
        view,
        use,
        research_questions(record.detail, view.competitor, view.dimension),
        packets,
        allowed,
        boundaries,
        (),
        review_projection_version=review_projection_version,
        generation_projection_version=generation_projection_version,
    )
    return result, seen


def test_question_atomic_module_has_an_independent_contract():
    assert importlib.util.find_spec("packages.agents.writer.question_atomic_delivery") is not None


@pytest.mark.asyncio
async def test_one_question_generates_three_independent_atoms_once(monkeypatch):
    from packages.research.evidence.report_claims import audit_report_claims

    case = await atomic_case()
    result, seen = await execute(case, monkeypatch)
    assert len(seen["dimension_question_atomic_generation"]) == 1
    assert len(result["claims"]) == len(result["reviews"]) == 3
    audited = audit_report_claims(
        result["claims"],
        result["reviews"],
        case[4],
        case[7],
        available_facts=case[4].facts,
        review_version=3,
    )
    assert all(c.status == "supported" for c in audited), audited
    assert result["compact"]["question_atomic_contract"] == "question-atomic-delivery-v1"
    assert "question_task_ledger" not in result["compact"]
    assert len(result["compact"]["question_answer_plans"][0]["claim_ids"]) == 3


@pytest.mark.asyncio
async def test_bad_atom_and_review_keep_independently_supported_peers(monkeypatch):
    from packages.research.evidence.report_claims import audit_report_claims

    case = await atomic_case()
    result, _ = await execute(case, monkeypatch, bad_atom=True, bad_review=True)
    assert len(result["claims"]) == 3
    audited = audit_report_claims(
        result["claims"],
        result["reviews"],
        case[4],
        case[7],
        available_facts=case[4].facts,
        review_version=3,
    )
    assert sum(c.status == "supported" for c in audited) == 2


@pytest.mark.asyncio
async def test_eight_atoms_are_all_reviewed_without_a_total_batch_cutoff(monkeypatch):
    texts = [f"Guests are limited to {i + 1} items in category {i}." for i in range(8)]
    question = "Example Product: " + "; ".join(
        f"How many items are allowed in category {i}" for i in range(8)
    ) + "?"
    case = await atomic_case(texts, question=question)
    result, seen = await execute(case, monkeypatch)
    assert len(result["claims"]) == len(result["reviews"]) == 8
    assert len(seen["dimension_question_atomic_review"]) == 8


@pytest.mark.asyncio
async def test_zero_attempt_generation_has_no_citable_claims(monkeypatch):
    case = await atomic_case()
    result, _ = await execute(case, monkeypatch, attempts=0)
    assert not result["claims"]
    assert not result["sent_fact_ids"]
    assert not result["upstream_dependencies"]


@pytest.mark.asyncio
async def test_atomic_receipt_replays_complete_originals_and_claim_reviews(monkeypatch):
    from packages.agents.writer.question_atomic_delivery import replay_atomic_delivery

    case = await atomic_case()
    result, _ = await execute(case, monkeypatch)
    use = next(u for u in case[1].detail.evidence_consumptions if u.id == case[5].id)
    replay = replay_atomic_delivery(case[0], case[1].detail, case[2], use, case[4])
    assert {c.id for c in replay["claims"]} == {c.id for c in result["claims"]}
    assert {r.claim_id for r in replay["reviews"]} == {c.id for c in result["claims"]}
    assert replay["sent_fact_ids"] == result["sent_fact_ids"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "parent",
        "advisory",
        "quote",
        "scope",
        "output",
        "attempt",
        "receipt_output_hash",
        "use",
        "cross_question",
    ],
)
async def test_atomic_replay_rejects_context_transport_and_receipt_tampering(monkeypatch, change):
    from packages.agents.writer.question_atomic_delivery import replay_atomic_delivery

    case = await atomic_case()
    service, record, snapshot, _, view, use, _, _, _ = case
    await execute(case, monkeypatch)
    span = next(
        s for s in record.detail.trace_spans if s.name == "dimension_question_atomic_generation"
    )
    receipt_span = next(
        s for s in record.detail.trace_spans if s.name == "question_atomic_delivery"
    )
    receipt = json.loads(receipt_span.full_output)
    if change in {"parent", "advisory", "quote", "scope", "use", "cross_question"}:
        system, raw = span.full_input.split("\nJSON:\n", 1)
        payload = expand_prompt_payload(json.loads(raw))
        if change == "parent":
            payload["request_context"] = {}
        elif change == "advisory":
            payload["upstream_context_gaps"] = []
        elif change == "quote":
            payload["evidence_view"]["facts"][0]["quote"] = "Invented quote."
        elif change == "scope":
            payload["questions"][0]["question"] += " Another request?"
        elif change == "cross_question":
            payload["questions"][0]["question_id"] = "foreign"
        else:
            payload["consumption_id"] = "wrong-use"
        span.full_input = system + "\nJSON:\n" + json.dumps(payload)
        receipt["dispatches"][0]["full_input_sha256"] = hashlib.sha256(
            span.full_input.encode()
        ).hexdigest()
    elif change == "output":
        span.full_output = "{}"
    elif change == "attempt":
        span.metadata["llm_transport_attempts"] = True
    else:
        receipt["dispatches"][0]["full_output_sha256"] = "wrong"
    receipt_span.full_output = json.dumps(receipt)
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    with pytest.raises((ValueError, RuntimeError)):
        replay_atomic_delivery(service, record.detail, snapshot, use, view)


@pytest.mark.asyncio
async def test_atomic_coverage_has_one_independent_review_and_concrete_answer(monkeypatch):
    from claim_review_fixture import answer_response

    from packages.research.evidence.report_claims import audit_report_claims

    case = await atomic_case(TEXTS[:1], question="Example Product：访客有私人区域吗？")
    service, record, _, _, view, use, _, boundaries, _ = case
    result, seen = await execute(case, monkeypatch)
    audited = audit_report_claims(
        result["claims"],
        result["reviews"],
        view,
        boundaries,
        available_facts=view.facts,
        review_version=3,
    )

    async def answer_model(record, **kwargs):
        assert kwargs["name"] == "dimension_question_atomic_answer_review"
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        seen.setdefault(kwargs["name"], []).append(payload)
        response = answer_response(
            payload,
            dict(
                version=3,
                answers=[
                    dict(
                        question_id=payload["questions"][0]["question_id"],
                        status="answered",
                        claim_ids=[c["id"] for c in payload["claims"]],
                        resolution="direct",
                        conclusion="no",
                        missing_fields=[],
                        reason="The published claim explicitly denies a personal area.",
                    )
                ],
            ),
            relation="explicit_negative",
        )
        return append_response(service, record, kwargs, response)

    monkeypatch.setattr(service, "_trace_llm_text", answer_model)
    from packages.agents.writer.question_atomic_delivery import atomic_answer_coverage
    rows, gaps, _ = await atomic_answer_coverage(service,
        record,
        research_questions(record.detail, view.competitor, view.dimension),
        result["compact"],
        [item.claim for item in audited if item.status == 'supported'],
        view,
        use,
        result["gaps"],
        answer_review_contract='subquestion-premises-v1',
    )
    assert len(seen["dimension_question_atomic_answer_review"]) == 1
    assert rows[0].status == "answered", (rows[0].reason, gaps)
    assert rows[0].conclusion == "no" and rows[0].answer == TEXTS[0]
    assert "dimension_answer_coverage" not in seen


def test_atomic_experiment_requires_its_own_default_off_setting():
    from packages.config import Settings

    assert Settings().writer_question_atomic_enabled is False


@pytest.mark.asyncio
async def test_production_writer_uses_pool_and_binds_atomic_receipt(monkeypatch):
    from claim_review_fixture import answer_response

    from packages.agents.qa.evidence_alignment import audit_dimension_claims

    case = await atomic_case(TEXTS[:1], question="Example Product：访客有私人区域吗？")
    service, record, snapshot, *_ = case
    from dataclasses import replace

    service._settings = replace(service._settings, writer_question_atomic_enabled=True)
    seen = {}
    normal_model = atomic_model(service, seen)

    async def model(record, **kwargs):
        if kwargs["name"] != "dimension_question_atomic_answer_review":
            return await normal_model(record, **kwargs)
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        seen.setdefault(kwargs["name"], []).append(payload)
        if payload.get('task_outcome_contract') == 'task-outcomes-v1':
            response = json.dumps(dict(version=1, task_reviews=[dict(task_id=t['task_id'],
                outcome='no', support_refs=[c['ref'] for c in t['support_choices'] if c['primary']],
                missing_fields=[], reason='The exact task is independently grounded.')
                for t in payload['tasks']]))
            return append_response(service, record, kwargs, response)
        response = answer_response(
            payload,
            dict(
                version=3,
                answers=[
                    dict(
                        question_id=q["question_id"],
                        status="answered",
                        claim_ids=[c["id"] for c in payload["claims"]],
                        resolution="direct",
                        conclusion="no",
                        missing_fields=[],
                        reason="The supported restriction directly denies the request.",
                    )
                    for q in payload["questions"]
                ],
            ),
            relation="explicit_negative",
        )
        return append_response(service, record, kwargs, response)

    monkeypatch.setattr(service, "_trace_llm_text", model)
    await service._real_writer_step(record)
    audit = record.detail.report_dimension_audits[0]
    assert audit.question_atomic_contract == "question-atomic-delivery-v1"
    assert audit.answer_review_contract == "task-outcomes-v1"
    assert audit.question_atomic_receipt_digest
    assert audit.answer_coverage[0].status == "answered"
    assert "否" in record.detail.report_md
    assert not any(s.name == "dimension_task_plan" for s in record.detail.trace_spans)
    assert service._final_qa_producer_verified(record, snapshot)
    assert not audit_dimension_claims(service, record, snapshot, producer_verified=True)
    from packages.agents.writer.question_atomic_delivery import digest

    receipt = next(
        json.loads(s.full_output)
        for s in record.detail.trace_spans
        if s.name == "question_atomic_delivery"
    )
    assert {d["name"] for d in receipt["dispatches"]} == {
        "dimension_question_atomic_generation",
        "dimension_question_atomic_review",
        "dimension_question_atomic_answer_review",
        "dimension_question_task_support_selection",
    }
    assert receipt['task_execution_policy'] == 'selected-task-atoms-v3'
    assert digest(receipt) == audit.question_atomic_receipt_digest
    record.detail.trace_spans = [
        s for s in record.detail.trace_spans if s.name != "question_atomic_delivery"
    ]
    issues = audit_dimension_claims(service, record, snapshot, producer_verified=True)
    assert any(i.metadata["claim_audit_reason"] == "question_atomic_replay_failed" for i in issues)
    record.detail.report_dimension_audits = [
        audit.model_copy(
            update=dict(question_atomic_contract=None, question_atomic_receipt_digest=None)
        )
    ]
    issues = audit_dimension_claims(service, record, snapshot, producer_verified=True)
    assert any(i.metadata["claim_audit_reason"] == "question_atomic_replay_failed" for i in issues)


@pytest.mark.asyncio
async def test_new_atomic_phases_preserve_writer_qa_answer_budget_allocations():
    case = await atomic_case()
    service, record, *_ = case
    assert (
        service._llm_phase(
            "writer",
            "Example Product/feature",
            name="dimension_question_atomic_generation",
            record=record,
        )
        == "writer:Example Product/feature"
    )
    assert (
        service._llm_phase(
            "qa", "Example Product/feature", name="dimension_question_atomic_review", record=record
        )
        == "qa:Example Product/feature"
    )
    assert (
        service._llm_phase(
            "qa",
            "Example Product/feature",
            name="dimension_question_atomic_answer_review",
            record=record,
        )
        == "answer:Example Product/feature"
    )


@pytest.mark.parametrize("text", ["Guests have no private vault.", "A guest has no private vault."])
def test_explicit_have_no_same_object_supports_a_negative_answer(text):
    from test_subquestion_premises import branch, parse

    question = "Does a guest have a private vault?"
    result = parse(question, [dict(id="c", text=text, kind="fact")], [branch(question, ["c"])])
    assert result.status == "answered", result.reason


@pytest.mark.parametrize(
    "text",
    [
        "Guests may have no private vault.",
        "If guests have no private vault, they can use a shared area.",
        "Guests have no private vault if administrators disable private vaults.",
        "Guests might have no private vault.",
        "Guests have no shared vault.",
    ],
)
def test_modal_conditional_or_other_object_have_no_never_proves_unconditional_denial(text):
    from test_subquestion_premises import branch, parse

    question = "Does a guest have a private vault?"
    result = parse(question, [dict(id="c", text=text, kind="fact")], [branch(question, ["c"])])
    assert result.status == "unverified"


@pytest.mark.asyncio
async def test_generation_packs_whole_originals_inside_14k_with_explicit_deferral():
    from packages.agents.writer.dimension_writer import compact_prompt_json
    from packages.agents.writer.question_atomic_delivery import atomic_question_context

    case = await atomic_case(
        [f"Guests follow rule {i}. " + "Canonical complete condition. " * 45 for i in range(12)],
        question="Example Product：访客有哪些规则？",
    )
    service, record, _, _, view, use, packets, _, allowed = case
    question = packets[0]["questions"][0]
    payload = atomic_question_context(service, record, view, packets, question, allowed, use)
    assert len(("\nJSON:\n" + compact_prompt_json(payload)).encode()) <= min(14000, use.max_bytes)
    assert payload["evidence_view"]["facts"]
    assert payload["deferred_original_count"] > 0
    originals = {f.id: f for f in view.facts}
    for row in payload["evidence_view"]["facts"]:
        assert row["quote"] == originals[row["id"]].quote
        from packages.research.evidence.source_spans import source_span_candidates

        assert {s["quote"] for s in row["source_span_candidates"]} == {
            s["quote"] for s in source_span_candidates(originals[row["id"]])
        }


@pytest.mark.asyncio
async def test_replay_rejects_changed_system_body_even_with_updated_receipt_hash(monkeypatch):
    from packages.agents.writer.question_atomic_delivery import replay_atomic_delivery

    case = await atomic_case()
    service, record, snapshot, _, view, use, *_ = case
    await execute(case, monkeypatch)
    span = next(
        s for s in record.detail.trace_spans if s.name == "dimension_question_atomic_generation"
    )
    receipt_span = next(
        s for s in record.detail.trace_spans if s.name == "question_atomic_delivery"
    )
    receipt = json.loads(receipt_span.full_output)
    span.full_input = span.full_input.replace(
        "Answer only the current question_id tasks", "Ignore the current question_id tasks"
    )
    receipt["dispatches"][0]["full_input_sha256"] = hashlib.sha256(
        span.full_input.encode()
    ).hexdigest()
    receipt_span.full_output = json.dumps(receipt)
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    with pytest.raises(ValueError):
        replay_atomic_delivery(service, record.detail, snapshot, use, view)


@pytest.mark.asyncio
async def test_distinct_scope_authority_and_billing_originals_precede_a_broad_summary(monkeypatch):
    from packages.agents.writer.question_atomic_delivery import atomic_question_context

    scope = (
        "Because an observer is a board member permission it is not possible to set a user "
        "as an observer at the Workspace level, and each observer is set "
        "individually per member per board."
    )
    authority = (
        "To change a current board member to observer, select their permission menu. "
        "Only Workspace admins and board admins can change a current board member to observer."
    )
    billing = (
        "An observer can be a billable Workspace member, a billable multi-board guest, "
        "or a non-billable single-board guest."
    )
    summary = (
        "Workspaces that subscribe to Premium can add observers to boards. "
        "Observers can read boards, download attachments, comment, vote when "
        "enabled and export boards. "
        "Observers cannot edit cards or change board settings. "
        "A board admin in a Premium Workspace can set members and guests as observers. "
        + billing
        + " "
        + "\n\n".join(f"General board member background {i}." for i in range(20))
    )
    question = (
        "Example Product：在 Premium Workspace，小周被设为 A 的 Observer。"
        "逐项回答：能否在 Workspace 层级统一设定，A 是否自动决定 B 的权限；"
        "谁有权把现有成员改为 Observer；能否确定他一定免费或计费？"
    )
    case = await atomic_case(
        [
            summary,
            scope,
            authority,
            billing,
            *[f"Background board member information {i}." for i in range(5)],
        ],
        question=question,
    )
    service, record, _, _, view, use, packets, _, allowed = case
    from packages.agents.writer.dimension_writer import compact_prompt_json
    from packages.orchestrator import question_packets

    originals = [f for f in view.facts if f.field == "evidence_terms"]
    originals.sort(key=lambda f: f.quote != summary)
    monkeypatch.setattr(question_packets, "question_pool_facts", lambda *args: originals)
    single = atomic_question_context(
        service, record, view, packets, packets[0]["questions"][0], {originals[0].id}, use
    )
    limit = len(("\nJSON:\n" + compact_prompt_json(single)).encode()) + 256
    bounded_use = use.model_copy(update=dict(max_bytes=min(14000, limit)))
    payload = atomic_question_context(
        service, record, view, packets, packets[0]["questions"][0], allowed, bounded_use
    )
    sent_quotes = {row["quote"] for row in payload["evidence_view"]["facts"]}
    assert {scope, authority, billing} <= sent_quotes


@pytest.mark.asyncio
@pytest.mark.parametrize("broken_phase", ["generation", "review"])
async def test_invalid_json_transport_replays_locally_beside_valid_peers(monkeypatch, broken_phase):
    from packages.agents.writer.question_atomic_delivery import (
        execute_question_atomic_delivery,
        replay_atomic_delivery,
    )

    question = (
        "Example Product：访客有私人区域吗？\nExample Product：访客需要账户邀请吗？"
        if broken_phase == "generation"
        else QUESTION
    )
    case = await atomic_case(question=question)
    service, record, snapshot, selected, view, use, packets, boundaries, allowed = case
    seen, damaged = {}, False
    normal = atomic_model(service, seen)

    async def model(record, **kwargs):
        nonlocal damaged
        if kwargs["name"] == "dimension_question_atomic_" + broken_phase and not damaged:
            damaged = True
            return append_response(service, record, kwargs, "not valid JSON")
        return await normal(record, **kwargs)

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
    )
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    replay = replay_atomic_delivery(service, record.detail, snapshot, use, view)
    assert replay["claims"] == result["claims"] and replay["reviews"] == result["reviews"]
    assert replay["reviews"]


@pytest.mark.asyncio
async def test_exhausted_budget_or_missing_review_never_publishes_an_atom(monkeypatch):
    from dataclasses import replace

    case = await atomic_case()
    service = case[0]
    service._settings = replace(service._settings, run_llm_max_calls=1, run_llm_max_tokens=1000)
    result, seen = await execute(case, monkeypatch)
    assert not seen and not result["claims"] and not result["reviews"]
    assert "claim_execution_budget_exceeded" in result["gaps"]


@pytest.mark.asyncio
async def test_one_original_can_offer_and_use_its_third_complete_span(monkeypatch):
    case = await atomic_case(["\n\n".join(TEXTS)])
    result, seen = await execute(case, monkeypatch)
    choices = seen["dimension_question_atomic_generation"][0]["evidence_view"]["facts"][0][
        "source_span_candidates"
    ]
    assert len(choices) >= 3
    assert TEXTS[2] in {c.text for c in result["claims"]}
    assert any(s.quote == TEXTS[2] for c in result["claims"] for s in c.source_span_bindings)


@pytest.mark.asyncio
async def test_atomic_generation_carries_all_three_advisories_and_exact_parent(monkeypatch):
    from test_writer_artifact_consumption import record_upstream

    from packages.agents.writer.question_atomic_delivery import replay_atomic_delivery

    case = await atomic_case()
    service, record, snapshot, _, view, use, *_ = case
    record_upstream(service, record)
    result, seen = await execute(case, monkeypatch)
    payload = seen["dimension_question_atomic_generation"][0]
    assert all(
        payload.get(key)
        for key in ("upstream_analysis", "comparison_assessment", "reflection_constraints")
    )
    assert payload["request_context"]["parents"][0]["text"] == QUESTION
    assert {d.kind for d in result["upstream_dependencies"]} == {
        "analyst",
        "comparator",
        "reflector",
    }
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    assert replay_atomic_delivery(service, record.detail, snapshot, use, view)["reviews"]


@pytest.mark.asyncio
async def test_no_fact_from_outside_the_unique_use_can_become_a_claim(monkeypatch):
    from packages.agents.writer.question_atomic_delivery import execute_question_atomic_delivery

    case = await atomic_case()
    service, record, _, selected, view, use, packets, boundaries, allowed = case

    async def foreign(record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        response = json.dumps(
            dict(
                question_plans=[
                    dict(
                        question_id=payload["questions"][0]["question_id"],
                        missing_fields=[],
                        atoms=[
                            dict(
                                text="Guests have no personal area.",
                                kind="fact",
                                competitor=view.competitor,
                                dimension=view.dimension,
                                fact_ids=["foreign-fact"],
                                source_ids=["foreign-source"],
                                source_span_ids=["foreign-span"],
                            )
                        ],
                    )
                ]
            )
        )
        return append_response(service, record, kwargs, response)

    monkeypatch.setattr(service, "_trace_llm_text", foreign)
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
    )
    assert not result["claims"] and not result["reviews"]


@pytest.mark.asyncio
@pytest.mark.parametrize("blocker", ["outside_view", "outside_allowed", "user_window", "complete"])
async def test_pool_exception_closure_defers_the_entire_group_before_authorizing_originals(
    monkeypatch, blocker
):
    from test_exception_recovery import ACCESS, AUTH, scoped_pair

    from packages.agents.writer import question_retrieval
    from packages.agents.writer.question_atomic_delivery import atomic_question_context
    from packages.orchestrator.question_packets import question_pool_facts
    from packages.research.evidence.answer_models import AnswerBoundary
    from packages.research.evidence.source_exceptions import source_exception_bindings

    monkeypatch.setattr(question_retrieval, "get_local_provider_from_env", lambda kind: None)
    repeats = {"outside_view": 1800, "outside_allowed": 0, "user_window": 180, "complete": 0}[
        blocker
    ]
    auth = AUTH + ("\n\n" + "Unrelated complete background. " * repeats if repeats else "")
    detail, _ = research_case(
        [ACCESS, auth], question="Example Product: Can removed organization members log in?"
    )
    detail.created_at = detail.updated_at = datetime.now(UTC)
    detail.plan.competitors, detail.plan.dimensions = ["Example Product"], ["feature"]
    for source, original in zip(detail.raw_sources, scoped_pair(), strict=True):
        source.url = TypeAdapter(HttpUrl).validate_python(source.url)
        qualifiers = dict(original.qualifiers)
        qualifiers["source_scope"] = dict(qualifiers["source_scope"], raw_source_id=source.id)
        source.metadata["normalized_fields"][0]["qualifiers"] = qualifiers
    snapshot = seal_snapshot(detail, phase="analysis", canonical_documents={})
    service, record = service_for(detail, task_execution=True)
    _, _, packets = await service._begin_question_evidence_use(
        record, agent="writer", competitor="Example Product", dimension="feature"
    )
    pool = question_pool_facts(detail, snapshot, packets[0])
    assert len(source_exception_bindings(pool)) == 1
    access_id = next(f.id for f in pool if f.quote == ACCESS)
    auth_id = next(f.id for f in pool if f.quote == auth)
    view, use, packets = await service._begin_question_pool_evidence_use(record, packet=packets[0])
    selected = service._writer_segment_context(
        record, dict(segment_competitor=view.competitor, dimension=view.dimension), view, use
    )
    boundaries = [AnswerBoundary.model_validate(b) for b in selected["answer_boundaries"]]
    allowed = {fid for b in boundaries for fid in b.allowed_fact_ids}
    assert access_id in view.fact_ids
    if blocker == "outside_view":
        assert auth_id not in view.fact_ids
    else:
        assert auth_id in view.fact_ids
    if blocker == "outside_allowed":
        allowed.remove(auth_id)
    payload = atomic_question_context(
        service, record, view, packets, packets[0]["questions"][0], allowed, use
    )
    if blocker == "complete":
        assert {row["id"] for row in payload["evidence_view"]["facts"]} == {access_id, auth_id}
        assert payload["source_exception_bindings"] == list(source_exception_bindings(pool))
        assert payload["deferred_original_count"] == payload["deferred_exception_group_count"] == 0
        assert payload["exception_closure_gaps"] == []
        return
    assert not payload["evidence_view"]["facts"], payload["evidence_view"]["facts"]
    assert payload["deferred_original_count"] == len(pool) == 2
    assert payload["deferred_exception_group_count"] == 1
    assert payload["exception_closure_gaps"] == [
        "exception_group_context_budget_exceeded"
        if blocker == "user_window"
        else "exception_partner_outside_generation_view"
    ]


@pytest.mark.parametrize(
    "text",
    [
        "Guests should have no private vault.",
        "Guests will probably have no private vault.",
        "Not all guests have no private vault.",
    ],
)
def test_new_have_no_detection_rejects_obligation_probability_and_nonuniversal_negation(text):
    from test_subquestion_premises import branch, parse

    question = "Does a guest have a private vault?"
    result = parse(question, [dict(id="c", text=text, kind="fact")], [branch(question, ["c"])])
    assert result.status == "unverified"


@pytest.mark.asyncio
async def test_operation_only_forecast_includes_a_nonempty_review_request(monkeypatch):
    from packages.agents.writer.question_atomic_delivery import execute_question_atomic_delivery

    case = await atomic_case(
        ["Guests can read board content."],
        question="Example Product: Can guests read board content?",
    )
    service, record, _, selected, view, use, packets, boundaries, allowed = case

    async def model(record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        if kwargs["name"] == "dimension_question_atomic_generation":
            row = next(r for r in payload["evidence_view"]["facts"] if r["operation_support_refs"])
            response = question_plan_response(
                payload,
                [
                    dict(
                        text="Guests can read board content.",
                        kind="fact",
                        support_refs=[row["operation_support_refs"][0]],
                    )
                ],
            )
        else:
            assert kwargs["name"] == "dimension_question_atomic_review"
            response = json.dumps(dict(reviews=[supported_review(c) for c in payload["claims"]]))
        return append_response(service, record, kwargs, response)

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
    )
    assert len(result["claims"]) == len(result["reviews"]) == 1
    forecast = result["compact"]["question_atomic_budget_forecasts"][0]
    assert forecast["candidate_claim_count"] >= 1
    assert forecast["minimum_reviewed_candidate_count"] == forecast["predicted_review_batches"] == 1
    assert len(forecast["request_envelope_bytes"]) == 3
    assert forecast["admitted"] is True


@pytest.mark.asyncio
async def test_no_legal_candidate_cannot_admit_an_empty_review_chain(monkeypatch):
    case = await atomic_case(
        ["Guests can read board content."],
        question="Example Product: Can guests read board content?",
    )
    monkeypatch.setattr(
        "packages.research.evidence.source_spans.source_span_candidates", lambda fact: ()
    )
    monkeypatch.setattr(
        "packages.research.evidence.operations.operation_observations", lambda *args: ()
    )
    result, seen = await execute(case, monkeypatch)
    forecast = result["compact"]["question_atomic_budget_forecasts"][0]
    assert not seen and not result["claims"] and not result["reviews"]
    assert forecast["admitted"] is False
    assert forecast["minimum_reviewed_candidate_count"] == forecast["predicted_review_batches"] == 0
    assert forecast["failure_reason"] == "question_candidate_support_unavailable"
    assert result["compact"]["question_answer_plans"][0]["reason"] == forecast["failure_reason"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "quote,question,binding_kind",
    [
        (
            "Guests require\nan account invitation.",
            "Example Product: Do guests require an account invitation?",
            "span",
        ),
        (
            "Guests can read\tboard content.",
            "Example Product: Can guests read board content?",
            "operation",
        ),
    ],
)
async def test_forecast_normalizes_claim_display_whitespace_without_changing_support(
    monkeypatch, quote, question, binding_kind
):
    from packages.agents.writer.question_atomic_delivery import (
        execute_question_atomic_delivery,
        replay_atomic_delivery,
    )

    case = await atomic_case([quote], question=question)
    service, record, snapshot, selected, view, use, packets, boundaries, allowed = case
    calls, originals = [], []

    async def model(record, **kwargs):
        calls.append(kwargs["name"])
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        if kwargs["name"] == "dimension_question_atomic_generation":
            row = payload["evidence_view"]["facts"][0]
            assert row["quote"] == quote
            if binding_kind == "span":
                support = next(s for s in row["source_span_candidates"] if s["quote"] == quote)
                ref = support["support_ref"]
                originals.append(support["quote"])
            else:
                ref = row["operation_support_refs"][0]
                originals.append(row["operation_observations"][0]["operation_quote"])
            response = question_plan_response(
                payload, [dict(text=" ".join(quote.split()), kind="fact", support_refs=[ref])]
            )
        else:
            assert kwargs["name"] == "dimension_question_atomic_review"
            assert payload["claims"][0]["support_quotes"] == originals
            response = json.dumps(dict(reviews=[supported_review(c) for c in payload["claims"]]))
        return append_response(service, record, kwargs, response)

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
    )
    assert calls == ["dimension_question_atomic_generation", "dimension_question_atomic_review"]
    assert len(result["claims"]) == len(result["reviews"]) == 1
    forecast = result["compact"]["question_atomic_budget_forecasts"][0]
    assert forecast["candidate_claim_count"] >= 1
    assert forecast["minimum_reviewed_candidate_count"] == forecast["predicted_review_batches"] == 1
    assert forecast["admitted"] is True
    claim = result["claims"][0]
    assert claim.text == " ".join(quote.split())
    assert (
        [claim.operation_binding.operation_quote]
        if claim.operation_binding
        else [span.quote for span in claim.source_span_bindings]
    ) == originals
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    assert replay_atomic_delivery(service, record.detail, snapshot, use, view)["claims"] == [claim]


@pytest.mark.asyncio
async def test_forecast_scans_past_eight_invalid_display_candidates_to_a_legal_complete_span(
    monkeypatch,
):
    from packages.agents.writer.question_atomic_delivery import execute_question_atomic_delivery

    target = "Guests require an account invitation."
    quote = "\n\n".join([*[f"Guests follow invitation guide #{i}." for i in range(8)], target])
    case = await atomic_case(
        [quote], question="Example Product: Do guests require an account invitation?"
    )
    service, record, _, selected, view, use, packets, boundaries, allowed = case
    calls = []

    async def model(record, **kwargs):
        calls.append(kwargs["name"])
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        if kwargs["name"] == "dimension_question_atomic_generation":
            row = payload["evidence_view"]["facts"][0]
            assert row["quote"] == quote
            assert len(row["source_span_candidates"]) == 9
            support = next(
                span for span in row["source_span_candidates"] if span["quote"] == target
            )
            response = question_plan_response(
                payload, [dict(text=target, kind="fact", support_refs=[support["support_ref"]])]
            )
        else:
            assert kwargs["name"] == "dimension_question_atomic_review"
            assert payload["claims"][0]["support_quotes"] == [target]
            response = json.dumps(dict(reviews=[supported_review(c) for c in payload["claims"]]))
        return append_response(service, record, kwargs, response)

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
    )
    assert calls == ["dimension_question_atomic_generation", "dimension_question_atomic_review"]
    assert len(result["claims"]) == len(result["reviews"]) == 1
    assert result["claims"][0].source_span_bindings[0].quote == target
    forecast = result["compact"]["question_atomic_budget_forecasts"][0]
    assert forecast["candidate_claim_count"] >= 1
    assert forecast["minimum_reviewed_candidate_count"] == forecast["predicted_review_batches"] == 1
    assert forecast["admitted"] is True


def active_atomic_budget(service, record, *, calls=6, tokens_used=22848, final_calls=5):
    """Anonymous live-checkpoint shape; retain original global and final floors."""
    from dataclasses import replace

    service._settings = replace(
        service._settings,
        run_llm_max_calls=24,
        run_llm_max_tokens=80000,
        run_llm_max_cost_usd=0.25,
        run_llm_max_repairs=0,
        llm_max_output_tokens=1600,
    )
    budget = service._run_llm_budget(record)
    for phase in budget.delivery_reserves:
        if phase.startswith(("collector:", "analyst:", "comparator:", "reflector:")):
            budget.finish_delivery(phase)
    budget.calls, budget.tokens_used = calls, tokens_used
    budget.delivery_reserves["final_qa:run"] = 11995
    budget.delivery_call_reserves["final_qa:run"] = final_calls
    assert budget.delivery_reserves["answer:Example Product/feature"] == 12000
    assert budget.delivery_reserves["writer:Example Product/feature"] == 0
    assert budget.delivery_reserves["qa:Example Product/feature"] == 0
    return budget


def anonymous_live_envelopes(service, record):
    from packages.agents.writer import question_atomic_delivery as atomic

    requests = []
    for name, agent, size in (
        (atomic.GENERATION_NAME, "writer", 15909),
        (atomic.REVIEW_NAME, "qa", 11196),
        (atomic.ANSWER_NAME, "qa", 16112),
    ):
        system = atomic.atomic_system(
            name, record.detail.output_language,
            review_projection_version=3, generation_projection_version=3,
        )
        user = "x" * (size - len(system.encode()) - 2)
        assert len(user.encode()) <= 14000
        requests.append((name, agent, system, user, 1600))
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("calls,tokens,final_calls", [(6, 22848, 5), (7, 24224, 3)])
async def test_live_checkpoint_current_requests_run_despite_nonbinding_future_forecast(
    monkeypatch, calls, tokens, final_calls
):
    import httpx
    from claim_review_fixture import answer_response

    from packages.agents.writer import question_atomic_delivery as atomic
    from packages.llm import DoubaoClient
    from packages.research.evidence.report_claims import audit_report_claims

    case = await atomic_case(TEXTS[:1], question="Example Product: Do guests have a personal area?")
    service, record, snapshot, selected, view, use, packets, boundaries, allowed = case
    budget = active_atomic_budget(
        service, record, calls=calls, tokens_used=tokens, final_calls=final_calls
    )
    # The production dimension entry stores these before generating or replaying.
    record.detail.report_answer_boundaries = list(boundaries)
    scope = "Example Product/feature"
    requests = anonymous_live_envelopes(service, record)
    for name, agent, system, user, output in requests:
        assert (
            service._llm_request_admission_error(
                record,
                agent=agent,
                subagent=scope,
                name=name,
                system=system,
                user=user,
                max_output_tokens=output,
            )
            is None
        )
    assert not atomic._chain_admissible(service, record, scope, requests)
    # Isolate the policy from unknown future model atoms. The preceding real
    # envelopes establish the 83–84k boundary; no predicted usage is charged.
    monkeypatch.setattr(atomic, "_chain_admissible", lambda *args: False)
    from dataclasses import replace

    service._llm = DoubaoClient(
        replace(
            service._settings,
            demo_mode=False,
            ark_api_key="offline-test",
            ark_model="offline-test",
            ark_base_url="https://example.invalid",
            llm_max_retries=0,
        )
    )
    transported = []

    async def post(url, payload, headers):
        system, user = [row["content"] for row in payload["messages"]]
        body = expand_prompt_payload(json.loads(user.split("\nJSON:\n", 1)[1]))
        name = next(
            name
            for name in (atomic.GENERATION_NAME, atomic.REVIEW_NAME, atomic.ANSWER_NAME)
            if system in {
                atomic.atomic_system(name, record.detail.output_language,
                    review_projection_version=3, generation_projection_version=4,
                    answer_review_contract=contract)
                for contract in ('subquestion-premises-v1', 'subquestion-premises-v2',
                                 'subquestion-premises-v3', 'subquestion-premises-v4',
                                 'subquestion-premises-v5')
            }
        )
        transported.append(name)
        if name == atomic.GENERATION_NAME:
            span = body["evidence_view"]["facts"][0]["source_span_candidates"][0]
            response = question_plan_response(
                body,
                [
                    dict(
                        text=TEXTS[0],
                        kind="fact",
                        support_refs=[span["support_ref"]],
                    )
                ],
            )
        elif name == atomic.REVIEW_NAME:
            response = json.dumps(dict(reviews=[supported_review(c) for c in body["claims"]]))
        else:
            response = answer_response(
                body,
                dict(
                    version=3,
                    answers=[
                        dict(
                            question_id=body["questions"][0]["question_id"],
                            status="answered",
                            claim_ids=[c["id"] for c in body["claims"]],
                            resolution="direct",
                            conclusion="no",
                            missing_fields=[],
                            reason="The reviewed source explicitly denies a personal area.",
                        )
                    ],
                ),
                relation="explicit_negative",
            )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": response}}],
                "usage": {"prompt_tokens": 500, "completion_tokens": 50},
            },
        )

    monkeypatch.setattr(service._llm, "_post_chat_completion", post)
    result = await atomic.execute_question_atomic_delivery(
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
        answer_review_contract="subquestion-premises-v2",
        generation_projection_version=4,
    )
    audited = audit_report_claims(
        result["claims"],
        result["reviews"],
        view,
        boundaries,
        available_facts=view.facts,
        review_version=3,
    )
    assert len(audited) == 1 and audited[0].status == "supported"
    answers, _, _ = await atomic.atomic_answer_coverage(service,
        record, packets[0]["questions"], result["compact"], [a.claim for a in audited], view, use,
        result["gaps"], answer_review_contract='subquestion-premises-v2',
    )
    assert answers[0].status == "answered" and answers[0].answer == TEXTS[0]
    assert transported == [atomic.GENERATION_NAME, atomic.REVIEW_NAME, atomic.ANSWER_NAME]
    assert (budget.calls, budget.tokens_used, budget.tokens_reserved) == (
        calls + 3,
        tokens + 1650,
        0,
    )
    assert budget.delivery_reserves["final_qa:run"] == 11995
    assert "final_qa:run" not in budget.delivery_finished
    forecast = result["compact"]["question_atomic_budget_forecasts"][0]
    assert forecast["admitted"] and not forecast["future_chain_admitted"]
    diagnostics = [
        json.loads(s.full_output)
        for s in record.detail.trace_spans
        if s.name == "question_atomic_budget_preflight"
    ]
    assert [d["current_request"]["name"] for d in diagnostics] == transported
    assert all(d["version"] == 2 and d["current_request"]["admitted"] for d in diagnostics)
    assert all(d["all_atoms_delivery_guaranteed"] is False for d in diagnostics)
    spans = [s for s in record.detail.trace_spans if s.kind == "llm"]
    assert all(s.metadata["llm_transport_attempts"] == 1 for s in spans)
    assert [d["current_request"]["full_input_sha256"] for d in diagnostics] == [
        hashlib.sha256(s.full_input.encode()).hexdigest() for s in spans
    ]
    use = next(u for u in record.detail.evidence_consumptions if u.id == use.id)
    assert (
        len(atomic.replay_atomic_delivery(service, record.detail, snapshot, use, view)["reviews"])
        == 1
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "limit,reason",
    [
        ("tokens", "run_llm_token_budget_exhausted"),
        ("calls", "run_llm_call_budget_exhausted"),
        ("cost", "run_llm_cost_budget_exhausted"),
        ("protection", "run_llm_budget_reserved_for_delivery"),
        ("reserved", "run_llm_budget_reserved_for_delivery"),
        ("repair", "run_llm_repair_budget_exhausted"),
    ],
)
async def test_current_atomic_generation_gate_preserves_real_limits(monkeypatch, limit, reason):
    from types import SimpleNamespace

    case = await atomic_case(TEXTS[:1], question="Example Product: Do guests have a personal area?")
    service, record, *_ = case
    budget = active_atomic_budget(service, record)
    if limit == "tokens":
        budget.tokens_used = 80000
    elif limit == "calls":
        budget.calls = 24
    elif limit == "cost":
        budget.cost_used_usd = 0.25
    elif limit == "protection":
        budget.tokens_used = 80000 - 12000 - 11995 - 1000
    elif limit == "reserved":
        budget.tokens_used, budget.tokens_reserved = 40000, 20000
    else:
        record.pending_graph_redo = SimpleNamespace()
    before = (budget.calls, budget.tokens_used, budget.tokens_reserved, budget.cost_used_usd)
    result, seen = await execute(case, monkeypatch)
    assert not seen and not result["claims"] and not result["reviews"]
    assert (
        budget.calls,
        budget.tokens_used,
        budget.tokens_reserved,
        budget.cost_used_usd,
    ) == before
    diagnostic = json.loads(
        next(
            s.full_output
            for s in record.detail.trace_spans
            if s.name == "question_atomic_budget_preflight"
        )
    )
    assert diagnostic["current_request"]["reason"] == reason
    assert diagnostic["current_request"]["admitted"] is False
    assert diagnostic["budget"]["tokens_reserved"] == before[2]
    assert diagnostic["budget"]["protected_tokens"] == 23995
    assert budget.delivery_reserves["final_qa:run"] == 11995


@pytest.mark.asyncio
async def test_current_review_exhaustion_after_real_generation_leaves_claim_unpublished(
    monkeypatch,
):
    from dataclasses import replace

    import httpx

    from packages.agents.writer import question_atomic_delivery as atomic
    from packages.llm import DoubaoClient
    from packages.research.evidence.report_claims import audit_report_claims

    case = await atomic_case(TEXTS[:1], question="Example Product: Do guests have a personal area?")
    service, record, _, selected, view, use, packets, boundaries, allowed = case
    budget = active_atomic_budget(service, record)
    service._llm = DoubaoClient(
        replace(
            service._settings,
            demo_mode=False,
            ark_api_key="offline-test",
            ark_model="offline-test",
            ark_base_url="https://example.invalid",
            llm_max_retries=0,
        )
    )
    transported = []

    async def post(url, payload, headers):
        system, user = [row["content"] for row in payload["messages"]]
        assert system == atomic.atomic_system(
            atomic.GENERATION_NAME, record.detail.output_language,
            review_projection_version=3, generation_projection_version=4,
        )
        transported.append(atomic.GENERATION_NAME)
        body = expand_prompt_payload(json.loads(user.split("\nJSON:\n", 1)[1]))
        span = body["evidence_view"]["facts"][0]["source_span_candidates"][0]
        response = question_plan_response(
            body,
            [
                dict(
                    text=TEXTS[0],
                    kind="fact",
                    support_refs=[span["support_ref"]],
                )
            ],
        )
        # A concurrent spender can remove headroom after generation admission.
        # Its state change does not consume the protected final allowances.
        budget.tokens_used = 80000 - 12000 - 11995 - 1000
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": response}}],
                "usage": {"prompt_tokens": 500, "completion_tokens": 50},
            },
        )

    monkeypatch.setattr(service._llm, "_post_chat_completion", post)
    result = await atomic.execute_question_atomic_delivery(
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
        generation_projection_version=4,
    )
    assert transported == [atomic.GENERATION_NAME]
    assert len(result["claims"]) == 1 and not result["reviews"]
    audited = audit_report_claims(
        result["claims"],
        result["reviews"],
        view,
        boundaries,
        available_facts=view.facts,
        review_version=3,
    )
    assert not any(c.status == "supported" for c in audited)
    diagnostic = [
        json.loads(s.full_output)
        for s in record.detail.trace_spans
        if s.name == "question_atomic_budget_preflight"
    ]
    assert [d["current_request"]["name"] for d in diagnostic] == [
        atomic.GENERATION_NAME,
        atomic.REVIEW_NAME,
    ]
    assert diagnostic[-1]["current_request"]["reason"] == "run_llm_budget_reserved_for_delivery"
    assert budget.delivery_reserves["final_qa:run"] == 11995
    assert "final_qa:run" not in budget.delivery_finished


@pytest.mark.asyncio
async def test_current_answer_gate_rejects_exhaustion_before_calling_transport(monkeypatch):
    from packages.agents.writer import question_atomic_delivery as atomic
    from packages.research.evidence.report_claims import audit_report_claims

    case = await atomic_case(TEXTS[:1], question="Example Product: Do guests have a personal area?")
    service, record, _, _, view, use, packets, boundaries, _ = case
    budget = active_atomic_budget(service, record)
    result, seen = await execute(case, monkeypatch)
    audited = audit_report_claims(
        result["claims"],
        result["reviews"],
        view,
        boundaries,
        available_facts=view.facts,
        review_version=3,
    )
    budget.calls = 24
    answers, gaps, _ = await service._dimension_question_coverage(
        record, packets[0]["questions"], result["compact"], audited, view, use, result["gaps"]
    )
    assert atomic.ANSWER_NAME not in seen
    assert answers[0].status == "unverified"
    assert "answer_semantic_review_unavailable" in gaps
    diagnostic = [
        json.loads(s.full_output)
        for s in record.detail.trace_spans
        if s.name == "question_atomic_budget_preflight"
    ][-1]
    assert diagnostic["current_request"]["name"] == atomic.ANSWER_NAME
    assert diagnostic["current_request"]["reason"] == "run_llm_call_budget_exhausted"


@pytest.mark.asyncio
async def test_forecast_oversize_review_does_not_veto_generation_but_actual_review_keeps_cap(
    monkeypatch,
):
    from packages.agents.writer import dimension_writer

    case = await atomic_case(TEXTS[:1], question="Example Product: Do guests have a personal area?")
    original = dimension_writer.review_payload

    def oversize_review(*args, **kwargs):
        # A synthetic full review payload exercises the unchanged 14k user cap.
        result = original(*args, **kwargs)
        result["complete_review_context"] = "x" * 14001
        return result

    monkeypatch.setattr(dimension_writer, "review_payload", oversize_review)
    result, seen = await execute(case, monkeypatch)
    assert len(seen["dimension_question_atomic_generation"]) == 1
    assert len(result["claims"]) == 1 and not result["reviews"]
    assert "claim_review_context_budget_exceeded" in result["gaps"]
