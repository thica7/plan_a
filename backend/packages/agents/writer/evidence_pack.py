from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from packages.research.evidence.normalization import normalized_fields_from_source
from packages.research.evidence.text import source_business_snippet
from packages.schema.api_dto import RunDetail
from packages.schema.models import RawSource

SCHEMA_VERSION = "writer_evidence_pack.v1"
UNSTRUCTURED_SIGNAL_LIMIT = 420
SOURCE_NOTE_LIMIT = 180
QUOTE_EXCERPT_LIMIT = 400
QUOTE_USED_BY_FACT_LIMIT = 12
STRUCTURED_KNOWLEDGE_LIST_LIMIT = 8
STRUCTURED_KNOWLEDGE_TEXT_LIMIT = 700
SINGLE_CALL_CONTEXT_TARGET_CHARS = 160_000
SOURCE_TOKEN_RE = re.compile(r"\[source:([^\]\s]+)\]")
NORMALIZED_FIELD_DROP_KEYS = {
    "kind",
    "competitor",
    "dimension",
    "confidence",
    "evidence_item_ids",
    "raw_text",
    "html",
    "source_quote",
    "evidence_quote",
    "source_url",
}


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
    structured_knowledge: dict[str, object] = Field(default_factory=dict)
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

    def source_appendix_rows(self) -> list[dict[str, object]]:
        return [
            {
                "source_id": item.id,
                "title": item.title,
                "url": item.url,
                "source_type": item.source_type,
                "competitor": item.competitor,
                "dimension": item.dimension,
                "confidence": item.confidence,
                "represented_by": list(item.represented_by),
                "no_signal_reason": item.no_signal_reason,
            }
            for item in self.pack.source_registry
        ]

    def segment_inputs(self) -> list[dict[str, object]]:
        all_dimensions = {group.dimension for group in self.pack.groups}
        user_research_dimensions = {
            group.dimension
            for group in self.pack.groups
            if _is_user_research_dimension(group.dimension)
            or group.user_research_source_ids
            or group.community_source_ids
        }
        return [
            self._segment("decision_summary", dimensions=all_dimensions),
            self._segment("user_research", dimensions=user_research_dimensions),
            self._segment("competitor_deep_dives", dimensions=all_dimensions),
            self._segment("swot_matrix", dimensions=all_dimensions),
            self._segment("support_appendix", dimensions=all_dimensions),
        ]

    def _segment(self, name: str, *, dimensions: set[str]) -> dict[str, object]:
        groups = [group for group in self.pack.groups if group.dimension in dimensions]
        allowed_source_ids = _unique(
            source_id for group in groups for source_id in group.source_ids
        )
        referenced_quote_ids: set[str] = set()
        for group in groups:
            for fact in group.facts:
                referenced_quote_ids.update(fact.quote_ids)
            for signal in group.unstructured_signals:
                referenced_quote_ids.update(signal.quote_ids)
            for quote in group.quotes:
                referenced_quote_ids.add(quote.id)
        payload: dict[str, object] = {
            "schema_version": self.pack.schema_version,
            "segment_name": name,
            "source_registry": [
                item.model_dump(mode="json")
                for item in self.pack.source_registry
                if item.id in allowed_source_ids
            ],
            "groups": [group.model_dump(mode="json") for group in groups],
            "quotes": [
                quote.model_dump(mode="json")
                for quote in self.pack.quotes
                if quote.id in referenced_quote_ids
                or any(source_id in allowed_source_ids for source_id in quote.source_ids)
                or any(
                    source_id in allowed_source_ids
                    for source_id in quote.full_text_source_ids
                )
            ],
            "matrix": self._segment_matrix(allowed_source_ids),
            "structured_knowledge": self.pack.structured_knowledge,
            "allowed_source_ids": allowed_source_ids,
        }
        payload["segment_input_chars"] = len(json.dumps(payload, ensure_ascii=False))
        return payload

    def _segment_matrix(self, allowed_source_ids: list[str]) -> dict[str, object]:
        allowed = set(allowed_source_ids)
        matrix = dict(self.pack.matrix)
        cells = matrix.get("cells")
        if not isinstance(cells, list):
            return matrix
        filtered_cells: list[dict[str, object]] = []
        for cell in cells:
            if not isinstance(cell, Mapping):
                continue
            raw_source_ids = cell.get("source_ids", [])
            if not isinstance(raw_source_ids, list):
                continue
            source_ids = [
                source_id
                for source_id in raw_source_ids
                if isinstance(source_id, str) and source_id in allowed
            ]
            if not source_ids:
                continue
            filtered_cells.append({**cell, "source_ids": source_ids})
        matrix["cells"] = filtered_cells
        return matrix

    def validate_segment_citations(
        self,
        markdown: str,
        *,
        allowed_source_ids: set[str],
    ) -> list[str]:
        invalid: list[str] = []
        registry_ids = {item.id for item in self.pack.source_registry}
        for match in SOURCE_TOKEN_RE.finditer(markdown or ""):
            source_id = match.group(1)
            if source_id not in registry_ids or source_id not in allowed_source_ids:
                invalid.append(source_id)
        return _unique(invalid)


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
        self._project_kb_slices()
        self._detect_pricing_conflicts()
        pack = WriterEvidencePack(
            source_registry=list(self.registry_by_id.values()),
            groups=list(self.groups.values()),
            quotes=list(self.quotes_by_key.values()),
            matrix=self._matrix_digest(),
            structured_knowledge=self._structured_knowledge_digest(),
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
        facts = self._project_normalized_fields(source)
        cluster_facts = self._project_community_clusters(source)
        signal = self._project_residual_signal(source, [*facts, *cluster_facts])
        if not facts and not cluster_facts and signal is None:
            self.registry_by_id[source.id].no_signal_reason = "no_clean_business_signal"

    def _project_kb_slices(self) -> None:
        for competitor, kb in self.detail.competitor_kbs.items():
            for dimension, findings in kb.slices.items():
                if dimension not in self.detail.plan.dimensions:
                    continue
                group = self._group(competitor, dimension)
                for index, finding in enumerate(findings):
                    text = _trim(_string(finding), 700)
                    if not text:
                        continue
                    signal = WriterKBSignal(
                        id=f"kb:{competitor}:{dimension}:{index}",
                        competitor=competitor,
                        dimension=dimension,
                        text=text,
                        source_ids=list(kb.sources),
                    )
                    group.kb_signals.append(signal)
                    for source_id in signal.source_ids:
                        if source_id in self.registry_by_id:
                            self._mark_source_represented(source_id, signal.id)

    def _project_normalized_fields(self, source: RawSource) -> list[WriterFact]:
        facts: list[WriterFact] = []
        for index, field in enumerate(normalized_fields_from_source(source), start=1):
            fact = self._fact_from_field(source, field, index=index)
            if fact is None:
                continue
            fact = self._add_fact(source, fact)
            facts.append(fact)
        return facts

    def _fact_from_field(
        self,
        source: RawSource,
        field: Mapping[str, object],
        *,
        index: int,
    ) -> WriterFact | None:
        kind = (
            _string(field.get("kind"))
            or _string(field.get("dimension"))
            or source.dimension
        )
        competitor = _string(field.get("competitor")) or source.competitor
        dimension = _string(field.get("dimension")) or source.dimension
        values: dict[str, object] = {}
        for raw_key, raw_value in field.items():
            key = str(raw_key).strip()
            normalized_key = key.casefold()
            if not key or normalized_key in NORMALIZED_FIELD_DROP_KEYS:
                continue
            value = _compact_value(raw_value)
            if value is not None:
                values[key] = value
        if not values:
            return None
        quote_text = _raw_string(field.get("source_quote")) or _raw_string(
            field.get("evidence_quote")
        )
        quote_ids = [self._quote_id_for_text(source, quote_text)] if quote_text else []
        confidence = _float(field.get("confidence"))
        if confidence is None:
            confidence = source.confidence
        return WriterFact(
            id=f"fact:{source.id}:{index}",
            kind=kind,
            competitor=competitor,
            dimension=dimension,
            values=values,
            source_ids=[source.id],
            quote_ids=quote_ids,
            confidence=round(confidence, 3),
        )

    def _quote_id_for_text(self, source: RawSource, text: str) -> str:
        key = _clean(text).casefold()
        quote = self.quotes_by_key.get(key)
        if quote is None:
            quote = WriterQuote(
                id=f"quote:{len(self.quotes_by_key) + 1}",
                excerpt=_trim(text, QUOTE_EXCERPT_LIMIT - 2),
                full_text_source_ids=[source.id],
                source_ids=[source.id],
                confidence=round(source.confidence, 3),
                raw_quote_chars=len(text),
            )
            self.quotes_by_key[key] = quote
            return quote.id
        self.deduped_quote_count += 1
        quote.full_text_source_ids = _unique([*quote.full_text_source_ids, source.id])
        quote.source_ids = _unique([*quote.source_ids, source.id])
        quote.confidence = round(max(quote.confidence, source.confidence), 3)
        quote.raw_quote_chars = max(quote.raw_quote_chars, len(text))
        return quote.id

    def _project_residual_signal(
        self,
        source: RawSource,
        facts: list[WriterFact],
    ) -> WriterUnstructuredSignal | None:
        snippet_source = source
        if facts:
            residual_metadata = dict(source.metadata)
            residual_metadata.pop("normalized_fields", None)
            residual_metadata.pop("community_claim_clusters", None)
            snippet_source = source.model_copy(update={"metadata": residual_metadata})
        clean_snippet = source_business_snippet(
            snippet_source,
            dimension=source.dimension,
            limit=UNSTRUCTURED_SIGNAL_LIMIT,
        )
        if clean_snippet and facts:
            clean_snippet = self._remove_covered_quotes(clean_snippet, facts)
            clean_snippet = self._extract_residual_signal(clean_snippet, facts)
        if not clean_snippet:
            return None
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
        self._group(source.competitor, source.dimension).unstructured_signals.append(signal)
        self._mark_source_represented(source.id, signal.id)
        return signal

    def _remove_covered_quotes(self, clean_snippet: str, facts: list[WriterFact]) -> str:
        residual = clean_snippet
        for fact in facts:
            for quote_id in fact.quote_ids:
                quote = self._quote_by_id(quote_id)
                if quote is None:
                    continue
                residual = residual.replace(quote.excerpt, " ")
        return _clean(residual)

    def _extract_residual_signal(
        self,
        clean_snippet: str,
        facts: list[WriterFact],
    ) -> str:
        if not facts:
            return clean_snippet
        residual = clean_snippet
        for fact in facts:
            for quote_id in fact.quote_ids:
                quote = self._quote_by_id(quote_id)
                if quote and _canonical_business_text(
                    residual
                ) in _canonical_business_text(quote.excerpt):
                    return ""
            residual = _mask_fact_terms(residual, fact)
        return residual if _has_meaningful_residual_signal(residual) else ""

    def _project_community_clusters(self, source: RawSource) -> list[WriterFact]:
        clusters = source.metadata.get("community_claim_clusters")
        if not isinstance(clusters, list):
            return []
        facts: list[WriterFact] = []
        for index, cluster in enumerate(clusters[:5], start=1):
            if not isinstance(cluster, Mapping):
                continue
            values: dict[str, object] = {}
            for key, limit in (
                ("label", 80),
                ("claim", 180),
                ("normalized_value", 120),
            ):
                value = _string(cluster.get(key))
                if value:
                    values[key] = _trim(value, limit)
            confidence = _float(cluster.get("confidence"))
            if confidence is not None:
                values["cluster_confidence"] = round(confidence, 3)
            for key, count, limit in (
                ("source_ids", 6, 80),
                ("official_source_ids", 6, 80),
                ("evidence", 3, 180),
                ("conflict_values", 5, 120),
            ):
                values_list = [
                    _trim(value, limit)
                    for value in _string_list(cluster.get(key))[:count]
                ]
                if values_list:
                    values[key] = values_list
            if not values:
                continue
            fact = WriterFact(
                id=f"fact:{source.id}:community:{index}",
                kind=f"community_{_string(cluster.get('kind')) or 'claim'}",
                competitor=source.competitor,
                dimension=source.dimension,
                values=values,
                source_ids=_unique(
                    [source.id, *_string_list(cluster.get("source_ids"))]
                ),
                confidence=round(
                    confidence if confidence is not None else source.confidence,
                    3,
                ),
            )
            facts.append(self._add_fact(source, fact))
        return facts

    def _add_fact(self, source: RawSource, fact: WriterFact) -> WriterFact:
        group = self._group(fact.competitor, fact.dimension)
        key = _fact_key(fact)
        for existing in group.facts:
            if _fact_key(existing) != key:
                continue
            self.deduped_fact_count += 1
            existing.source_ids = _unique([*existing.source_ids, *fact.source_ids])
            existing.quote_ids = _unique([*existing.quote_ids, *fact.quote_ids])
            existing.confidence = round(max(existing.confidence, fact.confidence), 3)
            for quote_id in fact.quote_ids:
                quote = self._quote_by_id(quote_id)
                if quote:
                    self._record_quote_used_by_fact(quote, existing.id)
            self._mark_source_represented(source.id, existing.id)
            return existing
        group.facts.append(fact)
        for quote_id in fact.quote_ids:
            quote = self._quote_by_id(quote_id)
            if quote:
                self._record_quote_used_by_fact(quote, fact.id)
        self._mark_source_represented(source.id, fact.id)
        return fact

    def _record_quote_used_by_fact(self, quote: WriterQuote, fact_id: str) -> None:
        quote.used_by_fact_ids = _unique(
            [*quote.used_by_fact_ids, fact_id]
        )[:QUOTE_USED_BY_FACT_LIMIT]

    def _detect_pricing_conflicts(self) -> None:
        for group in self.groups.values():
            positions_by_area: dict[str, dict[str, tuple[str, list[WriterFact]]]] = {}
            for fact in group.facts:
                if fact.kind.casefold() != "pricing":
                    continue
                pricing_position = _pricing_conflict_position(fact)
                if pricing_position is None:
                    continue
                claim_area, canonical_position, display_position = pricing_position
                area = positions_by_area.setdefault(claim_area, {})
                position = area.setdefault(
                    canonical_position,
                    (display_position, []),
                )
                position[1].append(fact)
            group.conflicts = [
                WriterConflict(
                    id=f"conflict:{_slug(group.competitor)}:{claim_area}",
                    claim_area=claim_area,
                    positions={
                        display_position: display_position
                        for display_position, _facts in positions.values()
                    },
                    source_ids_by_position={
                        display_position: _unique(
                            source_id
                            for fact in facts
                            for source_id in fact.source_ids
                        )
                        for display_position, facts in positions.values()
                    },
                    confidence_by_position={
                        display_position: round(
                            max(fact.confidence for fact in facts),
                            3,
                        )
                        for display_position, facts in positions.values()
                    },
                )
                for claim_area, positions in positions_by_area.items()
                if len(positions) > 1
            ]

    def _quote_by_id(self, quote_id: str) -> WriterQuote | None:
        for quote in self.quotes_by_key.values():
            if quote.id == quote_id:
                return quote
        return None

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

    def _structured_knowledge_digest(self) -> dict[str, object]:
        digest: dict[str, object] = {}
        for competitor, knowledge in self.detail.competitor_knowledge.items():
            item: dict[str, object] = {"confidence": round(knowledge.confidence, 3)}
            for field_name in (
                "review_summary",
                "pricing_model",
                "feature_tree",
                "user_personas",
            ):
                section = self._structured_section_digest(
                    getattr(knowledge, field_name, None)
                )
                if section is not None:
                    item[field_name] = section
            digest[competitor] = item
        return digest

    def _structured_section_digest(self, section: object) -> object | None:
        if not isinstance(section, BaseModel):
            return None
        payload = section.model_dump(
            mode="json",
            exclude_defaults=True,
            exclude_none=True,
        )
        compact = _compact_structured_knowledge_value(payload)
        return compact if compact not in ({}, []) else None

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
        kb_slice_count, represented_kb_slice_count, dropped_kb_slice_count = (
            self._kb_slice_counts(pack)
        )
        return WriterEvidencePackMetrics(
            writer_evidence_pack_chars=len(prompt_json),
            source_registry_count=len(pack.source_registry),
            represented_source_count=represented_count,
            raw_source_count=len(self.detail.raw_sources),
            dropped_source_count=0,
            no_signal_source_count=no_signal_count,
            kb_slice_count=kb_slice_count,
            represented_kb_slice_count=represented_kb_slice_count,
            dropped_kb_slice_count=dropped_kb_slice_count,
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
        kb_slice_count, represented_kb_slice_count, dropped_kb_slice_count = (
            self._kb_slice_counts(pack)
        )
        return {
            "source_registry_count": len(pack.source_registry),
            "represented_source_count": represented_count,
            "raw_source_count": len(self.detail.raw_sources),
            "dropped_source_count": 0,
            "no_signal_source_count": no_signal_count,
            "kb_slice_count": kb_slice_count,
            "represented_kb_slice_count": represented_kb_slice_count,
            "dropped_kb_slice_count": dropped_kb_slice_count,
        }

    def _kb_slice_counts(self, pack: WriterEvidencePack) -> tuple[int, int, int]:
        kb_slice_count = sum(
            len(findings)
            for kb in self.detail.competitor_kbs.values()
            for dimension, findings in kb.slices.items()
            if dimension in self.detail.plan.dimensions
        )
        represented_kb_slice_count = sum(len(group.kb_signals) for group in pack.groups)
        return (
            kb_slice_count,
            represented_kb_slice_count,
            max(0, kb_slice_count - represented_kb_slice_count),
        )

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


def _is_user_research_dimension(dimension: str) -> bool:
    normalized = dimension.casefold()
    return any(
        token in normalized
        for token in (
            "persona",
            "user",
            "review",
            "community",
            "interview",
            "survey",
        )
    )


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


def _string(value: object) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _raw_string(value: object) -> str:
    return value if isinstance(value, str) and value.strip() else ""


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, Mapping):
        values: list[str] = []
        for item in value.values():
            values.extend(_string_list(item))
        return values
    if isinstance(value, Iterable):
        values = []
        for item in value:
            if isinstance(item, str) and item.strip():
                values.append(item.strip())
            elif item is not None and not isinstance(item, str):
                text = str(item).strip()
                if text:
                    values.append(text)
        return values
    text = str(value).strip()
    return [text] if text else []


def _float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _compact_value(value: object) -> object | None:
    if isinstance(value, str):
        return _trim(value, QUOTE_EXCERPT_LIMIT) if value.strip() else None
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        number = _float(value)
        return value if number is not None else None
    if isinstance(value, list):
        items = [
            item
            for raw_item in value[:5]
            for item in [_compact_value(raw_item)]
            if item is not None
        ]
        return items or None
    if isinstance(value, Mapping):
        nested: dict[str, object] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key).strip()
            if not key or key.casefold() in NORMALIZED_FIELD_DROP_KEYS:
                continue
            nested_value = _compact_value(raw_value)
            if nested_value is not None:
                nested[key] = nested_value
        return nested or None
    return None


def _compact_structured_knowledge_value(value: object) -> object | None:
    if value is None:
        return None
    if isinstance(value, str):
        return _trim(value, STRUCTURED_KNOWLEDGE_TEXT_LIMIT) if value.strip() else None
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value
    if isinstance(value, list):
        items: list[object] = []
        for raw_item in value:
            item = _compact_structured_knowledge_value(raw_item)
            if item is None or item == {} or item == []:
                continue
            items.append(item)
            if len(items) >= STRUCTURED_KNOWLEDGE_LIST_LIMIT:
                break
        return items
    if isinstance(value, Mapping):
        compact: dict[str, object] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key).strip()
            if not key:
                continue
            item = _compact_structured_knowledge_value(raw_value)
            if item is None or item == {} or item == []:
                continue
            compact[key] = item
        return compact
    return value


def _fact_key(fact: WriterFact) -> str:
    if fact.kind.casefold() == "pricing":
        pricing_position = _pricing_conflict_position(fact)
        if pricing_position is not None:
            claim_area, canonical_position, _display_position = pricing_position
            payload = {
                "kind": "pricing",
                "competitor": fact.competitor.casefold(),
                "dimension": fact.dimension.casefold(),
                "claim_area": claim_area,
                "position": canonical_position,
                "model_type": _canonical_business_text(
                    _string(fact.values.get("model_type"))
                ),
                "usage_limit": _canonical_business_text(
                    _string(fact.values.get("usage_limit"))
                ),
                "enterprise_condition": _canonical_business_text(
                    _string(fact.values.get("enterprise_condition"))
                ),
            }
            return json.dumps(payload, ensure_ascii=False, sort_keys=True).casefold()
    payload = {
        "kind": fact.kind.casefold(),
        "competitor": fact.competitor.casefold(),
        "dimension": fact.dimension.casefold(),
        "values": fact.values,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True).casefold()


def _business_value_terms(fact: WriterFact) -> list[str]:
    if fact.kind.casefold() == "pricing":
        terms = [
            _canonical_business_text(_string(fact.values.get("tier_name"))),
            _canonical_price_text(_string(fact.values.get("price"))),
            _canonical_business_text(_string(fact.values.get("billing_cycle"))),
            _canonical_business_text(_string(fact.values.get("usage_limit"))),
            _canonical_business_text(_string(fact.values.get("enterprise_condition"))),
        ]
        return [term for term in terms if term]
    terms: list[str] = []
    for value in fact.values.values():
        for item in _string_list(value):
            term = _canonical_business_text(item)
            if term:
                terms.append(term)
    return _unique(terms)


def _mask_fact_terms(text: str, fact: WriterFact) -> str:
    residual = text
    if fact.kind.casefold() == "pricing":
        residual = _mask_pricing_fact_terms(residual, fact)
    else:
        for term in _business_value_terms(fact):
            residual = _replace_case_insensitive(residual, term, " ")
    return _clean(_strip_empty_sentence_fragments(residual))


def _mask_pricing_fact_terms(text: str, fact: WriterFact) -> str:
    residual = text
    tier_name = _string(fact.values.get("tier_name"))
    price = _string(fact.values.get("price"))
    billing_cycle = _string(fact.values.get("billing_cycle"))
    usage_limit = _string(fact.values.get("usage_limit"))
    enterprise_condition = _string(fact.values.get("enterprise_condition"))
    if tier_name:
        residual = _replace_case_insensitive(residual, tier_name, " ")
    amount = _price_amount(price)
    if amount:
        amount_pattern = re.escape(amount).replace(r"\$", r"\$ ?")
        residual = re.sub(
            rf"{amount_pattern}(?:\s*(?:/|per)\s*(?:month|monthly))?",
            " ",
            residual,
            flags=re.IGNORECASE,
        )
    if billing_cycle:
        for term in {
            billing_cycle,
            _canonical_billing_cycle(billing_cycle),
            "per month",
        }:
            if term:
                residual = _replace_case_insensitive(residual, term, " ")
    for term in (usage_limit, enterprise_condition):
        if term:
            residual = _replace_case_insensitive(residual, term, " ")
    residual = re.sub(
        r"\b(?:a|an|the)?\s*(?:plan|tier)?\s*(?:costs?|priced at|is)?\s*(?:for)?\b",
        " ",
        residual,
        flags=re.IGNORECASE,
    )
    return residual


def _replace_case_insensitive(text: str, term: str, replacement: str) -> str:
    clean_term = _clean(term)
    if not clean_term:
        return text
    pattern = re.escape(clean_term)
    if clean_term[0].isalnum():
        pattern = rf"\b{pattern}"
    if clean_term[-1].isalnum():
        pattern = rf"{pattern}\b"
    return re.sub(pattern, replacement, text, flags=re.IGNORECASE)


def _strip_empty_sentence_fragments(text: str) -> str:
    fragments = [
        fragment.strip(" .;:,")
        for fragment in re.split(r"(?<=[.!?])\s+", text)
    ]
    return " ".join(fragment for fragment in fragments if fragment)


def _has_meaningful_residual_signal(text: str) -> bool:
    terms = _salient_terms(text)
    meaningful_terms = [
        term.strip(".")
        for term in terms
        if term.strip(".") not in {"plan", "tier", "costs", "cost", "month", "monthly"}
    ]
    return len(meaningful_terms) >= 2


def _pricing_conflict_position(fact: WriterFact) -> tuple[str, str, str] | None:
    tier_name = _string(fact.values.get("tier_name"))
    price = _string(fact.values.get("price"))
    if not tier_name or not price:
        return None
    billing_cycle = _string(fact.values.get("billing_cycle"))
    canonical_cycle = _canonical_billing_cycle(billing_cycle) or _canonical_billing_cycle(
        price
    )
    if not canonical_cycle:
        return None
    canonical_price = _canonical_price_text(price)
    if not canonical_price:
        return None
    display_price = _display_price_for_cycle(price, canonical_cycle)
    claim_area = f"pricing:{_slug(tier_name)}:{_slug(canonical_cycle)}"
    canonical_position = f"{canonical_price}:{canonical_cycle}"
    return claim_area, canonical_position, display_price


def _display_price_for_cycle(price: str, canonical_cycle: str) -> str:
    text = _clean(price)
    amount = _price_amount(text)
    if amount and canonical_cycle == "monthly":
        return f"{amount}/month"
    return text


def _canonical_price_text(value: str) -> str:
    amount = _price_amount(value)
    if not amount:
        return _canonical_business_text(value)
    cycle = _canonical_billing_cycle(value)
    if cycle == "monthly":
        return f"{amount} per month"
    return amount


def _price_amount(value: str) -> str:
    match = re.search(r"([$€£]\s*)?\d+(?:\.\d+)?", value)
    if not match:
        return ""
    return match.group(0).replace(" ", "")


def _canonical_billing_cycle(value: str) -> str:
    text = _canonical_business_text(value)
    if not text:
        return ""
    if "per month" in text or text in {"monthly", "month"}:
        return "monthly"
    if "per year" in text or text in {"annually", "annual", "yearly", "year"}:
        return "annual"
    return text


def _canonical_business_text(value: str) -> str:
    text = _clean(value).casefold().replace("/", " per ")
    text = re.sub(r"\bmonthly\b", "month", text)
    text = re.sub(r"\bper\s+month\b", "per month", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or "unknown"
