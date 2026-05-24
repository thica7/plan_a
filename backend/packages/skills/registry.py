from __future__ import annotations

from pathlib import Path
from typing import Self

import yaml

from packages.schema.models import SkillSpec


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
            with yaml_path.open("r", encoding="utf-8") as handle:
                payload = yaml.safe_load(handle) or {}
            spec = SkillSpec.model_validate(payload)
            skills[spec.name] = spec
        return cls(skills)

    def get(self, name: str) -> SkillSpec | None:
        return self._skills.get(name)

    def list(self) -> list[SkillSpec]:
        return list(self._skills.values())

    def names(self) -> list[str]:
        return sorted(self._skills)
