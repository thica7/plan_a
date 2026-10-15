"""Synthetic offline fixtures; real retrieval, admission, agents and publication guards.

Only captured page bytes and model responses are replayed. These tests establish
execution and binding behavior, not real-model factual accuracy or web freshness.
"""

from datetime import UTC, datetime, timedelta
import json
import socket

import pytest
from test_agent_evidence_alignment import InputReplay

from packages.agents import SubagentContext
from packages.agents.writer.quality_preflight import run_writer_quality_preflight
from packages.knowledge.ingestion import IngestionPipeline
from packages.knowledge.models import DocumentCreate
from packages.knowledge.repository import KnowledgeRepository
from packages.research.evidence.admission import admit_evidence_items
from packages.research.extraction.feature import extract_generic_capabilities
from packages.research.models import CapturedPage, ResearchResult, SourceCandidate


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def deny(*_args, **_kwargs):
        raise AssertionError("Offline Agent replay attempted network access")

    for method in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, method, deny)


@pytest.mark.asyncio
@pytest.mark.parametrize("cross_product_claim", [False, True])
async def test_two_product_rag_to_real_hardening_and_qa(tmp_path, monkeypatch, cross_product_claim):
    monkeypatch.setenv("KB_DB_PATH", str(tmp_path / "alignment.db"))
    monkeypatch.setenv("KB_RETRIEVAL_MODE", "sparse")
    monkeypatch.setenv("KB_RERANKER_PROVIDER", "none")
    service = InputReplay(tmp_path)
    record = service.record
    detail = record.detail
    products = ["Acme Vault 7", "Maple Journal 4"]
    detail.plan.competitors, detail.plan.dimensions = products, ["feature"]
    detail.raw_sources = []
    detail.topic = "比较两款产品断网编辑及重新联网同步的条件；输出中文并保留出处"
    detail.plan.topic = detail.topic
    detail.plan.homepage_hints = {product: f"https://fixture{index}.example" for index, product in enumerate(products)}
    quotes = {product: f"{product} supports offline editing and synchronizes changes when connected."
              for product in products}
    selected_ids = {}
    async with KnowledgeRepository() as repo:
        pipeline = IngestionPipeline(repo, object())
        for index, product in enumerate(products):
            base = dict(title=f"{product} offline editing guide", text=quotes[product],
                        url=f"https://fixture{index}.example/features", source_type="official_docs",
                        competitor=product, dimension="feature", workspace_id=detail.workspace_id,
                        project_id=detail.project_id, last_verified_at=datetime.now(UTC))
            selected_ids[product] = await pipeline.ingest(DocumentCreate(**base))
            # Similar bodies must not bypass project, source role or verification age.
            for suffix, overrides in (
                ("foreign-project", {"project_id": "another-project"}),
                ("report", {"source_role": "historical_report"}),
                ("stale", {"last_verified_at": datetime.now(UTC) - timedelta(days=800)}),
                ("unmarked", {"competitor": None}),
            ):
                await pipeline.ingest(DocumentCreate(**{
                    **base, "url": base["url"] + "/" + suffix,
                    "text": base["text"] + " " + suffix, **overrides,
                }))

    source_by_product = {}
    for product in products:
        context = SubagentContext(run_id=detail.id, agent="collector", subagent=f"feature::{product}")
        seeds = await service._collect_competitor_from_kb(record, detail, "feature", product,
                                                        context, target_source_count=5)
        assert len(seeds) == 1 and seeds[0].metadata["kb_document_id"] == selected_ids[product]
        assert not seeds[0].metadata.get("normalized_fields")
        brief = service._research_brief(detail, product, "feature")
        candidate = SourceCandidate(title=seeds[0].title, url=str(seeds[0].url), origin="web_search",
                                    competitor=product, dimension="feature")
        page = CapturedPage(candidate_id=candidate.id, requested_url=candidate.url,
                            final_url=candidate.url, status="ok", title=candidate.title,
                            text=quotes[product], snippet=quotes[product],
                            content_hash=f"captured-{product}", quality_score=1)
        extraction = extract_generic_capabilities(brief, page)
        items = admit_evidence_items([extraction], captured_pages=[page], candidates=[candidate], brief=brief)
        assert items and all(item.status == "accepted" for item in items)
        result = ResearchResult(brief=brief, candidates=[candidate], captured_pages=[page],
                                extractions=[extraction], evidence_items=items)
        accepted = service._raw_sources_from_research_result(detail, brief, result,
                                                             batch_sources=[], target_source_count=1)
        assert accepted
        await service._persist_captured_sources_to_kb(record, detail, accepted, result, context)
        detail.raw_sources.extend(accepted)
        source_by_product[product] = accepted[0].id
    snapshot = await service._prepare_evidence_snapshot(record, phase="analysis")

    async def replay_json(_record, **kwargs):
        service.inputs.append(kwargs)
        if kwargs["agent"] == "analyst":
            product = kwargs["user"].split("Competitor: ")[1].splitlines()[0]
            return {"feature_tree": {"summary_claims": [{"claim": quotes[product],
                    "source_ids": [source_by_product[product]], "confidence": .9}]}}
        if kwargs["agent"] == "comparator":
            return {"matrix_summary": ["Both captured sources document offline editing"],
                    "winner_by_dimension": {}}
        return {"coverage_gaps": [], "gate_status": "pass"}

    async def replay_text(_record, **kwargs):
        service.inputs.append(kwargs)
        payload = json.loads(kwargs["user"].split("\nJSON:\n", 1)[1])
        if kwargs["name"] == "dimension_claim_writer":
            fact = next(f for f in payload["evidence_view"]["facts"] if f["field"] == "evidence_terms")
            product = fact["competitor"]
            claim = dict(text=quotes[product], kind="fact", competitor=product,
                         dimension="feature", fact_ids=[fact["id"]], source_ids=[fact["source_id"]])
            if fact.get("operation_observations"):
                claim["observation_id"] = fact["operation_observations"][0]["observation_id"]
            if cross_product_claim and product == products[0]:
                claim["source_ids"] = [source_by_product[products[1]]]
            return json.dumps({"claims": [claim]})
        assert kwargs["name"] == "dimension_claim_review"
        return json.dumps({"reviews": [{"claim_id": claim["id"], "verdict": "supported",
                            "reason": "Replay review; binding guards must still validate."}
                           for claim in payload["claims"]]})

    monkeypatch.setattr(service, "_trace_llm_json", replay_json)
    monkeypatch.setattr(service, "_trace_llm_text", replay_text)
    hardening_calls = []
    original_hardening = service._harden_report_markdown

    def recording_hardening(current_detail, markdown):
        result = original_hardening(current_detail, markdown)
        hardening_calls.append(result)
        return result

    monkeypatch.setattr(service, "_harden_report_markdown", recording_hardening)
    for source in detail.raw_sources:
        source.snippet = "LIVE_POISON"
    for product in products:
        await service._real_analyst_branch_step(record, "feature", product, expected_snapshot_id=snapshot.id)
    await service._real_comparator_step(record)
    await service._real_reflector_step(record)
    await service._real_writer_step(record)
    assert hardening_calls and run_writer_quality_preflight(detail, detail.report_md).passed
    await service._real_qa_step(record)
    assert all("LIVE_POISON" not in item["user"] for item in service.inputs)
    assert {use.agent for use in detail.evidence_consumptions} >= {
        "analyst", "comparator", "reflector", "writer", "qa"}
    assert all(use.snapshot_id == snapshot.id for use in detail.evidence_consumptions)
    assert f"[source:{source_by_product[products[1]]}]" in detail.report_md
    assert (quotes[products[0]] in detail.report_md) is not cross_product_claim
    assert [span.name for span in detail.trace_spans].count("rag_kb_warm_start") == 2


@pytest.mark.asyncio
async def test_planner_scope_and_real_survey_do_not_create_evidence(tmp_path):
    service = InputReplay(tmp_path)
    record = service.record
    record.detail.raw_sources = []
    record.detail.plan.dimensions = ["feature", "persona"]
    await service._real_planner_step(record)
    await service._run_survey_interview_enrichment(record, record.detail.plan.dimensions,
                                                 record.detail.plan.competitors)
    assert record.detail.plan.competitors == ["Phone X", "Phone X Pro"]
    assert not record.detail.raw_sources and not record.detail.evidence_consumptions
    assert [item["agent"] for item in service.inputs] == ["planner"]
    assert any(message.message_type == "survey_interview_skipped" for message in record.detail.agent_messages)
