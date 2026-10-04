from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from packages.knowledge.product_benchmark import main, provider_readiness, run_product_benchmark
from packages.knowledge.product_eval_data import DatasetValidationError


def _source(
    identifier: str,
    *,
    product: str = "Phone A",
    market: str = "CN",
    role: str = "source",
    published: str | None = "2025-01-01",
    fetched: str = "2025-01-02T00:00:00+00:00",
) -> dict:
    text = "Battery capacity is 5000 mAh."
    return {
        "id": identifier,
        "title": "Battery capacity",
        "url": f"https://example.com/{identifier}",
        "text": text,
        "role": role,
        "product": product,
        "market": market,
        "published_at": published,
        "updated_at": None,
        "fetched_at": fetched,
        "source_date_status": "provided" if published else "not_provided",
        "content_hash": hashlib.sha256(text.encode()).hexdigest(),
    }


def _files(tmp_path: Path, sources: list[dict], *, status: str = "reviewed", labels: bool = True):
    query = {
        "id": "q1",
        "query": "Battery capacity",
        "product": "Phone A",
        "market": "CN",
        "category": "spec",
        "dimension": "battery",
        "as_of": "2025-06-01",
        "purpose": "evaluation",
    }
    quote = "5000 mAh"
    label = {
        "query_id": "q1",
        "expected_outcome": "answer",
        "proofs": [
            {
                "source_id": "good",
                "start": sources[0]["text"].index(quote),
                "end": sources[0]["text"].index(quote) + len(quote),
                "quote": quote,
            }
        ],
        "expected_facts": ["Phone A battery is 5000 mAh"],
        "review_status": status,
        "reviewed_by": "reviewer" if status == "reviewed" else None,
        "reviewed_at": "2025-06-02" if status == "reviewed" else None,
    }
    paths = []
    for name, rows in (
        ("corpus", sources),
        ("queries", [query]),
        ("labels", [label] if labels else []),
    ):
        path = tmp_path / f"{name}.jsonl"
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        paths.append(path)
    return paths


@pytest.mark.asyncio
async def test_sparse_uses_original_query_and_sql_filters_shared_corpus(
    tmp_path: Path, monkeypatch
):
    boundary = _source(
        "undated-nextday-offset", published=None, fetched="2025-06-02T00:00:01+08:00"
    )
    boundary["text"] = "Battery capacity after cutoff is 6000 mAh."
    boundary["content_hash"] = hashlib.sha256(boundary["text"].encode()).hexdigest()
    sources = [
        _source("good"),
        _source("wrong-product", product="Phone B"),
        _source("wrong-market", market="US"),
        _source("wrong-role", role="historical_report"),
        _source("future", published="2025-12-01"),
        _source("undated-future", published=None, fetched="2025-12-01T00:00:00+00:00"),
        boundary,
    ]
    for source in sources[1:-1]:
        source["text"] = f"Battery capacity for {source['id']} is 6000 mAh."
        source["content_hash"] = hashlib.sha256(source["text"].encode()).hexdigest()
    paths = _files(tmp_path, sources)
    from packages.knowledge import product_benchmark

    observed = []
    original = product_benchmark._BenchmarkRepository._add_scope_filters

    def inspect(self, clauses, params, **kwargs):
        original(self, clauses, params, **kwargs)
        observed.append(" ".join(clauses))

    monkeypatch.setattr(product_benchmark._BenchmarkRepository, "_add_scope_filters", inspect)
    report = await run_product_benchmark(*paths, top_k=5)
    result = report["queries"][0]
    assert result["original_query"] == "Battery capacity"
    assert report["intent_policy"] == "raw"
    assert report["intent_plan_sha256"] is None
    assert result["query_plan"]["queries"] == ("Battery capacity",)
    assert [plan["query"] for plan in result["lexical_plans"]] == ["Battery capacity"]
    assert [hit["source_id"] for hit in result["hits"]] == ["good"]
    assert result["metrics"]["recall_at_k"] == 1
    context = result["ragas_input"]["contexts"][0]
    assert context["source_id"] == "good"
    assert context["excerpt_start"] is not None
    assert result["ragas_input"]["response"] is None
    assert {item["source_id"] for item in result["date_exclusions"]} == {
        "future",
        "undated-future",
        "undated-nextday-offset",
    }
    assert all(item["reason"] == "source_date_after_as_of" for item in result["date_exclusions"])
    assert any(
        "source_published_at" in sql and "workspace_id" in sql and "source_role" in sql
        for sql in observed
    )
    assert report["model_calls"] == 0
    assert report["refusal_behavior"] == {"status": "not_run", "reason": "no answer model executed"}
    assert all(
        mode["status"] == "not_run"
        for mode in report["modes"].values()
        if mode is not report["modes"]["sparse"]
    )


@pytest.mark.asyncio
async def test_formal_rejects_zero_reviewed_gold(tmp_path: Path):
    paths = _files(tmp_path, [_source("good")], labels=False)
    with pytest.raises(DatasetValidationError, match="no reviewed labels"):
        await run_product_benchmark(*paths)


def test_formal_cli_reports_not_ready_counts_without_report(tmp_path: Path, monkeypatch, capsys):
    paths = _files(tmp_path, [_source("good")], labels=False)
    output = tmp_path / "report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "benchmark",
            "--corpus",
            str(paths[0]),
            "--queries",
            str(paths[1]),
            "--labels",
            str(paths[2]),
            "--output",
            str(output),
        ],
    )
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert not output.exists()
    message = json.loads(capsys.readouterr().err)
    assert message["status"] == "not_ready"
    assert message["counts"]["reviewed"] == 0


@pytest.mark.asyncio
async def test_candidate_diagnostic_cannot_claim_semantic_quality(tmp_path: Path):
    paths = _files(tmp_path, [_source("good")], status="candidate")
    report = await run_product_benchmark(*paths, mode="candidate-diagnostic")
    assert report["semantic_quality_verified"] is False
    assert report["dataset"]["candidate"] == 1
    assert report["queries"][0]["review_status"] == "candidate"
    assert report["factual_quality"]["status"] == "not_run"


@pytest.mark.asyncio
async def test_title_match_does_not_claim_quote_retrieval(tmp_path: Path):
    source = _source("good")
    source["text"] = "Capacity " * 160 + "5000 mAh."
    source["content_hash"] = hashlib.sha256(source["text"].encode()).hexdigest()
    paths = _files(tmp_path, [source])
    query_path = paths[1]
    query = json.loads(query_path.read_text())
    query["query"] = "Battery"
    query_path.write_text(json.dumps(query) + "\n")
    report = await run_product_benchmark(*paths)
    row = report["queries"][0]
    assert row["metrics"]["recall_at_k"] == 1
    hit = row["hits"][0]
    excerpt = source["text"][hit["excerpt_start"] : hit["excerpt_end"]]
    assert hit["chunk_content_hash"] == hashlib.sha256(excerpt.encode()).hexdigest()[:16]
    assert hit["document_content_hash"] == source["content_hash"][:16]
    assert hit["content_hash"] == source["content_hash"]
    assert row["proofs"][0]["quote_in_retrieved_excerpt"] is False
    assert row["proof_excerpt_recall"] == 0
    assert "proof_excerpt_not_retrieved" in row["failure_reasons"]


@pytest.mark.asyncio
async def test_tuning_selects_only_tuning_labels_and_reports_exclusions(tmp_path: Path):
    paths = _files(tmp_path, [_source("good")], status="candidate")
    query = json.loads(paths[1].read_text())
    label = json.loads(paths[2].read_text())
    tuning = {**query, "id": "q2", "purpose": "tuning"}
    paths[1].write_text(json.dumps(query) + "\n" + json.dumps(tuning) + "\n")
    paths[2].write_text(json.dumps(label) + "\n" + json.dumps({**label, "query_id": "q2"}) + "\n")
    report = await run_product_benchmark(*paths, mode="tuning-diagnostic")
    assert [row["query_id"] for row in report["queries"]] == ["q2"]
    assert report["selected_purpose"] == "tuning"
    assert report["selected_label_count"] == 1
    assert report["purpose_excluded_label_count"] == 1
    assert report["dataset"]["included"] == 1
    assert report["dataset"]["labels_loaded"] == 2
    assert "evaluation_excluded" in report["dataset_reasons"]
    evaluation = await run_product_benchmark(*paths, mode="candidate-diagnostic")
    assert [row["query_id"] for row in evaluation["queries"]] == ["q1"]
    assert evaluation["purpose_excluded_label_count"] == 1


@pytest.mark.asyncio
async def test_formal_rejects_only_tuning_reviewed_labels(tmp_path: Path):
    paths = _files(tmp_path, [_source("good")])
    query = json.loads(paths[1].read_text())
    query["purpose"] = "tuning"
    paths[1].write_text(json.dumps(query) + "\n")
    with pytest.raises(DatasetValidationError, match="no reviewed labels"):
        await run_product_benchmark(*paths)


@pytest.mark.asyncio
async def test_tuning_does_not_fall_back_to_evaluation(tmp_path: Path):
    paths = _files(tmp_path, [_source("good")], status="candidate")
    with pytest.raises(ValueError, match="no tuning labels"):
        await run_product_benchmark(*paths, mode="tuning-diagnostic")


@pytest.mark.asyncio
async def test_strict_and_bounded_share_raw_query_but_recall_differs():
    root = Path(__file__).resolve().parents[3]
    paths = [
        root / f"eval/product-research-tuning-{kind}.jsonl"
        for kind in ("corpus", "queries", "labels")
    ]
    strict = await run_product_benchmark(
        *paths, mode="tuning-diagnostic", lexical_policy="strict"
    )
    bounded = await run_product_benchmark(
        *paths, mode="tuning-diagnostic", lexical_policy="bounded"
    )
    assert strict["model_calls"] == bounded["model_calls"] == 0
    assert strict["selected_label_count"] == bounded["selected_label_count"] == 14
    assert all(
        a["original_query"] == b["original_query"]
        for a, b in zip(strict["queries"], bounded["queries"], strict=True)
    )
    by_id_strict = {row["query_id"]: row for row in strict["queries"]}
    by_id_bounded = {row["query_id"]: row for row in bounded["queries"]}
    answer_ids = {f"lexical-tuning-{index:03d}" for index in range(1, 10)}
    insufficient_ids = {f"lexical-tuning-{index:03d}" for index in range(10, 15)}
    for rows in (by_id_strict, by_id_bounded):
        assert {query_id for query_id, row in rows.items()
                if row["expected_outcome"] == "answer"} == answer_ids
        assert {query_id for query_id, row in rows.items()
                if row["expected_outcome"] == "insufficient"} == insufficient_ids
        assert set(rows) == answer_ids | insufficient_ids
    assert any(
        by_id_bounded[query_id]["metrics"]["recall_at_k"]
        > by_id_strict[query_id]["metrics"]["recall_at_k"]
        for query_id in answer_ids
    )
    for query_id in insufficient_ids:
        for rows in (by_id_strict, by_id_bounded):
            assert rows[query_id]["hits"] == []
            assert rows[query_id]["metrics"] is None
    assert strict["lexical_policy"]["fallback_enabled"] is False
    assert bounded["lexical_policy"]["fallback_enabled"] is True
    assert strict["queries"][0]["lexical_plan"]["fallback_query"] is None
    assert bounded["queries"][0]["lexical_plan"]["fallback_query"]
    assert all(
        hit["metadata"]["lexical_retrieval"] is None
        for row in strict["queries"] for hit in row["hits"]
    )
    assert (
        bounded["queries"][0]["hits"][0]["metadata"]["lexical_retrieval"]["path"]
        == "fallback_body"
    )
    assert bounded["factual_quality"]["status"] == "not_run"
    assert all(
        rows[query_id]["proof_excerpt_recall"] is None
        and rows[query_id]["non_gold_source_count"] is None
        for rows in (by_id_strict, by_id_bounded) for query_id in insufficient_ids
    )


@pytest.mark.asyncio
async def test_non_gold_source_count_deduplicates_multiple_chunks(tmp_path: Path):
    good = _source("good")
    other = _source("other")
    other["text"] = "Battery capacity is 6000 mAh. " * 100
    other["content_hash"] = hashlib.sha256(other["text"].encode()).hexdigest()
    paths = _files(tmp_path, [good, other])
    report = await run_product_benchmark(*paths, top_k=5)
    row = report["queries"][0]
    assert sum(hit["source_id"] == "other" for hit in row["hits"]) >= 2
    assert row["non_gold_source_count"] == 1
    assert row["metrics"]["recall_at_k"] == 1


@pytest.mark.asyncio
async def test_invalid_lexical_policy_is_rejected(tmp_path: Path):
    paths = _files(tmp_path, [_source("good")])
    with pytest.raises(ValueError, match="lexical_policy"):
        await run_product_benchmark(*paths, lexical_policy="unbounded")


@pytest.mark.asyncio
async def test_same_query_new_as_of_cannot_reuse_later_snapshot(tmp_path: Path):
    future = _source("future", published="2025-12-01")
    future["text"] = "Battery capacity is 6000 mAh."
    future["content_hash"] = hashlib.sha256(future["text"].encode()).hexdigest()
    paths = _files(tmp_path, [_source("good"), future])
    query = json.loads(paths[1].read_text())
    label = json.loads(paths[2].read_text())
    query["as_of"] = "2026-01-01"
    earlier = {**query, "id": "q2", "as_of": "2025-06-01"}
    paths[1].write_text(json.dumps(query) + "\n" + json.dumps(earlier) + "\n")
    paths[2].write_text(json.dumps(label) + "\n" + json.dumps({**label, "query_id": "q2"}) + "\n")
    report = await run_product_benchmark(*paths, top_k=5)
    assert "future" in [hit["source_id"] for hit in report["queries"][0]["hits"]]
    assert [hit["source_id"] for hit in report["queries"][1]["hits"]] == ["good"]


@pytest.mark.asyncio
async def test_distinct_sources_with_same_body_cannot_share_a_gold_document(tmp_path: Path):
    paths = _files(tmp_path, [_source("other"), _source("good")])
    with pytest.raises(ValueError, match="distinct sources share one stored document"):
        await run_product_benchmark(*paths)


@pytest.mark.asyncio
async def test_same_url_new_body_cannot_archive_fixed_corpus_source(tmp_path: Path):
    good = _source("good")
    other = _source("other")
    other["url"] = good["url"]
    other["text"] = "Battery capacity is 6000 mAh."
    other["content_hash"] = hashlib.sha256(other["text"].encode()).hexdigest()
    paths = _files(tmp_path, [good, other])
    with pytest.raises(ValueError, match="fixed corpus source is not active"):
        await run_product_benchmark(*paths)


@pytest.mark.asyncio
async def test_basic_iso_fetched_date_is_normalized_for_as_of_sql(tmp_path: Path):
    good = _source("good", published=None, fetched="20250102T000000+0000")
    paths = _files(tmp_path, [good])
    report = await run_product_benchmark(*paths)
    assert [hit["source_id"] for hit in report["queries"][0]["hits"]] == ["good"]
    assert report["queries"][0]["date_exclusions"] == []


@pytest.mark.parametrize(
    "status",
    [
        {
            "requested_provider": "hash",
            "effective_provider": "hash",
            "model_version": "hash",
            "dimensions": 64,
            "degraded": False,
        },
        {
            "requested_provider": "x",
            "effective_provider": "uninitialized",
            "model_version": None,
            "dimensions": None,
            "degraded": False,
        },
        {
            "requested_provider": "x",
            "effective_provider": "x",
            "model_version": "x",
            "dimensions": 1024,
            "degraded": True,
        },
        {
            "requested_provider": "custom",
            "effective_provider": "real",
            "model_version": "real-v1",
            "dimensions": 1024,
            "degraded": False,
        },
    ],
)
def test_nonsemantic_provider_is_not_ready(status):
    assert provider_readiness(status)["semantic_ready"] is False


@pytest.mark.asyncio
async def test_structured_format_suffix_searches_factual_query(tmp_path: Path):
    paths = _files(tmp_path, [_source("good")])
    query = json.loads(paths[1].read_text())
    query["query"] = "Battery capacity; answer in Chinese and include citations"
    paths[1].write_text(json.dumps(query) + "\n")
    raw = await run_product_benchmark(*paths)
    structured = await run_product_benchmark(*paths, intent_policy="structured")
    row = structured["queries"][0]
    assert raw["queries"][0]["query_plan"]["queries"] == (query["query"],)
    assert row["original_query"] == row["ragas_input"]["query"] == query["query"]
    assert row["query_plan"]["origin"] == "format_suffix"
    assert row["query_plan"]["queries"] == ("Battery capacity",)
    assert [plan["query"] for plan in row["lexical_plans"]] == ["Battery capacity"]
    assert row["lexical_plan"]["legacy_original"] is True
    assert [hit["source_id"] for hit in row["hits"]] == ["good"]
    assert row["fact_query_results"][0]["query"] == "Battery capacity"


@pytest.mark.asyncio
async def test_explicit_two_facts_report_actual_groups_and_proofs(tmp_path: Path):
    first = _source("good")
    second = _source("warranty")
    second["text"] = "Warranty coverage is 24 months."
    second["content_hash"] = hashlib.sha256(second["text"].encode()).hexdigest()
    paths = _files(tmp_path, [first, second])
    query = json.loads(paths[1].read_text())
    query["query"] = "Battery capacity and warranty coverage; answer in Chinese"
    paths[1].write_text(json.dumps(query) + "\n")
    label = json.loads(paths[2].read_text())
    label["proofs"].append({"source_id": "warranty", "start": 21, "end": 30,
                            "quote": "24 months"})
    label["expected_facts"] = ["Secret expected fact never used as a query"]
    paths[2].write_text(json.dumps(label) + "\n")
    intent_path = tmp_path / "intents.jsonl"
    intent_path.write_text(json.dumps({"query_id": "q1", "intent": {
        "fact_queries": ["Battery capacity", "Warranty coverage"]}}) + "\n")
    report = await run_product_benchmark(
        *paths, intent_policy="structured", intent_plan_path=intent_path
    )
    row = report["queries"][0]
    assert report["intent_plan_sha256"] == hashlib.sha256(intent_path.read_bytes()).hexdigest()
    assert row["query_plan"]["origin"] == "explicit"
    assert row["query_plan"]["queries"] == ("Battery capacity", "Warranty coverage")
    assert [plan["query"] for plan in row["lexical_plans"]] == list(row["query_plan"]["queries"])
    assert {hit["source_id"] for hit in row["hits"]} == {"good", "warranty"}
    assert row["metrics"]["recall_at_k"] == row["proof_excerpt_recall"] == 1
    assert {item["query"] for item in row["fact_query_results"]} == set(
        row["query_plan"]["queries"]
    )
    assert {chunk_id for group in row["fact_query_results"] for chunk_id in group["chunk_ids"]} == {
        hit["chunk_id"] for hit in row["hits"]
    }
    assert all("Secret expected fact" not in item for item in row["query_plan"]["queries"])


@pytest.mark.asyncio
@pytest.mark.parametrize("rows,error", [
    ([{"query_id": "q1", "intent": {"fact_queries": ["Battery"]}, "expected_facts": []}], "keys"),
    ([{"query_id": "q1", "intent": {"fact_queries": ["Battery"], "source_id": "good"}}], "intent"),
    ([{"query_id": "unknown", "intent": {"fact_queries": ["Battery"]}}], "query_id"),
    ([{"query_id": " ", "intent": {"fact_queries": ["Battery"]}}], "query_id"),
    ([{"query_id": "q1", "intent": {"fact_queries": ["Battery"]}},
      {"query_id": "q1", "intent": {"fact_queries": ["Battery"]}}], "duplicate"),
])
async def test_intent_plan_rejects_invalid_rows(tmp_path: Path, rows: list[dict], error: str):
    paths = _files(tmp_path, [_source("good")])
    intent_path = tmp_path / "intents.jsonl"
    intent_path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(ValueError, match=error):
        await run_product_benchmark(
            *paths, intent_policy="structured", intent_plan_path=intent_path
        )


@pytest.mark.asyncio
async def test_raw_rejects_intent_plan(tmp_path: Path):
    paths = _files(tmp_path, [_source("good")])
    plan = tmp_path / "intents.jsonl"
    plan.write_text('{"query_id":"q1","intent":{"fact_queries":["Battery"]}}\n')
    with pytest.raises(ValueError, match="raw"):
        await run_product_benchmark(*paths, intent_plan_path=plan)


def test_cli_accepts_structured_intent_file(tmp_path: Path, monkeypatch):
    paths = _files(tmp_path, [_source("good")])
    plan = tmp_path / "intents.jsonl"
    plan.write_text('{"query_id":"q1","intent":{"fact_queries":["Battery capacity"]}}\n')
    output = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", [
        "benchmark", "--corpus", str(paths[0]), "--queries", str(paths[1]),
        "--labels", str(paths[2]), "--intent-policy", "structured",
        "--intent-plan", str(plan), "--output", str(output),
    ])
    assert main() == 0
    report = json.loads(output.read_text())
    assert report["intent_policy"] == "structured"
    assert report["queries"][0]["query_plan"]["origin"] == "explicit"


@pytest.mark.asyncio
async def test_intent_plan_rejects_nonselected_purpose(tmp_path: Path):
    paths = _files(tmp_path, [_source("good")])
    query = json.loads(paths[1].read_text())
    label = json.loads(paths[2].read_text())
    paths[1].write_text(json.dumps(query) + "\n" + json.dumps({
        **query, "id": "q2", "purpose": "tuning",
    }) + "\n")
    paths[2].write_text(json.dumps(label) + "\n" + json.dumps({
        **label, "query_id": "q2",
    }) + "\n")
    plan = tmp_path / "intents.jsonl"
    plan.write_text('{"query_id":"q2","intent":{"fact_queries":["Battery"]}}\n')
    with pytest.raises(ValueError, match="query_id"):
        await run_product_benchmark(
            *paths, mode="candidate-diagnostic", intent_policy="structured",
            intent_plan_path=plan,
        )


@pytest.mark.asyncio
async def test_retrieval_latency_excludes_lexical_report_generation(
    tmp_path: Path, monkeypatch
):
    from types import SimpleNamespace

    from packages.knowledge import product_benchmark

    paths = _files(tmp_path, [_source("good")])
    clock = {"value": 0}
    original = product_benchmark._lexical_plan

    def counted_plan(*args):
        clock["value"] += 1
        return original(*args)

    monkeypatch.setattr(product_benchmark, "_lexical_plan", counted_plan)
    monkeypatch.setattr(
        product_benchmark, "time",
        SimpleNamespace(perf_counter=lambda: clock["value"]),
    )
    report = await run_product_benchmark(*paths)
    assert clock["value"] == 2
    assert report["queries"][0]["latency_ms"] == 0
