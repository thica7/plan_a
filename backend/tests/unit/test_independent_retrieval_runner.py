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


@pytest.mark.asyncio
async def test_candidate_comparison_keeps_mode_and_product_scope_in_every_arm(monkeypatch, tmp_path):
    import scripts.eval_independent_retrieval as runner

    seen = []

    async def benchmark(*paths, **kwargs):
        seen.append(kwargs)
        return {}

    monkeypatch.setattr(runner, "run_product_benchmark", benchmark)
    await runner.compare_retrieval(
        (tmp_path / "c", tmp_path / "q", tmp_path / "l"), object(), object(),
        evaluation_mode="candidate-diagnostic", product_scope="product",
    )
    assert len(seen) == 6
    assert all(row["mode"] == "candidate-diagnostic" and row["product_scope"] == "product"
               for row in seen)


def test_new_candidates_require_explicit_diagnostic_and_inputs_cannot_drift(tmp_path):
    import json

    import scripts.eval_independent_retrieval as runner
    from packages.knowledge.product_eval_data import DatasetValidationError

    source = runner.ROOT / "eval/product-research-independent-v1"
    prefix = tmp_path / "candidate"
    for kind in ("corpus", "queries", "labels"):
        rows = [json.loads(line) for line in source.with_name(source.name + f"-{kind}.jsonl")
                .read_text().splitlines() if line.strip()]
        if kind == "labels":
            for row in rows:
                row.update(review_status="candidate", reviewed_by=None, reviewed_at=None)
        prefix.with_name(prefix.name + f"-{kind}.jsonl").write_text(
            "\n".join(json.dumps(row) for row in rows) + "\n"
        )
    with pytest.raises(DatasetValidationError):
        runner.load_evaluation_inputs(prefix, "formal")
    paths, hashes, dataset = runner.load_evaluation_inputs(prefix, "candidate-diagnostic")
    assert len(dataset.labels) == 8 and all(
        label["review_status"] == "candidate" for label in dataset.labels.values()
    )
    runner.verify_input_hashes(paths, hashes)
    paths[0].write_text(paths[0].read_text() + "\n")
    with pytest.raises(ValueError, match="changed during evaluation"):
        runner.verify_input_hashes(paths, hashes)


@pytest.mark.asyncio
async def test_ablation_separates_query_fusion_from_context_expansion(monkeypatch, tmp_path):
    import scripts.eval_independent_retrieval as runner

    seen = []

    async def benchmark(*paths, **kwargs):
        seen.append(kwargs)
        return {}

    monkeypatch.setattr(runner, "run_product_benchmark", benchmark)
    results = await runner.compare_retrieval(
        (tmp_path / "c", tmp_path / "q", tmp_path / "l"), object(), object(),
        evaluation_mode="candidate-diagnostic", product_scope="product", ablation=True,
    )
    assert list(results) == [f"{mode}_{strategy}"
                            for strategy in ("raw", "planned", "dual", "dual_context")
                            for mode in ("sparse", "hybrid", "hybrid_rerank")]
    assert len(seen) == 12
    assert [(row["intent_policy"], row["enable_query_fusion"], row["expand_context"])
            for row in seen] == (
        [("raw", False, False)] * 3 + [("structured", False, False)] * 3
        + [("structured", True, False)] * 3 + [("structured", True, True)] * 3
    )
    assert all(row["top_k"] == 3 and row["candidate_top_k"] == 20
               and row["mode"] == "candidate-diagnostic" and row["product_scope"] == "product"
               for row in seen)
