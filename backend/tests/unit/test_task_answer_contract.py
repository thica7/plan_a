"""Task decisions reach visible answers without granting whole-question coverage."""

import importlib
import importlib.util
import json

import pytest
from test_task_projection import projected_case

from packages.agents.writer.answer_presentation import (
    question_coverage_lines,
    question_coverage_matches,
)


def task_answer_plan(*args):
    spec = importlib.util.find_spec("packages.agents.writer.task_answers")
    assert spec is not None, "The server-owned task answer compiler is missing"
    return importlib.import_module(spec.name).task_answer_plan(*args)


def restore_task_segments(*args):
    return importlib.import_module("packages.agents.writer.task_answers").restore_task_segments(
        *args
    )


def test_reviewed_task_conclusion_is_visible_under_its_full_original_question():
    record, audit, _, _ = projected_case()
    lines = question_coverage_lines(audit, "zh-CN", detail=record.detail)
    assert any("子任务结论：是" in line for line in lines)
    assert any(audit.answer_coverage[0].question in line for line in lines)
    assert audit.answer_coverage[0].status == "unverified"
    report = f"### {audit.competitor} — 功能\n\n" + "\n".join(lines) + "\n"
    assert question_coverage_matches(report, audit, "zh-CN", detail=record.detail)
    assert not question_coverage_matches(
        report.replace("子任务结论：是", "子任务结论：否"), audit, "zh-CN", detail=record.detail
    )


def test_forged_task_decision_cannot_create_a_visible_answer():
    record, audit, span, receipt = projected_case()
    receipt["tasks"][0]["decision"]["conclusion"] = "no"
    span.full_output = json.dumps(receipt)
    assert not any(
        "子任务结论" in s for s in question_coverage_lines(audit, "zh-CN", detail=record.detail)
    )


def test_server_segments_preserve_scenario_and_trailing_instructions():
    text = "Assume A is enabled. Can A vote? Can B export? Keep all conditions."
    questions = [dict(question_id="q", question=text)]
    tasks = [
        dict(
            question_id="q",
            task_id=f"t{i}",
            question_quote=quote,
            focus=focus,
            state="supported",
            claim_id=f"c{i}",
            decision=dict(conclusion="yes", relation="direct"),
        )
        for i, (quote, focus) in enumerate([("Can A vote?", "vote"), ("Can B export?", "export")])
    ]
    plan = task_answer_plan(questions, tasks, {"c0", "c1"})
    parts = plan[0]["subquestions"]
    assert "".join(p["question_quote"] for p in parts) == text
    assert parts[0]["question_quote"].startswith("Assume A is enabled.")
    assert parts[-1]["question_quote"].endswith("Keep all conditions.")
    raw = json.dumps(
        dict(
            version=3,
            answers=[
                dict(
                    question_id="q",
                    subquestions=[
                        dict(
                            segment_id=p["segment_id"],
                            claim_ids=p["claim_ids"],
                            conclusion="yes",
                            relation="direct",
                        )
                        for p in parts
                    ],
                )
            ],
        )
    )
    restored = json.loads(restore_task_segments(raw, plan))
    assert [p["question_quote"] for p in restored["answers"][0]["subquestions"]] == [
        p["question_quote"] for p in parts
    ]


def test_conflicting_resource_results_share_one_complete_segment():
    q = dict(question_id="q", question="Assume both boards exist. Can A and B vote?")
    tasks = [
        dict(
            question_id="q",
            task_id=f"t{i}",
            question_quote="Can A and B vote?",
            focus="vote",
            state="supported",
            resource=r,
            claim_id=f"c{i}",
            decision=dict(conclusion=c, relation="resource_scope"),
        )
        for i, (r, c) in enumerate([("A", "yes"), ("B", "no")])
    ]
    plan = task_answer_plan([q], tasks, {"c0", "c1"})
    assert len(plan[0]["subquestions"]) == 1
    assert plan[0]["subquestions"][0]["conclusion"] == "depends"
    assert plan[0]["subquestions"][0]["claim_ids"] == ["c0", "c1"]


def test_unknown_segments_are_not_rewritten_into_valid_question_quotes():
    plan = task_answer_plan([dict(question_id="q", question="Can I export?")], [], set())
    raw = json.dumps(
        dict(
            version=3,
            answers=[
                dict(
                    question_id="q",
                    subquestions=[
                        dict(segment_id="forged", claim_ids=[], conclusion="yes", relation="direct")
                    ],
                )
            ],
        )
    )
    assert restore_task_segments(raw, plan) == raw


def test_repair_diagnostic_keeps_exact_failed_checks_outside_source_facts():
    from types import SimpleNamespace

    from packages.agents.writer import task_execution
    from packages.research.evidence.report_claims import ClaimReview

    review = ClaimReview(
        claim_id="c",
        verdict="unsupported",
        reason="The scope is too broad.",
        checks=[dict(check_id="scope", verdict="unsupported", claim_span="all boards")],
    )
    build = getattr(task_execution, "task_review_diagnostic", None)
    assert callable(build), "Concrete independent review feedback is not passed to task repair"
    row = build(SimpleNamespace(rule_reasons=("operation_binding_required",), review=review))
    assert row["rule_reasons"] == ["operation_binding_required"]
    assert row["review"]["reason"] == review.reason
    assert row["review"]["checks"][0]["claim_span"] == "all boards"
    assert row["purpose"] == "repair_only_not_evidence"


def test_bad_peer_does_not_discard_another_questions_restored_segments():
    plan = task_answer_plan(
        [
            dict(question_id="a", question="Can I export?"),
            dict(question_id="b", question="Can I import?"),
        ],
        [],
        set(),
    )
    raw = json.dumps(
        dict(
            answers=[
                dict(
                    question_id="a",
                    subquestions=[
                        dict(
                            segment_id="segment-0",
                            claim_ids=[],
                            conclusion="unknown",
                            relation="unresolved",
                        )
                    ],
                ),
                dict(question_id="b", subquestions=[None]),
            ]
        )
    )
    restored = json.loads(restore_task_segments(raw, plan))
    assert restored["answers"][0]["subquestions"][0]["question_quote"] == "Can I export?"


def test_model_cannot_replace_two_server_segments_with_one_complete_question():
    question = "Can 3 people use it? Can 2 people use it?"
    tasks = [
        dict(
            question_id="q", question_quote=q, task_id=str(i), focus="source_rule", state="planned"
        )
        for i, q in enumerate(["Can 3 people use it?", "Can 2 people use it?"])
    ]
    plan = task_answer_plan([dict(question_id="q", question=question)], tasks, set())
    raw = json.dumps(
        dict(
            answers=[
                dict(
                    question_id="q",
                    subquestions=[
                        dict(
                            question_quote=question,
                            claim_ids=["c"],
                            conclusion="no",
                            relation="upper_bound",
                        )
                    ],
                )
            ]
        )
    )
    restored = json.loads(restore_task_segments(raw, plan))
    assert not restored["answers"][0]["subquestions"]


@pytest.mark.parametrize("bad_id", [[], {}, None, 3, True])
def test_non_string_question_id_isolated_before_strict_answer_parser(bad_id):
    plan = task_answer_plan([dict(question_id="q", question="Can I export?")], [], set())
    raw = json.dumps(
        dict(
            answers=[
                dict(
                    question_id="q",
                    subquestions=[
                        dict(
                            segment_id="segment-0",
                            claim_ids=[],
                            conclusion="unknown",
                            relation="unresolved",
                        )
                    ],
                ),
                dict(question_id=bad_id, subquestions=[]),
            ]
        )
    )
    restored = json.loads(restore_task_segments(raw, plan))
    assert len(restored["answers"]) == 1
    assert restored["answers"][0]["subquestions"][0]["question_quote"] == "Can I export?"
