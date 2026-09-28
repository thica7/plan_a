from __future__ import annotations

from dataclasses import asdict

import pytest

from packages.config import Settings
from packages.enterprise import EnterpriseMemoryStore
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunService
from packages.schema.api_dto import RunCreateRequest
from packages.skills.registry import SkillRegistry
from packages.workflows.activities import CompetitiveIntelActivities
from packages.workflows.service import competitive_intel_input_from_run_request


def _request() -> RunCreateRequest:
    return RunCreateRequest(
        topic="研究一款无线吸尘器的同类产品",
        dimensions=["feature", "pricing"],
        target_product={
            "name": "示例无线吸尘器",
            "official_url": "https://example.com/vacuum",
            "category": "家用清洁电器",
            "audience": "小户型家庭",
            "use_cases": ["清洁地毯", "清理宠物毛发"],
            "market": "中国",
        },
    )


def test_target_product_is_a_typed_optional_run_contract() -> None:
    request = _request()
    assert request.target_product.name == "示例无线吸尘器"
    assert request.target_product.category == "家用清洁电器"
    assert RunCreateRequest(topic="Legacy topic", dimensions=["pricing"]).target_product is None


@pytest.mark.asyncio
async def test_product_discovery_does_not_force_ai_persona_dimension() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(demo_mode=True),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    detail = await service.create_run(RunCreateRequest(
        topic="家用清洁产品调研", dimensions=["feature"],
        target_product={"name": "示例吸尘器", "category": "家电"},
    ))
    assert detail.plan.dimensions == ["feature"]


@pytest.mark.asyncio
async def test_target_product_reaches_run_plan_and_temporal_activity() -> None:
    request = _request()
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(demo_mode=True, enterprise_store_backend="memory"),
        enterprise_store=EnterpriseMemoryStore(),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )
    direct = await service.create_run(request)
    assert direct.plan.target_product == request.target_product
    assert direct.plan.scenario_id.startswith("product_")
    assert "homepage_verified" not in direct.plan.qa_rule_ids

    workflow_input = competitive_intel_input_from_run_request(
        request.model_copy(update={"idempotency_key": "product-temporal-contract"})
    )
    assert asdict(workflow_input)["target_product"]["name"] == request.target_product.name
    activity = CompetitiveIntelActivities(service)
    created = await activity.create_run(workflow_input)
    restored = service.get_run(created.run_id)
    assert restored is not None
    assert restored.plan.target_product == request.target_product
