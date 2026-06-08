from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from packages.schema.enterprise import BusinessQARule


def list_business_qa_rules(
    *,
    layer: str | None = None,
    rule_ids: list[str] | None = None,
) -> list[BusinessQARule]:
    rules = _load_rules()
    if rule_ids is not None:
        allowed = set(rule_ids)
        rules = [rule for rule in rules if rule.id in allowed]
    if layer in {"L1", "L2", "L3"}:
        rules = [rule for rule in rules if layer in rule.applies_to_layers]
    return rules


@lru_cache(maxsize=1)
def _load_rules() -> list[BusinessQARule]:
    payload = yaml.safe_load(_rules_path().read_text(encoding="utf-8")) or {}
    rules = payload.get("rules", [])
    if not isinstance(rules, list):
        raise ValueError("qa_rules.yaml must contain a list under `rules`.")
    return [BusinessQARule.model_validate(_coerce_rule(item)) for item in rules]


def _coerce_rule(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("Each QA rule must be a mapping.")
    return item


def _rules_path() -> Path:
    return Path(__file__).with_name("qa_rules.yaml")
