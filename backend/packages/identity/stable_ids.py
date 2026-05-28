from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit, urlunsplit


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_url(url: str | None) -> str:
    """Canonicalize source URLs for stable evidence identity."""
    if not url:
        return ""

    raw = url.strip()
    if not raw:
        return ""

    parts = urlsplit(raw)
    if not parts.scheme or not parts.netloc:
        return raw.rstrip("/")

    path = parts.path.rstrip("/") or ""
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.lower().strip())


def normalize_dimension_key(dimension: str | None) -> str:
    if not dimension:
        return ""
    return re.sub(r"[^a-z0-9_]+", "_", normalize_text(dimension)).strip("_")


def compute_content_hash(content: str | bytes | None) -> str:
    if content is None:
        return _sha256_hex("")
    if isinstance(content, bytes):
        return hashlib.sha256(content).hexdigest()
    return _sha256_hex(content)


def compute_evidence_id(
    canonical_url: str | None,
    content_hash: str | None,
    competitor_id: str | None,
    dimension_key: str | None,
) -> str:
    raw = "|".join(
        [
            normalize_url(canonical_url),
            content_hash or "",
            competitor_id or "",
            normalize_dimension_key(dimension_key),
        ]
    )
    return _sha256_hex(raw)


def compute_claim_id(
    evidence_id: str | None,
    claim_text: str | None,
    claim_type: str | None,
) -> str:
    raw = "|".join(
        [
            evidence_id or "",
            normalize_text(claim_text),
            normalize_dimension_key(claim_type),
        ]
    )
    return _sha256_hex(raw)


def compute_competitor_set_hash(
    competitor_ids: list[str] | tuple[str, ...] | set[str] | None,
) -> str:
    if not competitor_ids:
        return _sha256_hex("")
    normalized = sorted({item.strip() for item in competitor_ids if item and item.strip()})
    return _sha256_hex("|".join(normalized))


def compute_topic_normalized(topic: str | None) -> str:
    text = normalize_text(topic)
    text = re.sub(r"[、，。！？,.;:!?]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()
