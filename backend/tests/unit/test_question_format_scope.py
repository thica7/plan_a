"""Presentation instructions remain part of a question, not another answer slot."""

from types import SimpleNamespace

import pytest

from packages.research.question_scope import research_questions


def questions(text, product="Example"):
    detail = SimpleNamespace(
        topic="research",
        plan=SimpleNamespace(
            competitors=["Example", "Other"],
            decision_brief=SimpleNamespace(decision_question=text),
        ),
    )
    return research_questions(detail, product, "feature")


@pytest.mark.parametrize("separator", ["", "\n"])
def test_format_request_with_whether_does_not_create_another_answer_slot(separator):
    first = "Example: B 允许投票，是否意味着他必须给每张卡片投票？"
    tail = "请将可以执行的操作、启用条件与是否存在强制义务分别说明。"
    rows = questions(first + separator + tail)
    assert len(rows) == 1
    assert first in rows[0]["question"] and tail in rows[0]["question"]


def test_format_request_does_not_consume_a_new_product_question():
    text = "Example 能下载吗？\n请将操作与条件分别说明。\nOther 是否可以投票？"
    assert len(questions(text)) == 1
    assert questions(text, "Other")[0]["question"] == "Other 是否可以投票？"


def test_actual_followup_and_standalone_request_are_retained():
    text = "Example 能下载吗？请说明是否能导出？"
    assert len(questions(text)) == 2
    assert questions("请将支持的操作分别说明。")[0]["question"]
