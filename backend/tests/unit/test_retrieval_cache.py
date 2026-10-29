from __future__ import annotations

import pytest

from packages.knowledge.models import RetrievalHit, RetrievalRequest
from packages.knowledge.retrieval import QueryRewriter, RetrievalService
from packages.knowledge import retrieval


class FakeRewriter(QueryRewriter):
    async def rewrite(self, query: str, *, num_rewrites: int) -> list[str]:
        return [f"{query} expanded"]


class CountingVectorStore:
    def __init__(self) -> None:
        self.calls = 0

    async def search(self, query_vector, **kwargs):
        self.calls += 1
        return [
            RetrievalHit(
                chunk_id=f"chunk-{self.calls}",
                document_id="doc",
                text="cached text",
                score=1.0,
            )
        ]


class EmptyRepo:
    async def search_documents(self, query: str, limit: int = 20, **kwargs):
        return []

    async def get_chunks_for_documents(self, doc_ids: list[str]):
        return {}


def embed(texts: list[str]) -> list[list[float]]:
    return [[float(len(text)), 0.0] for text in texts]


@pytest.mark.asyncio
async def test_retrieval_cache_reuses_identical_request_and_keys_parameters() -> None:
    vector_store = CountingVectorStore()
    service = RetrievalService(
        repo=EmptyRepo(),
        vector_store=vector_store,
        embed_fn=embed,
    )
    request = RetrievalRequest(
        query="security",
        mode="dense",
        enable_query_rewrite=False,
        final_top_k=1,
    )

    first = await service.retrieve(request)
    second = await service.retrieve(request)
    third = await service.retrieve(request.model_copy(update={"final_top_k": 2}))

    assert vector_store.calls == 2
    assert first.hits[0].chunk_id == second.hits[0].chunk_id
    assert third.hits[0].chunk_id == "chunk-2"


@pytest.mark.asyncio
async def test_retrieval_cache_is_bypassed_for_query_rewrite_requests() -> None:
    vector_store = CountingVectorStore()
    service = RetrievalService(
        repo=EmptyRepo(),
        vector_store=vector_store,
        embed_fn=embed,
        query_rewriter=FakeRewriter(),
    )
    request = RetrievalRequest(
        query="pricing",
        mode="dense",
        enable_query_rewrite=True,
        num_rewrites=1,
        final_top_k=2,
    )

    await service.retrieve(request)
    await service.retrieve(request)

    assert vector_store.calls == 4


@pytest.mark.asyncio
async def test_query_and_lexical_versions_each_invalidate_response_cache(monkeypatch) -> None:
    vector_store = CountingVectorStore()
    service = RetrievalService(EmptyRepo(), vector_store, embed_fn=embed)
    request = RetrievalRequest(query="security", mode="dense", enable_query_rewrite=False)
    await service.retrieve(request)
    await service.retrieve(request)
    assert vector_store.calls == 1
    monkeypatch.setattr(retrieval, "PLAN_VERSION", "intent-next")
    await service.retrieve(request)
    assert vector_store.calls == 2
    monkeypatch.setattr(retrieval, "LEXICAL_VERSION", "lexical-next")
    await service.retrieve(request)
    assert vector_store.calls == 3


def test_ttl_checks_actual_age_even_after_fresh_read_in_same_time_bucket(monkeypatch):
    clock = iter([20., 301., 301., 321.])
    monkeypatch.setattr(retrieval.time, "monotonic", lambda: next(clock))
    cache = retrieval._TTLCache(maxsize=2, ttl_seconds=300)
    cache.set("query", [1.])
    assert cache.get("query") == [1.]
    assert cache.get("query") is None


@pytest.mark.asyncio
async def test_embedding_entry_coalesces_32_calls_and_cache_returns_copies():
    import asyncio

    entered, release = asyncio.Event(), asyncio.Event()

    class Provider:
        model_version = "offline-v1"
        dimensions = 2
        calls = 0

        async def embed_query(self, query):
            self.calls += 1
            entered.set()
            await release.wait()
            return [1., 2.]

    provider = Provider()
    service = RetrievalService(EmptyRepo(), CountingVectorStore(), embed_fn=embed,
                               embedding_provider=provider)
    tasks = [asyncio.create_task(service._embed_query("same")) for _ in range(32)]
    await entered.wait()
    await asyncio.sleep(0)
    release.set()
    vectors = await asyncio.gather(*tasks)
    assert provider.calls == 1
    vectors[0][0] = 99.
    assert all(vector == [1., 2.] for vector in vectors[1:])
    hit = await service._embed_query("same")
    hit[0] = 88.
    assert await service._embed_query("same") == [1., 2.]


@pytest.mark.asyncio
async def test_embedding_keys_isolate_query_model_and_dimensions_during_inflight_work():
    import asyncio

    release = asyncio.Event()
    started = asyncio.Queue()

    class Provider:
        model_version = "offline-v1"
        dimensions = 2
        calls = []

        async def embed_query(self, query):
            key = (self.model_version, self.dimensions, query)
            self.calls.append(key)
            started.put_nowait(key)
            await release.wait()
            return [float(len(self.calls))] * key[1]

    provider = Provider()
    service = RetrievalService(EmptyRepo(), CountingVectorStore(), embed_fn=embed,
                               embedding_provider=provider)
    first = asyncio.create_task(service._embed_query("same"))
    await started.get()
    provider.model_version = "offline-v2"
    second = asyncio.create_task(service._embed_query("same"))
    await started.get()
    provider.dimensions = 3
    third = asyncio.create_task(service._embed_query("same"))
    fourth = asyncio.create_task(service._embed_query("other"))
    await started.get()
    await started.get()
    release.set()
    vectors = await asyncio.gather(first, second, third, fourth)
    assert len(provider.calls) == 4
    assert list(map(len, vectors)) == [2, 2, 3, 3]


@pytest.mark.asyncio
async def test_embedding_failure_and_model_version_change_do_not_poison_cache():
    class Provider:
        model_version = "offline-v1"
        dimensions = 2
        calls = 0

        async def embed_query(self, query):
            self.calls += 1
            if self.calls == 1:
                raise ValueError("synthetic provider error")
            self.model_version = "offline-v2"
            return [float(self.calls), 0.]

    provider = Provider()
    service = RetrievalService(EmptyRepo(), CountingVectorStore(), embed_fn=embed,
                               embedding_provider=provider)
    with pytest.raises(ValueError, match="synthetic"):
        await service._embed_query("same")
    assert await service._embed_query("same") == [2., 0.]
    provider.model_version = "offline-v1"
    assert await service._embed_query("same") == [3., 0.]
    assert provider.calls == 3


@pytest.mark.asyncio
async def test_independent_retrieval_services_share_one_provider_computation():
    import asyncio

    release = asyncio.Event()

    class Provider:
        model_version = "offline-v1"
        dimensions = 2
        calls = 0

        async def embed_query(self, query):
            self.calls += 1
            await release.wait()
            return [1., 2.]

    provider = Provider()
    services = [RetrievalService(EmptyRepo(), CountingVectorStore(), embed_fn=embed,
                                 embedding_provider=provider) for _ in range(32)]
    tasks = [asyncio.create_task(service._embed_query("same")) for service in services]
    for _ in range(5):
        await asyncio.sleep(0)
    release.set()
    vectors = await asyncio.gather(*tasks)
    assert provider.calls == 1
    vectors[0][0] = 99.
    assert all(vector == [1., 2.] for vector in vectors[1:])


@pytest.mark.asyncio
async def test_shared_flight_does_not_merge_distinct_custom_embedding_functions():
    import asyncio

    calls = []

    async def first(texts):
        calls.append("first")
        await asyncio.sleep(0)
        return [[1., 0.] for _ in texts]

    async def second(texts):
        calls.append("second")
        await asyncio.sleep(0)
        return [[2., 0.] for _ in texts]

    first_service = RetrievalService(EmptyRepo(), CountingVectorStore(), embed_fn=first)
    second_service = RetrievalService(EmptyRepo(), CountingVectorStore(), embed_fn=second)
    values = await asyncio.gather(first_service._embed_query("same"),
                                  second_service._embed_query("same"))
    assert values == [[1., 0.], [2., 0.]]
    assert sorted(calls) == ["first", "second"]
