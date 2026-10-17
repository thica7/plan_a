import json
from types import SimpleNamespace

import pytest

from packages.research.models import EvidenceItem, ResearchBrief


def brief(*questions):
    return ResearchBrief(
        run_id="run",
        topic="General feature research",
        competitor="Example Suite",
        dimension="feature",
        questions=[
            {"question_id": f"q{index}", "question": question}
            for index, question in enumerate(questions, 1)
        ],
    )


def evidence(identity="e1", **changes):
    quote = "Guests can read invited channels only after signing in."
    return EvidenceItem(
        **(
            dict(
                id=identity,
                competitor="Example Suite",
                dimension="feature",
                field="semantic_capability_access",
                quote=quote,
                value={
                    "status": "documented",
                    "evidence_terms": [quote],
                    "conditions": ["Only invited channels are accessible."],
                    "operations": [{"role": "Guest", "access_scope": "invited channels"}],
                },
                status="accepted",
                source_candidate_id="candidate",
                captured_page_id="page",
                source_url="https://example.test/docs/access",
            )
            | changes
        )
    )


def assessment(*rows):
    return {
        "questions": [
            dict(
                question_id="q1",
                status="candidate",
                evidence_ids=["e1"],
                missing_fields=[],
                reason="A source observation is available for downstream review.",
            )
            | row
            for row in (rows or ({},))
        ]
    }


def test_questions_are_optional_and_do_not_silently_drop_excess_requests():
    assert "questions" in ResearchBrief.model_fields
    from packages.research.models import ResearchQuestion

    assert ResearchBrief(run_id="r", topic="t", competitor="p", dimension="feature").questions == []
    original = [f"Example Suite: Can Guest read channel {index}?" for index in range(9)]
    request = brief(*original)
    assert [question.question for question in request.questions] == original
    assert isinstance(request.questions[0], ResearchQuestion)


def test_shared_question_scope_preserves_original_product_scoping_and_writer_entry():
    from packages.agents.writer.answer_coverage import research_questions as writer_questions
    from packages.research.question_scope import research_questions

    detail = SimpleNamespace(
        topic="General research",
        plan=SimpleNamespace(
            competitors=["Example Suite", "Other Suite"],
            decision_brief=SimpleNamespace(
                decision_question=(
                    "Example Suite: Can Guest read?\nCan Guest edit?\n"
                    "Other Suite: Can Guest share?"
                ),
            ),
        ),
    )
    rows = research_questions(detail, "Example Suite", "feature")
    assert [row["question"] for row in rows] == [
        "Example Suite: Can Guest read?",
        "Can Guest edit?",
    ]
    assert writer_questions is research_questions
    assert research_questions(detail, "Example Suite", "pricing") == []
    assert rows == research_questions(detail, "Example Suite", "feature")


def test_review_payload_keeps_only_current_accepted_observations_and_complete_conditions():
    from packages.research.question_evidence import question_review_payload

    request = brief(
        "Example Suite: Our Guest is already logged in; can they read private channels?"
    )
    original = evidence()
    items = [
        original,
        evidence("rejected", status="rejected"),
        evidence("other", competitor="Other Suite"),
        evidence("price", dimension="pricing"),
        evidence("noquote", quote=""),
        evidence("scalar", field="price_points", value="$5"),
    ]
    payload = question_review_payload(request, items)
    assert payload["questions"] == [question.model_dump() for question in request.questions]
    assert payload["evidence"] == [
        {
            "id": original.id,
            "quote": original.quote,
            "value": original.value,
            "source_url": original.source_url,
        }
    ]
    assert payload["product"] == request.competitor and payload["dimension"] == "feature"
    assert "already logged in" not in json.dumps(payload["evidence"])
    assert not payload["capacity_limited"]


def test_review_payload_selects_relevant_whole_records_with_explicit_capacity_metadata():
    from packages.research.question_evidence import question_review_payload

    request = brief("Can Guest read invited channels?")
    oversized = evidence(
        "large",
        quote="Unrelated export settings. " * 100,
        value={"status": "documented", "evidence_terms": ["x" * 3000]},
    )
    relevant = evidence()
    payload = question_review_payload(request, [oversized, relevant], max_bytes=1200)
    assert [row["id"] for row in payload["evidence"]] == [relevant.id]
    assert payload["evidence"][0]["value"] == relevant.value
    assert payload["capacity_limited"]
    assert payload["metadata"]["omitted_evidence_count"] == 1
    assert len(json.dumps(payload, ensure_ascii=False).encode()) <= 1200


def test_review_payload_preserves_direct_evidence_terms_and_rejects_question_overflow():
    from packages.research.question_evidence import question_review_payload

    direct = evidence(field="evidence_terms", value=["Original complete restriction."])
    assert (
        question_review_payload(brief("Can Guest read?"), [direct])["evidence"][0]["value"]
        == direct.value
    )
    with pytest.raises(ValueError, match="question"):
        question_review_payload(brief("原始问题" * 1000), [direct], max_bytes=800)


def test_arbitrary_capability_cannot_close_an_unassessed_question():
    from packages.research.question_evidence import question_evidence_gaps

    request = brief("Can Guest read private channels?", "Is export available on the Basic plan?")
    gaps = question_evidence_gaps(request, [evidence()])
    assert [gap.field for gap in gaps] == ["question.q1", "question.q2"]
    assert [gap.metadata["question"] for gap in gaps] == [q.question for q in request.questions]
    assert all(gap.metadata["source"] == "question_coverage" for gap in gaps)
    assert all(gap.suggested_action == "targeted_discovery" for gap in gaps)


def test_candidate_means_only_bound_observations_and_can_clear_retrieval_gap():
    from packages.research.question_evidence import question_evidence_gaps

    assert question_evidence_gaps(brief("Can Guest read?"), [evidence()], assessment()) == []


@pytest.mark.parametrize(
    "item",
    [
        evidence(status="rejected"),
        evidence(competitor="Other Suite"),
        evidence(dimension="pricing"),
        evidence(quote=""),
        evidence(field="billing_cycle", value="monthly"),
    ],
)
def test_candidate_cannot_bind_unusable_or_foreign_evidence(item):
    from packages.research.question_evidence import question_evidence_gaps

    assert len(question_evidence_gaps(brief("Can Guest read?"), [item], assessment())) == 1


@pytest.mark.parametrize(
    "rows",
    [
        {"questions": []},
        {"questions": None},
        None,
        assessment({"evidence_ids": []}),
        assessment({"evidence_ids": ["unknown"]}),
        assessment({"question_id": "unknown"}),
        assessment({}, {}),
        assessment({"status": "answered"}),
        assessment({"status": "candidate", "missing_fields": ["plan"]}),
        assessment({"evidence_ids": "e1"}),
        assessment({"reason": ""}),
        assessment({"question_id": []}),
        assessment({"status": []}),
    ],
)
def test_missing_unknown_duplicate_and_invalid_assessment_rows_keep_question_gap(rows):
    from packages.research.question_evidence import question_evidence_gaps

    gaps = question_evidence_gaps(brief("Can Guest read?"), [evidence()], rows)
    assert len(gaps) == 1 and gaps[0].metadata["question_id"] == "q1"


def test_missing_condition_is_preserved_for_targeted_original_question_query():
    from packages.research.question_evidence import question_evidence_gaps
    from packages.research.repair.strategies import repair_task_from_gap

    request = brief("Example Suite: Can Guest export on the Basic plan?")
    gap = question_evidence_gaps(
        request,
        [evidence()],
        assessment(
            {
                "status": "missing",
                "evidence_ids": [],
                "missing_fields": ["plan availability"],
                "reason": "The admitted originals do not cover this plan condition.",
            }
        ),
    )[0]
    assert gap.metadata["missing_fields"] == ["plan availability"]
    task = repair_task_from_gap(gap)
    assert task.required_action == "add_evidence"
    assert task.query_hints == [f"{request.competitor} official {request.questions[0].question}"]
    assert "question.q1" not in task.query_hints[0]


def test_duplicate_rows_do_not_erase_a_separate_valid_question_assessment():
    from packages.research.question_evidence import question_evidence_gaps

    rows = assessment({}, {}, {"question_id": "q2"})
    gaps = question_evidence_gaps(brief("Can Guest read?", "Can Guest edit?"), [evidence()], rows)
    assert [gap.metadata["question_id"] for gap in gaps] == ["q1"]


def test_gap_source_ids_keep_capture_identity_separate_from_observation_ids():
    from packages.research.question_evidence import question_evidence_gaps

    gap = question_evidence_gaps(
        brief("Can Guest read?"),
        [evidence()],
        assessment(
            {
                "status": "missing",
                "missing_fields": ["plan"],
            }
        ),
    )[0]
    assert gap.source_ids == ["page"]
    assert gap.metadata["evidence_ids"] == ["e1"]


def test_empty_question_scope_needs_no_assessment():
    from packages.research.question_evidence import question_evidence_gaps

    assert question_evidence_gaps(brief(), [evidence()], {"questions": []}) == []
