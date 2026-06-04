from __future__ import annotations

import re
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, HttpUrl


class HomepageVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor: str
    homepage_url: HttpUrl | None = None
    verified: bool
    reason: str


CURATED_HOMEPAGES: dict[str, str] = {
    "cursor": "https://cursor.com",
    "windsurf": "https://windsurf.com",
    "githubcopilot": "https://github.com/features/copilot",
    "claudecode": "https://www.anthropic.com/product/claude-code",
}


def verify_homepage(competitor: str, hint: str | None = None) -> HomepageVerification:
    """Resolve a verified homepage only from curated or explicitly trusted identity data.

    Unknown homepage guesses are returned as unverified candidates at most. This keeps
    synthetic domains out of the official-source pipeline.
    """

    name = competitor.strip()
    if _looks_phantom(name):
        return HomepageVerification(
            competitor=name,
            homepage_url=None,
            verified=False,
            reason="phantom_name",
        )

    curated = CURATED_HOMEPAGES.get(_registry_key(name))
    if curated is not None:
        return HomepageVerification(
            competitor=name,
            homepage_url=curated,  # type: ignore[arg-type]
            verified=True,
            reason="curated_registry",
        )

    if hint and _is_homepage_url(hint):
        return HomepageVerification(
            competitor=name,
            homepage_url=hint,  # type: ignore[arg-type]
            verified=False,
            reason="hint_candidate_unverified",
        )

    return HomepageVerification(
        competitor=name,
        homepage_url=None,
        verified=False,
        reason="no_verified_homepage",
    )


def verify_homepages(
    competitors: list[str],
    hints: dict[str, str] | None = None,
) -> dict[str, HomepageVerification]:
    hints = hints or {}
    return {
        competitor: verify_homepage(competitor, hints.get(competitor))
        for competitor in competitors
    }


def _looks_phantom(name: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")
    return any(token in normalized for token in ("fake", "not_exists", "nonexistent", "phantom"))


def _is_homepage_url(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    return "google.com/search" not in value.casefold()


def _registry_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.casefold())
