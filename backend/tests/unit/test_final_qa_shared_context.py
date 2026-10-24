"""Complete per-question contexts can be shared without hiding unsent findings."""

import importlib
import json


def batches(rows):
    module = importlib.import_module("packages.agents.qa.question_reconciliation")
    pack = getattr(module, "final_review_batches", None)
    assert callable(pack), "Final QA still repeats complete contexts per finding"
    return pack(rows, "basis", max_bytes=6000, max_batches=2)


def candidate(i, q="q", size=3000):
    return dict(
        issue_id=f"issue-{i}",
        finding=f"Q: condition {i} remains unverified.",
        question_id=q,
        question="Can the assigned role export this board?",
        answer=dict(status="unverified", claim_ids=["c"], answer=""),
        claims=[dict(id="c", text="x" * size, fact_ids=["f"], source_ids=["s"])],
        diagnostic_only=True,
        support_digest=f"digest-{i}",
    )


def test_multiple_findings_share_the_same_whole_question_and_support_once():
    rows = [candidate(i) for i in range(5)]
    packed, omitted = batches(rows)
    assert not omitted and len(packed) == 1
    payload = packed[0]
    assert len(json.dumps(payload, ensure_ascii=False).encode()) < 6000
    assert len(payload["question_contexts"]) == 1
    context = next(iter(payload["question_contexts"].values()))
    assert context["claims"] == rows[0]["claims"]
    assert [r["issue_id"] for r in payload["findings"]] == [r["issue_id"] for r in rows]


def test_two_distinct_large_contexts_use_two_bounded_calls():
    packed, omitted = batches([candidate(0, "a", 4000), candidate(1, "b", 4000)])
    assert len(packed) == 2 and not omitted


def test_oversized_whole_finding_is_retained_as_unsent_without_truncation():
    oversized = dict(candidate(1), finding="condition " * 1000)
    packed, omitted = batches([candidate(0), oversized])
    assert omitted == ["issue-1"]
    assert sum(len(b["findings"]) for b in packed) == 1
