from __future__ import annotations

import pytest

from packages.config import Settings
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunService
from packages.schema.api_dto import RunCreateRequest
from packages.skills.registry import SkillRegistry


@pytest.mark.asyncio
async def test_low_ranked_kb_candidate_does_not_become_high_confidence_fact() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(demo_mode=True),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    detail = await service.create_run(RunCreateRequest(
        topic="Compare team note tools", dimensions=["pricing"], competitors=["Notion"],
        target_product={"name": "NoteHarbor", "category": "team notes"},
    ))
    source = service._raw_source_from_kb_hit(
        detail, "Notion", "pricing", {
            "text": "Notion archived pricing reference says an old Team plan costs $9 per seat.",
            "title": "Old pricing reference", "url": "https://notion.so/old-pricing",
            "source_type": "webpage_verified", "document_id": "doc-1", "chunk_id": "chunk-1",
            "score": 0.02, "metadata": {},
        }, rank=1, query="Notion pricing",
    )
    assert source is not None
    assert source.candidate_confidence == 0.02
    assert source.confidence <= 0.75
    assert source.quality_score <= 0.75
