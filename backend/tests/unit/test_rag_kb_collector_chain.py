from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from packages.agents import SubagentContext
from packages.config import Settings
from packages.orchestrator.service import RunRecord, RunService
from packages.schema.api_dto import RunDetail
from packages.schema.models import AnalysisPlan
from packages.skills.registry import SkillRegistry
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


def _remove_sqlite_files(db_path: Path) -> None:
    for path in (db_path, db_path.with_suffix(".db-shm"), db_path.with_suffix(".db-wal")):
        path.unlink(missing_ok=True)