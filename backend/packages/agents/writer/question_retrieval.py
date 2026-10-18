"""Rank current, supported originals for explicit questions; never prove an answer."""

from __future__ import annotations

import asyncio
import math
import re
from datetime import UTC, datetime
from typing import Any

from packages.knowledge.local_models import (
    LocalEmbeddingProvider,
    LocalRerankerProvider,
    get_local_provider_from_env,
    local_model_strict,
)
from packages.knowledge.runtime import call_provider
from packages.research.evidence.operations import operation_observations, required_operations
from packages.research.evidence.snapshot import _verify, current_snapshot
from packages.research.evidence.snapshot_models import FACT_MARKET_POLICY_VERSION, canonical_json
from packages.research.evidence.views import _qualification

from .answer_coverage import question_terms, research_questions

CANDIDATE_LIMIT = 128
PER_QUESTION_LIMIT = 3
TOTAL_FACT_LIMIT = 8
EXCEPTION_CLOSURE_MAX_BYTES = 14000
RERANK_CANDIDATE_LIMIT = 12
_RRF_K = 60


def _round_robin(rows, limit):
    result = []
    seen = set()
    for index in range(max((len(row) for row in rows), default=0)):
        for row in rows:
            if index < len(row) and row[index] not in seen:
                seen.add(row[index])
                result.append(row[index])
                if len(result) >= limit:
                    return result
    return result


def _validate_scope(detail, snapshot, product, dimension):
    _verify(snapshot)
    current = current_snapshot(detail)
    if (
        current is None
        or current.id != snapshot.id
        or current.content_hash != snapshot.content_hash
    ):
        raise ValueError("question retrieval requires the current evidence snapshot")
    if (
        snapshot.run_id != detail.id
        or snapshot.workspace_id != detail.workspace_id
        or snapshot.project_id != detail.project_id
    ):
        raise ValueError("question retrieval evidence scope mismatch")
    if detail.evidence_inputs_dirty or snapshot.phase != "analysis":
        raise ValueError("question retrieval requires accepted analysis evidence")
    if snapshot.fact_market_policy_version != FACT_MARKET_POLICY_VERSION:
        raise ValueError("question retrieval requires the accepted evidence policy")
    if product not in detail.plan.competitors or dimension not in detail.plan.dimensions:
        raise ValueError("question retrieval product/dimension scope mismatch")


def _eligible_facts(snapshot, product, dimension):
    now = datetime.now(UTC)
    sources = {
        source.id
        for source in snapshot.sources
        if source.dimension == dimension
        and product in (source.competitor, *source.covered_competitors)
        and source.role == "source"
        and source.material_level in {"full_source", "kb_document"}
        and not _qualification(source, now)
        and (
            source.document_workspace_id is None
            or source.document_workspace_id == snapshot.workspace_id
        )
        and (
            source.document_project_id is None or source.document_project_id == snapshot.project_id
        )
    }
    conflicts = {key for conflict in snapshot.conflicts for key in conflict.fact_ids}
    return sorted(
        (
            fact
            for fact in snapshot.facts
            if fact.competitor == product
            and fact.dimension == dimension
            and fact.field == "evidence_terms"
            and fact.status == "supported"
            and fact.source_id in sources
            and fact.id not in conflicts
        ),
        key=lambda fact: fact.id,
    )


def _rank_text(fact):
    # The local model's tokenizer has its own limit. Never shorten originals here
    # or replace the originals later sent by the evidence view to Writer.
    return fact.quote + "\n" + fact.value_json


def _cosine(query, document):
    if not query or len(query) != len(document):
        raise ValueError("question embedding dimension mismatch")
    if not all(math.isfinite(value) for value in (*query, *document)):
        raise ValueError("question embedding contains nonfinite values")
    norm = math.sqrt(
        sum(value * value for value in query) * sum(value * value for value in document)
    )
    if not norm:
        raise ValueError("question embedding must be nonzero")
    return sum(left * right for left, right in zip(query, document, strict=True)) / norm


def _fuse(lexical, semantic):
    scores = {}
    for row in (lexical, semantic):
        for rank, fact_id in enumerate(row, 1):
            scores[fact_id] = scores.get(fact_id, 0.0) + 1 / (_RRF_K + rank)
    return sorted(scores, key=lambda fact_id: (-scores[fact_id], fact_id))


def _select_operation_facts(
    row, candidates, requested, operations, quotes, quote_hints, question_hints, observations
):
    """Repair operation omissions while retaining selected source condition branches."""
    selected = row[:PER_QUESTION_LIMIT]
    requested = set(requested)
    branches = {
        key: {
            canonical_json({
                name: value for name, value in item.items()
                if name not in {"fact_id", "source_id", "competitor", "quote", "operation_quote"}
            })
            for item in items if item["operation"] in requested
        }
        for key, items in observations.items()
    }
    protected = {
        key for key in selected
        if ("login" in question_hints & quote_hints[key]
            or re.search(
                r"\b(?:must|requires?|required|needs?|only|unless|before|without|"
                r"depending\s+on|depends?\s+on|if|when|after)\b|必须|需要|仅限|前提|除非|只有|仅当|取决于",
                quotes[key], re.I,
            ))
    }
    while requested:
        covered = set().union(*(operations[key] for key in selected)) & requested
        covered_branches = set().union(*(branches[key] for key in selected))
        missing = requested - covered
        additions = sorted(
            (key for key in candidates if key not in selected and operations[key] & missing),
            key=lambda key: (-len(operations[key] & missing), candidates.index(key)),
        )
        changed = False
        for key in additions:
            if len(selected) < PER_QUESTION_LIMIT:
                selected.append(key)
                changed = True
                break
            for index in reversed(range(len(selected))):
                if selected[index] in protected:
                    continue
                retained = set().union(*(
                    branches[other] for position, other in enumerate(selected)
                    if position != index
                ))
                if covered_branches <= retained | branches[key]:
                    selected[index] = key
                    changed = True
                    break
            if changed:
                break
        if not changed:
            break
    return selected


async def retrieve_question_facts(
    detail,
    snapshot,
    product,
    dimension,
    *,
    mode="hybrid",
    embedding_provider=None,
    reranker_provider=None,
) -> tuple[tuple[str, ...] | None, dict[str, Any]]:
    """Return bounded original IDs plus diagnostics, scoped to one accepted snapshot.

    ``None`` means no explicit questions. ``()`` means questions exist but no
    original was selected. Semantic scores affect order only, never support.
    Explicit providers must be strict local providers; HTTP/hash are rejected.
    No document/vector cache is shared across workspaces or snapshot versions.
    """
    if mode not in {"hybrid", "lexical"}:
        raise ValueError("question retrieval mode must be hybrid or lexical")
    _validate_scope(detail, snapshot, product, dimension)
    questions = research_questions(detail, product, dimension)
    diagnostic = {
        "mode": mode,
        "ranking_only": True,
        "workspace_id": snapshot.workspace_id,
        "project_id": snapshot.project_id,
        "snapshot_id": snapshot.id,
        "snapshot_content_hash": snapshot.content_hash,
        "product": product,
        "dimension": dimension,
        "embedding_model_version": None,
        "reranker_model_version": None,
        "degraded_reasons": [],
        "eligible_count": 0,
        "candidate_count": 0,
        "capacity_limited": False,
        "candidate_limit": CANDIDATE_LIMIT,
        "per_question_limit": PER_QUESTION_LIMIT,
        "total_fact_limit": TOTAL_FACT_LIMIT,
        "selected_fact_ids": [],
        "questions": [],
    }
    if not questions:
        diagnostic["mode"] = "no_questions"
        return None, diagnostic
    facts = _eligible_facts(snapshot, product, dimension)
    diagnostic["eligible_count"] = len(facts)
    if not facts:
        diagnostic["mode"] = "no_candidates"
        return (), diagnostic

    texts = {fact.id: _rank_text(fact) for fact in facts}
    quotes = {fact.id: fact.quote for fact in facts}
    hints = {fact.id: question_terms(texts[fact.id], product) for fact in facts}
    quote_hints = {key: question_terms(quote, product) for key, quote in quotes.items()}
    lexical_rows = []
    for question in questions:
        terms = question_terms(question["question"], product)
        scores = {fact.id: len(terms & hints[fact.id]) for fact in facts}
        lexical_rows.append(
            sorted(
                (key for key, score in scores.items() if score), key=lambda key: (-scores[key], key)
            )
        )
    pool_ids = _round_robin([*lexical_rows, [fact.id for fact in facts]], CANDIDATE_LIMIT)
    pool = set(pool_ids)
    lexical_rows = [[key for key in row if key in pool] for row in lexical_rows]
    diagnostic.update(candidate_count=len(pool_ids), capacity_limited=len(facts) > len(pool_ids))
    ranked_rows = lexical_rows

    if mode == "hybrid":
        if embedding_provider is None:
            try:
                # Frozen file hash verification can read large weights; it also
                # belongs off the event loop along with model computation.
                embedding_provider = await asyncio.to_thread(
                    get_local_provider_from_env, "embedding"
                )
            except Exception as error:
                if local_model_strict():
                    raise
                diagnostic["degraded_reasons"].append(
                    f"embedding_load_failed:{type(error).__name__}"
                )
        if not isinstance(embedding_provider, LocalEmbeddingProvider):
            diagnostic["degraded_reasons"].append("strict_local_provider_required")
        else:
            diagnostic["embedding_model_version"] = embedding_provider.model_version
            try:
                vectors = await call_provider(
                    embedding_provider.embed_documents, [texts[key] for key in pool_ids]
                )
                if len(vectors) != len(pool_ids):
                    raise ValueError("question embedding output count mismatch")
                semantic_rows = []
                for question in questions:
                    query = await call_provider(
                        embedding_provider.embed_query, question["question"]
                    )
                    scores = {
                        key: _cosine(query, vector)
                        for key, vector in zip(pool_ids, vectors, strict=True)
                    }
                    semantic_rows.append(sorted(pool_ids, key=lambda key: (-scores[key], key)))
                ranked_rows = [
                    _fuse(lexical, semantic)
                    for lexical, semantic in zip(lexical_rows, semantic_rows, strict=True)
                ]
            except Exception as error:
                if local_model_strict():
                    raise
                diagnostic["degraded_reasons"].append(
                    f"embedding_inference_failed:{type(error).__name__}"
                )
        if diagnostic["degraded_reasons"]:
            diagnostic["mode"] = "degraded_lexical"

    if reranker_provider is not None and diagnostic["mode"] == "hybrid":
        if not isinstance(reranker_provider, LocalRerankerProvider):
            diagnostic["degraded_reasons"].append("strict_local_reranker_required")
        else:
            diagnostic["reranker_model_version"] = reranker_provider.model_version
            try:
                reranked = []
                for question, row in zip(questions, ranked_rows, strict=True):
                    candidates = row[:RERANK_CANDIDATE_LIMIT]
                    scores = await call_provider(
                        reranker_provider.rerank,
                        question["question"],
                        [texts[key] for key in candidates],
                    )
                    if len(scores) != len(candidates) or not all(
                        math.isfinite(score) for score in scores
                    ):
                        raise ValueError("question reranker output mismatch")
                    reranked.append(
                        sorted(candidates, key=lambda key: (-scores[candidates.index(key)], key))
                    )
                ranked_rows = reranked
                diagnostic["mode"] = "hybrid_reranked"
            except Exception as error:
                if local_model_strict():
                    raise
                diagnostic["degraded_reasons"].append(
                    f"reranker_inference_failed:{type(error).__name__}"
                )

    if diagnostic["degraded_reasons"]:
        diagnostic["mode"] = "degraded_lexical"
        ranked_rows = lexical_rows
    _validate_scope(detail, snapshot, product, dimension)
    observations = {
        fact.id: operation_observations(fact, detail.plan.competitors)
        for fact in facts if fact.id in pool
    }
    operations = {
        key: {item["operation"] for item in items} for key, items in observations.items()
    }
    requested_rows = [required_operations(question["question"]) for question in questions]
    rows = [
        _select_operation_facts(
            row, list(dict.fromkeys([*row, *lexical, *pool_ids])), requested,
            operations, quotes, quote_hints,
            question_terms(question["question"], product), observations,
        )
        for question, row, lexical, requested in zip(
            questions, ranked_rows, lexical_rows, requested_rows, strict=True
        )
    ]
    from packages.research.evidence.source_exceptions import question_exception_fact_ids
    exception_rows = [
        question_exception_fact_ids(question['question'], facts) for question in questions
    ]
    # Required independent rules precede ordinary near-duplicate observations.
    ordered = _round_robin(exception_rows, len(facts)) + _round_robin(rows, len(facts))
    by_id = {fact.id: fact for fact in facts}
    selected_list, original_bytes = [], 0
    for key in dict.fromkeys(ordered):
        size = len(canonical_json(by_id[key].model_dump(mode='json')).encode('utf-8'))
        if (len(selected_list) < TOTAL_FACT_LIMIT
                and original_bytes + size <= EXCEPTION_CLOSURE_MAX_BYTES):
            selected_list.append(key)
            original_bytes += size
    selected = tuple(selected_list)
    diagnostic['selected_original_bytes'] = original_bytes
    diagnostic['exception_closure_max_bytes'] = EXCEPTION_CLOSURE_MAX_BYTES
    diagnostic['exception_closure_complete'] = all(
        set(row) <= set(selected) for row in exception_rows
    )
    selected_set = set(selected)
    candidate_operations = set().union(*operations.values())
    diagnostic["questions"] = [
        {
            "question_id": question["question_id"],
            "fact_ids": list(dict.fromkeys([*exceptions, *row])),
            "required_exception_fact_ids": exceptions,
            "missing_exception_fact_ids": [key for key in exceptions if key not in selected_set],
            "requested_operations": list(requested),
            "selected_operations": [op for op in requested if any(
                key in selected_set and op in operations[key] for key in row
            )],
            "missing_operations": [op for op in requested if not any(
                key in selected_set and op in operations[key] for key in row
            )],
            "candidate_missing_operations": [
                op for op in requested if op not in candidate_operations
            ],
        }
        for question, row, requested, exceptions in zip(
            questions, rows, requested_rows, exception_rows, strict=True
        )
    ]
    diagnostic["selected_fact_ids"] = list(selected)
    return selected, diagnostic
