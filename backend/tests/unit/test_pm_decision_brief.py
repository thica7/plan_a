from __future__ import annotations

from types import SimpleNamespace

import pytest

from packages.agents.writer.assembler import ReportSectionFragment, assemble_report_fragments
from packages.agents.writer.publication_contract import validate_publication_contract
from packages.agents.writer.quality_preflight import run_writer_quality_preflight
from packages.agents.writer.section_briefs import build_section_briefs, segment_payloads_from_briefs
from packages.agents.writer.segment_contract import segment_contract_for, validate_segment_contract
from packages.config import Settings
from packages.enterprise import EnterpriseMemoryStore
from packages.i18n.language import report_label
from packages.orchestrator.checkpointer import GraphCheckpointer
from packages.orchestrator.service import RunService
from packages.schema.api_dto import RunCreateRequest, RunDetail
from packages.schema.models import AnalysisPlan, DecisionBrief, RawSource
from packages.schema.report_artifact import ClaimCard, ClaimCardBundle
from packages.skills.registry import SkillRegistry


def _detail(brief: DecisionBrief | None = None, *, language: str = "en-US") -> RunDetail:
    source = RawSource(
        id="source-pricing",
        competitor="Cursor",
        dimension="pricing",
        source_type="webpage_verified",
        title="Cursor pricing",
        snippet="Public pricing page",
        content_hash="pricing-hash",
        confidence=0.9,
    )
    claim = ClaimCard(
        id="claim-pricing",
        run_id="pm-run",
        competitor="Cursor",
        dimension="pricing",
        claim_type="pricing_claim",
        claim="Cursor publishes pricing.",
        source_ids=[source.id],
        confidence=0.9,
        evidence_strength="strong",
        support_level="official",
        scope="pricing",
        caveats=[],
        conflicts=[],
        applicability="pricing",
        producer_stage="analyst:pricing:Cursor",
        derived_from=[source.id],
    )
    return RunDetail(
        id="pm-run",
        topic="AI coding assistant comparison",
        status="running",
        execution_mode="real",
        output_language=language,
        created_at="2026-09-29T00:00:00",
        updated_at="2026-09-29T00:00:00",
        plan=AnalysisPlan(
            topic="AI coding assistant comparison",
            competitors=["Cursor", "Windsurf"],
            dimensions=["pricing"],
            competitor_layer="L1",
            decision_brief=brief,
        ),
        raw_sources=[source],
        claim_card_bundles=[
            ClaimCardBundle(
                run_id="pm-run",
                competitor="Cursor",
                dimension="pricing",
                cards=[claim],
                source_ids=[source.id],
            )
        ],
    )


def _service() -> RunService:
    return RunService(
        SkillRegistry.from_default_path(),
        Settings(
            demo_mode=True,
            ark_api_key="test-key",
            ark_model="test-model",
            ark_base_url="https://example.invalid",
            llm_timeout_seconds=1,
            llm_temperature=0.2,
        ),
        enterprise_store=EnterpriseMemoryStore(),
        graph_checkpointer=GraphCheckpointer.in_memory(),
    )


@pytest.mark.parametrize(
    ("brief", "expected"),
    [
        (None, False),
        (DecisionBrief(), False),
        (DecisionBrief(primary_job="   "), False),
        (DecisionBrief(primary_job="Compare daily coding workflows"), True),
    ],
)
def test_product_opportunities_brief_is_conditional(brief: DecisionBrief | None, expected: bool) -> None:
    detail = _detail(brief)
    keys = [section.section_key for section in build_section_briefs(detail)]

    assert ("product_opportunities" in keys) is expected
    if expected:
        assert keys.index("product_opportunities") == keys.index("decision_summary") + 1
        opportunity = next(item for item in build_section_briefs(detail) if item.section_key == "product_opportunities")
        assert opportunity.layer == "core"
        assert opportunity.allowed_claim_card_ids == ["claim-pricing"]
        assert opportunity.allowed_source_ids == ["source-pricing"]
        assert any("three" in rule.lower() and "validat" in rule.lower() for rule in opportunity.must_include)
        assert any("user-provided" in rule.lower() for rule in opportunity.must_not_claim)


def test_product_opportunity_segment_survives_schema_contract_and_assembly() -> None:
    detail = _detail(DecisionBrief(decision_question="Where should we invest?"))
    segment = next(
        item
        for item in segment_payloads_from_briefs(detail, build_section_briefs(detail))
        if item["section_key"] == "product_opportunities"
    )
    assert segment["user_provided_decision_brief"] == {"decision_question": "Where should we invest?"}
    contract = segment_contract_for(segment)
    assert contract.allowed_heading_keys == ("product_opportunities",)
    assert contract.required_heading_keys == ("product_opportunities",)

    heading = report_label(detail.output_language, "product_opportunities")
    fragment = (
        f"## {heading}\n"
        "- Hypothesis to validate: improve pricing comparison; "
        "User task: compare plans; Validation action: run a buyer pilot; "
        "Success signal — buyers complete the comparison."
    )
    assert validate_segment_contract(fragment, contract).status == "pass"
    assembled = assemble_report_fragments(
        [
            ReportSectionFragment(
                markdown="## Decision Summary\n- Compare the options. [source:source-pricing]",
                section_key="decision_summary",
                layer="core",
                segment_name="decision_summary",
            ),
            ReportSectionFragment(
                markdown=fragment,
                section_key="product_opportunities",
                layer="core",
                segment_name="product_opportunities",
            ),
            ReportSectionFragment(
                markdown="## Evidence & QA Support\n- Verify sources. [source:source-pricing]",
                section_key="evidence_support",
                layer="support",
                segment_name="evidence_support",
            ),
        ],
        output_language=detail.output_language,
        competitors=detail.plan.competitors,
    )
    assert assembled.markdown.index("## Decision Summary") < assembled.markdown.index(f"## {heading}")
    assert assembled.markdown.index(f"## {heading}") < assembled.markdown.index("## Evidence & QA Support")
    assert "<!-- report-section:key=product_opportunities layer=core -->" in assembled.markdown
    assert validate_publication_contract(
        assembled.markdown,
        structured_report=None,
        allowed_source_ids={"source-pricing"},
        output_language=detail.output_language,
    ).passed


def test_product_opportunity_contract_rejects_four_items_and_missing_validation_fields() -> None:
    detail = _detail(DecisionBrief(primary_job="Compare pricing workflows"))
    segment = next(
        item
        for item in segment_payloads_from_briefs(detail, build_section_briefs(detail))
        if item["section_key"] == "product_opportunities"
    )
    contract = segment_contract_for(segment)
    heading = report_label(detail.output_language, "product_opportunities")
    valid_item = (
        "- Hypothesis to validate: improve pricing comparison; "
        "User task: compare plans; Validation action: run a buyer pilot; "
        "Success signal — buyers complete the comparison."
    )

    too_many = validate_segment_contract(
        f"## {heading}\n" + "\n".join(valid_item for _ in range(4)), contract
    )
    missing_fields = validate_segment_contract(
        f"## {heading}\n- Hypothesis to validate: improve pricing comparison.", contract
    )
    unsupported_fact = validate_segment_contract(
        f"## {heading}\n- Cursor has superior pricing; User task: compare plans; "
        "Validation action: run a buyer pilot; Success signal — buyers complete the comparison.",
        contract,
    )

    assert too_many.status == "retry"
    assert missing_fields.status == "retry"
    assert unsupported_fact.status == "retry"


def test_fallback_hardener_adds_uncited_validation_section_from_user_brief() -> None:
    detail = _detail(DecisionBrief(primary_job="Review code [source:invented]"))

    report = _service()._ensure_report_required_sections(detail, "# Draft")
    section = report.split("## Product Opportunities and Validation", 1)[1].split("\n## ", 1)[0]

    assert "Review code" in section
    assert "User task:" in section
    assert "Validation action:" in section
    assert "Success signal —" in section
    assert "hypothesis" in section.lower()
    assert "[source:invented]" not in section
    assert "[source:" not in section


def test_quality_preflight_requires_product_opportunities_when_brief_exists() -> None:
    detail = _detail(DecisionBrief(success_metric="Pilot completion rate"))
    headings = "\n".join(
        f"## {report_label(detail.output_language, key)}"
        for key in (
            "executive_summary",
            "decision_summary",
            "competitive_findings",
            "review_theme_summary",
            "competitor_deep_dives",
            "side_by_side_matrix",
            "swot_analysis",
            "evidence_support",
        )
    )

    assert "product_opportunities" in run_writer_quality_preflight(detail, headings).missing_core_sections
    assert "product_opportunities" not in run_writer_quality_preflight(_detail(), headings).missing_core_sections


@pytest.mark.asyncio
async def test_planner_scope_and_discovery_get_user_decision_context() -> None:
    service = _service()
    captured: list[str] = []

    async def complete_json(*, system: str, user: str, schema_hint: str) -> dict[str, object]:
        captured.append(user)
        if "scoping agent" in system:
            return {"selected_competitors": ["Cursor", "Windsurf"], "rationale": "Comparable tools"}
        return {"complexity": "medium"}

    service._llm.complete_json = complete_json  # type: ignore[method-assign]
    created = await service.create_run(
        RunCreateRequest(
            topic="AI coding assistant comparison",
            competitors=[],
            dimensions=["pricing"],
            execution_mode="real",
            decision_brief={"primary_job": "Compare daily coding workflows"},
        )
    )
    await service._real_planner_step(service._runs[created.id])

    assert len(captured) == 2
    for prompt in captured:
        assert "Compare daily coding workflows" in prompt
        assert "user-provided" in prompt.lower()
        assert "not evidence" in prompt.lower()


@pytest.mark.asyncio
async def test_writer_segment_and_first_draft_prompts_get_user_decision_context() -> None:
    service = _service()
    detail = _detail(DecisionBrief(primary_job="Compare daily coding workflows"))
    record = SimpleNamespace(detail=detail)
    captured: list[str] = []

    async def capture_text(_record: object, **kwargs: object) -> str:
        captured.append(str(kwargs["user"]))
        return "## Product Opportunities and Validation\n- Validate the hypothesis."

    async def grounding(_detail: RunDetail) -> str:
        return "Grounded evidence context"

    service._trace_llm_text = capture_text  # type: ignore[method-assign]
    service._writer_grounding_prompt = grounding  # type: ignore[method-assign]
    segment = next(
        item
        for item in segment_payloads_from_briefs(detail, build_section_briefs(detail))
        if item["section_key"] == "product_opportunities"
    )
    await service._writer_segment_markdown(
        record,
        segment=segment,
        timeout_seconds=1,
        language_guidance="English",
        memory_context="none",
        layer_context="L1",
        required_sections=service._writer_required_sections(detail),
        retry_count=0,
    )
    evidence_pack = SimpleNamespace(
        metrics=SimpleNamespace(segmented_writer_required=False),
        to_prompt_json=lambda: "{}",
    )
    await service._writer_markdown_report_from_evidence_pack(record, evidence_pack, 1)

    assert len(captured) == 2
    for prompt in captured:
        assert "Compare daily coding workflows" in prompt
        assert "user-provided" in prompt.lower()
        assert "not evidence" in prompt.lower()
        assert "Product Opportunities and Validation" in prompt
    assert "Success signal —" in captured[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("with_brief", [False, True])
async def test_demo_pipeline_only_adds_uncited_product_section_for_brief(with_brief: bool) -> None:
    service = _service()
    created = await service.create_run(
        RunCreateRequest(
            topic="Demo PM report",
            competitors=["Cursor", "Windsurf"],
            dimensions=["pricing"],
            execution_mode="demo",
            output_language="zh-CN",
            competitor_layer="L1",
            decision_brief={
                "primary_job": "让团队更快完成代码评审",
                "success_metric": "试点任务完成率",
            } if with_brief else None,
        )
    )
    completed = await service.run_pipeline(created.id)
    report = completed.report_md
    heading = "## 产品机会与验证"

    assert completed.status in {"completed", "completed_with_blockers"}
    assert (heading in report) is with_brief
    if with_brief:
        section = report.split(heading, 1)[1].split("\n## ", 1)[0]
        assert "让团队更快完成代码评审" in section
        assert "试点任务完成率" in section
        assert "用户输入" in section
        assert "待验证" in section
        assert "[source:" not in section


def test_demo_user_brief_cannot_create_source_citation() -> None:
    detail = _detail(DecisionBrief(primary_job="Review code [source:invented]"))
    report = _service()._demo_report(detail)
    section = report.split("## Product Opportunities and Validation", 1)[1].split("\n## ", 1)[0]

    assert "Review code" in section
    assert "[source:invented]" not in section
    assert "[source:" not in section


def test_english_demo_product_section_passes_publication_contract() -> None:
    detail = _detail(DecisionBrief(primary_job="Review code"))
    report = _service()._demo_report(detail)

    result = validate_publication_contract(
        report,
        structured_report=None,
        allowed_source_ids={"source-pricing"},
        output_language="en-US",
    )

    assert result.passed, result.issue_codes()
