import pytest

from packages.agents.writer.answer_resolution import resolution_reasons
from packages.research.extraction.semantic import MAX_INPUT_CHARS, semantic_body_window
from packages.research.models import CapturedPage, ResearchBrief


def window_request():
    return ResearchBrief(
        run_id="window",
        topic="General product research",
        competitor="Example Suite",
        dimension="feature",
        product_category="documents",
        questions=[
            {"question_id": "availability", "question": "Can Basic members use Answer Panel?"},
            {"question_id": "authorization", "question": "Can members read without authorization?"},
        ],
    )


def window_page(body):
    return CapturedPage(
        candidate_id="original",
        requested_url="https://example.test/guide",
        final_url="https://example.test/guide",
        title="Example Suite guide",
        text=body,
        content_hash="original",
        status="ok",
        quality_score=0.9,
        metadata={"document_headings": [(1, "Guide"), (2, "Availability"), (2, "Authorization")]},
    )


def test_multiple_questions_keep_complete_bounded_guide_with_distinct_conditions():
    body = (
        "Guide\nAvailability\nAnswer Panel is only available on the Summit plan.\n"
        "Authorization\nOnly members authorized by the backend can read the shared documents."
    )
    assert semantic_body_window(window_request(), window_page(body)) == body


def test_single_active_question_still_uses_its_original_source_section():
    body = (
        "Guide\nAvailability\nAnswer Panel is only available on the Summit plan.\n"
        "Authorization\nOnly members authorized by the backend can read the shared documents."
    )
    request = window_request().model_copy(
        update={
            "metadata": {
                "active_question_ids": ["availability"],
            }
        }
    )
    window = semantic_body_window(request, window_page(body))
    assert window in body and "Answer Panel" in window
    assert "authorized by the backend" not in window


def test_multiple_questions_keep_long_document_window_bounded_and_contiguous():
    body = (
        "Guide\nAvailability\nAnswer Panel is only available on the Summit plan.\n"
        + "Members organize their material.\n" * 500
        + "Authorization\nOnly authorized members can read the shared documents."
    )
    window = semantic_body_window(window_request(), window_page(body))
    assert window in body and len(window) <= MAX_INPUT_CHARS and len(window) < len(body)


def answer(body, *, quote="成员不能查看内部消息。", claim_text="成员不能查看内部消息。"):
    return (
        {
            "status": "answered",
            "resolution": "direct",
            "conclusion": "no",
            "answer": body,
            "claim_ids": ["claim"],
            "evidence_spans": [{"claim_id": "claim", "quote": quote}],
        },
        [{"id": "claim", "text": claim_text}],
    )


@pytest.mark.parametrize(
    "body",
    [
        "成员看不到内部消息。",
        "成员看不见内部消息。",
        "成员不会获得内部消息的访问权。",
        "成员不可以查看内部消息。",
        "成员不具备查看内部消息的权限。",
    ],
)
def test_explicit_chinese_negative_answers_pass_only_the_existing_structural_guard(body):
    row, claims = answer(body)
    assert resolution_reasons(row, "成员是否能看到内部消息？", claims) == ()


def test_chinese_negative_answer_still_requires_a_published_verbatim_span():
    row, claims = answer("成员看不到内部消息。", quote="编造的原文引用。")
    assert "evidence_span_invalid" in resolution_reasons(row, "成员是否能看到内部消息？", claims)


def test_chinese_negative_answer_still_rejects_a_different_object():
    row, claims = answer(
        "成员看不到文件夹。", quote="成员不能查看文件夹。", claim_text="成员不能查看文件夹。"
    )
    assert "answer_object_mismatch" in resolution_reasons(row, "成员是否能看到内部消息？", claims)


def test_chinese_negative_answer_still_rejects_a_different_role():
    row, claims = answer("成员看不到内部消息。")
    assert "question_role_mismatch" in resolution_reasons(row, "访客是否能看到内部消息？", claims)
