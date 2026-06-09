from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewSearchPlan:
    queries: list[str]
    rationale: str


def search_review_site_queries(*, competitor: str, topic: str) -> ReviewSearchPlan:
    return ReviewSearchPlan(
        queries=[
            f"{competitor} {topic} reviews pros cons G2",
            f"{competitor} {topic} Capterra reviews",
            f"{competitor} {topic} customer complaints alternatives",
        ],
        rationale="Review skill routes through public review and comparison pages.",
    )
