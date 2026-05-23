from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin, urlparse


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
    if not homepage_hint:
        return []
    parsed = urlparse(homepage_hint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return []
    base = f"{parsed.scheme}://{parsed.netloc}"
    paths = _dimension_paths(dimension)
    return [
        OfficialDocCandidate(
            title=f"{competitor} official {dimension} page",
            url=urljoin(base, path),
            rationale=f"Derived from planner homepage_hint and {dimension} skill.",
        )
        for path in paths
    ]


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
