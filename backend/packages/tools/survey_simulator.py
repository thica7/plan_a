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
        f"Synthetic interview note for {competitor} in {topic}: buyers evaluate {dimension} "
        f"through fit with workflow, onboarding effort, and switching risk.{feedback_hint}"
    )
    return [
        InterviewRecord(
            respondent=f"{competitor} target-user proxy",
            role="buyer/user persona synthesizer",
            summary=summary,
            content_hash=hashlib.sha256(summary.encode("utf-8")).hexdigest()[:16],
        )
    ]
