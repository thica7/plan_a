from datetime import UTC, datetime

import pytest

from packages.enterprise import EnterpriseMemoryStore
from packages.knowledge.models import DocumentCreate
from packages.knowledge.repository import KnowledgeRepository
from packages.rag.knowledge_bridge import sync_knowledge_to_evidence
from packages.schema.enterprise import KnowledgeEvidenceSyncRequest


@pytest.mark.asyncio
async def test_sync_only_own_sources_and_library_preserves_typed_origin(tmp_path):
    repo = KnowledgeRepository(str(tmp_path / "kb.db"))
    await repo.initialise()
    old = datetime(2020, 1, 1, tzinfo=UTC)
    try:
        for name, ws, project, role in [
            ("own", "a", "p", "source"),
            ("library", "a", None, "source"),
            ("other-project", "a", "q", "source"),
            ("foreign", "b", "p", "source"),
            ("unknown", None, None, "source"),
            ("report", "a", "p", "historical_report"),
        ]:
            await repo.upsert_document(
                DocumentCreate(
                    title=name,
                    workspace_id=ws,
                    project_id=project,
                    source_role=role,
                    market="US",
                    source_type="manual",
                    text=name,
                    source_published_at=old,
                    metadata={"last_verified_at": datetime.now(UTC).isoformat()},
                ),
                name,
            )
        store = EnterpriseMemoryStore()
        result = await sync_knowledge_to_evidence(
            repo=repo,
            store=store,
            workspace_id="a",
            project_id="p",
            request=KnowledgeEvidenceSyncRequest(limit=2),
        )
        records = store.list_evidence(project_id="p")
        assert result.loaded_count == 2
        assert {r.title for r in records} == {"own", "library"}
        for record in records:
            assert record.metadata["kb_document_workspace_id"] == "a"
            assert record.metadata["kb_document_project_id"] == (
                "p" if record.title == "own" else None
            )
            assert record.metadata["kb_source_role"] == "source"
            assert record.metadata["kb_market"] == "US"
            assert record.metadata["kb_freshness_basis_at"] == old.isoformat()
            assert record.freshness_score <= 0.4
    finally:
        await repo.close()
