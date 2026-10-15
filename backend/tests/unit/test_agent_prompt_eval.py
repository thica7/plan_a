import pytest

from scripts.eval_agent_prompts import score_output


def case(role="comparator", **updates):
    return {
        "role": role,
        "dimension": "pricing",
        "expected_status": "insufficient_evidence",
        "expected_winner": None,
        "allowed_source_ids": ["a", "b"],
        **updates,
    }


def test_eval_rejects_forced_winner_even_with_a_gap_label():
    output = {
        "assessments": {
            "pricing": {"status": "insufficient_evidence", "winner": "A", "source_ids": ["a"]}
        }
    }
    assert not score_output(case(), output)["no_unsupported_winner"]


def test_eval_legacy_tie_is_abstention_without_an_explicit_status():
    score = score_output(case(), {"winner_by_dimension": {"pricing": "tie"}})
    assert score["no_unsupported_winner"]
    assert score["correct_status"] is None


def test_eval_rejects_invented_citations():
    output = {
        "assessments": {
            "pricing": {
                "status": "insufficient_evidence",
                "winner": None,
                "source_ids": ["invented"],
            }
        }
    }
    assert not score_output(case(), output)["citations_valid"]


def test_eval_requires_comparable_winner_to_cite_every_product():
    output = {
        "assessments": {"pricing": {"status": "comparable", "winner": "B", "source_ids": ["b"]}}
    }
    sample = case(expected_status="comparable", expected_winner="B", required_source_ids=["a", "b"])
    assert not score_output(sample, output)["required_evidence_cited"]


@pytest.mark.parametrize(
    "text", ["Price is 1749 USD [source:a]", "Price is 17.49 USD [source:invented]"]
)
def test_writer_eval_detects_numeric_corruption_or_unknown_citation(text):
    sample = case(role="writer", required_text=["17.49"], expected_headings=["## 一句话结论"])
    score = score_output(sample, text)
    assert not (score["required_text_preserved"] and score["citations_valid"])


def test_eval_rejects_completion_without_price_facts():
    assert not score_output(
        case(role="collector", expected_actions=["fetch_page", "web_search"]), {"action": "finish"}
    )["correct_action"]


def test_eval_legacy_not_comparable_text_is_abstention():
    assert score_output(case(), {"winner_by_dimension": {"pricing": "not comparable"}})[
        "no_unsupported_winner"
    ]


def test_new_gap_assessment_requires_null_winner_and_cannot_hide_behind_tie():
    output = {
        "assessments": {
            "pricing": {"status": "insufficient_evidence", "winner": "tie", "source_ids": []}
        }
    }
    assert not score_output(case(), output)["no_unsupported_winner"]


@pytest.mark.parametrize(
    "output", [{"action": "fetch_page", "url": None}, {"action": "web_search", "query": ""}]
)
def test_collector_action_requires_a_usable_target(output):
    assert not score_output(
        case(role="collector", expected_actions=["fetch_page", "web_search"]), output
    )["correct_action"]
