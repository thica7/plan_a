from packages.memory import PreferenceMemoryStore
from packages.schema.enterprise import UserFeedbackRecord


def test_preference_memory_redacts_feedback_and_recalls_confirmed_candidates() -> None:
    memory = PreferenceMemoryStore.in_memory()
    feedback = memory.add_feedback(
        UserFeedbackRecord(
            id="",
            workspace_id="workspace-a",
            project_id="project-a",
            user_id="analyst-1",
            feedback_type="preference",
            target_type="report",
            target_id="report-1",
            message=(
                "Email user@example.com. Prefer official pricing docs, concise battlecard "
                "tables, explicit evidence gap risks, and QA release gate rules that must "
                "block redo regressions."
            ),
            tags=[],
        )
    )

    candidates = [
        memory.upsert_candidate(candidate)
        for candidate in memory.extract_candidates(feedback, auto_confirm=True)
    ]
    recall = memory.recall(
        workspace_id="workspace-a",
        project_id="project-a",
        query="pricing source risk",
        mark_used=True,
    )
    stats = memory.stats(workspace_id="workspace-a", project_id="project-a")

    assert feedback.id.startswith("feedback-")
    assert "[redacted:email]" in feedback.message
    assert feedback.redaction_counts["email"] == 1
    assert {candidate.kind for candidate in candidates} >= {
        "preferred_dimension",
        "source_preference",
        "writing_preference",
        "risk_preference",
        "failure_pattern",
        "qa_policy",
    }
    assert any(candidate.kind == "qa_policy" for candidate in recall.candidates)
    assert recall.candidates
    assert recall.candidates[0].status == "confirmed"
    assert recall.candidates[0].used_count == 1
    assert recall.prompt_context[0].startswith("[")
    assert stats.feedback_count == 1
    assert stats.confirmed_candidate_count == len(candidates)


def test_preference_memory_requires_confirmation_before_default_recall() -> None:
    memory = PreferenceMemoryStore.in_memory()
    feedback = memory.add_feedback(
        UserFeedbackRecord(
            id="",
            workspace_id="workspace-a",
            project_id="project-a",
            user_id="analyst-1",
            feedback_type="correction",
            target_type="claim",
            target_id="claim-1",
            message="Correction: persona analysis must not use unsupported claims.",
            tags=["persona"],
        )
    )
    [candidate] = [
        item
        for item in (
            memory.upsert_candidate(candidate)
            for candidate in memory.extract_candidates(feedback)
        )
        if item.kind == "correction"
    ]

    hidden = memory.recall(
        workspace_id="workspace-a",
        project_id="project-a",
        query="persona correction",
    )
    visible = memory.recall(
        workspace_id="workspace-a",
        project_id="project-a",
        query="persona correction",
        include_unconfirmed=True,
    )
    confirmed = memory.update_candidate_status(candidate.id, "confirmed")
    recalled = memory.recall(
        workspace_id="workspace-a",
        project_id="project-a",
        query="persona correction",
    )

    assert hidden.candidates == []
    assert visible.candidates[0].status == "candidate"
    assert confirmed is not None
    assert confirmed.status == "confirmed"
    assert recalled.candidates[0].id == candidate.id
