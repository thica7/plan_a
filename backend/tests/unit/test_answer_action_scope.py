"""Question decisions must use published claims about the requested operations."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from packages.agents.writer.answer_coverage import (
    coverage_resolution_reasons,
    parse_answer_coverage,
)
from packages.research.evidence.answer_coverage_models import ReportAnswerCoverage


def response(ids, **updates):
    row = dict(
        question_id="q",
        status="answered",
        claim_ids=ids,
        resolution="direct",
        conclusion="yes",
        missing_fields=[],
        reason="The selected claims answer the question.",
    )
    return json.dumps({"version": 3, "answers": [row | updates]})


def parse(question, texts, **updates):
    claims = [dict(id=f"c{i}", text=text) for i, text in enumerate(texts)]
    result = parse_answer_coverage(
        response([c["id"] for c in claims], **updates),
        [{"question_id": "q", "question": question}],
        {c["id"] for c in claims},
        claims=claims,
        required_binding_version=3,
    )
    return result[0], claims


@pytest.mark.parametrize(
    "question,texts",
    [
        (
            "他能下载 A 的卡片附件并导出 A 吗？",
            ["Observer 在启用投票的看板上可以投票，但投票不是强制义务。"],
        ),
        (
            "Can observers download attachments and export boards?",
            ["Observers can vote when voting is enabled."],
        ),
        (
            "Can observers download attachments and export boards?",
            ["Observers can download attachments."],
        ),
        ("能否导入文件？", ["可以导出文件。"]),
        (
            "同事只被授予 example.com 的 Cache Domain Purge 角色，没有其他角色。"
            "他能清除 other.example 的边缘缓存吗？",
            ["域范围角色仅适用于账户内指定的某个域名。"],
        ),
        ("Can members export boards?", ["Members can download files."]),
        (
            "Can observers download attachments\nand export boards?",
            ["Observers can export boards."],
        ),
        (
            "Can observers download attachments; and export boards?",
            ["Observers can export boards."],
        ),
        ("Can observers download attachments and export boards", ["Observers can vote."]),
        ("在看板中可以下载附件，并导出看板吗？", ["可以导出看板。"]),
        ("Can observers, after voting, download attachments?", ["Observers can vote."]),
        ("他可以下载附件吗；能否导出看板？", ["可以导出看板。"]),
    ],
)
def test_unrelated_or_incomplete_operation_cannot_be_answered(question, texts):
    result, _ = parse(question, texts)
    assert result.status == "unverified"
    assert not result.claim_ids and result.conclusion == "unknown"
    assert "answer_operation_not_grounded" in result.reason


@pytest.mark.parametrize(
    "question,texts",
    [
        (
            "他能下载 A 的卡片附件并导出 A 吗？",
            ["Observer 可以下载卡片附件。", "Observer 可以导出看板。"],
        ),
        (
            "Can observers download attachments and export boards?",
            ["Observers can download attachments.", "Observers can export boards."],
        ),
        (
            "After voting on a card, can observers download attachments?",
            ["Observers can download card attachments."],
        ),
        ("投票完成之后，他能下载卡片附件吗？", ["Observer 可以下载卡片附件。"]),
        ("Can guests access documents?", ["Guests can access invited documents."]),
        ("B 允许投票，是否意味着他必须给每张卡片投票？", ["可以投票并不意味着必须投票。"]),
        ("Can users purge the cache?", ["Users may invalidate the cache."]),
        (
            "Observers can vote. Are they required to vote?",
            ["Observers are allowed to vote but voting is not mandatory."],
        ),
        (
            "If observers can vote, can they download attachments?",
            ["Observers can download attachments."],
        ),
        (
            "Can observers download attachments after voting on a card?",
            ["Observers can download attachments."],
        ),
        ("如果他可以投票，他能下载附件吗？", ["Observer 可以下载附件。"]),
        (
            "How can observers download attachments after voting?",
            ["Observers can download attachments from the card menu."],
        ),
        (
            "Observers can vote; can they download attachments?",
            ["Observers can download attachments."],
        ),
        (
            "Observers can vote\nCan they download attachments?",
            ["Observers can download attachments."],
        ),
        ("他可以投票；能否下载附件？", ["Observer 可以下载附件。"]),
        ("在他可以投票的看板上，他能下载卡片附件吗？", ["Observer 可以下载卡片附件。"]),
    ],
)
def test_complete_supported_actions_and_background_remain_eligible(question, texts):
    result, claims = parse(question, texts)
    assert result.status == "answered", result.reason
    assert not coverage_resolution_reasons(result, claims, required_binding_version=3)


def test_extra_unselected_claim_does_not_complete_selected_answer():
    claims = [
        dict(id="vote", text="Observers can vote."),
        dict(id="download", text="Observers can download attachments."),
    ]
    result = parse_answer_coverage(
        response(["vote"]),
        [{"question_id": "q", "question": "Can observers download attachments?"}],
        {"vote", "download"},
        claims=claims,
        required_binding_version=3,
    )[0]
    assert result.status == "unverified"


def test_saved_answer_replay_detects_wrong_action_even_with_valid_identity():
    text = "Observers can vote."
    record = ReportAnswerCoverage(
        question_id="q",
        question="Can observers export boards?",
        status="answered",
        claim_ids=("vote",),
        reason="Based on 1 published claims; answered; direct answer.",
        answer=text,
        resolution="direct",
        conclusion="yes",
        binding_version=3,
        evidence_spans=({"claim_id": "vote", "quote": text},),
    )
    assert "answer_operation_not_grounded" in coverage_resolution_reasons(
        record, [{"id": "vote", "text": text}]
    )


@pytest.mark.parametrize(
    "case",
    json.loads((Path(__file__).parent / "fixtures/answer_action_v35.json").read_text())["cases"],
    ids=lambda case: case["group"],
)
def test_exact_saved_false_positives_are_rejected(case):
    record = ReportAnswerCoverage.model_validate(case["answer"])
    assert record.status == "answered"
    assert "answer_operation_not_grounded" in coverage_resolution_reasons(
        record, case["published_claims"]
    )


@pytest.mark.parametrize(
    "conclusion,expected", [("yes", "unverified"), ("no", "unverified"), ("depends", "partial")]
)
def test_partial_subset_does_not_settle_missing_operations(conclusion, expected):
    result, _ = parse(
        "Can observers download attachments and export boards?",
        ["Observers can download attachments."],
        status="partial",
        resolution="conditional",
        conclusion=conclusion,
    )
    assert result.status == expected


@pytest.mark.asyncio
async def test_second_review_cannot_promote_unrelated_claim_to_answered(monkeypatch):
    from test_answer_semantic_review import Reviewer

    from packages.research.evidence.report_claims import ReportClaim

    monkeypatch.setattr(
        "packages.agents.writer.price_answers.server_missing_price_answers", lambda *args: {}
    )
    first = json.dumps(
        {
            "version": 3,
            "answers": [
                dict(
                    question_id="q",
                    status="unanswered",
                    claim_ids=[],
                    resolution="unresolved",
                    conclusion="unknown",
                    missing_fields=[],
                    reason="No download claim was published.",
                )
            ],
        }
    )
    reviewer = Reviewer([first, response(["vote"])])
    claim = ReportClaim(
        id="vote",
        text="Observers can vote when enabled.",
        competitor="Example",
        dimension="feature",
        kind="fact",
        fact_ids=("f",),
        source_ids=("s",),
    )
    answers, gaps, _ = await reviewer._dimension_question_coverage(
        SimpleNamespace(detail=SimpleNamespace(output_language="en")),
        [{"question_id": "q", "question": "Can observers download attachments?"}],
        {},
        [SimpleNamespace(claim=claim, status="supported")],
        SimpleNamespace(competitor="Example", dimension="feature", facts=()),
        SimpleNamespace(max_bytes=12000),
        (),
    )
    assert len(reviewer.calls) == 2
    assert answers[0].status == "unverified"
    assert "answer_operation_not_grounded" in answers[0].reason
    assert "answer_coverage_incomplete" in gaps
