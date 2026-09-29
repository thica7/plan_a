from __future__ import annotations

import asyncio

import pytest

from packages.config import Settings
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunService
from packages.schema.api_dto import HitlResumeRequest, RunCreateRequest
from packages.skills.registry import SkillRegistry


def _service() -> RunService:
    return RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            backup_llm_api_key="mode-matrix-test-key",
            backup_llm_model="mode-matrix-test-model",
            hitl_timeout_seconds=120,
        ),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )


def _request(depth: str, collaboration: str, execution: str) -> RunCreateRequest:
    return RunCreateRequest(
        topic="家用清洁产品选择",
        target_product={"name": "洁净家无线吸尘器", "category": "家用清洁电器"},
        competitors=["飞跃牌"],
        dimensions=["feature", "pricing"],
        research_depth=depth,
        collaboration_mode=collaboration,
        execution_mode=execution,
        idempotency_key=f"pm-mode-matrix-{depth}-{collaboration}-{execution}",
    )


async def _wait_for_state(detail, *, status: str, node: str | None = None) -> None:
    for _ in range(300):
        if detail.status == status and detail.current_node == node:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(
        f"Expected {status}/{node}, got {detail.status}/{detail.current_node}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("depth", ["quick", "standard", "deep"])
@pytest.mark.parametrize("collaboration", ["ai", "assisted"])
@pytest.mark.parametrize("execution", ["demo", "real"])
async def test_twelve_mode_combinations_keep_axes_independent(
    depth: str, collaboration: str, execution: str,
) -> None:
    service = _service()
    try:
        detail = await service.create_run(_request(depth, collaboration, execution))
        assert detail.execution_mode == execution
        assert detail.plan.research_depth == depth
        assert detail.plan.collaboration_mode == collaboration
        assert detail.hitl_enabled is (collaboration == "assisted")
        assert detail.plan.competitor_layer in {"L1", "L2", "L3"}

        # Real mode is tested through planning only: no paid model or search is called.
        if execution == "real":
            return

        await service.run_pipeline(detail.id)
        if collaboration == "ai":
            assert detail.status == "completed"
            assert not any(event.type == "interrupt" for event in service.get_trace(detail.id) or [])
        else:
            assert detail.status == "interrupted"
            assert detail.current_node == "planner_hitl"
            for next_node in ("evidence_hitl", "qa_hitl"):
                await service.resume(detail.id, HitlResumeRequest(decision="accept"))
                await _wait_for_state(detail, status="interrupted", node=next_node)
            await service.resume(detail.id, HitlResumeRequest(decision="accept"))
            await _wait_for_state(detail, status="completed")
            interrupts = [event for event in service.get_trace(detail.id) or [] if event.type == "interrupt"]
            assert len(interrupts) == 3
        assert detail.comparison_matrix is not None
        assert len(detail.comparison_matrix.cells) == 4
        assert detail.plan.competitors == ["洁净家无线吸尘器", "飞跃牌"]
    finally:
        await service._graph_checkpointer.aclose()
