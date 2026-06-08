from __future__ import annotations

from dataclasses import dataclass, field

from packages.research.discovery.ranking import canonical_url
from packages.research.models import CapturedPage, SourceCandidate


@dataclass
class CaptureCache:
    pages_by_url: dict[str, CapturedPage] = field(default_factory=dict)
    hit_count: int = 0
    miss_count: int = 0

    def get(self, candidate: SourceCandidate) -> CapturedPage | None:
        page = self.pages_by_url.get(canonical_url(candidate.url))
        if page is None:
            self.miss_count += 1
            return None
        self.hit_count += 1
        return _rebind_page_to_candidate(page, candidate)

    def put(self, candidate: SourceCandidate, page: CapturedPage) -> None:
        self.pages_by_url[canonical_url(candidate.url)] = page


def _rebind_page_to_candidate(page: CapturedPage, candidate: SourceCandidate) -> CapturedPage:
    payload = page.model_dump(mode="python")
    payload.pop("id", None)
    payload["candidate_id"] = candidate.id
    payload["requested_url"] = candidate.url
    return CapturedPage.model_validate(payload)
