from __future__ import annotations

from typing import Any


async def run_enrichment(
    service: Any,
    record: Any,
    dimensions: list[str],
    competitors: list[str],
) -> None:
    await service._run_survey_interview_enrichment(record, dimensions, competitors)
