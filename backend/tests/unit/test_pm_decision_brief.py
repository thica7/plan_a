from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.deps import get_runtime_command_service
from app.main import create_app
from packages.agents.writer.assembler import (
    ReportSectionFragment,
    assemble_report_fragments,
    assemble_report_sections,
)
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
from packages.schema.decision_brief import decision_brief_prompt_context
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


@pytest.mark.parametrize("field", ["decision_question", "primary_job", "success_metric"])
@pytest.mark.parametrize(
    "token",
    [
        "[source:source-pricing]",
        "[SOURCE :source-pricing]",
        "[source：source-pricing]",
        "[来源:source-pricing]",
    ],
)
def test_decision_brief_rejects_source_token_in_any_field(field: str, token: str) -> None:
    with pytest.raises(ValidationError, match="source citation"):
        DecisionBrief(**{field: f"Review code {token}"})

    with pytest.raises(ValidationError, match="source citation"):
        RunCreateRequest(
            topic="AI coding assistant comparison",
            competitors=["Cursor"],
            dimensions=["pricing"],
            execution_mode="demo",
            decision_brief={field: f"Review code {token}"},
        )


def test_run_create_api_returns_422_for_brief_source_token() -> None:
    async def fake_create_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            route="local",
            metadata={},
            command_id="test-command",
            audit_correlation_id="test-audit",
            payload=_detail(),
        )

    app = create_app()
    app.dependency_overrides[get_runtime_command_service] = lambda: SimpleNamespace(
        create_run=fake_create_run
    )
    response = TestClient(app).post(
        "/api/runs",
        json={
            "topic": "AI coding assistant comparison",
            "competitors": ["Cursor"],
            "dimensions": ["pricing"],
            "execution_mode": "demo",
            "decision_brief": {"primary_job": "Review code [source:source-pricing]"},
        },
    )

    assert response.status_code == 422
    assert "decision_brief" in str(response.json())


def test_legacy_decision_brief_prompt_escapes_source_token() -> None:
    legacy_brief = DecisionBrief.model_construct(primary_job="Review code [source:source-pricing]")

    prompt = decision_brief_prompt_context(legacy_brief)

    assert "Review code" in prompt
    assert "[source:" not in prompt
    assert "［source:source-pricing］" in prompt


def test_legacy_decision_brief_full_report_does_not_cite_user_input() -> None:
    legacy_brief = DecisionBrief.model_construct(primary_job="Review code [source:source-pricing]")
    detail = _detail(legacy_brief)

    report = _service()._harden_report_markdown(detail, "# Draft")
    section = report.split("## Product Opportunities and Validation", 1)[1].split("\n## ", 1)[0]

    assert "Review code" in section
    assert "[source:" not in section
    assert run_writer_quality_preflight(detail, report).passed


@pytest.mark.parametrize(
    ("brief", "expected"),
    [
        (None, False),
        (DecisionBrief(), False),
        (DecisionBrief(primary_job="   "), False),
        (DecisionBrief(primary_job="Compare daily coding workflows"), True),
    ],
)
def test_product_opportunities_brief_is_conditional(
    brief: DecisionBrief | None, expected: bool,
) -> None:
    detail = _detail(brief)
    keys = [section.section_key for section in build_section_briefs(detail)]

    assert ("product_opportunities" in keys) is expected
    if expected:
        assert keys.index("product_opportunities") == keys.index("decision_summary") + 1
        opportunity = next(
            item for item in build_section_briefs(detail)
            if item.section_key == "product_opportunities"
        )
        assert opportunity.layer == "core"
        assert opportunity.allowed_claim_card_ids == ["claim-pricing"]
        assert opportunity.allowed_source_ids == ["source-pricing"]
        assert any(
            "three" in rule.lower() and "validat" in rule.lower()
            for rule in opportunity.must_include
        )
        assert any("user-provided" in rule.lower() for rule in opportunity.must_not_claim)
        assert opportunity.minimum_depth["maximum_bullet_items"] == 3


def test_product_opportunity_segment_survives_schema_contract_and_assembly() -> None:
    detail = _detail(DecisionBrief(decision_question="Where should we invest?"))
    segment = next(
        item
        for item in segment_payloads_from_briefs(detail, build_section_briefs(detail))
        if item["section_key"] == "product_opportunities"
    )
    assert segment["user_provided_decision_brief"] == {
        "decision_question": "Where should we invest?"
    }
    contract = segment_contract_for(segment)
    assert contract.allowed_heading_keys == ("product_opportunities",)
    assert contract.required_heading_keys == ("product_opportunities",)

    heading = report_label(detail.output_language, "product_opportunities")
    fragment = (
        f"## {heading}\n"
        "- Hypothesis to validate: improve pricing comparison — "
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
    assert (
        assembled.markdown.index("## Decision Summary")
        < assembled.markdown.index(f"## {heading}")
    )
    assert (
        assembled.markdown.index(f"## {heading}")
        < assembled.markdown.index("## Evidence & QA Support")
    )
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
        "- Hypothesis to validate: improve pricing comparison — "
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


def test_product_opportunity_contract_rejects_hidden_items_and_late_hypothesis_marker() -> None:
    detail = _detail(DecisionBrief(primary_job="Compare pricing workflows"))
    segment = next(
        item
        for item in segment_payloads_from_briefs(detail, build_section_briefs(detail))
        if item["section_key"] == "product_opportunities"
    )
    contract = segment_contract_for(segment)
    heading = report_label(detail.output_language, "product_opportunities")
    valid_item = (
        "- Hypothesis to validate: improve pricing comparison — "
        "User task: compare plans; Validation action: run a buyer pilot; "
        "Success signal — buyers complete the comparison."
    )

    for extra in (
        "4. Opportunity: add a discount workflow.",
        "Another opportunity is a discount workflow.",
        "### Fourth opportunity",
    ):
        result = validate_segment_contract(
            f"## {heading}\n{valid_item}\n{extra}", contract
        )
        assert result.status == "retry", extra

    late_marker = validate_segment_contract(
        f"## {heading}\n- Cursor has superior pricing, a hypothesis to validate; "
        "User task: compare plans; Validation action: run a buyer pilot; "
        "Success signal — buyers complete the comparison.",
        contract,
    )
    assert late_marker.status == "retry"


@pytest.mark.parametrize(
    ("language", "bullet"),
    [
        (
            "en-US",
            "Hypothesis to validate: test onboarding; Cursor offers free enterprise SSO. "
            "User task: onboard a team; Validation action: run a pilot; "
            "Success signal — the team completes setup.",
        ),
        (
            "zh-CN",
            "待验证机会假设：优化上手；Cursor 提供免费企业 SSO。"
            "用户任务：完成团队入门；验证动作：开展试点；成功信号：团队完成设置。",
        ),
    ],
)
def test_uncited_hypothesis_cannot_hide_second_competitor_fact(language: str, bullet: str) -> None:
    detail = _detail(DecisionBrief(primary_job="Test onboarding"), language=language)
    segment = next(
        item
        for item in segment_payloads_from_briefs(detail, build_section_briefs(detail))
        if item["section_key"] == "product_opportunities"
    )
    heading = report_label(language, "product_opportunities")
    fragment = f"## {heading}\n- {bullet}"

    assert validate_segment_contract(fragment, segment_contract_for(segment)).status == "retry"
    report = "\n".join(
        f"## {report_label(language, key)}\n"
        + (f"- {bullet}" if key == "product_opportunities" else "- Existing section content.")
        for key in (
            "executive_summary",
            "decision_summary",
            "product_opportunities",
            "competitive_findings",
            "review_theme_summary",
            "competitor_deep_dives",
            "side_by_side_matrix",
            "swot_analysis",
            "evidence_support",
        )
    )
    assert (
        "invalid_product_opportunities"
        in run_writer_quality_preflight(detail, report).failure_reasons
    )


@pytest.mark.parametrize(
    ("language", "bullet"),
    [
        (
            "en-US",
            "Hypothesis to validate: test onboarding because Cursor offers free SSO — "
            "User task: evaluate Cursor onboarding; Validation action: run a pilot; "
            "Success signal — the team completes setup.",
        ),
        (
            "zh-CN",
            "待验证机会假设：借助 Cursor 的免费 SSO 改进入门，"
            "用户任务：评估 Cursor 入门；验证动作：开展试点；成功信号：团队完成设置。",
        ),
    ],
)
def test_uncited_hypothesis_cannot_name_competitor_before_task(language: str, bullet: str) -> None:
    detail = _detail(DecisionBrief(primary_job="Evaluate Cursor onboarding"), language=language)
    segment = next(
        item
        for item in segment_payloads_from_briefs(detail, build_section_briefs(detail))
        if item["section_key"] == "product_opportunities"
    )
    fragment = f"## {report_label(language, 'product_opportunities')}\n- {bullet}"

    assert validate_segment_contract(fragment, segment_contract_for(segment)).status == "retry"
    report = "\n".join(
        f"## {report_label(language, key)}\n"
        + (f"- {bullet}" if key == "product_opportunities" else "- Existing section content.")
        for key in (
            "executive_summary",
            "decision_summary",
            "product_opportunities",
            "competitive_findings",
            "review_theme_summary",
            "competitor_deep_dives",
            "side_by_side_matrix",
            "swot_analysis",
            "evidence_support",
        )
    )
    assert (
        "invalid_product_opportunities"
        in run_writer_quality_preflight(detail, report).failure_reasons
    )


def test_product_opportunity_allows_competitor_in_task_or_with_citation() -> None:
    detail = _detail(DecisionBrief(primary_job="Evaluate Cursor onboarding"))
    segment = next(
        item
        for item in segment_payloads_from_briefs(detail, build_section_briefs(detail))
        if item["section_key"] == "product_opportunities"
    )
    contract = segment_contract_for(segment)
    heading = report_label(detail.output_language, "product_opportunities")
    generic = (
        f"## {heading}\n- Hypothesis to validate: test onboarding — "
        "User task: evaluate Cursor onboarding [source:source-pricing]; "
        "Validation action: run a pilot; "
        "Success signal — the team completes setup."
    )
    cited = (
        f"## {heading}\n- Cursor publishes pricing [source:source-pricing] — "
        "User task: compare Cursor plans; Validation action: run a buyer pilot; "
        "Success signal — buyers complete the comparison."
    )

    assert segment["allowed_source_ids"] == ["source-pricing"]
    assert validate_segment_contract(generic, contract).status == "pass"
    assert validate_segment_contract(cited, contract).status == "pass"


@pytest.mark.parametrize(
    ("language", "bullet"),
    [
        (
            "en-US",
            "Hypothesis to validate: test onboarding because Cursor offers free SSO — "
            "User task: compare Cursor pricing [source:source-pricing]; "
            "Validation action: run a pilot; Success signal — complete setup.",
        ),
        (
            "zh-CN",
            "待验证机会假设：借助 Cursor 免费 SSO 改进入门，"
            "用户任务：比较 Cursor 价格 [source:source-pricing]；"
            "验证动作：开展试点；成功信号：完成设置。",
        ),
        (
            "en-US",
            "Cursor offers free SSO — User task: compare Cursor pricing; "
            "Validation action: run a pilot; Success signal — complete setup "
            "[source:source-pricing].",
        ),
    ],
)
def test_task_or_signal_citation_cannot_support_prior_competitor_fact(
    language: str, bullet: str,
) -> None:
    detail = _detail(DecisionBrief(primary_job="Compare Cursor pricing"), language=language)
    segment = next(
        item
        for item in segment_payloads_from_briefs(detail, build_section_briefs(detail))
        if item["section_key"] == "product_opportunities"
    )
    fragment = f"## {report_label(language, 'product_opportunities')}\n- {bullet}"

    assert validate_segment_contract(fragment, segment_contract_for(segment)).status == "retry"
    report = "\n".join(
        f"## {report_label(language, key)}\n"
        + (f"- {bullet}" if key == "product_opportunities" else "- Existing section content.")
        for key in (
            "executive_summary",
            "decision_summary",
            "product_opportunities",
            "competitive_findings",
            "review_theme_summary",
            "competitor_deep_dives",
            "side_by_side_matrix",
            "swot_analysis",
            "evidence_support",
        )
    )
    assert (
        "invalid_product_opportunities"
        in run_writer_quality_preflight(detail, report).failure_reasons
    )
    with pytest.raises(RuntimeError, match="quality preflight"):
        _service()._harden_schema_contract_report_markdown(detail, report)


def test_fallback_hardener_adds_uncited_validation_section_from_user_brief() -> None:
    detail = _detail(DecisionBrief.model_construct(primary_job="Review code [source:invented]"))

    report = _service()._ensure_report_required_sections(detail, "# Draft")
    section = report.split("## Product Opportunities and Validation", 1)[1].split("\n## ", 1)[0]

    assert "Review code" in section
    assert "User task:" in section
    assert "Validation action:" in section
    assert "Success signal —" in section
    assert "hypothesis" in section.lower()
    assert "[source:invented]" not in section
    assert "[source:" not in section


def test_fallback_full_hardening_does_not_cite_user_context_or_hypothesis() -> None:
    detail = _detail(DecisionBrief(primary_job="Review code"))
    draft = (
        "# Draft\n\n## Competitive Findings\n"
        "- Cursor publishes pricing. [source:source-pricing]"
    )

    report = _service()._harden_report_markdown(detail, draft)
    section = report.split("## Product Opportunities and Validation", 1)[1].split("\n## ", 1)[0]

    assert "Review code" in section
    assert "[source:" not in section
    assert "Cursor publishes pricing. [source:source-pricing]" in report
    assert run_writer_quality_preflight(detail, report).passed
    assert [line for line in section.splitlines() if line.strip()] == [
        line for line in section.splitlines() if line.startswith("- ")
    ]
    assert "user-provided" in section.casefold()


def test_fallback_without_brief_keeps_legacy_sections() -> None:
    detail = _detail()

    report = _service()._harden_report_markdown(detail, "# Draft")

    assert "## Product Opportunities and Validation" not in report
    assert run_writer_quality_preflight(detail, report).passed


@pytest.mark.parametrize("invalid_body", ["four_items", "missing_fields", "competitor_fact"])
def test_fallback_replaces_only_invalid_existing_product_opportunities(invalid_body: str) -> None:
    detail = _detail(DecisionBrief(primary_job="Review code"))
    opportunity = (
        "- Hypothesis to validate: improve code review — User task: review code; "
        "Validation action: run a team pilot; Success signal — reviewers finish the task."
    )
    product_body = {
        "four_items": "\n".join(opportunity for _ in range(4)),
        "missing_fields": "- Hypothesis to validate: improve code review.",
        "competitor_fact": (
            "- Hypothesis to validate: test review because Cursor offers free SSO — "
            "User task: review code; Validation action: run a team pilot; "
            "Success signal — reviewers finish the task."
        ),
    }[invalid_body]
    draft = (
        "# Draft\n\n## Decision Summary\n- Keep the comparison conditional.\n\n"
        "## Product Opportunities and Validation\n"
        + product_body
        + "\n\n## Competitive Findings\n- Cursor publishes pricing. [source:source-pricing]"
    )

    report = _service()._harden_report_markdown(detail, draft)
    section = report.split("## Product Opportunities and Validation", 1)[1].split("\n## ", 1)[0]

    assert section.count("- ") == 1
    assert "user-provided" in section.casefold()
    assert "[source:" not in section
    assert "Cursor publishes pricing. [source:source-pricing]" in report
    assert run_writer_quality_preflight(detail, report).passed


def test_fallback_preserves_valid_existing_product_opportunities_and_citation() -> None:
    detail = _detail(DecisionBrief(primary_job="Review code"))
    cited_opportunity = (
        "- Cursor publishes pricing [source:source-pricing]; User task: compare plans; "
        "Validation action: run a buyer pilot; Success signal — buyers complete the comparison."
    )
    draft = (
        "# Draft\n\n## Product Opportunities and Validation\n"
        f"{cited_opportunity}\n\n## Competitive Findings\n"
        "- Cursor publishes pricing. [source:source-pricing]"
    )

    report = _service()._harden_report_markdown(detail, draft)
    section = report.split("## Product Opportunities and Validation", 1)[1].split("\n## ", 1)[0]

    assert cited_opportunity in section
    assert section.count("- ") == 1
    assert run_writer_quality_preflight(detail, report).passed


def test_fallback_without_brief_does_not_replace_existing_product_section() -> None:
    detail = _detail()
    draft = (
        "# Draft\n\n## Product Opportunities and Validation\n"
        "- Existing legacy text.\n\n## Competitive Findings\n"
        "- Cursor publishes pricing. [source:source-pricing]"
    )

    report = _service()._harden_report_markdown(detail, draft)

    assert "- Existing legacy text." in report


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

    assert (
        "product_opportunities"
        in run_writer_quality_preflight(detail, headings).missing_core_sections
    )
    assert (
        "product_opportunities"
        not in run_writer_quality_preflight(_detail(), headings).missing_core_sections
    )


@pytest.mark.parametrize(
    "product_body",
    [
        "\n".join(
            "- Hypothesis to validate: improve pricing comparison — User task: compare plans; "
            "Validation action: run a buyer pilot; Success signal — buyers complete the comparison."
            for _ in range(4)
        ),
        "- Hypothesis to validate: improve pricing comparison.",
        (
            "- Hypothesis to validate: improve pricing comparison — User task: "
            "compare plans; Validation action: run a buyer pilot; Success signal — "
            "buyers complete the comparison.\n"
            "### Fourth opportunity\nAn additional unsupported product idea."
        ),
    ],
)
def test_schema_contract_final_preflight_rejects_invalid_product_repair(product_body: str) -> None:
    detail = _detail(DecisionBrief(primary_job="Compare pricing workflows"))
    report = "\n".join(
        f"## {report_label(detail.output_language, key)}\n"
        + (product_body if key == "product_opportunities" else "- Existing section content.")
        for key in (
            "executive_summary",
            "decision_summary",
            "product_opportunities",
            "competitive_findings",
            "review_theme_summary",
            "competitor_deep_dives",
            "side_by_side_matrix",
            "swot_analysis",
            "evidence_support",
        )
    )

    assert (
        "invalid_product_opportunities"
        in run_writer_quality_preflight(detail, report).failure_reasons
    )
    with pytest.raises(RuntimeError, match="quality preflight"):
        _service()._harden_schema_contract_report_markdown(detail, report)


def test_schema_contract_final_preflight_accepts_valid_product_section() -> None:
    detail = _detail(DecisionBrief(primary_job="Compare pricing workflows"))
    product_body = (
        "- Hypothesis to validate: improve pricing comparison — User task: compare plans; "
        "Validation action: run a buyer pilot; Success signal — buyers complete the comparison."
    )
    report = "\n".join(
        f"## {report_label(detail.output_language, key)}\n"
        + (product_body if key == "product_opportunities" else "- Existing section content.")
        for key in (
            "executive_summary",
            "decision_summary",
            "product_opportunities",
            "competitive_findings",
            "review_theme_summary",
            "competitor_deep_dives",
            "side_by_side_matrix",
            "swot_analysis",
            "evidence_support",
        )
    )

    assembled = assemble_report_sections(
        [report],
        output_language=detail.output_language,
        competitors=detail.plan.competitors,
    )
    assert run_writer_quality_preflight(detail, assembled.markdown).passed
    assert (
        _service()._harden_schema_contract_report_markdown(detail, assembled.markdown)
        == assembled.markdown
    )


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
    assert "No preamble, paragraphs, numbered lists, extra headings" in captured[0]
    assert "Before User task, write only one hypothesis clause" in captured[0]
    assert "Do not name a researched competitor before User task without a citation" in captured[0]


@pytest.mark.asyncio
async def test_legacy_brief_is_escaped_in_actual_segment_context() -> None:
    legacy_brief = DecisionBrief.model_construct(
        primary_job="Review code [source:source-pricing]"
    )
    detail = _detail(legacy_brief)
    segment = next(
        item
        for item in segment_payloads_from_briefs(detail, build_section_briefs(detail))
        if item["section_key"] == "product_opportunities"
    )
    assert segment["allowed_source_ids"] == ["source-pricing"]
    assert "[source:source-pricing]" not in str(segment["user_provided_decision_brief"])

    captured: list[str] = []

    async def capture_text(_record: object, **kwargs: object) -> str:
        captured.append(str(kwargs["user"]))
        return "## Product Opportunities and Validation\n- Hypothesis to validate: test the task."

    service = _service()
    service._trace_llm_text = capture_text  # type: ignore[method-assign]
    await service._writer_segment_markdown(
        SimpleNamespace(detail=detail),
        segment=segment,
        timeout_seconds=1,
        language_guidance="English",
        memory_context="none",
        layer_context="L1",
        required_sections=service._writer_required_sections(detail),
        retry_count=0,
    )
    segment_context = captured[0].split("Segment Context JSON: ", 1)[1].split(
        "\n\nRequired sections", 1
    )[0]

    assert "Review code" in segment_context
    assert "[source:source-pricing]" not in segment_context
    assert "［source:source-pricing］" in segment_context
    assert "source-pricing" in segment_context


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


@pytest.mark.parametrize(
    ("language", "heading", "labels"),
    [
        ("zh-CN", "产品机会与验证", ("用户任务：", "验证动作：", "成功信号：")),
        (
            "en-US",
            "Product Opportunities and Validation",
            ("User task:", "validation action:", "success signal —"),
        ),
    ],
)
def test_demo_opportunity_is_one_complete_uncited_bullet(
    language: str, heading: str, labels: tuple[str, str, str]
) -> None:
    detail = _detail(
        DecisionBrief(primary_job="Review code", success_metric="Pilot completion rate"),
        language=language,
    )
    report = _service()._demo_report(detail)
    section = report.split(f"## {heading}", 1)[1].split("\n## ", 1)[0]
    bullets = [line for line in section.splitlines() if line.startswith("- ")]

    assert len(bullets) == 1
    assert all(label in bullets[0] for label in labels)
    assert "Review code" in bullets[0]
    assert "Pilot completion rate" in bullets[0]
    assert "[source:" not in section
    assert [line for line in section.splitlines() if line.strip()] == bullets
    assert ("用户输入" if language == "zh-CN" else "User-provided") in bullets[0]
    assert run_writer_quality_preflight(detail, report).passed


def test_demo_user_brief_cannot_create_source_citation() -> None:
    detail = _detail(DecisionBrief.model_construct(primary_job="Review code [source:invented]"))
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
