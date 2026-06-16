from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from packages.research.evidence.normalization import normalized_fields_from_source
from packages.research.evidence.text import source_business_snippet
from packages.schema.api_dto import RunDetail
from packages.schema.models import RawSource


SCHEMA_VERSION = "writer_evidence_pack.v1"
UNSTRUCTURED_SIGNAL_LIMIT = 420
SOURCE_NOTE_LIMIT = 180
SINGLE_CALL_CONTEXT_TARGET_CHARS = 160_000


class WriterSourceRegistryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    competitor: str
    covered_competitors: list[str] = Field(default_factory=list)
    dimension: str
    source_type: str
    title: str
    url: str | None = None
    confidence: float
    candidate_origin: str = "unknown"
    quality_score: float = 0.0
    short_source_note: str = ""
    has_normalized_fields: bool = False
    has_community_clusters: bool = False
    represented_by: list[str] = Field(default_factory=list)
    no_signal_reason: str | None = None


class WriterQuote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    excerpt: str
    full_text_source_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    used_by_fact_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    raw_quote_chars: int = 0


class WriterFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    competitor: str
    dimension: str
    values: dict[str, object] = Field(default_factory=dict)
    source_ids: list[str] = Field(default_factory=list)
    quote_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class WriterUnstructuredSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source_id: str
    competitor: str
    dimension: str
    source_type: str
    signal_summary: str
    salient_terms: list[str] = Field(default_factory=list)
    confidence: float
    quote_ids: list[str] = Field(default_factory=list)


class WriterKBSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    competitor: str
    dimension: str
    text: str
    source_ids: list[str] = Field(default_factory=list)
    merged_into: str | None = None


class WriterConflict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    claim_area: str
    positions: dict[str, str] = Field(default_factory=dict)
    source_ids_by_position: dict[str, list[str]] = Field(default_factory=dict)
    confidence_by_position: dict[str, float] = Field(default_factory=dict)
    resolution_status: Literal["unresolved", "resolved"] = "unresolved"


class WriterEvidenceGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitor: str
    dimension: str
    source_ids: list[str] = Field(default_factory=list)
    official_source_ids: list[str] = Field(default_factory=list)
    community_source_ids: list[str] = Field(default_factory=list)
    user_research_source_ids: list[str] = Field(default_factory=list)
    facts: list[WriterFact] = Field(default_factory=list)
    unstructured_signals: list[WriterUnstructuredSignal] = Field(default_factory=list)
    kb_signals: list[WriterKBSignal] = Field(default_factory=list)
    quotes: list[WriterQuote] = Field(default_factory=list)
    conflicts: list[WriterConflict] = Field(default_factory=list)
    confidence_summary: dict[str, float] = Field(default_factory=dict)
    coverage_notes: list[str] = Field(default_factory=list)


class WriterEvidencePack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    source_registry: list[WriterSourceRegistryItem] = Field(default_factory=list)
    groups: list[WriterEvidenceGroup] = Field(default_factory=list)
    quotes: list[WriterQuote] = Field(default_factory=list)
    matrix: dict[str, object] = Field(default_factory=dict)
    coverage: dict[str, object] = Field(default_factory=dict)


class WriterEvidencePackMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    writer_evidence_pack_chars: int = 0
    source_registry_count: int = 0
    represented_source_count: int = 0
    raw_source_count: int = 0
    dropped_source_count: int = 0
    no_signal_source_count: int = 0
    kb_slice_count: int = 0
    represented_kb_slice_count: int = 0
    dropped_kb_slice_count: int = 0
    largest_source_projection_chars: int = 0
    largest_group_chars: int = 0
    largest_quote_projection_chars: int = 0
    deduped_quote_count: int = 0
    deduped_fact_count: int = 0
    segmented_writer_required: bool = False


class WriterEvidencePackResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pack: WriterEvidencePack
    metrics: WriterEvidencePackMetrics
    warnings: list[str] = Field(default_factory=list)

    def to_prompt_json(self) -> str:
        return json.dumps(self.pack.model_dump(mode="json"), ensure_ascii=False)

    def telemetry_payload(self) -> dict[str, object]:
        payload = self.metrics.model_dump(mode="json")
        payload["preflight_warnings"] = list(self.warnings)
        return payload


USER_RESEARCH_SOURCE_TYPES = {
    "survey_simulated",
    "survey_response",
    "interview_record",
    "manual_transcript",
    "manual_user_note",
    "manual_note",
    "manual",
}
OFFICIAL_SOURCE_TYPES = {"webpage_verified", "official_docs", "official_webpage"}
COMMUNITY_SOURCE_TYPES = {
    "community_forum",
    "github_discussion",
    "reddit_thread",
    "snippet_only",
}


def build_writer_evidence_pack(detail: RunDetail) -> WriterEvidencePackResult:
    builder = _WriterEvidencePackBuilder(detail)
    return builder.build()


class _WriterEvidencePackBuilder:
    def __init__(self, detail: RunDetail) -> None:
        self.detail = detail
        self.registry_by_id: dict[str, WriterSourceRegistryItem] = {}
        self.groups: dict[tuple[str, str], WriterEvidenceGroup] = {}
        self.quotes_by_key: dict[str, WriterQuote] = {}
        self.warnings: list[str] = []
        self.deduped_quote_count = 0
        self.deduped_fact_count = 0

    def build(self) -> WriterEvidencePackResult:
        for source in self.detail.raw_sources:
            self._register_source(source)
            self._project_source(source)
        pack = WriterEvidencePack(
            source_registry=list(self.registry_by_id.values()),
            groups=list(self.groups.values()),
            quotes=list(self.quotes_by_key.values()),
            matrix=self._matrix_digest(),
        )
        pack.coverage = self._coverage_summary(pack)
        metrics = self._metrics(pack)
        return WriterEvidencePackResult(pack=pack, metrics=metrics, warnings=self.warnings)

    def _register_source(self, source: RawSource) -> None:
        fields = normalized_fields_from_source(source)
        item = WriterSourceRegistryItem(
            id=source.id,
            competitor=source.competitor,
            covered_competitors=list(source.covered_competitors),
            dimension=source.dimension,
            source_type=source.source_type,
            title=source.title,
            url=str(source.url) if source.url else None,
            confidence=round(source.confidence, 3),
            candidate_origin=source.candidate_origin,
            quality_score=round(source.quality_score, 3),
            short_source_note=_trim(_clean(source.title), SOURCE_NOTE_LIMIT),
            has_normalized_fields=bool(fields),
            has_community_clusters=bool(source.metadata.get("community_claim_clusters")),
        )
        self.registry_by_id[source.id] = item
        group = self._group(source.competitor, source.dimension)
        group.source_ids = _unique([*group.source_ids, source.id])
        if source.source_type.casefold() in OFFICIAL_SOURCE_TYPES:
            group.official_source_ids = _unique([*group.official_source_ids, source.id])
        if source.source_type.casefold() in COMMUNITY_SOURCE_TYPES or source.metadata.get(
            "community_evidence"
        ):
            group.community_source_ids = _unique([*group.community_source_ids, source.id])
        if source.source_type.casefold() in USER_RESEARCH_SOURCE_TYPES:
            group.user_research_source_ids = _unique(
                [*group.user_research_source_ids, source.id]
            )

    def _project_source(self, source: RawSource) -> None:
        clean_snippet = source_business_snippet(
            source,
            dimension=source.dimension,
            limit=UNSTRUCTURED_SIGNAL_LIMIT,
        )
        if clean_snippet:
            signal = WriterUnstructuredSignal(
                id=f"signal:{source.id}",
                source_id=source.id,
                competitor=source.competitor,
                dimension=source.dimension,
                source_type=source.source_type,
                signal_summary=clean_snippet,
                salient_terms=_salient_terms(clean_snippet),
                confidence=round(source.confidence, 3),
            )
            self._group(source.competitor, source.dimension).unstructured_signals.append(
                signal
            )
            self._mark_source_represented(source.id, signal.id)
        else:
            self.registry_by_id[source.id].no_signal_reason = "no_clean_business_signal"

    def _group(self, competitor: str, dimension: str) -> WriterEvidenceGroup:
        key = (competitor, dimension)
        if key not in self.groups:
            self.groups[key] = WriterEvidenceGroup(
                competitor=competitor,
                dimension=dimension,
            )
        return self.groups[key]

    def _mark_source_represented(self, source_id: str, item_id: str) -> None:
        item = self.registry_by_id[source_id]
        item.represented_by = _unique([*item.represented_by, item_id])
        item.no_signal_reason = None

    def _matrix_digest(self) -> dict[str, object]:
        matrix = self.detail.comparison_matrix
        if matrix is None:
            return {"winner_by_dimension": {}, "summary": [], "cells": []}
        return {
            "winner_by_dimension": dict(matrix.winner_by_dimension),
            "summary": list(matrix.summary),
            "cells": [
                {
                    "competitor": cell.competitor,
                    "dimension": cell.dimension,
                    "value": _trim(str(cell.value), 1200),
                    "source_ids": list(cell.source_ids),
                    "confidence": round(cell.confidence, 3),
                }
                for cell in matrix.cells
            ],
        }

    def _metrics(self, pack: WriterEvidencePack) -> WriterEvidencePackMetrics:
        prompt_json = json.dumps(pack.model_dump(mode="json"), ensure_ascii=False)
        group_sizes = [
            len(json.dumps(group.model_dump(mode="json"), ensure_ascii=False))
            for group in pack.groups
        ]
        quote_sizes = [
            len(json.dumps(quote.model_dump(mode="json"), ensure_ascii=False))
            for quote in pack.quotes
        ]
        represented_count = sum(1 for item in pack.source_registry if item.represented_by)
        no_signal_count = sum(1 for item in pack.source_registry if item.no_signal_reason)
        return WriterEvidencePackMetrics(
            writer_evidence_pack_chars=len(prompt_json),
            source_registry_count=len(pack.source_registry),
            represented_source_count=represented_count,
            raw_source_count=len(self.detail.raw_sources),
            dropped_source_count=0,
            no_signal_source_count=no_signal_count,
            largest_source_projection_chars=self._largest_source_projection_chars(pack),
            largest_group_chars=max(group_sizes, default=0),
            largest_quote_projection_chars=max(quote_sizes, default=0),
            deduped_quote_count=self.deduped_quote_count,
            deduped_fact_count=self.deduped_fact_count,
            segmented_writer_required=len(prompt_json) > SINGLE_CALL_CONTEXT_TARGET_CHARS,
        )

    def _coverage_summary(self, pack: WriterEvidencePack) -> dict[str, object]:
        represented_count = sum(1 for item in pack.source_registry if item.represented_by)
        no_signal_count = sum(1 for item in pack.source_registry if item.no_signal_reason)
        return {
            "source_registry_count": len(pack.source_registry),
            "represented_source_count": represented_count,
            "raw_source_count": len(self.detail.raw_sources),
            "dropped_source_count": 0,
            "no_signal_source_count": no_signal_count,
            "kb_slice_count": 0,
            "represented_kb_slice_count": 0,
            "dropped_kb_slice_count": 0,
        }

    def _largest_source_projection_chars(self, pack: WriterEvidencePack) -> int:
        source_projection_sizes: list[int] = []
        for item in pack.source_registry:
            source_projection = {
                "registry_item": item.model_dump(mode="json"),
                "unstructured_signals": [
                    signal.model_dump(mode="json")
                    for group in pack.groups
                    for signal in group.unstructured_signals
                    if signal.source_id == item.id
                ],
                "facts": [
                    fact.model_dump(mode="json")
                    for group in pack.groups
                    for fact in group.facts
                    if item.id in fact.source_ids
                ],
                "quotes": [
                    quote.model_dump(mode="json")
                    for quote in pack.quotes
                    if item.id in quote.source_ids
                    or item.id in quote.full_text_source_ids
                ],
            }
            source_projection_sizes.append(
                len(json.dumps(source_projection, ensure_ascii=False))
            )
        return max(source_projection_sizes, default=0)


def _clean(value: str) -> str:
    return " ".join((value or "").split())


def _trim(value: str, limit: int) -> str:
    text = _clean(value)
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)].rstrip()}..."


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        result.append(value)
        seen.add(value)
    return result


def _salient_terms(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9+.#-]{2,}", text.casefold())
    stop_words = {"and", "the", "for", "with", "that", "this", "from", "into"}
    terms: list[str] = []
    for word in words:
        if word in stop_words or word in terms:
            continue
        terms.append(word)
        if len(terms) >= 8:
            break
    return terms
