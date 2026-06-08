from __future__ import annotations

from pathlib import Path
from typing import Self

from packages.schema.models import SkillSpec
from packages.skills.base import SkillDefinition


class SkillRegistry:
    def __init__(self, skills: dict[str, SkillSpec]) -> None:
        self._skills = skills

    @classmethod
    def from_default_path(cls) -> Self:
        return cls.from_path(Path(__file__).parent)

    @classmethod
    def from_path(cls, path: Path) -> Self:
        skills: dict[str, SkillSpec] = {}
        for yaml_path in sorted(path.glob("*.yaml")):
            spec = SkillDefinition.from_yaml(yaml_path).spec
            skills[spec.name] = spec
        return cls(skills)

    def get(self, name: str) -> SkillSpec | None:
        return self._skills.get(name)

    def list(self) -> list[SkillSpec]:
        return list(self._skills.values())

    def names(self) -> list[str]:
        return sorted(self._skills)
