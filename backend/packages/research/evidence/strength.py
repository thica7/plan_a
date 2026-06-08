from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

EvidenceStrength = Literal[
    "high_confidence_verified",
    "verified_webpage",
    "secondary_verified",
    "qualitative_signal",
    "synthetic_signal",
    "weak_unreviewed",
    "blocked_or_invalid",
]

HIGH_CONFIDENCE_SOURCE_TYPES = {
    "official",
    "official_docs",
    "official_pricing",
    "official_site",
    "official_api",
    "pricing_page",
    "trust_center",
}
VERIFIED_SOURCE_TYPES = {
    *HIGH_CONFIDENCE_SOURCE_TYPES,
    "webpage_verified",
    "review_site",
    "news",
}
QUALITATIVE_SOURCE_TYPES = {
    "interview_record",
    "manual_transcript",
    "manual_note",
    "manual",
    "survey_response",
}
SYNTHETIC_SOURCE_TYPES = {
    "survey_simulated",
    "llm_public_knowledge",
}
BAD_QUALITY_LABELS = {"rejected", "stale"}
POLICY_BLOCKING_STATUSES = {"blocked", "error", "rejected"}


@dataclass(frozen=True)
class EvidenceStrengthDecision:
    evidence_id: str
    source_type: str
    strength: EvidenceStrength
    confidence: float
    quality_label: str
    reason: str

    @property
    def can_support_strong_report_section(self) -> bool:
        return self.strength in {"high_confidence_verified", "verified_webpage"}


def classify_evidence_strength(evidence: object) -> EvidenceStrengthDecision:
    """Classify what kind of report language an evidence-like object can support."""

    evidence_id = _string_attr(evidence, "id") or _string_attr(evidence, "raw_source_id")
    source_type = _source_type(evidence)
    confidence = _confidence(evidence)
    quality_label = _quality_label(evidence)
    metadata = _metadata(evidence)
    robots_status = _policy_status(metadata, "robots_status")
    policy_review_status = _policy_status(metadata, "policy_review_status")

    if (
        quality_label in BAD_QUALITY_LABELS
        or robots_status in POLICY_BLOCKING_STATUSES
        or policy_review_status in POLICY_BLOCKING_STATUSES
    ):
        return EvidenceStrengthDecision(
            evidence_id=evidence_id,
            source_type=source_type,
            strength="blocked_or_invalid",
            confidence=confidence,
            quality_label=quality_label,
            reason="Evidence is rejected, stale, robots-blocked, or policy-blocked.",
        )

    if source_type in SYNTHETIC_SOURCE_TYPES:
        return EvidenceStrengthDecision(
            evidence_id=evidence_id,
            source_type=source_type,
            strength="synthetic_signal",
            confidence=confidence,
            quality_label=quality_label,
            reason="Synthetic or model/public-knowledge evidence is directional only.",
        )

    if source_type in QUALITATIVE_SOURCE_TYPES:
        if confidence >= 0.75 and quality_label == "accepted":
            return EvidenceStrengthDecision(
                evidence_id=evidence_id,
                source_type=source_type,
                strength="qualitative_signal",
                confidence=confidence,
                quality_label=quality_label,
                reason="Reviewed user-research evidence can support qualitative caveats only.",
            )
        return EvidenceStrengthDecision(
            evidence_id=evidence_id,
            source_type=source_type,
            strength="weak_unreviewed",
            confidence=confidence,
            quality_label=quality_label,
            reason="User-research evidence is low-confidence or unreviewed.",
        )

    if not _has_url(evidence):
        return EvidenceStrengthDecision(
            evidence_id=evidence_id,
            source_type=source_type,
            strength="weak_unreviewed",
            confidence=confidence,
            quality_label=quality_label,
            reason="Factual evidence without a URL cannot support strong report language.",
        )

    if source_type in HIGH_CONFIDENCE_SOURCE_TYPES and confidence >= 0.9:
        return EvidenceStrengthDecision(
            evidence_id=evidence_id,
            source_type=source_type,
            strength="high_confidence_verified",
            confidence=confidence,
            quality_label=quality_label,
            reason="Official or trust source with high confidence.",
        )

    if source_type in VERIFIED_SOURCE_TYPES and confidence >= 0.75:
        return EvidenceStrengthDecision(
            evidence_id=evidence_id,
            source_type=source_type,
            strength="verified_webpage",
            confidence=confidence,
            quality_label=quality_label,
            reason="Verified webpage evidence meets the release confidence floor.",
        )

    if _is_public_web_url(evidence) and confidence >= 0.75:
        return EvidenceStrengthDecision(
            evidence_id=evidence_id,
            source_type=source_type,
            strength="secondary_verified",
            confidence=confidence,
            quality_label=quality_label,
            reason="Secondary public web evidence can support non-strong factual context.",
        )

    return EvidenceStrengthDecision(
        evidence_id=evidence_id,
        source_type=source_type,
        strength="weak_unreviewed",
        confidence=confidence,
        quality_label=quality_label,
        reason="Evidence does not meet verified-source or confidence requirements.",
    )


def evidence_can_support_strong_report_section(evidence: object) -> bool:
    return classify_evidence_strength(evidence).can_support_strong_report_section


def _source_type(evidence: object) -> str:
    return _string_attr(evidence, "source_type").casefold()


def _confidence(evidence: object) -> float:
    for name in ("reliability_score", "confidence"):
        value = getattr(evidence, name, None)
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            return max(0.0, min(1.0, float(value)))
    return 0.0


def _quality_label(evidence: object) -> str:
    return (_string_attr(evidence, "quality_label") or "accepted").casefold()


def _has_url(evidence: object) -> bool:
    return bool(_string_attr(evidence, "canonical_url") or _string_attr(evidence, "url"))


def _is_public_web_url(evidence: object) -> bool:
    raw_url = _string_attr(evidence, "canonical_url") or _string_attr(evidence, "url")
    parsed = urlparse(raw_url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _metadata(evidence: object) -> dict[str, object]:
    value = getattr(evidence, "metadata", {})
    return value if isinstance(value, dict) else {}


def _policy_status(metadata: dict[str, object], key: str) -> str:
    value = metadata.get(key) or metadata.get(f"source_{key}")
    return str(value or "").strip().casefold()


def _string_attr(evidence: object, name: str) -> str:
    value = getattr(evidence, name, "")
    return str(value or "").strip()
