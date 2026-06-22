from __future__ import annotations

import asyncio
import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from packages.agents.writer.assembler import (
    ReportSectionFragment,
    assemble_report_fragments,
    assemble_report_sections,
)
from packages.agents.writer.artifact_assembler import assemble_report_artifact_v2
from packages.agents.writer.artifact_publication_contract import (
    validate_report_artifact_publication,
)
from packages.agents.writer.evidence_pack import (
    SEGMENT_INPUT_TARGET_CHARS,
    build_writer_evidence_pack,
)
from packages.agents.writer.publication_contract import (
    PublicationContractIssue,
    PublicationContractResult,
    validate_publication_contract,
)
from packages.agents.writer.quality_preflight import run_writer_quality_preflight
from packages.agents.writer.repair import (
    WriterRepairPlan,
    apply_line_repair,
    build_writer_repair_plan,
    replace_markdown_section,
    report_regression_problem,
    section_regression_problem,
    structured_repair_target_for_issue,
)
from packages.agents.writer.segment_contract import (
    CORE_HEADING_KEYS,
    SECTION_ALLOWED_KEYS,
    SegmentContract,
    SUPPORT_HEADING_KEYS,
    heading_key_for,
    segment_contract_for,
    validate_segment_contract,
)
from packages.agents.writer.section_briefs import (
    build_section_briefs,
    segment_payloads_from_briefs,
)
from packages.agents.writer.structured_report import (
    BattlecardSection,
    CitedText,
    CompetitorDeepDiveSection,
    DecisionMatrixSection,
    ExecutiveSummarySection,
    ReportCore,
    ReportMetadata,
    ReportSupport,
    StructuredReport,
    SwotSection,
    UserReviewThemesSection,
)
from packages.agents.writer.structured_hygiene import (
    contains_internal_writer_term,
    find_malformed_source_token_attempts,
)
from packages.agents.writer.structured_sections import (
    StructuredReportGenerationError,
    StructuredSectionGenerationError,
)
from packages.agents.writer.structured_repair import (
    previous_recommendation_posture,
    recommendation_delta_problem,
)
from packages.business_intel.release_gate import REPORT_RICHNESS_MINIMUMS
from packages.business_intel.report_sections import (
    build_report_section_index,
    parse_report_section_marker,
)
from packages.business_intel.report_quality import compare_run_quality
from packages.business_intel.scenarios import get_scenario_pack
from packages.i18n.language import (
    language_instruction,
    normalize_output_language,
    repair_mojibake_text,
    report_label,
)
from packages.identity.source_resolver import (
    SOURCE_TOKEN_RE,
    source_token_match_value,
    source_tokens,
)
from packages.rag.grounded_prompt import build_run_grounding_prompt
from packages.research.evidence.normalization import normalized_fields_from_source
from packages.research.evidence.text import source_business_snippet
from packages.schema.api_dto import RunDetail
from packages.schema.models import (
    ComparisonCell,
    FeatureNode,
    KnowledgeClaim,
    QCIssue,
    RawSource,
    SWOTItem,
)

if TYPE_CHECKING:
    from packages.orchestrator.service import RunRecord


USER_RESEARCH_SOURCE_TYPE_ORDER = (
    "survey_simulated",
    "survey_response",
    "interview_record",
    "manual_transcript",
    "manual_user_note",
    "manual_note",
    "manual",
)
USER_RESEARCH_SOURCE_TYPES = set(USER_RESEARCH_SOURCE_TYPE_ORDER)
CJK_TEXT_RE = re.compile(r"[\u3400-\u9fff]")
PROMPT_SAFE_FIELD_ALIASES = {
    "source_registry": "source_index",
    "allowed_source_ids": "citation_source_ids",
    "claim_cards": "evidence_claims",
    "decision_cards": "decision_guidance",
    "publication_repair_issues": "report_repair_notes",
    "represented_by": "summarized_by",
}
PROMPT_DROPPED_INTERNAL_REFERENCE_KEYS = {
    "allowed_claim_card_ids",
    "allowed_decision_card_ids",
    "claim_card_ids",
    "decision_card_ids",
}
PRICING_LINE_TOKENS = (
    "price",
    "pricing",
    "cost",
    "$",
    "定价",
    "价格",
    "费用",
    "套餐",
    "月费",
    "席位",
    "报价",
)
FEATURE_LINE_TOKENS = (
    "feature",
    "capability",
    "function",
    "功能",
    "特征",
    "能力",
    "代码补全",
    "代理",
    "上下文",
)
PERSONA_LINE_TOKENS = (
    "persona",
    "customer",
    "user",
    "buyer",
    "use case",
    "用户",
    "用户画像",
    "买家",
    "采购",
    "客户",
    "访谈",
    "调查",
    "评价",
    "评论",
    "采纳",
    "采用",
    "切换",
    "痛点",
    "阻力",
)
CLAIM_LINE_TOKENS = PRICING_LINE_TOKENS + FEATURE_LINE_TOKENS + PERSONA_LINE_TOKENS
WRITER_NORMALIZED_FIELD_DROP_KEYS = {
    "content",
    "extracted_text",
    "full_text",
    "html",
    "markdown",
    "page_content",
    "raw",
    "raw_html",
    "raw_markdown",
    "raw_text",
    "text",
}
WRITER_NORMALIZED_FIELD_QUOTE_KEY_PARTS = (
    "evidence",
    "excerpt",
    "quote",
)
WRITER_NORMALIZED_FIELD_LONG_KEY_PARTS = (
    "blocker",
    "claim",
    "description",
    "note",
    "pain",
    "rationale",
    "reason",
    "summary",
    "trigger",
)
WRITER_NORMALIZED_SNIPPET_LIMIT = 1600
STRUCTURED_SECTION_INPUT_TARGET_CHARS = 28_000


def writer_user_research_policy_text() -> str:
    source_types = ", ".join(USER_RESEARCH_SOURCE_TYPE_ORDER)
    return (
        f"Treat {source_types} as user-research signals, not as official factual proof."
    )


def _assemble_repair_quality_gate(
    detail: RunDetail,
    markdown: str,
) -> dict[str, object]:
    candidate = detail.model_copy(update={"report_md": markdown})
    comparison = compare_run_quality(candidate)
    metric_by_name = {metric.name: metric.target_value for metric in comparison.metrics}
    quality_gate_metrics = {
        name: float(metric_by_name.get(name) or 0.0)
        for name in REPORT_RICHNESS_MINIMUMS
    }
    reasons = [
        name
        for name, minimum in REPORT_RICHNESS_MINIMUMS.items()
        if quality_gate_metrics[name] < minimum
    ]
    return {
        "quality_gate_passed": not reasons,
        "quality_gate_reasons": reasons,
        "quality_gate_metrics": quality_gate_metrics,
        **quality_gate_metrics,
    }


def _parse_structured_section_response(
    response: str,
    section_schema: type[BaseModel],
    allowed_source_ids: set[str],
) -> BaseModel:
    cleaned_response = response.strip()
    if not cleaned_response.startswith("{"):
        raise ValueError("structured writer response must be a JSON object")
    try:
        payload = json.loads(cleaned_response)
        payload = _normalize_structured_section_payload(payload)
        section = section_schema.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(f"structured writer response validation failed: {exc}") from exc

    cited_source_ids = _source_ids_from_section(section)
    invalid_source_ids = cited_source_ids - allowed_source_ids
    if invalid_source_ids:
        invalid = ", ".join(sorted(invalid_source_ids))
        raise ValueError(f"structured writer response used disallowed source_ids: {invalid}")
    return section


def _normalize_structured_section_payload(value: Any) -> Any:
    if isinstance(value, list):
        return [_normalize_structured_section_payload(item) for item in value]
    if not isinstance(value, dict):
        return value

    evidence_gap_hint = value.get("evidence_gap") is True
    normalized = {
        key: _normalize_structured_section_payload(child)
        for key, child in value.items()
        if key != "evidence_gap"
    }
    if normalized.get("evidence_role") == "evidence_gap" or evidence_gap_hint:
        normalized["evidence_role"] = "evidence_gap"
        normalized["confidence"] = "low"
    return normalized


def _structured_section_contract_instructions(
    section_schema: type[BaseModel],
) -> list[str]:
    if section_schema is CitedTextListSection:
        return [
            (
                'CitedTextListSection output must be exactly {"items": [...]} '
                "where every item is a CitedText data object."
            ),
            (
                "Schema JSON describes the shape; it is not the output. "
                "Never return $defs, properties, required, title, type, or "
                "additionalProperties as top-level keys."
            ),
        ]
    if section_schema is BattlecardSection:
        return [
            (
                "BattlecardSection is a cited derivative section. Every CitedText "
                "in use_when, attack_points, defense_points, likely_objections, "
                "and rebuttal_talk_tracks must include 1-3 source_ids inherited "
                "from the source-backed matrix, SWOT, deep-dive, user, or "
                "community evidence supporting that talk track."
            ),
            (
                "Do not output inference with empty source_ids. If a talk track "
                "cannot be cited from allowed_source_ids, move it to "
                "proof_needed_before_external_use or evidence_limits as "
                'evidence_role="evidence_gap", confidence="low".'
            ),
        ]
    return []


def _structured_section_generation_error(
    segment: Mapping[str, object],
    section_schema: type[BaseModel],
    exc: BaseException,
    *,
    error_kind: str,
    attempt: str,
) -> StructuredSectionGenerationError:
    section_id = str(segment.get("section_id") or "unknown")
    section_key = str(segment.get("section_key") or section_id)
    message = str(exc).strip() or exc.__class__.__name__
    return StructuredSectionGenerationError(
        section_key=section_key,
        section_id=section_id,
        schema_name=section_schema.__name__,
        message=message,
        error_kind=error_kind,
        attempt=attempt,
    )


def _source_ids_from_section(section: BaseModel) -> set[str]:
    source_ids: set[str] = set()

    def collect(value: object) -> None:
        if isinstance(value, dict):
            raw_source_id = value.get("source_id")
            if isinstance(raw_source_id, str):
                source_id = raw_source_id.strip()
                if source_id:
                    source_ids.add(source_id)
            raw_source_ids = value.get("source_ids")
            if isinstance(raw_source_ids, list):
                source_ids.update(
                    source_id.strip()
                    for source_id in raw_source_ids
                    if isinstance(source_id, str) and source_id.strip()
                )
            for child in value.values():
                collect(child)
            return
        if isinstance(value, list):
            for child in value:
                collect(child)

    collect(section.model_dump())
    return source_ids


def _strong_writer_source_ids(detail: RunDetail) -> set[str]:
    strong: set[str] = set()
    for source in detail.raw_sources:
        confidence = getattr(source, "confidence", None)
        source_type = str(getattr(source, "source_type", "") or "").casefold()
        metadata = getattr(source, "metadata", {}) or {}
        if confidence is not None and float(confidence) >= 0.75:
            strong.add(source.id)
        if source_type in {"official", "documentation", "pricing"}:
            strong.add(source.id)
        if metadata.get("official_source") is True or metadata.get("trusted_source") is True:
            strong.add(source.id)
    return strong


def _schema_first_real_run(detail: RunDetail, structured_enabled: bool) -> bool:
    return structured_enabled and detail.execution_mode == "real"


def _structured_markdown_fallback_allowed(
    detail: RunDetail, structured_enabled: bool
) -> bool:
    if not structured_enabled:
        return True
    return not _schema_first_real_run(detail, structured_enabled)


def build_structured_writer_section_plan(
    *, competitors: list[str], dimensions: list[str]
) -> list[dict[str, object]]:
    return [
        {
            "section_id": "executive_summary",
            "schema": "ExecutiveSummarySection",
            "owns_markdown_layout": False,
        },
        {
            "section_id": "decision_summary",
            "schema": "list[CitedText]",
            "owns_markdown_layout": False,
        },
        {
            "section_id": "competitive_findings",
            "schema": "list[CitedText]",
            "owns_markdown_layout": False,
        },
        {
            "section_id": "user_review_themes",
            "schema": "UserReviewThemesSection",
            "owns_markdown_layout": False,
        },
        *[
            {
                "section_id": "competitor_deep_dive",
                "competitor": competitor,
                "schema": "CompetitorDeepDiveSection",
                "owns_markdown_layout": False,
            }
            for competitor in competitors
        ],
        {
            "section_id": "decision_matrix",
            "dimensions": list(dimensions),
            "schema": "DecisionMatrixSection",
            "owns_markdown_layout": False,
        },
        {
            "section_id": "swot",
            "schema": "SwotSection",
            "owns_markdown_layout": False,
        },
        {
            "section_id": "battlecard",
            "schema": "BattlecardSection",
            "owns_markdown_layout": False,
        },
        {
            "section_id": "community_triangulation",
            "schema": "list[CitedText]",
            "owns_markdown_layout": False,
        },
        {
            "section_id": "support",
            "schema": "ReportSupport",
            "owns_markdown_layout": False,
        },
    ]


class WriterEvidencePreflightError(RuntimeError):
    """Raised when writer evidence cannot safely be sent to the LLM."""


class CitedTextListSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CitedText] = Field(min_length=1)


def _structured_section_key(item: dict[str, object]) -> str:
    section_id = str(item["section_id"])
    if section_id == "competitor_deep_dive":
        return f"competitor_deep_dive::{item['competitor']}"
    return section_id


def _structured_section_schema(schema_name: object) -> type[BaseModel]:
    schemas: dict[str, type[BaseModel]] = {
        "ExecutiveSummarySection": ExecutiveSummarySection,
        "list[CitedText]": CitedTextListSection,
        "UserReviewThemesSection": UserReviewThemesSection,
        "CompetitorDeepDiveSection": CompetitorDeepDiveSection,
        "DecisionMatrixSection": DecisionMatrixSection,
        "SwotSection": SwotSection,
        "BattlecardSection": BattlecardSection,
        "ReportSupport": ReportSupport,
    }
    return schemas[str(schema_name)]


def _structured_section_language_instruction(segment: dict[str, object]) -> str:
    if normalize_output_language(segment.get("output_language")) == "zh-CN":
        return (
            "Write every narrative text field in Simplified Chinese. Preserve "
            "product names, source IDs, URLs, and technical terms such as model "
            "names and API names in their original language when appropriate."
        )
    return "Write every narrative text field in English."


def _structured_section_inputs(
    *, evidence_pack_result, competitors: list[str], dimensions: list[str]
) -> dict[str, dict[str, object]]:
    segment_inputs = _structured_budgeted_segment_inputs(evidence_pack_result)
    base = None if segment_inputs else evidence_pack_result.to_prompt_json()
    output_language = getattr(
        getattr(evidence_pack_result, "pack", None),
        "output_language",
        "zh-CN",
    )
    inputs: dict[str, dict[str, object]] = {}
    for item in build_structured_writer_section_plan(
        competitors=competitors,
        dimensions=dimensions,
    ):
        section_id = str(item["section_id"])
        segment = {
            "section_id": section_id,
            "competitor": item.get("competitor"),
            "dimensions": item.get("dimensions", dimensions),
            "output_language": output_language,
        }
        if segment_inputs:
            matching_segments = _select_structured_evidence_segments(
                section_id=section_id,
                competitor=item.get("competitor"),
                segment_inputs=segment_inputs,
            )
            primary_segments = [
                _project_structured_section_segment(
                    segment,
                    section_id=section_id,
                )
                for segment in matching_segments[:1]
            ]
            omitted_segments = matching_segments[1:]
            segment["evidence_segments"] = primary_segments
            segment["allowed_source_ids"] = _source_ids_from_structured_segments(
                primary_segments
            )
            segment["additional_segment_count"] = len(omitted_segments)
            segment["additional_segment_refs"] = [
                _structured_segment_ref(omitted_segment)
                for omitted_segment in omitted_segments
            ]
        else:
            segment["evidence_pack"] = base
        inputs[_structured_section_key(item)] = segment
    return inputs


def _project_structured_section_segment(
    segment: dict[str, object],
    *,
    section_id: str,
) -> dict[str, object]:
    if _json_chars(segment) <= STRUCTURED_SECTION_INPUT_TARGET_CHARS:
        return segment

    projection_levels = (
        {
            "source_title_limit": 96,
            "coverage_note_count": 2,
            "coverage_note_limit": 140,
            "fact_count": 2,
            "signal_count": 1,
            "kb_signal_count": 1,
            "conflict_count": 1,
            "quote_count": 4,
            "text_limit": 180,
            "matrix_summary_count": 3,
            "matrix_value_limit": 220,
            "source_detail_level": 2,
            "group_source_id_count": 6,
        },
        {
            "source_title_limit": 80,
            "coverage_note_count": 1,
            "coverage_note_limit": 100,
            "fact_count": 1,
            "signal_count": 1,
            "kb_signal_count": 1,
            "conflict_count": 1,
            "quote_count": 2,
            "text_limit": 140,
            "matrix_summary_count": 2,
            "matrix_value_limit": 160,
            "source_detail_level": 2,
            "group_source_id_count": 6,
        },
        {
            "source_title_limit": 64,
            "coverage_note_count": 0,
            "coverage_note_limit": 80,
            "fact_count": 1,
            "signal_count": 0,
            "kb_signal_count": 1,
            "conflict_count": 0,
            "quote_count": 0,
            "text_limit": 100,
            "matrix_summary_count": 1,
            "matrix_value_limit": 100,
            "source_detail_level": 1,
            "group_source_id_count": 4,
        },
        {
            "source_title_limit": 0,
            "coverage_note_count": 0,
            "coverage_note_limit": 0,
            "fact_count": 1,
            "signal_count": 0,
            "kb_signal_count": 0,
            "conflict_count": 0,
            "quote_count": 0,
            "text_limit": 80,
            "matrix_summary_count": 1,
            "matrix_value_limit": 60,
            "source_detail_level": 0,
            "group_source_id_count": 3,
        },
    )
    original_chars = _json_chars(segment)
    for level, config in enumerate(projection_levels, start=1):
        projected = _compact_structured_section_segment(
            segment,
            section_id=section_id,
            original_chars=original_chars,
            projection_level=level,
            config=config,
        )
        if _json_chars(projected) <= STRUCTURED_SECTION_INPUT_TARGET_CHARS:
            return projected
    return _compact_structured_section_segment(
        segment,
        section_id=section_id,
        original_chars=original_chars,
        projection_level=len(projection_levels),
        config=projection_levels[-1],
    )


def _compact_structured_section_segment(
    segment: dict[str, object],
    *,
    section_id: str,
    original_chars: int,
    projection_level: int,
    config: Mapping[str, int],
) -> dict[str, object]:
    projected: dict[str, object] = {}
    for key in (
        "schema_version",
        "segment_name",
        "segment_kind",
        "section_id",
        "output_language",
        "segment_essential",
        "segment_competitor",
        "segment_dimension",
        "segment_batch",
        "shard_output_format",
        "coverage",
    ):
        if key in segment:
            projected[key] = segment[key]
    projected["section_id"] = projected.get("section_id") or section_id
    projected["section_projection"] = "compact"
    projected["section_projection_level"] = projection_level
    projected["original_segment_input_chars"] = original_chars
    projected["section_input_target_chars"] = STRUCTURED_SECTION_INPUT_TARGET_CHARS

    source_registry = segment.get("source_registry")
    if isinstance(source_registry, list):
        projected["source_registry"] = [
            _compact_section_source_registry_item(
                item,
                detail_level=config["source_detail_level"],
                title_limit=config["source_title_limit"],
            )
            for item in source_registry
            if isinstance(item, Mapping)
        ]

    groups = segment.get("groups")
    if isinstance(groups, list):
        projected["groups"] = [
            _compact_section_group_payload(group, config=config)
            for group in groups
            if isinstance(group, Mapping)
        ]

    quotes = segment.get("quotes")
    quote_count = config["quote_count"]
    if isinstance(quotes, list) and quote_count > 0:
        projected["quotes"] = [
            _compact_section_quote_payload(quote, text_limit=config["text_limit"])
            for quote in quotes[:quote_count]
            if isinstance(quote, Mapping)
        ]
        projected["quotes_truncated_count"] = max(0, len(quotes) - quote_count)
    elif isinstance(quotes, list):
        projected["quote_count"] = len(quotes)
        projected["quotes_omitted_for_section_projection"] = True

    matrix = segment.get("matrix")
    if isinstance(matrix, Mapping):
        projected["matrix"] = _compact_section_matrix_payload(matrix, config=config)

    structured_knowledge = segment.get("structured_knowledge")
    if isinstance(structured_knowledge, Mapping):
        projected["structured_knowledge"] = structured_knowledge

    allowed_source_ids = _string_values(segment.get("allowed_source_ids"))
    if allowed_source_ids:
        projected["allowed_source_id_count"] = len(allowed_source_ids)

    projected["segment_input_chars"] = _json_chars(projected)
    return projected


def _compact_section_source_registry_item(
    item: Mapping[str, object],
    *,
    detail_level: int,
    title_limit: int,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": item.get("id") or item.get("source_id"),
        "competitor": item.get("competitor"),
        "dimension": item.get("dimension"),
        "source_type": item.get("source_type"),
    }
    if detail_level >= 1:
        payload.update(
            {
                "confidence": item.get("confidence"),
                "authority_role": item.get("authority_role"),
            }
        )
    if detail_level >= 2:
        payload.update(
            {
                "covered_competitors": _string_values(item.get("covered_competitors")),
                "title": _compact_section_text(item.get("title"), title_limit),
                "quality_score": item.get("quality_score"),
                "has_normalized_fields": item.get("has_normalized_fields"),
                "has_community_clusters": item.get("has_community_clusters"),
                "no_signal_reason": item.get("no_signal_reason"),
            }
        )
    return {
        key: value
        for key, value in payload.items()
        if value not in (None, "", [])
    }


def _prompt_safe_writer_segment(segment: Mapping[str, object]) -> dict[str, object]:
    payload = dict(segment)
    payload.pop("allowed_claim_card_ids", None)
    payload.pop("allowed_decision_card_ids", None)

    section_brief = payload.get("section_brief")
    if isinstance(section_brief, Mapping):
        safe_brief = dict(section_brief)
        safe_brief.pop("allowed_claim_card_ids", None)
        safe_brief.pop("allowed_decision_card_ids", None)
        payload["section_brief"] = safe_brief

    claim_cards = payload.get("claim_cards")
    if isinstance(claim_cards, list):
        payload["claim_cards"] = [
            _prompt_safe_claim_card(card)
            for card in claim_cards
            if isinstance(card, Mapping)
        ]

    decision_cards = payload.get("decision_cards")
    if isinstance(decision_cards, list):
        payload["decision_cards"] = [
            _prompt_safe_decision_card(card)
            for card in decision_cards
            if isinstance(card, Mapping)
        ]
    return _reader_safe_prompt_field_names(payload)


def _reader_safe_prompt_field_names(value: object) -> object:
    if isinstance(value, Mapping):
        payload: dict[str, object] = {}
        for key, child in value.items():
            if key in PROMPT_DROPPED_INTERNAL_REFERENCE_KEYS:
                continue
            safe_key = PROMPT_SAFE_FIELD_ALIASES.get(str(key), str(key))
            payload[safe_key] = _reader_safe_prompt_field_names(child)
        return payload
    if isinstance(value, list):
        return [_reader_safe_prompt_field_names(item) for item in value]
    return value


def _reader_safe_prompt_json_text(json_text: str) -> str:
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError:
        return json_text
    return json.dumps(
        _reader_safe_prompt_field_names(payload),
        ensure_ascii=False,
    )


def _prompt_safe_claim_card(card: Mapping[str, object]) -> dict[str, object]:
    payload = dict(card)
    payload.pop("id", None)
    return payload


def _prompt_safe_decision_card(card: Mapping[str, object]) -> dict[str, object]:
    payload = dict(card)
    payload.pop("id", None)
    payload.pop("claim_card_ids", None)
    return payload


def _prompt_safe_citation_error_ids(source_ids: Sequence[str]) -> list[str]:
    return [
        source_id
        for source_id in _string_values(source_ids)
        if not _is_internal_writer_reference_id(source_id)
    ]


def _is_internal_writer_reference_id(value: str) -> bool:
    return value.startswith(("claim-", "decision-", "fact:", "signal:", "kb:"))


def _compact_section_group_payload(
    group: Mapping[str, object],
    *,
    config: Mapping[str, int],
) -> dict[str, object]:
    payload: dict[str, object] = {
        key: value
        for key, value in {
            "competitor": group.get("competitor"),
            "dimension": group.get("dimension"),
            "confidence_summary": group.get("confidence_summary"),
            "fact_count": group.get("fact_count"),
            "unstructured_signal_count": group.get("unstructured_signal_count"),
            "kb_signal_count": group.get("kb_signal_count"),
            "conflict_count": group.get("conflict_count"),
        }.items()
        if value not in (None, "", [])
    }
    for source_key in (
        "source_ids",
        "official_source_ids",
        "community_source_ids",
        "user_research_source_ids",
    ):
        _add_compact_source_id_scope(
            payload,
            source_key,
            group.get(source_key),
            max_count=config["group_source_id_count"],
        )
    coverage_notes = _string_values(group.get("coverage_notes"))
    note_count = config["coverage_note_count"]
    if note_count > 0:
        payload["coverage_notes"] = [
            _compact_section_text(note, config["coverage_note_limit"])
            for note in coverage_notes[:note_count]
        ]
    if len(coverage_notes) > note_count:
        payload["coverage_notes_truncated_count"] = len(coverage_notes) - note_count

    payload["facts"] = _compact_section_payload_list(
        group.get("facts"),
        limit=config["fact_count"],
        text_limit=config["text_limit"],
    )
    payload["unstructured_signals"] = _compact_section_payload_list(
        group.get("unstructured_signals"),
        limit=config["signal_count"],
        text_limit=config["text_limit"],
    )
    payload["kb_signals"] = _compact_section_payload_list(
        group.get("kb_signals"),
        limit=config["kb_signal_count"],
        text_limit=config["text_limit"],
    )
    conflicts = group.get("conflicts")
    payload["conflicts"] = _compact_section_payload_list(
        conflicts,
        limit=config["conflict_count"],
        text_limit=config["text_limit"],
    )
    for key in ("facts", "unstructured_signals", "kb_signals", "conflicts"):
        if not payload.get(key):
            payload.pop(key, None)
    return payload


def _add_compact_source_id_scope(
    payload: dict[str, object],
    key: str,
    value: object,
    *,
    max_count: int,
) -> None:
    source_ids = _string_values(value)
    if not source_ids:
        return
    payload[key] = source_ids[:max_count]
    payload[f"{key}_total_count"] = len(source_ids)
    if len(source_ids) > max_count:
        payload[f"{key}_truncated_count"] = len(source_ids) - max_count


def _compact_section_payload_list(
    value: object,
    *,
    limit: int,
    text_limit: int,
) -> list[object]:
    if not isinstance(value, list) or limit <= 0:
        return []
    return [_compact_section_value(item, text_limit) for item in value[:limit]]


def _compact_section_quote_payload(
    quote: Mapping[str, object],
    *,
    text_limit: int,
) -> dict[str, object]:
    return {
        key: value
        for key, value in {
            "id": quote.get("id"),
            "excerpt": _compact_section_text(quote.get("excerpt"), text_limit),
            "full_text_source_ids": _string_values(quote.get("full_text_source_ids")),
        }.items()
        if value not in (None, "", [])
    }


def _compact_section_matrix_payload(
    matrix: Mapping[str, object],
    *,
    config: Mapping[str, int],
) -> dict[str, object]:
    summary = _string_values(matrix.get("summary"))
    cells = matrix.get("cells")
    return {
        key: value
        for key, value in {
            "winner_by_dimension": matrix.get("winner_by_dimension"),
            "summary": [
                _compact_section_text(item, config["matrix_value_limit"])
                for item in summary[: config["matrix_summary_count"]]
            ],
            "summary_truncated_count": max(
                0,
                len(summary) - config["matrix_summary_count"],
            ),
            "cells": (
                [
                    _compact_section_matrix_cell(cell, config=config)
                    for cell in cells
                    if isinstance(cell, Mapping)
                ]
                if isinstance(cells, list)
                else []
            ),
        }.items()
        if value not in (None, "", [])
    }


def _compact_section_matrix_cell(
    cell: Mapping[str, object],
    *,
    config: Mapping[str, int],
) -> dict[str, object]:
    return {
        key: value
        for key, value in {
            "competitor": cell.get("competitor"),
            "dimension": cell.get("dimension"),
            "value": _compact_section_text(cell.get("value"), config["matrix_value_limit"]),
            "source_ids": _string_values(cell.get("source_ids")),
            "confidence": cell.get("confidence"),
        }.items()
        if value not in (None, "", [])
    }


def _compact_section_value(value: object, text_limit: int) -> object:
    if isinstance(value, str):
        return _compact_section_text(value, text_limit)
    if isinstance(value, Mapping):
        compact: dict[str, object] = {}
        for key, child in value.items():
            if key in {"url", "short_source_note"}:
                continue
            compact_value = _compact_section_value(child, text_limit)
            if compact_value not in (None, "", []):
                compact[str(key)] = compact_value
        return compact
    if isinstance(value, list):
        return [
            compact_item
            for item in value[:4]
            for compact_item in [_compact_section_value(item, text_limit)]
            if compact_item not in (None, "", [])
        ]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)


def _compact_section_text(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _string_values(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _json_chars(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False))


def _structured_budgeted_segment_inputs(evidence_pack_result) -> list[dict[str, object]]:
    if not hasattr(evidence_pack_result, "segment_inputs"):
        return []
    try:
        segments = evidence_pack_result.segment_inputs()
    except TypeError:
        return []
    if not isinstance(segments, list):
        return []
    return [dict(segment) for segment in segments if isinstance(segment, dict)]


def _select_structured_evidence_segments(
    *,
    section_id: str,
    competitor: object,
    segment_inputs: list[dict[str, object]],
) -> list[dict[str, object]]:
    target_segment_names = {
        "executive_summary": {"decision_summary", "side_by_side_matrix"},
        "decision_summary": {"decision_summary"},
        "competitive_findings": {"decision_summary", "side_by_side_matrix"},
        "user_review_themes": {"user_research"},
        "competitor_deep_dive": {"competitor_deep_dives"},
        "decision_matrix": {"decision_summary", "side_by_side_matrix"},
        "swot": {"swot_analysis"},
        "battlecard": {"decision_summary", "battlecard"},
        "community_triangulation": {"user_research"},
        "support": {"support_appendix"},
    }.get(section_id, set())

    selected: list[dict[str, object]] = []
    for segment in segment_inputs:
        segment_name = str(segment.get("segment_name") or segment.get("section_id") or "")
        if segment_name not in target_segment_names:
            continue
        if section_id == "competitor_deep_dive" and competitor is not None:
            segment_competitor = segment.get("segment_competitor") or segment.get(
                "competitor"
            )
            if segment_competitor and str(segment_competitor) != str(competitor):
                continue
        selected.append(segment)
    return selected


def _structured_segment_ref(segment: dict[str, object]) -> dict[str, object]:
    source_ids = _source_ids_from_structured_segments([segment])
    ref = {
        "segment_name": segment.get("segment_name") or segment.get("section_id"),
        "segment_competitor": segment.get("segment_competitor")
        or segment.get("competitor"),
        "segment_batch": segment.get("segment_batch"),
        "source_count": len(source_ids),
    }
    if len(source_ids) <= 6:
        ref["allowed_source_ids"] = source_ids
    else:
        ref["representative_source_ids"] = source_ids[:6]
        ref["allowed_source_ids_total_count"] = len(source_ids)
        ref["allowed_source_ids_truncated_count"] = len(source_ids) - 6
    return ref


def _source_ids_from_structured_segments(
    segments: list[dict[str, object]],
) -> list[str]:
    source_ids: set[str] = set()

    def add_source_id(value: object) -> None:
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                source_ids.add(cleaned)

    def collect_source_registry(value: object) -> None:
        if isinstance(value, dict):
            registry = value.get("source_registry")
            if isinstance(registry, list):
                for item in registry:
                    if isinstance(item, dict):
                        add_source_id(item.get("id"))
                        add_source_id(item.get("source_id"))
            allowed = value.get("allowed_source_ids")
            if isinstance(allowed, list):
                for source_id in allowed:
                    add_source_id(source_id)
            for child in value.values():
                collect_source_registry(child)
            return
        if isinstance(value, list):
            for child in value:
                collect_source_registry(child)

    collect_source_registry(segments)
    return sorted(source_ids)


class WriterAgentMixin:
    async def _real_writer_step(self, record: RunRecord) -> None:
        detail = record.detail
        detail.current_node = "writer"
        self._consume_queued_agent_messages(
            record,
            to_agent="writer",
            consumer_agent="writer",
            message_types={"reflection_ready"},
        )
        redo_messages = []
        for to_agent in ("writer", "writer_only"):
            redo_messages.extend(
                self._consume_queued_agent_messages(
                    record,
                    to_agent=to_agent,
                    consumer_agent="writer",
                    message_types={"redo_request"},
                )
            )
        await self.emit(detail.id, "node_started", "writer", None, "Calling report writer.")
        previous_report = detail.report_md
        writer_mode = "real LLM call"
        writer_error: str | None = None
        writer_repair_mode = "none"
        writer_repair_sections: list[str] = []
        writer_repair_decision = ""
        anti_regression_reason: str | None = None
        previous_report_protected = False
        structured_recommendation_guard_preserved = False
        structured_scoped_merge_applied = False
        structured_scoped_regression_checked = False
        redo_issue_by_id: dict[str, QCIssue] = {}
        for message in redo_messages:
            for item in message.payload.get("issues", []):
                issue = QCIssue.model_validate(item)
                redo_issue_by_id.setdefault(issue.id, issue)
        pending_redo = record.pending_graph_redo
        pending_issue_ids: set[str] = set()
        writer_only_pending_issue_ids: set[str] = set()
        if pending_redo is not None and pending_redo.issue_ids:
            pending_issue_ids = set(pending_redo.issue_ids)
            for issue in detail.qa_findings:
                if issue.id in pending_issue_ids:
                    redo_issue_by_id.setdefault(issue.id, issue)
            for message in record.detail.agent_messages:
                if message.message_type != "redo_request":
                    continue
                raw_issue_ids = message.payload.get("issue_ids", [])
                if not raw_issue_ids or not (set(raw_issue_ids) & pending_issue_ids):
                    continue
                for item in message.payload.get("issues", []):
                    issue = QCIssue.model_validate(item)
                    if issue.id in pending_issue_ids:
                        redo_issue_by_id.setdefault(issue.id, issue)
            if pending_redo.redo_scope.kind == "writer_only":
                writer_only_pending_issue_ids = pending_issue_ids
        redo_issues = list(redo_issue_by_id.values())
        structured_targets = [
            target
            for issue in redo_issues
            if (target := structured_repair_target_for_issue(issue)) is not None
        ]
        redo_source_message_ids = [message.id for message in redo_messages]
        if writer_only_pending_issue_ids:
            writer_only_messages_without_issue_ids: list[str] = []
            for message in record.detail.agent_messages:
                if message.message_type != "redo_request":
                    continue
                raw_issue_ids = message.payload.get("issue_ids", [])
                if raw_issue_ids:
                    message_issue_ids = set(raw_issue_ids)
                    if message_issue_ids & writer_only_pending_issue_ids:
                        redo_source_message_ids.append(message.id)
                    continue
                redo_scope = message.payload.get("redo_scope", {})
                redo_scope_kind = (
                    redo_scope.get("kind") if isinstance(redo_scope, dict) else None
                )
                if redo_scope_kind == "writer_only":
                    writer_only_messages_without_issue_ids.append(message.id)
            if len(writer_only_messages_without_issue_ids) == 1:
                redo_source_message_ids.append(writer_only_messages_without_issue_ids[0])
        redo_source_message_ids = list(dict.fromkeys(redo_source_message_ids))
        upstream_redo_stages = {"collector", "analyst", "comparator", "full"}
        upstream_data_changed = (
            pending_redo is not None
            and (
                pending_redo.stage in upstream_redo_stages
                or pending_redo.redo_scope.kind in upstream_redo_stages
            )
        )
        if redo_issues or upstream_data_changed:
            repair_plan = build_writer_repair_plan(
                detail,
                redo_issues,
                upstream_data_changed=upstream_data_changed,
            )
        else:
            repair_plan = None
        timeout_seconds = max(0.05, float(self._settings.writer_timeout_seconds))
        assemble_repair_succeeded = False
        if repair_plan is not None and repair_plan.mode == "assemble":
            writer_repair_mode = repair_plan.mode
            writer_repair_sections = repair_plan.sections
            writer_repair_decision = repair_plan.reason
            previous_report_protected = repair_plan.previous_report_protectable
            assembled = assemble_report_sections(
                [previous_report],
                output_language=detail.output_language,
                competitors=detail.plan.competitors,
            )
            preflight = run_writer_quality_preflight(detail, assembled.markdown)
            quality_gate = _assemble_repair_quality_gate(detail, assembled.markdown)
            await self.emit(
                detail.id,
                "writer_assemble_repair_completed",
                "writer",
                None,
                "Writer assembler repair completed",
                {
                    **assembled.telemetry,
                    "quality_preflight": preflight.telemetry_payload(),
                    **quality_gate,
                },
            )
            if preflight.passed and quality_gate["quality_gate_passed"]:
                detail.report_md = self._harden_report_markdown(
                    detail,
                    assembled.markdown,
                )
                writer_mode = "writer repair: assemble"
                assemble_repair_succeeded = True
            else:
                repair_plan = WriterRepairPlan(
                    mode="full",
                    reason=(
                        "assembler repair did not pass writer quality preflight "
                        "or depth gate"
                    ),
                    previous_report_protectable=True,
                    anti_regression_required=True,
                )
        if (
            not assemble_repair_succeeded
            and repair_plan is not None
            and repair_plan.mode == "line"
        ):
            writer_repair_mode = repair_plan.mode
            writer_repair_sections = repair_plan.sections
            writer_repair_decision = repair_plan.reason
            previous_report_protected = repair_plan.previous_report_protectable
            detail.report_md = self._harden_report_markdown(
                detail,
                apply_line_repair(previous_report, redo_issues),
            )
            writer_mode = "writer repair: line"
        elif (
            not assemble_repair_succeeded
            and repair_plan is not None
            and repair_plan.mode == "section"
        ):
            writer_repair_mode = repair_plan.mode
            writer_repair_sections = repair_plan.sections
            writer_repair_decision = repair_plan.reason
            previous_report_protected = repair_plan.previous_report_protectable
            try:
                report_md = previous_report
                for section in repair_plan.sections:
                    section_md = await asyncio.wait_for(
                        self._writer_section_repair_markdown(
                            record,
                            sections=[section],
                            previous_report=previous_report,
                        ),
                        timeout=timeout_seconds,
                    )
                    self._require_writer_report_output(section_md)
                    report_md = replace_markdown_section(
                        report_md,
                        section,
                        detail.output_language,
                        section_md,
                    )
                hardened_report = self._harden_report_markdown(detail, report_md)
                if repair_plan.anti_regression_required:
                    repair_comparison_metrics = detail.metrics.model_copy(
                        update={
                            "llm_calls": max(detail.metrics.llm_calls, 1),
                            "source_coverage_rate": max(
                                detail.metrics.source_coverage_rate, 1.0
                            ),
                            "claim_citation_rate": max(
                                detail.metrics.claim_citation_rate, 1.0
                            ),
                        }
                    )
                    previous_detail = detail.model_copy(
                        update={
                            "report_md": previous_report,
                            "qa_findings": [],
                            "metrics": repair_comparison_metrics,
                        }
                    )
                    candidate_detail = detail.model_copy(
                        update={
                            "report_md": hardened_report,
                            "qa_findings": [],
                            "metrics": repair_comparison_metrics,
                        }
                    )
                    anti_regression_reason = section_regression_problem(
                        previous_detail,
                        candidate_detail,
                        protected_sections=repair_plan.sections,
                    )
                if anti_regression_reason:
                    detail.report_md = self._preserve_hardened_previous_report(
                        detail,
                        previous_report,
                    )
                    writer_mode = "preserved previous report after writer anti-regression"
                else:
                    detail.report_md = hardened_report
                    writer_mode = "writer repair: section"
            except WriterEvidencePreflightError as exc:
                writer_error = str(exc)
                await self._fail_writer_without_report(
                    record,
                    writer_error,
                    writer_repair_mode=writer_repair_mode,
                    writer_repair_sections=writer_repair_sections,
                    writer_repair_decision=writer_repair_decision,
                    anti_regression_reason=anti_regression_reason,
                    previous_report_protected=previous_report_protected,
                )
            except TimeoutError as exc:
                timeout_reason = str(exc) or f"writer LLM exceeded {timeout_seconds:g}s"
                writer_error = timeout_reason
                if previous_report.strip():
                    detail.report_md = self._preserve_hardened_previous_report(
                        detail,
                        previous_report,
                    )
                    writer_mode = "preserved previous report after writer error"
                else:
                    await self._fail_writer_without_report(
                        record,
                        writer_error,
                        writer_repair_mode=writer_repair_mode,
                        writer_repair_sections=writer_repair_sections,
                        writer_repair_decision=writer_repair_decision,
                        anti_regression_reason=anti_regression_reason,
                        previous_report_protected=previous_report_protected,
                    )
            except Exception as exc:  # noqa: BLE001 - preserve existing reports, fail otherwise.
                writer_error = str(exc)
                if previous_report.strip():
                    detail.report_md = self._preserve_hardened_previous_report(
                        detail,
                        previous_report,
                    )
                    writer_mode = "preserved previous report after writer error"
                else:
                    await self._fail_writer_without_report(
                        record,
                        writer_error,
                        writer_repair_mode=writer_repair_mode,
                        writer_repair_sections=writer_repair_sections,
                        writer_repair_decision=writer_repair_decision,
                        anti_regression_reason=anti_regression_reason,
                        previous_report_protected=previous_report_protected,
                    )
        elif not assemble_repair_succeeded:
            if repair_plan is not None and repair_plan.mode == "full":
                writer_repair_mode = repair_plan.mode
                writer_repair_sections = repair_plan.sections
                writer_repair_decision = repair_plan.reason
                previous_report_protected = repair_plan.previous_report_protectable
            evidence_pack_result = build_writer_evidence_pack(detail)
            await self.emit(
                detail.id,
                "writer_preflight",
                "writer",
                None,
                "Writer evidence pack prepared.",
                evidence_pack_result.telemetry_payload(),
            )
            preflight_errors = evidence_pack_result.preflight_errors()
            if preflight_errors:
                await self._fail_writer_without_report(
                    record,
                    "writer evidence pack preflight failed: "
                    + ", ".join(preflight_errors),
                    writer_repair_mode=writer_repair_mode,
                    writer_repair_sections=writer_repair_sections,
                    writer_repair_decision=writer_repair_decision,
                    anti_regression_reason=anti_regression_reason,
                    previous_report_protected=previous_report_protected,
                )
            try:
                structured_enabled = self._settings.writer_structured_report_enabled
                schema_contract_report_generated = False
                segmented_writer_required = bool(
                    getattr(
                        evidence_pack_result.metrics,
                        "segmented_writer_required",
                        False,
                    )
                )
                if structured_enabled:
                    try:
                        report_md = await self._writer_schema_contract_segment_report(
                            record,
                            evidence_pack_result,
                            timeout_seconds,
                        )
                        publication_validation = validate_publication_contract(
                            report_md,
                            structured_report=None,
                            allowed_source_ids={
                                source.id for source in detail.raw_sources
                            },
                            output_language=detail.output_language,
                        )
                        publication_payload = (
                            publication_validation.telemetry_payload()
                        )
                        await self.emit(
                            detail.id,
                            "writer_publication_contract_validated",
                            "writer",
                            None,
                            "Writer publication contract validated.",
                            publication_payload,
                        )
                        self._trace_local_tool(
                            record,
                            agent="writer",
                            subagent=None,
                            name="writer_publication_contract_validated",
                            input_text="schema_contract_segment_report",
                            output_text=json.dumps(
                                publication_payload,
                                ensure_ascii=False,
                                default=str,
                            ),
                            metadata={
                                "passed": publication_validation.passed,
                                "issue_count": len(publication_validation.issues),
                            },
                        )
                        if not publication_validation.passed:
                            repaired_report_md = await self._repair_schema_contract_publication_issues(
                                record,
                                report_md=report_md,
                                validation=publication_validation,
                                timeout_seconds=timeout_seconds,
                            )
                            if repaired_report_md is not None:
                                report_md = repaired_report_md
                                publication_validation = validate_publication_contract(
                                    report_md,
                                    structured_report=None,
                                    allowed_source_ids={
                                        source.id for source in detail.raw_sources
                                    },
                                    output_language=detail.output_language,
                                )
                                publication_payload = (
                                    publication_validation.telemetry_payload()
                                )
                                await self.emit(
                                    detail.id,
                                    "writer_publication_contract_validated",
                                    "writer",
                                    None,
                                    "Writer publication contract validated after section repair.",
                                    publication_payload,
                                )
                                self._trace_local_tool(
                                    record,
                                    agent="writer",
                                    subagent=None,
                                    name="writer_publication_contract_validated",
                                    input_text="schema_contract_segment_report_repaired",
                                    output_text=json.dumps(
                                        publication_payload,
                                        ensure_ascii=False,
                                        default=str,
                                    ),
                                    metadata={
                                        "passed": publication_validation.passed,
                                        "issue_count": len(publication_validation.issues),
                                    },
                                )
                        if not publication_validation.passed:
                            raise ValueError(
                                "schema-contract segment publication contract failed: "
                                + ", ".join(publication_validation.issue_codes())
                            )
                        schema_contract_report_generated = True
                        writer_mode = "real schema-contract segmented writer call"
                        if pending_redo is not None:
                            scoped_competitors: set[str] = set()
                            scoped_dimensions: set[str] = set()
                            for scope in pending_redo.redo_scopes:
                                if scope.target_competitor:
                                    scoped_competitors.add(scope.target_competitor)
                                scoped_competitors.update(
                                    competitor
                                    for competitor in scope.target_competitors
                                    if competitor
                                )
                                if scope.target_subagent:
                                    scoped_dimensions.add(scope.target_subagent)
                            previous_recommendation = previous_recommendation_posture(
                                previous_structured_report=getattr(
                                    record,
                                    "structured_report_snapshot",
                                    None,
                                ),
                                previous_report=previous_report,
                            )
                            candidate_recommendation = previous_recommendation_posture(
                                previous_structured_report=None,
                                previous_report=report_md,
                            )
                            if previous_recommendation and candidate_recommendation:
                                recommendation_problem = recommendation_delta_problem(
                                    previous_recommendation=previous_recommendation,
                                    candidate_recommendation=candidate_recommendation,
                                    scoped_competitors=scoped_competitors,
                                    scoped_dimensions=scoped_dimensions,
                                    candidate_rationale=report_md,
                                )
                                recommendation_accepted = recommendation_problem is None
                                recommendation_reason = recommendation_problem or (
                                    "recommendation retained or justified by scoped "
                                    "evidence"
                                )
                                recommendation_payload: dict[str, object] = {
                                    "accepted": recommendation_accepted,
                                    "reason": recommendation_reason,
                                    "previous_recommendation": previous_recommendation,
                                    "candidate_recommendation": candidate_recommendation,
                                    "scoped_competitors": sorted(scoped_competitors),
                                    "scoped_dimensions": sorted(scoped_dimensions),
                                }
                                await self.emit(
                                    detail.id,
                                    "writer_recommendation_delta_checked",
                                    "writer",
                                    None,
                                    "Schema-contract segment recommendation delta checked.",
                                    recommendation_payload,
                                )
                                self._trace_local_tool(
                                    record,
                                    agent="writer",
                                    subagent=None,
                                    name="writer_recommendation_delta_checked",
                                    input_text="schema_contract_segment_report",
                                    output_text=json.dumps(
                                        recommendation_payload,
                                        ensure_ascii=False,
                                        default=str,
                                    ),
                                    metadata={
                                        "accepted": recommendation_accepted,
                                        "reason": recommendation_reason,
                                    },
                                )
                                if recommendation_problem:
                                    anti_regression_reason = recommendation_problem
                                    detail.report_md = (
                                        self._preserve_hardened_previous_report(
                                            detail,
                                            previous_report,
                                        )
                                    )
                                    report_md = detail.report_md
                                    writer_mode = (
                                        "preserved previous report after "
                                        "recommendation delta guard"
                                    )
                                    structured_recommendation_guard_preserved = True
                        if structured_targets:
                            await self.emit(
                                detail.id,
                                "writer_structured_repair_selected",
                                "writer",
                                None,
                                "Structured repair targets selected",
                                {
                                    "targets": list(dict.fromkeys(structured_targets)),
                                    "llm_required": any(
                                        target != "renderer"
                                        for target in structured_targets
                                    ),
                                    "authoring_mode": "schema_contract_segment",
                                },
                            )
                    except Exception as exc:  # noqa: BLE001 - structured path may be temporarily unavailable.
                        fallback_reason = str(exc)[:500]
                        if not _structured_markdown_fallback_allowed(
                            detail,
                            structured_enabled,
                        ):
                            writer_error = fallback_reason
                            previous_report_preserved = bool(previous_report.strip())
                            failed_closed_payload = {
                                "reason": fallback_reason,
                                "previous_report_preserved": previous_report_preserved,
                                "writer_repair_mode": writer_repair_mode,
                                "writer_repair_sections": list(writer_repair_sections),
                            }
                            await self.emit(
                                detail.id,
                                "writer_schema_first_failed_closed",
                                "writer",
                                None,
                                "Schema-first writer failed; Markdown fallback disabled for real runs.",
                                failed_closed_payload,
                            )
                            if previous_report_preserved:
                                detail.report_md = self._preserve_hardened_previous_report(
                                    detail,
                                    previous_report,
                                )
                                writer_mode = (
                                    "preserved previous report after schema-first writer error"
                                )
                                report_md = detail.report_md
                            else:
                                try:
                                    await self._fail_writer_without_report(
                                        record,
                                        writer_error,
                                        writer_repair_mode=writer_repair_mode,
                                        writer_repair_sections=writer_repair_sections,
                                        writer_repair_decision=writer_repair_decision,
                                        anti_regression_reason=anti_regression_reason,
                                        previous_report_protected=previous_report_protected,
                                    )
                                except RuntimeError:
                                    return
                        else:
                            fallback_payload = {"reason": fallback_reason}
                            await self.emit(
                                detail.id,
                                "writer_markdown_fallback_used",
                                "writer",
                                None,
                                "Structured writer failed; using Markdown writer fallback.",
                                fallback_payload,
                            )
                            self._trace_local_tool(
                                record,
                                agent="writer",
                                subagent=None,
                                name="writer_markdown_fallback_used",
                                input_text="structured_writer_exception",
                                output_text=fallback_reason,
                                metadata=fallback_payload,
                            )
                            report_md = await self._writer_markdown_report_from_evidence_pack(
                                record,
                                evidence_pack_result,
                                timeout_seconds,
                            )
                            writer_mode = (
                                "real segmented LLM call"
                                if segmented_writer_required
                                else "real LLM call"
                            )
                else:
                    report_md = await self._writer_markdown_report_from_evidence_pack(
                        record,
                        evidence_pack_result,
                        timeout_seconds,
                    )
                    writer_mode = (
                        "real segmented LLM call"
                        if segmented_writer_required
                        else "real LLM call"
                    )
                self._require_writer_report_output(report_md)
                if schema_contract_report_generated:
                    hardened_report = self._harden_schema_contract_report_markdown(
                        detail,
                        report_md,
                    )
                else:
                    hardened_report = self._harden_report_markdown(detail, report_md)
                if (
                    previous_report.strip()
                    and repair_plan is not None
                    and repair_plan.anti_regression_required
                    and not structured_recommendation_guard_preserved
                    and not (
                        structured_scoped_merge_applied
                        and structured_scoped_regression_checked
                    )
                ):
                    repair_comparison_metrics = detail.metrics.model_copy(
                        update={
                            "llm_calls": max(detail.metrics.llm_calls, 1),
                            "source_coverage_rate": max(
                                detail.metrics.source_coverage_rate, 1.0
                            ),
                            "claim_citation_rate": max(
                                detail.metrics.claim_citation_rate, 1.0
                            ),
                        }
                    )
                    previous_detail = detail.model_copy(
                        update={
                            "report_md": previous_report,
                            "qa_findings": [],
                            "metrics": repair_comparison_metrics,
                        }
                    )
                    candidate_detail = detail.model_copy(
                        update={
                            "report_md": hardened_report,
                            "qa_findings": [],
                            "metrics": repair_comparison_metrics,
                        }
                    )
                    protected_sections = repair_plan.sections or [
                        "review_theme_summary",
                        "swot_analysis",
                        "competitor_deep_dives",
                        self._layer_section_label_key(detail),
                    ]
                    anti_regression_reason = report_regression_problem(
                        previous_detail,
                        candidate_detail,
                        protected_sections=protected_sections,
                    )
                if anti_regression_reason and not structured_recommendation_guard_preserved:
                    detail.report_md = self._preserve_hardened_previous_report(
                        detail,
                        previous_report,
                    )
                    writer_mode = "preserved previous report after writer anti-regression"
                else:
                    detail.report_md = hardened_report
                    schema_contract_final_report_md = (
                        hardened_report
                        if (
                            schema_contract_report_generated
                            and not structured_recommendation_guard_preserved
                        )
                        else None
                    )
                    await self._publish_schema_contract_report_artifact_if_current(
                        record,
                        schema_contract_final_report_md=schema_contract_final_report_md,
                    )
            except TimeoutError as exc:
                timeout_reason = str(exc) or f"writer LLM exceeded {timeout_seconds:g}s"
                writer_error = timeout_reason
                if previous_report.strip():
                    detail.report_md = self._preserve_hardened_previous_report(
                        detail,
                        previous_report,
                    )
                    writer_mode = "preserved previous report after writer error"
                else:
                    await self._fail_writer_without_report(
                        record,
                        writer_error,
                        writer_repair_mode=writer_repair_mode,
                        writer_repair_sections=writer_repair_sections,
                        writer_repair_decision=writer_repair_decision,
                        anti_regression_reason=anti_regression_reason,
                        previous_report_protected=previous_report_protected,
                    )
            except Exception as exc:  # noqa: BLE001 - preserve existing reports, fail otherwise.
                writer_error = str(exc)
                if previous_report.strip():
                    detail.report_md = self._preserve_hardened_previous_report(
                        detail,
                        previous_report,
                    )
                    writer_mode = "preserved previous report after writer error"
                else:
                    await self._fail_writer_without_report(
                        record,
                        writer_error,
                        writer_repair_mode=writer_repair_mode,
                        writer_repair_sections=writer_repair_sections,
                        writer_repair_decision=writer_repair_decision,
                        anti_regression_reason=anti_regression_reason,
                        previous_report_protected=previous_report_protected,
                    )
        repair_metadata = {
            "writer_repair_mode": writer_repair_mode,
            "writer_repair_sections": writer_repair_sections,
            "writer_repair_decision": writer_repair_decision,
            "anti_regression_reason": anti_regression_reason,
            "previous_report_protected": previous_report_protected,
        }
        self._append_agent_message(
            record,
            from_agent="writer",
            to_agent="qa",
            message_type="report_ready",
            payload_schema="MarkdownReport",
            payload={
                "report_md": detail.report_md,
                "writer_mode": writer_mode,
                "error": writer_error,
                **repair_metadata,
            },
            source_message_ids=redo_source_message_ids,
        )
        detail.updated_at = datetime.utcnow()
        projection = self._sync_enterprise_projection(record)
        await self.emit(
            detail.id,
            "report_updated",
            "writer",
            None,
            f"Report markdown updated from {writer_mode}.",
            {
                "report_md": detail.report_md,
                "writer_mode": writer_mode,
                "error": writer_error,
                **repair_metadata,
                **self._enterprise_projection_payload(projection),
            },
        )
        await self.emit(detail.id, "node_completed", "writer", None, "Writer completed.")

    async def _fail_writer_without_report(
        self,
        record: RunRecord,
        reason: str,
        *,
        writer_repair_mode: str,
        writer_repair_sections: Sequence[str],
        writer_repair_decision: str,
        anti_regression_reason: str | None,
        previous_report_protected: bool,
    ) -> None:
        detail = record.detail
        detail.status = "failed"
        detail.current_node = None
        detail.updated_at = datetime.utcnow()
        await self.emit(
            detail.id,
            "run_failed",
            "writer",
            None,
            f"Writer failed before report generation: {reason}",
            {
                "error": reason,
                "writer_repair_mode": writer_repair_mode,
                "writer_repair_sections": list(writer_repair_sections),
                "writer_repair_decision": writer_repair_decision,
                "anti_regression_reason": anti_regression_reason,
                "previous_report_protected": previous_report_protected,
            },
        )
        raise RuntimeError(f"Writer failed before report generation: {reason}")

    def _require_writer_report_output(self, report_md: str) -> None:
        if not report_md.strip():
            raise RuntimeError("Writer returned empty report content")

    async def _publish_schema_contract_report_artifact_if_current(
        self,
        record: RunRecord,
        *,
        schema_contract_final_report_md: str | None,
    ) -> bool:
        detail = record.detail
        if (
            not schema_contract_final_report_md
            or detail.report_md != schema_contract_final_report_md
        ):
            self._clear_stale_report_artifact(detail)
            return False
        await self._publish_schema_contract_report_artifact(record)
        return True

    async def _publish_schema_contract_report_artifact(self, record: RunRecord) -> None:
        detail = record.detail
        artifact, validation = self._build_schema_contract_report_artifact(detail)
        validation_payload = validation.telemetry_payload()
        await self.emit(
            detail.id,
            "writer_report_artifact_v2_publication_validated",
            "writer",
            None,
            "Writer ReportArtifactV2 publication contract validated.",
            validation_payload,
        )
        self._trace_local_tool(
            record,
            agent="writer",
            subagent=None,
            name="writer_report_artifact_v2_publication_validated",
            input_text="schema_contract_report_artifact_v2",
            output_text=json.dumps(
                validation_payload,
                ensure_ascii=False,
                default=str,
            ),
            metadata={
                "passed": validation.passed,
                "issue_count": len(validation.issues),
            },
        )
        if not validation.passed:
            raise ValueError(
                "report artifact v2 publication contract failed: "
                + ", ".join(validation.issue_codes())
            )
        detail.report_artifact = artifact
        detail.report_md = artifact.render_cache.full_markdown

    def _build_schema_contract_report_artifact(self, detail: RunDetail):
        artifact = assemble_report_artifact_v2(
            detail,
            {"final_report": detail.report_md},
        )
        validation = validate_report_artifact_publication(
            artifact,
            allowed_source_ids={source.id for source in detail.raw_sources},
        )
        return artifact, validation

    def _set_schema_contract_report_artifact(self, detail: RunDetail) -> None:
        artifact, validation = self._build_schema_contract_report_artifact(detail)
        if not validation.passed:
            raise ValueError(
                "report artifact v2 publication contract failed: "
                + ", ".join(validation.issue_codes())
            )
        detail.report_artifact = artifact
        detail.report_md = artifact.render_cache.full_markdown

    def _clear_stale_report_artifact(self, detail: RunDetail) -> None:
        artifact = detail.report_artifact
        if artifact is None:
            return
        if artifact.legacy.source != "report_artifact_v2":
            return
        if artifact.render_cache.full_markdown != detail.report_md:
            detail.report_artifact = None

    async def _writer_structured_report(
        self,
        record: RunRecord,
        evidence_pack_result,
        timeout_seconds: float,
    ) -> StructuredReport:
        detail = record.detail
        competitors = list(detail.plan.competitors)
        dimensions = list(detail.plan.dimensions)
        allowed_source_ids = {source.id for source in detail.raw_sources}
        section_inputs = _structured_section_inputs(
            evidence_pack_result=evidence_pack_result,
            competitors=competitors,
            dimensions=dimensions,
        )
        sections: dict[str, BaseModel] = {}
        plan = build_structured_writer_section_plan(
            competitors=competitors,
            dimensions=dimensions,
        )
        total_sections = len(plan)
        for index, item in enumerate(plan, start=1):
            key = _structured_section_key(item)
            section_schema = _structured_section_schema(item["schema"])
            section_inputs[key]["section_key"] = key
            if "allowed_source_ids" in section_inputs[key]:
                section_allowed_source_ids = {
                    source_id
                    for source_id in section_inputs[key]["allowed_source_ids"]
                    if isinstance(source_id, str)
                }
            else:
                section_allowed_source_ids = allowed_source_ids
            event_payload: dict[str, object] = {
                "section_key": key,
                "section_id": str(item["section_id"]),
                "section_index": index,
                "section_total": total_sections,
                "section_schema": section_schema.__name__,
                "allowed_source_count": len(section_allowed_source_ids),
            }
            if item.get("competitor") is not None:
                event_payload["competitor"] = str(item["competitor"])
            await self.emit(
                detail.id,
                "writer_structured_section_started",
                "writer",
                key,
                f"Writing structured report section {index}/{total_sections}: {key}",
                event_payload,
            )
            try:
                sections[key] = await self._writer_structured_section_json(
                    record,
                    segment=section_inputs[key],
                    section_schema=section_schema,
                    allowed_source_ids=section_allowed_source_ids,
                    timeout_seconds=timeout_seconds,
                )
            except StructuredSectionGenerationError as exc:
                await self.emit(
                    detail.id,
                    "writer_structured_section_failed",
                    "writer",
                    key,
                    f"Structured report section failed {index}/{total_sections}: {key}",
                    {
                        **event_payload,
                        "schema_name": exc.schema_name,
                        "error": exc.message,
                        "error_kind": exc.error_kind,
                        "attempt": exc.attempt,
                    },
                )
                raise StructuredReportGenerationError((exc,)) from exc
            await self.emit(
                detail.id,
                "writer_structured_section_completed",
                "writer",
                key,
                f"Structured report section completed {index}/{total_sections}: {key}",
                event_payload,
            )

        executive_summary = sections["executive_summary"]
        decision_summary = sections["decision_summary"]
        competitive_findings = sections["competitive_findings"]
        user_review_themes = sections["user_review_themes"]
        deep_dives = [
            sections[f"competitor_deep_dive::{competitor}"]
            for competitor in competitors
        ]
        decision_matrix = sections["decision_matrix"]
        swot = sections["swot"]
        battlecard = sections["battlecard"]
        community_triangulation = sections["community_triangulation"]
        support = sections["support"]

        return StructuredReport(
            output_language=detail.output_language,
            topic=detail.topic,
            competitors=competitors,
            dimensions=dimensions,
            core=ReportCore(
                executive_summary=executive_summary,
                decision_summary=decision_summary.items,
                competitive_findings=competitive_findings.items,
                user_review_themes=user_review_themes,
                competitor_deep_dives=deep_dives,
                decision_matrix=decision_matrix,
                swot=swot,
                battlecard=battlecard,
                community_triangulation=community_triangulation.items,
            ),
            support=support,
            metadata=ReportMetadata(
                writer_mode="structured",
                segment_count=int(
                    getattr(evidence_pack_result.metrics, "segment_count", 0)
                ),
                source_count=len(detail.raw_sources),
                warnings=[],
                structured_report_version="1",
            ),
        )

    async def _writer_markdown_report_from_evidence_pack(
        self,
        record: RunRecord,
        evidence_pack_result,
        timeout_seconds: float,
    ) -> str:
        detail = record.detail
        layer_context = self._writer_layer_context(detail)
        memory_context = "\n".join(detail.plan.memory_prompt_context) or "none"
        required_sections = self._writer_required_sections(detail)
        grounding_prompt = await self._writer_grounding_prompt(detail)
        user_research_policy = writer_user_research_policy_text()
        language_guidance = language_instruction(detail.output_language)
        if evidence_pack_result.metrics.segmented_writer_required:
            return await self._writer_segmented_report_markdown(
                record,
                evidence_pack_result=evidence_pack_result,
                timeout_seconds=timeout_seconds,
                language_guidance=language_guidance,
                memory_context=memory_context,
                layer_context=layer_context,
                required_sections=required_sections,
            )

        writer_context_json = _reader_safe_prompt_json_text(
            evidence_pack_result.to_prompt_json()
        )
        return await asyncio.wait_for(
            self._trace_llm_text(
                record,
                agent="writer",
                subagent=None,
                name="report_writer",
                system=(
                    "You are a senior enterprise competitive-intelligence analyst. "
                    "Produce a concise decision-grade markdown first draft, not a short "
                    "summary. Use an analysis-first structure: lead with an executive "
                    "takeaway, decision summary, competitive findings, competitor deep "
                    "dives, and the selected layer-specific analysis. Put source quality, "
                    "scenario QA, claim risk, RAG gap-fill, verification tasks, and the "
                    "evidence appendix after the core analysis as support material. Write "
                    "with consulting depth: side-by-side matrices, dimension analysis, "
                    "risks, buying implications, and explicit next validation tasks. Cite "
                    "factual claims with existing source IDs using [source:ID]. Do not "
                    "invent source IDs. "
                    "Do not use web_search_result or confidence < 0.75 as the sole support "
                    "for a winner, legal/security certification, pricing, or procurement "
                    "recommendation. If evidence is incomplete, say the conclusion is "
                    "tentative and list the exact evidence gap. Do not claim all sources "
                    "are verified when any source_type is web_search_result or "
                    "llm_public_knowledge. "
                    "Follow the Grounded Evidence Contract exactly. "
                    f"{language_guidance} "
                    f"{user_research_policy} "
                    "Honor confirmed memory guidance when it does not conflict with "
                    "evidence, schema requirements, or compliance policy. "
                    "Use the requested competitive layer to choose the report shape: L1 "
                    "is a direct battlecard, L2 is adjacent workflow and enterprise-risk "
                    "analysis, and L3 is market landscape and category strategy."
                ),
                user=(
                    f"Topic: {detail.topic}\n"
                    f"Competitors: {', '.join(detail.plan.competitors)}\n"
                    f"Dimensions: {', '.join(detail.plan.dimensions)}\n"
                    f"Competitive Layer: {detail.plan.competitor_layer}\n"
                    f"Scenario ID: {detail.plan.scenario_id or 'auto'}\n"
                    "Scenario Recommended Dimensions: "
                    f"{', '.join(detail.plan.scenario_recommended_dimensions)}\n"
                    f"QA Rule IDs: {', '.join(detail.plan.qa_rule_ids)}\n"
                    f"Confirmed Memory Preferences:\n{memory_context}\n"
                    f"Layer Report Context: {layer_context}\n"
                    f"{grounding_prompt}\n"
                    f"{self._writer_community_policy_text()}\n"
                    f"Report Evidence Context JSON: {writer_context_json}\n\n"
                    f"Required sections:\n{required_sections}\n"
                    "Target 16,000-20,000 characters for the first draft. Use about "
                    "70-80% of the report on the Core analysis layer: decision summary, "
                    "competitive findings, user review themes, competitor deep dives, "
                    "SWOT, matrix interpretation, and layer-specific implications. "
                    "Core section minimums: Decision Summary 800+ characters; "
                    "Competitive Findings 1,200+; User Review Themes 1,000+ when "
                    "review, community, survey, interview, or persona evidence exists; "
                    "Competitor Deep Dives 1,400+ and every competitor covered; SWOT "
                    "1,400+ with explicit Strengths, Weaknesses, Opportunities, and "
                    "Threats for every competitor; Matrix Interpretation 900+; "
                    "Layer-specific Battlecard/Workflow/Market section 1,200+. Keep "
                    "the Support/audit layer concise and complete; it is the audit trail, "
                    "not the main readout. Prefer deeper cited analysis and decision "
                    "implications over repeated source IDs or QA boilerplate."
                ),
            ),
            timeout=timeout_seconds,
        )

    async def _writer_schema_contract_segment_report(
        self,
        record: RunRecord,
        evidence_pack_result,
        timeout_seconds: float,
    ) -> str:
        detail = record.detail
        section_briefs = build_section_briefs(detail)
        detail.section_briefs = section_briefs
        brief_segments = segment_payloads_from_briefs(detail, section_briefs)
        return await self._writer_segmented_report_markdown(
            record,
            evidence_pack_result=evidence_pack_result,
            timeout_seconds=timeout_seconds,
            language_guidance=language_instruction(detail.output_language),
            memory_context="\n".join(detail.plan.memory_prompt_context) or "none",
            layer_context=self._writer_layer_context(detail),
            required_sections=self._writer_required_sections(detail),
            segments_override=brief_segments,
            allow_required_section_backfill=False,
        )

    async def _repair_schema_contract_publication_issues(
        self,
        record: RunRecord,
        *,
        report_md: str,
        validation: PublicationContractResult,
        timeout_seconds: float,
    ) -> str | None:
        detail = record.detail
        repairable_issues = [
            issue
            for issue in validation.issues
            if issue.repair_target == "structured_section"
        ]
        if not repairable_issues or len(repairable_issues) != len(validation.issues):
            return None
        target_sections = self._publication_issue_section_keys(
            report_md,
            repairable_issues,
        )
        if not target_sections:
            return None
        await self.emit(
            detail.id,
            "writer_publication_contract_repair_selected",
            "writer",
            None,
            "Writer publication contract issues mapped to section repair.",
            {
                "sections": target_sections,
                "issue_codes": sorted({issue.code for issue in repairable_issues}),
                "issues": [
                    {
                        "code": issue.code,
                        "line_number": issue.line_number,
                        "message": issue.message,
                        "excerpt": issue.excerpt,
                    }
                    for issue in repairable_issues
                ],
            },
        )
        repaired_section_md = await self._writer_section_repair_markdown(
            record,
            sections=target_sections,
            previous_report=report_md,
            publication_issues=repairable_issues,
        )
        section_replacements = self._publication_section_repair_replacements(
            repaired_section_md,
            target_sections=target_sections,
            output_language=detail.output_language,
        )
        missing_sections = [
            section
            for section in target_sections
            if not section_replacements.get(section, "").strip()
        ]
        if missing_sections:
            await self.emit(
                detail.id,
                "writer_publication_contract_repair_incomplete",
                "writer",
                None,
                "Writer publication contract repair did not return every target section.",
                {
                    "sections": target_sections,
                    "missing_sections": missing_sections,
                    "issue_codes": sorted(
                        {issue.code for issue in repairable_issues}
                    ),
                },
            )
            return None
        repaired_report_md = report_md
        for section in target_sections:
            repaired_report_md = replace_markdown_section(
                repaired_report_md,
                section,
                detail.output_language,
                section_replacements[section],
            )
        await self.emit(
            detail.id,
            "writer_publication_contract_repaired",
            "writer",
            None,
            "Writer publication contract issues repaired by section rewrite.",
            {
                "sections": target_sections,
                "issue_codes": sorted({issue.code for issue in repairable_issues}),
                "before_chars": len(report_md),
                "after_chars": len(repaired_report_md),
            },
        )
        return repaired_report_md

    def _publication_section_repair_replacements(
        self,
        repaired_markdown: str,
        *,
        target_sections: Sequence[str],
        output_language: str,
    ) -> dict[str, str]:
        target_set = set(target_sections)
        h2_matches = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", repaired_markdown))
        if not h2_matches:
            if len(target_sections) == 1:
                return {target_sections[0]: repaired_markdown.strip()}
            return {}

        replacements: dict[str, str] = {}
        for index, match in enumerate(h2_matches):
            block_start = self._report_section_start_with_marker(
                repaired_markdown,
                match.start(),
            )
            block_end = (
                self._report_section_start_with_marker(
                    repaired_markdown,
                    h2_matches[index + 1].start(),
                )
                if index + 1 < len(h2_matches)
                else len(repaired_markdown)
            )
            section_key = self._report_section_marker_key_before_heading(
                repaired_markdown,
                match.start(),
            ) or heading_key_for(match.group(1).strip(), output_language)
            if section_key not in target_set or section_key in replacements:
                continue
            replacements[section_key] = repaired_markdown[
                block_start:block_end
            ].strip()

        if replacements:
            return replacements
        if len(target_sections) == 1 and len(h2_matches) == 1:
            return {target_sections[0]: repaired_markdown.strip()}
        return {}

    def _report_section_marker_key_before_heading(
        self,
        markdown: str,
        heading_start: int,
    ) -> str | None:
        previous_line_end = heading_start
        while previous_line_end > 0 and markdown[previous_line_end - 1] in " \t\r\n":
            previous_line_end -= 1
        previous_line_start = markdown.rfind("\n", 0, previous_line_end) + 1
        marker = parse_report_section_marker(
            markdown[previous_line_start:previous_line_end].strip()
        )
        return marker.section_key if marker is not None else None

    def _publication_issue_section_keys(
        self,
        report_md: str,
        issues: Sequence[PublicationContractIssue],
    ) -> list[str]:
        index = build_report_section_index(report_md)
        keys: list[str] = []
        for issue in issues:
            key = _section_key_at_line(index.sections, issue.line_number)
            if key is None:
                return []
            if key not in keys:
                keys.append(key)
        return keys

    async def _writer_structured_section_json(
        self,
        record: RunRecord,
        *,
        segment: dict[str, object],
        section_schema: type[BaseModel],
        allowed_source_ids: set[str],
        timeout_seconds: float,
    ) -> BaseModel:
        prompt = self._structured_section_prompt(
            segment=segment,
            section_schema=section_schema,
            allowed_source_ids=allowed_source_ids,
        )
        try:
            response = await asyncio.wait_for(
                self._trace_llm_text(
                    record,
                    agent="writer",
                    subagent=None,
                    name="structured_report_section",
                    system=(
                        "You are a senior enterprise competitive-intelligence analyst "
                        "writing one structured report section."
                    ),
                    user=prompt,
                ),
                timeout=timeout_seconds,
            )
        except TimeoutError as exc:
            raise _structured_section_generation_error(
                segment,
                section_schema,
                exc,
                error_kind="timeout",
                attempt="initial",
            ) from exc
        except Exception as exc:
            raise _structured_section_generation_error(
                segment,
                section_schema,
                exc,
                error_kind="llm_exception",
                attempt="initial",
            ) from exc
        try:
            return _parse_structured_section_response(
                response,
                section_schema,
                allowed_source_ids,
            )
        except ValueError as exc:
            retry_prompt = self._structured_section_prompt(
                segment=segment,
                section_schema=section_schema,
                allowed_source_ids=allowed_source_ids,
                previous_validation_error=str(exc),
            )
            try:
                retry_response = await asyncio.wait_for(
                    self._trace_llm_text(
                        record,
                        agent="writer",
                        subagent=None,
                        name="structured_report_section_retry",
                        system=(
                            "You are fixing a structured writer JSON response. "
                            "Return valid JSON only."
                        ),
                        user=retry_prompt,
                    ),
                    timeout=timeout_seconds,
                )
            except TimeoutError as retry_exc:
                raise _structured_section_generation_error(
                    segment,
                    section_schema,
                    retry_exc,
                    error_kind="timeout",
                    attempt="retry",
                ) from retry_exc
            except Exception as retry_exc:
                raise _structured_section_generation_error(
                    segment,
                    section_schema,
                    retry_exc,
                    error_kind="llm_exception",
                    attempt="retry",
                ) from retry_exc
            try:
                return _parse_structured_section_response(
                    retry_response,
                    section_schema,
                    allowed_source_ids,
                )
            except ValueError as retry_exc:
                raise _structured_section_generation_error(
                    segment,
                    section_schema,
                    retry_exc,
                    error_kind="validation",
                    attempt="retry",
                ) from retry_exc
            except Exception as retry_exc:
                raise _structured_section_generation_error(
                    segment,
                    section_schema,
                    retry_exc,
                    error_kind="unexpected",
                    attempt="retry",
                ) from retry_exc
        except Exception as exc:
            raise _structured_section_generation_error(
                segment,
                section_schema,
                exc,
                error_kind="unexpected",
                attempt="initial",
            ) from exc

    def _structured_section_prompt(
        self,
        *,
        segment: dict[str, object],
        section_schema: type[BaseModel],
        allowed_source_ids: set[str],
        previous_validation_error: str | None = None,
    ) -> str:
        schema_json = json.dumps(
            section_schema.model_json_schema(),
            ensure_ascii=False,
            sort_keys=True,
        )
        allowed_source_ids_json = json.dumps(
            sorted(allowed_source_ids),
            ensure_ascii=False,
        )
        segment_json = json.dumps(
            segment,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ).replace("[source:", "[source token:")
        previous_error = (previous_validation_error or "none").replace(
            "[source:",
            "[source token:",
        )
        language_guidance = _structured_section_language_instruction(segment)
        instructions = [
            "Return JSON only.",
            "Do not write Markdown headings.",
            language_guidance,
            "Do not include markdown citation tokens inside text fields.",
            "Put citations only in source_ids.",
            "Use only allowed_source_ids.",
            (
                "Choose evidence_role precisely: official/product/vendor facts use "
                "official_fact only when the cited source_registry item has "
                "authority_role=vendor_official; third-party webpage_verified "
                "sources are not official by default. user/community/forum signals "
                "use community_signal; "
                "simulated interviews/surveys use simulated_research; reasoned "
                "conclusions use inference; missing/unsupported evidence uses "
                "evidence_gap."
            ),
            (
                "Evidence gaps are absence-of-evidence statements: set "
                'evidence_role="evidence_gap", confidence="low", and do not '
                "add legacy evidence_gap fields."
            ),
        ]
        instructions.extend(_structured_section_contract_instructions(section_schema))
        instructions.extend(
            [
                f"Schema JSON: {schema_json}",
                f"allowed_source_ids JSON: {allowed_source_ids_json}",
                f"Segment JSON: {segment_json}",
                f"Previous validation error: {previous_error}",
            ]
        )
        return "\n".join(instructions)

    async def _writer_segmented_report_markdown(
        self,
        record: RunRecord,
        *,
        evidence_pack_result,
        timeout_seconds: float,
        language_guidance: str,
        memory_context: str,
        layer_context: str,
        required_sections: str,
        segments_override: Sequence[dict[str, object]] | None = None,
        allow_required_section_backfill: bool = True,
    ) -> str:
        detail = record.detail
        segment_inputs = (
            [dict(segment) for segment in segments_override]
            if segments_override is not None
            else list(evidence_pack_result.segment_inputs())
        )
        if not allow_required_section_backfill:
            segment_inputs = self._schema_contract_segment_inputs(segment_inputs)
        sections = await self._writer_segment_markdown_parts(
            record,
            evidence_pack_result=evidence_pack_result,
            segments=segment_inputs,
            timeout_seconds=timeout_seconds,
            language_guidance=language_guidance,
            memory_context=memory_context,
            layer_context=layer_context,
            required_sections=required_sections,
        )
        assembly_sections = self._writer_assembly_fragments(
            sections,
            output_language=detail.output_language,
        )
        assembled = assemble_report_fragments(
            assembly_sections,
            output_language=detail.output_language,
            competitors=detail.plan.competitors,
        )
        legacy_heading_telemetry = self._writer_legacy_heading_assembly_telemetry(
            sections,
            output_language=detail.output_language,
        )
        assembly_telemetry = {
            **assembled.telemetry,
            **self._writer_segment_fragment_telemetry(sections),
            "legacy_heading_duplicate_section_count_before": (
                legacy_heading_telemetry["duplicate_section_count_before"]
            ),
            "legacy_heading_merged_section_keys": (
                legacy_heading_telemetry["merged_section_keys"]
            ),
        }
        await self.emit(
            detail.id,
            "writer_assembly_completed",
            "writer",
            None,
            "Writer segmented report assembled",
            assembly_telemetry,
        )
        preflight = run_writer_quality_preflight(detail, assembled.markdown)
        await self.emit(
            detail.id,
            "writer_quality_preflight",
            "writer",
            None,
            "Writer assembled report quality preflight completed",
            preflight.telemetry_payload(),
        )
        if preflight.passed:
            return assembled.markdown

        if not allow_required_section_backfill:
            raise RuntimeError(
                "Schema-contract segmented report failed quality preflight: "
                f"{', '.join(preflight.failure_reasons)}"
            )

        hardened = self._harden_report_markdown(detail, assembled.markdown)
        repaired = assemble_report_sections(
            [hardened],
            output_language=detail.output_language,
            competitors=detail.plan.competitors,
        )
        repaired_preflight = run_writer_quality_preflight(detail, repaired.markdown)
        await self.emit(
            detail.id,
            "writer_quality_preflight_repair",
            "writer",
            None,
            "Writer assembled report quality preflight repair completed",
            {
                **repaired_preflight.telemetry_payload(),
                "initial_failure_reasons": list(preflight.failure_reasons),
                "repair_strategy": "harden_required_sections",
            },
        )
        if repaired_preflight.passed:
            return repaired.markdown

        raise RuntimeError(
            "Writer assembled report failed quality preflight: "
            f"{', '.join(repaired_preflight.failure_reasons)}"
        )

    def _schema_contract_segment_inputs(
        self,
        segments: Sequence[dict[str, object]],
    ) -> list[dict[str, object]]:
        schema_segments: list[dict[str, object]] = []
        for segment in segments:
            section_id = str(
                segment.get("section_id")
                or segment.get("section_key")
                or segment.get("segment_name")
                or ""
            )
            if section_id == "decision_summary":
                schema_segments.append(
                    {
                        **segment,
                        "require_executive_summary": True,
                    }
                )
                continue
            schema_segments.append(dict(segment))
        return schema_segments

    async def _writer_segment_markdown_parts(
        self,
        record: RunRecord,
        *,
        evidence_pack_result,
        segments: Sequence[dict[str, object]],
        timeout_seconds: float,
        language_guidance: str,
        memory_context: str,
        layer_context: str,
        required_sections: str,
    ) -> list[ReportSectionFragment]:
        detail = record.detail
        sections: list[ReportSectionFragment] = []
        shards_by_section: dict[tuple[str, str | None], list[str]] = {}
        section_allowed_source_ids: dict[tuple[str, str | None], set[str]] = {}
        segment_results = await self._writer_parallel_validated_segments(
            record,
            evidence_pack_result=evidence_pack_result,
            segments=segments,
            timeout_seconds=timeout_seconds,
            language_guidance=language_guidance,
            memory_context=memory_context,
            layer_context=layer_context,
            required_sections=required_sections,
        )
        for segment, segment_md, contract in segment_results:
            if contract.segment_kind == "evidence_shard":
                section_id = contract.section_id
                segment_competitor = (
                    segment.get("segment_competitor")
                    if isinstance(segment.get("segment_competitor"), str)
                    else None
                )
                shard_key = (
                    section_id,
                    (
                        segment_competitor
                        if section_id == "competitor_deep_dives"
                        else None
                    ),
                )
                shards_by_section.setdefault(shard_key, []).append(segment_md)
                section_allowed_source_ids.setdefault(shard_key, set()).update(
                    source_id
                    for source_id in (segment.get("allowed_source_ids") or [])
                    if isinstance(source_id, str)
                )
                continue
            sections.append(
                self._writer_report_section_fragment(
                    markdown=segment_md,
                    segment=segment,
                    contract=contract,
                )
            )

        section_segments: list[dict[str, object]] = []
        for (section_id, segment_competitor), shard_notes in shards_by_section.items():
            section_segments.append(
                self._writer_section_segment_from_shards(
                    detail,
                    section_id=section_id,
                    segment_competitor=segment_competitor,
                    shard_notes=shard_notes,
                    allowed_source_ids=section_allowed_source_ids[
                        (section_id, segment_competitor)
                    ],
                )
            )
        section_results = await self._writer_parallel_validated_segments(
            record,
            evidence_pack_result=evidence_pack_result,
            segments=section_segments,
            timeout_seconds=timeout_seconds,
            language_guidance=language_guidance,
            memory_context=memory_context,
            layer_context=layer_context,
            required_sections=required_sections,
        )
        for section_segment, section_md, section_contract in section_results:
            sections.append(
                self._writer_report_section_fragment(
                    markdown=section_md,
                    segment=section_segment,
                    contract=section_contract,
                )
            )
        return sections

    async def _writer_parallel_validated_segments(
        self,
        record: RunRecord,
        *,
        evidence_pack_result,
        segments: Sequence[dict[str, object]],
        timeout_seconds: float,
        language_guidance: str,
        memory_context: str,
        layer_context: str,
        required_sections: str,
    ) -> list[tuple[dict[str, object], str, SegmentContract]]:
        if not segments:
            return []

        async def run_segment(
            segment: dict[str, object],
        ) -> tuple[dict[str, object], str, SegmentContract]:
            segment_md, contract = await self._writer_validated_segment_markdown(
                record,
                evidence_pack_result=evidence_pack_result,
                segment=segment,
                timeout_seconds=timeout_seconds,
                language_guidance=language_guidance,
                memory_context=memory_context,
                layer_context=layer_context,
                required_sections=required_sections,
            )
            return segment, segment_md, contract

        tasks = [asyncio.create_task(run_segment(dict(segment))) for segment in segments]
        try:
            return await asyncio.gather(*tasks)
        except Exception:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    def _writer_report_section_fragment(
        self,
        *,
        markdown: str,
        segment: Mapping[str, object],
        contract: SegmentContract,
    ) -> ReportSectionFragment:
        segment_competitor = segment.get("segment_competitor")
        return ReportSectionFragment(
            markdown=markdown,
            section_key=str(segment.get("section_key") or contract.section_id),
            layer=str(
                segment.get("layer")
                or (
                    "support"
                    if contract.segment_kind == "support_fragment"
                    else "core"
                )
            ),
            segment_name=str(segment.get("segment_name") or contract.segment_name),
            competitor=segment_competitor
            if isinstance(segment_competitor, str) and segment_competitor
            else None,
        )

    def _writer_assembly_fragments(
        self,
        fragments: Sequence[ReportSectionFragment],
        *,
        output_language: object,
    ) -> list[ReportSectionFragment]:
        output_language_text = str(output_language)
        assembly_fragments: list[ReportSectionFragment] = []
        for fragment in fragments:
            matches = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", fragment.markdown))
            if not matches:
                assembly_fragments.append(fragment)
                continue

            intro = fragment.markdown[: matches[0].start()].strip()
            if intro:
                assembly_fragments.append(
                    ReportSectionFragment(
                        markdown=intro,
                        section_key="",
                        layer=fragment.layer,
                        segment_name=fragment.segment_name,
                        competitor=fragment.competitor,
                    )
                )

            for index, match in enumerate(matches):
                next_match = matches[index + 1] if index + 1 < len(matches) else None
                block = fragment.markdown[
                    match.start() : next_match.start() if next_match else None
                ].strip()
                heading_key = heading_key_for(match.group(1), output_language_text)
                layer = (
                    "support"
                    if heading_key in SUPPORT_HEADING_KEYS
                    else fragment.layer
                )
                assembly_fragments.append(
                    ReportSectionFragment(
                        markdown=block,
                        section_key=heading_key or "",
                        layer=layer,
                        segment_name=fragment.segment_name,
                        competitor=fragment.competitor,
                    )
                )
        return assembly_fragments

    def _writer_segment_fragment_telemetry(
        self,
        fragments: Sequence[ReportSectionFragment],
    ) -> dict[str, object]:
        layer_counts: dict[str, int] = {}
        for fragment in fragments:
            layer_counts[fragment.layer] = layer_counts.get(fragment.layer, 0) + 1
        return {
            "input_fragment_count": len(fragments),
            "fragment_layer_counts": layer_counts,
            "fragment_section_keys": [fragment.section_key for fragment in fragments],
            "fragment_segment_names": [fragment.segment_name for fragment in fragments],
        }

    def _writer_legacy_heading_assembly_telemetry(
        self,
        fragments: Sequence[ReportSectionFragment],
        *,
        output_language: object,
    ) -> dict[str, object]:
        output_language_text = str(output_language)
        heading_counts: dict[str, int] = {}
        for fragment in fragments:
            for match in re.finditer(r"(?m)^##\s+(.+?)\s*$", fragment.markdown):
                heading_key = heading_key_for(match.group(1), output_language_text)
                if heading_key is not None:
                    heading_counts[heading_key] = heading_counts.get(heading_key, 0) + 1
        canonical_order = CORE_HEADING_KEYS + SUPPORT_HEADING_KEYS
        return {
            "duplicate_section_count_before": sum(
                count - 1 for count in heading_counts.values() if count > 1
            ),
            "merged_section_keys": [
                key for key in canonical_order if heading_counts.get(key, 0) > 1
            ],
        }

    def _writer_section_segment_from_shards(
        self,
        detail: RunDetail,
        *,
        section_id: str,
        segment_competitor: str | None,
        shard_notes: Sequence[str],
        allowed_source_ids: set[str],
    ) -> dict[str, object]:
        segment_name = (
            f"{section_id} {segment_competitor}"
            if section_id == "competitor_deep_dives" and segment_competitor
            else section_id
        )
        section_segment: dict[str, object] = {
            "segment_name": segment_name,
            "segment_kind": "section_fragment",
            "section_id": section_id,
            "section_key": section_id,
            "layer": "support" if section_id == "evidence_support" else "core",
            "segment_competitor": segment_competitor,
            "output_language": detail.output_language,
            "segment_input_chars": 0,
            "allowed_source_ids": sorted(allowed_source_ids),
            "groups": [],
            "sources": [],
            "shard_notes": list(shard_notes),
            "segment_batch": "from_evidence_shards",
        }
        self._refresh_segment_input_chars(section_segment)
        if section_segment["segment_input_chars"] > SEGMENT_INPUT_TARGET_CHARS:
            section_segment["segment_input_target_chars"] = SEGMENT_INPUT_TARGET_CHARS
            section_segment["segment_over_budget_reason"] = (
                "shard_notes_exceed_budget"
            )
            self._refresh_segment_input_chars(section_segment)
        return section_segment

    def _refresh_segment_input_chars(self, segment: dict[str, object]) -> None:
        segment["segment_input_chars"] = 0
        while True:
            segment_input_chars = len(json.dumps(segment, ensure_ascii=False))
            if segment["segment_input_chars"] == segment_input_chars:
                return
            segment["segment_input_chars"] = segment_input_chars

    async def _writer_validated_segment_markdown(
        self,
        record: RunRecord,
        *,
        evidence_pack_result,
        segment: dict[str, object],
        timeout_seconds: float,
        language_guidance: str,
        memory_context: str,
        layer_context: str,
        required_sections: str,
    ):
        detail = record.detail
        contract = segment_contract_for(segment)
        segment_with_contract = {
            **segment,
            "allowed_heading_keys": list(contract.allowed_heading_keys),
            "required_heading_keys": list(contract.required_heading_keys),
            "forbidden_heading_keys": list(contract.forbidden_heading_keys),
            "allowed_h2_headings": [
                report_label(detail.output_language, key)
                for key in contract.allowed_heading_keys
            ],
            "required_h2_headings": [
                report_label(detail.output_language, key)
                for key in contract.required_heading_keys
            ],
            "forbidden_h2_headings": [
                report_label(detail.output_language, key)
                for key in contract.forbidden_heading_keys
            ],
        }
        allowed_source_id_list = [
            source_id
            for source_id in (segment.get("allowed_source_ids") or [])
            if isinstance(source_id, str)
        ]
        groups = segment.get("groups") or []
        payload = {
            "segment_name": segment["segment_name"],
            "segment_kind": contract.segment_kind,
            "section_id": contract.section_id,
            "allowed_heading_keys": list(contract.allowed_heading_keys),
            "required_heading_keys": list(contract.required_heading_keys),
            "forbidden_heading_keys": list(contract.forbidden_heading_keys),
            "segment_essential": contract.essential,
            "segment_competitor": segment.get("segment_competitor"),
            "segment_dimension": segment.get("segment_dimension"),
            "segment_batch": segment.get("segment_batch"),
            "segment_over_budget_reason": segment.get("segment_over_budget_reason"),
            "segment_input_chars": segment.get("segment_input_chars", 0),
            "segment_input_target_chars": segment.get("segment_input_target_chars"),
            "segment_source_count": len(allowed_source_id_list),
            "segment_group_count": len(groups) if isinstance(groups, list) else 0,
            "segment_allowed_source_ids": allowed_source_id_list,
            "segment_retry_count": 0,
        }
        await self.emit(
            detail.id,
            "writer_segment_preflight",
            "writer",
            None,
            f"Writer segment prepared: {segment['segment_name']}",
            payload,
        )
        segment_retry_count = 0
        segment_md = await self._writer_segment_markdown(
            record,
            segment=segment_with_contract,
            timeout_seconds=timeout_seconds,
            language_guidance=language_guidance,
            memory_context=memory_context,
            layer_context=layer_context,
            required_sections=required_sections,
            retry_count=0,
        )
        allowed_source_ids = set(allowed_source_id_list)
        segment_md = self._sanitize_writer_segment_citations(
            evidence_pack_result,
            segment_md,
            allowed_source_ids=allowed_source_ids,
        )
        invalid_sources = evidence_pack_result.validate_segment_citations(
            segment_md,
            allowed_source_ids=allowed_source_ids,
        )
        if invalid_sources:
            segment_md = await self._writer_segment_markdown(
                record,
                segment=segment_with_contract,
                timeout_seconds=timeout_seconds,
                language_guidance=language_guidance,
                memory_context=memory_context,
                layer_context=layer_context,
                required_sections=required_sections,
                retry_count=1,
                citation_error_ids=invalid_sources,
            )
            segment_retry_count = 1
            segment_md = self._sanitize_writer_segment_citations(
                evidence_pack_result,
                segment_md,
                allowed_source_ids=allowed_source_ids,
            )
            invalid_sources = evidence_pack_result.validate_segment_citations(
                segment_md,
                allowed_source_ids=allowed_source_ids,
            )
        if invalid_sources:
            raise RuntimeError(
                "Writer segment cited invalid source IDs after retry: "
                f"{', '.join(invalid_sources)}"
            )
        publication_hygiene_errors = self._writer_segment_publication_hygiene_errors(
            segment_md
        )
        if publication_hygiene_errors:
            retry_count = max(1, segment_retry_count + 1)
            segment_md = await self._writer_segment_markdown(
                record,
                segment=segment_with_contract,
                timeout_seconds=timeout_seconds,
                language_guidance=language_guidance,
                memory_context=memory_context,
                layer_context=layer_context,
                required_sections=required_sections,
                retry_count=retry_count,
                contract_errors=publication_hygiene_errors,
            )
            segment_retry_count = retry_count
            segment_md = self._sanitize_writer_segment_citations(
                evidence_pack_result,
                segment_md,
                allowed_source_ids=allowed_source_ids,
            )
            invalid_sources = evidence_pack_result.validate_segment_citations(
                segment_md,
                allowed_source_ids=allowed_source_ids,
            )
            if invalid_sources:
                raise RuntimeError(
                    "Writer segment cited invalid source IDs after publication "
                    f"hygiene retry: {', '.join(invalid_sources)}"
                )
            publication_hygiene_errors = (
                self._writer_segment_publication_hygiene_errors(segment_md)
            )
            if publication_hygiene_errors:
                raise RuntimeError(
                    "Writer segment violated publication hygiene after retry: "
                    f"{segment['segment_name']}: "
                    f"{'; '.join(publication_hygiene_errors)}"
                )
        truncation_error = self._writer_segment_truncation_error(segment_md)
        if truncation_error:
            retry_count = max(1, segment_retry_count + 1)
            segment_md = await self._writer_segment_markdown(
                record,
                segment=segment_with_contract,
                timeout_seconds=timeout_seconds,
                language_guidance=language_guidance,
                memory_context=memory_context,
                layer_context=layer_context,
                required_sections=required_sections,
                retry_count=retry_count,
                contract_errors=[truncation_error],
            )
            segment_retry_count = retry_count
            segment_md = self._sanitize_writer_segment_citations(
                evidence_pack_result,
                segment_md,
                allowed_source_ids=allowed_source_ids,
            )
            invalid_sources = evidence_pack_result.validate_segment_citations(
                segment_md,
                allowed_source_ids=allowed_source_ids,
            )
            if invalid_sources:
                raise RuntimeError(
                    "Writer segment cited invalid source IDs after truncation retry: "
                    f"{', '.join(invalid_sources)}"
                )
            truncation_error = self._writer_segment_truncation_error(segment_md)
            if truncation_error:
                raise RuntimeError(
                    "Writer segment appears truncated after retry: "
                    f"{segment['segment_name']}: {truncation_error}"
                )
        validation = validate_segment_contract(segment_md, contract)
        await self.emit(
            detail.id,
            "writer_segment_validated",
            "writer",
            None,
            f"Writer segment validated: {segment['segment_name']}",
            {
                "segment_name": segment["segment_name"],
                "segment_kind": contract.segment_kind,
                "section_id": contract.section_id,
                "validation_status": validation.status,
                "validation_errors": list(validation.errors),
                "h2_headings": list(validation.h2_headings),
                "forbidden_headings": list(validation.forbidden_headings),
                "forbidden_heading_keys": list(validation.forbidden_heading_keys),
                "invalid_heading_keys": list(validation.invalid_heading_keys),
                "missing_required_heading_keys": list(
                    validation.missing_required_heading_keys
                ),
                "segment_retry_count": segment_retry_count,
            },
        )
        if validation.status != "pass":
            contract_errors = validation.errors
            contract_forbidden_headings = validation.forbidden_headings
            contract_missing_required_heading_keys = (
                validation.missing_required_heading_keys
            )
            retry_count = max(1, segment_retry_count + 1)
            segment_md = await self._writer_segment_markdown(
                record,
                segment=segment_with_contract,
                timeout_seconds=timeout_seconds,
                language_guidance=language_guidance,
                memory_context=memory_context,
                layer_context=layer_context,
                required_sections=required_sections,
                retry_count=retry_count,
                contract_errors=contract_errors,
                contract_forbidden_headings=contract_forbidden_headings,
                contract_missing_required_heading_keys=(
                    contract_missing_required_heading_keys
                ),
            )
            segment_retry_count = retry_count
            segment_md = self._sanitize_writer_segment_citations(
                evidence_pack_result,
                segment_md,
                allowed_source_ids=allowed_source_ids,
            )
            invalid_sources = evidence_pack_result.validate_segment_citations(
                segment_md,
                allowed_source_ids=allowed_source_ids,
            )
            if invalid_sources:
                retry_count = max(1, segment_retry_count + 1)
                segment_md = await self._writer_segment_markdown(
                    record,
                    segment=segment_with_contract,
                    timeout_seconds=timeout_seconds,
                    language_guidance=language_guidance,
                    memory_context=memory_context,
                    layer_context=layer_context,
                    required_sections=required_sections,
                    retry_count=retry_count,
                    citation_error_ids=invalid_sources,
                    contract_errors=contract_errors,
                    contract_forbidden_headings=contract_forbidden_headings,
                    contract_missing_required_heading_keys=(
                        contract_missing_required_heading_keys
                    ),
                )
                segment_retry_count = retry_count
                segment_md = self._sanitize_writer_segment_citations(
                    evidence_pack_result,
                    segment_md,
                    allowed_source_ids=allowed_source_ids,
                )
                invalid_sources = evidence_pack_result.validate_segment_citations(
                    segment_md,
                    allowed_source_ids=allowed_source_ids,
                )
            if invalid_sources:
                raise RuntimeError(
                    "Writer segment cited invalid source IDs after contract retry: "
                    f"{', '.join(invalid_sources)}"
                )
            validation = validate_segment_contract(segment_md, contract)
            truncation_error = self._writer_segment_truncation_error(segment_md)
            if truncation_error:
                retry_count = max(1, segment_retry_count + 1)
                segment_md = await self._writer_segment_markdown(
                    record,
                    segment=segment_with_contract,
                    timeout_seconds=timeout_seconds,
                    language_guidance=language_guidance,
                    memory_context=memory_context,
                    layer_context=layer_context,
                    required_sections=required_sections,
                    retry_count=retry_count,
                    contract_errors=[*contract_errors, truncation_error],
                    contract_forbidden_headings=contract_forbidden_headings,
                    contract_missing_required_heading_keys=(
                        contract_missing_required_heading_keys
                    ),
                )
                segment_retry_count = retry_count
                segment_md = self._sanitize_writer_segment_citations(
                    evidence_pack_result,
                    segment_md,
                    allowed_source_ids=allowed_source_ids,
                )
                invalid_sources = evidence_pack_result.validate_segment_citations(
                    segment_md,
                    allowed_source_ids=allowed_source_ids,
                )
                if invalid_sources:
                    raise RuntimeError(
                        "Writer segment cited invalid source IDs after "
                        "contract truncation retry: "
                        f"{', '.join(invalid_sources)}"
                    )
                validation = validate_segment_contract(segment_md, contract)
                truncation_error = self._writer_segment_truncation_error(segment_md)
                if truncation_error:
                    raise RuntimeError(
                        "Writer segment appears truncated after contract "
                        f"truncation retry: {segment['segment_name']}: "
                        f"{truncation_error}"
                    )
            if validation.status != "pass":
                raise RuntimeError(
                    "Writer segment violated heading contract after retry: "
                    f"{segment['segment_name']}: {'; '.join(validation.errors)}"
                )
            publication_hygiene_errors = (
                self._writer_segment_publication_hygiene_errors(segment_md)
            )
            if publication_hygiene_errors:
                raise RuntimeError(
                    "Writer segment violated publication hygiene after contract retry: "
                    f"{segment['segment_name']}: "
                    f"{'; '.join(publication_hygiene_errors)}"
                )
            await self.emit(
                detail.id,
                "writer_segment_validated",
                "writer",
                None,
                f"Writer segment validated: {segment['segment_name']}",
                {
                    "segment_name": segment["segment_name"],
                    "segment_kind": contract.segment_kind,
                    "section_id": contract.section_id,
                    "validation_status": validation.status,
                    "validation_errors": list(validation.errors),
                    "h2_headings": list(validation.h2_headings),
                    "forbidden_headings": list(validation.forbidden_headings),
                    "forbidden_heading_keys": list(validation.forbidden_heading_keys),
                    "invalid_heading_keys": list(validation.invalid_heading_keys),
                    "missing_required_heading_keys": list(
                        validation.missing_required_heading_keys
                    ),
                    "segment_retry_count": segment_retry_count,
                },
            )
        return segment_md.strip(), contract

    def _writer_segment_publication_hygiene_errors(self, markdown: str) -> list[str]:
        malformed_count = 0
        internal_term_found = False
        for line in (markdown or "").splitlines():
            malformed_count += len(find_malformed_source_token_attempts(line))
            internal_term_found = internal_term_found or contains_internal_writer_term(
                line
            )
        errors: list[str] = []
        if malformed_count:
            errors.append(
                "segment contains malformed Markdown source citation syntax; "
                "use exact [source:ID] citations"
            )
        if internal_term_found:
            errors.append(
                "segment contains internal writer or evidence-pack terminology; "
                "remove internal writer process labels"
            )
        return errors

    def _writer_segment_truncation_error(self, markdown: str) -> str | None:
        stripped = markdown.strip()
        if not stripped:
            return None
        last_line = next(
            (line.strip() for line in reversed(stripped.splitlines()) if line.strip()),
            "",
        )
        if not last_line:
            return None
        if re.search(r"\[source:[^\]]*$", last_line):
            return "segment output ended with an incomplete source citation"
        if last_line.startswith(("#", "```")):
            return None
        if self._writer_segment_tail_is_complete(last_line):
            return None
        if re.match(r"^(?:[-*+]\s+|\d+[.)]\s+|\|)", last_line):
            return "segment output ended with an incomplete list or table row"
        if last_line.endswith((",", ":", ";")):
            return "segment output ended with a dangling clause"
        return None

    def _writer_segment_tail_is_complete(self, line: str) -> bool:
        line_without_citations = re.sub(r"\s*\[source:[^\]]+\]", "", line).rstrip()
        if not line_without_citations:
            return False
        if re.search(r"[.!?。！？…?)）\]}`|】》”’\"]$", line_without_citations):
            return True
        if re.search(r"\[source:[^\]]+\]", line):
            return not self._writer_segment_tail_has_dangling_fragment(
                line_without_citations
            )
        return False

    def _writer_segment_tail_has_dangling_fragment(self, line: str) -> bool:
        text = re.sub(r"^[-*+]\s+", "", line.strip())
        if not text:
            return True
        return bool(
            re.search(
                r"(?:虽然|因为|由于|如果|若|当|在|对|与|和|及|或|但|而|并|将|为|是|的|"
                r"功能面|技术面|安全面|定价面|市场面|用户面)$",
                text,
            )
        )

    def _sanitize_writer_segment_citations(
        self,
        evidence_pack_result,
        markdown: str,
        *,
        allowed_source_ids: set[str],
    ) -> str:
        sanitizer = getattr(evidence_pack_result, "sanitize_segment_citations", None)
        if callable(sanitizer):
            return sanitizer(markdown, allowed_source_ids=allowed_source_ids)
        return markdown

    def _writer_segment_required_outline(
        self,
        detail: RunDetail,
        segment: dict[str, object],
    ) -> str:
        contract = segment_contract_for(segment)
        section_id = contract.section_id
        competitor = str(segment.get("segment_competitor") or "").strip()
        source_warning = (
            "Do not copy placeholder source IDs from examples. Use only IDs from "
            "the citation source list in the segment context."
        )

        def h2(key: str) -> str:
            return f"## {report_label(detail.output_language, key)}"

        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        outline_labels = {
            "competitor_placeholder": ("<竞品>", "<competitor>"),
            "competitor_1": ("<竞品 1>", "<competitor 1>"),
            "competitor_2": ("<竞品 2>", "<competitor 2>"),
            "dimension": ("维度", "Dimension"),
            "pricing_packaging": ("定价与包装", "Pricing and Packaging"),
            "feature_workflow": ("功能与工作流能力", "Feature and Workflow Capability"),
            "user_persona_adoption": ("用户画像与采用", "User Persona and Adoption"),
            "cross_risks": ("跨竞品风险与影响", "Cross-Competitor Risks and Implications"),
            "direct_user_community": ("直接用户/社区信号", "Direct User / Community Signals"),
            "simulated_survey": ("模拟问卷与访谈信号", "Simulated Survey and Interview Signals"),
            "adoption_blockers": ("采用阻碍", "Adoption Blockers"),
            "switching_triggers": ("切换触发", "Switching Triggers"),
            "evidence_gaps": ("证据缺口", "Evidence Gaps"),
            "official_vs_community": ("官方事实与社区观察", "Official Facts vs Community Observations"),
            "repeated_signals": ("重复出现的信号", "Repeated Signals"),
            "contested_signals": ("有争议或低置信信号", "Contested or Low-Confidence Signals"),
            "positioning_core_value": ("定位与核心价值", "Positioning and Core Value"),
            "feature_capabilities": ("功能能力", "Feature Capabilities"),
            "community_feedback": (
                "社区反馈、采用阻碍与切换触发",
                "Community Feedback, Adoption Blockers, and Switching Triggers",
            ),
            "competitive_plays": ("竞争打法与证据缺口", "Competitive Plays and Evidence Gaps"),
            "strengths": ("优势", "Strengths"),
            "weaknesses": ("劣势", "Weaknesses"),
            "opportunities": ("机会", "Opportunities"),
            "threats": ("威胁", "Threats"),
            "attack_point": ("攻击点", "Attack Point"),
            "defense_rebuttal": ("防守/反驳", "Defense / Rebuttal"),
            "best_fit_buyer": ("最适合买方场景", "Best-Fit Buyer Scenario"),
            "proof_needed": ("使用前所需证据", "Proof Needed Before Use"),
            "workflow_overlap": ("工作流重叠", "Workflow Overlap"),
            "enterprise_buying_risk": ("企业采购风险", "Enterprise Buying Risk"),
            "switching_cost_controls": ("切换成本与控制点", "Switching Cost and Controls"),
            "category_segments": ("品类分段", "Category Segments"),
            "strategic_clusters": ("战略集群", "Strategic Clusters"),
            "trend_uncertainty": ("趋势信号与不确定性", "Trend Signals and Uncertainty"),
            "decision_implications": ("决策影响", "Decision Implications"),
            "operating_risks": ("运营风险", "Operating Risks"),
            "next_validation": ("下一步验证任务", "Next Validation Tasks"),
        }

        def outline_label(key: str) -> str:
            zh, en = outline_labels[key]
            return zh if is_zh else en

        def h3(key: str) -> str:
            return f"### {outline_label(key)}"

        def h4(key: str) -> str:
            return f"#### {outline_label(key)}"

        competitor_placeholder = outline_label("competitor_placeholder")
        deep_dive_competitor = competitor or competitor_placeholder

        if contract.segment_kind == "evidence_shard":
            return "\n".join(
                [
                    "Required segment outline:",
                    "Evidence shard only.",
                    "Do not write any ## H2 heading.",
                    "Return compact cited evidence notes as bullets.",
                    (
                        "Preserve exact source IDs for facts that should be cited by "
                        "the section writer."
                    ),
                    source_warning,
                ]
            )
        if section_id == "decision_summary":
            return "\n".join(
                [
                    "Required segment outline:",
                    h2("executive_summary"),
                    "- 3-5 cited bullets: final recommendation, competitor posture, confidence/risk boundary, immediate next action.",
                    h2("decision_summary"),
                    "- Recommended decision / buying posture.",
                    "- Confidence level and what must not be overstated.",
                    h2("competitive_findings"),
                    h3("pricing_packaging"),
                    h3("feature_workflow"),
                    h3("user_persona_adoption"),
                    h3("cross_risks"),
                    (
                        "Must include: at least three cited bullets and one "
                        "cross-competitor comparison."
                    ),
                    source_warning,
                ]
            )
        if section_id == "review_theme_summary":
            return "\n".join(
                [
                    "Required segment outline:",
                    h2("review_theme_summary"),
                    f"### {competitor_placeholder}",
                    h4("direct_user_community"),
                    h4("simulated_survey"),
                    h4("adoption_blockers"),
                    h4("switching_triggers"),
                    h4("evidence_gaps"),
                    h2("community_evidence_triangulation"),
                    h3("official_vs_community"),
                    h3("repeated_signals"),
                    h3("contested_signals"),
                    (
                        "Must include: separate direct user/community signals from "
                        "simulated survey/interview signals."
                    ),
                    source_warning,
                ]
            )
        if section_id == "competitor_deep_dives":
            return "\n".join(
                [
                    "Required segment outline:",
                    h2("competitor_deep_dives"),
                    f"### {deep_dive_competitor}",
                    h4("positioning_core_value"),
                    h4("pricing_packaging"),
                    h4("feature_capabilities"),
                    h4("user_persona_adoption"),
                    h4("community_feedback"),
                    h4("competitive_plays"),
                    (
                        "Must include: exactly one competitor ownership H3 matching "
                        "segment_competitor."
                    ),
                    source_warning,
                ]
            )
        if section_id == "side_by_side_matrix":
            return "\n".join(
                [
                    "Required segment outline:",
                    h2("side_by_side_matrix"),
                    (
                        f"| {outline_label('dimension')} | "
                        f"{outline_label('competitor_1')} | "
                        f"{outline_label('competitor_2')} |"
                    ),
                    "|---|---|---|",
                    (
                        "Must include: one cited row per decision dimension and a short "
                        "matrix interpretation after the table."
                    ),
                    source_warning,
                ]
            )
        if section_id == "swot_analysis":
            return "\n".join(
                [
                    "Required segment outline:",
                    h2("swot_analysis"),
                    f"### {competitor_placeholder}",
                    h4("strengths"),
                    h4("weaknesses"),
                    h4("opportunities"),
                    h4("threats"),
                    (
                        "Must include: all four SWOT quadrants for every competitor. "
                        "Use evidence-gap notes instead of unsupported claims."
                    ),
                    source_warning,
                ]
            )
        if section_id == "battlecard":
            return "\n".join(
                [
                    "Required segment outline:",
                    h2("battlecard"),
                    f"### {competitor_placeholder}",
                    h4("attack_point"),
                    h4("defense_rebuttal"),
                    h4("best_fit_buyer"),
                    h4("proof_needed"),
                    (
                        "Must include: competitor-specific attack point, defense or "
                        "objection handling, use-when scenario, and evidence risk."
                    ),
                    source_warning,
                ]
            )
        if section_id == "workflow_enterprise_risk":
            return "\n".join(
                [
                    "Required segment outline:",
                    h2("workflow_enterprise_risk"),
                    h3("workflow_overlap"),
                    h3("enterprise_buying_risk"),
                    h3("switching_cost_controls"),
                    (
                        "Must include: workflow overlap, ecosystem leverage, enterprise "
                        "controls, and risks that change the recommendation."
                    ),
                    source_warning,
                ]
            )
        if section_id == "market_landscape":
            return "\n".join(
                [
                    "Required segment outline:",
                    h2("market_landscape"),
                    h3("category_segments"),
                    h3("strategic_clusters"),
                    h3("trend_uncertainty"),
                    (
                        "Must include: market segmentation, strategic options, and "
                        "uncertainty boundaries."
                    ),
                    source_warning,
                ]
            )
        if section_id == "business_implications":
            return "\n".join(
                [
                    "Required segment outline:",
                    h2("business_implications"),
                    h3("decision_implications"),
                    h3("operating_risks"),
                    h3("next_validation"),
                    (
                        "Must include: what the evidence changes for product, GTM, "
                        "procurement, or follow-up analysis."
                    ),
                    source_warning,
                ]
            )
        if section_id == "swot_matrix":
            return "\n".join(
                [
                    "Required segment outline:",
                    h2("side_by_side_matrix"),
                    (
                        f"| {outline_label('dimension')} | "
                        f"{outline_label('competitor_1')} | "
                        f"{outline_label('competitor_2')} |"
                    ),
                    "|---|---|---|",
                    h2("swot_analysis"),
                    f"### {competitor_placeholder}",
                    h4("strengths"),
                    h4("weaknesses"),
                    h4("opportunities"),
                    h4("threats"),
                    (
                        "Must include: matrix interpretation and all four SWOT quadrants "
                        "for every competitor."
                    ),
                    source_warning,
                ]
            )
        if section_id == "evidence_support":
            return "\n".join(
                [
                    "Required segment outline:",
                    (
                        "Support headings are allowed and optional; include only "
                        "applicable support sections."
                    ),
                    h2("evidence_support"),
                    h2("source_quality"),
                    h2("user_research_evidence"),
                    h2("rag_gap_fill"),
                    h2("scenario_checklist"),
                    h2("confidence_notes"),
                    h2("claim_risk"),
                    h2("next_collection"),
                    h2("evidence_appendix"),
                    (
                        "Must include: concise source-quality, coverage, confidence, "
                        "and gap support without restarting core analysis."
                    ),
                    (
                        "Do not write an exact total source count unless it is copied "
                        "from deterministic source telemetry in the segment context."
                    ),
                    source_warning,
                ]
            )
        return "\n".join(
            [
                "Required segment outline:",
                "Write only headings allowed by this segment contract.",
                *[
                    h2(key)
                    for key in (
                        contract.required_heading_keys or contract.allowed_heading_keys
                    )
                ],
                source_warning,
            ]
        )

    async def _writer_segment_markdown(
        self,
        record: RunRecord,
        *,
        segment: dict[str, object],
        timeout_seconds: float,
        language_guidance: str,
        memory_context: str,
        layer_context: str,
        required_sections: str,
        retry_count: int,
        citation_error_ids: list[str] | None = None,
        contract_errors: list[str] | None = None,
        contract_forbidden_headings: list[str] | None = None,
        contract_missing_required_heading_keys: list[str] | None = None,
    ) -> str:
        detail = record.detail
        segment_json = json.dumps(
            _prompt_safe_writer_segment(segment),
            ensure_ascii=False,
        )
        allowed_h2_headings = ", ".join(
            heading
            for heading in segment.get("allowed_h2_headings", [])
            if isinstance(heading, str)
        )
        required_h2_headings = ", ".join(
            heading
            for heading in segment.get("required_h2_headings", [])
            if isinstance(heading, str)
        )
        forbidden_h2_headings = ", ".join(
            heading
            for heading in segment.get("forbidden_h2_headings", [])
            if isinstance(heading, str)
        )
        heading_language_instruction = ""
        if normalize_output_language(detail.output_language) == "zh-CN":
            heading_language_instruction = (
                "For zh-CN output, write structural H3/H4 headings and table "
                "headers in Chinese. Keep product names, API names, model names, "
                "and source IDs in their original language.\n"
            )
        segment_outline = self._writer_segment_required_outline(detail, segment)
        citation_warning = ""
        if citation_error_ids:
            safe_error_ids = _prompt_safe_citation_error_ids(citation_error_ids)
            citation_error_summary = (
                "Previous segment cited source IDs outside this segment: "
                f"{', '.join(safe_error_ids)}."
                if safe_error_ids
                else (
                    "Previous segment cited non-source internal IDs that cannot be "
                    "used as citations."
                )
            )
            citation_warning = (
                f"{citation_error_summary} Rewrite using only this segment's "
                "citation source IDs. "
                "Use exact [source:ID] syntax with no space after source:. Do not put "
                "multiple source IDs inside one [source:...] token; cite multiple "
                "sources as consecutive citations such as [source:A][source:B].\n"
            )
        contract_warning = ""
        if contract_errors:
            forbidden = ", ".join(contract_forbidden_headings or [])
            missing = ", ".join(contract_missing_required_heading_keys or [])
            contract_warning = (
                "Previous segment violated its heading contract or publication contract: "
                f"{'; '.join(contract_errors)}. "
                f"Missing required H2 heading keys: {missing or 'none'}. "
                f"Forbidden H2 headings found: {forbidden or 'none'}. "
                "Rewrite only this segment and obey the segment contract exactly.\n"
            )
        user_research_gap_instruction = ""
        section_id = str(
            segment.get("section_id")
            or segment.get("section_key")
            or segment.get("segment_name")
            or ""
        )
        section_brief = segment.get("section_brief")
        repair_targets = segment.get("repair_targets")
        if not isinstance(repair_targets, Mapping) and isinstance(
            section_brief, Mapping
        ):
            repair_targets = section_brief.get("repair_targets")
        scoped_empty = (
            isinstance(repair_targets, Mapping)
            and repair_targets.get("scoped_card_status") == "empty"
        )
        if (
            (section_id == "review_theme_summary" or scoped_empty)
            and not segment.get("groups")
            and not segment.get("allowed_source_ids")
        ):
            user_research_gap_instruction = (
                "This review-theme segment has no groups or allowed sources; write "
                "the section as an evidence gap/absence note and do not invent user "
                "research findings.\n"
            )
        publication_repair_instruction = self._writer_publication_repair_instruction(
            _publication_issues_from_segment(segment)
        )
        shard_instruction = ""
        if segment.get("segment_kind") == "evidence_shard":
            shard_instruction += (
                "This is an evidence shard. Return compact structured notes as bullets. "
                "Do not write any ## H2 heading. Do not write a final report section. "
                "Preserve exact source IDs for facts that should be cited by the section writer.\n"
            )
        if segment.get("shard_notes"):
            shard_instruction += (
                "This section writer receives evidence shard notes in segment.shard_notes. "
                "Write exactly one canonical report section or allowed section group from those notes.\n"
            )
        user_research_policy = writer_user_research_policy_text()
        return await asyncio.wait_for(
            self._trace_llm_text(
                record,
                agent="writer",
                subagent=None,
                name="report_writer_segment",
                system=(
                    "You are a senior enterprise competitive-intelligence analyst writing "
                    "one section group of a larger markdown report. Return only markdown "
                    "for this segment. Cite factual claims only with source IDs in "
                    "the segment's citation source list. Do not invent source IDs. "
                    "Use exact [source:ID] syntax with no space after source:. Do not "
                    "combine multiple source IDs inside one [source:...] token; write "
                    "consecutive citations like [source:A][source:B]. "
                    "Do not use web_search_result or confidence < 0.75 as the sole support "
                    "for a winner, legal/security certification, pricing, or procurement "
                    "recommendation. If evidence is incomplete, say the conclusion is "
                    "tentative and list the exact evidence gap. Do not claim all sources "
                    "are verified when any source_type is web_search_result or "
                    "llm_public_knowledge. "
                    f"{user_research_policy} "
                    f"{language_guidance}"
                ),
                user=(
                    f"Topic: {detail.topic}\n"
                    f"Competitors: {', '.join(detail.plan.competitors)}\n"
                    f"Dimensions: {', '.join(detail.plan.dimensions)}\n"
                    f"segment_name={segment['segment_name']}\n"
                    f"segment_kind={segment.get('segment_kind', 'section_fragment')}\n"
                    f"section_id={segment.get('section_id', segment['segment_name'])}\n"
                    f"segment_competitor={segment.get('segment_competitor') or 'all'}\n"
                    f"retry_count={retry_count}\n"
                    "Allowed H2 headings for this segment: "
                    f"{allowed_h2_headings or 'none'}\n"
                    "Required H2 headings for this segment: "
                    f"{required_h2_headings or 'none'}\n"
                    "Forbidden H2 headings for this segment: "
                    f"{forbidden_h2_headings or 'none'}\n"
                    f"{heading_language_instruction}"
                    f"{segment_outline}\n"
                    f"{citation_warning}"
                    f"{contract_warning}"
                    f"{user_research_gap_instruction}"
                    f"{publication_repair_instruction}"
                    f"{shard_instruction}"
                    "Do not write headings outside this segment's contract. "
                    "Do not write support or appendix sections unless "
                    "segment_kind=support_fragment. If segment_kind=evidence_shard, "
                    "do not write any ## H2 headings.\n"
                    f"Confirmed Memory Preferences:\n{memory_context}\n"
                    f"Layer Report Context: {layer_context}\n"
                    f"{self._writer_community_policy_text()}\n"
                    f"Segment Context JSON: {segment_json}\n\n"
                    f"Required sections for full report:\n{required_sections}\n"
                    "Write with consulting depth for this segment. Keep support material "
                    "concise and preserve [source:ID] citation syntax."
                ),
            ),
            timeout=timeout_seconds,
        )

    async def _writer_section_repair_markdown(
        self,
        record: RunRecord,
        *,
        sections: Sequence[str],
        previous_report: str,
        publication_issues: Sequence[PublicationContractIssue] | None = None,
    ) -> str:
        detail = record.detail
        evidence_pack_result = build_writer_evidence_pack(detail)
        preflight_errors = evidence_pack_result.preflight_errors()
        if preflight_errors:
            raise WriterEvidencePreflightError(
                "writer evidence pack preflight failed: "
                + ", ".join(preflight_errors)
            )
        segmented_writer_required = getattr(
            getattr(evidence_pack_result, "metrics", None),
            "segmented_writer_required",
            False,
        )
        if segmented_writer_required:
            if hasattr(evidence_pack_result, "repair_segment_inputs"):
                repair_payloads = evidence_pack_result.repair_segment_inputs(sections)
            else:
                repair_payloads = [evidence_pack_result.repair_segment_input(sections)]
            repair_segments = [
                segment
                for payload in repair_payloads
                for segment in (payload.get("segments") or [])
                if isinstance(segment, dict)
            ]
            repair_has_evidence_shards = any(
                segment.get("segment_kind") == "evidence_shard"
                for segment in repair_segments
            )
            writer_context_jsons = [
                json.dumps(
                    _reader_safe_prompt_field_names(payload),
                    ensure_ascii=False,
                )
                for payload in repair_payloads
            ]
        else:
            repair_payloads = []
            repair_segments = []
            repair_has_evidence_shards = False
            writer_context_jsons = [
                _reader_safe_prompt_json_text(evidence_pack_result.to_prompt_json())
            ]
        telemetry_payload = (
            evidence_pack_result.telemetry_payload()
            if hasattr(evidence_pack_result, "telemetry_payload")
            else {}
        )
        telemetry_payload = dict(telemetry_payload)
        telemetry_payload.update(
            {
                "writer_repair_mode": "section",
                "writer_repair_sections": list(sections),
                "segmented_writer_required": bool(segmented_writer_required),
                "repair_segment_count": (
                    len(repair_payloads) if segmented_writer_required else 1
                ),
            }
        )
        if repair_payloads:
            telemetry_payload["repair_input_chars"] = [
                payload.get("repair_input_chars") for payload in repair_payloads
            ]
            telemetry_payload["repair_part_count"] = len(repair_payloads)
        await self.emit(
            detail.id,
            "writer_preflight",
            "writer",
            None,
            "Writer evidence pack prepared for section repair.",
            telemetry_payload,
        )
        language_guidance = language_instruction(detail.output_language)
        section_headings = "\n".join(
            self._writer_section_heading_instruction(detail, section) for section in sections
        )
        if repair_has_evidence_shards:
            timeout_seconds = max(0.05, float(self._settings.writer_timeout_seconds))
            repair_segments = [
                self._with_publication_repair_issues(
                    segment,
                    publication_issues=publication_issues,
                )
                for segment in repair_segments
            ]
            repaired_fragments = await self._writer_segment_markdown_parts(
                record,
                evidence_pack_result=evidence_pack_result,
                segments=repair_segments,
                timeout_seconds=timeout_seconds,
                language_guidance=language_guidance,
                memory_context="\n".join(detail.plan.memory_prompt_context) or "none",
                layer_context=self._writer_layer_context(detail),
                required_sections=self._writer_required_sections(detail),
            )
            repaired_parts = self._filter_section_repair_parts_to_requested_sections(
                [fragment.markdown for fragment in repaired_fragments],
                sections=sections,
                output_language=detail.output_language,
            )
            return self._join_section_repair_parts(
                repaired_parts,
                section_headings,
            )

        repaired_sections = []
        for writer_context_json in writer_context_jsons:
            repaired_sections.append(
                await self._trace_llm_text(
                    record,
                    agent="writer",
                    subagent=None,
                    name="report_section_repair",
                    system=(
                        "You are a senior enterprise competitive-intelligence analyst repairing "
                        "one section of an existing markdown report. Return only the requested "
                        "section markdown. Preserve existing [source:ID] syntax, never invent "
                        "source IDs, and cite factual claims with available source IDs. "
                        f"{language_guidance}"
                    ),
                    user=(
                        f"Topic: {detail.topic}\n"
                        f"Competitors: {', '.join(detail.plan.competitors)}\n"
                        f"Dimensions: {', '.join(detail.plan.dimensions)}\n"
                        f"Repair only these sections: {', '.join(sections)}\n"
                        f"Expected section headings:\n{section_headings}\n"
                        "return only the requested section markdown; do not rewrite unrelated "
                        "sections or include commentary outside the section.\n"
                        "Use the exact requested level-2 heading for each returned section.\n"
                        "You must preserve existing [source:ID] syntax.\n"
                        f"{self._writer_community_policy_text()}\n"
                        f"{self._writer_publication_repair_instruction(publication_issues)}"
                        f"Report Evidence Context JSON: {writer_context_json}\n\n"
                        f"Previous report:\n{previous_report}"
                    ),
                )
            )
        return self._join_section_repair_parts(repaired_sections, section_headings)

    def _with_publication_repair_issues(
        self,
        segment: dict[str, object],
        *,
        publication_issues: Sequence[PublicationContractIssue] | None,
    ) -> dict[str, object]:
        if not publication_issues:
            return segment
        return {
            **segment,
            "publication_repair_issues": [
                {
                    "code": issue.code,
                    "line_number": issue.line_number,
                    "message": issue.message,
                    "excerpt": issue.excerpt,
                }
                for issue in publication_issues
            ],
        }

    def _writer_community_policy_text(self) -> str:
        return (
            "Official facts vs community observations: official docs may support official "
            "commitments; community_triangulated, community_observed, and "
            "community_contested clusters may support actual-use risks, user evaluation, "
            "and pricing caveats. Do not present community observations as official "
            "commitments unless an official source also supports the same claim."
        )

    def _writer_publication_repair_instruction(
        self,
        issues: Sequence[PublicationContractIssue] | None,
    ) -> str:
        base = (
            "Do not mention internal JSON or implementation field names in the report "
            "body. Refer to implementation objects as sources, evidence, "
            "or the source list in reader-facing language.\n"
        )
        if not issues:
            return base
        issue_lines = []
        for issue in issues:
            excerpt = issue.excerpt or issue.message
            issue_lines.append(
                f"- line {issue.line_number}: {issue.code}; remove or rewrite "
                f"this excerpt: {excerpt}"
            )
        return (
            base
            + "Previous assembled report failed publication contract for this "
            + "section. Repair only the listed issue(s):\n"
            + "\n".join(issue_lines)
            + "\n"
        )

    def _writer_section_heading_instruction(self, detail: RunDetail, section: str) -> str:
        try:
            heading = report_label(detail.output_language, section)
        except KeyError:
            heading = section
        return f"{section} -> ## {heading}"

    def _filter_section_repair_parts_to_requested_sections(
        self,
        parts: Sequence[str],
        *,
        sections: Sequence[str],
        output_language: object,
    ) -> list[str]:
        output_language_text = str(output_language)
        requested_keys = self._requested_section_keys(sections, output_language_text)
        if not requested_keys:
            return list(parts)

        filtered_parts: list[str] = []
        for part in parts:
            filtered_part = self._filter_section_repair_part_to_requested_sections(
                part,
                requested_keys=requested_keys,
                output_language=output_language_text,
            )
            if filtered_part is None:
                filtered_parts.append(part)
            elif filtered_part:
                filtered_parts.append(filtered_part)
        return filtered_parts

    def _requested_section_keys(
        self,
        sections: Sequence[str],
        output_language: str,
    ) -> set[str]:
        requested_keys: set[str] = set()
        for section in sections:
            section_text = str(section).strip()
            if not section_text:
                continue
            requested_keys.add(section_text)
            if (
                section_text not in CORE_HEADING_KEYS
                and section_text not in SUPPORT_HEADING_KEYS
            ):
                requested_keys.update(SECTION_ALLOWED_KEYS.get(section_text, ()))
            section_heading_key = heading_key_for(section_text, output_language)
            if section_heading_key is not None:
                requested_keys.add(section_heading_key)
            try:
                label_key = heading_key_for(
                    report_label(output_language, section_text),
                    output_language,
                )
            except KeyError:
                label_key = None
            if label_key is not None:
                requested_keys.add(label_key)
        return requested_keys

    def _filter_section_repair_part_to_requested_sections(
        self,
        part: str,
        *,
        requested_keys: set[str],
        output_language: str,
    ) -> str | None:
        matches = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", part))
        if not matches:
            return None

        blocks: list[str] = []
        for index, match in enumerate(matches):
            heading_key = heading_key_for(match.group(1), output_language)
            if heading_key not in requested_keys:
                continue
            next_match = matches[index + 1] if index + 1 < len(matches) else None
            block = part[
                match.start() : next_match.start() if next_match else None
            ].strip()
            if block:
                blocks.append(block)
        return "\n\n".join(blocks).strip()

    def _join_section_repair_parts(
        self,
        parts: Sequence[str],
        section_headings: str,
    ) -> str:
        requested_headings = {
            line.split("->", 1)[1].strip()
            for line in section_headings.splitlines()
            if "->" in line
        }
        seen_headings: set[str] = set()
        cleaned_parts: list[str] = []
        for part in parts:
            cleaned_lines: list[str] = []
            for line in part.strip().splitlines():
                heading = line.strip()
                is_top_level_heading = heading.startswith("## ") and not heading.startswith(
                    "### "
                )
                if heading in requested_headings or is_top_level_heading:
                    if heading in seen_headings:
                        continue
                    seen_headings.add(heading)
                cleaned_lines.append(line)
            cleaned_part = "\n".join(cleaned_lines).strip()
            if cleaned_part:
                cleaned_parts.append(cleaned_part)
        return "\n\n".join(cleaned_parts)

    def _preserve_hardened_previous_report(
        self,
        detail: RunDetail,
        previous_report: str,
    ) -> str:
        if self._has_report_section_markers(previous_report):
            preserved_report = self._harden_schema_contract_report_markdown(
                detail,
                previous_report,
            )
        else:
            preserved_report = self._harden_report_markdown(detail, previous_report)
        if detail.report_md != preserved_report:
            detail.report_md = preserved_report
        if self._has_report_section_markers(preserved_report):
            self._set_schema_contract_report_artifact(detail)
            return detail.report_md
        else:
            self._clear_stale_report_artifact(detail)
        return preserved_report

    def _has_report_section_markers(self, markdown: str) -> bool:
        return bool(re.search(r"^<!--\s*report-section:", markdown, flags=re.MULTILINE))

    def _backfill_layer_sections(
        self,
        detail: RunDetail,
        source_ids: list[str],
    ) -> list[str]:
        return self._backfill_layer_sections_lines(detail, source_ids)

    def _backfill_layer_sections_lines(
        self,
        detail: RunDetail,
        source_ids: list[str],
    ) -> list[str]:
        refs = self._format_source_refs(source_ids)
        heading = self._layer_section_heading(detail)
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        layer = detail.plan.competitor_layer
        if layer == "L1":
            if is_zh:
                bullets = [
                    f"- 直接战报定位：把当前赢家作为短期替代或对抗话术的候选主线，但只在引用证据覆盖的范围内使用。{refs}",
                    f"- 反对意见处理：优先围绕定价、包装、功能对齐、采购阻力和切换触发组织回答，不把弱单元格包装成确定结论。{refs}",
                    f"- 行动偏向：使用置信度最高的维度赢家作为初始战报骨架，并在发布前验证单来源、低置信度或社区观察支持的声明。{refs}",
                    f"- 落地检查：每条战报话术都要同时包含可引用证据、目标买家、可能反驳点和下一步验证任务，避免只给一句赢家判断。{refs}",
                ]
            else:
                bullets = [
                    f"- Direct-use position: treat the current winners as candidate near-term replacement or objection-handling lines only within the cited evidence boundary.{refs}",
                    f"- Objection handling: organize responses around pricing, packaging, feature parity, procurement friction, and switching triggers without turning weak cells into settled conclusions.{refs}",
                    f"- Action bias: use the highest-confidence dimension winners as the initial battlecard spine, then verify single-source, low-confidence, or community-observed claims before publication.{refs}",
                    f"- Deployment check: every battlecard line should pair cited evidence, target buyer, likely rebuttal, and next validation task instead of stopping at a one-sentence winner claim.{refs}",
                ]
        elif layer == "L2":
            if is_zh:
                bullets = [
                    f"- 相邻工作流威胁：从工作流重叠、集成杠杆和切换成本阅读矩阵，而不是只比较孤立功能。{refs}",
                    f"- 采购风险：在提出企业建议前，把已证实的组织控制措施与搜索线索、社区观察或低置信度声明分开。{refs}",
                    f"- 监控列表：重点关注相邻竞品能通过一次集成、权限或打包变化吞并目标工作流的维度。{refs}",
                    f"- 行动节奏：把强证据维度写成可执行建议，把弱证据维度转为验证任务，避免把工作流风险过早定性。{refs}",
                ]
            else:
                bullets = [
                    f"- Adjacent-workflow threat: read the matrix through workflow overlap, integration leverage, and switching-cost exposure rather than isolated feature parity.{refs}",
                    f"- Buying risk: separate proven enterprise controls from search leads, community observations, or low-confidence claims before making procurement recommendations.{refs}",
                    f"- Watchlist: monitor dimensions where adjacent competitors could absorb the target workflow through one integration, permission, or packaging change.{refs}",
                    f"- Action cadence: turn strong-evidence dimensions into recommendations and weak-evidence dimensions into validation tasks instead of overstating workflow risk.{refs}",
                ]
        elif layer == "L3":
            if is_zh:
                bullets = [
                    f"- 类别视角：避免只宣布单一直接赢家，应按细分市场、趋势信号和基准强度给竞品分组。{refs}",
                    f"- 战略视角：当证据广度仍不足以支撑景观级覆盖时，把建议写成投资组合选项而不是终局判断。{refs}",
                    f"- 不确定性视角：在做类别范围声明前，优先增加竞品、市场级来源和跨来源验证。{refs}",
                    f"- 决策节奏：用高置信信号确定短期动作，用低覆盖区域定义观察指标和后续研究任务。{refs}",
                ]
            else:
                bullets = [
                    f"- Category view: avoid a single direct winner and group competitors by segment, trend signal, and benchmark strength.{refs}",
                    f"- Strategy view: treat recommendations as portfolio options while evidence breadth remains below landscape-grade coverage.{refs}",
                    f"- Uncertainty view: prioritize adding competitors, market-level sources, and cross-source validation before making category-wide claims.{refs}",
                    f"- Decision cadence: use high-confidence signals for near-term action and low-coverage areas for watch metrics and follow-up research tasks.{refs}",
                ]
        else:
            if is_zh:
                bullets = [
                    f"- 业务含义：当前报告应作为带不确定性边界的证据读数，而不是最终市场结论。{refs}",
                    f"- 决策使用：把高置信矩阵单元转成可行动建议，把弱单元格保留为验证任务。{refs}",
                    f"- 风险控制：当来源为单条、搜索线索或低置信度时，不要夸大采购、合规、功能或价格结论。{refs}",
                    f"- 后续动作：优先补齐影响赢家判断的来源，再扩大到支持层审计材料。{refs}",
                ]
            else:
                bullets = [
                    f"- Business implication: use this as an evidence-indexed readout with explicit uncertainty rather than a final market conclusion.{refs}",
                    f"- Decision use: turn high-confidence matrix cells into action and keep weak cells as validation tasks.{refs}",
                    f"- Risk control: do not overstate procurement, compliance, feature, or pricing claims when support is single-source, search-only, or low-confidence.{refs}",
                    f"- Next action: fill the sources that could change winner judgments before expanding support-layer audit material.{refs}",
                ]
        return ["", f"## {heading}", *bullets]

    def _backfill_executive_summary_section(
        self, detail: RunDetail, source_ids: list[str]
    ) -> list[str]:
        refs = self._format_source_refs(source_ids)
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        competitors = ", ".join(detail.plan.competitors) or detail.topic
        dimensions = ", ".join(detail.plan.dimensions) or (
            "\u8bf7\u6c42\u7ef4\u5ea6" if is_zh else "requested dimensions"
        )
        if detail.comparison_matrix is not None and detail.comparison_matrix.winner_by_dimension:
            winners = ", ".join(
                f"{dimension}: {winner}"
                for dimension, winner in detail.comparison_matrix.winner_by_dimension.items()
                if winner
            )
        else:
            winners = (
                "\u5c1a\u65e0\u8db3\u591f\u7a33\u5b9a\u7684\u7ef4\u5ea6\u8d62\u5bb6"
                if is_zh
                else "no sufficiently stable dimension winner yet"
            )
        if is_zh:
            return [
                "",
                f"## {report_label(detail.output_language, 'executive_takeaway')}",
                (
                    f"- \u6838\u5fc3\u7ed3\u8bba\uff1a\u672c\u62a5\u544a\u5bf9 {competitors} "
                    f"\u5728 {dimensions} \u4e0a\u7684\u7ade\u4e89\u4f4d\u7f6e\u8fdb\u884c\u51b3\u7b56\u5bfc\u5411\u5bf9\u6bd4\uff1b"
                    f"\u5f53\u524d\u7ef4\u5ea6\u4fe1\u53f7\u4e3a {winners}\u3002{refs}"
                ),
                (
                    "- \u51b3\u7b56\u59ff\u6001\uff1a\u4f18\u5148\u91c7\u7528\u6709\u9ad8\u7f6e\u4fe1\u5ea6\u6765\u6e90"
                    "\u548c\u53ef\u8ffd\u6eaf\u5f15\u7528\u652f\u6491\u7684\u7ed3\u8bba\uff0c\u5c06\u5355\u6765\u6e90\u3001"
                    f"\u793e\u533a\u4fe1\u53f7\u6216\u4f4e\u7f6e\u4fe1\u5ea6\u6750\u6599\u7559\u4f5c\u9a8c\u8bc1\u4efb\u52a1\u3002{refs}"
                ),
                (
                    "- \u98ce\u9669\u8fb9\u754c\uff1a\u4e0d\u5e94\u628a\u77e9\u9635\u8d62\u5bb6\u3001\u4ef7\u683c\u4f18\u52bf\u3001"
                    "\u4f01\u4e1a\u91c7\u8d2d\u51c6\u5907\u5ea6\u6216\u5b89\u5168\u5408\u89c4\u63a8\u65ad\u5199\u6210"
                    f"\u8131\u79bb\u8bc1\u636e\u7684\u7edd\u5bf9\u6392\u540d\u3002{refs}"
                ),
                (
                    "- \u7acb\u5373\u884c\u52a8\uff1a\u5148\u5bf9\u5f71\u54cd\u91c7\u8d2d\u5224\u65ad\u7684\u5173\u952e"
                    "\u8bc1\u636e\u7f3a\u53e3\u505a\u8865\u91c7\uff0c\u518d\u5c06\u672c\u62a5\u544a\u8f6c\u5316\u4e3a"
                    f"\u9500\u552e\u6218\u62a5\u6216\u4ea7\u54c1\u5e94\u5bf9\u8def\u7ebf\u3002{refs}"
                ),
            ]
        return [
            "",
            f"## {report_label(detail.output_language, 'executive_takeaway')}",
            (
                f"- Core conclusion: this report compares {competitors} across {dimensions} "
                f"for a decision-grade competitive readout; current dimension signals are {winners}.{refs}"
            ),
            (
                "- Decision posture: prioritize claims backed by high-confidence, traceable "
                "sources and keep single-source, community-only, or lower-confidence material "
                f"as validation work rather than final proof.{refs}"
            ),
            (
                "- Risk boundary: do not turn matrix winners, pricing advantages, enterprise "
                "procurement readiness, or security assumptions into absolute rankings detached "
                f"from the cited evidence.{refs}"
            ),
            (
                "- Immediate next action: fill the evidence gaps that could change the buying "
                "judgment before converting this report into a sales battlecard or product "
                f"response roadmap.{refs}"
            ),
        ]

    def _backfill_decision_summary_section(
        self, detail: RunDetail, source_ids: list[str]
    ) -> list[str]:
        refs = self._format_source_refs(source_ids)
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        dimensions = ", ".join(detail.plan.dimensions) or (
            "所请求的维度" if is_zh else "the requested dimensions"
        )
        competitors = ", ".join(detail.plan.competitors) or detail.topic
        if detail.comparison_matrix is not None and detail.comparison_matrix.winner_by_dimension:
            winners = ", ".join(
                f"{dimension}: {winner}"
                for dimension, winner in detail.comparison_matrix.winner_by_dimension.items()
            )
        else:
            winners = (
                "尚无评分赢家；将来源覆盖率和 QA 状态作为约束条件"
                if is_zh
                else "no scored winner yet; use source coverage and QA status as constraints"
            )
        if is_zh:
            return [
                "",
                f"## {report_label(detail.output_language, 'decision_summary')}",
                (
                    f"- 推荐行动：使用此 {self._writer_layer_label(detail)} 对比 "
                    f"{competitors} 在 {dimensions} 上的表现；决策锚定在 {winners}。{refs}"
                ),
                (
                    "- 决策姿态：优先考虑具有已证实、高置信度证据的维度，"
                    "并将薄弱单元格路由到验证计划中。"
                    f"{refs}"
                ),
                (
                    "- 当证据为单来源或仅限搜索时，不要夸大矩阵赢家、采购准备就绪度、安全姿态"
                    f"或定价结论。{refs}"
                ),
            ]
        return [
            "",
            f"## {report_label(detail.output_language, 'decision_summary')}",
            (
                f"- Recommended action: use this {self._writer_layer_label(detail)} to compare "
                f"{competitors} on {dimensions}; anchor the decision on {winners}.{refs}"
            ),
            (
                "- Decision posture: prioritize dimensions with verified, high-confidence "
                f"evidence and route weak cells into the verification plan.{refs}"
            ),
            (
                "- Do not overstate matrix winners, procurement readiness, security posture, "
                f"or pricing conclusions when evidence is single-source or search-only.{refs}"
            ),
        ]

    def _backfill_competitive_findings_section(self, detail: RunDetail) -> list[str]:
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        lines = [
            "",
            f"## {report_label(detail.output_language, 'competitive_findings')}",
        ]
        return self._backfill_competitive_findings_lines(detail, lines, is_zh)

    def _backfill_competitive_findings_lines(
        self,
        detail: RunDetail,
        lines: list[str],
        is_zh: bool,
    ) -> list[str]:
        if detail.comparison_matrix is None:
            source_ids = self._matrix_source_ids(detail)
            refs = self._format_source_refs(source_ids)
            if is_zh:
                lines.extend(
                    [
                        f"- 竞争发现暂以证据覆盖为核心约束：结构化对比矩阵尚未形成，因此不能直接宣布赢家。{refs}",
                        f"- 可用信号应先按竞品、维度和来源类型分层阅读，避免把单条搜索线索或低置信度材料提升为采购结论。{refs}",
                        f"- 决策含义是先补齐关键单元格，再把价格、功能、用户人群和切换触发转成正式竞争建议。{refs}",
                        f"- 下一轮优先收集能够互相印证的官方页面、社区讨论、案例或访谈材料，让矩阵具备可解释的强弱差异。{refs}",
                    ]
                )
            else:
                lines.extend(
                    [
                        (
                            "- Competitive findings are currently constrained by source coverage: "
                            f"the structured comparison matrix is not available, so no winner should be declared yet.{refs}"
                        ),
                        (
                            "- Read the available signals by competitor, dimension, and source type before promoting "
                            f"any search-only or low-confidence item into a buying conclusion.{refs}"
                        ),
                        (
                            "- The practical decision is to fill the key cells first, then turn pricing, feature, "
                            f"persona, and switching signals into a formal competitive recommendation.{refs}"
                        ),
                        (
                            "- Next collection should prioritize mutually confirming official pages, community "
                            f"discussions, case studies, or interviews so the matrix can explain real strengths and weaknesses.{refs}"
                        ),
                    ]
                )
            return lines

        matrix_refs = self._matrix_source_ids(detail)
        matrix_ref_text = self._format_source_refs(matrix_refs)
        dimensions = ", ".join(detail.plan.dimensions) or (
            "请求维度" if is_zh else "requested dimensions"
        )
        winners = ", ".join(
            f"{dimension}: {winner}"
            for dimension, winner in detail.comparison_matrix.winner_by_dimension.items()
            if winner
        ) or ("尚无确认赢家" if is_zh else "no confirmed winners")
        if is_zh:
            lines.append(
                f"- 总体读数：本轮矩阵覆盖 {dimensions}，当前赢家线索为 {winners}；这些结论应被视为带证据边界的竞争判断，而不是脱离来源的绝对排名。{matrix_ref_text}"
            )
        else:
            lines.append(
                f"- Overall read: the current matrix covers {dimensions}, with winner signals at {winners}; "
                f"treat these as evidence-bounded competitive judgments, not absolute rankings detached from the cited cells.{matrix_ref_text}"
            )

        for dimension in detail.plan.dimensions:
            cells = [
                cell for cell in detail.comparison_matrix.cells if cell.dimension == dimension
            ]
            if not cells:
                continue
            source_ids = [source_id for cell in cells for source_id in cell.source_ids]
            refs = self._format_source_refs(source_ids)
            winner = detail.comparison_matrix.winner_by_dimension.get(dimension)
            cell_summary = "; ".join(
                f"{cell.competitor}: {self._trim_sentence(cell.value, 140)}"
                for cell in cells[:4]
            )
            confidence_values = [cell.confidence for cell in cells]
            confidence_summary = (
                f"{min(confidence_values):.2f}-{max(confidence_values):.2f}"
                if confidence_values
                else "unknown"
            )
            if winner:
                if is_zh:
                    lines.append(
                        f"- {dimension}：{winner} 在该维度领先；可写成竞争优势的前提是同时保留对比单元格的差异：{cell_summary or '暂无单元格摘要'}。{refs}"
                    )
                    lines.append(
                        f"- {dimension} 的证据姿态：单元格置信度区间为 {confidence_summary}，销售或产品话术应强调已引用材料能证明的部分，并把弱单元格列入验证任务。{refs}"
                    )
                else:
                    lines.append(
                        f"- {dimension}: {winner} leads this dimension, but the implication should stay tied to "
                        f"the cited cell differences: {cell_summary or 'no cell summary available'}.{refs}"
                    )
                    lines.append(
                        f"- {dimension} evidence posture: cell confidence ranges {confidence_summary}; sales or "
                        f"product messaging should emphasize only what the cited material can support and route weaker cells into verification tasks.{refs}"
                    )
            else:
                if is_zh:
                    lines.append(
                        f"- {dimension}：存在可用于对比的证据，但暂不宣布明确赢家；当前单元格显示 {cell_summary or '暂无单元格摘要'}。{refs}"
                    )
                    lines.append(
                        f"- {dimension} 的处理方式：置信度区间为 {confidence_summary}，应把差异转成待验证假设，而不是直接转成采购或市场声明。{refs}"
                    )
                else:
                    lines.append(
                        f"- {dimension}: evidence exists for comparison, but no clear winner should be asserted "
                        f"without another validation pass; current cells show {cell_summary or 'no cell summary available'}.{refs}"
                    )
                    lines.append(
                        f"- {dimension} handling: confidence ranges {confidence_summary}, so the difference should "
                        f"become a validation hypothesis rather than an immediate procurement or market claim.{refs}"
                    )

        if len(lines) == 2:
            refs = self._format_source_refs(matrix_refs)
            if is_zh:
                lines.append(f"- 尚无维度级别的发现；在做出竞争建议之前，请使用收集任务。{refs}")
            else:
                lines.append(
                    "- No dimension-level findings are available yet; use collection tasks before "
                    f"making a competitive recommendation.{refs}"
                )
        elif is_zh:
            lines.append(
                f"- 竞争建议落地时，应把赢家、证据强度、弱单元格和下一步验证放在同一段中呈现；这样能让报告既可行动，又不会把证据缺口包装成确定事实。{matrix_ref_text}"
            )
        else:
            lines.append(
                "- When turning these findings into action, present the winner, evidence strength, weak cells, "
                f"and next validation step together; that keeps the report usable without packaging evidence gaps as settled facts.{matrix_ref_text}"
            )
        return lines

    def _backfill_side_by_side_matrix_section(self, detail: RunDetail) -> list[str]:
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        lines = [
            "",
            f"## {report_label(detail.output_language, 'side_by_side_matrix')}",
        ]
        matrix = detail.comparison_matrix
        if matrix is None or not matrix.cells:
            refs = self._format_source_refs(self._matrix_source_ids(detail))
            if is_zh:
                lines.extend(
                    [
                        f"- 结构化对比矩阵尚不可用；所有维度判断都应先作为证据缺口处理。{refs}",
                        f"- 宣布赢家前，需要先为每个竞品和维度补齐或重新生成矩阵单元格。{refs}",
                    ]
                )
            else:
                lines.extend(
                    [
                        (
                            "- The structured comparison matrix is not available yet; "
                            f"treat all dimension-level reads as evidence gaps.{refs}"
                        ),
                        (
                            "- Before declaring winners, collect or regenerate matrix cells "
                            f"for every requested competitor and dimension.{refs}"
                        ),
                    ]
                )
            return lines

        matrix_refs = self._format_source_refs(self._matrix_source_ids(detail))
        winners = ", ".join(
            f"{dimension}: {winner}"
            for dimension, winner in matrix.winner_by_dimension.items()
            if winner
        )
        if winners:
            prefix = (
                "- 结构化矩阵中的赢家信号："
                if is_zh
                else "- Winner signals from the structured matrix: "
            )
            lines.append(f"{prefix}{winners}.{matrix_refs}")
        summary_prefix = "- 矩阵备注：" if is_zh else "- Matrix note: "
        for summary_item in matrix.summary[:3]:
            lines.append(
                f"{summary_prefix}"
                f"{self._markdown_table_cell(summary_item, limit=260)}{matrix_refs}"
            )

        table_header = (
            "| 竞品 | 维度 | 发现 | 置信度 | 证据 |"
            if is_zh
            else "| Competitor | Dimension | Finding | Confidence | Evidence |"
        )
        lines.extend(
            [
                "",
                table_header,
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for cell in self._ordered_comparison_cells(detail):
            refs = self._format_source_refs(cell.source_ids)
            lines.append(
                "| "
                f"{self._markdown_table_cell(cell.competitor)} | "
                f"{self._markdown_table_cell(cell.dimension)} | "
                f"{self._markdown_table_cell(cell.value, limit=260)} | "
                f"{cell.confidence:.2f} | "
                f"{refs or '-'} |"
            )
        return lines

    def _backfill_competitor_deep_dives_section(self, detail: RunDetail) -> list[str]:
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        lines = [
            "",
            f"## {report_label(detail.output_language, 'competitor_deep_dives')}",
        ]
        matrix = detail.comparison_matrix
        for competitor in detail.plan.competitors:
            lines.append(f"### {competitor}")
            if matrix is None:
                source_ids = [
                    source.id for source in detail.raw_sources if source.competitor == competitor
                ][:4]
                if is_zh:
                    lines.append(
                        f"- {competitor} 优势：尚未确立；在声称优势之前，请使用已证实的证据。"
                        f"{self._format_source_refs(source_ids)}"
                    )
                    lines.append(
                        f"- {competitor} 劣势：覆盖不足的维度在链接更多来源之前仍未解决。"
                        f"{self._format_source_refs(source_ids)}"
                    )
                    lines.append(
                        f"- {competitor} 注意事项：在 QA 和来源覆盖率提高之前，避免绝对声明。"
                        f"{self._format_source_refs(source_ids)}"
                    )
                else:
                    lines.append(
                        "- Positioning: not established yet; use verified evidence before "
                        f"claiming advantage.{self._format_source_refs(source_ids)}"
                    )
                    lines.append(
                        "- Pricing, feature, and persona watchouts: under-covered dimensions "
                        "remain unresolved until more sources are linked."
                        f"{self._format_source_refs(source_ids)}"
                    )
                    lines.append(
                        "- Evidence gaps: avoid absolute claims until QA and source coverage "
                        f"improve.{self._format_source_refs(source_ids)}"
                    )
                continue

            competitor_cells = [
                cell for cell in matrix.cells if cell.competitor == competitor
            ]
            source_ids = [source_id for cell in competitor_cells for source_id in cell.source_ids]
            winning_dimensions = [
                dimension
                for dimension, winner in matrix.winner_by_dimension.items()
                if winner == competitor
            ]
            weaker_dimensions = [
                dimension
                for dimension, winner in matrix.winner_by_dimension.items()
                if winner and winner != competitor
            ]
            if is_zh:
                wins = ", ".join(winning_dimensions) or "尚无确认的维度赢家"
                weaknesses = ", ".join(weaker_dimensions) or "尚无明确的矩阵落后维度"
                lines.append(
                    f"- {competitor} 优势：{wins}；保持声明限定在引用的维度证据范围内。"
                    f"{self._format_source_refs(source_ids)}"
                )
                lines.append(
                    f"- {competitor} 劣势：{weaknesses}；验证差距是真正的竞争劣势还是收集限制。"
                    f"{self._format_source_refs(source_ids)}"
                )
                lines.append(
                    f"- {competitor} 注意事项：在将这些转为外部宣传信息之前，"
                    "监控定价、包装、功能和买家反对意见声明。"
                    f"{self._format_source_refs(source_ids)}"
                )
            else:
                wins = ", ".join(winning_dimensions) or "no confirmed dimension winner yet"
                weaknesses = ", ".join(weaker_dimensions) or "no explicit matrix loss yet"
                lines.append(
                    f"- Wins: {wins}; keep the claim scoped to the cited dimension "
                    f"evidence.{self._format_source_refs(source_ids)}"
                )
                lines.append(
                    f"- Weaknesses: {weaknesses}; verify whether gaps are real competitive "
                    "disadvantages or collection limits."
                    f"{self._format_source_refs(source_ids)}"
                )
                lines.append(
                    "- Watchouts: monitor pricing, packaging, feature, and buyer objection "
                    "claims before turning this into external messaging."
                    f"{self._format_source_refs(source_ids)}"
                )
        return lines

    def _backfill_evidence_support_section(self, detail: RunDetail) -> list[str]:
        refs = self._format_source_refs(self._matrix_source_ids(detail))
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        if is_zh:
            return [
                "",
                f"## {report_label(detail.output_language, 'evidence_support')}",
                (
                    "- 使用以下支持部分来审计来源质量、场景 QA、知识覆盖、"
                    f"声明风险以及剩余的验证任务。{refs}"
                ),
                f"- 保持支持材料简洁且完整，以便上面的决策分析仍为主要读取内容。{refs}",
            ]
        return [
            "",
            f"## {report_label(detail.output_language, 'evidence_support')}",
            (
                "- Use the following support sections to audit source quality, scenario QA, "
                f"knowledge coverage, claim risk, and remaining verification tasks.{refs}"
            ),
            (
                "- Keep support material concise and complete so the decision analysis above "
                f"remains the primary readout.{refs}"
            ),
        ]

    def _backfill_source_quality_section(self, detail: RunDetail) -> list[str]:
        heading = report_label(detail.output_language, "source_quality")
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        if not detail.raw_sources:
            return [
                "",
                f"## {heading}",
                (
                    "- 没有可用的原始来源，因此所有结论在使用前都需要进行收集。"
                    if is_zh
                    else (
                        "- No raw sources are available, so all conclusions require "
                        "collection before use."
                    )
                ),
            ]
        by_type: dict[str, list[tuple[str, float]]] = {}
        for source in detail.raw_sources:
            by_type.setdefault(source.source_type, []).append((source.id, source.confidence))
        lines = ["", f"## {heading}"]
        for source_type, values in sorted(by_type.items()):
            source_ids = [source_id for source_id, _confidence in values]
            avg_confidence = sum(confidence for _source_id, confidence in values) / len(values)
            if is_zh:
                lines.append(
                    f"- {source_type}：{len(values)} 个来源，平均置信度 "
                    f"{avg_confidence:.2f}{self._format_source_refs(source_ids)}"
                )
            else:
                lines.append(
                    f"- {source_type}: {len(values)} source(s), avg confidence "
                    f"{avg_confidence:.2f}{self._format_source_refs(source_ids)}"
                )
        return lines

    def _backfill_scenario_checklist_section(self, detail: RunDetail) -> list[str]:
        scenario_id = detail.plan.scenario_id or "auto"
        pack = get_scenario_pack(scenario_id) if detail.plan.scenario_id else None
        recommended = detail.plan.scenario_recommended_dimensions or detail.plan.dimensions
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        if is_zh:
            lines = [
                "",
                f"## {report_label(detail.output_language, 'scenario_checklist')}",
                (
                    f"- 场景：{scenario_id}；竞品层：{detail.plan.competitor_layer}；"
                    f"推荐维度：{', '.join(recommended) or '无'}。"
                ),
            ]
            if pack is not None:
                lines.append(f"- 场景意图：{pack.description}")
                for question in pack.analyst_questions[:3]:
                    lines.append(f"- 分析师问题：{question}")
                for requirement in pack.evidence_requirements[:3]:
                    lines.append(f"- 证据要求：{requirement}")
            if detail.plan.qa_rule_ids:
                lines.append(f"- QA 规则：{', '.join(detail.plan.qa_rule_ids)}")
        else:
            lines = [
                "",
                f"## {report_label(detail.output_language, 'scenario_checklist')}",
                (
                    f"- Scenario: {scenario_id}; layer: {detail.plan.competitor_layer}; "
                    f"recommended dimensions: {', '.join(recommended) or 'none'}."
                ),
            ]
            if pack is not None:
                lines.append(f"- Scenario intent: {pack.description}")
                for question in pack.analyst_questions[:3]:
                    lines.append(f"- Analyst question: {question}")
                for requirement in pack.evidence_requirements[:3]:
                    lines.append(f"- Evidence requirement: {requirement}")
            if detail.plan.qa_rule_ids:
                lines.append(f"- QA rules: {', '.join(detail.plan.qa_rule_ids)}")
        return lines

    def _backfill_next_collection_plan(self, detail: RunDetail) -> list[str]:
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        lines = ["", f"## {report_label(detail.output_language, 'next_collection')}"]
        source_ids_by_dimension: dict[str, list[str]] = {}
        for source in detail.raw_sources:
            source_ids_by_dimension.setdefault(source.dimension, []).append(source.id)
        planned = 0
        for dimension in detail.plan.dimensions:
            source_ids = source_ids_by_dimension.get(dimension, [])
            if len(source_ids) >= max(1, min(2, len(detail.plan.competitors))):
                continue
            planned += 1
            if is_zh:
                lines.append(
                    f"- 为覆盖不足的竞品添加更强的 {dimension} 证据"
                    f"{self._format_source_refs(source_ids)}"
                )
            else:
                lines.append(
                    f"- Add stronger {dimension} evidence for under-covered competitors"
                    f"{self._format_source_refs(source_ids)}"
                )
        for issue in detail.qa_findings[:3]:
            planned += 1
            if is_zh:
                lines.append(f"- 解决 QA 发现：{issue.problem}")
            else:
                lines.append(f"- Resolve QA finding: {issue.problem}")
        if planned == 0:
            if is_zh:
                lines.append(
                    "- 仅针对陈旧、被拒绝或低置信度的证据重新进行收集。"
                )
            else:
                lines.append(
                    "- Re-run collection only for stale, rejected, or low-confidence evidence."
                )
        return lines

    def _writer_source_appendix_lines(self, detail: RunDetail) -> list[str]:
        evidence_pack_result = build_writer_evidence_pack(detail)
        lines = ["", f"## {report_label(detail.output_language, 'evidence_appendix')}"]
        for row in evidence_pack_result.source_appendix_rows():
            source_id = row["source_id"]
            title = row["title"] or source_id
            source_type = row["source_type"]
            competitor = row["competitor"]
            dimension = row["dimension"]
            confidence = row["confidence"]
            url = row["url"] or "no url"
            lines.append(
                f"- [source:{source_id}] {title} | {source_type} | "
                f"{competitor}/{dimension} | confidence={confidence} | {url}"
            )
        return lines

    def _backfill_evidence_appendix(self, detail: RunDetail) -> list[str]:
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        lines = ["", f"## {report_label(detail.output_language, 'evidence_appendix')}"]
        if not detail.raw_sources:
            if is_zh:
                lines.append("- 本报告草案未附带任何证据记录。")
            else:
                lines.append("- No evidence records are attached to this report draft.")
            return lines
        for source in detail.raw_sources[:8]:
            if is_zh:
                lines.append(
                    f"- {source.id}：{source.title} / {source.source_type} / 置信度 "
                    f"{source.confidence:.2f} [source:{source.id}]"
                )
            else:
                lines.append(
                    f"- {source.id}: {source.title} / {source.source_type} / confidence "
                    f"{source.confidence:.2f} [source:{source.id}]"
                )
        if len(detail.raw_sources) > 8:
            omitted_count = len(detail.raw_sources) - 8
            if is_zh:
                lines.append(f"- 附录中省略了 {omitted_count} 个额外来源。")
            else:
                lines.append(f"- {omitted_count} additional source(s) omitted from this appendix.")
        return lines

    def _harden_report_markdown(self, detail: RunDetail, markdown: str) -> str:
        repaired = repair_mojibake_text(markdown)
        return self._ensure_report_claim_citations(
            detail,
            self._repair_report_source_tokens(
                detail,
                self._ensure_report_required_sections(detail, repaired),
            ),
        )

    def _harden_schema_contract_report_markdown(
        self,
        detail: RunDetail,
        markdown: str,
    ) -> str:
        repaired = repair_mojibake_text(markdown)
        repaired = self._repair_report_source_tokens(detail, repaired)
        preflight = run_writer_quality_preflight(detail, repaired)
        if not preflight.passed:
            raise RuntimeError(
                "Schema-contract report failed quality preflight after hardening: "
                f"{', '.join(preflight.failure_reasons)}"
            )
        publication_validation = validate_publication_contract(
            repaired,
            structured_report=None,
            allowed_source_ids={source.id for source in detail.raw_sources},
            output_language=detail.output_language,
        )
        if not publication_validation.passed:
            raise ValueError(
                "schema-contract report failed publication contract after hardening: "
                + ", ".join(publication_validation.issue_codes())
            )
        return repaired

    def _ensure_report_required_sections(self, detail: RunDetail, markdown: str) -> str:
        hardened = markdown.strip()
        if not hardened:
            raise RuntimeError("Writer returned empty report content")
        source_ids = self._matrix_source_ids(detail)
        executive_headings = self._report_label_aliases(
            "executive_takeaway",
            "executive_summary",
            "executive_overview",
        )
        layer_heading_aliases = self._report_label_aliases(
            self._layer_section_label_key(detail)
        )
        core_section_groups = [
            (
                executive_headings,
                self._backfill_executive_summary_section(detail, source_ids),
            ),
            (
                self._report_label_aliases("decision_summary"),
                self._backfill_decision_summary_section(detail, source_ids),
            ),
            (
                self._report_label_aliases("competitive_findings"),
                self._backfill_competitive_findings_section(detail),
            ),
            (
                self._report_label_aliases("review_theme_summary"),
                self._backfill_review_theme_section(detail),
            ),
            (
                self._report_label_aliases("competitor_deep_dives"),
                self._backfill_competitor_deep_dives_section(detail),
            ),
            (
                self._report_label_aliases("side_by_side_matrix"),
                self._backfill_side_by_side_matrix_section(detail),
            ),
            (
                self._report_label_aliases("swot_analysis"),
                self._backfill_swot_section(detail),
            ),
            (
                layer_heading_aliases,
                self._backfill_layer_sections(detail, source_ids),
            ),
        ]
        core_blocks = [
            self._section_body(lines)
            for headings, lines in core_section_groups
            if lines and not self._report_has_any_h2_heading(hardened, headings)
        ]
        if core_blocks:
            support_headings = [
                heading
                for aliases in self._support_report_heading_alias_groups()
                for heading in aliases
            ]
            insert_at = self._first_report_h2_heading_index(
                hardened, support_headings
            )
            core_block = "\n\n".join(core_blocks)
            if insert_at is None:
                hardened = f"{hardened}\n\n{core_block}"
            else:
                hardened = (
                    f"{hardened[:insert_at].rstrip()}\n\n{core_block}\n\n"
                    f"{hardened[insert_at:].lstrip()}"
                )

        support_section_groups = [
            (
                report_label(detail.output_language, "evidence_support"),
                self._report_label_aliases("evidence_support"),
                self._backfill_evidence_support_section(detail),
            ),
            (
                report_label(detail.output_language, "source_quality"),
                self._report_label_aliases("source_quality"),
                self._backfill_source_quality_section(detail),
            ),
            (
                report_label(detail.output_language, "memory_context"),
                self._report_label_aliases("memory_context"),
                self._backfill_memory_context_section(detail),
            ),
            (
                report_label(detail.output_language, "user_research_evidence"),
                self._report_label_aliases("user_research_evidence"),
                self._backfill_user_research_section(detail),
            ),
            (
                report_label(detail.output_language, "rag_gap_fill"),
                self._report_label_aliases("rag_gap_fill"),
                self._backfill_rag_gap_fill_section(detail),
            ),
            (
                report_label(detail.output_language, "scenario_checklist"),
                self._report_label_aliases("scenario_checklist"),
                self._backfill_scenario_checklist_section(detail),
            ),
            (
                report_label(detail.output_language, "claim_risk"),
                self._report_label_aliases("claim_risk"),
                self._backfill_claim_validation_section(detail),
            ),
            (
                report_label(detail.output_language, "next_collection"),
                self._report_label_aliases("next_collection"),
                self._backfill_next_collection_plan(detail),
            ),
            (
                report_label(detail.output_language, "evidence_appendix"),
                self._report_label_aliases("evidence_appendix"),
                self._backfill_evidence_appendix(detail),
            ),
        ]
        support_order_heading_groups = self._support_report_heading_alias_groups()
        for heading, heading_aliases, lines in support_section_groups:
            if lines and not self._report_has_any_heading(
                hardened, heading_aliases
            ):
                support_index = next(
                    index
                    for index, aliases in enumerate(support_order_heading_groups)
                    if heading in aliases
                )
                later_headings = [
                    later_heading
                    for aliases in support_order_heading_groups[support_index + 1 :]
                    for later_heading in aliases
                ]
                insert_at = self._first_report_h2_heading_index(
                    hardened, later_headings
                )
                section_body = self._section_body(lines)
                if insert_at is None:
                    hardened = f"{hardened}\n\n{section_body}"
                else:
                    hardened = (
                        f"{hardened[:insert_at].rstrip()}\n\n{section_body}\n\n"
                        f"{hardened[insert_at:].lstrip()}"
                    )
        return self._normalize_report_section_order(detail, hardened)

    def _layer_section_heading(self, detail: RunDetail) -> str:
        return report_label(detail.output_language, self._layer_section_label_key(detail))

    def _layer_section_label_key(self, detail: RunDetail) -> str:
        if detail.plan.competitor_layer == "L1":
            return "battlecard"
        if detail.plan.competitor_layer == "L2":
            return "workflow_enterprise_risk"
        if detail.plan.competitor_layer == "L3":
            return "market_landscape"
        return "business_implications"

    def _report_label_aliases(self, *keys: str) -> list[str]:
        labels: list[str] = []
        for key in keys:
            for output_language in ("en-US", "zh-CN"):
                label = report_label(output_language, key)
                if label not in labels:
                    labels.append(label)
        return labels

    def _support_report_heading_alias_groups(self) -> list[list[str]]:
        return [
            self._report_label_aliases("evidence_support"),
            self._report_label_aliases("source_quality"),
            self._report_label_aliases("memory_context"),
            self._report_label_aliases("user_research_evidence"),
            self._report_label_aliases("rag_gap_fill"),
            self._report_label_aliases("scenario_checklist"),
            self._report_label_aliases("knowledge_coverage"),
            self._report_label_aliases("confidence_notes"),
            self._report_label_aliases("claim_risk"),
            self._report_label_aliases("next_collection"),
            self._report_label_aliases("evidence_appendix"),
            self._report_label_aliases("generation_notes"),
        ]

    def _report_has_heading(self, markdown: str, heading: str) -> bool:
        return any(
            self._report_heading_matches(match.group(1), heading)
            for match in self._iter_report_headings(markdown)
        )

    def _report_has_any_heading(self, markdown: str, headings: Iterable[str]) -> bool:
        return any(self._report_has_heading(markdown, heading) for heading in headings)

    def _report_has_h2_heading(self, markdown: str, heading: str) -> bool:
        return any(
            self._report_heading_matches(match.group(1), heading)
            for match in self._iter_report_h2_headings(markdown)
        )

    def _report_has_any_h2_heading(
        self, markdown: str, headings: Iterable[str]
    ) -> bool:
        return any(
            self._report_has_h2_heading(markdown, heading) for heading in headings
        )

    def _first_report_h2_heading_index(
        self, markdown: str, headings: Iterable[str]
    ) -> int | None:
        heading_list = list(headings)
        positions = [
            match.start()
            for match in self._iter_report_h2_headings(markdown)
            if any(
                self._report_heading_matches(match.group(1), heading)
                for heading in heading_list
            )
        ]
        return min(positions) if positions else None

    def _iter_report_h2_headings(self, markdown: str) -> Iterable[re.Match[str]]:
        return re.finditer(
            r"^\s*##\s+(.+?)\s*#*\s*$",
            markdown,
            flags=re.IGNORECASE | re.MULTILINE,
        )

    def _first_report_heading_index(
        self, markdown: str, headings: Iterable[str]
    ) -> int | None:
        heading_list = list(headings)
        positions = [
            match.start()
            for match in self._iter_report_headings(markdown)
            if any(
                self._report_heading_matches(match.group(1), heading)
                for heading in heading_list
            )
        ]
        return min(positions) if positions else None

    def _iter_report_headings(self, markdown: str) -> Iterable[re.Match[str]]:
        return re.finditer(
            r"^\s*#{1,6}\s+(.+?)\s*#*\s*$",
            markdown,
            flags=re.IGNORECASE | re.MULTILINE,
        )

    def _report_heading_matches(self, heading: str, alias: str) -> bool:
        normalized_heading = self._normalize_report_heading_text(heading)
        normalized_alias = self._normalize_report_heading_text(alias)
        compact_heading = self._compact_report_heading_text(heading)
        compact_alias = self._compact_report_heading_text(alias)
        return (
            normalized_heading == normalized_alias
            or normalized_alias in normalized_heading
            or compact_heading == compact_alias
            or compact_alias in compact_heading
        )

    def _normalize_report_heading_text(self, heading: str) -> str:
        cleaned = re.sub(r"\s+", " ", heading.strip().strip("#").strip())
        cleaned = re.sub(
            r"^(?:section\s+)?(?:\d+(?:\.\d+)*|[ivxlcdm]+)[\.)]\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        return cleaned.casefold()

    def _compact_report_heading_text(self, heading: str) -> str:
        return re.sub(r"\s+", "", self._normalize_report_heading_text(heading))

    def _normalize_report_section_order(self, detail: RunDetail, markdown: str) -> str:
        matches = list(
            re.finditer(
                r"^##\s+(.+?)\s*$",
                markdown,
                flags=re.MULTILINE,
            )
        )
        if not matches:
            return markdown

        heading_groups = self._ordered_report_heading_groups(detail)
        heading_order = [
            (index, heading)
            for index, group in enumerate(heading_groups)
            for heading in group
        ]
        support_heading_aliases = [
            heading
            for group in self._support_report_heading_alias_groups()
            for heading in group
        ]
        first_support_start = min(
            (
                match.start()
                for match in matches
                if any(
                    self._report_heading_matches(match.group(1).strip(), heading)
                    for heading in support_heading_aliases
                )
            ),
            default=None,
        )
        known_sections: dict[int, list[str]] = {}
        pre_support_unknown_sections: list[str] = []
        tail_unknown_sections: list[str] = []
        for index, match in enumerate(matches):
            section_start = self._report_section_start_with_marker(
                markdown,
                match.start(),
            )
            section_end = (
                self._report_section_start_with_marker(
                    markdown,
                    matches[index + 1].start(),
                )
                if index + 1 < len(matches)
                else len(markdown)
            )
            heading = match.group(1).strip()
            section = markdown[section_start:section_end].strip()
            order_index = next(
                (
                    index
                    for index, known_heading in heading_order
                    if self._report_heading_matches(heading, known_heading)
                ),
                None,
            )
            if order_index is None:
                if first_support_start is not None and match.start() < first_support_start:
                    pre_support_unknown_sections.append(section)
                else:
                    tail_unknown_sections.append(section)
            else:
                known_sections.setdefault(order_index, []).append(section)

        if not known_sections:
            return markdown

        first_section_start = self._report_section_start_with_marker(
            markdown,
            matches[0].start(),
        )
        preamble = markdown[:first_section_start].strip()
        support_start_index = len(heading_groups) - len(
            self._support_report_heading_alias_groups()
        )
        core_sections = [
            section
            for index in range(support_start_index)
            for section in known_sections.get(index, [])
        ]
        support_sections = [
            section
            for index in range(support_start_index, len(heading_groups))
            for section in known_sections.get(index, [])
        ]
        return "\n\n".join(
            part
            for part in [
                preamble,
                *core_sections,
                *pre_support_unknown_sections,
                *support_sections,
                *tail_unknown_sections,
            ]
            if part
        )

    def _report_section_start_with_marker(
        self,
        markdown: str,
        heading_start: int,
    ) -> int:
        previous_line_end = heading_start
        while previous_line_end > 0 and markdown[previous_line_end - 1] in " \t\r\n":
            previous_line_end -= 1
        previous_line_start = markdown.rfind("\n", 0, previous_line_end) + 1
        previous_line = markdown[previous_line_start:previous_line_end].strip()
        if re.fullmatch(r"<!--\s*report-section:[^>]*-->", previous_line):
            return previous_line_start
        return heading_start

    def _ordered_report_heading_groups(self, detail: RunDetail) -> list[list[str]]:
        return [
            self._report_label_aliases(
                "executive_takeaway",
                "executive_summary",
                "executive_overview",
            ),
            self._report_label_aliases("decision_summary"),
            self._report_label_aliases("competitive_findings"),
            self._report_label_aliases("review_theme_summary"),
            self._report_label_aliases("dimension_winners"),
            self._report_label_aliases("comparison_matrix", "side_by_side_matrix"),
            self._report_label_aliases("competitor_deep_dives"),
            self._report_label_aliases("swot_analysis"),
            self._report_label_aliases(self._layer_section_label_key(detail)),
            *self._support_report_heading_alias_groups(),
        ]

    def _section_body(self, lines: list[str]) -> str:
        return "\n".join(lines).strip()

    def _writer_layer_label(self, detail: RunDetail) -> str:
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        if detail.plan.competitor_layer == "L1":
            return "直接战报" if is_zh else "Direct Battlecard"
        if detail.plan.competitor_layer == "L2":
            return "相邻工作流评估" if is_zh else "Adjacent Workflow Review"
        if detail.plan.competitor_layer == "L3":
            return "市场格局" if is_zh else "Market Landscape"
        return "竞品分析报告" if is_zh else "Competitive Analysis Report"

    def _writer_layer_context(self, detail: RunDetail) -> str:
        layer = detail.plan.competitor_layer
        scenario = detail.plan.scenario_id or "auto"
        recommended = ", ".join(detail.plan.scenario_recommended_dimensions) or "none"
        if layer == "L1":
            focus = (
                "Direct replacement comparison. Emphasize winner/loser tradeoffs, pricing "
                "and packaging, feature parity, sales objections, switching triggers, and "
                "near-term product response."
            )
        elif layer == "L2":
            focus = (
                "Adjacent workflow comparison. Emphasize workflow overlap, ecosystem and "
                "integration leverage, enterprise adoption risk, switching cost, and where "
                "an adjacent product could absorb the user's use case."
            )
        elif layer == "L3":
            focus = (
                "Market landscape analysis. Emphasize category segmentation, clusters, trend "
                "signals, benchmark dimensions, uncertainty, and strategy options rather than "
                "a simplistic direct winner."
            )
        else:
            focus = "General competitive-intelligence report with explicit uncertainty."
        return f"{focus} Scenario={scenario}. Recommended dimensions={recommended}."

    def _writer_required_sections(self, detail: RunDetail) -> str:
        output_language = detail.output_language
        analysis_sections = [
            (
                f"{report_label(output_language, 'executive_takeaway')}: lead with the "
                "decision-grade takeaway and confidence caveats."
            ),
            (
                f"{report_label(output_language, 'decision_summary')}: state the recommended "
                "action, decision posture, and what not to overstate."
            ),
            (
                f"{report_label(output_language, 'competitive_findings')}: summarize the "
                "highest-impact dimension findings and implications."
            ),
            (
                f"{report_label(output_language, 'review_theme_summary')}: summarize cited "
                "user praise, complaints, adoption blockers, and switching triggers; mark "
                "missing review evidence as an evidence gap."
            ),
            (
                f"{report_label(output_language, 'competitor_deep_dives')}: cover where "
                "each competitor wins, has weaknesses, and needs watchouts."
            ),
            (
                f"{report_label(output_language, 'swot_analysis')}: include Strengths, "
                "Weaknesses, Opportunities, and Threats for each competitor using cited SWOT "
                "analysis or explicit evidence-gap notes. Use explicit quadrant labels "
                "`Strengths`, `Weaknesses`, `Opportunities`, and `Threats` (or the localized "
                "equivalents) under every competitor instead of only writing general prose."
            ),
            (
                f"{report_label(output_language, 'side_by_side_matrix')}: cover every "
                "competitor and dimension with cited cells."
            ),
        ]
        if any(source.metadata.get("community_evidence") for source in detail.raw_sources):
            analysis_sections.append(
                f"{report_label(output_language, 'community_evidence_triangulation')}: "
                "separate official facts from community observations, contested claims, "
                "and actual-use risks."
            )
        layer = detail.plan.competitor_layer
        if layer == "L1":
            layer_sections = [
                (
                    f"{report_label(output_language, 'battlecard')}: where each competitor "
                    "wins, loses, is vulnerable, and how to handle objections."
                ),
                "Pricing, packaging, feature parity, switching triggers, and sales response.",
                "Recommended product or go-to-market response with evidence limits.",
            ]
        elif layer == "L2":
            layer_sections = [
                (
                    f"{report_label(output_language, 'workflow_enterprise_risk')}: workflow "
                    "overlap, ecosystem leverage, and enterprise-risk implications."
                ),
                "Enterprise buying risks, switching costs, integration exposure, and controls.",
                "Strategic watchlist for adjacent competitors that could absorb the workflow.",
            ]
        elif layer == "L3":
            layer_sections = [
                (
                    f"{report_label(output_language, 'market_landscape')}: market "
                    "segmentation, competitor clusters, and category strategy."
                ),
                "Trend and benchmark signals by category segment.",
                "Strategic options with uncertainty and evidence gaps clearly separated.",
            ]
        else:
            layer_sections = [
                (
                    f"{report_label(output_language, 'business_implications')}: business "
                    "implications and next validation tasks."
                )
            ]
        support_sections = [
            (
                f"{report_label(output_language, 'evidence_support')}: place source quality, "
                "QA, RAG gap-fill, claim risk, verification, and appendices after the core "
                "analysis."
            ),
            (
                f"{report_label(output_language, 'source_quality')}: separate official or "
                "verified sources from search-only or low-confidence leads."
            ),
            (
                f"{report_label(output_language, 'memory_context')}: include confirmed memory "
                "guidance only when present and not conflicting with evidence."
            ),
            (
                f"{report_label(output_language, 'user_research_evidence')}: treat surveys, "
                "interviews, and manual notes as directional signals, not official proof."
            ),
            (
                f"{report_label(output_language, 'rag_gap_fill')}: list retrieval gaps that "
                "must be closed before publication, including the gap id or topic, suggested "
                "retrieval query, evidence needed, current status, and how the gap affects the "
                "recommendation. Do not use a one-line placeholder."
            ),
            (
                f"{report_label(output_language, 'scenario_checklist')}: tie the selected "
                "ScenarioPack to analyst questions, evidence requirements, and QA rules."
            ),
            (
                f"{report_label(output_language, 'claim_risk')}: list weak claims, "
                "low-confidence sources, and single-source high-risk conclusions."
            ),
            (
                f"{report_label(output_language, 'next_collection')}: next collection and "
                "verification tasks."
            ),
            (
                f"{report_label(output_language, 'evidence_appendix')}: important source IDs "
                "with type and confidence."
            ),
        ]
        core_lines = [
            "Core analysis layer (target 65-75% of the report body):",
            *(
                f"{index}. {section}"
                for index, section in enumerate(
                    [*analysis_sections, *layer_sections], start=1
                )
            ),
        ]
        support_lines = [
            "Support/audit layer (concise audit trail after core analysis):",
            *(
                f"{index}. {section}"
                for index, section in enumerate(support_sections, start=1)
            ),
        ]
        return "\n".join([*core_lines, *support_lines])

    async def _writer_grounding_prompt(self, detail: RunDetail) -> str:
        grounding = build_run_grounding_prompt(
            sources=detail.raw_sources,
            qa_findings=detail.qa_findings,
        )
        kb_source_ids = [
            source.id for source in detail.raw_sources if source.candidate_origin == "rag_kb"
        ]
        if kb_source_ids:
            grounding += "\n\n## KB-Reused Evidence\n"
            grounding += (
                "Use KB-reused evidence only through these existing source tokens: "
                f"{', '.join(f'[source:{source_id}]' for source_id in kb_source_ids[:8])}.\n"
            )
        return grounding

    def _writer_context_package(self, detail: RunDetail) -> dict[str, object]:
        return {
            "sources": self._writer_source_digest(detail.raw_sources),
            "competitors": {
                competitor: self._writer_competitor_digest(detail, competitor)
                for competitor in detail.plan.competitors
            },
            "comparison_matrix": self._writer_matrix_digest(detail),
            "qa_findings": [self._writer_issue_digest(issue) for issue in detail.qa_findings],
            "reflections": [
                {
                    "iteration": reflection.iteration,
                    "coverage_gaps": list(reflection.coverage_gaps),
                    "confidence_outliers": list(reflection.confidence_outliers),
                    "cross_competitor_gaps": list(reflection.cross_competitor_gaps),
                }
                for reflection in detail.reflections
            ],
        }

    def _writer_source_digest(self, sources: list[RawSource]) -> list[dict[str, object]]:
        digests: list[dict[str, object]] = []
        for source in sources:
            snippet = self._writer_source_snippet(source)
            digest = {
                "id": source.id,
                "competitor": source.competitor,
                "covered_competitors": source.covered_competitors,
                "dimension": source.dimension,
                "source_type": source.source_type,
                "title": source.title,
                "url": str(source.url) if source.url else None,
                "snippet": snippet,
                "confidence": round(source.confidence, 3),
            }
            if not snippet:
                digest["snippet_quality"] = "omitted_no_clean_business_snippet"
            normalized_fields = self._writer_normalized_fields_digest(source)
            if normalized_fields:
                digest["normalized_fields"] = normalized_fields
            if source.metadata.get("community_evidence"):
                digest["community_evidence"] = True
                community_source_type = self._writer_metadata_string(
                    source.metadata.get("community_source_type")
                )
                if community_source_type is not None:
                    digest["community_source_type"] = community_source_type
                community_authority_signal = self._writer_metadata_string(
                    source.metadata.get("community_authority_signal")
                )
                if community_authority_signal is not None:
                    digest["community_authority_signal"] = community_authority_signal
                digest["official_commitment"] = bool(
                    source.metadata.get("official_commitment", False)
                )
                clusters = self._writer_community_cluster_list_digest(
                    source.metadata.get("community_claim_clusters")
                )
                if clusters:
                    digest["community_claim_clusters"] = clusters
            digests.append(digest)
        return digests

    def _writer_source_snippet(self, source: RawSource) -> str:
        raw_len = len(source.snippet or "")
        normalized_limit = (
            WRITER_NORMALIZED_SNIPPET_LIMIT
            if normalized_fields_from_source(source)
            else max(raw_len, 50000)
        )
        return source_business_snippet(
            source,
            dimension=source.dimension,
            limit=normalized_limit,
        )

    def _writer_normalized_fields_digest(
        self,
        source: RawSource,
    ) -> list[dict[str, object]]:
        fields = normalized_fields_from_source(source)
        digests: list[dict[str, object]] = []
        for field in fields:
            if not isinstance(field, Mapping):
                continue
            digest: dict[str, object] = {}
            for raw_key, raw_value in field.items():
                key = str(raw_key)
                normalized_key = key.strip().lower()
                if normalized_key in WRITER_NORMALIZED_FIELD_DROP_KEYS:
                    continue
                value = self._writer_normalized_field_value(normalized_key, raw_value)
                if value is not None:
                    digest[key] = value
            if digest:
                digests.append(digest)
        return digests

    def _writer_normalized_field_value(
        self,
        key: str,
        value: object,
    ) -> object | None:
        if isinstance(value, str):
            if not value.strip():
                return None
            return self._trim_sentence(
                value,
                self._writer_normalized_field_limit(key),
            )
        if isinstance(value, bool):
            return value
        if isinstance(value, int | float):
            return value if math.isfinite(float(value)) else None
        if isinstance(value, list):
            items: list[object] = []
            for item in value:
                item_value = self._writer_normalized_field_value(key, item)
                if item_value is not None:
                    items.append(item_value)
                if len(items) >= 5:
                    break
            return items or None
        if isinstance(value, Mapping):
            nested: dict[str, object] = {}
            for raw_key, raw_value in value.items():
                nested_key = str(raw_key)
                normalized_nested_key = nested_key.strip().lower()
                if normalized_nested_key in WRITER_NORMALIZED_FIELD_DROP_KEYS:
                    continue
                nested_value = self._writer_normalized_field_value(
                    normalized_nested_key,
                    raw_value,
                )
                if nested_value is not None:
                    nested[nested_key] = nested_value
            return nested or None
        return None

    def _writer_normalized_field_limit(self, key: str) -> int:
        if any(part in key for part in WRITER_NORMALIZED_FIELD_QUOTE_KEY_PARTS):
            return 1200
        if any(part in key for part in WRITER_NORMALIZED_FIELD_LONG_KEY_PARTS):
            return 800
        return 400

    def _writer_source_text_keys(
        self,
        detail: RunDetail,
        *,
        competitor: str,
        dimension: str | None = None,
    ) -> set[str]:
        keys: set[str] = set()
        for source in detail.raw_sources:
            if dimension is not None and source.dimension != dimension:
                continue
            if not self._source_matches_competitor(source, competitor):
                continue
            snippet = self._writer_source_snippet(source)
            key = self._writer_dedupe_text_key(snippet)
            if key:
                keys.add(key)
        return keys

    def _writer_dedupe_text_key(self, value: str) -> str:
        return " ".join(value.split()).casefold()

    def _writer_metadata_string(self, value: object, limit: int = 80) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        return self._trim_sentence(value, limit)

    def _writer_community_cluster_list_digest(
        self,
        clusters: object,
    ) -> list[dict[str, object]]:
        if not isinstance(clusters, list):
            return []
        digests: list[dict[str, object]] = []
        for cluster in clusters:
            if not isinstance(cluster, Mapping):
                continue
            digest = self._writer_community_cluster_digest(cluster)
            if digest:
                digests.append(digest)
            if len(digests) >= 5:
                break
        return digests

    def _writer_community_cluster_digest(
        self,
        cluster: Mapping[str, object],
    ) -> dict[str, object]:
        digest: dict[str, object] = {}
        for key, limit in (
            ("kind", 80),
            ("label", 80),
            ("claim", 180),
            ("normalized_value", 120),
        ):
            value = cluster.get(key)
            if isinstance(value, str) and value.strip():
                digest[key] = self._trim_sentence(value, limit)
        confidence = self._writer_cluster_confidence(cluster.get("confidence"))
        if confidence is not None:
            digest["confidence"] = confidence
        for key, count, limit in (
            ("source_ids", 6, 80),
            ("official_source_ids", 6, 80),
            ("evidence", 3, 180),
            ("conflict_values", 5, 120),
        ):
            values = self._writer_string_list_digest(
                cluster.get(key),
                count=count,
                limit=limit,
            )
            if values:
                digest[key] = values
        return digest

    def _writer_cluster_confidence(self, value: object) -> float | None:
        if isinstance(value, bool):
            return None
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(confidence):
            return None
        return round(confidence, 3)

    def _writer_string_list_digest(
        self,
        values: object,
        *,
        count: int,
        limit: int,
    ) -> list[str]:
        if not isinstance(values, list):
            return []
        digest: list[str] = []
        for value in values:
            if isinstance(value, str) and value.strip():
                digest.append(self._trim_sentence(value, limit))
            if len(digest) >= count:
                break
        return digest

    def _writer_competitor_digest(self, detail: RunDetail, competitor: str) -> dict[str, object]:
        kb = detail.competitor_kbs.get(competitor)
        knowledge = detail.competitor_knowledge.get(competitor)
        slices = {}
        if kb is not None:
            slices = {
                dimension: self._writer_unique_kb_findings(
                    detail,
                    competitor=competitor,
                    dimension=dimension,
                    findings=findings,
                )
                for dimension, findings in kb.slices.items()
                if dimension in detail.plan.dimensions
            }
        return {
            "kb_slices": slices,
            "source_ids": (knowledge.source_ids[:8] if knowledge is not None else []),
            "confidence": (
                round(knowledge.confidence, 3) if knowledge is not None else None
            ),
            "pricing": self._writer_pricing_digest(knowledge),
            "feature_tree": self._writer_feature_tree_digest(knowledge),
            "feature_claims": self._writer_feature_claim_digest(knowledge),
            "persona_claims": self._writer_persona_claim_digest(knowledge),
        }

    def _writer_unique_kb_findings(
        self,
        detail: RunDetail,
        *,
        competitor: str,
        dimension: str,
        findings: Sequence[str],
    ) -> list[str]:
        source_text_keys = self._writer_source_text_keys(
            detail,
            competitor=competitor,
            dimension=dimension,
        )
        unique: list[str] = []
        seen: set[str] = set()
        for finding in findings:
            key = self._writer_dedupe_text_key(finding)
            if not key or key in seen or key in source_text_keys:
                continue
            unique.append(finding)
            seen.add(key)
        return unique

    def _writer_pricing_digest(self, knowledge: object | None) -> dict[str, object]:
        if knowledge is None or not hasattr(knowledge, "pricing_model"):
            return {"tiers": [], "notes": []}
        pricing = knowledge.pricing_model
        return {
            "tiers": [
                {
                    "name": self._trim_sentence(tier.name, 80),
                    "price": self._trim_sentence(tier.price, 80),
                    "claims": self._writer_claim_digest(tier.claims, limit=2),
                }
                for tier in pricing.tiers[:4]
            ],
            "notes": self._writer_claim_digest(pricing.notes, limit=3),
        }

    def _writer_feature_claim_digest(self, knowledge: object | None) -> list[dict[str, object]]:
        if knowledge is None or not hasattr(knowledge, "feature_tree"):
            return []
        claims = list(knowledge.feature_tree.summary_claims)
        for node in knowledge.feature_tree.nodes[:4]:
            claims.extend(node.claims[:2])
        return self._writer_claim_digest(claims, limit=8)

    def _writer_feature_tree_digest(self, knowledge: object | None) -> list[dict[str, object]]:
        if knowledge is None or not hasattr(knowledge, "feature_tree"):
            return []
        nodes = list(knowledge.feature_tree.nodes)
        return [
            {
                "name": self._trim_sentence(node.name, 80),
                "description": self._trim_sentence(node.description, 160),
                "source_ids": self._feature_node_source_ids(node)[:4],
                "claim_count": len(node.claims),
                "child_count": len(node.children),
            }
            for node in nodes[:8]
        ]

    def _writer_persona_claim_digest(self, knowledge: object | None) -> list[dict[str, object]]:
        if knowledge is None or not hasattr(knowledge, "user_personas"):
            return []
        claims = list(knowledge.user_personas.summary_claims)
        for segment in knowledge.user_personas.segments[:4]:
            claims.extend(segment.claims[:2])
        return self._writer_claim_digest(claims, limit=8)

    def _writer_claim_digest(
        self,
        claims: list[KnowledgeClaim],
        *,
        limit: int,
    ) -> list[dict[str, object]]:
        return [
            {
                "claim": self._trim_sentence(claim.claim, 180),
                "source_ids": claim.source_ids[:4],
                "confidence": round(claim.confidence, 3),
            }
            for claim in claims[:limit]
        ]

    def _writer_matrix_digest(self, detail: RunDetail) -> dict[str, object]:
        if detail.comparison_matrix is None:
            return {"winner_by_dimension": {}, "summary": [], "cells": []}
        return {
            "winner_by_dimension": detail.comparison_matrix.winner_by_dimension,
            "summary": [
                self._writer_matrix_summary_item(item)
                for item in detail.comparison_matrix.summary
            ],
            "cells": [
                {
                    "competitor": cell.competitor,
                    "dimension": cell.dimension,
                    "value": self._writer_matrix_cell_value(cell),
                    "source_ids": cell.source_ids,
                    "confidence": round(cell.confidence, 3),
                }
                for cell in detail.comparison_matrix.cells
            ],
        }

    def _writer_matrix_summary_item(self, item: str) -> str:
        return item

    def _writer_matrix_cell_value(self, cell: object) -> str:
        return str(getattr(cell, "value", ""))

    def _feature_node_source_ids(self, node: FeatureNode) -> list[str]:
        source_ids: list[str] = []
        seen: set[str] = set()
        claims = [*node.claims, *self._feature_child_claims(node)]
        for claim in claims:
            for source_id in claim.source_ids:
                if source_id not in seen:
                    seen.add(source_id)
                    source_ids.append(source_id)
        return source_ids

    def _writer_issue_digest(self, issue: QCIssue) -> dict[str, object]:
        return {
            "id": issue.id,
            "severity": issue.severity,
            "target_agent": issue.target_agent,
            "target_subagent": issue.target_subagent,
            "target_competitor": issue.target_competitor,
            "problem": issue.problem,
        }

    def _matrix_source_ids(self, detail: RunDetail) -> list[str]:
        if detail.comparison_matrix is None:
            return [source.id for source in detail.raw_sources[:3]]
        source_ids: list[str] = []
        seen: set[str] = set()
        for cell in detail.comparison_matrix.cells:
            for source_id in cell.source_ids:
                if source_id not in seen:
                    seen.add(source_id)
                    source_ids.append(source_id)
                if len(source_ids) >= 6:
                    return source_ids
        return source_ids

    def _ordered_comparison_cells(self, detail: RunDetail) -> list[ComparisonCell]:
        matrix = detail.comparison_matrix
        if matrix is None:
            return []
        ordered_cells: list[ComparisonCell] = []
        seen_indexes: set[int] = set()
        competitors = matrix.competitors or detail.plan.competitors
        dimensions = matrix.dimensions or detail.plan.dimensions
        for competitor in competitors:
            for dimension in dimensions:
                for index, cell in enumerate(matrix.cells):
                    if index in seen_indexes:
                        continue
                    if cell.competitor == competitor and cell.dimension == dimension:
                        ordered_cells.append(cell)
                        seen_indexes.add(index)
        for index, cell in enumerate(matrix.cells):
            if index not in seen_indexes:
                ordered_cells.append(cell)
        return ordered_cells

    def _format_source_refs(self, source_ids: Iterable[str]) -> str:
        unique = []
        seen: set[str] = set()
        for source_id in source_ids:
            if source_id and source_id not in seen:
                unique.append(source_id)
                seen.add(source_id)
            if len(unique) >= 4:
                break
        if not unique:
            return ""
        return " " + " ".join(f"[source:{source_id}]" for source_id in unique)

    def _backfill_memory_context_section(self, detail: RunDetail) -> list[str]:
        if not detail.plan.memory_prompt_context:
            return []
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        candidate_ids = ", ".join(detail.plan.memory_candidate_ids) or ("无" if is_zh else "none")
        if is_zh:
            lines = [
                "",
                f"## {report_label(detail.output_language, 'memory_context')}",
                (
                    "已确认的 MemoryAgent 指导被用作规划和写作上下文；"
                    "任何被记住的领域事实在发布前仍需要当前的证据支持。"
                ),
                f"- 候选 ID：{candidate_ids}",
                f"- 召回得分：{detail.plan.memory_recall_score}/100",
            ]
        else:
            lines = [
                "",
                f"## {report_label(detail.output_language, 'memory_context')}",
                (
                    "Confirmed MemoryAgent guidance was used as planning and writing context; "
                    "any remembered domain fact still needs current evidence before publication."
                ),
                f"- Candidate IDs: {candidate_ids}",
                f"- Recall score: {detail.plan.memory_recall_score}/100",
            ]
        lines.extend(
            f"- {self._memory_context_label(item, is_zh=is_zh)}: {item}"
            for item in detail.plan.memory_prompt_context[:6]
        )
        return lines

    def _memory_context_label(self, item: str, *, is_zh: bool = False) -> str:
        normalized = item.casefold()
        if normalized.startswith("[domain fact") or "domain fact" in normalized:
            return "领域事实" if is_zh else "Domain fact"
        if normalized.startswith("[qa policy") or "qa policy" in normalized:
            return "QA策略" if is_zh else "QA policy"
        if normalized.startswith("[failure pattern") or "failure pattern" in normalized:
            return "失败模式" if is_zh else "Failure pattern"
        return "指导" if is_zh else "Guidance"

    def _backfill_review_theme_section(self, detail: RunDetail) -> list[str]:
        summaries = [
            knowledge.review_summary
            for knowledge in detail.competitor_knowledge.values()
            if self._review_summary_has_content(knowledge.review_summary)
        ]
        needs_review = self._needs_review_theme_section(detail)

        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        lines = ["", f"## {report_label(detail.output_language, 'review_theme_summary')}"]
        if not summaries:
            refs = self._format_source_refs(self._matrix_source_ids(detail))
            if is_zh:
                if needs_review:
                    lines.append(
                        "- 已请求评价、用户或买家维度分析，但尚无可引用的结构化评价主题；"
                        f"相关结论需保留为 Evidence gap。{refs}"
                    )
                else:
                    lines.append(
                        "- 本核心报告节尚无可引用的用户评价主题；"
                        f"不要编造评价结论，需标记为 Evidence gap。{refs}"
                    )
            else:
                if needs_review:
                    lines.append(
                        "- Review, user, or buyer analysis was requested, but no cited review "
                        f"themes are available yet; keep conclusions as Evidence gap.{refs}"
                    )
                else:
                    lines.append(
                        "- This required core report section has no cited user-review themes "
                        f"yet; do not invent review conclusions. Evidence gap.{refs}"
                    )
            return lines

        category_labels = (
            ("Praise", "好评主题", "praise_themes"),
            ("Complaints", "投诉主题", "complaint_themes"),
            ("Adoption blockers", "采用阻碍", "adoption_blockers"),
            ("Switching triggers", "切换触发", "switching_triggers"),
        )
        for summary in summaries[:4]:
            competitor = summary.competitor or "Unknown competitor"
            lines.append(f"### {competitor}")
            if is_zh:
                lines.append(f"- 情绪提示: {summary.sentiment_hint}")
            else:
                lines.append(f"- Sentiment hint: {summary.sentiment_hint}")
            for en_label, zh_label, field_name in category_labels:
                label = zh_label if is_zh else en_label
                items = getattr(summary, field_name)
                for item in items[:2]:
                    refs = self._format_source_refs(item.source_ids or summary.source_ids)
                    evidence = f" - {item.evidence}" if item.evidence else ""
                    gap = " Evidence gap." if item.evidence_gap else ""
                    lines.append(f"- {label}: {item.theme}{evidence}{gap}{refs}")
        return lines

    def _needs_review_theme_section(self, detail: RunDetail) -> bool:
        review_hints = (
            "review",
            "persona",
            "user",
            "customer",
            "buyer",
            "feedback",
        )
        return any(
            any(hint in dimension.casefold().replace("-", "_") for hint in review_hints)
            for dimension in detail.plan.dimensions
        )

    def _review_summary_has_content(self, summary: object) -> bool:
        return any(
            getattr(summary, field_name, None)
            for field_name in (
                "praise_themes",
                "complaint_themes",
                "adoption_blockers",
                "switching_triggers",
            )
        )

    def _backfill_swot_section(self, detail: RunDetail) -> list[str]:
        analyses = [
            knowledge.swot_analysis
            for knowledge in detail.competitor_knowledge.values()
            if self._swot_analysis_has_content(knowledge.swot_analysis)
        ]
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        lines = ["", f"## {report_label(detail.output_language, 'swot_analysis')}"]
        if not analyses:
            if is_zh:
                lines.append("- 优势: 证据缺口（Evidence gap）：尚无可引用的 SWOT 优势证据。")
                lines.append("- 劣势: 证据缺口（Evidence gap）：尚无可引用的 SWOT 劣势证据。")
                lines.append("- 机会: 证据缺口（Evidence gap）：尚无可引用的 SWOT 机会证据。")
                lines.append("- 威胁: 证据缺口（Evidence gap）：尚无可引用的 SWOT 威胁证据。")
            else:
                lines.append(
                    "- Strengths: Evidence gap - no cited SWOT strength is established yet."
                )
                lines.append(
                    "- Weaknesses: Evidence gap - no cited SWOT weakness is established yet."
                )
                lines.append(
                    "- Opportunities: Evidence gap - no cited SWOT opportunity is established yet."
                )
                lines.append(
                    "- Threats: Evidence gap - no cited SWOT threat is established yet."
                )
            return lines

        for analysis in analyses[:4]:
            lines.append(f"### {analysis.competitor or 'Unknown competitor'}")
            if is_zh:
                lines.extend(
                    self._swot_item_lines(
                        "优势",
                        analysis.strengths,
                        gap_text="证据缺口（Evidence gap）。",
                        empty_gap_text="证据缺口（Evidence gap）：尚无可引用条目。",
                    )
                )
                lines.extend(
                    self._swot_item_lines(
                        "劣势",
                        analysis.weaknesses,
                        gap_text="证据缺口（Evidence gap）。",
                        empty_gap_text="证据缺口（Evidence gap）：尚无可引用条目。",
                    )
                )
                lines.extend(
                    self._swot_item_lines(
                        "机会",
                        analysis.opportunities,
                        gap_text="证据缺口（Evidence gap）。",
                        empty_gap_text="证据缺口（Evidence gap）：尚无可引用条目。",
                    )
                )
                lines.extend(
                    self._swot_item_lines(
                        "威胁",
                        analysis.threats,
                        gap_text="证据缺口（Evidence gap）。",
                        empty_gap_text="证据缺口（Evidence gap）：尚无可引用条目。",
                    )
                )
            else:
                lines.extend(self._swot_item_lines("Strengths", analysis.strengths))
                lines.extend(self._swot_item_lines("Weaknesses", analysis.weaknesses))
                lines.extend(self._swot_item_lines("Opportunities", analysis.opportunities))
                lines.extend(self._swot_item_lines("Threats", analysis.threats))
        return lines

    def _swot_analysis_has_content(self, analysis: object) -> bool:
        return any(
            getattr(analysis, field_name, None)
            for field_name in ("strengths", "weaknesses", "opportunities", "threats")
        )

    def _swot_item_lines(
        self,
        label: str,
        items: Sequence[SWOTItem] | Sequence[object],
        *,
        gap_text: str = "Evidence gap.",
        empty_gap_text: str = "Evidence gap - no cited item is established yet.",
    ) -> list[str]:
        if not items:
            return [f"- {label}: {empty_gap_text}"]
        lines: list[str] = []
        for item in items[:2]:
            text = str(getattr(item, "text", "") or "No SWOT item text available.")
            refs = self._format_source_refs(getattr(item, "source_ids", []))
            gap = f" {gap_text}" if getattr(item, "evidence_gap", False) else ""
            lines.append(f"- {label}: {text}{gap}{refs}")
        return lines

    def _backfill_user_research_section(self, detail: RunDetail) -> list[str]:
        research_sources = [
            source
            for source in detail.raw_sources
            if source.source_type in USER_RESEARCH_SOURCE_TYPES
        ]
        persona_requested = any(
            dimension.casefold().replace("-", "_") in {"persona", "user", "review"}
            for dimension in detail.plan.dimensions
        )
        if not research_sources and not persona_requested:
            return []
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        if is_zh:
            lines = [
                "",
                f"## {report_label(detail.output_language, 'user_research_evidence')}",
                (
                    "调查问卷、访谈和手动笔记输入被视为方向性的买家或用户信号，而非官方的事实证明。"
                ),
            ]
            if not research_sources:
                lines.append(
                    "- 已请求用户画像或评论分析，但尚未附加用户研究来源；"
                    "将画像结论保持在证据差距通道中。"
                    f"{self._format_source_refs(self._matrix_source_ids(detail))}"
                )
                return lines
            for source in research_sources[:5]:
                lines.append(
                    f"- {source.title} / {source.source_type} / 置信度 {source.confidence:.2f}"
                    f" [source:{source.id}]"
                )
        else:
            lines = [
                "",
                f"## {report_label(detail.output_language, 'user_research_evidence')}",
                (
                    "Survey, interview, and manual-note inputs are treated as directional "
                    "buyer or user signals, not as official factual proof."
                ),
            ]
            if not research_sources:
                lines.append(
                    "- Persona or review analysis was requested, but no user-research source "
                    "is attached yet; keep persona conclusions in the evidence-gap lane."
                    f"{self._format_source_refs(self._matrix_source_ids(detail))}"
                )
                return lines
            for source in research_sources[:5]:
                lines.append(
                    f"- {source.title} / {source.source_type} / confidence {source.confidence:.2f}"
                    f" [source:{source.id}]"
                )
        return lines

    def _backfill_rag_gap_fill_section(self, detail: RunDetail) -> list[str]:
        collector_gaps = [
            issue
            for issue in detail.qa_findings
            if issue.target_agent == "collector" and issue.severity in {"warn", "blocker"}
            and not issue.field_path.startswith("release_gate.")
        ]
        if not collector_gaps:
            return []
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        if is_zh:
            lines = [
                "",
                f"## {report_label(detail.output_language, 'rag_gap_fill')}",
                (
                    "在报告发布或用作最终决策产物之前，应通过检索来填补收集器证据差距。"
                ),
            ]
            for issue in collector_gaps[:5]:
                scope = issue.redo_scope
                target = scope.target_subagent or issue.target_subagent or issue.field_path
                competitor = scope.target_competitor or issue.target_competitor or "所有竞品"
                query = self._gap_fill_query(detail, issue)
                sources = self._format_source_refs(self._matrix_source_ids(detail))
                lines.append(
                    f"- 差距：{issue.problem} 目标={target}；"
                    f"竞品={competitor}；重新执行={scope.kind}。"
                    f"建议的检索查询：{query}。{sources}"
                )
            lines.append(
                "- 运行“证据差距填补”操作以检索、重排并附加已证实的证据。"
                "详细差距标识和检索上下文保留在运行审计元数据中。"
            )
        else:
            lines = [
                "",
                f"## {report_label(detail.output_language, 'rag_gap_fill')}",
                (
                    "Collector evidence gaps should be closed through retrieval before this "
                    "report is published or used as a final decision artifact."
                ),
            ]
            for issue in collector_gaps[:5]:
                scope = issue.redo_scope
                target = scope.target_subagent or issue.target_subagent or issue.field_path
                competitor = scope.target_competitor or issue.target_competitor or "all competitors"
                query = self._gap_fill_query(detail, issue)
                sources = self._format_source_refs(self._matrix_source_ids(detail))
                lines.append(
                    f"- Gap: {issue.problem} Target={target}; "
                    f"competitor={competitor}; redo={scope.kind}. "
                    f"Suggested retrieval query: {query}.{sources}"
                )
            lines.append(
                "- Run the Evidence Gap Fill action to retrieve, rerank, and attach verified "
                "evidence. Detailed gap identifiers and retrieval contexts stay in the run "
                "audit metadata."
            )
        return lines

    def _gap_fill_query(self, detail: RunDetail, issue: QCIssue) -> str:
        dimension = issue.target_subagent or "evidence"
        competitor = (
            issue.target_competitor
            or ", ".join(detail.plan.competitors[:3])
            or detail.topic
        )
        query = f"{competitor} {dimension} {issue.problem}".strip()
        return " ".join(query.split())[:180]

    def _backfill_claim_validation_section(self, detail: RunDetail) -> list[str]:
        is_zh = normalize_output_language(detail.output_language) == "zh-CN"
        lines = ["", f"## {report_label(detail.output_language, 'claim_risk')}"]
        source_by_id = {source.id: source for source in detail.raw_sources}
        claims = self._knowledge_claims(detail)
        issue_counts = {
            "blocker": sum(1 for issue in detail.qa_findings if issue.severity == "blocker"),
            "warn": sum(1 for issue in detail.qa_findings if issue.severity == "warn"),
            "info": sum(1 for issue in detail.qa_findings if issue.severity == "info"),
        }
        if is_zh:
            lines.append(
                "- QA 状态："
                f"{issue_counts['blocker']} 个阻碍型，{issue_counts['warn']} 个警告型，"
                f"{issue_counts['info']} 个信息型发现，存在于 {len(claims)} 个结构化声明中。"
                f"{self._format_source_refs(self._matrix_source_ids(detail))}"
            )
        else:
            lines.append(
                "- QA status: "
                f"{issue_counts['blocker']} blocker(s), {issue_counts['warn']} warning(s), "
                f"{issue_counts['info']} info finding(s) across {len(claims)} structured claim(s)."
                f"{self._format_source_refs(self._matrix_source_ids(detail))}"
            )

        weak_claims = [
            claim
            for claim in claims
            if claim.confidence < 0.65
            or self._claim_has_weak_sources(claim.source_ids, source_by_id)
            or self._claim_needs_triangulation(claim.claim, claim.source_ids)
        ]
        if weak_claims:
            for claim in weak_claims[:5]:
                labels = []
                if claim.confidence < 0.65:
                    labels.append(
                        f"置信度 {claim.confidence:.2f}"
                        if is_zh
                        else f"confidence {claim.confidence:.2f}"
                    )
                if self._claim_has_weak_sources(claim.source_ids, source_by_id):
                    labels.append("弱来源组合" if is_zh else "weak source mix")
                if self._claim_needs_triangulation(claim.claim, claim.source_ids):
                    labels.append("需要交叉验证" if is_zh else "needs triangulation")
                if is_zh:
                    lines.append(
                        f"- 审查声明 ({', '.join(labels)})：{self._trim_sentence(claim.claim)}"
                        f"{self._format_source_refs(claim.source_ids)}"
                    )
                else:
                    lines.append(
                        f"- Review claim ({', '.join(labels)}): {self._trim_sentence(claim.claim)}"
                        f"{self._format_source_refs(claim.source_ids)}"
                    )
        else:
            if is_zh:
                lines.append(
                    "- 未检测到低置信度或单来源的高风险结构化声明。"
                    f"{self._format_source_refs(self._matrix_source_ids(detail))}"
                )
            else:
                lines.append(
                    "- No low-confidence or single-source high-risk structured claims were "
                    "detected."
                    f"{self._format_source_refs(self._matrix_source_ids(detail))}"
                )

        for issue in detail.qa_findings[:4]:
            if is_zh:
                lines.append(
                    f"- QA {issue.severity}："
                    f"{self._trim_sentence(issue.problem)}"
                )
            else:
                lines.append(
                    f"- QA {issue.severity}: "
                    f"{self._trim_sentence(issue.problem)}"
                )

        reflection_gaps = self._reflection_gap_notes(detail)
        for note in reflection_gaps[:4]:
            if is_zh:
                lines.append(
                    f"- 证据差距：{self._trim_sentence(note)}"
                    f"{self._format_source_refs(self._matrix_source_ids(detail))}"
                )
            else:
                lines.append(
                    f"- Evidence gap: {self._trim_sentence(note)}"
                    f"{self._format_source_refs(self._matrix_source_ids(detail))}"
                )
        return lines

    def _knowledge_claims(self, detail: RunDetail) -> list[KnowledgeClaim]:
        claims = []
        for knowledge in detail.competitor_knowledge.values():
            for node in knowledge.feature_tree.nodes:
                claims.extend(node.claims)
                claims.extend(self._feature_child_claims(node))
            claims.extend(knowledge.feature_tree.summary_claims)
            for tier in knowledge.pricing_model.tiers:
                claims.extend(tier.claims)
            claims.extend(knowledge.pricing_model.notes)
            for segment in knowledge.user_personas.segments:
                claims.extend(segment.claims)
            claims.extend(knowledge.user_personas.summary_claims)
        return claims

    def _feature_child_claims(self, node: FeatureNode) -> list[KnowledgeClaim]:
        claims = []
        for child in node.children:
            claims.extend(child.claims)
            claims.extend(self._feature_child_claims(child))
        return claims

    def _claim_has_weak_sources(
        self, source_ids: list[str], source_by_id: dict[str, RawSource]
    ) -> bool:
        if not source_ids:
            return True
        sources = [source_by_id[source_id] for source_id in source_ids if source_id in source_by_id]
        if not sources:
            return True
        weak_types = {"web_search_result", "llm_public_knowledge"}
        return all(
            source.source_type in weak_types or source.confidence < 0.75
            for source in sources
        )

    def _claim_needs_triangulation(self, claim: str, source_ids: list[str]) -> bool:
        if len(set(source_ids)) >= 2:
            return False
        return bool(
            re.search(
                r"\b(best|better|leader|recommended|safest|cheapest|fastest|"
                r"enterprise-ready|soc\s*2|sso|saml|security|compliance)\b",
                claim,
                flags=re.IGNORECASE,
            )
        )

    def _reflection_gap_notes(self, detail: RunDetail) -> list[str]:
        if not detail.reflections:
            return []
        latest = detail.reflections[-1]
        return [
            *latest.coverage_gaps,
            *latest.confidence_outliers,
            *latest.cross_competitor_gaps,
        ]

    def _trim_sentence(self, value: str, limit: int = 220) -> str:
        text = " ".join(value.split())
        if len(text) <= limit:
            return text
        return f"{text[: limit - 1].rstrip()}..."

    def _markdown_table_cell(self, value: object, *, limit: int | None = None) -> str:
        text = " ".join(str(value or "").split())
        if limit is not None:
            text = self._trim_sentence(text, limit)
        return text.replace("|", "\\|") or "-"

    def _extract_cited_source_ids(self, report_md: str) -> set[str]:
        cited = set(source_tokens(report_md))
        for pattern in (
            r"(?<![-\w])source(?:\s+id)?\s*:\s*([A-Za-z0-9_.:-]+)",
            r"\[source(?:\s+id)?\s+([A-Za-z0-9_.:-]+)\]",
        ):
            cited.update(re.findall(pattern, report_md, flags=re.IGNORECASE))
        return cited

    def _repair_report_source_tokens(self, detail: RunDetail, markdown: str) -> str:
        valid_source_ids = {source.id for source in detail.raw_sources}
        if not valid_source_ids:
            return markdown

        repaired_lines: list[str] = []
        for line in markdown.splitlines():
            repaired_lines.append(
                SOURCE_TOKEN_RE.sub(
                    lambda match, current_line=line: self._repair_report_source_token(
                        detail,
                        current_line,
                        source_token_match_value(match),
                        valid_source_ids,
                    ),
                    line,
                )
            )
        return "\n".join(repaired_lines)

    def _repair_report_source_token(
        self,
        detail: RunDetail,
        line: str,
        token: str,
        valid_source_ids: set[str],
    ) -> str:
        source_id = token.split("#", 1)[0]
        if source_id in valid_source_ids:
            return f"[source:{token}]"

        dimension_match = [
            source.id
            for source in detail.raw_sources
            if source.dimension.casefold() == source_id.casefold()
        ]
        replacement_ids = dimension_match or self._source_ids_for_report_line(detail, line)
        if not replacement_ids:
            return f"[source:{token}]"
        return f"[source:{replacement_ids[0]}]"

    def _ensure_report_claim_citations(self, detail: RunDetail, markdown: str) -> str:
        hardened_lines: list[str] = []
        for line in markdown.splitlines():
            if not self._report_line_needs_citation(line):
                hardened_lines.append(line)
                continue
            if self._extract_cited_source_ids(line):
                hardened_lines.append(line)
                continue
            source_ids = self._source_ids_for_report_line(detail, line)
            if not source_ids:
                hardened_lines.append(line)
                continue
            citation_text = " ".join(f"[source:{source_id}]" for source_id in source_ids[:2])
            stripped = line.rstrip()
            if stripped.startswith("|") and stripped.endswith("|"):
                hardened_lines.append(f"{stripped[:-1].rstrip()} {citation_text} |")
            else:
                hardened_lines.append(f"{stripped} {citation_text}")
        return "\n".join(hardened_lines)

    def _report_line_needs_citation(self, line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return False
        if stripped.startswith("<!--") and "report-section:" in stripped:
            return False
        if stripped.startswith("|"):
            return False
        if stripped.startswith("#"):
            return False
        if set(stripped) <= {"-", " ", "|", ":"}:
            return False
        if re.fullmatch(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?", stripped):
            return False
        if self._report_line_is_explicit_gap_statement(stripped):
            return False
        if CJK_TEXT_RE.search(stripped):
            normalized = stripped.casefold()
            if len(stripped) >= 12 and any(
                token in normalized for token in CLAIM_LINE_TOKENS
            ):
                return True
        return bool(re.search(r"[A-Za-z0-9]", stripped)) and len(stripped) >= 24

    def _report_line_is_explicit_gap_statement(self, line: str) -> bool:
        normalized = line.casefold()
        return any(
            marker in normalized
            for marker in (
                "evidence gap",
                "no cited swot",
                "no cited item",
                "no cited user-review",
                "证据缺口",
                "尚无可引用",
            )
        )

    def _source_ids_for_report_line(self, detail: RunDetail, line: str) -> list[str]:
        normalized = line.casefold()
        matched_competitors = [
            competitor
            for competitor in detail.plan.competitors
            if competitor.casefold() in normalized
        ]
        matched_dimensions = [
            dimension
            for dimension in detail.plan.dimensions
            if dimension.casefold() in normalized
            or (
                dimension == "pricing"
                and any(token in normalized for token in PRICING_LINE_TOKENS)
            )
            or (
                dimension == "feature"
                and any(token in normalized for token in FEATURE_LINE_TOKENS)
            )
            or (
                dimension == "persona"
                and any(token in normalized for token in PERSONA_LINE_TOKENS)
            )
        ]

        def unique(ids: list[str]) -> list[str]:
            seen: set[str] = set()
            return [
                source_id for source_id in ids if not (source_id in seen or seen.add(source_id))
            ]

        source_dimensions = {source.id: source.dimension for source in detail.raw_sources}

        def rank_source_ids_by_dimension(ids: list[str], primary_dimension: str) -> list[str]:
            primary_ids = [
                source_id
                for source_id in ids
                if source_dimensions.get(source_id) == primary_dimension
            ]
            other_ids = [
                source_id
                for source_id in ids
                if source_dimensions.get(source_id) != primary_dimension
            ]
            return [*primary_ids, *other_ids]

        source_ids = [
            source.id
            for source in detail.raw_sources
            if (
                not matched_competitors
                or any(
                    self._source_matches_competitor(source, competitor)
                    for competitor in matched_competitors
                )
            )
            and (not matched_dimensions or source.dimension in matched_dimensions)
        ]
        if not source_ids and matched_competitors:
            source_ids = [
                source.id
                for source in detail.raw_sources
                if any(
                    self._source_matches_competitor(source, competitor)
                    for competitor in matched_competitors
                )
            ]
        if not source_ids and matched_dimensions:
            source_ids = [
                source.id for source in detail.raw_sources if source.dimension in matched_dimensions
            ]
        if not source_ids:
            source_ids = [source.id for source in detail.raw_sources]
        if "pricing" in matched_dimensions:
            source_ids = rank_source_ids_by_dimension(source_ids, "pricing")
        elif "feature" in matched_dimensions:
            source_ids = rank_source_ids_by_dimension(source_ids, "feature")
        if "persona" in matched_dimensions and not {
            "pricing",
            "feature",
        }.intersection(matched_dimensions):
            source_type_rank = {
                source_type: index
                for index, source_type in enumerate(USER_RESEARCH_SOURCE_TYPE_ORDER)
            }
            preferred_user_research_sources = [
                source
                for source in detail.raw_sources
                if source.id in source_ids and source.source_type in USER_RESEARCH_SOURCE_TYPES
            ]
            preferred_user_research_ids = [
                source.id
                for source in sorted(
                    preferred_user_research_sources,
                    key=lambda source: source_type_rank.get(
                        source.source_type, len(source_type_rank)
                    ),
                )
            ]
            if preferred_user_research_ids:
                source_ids = [*preferred_user_research_ids, *source_ids]
        return unique(source_ids)


def _publication_issues_from_segment(
    segment: Mapping[str, object],
) -> list[PublicationContractIssue]:
    raw_issues = segment.get("publication_repair_issues")
    if not isinstance(raw_issues, list):
        return []
    issues: list[PublicationContractIssue] = []
    for item in raw_issues:
        if not isinstance(item, Mapping):
            continue
        issues.append(
            PublicationContractIssue(
                code=str(item.get("code") or "publication_contract"),
                line_number=_safe_int(item.get("line_number")),
                message=str(item.get("message") or ""),
                repair_target="structured_section",
                excerpt=str(item.get("excerpt") or ""),
            )
        )
    return issues


def _section_key_at_line(sections: Sequence[object], line_number: int) -> str | None:
    current_key: str | None = None
    for section in sections:
        line_start = getattr(section, "line_start", 0)
        if line_start > line_number:
            break
        section_key = getattr(section, "section_key", None)
        if isinstance(section_key, str) and section_key:
            current_key = section_key
    return current_key


def _safe_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return 0
