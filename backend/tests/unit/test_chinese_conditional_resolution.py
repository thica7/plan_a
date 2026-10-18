"""Anonymous Chinese necessary-condition assertions and existing boundaries."""

import pytest

from packages.agents.writer.answer_coverage import coverage_resolution_reasons
from packages.agents.writer.answer_resolution import resolution_reasons
from packages.research.evidence.answer_coverage_models import ReportAnswerCoverage


QUESTION = "访客有登录凭证但尚未获后端授权就能访问文档吗？"
RULE = "只有在后端被授权的访客才能访问文档。"


def coverage(text=RULE, question=QUESTION, **updates):
    claims = [{"id": "c1", "text": text}]
    fields = {
        "question_id": "q1",
        "question": question,
        "status": "answered",
        "resolution": "conditional",
        "conclusion": "no",
        "answer": text,
        "claim_ids": ("c1",),
        "evidence_spans": ({"claim_id": "c1", "quote": text},),
        "reason": "Reviewed the complete cited rule.",
        "binding_version": 2,
    }
    fields.update(updates)
    return ReportAnswerCoverage(**fields), claims


@pytest.mark.parametrize(
    "text",
    [
        RULE,
        "只有在后端被授权的人才能访问文档。",
        "访客只有获得后端授权才访问文档。",
        "只有获得后端授权的访客才可查看文档。",
        "只有获得后端授权的访客，才能访问文档。",
    ],
)
def test_complete_necessary_condition_is_an_answer(text):
    record, claims = coverage(text, question="有登录凭证但后端未授权，登录就能访问文档吗？")
    assert coverage_resolution_reasons(record, claims, require_v2=True) == ()


def test_necessary_condition_keeps_an_explicit_guest_subject():
    record, claims = coverage()
    assert coverage_resolution_reasons(record, claims, require_v2=True) == ()


def test_setup_and_login_background_keeps_the_complete_access_condition():
    text = (
        "配置完成后，访问文档的访客会被提示使用其已有凭证登录；"
        "只有在你的后端中被授权的人才能访问你的文档。"
    )
    record, claims = coverage(text, question="有登录凭证但后端未授权，拿到链接并登录就一定能看吗？")
    assert coverage_resolution_reasons(record, claims, require_v2=True) == ()


@pytest.mark.parametrize("heading", ["建议：", "背景：", "示例：", "引用示例："])
@pytest.mark.parametrize("separator", ["\n", "\r\n", "\n\n"])
def test_non_asserting_heading_keeps_its_scope_across_line_breaks(heading, separator):
    record, claims = coverage(heading + separator + RULE)
    assert "answer_body_unresolved" in coverage_resolution_reasons(record, claims, require_v2=True)


@pytest.mark.parametrize("text", [
    "示例。\n" + RULE,
    "以下是假设。\n" + RULE,
    "以下是建议。\n" + RULE,
    RULE + "\n以上仅为示例。",
])
def test_non_assertion_marker_applies_to_the_complete_block(text):
    record, claims = coverage(text)
    assert "answer_body_unresolved" in coverage_resolution_reasons(record, claims, require_v2=True)


def test_explicit_rule_introduction_keeps_the_non_quoted_statement_resolving():
    record, claims = coverage("访问规则如下。\n" + RULE)
    assert coverage_resolution_reasons(record, claims, require_v2=True) == ()


@pytest.mark.parametrize(
    "text",
    [
        "\n" + RULE,
        RULE + "\n",
        "只有在后端被授权的访客\n才能访问文档。",
        "配置完成后，访问文档的访客会被提示使用其已有凭证登录；\n"
        "只有在你的后端中被授权的人才能访问你的文档。",
    ],
)
def test_line_breaks_keep_a_complete_assertion_resolving(text):
    record, claims = coverage(text, question="有登录凭证但后端未授权，拿到链接并登录就一定能看吗？")
    assert coverage_resolution_reasons(record, claims, require_v2=True) == ()


@pytest.mark.parametrize("opening,closing", [
    ("“", "”"), ('"', '"'), ("「", "」"), ("‘", "’"), ("'", "'"), ("『", "』"),
])
def test_cross_sentence_quotation_cannot_supply_an_assertion(opening, closing):
    record, claims = coverage(opening + "示例。\n" + RULE + closing)
    assert "answer_body_unresolved" in coverage_resolution_reasons(record, claims, require_v2=True)


@pytest.mark.parametrize("text", [
    "“示例。\n「说明。\n" + RULE + "」”",
    '"示例。\n\n“说明。\n' + RULE + '”"',
    "“示例。\n" + RULE,
    RULE + "\n“背景说明。”",
    "“背景说明。”\n" + RULE,
])
def test_quoted_or_mixed_blocks_conservatively_skip_the_new_assertion_path(text):
    record, claims = coverage(text)
    assert "answer_body_unresolved" in coverage_resolution_reasons(record, claims, require_v2=True)


def test_explicit_negative_statement_keeps_the_existing_path_in_a_mixed_block():
    text = "未获后端授权的访客不能访问文档。\n“示例。\n" + RULE + "”"
    record, claims = coverage(text)
    assert coverage_resolution_reasons(record, claims, require_v2=True) == ()


@pytest.mark.parametrize(
    "body",
    [
        "只有在后端被授权的访客。",
        "只有在后端被授权的访客才。",
        "只有在后端被授权的访客才能。",
        "只有在后端被授权的访客才能访问。",
        "只有才能访问文档。",
        "只有 才能访问文档。",
        "只有在后端被授权的访客才能访问文档吗？",
        "只有在后端被授权的访客才能访问文档？",
        "是否只有在后端被授权的访客才能访问文档。",
        "只有在后端被授权的访客才能如何访问文档？",
        "建议只有在后端被授权的访客才能访问文档。",
        "请确认只有在后端被授权的访客才能访问文档。",
        "背景：只有在后端被授权的访客才能访问文档。",
        "例如，只有在后端被授权的访客才能访问文档。",
        "假设只有在后端被授权的访客才能访问文档。",
        "讨论“只有在后端被授权的访客才能访问文档”。",
        "“只有在后端被授权的访客才能访问文档”。",
        "“\n只有在后端被授权的访客才能访问文档\n”。",
    ],
)
def test_non_asserting_or_incomplete_conditions_do_not_resolve_the_question(body):
    record, claims = coverage(body)
    assert "answer_body_unresolved" in coverage_resolution_reasons(record, claims, require_v2=True)


def test_reason_cannot_complete_a_condition_fragment():
    record, claims = coverage("只有在后端被授权的访客。", reason=RULE)
    assert "answer_body_unresolved" in coverage_resolution_reasons(record, claims, require_v2=True)


@pytest.mark.parametrize(
    "text,question,reason",
    [
        ("只有在后端被授权的编辑者才能访问文档。", QUESTION, "question_role_not_grounded"),
        ("只有在后端被授权的访客才能访问看板。", QUESTION, "answer_object_mismatch"),
    ],
)
def test_explicit_necessary_conditions_keep_role_and_object_guards(text, question, reason):
    record, claims = coverage(text, question)
    assert reason in coverage_resolution_reasons(record, claims, require_v2=True)


def test_source_role_cannot_be_replaced_in_a_necessary_condition():
    record, _ = coverage(RULE)
    claims = [{"id": "c1", "text": "只有在后端被授权的编辑者才能访问文档。"}]
    payload = record.model_dump(mode="json")
    payload["evidence_spans"] = [{"claim_id": "c1", "quote": claims[0]["text"]}]
    assert "question_role_not_grounded" in resolution_reasons(payload, QUESTION, claims)


@pytest.mark.parametrize(
    "updates,reason",
    [
        ({"answer": RULE + "访客登录后访问文档。"}, "answer_selection_binding_invalid"),
        ({"evidence_spans": ({"claim_id": "c1", "quote": "才能访问文档"},)}, "answer_selection_binding_invalid"),
        ({"evidence_spans": ({"claim_id": "other", "quote": RULE},)}, "evidence_span_invalid"),
        ({"claim_ids": ("other",)}, "answer_claim_ids_invalid"),
        ({"basis_snapshot_id": "another-snapshot"}, "answer_resolution_unverified"),
        ({"binding_version": None}, "answer_selection_version_required"),
        ({"conclusion": "not_applicable"}, "answer_conclusion_missing"),
    ],
)
def test_necessary_condition_does_not_bypass_existing_bindings(updates, reason):
    record, claims = coverage(**updates)
    assert reason in coverage_resolution_reasons(record, claims, require_v2=True)


def test_necessary_condition_does_not_establish_an_unstated_exclusive_plan():
    record, claims = coverage("Summit 套餐包含文档访问功能。")
    record = record.model_copy(update={"answer": "只有 Summit 套餐的访客才能访问文档。"})
    assert "answer_plan_exclusivity_unverified" in coverage_resolution_reasons(record, claims, require_v2=True)


@pytest.mark.parametrize("resolution", ["direct", "conditional"])
def test_explicit_negative_answer_keeps_its_polarity(resolution):
    record, claims = coverage("未获后端授权的访客不能访问文档。", resolution=resolution)
    assert record.conclusion == "no"
    assert coverage_resolution_reasons(record, claims, require_v2=True) == ()
