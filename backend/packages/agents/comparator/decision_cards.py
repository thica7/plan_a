from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Any

from packages.refs import merge_ordered_refs
from packages.schema.models import ComparisonCell, ComparisonMatrix
from packages.schema.report_artifact import (
    ClaimCard,
    ClaimCardBundle,
    DecisionCard,
    DecisionCardBundle,
)


_EVIDENCE_RANK = {
    "insufficient": 0,
    "weak": 1,
    "moderate": 2,
    "strong": 3,
}
_EVIDENCE_BY_RANK = {value: key for key, value in _EVIDENCE_RANK.items()}
_FALLBACK_CONFIDENCE_CAP = 0.74


def build_decision_card_bundle(
    *,
    run_id: str,
    claim_bundles: Sequence[ClaimCardBundle],
    matrix: ComparisonMatrix,
    fallback_used: bool,
) -> DecisionCardBundle:
    supported_claims_by_key = _supported_claims_by_key(claim_bundles)
    cell_by_key = {(cell.dimension, cell.competitor): cell for cell in matrix.cells}
    cards: list[DecisionCard] = []

    for dimension in matrix.dimensions:
        winner = matrix.winner_by_dimension.get(dimension)
        if not winner or winner.casefold() == "tie":
            continue
        claims = supported_claims_by_key.get((winner, dimension), [])
        if not claims:
            continue
        cards.append(
            _dimension_winner_card(
                run_id=run_id,
                dimension=dimension,
                winner=winner,
                competitors=matrix.competitors,
                claims=claims,
                cell=cell_by_key.get((dimension, winner)),
                fallback_used=fallback_used,
            )
        )

    winner_counts = _winner_counts(cards)
    recommendation_card_id: str | None = None
    overall = _overall_recommendation_card(
        run_id=run_id,
        matrix=matrix,
        dimension_cards=cards,
        winner_counts=winner_counts,
        fallback_used=fallback_used,
    )
    if overall is not None:
        recommendation_card_id = overall.id
        cards.append(overall)

    return DecisionCardBundle(
        run_id=run_id,
        cards=cards,
        matrix_snapshot=matrix.model_dump(mode="json"),
        coverage_by_dimension=_coverage_by_dimension(
            matrix=matrix,
            supported_claims_by_key=supported_claims_by_key,
        ),
        recommendation_card_id=recommendation_card_id,
        producer_context={
            "produced_by": "comparator",
            "producer_stage": "comparator",
            "fallback_used": fallback_used,
            "overall_winner_counts": dict(winner_counts),
            "overall_winner_tie": _has_top_count_tie(winner_counts),
            "overall_winner_split": _has_winner_split(winner_counts),
        },
    )


def _dimension_winner_card(
    *,
    run_id: str,
    dimension: str,
    winner: str,
    competitors: Sequence[str],
    claims: Sequence[ClaimCard],
    cell: ComparisonCell | None,
    fallback_used: bool,
) -> DecisionCard:
    claim_card_ids = [claim.id for claim in claims]
    source_ids = merge_ordered_refs(source_id for claim in claims for source_id in claim.source_ids)
    evidence_strength = _aggregate_evidence_strength(claims)
    confidence = _cap_confidence(
        _decision_confidence(claims, cell),
        fallback_used=fallback_used,
    )
    posture = _posture_for_decision(
        evidence_strength=evidence_strength,
        confidence=confidence,
        fallback_used=fallback_used,
    )
    alternatives = [competitor for competitor in competitors if competitor != winner]
    rationale = (
        f"{winner} is the supported winner for {dimension} based on "
        f"{len(claim_card_ids)} analyst claim card"
        f"{'' if len(claim_card_ids) == 1 else 's'}."
    )
    return DecisionCard(
        id=_decision_card_id(run_id, "dimension_winner", dimension, winner),
        run_id=run_id,
        decision_type="dimension_winner",
        subject=dimension,
        recommendation=f"Prefer {winner} for {dimension}.",
        posture=posture,
        rationale=rationale,
        claim_card_ids=claim_card_ids,
        source_ids=source_ids,
        winner=winner,
        alternatives=alternatives,
        why_not={
            competitor: f"No supported {dimension} win over {winner}."
            for competitor in alternatives
        },
        risk_factors=_risk_factors(
            evidence_strength=evidence_strength,
            fallback_used=fallback_used,
            source_count=len(source_ids),
        ),
        evidence_strength=evidence_strength,
        confidence=confidence,
        produced_by="comparator",
        producer_stage="comparator",
        metadata={
            "dimension": dimension,
            "fallback_used": fallback_used,
            "matrix_cell_confidence": cell.confidence if cell is not None else None,
        },
    )


def _overall_recommendation_card(
    *,
    run_id: str,
    matrix: ComparisonMatrix,
    dimension_cards: Sequence[DecisionCard],
    winner_counts: Counter[str],
    fallback_used: bool,
) -> DecisionCard | None:
    supported_cards = [card for card in dimension_cards if card.claim_card_ids]
    if not supported_cards:
        return None

    winner = _single_supported_winner(winner_counts)
    if winner is None:
        return None

    supporting_cards = [card for card in supported_cards if card.winner == winner]
    claim_card_ids = merge_ordered_refs(
        claim_card_id for card in supporting_cards for claim_card_id in card.claim_card_ids
    )
    if not claim_card_ids:
        return None

    source_ids = merge_ordered_refs(
        source_id for card in supporting_cards for source_id in card.source_ids
    )
    evidence_strength = _overall_evidence_strength(supporting_cards)
    confidence = _cap_confidence(
        _average(card.confidence for card in supporting_cards),
        fallback_used=fallback_used,
    )
    posture = _overall_posture_for_decision(
        supporting_cards=supporting_cards,
        evidence_strength=evidence_strength,
        confidence=confidence,
        fallback_used=fallback_used,
    )
    supported_dimensions = [card.subject for card in supporting_cards]
    alternatives = [competitor for competitor in matrix.competitors if competitor != winner]

    return DecisionCard(
        id=_decision_card_id(run_id, "overall_recommendation", "overall", winner),
        run_id=run_id,
        decision_type="overall_recommendation",
        subject="overall",
        recommendation=(
            f"Use {winner} as the leading recommendation across "
            f"{', '.join(supported_dimensions)}."
        ),
        posture=posture,
        rationale=(
            f"{winner} has supported comparator wins in "
            f"{len(supported_dimensions)} dimension"
            f"{'' if len(supported_dimensions) == 1 else 's'}."
        ),
        claim_card_ids=claim_card_ids,
        source_ids=source_ids,
        winner=winner,
        alternatives=alternatives,
        why_not={
            competitor: f"{winner} has stronger supported decision-card coverage."
            for competitor in alternatives
        },
        risk_factors=_risk_factors(
            evidence_strength=evidence_strength,
            fallback_used=fallback_used,
            source_count=len(source_ids),
        ),
        evidence_strength=evidence_strength,
        confidence=confidence,
        produced_by="comparator",
        producer_stage="comparator",
        metadata={
            "supported_dimensions": supported_dimensions,
            "fallback_used": fallback_used,
            "dimension_card_ids": [card.id for card in supporting_cards],
        },
    )


def _supported_claims_by_key(
    claim_bundles: Sequence[ClaimCardBundle],
) -> dict[tuple[str, str], list[ClaimCard]]:
    claims_by_key: dict[tuple[str, str], list[ClaimCard]] = {}
    for bundle in claim_bundles:
        for card in bundle.cards:
            if card.support_level == "gap" or not card.source_ids:
                continue
            claims_by_key.setdefault((card.competitor, card.dimension), []).append(card)
    return claims_by_key


def _coverage_by_dimension(
    *,
    matrix: ComparisonMatrix,
    supported_claims_by_key: dict[tuple[str, str], list[ClaimCard]],
) -> dict[str, Any]:
    coverage: dict[str, Any] = {}
    for dimension in matrix.dimensions:
        winner = matrix.winner_by_dimension.get(dimension)
        winner_claims = supported_claims_by_key.get((winner or "", dimension), [])
        coverage[dimension] = {
            "winner": winner,
            "supported_claim_card_count": len(winner_claims),
            "source_ids": merge_ordered_refs(
                source_id for claim in winner_claims for source_id in claim.source_ids
            ),
            "decision_card_eligible": bool(winner_claims and winner and winner.casefold() != "tie"),
        }
    return coverage


def _aggregate_evidence_strength(claims: Sequence[ClaimCard]) -> str:
    if not claims:
        return "insufficient"
    rank = max(_EVIDENCE_RANK[claim.evidence_strength] for claim in claims)
    return _EVIDENCE_BY_RANK[rank]


def _overall_evidence_strength(cards: Sequence[DecisionCard]) -> str:
    if not cards:
        return "insufficient"
    rank = min(_EVIDENCE_RANK[card.evidence_strength] for card in cards)
    return _EVIDENCE_BY_RANK[rank]


def _winner_counts(cards: Sequence[DecisionCard]) -> Counter[str]:
    return Counter(str(card.winner) for card in cards if card.winner)


def _single_supported_winner(winner_counts: Counter[str]) -> str | None:
    if len(winner_counts) != 1:
        return None
    return next(iter(winner_counts))


def _has_top_count_tie(winner_counts: Counter[str]) -> bool:
    if len(winner_counts) < 2:
        return False
    [(_, count), *rest] = winner_counts.most_common()
    return bool(rest and rest[0][1] == count)


def _has_winner_split(winner_counts: Counter[str]) -> bool:
    return len(winner_counts) > 1


def _decision_confidence(claims: Sequence[ClaimCard], cell: ComparisonCell | None) -> float:
    confidence = _average(claim.confidence for claim in claims)
    if cell is not None and cell.confidence > 0:
        confidence = min(confidence, cell.confidence)
    return max(0.0, min(1.0, confidence))


def _cap_confidence(confidence: float, *, fallback_used: bool) -> float:
    confidence = max(0.0, min(1.0, confidence))
    if fallback_used:
        return min(confidence, _FALLBACK_CONFIDENCE_CAP)
    return confidence


def _posture_for_decision(
    *,
    evidence_strength: str,
    confidence: float,
    fallback_used: bool,
) -> str:
    if fallback_used:
        return "tentative" if evidence_strength in {"moderate", "strong"} else "watch"
    if evidence_strength in {"moderate", "strong"} and confidence >= 0.8:
        return "strong"
    if evidence_strength == "insufficient":
        return "insufficient_evidence"
    return "tentative"


def _overall_posture_for_decision(
    *,
    supporting_cards: Sequence[DecisionCard],
    evidence_strength: str,
    confidence: float,
    fallback_used: bool,
) -> str:
    posture = _posture_for_decision(
        evidence_strength=evidence_strength,
        confidence=confidence,
        fallback_used=fallback_used,
    )
    if posture == "strong" and not all(
        card.evidence_strength == "strong" and card.posture == "strong"
        for card in supporting_cards
    ):
        return "tentative"
    return posture


def _risk_factors(
    *,
    evidence_strength: str,
    fallback_used: bool,
    source_count: int,
) -> list[str]:
    risks: list[str] = []
    if fallback_used:
        risks.append("Comparator used deterministic fallback; treat posture as non-strong.")
    if evidence_strength in {"weak", "insufficient"}:
        risks.append("Supporting claim-card evidence is limited.")
    if source_count < 2:
        risks.append("Decision is supported by fewer than two source IDs.")
    return risks


def _average(values: Iterable[float]) -> float:
    collected = [float(value) for value in values]
    if not collected:
        return 0.0
    return max(0.0, min(1.0, sum(collected) / len(collected)))


def _decision_card_id(
    run_id: str,
    decision_type: str,
    subject: str,
    winner: str,
) -> str:
    basis = "|".join((run_id, decision_type, subject, winner))
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:10]
    return f"decision-{_slug(decision_type)}-{_slug(subject)}-{_slug(winner)}-{digest}"


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().casefold()).strip("-")
    return slug or "unknown"


__all__ = ["build_decision_card_bundle"]
