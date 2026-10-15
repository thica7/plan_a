"""Original and structured queries keep equal branch authority."""
from __future__ import annotations

import pytest

from packages.knowledge.models import RetrievalHit, RetrievalRequest
from packages.knowledge.retrieval import RetrievalService


class SearchRepo:
    def __init__(self, results):
        self.results = results
        self.calls = []

    async def search_chunks(self, query, **kwargs):
        self.calls.append((query, kwargs))
        return [hit.model_copy(deep=True) for hit in self.results.get(query, [])]


def hit(key):
    return RetrievalHit(chunk_id=key, document_id=key, text=key, score=1,
                        workspace_id="ws", project_id="project", competitor="Acme",
                        dimension="feature", market="CN", source_role="source")


def request(query="original clause", **kwargs):
    values = dict(query=query, mode="sparse", enable_query_rewrite=False,
                  top_k=10, final_top_k=10, rerank_top_k=0,
                  retrieval_intent={"fact_queries": ["fact one", "fact two"]})
    values.update(kwargs)
    return RetrievalRequest(**values)


@pytest.mark.asyncio
async def test_original_unique_evidence_survives_structured_query_branch():
    repo = SearchRepo({"original clause": [hit("original-only")],
                       "fact one": [hit("fact-only")], "fact two": [hit("fact-only")]})
    service = RetrievalService(repo, object(), embed_fn=lambda texts: [])
    response = await service.retrieve(request())
    assert {item.chunk_id for item in response.hits} == {"original-only", "fact-only"}
    assert [query for query, _ in repo.calls] == ["original clause", "fact one", "fact two"]
    by_id = {item.chunk_id: item.score for item in response.hits}
    assert by_id["original-only"] == by_id["fact-only"]
    assert response.diagnostics["query_fusion"]["branch_weights"] == {"original": 1.0, "structured": 1.0}
    assert len(response.diagnostics["fact_query_results"]) == 2


@pytest.mark.asyncio
async def test_five_fact_lists_are_first_fused_into_one_equal_branch():
    facts = [f"fact {index}" for index in range(5)]
    repo = SearchRepo({"original clause": [hit("original-only")],
                       **{fact: [hit("fact-only")] for fact in facts}})
    response = await RetrievalService(repo, object(), embed_fn=lambda texts: []).retrieve(
        request(retrieval_intent={"fact_queries": facts}))
    assert response.hits[0].chunk_id == "original-only"
    assert response.hits[0].score == response.hits[1].score


@pytest.mark.asyncio
async def test_identical_original_and_fact_query_search_is_deduplicated():
    repo = SearchRepo({"same fact": [hit("shared")]})
    response = await RetrievalService(repo, object(), embed_fn=lambda texts: []).retrieve(
        request("same fact", retrieval_intent={"fact_queries": ["same fact"]}))
    assert [query for query, _ in repo.calls] == ["same fact"]
    assert response.hits[0].chunk_id == "shared"
    assert response.diagnostics["query_fusion"]["executed_queries"] == ["same fact"]


@pytest.mark.asyncio
async def test_final_rerank_receives_complete_original_query():
    original = "original clause；输出中文并引用"
    repo = SearchRepo({"fact one": [hit("fact-only")]})
    seen = []

    def rerank(query, texts):
        seen.append(query)
        return [1.0] * len(texts)

    await RetrievalService(repo, object(), embed_fn=lambda texts: [], rerank_fn=rerank).retrieve(
        request(original, rerank_top_k=5))
    assert seen == [original]


@pytest.mark.asyncio
async def test_same_scope_filters_pass_to_both_query_routes():
    repo = SearchRepo({})
    req = request(workspace_id="ws", project_id="project", competitors=["Acme"],
                  dimensions=["feature"], market="CN", source_roles=["source"], max_age_days=7)
    await RetrievalService(repo, object(), embed_fn=lambda texts: []).retrieve(req)
    assert len(repo.calls) == 3
    assert all(kwargs == repo.calls[0][1] for _, kwargs in repo.calls)
    assert repo.calls[0][1]["scope"] == req.scope


@pytest.mark.asyncio
async def test_fusion_false_retains_structured_only_ablation_and_raw_stays_unplanned():
    repo = SearchRepo({"fact one": [hit("fact-only")], "original clause": [hit("original-only")]})
    service = RetrievalService(repo, object(), embed_fn=lambda texts: [], enable_query_fusion=False)
    response = await service.retrieve(request())
    assert [item.chunk_id for item in response.hits] == ["fact-only"]
    assert [query for query, _ in repo.calls] == ["fact one", "fact two"]
    repo.calls.clear()
    response = await service.retrieve(request(intent_policy="raw", retrieval_intent=None))
    assert [query for query, _ in repo.calls] == ["original clause"]
    assert response.diagnostics["query_plan"]["origin"] == "raw"


@pytest.mark.asyncio
async def test_fusion_and_context_flags_each_invalidate_response_cache():
    repo = SearchRepo({"original clause": [hit("original-only")], "fact one": [hit("fact-only")]})
    service = RetrievalService(repo, object(), embed_fn=lambda texts: [])
    await service.retrieve(request())
    count = len(repo.calls)
    await service.retrieve(request())
    assert len(repo.calls) == count
    service._enable_query_fusion = False
    await service.retrieve(request())
    assert len(repo.calls) == count + 2
    service._expand_context = False
    await service.retrieve(request())
    assert len(repo.calls) == count + 4


@pytest.mark.asyncio
async def test_raw_route_reports_actual_query_and_channel_budget():
    repo = SearchRepo({"battery": [hit("one")]})
    response = await RetrievalService(repo, object(), embed_fn=lambda texts: []).retrieve(
        request("battery", intent_policy="raw", retrieval_intent=None))
    route = response.diagnostics["query_fusion"]
    assert route["executed_queries"] == ["battery"]
    assert route["search_budget"] == {"per_query_top_k": 10, "unique_queries": 1,
                                       "max_candidates": 10}


@pytest.mark.asyncio
async def test_cached_ranking_provenance_is_separate_from_current_execution_budget():
    repo = SearchRepo({"original clause": [hit("original-only")], "fact one": [hit("fact-only")]})
    service = RetrievalService(repo, object(), embed_fn=lambda texts: [])
    cold = await service.retrieve(request())
    calls = len(repo.calls)
    warm = await service.retrieve(request())
    assert len(repo.calls) == calls
    assert warm.diagnostics["query_fusion"]["executed_queries"] == []
    assert warm.diagnostics["query_fusion"]["search_budget"] == {
        "per_query_top_k": 10, "unique_queries": 0, "max_candidates": 0,
    }
    assert warm.diagnostics["cache"]["hit"] is True
    assert cold.diagnostics["cache"]["hit"] is False
    provenance = warm.diagnostics["cached_ranking_provenance"]
    assert provenance["query_fusion"] == cold.diagnostics["query_fusion"]
    assert provenance["candidates"] == cold.diagnostics["candidates"]
    assert provenance["candidate_refs"] == cold.diagnostics["candidate_refs"]
    assert warm.diagnostics["candidates"] == {"dense": 0, "sparse": 0, "reranked": 0}
    assert warm.diagnostics["candidate_refs"] == []
    assert [(item.chunk_id, item.score) for item in warm.hits] == [
        (item.chunk_id, item.score) for item in cold.hits]
    again = await service.retrieve(request())
    assert again.diagnostics["cached_ranking_provenance"] == provenance
    assert again.diagnostics["query_fusion"]["executed_queries"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("repeated_a", [["fact A", "fact A", "fact A"],
                                        ["fact A", " FACT a ", "FaCt A"]])
async def test_repeated_fact_queries_have_one_fusion_vote_and_keep_diagnostic_slots(repeated_a):
    results = {"fact A": [hit("A")], "fact B": [hit("B")], "fact C": [hit("B")]}

    async def retrieve(facts, *, enabled=True):
        repo = SearchRepo(results)
        response = await RetrievalService(repo, object(), embed_fn=lambda texts: [],
                                          enable_query_fusion=enabled).retrieve(
            request(retrieval_intent={"fact_queries": facts}))
        return response, [query for query, _ in repo.calls]

    unique, unique_calls = await retrieve(["fact A", "fact B", "fact C"])
    repeated, repeated_calls = await retrieve([*repeated_a, "fact B", "fact C"])
    assert unique_calls == repeated_calls
    assert [(item.chunk_id, item.score) for item in unique.hits] == [
        (item.chunk_id, item.score) for item in repeated.hits]
    assert [item.chunk_id for item in repeated.hits] == ["B", "A"]
    assert len(repeated.diagnostics["fact_query_results"]) == 5
    assert len(repeated.diagnostics["query_plan"]["queries"]) == 5
    legacy, _ = await retrieve([*repeated_a, "fact B", "fact C"], enabled=False)
    assert [item.chunk_id for item in legacy.hits] == ["A", "B"]
