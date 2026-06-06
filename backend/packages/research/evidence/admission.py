from __future__ import annotations

import hashlib
import re
from collections.abc import Callable

from packages.business_intel.entity_resolver import (
    confusion_terms_for_competitor,
    identity_terms_for_competitor,
    normalize_competitor_key,
)
from packages.identity import compute_raw_source_id
from packages.research.evidence.citations import snippet_from_evidence_items
from packages.research.evidence.store import accepted_evidence_by_page
from packages.research.extraction.quality import quote_quality_problem
from packages.research.models import (
    CapturedPage,
    EvidenceItem,
    EvidenceQuote,
    ExtractionResult,
    ResearchBrief,
    ResearchResult,
    SourceCandidate,
)
from packages.schema.models import RawSource

SourceExistsCallable = Callable[[str, list[RawSource]], bool]
SourceConfidenceCallable = Callable[[SourceCandidate, CapturedPage, str, list[EvidenceItem]], float]
FallbackSnippetCallable = Callable[[CapturedPage], str]
SourceUsableCallable = Callable[[RawSource], bool]

USER_RESEARCH_SOURCE_TYPES = {
    "survey_simulated",
    "survey_response",
    "interview_record",
    "manual_transcript",
    "manual_note",
    "manual",
}


def admit_evidence_items(
    extractions: list[ExtractionResult],
    *,
    captured_pages: list[CapturedPage] | None = None,
    candidates: list[SourceCandidate] | None = None,
    min_accept_confidence: float = 0.35,
    min_page_quality: float = 0.25,
) -> list[EvidenceItem]:
    page_by_id = {page.id: page for page in captured_pages or []}
    candidate_by_id = {candidate.id: candidate for candidate in candidates or []}
    items: list[EvidenceItem] = []
    for extraction in extractions:
        page = page_by_id.get(extraction.captured_page_id)
        candidate = candidate_by_id.get(extraction.source_candidate_id)
        quote_by_field = _quote_by_field(extraction.quotes)
        for field, value in extraction.fields.items():
            if _empty_evidence_value(value):
                continue
            quote = quote_by_field.get(field)
            rejection_reasons = _admission_rejection_reasons(
                extraction,
                field=field,
                value=value,
                quote=quote,
                page=page,
                min_accept_confidence=min_accept_confidence,
                min_page_quality=min_page_quality,
            )
            status = "rejected" if rejection_reasons else "accepted"
            items.append(
                EvidenceItem(
                    competitor=extraction.competitor,
                    dimension=extraction.dimension,
                    field=field,
                    value=value,
                    source_candidate_id=extraction.source_candidate_id,
                    captured_page_id=extraction.captured_page_id,
                    source_url=(quote.source_url if quote is not None else None)
                    or (page.final_url if page is not None else None),
                    quote=quote.text if quote is not None else "",
                    confidence=extraction.confidence,
                    status=status,
                    rejection_reason="; ".join(rejection_reasons) if rejection_reasons else None,
                    metadata={
                        "extraction_id": extraction.id,
                        "extractor_name": extraction.extractor_name,
                        "capture_status": page.status if page is not None else None,
                        "capture_failure_reason": page.failure_reason if page is not None else None,
                        "page_quality_score": page.quality_score if page is not None else None,
                        "candidate_origin": candidate.origin if candidate is not None else None,
                        "candidate_confidence": (
                            candidate.confidence if candidate is not None else None
                        ),
                    },
                )
            )
    return items


def _admission_rejection_reasons(
    extraction: ExtractionResult,
    *,
    field: str,
    value: object,
    quote: EvidenceQuote | None,
    page: CapturedPage | None,
    min_accept_confidence: float,
    min_page_quality: float,
) -> list[str]:
    reasons: list[str] = []
    if extraction.confidence < min_accept_confidence:
        reasons.append(
            f"extraction_confidence_below_{min_accept_confidence:.2f}"
        )
    if page is None:
        reasons.append("captured_page_missing")
    elif page.status != "ok":
        reasons.append(f"capture_status_{page.status}")
    elif page.quality_score < min_page_quality:
        reasons.append(f"page_quality_below_{min_page_quality:.2f}")
    if _requires_field_quote(extraction, field, value) and (
        quote is None or len(quote.text.strip()) < 24
    ):
        reasons.append("field_quote_missing_or_too_short")
    if quote is not None:
        quote_problem = quote_quality_problem(quote.text, dimension=extraction.dimension)
        if quote_problem:
            reasons.append(quote_problem)
    return reasons


def _quote_by_field(quotes: list[EvidenceQuote]) -> dict[str, EvidenceQuote]:
    return {
        quote.field: quote
        for quote in quotes
        if quote.field and quote.text and quote.field not in {"confidence_reason"}
    }


def _requires_field_quote(extraction: ExtractionResult, field: str, value: object) -> bool:
    if field == "confidence_reason":
        return False
    if extraction.status == "not_applicable" and field in {
        "pricing_model_type",
        "not_applicable_reason",
    }:
        return False
    if isinstance(value, dict) and value.get("status") in {"not_applicable", "unsupported"}:
        return False
    return True


def _empty_evidence_value(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, list | tuple | set):
        return len(value) == 0
    if isinstance(value, dict):
        if not value:
            return True
        return value.get("status") == "not_found_in_source"
    return False


def raw_source_from_capture(
    brief: ResearchBrief,
    candidate: SourceCandidate,
    capture: CapturedPage,
    *,
    confidence: float,
    source_type: str = "webpage_verified",
    snippet: str | None = None,
) -> RawSource:
    evidence_snippet = snippet or capture.snippet or candidate.snippet
    content_hash = capture.content_hash or _content_hash(evidence_snippet or candidate.title)
    return RawSource(
        id=compute_raw_source_id(
            source_type=source_type,
            competitor=brief.competitor,
            dimension=brief.dimension,
            url=capture.final_url,
            content_hash=content_hash,
            title=capture.title or candidate.title,
            snippet=evidence_snippet,
            run_id=brief.run_id,
        ),
        competitor=brief.competitor,
        dimension=brief.dimension,
        source_type=source_type,
        title=capture.title or candidate.title,
        url=capture.final_url,
        snippet=evidence_snippet,
        content_hash=content_hash,
        confidence=confidence,
        candidate_origin=candidate.origin,
        candidate_rank=candidate.rank,
        candidate_confidence=candidate.confidence,
        fetch_method=capture.fetch_method,
        quality_score=capture.quality_score,
        failure_reason=capture.failure_reason,
    )


def raw_sources_from_research_result(
    brief: ResearchBrief,
    result: ResearchResult,
    *,
    batch_sources: list[RawSource],
    target_source_count: int,
    requires_accepted_evidence: bool,
    source_exists: SourceExistsCallable,
    confidence_for_source: SourceConfidenceCallable,
    fallback_snippet: FallbackSnippetCallable,
    source_is_usable: SourceUsableCallable = lambda source: source_quality_problem(source) is None,
) -> list[RawSource]:
    candidate_by_id = {candidate.id: candidate for candidate in result.candidates}
    accepted_by_page = accepted_evidence_by_page(result.evidence_items)
    sources: list[RawSource] = []

    for page in sorted(
        result.captured_pages,
        key=lambda item: _research_page_score(item, accepted_by_page),
        reverse=True,
    ):
        if len(batch_sources) + len(sources) >= target_source_count:
            break
        candidate = candidate_by_id.get(page.candidate_id)
        if candidate is None or page.status != "ok":
            continue
        page_items = accepted_by_page.get(page.id, [])
        if requires_accepted_evidence and not page_items:
            continue
        if source_exists(page.final_url, [*batch_sources, *sources]):
            continue
        fallback = fallback_snippet(page)
        snippet = snippet_from_evidence_items(page_items, fallback=fallback)
        source = raw_source_from_capture(
            brief,
            candidate,
            page,
            confidence=confidence_for_source(candidate, page, snippet, page_items),
            source_type="webpage_verified",
            snippet=snippet,
        )
        if not source_is_usable(source):
            continue
        sources.append(source)
    return sources


def _research_page_score(
    page: CapturedPage,
    accepted_by_page: dict[str, list[EvidenceItem]],
) -> tuple[int, float, float, int]:
    items = accepted_by_page.get(page.id, [])
    return (
        1 if items else 0,
        max((item.confidence for item in items), default=0.0),
        page.quality_score,
        page.text_length,
    )


def source_quality_problem(source: RawSource) -> str | None:
    text = f"{source.title}\n{source.snippet}".strip()
    normalized = text.casefold()
    snippet_normalized = source.snippet.casefold()
    if len(source.snippet.strip()) < 24 and not has_concrete_source_signal(
        source.dimension, normalized
    ):
        return (
            f"Source {source.id} snippet is too short to support a reliable "
            f"{source.dimension} claim."
        )
    if looks_like_binary_or_pdf(source.snippet):
        return (
            f"Source {source.id} looks like unreadable binary/PDF text, "
            "not usable extracted evidence."
        )
    if looks_like_soft_404(source):
        return f"Source {source.id} appears to be a soft 404 or not-found page."
    if looks_like_navigation_only(snippet_normalized) and not has_dimension_specific_fact(
        source.dimension, snippet_normalized
    ):
        return f"Source {source.id} appears to contain mostly navigation or boilerplate text."
    if (
        source.source_type == "webpage_verified"
        and source.confidence <= 0.88
        and not has_dimension_specific_fact(source.dimension, snippet_normalized)
    ):
        return (
            f"Source {source.id} has low confidence ({source.confidence:.2f}) "
            f"and does not expose a concrete {source.dimension} fact in the fetched snippet."
        )
    if source.url and is_low_value_url(str(source.url)):
        return f"Source {source.id} points to a low-value page for structured evidence extraction."
    if source.url and is_dimension_mismatch_url(source.dimension, str(source.url)):
        return (
            f"Source {source.id} points to a page whose URL is mismatched for "
            f"{source.dimension} evidence."
        )
    if identity_problem := competitor_identity_problem(source):
        return identity_problem
    if not dimension_terms_present(source.dimension, normalized):
        return (
            f"Source {source.id} does not contain enough {source.dimension} "
            "terminology for this dimension."
        )
    return None


def has_concrete_source_signal(dimension: str, normalized_text: str) -> bool:
    dimension_key = dimension.casefold()
    if "pricing" in dimension_key:
        return bool(
            re.search(
                r"(?:\$|usd|rmb|cny|eur|\d+\s*(?:/|per)\s*(?:token|seat|month|year))",
                normalized_text,
            )
        )
    if "persona" in dimension_key or "user" in dimension_key:
        return any(
            term in normalized_text
            for term in ("developer", "customer", "enterprise", "team", "user")
        )
    return any(
        term in normalized_text for term in ("model", "api", "feature", "coding", "reasoning")
    )


def looks_like_binary_or_pdf(text: str) -> bool:
    if "%pdf" in text[:80].casefold() or " endobj" in text.casefold():
        return True
    if not text:
        return True
    replacement_ratio = text.count("\ufffd") / max(1, len(text))
    control_ratio = sum(1 for char in text if ord(char) < 32 and char not in "\n\r\t") / max(
        1, len(text)
    )
    return replacement_ratio > 0.02 or control_ratio > 0.01


def looks_like_soft_404(source: RawSource) -> bool:
    normalized = f"{source.title}\n{source.snippet}".casefold()
    title = source.title.casefold().strip()
    if title in {"404", "not found", "404: this page could not be found"}:
        return True
    markers = (
        "page not found",
        "404 not found",
        "this page could not be found",
        "this page does not exist",
        "this page doesn't exist",
        "we couldn't find that page",
        "we could not find that page",
    )
    if any(marker in normalized for marker in markers):
        return True
    return bool(re.search(r"(?:^|\s)404(?:\s|:|-)", normalized) and "not found" in normalized)


def looks_like_navigation_only(normalized_text: str) -> bool:
    nav_markers = [
        "skip to main content",
        "open menu",
        "toggle theme",
        "sign in",
        "sign up",
        "log in",
        "language",
        "cookie",
        "this browser is no longer supported",
        "download microsoft edge",
        "search docs",
        "search...",
        "navigation",
        "home page",
        "resources",
        "back to blog",
    ]
    marker_count = sum(1 for marker in nav_markers if marker in normalized_text)
    return marker_count >= 3 and not has_dimension_specific_fact("generic", normalized_text)


def has_dimension_specific_fact(dimension: str, normalized_text: str) -> bool:
    if not normalized_text.strip():
        return False
    dimension_key = dimension.casefold()
    if "pricing" in dimension_key:
        return bool(
            re.search(
                r"(?:\$|usd|cny|rmb|eur|free|per\s+(?:user|seat|month|year|token)|\bplan\b|\btier\b)",
                normalized_text,
            )
        )
    if "persona" in dimension_key or "user" in dimension_key:
        return bool(
            re.search(
                r"(?:target(?:ed)?\s+(?:user|customer|persona)|for\s+(?:developers|teams|enterprises|"
                r"engineering|marketing|sales)|case stud(?:y|ies)|customer|"
                r"enterprise|adoption|use case)",
                normalized_text,
            )
        )
    if "review" in dimension_key or "feedback" in dimension_key:
        return bool(
            re.search(
                r"(?:review|feedback|rating|complaint|praise|customer|user|adoption|"
                r"switching|pain point)",
                normalized_text,
            )
        )
    if "generic" in dimension_key:
        return bool(
            re.search(
                r"(?:\$\d+|\d+\s*(?:k|m|%|tokens?|users?|seats?)|supports|provides|includes|"
                r"offers|built for|used by|target(?:ed)?)",
                normalized_text,
            )
        )
    return bool(
        re.search(
            r"(?:supports|provides|includes|offers|can\s+(?:write|generate|explain|run)|"
            r"context window|context awareness|tool calls?|code completion|"
            r"pull requests?|api|benchmark|cascade|autocomplete|supercomplete|"
            r"write/chat modes?|auto-execution|model context protocol|mcp|"
            r"jetbrains plugin|command|tab)",
            normalized_text,
        )
    )


def is_low_value_url(url: str) -> bool:
    lowered = url.casefold()
    return any(
        host in lowered
        for host in (
            "youtube.com",
            "youtu.be",
            "google.com/search",
            "accounts.google",
        )
    )


def is_dimension_mismatch_url(dimension: str, url: str) -> bool:
    lowered = url.casefold()
    dimension_key = dimension.casefold()
    if "persona" in dimension_key or "user" in dimension_key:
        return any(
            token in lowered
            for token in (
                "/pricing",
                "/plans",
                "/billing",
                "/accounts/usage",
                "/subscription",
                "/manage-plan",
            )
        )
    return False


def competitor_identity_problem(source: RawSource) -> str | None:
    if source.source_type in USER_RESEARCH_SOURCE_TYPES:
        return None
    key = normalize_competitor_key(source.competitor)
    if not key or key.startswith("crossmodel"):
        return None
    haystack = f"{source.title}\n{source.url or ''}\n{source.snippet}".casefold()
    for term in confusion_terms_for_competitor(source.competitor):
        if (
            key == "windsurf"
            and term == "devin.ai"
            and is_windsurf_docs_redirect_source(source, haystack)
        ):
            continue
        if term in haystack:
            return (
                f"Source {source.id} appears to describe `{term}` rather than "
                f"{source.competitor}."
            )
    hints = identity_terms_for_competitor(source.competitor)
    if hints and not any(term in haystack for term in hints):
        return (
            f"Source {source.id} does not expose a recognizable {source.competitor} "
            "product identity signal."
        )
    return None


def is_windsurf_docs_redirect_source(source: RawSource, haystack: str) -> bool:
    url = str(source.url or "").casefold()
    return (
        any(path in url for path in ("docs.devin.ai/desktop", "docs.devin.ai/windsurf"))
        and "windsurf" in haystack
        and "devin desktop" not in haystack
        and "cognition devin" not in haystack
    )


def dimension_terms_present(dimension: str, normalized_text: str) -> bool:
    dimension_key = dimension.casefold()
    if "pricing" in dimension_key:
        terms = (
            "pricing",
            "price",
            "cost",
            "billing",
            "token",
            "tier",
            "free",
            "enterprise",
            "plan",
            "$",
        )
    elif "persona" in dimension_key or "user" in dimension_key:
        terms = (
            "customer",
            "user",
            "developer",
            "enterprise",
            "team",
            "persona",
            "target",
            "use case",
            "case study",
            "organization",
        )
    elif "review" in dimension_key or "feedback" in dimension_key:
        terms = (
            "review",
            "feedback",
            "rating",
            "complaint",
            "praise",
            "customer",
            "user",
            "adoption",
            "switching",
            "pain point",
        )
    else:
        terms = (
            "feature",
            "capability",
            "model",
            "context",
            "multimodal",
            "coding",
            "reasoning",
            "benchmark",
            "api",
            "tool",
        )
    return any(term in normalized_text for term in terms)


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16]
