"""Validated, local product research evaluation data.

Proof offsets address the saved ``text`` excerpt, not the original web page.
Dataset metadata reports provenance; it does not certify semantic correctness.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse


class DatasetValidationError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        counts: dict[str, int] | None = None,
        reasons: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.counts = counts or {}
        self.reasons = reasons or []


@dataclass(frozen=True)
class ProductEvalDataset:
    sources: dict[str, dict]
    queries: dict[str, dict]
    labels: dict[str, dict]
    counts: dict[str, int]
    reasons: list[str]
    semantic_quality_verified: bool = False


def _fail(message: str) -> None:
    raise DatasetValidationError(message)


def _nonempty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{field} must be a nonempty string")
    return value


def _date(value: object, field: str, *, required: bool = False) -> date | None:
    if value is None and not required:
        return None
    text = _nonempty(value, field)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        _fail(f"{field} must be an ISO-8601 date or datetime")


def _read_jsonl(path: str | Path, kind: str, id_field: str) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for line_number, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            _fail(f"{kind} line {line_number}: invalid JSON: {exc}")
        if not isinstance(row, dict):
            _fail(f"{kind} line {line_number}: expected object")
        identifier = _nonempty(row.get(id_field), f"{kind}.{id_field}")
        if identifier in rows:
            _fail(f"duplicate {kind} {id_field}: {identifier}")
        rows[identifier] = row
    return rows


def _validate_source(source: dict) -> bool:
    source_id = source["id"]
    text = _nonempty(source.get("text"), f"source {source_id} text")
    url = _nonempty(source.get("url"), f"source {source_id} URL")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        _fail(f"source {source_id} URL must be HTTPS")
    if source.get("role") not in {"source", "historical_report"}:
        _fail(f"source {source_id} role must be source or historical_report")
    _nonempty(source.get("product"), f"source {source_id} product")
    _nonempty(source.get("market"), f"source {source_id} market")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if source.get("content_hash") != digest:
        _fail(f"source {source_id} content_hash does not match saved text")
    for field in ("published_at", "updated_at"):
        if field not in source:
            _fail(f"source {source_id} {field} must be explicit, even when null")
    published = _date(source["published_at"], f"source {source_id} published_at")
    updated = _date(source["updated_at"], f"source {source_id} updated_at")
    _date(source.get("fetched_at"), f"source {source_id} fetched_at", required=True)
    unknown = published is None and updated is None
    required_status = "not_provided" if unknown else "provided"
    if source.get("source_date_status") != required_status:
        _fail(f"source {source_id} source_date_status must be {required_status}")
    return unknown


def _validate_query(query: dict) -> None:
    query_id = query["id"]
    for field in ("query", "product", "market"):
        _nonempty(query.get(field), f"query {query_id} {field}")
    if query.get("purpose") not in {"evaluation", "tuning"}:
        _fail(f"query {query_id} purpose must be evaluation or tuning")
    as_of = query.get("as_of")
    if not isinstance(as_of, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of):
        _fail(f"query {query_id} as_of must be YYYY-MM-DD")
    _date(as_of, f"query {query_id} as_of", required=True)


def _validate_label(label: dict, queries: dict[str, dict], sources: dict[str, dict]) -> None:
    query_id = label["query_id"]
    if query_id not in queries:
        _fail(f"label {query_id} refers to unknown query")
    outcome = label.get("expected_outcome")
    if outcome not in {"answer", "clarify", "insufficient"}:
        _fail(f"label {query_id} expected_outcome must be explicit")
    status = label.get("review_status")
    if status not in {"candidate", "reviewed"}:
        _fail(f"label {query_id} review_status must be candidate or reviewed")
    if status == "reviewed":
        _nonempty(label.get("reviewed_by"), f"label {query_id} reviewed_by")
        _date(label.get("reviewed_at"), f"label {query_id} reviewed_at", required=True)
    elif label.get("reviewed_by") or label.get("reviewed_at"):
        _fail(f"label {query_id} candidate cannot claim human review")
    proofs = label.get("proofs")
    facts = label.get("expected_facts")
    if not isinstance(proofs, list):
        _fail(f"label {query_id} proofs must be a list")
    if not isinstance(facts, list) or any(
        not isinstance(fact, str) or not fact.strip() for fact in facts
    ):
        _fail(f"label {query_id} expected_facts must be a list of nonempty strings")
    if outcome == "answer" and not proofs:
        _fail(f"label {query_id} answer requires a proof")
    if outcome == "answer" and not facts:
        _fail(f"label {query_id} answer requires expected_facts")
    query = queries[query_id]
    as_of = _date(query.get("as_of"), f"query {query_id} as_of")
    for proof in proofs:
        if not isinstance(proof, dict):
            _fail(f"label {query_id} proof must be an object")
        source_id = _nonempty(proof.get("source_id"), f"label {query_id} proof source_id")
        if source_id not in sources:
            _fail(f"label {query_id} proof refers to unknown source {source_id}")
        source = sources[source_id]
        start, end = proof.get("start"), proof.get("end")
        if (
            type(start) is not int
            or type(end) is not int
            or start < 0
            or end <= start
            or end > len(source["text"])
        ):
            _fail(f"label {query_id} proof offset outside saved source text")
        quote = _nonempty(proof.get("quote"), f"label {query_id} proof quote")
        if source["text"][start:end] != quote:
            _fail(f"label {query_id} proof quote does not match saved source text")
        for field in ("product", "market"):
            if source[field] != query[field]:
                _fail(f"label {query_id} proof {field} differs from query")
        if outcome == "answer" and as_of is not None:
            source_dates = [
                _date(source[field], f"source {source_id} {field}")
                for field in ("published_at", "updated_at")
            ]
            if any(value > as_of for value in source_dates if value is not None):
                _fail(f"label {query_id} source date after query as_of")
            if (
                not any(source_dates)
                and _date(source["fetched_at"], f"source {source_id} fetched_at") > as_of
            ):
                _fail(f"label {query_id} unknown source date cannot support historical as_of")


def load_dataset(
    corpus_path: str | Path,
    queries_path: str | Path,
    labels_path: str | Path,
    *,
    require_reviewed: bool = True,
) -> ProductEvalDataset:
    """Load fixed excerpts and human review labels from local JSONL files.

    Formal mode includes reviewed labels only. Diagnostic mode may include
    candidates, but ``semantic_quality_verified`` is always false: a review
    record alone cannot prove the underlying claim is factually correct.
    """
    sources = _read_jsonl(corpus_path, "source", "id")
    queries = _read_jsonl(queries_path, "query", "id")
    all_labels = _read_jsonl(labels_path, "label", "query_id")
    unknown_dates = sum(_validate_source(source) for source in sources.values())
    for query in queries.values():
        _validate_query(query)
    for label in all_labels.values():
        _validate_label(label, queries, sources)
    candidate_count = sum(label["review_status"] == "candidate" for label in all_labels.values())
    reviewed_count = len(all_labels) - candidate_count
    counts = {
        "queries": len(queries),
        "unlabeled": len(queries) - len(all_labels),
        "candidate": candidate_count,
        "reviewed": reviewed_count,
    }
    reasons: list[str] = []
    if unknown_dates:
        counts["source_date_unknown"] = unknown_dates
        reasons.append("source_date_unknown")
    if candidate_count and require_reviewed:
        reasons.append("candidate_excluded")
    tuning_excluded = sum(
        label["review_status"] == "reviewed" and queries[query_id]["purpose"] == "tuning"
        for query_id, label in all_labels.items()
    )
    if tuning_excluded and require_reviewed:
        reasons.append("tuning_excluded")
    labels = {
        query_id: label
        for query_id, label in all_labels.items()
        if not require_reviewed
        or (label["review_status"] == "reviewed" and queries[query_id]["purpose"] == "evaluation")
    }
    counts["included"] = len(labels)
    if require_reviewed and not labels:
        raise DatasetValidationError(
            "no reviewed labels available for formal evaluation", counts=counts, reasons=reasons
        )
    return ProductEvalDataset(sources, queries, labels, counts, reasons)
