from __future__ import annotations

from datetime import datetime

from packages.agents.writer.repair import (
    apply_line_repair,
    build_writer_repair_plan,
    replace_markdown_section,
    report_regression_problem,
)
from packages.schema.api_dto import RunDetail
from packages.schema.models import (
    AnalysisPlan,
    QCIssue,
    RawSource,
    RedoScope,
    RunMetrics,
)


def test_writer_repair_classifies_line_repair_for_protectable_report() -> None:
    detail = _detail(report_md=_protectable_report())
    issues = [_report_line_issue(line_number=8, problem="non-publishable text noise")]

    plan = build_writer_repair_plan(detail, issues, upstream_data_changed=False)

    assert plan.mode == "line"
    assert plan.previous_report_protectable is True
    assert plan.line_numbers == [8]


def test_writer_repair_requires_full_rewrite_for_poor_report() -> None:
    detail = _detail(report_md="# Report\n\nthin")
    issues = [_report_line_issue(line_number=3, problem="non-publishable text noise")]

    plan = build_writer_repair_plan(detail, issues, upstream_data_changed=False)

    assert plan.mode == "full"
    assert plan.previous_report_protectable is False
    assert "report is not protectable" in plan.reason


def test_writer_repair_upstream_changed_allows_full_without_anti_regression() -> None:
    detail = _detail(report_md=_protectable_report())
    issues = [_report_line_issue(line_number=8, problem="stale pricing evidence")]

    plan = build_writer_repair_plan(detail, issues, upstream_data_changed=True)

    assert plan.mode == "full"
    assert plan.previous_report_protectable is True
    assert plan.anti_regression_required is False


def test_writer_repair_maps_thin_competitive_findings_to_section_repair() -> None:
    detail = _detail(report_md=_protectable_report())
    issue = QCIssue.model_construct(
        id="issue-competitive-findings-thin",
        severity="blocker",
        detected_by="report_quality",
        target_agent="writer",
        field_path="report_quality.core_section_depth_score",
        problem="Competitive Findings section is too thin for decision-grade reporting.",
        redo_scope=RedoScope(kind="writer_only", rationale="Expand Competitive Findings."),
    )

    plan = build_writer_repair_plan(detail, [issue], upstream_data_changed=False)

    assert plan.mode == "section"
    assert plan.sections == ["competitive_findings"]


def test_writer_repair_maps_thin_decision_summary_to_section_repair() -> None:
    detail = _detail(report_md=_protectable_report())
    issue = QCIssue.model_construct(
        id="issue-decision-summary-thin",
        severity="blocker",
        detected_by="report_quality",
        target_agent="writer",
        field_path="report_quality.core_section_depth_score",
        problem="Decision Summary section needs recommended action and immediate next move.",
        redo_scope=RedoScope(kind="writer_only", rationale="Expand Decision Summary."),
    )

    plan = build_writer_repair_plan(detail, [issue], upstream_data_changed=False)

    assert plan.mode == "section"
    assert plan.sections == ["decision_summary"]


def test_apply_line_repair_removes_only_still_noisy_lines() -> None:
    markdown = "good opening\nbad line \ufffd\nkeep this cited line [source:pricing-1]\n"
    issues = [_report_line_issue(line_number=2, problem="non-publishable text noise")]

    repaired = apply_line_repair(markdown, issues)

    assert "bad line" not in repaired
    assert "good opening" in repaired
    assert "keep this cited line [source:pricing-1]" in repaired


def test_replace_markdown_section_preserves_unrelated_sections() -> None:
    original = (
        "# Report\n\n"
        "## Executive Summary\n"
        "Keep this summary. [source:pricing-1]\n\n"
        "## User Review Themes\n"
        "Thin.\n\n"
        "## SWOT Analysis\n"
        "- Strengths: keep swot. [source:pricing-1]\n"
    )
    replacement = (
        "## User Review Themes\n"
        "- Praise: users value direct workflow fit. [source:pricing-1]\n"
        "- Blocker: rollout still needs security proof. [source:pricing-1]\n"
    )

    updated = replace_markdown_section(
        original,
        target_section="review_theme_summary",
        output_language="en-US",
        replacement_markdown=replacement,
    )

    assert "Keep this summary. [source:pricing-1]" in updated
    assert "- Strengths: keep swot. [source:pricing-1]" in updated
    assert "- Praise: users value direct workflow fit. [source:pricing-1]" in updated
    assert "Thin." not in updated


def test_replace_markdown_section_replaces_zh_cn_heading_without_duplicate() -> None:
    original = (
        "# 报告\n\n"
        "## 执行摘要\n"
        "保留摘要内容。 [source:pricing-1]\n\n"
        "## 用户评价整理\n"
        "旧的用户评价内容。\n\n"
        "## SWOT 分析\n"
        "- 保留 SWOT 内容。 [source:feature-1]\n"
    )
    replacement = (
        "## 用户评价整理\n"
        "- 新评价: 买家关注定价透明度。 [source:pricing-1]\n"
    )

    updated = replace_markdown_section(
        original,
        "review_theme_summary",
        "zh-CN",
        replacement,
    )

    assert updated.count("## 用户评价整理") == 1
    assert "旧的用户评价内容" not in updated
    assert "- 新评价: 买家关注定价透明度。 [source:pricing-1]" in updated
    assert "保留摘要内容。 [source:pricing-1]" in updated
    assert "- 保留 SWOT 内容。 [source:feature-1]" in updated


def test_report_regression_detects_collapsed_review_section() -> None:
    previous = _detail(report_md=_protectable_report())
    candidate = _detail(
        report_md=_protectable_report().replace(
            (
                "User review themes show Cursor is easier to explain during procurement, "
                "while Copilot benefits from\n"
                "existing Microsoft workflow familiarity. [source:pricing-1]\n"
                "- Customer theme: pricing clarity supports fast evaluation. [source:pricing-1]\n"
                "- Adoption blocker: security review and procurement packaging still need "
                "deeper evidence.\n"
                "[source:feature-1]"
            ),
            "Existing evidence does not provide verified user reviews.",
        )
    )

    problem = report_regression_problem(
        previous, candidate, protected_sections=["review_theme_summary"]
    )

    assert problem is not None
    assert "review_theme_summary" in problem


def test_report_regression_detects_collapsed_zh_cn_review_section() -> None:
    previous_body = (
        "用户评价整理显示，采购团队更容易理解 Cursor 的定价透明度，也会继续比较 "
        "Copilot 在微软工作流中的熟悉度。 [source:pricing-1]\n"
        "- 客户主题: 定价清晰度帮助销售团队更快完成评估。 [source:pricing-1]\n"
        "- 采用阻碍: 安全审查和采购包装仍需要更深证据。 [source:feature-1]\n"
        "- 转换触发: 当团队需要更直接的开发流程说明时，Cursor 更容易被提出。 "
        "[source:pricing-1]\n"
        "- 采购语境: 团队还会比较上线培训、合规审查和现有微软采购路径，"
        "因此评价摘要必须保留这些有证据的购买阻力。 [source:feature-1]"
    )
    previous = _detail(
        report_md=(
            "# Cursor vs Copilot\n\n"
            "## 用户评价整理\n"
            f"{previous_body}\n\n"
            "## SWOT 分析\n"
            "- 优势: 保留 SWOT 内容。 [source:feature-1]\n"
        )
    )
    candidate = _detail(
        report_md=previous.report_md.replace(
            previous_body,
            "现有证据不足以提供已验证的用户评价。",
        )
    )

    problem = report_regression_problem(previous, candidate, ["review_theme_summary"])

    assert problem is not None
    assert "review_theme_summary" in problem


def test_writer_repair_helpers_accept_approved_positional_api() -> None:
    detail = _detail(report_md=_protectable_report())
    issues = [_report_line_issue(line_number=8, problem="non-publishable text noise")]

    plan = build_writer_repair_plan(detail, issues)

    assert plan.mode == "line"

    updated = replace_markdown_section(
        "# Report\n\n## User Review Themes\nThin.\n",
        "review_theme_summary",
        "en-US",
        "## User Review Themes\nCited replacement. [source:pricing-1]\n",
    )

    assert "Cited replacement. [source:pricing-1]" in updated
    assert "Thin." not in updated

    problem = report_regression_problem(detail, detail, ["review_theme_summary"])

    assert problem is None


def _report_line_issue(*, line_number: int, problem: str) -> QCIssue:
    field_path = f"report_md.line[{line_number}]"
    return QCIssue(
        id=f"issue-line-{line_number}",
        severity="blocker",
        detected_by="text_quality",
        target_agent="writer",
        field_path=field_path,
        problem=problem,
        redo_scope=RedoScope(kind="writer_only", rationale=problem),
    )


def _detail(*, report_md: str) -> RunDetail:
    return RunDetail(
        id="run-writer-repair",
        topic="Cursor vs Copilot pricing",
        status="running",
        execution_mode="real",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        plan=AnalysisPlan(
            topic="Cursor vs Copilot pricing",
            competitors=["Cursor", "Copilot"],
            dimensions=["pricing", "feature", "persona"],
            competitor_layer="L1",
        ),
        raw_sources=[
            RawSource(
                id="pricing-1",
                competitor="Cursor",
                dimension="pricing",
                source_type="webpage_verified",
                title="Cursor pricing",
                url="https://example.com/cursor-pricing",
                snippet="Cursor pricing is published.",
                content_hash="pricing-1",
                confidence=0.9,
            ),
            RawSource(
                id="feature-1",
                competitor="Copilot",
                dimension="feature",
                source_type="webpage_verified",
                title="Copilot feature",
                url="https://example.com/copilot-feature",
                snippet="Copilot has IDE integration.",
                content_hash="feature-1",
                confidence=0.9,
            ),
        ],
        metrics=RunMetrics(llm_calls=3, source_coverage_rate=1.0, claim_citation_rate=1.0),
        report_md=report_md,
    )


def _protectable_report() -> str:
    return """
# Cursor vs Copilot Direct Battlecard

## Executive Summary
Cursor has stronger pricing transparency, while Copilot has integration breadth.
[source:pricing-1] [source:feature-1]

## Decision Summary
Recommended action: use Cursor's pricing clarity as the initial L1 battlecard point while
keeping Copilot's bundled distribution as the procurement counter-position.
- Do not overstate a winner beyond pricing and workflow evidence; enterprise security proof
still needs direct validation before procurement guidance becomes firm. [source:feature-1]
- Immediate next move: collect one current trust-center source and one buyer-objection source
so sales can separate pricing clarity from rollout risk. [source:pricing-1]
[source:pricing-1] [source:feature-1]

## Competitive Findings
- Pricing: Cursor has clearer standalone pricing evidence, which makes the sales response easier.
[source:pricing-1]
- Feature: Copilot has broad IDE integration evidence, which gives it a defensible adoption path.
[source:feature-1]
- Persona: developer evaluators can understand Cursor's focused value faster, while platform
buyers may still prefer Copilot's Microsoft adjacency for governance and procurement continuity.
[source:pricing-1] [source:feature-1]

## Competitor Deep Dives
- Cursor wins on pricing clarity and focused workflow; watchouts remain procurement and
security proof.
[source:pricing-1]
- Copilot wins on distribution and IDE breadth; watchouts remain direct packaging comparison.
[source:feature-1]
- Cursor weakness: the available evidence does not yet prove enterprise rollout readiness, so
sales should keep security claims qualified until a verified trust source is collected.
[source:feature-1]
- Copilot weakness: bundled familiarity can obscure standalone value comparison, so evaluators
need pricing and onboarding proof before accepting it as the default choice. [source:pricing-1]

## User Review Themes
User review themes show Cursor is easier to explain during procurement, while Copilot benefits from
existing Microsoft workflow familiarity. [source:pricing-1]
- Customer theme: pricing clarity supports fast evaluation. [source:pricing-1]
- Adoption blocker: security review and procurement packaging still need deeper evidence.
[source:feature-1]

## SWOT Analysis
- Strengths: Cursor has pricing clarity that sales can explain quickly. [source:pricing-1]
- Weaknesses: Enterprise procurement proof remains incomplete. [source:feature-1]
- Opportunities: Buyer education can focus on standalone value. [source:pricing-1]
- Threats: Copilot can defend through Microsoft distribution. [source:feature-1]

## Battlecard
Sales should use pricing transparency and switching objections as the first battlecard line.
[source:pricing-1] [source:feature-1]
- Response guidance: lead with Cursor's transparent evaluation path when buyers ask for direct
developer workflow value. [source:pricing-1]
- Objection handling: acknowledge Copilot's Microsoft distribution advantage, then ask whether
the buyer needs bundled familiarity or a focused coding workflow proof. [source:feature-1]
- Follow-up: request security, onboarding, and procurement evidence before making an absolute
replacement claim. [source:pricing-1] [source:feature-1]

## Source Quality & Coverage
The run uses verified pages for both target competitors. [source:pricing-1] [source:feature-1]

## User Research Evidence
Review and buyer-feedback inputs are directional demand evidence. [source:pricing-1]

## Scenario QA Checklist
- Scenario: l1_pricing_pack; layer: L1; recommended dimensions: pricing, feature, persona.

## Claim Validation & Evidence Risk
No unresolved blocker claims were detected, but security and procurement claims remain gated.
[source:pricing-1] [source:feature-1]

## Evidence Appendix
- pricing-1: Cursor pricing [source:pricing-1]
- feature-1: Copilot feature [source:feature-1]
""".strip()
