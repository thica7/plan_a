from datetime import UTC, datetime, timedelta

import pytest

from packages.agents import SubagentContext
from packages.config import Settings
from packages.orchestrator.service import RunRecord, RunService
from packages.schema.api_dto import RunDetail
from packages.schema.models import AnalysisPlan, TargetProduct
from packages.skills.registry import SkillRegistry
from packages.tools import rag_retrieve
from packages.tools.ingest_document import ingest_document_tool


def service_and_detail(dimension="feature", market=" CN "):
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(), settings=Settings(demo_mode=True)
    )
    detail = RunDetail(
        id="collector-scope",
        workspace_id="ws-a",
        project_id="project-a",
        topic="Vacuum X Pro evidence",
        status="running",
        execution_mode="real",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        plan=AnalysisPlan(
            topic="Vacuum X Pro evidence",
            competitors=["Vacuum X Pro"],
            dimensions=[dimension],
            target_product=TargetProduct(name="Vacuum X Pro", market=market),
        ),
    )
    return service, detail


def good_hit(**changes):
    hit = dict(
        chunk_id="chunk",
        document_id="document",
        document_version=2,
        content_hash="document-hash",
        text="Vacuum X Pro supports a sixty minute battery runtime.",
        score=0.99,
        url="https://vacuum.example/specs",
        title="Vacuum X Pro specs",
        source_type="webpage_verified",
        workspace_id="ws-a",
        project_id="project-a",
        competitor="Vacuum X Pro",
        dimension="feature",
        market="CN",
        source_role="source",
        status="active",
        fetched_at=datetime.now(UTC).isoformat(),
    )
    hit.update(changes)
    return hit


async def collect(service, detail):
    return await service._collect_competitor_from_kb(
        RunRecord(detail=detail),
        detail,
        detail.plan.dimensions[0],
        "Vacuum X Pro",
        SubagentContext(run_id=detail.id, agent="collector", subagent="feature::Vacuum X Pro"),
        target_source_count=1,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "dimension,ttl",
    [("pricing", 7), ("version", 7), ("版本", 7), ("价格", 7), ("定价", 7), ("feature", 30)],
)
async def test_collector_injects_server_scope_and_freshness(monkeypatch, dimension, ttl):
    service, detail = service_and_detail(dimension)
    requests = []

    class FakeTool:
        async def ainvoke(self, request):
            requests.append(request)
            return []

    monkeypatch.setattr(rag_retrieve, "rag_retrieve_tool", FakeTool())
    await collect(service, detail)
    request = requests[0]
    assert request["workspace_id"] == detail.workspace_id
    assert request["project_id"] == detail.project_id
    assert request["include_workspace_library"] is True
    assert request["competitors"] == ["Vacuum X Pro"]
    assert request["market"] == "CN"
    assert request["source_roles"] == ["source"]
    assert request["max_age_days"] == ttl


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"workspace_id": "ws-b"},
        {"project_id": "project-b"},
        {"workspace_id": None},
        {"competitor": "Vacuum X"},
        {"dimension": "pricing"},
        {"market": "US"},
        {"source_role": "historical_report"},
        {"status": "stale"},
        {"fetched_at": (datetime.now(UTC) - timedelta(days=31)).isoformat()},
        {"last_verified_at": (datetime.now(UTC) + timedelta(days=1)).isoformat()},
    ],
)
async def test_collector_defends_against_fake_or_old_tool_hits(monkeypatch, changes):
    service, detail = service_and_detail()

    class FakeTool:
        async def ainvoke(self, request):
            return [good_hit(**changes)]

    monkeypatch.setattr(rag_retrieve, "rag_retrieve_tool", FakeTool())
    assert await collect(service, detail) == []


@pytest.mark.asyncio
async def test_collector_allows_only_same_workspace_library_and_preserves_original_reference(
    monkeypatch,
):
    service, detail = service_and_detail()
    fetched = datetime.now(UTC) - timedelta(days=2)

    class FakeTool:
        async def ainvoke(self, request):
            return [
                good_hit(workspace_id="ws-b", project_id=None),
                good_hit(
                    project_id=None,
                    fetched_at=fetched.isoformat(),
                    metadata={
                        "collector_confidence": 0.4,
                        "capture_content_hash": "original-capture",
                    },
                ),
            ]

    monkeypatch.setattr(rag_retrieve, "rag_retrieve_tool", FakeTool())
    sources = await collect(service, detail)
    assert len(sources) == 1
    source = sources[0]
    assert source.confidence == 0.4
    assert source.content_hash == "original-capture"
    assert source.metadata["kb_document_version"] == 2
    assert source.metadata["kb_document_content_hash"] == "document-hash"
    assert source.metadata["source_fetched_at"] == fetched.isoformat()
    assert source.extracted_at == fetched


@pytest.mark.asyncio
async def test_tools_fail_closed_without_scope_and_do_not_create_unknown_documents(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("KB_DB_PATH", str(tmp_path / "kb.db"))
    assert (
        await rag_retrieve.rag_retrieve_tool.ainvoke(
            dict(query="vacuum", competitors=[], dimensions=[], top_k=1, mode="sparse")
        )
        == []
    )
    with pytest.raises(ValueError, match="workspace"):
        await ingest_document_tool.ainvoke(
            dict(
                url="https://vacuum.example",
                title="Vacuum",
                text="Vacuum facts",
                competitor="Vacuum X Pro",
                dimension="feature",
                source_type="manual",
                index_vectors=False,
            )
        )
    assert not (tmp_path / "kb.db").exists()


@pytest.mark.asyncio
async def test_zero_fact_confidence_is_not_upgraded_by_retrieval_score(monkeypatch):
    service, detail = service_and_detail()

    class FakeTool:
        async def ainvoke(self, request):
            return [good_hit(metadata={"collector_confidence": 0.0})]

    monkeypatch.setattr(rag_retrieve, "rag_retrieve_tool", FakeTool())
    assert (await collect(service, detail))[0].confidence == 0.0


@pytest.mark.asyncio
async def test_real_sparse_tool_filters_namespace_roles_market_and_source_age(
    tmp_path, monkeypatch
):
    from packages.tools.ingest_document import ingest_document_reference

    monkeypatch.setenv("KB_DB_PATH", str(tmp_path / "kb.db"))
    service, detail = service_and_detail()
    ids = []
    for changes in [
        {"workspace_id": "ws-b"},
        {"project_id": "project-b"},
        {"competitor": "Vacuum X"},
        {"market": "US"},
        {"source_role": "historical_report"},
        {"fetched_at": datetime.now(UTC) - timedelta(days=31)},
        {"fetched_at": datetime.now(UTC) + timedelta(days=1)},
        {"project_id": None},
        {},
    ]:
        fields = dict(
            url="https://vacuum.example/specs",
            title="Vacuum source",
            text="Vacuum X Pro battery facts",
            source_type="manual",
            competitor="Vacuum X Pro",
            dimension="feature",
            workspace_id="ws-a",
            project_id="project-a",
            market="CN",
            index_vectors=False,
        )
        fields.update(changes)
        # Distinct text allows time variants to exercise their own stored timestamps.
        fields["text"] += f" sample {len(ids)}"
        reference = await ingest_document_reference(**fields)
        ids.append(reference["document_id"])
    hits = await rag_retrieve.rag_retrieve_tool.ainvoke(
        dict(
            query="vacuum",
            competitors=["Vacuum X Pro"],
            dimensions=["feature"],
            top_k=20,
            mode="sparse",
            workspace_id=detail.workspace_id,
            project_id=detail.project_id,
            include_workspace_library=True,
            market="CN",
            source_roles=["source"],
            max_age_days=30,
        )
    )
    assert {hit["document_id"] for hit in hits} == set(ids[-2:])
