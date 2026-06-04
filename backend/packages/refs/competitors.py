from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from packages.identity import normalize_key


class CompetitorLike(Protocol):
    id: str
    name: str
    normalized_name: str
    aliases: list[str]


@dataclass(frozen=True)
class CompetitorRef:
    id: str
    name: str
    aliases: tuple[str, ...] = ()

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(
            key for key in [self.id, self.name, *self.aliases] if normalize_competitor_key(key)
        )


class CompetitorResolver:
    def __init__(self, competitors: list[CompetitorRef]) -> None:
        self._by_id = {item.id: item for item in competitors}
        self._id_by_key: dict[str, str] = {}
        for competitor in competitors:
            for key in competitor.keys:
                self._id_by_key[normalize_competitor_key(key)] = competitor.id

    @classmethod
    def from_records(cls, competitors: list[CompetitorLike]) -> CompetitorResolver:
        return cls(
            [
                CompetitorRef(
                    id=item.id,
                    name=item.name,
                    aliases=tuple([item.normalized_name, *item.aliases]),
                )
                for item in competitors
            ]
        )

    def resolve_id(self, value: str | None, *, fallback: str | None = None) -> str:
        if not value:
            return fallback or ""
        key = normalize_competitor_key(value)
        return self._id_by_key.get(key) or fallback or key

    def display_name(self, competitor_id: str) -> str:
        return self._by_id.get(competitor_id, CompetitorRef(competitor_id, competitor_id)).name

    def alias_map(self) -> dict[str, str]:
        return dict(self._id_by_key)


def build_competitor_alias_map(competitors: list[CompetitorLike]) -> dict[str, str]:
    return CompetitorResolver.from_records(competitors).alias_map()


def normalize_competitor_key(value: str | None) -> str:
    return normalize_key(value)
