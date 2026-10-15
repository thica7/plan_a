from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from packages.agents import SubagentContext
from packages.config import Settings
from packages.orchestrator.service import RunRecord, RunService
from packages.schema.api_dto import RunDetail
from packages.schema.models import AnalysisPlan
from packages.skills.registry import SkillRegistry
from packages.tools import rag_retrieve
from packages.tools.ingest_document import ingest_document_tool


@pytest.mark.asyncio
async def test_collector_reuses_verified_source_written_to_sparse_kb(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "kb.db"
    _remove_sqlite_files(db_path)
    monkeypatch.setenv("KB_DB_PATH", str(db_path))
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-kb-chain",
        workspace_id="ws-a",
        project_id="project-a",
        topic="Acme coding agent feature evidence",
        status="running",
        execution_mode="real",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        plan=AnalysisPlan(
            topic="Acme coding agent feature evidence",
            competitors=["Acme"],
            dimensions=["feature"],
            homepage_hints={"Acme": "https://acme.example"},
        ),
    )
    query = service._kb_retrieval_query(detail, "Acme", "feature")
    try:
        doc_id = await ingest_document_tool.ainvoke(
            {
                "url": "https://acme.example/features",
                "title": "Acme feature docs",
                "text": (
                    f"{query}\n\n"
                    "Acme supports agentic coding workflows, repository context, "
                    "tool calls, and code generation for developer teams."
                ),
                "competitor": "Acme",
                "dimension": "feature",
                "source_type": "webpage_verified",
                "metadata": {
                    "run_id": "collector-run-1",
                    "raw_source_id": "raw-source-feature-1",
                    "collector_confidence": 0.93,
                    "collector_candidate_origin": "web_fetch",
                    "collector_fetch_method": "browser_fetch",
                },
                "crawl_run_id": "collector-run-1",
                "index_vectors": False,
                "workspace_id": detail.workspace_id,
                "project_id": detail.project_id,
            }
        )

        record = RunRecord(detail=detail)
        context = SubagentContext(run_id=detail.id, agent="collector", subagent="feature::Acme")
        sources = await service._collect_competitor_from_kb(
            record,
            detail,
            "feature",
            "Acme",
            context,
            target_source_count=1,
        )

        assert len(sources) == 1
        source = sources[0]
        assert source.candidate_origin == "rag_kb"
        assert source.fetch_method == "rag_kb_retrieve"
        assert str(source.url) == "https://acme.example/features"
        assert source.metadata["kb_document_id"] == doc_id
        assert source.metadata["kb_raw_source_id"] == "raw-source-feature-1"
        assert source.metadata["kb_collector_run_id"] == "collector-run-1"
        assert source.metadata["kb_collector_candidate_origin"] == "web_fetch"
        assert source.metadata["kb_collector_fetch_method"] == "browser_fetch"
        assert source.metadata["kb_collector_confidence"] == 0.93
        assert json.loads(record.detail.trace_spans[-1].full_input)["intent_policy"] == "structured"
        plan = source.metadata["kb_retrieval"]["query_plan"]
        assert plan["queries"]
        assert all("official source" not in query for query in plan["queries"])
        assert plan["origin"] == "explicit"
    finally:
        _remove_sqlite_files(db_path)


@pytest.mark.asyncio
async def test_collector_traces_rejected_kb_hits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-kb-rejections",
        workspace_id="ws-a",
        project_id="project-a",
        topic="Acme coding agent feature evidence",
        status="running",
        execution_mode="real",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        plan=AnalysisPlan(
            topic="Acme coding agent feature evidence",
            competitors=["Acme"],
            dimensions=["feature"],
            homepage_hints={"Acme": "https://acme.example"},
        ),
    )

    fake_hits = [
        {
            "document_id": "kb-doc-empty",
            "chunk_id": "kb-chunk-empty",
            "text": "",
            "url": "https://acme.example/empty",
            "title": "Empty KB hit",
            "source_type": "webpage_verified",
            "score": 0.78,
        },
        {
            "document_id": "kb-doc-search",
            "chunk_id": "kb-chunk-search",
            "text": "Search result snippets should not be reused as verified evidence.",
            "url": "https://acme.example/search-result",
            "title": "Search-only KB hit",
            "source_type": "web_search_result",
            "rerank_score": 0.91,
            "metadata": {
                "raw_source_id": "raw-search-result",
                "run_id": "collector-run-search",
            },
        },
        {
            "document_id": "kb-doc-feature",
            "chunk_id": "kb-chunk-feature",
            "text": (
                "Acme supports agentic coding workflows, repository context, "
                "tool calls, and code generation for developer teams."
            ),
            "url": "https://acme.example/features",
            "title": "Acme feature docs",
            "source_type": "webpage_verified",
            "score": 0.87,
            "workspace_id": detail.workspace_id,
            "project_id": detail.project_id,
            "competitor": "Acme",
            "dimension": "feature",
            "document_version": 1,
            "content_hash": "verified-document-hash",
            "fetched_at": datetime.now(UTC).isoformat(),
            "metadata": {
                "raw_source_id": "raw-source-feature-1",
                "run_id": "collector-run-1",
            },
        },
    ]

    class FakeRagRetrieveTool:
        async def ainvoke(self, _request: dict[str, object]) -> list[dict[str, object]]:
            return fake_hits

    monkeypatch.setattr(rag_retrieve, "rag_retrieve_tool", FakeRagRetrieveTool())
    record = RunRecord(detail=detail)
    context = SubagentContext(run_id=detail.id, agent="collector", subagent="feature::Acme")

    sources = await service._collect_competitor_from_kb(
        record,
        detail,
        "feature",
        "Acme",
        context,
        target_source_count=1,
    )

    span = record.detail.trace_spans[-1]
    output = json.loads(span.full_output)
    assert len(sources) == 1
    assert span.name == "rag_kb_warm_start"
    assert span.metadata["hit_count"] == 3
    assert span.metadata["source_count"] == 1
    assert span.metadata["rejection_count"] == 2
    assert span.metadata["top_rejection_reason"] == "missing_text"
    assert output["rejections"] == [
        {
            "rank": 0,
            "reason": "missing_text",
            "document_id": "kb-doc-empty",
            "chunk_id": "kb-chunk-empty",
            "source_type": "webpage_verified",
            "url": "https://acme.example/empty",
            "title": "Empty KB hit",
            "score": 0.78,
        },
        {
            "rank": 1,
            "reason": "disallowed_source_type",
            "document_id": "kb-doc-search",
            "chunk_id": "kb-chunk-search",
            "source_type": "web_search_result",
            "url": "https://acme.example/search-result",
            "title": "Search-only KB hit",
            "score": 0.91,
            "kb_raw_source_id": "raw-search-result",
            "kb_collector_run_id": "collector-run-search",
        },
    ]


def _remove_sqlite_files(db_path: Path) -> None:
    for path in (db_path, db_path.with_suffix(".db-shm"), db_path.with_suffix(".db-wal")):
        path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_collector_auto_plan_keeps_numeric_conditions_in_their_own_clause(monkeypatch):
    from packages.knowledge.models import RetrievalRequest
    from packages.knowledge.query_intent import resolve_retrieval_plan

    service = RunService(SkillRegistry.from_default_path(), Settings(demo_mode=True))
    now = datetime.now(UTC)
    topic = "Acme V7 的充电器45W是什么规格？电池50Wh是否影响续航？"
    detail = RunDetail(id="numeric-collector", workspace_id="ws", project_id="project", topic=topic,
        status="running", execution_mode="real",
        created_at=now, updated_at=now, plan=AnalysisPlan(topic=topic, competitors=["Acme V7"], dimensions=["feature"]))
    plans = []

    class InspectTool:
        async def ainvoke(self, request):
            plans.append(resolve_retrieval_plan(RetrievalRequest(**request)))
            return []

    monkeypatch.setattr(rag_retrieve, "rag_retrieve_tool", InspectTool())
    await service._collect_competitor_from_kb(RunRecord(detail=detail), detail, "feature", "Acme V7",
        SubagentContext(run_id=detail.id, agent="collector", subagent="feature::Acme V7"), target_source_count=1)
    plan = plans[0]
    assert plan.origin == "auto"
    charger = next(query for query in plan.queries if "charger" in query)
    assert "45w" in charger and "50wh" not in charger
    assert "50" not in charger and "7" not in charger


@pytest.mark.asyncio
async def test_real_collector_scopes_multi_product_topic_to_product_and_dimension(tmp_path, monkeypatch):
    monkeypatch.setenv("KB_DB_PATH", str(tmp_path / "branches.db"))
    monkeypatch.setenv("KB_RETRIEVAL_MODE", "sparse")
    monkeypatch.setenv("KB_RERANKER_PROVIDER", "none")
    topic = "比较 Notion、Confluence、Coda 和 Nuclino 的创建、编辑、分享及各套餐权限"
    products = ["Notion", "Confluence", "Coda", "Nuclino"]
    now = datetime.now(UTC)
    detail = RunDetail(id="four-products", workspace_id="ws", project_id="project", topic=topic,
        status="running", execution_mode="real", created_at=now, updated_at=now,
        plan=AnalysisPlan(topic=topic, competitors=products, dimensions=["feature", "pricing"]))
    service = RunService(SkillRegistry.from_default_path(), Settings(demo_mode=True))
    documents = {}
    for dimension, text in (("feature", "Notion supports creating, editing and sharing pages."),
                            ("pricing", "Notion plans cost 10 USD per member monthly.")):
        documents[dimension] = await ingest_document_tool.ainvoke({
            "url": f"https://notion.example/{dimension}", "title": f"Notion {dimension} guide",
            "text": text, "competitor": "Notion", "dimension": dimension,
            "source_type": "official_docs", "index_vectors": False,
            "workspace_id": "ws", "project_id": "project",
        })
    plans = []
    for dimension in ("feature", "pricing"):
        record = RunRecord(detail=detail)
        sources = await service._collect_competitor_from_kb(record, detail, dimension, "Notion",
            SubagentContext(run_id=detail.id, agent="collector", subagent=f"{dimension}::Notion"),
            target_source_count=1)
        assert len(sources) == 1
        assert sources[0].metadata["kb_document_id"] == documents[dimension]
        assert sources[0].metadata["kb_retrieval_original_query"] == topic
        plan = sources[0].metadata["kb_retrieval"]["query_plan"]
        assert all(other not in " ".join(plan["queries"]) for other in products[1:])
        plans.append(plan["queries"])
    assert plans[0] != plans[1]
    assert any("editing" in query for query in plans[0])
    assert all("editing" not in query for query in plans[1])
