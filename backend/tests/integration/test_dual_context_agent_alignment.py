"""Offline synthetic replay proves expanded prerequisites reach actual consumers."""

from datetime import UTC, datetime
import json
import socket

import pytest
from claim_review_fixture import supported_review
from test_agent_evidence_alignment import InputReplay

from packages.agents import SubagentContext
from packages.agents.writer.quality_preflight import run_writer_quality_preflight
from packages.knowledge.ingestion import IngestionPipeline
from packages.knowledge.models import DocumentCreate
from packages.knowledge.repository import KnowledgeRepository
from packages.research.evidence.admission import admit_evidence_items
from packages.research.extraction.feature import extract_generic_capabilities
from packages.research.models import CapturedPage, ResearchResult, SourceCandidate


@pytest.mark.asyncio
async def test_parent_prerequisite_survives_collector_admission_snapshot_and_writer(tmp_path, monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("Offline context replay attempted network access")

    for method in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, method, deny)
    monkeypatch.setenv("KB_DB_PATH", str(tmp_path / "context.db"))
    monkeypatch.setenv("KB_RETRIEVAL_MODE", "sparse")
    monkeypatch.setenv("KB_RERANKER_PROVIDER", "none")
    service = InputReplay(tmp_path)
    record, product = service.record, "Acme Vault 7"
    detail = record.detail
    detail.plan.competitors, detail.plan.dimensions = [product], ["feature"]
    detail.plan.homepage_hints = {product: "https://fixture.example"}
    detail.topic = "Acme Vault 7 在断网时能否编辑，重新联网同步需要哪些条件？"
    detail.plan.topic = detail.topic
    detail.raw_sources = []
    prerequisite = "Acme Vault 7 workspace owners can enable offline editing."
    capability = "Acme Vault 7 supports offline editing and synchronizes changes when connected."
    text = prerequisite + "\n\n" + "Background reference material. " * 55 + "\n\n" + capability
    async with KnowledgeRepository() as repo:
        await IngestionPipeline(repo, object()).ingest(DocumentCreate(
            title=f"{product} feature guide", text=text, url="https://fixture.example/features",
            # This local corpus replays a previously verified webpage capture.
            source_type="webpage_verified", competitor=product, dimension="feature",
            workspace_id=detail.workspace_id, project_id=detail.project_id,
            last_verified_at=datetime.now(UTC),
        ))
    context = SubagentContext(run_id=detail.id, agent="collector", subagent=f"feature::{product}")
    seeds = await service._collect_competitor_from_kb(record, detail, "feature", product,
                                                    context, target_source_count=1)
    assert len(seeds) == 1
    seed = seeds[0]
    assert prerequisite in seed.snippet and capability in seed.snippet
    assert seed.metadata["kb_evidence_context"]["status"] == "expanded"
    assert not seed.metadata.get("normalized_fields")

    # The capture boundary replays exactly what Collector retained; it does not
    # restore the known full page behind the tested context/summary path.
    brief = service._research_brief(detail, product, "feature")
    candidate = SourceCandidate(title=seed.title, url=str(seed.url), origin="web_search",
                                competitor=product, dimension="feature")
    page = CapturedPage(candidate_id=candidate.id, requested_url=candidate.url,
                        final_url=candidate.url, status="ok", title=candidate.title,
                        text=seed.snippet, snippet=seed.snippet,
                        content_hash="replayed-context-v1", quality_score=1)
    extraction = extract_generic_capabilities(brief, page)
    items = admit_evidence_items([extraction], captured_pages=[page], candidates=[candidate], brief=brief)
    assert items and any(item.status == "accepted" for item in items)
    result = ResearchResult(brief=brief, candidates=[candidate], captured_pages=[page],
                            extractions=[extraction], evidence_items=items)
    accepted = service._raw_sources_from_research_result(detail, brief, result,
                                                        batch_sources=[], target_source_count=1)
    assert accepted and accepted[0].source_type == "webpage_verified"
    await service._persist_captured_sources_to_kb(record, detail, accepted, result, context)
    detail.raw_sources = accepted
    snapshot = await service._prepare_evidence_snapshot(record, phase="analysis")
    assert detail.raw_sources[0].source_type == "webpage_verified"
    source_id = accepted[0].id

    async def replay_json(_record, **kwargs):
        service.inputs.append(kwargs)
        if kwargs["agent"] == "analyst":
            return {"feature_tree": {"summary_claims": [{"claim": prerequisite,
                    "source_ids": [source_id], "confidence": .9}]}}
        if kwargs["agent"] == "comparator":
            return {"matrix_summary": ["Owner prerequisite retained"], "winner_by_dimension": {}}
        return {"coverage_gaps": [], "gate_status": "pass"}

    async def replay_text(_record, **kwargs):
        service.inputs.append(kwargs)
        payload = json.loads(kwargs["user"].split("\nJSON:\n", 1)[1])
        if kwargs["name"] == "dimension_claim_writer":
            facts = payload["evidence_view"]["facts"]
            fact = next(f for f in facts if f["field"] == "evidence_terms"
                        and prerequisite.rstrip(".") in f["quote"])
            claim = dict(text=prerequisite, kind="fact", competitor=product, dimension="feature",
                         fact_ids=[fact["id"]], source_ids=[source_id])
            if fact.get("operation_observations"):
                claim["observation_id"] = fact["operation_observations"][0]["observation_id"]
            return json.dumps({"claims": [claim]})
        if kwargs["name"] == "dimension_answer_coverage":
            # Transport fixture only; semantic quality is tested with real models separately.
            return json.dumps({"answers": [dict(question_id=q["question_id"], status="answered",
                claim_ids=[c["id"] for c in payload["claims"]],
                reason="Replay retains offline editing and its owner prerequisite.")
                for q in payload["questions"]]})
        assert kwargs["name"] == "dimension_claim_review"
        return json.dumps({"reviews": [supported_review(claim,
                            "Fixed replay checks preserved owner prerequisite.")
                           for claim in payload["claims"]]})

    monkeypatch.setattr(service, "_trace_llm_json", replay_json)
    monkeypatch.setattr(service, "_trace_llm_text", replay_text)
    detail.raw_sources[0].snippet = "LIVE_POISON"
    await service._real_analyst_branch_step(record, "feature", product, expected_snapshot_id=snapshot.id)
    await service._real_comparator_step(record)
    await service._real_reflector_step(record)
    await service._real_writer_step(record)
    assert run_writer_quality_preflight(detail, detail.report_md).passed
    await service._real_qa_step(record)
    assert not detail.qa_findings
    assert prerequisite in detail.report_md and f"[source:{source_id}]" in detail.report_md
    for agent in ("analyst", "comparator", "reflector", "writer", "qa"):
        assert any(use.agent == agent and use.snapshot_id == snapshot.id
                   for use in detail.evidence_consumptions)
    assert all("LIVE_POISON" not in item["user"] for item in service.inputs)
    assert any(prerequisite.rstrip(".") in item["user"] for item in service.inputs if item["agent"] == "analyst")
    assert any(prerequisite.rstrip(".") in item["user"] for item in service.inputs if item["name"] == "dimension_claim_writer")
