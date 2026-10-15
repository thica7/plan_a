import pytest


@pytest.mark.asyncio
async def test_comparison_reuses_providers_and_fixed_broad_top3_for_all_arms(monkeypatch, tmp_path):
    import scripts.eval_independent_retrieval as runner

    seen = []
    embedding, reranker = object(), object()

    async def benchmark(*paths, **kwargs):
        seen.append((paths, kwargs))
        return {"queries": [], "external_model_calls": 0}

    monkeypatch.setattr(runner, "run_product_benchmark", benchmark)
    paths = tuple(tmp_path / name for name in ("corpus", "queries", "labels"))
    result = await runner.compare_retrieval(paths, embedding, reranker)
    assert list(result) == ["sparse", "hybrid", "hybrid_rerank",
                            "sparse_structured", "hybrid_structured", "hybrid_rerank_structured"]
    assert [row[1]["retrieval_mode"] for row in seen] == ["sparse", "hybrid", "hybrid"] * 2
    assert [row[1]["enable_rerank"] for row in seen] == [False, False, True] * 2
    assert [row[1]["intent_policy"] for row in seen] == ["raw"] * 3 + ["structured"] * 3
    assert all(
        row[0] == paths and row[1]["top_k"] == 3 and row[1]["product_scope"] == "broad"
        for row in seen
    )
    assert seen[1][1]["embedding_provider"] is embedding
    assert seen[2][1]["embedding_provider"] is embedding
    assert seen[2][1]["reranker_provider"] is reranker
