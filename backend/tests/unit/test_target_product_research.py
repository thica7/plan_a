from __future__ import annotations

import pytest

from packages.config import Settings
from packages.orchestrator.service import RunService
from packages.schema.api_dto import RunCreateRequest, RunDetail
from packages.schema.models import AnalysisPlan, RawSource, TargetProduct, TargetProductEvidence
from packages.search import SearchResult
from packages.skills.registry import SkillRegistry


def test_target_product_becomes_cited_research_subject_without_changing_discovery() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(demo_mode=True),
    )
    plan = AnalysisPlan(
        topic="Compare home vacuums", competitors=["飞跃牌"],
        dimensions=["pricing", "feature"],
        target_product=TargetProduct(
            name="洁净家", category="家用清洁电器",
            official_url="https://cleanhome.example/product",
        ),
        target_product_evidence=TargetProductEvidence(
            status="verified", source_url="https://cleanhome.example/product",
        ),
    )
    service._include_target_product_in_plan(plan)
    assert plan.competitors == ["洁净家", "飞跃牌"]
    assert "洁净家" not in plan.homepage_hints
    assert plan.homepage_verified["洁净家"] is False
    tasks = service._build_task_decomposition(plan)
    assert {(task.stage, task.competitor, task.dimension) for task in tasks} >= {
        ("collector", "洁净家", "pricing"),
        ("collector", "洁净家", "feature"),
        ("analyst", "洁净家", "pricing"),
    }
    detail = RunDetail(
        id="target-run", topic=plan.topic, status="running", execution_mode="real",
        created_at="2026-09-28T00:00:00", updated_at="2026-09-28T00:00:00", plan=plan,
        raw_sources=[RawSource(
            id="target-price-source", competitor="洁净家", dimension="pricing",
            source_type="webpage_verified", title="洁净家产品价格",
            url="https://cleanhome.example/product",
            snippet="洁净家无线吸尘器售价 ¥1,299，包含两年保修服务。",
            content_hash="target-price", confidence=.9,
        )],
    )
    matrix = service._build_comparison_matrix(detail, {})
    assert matrix.target_product == "洁净家"
    assert {(cell.competitor, cell.role) for cell in matrix.cells} == {
        ("洁净家", "target"), ("飞跃牌", "competitor"),
    }
    assert next(cell for cell in matrix.cells if cell.competitor == "洁净家" and cell.dimension == "pricing").source_ids == ["target-price-source"]
    candidate = service._target_product_user_candidate(detail, "洁净家", "pricing")
    assert candidate is not None
    assert candidate.url == "https://cleanhome.example/product"
    assert candidate.origin == "web_search"
    assert candidate.metadata["authority"] == "unverified"
    detail.plan.target_product_evidence = detail.plan.target_product_evidence.model_copy(
        update={"status": "unverified"}
    )
    assert service._target_product_user_candidate(detail, "洁净家", "feature") is not None


@pytest.mark.asyncio
async def test_real_planner_keeps_rival_discovery_separate_from_target_tasks(monkeypatch) -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True, ark_api_key="key", ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            pplx_api_key="key",
        ),
    )

    async def fake_target_research(record) -> None:
        record.detail.plan.target_product_evidence = TargetProductEvidence(
            status="verified", source_url="https://cleanhome.example/product",
        )

    async def fake_search(*args, **kwargs) -> list[SearchResult]:
        return [SearchResult(
            title="飞跃牌无线吸尘器", snippet="飞跃牌提供无线吸尘器。",
            url="https://flying.example/vacuum",
        )]

    async def fake_llm(*args, **kwargs) -> dict:
        if kwargs.get("name") == "competitor_discovery":
            return {
                "candidates": [{"name": "飞跃牌", "relationship": "direct"}],
                "selected_competitors": ["飞跃牌"],
            }
        return {"complexity": "low", "homepage_hints": {}}

    monkeypatch.setattr(service, "_research_target_product", fake_target_research)
    monkeypatch.setattr(service, "_trace_search", fake_search)
    monkeypatch.setattr(service, "_trace_llm_json", fake_llm)
    detail = await service.create_run(RunCreateRequest(
        topic="Compare home vacuums", competitors=[], dimensions=["pricing", "feature"],
        execution_mode="real", hitl_enabled=False,
        target_product={
            "name": "洁净家", "category": "家用清洁电器",
            "official_url": "https://cleanhome.example/product",
        },
    ))
    record = service._runs[detail.id]
    await service._real_planner_step(record)
    assert record.detail.competitor_discovery.selected_competitors == ["飞跃牌"]
    assert record.detail.plan.competitors == ["洁净家", "飞跃牌"]
    assert {task.competitor for task in record.detail.plan.task_decomposition} == {"洁净家", "飞跃牌"}
    assert record.detail.plan.homepage_verified["洁净家"] is False
