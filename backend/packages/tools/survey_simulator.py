from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class InterviewRecord:
    respondent: str
    role: str
    summary: str
    content_hash: str


def survey_simulator(
    *,
    topic: str,
    competitor: str,
    dimension: str,
    qa_feedback: list[dict[str, object]] | None = None,
) -> list[InterviewRecord]:
    feedback_hint = ""
    if qa_feedback:
        feedback_hint = f" Redo focus: {qa_feedback[0].get('problem', '')}"
    summary = (
        f"Synthetic interview note for {competitor} in {topic}: proxy respondents include "
        "an individual developer testing daily productivity, a team technical lead planning "
        "pull request workflow rollout, and an enterprise platform buyer reviewing governance. "
        f"They evaluate {dimension} through workflow fit, onboarding effort, migration cost, "
        "security controls, budget approval, context quality, and switching risk."
        f"{feedback_hint}"
    )
    return [
        InterviewRecord(
            respondent=f"{competitor} target-user proxy",
            role="buyer/user persona synthesizer",
            summary=summary,
            content_hash=hashlib.sha256(summary.encode("utf-8")).hexdigest()[:16],
        )
    ]
