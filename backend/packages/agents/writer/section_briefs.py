from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Literal

from packages.schema.api_dto import RunDetail
from packages.schema.models import RawSource
from packages.schema.report_artifact import ClaimCard, DecisionCard, SectionBrief

SCHEMA_VERSION = "writer_section_brief.v1"

CoreSectionKey = Literal[
    "decision_summary",
    "review_theme_summary",
    "competitor_deep_dives",
    "side_by_side_matrix",
    "swot_analysis",
    "battlecard",
    "workflow_enterprise_risk",
    "market_landscape",
    "business_implications",
]

_LAYER_SECTION_BY_LAYER = {
    "L1": "battlecard",
    "L2": "workflow_enterprise_risk",
    "L3": "market_landscape",
    "unknown": "business_implications",
}

_SECTION_DECISION_TYPES: dict[str, tuple[str, ...]] = {
    "decision_summary": (
        "overall_recommendation",
        "risk_adjusted_recommendation",
        "dimension_winner",
        "why_not",
    ),
    "review_theme_summary": (),
    "competitor_deep_dives": ("dimension_winner",),
    "side_by_side_matrix": (
        "dimension_winner",
        "overall_recommendation",
        "risk_adjusted_recommendation",
    ),
    "swot_analysis": ("swot_interpretation",),
    "battlecard": ("battlecard_position", "why_not"),
    "workflow_enterprise_risk": ("risk_adjusted_recommendation", "why_not"),
    "market_landscape": ("dimension_winner", "risk_adjusted_recommendation"),
    "business_implications": (
        "overall_recommendation",
        "risk_adjusted_recommendation",
    ),
}

_SUPPORT_NO_NEW_RECOMMENDATIONS_RULE = (
    "Do not add new business recommendations in support/audit material; only explain "
    "evidence coverage, confidence, gaps, and provenance for recommendations already "
    "made in core sections."
)

_USER_RESEARCH_TOKENS = (
    "persona",
    "user",
    "review",
    "community",
    "survey",
    "interview",
    "customer",
    "adoption",
    "feedback",
)
_USER_RESEARCH_SOURCE_TYPES = (
    "survey",
    "interview",
    "manual_user",
    "manual_note",
    "community",
    "forum",
    "review",
)
_BUSINESS_CLAIM_TOKENS = (
    "pricing",
    "price",
    "packaging",
    "feature",
    "capability",
    "product",
    "workflow",
    "security",
    "enterprise",
    "market",
    "integration",
)


def build_section_briefs(detail: RunDetail) -> list[SectionBrief]:
    claim_cards = _claim_cards(detail)
    decision_cards = _decision_cards(detail)
    raw_sources_by_id = {source.id: source for source in detail.raw_sources}
    all_claim_ids = [card.id for card in claim_cards]
    all_decision_ids = [card.id for card in decision_cards]
    all_source_ids = _all_source_ids(
        detail,
        claim_cards,
        decision_cards,
        raw_sources_by_id=raw_sources_by_id,
    )

    briefs: list[SectionBrief] = []
    for section_key in _core_section_keys(detail):
        section_decisions = _decisions_for_section(section_key, decision_cards)
        decision_ids = [card.id for card in section_decisions]
        claim_ids = _claim_ids_for_section(
            section_key,
            claim_cards,
            section_decisions,
            raw_sources_by_id=raw_sources_by_id,
            plan_dimensions=detail.plan.dimensions,
        )
        source_ids = _source_ids_for_section(
            section_key,
            detail,
            claim_cards=claim_cards,
            decision_cards=section_decisions,
            claim_ids=claim_ids,
            raw_sources_by_id=raw_sources_by_id,
        )
        must_include = _must_include(section_key)
        if not claim_ids and not decision_ids:
            must_include.append(
                "No section-relevant card scope is available; write an explicit "
                "evidence gap instead of using out-of-scope cards."
            )
        briefs.append(
            SectionBrief(
                id=f"brief-{section_key}",
                section_key=section_key,
                layer="core",
                required_questions=_required_questions(section_key),
                allowed_claim_card_ids=claim_ids,
                allowed_decision_card_ids=decision_ids,
                allowed_source_ids=source_ids,
                must_include=must_include,
                must_not_claim=[
                    "Do not cite or rely on claim, decision, or source IDs outside this brief.",
                    "Do not convert evidence gaps into factual claims.",
                ],
                tone="executive" if section_key == "decision_summary" else "analytical",
                minimum_depth=_minimum_depth(section_key),
                citation_policy={
                    "mode": "card_scoped",
                    "allowed_source_ids_only": True,
                },
                repair_targets={
                    "section_key": section_key,
                    "artifact_layer": "core",
                    "scoped_card_status": (
                        "empty" if not claim_ids and not decision_ids else "scoped"
                    ),
                },
            )
        )

    for section_key, layer in (("evidence_support", "support"),):
        briefs.append(
            SectionBrief(
                id=f"brief-{section_key}",
                section_key=section_key,
                layer=layer,
                required_questions=_required_questions(section_key),
                allowed_claim_card_ids=list(all_claim_ids),
                allowed_decision_card_ids=list(all_decision_ids),
                allowed_source_ids=list(all_source_ids),
                must_include=_must_include(section_key),
                must_not_claim=[_SUPPORT_NO_NEW_RECOMMENDATIONS_RULE],
                tone="audit",
                minimum_depth={"paragraphs": 1, "coverage": "concise"},
                citation_policy={
                    "mode": "all_cards_all_sources",
                    "allowed_source_ids_only": True,
                },
                repair_targets={
                    "section_key": section_key,
                    "artifact_layer": layer,
                    "audit_intent": (
                        "Task 4 renders audit-like provenance in support; Task 5 "
                        "will split audit artifacts."
                    ),
                },
            )
        )

    return briefs


def segment_payloads_from_briefs(
    detail: RunDetail,
    briefs: Sequence[SectionBrief],
) -> list[dict[str, object]]:
    claim_cards_by_id = {card.id: card for card in _claim_cards(detail)}
    decision_cards_by_id = {card.id: card for card in _decision_cards(detail)}
    raw_sources_by_id = {source.id: source for source in detail.raw_sources}
    payloads: list[dict[str, object]] = []
    for brief in briefs:
        if brief.section_key == "competitor_deep_dives":
            payloads.extend(
                _competitor_deep_dive_payloads(
                    detail,
                    brief,
                    claim_cards_by_id=claim_cards_by_id,
                    decision_cards_by_id=decision_cards_by_id,
                    raw_sources_by_id=raw_sources_by_id,
                )
            )
            continue
        payloads.append(
            _section_payload_from_brief(
                detail,
                brief,
                claim_cards_by_id=claim_cards_by_id,
                decision_cards_by_id=decision_cards_by_id,
                raw_sources_by_id=raw_sources_by_id,
            )
        )
    return payloads


def _section_payload_from_brief(
    detail: RunDetail,
    brief: SectionBrief,
    *,
    claim_cards_by_id: Mapping[str, ClaimCard],
    decision_cards_by_id: Mapping[str, DecisionCard],
    raw_sources_by_id: Mapping[str, RawSource],
    segment_name: str | None = None,
    segment_competitor: str | None = None,
    allowed_claim_card_ids: Sequence[str] | None = None,
    allowed_decision_card_ids: Sequence[str] | None = None,
    allowed_source_ids: Sequence[str] | None = None,
) -> dict[str, object]:
    source_id_scope = brief.allowed_source_ids if allowed_source_ids is None else allowed_source_ids
    claim_id_scope = (
        brief.allowed_claim_card_ids if allowed_claim_card_ids is None else allowed_claim_card_ids
    )
    decision_id_scope = (
        brief.allowed_decision_card_ids
        if allowed_decision_card_ids is None
        else allowed_decision_card_ids
    )
    scoped_source_ids = [
        source_id for source_id in source_id_scope if source_id in raw_sources_by_id
    ]
    scoped_claim_ids = list(claim_id_scope)
    scoped_decision_ids = list(decision_id_scope)
    segment_kind = "section_fragment" if brief.layer == "core" else "support_fragment"
    section_brief = brief.model_copy(
        update={
            "allowed_claim_card_ids": scoped_claim_ids,
            "allowed_decision_card_ids": scoped_decision_ids,
            "allowed_source_ids": scoped_source_ids,
        }
    )
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "segment_name": segment_name or brief.section_key,
        "segment_kind": segment_kind,
        "section_id": brief.section_key,
        "section_key": brief.section_key,
        "layer": brief.layer,
        "output_language": detail.output_language,
        "segment_essential": brief.layer == "core",
        "allowed_source_ids": scoped_source_ids,
        "allowed_claim_card_ids": scoped_claim_ids,
        "allowed_decision_card_ids": scoped_decision_ids,
        "section_brief": section_brief.model_dump(mode="json"),
        "schema_contract_source": "section_brief",
        "claim_cards": [
            _claim_card_payload(
                claim_cards_by_id[claim_id],
                allowed_source_ids=set(scoped_source_ids),
            )
            for claim_id in scoped_claim_ids
            if claim_id in claim_cards_by_id
        ],
        "decision_cards": [
            _decision_card_payload(
                decision_cards_by_id[decision_id],
                allowed_source_ids=set(scoped_source_ids),
            )
            for decision_id in scoped_decision_ids
            if decision_id in decision_cards_by_id
        ],
        "source_registry": [
            _raw_source_payload(raw_sources_by_id[source_id])
            for source_id in scoped_source_ids
            if source_id in raw_sources_by_id
        ],
        "groups": [],
    }
    if segment_competitor:
        payload["segment_competitor"] = segment_competitor
    if brief.section_key == "decision_summary":
        payload["require_executive_summary"] = True
    _refresh_segment_input_chars(payload)
    return payload


def _competitor_deep_dive_payloads(
    detail: RunDetail,
    brief: SectionBrief,
    *,
    claim_cards_by_id: Mapping[str, ClaimCard],
    decision_cards_by_id: Mapping[str, DecisionCard],
    raw_sources_by_id: Mapping[str, RawSource],
) -> list[dict[str, object]]:
    competitors = _competitors(detail)
    if not competitors:
        return [
            _section_payload_from_brief(
                detail,
                brief,
                claim_cards_by_id=claim_cards_by_id,
                decision_cards_by_id=decision_cards_by_id,
                raw_sources_by_id=raw_sources_by_id,
            )
        ]
    payloads: list[dict[str, object]] = []
    allowed_source_id_set = set(brief.allowed_source_ids)
    for competitor in competitors:
        claim_ids = [
            claim_id
            for claim_id in brief.allowed_claim_card_ids
            if claim_id in claim_cards_by_id
            and _claim_matches_competitor(claim_cards_by_id[claim_id], competitor)
        ]
        source_ids = _unique(
            [
                *[
                    source_id
                    for claim_id in claim_ids
                    for source_id in claim_cards_by_id[claim_id].source_ids
                ],
                *[
                    source_id
                    for source_id, source in raw_sources_by_id.items()
                    if source_id in allowed_source_id_set
                    and _source_matches_competitor(source, competitor)
                    and _source_dimension_in_plan(source, detail.plan.dimensions)
                ],
            ]
        )
        decision_ids = [
            decision_id
            for decision_id in brief.allowed_decision_card_ids
            if decision_id in decision_cards_by_id
            and _decision_matches_competitor(
                decision_cards_by_id[decision_id],
                competitor,
                claim_cards_by_id=claim_cards_by_id,
            )
        ]
        payloads.append(
            _section_payload_from_brief(
                detail,
                brief,
                claim_cards_by_id=claim_cards_by_id,
                decision_cards_by_id=decision_cards_by_id,
                raw_sources_by_id=raw_sources_by_id,
                segment_name=f"{brief.section_key} {competitor}",
                segment_competitor=competitor,
                allowed_claim_card_ids=claim_ids,
                allowed_decision_card_ids=decision_ids,
                allowed_source_ids=source_ids,
            )
        )
    return payloads


def _core_section_keys(detail: RunDetail) -> list[CoreSectionKey]:
    layer_section = _LAYER_SECTION_BY_LAYER.get(
        detail.plan.competitor_layer,
        "business_implications",
    )
    return _unique(
        [
            "decision_summary",
            "review_theme_summary",
            "competitor_deep_dives",
            "side_by_side_matrix",
            "swot_analysis",
            layer_section,
        ]
    )


def _claim_cards(detail: RunDetail) -> list[ClaimCard]:
    cards: list[ClaimCard] = []
    seen: set[str] = set()
    for bundle in detail.claim_card_bundles:
        for card in bundle.cards:
            if card.id in seen:
                continue
            cards.append(card)
            seen.add(card.id)
    return cards


def _decision_cards(detail: RunDetail) -> list[DecisionCard]:
    if detail.decision_card_bundle is None:
        return []
    cards: list[DecisionCard] = []
    seen: set[str] = set()
    for card in detail.decision_card_bundle.cards:
        if card.id in seen:
            continue
        cards.append(card)
        seen.add(card.id)
    return cards


def _decisions_for_section(
    section_key: str,
    decision_cards: Sequence[DecisionCard],
) -> list[DecisionCard]:
    decision_types = set(_SECTION_DECISION_TYPES.get(section_key, ()))
    if not decision_types:
        return []
    return [card for card in decision_cards if card.decision_type in decision_types]


def _claim_ids_for_section(
    section_key: str,
    claim_cards: Sequence[ClaimCard],
    section_decisions: Sequence[DecisionCard],
    *,
    raw_sources_by_id: Mapping[str, RawSource],
    plan_dimensions: Sequence[str],
) -> list[str]:
    section_claim_ids = [
        card.id
        for card in _claims_for_section(
            section_key,
            claim_cards,
            raw_sources_by_id=raw_sources_by_id,
            plan_dimensions=plan_dimensions,
        )
    ]
    decision_claim_ids = [
        claim_id for decision in section_decisions for claim_id in decision.claim_card_ids
    ]
    return _unique([*section_claim_ids, *decision_claim_ids])


def _all_source_ids(
    detail: RunDetail,
    claim_cards: Sequence[ClaimCard],
    decision_cards: Sequence[DecisionCard],
    *,
    raw_sources_by_id: Mapping[str, RawSource],
) -> list[str]:
    raw_source_ids = set(raw_sources_by_id)
    return _unique(
        source_id
        for source_id in [
            *[source_id for card in claim_cards for source_id in card.source_ids],
            *[source_id for bundle in detail.claim_card_bundles for source_id in bundle.source_ids],
            *[source_id for card in decision_cards for source_id in card.source_ids],
            *[source.id for source in detail.raw_sources],
        ]
        if source_id in raw_source_ids
    )


def _source_ids_for_scope(
    *,
    claim_cards: Sequence[ClaimCard],
    decision_cards: Sequence[DecisionCard],
    claim_ids: Sequence[str],
    raw_source_ids: set[str],
) -> list[str]:
    claim_id_set = set(claim_ids)
    source_ids = _unique(
        source_id
        for source_id in [
            *[
                source_id
                for card in claim_cards
                if card.id in claim_id_set
                for source_id in card.source_ids
            ],
            *[source_id for card in decision_cards for source_id in card.source_ids],
        ]
        if source_id in raw_source_ids
    )
    return source_ids


def _source_ids_for_section(
    section_key: str,
    detail: RunDetail,
    *,
    claim_cards: Sequence[ClaimCard],
    decision_cards: Sequence[DecisionCard],
    claim_ids: Sequence[str],
    raw_sources_by_id: Mapping[str, RawSource],
) -> list[str]:
    source_ids = _source_ids_for_scope(
        claim_cards=claim_cards,
        decision_cards=decision_cards,
        claim_ids=claim_ids,
        raw_source_ids=set(raw_sources_by_id),
    )
    if section_key != "competitor_deep_dives":
        return source_ids
    return _unique(
        [
            *source_ids,
            *[
                source.id
                for source in raw_sources_by_id.values()
                if _source_matches_plan_competitors(source, detail)
                and _source_dimension_in_plan(source, detail.plan.dimensions)
            ],
        ]
    )


def _claims_for_section(
    section_key: str,
    claim_cards: Sequence[ClaimCard],
    *,
    raw_sources_by_id: Mapping[str, RawSource],
    plan_dimensions: Sequence[str],
) -> list[ClaimCard]:
    if section_key == "review_theme_summary":
        return [
            card
            for card in claim_cards
            if _is_user_research_claim(card, raw_sources_by_id=raw_sources_by_id)
        ]
    return [
        card for card in claim_cards if _is_business_claim(card, plan_dimensions=plan_dimensions)
    ]


def _is_user_research_claim(
    card: ClaimCard,
    *,
    raw_sources_by_id: Mapping[str, RawSource],
) -> bool:
    text = _claim_search_text(card)
    if any(token in text for token in _USER_RESEARCH_TOKENS):
        return True
    for source_id in card.source_ids:
        source = raw_sources_by_id.get(source_id)
        if source is None:
            continue
        source_text = " ".join(
            (
                source.source_type,
                source.dimension,
                source.title,
                source.snippet,
            )
        ).casefold()
        if any(token in source_text for token in _USER_RESEARCH_TOKENS):
            return True
        if any(token in source.source_type.casefold() for token in _USER_RESEARCH_SOURCE_TYPES):
            return True
    return False


def _is_business_claim(
    card: ClaimCard,
    *,
    plan_dimensions: Sequence[str],
) -> bool:
    if card.support_level == "gap":
        return False
    text = _claim_search_text(card)
    dimension_tokens = [
        dimension.casefold()
        for dimension in plan_dimensions
        if isinstance(dimension, str) and dimension.strip()
    ]
    return any(token in text for token in (*dimension_tokens, *_BUSINESS_CLAIM_TOKENS))


def _claim_search_text(card: ClaimCard) -> str:
    return " ".join(
        (
            card.dimension,
            card.claim_type,
            card.claim,
            card.scope,
            card.applicability,
            " ".join(card.caveats),
            " ".join(card.conflicts),
        )
    ).casefold()


def _competitors(detail: RunDetail) -> list[str]:
    return _unique(detail.plan.competitors)


def _claim_matches_competitor(card: ClaimCard, competitor: str) -> bool:
    return _same_name(card.competitor, competitor)


def _decision_matches_competitor(
    card: DecisionCard,
    competitor: str,
    *,
    claim_cards_by_id: Mapping[str, ClaimCard],
) -> bool:
    if card.winner and _same_name(card.winner, competitor):
        return True
    return any(
        claim_id in claim_cards_by_id
        and _claim_matches_competitor(claim_cards_by_id[claim_id], competitor)
        for claim_id in card.claim_card_ids
    )


def _source_matches_plan_competitors(source: RawSource, detail: RunDetail) -> bool:
    return any(
        _source_matches_competitor(source, competitor) for competitor in _competitors(detail)
    )


def _source_matches_competitor(source: RawSource, competitor: str) -> bool:
    if _same_name(source.competitor, competitor):
        return True
    return any(_same_name(name, competitor) for name in source.covered_competitors)


def _source_dimension_in_plan(source: RawSource, dimensions: Sequence[str]) -> bool:
    dimension_names = {
        dimension.casefold().strip()
        for dimension in dimensions
        if isinstance(dimension, str) and dimension.strip()
    }
    if not dimension_names or not source.dimension:
        return True
    return source.dimension.casefold().strip() in dimension_names


def _same_name(value: str | None, expected: str) -> bool:
    if not value or not expected:
        return False
    return value.casefold().strip() == expected.casefold().strip()


def _required_questions(section_key: str) -> list[str]:
    questions = {
        "decision_summary": [
            "What should the buyer or strategy owner do, and how confident is that recommendation?",
            "Which competitors, risks, and evidence boundaries most affect the decision?",
        ],
        "review_theme_summary": [
            "What user, community, survey, interview, or persona themes materially "
            "affect adoption?",
            "Which themes are direct evidence versus simulated or inferred signals?",
        ],
        "competitor_deep_dives": [
            "What does each competitor do well, where are the gaps, and what "
            "evidence supports those claims?",
        ],
        "side_by_side_matrix": [
            "How do competitors compare across the requested decision dimensions?",
        ],
        "swot_analysis": [
            "What strengths, weaknesses, opportunities, and threats follow from the scoped cards?",
        ],
        "battlecard": [
            "What attack points, rebuttals, best-fit scenarios, and proof gaps "
            "should sales or strategy use?",
        ],
        "workflow_enterprise_risk": [
            "Which workflow overlaps and enterprise risks change adoption or procurement posture?",
        ],
        "market_landscape": [
            "What category structure, strategic clusters, and trend uncertainties matter?",
        ],
        "business_implications": [
            "What operating decisions or validation tasks follow from the evidence?",
        ],
        "evidence_support": [
            "What source coverage, confidence limits, gaps, and evidence risks "
            "should the reader audit?",
        ],
        "generation_notes": [
            "What card and source scope constrained this report generation?",
        ],
    }
    return list(
        questions.get(
            section_key,
            ["Answer the section contract using only scoped cards and sources."],
        )
    )


def _must_include(section_key: str) -> list[str]:
    includes = {
        "decision_summary": [
            "Executive summary heading plus decision summary and competitive findings headings.",
            "Recommendation posture, confidence, and risk boundary.",
        ],
        "review_theme_summary": [
            "User/community themes and evidence gaps separated from unsupported claims.",
        ],
        "competitor_deep_dives": [
            "Competitor-specific analysis tied to allowed claim cards.",
        ],
        "side_by_side_matrix": [
            "A cited comparison across requested dimensions.",
        ],
        "swot_analysis": [
            "Strengths, weaknesses, opportunities, and threats for relevant competitors.",
        ],
        "battlecard": [
            "Attack point, defense/rebuttal, best-fit buyer, and proof needed.",
        ],
        "workflow_enterprise_risk": [
            "Workflow overlap, enterprise buying risk, and switching controls.",
        ],
        "market_landscape": [
            "Category segments, strategic clusters, and trend uncertainty.",
        ],
        "business_implications": [
            "Decision implications, operating risks, and next validation tasks.",
        ],
        "evidence_support": [
            "Source quality, coverage, confidence, claim risk, and next collection notes.",
        ],
        "generation_notes": [
            "Brief/card/source scope and any generation caveats.",
        ],
    }
    return list(includes.get(section_key, ()))


def _minimum_depth(section_key: str) -> dict[str, object]:
    if section_key == "decision_summary":
        return {"paragraphs": 3, "requires_executive_summary": True}
    if section_key in {"side_by_side_matrix", "swot_analysis"}:
        return {"paragraphs": 2, "requires_structured_comparison": True}
    return {"paragraphs": 2}


def _claim_card_payload(
    card: ClaimCard,
    *,
    allowed_source_ids: set[str],
) -> dict[str, object]:
    return {
        "id": card.id,
        "competitor": card.competitor,
        "dimension": card.dimension,
        "claim_type": card.claim_type,
        "claim": card.claim,
        "source_ids": [
            source_id for source_id in card.source_ids if source_id in allowed_source_ids
        ],
        "confidence": card.confidence,
        "evidence_strength": card.evidence_strength,
        "support_level": card.support_level,
        "scope": card.scope,
        "caveats": list(card.caveats),
        "conflicts": list(card.conflicts),
        "applicability": card.applicability,
    }


def _decision_card_payload(
    card: DecisionCard,
    *,
    allowed_source_ids: set[str],
) -> dict[str, object]:
    return {
        "id": card.id,
        "decision_type": card.decision_type,
        "subject": card.subject,
        "recommendation": card.recommendation,
        "posture": card.posture,
        "rationale": card.rationale,
        "claim_card_ids": list(card.claim_card_ids),
        "source_ids": [
            source_id for source_id in card.source_ids if source_id in allowed_source_ids
        ],
        "winner": card.winner,
        "alternatives": list(card.alternatives),
        "why_not": dict(card.why_not),
        "risk_factors": list(card.risk_factors),
        "evidence_strength": card.evidence_strength,
        "confidence": card.confidence,
    }


def _raw_source_payload(source: RawSource) -> dict[str, object]:
    return {
        "id": source.id,
        "competitor": source.competitor,
        "covered_competitors": list(source.covered_competitors),
        "dimension": source.dimension,
        "source_type": source.source_type,
        "title": source.title,
        "url": str(source.url) if source.url else None,
        "snippet": source.snippet,
        "confidence": source.confidence,
        "quality_score": source.quality_score,
    }


def _refresh_segment_input_chars(payload: dict[str, object]) -> None:
    payload["segment_input_chars"] = 0
    while True:
        size = len(json.dumps(payload, ensure_ascii=False))
        if payload["segment_input_chars"] == size:
            return
        payload["segment_input_chars"] = size


def _unique(values: Iterable[str] | Sequence[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        text = value.strip()
        if not text or text in seen:
            continue
        result.append(text)
        seen.add(text)
    return result


__all__ = ["build_section_briefs", "segment_payloads_from_briefs"]
