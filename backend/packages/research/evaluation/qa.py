from __future__ import annotations

from packages.research.evaluation.gaps import quality_gaps_from_extractions
from packages.research.models import ExtractionResult, QualityGap, ResearchBrief


def evaluate_research_quality(
    brief: ResearchBrief,
    extractions: list[ExtractionResult],
) -> list[QualityGap]:
    return quality_gaps_from_extractions(brief, extractions)
