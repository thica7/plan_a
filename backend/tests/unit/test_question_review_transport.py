"""Readable v6 final-QA transport keeps complete question-owned requests."""

import importlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest


def transport():
    name = "packages.agents.qa.question_review_transport"
    assert importlib.util.find_spec(name), "v6 needs its own readable JSON transport"
    return importlib.import_module(name)


def candidate(issue, question):
    return dict(
        issue_id=issue,
        question_id=question,
        question="Complete scenario?",
        request_context={"parents": [{"text": "unless A AND B"}]},
        claims=[{"quote": "Permission does not impose an obligation."}],
    )


def test_plain_json_preserves_complete_content_without_reference_decoding():
    module = transport()
    value = dict(findings=[candidate("price", "price"), candidate("guest", "guest")])
    raw = module.dumps(value)
    assert json.loads(raw) == value
    assert module.loads(raw, expected=deepcopy(value)) == value
    assert "unless A AND B" in raw
    assert set(json.loads(raw)) == {"findings"}


@pytest.mark.parametrize(
    "raw",
    [
        '{"x":1,"x":1}',
        '{"nested":{"x":1,"x":1}}',
        '{"x":NaN}',
        '{"x":Infinity}',
        '{"x":-Infinity}',
        '{"x":1e999}',
        '{ "x":1}',
        '{"z":1,"a":2}',
        '{"x":"\\u4e2d"}',
    ],
)
def test_plain_loads_rejects_duplicate_nonfinite_and_noncanonical_json(raw):
    with pytest.raises(ValueError):
        transport().loads(raw)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), {1: "ambiguous"}, (1, 2)])
def test_plain_dumps_rejects_non_json_or_nonfinite_values(value):
    with pytest.raises(ValueError):
        transport().dumps(value)


def test_plain_replay_requires_complete_server_reconstruction():
    module = transport()
    expected = candidate("price", "price")
    for changed in [
        dict(expected, question_id="guest"),
        dict(expected, request_context={"parents": [{"text": "unless A OR B"}]}),
        dict(expected, claims=[]),
    ]:
        with pytest.raises(ValueError):
            module.loads(module.dumps(changed), expected=expected)


def test_each_batch_contains_one_question_and_unmapped_is_separate():
    rows = [
        candidate("price", "price"),
        candidate("guest", "guest"),
        candidate("unknown", "unmapped"),
        candidate("price-old", "price"),
    ]
    batches, omitted = transport().final_review_batches(
        rows, "basis", max_bytes=8192, max_batches=6
    )
    assert not omitted
    assert [[r["issue_id"] for r in b["findings"]] for b in batches] == [
        ["price", "price-old"],
        ["guest"],
        ["unknown"],
    ]
    assert all(len({r["question_id"] for r in b["findings"]}) == 1 for b in batches)


def test_whole_item_byte_boundary_and_six_batch_window_are_explicit():
    module = transport()
    rows = [candidate(str(i), str(i)) for i in range(7)]
    exact = len(
        (
            "\nJSON:\n" + module.dumps(dict(version=1, basis_hash="basis", findings=rows[:1]))
        ).encode()
    )
    assert module.final_review_batches(rows[:1], "basis", max_bytes=exact, max_batches=6)[1] == []
    assert module.final_review_batches(rows[:1], "basis", max_bytes=exact - 1, max_batches=6) == (
        [],
        ["0"],
    )
    batches, omitted = module.final_review_batches(rows, "basis", max_bytes=8192, max_batches=6)
    assert len(batches) == 6 and omitted == ["6"]
    assert module.final_review_batches(rows[-1:], "basis", max_bytes=8192, max_batches=6)[1] == []


def test_same_question_complete_context_is_readable_once_with_named_binding():
    module = transport()
    row = candidate("current", "guest")
    row["claims"][0]["quote"] = "Full original condition. " * 250
    other = dict(deepcopy(row), issue_id="history", finding="A historical objection.")
    batches, omitted = module.final_review_batches(
        [row, other], "basis", max_bytes=8192, max_batches=6
    )
    assert omitted == [] and len(batches) == 1
    payload = json.loads(module.dumps(batches[0]))
    context = payload["question_contexts"]["current"]
    assert context["claims"] == row["claims"]
    assert context["request_context"] == row["request_context"]
    for finding, expected in zip(payload["findings"], [row, other], strict=True):
        assert finding["context_id"] == "current"
        assert finding["question_id"] == expected["question_id"]
        assert {**context, **{k: v for k, v in finding.items() if k != "context_id"}} == expected
    assert module.dumps(payload).count("Full original condition. ") == 250


@pytest.mark.parametrize("field", ["question", "request_context", "claims"])
def test_different_complete_contexts_never_share_a_named_binding(field):
    row = candidate("current", "guest")
    row["claims"][0]["quote"] = "Full original condition. " * 250
    other = dict(deepcopy(row), issue_id="history")
    other[field] = "Changed parent, condition or original."
    batches, omitted = transport().final_review_batches(
        [row, other], "basis", max_bytes=8192, max_batches=6
    )
    assert not omitted and all("question_contexts" not in b for b in batches)
    assert [r for b in batches for r in b["findings"]] == [row, other]


def test_unrecognized_row_fields_remain_each_findings_own_data():
    row = candidate("current", "guest")
    other = dict(deepcopy(row), issue_id="history", future_field="Different local condition.")
    batches, omitted = transport().final_review_batches(
        [row, other], "basis", max_bytes=8192, max_batches=6
    )
    assert not omitted
    assert "future_field" not in batches[0]["question_contexts"]["current"]
    assert "future_field" not in batches[0]["findings"][0]
    assert batches[0]["findings"][1]["future_field"] == other["future_field"]


def test_preexisting_context_id_data_is_never_overwritten_by_named_binding():
    row = candidate("current", "guest")
    other = dict(deepcopy(row), issue_id="history", context_id="preexisting-local-data")
    batches, omitted = transport().final_review_batches(
        [row, other], "basis", max_bytes=8192, max_batches=6
    )
    assert not omitted and batches[0]["findings"] == [row, other]
    assert "question_contexts" not in batches[0]


@pytest.mark.parametrize("product", ["bitwarden", "1password"])
def test_complete_public_v5_candidate_fits_readable_v6_without_losing_conditions(product):
    path = Path(__file__).resolve().parents[1] / "fixtures/final_question_v5_candidates.json"
    row = json.loads(path.read_text())[product]
    batches, omitted = transport().final_review_batches(
        [row], "0" * 64, max_bytes=8192, max_batches=6
    )
    assert omitted == [] and batches[0]["findings"] == [row]
    assert len(("\nJSON:\n" + transport().dumps(batches[0])).encode()) <= 8192
