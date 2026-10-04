"""Conservative, offline planning for caller-declared retrieval facts."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import RetrievalRequest

PLAN_VERSION = "intent-v1"
_FORMAT_SUFFIX = re.compile(
    r"(?P<body>.*?)[；;。，,\n]\s*(?P<suffix>"
    r"输出中文(?:并(?:保留出处|附上出处|提供引用))?"
    r"|请用中文(?:回答)?(?:并(?:保留出处|附上出处|提供引用))?"
    r"|answer in Chinese(?: and include citations)?"
    r")\s*[。.!！]?\s*$",
    re.IGNORECASE | re.DOTALL,
)
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


@dataclass(frozen=True)
class RetrievalPlan:
    version: str
    origin: str
    original_query: str
    queries: tuple[str, ...]
    output_language: str | None
    require_citations: bool
    required_terms: tuple[str, ...]


def _contains_term(text: str, term: str) -> bool:
    escaped = re.escape(term)
    if _NUMBER.fullmatch(term):
        return any(match.group() == term for match in _NUMBER.finditer(text))
    if term[0].isascii() and term[0].isalnum():
        escaped = r"(?<![A-Za-z0-9])" + escaped
    if term[-1].isascii() and term[-1].isalnum():
        escaped += r"(?![A-Za-z0-9])"
    return re.search(escaped, text, re.IGNORECASE) is not None


def resolve_retrieval_plan(request: RetrievalRequest) -> RetrievalPlan:
    """Preserve the original query and only remove a complete, known final format clause."""
    original = request.query
    if request.intent_policy == "raw":
        return RetrievalPlan(PLAN_VERSION, "raw", original, (original,), None, False, ())

    match = _FORMAT_SUFFIX.fullmatch(original)
    factual = match.group("body").strip() if match and match.group("body").strip() else original
    suffix = match.group("suffix") if match and factual != original else ""
    language = "中文" if suffix else None
    citations = bool(re.search(r"出处|引用|citations", suffix, re.IGNORECASE))

    intent = request.retrieval_intent
    if intent is None:
        return RetrievalPlan(PLAN_VERSION, "format_suffix" if suffix else "original",
                             original, (factual,), language, citations, ())

    # A complete known competitor model is already represented by its name; its
    # internal digits must not become a free-standing numeric constraint.
    number_source = factual
    for name in sorted(request.competitors, key=len, reverse=True):
        if name:
            escaped = re.escape(name)
            number_source = re.sub(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])",
                                   " ", number_source, flags=re.IGNORECASE)
    numbers = tuple(dict.fromkeys(match.group() for match in _NUMBER.finditer(number_source)))
    required = tuple(dict.fromkeys((*intent.required_terms, *numbers)))
    queries = []
    for fact in intent.fact_queries:
        query = fact.strip()
        for term in required:
            if not _contains_term(query, term):
                query += " " + term
        if len(query) > 2_000:
            raise ValueError("Preserved fact query and required terms exceed 2000 characters")
        queries.append(query)
    return RetrievalPlan(PLAN_VERSION, "explicit", original, tuple(queries),
                         intent.output_language or language,
                         intent.require_citations or citations, required)
