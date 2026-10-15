"""Immutable, JSON-safe evidence records shared by research stages."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_serializer,
    model_validator,
)

if TYPE_CHECKING:
    from packages.schema.models import RawSource

SNAPSHOT_SCHEMA_VERSION = "run_evidence_snapshot.v1"
FACT_MARKET_POLICY_VERSION = "source_rows.v1"
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

        payload = json.loads(self.payload_json)
        metadata = payload.get("metadata", {})
        allowed = {
            "normalized_fields",
            "market",
            "source_material_level",
            "source_published_at",
            "source_updated_at",
            "source_fetched_at",
            "fetched_at",
            "last_verified_at",
            "verification_status",
            "kb_document_id",
            "document_id",
            "kb_document_version",
            "document_version",
            "kb_document_content_hash",
            "kb_content_hash",
            "kb_chunk_id",
            "kb_chunk_ids",
            "chunk_id",
            "chunk_ids",
            "source_role",
            "fallback_synthetic",
            "survey_interview_synthetic",
            "community_evidence",
            "kb_document_workspace_id",
            "kb_document_project_id",
            "kb_source_role",
            "kb_document_status",
        }
        payload["metadata"] = {key: value for key, value in metadata.items() if key in allowed}
        payload["snippet"] = self.snippet
        return RawSource.model_validate(payload)


class EvidenceArtifactDependency(_FrozenRecord):
    """Bind a persisted stage artifact to its actual producer credentials."""

    kind: str
    competitor: str | None = None
    dimension: str | None = None
    consumption_ids: tuple[str, ...]
    payload_hash: str
    upstream_hash: str | None = None


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
    fact_market_policy_version: str | None = None
    id: str
    run_id: str
    workspace_id: str
    project_id: str | None = None
    version: int = Field(ge=1)
    parent_id: str | None = None
    phase: EvidencePhase
    competitors: tuple[str, ...] = ()
    sources: tuple[EvidenceSource, ...] = ()
    facts: tuple[EvidenceFact, ...] = ()
    conflicts: tuple[EvidenceConflict, ...] = ()
    gaps: tuple[EvidenceGap, ...] = ()
    content_hash: str
    created_at: datetime

    @model_serializer(mode="wrap")
    def serialize_policy(self, handler):
        payload = handler(self)
        # Historical v1 records predate this additive, hash-protected policy.
        # Preserve their serialized bytes and audit hashes when reopening them.
        if self.fact_market_policy_version is None:
            payload.pop("fact_market_policy_version", None)
        return payload


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
    requested_fact_ids: tuple[str, ...] | None = None
    fact_ids: tuple[str, ...] = ()
    max_bytes: int = Field(default=8192, ge=0)
    view_max_bytes: int | None = Field(default=None, ge=1)
    estimated_bytes: int = Field(default=0, ge=0)
    estimated_tokens: int = Field(default=0, ge=0)
    status: Literal["started", "validated", "rejected", "reused"] = "started"
    validated_snapshot_id: str | None = None
    reused_from_snapshot_id: str | None = None
    created_at: datetime


    @model_validator(mode="after")
    def validate_view_budget(self) -> EvidenceConsumption:
        if self.view_max_bytes is not None and self.view_max_bytes > self.max_bytes:
            raise ValueError("evidence view budget exceeds stage budget")
        return self

    @model_serializer(mode="wrap")
    def serialize_credential(self, handler):
        payload = handler(self)
        if self.view_max_bytes is None:
            payload.pop("view_max_bytes", None)
        if self.requested_fact_ids is None:
            payload.pop('requested_fact_ids', None)
        return payload


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
    comparison_products: tuple[str, ...] = ()
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
        # Sources and facts below already declare their IDs; credentials retain
        # the full lists but prompts do not repeat those lists a second time.
        payload = self.model_dump(mode="json", exclude={"sources", "facts", "conflicts", "source_ids", "fact_ids", "content_hash", "dependency_hash", "comparison_products"})
        from packages.research.evidence.capabilities import capability_keys, capability_conditioned

        products = self.comparison_products or {fact.competitor for fact in self.facts}

        fact_sources = {fact.source_id for fact in self.facts if fact.quote}
        payload["gaps"] = [gap.model_dump(mode="json", exclude_none=True, exclude={"id"}) for gap in self.gaps]
        payload["sources"] = [
            source.model_dump(mode="json", exclude_none=True,
                              exclude={"payload_json", "semantic_id", "chunk_id", "chunk_ids",
                                       "document_content_hash", "document_workspace_id", "document_project_id",
                                       "document_id", "document_version", "extracted_at",
                                       *(("snippet",) if source.id in fact_sources else ())})
            for source in self.sources
        ]
        for source, rendered_source in zip(self.sources, payload["sources"]):
            if source.chunk_ids:
                rendered_source["chunk_ids"] = list(source.chunk_ids)
            if source.source_fetched_at == source.last_verified_at:
                rendered_source.pop("source_fetched_at", None)
            if source.covered_competitors == (source.competitor,):
                rendered_source.pop("covered_competitors", None)
        repeated = Counter((fact.source_id, fact.quote) for fact in self.facts if fact.quote)
        quote_keys = {key: f"q{number}" for number, key in enumerate(sorted(key for key, count in repeated.items() if count > 1))}

        def referenced_value(value, source_id):
            if isinstance(value, str) and (source_id, value) in quote_keys:
                return {"quote_ref": quote_keys[source_id, value]}
            if isinstance(value, list):
                return [referenced_value(item, source_id) for item in value]
            if isinstance(value, dict):
                return {key: referenced_value(item, source_id) for key, item in value.items()}
            return value

        payload["facts"] = [
            {
                **fact.model_dump(mode="json", exclude_none=True,
                                  exclude={"value_json", "qualifiers_json", "semantic_id", "quote", "evidence_item_ids"}),
                **({"quote_ref": quote_keys[fact.source_id, fact.quote]} if (fact.source_id, fact.quote) in quote_keys else {"quote": fact.quote}),
                "value": referenced_value(fact.value, fact.source_id),
                "qualifiers": fact.qualifiers,
                **({"capability_keys": list(capability_keys(fact, products)),
                    "capability_conditions": "review_original_conditions"}
                   if fact.field == "evidence_terms" and capability_keys(fact, products) and capability_conditioned(fact) else
                   {"capability_keys": list(capability_keys(fact, products))} if fact.field == "evidence_terms" and capability_keys(fact, products) else {}),
            }
            for fact in self.facts
        ]
        if quote_keys:
            payload["quoted_evidence"] = {name: key[1] for key, name in quote_keys.items()}
        # Price observations repeat the same exact conditions on their plan,
        # amount and billing facts. Keep one lossless copy in this local view.
        if self.agent in {"analyst", "comparator", "reflector", "writer"}:
            counts = Counter(canonical_json(fact.qualifiers) for fact in self.facts)
            shared = {key: f"p{index}" for index, key in enumerate(sorted(
                key for key, count in counts.items() if count > 1 and len(key.encode()) > 120
            ))}
            for fact, rendered_fact in zip(self.facts, payload["facts"]):
                key = canonical_json(fact.qualifiers)
                if key in shared:
                    rendered_fact.pop("qualifiers")
                    rendered_fact["qualifiers_ref"] = shared[key]
            if shared:
                payload["qualifier_sets"] = {ref: json.loads(key) for key, ref in shared.items()}
        payload["scope_instructions"] = (
            "Resolve quote_ref only from quoted_evidence in this view, including exact text values. "
            "context_budget_exceeded means collected evidence was omitted from this view; "
            "do not claim that the product lacks evidence or lacks the capability."
        )
        if payload.get("qualifier_sets"):
            payload["scope_instructions"] += " Resolve qualifiers_ref only from qualifier_sets in this view; keep all conditions."
        payload["conflicts"] = [
            {
                **conflict.model_dump(mode="json", exclude={"qualifiers_json"}),
                "qualifiers": conflict.qualifiers,
            }
            for conflict in self.conflicts
        ]
        if self.agent == 'writer' and self.dimension == 'feature':
            # The same exact access branches occur in values and operation
            # bindings across observations. Budget them once before selection.
            counts = Counter()
            def count_strings(value):
                if isinstance(value, str) and len(value.encode()) >= 120:
                    counts[value] += 1
                elif isinstance(value, dict):
                    for item in value.values(): count_strings(item)
                elif isinstance(value, list):
                    for item in value: count_strings(item)
            count_strings(payload)
            refs = {value: f't{index}' for index, (value, count) in enumerate(sorted(counts.items())) if count > 1}
            def replace_strings(value):
                if isinstance(value, str) and value in refs: return {'text_ref': refs[value]}
                if isinstance(value, dict): return {key: replace_strings(item) for key, item in value.items()}
                if isinstance(value, list): return [replace_strings(item) for item in value]
                return value
            payload = replace_strings(payload)
            if refs:
                payload['text_sets'] = {ref: value for value, ref in refs.items()}
                payload['scope_instructions'] += ' Resolve text_ref only from text_sets in this view; original branches and prerequisites stay complete.'
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
