"""Structured source-claim extraction for KB/live consistency gates."""

from __future__ import annotations

import re
from dataclasses import dataclass

from packages.schema.models import RawSource

CONTRADICTION_FACT_TERMS = (
    "sso",
    "saml",
    "scim",
    "soc 2",
    "iso",
    "audit log",
    "api",
    "free plan",
    "enterprise plan",
    "self-hosted",
)
PRICING_PLAN_TERMS = ("free", "pro", "team", "teams", "business", "enterprise")
PRICE_AMOUNT_RE = re.compile(
    r"(?:\$|usd\s*)(?P<prefix>\d+(?:\.\d+)?)|"
    r"(?P<suffix>\d+(?:\.\d+)?)\s*(?:usd|dollars?)",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class StructuredSourceClaim:
    source_id: str
    competitor: str
    dimension: str
    subject: str
    predicate: str
    value: str
    polarity: str
    claim_area: str
    position: str
    is_kb_reuse: bool


@dataclass(frozen=True)
class StructuredSourceConflict:
    claim_area: str
    source_ids_by_position: dict[str, list[str]]
    claims: list[StructuredSourceClaim]

    def to_qa_payload(self) -> dict[str, dict[str, list[str]] | str]:
        return {
            "claim_area": self.claim_area,
            "source_ids_by_position": self.source_ids_by_position,
        }


def extract_structured_fact_positions(
    text: str,
    *,
    dimension: str = "",
) -> list[tuple[str, str]]:
    """Extract deterministic fact positions such as support:sso or price:pro:month."""
    normalized = text.casefold()
    positions = _binary_fact_positions(normalized)
    if "pricing" in dimension.casefold():
        positions.extend(_pricing_fact_positions(normalized))
    return positions


def extract_structured_source_claims(
    sources: list[RawSource],
    *,
    dimension: str,
) -> list[StructuredSourceClaim]:
    claims: list[StructuredSourceClaim] = []
    for source in sources:
        text = f"{source.title}\n{source.snippet}".casefold()
        positions = extract_structured_fact_positions(text, dimension=dimension)
        claims.extend(_claims_from_positions(source, positions))
    return claims


def find_structured_source_conflicts(
    sources: list[RawSource],
    *,
    dimension: str,
) -> list[StructuredSourceConflict]:
    claims = extract_structured_source_claims(sources, dimension=dimension)
    by_claim_area: dict[str, dict[str, list[StructuredSourceClaim]]] = {}
    for claim in claims:
        by_claim_area.setdefault(claim.claim_area, {}).setdefault(claim.position, []).append(claim)

    conflicts: list[StructuredSourceConflict] = []
    for claim_area, positions in by_claim_area.items():
        if len(positions) < 2:
            continue
        flattened = [claim for grouped in positions.values() for claim in grouped]
        has_kb = any(claim.is_kb_reuse for claim in flattened)
        has_live = any(not claim.is_kb_reuse for claim in flattened)
        if not (has_kb and has_live):
            continue
        conflicts.append(
            StructuredSourceConflict(
                claim_area=claim_area,
                source_ids_by_position={
                    position: sorted({claim.source_id for claim in grouped})
                    for position, grouped in positions.items()
                },
                claims=flattened,
            )
        )
    return conflicts


def _claims_from_positions(
    source: RawSource,
    positions: list[tuple[str, str]],
) -> list[StructuredSourceClaim]:
    claims: list[StructuredSourceClaim] = []
    for claim_area, position in positions:
        if claim_area.startswith("support:"):
            term = claim_area.removeprefix("support:")
            claims.append(
                _claim(
                    source,
                    predicate=f"supports:{term}",
                    value="true" if position == "supported" else "false",
                    polarity="positive" if position == "supported" else "negative",
                    claim_area=claim_area,
                    position=position,
                )
            )
        elif claim_area.startswith("price:"):
            claims.append(
                _claim(
                    source,
                    predicate=claim_area,
                    value=position,
                    polarity="observed",
                    claim_area=claim_area,
                    position=position,
                )
            )
    return claims


def _binary_fact_positions(text: str) -> list[tuple[str, str]]:
    positions: list[tuple[str, str]] = []
    for term in CONTRADICTION_FACT_TERMS:
        start = text.find(term)
        if start < 0:
            continue
        window = text[max(0, start - 90) : start + len(term) + 90]
        claim_area = f"support:{term}"
        if _negative_position_window(window, term):
            positions.append((claim_area, "unsupported"))
        elif _positive_position_window(window):
            positions.append((claim_area, "supported"))
    return positions


def _pricing_fact_positions(text: str) -> list[tuple[str, str]]:
    positions: list[tuple[str, str]] = []
    for match in PRICE_AMOUNT_RE.finditer(text):
        value = match.group("prefix") or match.group("suffix")
        if not value:
            continue
        window = text[max(0, match.start() - 80) : match.end() + 80]
        plan = next((term for term in PRICING_PLAN_TERMS if term in window), "")
        if not plan:
            continue
        cadence = "year" if any(term in window for term in ("year", "annual")) else "month"
        normalized_amount = value.rstrip("0").rstrip(".") if "." in value else value
        positions.append((f"price:{plan}:{cadence}", f"${normalized_amount}/{cadence}"))
    if "free plan" in text or "free tier" in text:
        if _negative_position_window(text, "free plan"):
            positions.append(("support:free plan", "unsupported"))
        elif _positive_position_window(text):
            positions.append(("support:free plan", "supported"))
    return positions


def _claim(
    source: RawSource,
    *,
    predicate: str,
    value: str,
    polarity: str,
    claim_area: str,
    position: str,
) -> StructuredSourceClaim:
    return StructuredSourceClaim(
        source_id=source.id,
        competitor=source.competitor,
        dimension=source.dimension,
        subject=source.competitor,
        predicate=predicate,
        value=value,
        polarity=polarity,
        claim_area=claim_area,
        position=position,
        is_kb_reuse=bool(
            source.candidate_origin == "rag_kb" or source.metadata.get("kb_retrieved")
        ),
    )


def _positive_position_window(window: str) -> bool:
    return any(
        marker in window
        for marker in (
            "supports",
            "support ",
            "includes",
            "include ",
            "available",
            "offers",
            "provides",
            "has ",
        )
    )


def _negative_position_window(window: str, term: str) -> bool:
    return any(
        marker in window
        for marker in (
            f"does not support {term}",
            f"doesn't support {term}",
            f"not support {term}",
            f"no {term}",
            f"without {term}",
            f"{term} is not available",
            f"{term} unavailable",
            f"{term} removed",
            f"{term} deprecated",
            f"{term} discontinued",
            f"no longer supports {term}",
        )
    )