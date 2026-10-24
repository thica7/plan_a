"""Evidence availability and answer delivery are separate stage-local states."""

import importlib
import importlib.util


def state(row, **kwargs):
    spec = importlib.util.find_spec("packages.research.question_state")
    assert spec is not None, "Agents do not yet share a question-state vocabulary"
    return importlib.import_module(spec.name).question_state(row, **kwargs)


def test_context_omission_is_not_reclassified_as_missing_source_or_answered():
    result = state(
        dict(
            question_id="q",
            evidence_gap="context_budget_exceeded",
            evidence_gaps=["original_not_sent"],
            missing_core_fact_ids=["f"],
        ),
        reviewed_tasks=[dict(task_id="t")],
        answer_status="unverified",
    )
    assert result["evidence_state"] == "context_omitted"
    assert result["delivery_state"] == "reviewed_local_answers"
    assert result["whole_question_status"] == "unverified"
    assert result["missing_core_fact_ids"] == ["f"]


def test_available_context_never_grants_answer_completion():
    result = state(dict(question_id="q", evidence_gaps=[], evidence_gap=None))
    assert result["evidence_state"] == "source_context_available"
    assert result["delivery_state"] == "not_reviewed"
    assert result["whole_question_status"] == "not_reviewed"
