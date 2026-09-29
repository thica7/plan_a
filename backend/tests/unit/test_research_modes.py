from dataclasses import asdict

import pytest
from pydantic import ValidationError

from packages.config import Settings
from packages.identity import compute_workflow_idempotency_key
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunService, _active_run_fingerprint
from packages.schema import models
from packages.schema.api_dto import RunCreateRequest
from packages.skills.registry import SkillRegistry
from packages.workflows.activities import CompetitiveIntelActivities
from packages.workflows.models import CompetitiveIntelWorkflowInput
from packages.workflows.service import (
    competitive_intel_input_from_run_request,
    workflow_idempotency_key,
)


def _request(**overrides: object) -> RunCreateRequest:
    return RunCreateRequest(
        topic="AI coding assistant comparison",
        competitors=["Cursor"],
        dimensions=["pricing"],
        execution_mode="demo",
        **overrides,
    )


def _service(*, hitl_enabled: bool = False) -> RunService:
    return RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(demo_mode=True, hitl_enabled=hitl_enabled),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )


def test_research_modes_contract_accepts_optional_brief_and_limits_text() -> None:
    brief_type = models.DecisionBrief
    assert brief_type().model_dump() == {
        "decision_question": "",
        "primary_job": "",
        "success_metric": "",
    }
    request = _request(
        research_depth="deep",
        collaboration_mode="assisted",
        decision_brief={
            "decision_question": "Which product should we build?",
            "primary_job": "Choose a product direction",
            "success_metric": "Decision made",
        },
    )
    assert isinstance(request.decision_brief, brief_type)
    assert request.decision_brief.decision_question == "Which product should we build?"
    with pytest.raises(ValidationError):
        brief_type(decision_question="x" * 501)
    with pytest.raises(ValidationError):
        _request(research_depth="unlimited")
    with pytest.raises(ValidationError):
        _request(collaboration_mode="manual")


@pytest.mark.parametrize(
    ("collaboration_mode", "hitl_enabled"),
    [("ai", True), ("assisted", False)],
)
def test_conflicting_explicit_collaboration_and_hitl_are_rejected(
    collaboration_mode: str,
    hitl_enabled: bool,
) -> None:
    with pytest.raises(ValidationError, match="collaboration_mode"):
        _request(collaboration_mode=collaboration_mode, hitl_enabled=hitl_enabled)


@pytest.mark.asyncio
async def test_run_persists_research_modes_and_collaboration_controls_hitl() -> None:
    service = _service(hitl_enabled=True)
    request = _request(
        research_depth="quick",
        collaboration_mode="ai",
        decision_brief={"decision_question": "Where should we invest?"},
    )
    detail = await service.create_run(request)

    assert detail.plan.research_depth == "quick"
    assert detail.plan.collaboration_mode == "ai"
    assert detail.plan.decision_brief == request.decision_brief
    assert detail.hitl_enabled is False
    assert service.get_run(detail.id).plan.decision_brief == request.decision_brief


@pytest.mark.asyncio
async def test_legacy_request_keeps_hitl_defaults_and_workflow_key() -> None:
    service = _service(hitl_enabled=True)
    request = _request()
    detail = await service.create_run(request)

    assert request.research_depth is None
    assert request.collaboration_mode is None
    assert request.decision_brief is None
    assert detail.plan.research_depth is None
    assert detail.plan.collaboration_mode is None
    assert detail.plan.decision_brief is None
    assert detail.hitl_enabled is True

    old_payload = request.model_dump(
        mode="json",
        exclude={"idempotency_key", "research_depth", "collaboration_mode", "decision_brief"},
    )
    assert workflow_idempotency_key(request) == compute_workflow_idempotency_key(old_payload)


def test_active_run_fingerprint_includes_each_explicit_research_mode_field() -> None:
    common = dict(
        workspace_id="default-workspace",
        project_id=None,
        topic="AI coding assistant comparison",
        competitors=["Cursor"],
        dimensions=["pricing"],
        competitor_layer=None,
        scenario_id=None,
        execution_mode="demo",
        output_language="zh-CN",
        auto_redo_warn_enabled=False,
        hitl_enabled=False,
    )
    legacy = _active_run_fingerprint(**common)
    assert _active_run_fingerprint(**common, research_depth="quick") != legacy
    assert _active_run_fingerprint(**common, collaboration_mode="ai") != legacy
    assert _active_run_fingerprint(
        **common,
        decision_brief=models.DecisionBrief(decision_question="Build or buy?"),
    ) != legacy


@pytest.mark.asyncio
async def test_temporal_round_trip_preserves_research_modes_to_run_plan() -> None:
    from temporalio.converter import DataConverter

    service = _service()
    request = _request(
        idempotency_key="research-modes-temporal-roundtrip",
        research_depth="deep",
        collaboration_mode="assisted",
        decision_brief={
            "decision_question": "Which segment first?",
            "primary_job": "Choose a launch segment",
            "success_metric": "Segment approved",
        },
    )
    workflow_input = competitive_intel_input_from_run_request(request)
    payloads = await DataConverter.default.encode([workflow_input])
    [decoded] = await DataConverter.default.decode(
        payloads, [CompetitiveIntelWorkflowInput]
    )
    assert asdict(decoded)["decision_brief"] == request.decision_brief.model_dump()

    result = await CompetitiveIntelActivities(service).create_run(decoded)
    detail = service.get_run(result.run_id)
    assert detail.plan.research_depth == "deep"
    assert detail.plan.collaboration_mode == "assisted"
    assert detail.plan.decision_brief == request.decision_brief
    assert detail.hitl_enabled is True
