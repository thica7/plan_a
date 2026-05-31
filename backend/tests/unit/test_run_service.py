import asyncio
import time
from pathlib import Path
from uuid import uuid4

import pytest

from packages.config import Settings
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunService
from packages.schema.api_dto import HitlResumeRequest, RunCreateRequest, RunDetail
from packages.schema.models import (
    AnalysisPlan,
    ComparisonCell,
    ComparisonMatrix,
    CompetitorKB,
    QCIssue,
    RawSource,
    RedoScope,
    ReflectionRecord,
    RevisionRecord,
)
from packages.search import SearchResult
from packages.skills.registry import SkillRegistry
from packages.tools.fetch_page import FetchPageResult


@pytest.mark.asyncio
async def test_real_mode_requires_ark_credentials() -> None:
    settings = Settings(
        demo_mode=True,
        ark_api_key=None,
        ark_model=None,
        ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
        llm_timeout_seconds=10,
        llm_temperature=0.2,
    )
    service = RunService(skill_registry=SkillRegistry.from_default_path(), settings=settings)

    with pytest.raises(ValueError, match="ARK_API_KEY and ARK_MODEL"):
        await service.create_run(
            RunCreateRequest(
                topic="AI research assistant competitive analysis",
                competitors=["Perplexity"],
                dimensions=["pricing"],
                execution_mode="real",
            )
        )


@pytest.mark.asyncio
async def test_topic_only_run_discovers_competitors_in_planner() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )

    async def fake_complete_json(*, system: str, user: str, schema_hint: str) -> dict:
        if "scoping agent" in system:
            return {
                "candidates": [
                    {"name": "Alpha", "rationale": "Direct AI sales product.", "confidence": 0.8},
                    {"name": "Beta", "rationale": "Direct replacement.", "confidence": 0.7},
                ],
                "selected_competitors": ["Alpha", "Beta", "Alpha"],
                "rationale": "Direct products.",
            }
        return {"complexity": "medium", "homepage_hints": {"Alpha": "https://alpha.example"}}

    service._llm.complete_json = fake_complete_json  # type: ignore[method-assign]
    detail = await service.create_run(
        RunCreateRequest(
            topic="AI sales assistant comparison",
            competitors=[],
            dimensions=["pricing"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]

    await service._real_planner_step(record)

    assert record.detail.plan.competitors == ["Alpha", "Beta"]
    assert record.detail.plan.homepage_hints["Alpha"] == "https://alpha.example"
    assert record.detail.competitor_discovery is not None
    assert record.detail.competitor_discovery.rationale == "Direct products."
    assert record.detail.competitor_discovery.candidates[0].selected is True
    assert record.detail.competitor_discovery.candidates[0].confidence == 0.8
    assert record.detail.metrics.llm_calls == 2
    llm_span_names = [span.name for span in record.detail.trace_spans if span.kind == "llm"]
    assert llm_span_names == ["competitor_discovery", "planner_scope"]
    assert record.detail.agent_messages[-1].trace_span_ids
    assert record.detail.trace_spans[0].agent == "planner"


@pytest.mark.asyncio
async def test_create_run_filters_phantom_competitors_with_homepage_gate() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key=None,
            ark_model=None,
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )

    detail = await service.create_run(
        RunCreateRequest(
            topic="AI coding assistant comparison",
            competitors=["Cursor", "FAKE_PRODUCT_NOT_EXISTS", "Windsurf"],
            dimensions=["pricing"],
            execution_mode="demo",
        )
    )

    assert detail.plan.competitors == ["Cursor", "Windsurf"]
    assert detail.plan.homepage_verified == {"Cursor": True, "Windsurf": True}
    assert "FAKE_PRODUCT_NOT_EXISTS" not in detail.plan.homepage_hints


@pytest.mark.asyncio
async def test_trace_spans_redact_sensitive_text_before_storage() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key=None,
            ark_model=None,
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = await service.create_run(
        RunCreateRequest(
            topic="AI research assistant competitive analysis",
            competitors=["Perplexity"],
            dimensions=["pricing"],
            execution_mode="demo",
        )
    )
    record = service._runs[detail.id]

    service._append_trace_span(
        record,
        kind="tool",
        agent="collector",
        subagent="pricing",
        name="compliance_probe",
        status="ok",
        started=time.perf_counter(),
        input_text=(
            "contact alice@example.com with "
            "OPENROUTER_TEST_KEY_REDACTED"
        ),
        output_text="Bearer abcdef1234567890 accepted",
    )

    span = record.detail.trace_spans[-1]
    tool_message = record.detail.tool_call_messages[-1]
    assert "alice@example.com" not in span.full_input
    assert "sk-or-v1-" not in span.full_input
    assert "abcdef1234567890" not in span.full_output
    assert "[redacted:email]" in span.full_input
    assert "[redacted:api_key]" in span.full_input
    assert "[redacted:bearer_token]" in span.full_output
    assert span.metadata["pii_redacted"] is True
    assert span.trace_id
    assert span.otel_span_id
    assert span.traceparent == f"00-{span.trace_id}-{span.otel_span_id}-01"
    assert record.detail.metrics.compliance_redaction_count == 3
    assert tool_message.arguments["input"] == span.full_input


@pytest.mark.asyncio
async def test_trace_span_compliance_policy_can_disable_redaction() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key=None,
            ark_model=None,
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            compliance_redaction_enabled=False,
        ),
    )
    detail = await service.create_run(
        RunCreateRequest(
            topic="AI research assistant competitive analysis",
            competitors=["Perplexity"],
            dimensions=["pricing"],
            execution_mode="demo",
        )
    )
    record = service._runs[detail.id]

    service._append_trace_span(
        record,
        kind="tool",
        agent="collector",
        subagent="pricing",
        name="compliance_disabled_probe",
        status="ok",
        started=time.perf_counter(),
        input_text="contact alice@example.com",
        output_text="ok",
    )

    span = record.detail.trace_spans[-1]
    assert "alice@example.com" in span.full_input
    assert span.metadata["compliance_redaction_enabled"] is False
    assert record.detail.metrics.compliance_redaction_count == 0


def test_qa_marks_unverified_source_without_missing_false_positive() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-1",
        topic="Test",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="Test", competitors=["A"], dimensions=["pricing"]),
        raw_sources=[
            RawSource(
                id="pricing-1",
                competitor="A",
                dimension="pricing",
                source_type="llm_public_knowledge",
                title="A pricing",
                url="https://example.com/pricing",
                snippet="Pricing summary",
                content_hash="abc",
                confidence=0.7,
            )
        ],
        competitor_kbs={
            "A": CompetitorKB(
                competitor="A",
                slices={"pricing": ["Pricing summary"]},
                sources=["pricing-1"],
                confidence=0.7,
            )
        },
    )

    issues = service._build_qa_issues(detail)

    assert [issue.id for issue in issues] == ["unverified-pricing-a-pricing-1"]
    assert issues[0].severity == "warn"
    assert issues[0].redo_scope.target_competitor == "A"


def test_qa_marks_missing_dimension_as_blocker() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-1",
        topic="Test",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="Test", competitors=["A"], dimensions=["pricing"]),
    )

    issues = service._build_qa_issues(detail)

    assert [issue.id for issue in issues] == ["missing-pricing"]
    assert issues[0].severity == "blocker"
    assert issues[0].redo_scope.kind == "collector"


def test_qa_marks_phantom_citation_as_writer_only_blocker() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-1",
        topic="Test",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="Test", competitors=["A"], dimensions=["pricing"]),
        report_md="The report cites a non-existent source [source:pricing-404].",
        raw_sources=[
            RawSource(
                id="pricing-1",
                competitor="A",
                dimension="pricing",
                source_type="webpage_verified",
                title="A pricing",
                url="https://example.com/pricing",
                snippet="A costs $10.",
                content_hash="abc",
                confidence=0.8,
            )
        ],
        competitor_kbs={
            "A": CompetitorKB(
                competitor="A",
                slices={"pricing": ["A has a $10 plan."]},
                sources=["pricing-1"],
                confidence=0.8,
            )
        },
    )

    issues = service._build_qa_issues(detail)

    phantom = [issue for issue in issues if issue.id == "phantom-citation-pricing-404"]
    assert len(phantom) == 1
    assert phantom[0].severity == "blocker"
    assert phantom[0].redo_scope.kind == "writer_only"


def test_qa_surfaces_latest_reflector_findings() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-1",
        topic="Test",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="Test", competitors=["A"], dimensions=["pricing", "feature"]),
        raw_sources=[
            RawSource(
                id="pricing-1",
                competitor="A",
                dimension="pricing",
                source_type="webpage_verified",
                title="A pricing",
                url="https://example.com/pricing",
                snippet="A costs $10.",
                content_hash="abc",
                confidence=0.8,
            ),
            RawSource(
                id="feature-1",
                competitor="A",
                dimension="feature",
                source_type="webpage_verified",
                title="A feature",
                url="https://example.com/features",
                snippet="A has features.",
                content_hash="def",
                confidence=0.8,
            ),
        ],
        competitor_kbs={
            "A": CompetitorKB(
                competitor="A",
                slices={"pricing": ["A costs $10."], "feature": ["A has features."]},
                sources=["pricing-1", "feature-1"],
                confidence=0.8,
            )
        },
        report_md="A has pricing and feature notes [source:pricing-1] [source:feature-1].",
        comparison_matrix=ComparisonMatrix(
            competitors=["A"],
            dimensions=["pricing", "feature"],
            cells=[
                ComparisonCell(
                    competitor="A",
                    dimension="pricing",
                    value="A costs $10. [source:pricing-1]",
                    source_ids=["pricing-1"],
                    confidence=0.8,
                ),
                ComparisonCell(
                    competitor="A",
                    dimension="feature",
                    value="A has features. [source:feature-1]",
                    source_ids=["feature-1"],
                    confidence=0.8,
                ),
            ],
            winner_by_dimension={"pricing": "A", "feature": "A"},
            summary=[],
        ),
        reflections=[
            ReflectionRecord(
                iteration=1,
                coverage_gaps=["Feature dimension needs more independent sources."],
                confidence_outliers=["Pricing confidence looks inflated."],
                cross_competitor_gaps=["No cross-competitor feature comparison."],
            )
        ],
    )

    issues = service._build_qa_issues(detail)
    reflector_issues = [issue for issue in issues if issue.detected_by == "reflector"]

    assert [issue.target_subagent for issue in reflector_issues] == [
        "feature",
        "pricing",
        "feature",
    ]
    assert [issue.redo_scope.kind for issue in reflector_issues] == [
        "collector",
        "collector",
        "comparator",
    ]
    assert all(issue.severity == "warn" for issue in reflector_issues)


def test_qa_marks_empty_analyst_output_for_scoped_redo() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-1",
        topic="Test",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="Test", competitors=["A"], dimensions=["pricing"]),
        raw_sources=[
            RawSource(
                id="pricing-1",
                competitor="A",
                dimension="pricing",
                source_type="webpage_verified",
                title="A pricing",
                url="https://example.com/pricing",
                snippet="A costs $10.",
                content_hash="abc",
                confidence=0.8,
            )
        ],
    )

    issues = service._build_qa_issues(detail)

    assert [issue.id for issue in issues] == ["empty-analyst-pricing-a"]
    assert issues[0].target_agent == "analyst"
    assert issues[0].redo_scope.kind == "analyst"
    assert issues[0].redo_scope.target_subagent == "pricing"


def test_comparison_matrix_uses_kb_and_sources() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-1",
        topic="Test",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="Test", competitors=["A"], dimensions=["pricing"]),
        raw_sources=[
            RawSource(
                id="pricing-1",
                competitor="A",
                dimension="pricing",
                source_type="webpage_verified",
                title="A pricing",
                url="https://example.com/pricing",
                snippet="A costs $10.",
                content_hash="abc",
                confidence=0.8,
            )
        ],
    )
    service._merge_kb_slice(detail, "pricing", {"A": ["A has a $10 plan."]})

    matrix = service._build_comparison_matrix(
        detail,
        {"matrix_summary": ["A is cheaper."], "winner_by_dimension": {"pricing": "A"}},
    )

    assert matrix.cells[0].value == "A has a $10 plan."
    assert matrix.cells[0].source_ids == ["pricing-1"]
    assert matrix.winner_by_dimension["pricing"] == "A"


def test_comparison_matrix_maps_multi_competitor_sources() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-1",
        topic="Test",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="Test", competitors=["A", "B"], dimensions=["feature"]),
        raw_sources=[
            RawSource(
                id="feature-1",
                competitor="A, B",
                dimension="feature",
                source_type="webpage_verified",
                title="A and B features",
                url="https://example.com/features",
                snippet="A and B both support advanced features.",
                content_hash="abc",
                confidence=0.8,
            )
        ],
    )
    service._merge_kb_slice(
        detail,
        "feature",
        {
            "A": ["A supports advanced features (source id: feature-1)."],
            "B": ["B supports advanced features (source id: feature-1)."],
        },
    )

    matrix = service._build_comparison_matrix(detail, {"matrix_summary": []})

    assert all(cell.source_ids == ["feature-1"] for cell in matrix.cells)
    assert all(cell.confidence == 0.8 for cell in matrix.cells)
    assert detail.competitor_kbs["A"].sources == ["feature-1"]
    assert detail.competitor_kbs["B"].sources == ["feature-1"]


@pytest.mark.asyncio
async def test_collect_join_normalizes_covered_competitors_and_dedupes() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = await service.create_run(
        RunCreateRequest(
            topic="Collect join smoke",
            competitors=["A", "B"],
            dimensions=["feature"],
            execution_mode="demo",
        )
    )
    record = service._runs[detail.id]
    record.detail.raw_sources = [
        RawSource(
            id="feature-1",
            competitor="Cross-model all 2 competitors",
            dimension="feature",
            source_type="webpage_verified",
            title="A and B features",
            url="https://example.com/features",
            snippet="A and B both support advanced features.",
            content_hash="abc",
            confidence=0.8,
        ),
        RawSource(
            id="feature-2",
            competitor="Cross-model all 2 competitors",
            dimension="feature",
            source_type="webpage_verified",
            title="A and B features",
            url="https://example.com/features",
            snippet="Duplicate evidence.",
            content_hash="abc",
            confidence=0.7,
        ),
    ]

    await service._real_collect_join_step(record, ["feature"])

    assert len(record.detail.raw_sources) == 1
    assert record.detail.raw_sources[0].covered_competitors == ["A", "B"]
    assert service.get_trace(detail.id)[-1].subagent == "collect_join"


def test_qa_marks_matrix_unknown_source_for_comparator_redo() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-1",
        topic="Test",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="Test", competitors=["A"], dimensions=["pricing"]),
        raw_sources=[
            RawSource(
                id="pricing-1",
                competitor="A",
                dimension="pricing",
                source_type="webpage_verified",
                title="A pricing",
                url="https://example.com/pricing",
                snippet="A costs $10.",
                content_hash="abc",
                confidence=0.8,
            )
        ],
        competitor_kbs={
            "A": CompetitorKB(
                competitor="A",
                slices={"pricing": ["A has a $10 plan."]},
                sources=["pricing-1"],
                confidence=0.8,
            )
        },
        comparison_matrix=ComparisonMatrix(
            competitors=["A"],
            dimensions=["pricing"],
            cells=[
                ComparisonCell(
                    competitor="A",
                    dimension="pricing",
                    value="A has a $10 plan.",
                    source_ids=["pricing-404"],
                    confidence=0.8,
                )
            ],
        ),
    )

    issues = service._build_qa_issues(detail)

    matrix = [issue for issue in issues if issue.id == "matrix-unknown-source-pricing-404"]
    assert len(matrix) == 1
    assert matrix[0].severity == "blocker"
    assert matrix[0].redo_scope.kind == "comparator"


def test_qa_marks_matrix_value_citation_missing_from_source_ids() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-1",
        topic="Test",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="Test", competitors=["A"], dimensions=["feature"]),
        raw_sources=[
            RawSource(
                id="feature-1",
                competitor="A",
                dimension="feature",
                source_type="webpage_verified",
                title="A features",
                url="https://example.com/features",
                snippet="A supports advanced features.",
                content_hash="abc",
                confidence=0.8,
            )
        ],
        competitor_kbs={
            "A": CompetitorKB(
                competitor="A",
                slices={"feature": ["A supports advanced features (source id: feature-1)."]},
                sources=["feature-1"],
                confidence=0.8,
            )
        },
        comparison_matrix=ComparisonMatrix(
            competitors=["A"],
            dimensions=["feature"],
            cells=[
                ComparisonCell(
                    competitor="A",
                    dimension="feature",
                    value="A supports advanced features (source id: feature-1).",
                    source_ids=[],
                    confidence=0.0,
                )
            ],
        ),
    )

    issues = service._build_qa_issues(detail)

    matrix = [
        issue for issue in issues if issue.id == "matrix-missing-cited-source-a-feature-feature-1"
    ]
    assert len(matrix) == 1
    assert matrix[0].severity == "blocker"
    assert matrix[0].redo_scope.kind == "comparator"


def test_qa_marks_matrix_missing_cell_for_comparator_redo() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    detail = RunDetail(
        id="run-1",
        topic="Test",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="Test", competitors=["A", "B"], dimensions=["pricing"]),
        raw_sources=[
            RawSource(
                id="pricing-1",
                competitor="A",
                dimension="pricing",
                source_type="webpage_verified",
                title="A pricing",
                url="https://example.com/pricing",
                snippet="A costs $10.",
                content_hash="abc",
                confidence=0.8,
            ),
            RawSource(
                id="pricing-2",
                competitor="B",
                dimension="pricing",
                source_type="webpage_verified",
                title="B pricing",
                url="https://example.com/b-pricing",
                snippet="B costs $20.",
                content_hash="def",
                confidence=0.8,
            ),
        ],
        competitor_kbs={
            "A": CompetitorKB(
                competitor="A",
                slices={"pricing": ["A has a $10 plan."]},
                sources=["pricing-1"],
                confidence=0.8,
            ),
            "B": CompetitorKB(
                competitor="B",
                slices={"pricing": ["B has a $20 plan."]},
                sources=["pricing-2"],
                confidence=0.8,
            ),
        },
        comparison_matrix=ComparisonMatrix(
            competitors=["A", "B"],
            dimensions=["pricing"],
            cells=[
                ComparisonCell(
                    competitor="A",
                    dimension="pricing",
                    value="A has a $10 plan.",
                    source_ids=["pricing-1"],
                    confidence=0.8,
                )
            ],
        ),
    )

    issues = service._build_qa_issues(detail)

    matrix = [issue for issue in issues if issue.id == "matrix-missing-cell-b-pricing"]
    assert len(matrix) == 1
    assert matrix[0].severity == "warn"
    assert matrix[0].redo_scope.kind == "comparator"


@pytest.mark.asyncio
async def test_resume_redo_respects_max_iterations() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            max_iterations=1,
        ),
    )
    detail = await service.create_run(
        RunCreateRequest(
            topic="Test",
            competitors=["A"],
            dimensions=["pricing"],
            execution_mode="demo",
        )
    )
    record = service._runs[detail.id]
    record.detail.status = "completed"
    record.detail.qa_findings = [
        QCIssue(
            id="missing-pricing",
            severity="blocker",
            detected_by="coverage",
            target_agent="collector",
            target_subagent="pricing",
            field_path="raw_sources[pricing]",
            problem="No evidence sources were collected for pricing.",
            redo_scope=RedoScope(
                kind="collector", target_subagent="pricing", rationale="Missing pricing."
            ),
        )
    ]
    record.detail.revisions = [
        RevisionRecord(
            id="revision-1",
            iteration=1,
            stage="collector",
            issue_count_before=1,
            issue_count_after=1,
        )
    ]

    assert service.can_start_redo(detail.id) is False
    updated = await service.resume(detail.id, HitlResumeRequest(decision="redo"))

    assert updated is not None
    assert updated.status == "completed"
    assert service._runs[detail.id].events[-1].message == "Maximum redo iterations reached (1)."


def test_convergence_ratio_tracks_remaining_issue_share() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )

    assert service._convergence_ratio(4, 1) == 0.25
    assert service._convergence_ratio(0, 1) == 1.0


@pytest.mark.asyncio
async def test_writer_timeout_preserves_previous_report_and_metrics() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )

    async def fake_complete_text(*, system: str, user: str) -> str:  # noqa: ARG001
        raise TimeoutError("LLM request timed out after 60.0 seconds.")

    service._llm.complete_text = fake_complete_text  # type: ignore[method-assign]
    detail = await service.create_run(
        RunCreateRequest(
            topic="Writer fallback",
            competitors=["A"],
            dimensions=["pricing"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]
    record.detail.raw_sources = [
        RawSource(
            id="pricing-1",
            competitor="A",
            dimension="pricing",
            source_type="webpage_verified",
            title="A pricing",
            url="https://example.com/pricing",
            snippet="A costs $10 per month.",
            content_hash="abc",
            confidence=0.9,
        )
    ]
    record.detail.comparison_matrix = ComparisonMatrix(
        competitors=["A"],
        dimensions=["pricing"],
        cells=[
            ComparisonCell(
                competitor="A",
                dimension="pricing",
                value="A costs $10 per month.",
                source_ids=["pricing-1"],
                confidence=0.9,
            )
        ],
        winner_by_dimension={"pricing": "A"},
        summary=["A has transparent pricing."],
    )
    record.detail.report_md = "Previous report. [source:pricing-1]"
    record.detail.revisions = [
        RevisionRecord(
            id="rev-1", iteration=1, stage="collector", issue_count_before=2, issue_count_after=1
        )
    ]

    await service._real_writer_step(record)

    assert record.detail.report_md == "Previous report. [source:pricing-1]"
    assert record.detail.metrics.revision_count == 1
    assert (
        record.detail.agent_messages[-1].payload["writer_mode"]
        == "preserved previous report after writer error"
    )
    assert record.detail.agent_messages[-1].trace_span_ids
    assert record.detail.trace_spans[-2].agent == "writer"
    assert record.detail.trace_spans[-2].status == "error"


def test_candidate_evidence_prefers_matching_search_results() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )

    results = [
        SearchResult(title="Generic market map", url="https://example.com/map", snippet="A list."),
        SearchResult(
            title="Alpha product review", url="https://example.com/alpha", snippet="Alpha details."
        ),
    ]

    evidence = service._candidate_evidence("Alpha", results)

    assert [item.url for item in evidence] == ["https://example.com/alpha"]


@pytest.mark.asyncio
async def test_search_result_becomes_unverified_raw_source(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch_page(url: str):  # noqa: ANN202 - test double mirrors async tool shape.
        return None

    monkeypatch.setattr("packages.orchestrator.service.fetch_page", fake_fetch_page)
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            pplx_api_key="pplx-key",
        ),
    )
    detail = RunDetail(
        id="run-1",
        topic="Test",
        status="running",
        execution_mode="real",
        created_at="2026-05-23T00:00:00",
        updated_at="2026-05-23T00:00:00",
        plan=AnalysisPlan(topic="Test", competitors=["A"], dimensions=["pricing"]),
    )

    source = await service._source_from_search_result(
        detail,
        "A",
        "pricing",
        SearchResult(
            title="A pricing",
            url="https://example.com/pricing",
            snippet="A has a public pricing page.",
        ),
    )

    assert source is not None
    assert source.source_type == "web_search_result"
    assert str(source.url) == "https://example.com/pricing"


@pytest.mark.asyncio
async def test_real_pipeline_runs_through_langgraph() -> None:
    checkpoint_path = Path("runs") / f"test_graph_checkpoints_{uuid4().hex}.db"
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
        graph_checkpointer=GraphCheckpointer(checkpoint_path),
    )
    order: list[str] = []

    async def fake_planner(record):  # noqa: ANN001, ANN202 - test double for bound service method.
        order.append("planner")

    async def fake_collector(record, dimension, competitor):  # noqa: ANN001, ANN202
        order.append(f"collector:{competitor}:{dimension}")

    async def fake_analyst(record, dimension, competitor):  # noqa: ANN001, ANN202
        order.append(f"analyst:{competitor}:{dimension}")

    async def fake_comparator(record):  # noqa: ANN001, ANN202
        order.append("comparator")

    async def fake_reflector(record):  # noqa: ANN001, ANN202
        order.append("reflector")

    async def fake_writer(record):  # noqa: ANN001, ANN202
        order.append("writer")

    async def fake_qa(record):  # noqa: ANN001, ANN202
        order.append("qa")

    async def fake_phase_qa(record, phase):  # noqa: ANN001, ANN202
        order.append(f"qa:{phase}")
        record.detail.qa_findings = []

    service._real_planner_step = fake_planner  # type: ignore[method-assign]
    service._real_collector_branch_step = fake_collector  # type: ignore[method-assign]
    service._real_phase_qa_step = fake_phase_qa  # type: ignore[method-assign]
    service._real_analyst_branch_step = fake_analyst  # type: ignore[method-assign]
    service._real_comparator_step = fake_comparator  # type: ignore[method-assign]
    service._real_reflector_step = fake_reflector  # type: ignore[method-assign]
    service._real_writer_step = fake_writer  # type: ignore[method-assign]
    service._real_qa_step = fake_qa  # type: ignore[method-assign]

    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic="Graph smoke",
                competitors=["A"],
                dimensions=["pricing", "feature"],
                execution_mode="real",
            )
        )

        await service.run_pipeline(detail.id)

        assert order[0] == "planner", [
            event.message for event in service.get_trace(detail.id) or []
        ]
        assert set(order[1:3]) == {"collector:A:pricing", "collector:A:feature"}
        assert order[3] == "qa:collect"
        assert set(order[4:6]) == {"analyst:A:pricing", "analyst:A:feature"}
        assert order[6:] == ["qa:analyst", "comparator", "reflector", "writer", "qa"]
        assert service.get_run(detail.id).status == "completed"  # type: ignore[union-attr]
        assert checkpoint_path.exists()
    finally:
        await service._graph_checkpointer.aclose()
        for path in Path("runs").glob(f"{checkpoint_path.stem}*"):
            path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_collector_and_analyst_dimensions_run_concurrently() -> None:
    checkpoint_path = Path("runs") / f"test_parallel_graph_{uuid4().hex}.db"
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
        graph_checkpointer=GraphCheckpointer(checkpoint_path),
    )
    timeline: list[tuple[str, str, float]] = []

    async def fake_planner(record):  # noqa: ANN001, ANN202
        timeline.append(("planner", "done", asyncio.get_running_loop().time()))

    async def fake_collector(record, dimension, competitor):  # noqa: ANN001, ANN202
        timeline.append(
            (f"collector:{competitor}:{dimension}", "start", asyncio.get_running_loop().time())
        )
        await asyncio.sleep(0.05)
        timeline.append(
            (f"collector:{competitor}:{dimension}", "end", asyncio.get_running_loop().time())
        )

    async def fake_analyst(record, dimension, competitor):  # noqa: ANN001, ANN202
        timeline.append(
            (f"analyst:{competitor}:{dimension}", "start", asyncio.get_running_loop().time())
        )
        await asyncio.sleep(0.05)
        timeline.append(
            (f"analyst:{competitor}:{dimension}", "end", asyncio.get_running_loop().time())
        )

    async def fake_comparator(record):  # noqa: ANN001, ANN202
        timeline.append(("comparator", "done", asyncio.get_running_loop().time()))

    async def fake_reflector(record):  # noqa: ANN001, ANN202
        timeline.append(("reflector", "done", asyncio.get_running_loop().time()))

    async def fake_writer(record):  # noqa: ANN001, ANN202
        timeline.append(("writer", "done", asyncio.get_running_loop().time()))

    async def fake_qa(record):  # noqa: ANN001, ANN202
        timeline.append(("qa", "done", asyncio.get_running_loop().time()))

    async def fake_phase_qa(record, phase):  # noqa: ANN001, ANN202
        timeline.append((f"qa:{phase}", "done", asyncio.get_running_loop().time()))

    service._real_planner_step = fake_planner  # type: ignore[method-assign]
    service._real_collector_branch_step = fake_collector  # type: ignore[method-assign]
    service._real_phase_qa_step = fake_phase_qa  # type: ignore[method-assign]
    service._real_analyst_branch_step = fake_analyst  # type: ignore[method-assign]
    service._real_comparator_step = fake_comparator  # type: ignore[method-assign]
    service._real_reflector_step = fake_reflector  # type: ignore[method-assign]
    service._real_writer_step = fake_writer  # type: ignore[method-assign]
    service._real_qa_step = fake_qa  # type: ignore[method-assign]

    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic="Parallel smoke",
                competitors=["A"],
                dimensions=["pricing", "feature"],
                execution_mode="real",
            )
        )

        await service.run_pipeline(detail.id)

        assert _overlaps(timeline, "collector:A:pricing", "collector:A:feature")
        assert _overlaps(timeline, "analyst:A:pricing", "analyst:A:feature")
    finally:
        await service._graph_checkpointer.aclose()
        for path in Path("runs").glob(f"{checkpoint_path.stem}*"):
            path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_collect_qa_blocks_and_retries_collector_before_analyst() -> None:
    checkpoint_path = Path("runs") / f"test_collect_gate_graph_{uuid4().hex}.db"
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            max_iterations=2,
        ),
        graph_checkpointer=GraphCheckpointer(checkpoint_path),
    )
    order: list[str] = []
    collector_calls = 0

    async def fake_planner(record):  # noqa: ANN001, ANN202
        order.append("planner")

    async def fake_collector(record, dimension, competitor):  # noqa: ANN001, ANN202
        nonlocal collector_calls
        collector_calls += 1
        order.append(f"collector:{collector_calls}")
        if collector_calls == 1:
            return
        record.detail.raw_sources.append(
            RawSource(
                id="pricing-1",
                competitor=competitor,
                dimension=dimension,
                source_type="webpage_verified",
                title="A pricing",
                url="https://example.com/pricing",
                snippet="A costs $10.",
                content_hash="abc",
                confidence=0.8,
            )
        )

    async def fake_analyst(record, dimension, competitor):  # noqa: ANN001, ANN202
        order.append("analyst")
        service._merge_competitor_kb_slice(
            record.detail, competitor, dimension, ["A costs $10. [source:pricing-1]"]
        )

    async def fake_comparator(record):  # noqa: ANN001, ANN202
        order.append("comparator")
        record.detail.comparison_matrix = service._build_comparison_matrix(record.detail, {})

    async def fake_reflector(record):  # noqa: ANN001, ANN202
        order.append("reflector")

    async def fake_writer(record):  # noqa: ANN001, ANN202
        order.append("writer")
        record.detail.report_md = "A costs $10. [source:pricing-1]"

    async def fake_qa(record):  # noqa: ANN001, ANN202
        order.append("qa")
        record.detail.qa_findings = []

    service._real_planner_step = fake_planner  # type: ignore[method-assign]
    service._real_collector_branch_step = fake_collector  # type: ignore[method-assign]
    service._real_analyst_branch_step = fake_analyst  # type: ignore[method-assign]
    service._real_comparator_step = fake_comparator  # type: ignore[method-assign]
    service._real_reflector_step = fake_reflector  # type: ignore[method-assign]
    service._real_writer_step = fake_writer  # type: ignore[method-assign]
    service._real_qa_step = fake_qa  # type: ignore[method-assign]

    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic="Collect gate",
                competitors=["A"],
                dimensions=["pricing"],
                execution_mode="real",
            )
        )

        await service.run_pipeline(detail.id)

        assert order == [
            "planner",
            "collector:1",
            "collector:2",
            "analyst",
            "comparator",
            "reflector",
            "writer",
            "qa",
        ]
        updated = service.get_run(detail.id)
        assert updated is not None
        assert updated.status == "completed"
        assert updated.qa_findings == []
    finally:
        await service._graph_checkpointer.aclose()
        for path in Path("runs").glob(f"{checkpoint_path.stem}*"):
            path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_real_pipeline_auto_runs_scoped_redo_for_qa_findings() -> None:
    checkpoint_path = Path("runs") / f"test_auto_redo_graph_{uuid4().hex}.db"
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            max_iterations=2,
        ),
        graph_checkpointer=GraphCheckpointer(checkpoint_path),
    )
    qa_calls = 0

    async def fake_planner(record):  # noqa: ANN001, ANN202
        record.detail.plan.competitors = ["A"]

    async def fake_collector(record, dimension, competitor):  # noqa: ANN001, ANN202
        record.detail.raw_sources.append(
            RawSource(
                id=f"{dimension}-{len(record.detail.raw_sources) + 1}",
                competitor=competitor,
                dimension=dimension,
                source_type="webpage_verified",
                title=f"A {dimension}",
                url=f"https://example.com/{dimension}",
                snippet=f"A {dimension} evidence.",
                content_hash=f"{dimension}-hash",
                confidence=0.8,
            )
        )

    async def fake_analyst(record, dimension, competitor):  # noqa: ANN001, ANN202
        service._merge_competitor_kb_slice(
            record.detail, competitor, dimension, [f"A {dimension} finding."]
        )

    async def fake_comparator(record):  # noqa: ANN001, ANN202
        record.detail.comparison_matrix = service._build_comparison_matrix(
            record.detail, {"matrix_summary": []}
        )

    async def fake_reflector(record):  # noqa: ANN001, ANN202
        return None

    async def fake_writer(record):  # noqa: ANN001, ANN202
        record.detail.report_md = f"Report pass {qa_calls}."

    async def fake_qa(record):  # noqa: ANN001, ANN202
        nonlocal qa_calls
        qa_calls += 1
        if qa_calls == 1:
            record.detail.qa_findings = [
                QCIssue(
                    id="missing-pricing",
                    severity="blocker",
                    detected_by="coverage",
                    target_agent="collector",
                    target_subagent="pricing",
                    field_path="raw_sources[pricing]",
                    problem="Redo pricing evidence.",
                    redo_scope=RedoScope(
                        kind="collector", target_subagent="pricing", rationale="Redo pricing."
                    ),
                )
            ]
        else:
            record.detail.qa_findings = []

    service._real_planner_step = fake_planner  # type: ignore[method-assign]
    service._real_collector_branch_step = fake_collector  # type: ignore[method-assign]
    service._real_analyst_branch_step = fake_analyst  # type: ignore[method-assign]
    service._real_comparator_step = fake_comparator  # type: ignore[method-assign]
    service._real_reflector_step = fake_reflector  # type: ignore[method-assign]
    service._real_writer_step = fake_writer  # type: ignore[method-assign]
    service._real_qa_step = fake_qa  # type: ignore[method-assign]

    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic="Auto redo smoke",
                competitors=["A"],
                dimensions=["pricing"],
                execution_mode="real",
            )
        )

        await service.run_pipeline(detail.id)

        updated = service.get_run(detail.id)
        assert updated is not None
        assert updated.status == "completed"
        assert updated.qa_findings == []
        assert len(updated.revisions) == 1
        assert updated.revisions[0].stage == "collector"
        assert qa_calls == 2
        assert any(
            event.subagent == "auto_redo" and event.type == "node_started"
            for event in service.get_trace(detail.id) or []
        )
    finally:
        await service._graph_checkpointer.aclose()
        for path in Path("runs").glob(f"{checkpoint_path.stem}*"):
            path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_real_pipeline_does_not_auto_redo_warn_only_findings() -> None:
    checkpoint_path = Path("runs") / f"test_auto_redo_warn_graph_{uuid4().hex}.db"
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            max_iterations=2,
        ),
        graph_checkpointer=GraphCheckpointer(checkpoint_path),
    )
    qa_calls = 0

    async def fake_planner(record):  # noqa: ANN001, ANN202
        record.detail.plan.competitors = ["A"]

    async def fake_collector(record, dimension, competitor):  # noqa: ANN001, ANN202
        record.detail.raw_sources.append(
            RawSource(
                id="pricing-1",
                competitor=competitor,
                dimension=dimension,
                source_type="webpage_verified",
                title="A pricing",
                url="https://example.com/pricing",
                snippet="A pricing evidence.",
                content_hash="pricing-hash",
                confidence=0.8,
            )
        )

    async def fake_analyst(record, dimension, competitor):  # noqa: ANN001, ANN202
        service._merge_competitor_kb_slice(
            record.detail, competitor, dimension, ["A pricing finding. [source:pricing-1]"]
        )

    async def fake_comparator(record):  # noqa: ANN001, ANN202
        record.detail.comparison_matrix = service._build_comparison_matrix(
            record.detail, {"matrix_summary": []}
        )

    async def fake_reflector(record):  # noqa: ANN001, ANN202
        return None

    async def fake_writer(record):  # noqa: ANN001, ANN202
        record.detail.report_md = "Report with a warning only. [source:pricing-1]"

    async def fake_qa(record):  # noqa: ANN001, ANN202
        nonlocal qa_calls
        qa_calls += 1
        record.detail.qa_findings = [
            QCIssue(
                id="unverified-pricing",
                severity="warn",
                detected_by="coverage",
                target_agent="collector",
                target_subagent="pricing",
                field_path="raw_sources[pricing].source_type",
                problem="Pricing source is not independently verified.",
                redo_scope=RedoScope(
                    kind="collector", target_subagent="pricing", rationale="Retry pricing."
                ),
            )
        ]

    service._real_planner_step = fake_planner  # type: ignore[method-assign]
    service._real_collector_branch_step = fake_collector  # type: ignore[method-assign]
    service._real_analyst_branch_step = fake_analyst  # type: ignore[method-assign]
    service._real_comparator_step = fake_comparator  # type: ignore[method-assign]
    service._real_reflector_step = fake_reflector  # type: ignore[method-assign]
    service._real_writer_step = fake_writer  # type: ignore[method-assign]
    service._real_qa_step = fake_qa  # type: ignore[method-assign]

    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic="Warn only auto redo",
                competitors=["A"],
                dimensions=["pricing"],
                execution_mode="real",
                auto_redo_warn_enabled=False,
            )
        )

        await service.run_pipeline(detail.id)

        updated = service.get_run(detail.id)
        assert updated is not None
        assert updated.status == "completed"
        assert [issue.id for issue in updated.qa_findings] == ["unverified-pricing"]
        assert updated.revisions == []
        assert qa_calls == 1
        assert not any(
            event.subagent == "auto_redo" and event.type == "node_started"
            for event in service.get_trace(detail.id) or []
        )
    finally:
        await service._graph_checkpointer.aclose()
        for path in Path("runs").glob(f"{checkpoint_path.stem}*"):
            path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_real_pipeline_auto_redoes_warn_when_run_option_enabled() -> None:
    checkpoint_path = Path("runs") / f"test_auto_redo_warn_enabled_graph_{uuid4().hex}.db"
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            max_iterations=2,
        ),
        graph_checkpointer=GraphCheckpointer(checkpoint_path),
    )
    qa_calls = 0

    async def fake_planner(record):  # noqa: ANN001, ANN202
        record.detail.plan.competitors = ["A"]

    async def fake_collector(record, dimension, competitor):  # noqa: ANN001, ANN202
        record.detail.raw_sources.append(
            RawSource(
                id=f"pricing-{len(record.detail.raw_sources) + 1}",
                competitor=competitor,
                dimension=dimension,
                source_type="webpage_verified",
                title="A pricing",
                url="https://example.com/pricing",
                snippet="A pricing evidence.",
                content_hash=f"pricing-hash-{len(record.detail.raw_sources) + 1}",
                confidence=0.8,
            )
        )

    async def fake_analyst(record, dimension, competitor):  # noqa: ANN001, ANN202
        service._merge_competitor_kb_slice(
            record.detail, competitor, dimension, ["A pricing finding."]
        )

    async def fake_comparator(record):  # noqa: ANN001, ANN202
        record.detail.comparison_matrix = service._build_comparison_matrix(
            record.detail, {"matrix_summary": []}
        )

    async def fake_reflector(record):  # noqa: ANN001, ANN202
        return None

    async def fake_writer(record):  # noqa: ANN001, ANN202
        record.detail.report_md = f"Report pass {qa_calls}."

    async def fake_qa(record):  # noqa: ANN001, ANN202
        nonlocal qa_calls
        qa_calls += 1
        if qa_calls == 1:
            record.detail.qa_findings = [
                QCIssue(
                    id="unverified-pricing",
                    severity="warn",
                    detected_by="coverage",
                    target_agent="collector",
                    target_subagent="pricing",
                    field_path="raw_sources[pricing].source_type",
                    problem="Pricing source is not independently verified.",
                    redo_scope=RedoScope(
                        kind="collector", target_subagent="pricing", rationale="Retry pricing."
                    ),
                )
            ]
        else:
            record.detail.qa_findings = []

    service._real_planner_step = fake_planner  # type: ignore[method-assign]
    service._real_collector_branch_step = fake_collector  # type: ignore[method-assign]
    service._real_analyst_branch_step = fake_analyst  # type: ignore[method-assign]
    service._real_comparator_step = fake_comparator  # type: ignore[method-assign]
    service._real_reflector_step = fake_reflector  # type: ignore[method-assign]
    service._real_writer_step = fake_writer  # type: ignore[method-assign]
    service._real_qa_step = fake_qa  # type: ignore[method-assign]

    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic="Warn auto redo enabled",
                competitors=["A"],
                dimensions=["pricing"],
                execution_mode="real",
                auto_redo_warn_enabled=True,
            )
        )

        await service.run_pipeline(detail.id)

        updated = service.get_run(detail.id)
        assert updated is not None
        assert updated.status == "completed"
        assert updated.qa_findings == []
        assert len(updated.revisions) == 1
        assert qa_calls == 2
        auto_redo_events = [
            event
            for event in service.get_trace(detail.id) or []
            if event.subagent == "auto_redo" and event.type == "node_started"
        ]
        assert len(auto_redo_events) == 1
        assert auto_redo_events[0].payload["include_warn"] is True
    finally:
        await service._graph_checkpointer.aclose()
        for path in Path("runs").glob(f"{checkpoint_path.stem}*"):
            path.unlink(missing_ok=True)


def _overlaps(timeline: list[tuple[str, str, float]], left: str, right: str) -> bool:
    points = {(name, phase): timestamp for name, phase, timestamp in timeline}
    return (
        points[(left, "start")] < points[(right, "end")]
        and points[(right, "start")] < points[(left, "end")]
    )


@pytest.mark.asyncio
async def test_collector_and_analyst_trace_spans_have_independent_contexts() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            analyst_react_enabled=False,
        ),
    )

    async def fake_complete_json(*, system: str, user: str, schema_hint: str) -> dict:
        if "collector subagent" in system:
            dimension = "pricing" if "Dimension: pricing" in user else "feature"
            return {
                "sources": [
                    {
                        "competitor": "A",
                        "title": f"A {dimension}",
                        "url": None,
                        "summary": f"A {dimension} summary.",
                        "confidence": 0.7,
                    }
                ]
            }
        return {"competitor_findings": {"A": ["A finding."]}, "caveats": []}

    service._llm.complete_json = fake_complete_json  # type: ignore[method-assign]
    detail = await service.create_run(
        RunCreateRequest(
            topic="Context smoke",
            competitors=["A"],
            dimensions=["pricing", "feature"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]

    await asyncio.gather(
        service._real_collector_step(record, "pricing"),
        service._real_collector_step(record, "feature"),
    )
    await asyncio.gather(
        service._real_analyst_step(record, "pricing"),
        service._real_analyst_step(record, "feature"),
    )

    context_ids = {
        span.metadata["context_id"]
        for span in record.detail.trace_spans
        if span.kind == "llm" and span.agent in {"collector", "analyst"}
    }
    assert len(context_ids) == 4
    assert all(str(context_id).startswith(f"{detail.id}:") for context_id in context_ids)
    assert all(
        span.metadata["message_count"] == 3
        for span in record.detail.trace_spans
        if span.kind == "llm" and span.agent in {"collector", "analyst"}
    )
    assert len({source.id for source in record.detail.raw_sources}) == len(
        record.detail.raw_sources
    )


@pytest.mark.asyncio
async def test_collector_react_runner_searches_fetches_and_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch_page(url: str):  # noqa: ANN202
        return FetchPageResult(
            url=url,
            ok=True,
            title="A pricing page",
            text="A pricing starts at $10 per seat.",
            content_hash="reacthash",
            status_code=200,
        )

    monkeypatch.setattr("packages.orchestrator.service.fetch_page", fake_fetch_page)
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            pplx_api_key="pplx-key",
        ),
    )
    actions = [
        {
            "action": "web_search",
            "query": "A pricing official",
            "rationale": "Find official pricing.",
        },
        {
            "action": "fetch_page",
            "url": "https://example.com/pricing",
            "rationale": "Inspect pricing page.",
        },
        {
            "action": "finish",
            "rationale": "Evidence is sufficient.",
            "sources": [
                {
                    "competitor": "A",
                    "title": "A pricing page",
                    "url": "https://example.com/pricing",
                    "summary": "A pricing starts at $10 per seat.",
                    "confidence": 0.86,
                }
            ],
        },
    ]

    async def fake_complete_json(*, system: str, user: str, schema_hint: str) -> dict:
        if "bounded collector ReAct runner" in system:
            return actions.pop(0)
        raise AssertionError("Fallback collector LLM should not be called when ReAct finishes.")

    async def fake_search(query: str, max_results: int = 3) -> list[SearchResult]:
        return [
            SearchResult(
                title="A pricing page",
                url="https://example.com/pricing",
                snippet="Official pricing information.",
            )
        ]

    service._llm.complete_json = fake_complete_json  # type: ignore[method-assign]
    service._search.search = fake_search  # type: ignore[method-assign]
    detail = await service.create_run(
        RunCreateRequest(
            topic="React smoke",
            competitors=["A"],
            dimensions=["pricing"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]

    await service._real_collector_step(record, "pricing")

    assert len(record.detail.raw_sources) == 1
    assert record.detail.raw_sources[0].source_type == "webpage_verified"
    assert record.detail.raw_sources[0].snippet == "A pricing starts at $10 per seat."
    traced_action_spans = [
        span for span in record.detail.trace_spans if not span.name.startswith("agent_message:")
    ]
    span_names = [span.name for span in traced_action_spans]
    assert span_names == [
        "pricing_react_turn_1",
        "web_search",
        "pricing_react_turn_2",
        "robots_check",
        "fetch_page",
        "pricing_react_turn_3",
        "extract_facts",
    ]
    finish_span = next(span for span in traced_action_spans if span.name == "pricing_react_turn_3")
    assert finish_span.metadata["tool_call_count"] == 3
    assert "context_id" in finish_span.metadata


@pytest.mark.asyncio
async def test_collector_react_finish_fetches_uninspected_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch_page(url: str):  # noqa: ANN202
        return FetchPageResult(
            url=url,
            ok=True,
            title="A pricing page",
            text="A pricing starts at $10 per seat.",
            content_hash="finishhash",
            status_code=200,
        )

    monkeypatch.setattr("packages.orchestrator.service.fetch_page", fake_fetch_page)
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            pplx_api_key="pplx-key",
        ),
    )
    actions = [
        {
            "action": "finish",
            "sources": [
                {
                    "competitor": "A",
                    "title": "A pricing",
                    "url": "https://example.com/pricing",
                    "summary": "A has public pricing.",
                    "confidence": 0.8,
                }
            ],
        }
    ]

    async def fake_complete_json(*, system: str, user: str, schema_hint: str) -> dict:
        if "bounded collector ReAct runner" in system:
            return actions.pop(0)
        raise AssertionError("Fallback collector LLM should not be called when ReAct finishes.")

    service._llm.complete_json = fake_complete_json  # type: ignore[method-assign]
    detail = await service.create_run(
        RunCreateRequest(
            topic="React finish fetch smoke",
            competitors=["A"],
            dimensions=["pricing"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]

    await service._real_collector_step(record, "pricing")

    assert record.detail.raw_sources[0].source_type == "webpage_verified"
    assert record.detail.raw_sources[0].content_hash == "finishhash"
    assert [
        span.name
        for span in record.detail.trace_spans
        if not span.name.startswith("agent_message:")
    ] == [
        "pricing_react_turn_1",
        "robots_check",
        "fetch_page",
        "extract_facts",
    ]


@pytest.mark.asyncio
async def test_analyst_react_runner_inspects_validates_and_finishes() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )
    actions = [
        {"action": "inspect_sources", "rationale": "Review available pricing evidence."},
        {
            "action": "validate_citations",
            "source_ids": ["pricing-1"],
            "rationale": "Check cited source IDs.",
        },
        {
            "action": "finish",
            "competitor_findings": {"A": ["A has a $10 plan [source:pricing-1]."]},
            "source_ids_used": ["pricing-1"],
            "caveats": [],
            "rationale": "Pricing evidence is ready.",
        },
    ]

    async def fake_complete_json(*, system: str, user: str, schema_hint: str) -> dict:
        if "bounded analyst ReAct runner" in system:
            return actions.pop(0)
        raise AssertionError("Fallback analyst LLM should not be called when ReAct finishes.")

    service._llm.complete_json = fake_complete_json  # type: ignore[method-assign]
    detail = await service.create_run(
        RunCreateRequest(
            topic="Analyst ReAct smoke",
            competitors=["A"],
            dimensions=["pricing"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]
    record.detail.raw_sources = [
        RawSource(
            id="pricing-1",
            competitor="A",
            dimension="pricing",
            source_type="webpage_verified",
            title="A pricing",
            url="https://example.com/pricing",
            snippet="A pricing starts at $10 per seat.",
            content_hash="reacthash",
            confidence=0.86,
        )
    ]

    await service._real_analyst_step(record, "pricing")

    assert record.detail.competitor_kbs["A"].slices["pricing"] == [
        "A has a $10 plan [source:pricing-1]."
    ]
    span_names = [span.name for span in record.detail.trace_spans]
    assert span_names == [
        "pricing_analyst_react_turn_1",
        "inspect_sources",
        "pricing_analyst_react_turn_2",
        "validate_citations",
        "pricing_analyst_react_turn_3",
    ]
    finish_span = record.detail.trace_spans[-1]
    assert finish_span.metadata["tool_call_count"] == 2
    assert "context_id" in finish_span.metadata


@pytest.mark.asyncio
async def test_analyst_react_runner_auto_validates_finish() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
    )

    async def fake_complete_json(*, system: str, user: str, schema_hint: str) -> dict:
        if "bounded analyst ReAct runner" in system:
            return {
                "action": "finish",
                "competitor_findings": {"A": ["A has a $10 plan."]},
                "source_ids_used": ["pricing-1"],
                "caveats": [],
                "rationale": "Evidence is sufficient.",
            }
        raise AssertionError("Fallback analyst LLM should not be called when ReAct finishes.")

    service._llm.complete_json = fake_complete_json  # type: ignore[method-assign]
    detail = await service.create_run(
        RunCreateRequest(
            topic="Analyst auto validation smoke",
            competitors=["A"],
            dimensions=["pricing"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]
    record.detail.raw_sources = [
        RawSource(
            id="pricing-1",
            competitor="A",
            dimension="pricing",
            source_type="webpage_verified",
            title="A pricing",
            url="https://example.com/pricing",
            snippet="A pricing starts at $10 per seat.",
            content_hash="reacthash",
            confidence=0.86,
        )
    ]

    await service._real_analyst_step(record, "pricing")

    assert record.detail.competitor_kbs["A"].slices["pricing"] == [
        "A has a $10 plan. [source:pricing-1]"
    ]
    assert [span.name for span in record.detail.trace_spans] == [
        "pricing_analyst_react_turn_1",
        "inspect_sources",
        "validate_citations",
    ]
    assert record.detail.trace_spans[-1].metadata["valid_count"] == 1


@pytest.mark.asyncio
async def test_real_scoped_redo_runs_through_langgraph() -> None:
    checkpoint_path = Path("runs") / f"test_scoped_redo_checkpoints_{uuid4().hex}.db"
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
        graph_checkpointer=GraphCheckpointer(checkpoint_path),
    )
    order: list[str] = []

    async def fake_planner(record):  # noqa: ANN001, ANN202
        order.append("planner")

    async def fake_collector(record, dimension, competitor):  # noqa: ANN001, ANN202
        order.append(f"collector:{competitor}:{dimension}")

    async def fake_analyst(record, dimension, competitor):  # noqa: ANN001, ANN202
        order.append(f"analyst:{competitor}:{dimension}")

    async def fake_comparator(record):  # noqa: ANN001, ANN202
        order.append("comparator")

    async def fake_reflector(record):  # noqa: ANN001, ANN202
        order.append("reflector")

    async def fake_writer(record):  # noqa: ANN001, ANN202
        order.append("writer")

    async def fake_qa(record):  # noqa: ANN001, ANN202
        order.append("qa")

    async def fake_phase_qa(record, phase):  # noqa: ANN001, ANN202
        order.append(f"qa:{phase}")
        record.detail.qa_findings = []

    service._real_planner_step = fake_planner  # type: ignore[method-assign]
    service._real_collector_branch_step = fake_collector  # type: ignore[method-assign]
    service._real_phase_qa_step = fake_phase_qa  # type: ignore[method-assign]
    service._real_analyst_branch_step = fake_analyst  # type: ignore[method-assign]
    service._real_comparator_step = fake_comparator  # type: ignore[method-assign]
    service._real_reflector_step = fake_reflector  # type: ignore[method-assign]
    service._real_writer_step = fake_writer  # type: ignore[method-assign]
    service._real_qa_step = fake_qa  # type: ignore[method-assign]

    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic="Scoped redo smoke",
                competitors=["A"],
                dimensions=["pricing", "feature"],
                execution_mode="real",
            )
        )
        record = service._runs[detail.id]
        record.detail.status = "completed"
        record.detail.report_md = "Before redo"
        record.detail.raw_sources = [
            RawSource(
                id="pricing-1",
                competitor="A",
                dimension="pricing",
                source_type="webpage_verified",
                title="A pricing",
                url="https://example.com/pricing",
                snippet="A costs $10.",
                content_hash="abc",
                confidence=0.8,
            ),
            RawSource(
                id="feature-1",
                competitor="A",
                dimension="feature",
                source_type="webpage_verified",
                title="A feature",
                url="https://example.com/features",
                snippet="A has features.",
                content_hash="def",
                confidence=0.8,
            ),
        ]
        record.detail.qa_findings = [
            QCIssue(
                id="missing-pricing",
                severity="blocker",
                detected_by="coverage",
                target_agent="collector",
                target_subagent="pricing",
                field_path="raw_sources[pricing]",
                problem="Redo pricing evidence.",
                redo_scope=RedoScope(
                    kind="collector", target_subagent="pricing", rationale="Redo pricing."
                ),
            )
        ]

        await service.run_scoped_redo(detail.id)

        assert order == [
            "collector:A:pricing",
            "qa:collect",
            "analyst:A:pricing",
            "qa:analyst",
            "comparator",
            "reflector",
            "writer",
            "qa",
        ], [event.message for event in service.get_trace(detail.id) or []]
        updated = service.get_run(detail.id)
        assert updated is not None
        assert updated.status == "completed"
        assert updated.revisions[0].stage == "collector"
        assert all(source.dimension != "pricing" for source in updated.raw_sources)
        assert any(source.dimension == "feature" for source in updated.raw_sources)
    finally:
        await service._graph_checkpointer.aclose()
        for path in Path("runs").glob(f"{checkpoint_path.stem}*"):
            path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_demo_pipeline_uses_same_langgraph_fanout_shape() -> None:
    checkpoint_path = Path("runs") / f"test_demo_graph_checkpoints_{uuid4().hex}.db"
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=True,
            ark_api_key=None,
            ark_model=None,
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
        ),
        graph_checkpointer=GraphCheckpointer(checkpoint_path),
    )
    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic="Demo graph smoke",
                competitors=["A", "B"],
                dimensions=["pricing"],
                execution_mode="demo",
            )
        )

        await service.run_pipeline(detail.id)
        updated = service.get_run(detail.id)
        assert updated is not None
        assert updated.status == "completed"

        events = service.get_trace(detail.id) or []
        collector_subagents = sorted(
            event.subagent
            for event in events
            if event.type == "node_completed" and event.agent == "collector"
        )
        assert collector_subagents == ["pricing::A", "pricing::B"]
        assert any(event.agent == "collector_dispatch" for event in events)
        assert any(event.agent == "analyst_dispatch" for event in events)
    finally:
        await service._graph_checkpointer.aclose()
        for path in Path("runs").glob(f"{checkpoint_path.stem}*"):
            path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_hitl_uses_langgraph_command_resume_and_updates_plan() -> None:
    checkpoint_path = Path("runs") / f"test_hitl_checkpoints_{uuid4().hex}.db"
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            hitl_enabled=True,
            hitl_timeout_seconds=5,
        ),
        graph_checkpointer=GraphCheckpointer(checkpoint_path),
    )

    async def fake_planner(record):  # noqa: ANN001, ANN202
        record.detail.current_node = "planner"

    async def fake_collector(record, dimension, competitor):  # noqa: ANN001, ANN202
        return None

    async def fake_analyst(record, dimension, competitor):  # noqa: ANN001, ANN202
        return None

    async def fake_phase_qa(record, phase):  # noqa: ANN001, ANN202
        record.detail.qa_findings = []

    async def fake_node(record):  # noqa: ANN001, ANN202
        return None

    async def fake_qa_hitl(record):  # noqa: ANN001, ANN202
        return {"redo_kind": "end"}

    service._real_planner_step = fake_planner  # type: ignore[method-assign]
    service._real_collector_branch_step = fake_collector  # type: ignore[method-assign]
    service._real_analyst_branch_step = fake_analyst  # type: ignore[method-assign]
    service._real_phase_qa_step = fake_phase_qa  # type: ignore[method-assign]
    service._real_comparator_step = fake_node  # type: ignore[method-assign]
    service._real_reflector_step = fake_node  # type: ignore[method-assign]
    service._real_writer_step = fake_node  # type: ignore[method-assign]
    service._real_qa_step = fake_node  # type: ignore[method-assign]
    service._real_qa_hitl_step = fake_qa_hitl  # type: ignore[method-assign]

    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic="HITL smoke",
                competitors=["A"],
                dimensions=["pricing"],
                execution_mode="real",
            )
        )
        record = service._runs[detail.id]
        await service.run_pipeline(detail.id)

        assert record.detail.status == "interrupted"
        assert service.has_pending_interrupt(detail.id) is True
        assert record.active_graph_kind == "real"

        updated = await service.resume(
            detail.id,
            HitlResumeRequest(decision="modify_plan", dimensions=["feature"]),
        )

        assert updated is not None
        for _ in range(300):
            if record.detail.status == "completed":
                break
            await asyncio.sleep(0.01)

        assert record.detail.plan.dimensions == ["feature"]
        assert record.detail.status == "completed"
        assert service.has_pending_interrupt(detail.id) is False
        assert any(event.type == "interrupt" for event in service.get_trace(detail.id) or [])
    finally:
        await service._graph_checkpointer.aclose()
        for path in Path("runs").glob(f"{checkpoint_path.stem}*"):
            for _ in range(10):
                try:
                    path.unlink(missing_ok=True)
                    break
                except PermissionError:
                    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_hitl_timeout_auto_accepts_interrupt() -> None:
    checkpoint_path = Path("runs") / f"test_hitl_timeout_checkpoints_{uuid4().hex}.db"
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            hitl_enabled=True,
            hitl_timeout_seconds=0.05,
        ),
        graph_checkpointer=GraphCheckpointer(checkpoint_path),
    )

    async def fake_planner(record):  # noqa: ANN001, ANN202
        record.detail.current_node = "planner"

    async def fake_collector(record, dimension, competitor):  # noqa: ANN001, ANN202
        return None

    async def fake_analyst(record, dimension, competitor):  # noqa: ANN001, ANN202
        return None

    async def fake_phase_qa(record, phase):  # noqa: ANN001, ANN202
        record.detail.qa_findings = []

    async def fake_node(record):  # noqa: ANN001, ANN202
        return None

    async def fake_qa_hitl(record):  # noqa: ANN001, ANN202
        return {"redo_kind": "end"}

    service._real_planner_step = fake_planner  # type: ignore[method-assign]
    service._real_collector_branch_step = fake_collector  # type: ignore[method-assign]
    service._real_analyst_branch_step = fake_analyst  # type: ignore[method-assign]
    service._real_phase_qa_step = fake_phase_qa  # type: ignore[method-assign]
    service._real_comparator_step = fake_node  # type: ignore[method-assign]
    service._real_reflector_step = fake_node  # type: ignore[method-assign]
    service._real_writer_step = fake_node  # type: ignore[method-assign]
    service._real_qa_step = fake_node  # type: ignore[method-assign]
    service._real_qa_hitl_step = fake_qa_hitl  # type: ignore[method-assign]

    try:
        detail = await service.create_run(
            RunCreateRequest(
                topic="HITL timeout smoke",
                competitors=["A"],
                dimensions=["pricing"],
                execution_mode="real",
            )
        )
        record = service._runs[detail.id]
        await service.run_pipeline(detail.id)

        assert record.detail.status == "interrupted"
        for _ in range(300):
            if record.detail.status == "completed":
                break
            await asyncio.sleep(0.01)

        assert record.detail.status == "completed"
        assert service.has_pending_interrupt(detail.id) is False
        assert any("auto-accepted" in event.message for event in service.get_trace(detail.id) or [])
    finally:
        await service._graph_checkpointer.aclose()
        for path in Path("runs").glob(f"{checkpoint_path.stem}*"):
            for _ in range(10):
                try:
                    path.unlink(missing_ok=True)
                    break
                except PermissionError:
                    await asyncio.sleep(0.05)
