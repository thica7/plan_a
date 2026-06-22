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
) -> None:
    db_path = Path("backend/tests/unit/.tmp_rag_kb_collector_chain.db")
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
