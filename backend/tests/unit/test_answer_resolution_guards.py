"""Anonymous examples for the deterministic answer boundary checks."""

import pytest

from packages.agents.writer.answer_resolution import resolution_reasons


def claim(text, claim_id="c1"):
    return {"id": claim_id, "text": text}


def answer(text, evidence, **updates):
    result = {
        "status": "answered",
        "answer": text,
        "resolution": "direct",
        "conclusion": "yes",
        "claim_ids": [row["id"] for row in evidence],
        "evidence_spans": [
            {"claim_id": row["id"], "quote": row["text"]} for row in evidence
        ],
        "reason": "The cited rule resolves this question.",
        "missing_fields": [],
    }
    result.update(updates)
    return result


@pytest.mark.parametrize("status", ["answered", "partial"])
def test_folder_rule_cannot_answer_private_message_question(status):
    evidence = [claim("Guests can access folders shared with them.")]
    result = answer("Guests can send private messages.", evidence, status=status)
    assert "question_object_mismatch" in resolution_reasons(
        result, "Can guests send private messages?", evidence
    )


def test_board_rule_cannot_answer_document_question():
    evidence = [claim("Editors can modify boards they own.")]
    assert "question_object_mismatch" in resolution_reasons(
        answer("Editors can edit documents.", evidence),
        "Can editors edit documents?",
        evidence,
    )


def test_generic_user_category_is_not_a_resolving_answer_body():
    evidence = [claim("Guests are an external user category.")]
    result = answer(
        "Guests are an external user category.",
        evidence,
        reason="Guests can send private messages to members.",
    )
    assert "answer_body_unresolved" in resolution_reasons(
        result, "Can guests send private messages?", evidence
    )


def test_user_category_claim_cannot_ground_a_new_capability_in_the_body():
    evidence = [claim("Guests are an external user category.")]
    result = answer("Yes, guests can send private messages.", evidence)
    assert "question_scope_not_grounded" in resolution_reasons(
        result, "Can guests send private messages?", evidence
    )


def test_reason_does_not_replace_empty_display_answer():
    evidence = [claim("Guests can access documents after signing in.")]
    result = answer("  ", evidence, reason="Guests can access documents after signing in.")
    assert "answer_body_missing" in resolution_reasons(
        result, "Can guests access documents?", evidence
    )


@pytest.mark.parametrize(
    "spans,extra",
    [
        ([], {"answer_span": "Guests can access documents."}),
        ([{"claim_id": "c1", "quote": "Guests can access documents."}], {}),
        ([{"claim_id": "other", "quote": "Guests can access folders."}], {}),
        ([{"claim_id": "c1", "quote": " "}], {}),
        ([{"claim_id": "c1", "quote": "."}], {}),
    ],
)
def test_only_real_claim_spans_can_ground_an_answer(spans, extra):
    evidence = [claim("Guests can access folders.")]
    result = answer(
        "Guests can access documents.", evidence, evidence_spans=spans, **extra
    )
    reasons = resolution_reasons(result, "Can guests access documents?", evidence)
    assert "claim_evidence_missing" in reasons or "evidence_span_invalid" in reasons


def test_each_referenced_claim_requires_its_own_real_span():
    evidence = [
        claim("Guests can access documents.", "c1"),
        claim("Guests must sign in before accessing documents.", "c2"),
    ]
    result = answer("Guests can access documents after signing in.", evidence)
    result["evidence_spans"] = result["evidence_spans"][:1]
    assert "claim_evidence_missing" in resolution_reasons(
        result, "Can guests access documents?", evidence
    )


def test_quote_cannot_borrow_its_object_from_another_claim_sentence():
    evidence = [claim("Guests can access folders. Editors can access documents.")]
    result = answer("Guests can access documents.", evidence)
    result["evidence_spans"] = [
        {"claim_id": "c1", "quote": "Guests can access folders."}
    ]
    assert "question_object_mismatch" in resolution_reasons(
        result, "Can guests access documents?", evidence
    )


def test_whole_claim_cannot_join_different_subject_object_pairs():
    evidence = [claim("Guests can access folders. Editors can access documents.")]
    result = answer("Guests can access documents.", evidence)
    assert "question_role_mismatch" in resolution_reasons(
        result, "Can guests access documents?", evidence
    )


@pytest.mark.parametrize("separator", [", while ", ", and ", " and "])
def test_independent_clauses_keep_their_own_subject_object_pairs(separator):
    evidence = [claim("Guests can access folders" + separator + "editors can access documents.")]
    result = answer("Guests can access documents.", evidence)
    assert "question_role_mismatch" in resolution_reasons(
        result, "Can guests access documents?", evidence
    )


def test_generic_independent_subject_does_not_borrow_the_next_clauses_named_role():
    evidence = [claim("Users can access documents, while guests can access folders.")]
    result = answer("Guests can access documents.", evidence)
    assert "question_role_not_grounded" in resolution_reasons(
        result, "Can guests access documents?", evidence
    )


def test_objectless_fragment_retains_its_claim_object_boundary():
    evidence = [claim("Guests can access folders.")]
    result = answer("Guests can access documents.", evidence)
    result["evidence_spans"] = [{"claim_id": "c1", "quote": "Guests can access"}]
    assert "question_object_mismatch" in resolution_reasons(
        result, "Can guests access documents?", evidence
    )


def test_named_role_mismatch_is_not_supported_by_object_overlap():
    evidence = [claim("Editors can modify documents.")]
    assert "question_role_mismatch" in resolution_reasons(
        answer("Guests can edit documents.", evidence),
        "Can guests edit documents?",
        evidence,
    )


def test_generic_subject_cannot_invent_a_specific_role():
    evidence = [claim("Users can modify documents.")]
    assert "question_role_not_grounded" in resolution_reasons(
        answer("Guests can edit documents.", evidence),
        "Can guests edit documents?",
        evidence,
    )


def test_recipient_role_is_not_the_action_subject():
    evidence = [claim("Administrators can send private messages to guests.")]
    assert "question_role_mismatch" in resolution_reasons(
        answer("Guests can send private messages.", evidence),
        "Can guests send private messages?",
        evidence,
    )


def test_generic_actor_with_named_recipient_does_not_ground_named_subject():
    evidence = [claim("Users can send private messages to guests.")]
    assert "question_role_not_grounded" in resolution_reasons(
        answer("Guests can send private messages.", evidence),
        "Can guests send private messages?",
        evidence,
    )


def test_condition_actor_does_not_replace_main_clause_subject():
    evidence = [claim("After administrators invite guests, guests can access documents.")]
    result = answer("Guests can access documents after an invitation.", evidence)
    assert resolution_reasons(result, "Can guests access documents?", evidence) == ()


def test_background_inviter_does_not_gain_the_main_subjects_access():
    evidence = [claim("After administrators invite guests, guests can access documents.")]
    result = answer("Administrators can access documents.", evidence)
    assert "question_role_mismatch" in resolution_reasons(
        result, "Can administrators access documents?", evidence
    )


def test_product_prefix_does_not_hide_an_inverted_question_subject():
    evidence = [claim("Editors can edit documents.")]
    result = answer("Guests can edit documents.", evidence)
    assert "question_role_mismatch" in resolution_reasons(
        result, "Example Product: Can guests edit documents?", evidence
    )


@pytest.mark.parametrize(
    "source,question,body",
    [
        (
            "Guests and editors can access documents.",
            "Can editors access documents?",
            "Editors can access documents.",
        ),
        (
            "由管理员邀请的访客可以访问文档。",
            "访客可以访问文档吗？",
            "可以，访客受邀后可以访问文档。",
        ),
    ],
)
def test_explicit_subjects_survive_conjunctions_and_passive_invitation(source, question, body):
    evidence = [claim(source)]
    assert resolution_reasons(answer(body, evidence), question, evidence) == ()


@pytest.mark.parametrize(
    "source",
    [
        "Guests, after signing in, can access documents.",
        "All users, including guests, can access documents.",
        "Guests can access documents and folders.",
    ],
)
def test_explicit_subject_insertions_and_same_subject_objects_remain_valid(source):
    evidence = [claim(source)]
    result = answer("Guests can access documents.", evidence)
    assert resolution_reasons(result, "Can guests access documents?", evidence) == ()


def test_setup_prefix_does_not_allow_a_category_definition_as_an_answer():
    evidence = [claim("Guests can access documents.")]
    result = answer("Guests are an external user category.", evidence)
    assert "answer_body_unresolved" in resolution_reasons(
        result, "In our setup, can guests access documents?", evidence
    )


def test_chinese_explicit_can_answer_keeps_its_condition():
    evidence = [claim("Guests can access documents after signing in.")]
    result = answer("能，访客登录后进入文档。", evidence)
    assert resolution_reasons(result, "访客能访问文档吗？", evidence) == ()


@pytest.mark.parametrize(
    "question,source,body",
    [
        (
            "Can guests edit documents?",
            "Guests can edit documents after signing in.",
            "Yes, guests can edit documents after signing in.",
        ),
        (
            "访客可以编辑文档吗？",
            "Guests can edit documents after signing in.",
            "可以，访客登录后可编辑文档。",
        ),
        (
            "Can administrators send private messages to guests?",
            "Administrators can send private messages to guests.",
            "Yes, administrators can send private messages to guests.",
        ),
        (
            "Can guests access documents?",
            "Guests invited by administrators can access documents.",
            "Yes, guests invited by administrators can access documents.",
        ),
    ],
)
def test_same_object_same_subject_rule_passes(question, source, body):
    evidence = [claim(source)]
    assert resolution_reasons(answer(body, evidence), question, evidence) == ()


def test_conditional_conclusion_from_same_scope_rule_passes():
    evidence = [claim("Guests can access documents only after the owner invites them.")]
    result = answer(
        "It depends: guests can access a document if its owner invites them.",
        evidence,
        resolution="conditional",
        conclusion="depends",
    )
    assert resolution_reasons(result, "Can guests access documents?", evidence) == ()


def test_simple_factual_access_answer_does_not_require_a_modal_verb():
    evidence = [claim("Guests access documents through a personal invitation link.")]
    result = answer("Guests access documents through a personal invitation link.", evidence)
    assert resolution_reasons(result, "Can guests access documents?", evidence) == ()


@pytest.mark.parametrize("conclusion", ["unknown", "not_applicable"])
def test_direct_closed_question_requires_an_actual_conclusion(conclusion):
    evidence = [claim("Guests can access documents.")]
    assert "answer_conclusion_missing" in resolution_reasons(
        answer("Guests can access documents.", evidence, conclusion=conclusion),
        "Can guests access documents?",
        evidence,
    )


def test_embedded_which_does_not_turn_a_closed_question_into_an_open_one():
    evidence = [claim("Guests can access documents.")]
    result = answer("Guests can access documents.", evidence, conclusion="not_applicable")
    assert "answer_conclusion_missing" in resolution_reasons(
        result, "Can guests choose which documents they access?", evidence
    )


def test_open_explanation_can_use_not_applicable_with_a_real_answer():
    evidence = [claim("Guests access documents through a personal invitation link.")]
    result = answer(
        "Guests access documents through their personal invitation link.",
        evidence,
        conclusion="not_applicable",
    )
    assert resolution_reasons(result, "How do guests access documents?", evidence) == ()


def test_affirmative_enum_cannot_hide_a_missing_display_conclusion():
    evidence = [claim("Guests can access documents.")]
    assert "answer_body_unresolved" in resolution_reasons(
        answer("A guest is an external user category.", evidence),
        "Can guests access documents?",
        evidence,
    )


def test_display_answer_cannot_switch_to_an_unrelated_object():
    evidence = [claim("Guests can access documents.")]
    assert "answer_object_mismatch" in resolution_reasons(
        answer("Guests can access boards.", evidence),
        "Can guests access documents?",
        evidence,
    )


def test_display_answer_cannot_switch_to_another_explicit_subject():
    evidence = [claim("Guests can access documents.")]
    assert "answer_role_mismatch" in resolution_reasons(
        answer("Editors can access documents.", evidence),
        "Can guests access documents?",
        evidence,
    )


def test_real_clarification_asks_for_the_missing_condition():
    result = answer(
        "Which account creation period applies to these guests?",
        [],
        resolution="clarification",
        conclusion="unknown",
        missing_fields=["account_creation_period"],
    )
    assert resolution_reasons(result, "Can guests become administrators?", []) == ()


def test_feature_statement_is_not_a_clarification_even_with_missing_fields():
    result = answer(
        "Guest access is supported.",
        [],
        resolution="clarification",
        conclusion="unknown",
        missing_fields=["account_creation_period"],
    )
    assert "clarification_missing" in resolution_reasons(
        result, "Can guests become administrators?", []
    )


def test_insufficient_answer_keeps_unknown_and_explicit_missing_fields():
    result = answer(
        "The reviewed material does not establish the total price.",
        [],
        status="partial",
        resolution="insufficient",
        conclusion="unknown",
        missing_fields=["seat_price", "billing_period"],
    )
    assert resolution_reasons(result, "What is the total price for our team?", []) == ()


@pytest.mark.parametrize(
    "updates,reason",
    [
        ({"conclusion": "no"}, "insufficient_conclusion_invalid"),
        ({"missing_fields": []}, "insufficient_fields_missing"),
    ],
)
def test_insufficient_resolution_cannot_turn_missing_evidence_into_no(updates, reason):
    result = answer(
        "The reviewed material does not establish a price.",
        [],
        resolution="insufficient",
        conclusion="unknown",
        missing_fields=["price"],
    )
    result.update(updates)
    assert reason in resolution_reasons(result, "What is the price?", [])


def test_unknown_objects_and_unknown_named_roles_are_left_to_semantic_review():
    evidence = [claim("Curators can adjust tessellations.")]
    result = answer("Curators can adjust tessellations.", evidence)
    assert resolution_reasons(result, "Can curators adjust tessellations?", evidence) == ()


def test_unanswered_record_does_not_need_evidence_or_make_a_negative_claim():
    result = answer(
        "The reviewed material does not settle this question.",
        [],
        status="unverified",
        resolution="unresolved",
        conclusion="unknown",
    )
    assert resolution_reasons(result, "Can guests send private messages?", []) == ()
