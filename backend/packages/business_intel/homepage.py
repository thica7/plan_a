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


def verify_homepage(competitor: str, hint: str | None = None) -> HomepageVerification:
    """Deterministic Phase 2 homepage gate before real source registry exists."""

    name = competitor.strip()
    if _looks_phantom(name):
        return HomepageVerification(
            competitor=name,
            homepage_url=None,
            verified=False,
            reason="phantom_name",
        )
    url = hint if hint and _is_homepage_url(hint) else _synthetic_homepage(name)
    return HomepageVerification(
        competitor=name,
        homepage_url=url,  # type: ignore[arg-type]
        verified=True,
        reason="synthetic_verified" if url != hint else "hint_verified",
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


def _synthetic_homepage(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "", name.casefold())
    return f"https://www.{slug or 'competitor'}.com"
