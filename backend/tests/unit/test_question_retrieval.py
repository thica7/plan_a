from __future__ import annotations

import asyncio
import importlib
import json
import threading
from datetime import UTC, datetime, timedelta

import pytest
from test_run_evidence_snapshot import make_detail

from packages.knowledge.embeddings import HashEmbeddingProvider, HttpEmbeddingProvider
from packages.knowledge.local_models import LocalEmbeddingProvider, LocalRerankerProvider
from packages.knowledge.reranker import HashRerankerProvider
from packages.research.evidence.snapshot import _contract, _digest, _snapshot_id, seal_snapshot


def retrieval_api():
    try:
        return importlib.import_module("packages.agents.writer.question_retrieval")
    except ModuleNotFoundError:
        pytest.fail("question-level local semantic retrieval is not implemented")


def research_case(quotes, *, question="Example Product 的访客是否必须先认证身份？"):
    detail = make_detail()
    detail.topic = question
    detail.plan.competitors = ["Example Product", "Other Product"]
    detail.plan.dimensions = ["feature", "pricing"]
    prototype = detail.raw_sources[0]
    detail.raw_sources = []
    for number, quote in enumerate(quotes):
        source = prototype.model_copy(deep=True)
        source.id = f"source-{number}"
        source.competitor = "Example Product"
        source.covered_competitors = [source.competitor]
        source.dimension = "feature"
        source.metadata = {
            "source_material_level": "full_source",
            "last_verified_at": datetime.now(UTC).isoformat(),
            "normalized_fields": [
                {
                    "kind": "feature",
                    "dimension": "feature",
                    "competitor": source.competitor,
                    "slot": f"observation-{number}",
                    "support_level": "documented",
                    "evidence_terms": [quote],
                    "evidence_quote": quote,
                    "confidence": 0.9,
                    "evidence_item_ids": [f"original-{number}"],
                }
            ],
        }
        detail.raw_sources.append(source)
    snapshot = seal_snapshot(detail, phase="analysis", canonical_documents={})
    return detail, snapshot


def replace_snapshot(detail, snapshot, **updates):
    updated = snapshot.model_copy(update=updates)
    updated = updated.model_copy(update={"content_hash": _digest(_contract(updated))})
    updated = updated.model_copy(update={"id": _snapshot_id(updated)})
    detail.evidence_snapshots = [updated]
    detail.evidence_snapshot_id = updated.id
    return updated


class SemanticModel:
    def __init__(self):
        self.texts = []
        self.thread_ids = []

    def encode(self, texts, **kwargs):
        self.texts.extend(texts)
        self.thread_ids.append(threading.get_ident())
        return [
            [1.0, 0.0] if text.startswith("query:") or "authenticate" in text else [0.0, 1.0]
            for text in texts
        ]


@pytest.fixture
def semantic_provider(tmp_path, monkeypatch):
    model = SemanticModel()
    monkeypatch.setattr(
        "packages.knowledge.local_models._load_sentence_transformer", lambda *args, **kwargs: model
    )
    provider = LocalEmbeddingProvider(
        tmp_path, model_id="intfloat/multilingual-e5-small", revision="anonymous-test"
    )
    return provider, model


@pytest.mark.asyncio
async def test_anonymous_cross_language_recall_uses_original_fact_ids(semantic_provider):
    provider, model = semantic_provider
    quotes = [f"Editors can format heading style {index}." for index in range(9)]
    answer = "Visitors must authenticate before entering an individually invited board."
    detail, snapshot = research_case([*quotes, answer])
    before = snapshot.model_dump_json()
    module = retrieval_api()
    lexical, _ = await module.retrieve_question_facts(
        detail, snapshot, "Example Product", "feature", mode="lexical"
    )
    selected, diagnostic = await module.retrieve_question_facts(
        detail, snapshot, "Example Product", "feature", embedding_provider=provider
    )
    target = next(f.id for f in snapshot.facts if f.field == "evidence_terms" and f.quote == answer)
    assert target not in (lexical or ())
    assert selected[0] == target
    assert set(selected) <= {f.id for f in snapshot.facts if f.status == "supported"}
    assert snapshot.model_dump_json() == before
    assert diagnostic["mode"] == "hybrid"
    assert diagnostic["ranking_only"] is True
    assert diagnostic["embedding_model_version"] == provider.model_version
    assert all(identity != threading.get_ident() for identity in model.thread_ids)


@pytest.mark.asyncio
async def test_candidate_scope_rejects_other_product_dimension_status_and_source(semantic_provider):
    provider, model = semantic_provider
    detail, snapshot = research_case(["Visitors must authenticate before entering a board."] * 8)
    originals = [fact for fact in snapshot.facts if fact.field == "evidence_terms"]
    forbidden = [
        originals[1].model_copy(update={"competitor": "Other Product"}),
        originals[2].model_copy(update={"dimension": "pricing"}),
        originals[3].model_copy(update={"status": "signal"}),
        originals[4].model_copy(update={"status": "unknown"}),
        originals[5].model_copy(update={"source_id": "missing-source"}),
    ]
    sources = {source.id: source for source in snapshot.sources}
    sources[originals[6].source_id] = sources[originals[6].source_id].model_copy(
        update={"last_verified_at": datetime.now(UTC) - timedelta(days=60)}
    )
    sources[originals[7].source_id] = sources[originals[7].source_id].model_copy(
        update={"role": "historical_report"}
    )
    snapshot = replace_snapshot(
        detail,
        snapshot,
        facts=(originals[0], *forbidden, originals[6], originals[7]),
        sources=tuple(sources.values()),
    )
    selected, diagnostic = await retrieval_api().retrieve_question_facts(
        detail, snapshot, "Example Product", "feature", embedding_provider=provider
    )
    assert selected == (originals[0].id,)
    assert diagnostic["eligible_count"] == 1
    assert len([text for text in model.texts if text.startswith("passage:")]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["workspace_id", "project_id", "id"])
async def test_foreign_scope_is_rejected_before_local_model_calls(semantic_provider, scope):
    provider, model = semantic_provider
    detail, snapshot = research_case(["Visitors must authenticate."])
    setattr(detail, scope, "foreign-scope")
    with pytest.raises(ValueError, match="scope|identity"):
        await retrieval_api().retrieve_question_facts(
            detail, snapshot, "Example Product", "feature", embedding_provider=provider
        )
    assert model.texts == []


@pytest.mark.asyncio
async def test_old_or_mutated_snapshot_cannot_be_retrieved(semantic_provider):
    provider, model = semantic_provider
    detail, old = research_case(["Visitors must authenticate."])
    detail.raw_sources[0].metadata["normalized_fields"][0]["evidence_quote"] += " Current original."
    current = seal_snapshot(detail, phase="analysis", canonical_documents={})
    with pytest.raises(ValueError, match="current|snapshot"):
        await retrieval_api().retrieve_question_facts(
            detail, old, "Example Product", "feature", embedding_provider=provider
        )
    mutated = current.model_copy(update={"facts": ()})
    with pytest.raises(ValueError, match="hash|snapshot"):
        await retrieval_api().retrieve_question_facts(
            detail, mutated, "Example Product", "feature", embedding_provider=provider
        )
    assert model.texts == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider", [HashEmbeddingProvider(), HttpEmbeddingProvider(url="http://invalid")]
)
async def test_hash_and_http_providers_are_never_semantic_fallbacks(provider):
    detail, snapshot = research_case(
        ["Visitors must authenticate before entering a board."],
        question="Example Product: Must visitors authenticate?",
    )
    selected, diagnostic = await retrieval_api().retrieve_question_facts(
        detail, snapshot, "Example Product", "feature", embedding_provider=provider
    )
    assert selected
    assert diagnostic["mode"] == "degraded_lexical"
    assert "strict_local_provider_required" in diagnostic["degraded_reasons"]
    assert diagnostic["embedding_model_version"] is None


@pytest.mark.asyncio
async def test_local_failure_is_explicit_lexical_degradation(tmp_path, monkeypatch):
    def unavailable(*args, **kwargs):
        raise RuntimeError("anonymous local model unavailable")

    monkeypatch.setattr("packages.knowledge.local_models._load_sentence_transformer", unavailable)
    provider = LocalEmbeddingProvider(
        tmp_path, model_id="intfloat/multilingual-e5-small", revision="test"
    )
    detail, snapshot = research_case(
        ["Visitors must authenticate before entering a board."],
        question="Example Product: Must visitors authenticate?",
    )
    selected, diagnostic = await retrieval_api().retrieve_question_facts(
        detail, snapshot, "Example Product", "feature", embedding_provider=provider
    )
    assert selected
    assert diagnostic["mode"] == "degraded_lexical"
    assert diagnostic["degraded_reasons"] == ["embedding_inference_failed:RuntimeError"]


@pytest.mark.asyncio
async def test_ranking_receives_complete_values_and_quotes(semantic_provider):
    provider, model = semantic_provider
    quote = "Visitors must authenticate. " + "Original condition. " * 140 + "END-QUOTE"
    detail, snapshot = research_case([quote])
    original = next(f for f in snapshot.facts if f.field == "evidence_terms")
    complete = original.model_copy(
        update={"value_json": json.dumps([quote, "END-VALUE condition"])}
    )
    snapshot = replace_snapshot(detail, snapshot, facts=(complete,))
    selected, _ = await retrieval_api().retrieve_question_facts(
        detail, snapshot, "Example Product", "feature", embedding_provider=provider
    )
    assert selected == (complete.id,)
    passage = next(text for text in model.texts if text.startswith("passage:"))
    assert quote in passage
    assert "END-VALUE condition" in passage


@pytest.mark.asyncio
async def test_pool_and_per_question_caps_are_bounded_and_round_robin(semantic_provider):
    provider, model = semantic_provider
    detail, snapshot = research_case(
        [f"Visitors authenticate for workflow {index}." for index in range(140)],
        question="\n".join(
            f"Example Product: How do visitors authenticate for workflow {index}?"
            for index in range(4)
        ),
    )
    selected, diagnostic = await retrieval_api().retrieve_question_facts(
        detail, snapshot, "Example Product", "feature", embedding_provider=provider
    )
    assert len(selected) <= 8
    assert diagnostic["candidate_count"] == 128
    assert diagnostic["eligible_count"] == 140
    assert diagnostic["capacity_limited"] is True
    assert len([text for text in model.texts if text.startswith("passage:")]) == 128
    assert all(len(row["fact_ids"]) <= 3 for row in diagnostic["questions"])
    assert len(diagnostic["questions"]) == 4


@pytest.mark.asyncio
async def test_no_question_skips_model_loading_and_empty_eligible_is_explicit(monkeypatch):
    module = retrieval_api()

    def forbidden(*args, **kwargs):
        raise AssertionError("no local model should load")

    monkeypatch.setattr(module, "get_local_provider_from_env", forbidden)
    detail, snapshot = research_case(["Visitors authenticate."], question="Product research")
    selected, diagnostic = await module.retrieve_question_facts(
        detail, snapshot, "Example Product", "feature"
    )
    assert selected is None
    assert diagnostic["mode"] == "no_questions"
    detail.topic = "Example Product 的访客是否需要认证？"
    snapshot = replace_snapshot(detail, snapshot, facts=())
    selected, diagnostic = await module.retrieve_question_facts(
        detail, snapshot, "Example Product", "feature"
    )
    assert selected == ()
    assert diagnostic["mode"] == "no_candidates"


@pytest.mark.asyncio
async def test_default_frozen_factory_and_reranker_run_off_event_loop(
    semantic_provider, tmp_path, monkeypatch
):
    provider, model = semantic_provider
    module = retrieval_api()
    calls = []

    def factory(kind):
        calls.append((kind, threading.get_ident()))
        return provider

    class CrossEncoder:
        def predict(self, pairs, **kwargs):
            calls.append(("rerank", threading.get_ident()))
            return [10.0 if "second" in text else -10.0 for _, text in pairs]

    monkeypatch.setattr(module, "get_local_provider_from_env", factory)
    monkeypatch.setattr(
        "packages.knowledge.local_models._load_cross_encoder", lambda *a, **k: CrossEncoder()
    )
    reranker = LocalRerankerProvider(tmp_path, model_id="BAAI/bge-reranker-v2-m3", revision="test")
    detail, snapshot = research_case(
        ["Visitors authenticate first.", "Visitors authenticate second."]
    )
    selected, diagnostic = await module.retrieve_question_facts(
        detail, snapshot, "Example Product", "feature", reranker_provider=reranker
    )
    target = next(
        f.id for f in snapshot.facts if f.field == "evidence_terms" and "second" in f.quote
    )
    assert selected[0] == target
    assert diagnostic["mode"] == "hybrid_reranked"
    assert diagnostic["reranker_model_version"] == reranker.model_version
    assert all(identity != threading.get_ident() for _, identity in calls)
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_invalid_reranker_explicitly_degrades_to_lexical(semantic_provider):
    provider, _ = semantic_provider
    detail, snapshot = research_case(
        ["Visitors must authenticate before entering a board."],
        question="Example Product: Must visitors authenticate?",
    )
    selected, diagnostic = await retrieval_api().retrieve_question_facts(
        detail,
        snapshot,
        "Example Product",
        "feature",
        embedding_provider=provider,
        reranker_provider=HashRerankerProvider(),
    )
    assert selected
    assert diagnostic["mode"] == "degraded_lexical"
    assert diagnostic["degraded_reasons"] == ["strict_local_reranker_required"]


@pytest.mark.asyncio
async def test_snapshot_change_during_inference_is_rejected(semantic_provider, monkeypatch):
    provider, model = semantic_provider
    detail, snapshot = research_case(["Visitors must authenticate."])
    original_encode = model.encode

    def update_inputs(texts, **kwargs):
        detail.evidence_inputs_dirty = True
        return original_encode(texts, **kwargs)

    monkeypatch.setattr(model, "encode", update_inputs)
    with pytest.raises(ValueError, match="accepted|changed"):
        await retrieval_api().retrieve_question_facts(
            detail, snapshot, "Example Product", "feature", embedding_provider=provider
        )


@pytest.mark.asyncio
async def test_unaccepted_policy_snapshot_is_rejected_before_inference(semantic_provider):
    provider, model = semantic_provider
    detail, snapshot = research_case(["Visitors must authenticate."])
    snapshot = replace_snapshot(detail, snapshot, fact_market_policy_version=None)
    with pytest.raises(ValueError, match="policy|accepted"):
        await retrieval_api().retrieve_question_facts(
            detail, snapshot, "Example Product", "feature", embedding_provider=provider
        )
    assert model.texts == []


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["factory", "embedding", "reranker"])
@pytest.mark.parametrize("strict", [True, False])
async def test_local_failures_obey_explicit_strict_policy(
    semantic_provider, tmp_path, monkeypatch, stage, strict
):
    provider, model = semantic_provider
    module = retrieval_api()
    monkeypatch.setenv("KB_LOCAL_MODEL_STRICT", "true" if strict else "false")
    failure = RuntimeError(f"anonymous-{stage}-failure")

    def fail(*args, **kwargs):
        raise failure

    kwargs = {"embedding_provider": provider}
    if stage == "factory":
        monkeypatch.setattr(module, "get_local_provider_from_env", fail)
        kwargs = {}
    elif stage == "embedding":
        monkeypatch.setattr(model, "encode", fail)
    else:

        class FailingCrossEncoder:
            predict = staticmethod(fail)

        monkeypatch.setattr(
            "packages.knowledge.local_models._load_cross_encoder",
            lambda *a, **k: FailingCrossEncoder(),
        )
        kwargs["reranker_provider"] = LocalRerankerProvider(
            tmp_path, model_id="BAAI/bge-reranker-v2-m3", revision="test"
        )
    detail, snapshot = research_case(
        ["Visitors must authenticate."], question="Example Product: Must visitors authenticate?"
    )
    if strict:
        with pytest.raises(RuntimeError) as caught:
            await module.retrieve_question_facts(
                detail, snapshot, "Example Product", "feature", **kwargs
            )
        assert caught.value is failure
    else:
        selected, diagnostic = await module.retrieve_question_facts(
            detail, snapshot, "Example Product", "feature", **kwargs
        )
        assert selected
        assert diagnostic["mode"] == "degraded_lexical"
        assert diagnostic["degraded_reasons"]


@pytest.mark.asyncio
async def test_unknown_source_material_cannot_consume_question_fact_quota(semantic_provider):
    provider, model = semantic_provider
    detail, snapshot = research_case(["Visitors must authenticate."])
    snapshot = replace_snapshot(
        detail,
        snapshot,
        sources=tuple(
            source.model_copy(update={"material_level": "unknown"}) for source in snapshot.sources
        ),
    )
    selected, diagnostic = await retrieval_api().retrieve_question_facts(
        detail, snapshot, "Example Product", "feature", embedding_provider=provider
    )
    assert selected == ()
    assert diagnostic["mode"] == "no_candidates"
    assert model.texts == []
