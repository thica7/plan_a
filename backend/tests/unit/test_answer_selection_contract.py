"""Anonymous examples for selecting and replaying published answer claims."""

import json
from claim_review_fixture import answer_response

from claim_review_fixture import expand_prompt_payload, question_plan_response

import pytest

from packages.agents.writer.answer_coverage import (
    coverage_resolution_reasons,
    parse_answer_coverage,
)
from packages.research.evidence.answer_coverage_models import ReportAnswerCoverage


QUESTION = {"question_id": "q", "question": "Can guests access documents?"}


def selection(**updates):
    return {
        "question_id": "q",
        "status": "answered",
        "claim_ids": ["c1"],
        "reason": "The selected published rule answers this request.",
        "resolution": "direct",
        "conclusion": "yes",
        "missing_fields": [],
        **updates,
    }


def parse(rows, claims, *, version=2, questions=(QUESTION,), supported=None):
    payload = {"answers": rows}
    if version is not None:
        payload["version"] = version
    return parse_answer_coverage(
        json.dumps(payload), questions,
        {claim["id"] for claim in claims} if supported is None else supported,
        claims=claims,
    )


def test_selection_materializes_every_complete_claim_in_selected_order():
    claims = [
        {"id": "c1", "text": "Guests can access only documents shared directly with them."},
        {"id": "c2", "text": "Guests must sign in before accessing documents on paid plans."},
    ]
    result = parse([selection(claim_ids=["c2", "c1"])], claims)[0]
    assert result.status == "answered"
    assert result.answer == claims[1]["text"] + "\n" + claims[0]["text"]
    assert result.claim_ids == ("c2", "c1")
    assert [(span.claim_id, span.quote) for span in result.evidence_spans] == [
        (claim["id"], claim["text"]) for claim in reversed(claims)
    ]
    assert not coverage_resolution_reasons(result, claims)


@pytest.mark.parametrize("extra", [
    {"answer": "Guests can access all documents without signing in."},
    {"evidence_spans": [{"claim_id": "c1", "quote": "Guests can access"}]},
    {"question": "Can guests access everything?"},
    {"basis_snapshot_id": "other-snapshot"},
    {"binding_version": 2},
])
def test_selection_rejects_model_prose_fragments_and_server_identity(extra):
    claims = [{"id": "c1", "text": "Guests can access invited documents after signing in."}]
    result = parse([selection(**extra)], claims)[0]
    assert result.status == "unverified"
    assert not result.claim_ids and not result.answer and not result.evidence_spans


@pytest.mark.parametrize("ids,supported", [
    (["c1", "unknown"], {"c1"}),
    (["c1", "c1"], {"c1"}),
    ([], {"c1"}),
    (["c1"], set()),
])
def test_selection_rejects_invalid_ids_without_silently_filtering(ids, supported):
    result = parse(
        [selection(claim_ids=ids)],
        [{"id": "c1", "text": "Guests can access invited documents."}],
        supported=supported,
    )[0]
    assert result.status == "unverified"
    assert not result.claim_ids and not result.answer and not result.evidence_spans


def test_selection_requires_the_actual_published_text_for_every_id():
    result = parse([selection(claim_ids=["c1", "c2"])], [
        {"id": "c1", "text": "Guests can access invited documents."},
    ], supported={"c1", "c2"})[0]
    assert result.status == "unverified" and not result.claim_ids


def test_selection_keeps_other_questions_when_one_row_is_invalid():
    claims = [{"id": "c1", "text": "Guests can access invited documents."}]
    questions = [QUESTION, {**QUESTION, "question_id": "other"}]
    result = parse([
        selection(claim_ids=["c1", "unknown"]), selection(question_id="other"),
    ], claims, questions=questions)
    assert [row.status for row in result] == ["unverified", "answered"]


def padded_claim(claim_id, length):
    prefix = "Guests can access invited documents. "
    return {"id": claim_id, "text": prefix + "x" * (length - len(prefix))}


@pytest.mark.parametrize("lengths,expected", [
    ([600], "answered"),
    ([601], "unverified"),
    ([599, 600], "answered"),
    ([600, 600], "unverified"),
])
def test_selection_preserves_full_text_or_rejects_capacity_overflow(lengths, expected):
    claims = [padded_claim(f"c{i}", length) for i, length in enumerate(lengths)]
    result = parse([selection(claim_ids=[claim["id"] for claim in claims])], claims)[0]
    assert result.status == expected
    if expected == "answered":
        assert result.answer == "\n".join(claim["text"] for claim in claims)
        assert [span.quote for span in result.evidence_spans] == [claim["text"] for claim in claims]
    else:
        assert not result.claim_ids and not result.answer and not result.evidence_spans


@pytest.mark.parametrize("count,expected", [(8, "answered"), (9, "unverified")])
def test_selection_does_not_trim_the_selected_claim_count(count, expected):
    claims = [{"id": f"c{i}", "text": "Guests can access invited documents."} for i in range(count)]
    result = parse([selection(claim_ids=[claim["id"] for claim in claims])], claims)[0]
    assert result.status == expected
    assert len(result.claim_ids) == (count if expected == "answered" else 0)


@pytest.mark.parametrize("version", [True, 2.0, 3.0, "2", "3", 1, 999])
def test_selection_requires_the_exact_supported_integer_version(version):
    result = parse([selection()], [{"id": "c1", "text": "Guests can access documents."}], version=version)[0]
    assert result.status == "unverified"


@pytest.mark.parametrize("text", [
    "该功能不包含在 Starter 套餐中。",
    "该功能未包含在 Starter 套餐中。",
    "Starter 套餐不含该功能。",
    "The feature is not included in the Starter plan.",
])
def test_complete_negative_inclusion_claim_is_a_resolving_answer(text):
    result = parse([selection(conclusion="no")], [{"id": "c1", "text": text}],
        questions=({"question_id": "q", "question": "Does the Starter plan include this feature?"},))[0]
    assert result.status == "answered"
    assert result.answer == text


def test_selection_still_rejects_unrelated_objects_and_roles():
    for text in ("Guests can access folders.", "Editors can access documents."):
        result = parse([selection()], [{"id": "c1", "text": text}])[0]
        assert result.status == "unverified"


def test_legacy_missing_span_does_not_discard_only_the_unbound_id():
    claims = [
        {"id": "c1", "text": "Guests can access invited documents."},
        {"id": "c2", "text": "Guests must sign in to access documents."},
    ]
    result = parse([selection(
        claim_ids=["c1", "c2"], answer="Guests can access invited documents after signing in.",
        evidence_spans=[{"claim_id": "c1", "quote": claims[0]["text"]}],
    )], claims, version=None)[0]
    assert result.status == "unverified" and not result.claim_ids


def test_legacy_response_cannot_claim_the_server_binding_version():
    text = "Guests can access invited documents."
    result = parse([selection(
        answer=text, evidence_spans=[{"claim_id": "c1", "quote": text}], binding_version=2,
    )], [{"id": "c1", "text": text}], version=None)[0]
    assert result.status == "unverified" and not result.claim_ids


def test_live_parser_requires_v2_while_legacy_reading_remains_available():
    text = "Guests can access invited documents."
    claims = [{"id": "c1", "text": text}]
    response = json.dumps({"answers": [selection(
        answer=text, evidence_spans=[{"claim_id": "c1", "quote": text}],
    )]})
    assert parse_answer_coverage(response, (QUESTION,), {"c1"}, claims=claims)[0].status == "answered"
    result = parse_answer_coverage(response, (QUESTION,), {"c1"}, claims=claims, require_v2=True)[0]
    assert result.status == "unverified" and not result.claim_ids


def test_selection_binding_is_replayed_after_serialization():
    claims = [{"id": "c1", "text": "Guests can access invited documents after signing in."}]
    result = parse([selection()], claims)[0]
    assert result.status == "answered"
    persisted = ReportAnswerCoverage.model_validate_json(result.model_dump_json())
    assert persisted.binding_version == 2
    assert not coverage_resolution_reasons(persisted, claims)
    changed = persisted.model_copy(update={"answer": "Guests can access all documents without signing in."})
    assert coverage_resolution_reasons(changed, claims)
    missing = persisted.model_copy(update={"evidence_spans": ()})
    assert coverage_resolution_reasons(missing, claims)


def test_selection_replay_rejects_reordered_spans_and_changed_claim_ids():
    claims = [
        {"id": "c1", "text": "Guests can access invited documents."},
        {"id": "c2", "text": "Guests must sign in before accessing documents."},
    ]
    result = parse([selection(claim_ids=["c1", "c2"])], claims)[0]
    assert result.status == "answered"
    reordered = result.model_copy(update={"evidence_spans": tuple(reversed(result.evidence_spans))})
    changed = result.model_copy(update={"claim_ids": ("c1",)})
    assert "answer_selection_binding_invalid" in coverage_resolution_reasons(reordered, claims)
    assert "answer_selection_binding_invalid" in coverage_resolution_reasons(changed, claims)


def test_legacy_default_does_not_change_saved_record_shape():
    from packages.research.evidence.report_claims import ReportDimensionAudit

    record = ReportAnswerCoverage(**QUESTION, status="unverified", reason="No reviewed claims.")
    assert "binding_version" not in record.model_dump(mode="json")
    audit = ReportDimensionAudit(competitor="Product A", dimension="feature", consumption_id="use")
    assert "answer_binding_version" not in audit.model_dump(mode="json")


@pytest.mark.asyncio
@pytest.mark.parametrize("coverage_mode", ["selection", "legacy", "stripped"])
async def test_writer_publishes_bound_plan_rules_and_final_qa_rejects_changed_answer(monkeypatch, coverage_mode):
    from pydantic import HttpUrl, TypeAdapter
    from claim_review_fixture import supported_review
    from test_run_evidence_snapshot import make_detail
    from test_stage_evidence_views import FixedTime

    from packages.agents.qa.evidence_alignment import audit_dimension_claims
    from packages.agents.writer.dimension_writer import render_dimension_report
    from packages.config import Settings
    from packages.memory import KBCache, RunJournal
    from packages.orchestrator.checkpointer import GraphCheckpointer
    from packages.orchestrator.service import RunRecord, RunService
    from packages.research.evidence.snapshot import seal_snapshot
    from packages.schema.models import DecisionBrief
    from packages.skills.registry import SkillRegistry

    monkeypatch.setattr("packages.research.evidence.views.datetime", FixedTime)
    detail = make_detail()
    detail.plan.competitors = ["Product A"]
    detail.plan.dimensions = ["feature"]
    detail.plan.decision_brief = DecisionBrief(decision_question=(
        "Product A: Can guests edit and comment on boards on the paid plan "
        "when the board is shared publicly?"
    ))
    source = detail.raw_sources[0]
    source.dimension = "feature"
    source.url = TypeAdapter(HttpUrl).validate_python("https://product-a.example/permissions")
    source.metadata.pop("market", None)
    source.metadata["source_material_level"] = "full_source"
    quotes = [
        "Guests can edit boards on paid plans when the board is shared publicly.",
        "Guests can comment on boards on paid plans when the board is shared publicly.",
    ]
    source.metadata["normalized_fields"] = [
        {
            "kind": "feature", "competitor": "Product A", "dimension": "feature",
            "slot": f"permission_{index}", "support_level": "documented", "confidence": 0.8,
            "evidence_terms": [quote], "evidence_quote": quote,
            "evidence_item_ids": [f"permission-{index}"],
        }
        for index, quote in enumerate(quotes)
    ]
    service = RunService(
        SkillRegistry.from_default_path(), Settings(demo_mode=True),
        journal=RunJournal.in_memory(), kb_cache=KBCache.in_memory(),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    record = RunRecord(detail)
    service._runs[detail.id] = record
    seal_snapshot(detail, phase="analysis", canonical_documents={})
    writes = []

    async def model(record, **kwargs):
        payload = expand_prompt_payload(json.loads(kwargs["user"].split("\nJSON:\n", 1)[1]))
        if kwargs["name"] == "dimension_claim_review":
            return json.dumps({"reviews": [supported_review(claim) for claim in payload["claims"]]})
        if kwargs["name"] in {"dimension_answer_coverage", "dimension_answer_review"}:
            answers = [selection(
                question_id=question["question_id"],
                claim_ids=[claim["id"] for claim in payload["claims"]],
            ) for question in payload["questions"]]
            if coverage_mode == "legacy":
                for answer in answers:
                    answer["answer"] = "\n".join(claim["text"] for claim in payload["claims"])
                    answer["evidence_spans"] = [
                        {"claim_id": claim["id"], "quote": claim["text"]} for claim in payload["claims"]
                    ]
                return json.dumps({"answers": answers})
            return answer_response(payload, {"version": 3, "answers": answers})
        assert kwargs["name"] == "dimension_claim_writer"
        writes.append(kwargs["system"])
        drafts = []
        for fact in payload["evidence_view"]["facts"]:
            candidate = next(row for row in fact["operation_observations"]
                             if row["operation"] in {"edit", "comment"})
            drafts.append({
                "text": fact["quote"], "kind": "fact", "competitor": "Product A",
                "dimension": "feature", "fact_ids": [fact["id"]],
                "source_ids": [fact["source_id"]], "observation_id": candidate["observation_id"],
            })
        return question_plan_response(payload, drafts)

    monkeypatch.setattr(service, "_trace_llm_text", model)
    await service._real_writer_step(record)
    audit = detail.report_dimension_audits[0]
    audit = type(audit).model_validate_json(audit.model_dump_json())
    assert audit.answer_binding_version == 3
    assert {item.claim.text for item in audit.claims if item.status == "supported"} == set(quotes), (
        audit.gaps, [(item.status, item.rule_reasons) for item in audit.claims],
    )
    assert {item.claim.operation_binding.operation for item in audit.claims} == {"edit", "comment"}
    coverage = audit.answer_coverage[0]
    if coverage_mode == "legacy":
        assert coverage.status == "unverified" and not coverage.claim_ids
        return
    assert coverage.status == "answered" and coverage.binding_version == 3
    assert set(coverage.answer.splitlines()) == set(quotes)
    assert writes and "Prioritize question-resolving role, plan, login and access restrictions" in writes[0]
    assert "Write edit and comment permission rules as separate claims" in writes[0]
    snapshot = service._current_evidence_snapshot(record)
    assert not audit_dimension_claims(service, record, snapshot, producer_verified=True)

    updates = {"answer": "Guests can edit and comment on all boards on every plan."}
    if coverage_mode == "stripped":
        updates["binding_version"] = None
    changed = coverage.model_copy(update=updates)
    detail.report_dimension_audits = [audit.model_copy(update={"answer_coverage": (changed,)})]
    detail.report_md = render_dimension_report(detail, detail.report_dimension_audits, snapshot=snapshot)
    issues = audit_dimension_claims(service, record, snapshot, producer_verified=True)
    assert any(issue.metadata.get("claim_audit_reason") == "answer_coverage_incomplete" for issue in issues)


def test_v3_is_legal_for_new_selection_but_require_v2_keeps_its_old_meaning():
    claims = [{'id': 'c1', 'text': 'Guests can access documents.'}]
    assert parse([selection()], claims, version=3)[0].binding_version == 3
    result = parse_answer_coverage(json.dumps({'version': 3, 'answers': [selection()]}),
        [QUESTION], {'c1'}, claims=claims, require_v2=True)[0]
    assert result.status == 'unverified'
