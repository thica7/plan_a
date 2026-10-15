"""Synthetic fixed excerpts exercise metric boundaries, never formal human labels."""

import hashlib
import json
from datetime import UTC, datetime

import pytest

from packages.knowledge.models import KnowledgeChunk, KnowledgeDocument, RetrievalHit
from packages.knowledge.product_benchmark import run_product_benchmark


def context_fixture(tmp_path):
    condition = "Only workspace owners may export the workspace."
    anchor = "Northstar editor supports offline editing."
    text = condition + "\n\n" + "Background reference material. " * 55 + "\n\n" + anchor
    source = dict(id="source-1", title="Northstar feature guide", url="https://fixture.example/guide",
                  product="Northstar", market="US", role="source", text=text,
                  content_hash=hashlib.sha256(text.encode()).hexdigest(), published_at=None,
                  updated_at=None, fetched_at="2026-10-01T00:00:00Z", source_date_status="not_provided")
    query = dict(id="query-1", query="Northstar editor offline", product="Northstar", market="US",
                 purpose="evaluation", as_of="2026-10-15")
    label = dict(query_id="query-1", expected_outcome="answer", review_status="candidate",
                 reviewed_by=None, reviewed_at=None, expected_facts=[condition, anchor],
                 proofs=[dict(source_id="source-1", start=text.index(quote),
                              end=text.index(quote) + len(quote), quote=quote)
                         for quote in (condition, anchor)])
    paths = tuple(tmp_path / name for name in ("corpus.jsonl", "queries.jsonl", "labels.jsonl"))
    for path, value in zip(paths, (source, query, label), strict=True):
        path.write_text(json.dumps(value) + "\n")
    return paths


@pytest.mark.asyncio
async def test_context_gain_is_scored_separately_from_anchor_ranking(tmp_path):
    paths = context_fixture(tmp_path)
    baseline = await run_product_benchmark(*paths, mode="candidate-diagnostic", top_k=1,
                                           enable_query_fusion=False, expand_context=False)
    expanded = await run_product_benchmark(*paths, mode="candidate-diagnostic", top_k=1,
                                           enable_query_fusion=False, expand_context=True)
    old, new = baseline["queries"][0], expanded["queries"][0]
    assert old["metrics"]["recall_at_k"] == new["metrics"]["recall_at_k"] == 1
    assert old["proof_excerpt_recall"] == new["anchor_proof_excerpt_recall"] < 1
    assert new["proof_excerpt_recall"] == 1 and new["extra_context_chars"] > 0
    assert expanded["expand_context"] is True and baseline["expand_context"] is False
    assert expanded["semantic_quality_verified"] is False


def test_metric_refuses_forged_expanded_context():
    from packages.knowledge.product_benchmark import _evidence_excerpt

    anchor = "Northstar supports offline editing."
    text = "Only owners may export.\n\n" + anchor
    doc = KnowledgeDocument(id="d", title="Guide", text=text, source_type="official_docs",
                            content_hash="body-hash", fetched_at=datetime.now(UTC),
                            workspace_id="ws", project_id="project", competitor="Northstar")
    chunk = KnowledgeChunk(id="c", document_id="d", text=anchor, chunk_index=1, token_count=6,
                           embedding_model="", content_hash=hashlib.sha256(anchor.encode()).hexdigest()[:16])
    hit = RetrievalHit(chunk_id="c", document_id="d", text=anchor, score=1,
                       content_hash=doc.content_hash, workspace_id="ws", project_id="project",
                       competitor="Northstar", metadata={"evidence_context": {
                           "status": "expanded", "text": text, "start": 0, "end": len(text),
                           "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                           "source": {"document_id": "different-document"},
                       }})
    with pytest.raises(RuntimeError, match="context"):
        _evidence_excerpt(hit, doc, chunk)


def test_repeated_anchor_without_coordinates_cannot_claim_a_specific_proof_span():
    from packages.knowledge.product_benchmark import _evidence_excerpt

    anchor = "Northstar supports offline editing."
    doc = KnowledgeDocument(id="d", title="Guide", text=anchor + "\n\n" + anchor,
                            source_type="official_docs", content_hash="body-hash",
                            fetched_at=datetime.now(UTC))
    chunk = KnowledgeChunk(id="c", document_id="d", text=anchor, chunk_index=1, token_count=6,
                           embedding_model="", content_hash=hashlib.sha256(anchor.encode()).hexdigest()[:16])
    hit = RetrievalHit(chunk_id="c", document_id="d", text=anchor, score=1, content_hash="body-hash")
    excerpt, start, end, context = _evidence_excerpt(hit, doc, chunk)
    assert excerpt == anchor and context is None
    assert start is None and end is None


@pytest.mark.asyncio
async def test_benchmark_handles_ambiguous_top_anchor_and_later_valid_proof(tmp_path, monkeypatch):
    from packages.knowledge.product_benchmark import run_product_benchmark
    from packages.knowledge.retrieval import RetrievalService

    repeated = 'Northstar battery export supports offline editing. ' * 24
    proof = 'Northstar workspace owners may export battery files.'
    text = repeated + '\n\n' + repeated + '\n\n' + proof
    source = dict(id='source', title='Northstar feature guide', url='https://fixture.example/guide',
        product='Northstar', market='US', role='source', text=text,
        content_hash=hashlib.sha256(text.encode()).hexdigest(), published_at=None, updated_at=None,
        fetched_at='2026-10-01T00:00:00Z', source_date_status='not_provided')
    query = dict(id='query', query='Northstar battery export', product='Northstar', market='US',
        purpose='evaluation', as_of='2026-10-15')
    start = text.index(proof)
    label = dict(query_id='query', expected_outcome='answer', review_status='candidate',
        reviewed_by=None, reviewed_at=None, expected_facts=[proof],
        proofs=[dict(source_id='source', start=start, end=start + len(proof), quote=proof)])
    paths = [tmp_path / name for name in ('corpus.jsonl', 'queries.jsonl', 'labels.jsonl')]
    for path, value in zip(paths, (source, query, label)):
        path.write_text(json.dumps(value) + '\n')

    # Return two genuine ingested anchors in an admissible ranking order.
    async def repeated_then_unique(self, question, hits, request):
        repeated_hits = [hit for hit in hits if text.count(hit.text) > 1]
        proof_hits = [hit for hit in hits if proof in hit.text and text.count(hit.text) == 1]
        assert repeated_hits and proof_hits
        return [repeated_hits[0], proof_hits[0]]
    monkeypatch.setattr(RetrievalService, '_post_process', repeated_then_unique)
    result = await run_product_benchmark(*paths, mode='candidate-diagnostic', top_k=3,
        enable_query_fusion=False, expand_context=False)
    row = result['queries'][0]
    assert row['hits'][0]['excerpt_start'] is None
    assert row['proof_excerpt_recall'] == 1
    assert row['proof_excerpt_in_top_1'] is False
