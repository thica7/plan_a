from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from packages.business_intel.entity_resolver import trusted_source_candidates


@dataclass(frozen=True)
class OfficialDocCandidate:
    title: str
    url: str
    rationale: str


def find_official_docs(
    *,
    competitor: str,
    dimension: str,
    homepage_hint: str | None,
) -> list[OfficialDocCandidate]:
    candidates: list[OfficialDocCandidate] = [
        OfficialDocCandidate(
            title=candidate.title,
            url=candidate.url,
            rationale=candidate.rationale,
        )
        for candidate in trusted_source_candidates(competitor, dimension)
    ]
    if not homepage_hint:
        return candidates
    parsed = urlparse(homepage_hint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return candidates
    base = f"{parsed.scheme}://{parsed.netloc}"
    paths = _dimension_paths(dimension)
    for path in paths:
        candidates.append(
            OfficialDocCandidate(
                title=f"{competitor} official {dimension} page",
                url=urljoin(base, path),
                rationale=f"Derived from planner homepage_hint and {dimension} skill.",
            )
        )
    return _dedupe_candidates(candidates)


def _dimension_paths(dimension: str) -> list[str]:
    key = dimension.casefold()
    if "pricing" in key:
        return ["/pricing", "/plans", "/enterprise"]
    if "security" in key:
        return ["/security", "/trust", "/compliance"]
    if "integration" in key:
        return ["/integrations", "/developers", "/docs"]
    if "persona" in key:
        return ["/customers", "/case-studies", "/use-cases"]
    return ["/features", "/product", "/docs", "/changelog"]


def _dedupe_candidates(candidates: list[OfficialDocCandidate]) -> list[OfficialDocCandidate]:
    seen: set[str] = set()
    deduped: list[OfficialDocCandidate] = []
    for candidate in candidates:
        key = candidate.url.rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped
