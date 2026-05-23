from __future__ import annotations

from pathlib import Path

import yaml

from packages.schema.models import SkillSpec


def load_skill_spec(path: Path) -> SkillSpec:
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    return SkillSpec.model_validate(payload)


class SkillDefinition:
    def __init__(self, spec: SkillSpec, source_path: Path) -> None:
        self.spec = spec
        self.source_path = source_path

    @classmethod
    def from_yaml(cls, path: Path) -> "SkillDefinition":
        return cls(spec=load_skill_spec(path), source_path=path)
