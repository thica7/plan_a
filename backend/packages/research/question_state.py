"""Stage-local diagnostics; these states never authorize publication."""


def question_state(question, *, reviewed_tasks=(), answer_status=None):
    if question.get("evidence_gap") == "context_budget_exceeded":
        evidence = "context_omitted"
    elif question.get("evidence_gaps") or question.get("minimum_evidence_missing"):
        evidence = "evidence_unverified"
    elif "evidence_gaps" in question:
        evidence = "source_context_available"
    else:
        evidence = "not_assessed"
    return dict(
        question_id=question["question_id"],
        evidence_state=evidence,
        delivery_state="reviewed_local_answers" if reviewed_tasks else "not_reviewed",
        whole_question_status=answer_status or "not_reviewed",
        missing_core_fact_ids=list(question.get("missing_core_fact_ids", ())),
        missing_exception_fact_ids=list(question.get("missing_exception_fact_ids", ())),
    )
