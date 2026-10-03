"""Immutable, JSON-safe evidence records shared by research stages."""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:
    from packages.schema.models import RawSource

SNAPSHOT_SCHEMA_VERSION = "run_evidence_snapshot.v1"
EvidencePhase = Literal["collect", "analysis"]


def canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _canonical_object_json(value: str) -> str:
    decoded = json.loads(value)
    if not isinstance(decoded, dict):
        raise ValueError("qualifiers must be a JSON object")
    return canonical_json(decoded)


class _FrozenRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceSource(_FrozenRecord):
    id: str
    semantic_id: str
    competitor: str
    covered_competitors: tuple[str, ...] = ()
    dimension: str
    source_type: str
    title: str
    url: str | None = None
    content_hash: str
    snippet: str = ""
    role: Literal["source", "historical_report"] = "source"
    market: str | None = None
    confidence: float = Field(ge=0, le=1)
    status: str = "active"
    verification_status: str = "unknown"
    material_level: Literal[
        "full_source", "summary", "search_summary", "historical_report", "kb_document", "unknown"
    ] = "unknown"
    source_published_at: datetime | None = None
    source_updated_at: datetime | None = None
    source_fetched_at: datetime | None = None
    last_verified_at: datetime | None = None
    extracted_at: datetime
    document_id: str | None = None
    chunk_id: str | None = None
    chunk_ids: tuple[str, ...] = ()
    document_version: int | None = Field(default=None, ge=1)
    document_content_hash: str | None = None
    document_workspace_id: str | None = None
    document_project_id: str | None = None
    payload_json: str

    @field_validator("payload_json")
    @classmethod
    def validate_payload_json(cls, value: str) -> str:
        payload = json.loads(value)
        if not isinstance(payload, dict):
            raise ValueError("source payload must be a JSON object")
        return canonical_json(payload)

    def to_raw_source(self) -> RawSource:
        """Decode a fresh safe projection; mutable descendants never alias history."""
        from packages.schema.models import RawSource

        return RawSource.model_validate(json.loads(self.payload_json))


class EvidenceFact(_FrozenRecord):
    id: str
    semantic_id: str
    evidence_item_ids: tuple[str, ...] = ()
    source_id: str
    competitor: str
    dimension: str
    field: str
    value_json: str
    unit: str | None = None
    market: str | None = None
    qualifiers_json: str = "{}"
    quote: str = ""
    status: Literal["supported", "signal", "unknown"] = "unknown"
    confidence: float = Field(ge=0, le=1)

    @field_validator("value_json")
    @classmethod
    def validate_json(cls, value: str) -> str:
        return canonical_json(json.loads(value))

    @field_validator("qualifiers_json")
    @classmethod
    def validate_qualifiers_json(cls, value: str) -> str:
        return _canonical_object_json(value)

    @property
    def value(self) -> object:
        return json.loads(self.value_json)

    @property
    def qualifiers(self) -> dict[str, object]:
        return json.loads(self.qualifiers_json)


class EvidenceConflict(_FrozenRecord):
    id: str
    competitor: str
    dimension: str
    field: str
    unit: str | None = None
    market: str | None = None
    qualifiers_json: str = "{}"
    fact_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    status: Literal["unresolved", "unknown"] = "unresolved"
    reason: str = "inconsistent_values"

    @field_validator("qualifiers_json")
    @classmethod
    def validate_qualifiers_json(cls, value: str) -> str:
        return _canonical_object_json(value)

    @property
    def qualifiers(self) -> dict[str, object]:
        return json.loads(self.qualifiers_json)


class EvidenceGap(_FrozenRecord):
    id: str
    reason: str
    source_id: str | None = None
    fact_id: str | None = None
    document_id: str | None = None
    competitor: str | None = None
    dimension: str | None = None


class RunEvidenceSnapshot(_FrozenRecord):
    schema_version: Literal["run_evidence_snapshot.v1"] = SNAPSHOT_SCHEMA_VERSION
    id: str
    run_id: str
    workspace_id: str
    project_id: str | None = None
    version: int = Field(ge=1)
    parent_id: str | None = None
    phase: EvidencePhase
    sources: tuple[EvidenceSource, ...] = ()
    facts: tuple[EvidenceFact, ...] = ()
    conflicts: tuple[EvidenceConflict, ...] = ()
    gaps: tuple[EvidenceGap, ...] = ()
    content_hash: str
    created_at: datetime


class EvidenceConsumption(_FrozenRecord):
    id: str
    run_id: str = ""
    workspace_id: str = ""
    project_id: str | None = None
    agent: str
    snapshot_id: str
    snapshot_version: int = Field(ge=1)
    dependency_hash: str
    competitor: str | None = None
    dimension: str | None = None
    source_ids: tuple[str, ...] = ()
    requested_source_ids: tuple[str, ...] | None = None
    fact_ids: tuple[str, ...] = ()
    max_bytes: int = Field(default=8192, ge=0)
    estimated_bytes: int = Field(default=0, ge=0)
    estimated_tokens: int = Field(default=0, ge=0)
    status: Literal["started", "validated", "rejected", "reused"] = "started"
    validated_snapshot_id: str | None = None
    reused_from_snapshot_id: str | None = None
    created_at: datetime


class StageEvidenceView(_FrozenRecord):
    """Task 2 selects these fields and supplies bounded prompt serialization."""

    agent: str
    run_id: str
    workspace_id: str
    project_id: str | None = None
    snapshot_id: str
    snapshot_version: int = Field(ge=1)
    content_hash: str
    competitor: str | None = None
    dimension: str | None = None
    source_ids: tuple[str, ...] = ()
    fact_ids: tuple[str, ...] = ()
    sources: tuple[EvidenceSource, ...] = ()
    facts: tuple[EvidenceFact, ...] = ()
    conflicts: tuple[EvidenceConflict, ...] = ()
    gaps: tuple[EvidenceGap, ...] = ()
    dependency_hash: str
    max_bytes: int = Field(default=8192, ge=0)
    estimated_bytes: int = Field(default=0, ge=0)
    estimated_tokens: int = Field(default=0, ge=0)
    token_estimation_method: Literal["utf8_bytes_plus_256"] = "utf8_bytes_plus_256"

    def to_prompt_json(self) -> str:
        """Serialize typed evidence data, excluding mutable compatibility payloads."""
        payload = self.model_dump(mode="json", exclude={"sources", "facts", "conflicts"})
        payload["sources"] = [
            source.model_dump(mode="json", exclude={"payload_json"}) for source in self.sources
        ]
        payload["facts"] = [
            {
                **fact.model_dump(mode="json", exclude={"value_json", "qualifiers_json"}),
                "value": fact.value,
                "qualifiers": fact.qualifiers,
            }
            for fact in self.facts
        ]
        payload["conflicts"] = [
            {
                **conflict.model_dump(mode="json", exclude={"qualifiers_json"}),
                "qualifiers": conflict.qualifiers,
            }
            for conflict in self.conflicts
        ]
        rendered = canonical_json(payload)
        if len(rendered.encode("utf-8")) > self.max_bytes:
            raise ValueError("evidence view exceeds its byte budget")
        return rendered


class EvidenceChanges(_FrozenRecord):
    added_sources: frozenset[str] = frozenset()
    removed_sources: frozenset[str] = frozenset()
    changed_sources: frozenset[str] = frozenset()
    unchanged_sources: frozenset[str] = frozenset()
    added_facts: frozenset[str] = frozenset()
    removed_facts: frozenset[str] = frozenset()
    changed_facts: frozenset[str] = frozenset()
    unchanged_facts: frozenset[str] = frozenset()
