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


def _request(
    depth: str, collaboration: str, execution: str, lens: str = "L1",
) -> RunCreateRequest:
    return RunCreateRequest(
        topic="家用清洁产品选择",
        target_product={"name": "洁净家无线吸尘器", "category": "家用清洁电器"},
        competitors=["飞跃牌"],
        dimensions=["feature", "pricing"],
        research_depth=depth,
        collaboration_mode=collaboration,
        competitor_layer=lens,
        execution_mode=execution,
        idempotency_key=f"pm-mode-matrix-{lens}-{depth}-{collaboration}-{execution}",
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
@pytest.mark.parametrize("lens", ["L1", "L2", "L3"])
@pytest.mark.parametrize("depth", ["quick", "standard", "deep"])
@pytest.mark.parametrize("collaboration", ["ai", "assisted"])
@pytest.mark.parametrize("execution", ["demo", "real"])
async def test_thirty_six_mode_combinations_keep_axes_independent(
    lens: str, depth: str, collaboration: str, execution: str,
) -> None:
    service = _service()
    try:
        detail = await service.create_run(_request(depth, collaboration, execution, lens))
        assert detail.execution_mode == execution
        assert detail.plan.research_depth == depth
        assert detail.plan.collaboration_mode == collaboration
        assert detail.hitl_enabled is (collaboration == "assisted")
        assert detail.plan.competitor_layer == lens

        # Real mode is tested through planning only: no paid model or search is called.
        if execution == "real":
            return

        await service.run_pipeline(detail.id)
        if collaboration == "ai":
            assert detail.status == "completed"
            assert not any(
                event.type == "interrupt" for event in service.get_trace(detail.id) or []
            )
        else:
            assert detail.status == "interrupted"
            assert detail.current_node == "planner_hitl"
            for next_node in ("evidence_hitl", "qa_hitl"):
                await service.resume(detail.id, HitlResumeRequest(decision="accept"))
                await _wait_for_state(detail, status="interrupted", node=next_node)
            await service.resume(detail.id, HitlResumeRequest(decision="accept"))
            await _wait_for_state(detail, status="completed")
            interrupts = [
                event for event in service.get_trace(detail.id) or []
                if event.type == "interrupt"
            ]
            assert len(interrupts) == 3
        assert detail.comparison_matrix is not None
        assert len(detail.comparison_matrix.cells) == 4
        assert detail.plan.competitors == ["洁净家无线吸尘器", "飞跃牌"]
    finally:
        await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_cancelled_followup_resume_does_not_cancel_prior_graph_resume() -> None:
    service = _service()
    active_resume: asyncio.Task[None] | None = None
    try:
        detail = await service.create_run(_request("standard", "assisted", "demo"))
        record = service._runs[detail.id]
        gate = asyncio.Event()
        active_resume = asyncio.create_task(gate.wait())
        record.resume_task = active_resume
        record.pending_interrupts["evidence"] = {
            "stage": "evidence", "interrupt_node": "evidence_hitl",
        }
        detail.status = "interrupted"
        detail.current_node = "evidence_hitl"

        followup = asyncio.create_task(
            service.resume(detail.id, HitlResumeRequest(decision="accept"))
        )
        await asyncio.sleep(0)
        followup.cancel()
        with pytest.raises(asyncio.CancelledError):
            await followup

        assert not active_resume.cancelled()
    finally:
        if active_resume is not None:
            active_resume.cancel()
            await asyncio.gather(active_resume, return_exceptions=True)
        await service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_cancelled_accepted_review_still_schedules_graph_resume() -> None:
    service = _service()
    entered_lifecycle = asyncio.Event()
    graph_resumes: list[str] = []

    async def blocked_lifecycle(*_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
        entered_lifecycle.set()
        await asyncio.Event().wait()

    async def fake_graph_resume(_run_id: str, request: HitlResumeRequest) -> None:
        graph_resumes.append(request.decision)

    service._record_hitl_lifecycle_event = blocked_lifecycle  # type: ignore[method-assign]
    service._resume_interrupted_graph = fake_graph_resume  # type: ignore[method-assign]
    try:
        detail = await service.create_run(_request("standard", "assisted", "demo"))
        record = service._runs[detail.id]
        record.pending_interrupts["evidence"] = {
            "stage": "evidence", "interrupt_node": "evidence_hitl",
        }
        detail.status = "interrupted"
        detail.current_node = "evidence_hitl"

        review = asyncio.create_task(
            service.resume(detail.id, HitlResumeRequest(decision="accept"))
        )
        await entered_lifecycle.wait()
        review.cancel()
        with pytest.raises(asyncio.CancelledError):
            await review

        assert record.resume_task is not None
        await record.resume_task
        assert graph_resumes == ["accept"]
        assert detail.status == "running"
    finally:
        await service._graph_checkpointer.aclose()
