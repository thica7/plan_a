"""Immutable requirements and auditable decisions for answer boundaries."""

from __future__ import annotations

import json
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from packages.research.evidence.snapshot_models import canonical_json


class _FrozenRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AnswerRequirement(_FrozenRecord):
    competitor: str
    dimension: str
    intent: Literal[
        "facts", "source_guidance", "current_price", "price_comparison", "total_cost", "compliance"
    ] = "facts"
    market: str | None = None
    as_of: date
    context_json: str = "{}"

    @field_validator("context_json")
    @classmethod
    def validate_context_json(cls, value: str) -> str:
        context = json.loads(value)
        if not isinstance(context, dict):
            raise ValueError("answer context must be a JSON object")
        return canonical_json(context)

    @property
    def context(self) -> dict[str, object]:
        """Decode a fresh object so callers cannot change persisted requirements."""
        return json.loads(self.context_json)


class FactDecision(_FrozenRecord):
    fact_id: str
    source_id: str
    allowed: bool
    reasons: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()


class AnswerBoundary(_FrozenRecord):
    snapshot_id: str
    requirement: AnswerRequirement
    status: Literal["answer", "partial", "clarify", "insufficient"]
    allowed_fact_ids: tuple[str, ...] = ()
    withheld_fact_ids: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    clarification_fields: tuple[str, ...] = ()
    fact_decisions: tuple[FactDecision, ...] = ()
    view_source_ids: tuple[str, ...] = ()
    view_fact_ids: tuple[str, ...] = ()
