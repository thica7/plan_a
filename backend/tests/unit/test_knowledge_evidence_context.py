"""Evidence context is bounded, canonical text surrounding an unchanged anchor."""
from __future__ import annotations

import hashlib
import importlib

import pytest

from packages.knowledge.ingestion import IngestionPipeline
from packages.knowledge.models import DocumentCreate, RetrievalRequest
from packages.knowledge.repository import KnowledgeRepository
from packages.knowledge.retrieval import RetrievalService


def req(**kwargs):
    values = dict(query="battery", mode="sparse", enable_query_rewrite=False,
                  workspace_id="ws", project_id="project", intent_policy="raw",
                  final_top_k=1, rerank_top_k=0)
    values.update(kwargs)
    return RetrievalRequest(**values)


async def seed(repo, text, **kwargs):
    fields = dict(title="Guide", text=text, source_type="manual", workspace_id="ws",
                  project_id="project", competitor="Acme Vault 7", dimension="feature", market="CN")
    fields.update(kwargs)
    pipeline = IngestionPipeline(repo, object(), chunk_size=55, chunk_overlap=8)
    identifier = await pipeline.ingest(DocumentCreate(**fields))
    return identifier, await repo.get_chunks_for_document(identifier)


@pytest.mark.asyncio
async def test_context_keeps_anchor_and_uses_continuous_canonical_parent(tmp_path):
    text = "Requires admin approval before enabling.\n\nThe battery supports offline operation.\n\nOnly enterprise plans include this capability."
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        doc_id, chunks = await seed(repo, text)
        response = await RetrievalService(repo, object(), embed_fn=lambda texts: []).retrieve(req())
        hit = response.hits[0]
        anchor = next(chunk for chunk in chunks if chunk.id == hit.chunk_id)
        context = hit.metadata["evidence_context"]
        assert hit.text == anchor.text
        assert context["status"] == "expanded" and context["text"] == text
        assert text[context["start"]:context["end"]] == context["text"]
        assert context["covered_chunk_ids"] == [chunk.id for chunk in chunks]
        assert context["source"]["document_id"] == doc_id
        assert context["anchor"]["chunk_id"] == hit.chunk_id
        assert context["text_sha256"] == hashlib.sha256(text.encode()).hexdigest()
        module = importlib.import_module("packages.knowledge.evidence_context")
        assert module.evidence_text_for_hit(hit) == text
        assert module.get_validated_evidence_context(hit.model_dump(), canonical_text=text) == context


@pytest.mark.asyncio
async def test_document_metadata_cannot_forge_evidence_context_even_when_disabled(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        await seed(repo, "battery has a canonical source.", metadata={"evidence_context": {"text": "forged"}})
        response = await RetrievalService(repo, object(), embed_fn=lambda texts: [], expand_context=False).retrieve(req())
        assert "evidence_context" not in response.hits[0].metadata


@pytest.mark.asyncio
async def test_ambiguous_legacy_anchor_is_skipped_without_offsets(tmp_path):
    text = "battery repeated requires admin approval.\n\nbattery repeated requires admin approval."
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        _, chunks = await seed(repo, text)
        for chunk in chunks:
            await repo._connection.execute("UPDATE chunks SET metadata_json='{}' WHERE id=?", [chunk.id])
        response = await RetrievalService(repo, object(), embed_fn=lambda texts: []).retrieve(req())
        context = response.hits[0].metadata["evidence_context"]
        assert context["status"] == "skipped" and context["omission_reason"] == "ambiguous_anchor"
        assert "text" not in context


@pytest.mark.asyncio
async def test_bad_anchor_coordinates_are_skipped_without_falling_back(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        _, chunks = await seed(repo, "battery canonical anchor.\n\nNeeds admin approval.")
        import json
        metadata = {**chunks[0].metadata, "source_start": 1, "source_end": 5}
        await repo._connection.execute("UPDATE chunks SET metadata_json=? WHERE id=?", [json.dumps(metadata), chunks[0].id])
        response = await RetrievalService(repo, object(), embed_fn=lambda texts: []).retrieve(req())
        assert response.hits[0].metadata["evidence_context"]["omission_reason"] == "invalid_anchor_offsets"


@pytest.mark.asyncio
async def test_context_stays_in_current_section_and_ignores_document_parent_version(tmp_path):
    text = "Offline\n\nThe battery supports operation.\n\nAdmin approval is required.\n\nPricing\n\nFree access is unavailable."
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        old, _ = await seed(repo, "OLD VERSION battery has unrestricted access.", url="https://example.test/guide")
        current, _ = await seed(repo, text, url="https://example.test/guide",
                                markdown="# Offline\n# Pricing")
        stored = await repo.get_document(current)
        assert stored.parent_document_id == old
        response = await RetrievalService(repo, object(), embed_fn=lambda texts: []).retrieve(req())
        context = response.hits[0].metadata["evidence_context"]
        assert context["source"]["document_id"] == current
        assert context["text"].strip().endswith("Admin approval is required.")
        assert "Pricing" not in context["text"] and "OLD VERSION" not in context["text"]


@pytest.mark.asyncio
async def test_incomplete_table_cannot_be_expanded(tmp_path):
    text = "battery | enabled\n| --- | --- |\n| Basic | yes |"
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        await seed(repo, text, metadata={"tables": [{"text": text, "structure_gap": "missing_headers"}]})
        response = await RetrievalService(repo, object(), embed_fn=lambda texts: []).retrieve(req())
        context = response.hits[0].metadata["evidence_context"]
        assert context["status"] == "skipped" and context["omission_reason"] == "incomplete_table"


@pytest.mark.asyncio
async def test_context_after_cache_hit_is_rebuilt_from_corrected_canonical_text(tmp_path):
    old_text = "battery canonical evidence.\n\nOnly administrators can enable it."
    new_text = "battery canonical evidence.\n\nAll paid accounts can enable it."
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        doc_id, _ = await seed(repo, old_text)
        service = RetrievalService(repo, object(), embed_fn=lambda texts: [])
        first = await service.retrieve(req())
        assert first.hits[0].metadata["evidence_context"]["text"] == old_text
        digest = hashlib.sha256(new_text.encode()).hexdigest()[:16]
        await repo._connection.execute("UPDATE documents SET text=?,content_hash=? WHERE id=?", [new_text, digest, doc_id])
        second = await service.retrieve(req())
        assert second.hits[0].metadata["evidence_context"]["text"] == new_text
        cached = service._retrieval_cache.get(service._response_cache_key(req()))
        assert "evidence_context" not in cached.hits[0].metadata


@pytest.mark.asyncio
async def test_context_helper_rejects_identity_hash_range_and_anchor_tampering(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        text = "battery canonical source evidence.\n\nOnly administrators can enable this capability."
        await seed(repo, text)
        response = await RetrievalService(repo, object(), embed_fn=lambda texts: []).retrieve(req())
        hit = response.hits[0]
        module = importlib.import_module("packages.knowledge.evidence_context")
        context = hit.metadata["evidence_context"]
        for field, value in [("document_id", "other"), ("document_version", 9),
                             ("workspace_id", "foreign"), ("competitor", "Acme Vault 8"),
                             ("dimension", "pricing"), ("market", "US"),
                             ("source_role", "historical_report"), ("content_hash", "bad")]:
            changed = hit.model_copy(deep=True)
            changed.metadata["evidence_context"]["source"][field] = value
            assert module.get_validated_evidence_context(changed) is None
        for field, value in [("text", "forged"), ("start", -1), ("end", 9999),
                             ("text_sha256", "bad"), ("start", True)]:
            changed = hit.model_copy(deep=True)
            changed.metadata["evidence_context"][field] = value
            assert module.get_validated_evidence_context(changed) is None
        changed = hit.model_copy(update={"text": "wrong anchor"}, deep=True)
        assert module.get_validated_evidence_context(changed) is None
        assert module.evidence_text_for_hit(changed) == "wrong anchor"
        assert module.get_validated_evidence_context(hit, canonical_text="other source") is None
        assert module.get_validated_evidence_context(hit) == context


@pytest.mark.asyncio
async def test_context_budget_caps_each_hit_and_request_and_deduplicates_overlap(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        text = "battery " + "a" * 80 + "\n\n" + "requires admin " + "b" * 2100
        for index in range(4):
            await seed(repo, text + str(index), title=f"Guide {index}")
        response = await RetrievalService(repo, object(), embed_fn=lambda texts: []).retrieve(req(final_top_k=4))
        contexts = [hit.metadata["evidence_context"] for hit in response.hits]
        extra = sum(len(context["text"]) - len(hit.text) for hit, context in zip(response.hits, contexts)
                    if context["status"] == "expanded")
        assert extra <= 6000
        assert all(len(context["text"]) <= 3000 for context in contexts if context["status"] == "expanded")
        assert any(context["omission_reason"] == "request_budget" for context in contexts)
        one = await RetrievalService(repo, object(), embed_fn=lambda texts: []).retrieve(req(query="a", final_top_k=10))
        expanded = [hit.metadata["evidence_context"] for hit in one.hits
                    if hit.metadata["evidence_context"]["status"] == "expanded"]
        for index, context in enumerate(expanded):
            assert not any(context["source"]["document_id"] == previous["source"]["document_id"]
                           and context["start"] < previous["end"] and previous["start"] < context["end"]
                           for previous in expanded[:index])


@pytest.mark.asyncio
async def test_oversize_table_anchor_is_preserved_and_context_skipped(tmp_path):
    text = "battery | " + "a" * 3100
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        await seed(repo, text, metadata={"tables": [{"text": text}]})
        response = await RetrievalService(repo, object(), embed_fn=lambda texts: []).retrieve(req())
        assert response.hits[0].text == text
        assert response.hits[0].metadata["evidence_context"]["omission_reason"] == "anchor_too_large"


@pytest.mark.asyncio
async def test_helper_rejects_malformed_mapping_scope_and_noncanonical_hash(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        await seed(repo, "battery canonical source evidence.\n\nOnly administrators can enable this capability.")
        response = await RetrievalService(repo, object(), embed_fn=lambda texts: []).retrieve(req())
        helper = importlib.import_module("packages.knowledge.evidence_context").get_validated_evidence_context
        data = response.hits[0].model_dump()
        for field, value in [("workspace_id", {"foreign": "scope"}), ("document_version", True),
                             ("content_hash", "arbitrary"), ("source_role", "unsupported")]:
            import copy
            changed = copy.deepcopy(data)
            changed[field] = value
            changed["metadata"]["evidence_context"]["source"][field] = value
            assert helper(changed) is None
        changed = response.hits[0].model_copy(update={"status": "archived"})
        assert helper(changed) is None


@pytest.mark.asyncio
async def test_partial_canonical_table_is_skipped_even_for_legacy_unmarked_chunk(tmp_path):
    table = "battery | admin | enterprise\nBasic | required | unavailable\nPremium | required | available"
    text = "Rules\n\n" + table + "\n\n" + "Other content " * 250
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        identifier, chunks = await seed(repo, text, metadata={"tables": [{"text": table}]})
        anchor = next(chunk for chunk in chunks if "battery" in chunk.text)
        import json
        changed = "battery | admin | enterprise"
        await repo._connection.execute(
            "UPDATE chunks SET text=?,content_hash=?,metadata_json=? WHERE id=?",
            [changed, hashlib.sha256(changed.encode()).hexdigest()[:16], json.dumps({}), anchor.id])
        response = await RetrievalService(repo, object(), embed_fn=lambda texts: []).retrieve(req())
        context = response.hits[0].metadata["evidence_context"]
        assert context["status"] == "skipped" and context["omission_reason"] == "partial_table"


@pytest.mark.asyncio
async def test_stale_canonical_hash_does_not_produce_expanded_context_after_cache_hit(tmp_path):
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        identifier, _ = await seed(repo, "battery canonical evidence.\n\nOnly administrators can enable it.")
        service = RetrievalService(repo, object(), embed_fn=lambda texts: [])
        assert (await service.retrieve(req())).hits[0].metadata["evidence_context"]["status"] == "expanded"
        await repo._connection.execute("UPDATE documents SET text=text || 'corrected' WHERE id=?", [identifier])
        context = (await service.retrieve(req())).hits[0].metadata["evidence_context"]
        assert context["status"] == "skipped" and context["omission_reason"] == "source_hash_mismatch"


@pytest.mark.asyncio
async def test_neighbor_context_preserves_overlapping_text_once_and_uses_only_nearest_chunks(tmp_path):
    text = "\n\n".join([f"Row {index} " + ("battery " if index == 6 else "prefix ") + str(index) * 35
                           for index in range(12)])
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        await seed(repo, text)
        response = await RetrievalService(repo, object(), embed_fn=lambda texts: []).retrieve(req())
        context = response.hits[0].metadata["evidence_context"]
        # Small parent is complete; next test corpus forces the bounded neighbour strategy.
        assert context["text"] == text
        identifier, _ = await seed(repo, text + "\n\n" + "tail " * 700,
                                   competitor="Other", title="Long parent")
        response = await RetrievalService(repo, object(), embed_fn=lambda texts: []).retrieve(req(competitors=["Other"]))
        context = response.hits[0].metadata["evidence_context"]
        assert context["method"] == "adjacent_chunks" and context["source"]["document_id"] == identifier
        assert "Row 5 " in context["text"] and "Row 6 " in context["text"] and "Row 7 " in context["text"]
        assert "Row 4 " not in context["text"] and "Row 8 " not in context["text"]
        assert len(context["covered_chunk_ids"]) == 3


@pytest.mark.asyncio
async def test_dense_context_does_not_replace_vector_anchor_reference(tmp_path):
    from packages.knowledge.embeddings import HashEmbeddingProvider
    from test_knowledge_scope_retrieval import MemoryVectors

    text = "Requires admin approval before enabling.\n\nThe battery supports offline operation.\n\nOnly enterprise plans include this capability."
    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        vectors = MemoryVectors()
        provider = HashEmbeddingProvider(dimensions=8)
        pipeline = IngestionPipeline(repo, vectors, chunk_size=55, chunk_overlap=8)
        identifier = await pipeline.ingest(DocumentCreate(
            title="Guide", text=text, source_type="manual", workspace_id="ws", project_id="project"),
            embedding_provider=provider)
        service = RetrievalService(repo, vectors, embed_fn=provider.embed_documents,
                                   embedding_provider=provider)
        request = req(mode="dense")
        before = (await vectors.search([]))[0]
        for response in [await service.retrieve(request), await service.retrieve(request)]:
            hit = response.hits[0]
            assert hit.document_id == identifier and hit.chunk_id == before.chunk_id
            assert hit.text == before.text and hit.metadata["vector_index"] == before.metadata["vector_index"]
            assert hit.metadata["evidence_context"]["text"] == text


@pytest.mark.asyncio
async def test_context_rejects_malformed_canonical_structure_without_crashing(tmp_path):
    import json

    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        identifier, _ = await seed(repo, "battery canonical evidence.\n\nOnly administrators can enable it.")
        for metadata in ({"headings": 42}, {"tables": 42}):
            await repo._connection.execute("UPDATE documents SET metadata_json=? WHERE id=?", [json.dumps(metadata), identifier])
            response = await RetrievalService(repo, object(), embed_fn=lambda texts: []).retrieve(req())
            assert response.hits[0].metadata["evidence_context"]["omission_reason"] == "invalid_source_structure"


@pytest.mark.asyncio
async def test_context_helper_rejects_unhashable_discriminator_values(tmp_path):
    import copy

    async with KnowledgeRepository(str(tmp_path / "kb.db")) as repo:
        await seed(repo, "battery canonical source evidence.\n\nOnly administrators can enable this capability.")
        response = await RetrievalService(repo, object(), embed_fn=lambda texts: []).retrieve(req())
        helper = importlib.import_module("packages.knowledge.evidence_context").get_validated_evidence_context
        data = response.hits[0].model_dump()
        bad_method = copy.deepcopy(data)
        bad_method["metadata"]["evidence_context"]["method"] = []
        assert helper(bad_method) is None
        bad_role = copy.deepcopy(data)
        bad_role["source_role"] = []
        bad_role["metadata"]["evidence_context"]["source"]["source_role"] = []
        assert helper(bad_role) is None
        bad_status = copy.deepcopy(data)
        bad_status["status"] = []
        assert helper(bad_status) is None
