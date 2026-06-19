from __future__ import annotations

import hashlib

from pydantic import HttpUrl, TypeAdapter, ValidationError

from packages.community.source_classifier import classify_community_source
from packages.identity import compute_raw_source_id
from packages.research.models import SourceCandidate
from packages.schema.models import RawSource

SNIPPET_ONLY_CONFIDENCE_CAP = 0.55
COMMUNITY_ORIGIN_SOURCE_TYPES = {
    "community_forum",
    "reddit_thread",
    "github_discussion",
    "github_issue",
    "review_site",
    "developer_blog",
    "snippet_only",
}
_HTTP_URL_ADAPTER = TypeAdapter(HttpUrl)


def reclassify_community_source(source: RawSource, *, run_id: str) -> RawSource:
    classification = classify_community_source(
        url=str(source.url or ""),
        title=source.title,
        snippet=source.snippet,
    )
    if not classification.is_community:
        if not _is_community_origin_source(source):
            return source
        source_type = _community_origin_source_type(source)
        metadata = {
            **source.metadata,
            "community_evidence": True,
            "community_source_type": source.metadata.get("community_source_type")
            if isinstance(source.metadata.get("community_source_type"), str)
            else "community_search",
            "community_classification_reason": source.metadata.get(
                "community_classification_reason",
                "community_origin_preserved_after_final_url_reclassification",
            ),
            "official_commitment": False,
        }
        confidence = min(
            SNIPPET_ONLY_CONFIDENCE_CAP,
            source.confidence,
            source.candidate_confidence
            if isinstance(source.candidate_confidence, int | float)
            else source.confidence,
        )
        return source.model_copy(
            update={
                "id": compute_raw_source_id(
                    source_type=source_type,
                    competitor=source.competitor,
                    dimension=source.dimension,
                    url=str(source.url) if source.url else None,
                    content_hash=source.content_hash,
                    title=source.title,
                    snippet=source.snippet,
                    run_id=run_id,
                ),
                "source_type": source_type,
                "confidence": confidence,
                "metadata": metadata,
            }
        )
    confidence = max(source.confidence, classification.base_confidence)
    source_type = classification.source_type
    metadata = {
        **source.metadata,
        "community_evidence": True,
        "community_source_type": source_type,
        "community_authority_signal": classification.authority_signal,
        "community_classification_reason": classification.reason,
        "official_commitment": False,
    }
    return source.model_copy(
        update={
            "id": compute_raw_source_id(
                source_type=source_type,
                competitor=source.competitor,
                dimension=source.dimension,
                url=str(source.url) if source.url else None,
                content_hash=source.content_hash,
                title=source.title,
                snippet=source.snippet,
                run_id=run_id,
            ),
            "source_type": source_type,
            "confidence": min(0.92, confidence),
            "metadata": metadata,
        }
    )


def _is_community_origin_source(source: RawSource) -> bool:
    return (
        source.candidate_origin == "community_search"
        or source.metadata.get("community_evidence") is True
        or isinstance(source.metadata.get("community_source_type"), str)
    )


def _community_origin_source_type(source: RawSource) -> str:
    metadata_source_type = source.metadata.get("community_source_type")
    if (
        isinstance(metadata_source_type, str)
        and metadata_source_type in COMMUNITY_ORIGIN_SOURCE_TYPES
    ):
        return metadata_source_type
    if source.source_type in COMMUNITY_ORIGIN_SOURCE_TYPES:
        return source.source_type
    return "snippet_only"


def snippet_only_source_from_candidate(
    candidate: SourceCandidate,
    *,
    run_id: str,
) -> RawSource | None:
    if not _is_http_url(candidate.url):
        return None
    classification = classify_community_source(
        url=candidate.url,
        title=candidate.title,
        snippet=candidate.snippet,
    )
    if not classification.is_community:
        return None
    snippet = " ".join((candidate.snippet or candidate.title).split())
    if not _has_concrete_community_signal(snippet):
        return None
    content_hash = hashlib.sha256(
        snippet.encode("utf-8", errors="ignore")
    ).hexdigest()[:16]
    confidence = min(
        SNIPPET_ONLY_CONFIDENCE_CAP,
        candidate.confidence,
        classification.base_confidence,
    )
    return RawSource(
        id=compute_raw_source_id(
            source_type="snippet_only",
            competitor=candidate.competitor,
            dimension=candidate.dimension,
            url=candidate.url,
            content_hash=content_hash,
            title=candidate.title,
            snippet=snippet,
            run_id=run_id,
        ),
        competitor=candidate.competitor,
        dimension=candidate.dimension,
        source_type="snippet_only",
        title=candidate.title,
        url=candidate.url,
        snippet=snippet,
        content_hash=content_hash,
        confidence=confidence,
        candidate_origin=candidate.origin,
        candidate_rank=candidate.rank,
        candidate_confidence=candidate.confidence,
        fetch_method="search_snippet_only",
        quality_score=0.0,
        failure_reason="community_fetch_unavailable_or_rejected",
        metadata={
            "community_evidence": True,
            "community_source_type": classification.source_type,
            "community_authority_signal": classification.authority_signal,
            "community_classification_reason": classification.reason,
            "community_query": candidate.query,
            "snippet_only": True,
            "official_commitment": False,
        },
    )


def _has_concrete_community_signal(snippet: str) -> bool:
    normalized = snippet.casefold()
    concrete_terms = (
        "$",
        "per month",
        "usage limit",
        "quota",
        "complaint",
        "complain",
        "switched",
        "adoption",
        "context window",
        "limitation",
        "pricing",
        "cost",
    )
    return len(snippet) >= 40 and any(term in normalized for term in concrete_terms)


def _is_http_url(url: str) -> bool:
    try:
        validated = _HTTP_URL_ADAPTER.validate_python(url)
    except (ValidationError, ValueError):
        return False
    return validated.scheme in {"http", "https"}
