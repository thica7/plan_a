import pytest

from packages.config import Settings
from packages.enterprise import EnterpriseMemoryStore
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunService
from packages.schema.api_dto import RunCreateRequest
from packages.skills.registry import SkillRegistry


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["zh-CN", "en-US"])
@pytest.mark.parametrize("layer", ["L1", "L2", "L3"])
async def test_demo_fixture_passes_current_release_depth_rules(language, layer) -> None:
    service = RunService(
        SkillRegistry.from_default_path(),
        Settings(
            demo_mode=True,
            ark_api_key=None,
            ark_model=None,
            ark_base_url="https://example.invalid",
            llm_timeout_seconds=1,
            llm_temperature=0.2,
        ),
        enterprise_store=EnterpriseMemoryStore(),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    detail = await service.create_run(
        RunCreateRequest(
            topic="Demo quality contract",
            competitors=["Cursor", "GitHub Copilot"],
            dimensions=["pricing"],
            execution_mode="demo",
            output_language=language,
            competitor_layer=layer,
        )
    )
    completed = await service.run_pipeline(detail.id)
    if layer == "L1":
        assert completed.status == "completed"
    else:
        # A pricing-only fixture still lacks the other layer-specific business evidence.
        assert completed.status == "completed_with_blockers"
    assert not any(
        finding.field_path == "release_gate.report_depth_required"
        for finding in completed.qa_findings
    )


@pytest.mark.asyncio
async def test_thin_demo_report_still_completes_with_depth_blockers() -> None:
    service = RunService(
        SkillRegistry.from_default_path(),
        Settings(
            demo_mode=True,
            ark_api_key=None,
            ark_model=None,
            ark_base_url="https://example.invalid",
            llm_timeout_seconds=1,
            llm_temperature=0.2,
        ),
        enterprise_store=EnterpriseMemoryStore(),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    service._demo_report = lambda detail: "# Thin report\n\nInsufficient fixture analysis."
    detail = await service.create_run(
        RunCreateRequest(
            topic="Thin report gate",
            competitors=["Cursor", "GitHub Copilot"],
            dimensions=["pricing"],
            execution_mode="demo",
        )
    )
    completed = await service.run_pipeline(detail.id)
    assert completed.status == "completed_with_blockers"
    assert any(
        finding.field_path == "release_gate.report_depth_required"
        for finding in completed.qa_findings
    )
