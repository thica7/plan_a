"""Conservative, offline planning for caller-declared retrieval facts."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .lexical import quantity_literals, query_terms
from .models import RetrievalRequest
from .tokenization import lexical_tokens

PLAN_VERSION = "intent-v3"
_FORMAT_SUFFIX = re.compile(
    r"(?P<body>.*?)[；;。，,？?！!\n]\s*(?P<suffix>"
    r"输出中文(?:并(?:保留出处|附上出处|提供引用))?"
    r"|(?:请)?用中文(?:回答)?(?:并(?:保留出处|附上出处|提供引用|保留条件))?"
    r"|answer in Chinese(?: and include citations)?"
    r")\s*[。.!！]?\s*$",
    re.IGNORECASE | re.DOTALL,
)
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_LATIN = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")
_CONDITIONS = frozenset({"free", "admin", "guest", "private",
                         "enterprise", "paid", "public", "invited", "owner", "viewer", "permission"})
_PRICING_TOPICS = frozenset({"pricing", "plans", "billing", "subscription", "monthly", "annual", "seat", "license"})
_SECURITY_TOPICS = frozenset({"security", "privacy", "encryption", "local", "retention", "deletion", "history", "branch protection"})


def _dimension_topics(topics: list[str], dimensions: list[str]) -> list[str]:
    """Use only recognized dimension semantics; unknown dimensions keep all topics."""
    if not dimensions:
        return topics
    allowed: set[str] = set()
    for dimension in dimensions:
        value = dimension.casefold()
        if any(term in value for term in ("pricing", "价格", "定价")):
            allowed.update(_PRICING_TOPICS | _CONDITIONS)
        elif any(term in value for term in ("security", "安全", "privacy", "隐私")):
            allowed.update(_SECURITY_TOPICS | _CONDITIONS)
        elif value in {"feature", "features", "功能"}:
            allowed.update(set(topics) - _PRICING_TOPICS)
        elif value in {"persona", "user", "users", "usecases", "目标用户", "用户"}:
            allowed.update(_CONDITIONS)
        else:
            return topics
    return [topic for topic in topics if topic in allowed]


def _auto_fact_queries(
    factual: str, competitors: list[str], dimensions: list[str]
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]] | None:
    """Split recognized long questions into bounded facts, retaining access/model anchors."""
    if (len(lexical_tokens(factual)) < 12 or not re.search(r"[\u3400-\u9fff]", factual)
            or re.search(r"输出中文|answer in Chinese", factual, re.IGNORECASE)):
        return None
    concepts, literals = query_terms(factual, competitors)
    if not concepts:
        return None
    anchor_tokens = {term for term in literals if term.isascii()
                     and not any(char.isdigit() for char in term)}
    prefix = re.split(r"[\u3400-\u9fff]", factual, maxsplit=1)[0]
    # A model number beside an initial product name is shared. Other numerical
    # constraints belong to their original clause (e.g. charger W vs battery Wh).
    prefix_quantities = set(quantity_literals(prefix))
    anchor_tokens.update(term for term in lexical_tokens(prefix)
                         if term in literals and term not in prefix_quantities)
    if len(anchor_tokens) > 12:
        return None
    anchors = list(dict.fromkeys(match.group() for match in _LATIN.finditer(factual)
                                if match.group().casefold() in anchor_tokens))
    unknown_terms = tuple(dict.fromkeys(term for term in literals if not term.isascii()))
    # Unknown Chinese names need a declared product boundary or a preserved
    # Latin product/model anchor before topic-only recall is safe to attempt.
    if unknown_terms and not competitors and not anchors:
        return None
    if len(" ".join(anchors)) > 350:
        return None
    queries: list[str] = []
    preserved_clauses: list[str] = []
    if any(re.search(r"[,，]", value) for value in quantity_literals(factual)):
        # Unsupported grouped numbers must remain whole. Splitting 1,050Wh
        # into independent clauses would let fragments bypass quantity checks.
        clauses = [factual]
        preserved_clauses.append(factual)
    else:
        clauses = re.split(r"[？?；;。!！\n，,、]+", factual)
    for clause in clauses:
        topics, clause_literals = query_terms(clause, competitors)
        relevant = _dimension_topics(topics, dimensions)
        if any(not term.isascii() for term in clause_literals):
            preserved_clauses.append(clause.strip())
        if relevant != topics:
            preserved_clauses.append(clause.strip())
        conditions = [topic for topic in relevant if topic in _CONDITIONS]
        facts = [topic for topic in relevant if topic not in _CONDITIONS]
        contextual = [topic for topic in facts if topic in {"plans", "repository"}]
        if conditions and len(facts) > len(contextual):
            # Plan/repository qualifiers beside a specific capability belong
            # with access lookup; pricing-only plans remains its own fact.
            facts = [topic for topic in facts if topic not in contextual]
            conditions.extend(contextual)
        # Unknown Chinese clauses remain available to later verification. They
        # are not asserted to hold by retrieval: a topic may recall evidence that
        # disproves the question's premise. Numbers and known access conditions
        # still constrain their own clause, and model anchors constrain all facts.
        clause_quantities = set(quantity_literals(clause))
        local_terms = [term for term in clause_literals if (term.isascii() or term in clause_quantities)
                       and term not in anchor_tokens]
        # Access requirements have their own bounded lookup. A condition is not
        # required to occur verbatim in every fact that could refute a premise.
        for fact in [*facts, *([" ".join(conditions)] if conditions else [])]:
            query = " ".join(dict.fromkeys([*anchors, *local_terms, fact])).strip()
            if query and query not in queries:
                queries.append(query)
    if not queries:
        return None
    # Preserve omitted clauses rather than merging unrelated numeric conditions.
    if len(queries) > 5:
        preserved_clauses = [factual]
    return tuple(queries[:5]), unknown_terms, tuple(dict.fromkeys(preserved_clauses))


@dataclass(frozen=True)
class RetrievalPlan:
    version: str
    origin: str
    original_query: str
    queries: tuple[str, ...]
    output_language: str | None
    require_citations: bool
    required_terms: tuple[str, ...]
    planning_reason: str | None = None
    unknown_terms: tuple[str, ...] = ()
    preserved_clauses: tuple[str, ...] = ()


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
    """Keep the original question while planning deterministic, bounded fact searches."""
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
        automatic = _auto_fact_queries(factual, request.competitors, request.dimensions)
        if automatic:
            queries, unknown_terms, clauses = automatic
            return RetrievalPlan(PLAN_VERSION, "auto", original, queries, language, citations, (),
                "unresolved_clauses_preserved_for_verification" if clauses else None,
                unknown_terms, clauses)
        concepts, literals = query_terms(factual, request.competitors)
        if (len(request.competitors) == len(request.dimensions) == 1
                and len(lexical_tokens(factual)) >= 12 and re.search(r"[\u3400-\u9fff]", factual)
                and request.competitors[0].strip() and request.dimensions[0].strip()
                and request.scope is not None and request.source_roles == ["source"]
                and not _dimension_topics(concepts, request.dimensions)
                and not any(_NUMBER.search(term) for term in literals)):
            # This is a canonical product/dimension browse for broad research
            # briefs. Do not report it as successful semantic fact parsing or
            # allow it to remove additional model/numeric requirements.
            return RetrievalPlan(PLAN_VERSION, "dimension_scope_lookup", original,
                (request.competitors[0],), language, citations, (),
                "metadata_scoped_browse_without_fact_parse", tuple(literals), (factual,))
        reason = ("unsupported_or_unbounded_question" if len(lexical_tokens(factual)) >= 12
                  else None)
        return RetrievalPlan(PLAN_VERSION, "format_suffix" if suffix else "original",
                             original, (factual,), language, citations, (), reason)

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
