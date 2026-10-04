"""Caller-declared retrieval facts and conservative output-format separation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from packages.knowledge.ingestion import IngestionPipeline
from packages.knowledge.models import DocumentCreate, RetrievalIntent, RetrievalRequest
from packages.knowledge.query_intent import resolve_retrieval_plan
from packages.knowledge.repository import KnowledgeRepository
from packages.knowledge.retrieval import QueryRewriter, RetrievalService


def request(query: str, **changes) -> RetrievalRequest:
    return RetrievalRequest(query=query, workspace_id="ws-a", project_id="project-a", **changes)


@pytest.mark.parametrize(
    "field", ["scope", "workspace_id", "project_id", "competitor", "market", "role"]
)
def test_intent_rejects_authority_fields(field):
    with pytest.raises(ValidationError):
        RetrievalIntent(fact_queries=["battery"], **{field: "other"})


@pytest.mark.parametrize("values", [
    {"fact_queries": []}, {"fact_queries": [" "]},
    {"fact_queries": ["fact"] * 6}, {"fact_queries": ["x" * 501]},
    {"fact_queries": ["fact"], "required_terms": [" "]},
    {"fact_queries": ["fact"], "required_terms": ["x"] * 11},
    {"fact_queries": ["fact"], "required_terms": ["x" * 81]},
    {"fact_queries": ["fact"], "output_language": "x" * 41},
])
def test_intent_bounds(values):
    with pytest.raises(ValidationError):
        RetrievalIntent(**values)


def test_structured_suffix_only_after_boundary_and_preserves_original():
    original = "Vacuum X 36 的续航；输出中文并保留出处"
    plan = resolve_retrieval_plan(request(original))
    assert plan.original_query == original
    assert plan.queries == ("Vacuum X 36 的续航",)
    assert plan.output_language == "中文"
    assert plan.require_citations is True

    english = resolve_retrieval_plan(request(
        "Battery runtime; answer in Chinese and include citations"
    ))
    assert english.queries == ("Battery runtime",)
    assert english.output_language == "中文"

    comma = resolve_retrieval_plan(request(
        "Battery runtime, answer in Chinese and include citations"
    ))
    assert comma.queries == ("Battery runtime",)
    assert comma.output_language == "中文"
    assert english.require_citations is True


@pytest.mark.parametrize("query", [
    "中文支持、消息保留和引用功能", "battery answer in Chinese and include citations",
    "battery；输出中文并保留出处，也比较价格", "battery；输出火星语",
])
def test_unknown_or_body_phrases_are_not_stripped(query):
    assert resolve_retrieval_plan(request(query)).queries == (query,)


def test_raw_policy_is_exact_and_conflicts_with_explicit_intent():
    query = "battery；输出中文并保留出处"
    plan = resolve_retrieval_plan(request(query, intent_policy="raw"))
    assert plan.queries == (query,)
    with pytest.raises(ValidationError):
        request(query, intent_policy="raw", retrieval_intent={"fact_queries": ["battery"]})


def test_explicit_facts_preserve_terms_and_standalone_numbers():
    plan = resolve_retrieval_plan(request(
        "Vacuum X 36 与 Vacuum 24 的电池；输出中文并保留出处",
        competitors=["Vacuum X 36"],
        retrieval_intent={"fact_queries": ["电池容量", "质保"], "required_terms": ["Li-ion"]},
    ))
    assert plan.origin == "explicit"
    assert len(plan.queries) == 2
    assert all("Li-ion" in query and "24" in query for query in plan.queries)
    assert all("36" not in query for query in plan.queries)
    assert all("输出中文" not in query for query in plan.queries)


def test_full_competitor_model_number_is_not_appended():
    plan = resolve_retrieval_plan(request(
        "Vacuum X 36 电池", competitors=["Vacuum X 36"],
        retrieval_intent={"fact_queries": ["电池容量"]},
    ))
    assert plan.queries == ("电池容量",)


def test_numbers_next_to_units_or_unknown_model_are_preserved():
    plan = resolve_retrieval_plan(request(
        "Vacuum X 36 与 Y2 电池 5000mAh，输出中文",
        competitors=["Vacuum X 36"],
        retrieval_intent={"fact_queries": ["电池容量"]},
    ))
    assert plan.queries == ("电池容量 2 5000",)
    assert plan.required_terms == ("2", "5000")


@pytest.mark.parametrize(
    "required, fact",
    [
        ("36", "续航 36.5 小时"),
        ("36", "续航 0.36 小时"),
        ("36.5", "续航 136.5 小时"),
        ("36.5", "续航 36.50 小时"),
    ],
)
def test_required_number_is_not_satisfied_by_a_different_numeric_token(required, fact):
    plan = resolve_retrieval_plan(request(
        "续航对比", retrieval_intent={"fact_queries": [fact], "required_terms": [required]},
    ))
    assert plan.queries == (f"{fact} {required}",)


@pytest.mark.parametrize("required, fact", [("5000", "5000mAh"), ("2", "Y2")])
def test_required_number_matches_complete_token_next_to_unit_or_model_letter(required, fact):
    plan = resolve_retrieval_plan(request(
        "电池对比", retrieval_intent={"fact_queries": [fact], "required_terms": [required]},
    ))
    assert plan.queries == (fact,)


@pytest.mark.asyncio
async def test_legacy_rewrite_diagnostics_list_actual_queries():
    class Rewriter(QueryRewriter):
        async def rewrite(self, query: str, *, num_rewrites: int) -> list[str]:
            return ["capacity"]

    class Repo:
        async def search_chunks(self, query, **kwargs):
            return []

    engine = RetrievalService(Repo(), object(), embed_fn=lambda texts: [],
                              query_rewriter=Rewriter())
    response = await engine.retrieve(request("battery", mode="sparse", num_rewrites=1))
    assert response.diagnostics["query_plan"]["queries"] == ("battery", "capacity")


def test_preserved_constraints_over_query_limit_are_rejected():
    with pytest.raises(ValueError, match="2000"):
        resolve_retrieval_plan(request(
            " ".join(str(number) for number in range(420)), retrieval_intent={
                "fact_queries": ["x" * 500],
            },
        ))


class ForbiddenRewriter(QueryRewriter):
    async def rewrite(self, query: str, *, num_rewrites: int) -> list[str]:
        raise AssertionError("explicit facts must not invoke LLM rewrite")


@pytest.mark.asyncio
async def test_explicit_facts_search_real_sqlite_and_report_only_final_chunk_ids(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        class NoVectors:
            async def upsert(self, ids, vectors, payloads):
                pass

        ids = []
        for text in ["battery capacity 36 hours", "warranty coverage 36 months"]:
            ids.append(await IngestionPipeline(repo, NoVectors()).ingest(
                DocumentCreate(title=text, text=text, source_type="manual",
                               workspace_id="ws-a", project_id="project-a"),
            ))
        engine = RetrievalService(repo, NoVectors(), embed_fn=lambda texts: [],
                                  query_rewriter=ForbiddenRewriter())
        original = "battery and warranty 36；answer in Chinese and include citations"
        response = await engine.retrieve(request(
            original, mode="sparse", top_k=5, final_top_k=5,
            retrieval_intent={"fact_queries": ["battery capacity", "warranty coverage"]},
        ))
        assert response.query == original
        assert {hit.document_id for hit in response.hits} == set(ids)
        grouped = response.diagnostics["fact_query_results"]
        assert len(grouped) == 2
        assert {cid for group in grouped for cid in group["chunk_ids"]} == {
            hit.chunk_id for hit in response.hits
        }
        assert response.diagnostics["query_plan"]["origin"] == "explicit"

        narrowed = await engine.retrieve(request(
            original, mode="sparse", top_k=5, final_top_k=1,
            retrieval_intent={"fact_queries": ["battery capacity", "warranty coverage"]},
        ))
        assert len(narrowed.hits) == 1
        retained_id = narrowed.hits[0].chunk_id
        narrowed_groups = narrowed.diagnostics["fact_query_results"]
        assert sorted(group["chunk_ids"] for group in narrowed_groups) == [[], [retained_id]]


@pytest.mark.asyncio
async def test_explicit_fact_lists_rrf_deduplicates_shared_chunk(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        await IngestionPipeline(repo, object()).ingest(DocumentCreate(
            title="shared", text="battery capacity", source_type="manual",
            workspace_id="ws-a", project_id="project-a",
        ))
        engine = RetrievalService(repo, object(), embed_fn=lambda texts: [],
                                  query_rewriter=ForbiddenRewriter())
        response = await engine.retrieve(request(
            "battery capacity", mode="sparse", final_top_k=5,
            retrieval_intent={"fact_queries": ["battery", "capacity"]},
        ))
        assert len(response.hits) == response.total == 1
        chunk_id = response.hits[0].chunk_id
        assert [item["chunk_ids"] for item in response.diagnostics["fact_query_results"]] == [
            [chunk_id], [chunk_id],
        ]


@pytest.mark.asyncio
async def test_explicit_number_and_scope_filter_before_sparse_limit(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        pipeline = IngestionPipeline(repo, object())
        foreign = [
            {"workspace_id": "ws-b"}, {"project_id": "project-b"},
            {"competitor": "Other"}, {"market": "US"},
            {"source_type": "report"},
        ]
        for override in foreign:
            fields = dict(title="foreign", text="battery capacity 36 hours " + repr(override),
                          source_type="manual", workspace_id="ws-a", project_id="project-a",
                          competitor="Vacuum", market="CN")
            fields.update(override)
            await pipeline.ingest(DocumentCreate(**fields))
        await pipeline.ingest(DocumentCreate(
            title="wrong number", text="battery capacity 24 hours", source_type="manual",
            workspace_id="ws-a", project_id="project-a", competitor="Vacuum", market="CN",
        ))
        own = await pipeline.ingest(DocumentCreate(
            title="correct", text="battery capacity 36 hours", source_type="manual",
            workspace_id="ws-a", project_id="project-a", competitor="Vacuum", market="CN",
        ))
        engine = RetrievalService(repo, object(), embed_fn=lambda texts: [],
                                  query_rewriter=ForbiddenRewriter())
        response = await engine.retrieve(request(
            "Vacuum battery 36", mode="sparse", competitors=["Vacuum"], market="CN",
            source_roles=["source"], top_k=1, final_top_k=1,
            retrieval_intent={"fact_queries": ["battery capacity"]},
        ))
        assert [hit.document_id for hit in response.hits] == [own]
        assert response.diagnostics["query_plan"]["queries"] == ("battery capacity 36",)


@pytest.mark.asyncio
async def test_plan_cache_isolated_and_canonical_rechecked(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        own = await IngestionPipeline(repo, object()).ingest(DocumentCreate(
            title="battery", text="battery capacity", source_type="manual",
            workspace_id="ws-a", project_id="project-a",
        ))
        engine = RetrievalService(repo, object(), embed_fn=lambda texts: [],
                                  query_rewriter=ForbiddenRewriter())
        calls = []
        search = repo.search_chunks

        async def observed(query, **kwargs):
            calls.append(query)
            return await search(query, **kwargs)

        repo.search_chunks = observed
        common = dict(mode="sparse", enable_query_rewrite=False)
        raw = request("battery；输出中文", intent_policy="raw", **common)
        structured = request("battery；输出中文", **common)
        await engine.retrieve(raw)
        first = await engine.retrieve(structured)
        assert first.hits and first.hits[0].document_id == own
        assert calls == ["battery；输出中文", "battery"]
        await engine.retrieve(structured)
        assert calls == ["battery；输出中文", "battery"]
        await repo.soft_delete(own)
        stale = await engine.retrieve(structured)
        assert stale.hits == []


@pytest.mark.asyncio
async def test_reranker_receives_factual_text_without_format_suffix(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        await IngestionPipeline(repo, object()).ingest(DocumentCreate(
            title="battery", text="battery capacity", source_type="manual",
            workspace_id="ws-a", project_id="project-a",
        ))
        seen = []

        def rerank(query, texts):
            seen.append(query)
            return [1.0] * len(texts)

        engine = RetrievalService(repo, object(), embed_fn=lambda texts: [],
                                  rerank_fn=rerank, query_rewriter=ForbiddenRewriter())
        await engine.retrieve(request("battery capacity；输出中文并保留出处",
                                      mode="sparse", rerank_top_k=1))
        assert seen == ["battery capacity"]
