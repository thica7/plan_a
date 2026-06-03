from fastapi.testclient import TestClient

from app.deps import get_enterprise_store
from app.main import create_app
from packages.enterprise import EnterpriseMemoryStore
from packages.rag import ingest_evidence_seed_corpus, retrieve_grounded_context
from packages.schema.enterprise import ProjectRecord


def test_evidence_seed_corpus_ingests_searchable_records() -> None:
    store = EnterpriseMemoryStore()
    store.upsert_project(
        ProjectRecord(
            id="project-seed",
            workspace_id="workspace-seed",
            name="AI coding assistant comparison",
            topic="AI coding assistant comparison",
            topic_normalized="ai-coding-assistant-comparison",
        )
    )

    result = ingest_evidence_seed_corpus(
        store=store,
        workspace_id="workspace-seed",
        project_id="project-seed",
        topic="AI coding assistant comparison",
        competitors=["Cursor", "GitHub Copilot"],
        dimensions=["pricing"],
        run_id="seed-smoke",
    )
    hits = store.search_evidence(
        workspace_id="workspace-seed",
        project_id="project-seed",
        query="Cursor AI coding assistant pricing official",
        limit=5,
    )
    context = retrieve_grounded_context(
        store=store,
        workspace_id="workspace-seed",
        project_id="project-seed",
        gap_id="gap-seed-pricing",
        query="Cursor pricing official source",
        source_type_required="official_pricing",
    )

    assert result.loaded_count == 50
    assert result.matched_count == 2
    assert result.ingested_count == 2
    assert result.indexed_count == 2
    assert result.duplicate_count == 0
    assert set(result.competitors) == {"Cursor", "GitHub Copilot"}
    assert set(result.dimensions) == {"pricing"}
    assert len(store.list_evidence(project_id="project-seed")) == 2
    assert any(hit.evidence.metadata["seed_corpus"] is True for hit in hits)
    assert context.candidate_ids
    assert any(item in context.candidate_ids for item in result.evidence_ids)
    assert "Seed evidence for AI coding assistant" in context.grounded_context
    assert {
        source.trust_level
        for source in store.list_source_registry(workspace_id="workspace-seed")
    } == {"official"}


def test_enterprise_router_ingests_project_evidence_seed() -> None:
    store = EnterpriseMemoryStore()
    store.upsert_project(
        ProjectRecord(
            id="project-api-seed",
            workspace_id="workspace-api-seed",
            name="Product analytics platform",
            topic="Product analytics platform",
            topic_normalized="product-analytics-platform",
        )
    )
    app = create_app()
    app.dependency_overrides[get_enterprise_store] = lambda: store
    client = TestClient(app)

    response = client.post(
        "/api/enterprise/projects/project-api-seed/evidence/seed",
        json={"competitors": ["Amplitude"], "dimensions": ["feature"]},
        headers={"X-User-Role": "analyst", "X-Workspace-Id": "workspace-api-seed"},
    )
    search = client.get(
        "/api/enterprise/evidence/search",
        params={
            "workspace_id": "workspace-api-seed",
            "project_id": "project-api-seed",
            "query": "Amplitude feature product analytics",
        },
        headers={"X-User-Role": "analyst", "X-Workspace-Id": "workspace-api-seed"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["loaded_count"] == 50
    assert body["matched_count"] == 1
    assert body["ingested_count"] == 1
    assert body["dimensions"] == ["feature"]
    assert search.status_code == 200
    assert search.json()[0]["evidence"]["metadata"]["seed_id"] == "seed_006"
