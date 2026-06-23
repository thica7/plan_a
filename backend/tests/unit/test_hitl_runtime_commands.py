import asyncio

import pytest

from packages.auth import EnterpriseUserContext
from packages.config import Settings
from packages.enterprise import EnterpriseMemoryStore
from packages.memory import PreferenceMemoryStore
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunService
from packages.runtime import (
    RequestRedoCommand,
    ResumeReviewCommand,
    RuntimeCommandError,
    RuntimeCommandService,
)
from packages.runtime import service as runtime_service_module
from packages.schema.api_dto import HitlResumeRequest, RunCreateRequest
from packages.schema.models import QCIssue, RedoScope
from packages.skills.registry import SkillRegistry


@pytest.mark.asyncio
async def test_resume_review_requires_pending_hitl_interrupt() -> None:
    store = EnterpriseMemoryStore()
    run_service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=_settings(),
        enterprise_store=store,
        preference_memory=PreferenceMemoryStore.in_memory(),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    runtime = RuntimeCommandService(
        settings=_settings(),
        run_service=run_service,
        workflow_service=object(),
        enterprise_store=store,
        preference_memory=PreferenceMemoryStore.in_memory(),
    )

    try:
        detail = await run_service.create_run(
            RunCreateRequest(
                topic="HITL runtime stale accept",
                competitors=["A"],
                dimensions=["pricing"],
                execution_mode="demo",
            )
        )
        run_service._runs[detail.id].detail.status = "completed"

        with pytest.raises(RuntimeCommandError) as blocked:
            await runtime.resume_review(
                ResumeReviewCommand(
                    run_id=detail.id,
                    request=HitlResumeRequest(decision="accept"),
                ),
                actor=_actor(),
            )

        assert blocked.value.status_code == 409
        assert "no pending HITL interrupt" in str(blocked.value.detail)
        assert run_service._runs[detail.id].detail.status == "completed"
    finally:
        await run_service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_request_redo_prefers_requested_issue_ids() -> None:
    store = EnterpriseMemoryStore()
    run_service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=_settings(),
        enterprise_store=store,
        preference_memory=PreferenceMemoryStore.in_memory(),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    runtime = RuntimeCommandService(
        settings=_settings(),
        run_service=run_service,
        workflow_service=object(),
        enterprise_store=store,
        preference_memory=PreferenceMemoryStore.in_memory(),
    )

    try:
        detail = await run_service.create_run(
            RunCreateRequest(
                topic="HITL runtime scoped redo",
                competitors=["A"],
                dimensions=["pricing"],
                execution_mode="demo",
            )
        )
        detail.qa_findings = [
            QCIssue(
                id="qc-release-1",
                severity="blocker",
                detected_by="coverage",
                target_agent="collector",
                target_subagent="pricing",
                target_competitor="A",
                field_path="release_gate.claim_uses_low_confidence_evidence",
                problem="Pricing evidence is weak.",
                redo_scope=RedoScope(
                    kind="collector",
                    target_subagent="pricing",
                    target_competitor="A",
                    target_competitors=["A"],
                    rationale="Collect stronger pricing evidence.",
                ),
                metadata={"release_gate_issue_id": "release-issue-1"},
            )
        ]

        scheduled: list[asyncio.Task[None]] = []
        calls: list[tuple[str, bool, list[str] | None]] = []

        async def fake_scoped_redo(
            run_id: str,
            *,
            auto_continue: bool = False,
            preferred_issue_ids: list[str] | None = None,
        ) -> None:
            calls.append((run_id, auto_continue, preferred_issue_ids))

        run_service.run_scoped_redo = fake_scoped_redo  # type: ignore[method-assign]
        original_create_task = runtime_service_module.asyncio.create_task
        def capture_background_task(coro: object) -> asyncio.Task[None]:
            task = original_create_task(coro)  # type: ignore[arg-type]
            scheduled.append(task)
            return task

        runtime_service_module.asyncio.create_task = capture_background_task
        try:
            result = await runtime.request_redo(
                RequestRedoCommand(run_id=detail.id, issue_ids=["release-issue-1"]),
                actor=_actor(),
            )
            await asyncio.gather(*scheduled)
        finally:
            runtime_service_module.asyncio.create_task = original_create_task

        assert result.status == "accepted"
        assert result.metadata["issue_ids"] == ["release-issue-1"]
        assert calls == [(detail.id, False, ["release-issue-1"])]
    finally:
        await run_service._graph_checkpointer.aclose()


@pytest.mark.asyncio
async def test_request_redo_rejects_stale_requested_issue_ids() -> None:
    store = EnterpriseMemoryStore()
    run_service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=_settings(),
        enterprise_store=store,
        preference_memory=PreferenceMemoryStore.in_memory(),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    runtime = RuntimeCommandService(
        settings=_settings(),
        run_service=run_service,
        workflow_service=object(),
        enterprise_store=store,
        preference_memory=PreferenceMemoryStore.in_memory(),
    )

    try:
        detail = await run_service.create_run(
            RunCreateRequest(
                topic="HITL runtime stale redo target",
                competitors=["A"],
                dimensions=["pricing"],
                execution_mode="demo",
            )
        )
        detail.qa_findings = [
            QCIssue(
                id="qc-release-1",
                severity="blocker",
                detected_by="coverage",
                target_agent="collector",
                target_subagent="pricing",
                target_competitor="A",
                field_path="release_gate.claim_uses_low_confidence_evidence",
                problem="Pricing evidence is weak.",
                redo_scope=RedoScope(
                    kind="collector",
                    target_subagent="pricing",
                    target_competitor="A",
                    target_competitors=["A"],
                    rationale="Collect stronger pricing evidence.",
                ),
            )
        ]

        with pytest.raises(RuntimeCommandError) as blocked:
            await runtime.request_redo(
                RequestRedoCommand(run_id=detail.id, issue_ids=["release-issue-missing"]),
                actor=_actor(),
            )

        assert blocked.value.status_code == 409
        assert blocked.value.detail == "Requested redo issue is no longer active."
    finally:
        await run_service._graph_checkpointer.aclose()


def _settings() -> Settings:
    return Settings(
        demo_mode=True,
        ark_api_key="key",
        ark_model="model",
        ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
        llm_timeout_seconds=10,
        llm_temperature=0.2,
        enterprise_store_backend="memory",
        enterprise_database_url=None,
        hitl_enabled=True,
    )


def _actor() -> EnterpriseUserContext:
    return EnterpriseUserContext(
        user_id="system-user",
        role="owner",
        workspace_id="default-workspace",
    )
