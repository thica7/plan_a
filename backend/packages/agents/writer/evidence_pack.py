from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Mapping
from typing import Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from packages.identity.source_resolver import source_tokens
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
SEGMENT_INPUT_TARGET_CHARS = SINGLE_CALL_CONTEXT_TARGET_CHARS
SEGMENT_SOURCE_BATCH_SIZE = 4
SEGMENT_FACT_BATCH_SIZE = 32
T = TypeVar("T")
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

    def preflight_errors(self) -> list[str]:
        errors: list[str] = []
        for item in self.pack.source_registry:
            if not item.represented_by and not item.no_signal_reason:
                errors.append(f"source_not_represented:{item.id}")
        if self.metrics.dropped_source_count:
            errors.append(f"dropped_source_count:{self.metrics.dropped_source_count}")
        if self.metrics.dropped_kb_slice_count:
            errors.append(f"dropped_kb_slice_count:{self.metrics.dropped_kb_slice_count}")
        return errors

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
        groups = list(self.pack.groups)
        all_source_ids = [item.id for item in self.pack.source_registry]
        all_competitors = _unique(group.competitor for group in groups)
        user_research_groups = [
            group
            for group in groups
            if _is_user_research_dimension(group.dimension)
            or group.user_research_source_ids
            or group.community_source_ids
        ]
        segments = [
            self._segment(
                "decision_summary",
                groups=groups,
                allowed_source_ids=all_source_ids,
                group_projection="compact",
                quote_projection="compact",
                matrix_projection="compact",
                structured_competitors=all_competitors,
                structured_projection="compact",
            ),
        ]
        segments.extend(self._user_research_segments(user_research_groups))
        for competitor in all_competitors:
            competitor_groups = [
                group for group in groups if group.competitor == competitor
            ]
            segments.extend(
                self._competitor_deep_dive_segments(competitor, competitor_groups)
            )
        segments.extend(
            [
                self._segment(
                    "swot_matrix",
                    groups=groups,
                    allowed_source_ids=all_source_ids,
                    group_projection="summary",
                    quote_projection="none",
                    matrix_projection="compact",
                    structured_competitors=[],
                    structured_projection="compact",
                ),
                self._segment(
                    "support_appendix",
                    groups=[],
                    allowed_source_ids=all_source_ids,
                    group_projection="none",
                    quote_projection="none",
                    matrix_projection="coverage",
                    structured_competitors=[],
                    structured_projection="compact",
                    include_coverage=True,
                ),
            ]
        )
        return segments

    def _user_research_segments(
        self,
        groups: list[WriterEvidenceGroup],
    ) -> list[dict[str, object]]:
        segment = self._segment(
            "user_research",
            groups=groups,
            group_projection="full",
            quote_projection="full",
            matrix_projection="compact",
            structured_competitors=_unique(group.competitor for group in groups),
            structured_projection="compact",
        )
        if segment["segment_input_chars"] < SEGMENT_INPUT_TARGET_CHARS:
            return [segment]
        segments: list[dict[str, object]] = []
        for group in groups:
            group_segment = self._segment(
                "user_research",
                groups=[group],
                group_projection="full",
                quote_projection="full",
                matrix_projection="compact",
                structured_competitors=[group.competitor],
                structured_projection="compact",
                segment_competitor=group.competitor,
                segment_dimension=group.dimension,
            )
            if group_segment["segment_input_chars"] < SEGMENT_INPUT_TARGET_CHARS:
                segments.append(group_segment)
                continue
            segments.extend(self._split_user_research_group_segments(group))
        return segments

    def _split_user_research_group_segments(
        self,
        group: WriterEvidenceGroup,
    ) -> list[dict[str, object]]:
        segments: list[dict[str, object]] = []
        source_ids = self._source_ids_for_groups([group])
        if len(source_ids) > 1:
            for batch_index, source_batch in enumerate(
                _chunked(source_ids, SEGMENT_SOURCE_BATCH_SIZE),
                start=1,
            ):
                sliced_group = self._group_for_source_ids(group, source_batch)
                source_segment = self._segment(
                    "user_research",
                    groups=[sliced_group],
                    group_projection="full",
                    quote_projection="full",
                    matrix_projection="compact",
                    structured_competitors=[group.competitor],
                    structured_projection="compact",
                    segment_competitor=group.competitor,
                    segment_dimension=group.dimension,
                    segment_batch=f"sources:{batch_index}",
                )
                if source_segment["segment_input_chars"] < SEGMENT_INPUT_TARGET_CHARS:
                    segments.append(source_segment)
                    continue
                segments.extend(
                    self._split_user_research_fact_segments(
                        sliced_group,
                        batch_prefix=f"sources:{batch_index}",
                    )
                )
            return segments
        return self._split_user_research_fact_segments(group, batch_prefix="facts")

    def _split_user_research_fact_segments(
        self,
        group: WriterEvidenceGroup,
        *,
        batch_prefix: str,
    ) -> list[dict[str, object]]:
        if not group.facts:
            return [
                self._segment(
                    "user_research",
                    groups=[group],
                    group_projection="compact",
                    quote_projection="compact",
                    matrix_projection="compact",
                    structured_competitors=[group.competitor],
                    structured_projection="compact",
                    segment_competitor=group.competitor,
                    segment_dimension=group.dimension,
                    segment_batch=batch_prefix,
                )
            ]
        segments: list[dict[str, object]] = []
        for facts in _chunked(group.facts, SEGMENT_FACT_BATCH_SIZE):
            segments.extend(
                self._budgeted_fact_segments(
                    "user_research",
                    group=group,
                    facts=facts,
                    structured_competitors=[group.competitor],
                    structured_projection="compact",
                    segment_competitor=group.competitor,
                    batch_prefix=batch_prefix,
                    existing_count=len(segments),
                )
            )
        return segments

    def _competitor_deep_dive_segments(
        self,
        competitor: str,
        groups: list[WriterEvidenceGroup],
    ) -> list[dict[str, object]]:
        segment = self._segment(
            "competitor_deep_dives",
            groups=groups,
            group_projection="full",
            quote_projection="full",
            matrix_projection="compact",
            structured_competitors=[competitor],
            structured_projection="full",
            segment_competitor=competitor,
        )
        if segment["segment_input_chars"] < SEGMENT_INPUT_TARGET_CHARS:
            return [segment]
        segments: list[dict[str, object]] = []
        for group in groups:
            dimension_segment = self._segment(
                "competitor_deep_dives",
                groups=[group],
                group_projection="full",
                quote_projection="full",
                matrix_projection="compact",
                structured_competitors=[competitor],
                structured_projection="full",
                segment_competitor=competitor,
                segment_dimension=group.dimension,
            )
            if dimension_segment["segment_input_chars"] < SEGMENT_INPUT_TARGET_CHARS:
                segments.append(dimension_segment)
                continue
            segments.extend(self._split_group_segments(competitor, group))
        return segments

    def _split_group_segments(
        self,
        competitor: str,
        group: WriterEvidenceGroup,
    ) -> list[dict[str, object]]:
        segments: list[dict[str, object]] = []
        source_ids = self._source_ids_for_groups([group])
        if len(source_ids) > 1:
            for batch_index, source_batch in enumerate(
                _chunked(source_ids, SEGMENT_SOURCE_BATCH_SIZE),
                start=1,
            ):
                sliced_group = self._group_for_source_ids(group, source_batch)
                source_segment = self._segment(
                    "competitor_deep_dives",
                    groups=[sliced_group],
                    group_projection="full",
                    quote_projection="full",
                    matrix_projection="compact",
                    structured_competitors=[competitor],
                    structured_projection="full",
                    segment_competitor=competitor,
                    segment_dimension=group.dimension,
                    segment_batch=f"sources:{batch_index}",
                )
                if source_segment["segment_input_chars"] < SEGMENT_INPUT_TARGET_CHARS:
                    segments.append(source_segment)
                    continue
                segments.extend(
                    self._split_group_fact_segments(
                        competitor,
                        sliced_group,
                        batch_prefix=f"sources:{batch_index}",
                    )
                )
            return segments
        return self._split_group_fact_segments(competitor, group, batch_prefix="facts")

    def _split_group_fact_segments(
        self,
        competitor: str,
        group: WriterEvidenceGroup,
        *,
        batch_prefix: str,
    ) -> list[dict[str, object]]:
        if not group.facts:
            return [
                self._segment(
                    "competitor_deep_dives",
                    groups=[group],
                    group_projection="compact",
                    quote_projection="compact",
                    matrix_projection="compact",
                    structured_competitors=[competitor],
                    structured_projection="compact",
                    segment_competitor=competitor,
                    segment_dimension=group.dimension,
                    segment_batch=batch_prefix,
                )
            ]
        segments: list[dict[str, object]] = []
        for facts in _chunked(group.facts, SEGMENT_FACT_BATCH_SIZE):
            segments.extend(
                self._budgeted_fact_segments(
                    "competitor_deep_dives",
                    group=group,
                    facts=facts,
                    structured_competitors=[competitor],
                    structured_projection="full",
                    segment_competitor=competitor,
                    batch_prefix=batch_prefix,
                    existing_count=len(segments),
                )
            )
        return segments

    def _budgeted_fact_segments(
        self,
        name: str,
        *,
        group: WriterEvidenceGroup,
        facts: list[WriterFact],
        structured_competitors: list[str],
        structured_projection: Literal["full", "compact"],
        segment_competitor: str,
        batch_prefix: str,
        existing_count: int,
    ) -> list[dict[str, object]]:
        segment = self._fact_segment(
            name,
            group=group,
            facts=facts,
            structured_competitors=structured_competitors,
            structured_projection=structured_projection,
            segment_competitor=segment_competitor,
            segment_batch=f"{batch_prefix}:facts:{existing_count + 1}",
        )
        if (
            segment["segment_input_chars"] <= SEGMENT_INPUT_TARGET_CHARS
            or len(facts) <= 1
        ):
            if segment["segment_input_chars"] > SEGMENT_INPUT_TARGET_CHARS:
                segment["segment_over_budget_reason"] = "single_fact_exceeds_budget"
                segment["segment_input_target_chars"] = SEGMENT_INPUT_TARGET_CHARS
                segment["segment_input_chars"] = len(
                    json.dumps(segment, ensure_ascii=False)
                )
            return [segment]
        midpoint = max(1, len(facts) // 2)
        left_segments = self._budgeted_fact_segments(
            name,
            group=group,
            facts=facts[:midpoint],
            structured_competitors=structured_competitors,
            structured_projection=structured_projection,
            segment_competitor=segment_competitor,
            batch_prefix=batch_prefix,
            existing_count=existing_count,
        )
        right_segments = self._budgeted_fact_segments(
            name,
            group=group,
            facts=facts[midpoint:],
            structured_competitors=structured_competitors,
            structured_projection=structured_projection,
            segment_competitor=segment_competitor,
            batch_prefix=batch_prefix,
            existing_count=existing_count + len(left_segments),
        )
        return [*left_segments, *right_segments]

    def _fact_segment(
        self,
        name: str,
        *,
        group: WriterEvidenceGroup,
        facts: list[WriterFact],
        structured_competitors: list[str],
        structured_projection: Literal["full", "compact"],
        segment_competitor: str,
        segment_batch: str,
    ) -> dict[str, object]:
        fact_source_ids = _unique(
            source_id for fact in facts for source_id in fact.source_ids
        )
        if not fact_source_ids:
            fact_source_ids = self._source_ids_for_groups([group])
        sliced_group = self._group_for_source_ids(group, fact_source_ids)
        sliced_group = sliced_group.model_copy(update={"facts": facts})
        return self._segment(
            name,
            groups=[sliced_group],
            group_projection="full",
            quote_projection="full_referenced",
            matrix_projection="compact",
            structured_competitors=structured_competitors,
            structured_projection=structured_projection,
            segment_competitor=segment_competitor,
            segment_dimension=group.dimension,
            segment_batch=segment_batch,
        )

    def _segment(
        self,
        name: str,
        *,
        groups: list[WriterEvidenceGroup],
        group_projection: Literal["full", "compact", "summary", "none"],
        quote_projection: Literal["full", "full_referenced", "compact", "none"],
        matrix_projection: Literal["compact", "coverage"],
        structured_competitors: list[str],
        structured_projection: Literal["full", "compact"],
        allowed_source_ids: list[str] | None = None,
        segment_competitor: str | None = None,
        segment_dimension: str | None = None,
        segment_batch: str | None = None,
        include_coverage: bool = False,
    ) -> dict[str, object]:
        registry_ids = {item.id for item in self.pack.source_registry}
        if allowed_source_ids is None:
            allowed_source_ids = self._source_ids_for_groups(groups)
        allowed_source_ids = _unique(
            source_id for source_id in allowed_source_ids if source_id in registry_ids
        )
        group_payloads = [
            self._group_payload(group, projection=group_projection) for group in groups
        ]
        referenced_quote_ids: set[str] = set()
        if quote_projection != "none":
            for group_payload in group_payloads:
                facts = group_payload.get("facts", [])
                if isinstance(facts, list):
                    for fact in facts:
                        if isinstance(fact, Mapping):
                            referenced_quote_ids.update(_string_list(fact.get("quote_ids")))
                signals = group_payload.get("unstructured_signals", [])
                if isinstance(signals, list):
                    for signal in signals:
                        if isinstance(signal, Mapping):
                            referenced_quote_ids.update(
                                _string_list(signal.get("quote_ids"))
                            )
                quotes = group_payload.get("quotes", [])
                if isinstance(quotes, list):
                    for quote in quotes:
                        if isinstance(quote, Mapping):
                            referenced_quote_ids.update(_string_list(quote.get("id")))
        allowed = set(allowed_source_ids)
        payload: dict[str, object] = {
            "schema_version": self.pack.schema_version,
            "segment_name": name,
            "segment_competitor": segment_competitor,
            "segment_dimension": segment_dimension,
            "segment_batch": segment_batch,
            "source_registry": [
                self._segment_registry_item(item)
                for item in self.pack.source_registry
                if item.id in allowed_source_ids
            ],
            "groups": group_payloads,
            "quotes": [
                self._segment_quote(quote, compact=quote_projection == "compact")
                for quote in self.pack.quotes
                if quote_projection != "none"
                and (
                    quote.id in referenced_quote_ids
                    or (
                        quote_projection == "full"
                        and (
                            any(source_id in allowed for source_id in quote.source_ids)
                            or any(
                                source_id in allowed
                                for source_id in quote.full_text_source_ids
                            )
                        )
                    )
                )
            ],
            "matrix": (
                self._coverage_matrix()
                if matrix_projection == "coverage"
                else self._segment_matrix(allowed_source_ids)
            ),
            "structured_knowledge": {
                competitor: self._segment_structured_knowledge_item(
                    payload,
                    compact=structured_projection == "compact",
                )
                for competitor, payload in self.pack.structured_knowledge.items()
                if competitor in structured_competitors
            },
            "allowed_source_ids": allowed_source_ids,
        }
        if include_coverage:
            payload["coverage"] = dict(self.pack.coverage)
        payload["segment_input_chars"] = len(json.dumps(payload, ensure_ascii=False))
        return payload

    def _source_ids_for_groups(self, groups: list[WriterEvidenceGroup]) -> list[str]:
        return _unique(
            source_id
            for group in groups
            for source_id in [
                *group.source_ids,
                *group.official_source_ids,
                *group.community_source_ids,
                *group.user_research_source_ids,
                *[
                    source_id
                    for fact in group.facts
                    for source_id in fact.source_ids
                ],
                *[
                    signal.source_id
                    for signal in group.unstructured_signals
                ],
                *[
                    source_id
                    for signal in group.kb_signals
                    for source_id in signal.source_ids
                ],
                *[
                    source_id
                    for conflict in group.conflicts
                    for source_ids in conflict.source_ids_by_position.values()
                    for source_id in source_ids
                ],
            ]
        )

    def _segment_registry_item(self, item: WriterSourceRegistryItem) -> dict[str, object]:
        represented_by = list(item.represented_by)
        return {
            "id": item.id,
            "competitor": item.competitor,
            "covered_competitors": list(item.covered_competitors),
            "dimension": item.dimension,
            "source_type": item.source_type,
            "title": item.title,
            "confidence": item.confidence,
            "represented_by": represented_by[:4],
            "represented_by_count": len(represented_by),
            "no_signal_reason": item.no_signal_reason,
        }

    def _group_payload(
        self,
        group: WriterEvidenceGroup,
        *,
        projection: Literal["full", "compact", "summary", "none"],
    ) -> dict[str, object]:
        if projection == "full":
            return group.model_dump(mode="json")
        if projection == "none":
            return {}
        base: dict[str, object] = {
            "competitor": group.competitor,
            "dimension": group.dimension,
            "source_ids": list(group.source_ids),
            "official_source_ids": list(group.official_source_ids),
            "community_source_ids": list(group.community_source_ids),
            "user_research_source_ids": list(group.user_research_source_ids),
            "confidence_summary": dict(group.confidence_summary),
            "coverage_notes": list(group.coverage_notes),
            "fact_count": len(group.facts),
            "unstructured_signal_count": len(group.unstructured_signals),
            "kb_signal_count": len(group.kb_signals),
            "conflict_count": len(group.conflicts),
        }
        if projection == "summary":
            if group.conflicts:
                base["conflicts"] = [
                    {
                        "id": conflict.id,
                        "claim_area": conflict.claim_area,
                        "positions": conflict.positions,
                        "source_ids_by_position": conflict.source_ids_by_position,
                        "resolution_status": conflict.resolution_status,
                    }
                    for conflict in group.conflicts
                ]
            return base
        compact_facts = group.facts[:4]
        compact_unstructured_signals = group.unstructured_signals[:2]
        compact_kb_signals = group.kb_signals[:3]
        base["facts_truncated_count"] = max(0, len(group.facts) - len(compact_facts))
        base["unstructured_signals_truncated_count"] = max(
            0,
            len(group.unstructured_signals) - len(compact_unstructured_signals),
        )

        base["kb_signals_truncated_count"] = max(
            0,
            len(group.kb_signals) - len(compact_kb_signals),
        )
        base["facts"] = [
            {
                "id": fact.id,
                "kind": fact.kind,
                "competitor": fact.competitor,
                "dimension": fact.dimension,
                "values": _compact_segment_value(fact.values),
                "source_ids": list(fact.source_ids),
                "quote_ids": list(fact.quote_ids),
                "confidence": fact.confidence,
            }
            for fact in compact_facts
        ]
        base["unstructured_signals"] = [
            {
                "id": signal.id,
                "source_id": signal.source_id,
                "competitor": signal.competitor,
                "dimension": signal.dimension,
                "source_type": signal.source_type,
                "signal_summary": _trim(signal.signal_summary, 220),
                "salient_terms": list(signal.salient_terms),
                "confidence": signal.confidence,
                "quote_ids": list(signal.quote_ids),
            }
            for signal in compact_unstructured_signals
        ]
        base["kb_signals"] = [
            {
                "id": signal.id,
                "competitor": signal.competitor,
                "dimension": signal.dimension,
                "text": _trim(signal.text, 220),
                "source_ids": list(signal.source_ids),
                "merged_into": signal.merged_into,
            }
            for signal in compact_kb_signals
        ]
        base["conflicts"] = [
            conflict.model_dump(mode="json") for conflict in group.conflicts
        ]
        return base

    def _group_for_source_ids(
        self,
        group: WriterEvidenceGroup,
        source_ids: list[str],
    ) -> WriterEvidenceGroup:
        source_id_set = set(source_ids)
        kb_signals = []
        for signal in group.kb_signals:
            signal_source_ids = [
                source_id
                for source_id in signal.source_ids
                if source_id in source_id_set
            ]
            if signal_source_ids:
                kb_signals.append(
                    signal.model_copy(update={"source_ids": signal_source_ids})
                )
        conflicts = []
        for conflict in group.conflicts:
            source_ids_by_position = {
                position: [
                    source_id
                    for source_id in position_source_ids
                    if source_id in source_id_set
                ]
                for position, position_source_ids in conflict.source_ids_by_position.items()
            }
            source_ids_by_position = {
                position: position_source_ids
                for position, position_source_ids in source_ids_by_position.items()
                if position_source_ids
            }
            if source_ids_by_position:
                conflicts.append(
                    conflict.model_copy(
                        update={"source_ids_by_position": source_ids_by_position}
                    )
                )
        return group.model_copy(
            update={
                "source_ids": [
                    source_id
                    for source_id in group.source_ids
                    if source_id in source_id_set
                ],
                "official_source_ids": [
                    source_id
                    for source_id in group.official_source_ids
                    if source_id in source_id_set
                ],
                "community_source_ids": [
                    source_id
                    for source_id in group.community_source_ids
                    if source_id in source_id_set
                ],
                "user_research_source_ids": [
                    source_id
                    for source_id in group.user_research_source_ids
                    if source_id in source_id_set
                ],
                "facts": [
                    fact
                    for fact in group.facts
                    if any(source_id in source_id_set for source_id in fact.source_ids)
                ],
                "unstructured_signals": [
                    signal
                    for signal in group.unstructured_signals
                    if signal.source_id in source_id_set
                ],
                "kb_signals": kb_signals,
                "quotes": [
                    quote
                    for quote in group.quotes
                    if any(source_id in source_id_set for source_id in quote.source_ids)
                ],
                "conflicts": conflicts,
            }
        )

    def _segment_structured_knowledge_item(
        self,
        payload: object,
        *,
        compact: bool,
    ) -> object:
        if not compact or not isinstance(payload, Mapping):
            return payload
        summary: dict[str, object] = {}
        confidence = payload.get("confidence")
        if confidence is not None:
            summary["confidence"] = confidence
        for key in ("review_summary", "pricing_model", "feature_tree", "user_personas"):
            if key in payload:
                summary[f"{key}_present"] = True
        return summary or {}

    def _segment_quote(self, quote: WriterQuote, *, compact: bool) -> dict[str, object]:
        if not compact:
            payload = quote.model_dump(mode="json")
            payload["excerpt"] = _trim(quote.excerpt, 300)
            return payload
        return {
            "id": quote.id,
            "excerpt": _trim(quote.excerpt, 100),
            "source_ids": list(quote.source_ids),
            "confidence": quote.confidence,
            "raw_quote_chars": quote.raw_quote_chars,
        }

    def _coverage_matrix(self) -> dict[str, object]:
        return {
            "winner_by_dimension": self.pack.matrix.get("winner_by_dimension", {}),
            "summary": self.pack.matrix.get("summary", []),
            "cell_count": len(self.pack.matrix.get("cells", []))
            if isinstance(self.pack.matrix.get("cells"), list)
            else 0,
        }

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
            filtered_cells.append(
                {
                    **cell,
                    "value": _trim(str(cell.get("value", "")), 240),
                    "source_ids": source_ids,
                }
            )
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
        for source_id in source_tokens(markdown or ""):
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
                signal_source_ids = self._kb_signal_source_ids(kb.sources, dimension)
                for index, finding in enumerate(findings):
                    text = _trim(_string(finding), 700)
                    if not text:
                        continue
                    signal = WriterKBSignal(
                        id=f"kb:{competitor}:{dimension}:{index}",
                        competitor=competitor,
                        dimension=dimension,
                        text=text,
                        source_ids=signal_source_ids,
                    )
                    group.kb_signals.append(signal)
                    for source_id in signal.source_ids:
                        if source_id in self.registry_by_id:
                            self._mark_source_represented(source_id, signal.id)

    def _kb_signal_source_ids(self, source_ids: Iterable[str], dimension: str) -> list[str]:
        source_id_list = _unique(source_ids)
        matching_source_ids = [
            source_id
            for source_id in source_id_list
            if source_id in self.registry_by_id
            and self.registry_by_id[source_id].dimension == dimension
        ]
        return matching_source_ids or source_id_list

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


def _chunked(values: list[T], size: int) -> Iterable[list[T]]:
    chunk_size = max(1, size)
    for index in range(0, len(values), chunk_size):
        yield values[index : index + chunk_size]


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
            "customer",
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


def _compact_segment_value(value: object) -> object | None:
    if isinstance(value, str):
        return _trim(value, 80) if value.strip() else None
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        number = _float(value)
        return value if number is not None else None
    if isinstance(value, list):
        items = [
            item
            for raw_item in value[:4]
            for item in [_compact_segment_value(raw_item)]
            if item is not None
        ]
        return items or None
    if isinstance(value, Mapping):
        nested: dict[str, object] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key).strip()
            if not key:
                continue
            nested_value = _compact_segment_value(raw_value)
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
