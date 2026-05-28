from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ExtractedFact:
    fact: str
    source_id: str | None
    dimension: str
    confidence: float
    content_hash: str


def extract_facts(
    text: str,
    *,
    dimension: str,
    source_id: str | None = None,
    max_facts: int = 5,
) -> list[ExtractedFact]:
    normalized = _collapse_space(text)
    if not normalized:
        return []
    candidates = _sentence_candidates(normalized)
    ranked = sorted(
        candidates,
        key=lambda sentence: (
            _dimension_score(sentence, dimension),
            min(len(sentence), 240),
        ),
        reverse=True,
    )
    facts: list[ExtractedFact] = []
    seen: set[str] = set()
    for sentence in ranked:
        clean = sentence.strip(" -:\t")
        if len(clean) < 18:
            continue
        key = clean.casefold()
        if key in seen:
            continue
        seen.add(key)
        score = _dimension_score(clean, dimension)
        facts.append(
            ExtractedFact(
                fact=clean[:420],
                source_id=source_id,
                dimension=dimension,
                confidence=min(0.95, 0.55 + score * 0.1),
                content_hash=hashlib.sha256(clean.encode("utf-8", errors="ignore")).hexdigest()[
                    :16
                ],
            )
        )
        if len(facts) >= max_facts:
            break
    return facts


def _sentence_candidates(text: str) -> list[str]:
    chunks = re.split(r"(?<=[.!?])\s+|\n+|(?<=。)\s*", text)
    return [chunk for chunk in chunks if chunk.strip()]


def _dimension_score(sentence: str, dimension: str) -> int:
    normalized = sentence.casefold()
    dimension_key = dimension.casefold()
    if "pricing" in dimension_key:
        terms = [
            "pricing",
            "price",
            "cost",
            "plan",
            "tier",
            "billing",
            "$",
            "usd",
            "per user",
            "per seat",
        ]
    elif "persona" in dimension_key or "user" in dimension_key:
        terms = [
            "customer",
            "user",
            "persona",
            "developer",
            "team",
            "enterprise",
            "use case",
            "case study",
        ]
    else:
        terms = [
            "feature",
            "supports",
            "includes",
            "api",
            "model",
            "context",
            "integration",
            "workflow",
        ]
    return sum(1 for term in terms if term in normalized)


def _collapse_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
