from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from typing import Any

from packages.refs import merge_ordered_refs
from packages.schema.models import KnowledgeClaim, RawSource
from packages.schema.report_artifact import ClaimCard, ClaimCardBundle


def build_claim_card_bundle(
    *,
    run_id: str,
    competitor: str,
    dimension: str,
    claims: Sequence[KnowledgeClaim],
    sources: Sequence[RawSource],
    producer_stage: str,
) -> ClaimCardBundle:
    source_by_id = {source.id: source for source in sources}
    cards: list[ClaimCard] = []
    dropped_claims: list[dict[str, Any]] = []
    dimension_irrelevant_source_count = 0

    for claim_index, claim in enumerate(claims, start=1):
        available_source_ids = [
            source_id for source_id in claim.source_ids if source_id in source_by_id
        ]
        dimension_irrelevant_source_ids = [
            source_id
            for source_id in available_source_ids
            if not _source_relevant_to_dimension(source_by_id[source_id], dimension)
        ]
        dimension_irrelevant_source_count += len(dimension_irrelevant_source_ids)
        source_ids = merge_ordered_refs(
            source_id
            for source_id in available_source_ids
            if source_id not in set(dimension_irrelevant_source_ids)
        )
        dropped_source_ids = [
            source_id for source_id in claim.source_ids if source_id not in source_by_id
        ]
        dropped_source_ids = merge_ordered_refs(
            [*dropped_source_ids, *dimension_irrelevant_source_ids]
        )
        if not source_ids:
            dropped_claims.append(
                {
                    "claim": claim.claim,
                    "source_ids": list(claim.source_ids),
                    "dropped_source_ids": dropped_source_ids,
                }
            )
            cards.append(
                _unsupported_claim_gap_card(
                    run_id=run_id,
                    competitor=competitor,
                    dimension=dimension,
                    producer_stage=producer_stage,
                    claim=claim,
                    missing_source_ids=dropped_source_ids,
                    ordinal=claim_index,
                )
            )
            continue

        claim_sources = [source_by_id[source_id] for source_id in source_ids]
        support_level = _support_level_for_sources(claim_sources)
        evidence_strength = _evidence_strength_for_claim(claim, claim_sources)
        caveats: list[str] = []
        if dropped_source_ids:
            caveats.append(
                "Some cited source IDs were unavailable or out of scope for this dimension."
            )

        cards.append(
            ClaimCard(
                id=_claim_card_id(
                    run_id=run_id,
                    competitor=competitor,
                    dimension=dimension,
                    ordinal=claim_index,
                    claim=claim.claim,
                ),
                run_id=run_id,
                competitor=competitor,
                dimension=dimension,
                claim_type=_claim_type_for_dimension(dimension),
                claim=claim.claim,
                source_ids=source_ids,
                confidence=claim.confidence,
                evidence_strength=evidence_strength,
                support_level=support_level,
                scope=_scope_for_dimension(dimension),
                caveats=caveats,
                conflicts=[],
                applicability=f"{competitor} {dimension} analysis",
                produced_by="analyst",
                producer_stage=producer_stage,
                derived_from=source_ids,
                metadata={
                    "source_types": [
                        source.source_type for source in claim_sources if source.source_type
                    ],
                    "dropped_source_ids": dropped_source_ids,
                    "dimension_irrelevant_source_ids": dimension_irrelevant_source_ids,
                },
            )
        )

    represented_source_ids = {
        source_id for card in cards for source_id in card.source_ids
    }
    supplemental_cards = _supplemental_user_research_cards(
        run_id=run_id,
        competitor=competitor,
        dimension=dimension,
        producer_stage=producer_stage,
        sources=[
            source
            for source in sources
            if source.id not in represented_source_ids
            and _is_user_research_source(source)
        ],
        starting_ordinal=len(cards) + 1,
    )
    cards.extend(supplemental_cards)

    if not cards:
        cards.append(
            _gap_card(
                run_id=run_id,
                competitor=competitor,
                dimension=dimension,
                producer_stage=producer_stage,
                dropped_claims=dropped_claims,
            )
        )

    card_source_ids = merge_ordered_refs(
        source_id for card in cards for source_id in card.source_ids
    )
    gap_count = sum(1 for card in cards if card.support_level == "gap")
    return ClaimCardBundle(
        run_id=run_id,
        competitor=competitor,
        dimension=dimension,
        cards=cards,
        source_ids=card_source_ids,
        coverage={
            "claim_count": len(claims),
            "card_count": len(cards),
            "dropped_claim_count": len(dropped_claims),
            "provided_source_count": len(sources),
            "dimension_irrelevant_source_count": dimension_irrelevant_source_count,
        },
        gap_count=gap_count,
        producer_context={
            "producer_stage": producer_stage,
            "produced_by": "analyst",
        },
    )


def _supplemental_user_research_cards(
    *,
    run_id: str,
    competitor: str,
    dimension: str,
    producer_stage: str,
    sources: Sequence[RawSource],
    starting_ordinal: int,
) -> list[ClaimCard]:
    cards: list[ClaimCard] = []
    for offset, source in enumerate(sources):
        claim = _user_research_claim_from_source(competitor, source)
        source_ids = [source.id]
        claim_model = KnowledgeClaim(
            claim=claim,
            source_ids=source_ids,
            confidence=source.confidence,
        )
        cards.append(
            ClaimCard(
                id=_claim_card_id(
                    run_id=run_id,
                    competitor=competitor,
                    dimension=dimension,
                    ordinal=starting_ordinal + offset,
                    claim=claim,
                ),
                run_id=run_id,
                competitor=competitor,
                dimension=dimension,
                claim_type="user_research_signal",
                claim=claim,
                source_ids=source_ids,
                confidence=source.confidence,
                evidence_strength=_evidence_strength_for_claim(claim_model, [source]),
                support_level=_support_level_for_sources([source]),
                scope=_scope_for_dimension(dimension),
                caveats=_user_research_caveats(source),
                conflicts=[],
                applicability=f"{competitor} {dimension} user research",
                produced_by="analyst",
                producer_stage=producer_stage,
                derived_from=source_ids,
                metadata={
                    "supplemental_from_raw_source": True,
                    "source_type": source.source_type,
                    "source_role": source.metadata.get("source_role"),
                },
            )
        )
    return cards


def _user_research_claim_from_source(competitor: str, source: RawSource) -> str:
    evidence_text = _trim_text(source.snippet or source.title, limit=260)
    source_role = source.metadata.get("source_role")
    role_text = (
        str(source_role).replace("_", " ").strip()
        if isinstance(source_role, str) and source_role.strip()
        else source.source_type.replace("_", " ")
    )
    return f"{competitor} user research signal ({role_text}): {evidence_text}"


def _user_research_caveats(source: RawSource) -> list[str]:
    if _is_synthetic_source(source):
        return [
            "Synthetic user research; treat as directional interview/survey signal, not observed respondent evidence."
        ]
    return []


def _is_user_research_source(source: RawSource) -> bool:
    source_type = _normalized_source_type(source)
    source_role = source.metadata.get("source_role")
    source_role_text = source_role.casefold() if isinstance(source_role, str) else ""
    return (
        source.dimension.strip().casefold() in {"persona", "user", "users", "review"}
        and any(
            marker in source_type or marker in source_role_text
            for marker in (
                "survey",
                "interview",
                "manual_user",
                "manual_note",
                "manual_transcript",
                "review",
                "community",
                "forum",
                "reddit",
            )
        )
    )


def _unsupported_claim_gap_card(
    *,
    run_id: str,
    competitor: str,
    dimension: str,
    producer_stage: str,
    claim: KnowledgeClaim,
    missing_source_ids: list[str],
    ordinal: int,
) -> ClaimCard:
    clean_missing_source_ids = merge_ordered_refs(missing_source_ids)
    return ClaimCard(
        id=_claim_card_id(
            run_id=run_id,
            competitor=competitor,
            dimension=dimension,
            ordinal=ordinal,
            claim=f"unsupported:{claim.claim}",
        ),
        run_id=run_id,
        competitor=competitor,
        dimension=dimension,
        claim_type="evidence_gap",
        claim=claim.claim,
        source_ids=[],
        confidence=0.0,
        evidence_strength="insufficient",
        support_level="gap",
        scope=_scope_for_dimension(dimension),
        caveats=[
            "Claim cited source IDs that were missing or unavailable to the analyst bundle."
        ],
        conflicts=[],
        applicability=f"{competitor} {dimension} analysis",
        produced_by="analyst",
        producer_stage=producer_stage,
        derived_from=[],
        metadata={
            "missing_source_ids": clean_missing_source_ids,
            "dropped_source_ids": clean_missing_source_ids,
            "original_claim_confidence": claim.confidence,
        },
    )


def _gap_card(
    *,
    run_id: str,
    competitor: str,
    dimension: str,
    producer_stage: str,
    dropped_claims: list[dict[str, Any]],
) -> ClaimCard:
    missing_source_ids = merge_ordered_refs(
        source_id
        for dropped_claim in dropped_claims
        for source_id in dropped_claim.get("source_ids", [])
    )
    return ClaimCard(
        id=_claim_card_id(
            run_id=run_id,
            competitor=competitor,
            dimension=dimension,
            ordinal=1,
            claim="gap",
        ),
        run_id=run_id,
        competitor=competitor,
        dimension=dimension,
        claim_type="evidence_gap",
        claim=f"No supported {dimension} claims were produced for {competitor}.",
        source_ids=[],
        confidence=0.0,
        evidence_strength="insufficient",
        support_level="gap",
        scope=_scope_for_dimension(dimension),
        caveats=["No cited claims matched the available scoped sources."],
        conflicts=[],
        applicability=f"{competitor} {dimension} analysis",
        produced_by="analyst",
        producer_stage=producer_stage,
        derived_from=[],
        metadata={
            "dropped_claim_count": len(dropped_claims),
            "dropped_source_ids": missing_source_ids,
        },
    )


def _support_level_for_sources(sources: Sequence[RawSource]) -> str:
    source_types = [_normalized_source_type(source) for source in sources]
    if any(
        "simulated" in source_type or _is_synthetic_source(source)
        for source, source_type in zip(sources, source_types)
    ):
        return "simulated"
    if any(_is_official_source(source) for source in sources):
        return "official"
    community_source_count = sum(
        1 for source_type in source_types if _is_community_source_type(source_type)
    )
    if community_source_count >= 2:
        return "triangulated_community"
    return "single_source"


def _evidence_strength_for_claim(
    claim: KnowledgeClaim,
    sources: Sequence[RawSource],
) -> str:
    confidence = min(
        1.0,
        max(claim.confidence, *(source.confidence for source in sources), 0.0),
    )
    if confidence >= 0.85 and len(sources) >= 2:
        return "strong"
    if confidence >= 0.7:
        return "moderate"
    return "weak"


def _normalized_source_type(source: RawSource) -> str:
    metadata_source_type = source.metadata.get("community_source_type")
    if isinstance(metadata_source_type, str) and metadata_source_type.strip():
        return metadata_source_type.strip().casefold()
    return source.source_type.strip().casefold()


def _is_synthetic_source(source: RawSource) -> bool:
    return any(
        _metadata_truthy(source.metadata.get(key))
        for key in ("survey_interview_synthetic", "fallback_synthetic", "synthetic")
    )


def _metadata_truthy(value: object) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().casefold() == "true"
    return False


def _is_official_source(source: RawSource) -> bool:
    trusted_official = source.metadata.get("trusted_official")
    if trusted_official is True:
        return True
    if isinstance(trusted_official, str) and trusted_official.strip().casefold() == "true":
        return True
    return _is_official_source_type(source.source_type.strip().casefold())


def _is_official_source_type(source_type: str) -> bool:
    return (
        source_type == "official"
        or "official" in source_type
        or source_type in {"webpage_verified", "pricing_page", "docs"}
    )


def _is_community_source_type(source_type: str) -> bool:
    return any(
        marker in source_type
        for marker in ("community", "reddit", "forum", "github_issue", "discussion")
    )


def _source_relevant_to_dimension(source: RawSource, dimension: str) -> bool:
    dimension_key = dimension.casefold().strip()
    if "pricing" in dimension_key or "price" in dimension_key:
        return _source_has_pricing_evidence(source)
    return True


def _source_has_pricing_evidence(source: RawSource) -> bool:
    normalized_fields = source.metadata.get("normalized_fields")
    if _normalized_fields_include_pricing(normalized_fields):
        return True
    high_signal_text = " ".join(
        str(value or "")
        for value in (
            source.title,
            source.url,
            source.metadata.get("canonical_url"),
            source.metadata.get("source_role"),
        )
    ).casefold()
    if any(
        token in high_signal_text
        for token in (
            "pricing",
            "price",
            "plans",
            "plan",
            "billing",
            "usage",
            "cost",
            "costs",
        )
    ):
        return True
    snippet = (source.snippet or "").casefold()
    has_money_or_unit = bool(
        re.search(
            r"([$€£]\s?\d|\b\d+\s?(?:usd|eur|gbp|credits?|tokens?)\b|/mo\b|per month|monthly|yearly|annually)",
            snippet,
        )
    )
    has_pricing_context = any(
        token in snippet
        for token in (
            "pricing",
            "price",
            "plan",
            "billing",
            "cost",
            "credit",
            "usage",
            "subscription",
            "monthly",
            "yearly",
            "month",
            "user",
        )
    )
    return has_money_or_unit and has_pricing_context


def _normalized_fields_include_pricing(value: object) -> bool:
    if value is None:
        return False
    text = repr(value).casefold()
    return any(
        token in text
        for token in (
            "price",
            "pricing",
            "price_point",
            "billing",
            "cost",
            "credit",
            "plan",
            "tier",
        )
    )


def _claim_type_for_dimension(dimension: str) -> str:
    dimension_key = _slug(dimension)
    if "pricing" in dimension.casefold():
        return "pricing_fact"
    if "persona" in dimension.casefold() or "user" in dimension.casefold():
        return "persona_claim"
    return f"{dimension_key}_claim" if dimension_key else "dimension_claim"


def _scope_for_dimension(dimension: str) -> str:
    clean_dimension = " ".join(dimension.split()) or "dimension"
    return f"current {clean_dimension} analysis"


def _claim_card_id(
    *,
    run_id: str,
    competitor: str,
    dimension: str,
    ordinal: int,
    claim: str,
) -> str:
    basis = "|".join((run_id, competitor, dimension, str(ordinal), claim))
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:10]
    return f"claim-{_slug(competitor)}-{_slug(dimension)}-{ordinal}-{digest}"


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().casefold()).strip("-")
    return slug or "unknown"


def _trim_text(value: str, *, limit: int) -> str:
    text = " ".join((value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1].rstrip()}..."


__all__ = ["build_claim_card_bundle"]
