from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from packages.business_intel.entity_resolver import trusted_source_candidates
from packages.research.discovery.constants import SOURCE_ORIGIN_PRIORITY


@dataclass(frozen=True)
class OfficialDocCandidate:
    title: str
    url: str
    rationale: str
    origin: str = "trusted_registry"
    rank: int = 0
    confidence: float = 0.95


def find_official_docs(
    *,
    competitor: str,
    dimension: str,
    homepage_hint: str | None,
) -> list[OfficialDocCandidate]:
    candidates: list[OfficialDocCandidate] = []
    for rank, candidate in enumerate(trusted_source_candidates(competitor, dimension)):
        candidates.append(
            OfficialDocCandidate(
                title=candidate.title,
                url=candidate.url,
                rationale=candidate.rationale,
                origin="trusted_registry",
                rank=rank,
                confidence=0.98,
            )
        )
    if not homepage_hint:
        return candidates
    parsed = urlparse(homepage_hint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return candidates
    base = f"{parsed.scheme}://{parsed.netloc}"
    paths = _dimension_paths(dimension)
    derived_confidence = 0.45 if candidates else 0.62
    base_rank = len(candidates)
    for offset, path in enumerate(paths):
        candidates.append(
            OfficialDocCandidate(
                title=f"{competitor} official {dimension} page",
                url=urljoin(base, path),
                rationale=f"Derived from planner homepage_hint and {dimension} skill.",
                origin="homepage_derived",
                rank=base_rank + offset,
                confidence=derived_confidence,
            )
        )
    return _dedupe_candidates(candidates)


def _dimension_paths(dimension: str) -> list[str]:
    key = dimension.casefold()
    if "pricing" in key:
        return [
            "/pricing",
            "/plans",
            "/enterprise",
            "/business",
            "/docs/pricing",
            "/api/pricing",
        ]
    if "security" in key:
        return ["/security", "/trust", "/compliance", "/privacy", "/enterprise/security"]
    if "integration" in key:
        return ["/integrations", "/developers", "/docs", "/api", "/changelog"]
    if "persona" in key:
        return [
            "/customers",
            "/customer-stories",
            "/case-studies",
            "/use-cases",
            "/solutions",
            "/enterprise",
            "/business",
            "/docs",
        ]
    return [
        "/features",
        "/product",
        "/products",
        "/docs",
        "/docs/models",
        "/models",
        "/changelog",
        "/news",
        "/blog",
    ]


def _dedupe_candidates(candidates: list[OfficialDocCandidate]) -> list[OfficialDocCandidate]:
    best_by_url: dict[str, OfficialDocCandidate] = {}
    for candidate in candidates:
        key = candidate.url.rstrip("/")
        existing = best_by_url.get(key)
        if existing is None or _candidate_key(candidate) > _candidate_key(existing):
            best_by_url[key] = candidate
    return sorted(best_by_url.values(), key=_candidate_key, reverse=True)


def _candidate_key(candidate: OfficialDocCandidate) -> tuple[int, float, int, str]:
    return (
        SOURCE_ORIGIN_PRIORITY.get(candidate.origin, 0),
        candidate.confidence,
        -candidate.rank,
        candidate.url,
    )
