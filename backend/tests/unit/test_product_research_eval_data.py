from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from packages.knowledge.product_eval_data import DatasetValidationError, load_dataset


def _write(path: Path, rows: list[dict]) -> Path:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )
    return path


def _source() -> dict:
    text = "iPhone 15 配备 4800 万像素主摄。"
    return {
        "id": "apple-iphone15-camera",
        "url": "https://www.apple.com.cn/iphone-15/specs/",
        "text": text,
        "role": "source",
        "product": "iPhone 15",
        "market": "中国大陆",
        "published_at": "2023-09-13",
        "updated_at": None,
        "source_date_status": "provided",
        "fetched_at": "2026-10-04T10:00:00+08:00",
        "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def _query() -> dict:
    return {
        "id": "q-1",
        "query": "iPhone 15 的主摄像素是多少？",
        "product": "iPhone 15",
        "market": "中国大陆",
        "as_of": "2026-10-04",
        "purpose": "evaluation",
    }


def _label(source: dict, *, status: str = "reviewed") -> dict:
    quote = "4800 万像素"
    start = source["text"].index(quote)
    return {
        "query_id": "q-1",
        "expected_outcome": "answer",
        "proofs": [
            {"source_id": source["id"], "start": start, "end": start + len(quote), "quote": quote}
        ],
        "expected_facts": ["iPhone 15 主摄为 4800 万像素"],
        "review_status": status,
        "reviewed_by": "human-reviewer" if status == "reviewed" else None,
        "reviewed_at": "2026-10-04T12:00:00+08:00" if status == "reviewed" else None,
    }


def _load(tmp_path: Path, sources: list[dict], queries: list[dict], labels: list[dict], **kwargs):
    return load_dataset(
        _write(tmp_path / "corpus.jsonl", sources),
        _write(tmp_path / "queries.jsonl", queries),
        _write(tmp_path / "labels.jsonl", labels),
        **kwargs,
    )


def test_reviewed_answer_loads_with_exact_local_text_offsets(tmp_path: Path) -> None:
    source = _source()
    dataset = _load(tmp_path, [source], [_query()], [_label(source)])
    assert len(dataset.sources) == len(dataset.queries) == len(dataset.labels) == 1
    assert dataset.counts == {
        "queries": 1,
        "unlabeled": 0,
        "candidate": 0,
        "reviewed": 1,
        "included": 1,
    }
    assert dataset.semantic_quality_verified is False


def test_draft_queries_are_unlabeled_and_never_negative(tmp_path: Path) -> None:
    query_path = (
        Path(__file__).resolve().parents[3] / "eval" / "product-research-queries-draft.jsonl"
    )
    dataset = load_dataset(
        _write(tmp_path / "corpus.jsonl", []),
        query_path,
        _write(tmp_path / "labels.jsonl", []),
        require_reviewed=False,
    )
    assert dataset.counts == {
        "queries": 50,
        "unlabeled": 50,
        "candidate": 0,
        "reviewed": 0,
        "included": 0,
    }
    assert dataset.labels == {}
    assert dataset.semantic_quality_verified is False
    with pytest.raises(DatasetValidationError, match="no reviewed labels"):
        load_dataset(tmp_path / "corpus.jsonl", query_path, tmp_path / "labels.jsonl")


def test_repository_product_research_files_load_only_as_diagnostic() -> None:
    eval_dir = Path(__file__).resolve().parents[3] / "eval"
    paths = (
        eval_dir / "product-research-corpus.jsonl",
        eval_dir / "product-research-queries-draft.jsonl",
        eval_dir / "product-research-labels.jsonl",
    )
    diagnostic = load_dataset(*paths, require_reviewed=False)
    assert diagnostic.counts["queries"] == 50
    assert diagnostic.counts["candidate"] > 0
    assert diagnostic.counts["reviewed"] == 0
    assert diagnostic.counts["included"] == diagnostic.counts["candidate"]
    assert diagnostic.semantic_quality_verified is False
    with pytest.raises(DatasetValidationError, match="no reviewed labels") as exc:
        load_dataset(*paths)
    assert exc.value.counts["included"] == 0
    assert "candidate_excluded" in exc.value.reasons


def test_candidate_excluded_from_formal_eval_and_available_for_diagnosis(tmp_path: Path) -> None:
    source = _source()
    label = _label(source, status="candidate")
    diagnostic = _load(tmp_path, [source], [_query()], [label], require_reviewed=False)
    assert diagnostic.labels["q-1"] == label
    assert diagnostic.counts["candidate"] == 1
    assert diagnostic.semantic_quality_verified is False
    with pytest.raises(DatasetValidationError, match="no reviewed labels") as exc:
        _load(tmp_path, [source], [_query()], [label])
    assert exc.value.counts["candidate"] == 1
    assert "candidate_excluded" in exc.value.reasons


@pytest.mark.parametrize("kind", ["source", "query", "label"])
def test_duplicate_ids_rejected(tmp_path: Path, kind: str) -> None:
    source = _source()
    sources, queries, labels = [source], [_query()], [_label(source)]
    {"source": sources, "query": queries, "label": labels}[kind].append(
        dict({"source": sources, "query": queries, "label": labels}[kind][0])
    )
    with pytest.raises(DatasetValidationError, match="duplicate"):
        _load(tmp_path, sources, queries, labels)


@pytest.mark.parametrize(
    "mutation,pattern",
    [
        (lambda s, q, label: label["proofs"][0].update(source_id="missing"), "unknown source"),
        (lambda s, q, label: label["proofs"][0].update(quote="wrong"), "quote"),
        (lambda s, q, label: label["proofs"][0].update(end=999), "offset"),
        (lambda s, q, label: s.update(content_hash="0" * 64), "content_hash"),
        (lambda s, q, label: s.update(market="美国"), "market"),
        (lambda s, q, label: s.update(product="iPhone 15 Pro"), "product"),
        (lambda s, q, label: s.update(url="http://example.com"), "HTTPS"),
        (lambda s, q, label: s.update(published_at=None, updated_at=None), "source_date_status"),
        (lambda s, q, label: s.update(fetched_at=None), "fetched_at"),
        (lambda s, q, label: label.update(reviewed_by=None), "reviewed_by"),
        (lambda s, q, label: label.update(expected_facts=[]), "expected_facts"),
        (lambda s, q, label: label.update(proofs=[]), "proof"),
    ],
)
def test_invalid_evidence_or_review_rejected(tmp_path: Path, mutation, pattern: str) -> None:
    source, query = _source(), _query()
    label = _label(source)
    mutation(source, query, label)
    with pytest.raises(DatasetValidationError, match=pattern):
        _load(tmp_path, [source], [query], [label])


def test_candidate_cannot_claim_human_review(tmp_path: Path) -> None:
    source = _source()
    label = _label(source, status="candidate")
    label["reviewed_by"] = "someone"
    with pytest.raises(DatasetValidationError, match="candidate"):
        _load(tmp_path, [source], [_query()], [label], require_reviewed=False)


def test_clarify_is_explicit_not_inferred_from_empty_proofs(tmp_path: Path) -> None:
    source = _source()
    label = _label(source)
    label.update(expected_outcome="clarify", proofs=[], expected_facts=[])
    dataset = _load(tmp_path, [source], [_query()], [label])
    assert dataset.labels["q-1"]["expected_outcome"] == "clarify"
    del label["expected_outcome"]
    with pytest.raises(DatasetValidationError, match="expected_outcome"):
        _load(tmp_path, [source], [_query()], [label])


def test_purpose_must_be_explicit_and_valid(tmp_path: Path) -> None:
    source = _source()
    query = _query()
    query["purpose"] = "unknown"
    with pytest.raises(DatasetValidationError, match="purpose"):
        _load(tmp_path, [source], [query], [_label(source)])


def test_unknown_query_reference_rejected(tmp_path: Path) -> None:
    source = _source()
    label = _label(source)
    label["query_id"] = "missing"
    with pytest.raises(DatasetValidationError, match="unknown query"):
        _load(tmp_path, [source], [_query()], [label])


def test_tuning_reviewed_label_cannot_create_formal_gold(tmp_path: Path) -> None:
    source = _source()
    query = _query()
    query["purpose"] = "tuning"
    label = _label(source)
    diagnostic = _load(tmp_path, [source], [query], [label], require_reviewed=False)
    assert diagnostic.labels["q-1"] == label
    assert diagnostic.queries["q-1"]["purpose"] == "tuning"
    assert diagnostic.counts["included"] == 1
    with pytest.raises(DatasetValidationError, match="no reviewed labels") as exc:
        _load(tmp_path, [source], [query], [label])
    assert exc.value.counts["reviewed"] == 1
    assert exc.value.counts["included"] == 0
    assert "tuning_excluded" in exc.value.reasons


def test_formal_mode_includes_only_evaluation_reviewed_labels(tmp_path: Path) -> None:
    source = _source()
    evaluation = _query()
    tuning = dict(evaluation, id="q-2", purpose="tuning")
    evaluation_label = _label(source)
    tuning_label = dict(evaluation_label, query_id="q-2")
    dataset = _load(
        tmp_path,
        [source],
        [evaluation, tuning],
        [evaluation_label, tuning_label],
    )
    assert list(dataset.labels) == ["q-1"]
    assert dataset.counts["reviewed"] == 2
    assert dataset.counts["included"] == 1
    assert "tuning_excluded" in dataset.reasons


def test_explicit_unknown_source_date_is_reported(tmp_path: Path) -> None:
    source = _source()
    source.update(published_at=None, updated_at=None, source_date_status="not_provided")
    dataset = _load(tmp_path, [source], [_query()], [_label(source)])
    assert dataset.counts["source_date_unknown"] == 1
    assert "source_date_unknown" in dataset.reasons


def test_unknown_source_date_cannot_support_historical_as_of(tmp_path: Path) -> None:
    source = _source()
    source.update(published_at=None, updated_at=None, source_date_status="not_provided")
    query = _query()
    query["as_of"] = "2024-01-01"
    with pytest.raises(DatasetValidationError, match="historical as_of"):
        _load(tmp_path, [source], [query], [_label(source)])


def test_future_source_date_cannot_support_as_of(tmp_path: Path) -> None:
    source = _source()
    source["published_at"] = "2026-10-04"
    query = _query()
    query["as_of"] = "2024-01-01"
    with pytest.raises(DatasetValidationError, match="after query as_of"):
        _load(tmp_path, [source], [query], [_label(source)])


def test_query_as_of_must_be_explicit_day_not_timestamp(tmp_path: Path) -> None:
    source = _source()
    query = _query()
    query["as_of"] = "2026-10-04T08:00:00+08:00"
    with pytest.raises(DatasetValidationError, match="as_of.*YYYY-MM-DD"):
        _load(tmp_path, [source], [query], [_label(source)])
    query.pop("as_of")
    with pytest.raises(DatasetValidationError, match="as_of.*YYYY-MM-DD"):
        _load(tmp_path, [source], [query], [_label(source)])
