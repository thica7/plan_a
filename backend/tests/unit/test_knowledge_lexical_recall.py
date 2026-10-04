"""Bounded, offline lexical fallback against a real SQLite FTS index."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from packages.knowledge.embeddings import HashEmbeddingProvider
from packages.knowledge.lexical import build_lexical_plan
from packages.knowledge.models import (
    DocumentCreate,
    KnowledgeChunk,
    KnowledgeScope,
    RetrievalHit,
    RetrievalRequest,
)
from packages.knowledge.repository import KnowledgeRepository
from packages.knowledge.retrieval import RetrievalService


def test_plan_keeps_unknown_terms_and_numbers_and_removes_only_full_product_name():
    plan = build_lexical_plan("请问Model 36 Pro的保修期36 months多久", ["Model 36 Pro"])
    assert plan.concepts == ["warranty"]
    assert "36" in plan.literals
    assert "months" in plan.literals
    assert "model" not in plan.literals
    assert plan.fallback_query
    assert plan.strict_query


@pytest.mark.parametrize("query", ["annual", "seat"])
def test_english_alias_requires_whole_word(query):
    plan = build_lexical_plan(query)
    assert plan.concepts == [query]
    assert "biannual" not in plan.fallback_query
    assert "seattle" not in plan.fallback_query


def test_question_only_and_bounds_disable_expansion():
    assert build_lexical_plan("请问有哪些功能吗").fallback_query is None
    assert build_lexical_plan(" ").fallback_query is None
    assert (
        build_lexical_plan(
            " ".join(
                [
                    "battery",
                    "capacity",
                    "warranty",
                    "duration",
                    "refund",
                    "shipping",
                    "export",
                    "license",
                    "subscription",
                ]
            )
        ).disabled_reason
        == "too_many_concepts"
    )
    assert (
        build_lexical_plan(" ".join(f"unknown{i}" for i in range(13))).disabled_reason
        == "too_many_literals"
    )


def test_chinese_connectors_do_not_become_literal_requirements():
    plan = build_lexical_plan("月付与年付的计费差异是什么")
    assert plan.concepts == ["monthly", "annual", "billing"]
    assert plan.literals == []
    assert build_lexical_plan("价格和隐私是什么").literals == []


def test_unknown_chinese_nouns_keep_internal_question_characters():
    assert build_lexical_plan("智能 battery").literals == ["智能"]
    assert build_lexical_plan("性能 warranty").literals == ["性能"]
    assert build_lexical_plan("模型的 warranty").literals == ["模型", "型的"]
    assert build_lexical_plan("请问有哪些功能吗").disabled_reason == "question_only"
    assert build_lexical_plan("月付与年付的计费差异是什么").literals == []


async def add(repo, text, *, title="Guide", **overrides):
    values = dict(
        title=title,
        source_type="manual",
        text=text,
        workspace_id="ws",
        project_id="project",
        competitor="Acme",
        dimension="policy",
        market="CN",
    )
    values.update(overrides)
    doc = await repo.upsert_document(
        DocumentCreate(**values), content_hash=f"hash-{len(text)}-{text}-{title}-{overrides}"
    )
    await repo.insert_chunks(
        [
            KnowledgeChunk(
                id=f"chunk-{doc.id}",
                document_id=doc.id,
                chunk_index=0,
                text=text,
                token_count=10,
                embedding_model="",
                content_hash="chunkhash",
            )
        ]
    )
    return doc


@pytest.mark.asyncio
async def test_cross_language_warranty_and_strict_opt_out(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        chinese = await add(repo, "保修期限为两年")
        english = await add(repo, "Warranty lasts two years")
        assert chinese.id in [
            d.id for d in await repo.search_documents("请问Acme的保修期多久", competitors=["Acme"])
        ]
        assert english.id in [
            h.document_id
            for h in await repo.search_chunks("请问Acme的保修期多久", competitors=["Acme"])
        ]
        assert chinese.id in [
            h.document_id for h in await repo.search_chunks("warranty", competitors=["Acme"])
        ]
    async with KnowledgeRepository(str(tmp_path / "kb.db"), lexical_fallback=False) as repo:
        assert await repo.search_chunks("warranty", competitors=["Acme"])
        assert chinese.id not in [
            h.document_id for h in await repo.search_chunks("warranty", competitors=["Acme"])
        ]


@pytest.mark.asyncio
async def test_literal_and_word_boundaries(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        good = await add(repo, "保修 36 months")
        await add(repo, "保修 24 months")
        assert [h.document_id for h in await repo.search_chunks("warranty 36 months")] == [good.id]
        await add(repo, "biannual renewals")
        await add(repo, "seattle guide")
        assert await repo.search_chunks("annual") == []
        assert await repo.search_chunks("seat") == []


@pytest.mark.asyncio
async def test_unknown_chinese_noun_never_degrades_to_single_character_match(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        good_intelligent = await add(repo, "智能 电池")
        await add(repo, "智 电池")
        good_performance = await add(repo, "性能 保修")
        await add(repo, "性 保修")
        assert [hit.document_id for hit in await repo.search_chunks("智能 battery")] == [
            good_intelligent.id
        ]
        assert [hit.document_id for hit in await repo.search_chunks("性能 warranty")] == [
            good_performance.id
        ]


@pytest.mark.asyncio
async def test_body_precedes_title_and_metadata_is_ephemeral(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        title = await add(repo, "unrelated text", title="Warranty")
        body = await add(repo, "保修服务", title="Guide", metadata={"lexical_retrieval": "forged"})
        hits = await repo.search_chunks("warranty", limit=1)
        assert [h.document_id for h in hits] == [body.id]
        assert hits[0].metadata["lexical_retrieval"]["path"] == "fallback_body"
        assert (await repo.get_document(body.id)).metadata["lexical_retrieval"] == "forged"
        assert title.id not in [h.document_id for h in hits]


@pytest.mark.asyncio
async def test_filters_apply_before_limit_and_stale_discount(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        for override in (
            {"workspace_id": "other"},
            {"project_id": "other"},
            {"competitor": "Other"},
            {"dimension": "other"},
            {"market": "US"},
            {"source_role": "historical_report"},
            {"source_published_at": datetime.now(UTC) - timedelta(days=100)},
        ):
            await add(repo, "保修服务", **override)
        own = await add(repo, "保修服务", source_published_at=datetime.now(UTC))
        scope = KnowledgeScope(workspace_id="ws", project_id="project")
        kwargs = dict(
            scope=scope,
            competitors=["Acme"],
            dimensions=["policy"],
            market="CN",
            source_roles=["source"],
            max_age_days=7,
        )
        assert [h.document_id for h in await repo.search_chunks("warranty", limit=1, **kwargs)] == [
            own.id
        ]
        stale = await add(repo, "保修 extra", title="Stale")
        await repo._connection.execute(
            "UPDATE documents SET status = 'stale' WHERE id = ?", (stale.id,)
        )
        hits = await repo.search_chunks("warranty", limit=10)
        assert next(h.score for h in hits if h.document_id == stale.id) < next(
            h.score for h in hits if h.document_id == own.id
        )


@pytest.mark.asyncio
async def test_sparse_canonical_recheck_preserves_only_current_diagnostic(tmp_path):
    class UnusedVectors:
        async def search(self, *_args, **_kwargs):
            raise AssertionError("sparse retrieval must not search vectors")

    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        doc = await add(repo, "保修服务", metadata={"lexical_retrieval": "forged"})
        service = RetrievalService(repo, UnusedVectors(), embed_fn=lambda _: [])
        request = RetrievalRequest(
            query="warranty",
            mode="sparse",
            workspace_id="ws",
            project_id="project",
            competitors=["Acme"],
            dimensions=["policy"],
            market="CN",
            source_roles=["source"],
            top_k=2,
            final_top_k=2,
            enable_query_rewrite=False,
        )
        response = await service.retrieve(request)
        assert [hit.document_id for hit in response.hits] == [doc.id]
        assert response.hits[0].metadata["lexical_retrieval"] == {
            "version": "lexical-v1",
            "path": "fallback_body",
            "concepts": ["warranty"],
        }
        assert (await repo.get_document(doc.id)).metadata["lexical_retrieval"] == "forged"


@pytest.mark.asyncio
async def test_question_only_cannot_match_question_words_but_product_title_still_works(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        await add(repo, "请问 what", title="Acme")
        assert await repo.search_chunks("请问") == []
        assert await repo.search_documents("what") == []
        assert [hit.title for hit in await repo.search_chunks("Acme", competitors=["Acme"])] == [
            "Acme"
        ]


@pytest.mark.asyncio
async def test_document_search_does_not_claim_body_provenance_for_title_match(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        doc = await add(repo, "unrelated", title="Warranty", metadata={"origin": "source"})
        found = await repo.search_documents("warranty")
        assert [item.id for item in found] == [doc.id]
        assert found[0].metadata == {"origin": "source"}


@pytest.mark.asyncio
async def test_disabled_fallback_keeps_first_body_hit_when_title_matches_same_chunk(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db"), lexical_fallback=False) as repo:
        first = await add(repo, "warranty", title="Guide")
        second = await add(repo, "warranty with many unrelated filler words", title="Warranty")
        hits = await repo.search_chunks("warranty")
        assert [hit.document_id for hit in hits] == [first.id, second.id]
        assert [hit.score for hit in hits] == [1.0, 0.5]


@pytest.mark.asyncio
async def test_complete_product_name_with_question_mark_keeps_strict_title_lookup(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        doc = await add(repo, "unrelated", title="AuroraCam X", competitor="AuroraCam X")
        hits = await repo.search_chunks("AuroraCam X?", competitors=["AuroraCam X"])
        assert [hit.document_id for hit in hits] == [doc.id]
        assert hits[0].metadata["lexical_retrieval"]["path"] == "title"


@pytest.mark.asyncio
async def test_dense_does_not_expose_forged_source_lexical_diagnostic(tmp_path):
    class FixedVectors:
        def __init__(self, hit):
            self.hit = hit

        async def search(self, *_args, **_kwargs):
            return [self.hit]

    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        doc = await add(
            repo, "保修服务", metadata={"lexical_retrieval": "forged", "origin": "source"}
        )
        await repo._connection.execute(
            "UPDATE documents SET indexing_status = 'ready', embedding_model = ?, "
            "embedding_dimensions = 8, index_version = 'v1' WHERE id = ?",
            ("hash-embedding-v1", doc.id),
        )
        hit = RetrievalHit(
            chunk_id=f"chunk-{doc.id}",
            document_id=doc.id,
            text="保修服务",
            score=1.0,
            workspace_id="ws",
            project_id="project",
            competitor="Acme",
            dimension="policy",
            market="CN",
            source_role="source",
            source_type="manual",
            document_version=doc.version,
            content_hash=doc.content_hash,
            metadata={
                "vector_index": {
                    "model_version": "hash-embedding-v1",
                    "index_version": "v1",
                    "dimensions": 8,
                    "chunk_content_hash": "chunkhash",
                }
            },
        )
        provider = HashEmbeddingProvider(dimensions=8)
        service = RetrievalService(
            repo,
            FixedVectors(hit),
            embed_fn=provider.embed_documents,
            embedding_provider=provider,
        )
        request = RetrievalRequest(
            query="warranty",
            mode="dense",
            workspace_id="ws",
            project_id="project",
            competitors=["Acme"],
            dimensions=["policy"],
            market="CN",
            source_roles=["source"],
            top_k=1,
            final_top_k=1,
            enable_query_rewrite=False,
        )
        response = await service.retrieve(request)
        assert len(response.hits) == 1
        assert "lexical_retrieval" not in response.hits[0].metadata
        assert response.hits[0].metadata["origin"] == "source"
        assert (await repo.get_document(doc.id)).metadata["lexical_retrieval"] == "forged"


@pytest.mark.asyncio
async def test_disabled_fallback_does_not_echo_forged_source_diagnostic(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db"), lexical_fallback=False) as repo:
        doc = await add(repo, "warranty", metadata={"lexical_retrieval": "forged"})
        hits = await repo.search_chunks("warranty")
        assert [hit.document_id for hit in hits] == [doc.id]
        assert "lexical_retrieval" not in hits[0].metadata
        assert (await repo.get_document(doc.id)).metadata["lexical_retrieval"] == "forged"
