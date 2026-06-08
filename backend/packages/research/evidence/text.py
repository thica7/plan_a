from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from packages.research.evidence.normalization import normalized_summary_from_source
from packages.research.extraction.quality import (
    clean_evidence_quote,
    quote_quality_problem,
    text_noise_problem,
)


def source_business_snippet(
    source: object,
    *,
    dimension: str = "",
    limit: int = 260,
) -> str:
    source_dimension = dimension or _source_field(source, "dimension")
    normalized = normalized_summary_from_source(source, dimension=source_dimension, limit=limit)
    if normalized:
        return normalized
    snippet = " ".join(_source_field(source, "snippet").split())
    if not snippet:
        return ""
    if quote_quality_problem(snippet, dimension=source_dimension):
        return ""
    cleaned = clean_evidence_quote(snippet, dimension=source_dimension, max_chars=limit)
    if not cleaned or quote_quality_problem(cleaned, dimension=source_dimension):
        return ""
    return cleaned


def deterministic_claim_text_from_source(
    *,
    competitor: str,
    dimension: str,
    source: object,
    limit: int = 240,
) -> str:
    snippet = source_business_snippet(source, dimension=dimension, limit=limit)
    if snippet:
        return f"{competitor} {dimension}: {snippet}"
    title = " ".join(_source_field(source, "title").split())
    if title:
        return (
            f"{competitor} has collected {dimension} evidence from {title}, "
            "but the page needs a cleaner extracted snippet before publishable use."
        )
    return (
        f"{competitor} has collected {dimension} evidence, but the source needs "
        "cleaner extracted text before publishable use."
    )


def publishable_text_noise_problem(text: str) -> str | None:
    return text_noise_problem(text)


def _source_field(source: object, field: str) -> str:
    if isinstance(source, Mapping):
        return str(source.get(field) or "")
    value: Any = getattr(source, field, "")
    return str(value or "")
