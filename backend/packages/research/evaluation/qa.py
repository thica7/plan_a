from __future__ import annotations

from packages.research.evaluation.gaps import (
    quality_gaps_from_admitted_evidence,
    quality_gaps_from_extractions,
)
from packages.research.models import EvidenceItem, ExtractionResult, QualityGap, ResearchBrief


def evaluate_research_quality(
    brief: ResearchBrief,
    extractions: list[ExtractionResult],
    evidence_items: list[EvidenceItem] | None = None,
) -> list[QualityGap]:
    gaps = quality_gaps_from_extractions(brief, extractions)
    if evidence_items is not None:
        gaps.extend(quality_gaps_from_admitted_evidence(brief, extractions, evidence_items))
    return _dedupe_gaps(gaps)


def _dedupe_gaps(gaps: list[QualityGap]) -> list[QualityGap]:
    seen: set[tuple[str, str | None, str | None, str]] = set()
    deduped: list[QualityGap] = []
    for gap in gaps:
        key = (gap.dimension, gap.competitor, gap.field, gap.reason)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(gap)
    return deduped
