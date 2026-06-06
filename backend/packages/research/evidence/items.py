from __future__ import annotations

from packages.research.evidence.admission import admit_evidence_items
from packages.research.models import EvidenceItem, ExtractionResult


def evidence_items_from_extractions(
    extractions: list[ExtractionResult],
    *,
    min_accept_confidence: float = 0.35,
) -> list[EvidenceItem]:
    return admit_evidence_items(
        extractions,
        min_accept_confidence=min_accept_confidence,
    )
