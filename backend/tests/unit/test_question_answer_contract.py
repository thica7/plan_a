import json

from packages.agents.writer.answer_coverage import parse_answer_coverage


QUESTION = {"question_id": "q1", "question": "Can guests read private messages?"}
CLAIM = {"id": "c1", "text": "Guests cannot read private messages."}


def row(**changes):
    return dict(question_id="q1", status="answered", answer=CLAIM["text"],
                resolution="direct", conclusion="no", claim_ids=["c1"],
                evidence_spans=[{"claim_id": "c1", "quote": CLAIM["text"]}],
                missing_fields=[], reason="The published observation answers the request.") | changes


def parse(answer, claims=(CLAIM,)):
    return parse_answer_coverage(json.dumps({"answers": [answer]}), [QUESTION],
                                 {claim["id"] for claim in claims}, claims=claims)[0]


def test_actual_answer_and_exact_published_span_are_retained():
    coverage = parse(row())
    assert coverage.status == "answered"
    assert coverage.answer == CLAIM["text"]
    assert coverage.evidence_spans[0].quote == CLAIM["text"]


def test_claim_id_and_coverage_reason_do_not_substitute_for_a_visible_answer():
    answer = {k: row()[k] for k in ("question_id", "status", "claim_ids", "reason")}
    coverage = parse(answer)
    assert coverage.status == "unverified" and not coverage.answer


def test_folder_evidence_cannot_complete_a_private_message_question():
    claim = {"id": "c1", "text": "Guests can read shared folders."}
    coverage = parse(row(answer=claim["text"], conclusion="yes",
                         evidence_spans=[{"claim_id": "c1", "quote": claim["text"]}]), (claim,))
    assert coverage.status == "unverified" and not coverage.answer


def test_reason_cannot_supply_a_missing_clarification_in_the_answer():
    coverage = parse(row(answer="Guests cannot read private messages.",
                         resolution="clarification", conclusion="depends",
                         reason="Ask the user to confirm their account date."))
    assert coverage.status == "unverified" and not coverage.answer


def test_actual_clarification_keeps_original_rule_and_literal_span_without_a_permission_assertion():
    claim = {'id': 'c1', 'text': 'Guests may read private messages only in legacy accounts.'}
    coverage = parse(row(answer='Please provide the account creation date.',
                         resolution='clarification', conclusion='unknown',
                         missing_fields=['account_created_at'],
                         evidence_spans=[{'claim_id': 'c1', 'quote': claim['text']}]), (claim,))
    assert coverage.status == 'answered' and coverage.resolution == 'clarification'


def test_model_cannot_assert_server_proven_insufficiency_without_source_review():
    coverage = parse(row(answer="The current price is not in the admitted evidence.",
                         resolution="insufficient", conclusion="unknown", claim_ids=[],
                         evidence_spans=[], missing_fields=["current_price"]))
    assert coverage.status == "unverified" and not coverage.answer


def test_fabricated_excerpt_cannot_complete_an_answer():
    coverage = parse(row(evidence_spans=[{"claim_id": "c1", "quote": "Guests can read messages."}]))
    assert coverage.status == "unverified" and not coverage.answer
