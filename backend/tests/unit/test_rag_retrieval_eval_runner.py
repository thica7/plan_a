from __future__ import annotations

import pytest

from packages.knowledge.benchmark import load_benchmark_cases, run_benchmark


@pytest.mark.asyncio
async def test_benchmark_executes_retrieval_admission_and_citations():
    cases = load_benchmark_cases()
    assert {
        "long_tail_chunk",
        "chinese",
        "mixed_language",
        "index_recovery",
        "missing_evidence",
    } <= {case["scenario"] for case in cases}
    report = await run_benchmark(top_k=3)
    assert report["provider"]["effective_provider"] == "hash"
    assert report["model_calls"] == 0
    assert set(report["modes"]) == {"sparse", "hybrid", "rerank"}
    for mode in report["modes"].values():
        assert 0 <= mode["recall_at_k"] <= 1
        assert 0 <= mode["mrr"] <= 1
        assert 0 <= mode["ndcg_at_k"] <= 1
        assert mode["latency_ms"]["p95"] >= 0
        assert mode["citation_correctness"] == 1
        assert mode["stale_source_misuse"] == 0
        assert mode["scope_leaks"] == 0
        missing = next(item for item in mode["queries"] if item["scenario"] == "missing_evidence")
        assert missing["insufficient_evidence"] is True
        assert missing["citations"] == []
    recovered = report["index_recovery"]
    assert recovered["same_chunk_ids"] is True
    assert recovered["status"] == "ready"


@pytest.mark.asyncio
async def test_same_corpus_shows_tail_and_chinese_regressions_in_legacy_sparse():
    baseline = await run_benchmark(top_k=3, legacy_sparse=True)
    queries = {query["scenario"]: query for query in baseline["modes"]["sparse"]["queries"]}
    assert queries["chinese"]["hits"] == []
    assert all("xenon" not in hit["text"] for hit in queries["long_tail_chunk"]["hits"])
