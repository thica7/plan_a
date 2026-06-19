# Writer Redo Tiered Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a tiered `writer_only` redo path that preserves good reports, repairs local or section-level defects, and only performs full rewrites when the previous report is not worth protecting or upstream facts changed.

**Architecture:** Keep the public five-level `RedoScope.kind` contract unchanged. Add a focused writer repair helper module that classifies writer redo into `line`, `section`, or `full`, then wire the existing writer node to consume `RedoRequestPayload` and apply the selected repair mode. Use existing `compare_run_quality()` metrics for protectability and add section-level anti-regression checks before accepting full rewrites.

**Tech Stack:** Python 3.12, Pydantic models, LangGraph orchestration, pytest, ruff, existing conda environment at `D:\Anaconda\envs\bd-competiscope-v2\python.exe`.

---

## File Structure

- Create `backend/packages/agents/writer/repair.py`
  - Owns writer repair planning, report section parsing, line repair, section replacement, and anti-regression checks.
  - Depends on public DTOs and `compare_run_quality()`, not on `RunService`.
- Modify `backend/packages/agents/writer/logic.py`
  - Consumes queued writer `redo_request` messages.
  - Runs line repair, section repair, or full writer flow according to `WriterRepairPlan`.
  - Emits repair-mode metadata in writer events and agent messages.
- Modify `backend/packages/schema/messages.py`
  - Allows `MarkdownReport` payloads to carry repair metadata without changing the report schema.
- Add `backend/tests/unit/test_writer_repair.py`
  - Fast unit tests for repair classification, line repair, section replacement, and anti-regression helpers.
- Modify `backend/tests/unit/test_run_service.py`
  - Service-level tests proving writer line repair avoids LLM calls, section repair preserves unrelated sections, full rewrite is used for poor drafts, and anti-regression rejects collapsed rewrites.
- Optionally modify `backend/tests/unit/test_report_quality.py`
  - Only if the repair helper needs one small public metric utility in `report_quality.py`; prefer not to change this file.

## Precondition

The Markdown table separator false positive is already fixed in commit `ac54e432`. Do not reimplement that fix. Keep the existing test `test_qa_does_not_flag_markdown_table_separators_as_text_noise` passing.

---

### Task 1: Writer Repair Helper

**Files:**
- Create: `backend/packages/agents/writer/repair.py`
- Create: `backend/tests/unit/test_writer_repair.py`

- [ ] **Step 1: Write failing unit tests for repair planning and report patch helpers**

Create `backend/tests/unit/test_writer_repair.py` with these tests. The helper functions build a protectable report with substantive core sections, a poor report, line-level QA issues, and section-level QA issues.

```python
from __future__ import annotations

from datetime import datetime

from packages.agents.writer.repair import (
    apply_line_repair,
    build_writer_repair_plan,
    report_regression_problem,
    replace_markdown_section,
)
from packages.schema.api_dto import RunDetail
from packages.schema.models import AnalysisPlan, QCIssue, RawSource, RedoScope, RunMetrics


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


def test_report_regression_detects_collapsed_review_section() -> None:
    previous = _detail(report_md=_protectable_report())
    candidate = _detail(
        report_md=_protectable_report().replace(
            (
                "User review themes show Cursor is easier to explain during procurement, "
                "while Copilot benefits from existing Microsoft workflow familiarity. "
                "[source:pricing-1]\n"
                "- Customer theme: pricing clarity supports fast evaluation. [source:pricing-1]\n"
                "- Adoption blocker: security review and procurement packaging still need "
                "deeper evidence. [source:feature-1]"
            ),
            "Existing evidence does not provide verified user reviews.",
        )
    )

    problem = report_regression_problem(previous, candidate, protected_sections=["review_theme_summary"])

    assert problem is not None
    assert "review_theme_summary" in problem


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
[source:pricing-1] [source:feature-1]

## Competitive Findings
- Pricing: Cursor has clearer standalone pricing evidence, which makes the sales response easier.
[source:pricing-1]
- Feature: Copilot has broad IDE integration evidence, which gives it a defensible adoption path.
[source:feature-1]

## Competitor Deep Dives
- Cursor wins on pricing clarity and focused workflow; watchouts remain procurement and security proof.
[source:pricing-1]
- Copilot wins on distribution and IDE breadth; watchouts remain direct packaging comparison.
[source:feature-1]

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
```

- [ ] **Step 2: Run tests to verify they fail for missing helper module**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_writer_repair.py -q
```

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'packages.agents.writer.repair'`.

- [ ] **Step 3: Implement the minimal repair helper module**

Create `backend/packages/agents/writer/repair.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from packages.business_intel.report_quality import compare_run_quality
from packages.i18n.language import report_label
from packages.research.evidence.text import publishable_text_noise_problem
from packages.schema.api_dto import RunDetail
from packages.schema.models import QCIssue

WriterRepairMode = Literal["line", "section", "full"]

LINE_REPAIR_MAX_ISSUES = 5
PROTECTABLE_MINIMUMS = {
    "report_structure_score": 0.7,
    "decision_summary_section_score": 1.0,
    "competitive_findings_section_score": 1.0,
    "competitor_deep_dive_section_score": 1.0,
    "layer_analysis_section_score": 1.0,
    "core_analysis_depth_score": 0.6,
    "citation_validity_rate": 0.6,
}
SECTION_REPAIR_HINTS: dict[str, tuple[str, ...]] = {
    "review_theme_summary": ("review", "user review", "review_theme", "用户评价", "user_research"),
    "swot_analysis": ("swot", "strength", "weakness", "opportunit", "threat", "SWOT"),
    "competitor_deep_dives": ("competitor deep", "deep_dive", "竞品深挖"),
    "battlecard": ("battlecard", "战报", "response guidance"),
    "claim_risk": ("claim risk", "claim_validation", "evidence risk"),
    "rag_gap_fill": ("rag", "gap fill", "retrieval"),
}


@dataclass(frozen=True)
class WriterRepairPlan:
    mode: WriterRepairMode
    reason: str
    previous_report_protectable: bool
    line_numbers: list[int] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)
    anti_regression_required: bool = False


@dataclass(frozen=True)
class MarkdownSection:
    heading: str
    body: str
    start: int
    end: int


def build_writer_repair_plan(
    detail: RunDetail,
    issues: list[QCIssue],
    *,
    upstream_data_changed: bool,
) -> WriterRepairPlan:
    protectable = _previous_report_is_protectable(detail)
    if upstream_data_changed:
        return WriterRepairPlan(
            mode="full",
            reason="upstream data changed; full rewrite allowed with anti-regression guard",
            previous_report_protectable=protectable,
            anti_regression_required=protectable,
        )
    if not protectable:
        return WriterRepairPlan(
            mode="full",
            reason="report is not protectable; full rewrite required",
            previous_report_protectable=False,
            anti_regression_required=False,
        )
    line_numbers = _report_line_numbers(issues)
    if line_numbers and len(line_numbers) <= LINE_REPAIR_MAX_ISSUES and len(line_numbers) == len(issues):
        return WriterRepairPlan(
            mode="line",
            reason="small set of report line findings on protectable report",
            previous_report_protectable=True,
            line_numbers=line_numbers,
            anti_regression_required=False,
        )
    sections = _target_sections(issues)
    if sections and len(sections) <= 2:
        return WriterRepairPlan(
            mode="section",
            reason="small set of section findings on protectable report",
            previous_report_protectable=True,
            sections=sections,
            anti_regression_required=True,
        )
    return WriterRepairPlan(
        mode="full",
        reason="writer findings are broad or unmapped; full rewrite required",
        previous_report_protectable=True,
        anti_regression_required=True,
    )


def apply_line_repair(markdown: str, issues: list[QCIssue]) -> str:
    target_lines = set(_report_line_numbers(issues))
    if not target_lines:
        return markdown
    repaired_lines: list[str] = []
    for line_number, line in enumerate(markdown.splitlines(), start=1):
        if line_number in target_lines and publishable_text_noise_problem(line):
            continue
        repaired_lines.append(line)
    return "\n".join(repaired_lines).strip()


def replace_markdown_section(
    markdown: str,
    *,
    target_section: str,
    output_language: str,
    replacement_markdown: str,
) -> str:
    sections = _sections(markdown)
    aliases = _section_aliases(target_section, output_language)
    target = next(
        (section for section in sections if _heading_matches(section.heading, aliases)),
        None,
    )
    replacement = _normalize_section_replacement(replacement_markdown)
    if target is None:
        return f"{markdown.rstrip()}\n\n{replacement}".strip()
    return f"{markdown[: target.start].rstrip()}\n\n{replacement}\n\n{markdown[target.end :].lstrip()}".strip()


def report_regression_problem(
    previous: RunDetail,
    candidate: RunDetail,
    *,
    protected_sections: list[str],
) -> str | None:
    comparison = compare_run_quality(candidate, baseline=previous)
    if comparison.regression_gate_status == "fail":
        return "; ".join(comparison.regression_gate_reasons)
    for section_key in protected_sections:
        previous_chars = _section_content_chars(previous.report_md, section_key, previous.output_language)
        candidate_chars = _section_content_chars(candidate.report_md, section_key, candidate.output_language)
        if previous_chars >= 180 and candidate_chars < max(120, previous_chars * 0.55):
            return (
                f"{section_key} section regressed from {previous_chars} to "
                f"{candidate_chars} substantive characters"
            )
    return None


def _previous_report_is_protectable(detail: RunDetail) -> bool:
    if not detail.report_md.strip():
        return False
    comparison = compare_run_quality(detail)
    metric_by_name = {metric.name: metric.target_value for metric in comparison.metrics}
    if comparison.report_quality_signal:
        return True
    return all(metric_by_name.get(name, 0.0) >= minimum for name, minimum in PROTECTABLE_MINIMUMS.items())


def _report_line_numbers(issues: list[QCIssue]) -> list[int]:
    numbers: list[int] = []
    for issue in issues:
        match = re.fullmatch(r"report_md\.line\[(\d+)\]", issue.field_path)
        if match:
            numbers.append(int(match.group(1)))
    return sorted(set(numbers))


def _target_sections(issues: list[QCIssue]) -> list[str]:
    sections: list[str] = []
    for issue in issues:
        haystack = " ".join(
            value
            for value in [
                issue.field_path,
                issue.problem,
                issue.target_subagent or "",
                issue.redo_scope.target_subagent or "",
            ]
            if value
        ).casefold()
        for section_key, hints in SECTION_REPAIR_HINTS.items():
            if any(hint.casefold() in haystack for hint in hints) and section_key not in sections:
                sections.append(section_key)
    return sections


def _sections(markdown: str) -> list[MarkdownSection]:
    matches = list(re.finditer(r"^\s*##(?!#)\s+(.+?)\s*#*\s*$", markdown, flags=re.MULTILINE))
    sections: list[MarkdownSection] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        sections.append(
            MarkdownSection(
                heading=match.group(1).strip(),
                body=markdown[match.end() : end].strip(),
                start=match.start(),
                end=end,
            )
        )
    return sections


def _section_aliases(section_key: str, output_language: str) -> tuple[str, ...]:
    aliases = [section_key.replace("_", " ")]
    label_key = "battlecard" if section_key == "battlecard" else section_key
    for language in (output_language, "en-US", "zh-CN"):
        try:
            aliases.append(report_label(language, label_key))
        except KeyError:
            continue
    return tuple(dict.fromkeys(aliases))


def _heading_matches(heading: str, aliases: tuple[str, ...]) -> bool:
    normalized = _normalize_heading(heading)
    return any(_normalize_heading(alias) in normalized for alias in aliases)


def _normalize_heading(value: str) -> str:
    value = re.sub(r"^(?:\d+(?:\.\d+)*|[ivxlcdm]+)[\.)]\s*", "", value.strip(), flags=re.I)
    return re.sub(r"\s+", " ", value).casefold()


def _normalize_section_replacement(markdown: str) -> str:
    return markdown.strip()


def _section_content_chars(markdown: str, section_key: str, output_language: str) -> int:
    aliases = _section_aliases(section_key, output_language)
    section = next(
        (item for item in _sections(markdown) if _heading_matches(item.heading, aliases)),
        None,
    )
    if section is None:
        return 0
    chars = 0
    for line in section.body.splitlines():
        cleaned = re.sub(r"\[source:[^\]]+\]", "", line, flags=re.I)
        cleaned = re.sub(r"^[\s|*\-:]+|[\s|]+$", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if cleaned and re.search(r"\w", cleaned):
            chars += len(cleaned)
    return chars
```

- [ ] **Step 4: Run tests to verify the helper passes**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_writer_repair.py -q
```

Expected: PASS for all tests in `test_writer_repair.py`.

- [ ] **Step 5: Commit Task 1**

Run:

```powershell
git add -- backend/packages/agents/writer/repair.py backend/tests/unit/test_writer_repair.py
git commit -m "feat: add writer redo repair planner"
```

---

### Task 2: Writer Line Repair Integration

**Files:**
- Modify: `backend/packages/agents/writer/logic.py`
- Modify: `backend/packages/schema/messages.py`
- Modify: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Write failing service test for line repair avoiding LLM rewrite**

Add this test near the existing writer tests in `backend/tests/unit/test_run_service.py`:

```python
@pytest.mark.asyncio
async def test_writer_line_repair_preserves_protectable_report_without_llm() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            writer_timeout_seconds=5,
        ),
    )
    llm_calls = 0

    async def fake_complete_text(*, system: str, user: str) -> str:  # noqa: ARG001
        nonlocal llm_calls
        llm_calls += 1
        return "# Replacement should not be used"

    service._llm.complete_text = fake_complete_text  # type: ignore[method-assign]
    detail = await service.create_run(
        RunCreateRequest(
            topic="Writer line repair",
            competitors=["Cursor", "Copilot"],
            dimensions=["pricing", "feature", "persona"],
            execution_mode="real",
            output_language="en-US",
        )
    )
    record = service._runs[detail.id]
    record.detail.raw_sources = _writer_repair_sources()
    record.detail.report_md = _writer_repair_protectable_report().replace(
        "## SWOT Analysis",
        "bad line \ufffd\n\n## SWOT Analysis",
    )
    issue = QCIssue(
        id="issue-line-noise",
        severity="blocker",
        detected_by="text_quality",
        target_agent="writer",
        field_path="report_md.line[26]",
        problem="Report line 26 contains non-publishable text noise.",
        redo_scope=RedoScope(kind="writer_only", rationale="repair noisy report line"),
    )
    record.detail.qa_findings = [issue]
    service._append_agent_message(
        record,
        from_agent="qa",
        to_agent="writer",
        message_type="redo_request",
        payload_schema="RedoRequestPayload",
        payload={
            "redo_scope": issue.redo_scope.model_dump(mode="json"),
            "issues": [issue.model_dump(mode="json")],
            "issue_ids": [issue.id],
        },
    )

    await service._real_writer_step(record)

    assert llm_calls == 0
    assert "bad line" not in record.detail.report_md
    assert "## User Review Themes" in record.detail.report_md
    assert "## SWOT Analysis" in record.detail.report_md
    assert record.detail.agent_messages[-1].payload["writer_mode"] == "writer repair: line"
    assert record.detail.agent_messages[-1].payload["writer_repair_mode"] == "line"
```

Also add helper functions near existing test helpers:

```python
def _writer_repair_sources() -> list[RawSource]:
    return [
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
    ]


def _writer_repair_protectable_report() -> str:
    return """# Cursor vs Copilot Direct Battlecard

## Executive Summary
Cursor has stronger pricing transparency, while Copilot has integration breadth.
[source:pricing-1] [source:feature-1]

## Decision Summary
Recommended action: use Cursor's pricing clarity as the initial L1 battlecard point while
keeping Copilot's bundled distribution as the procurement counter-position.
[source:pricing-1] [source:feature-1]

## Competitive Findings
- Pricing: Cursor has clearer standalone pricing evidence, which makes the sales response easier.
[source:pricing-1]
- Feature: Copilot has broad IDE integration evidence, which gives it a defensible adoption path.
[source:feature-1]

## Competitor Deep Dives
- Cursor wins on pricing clarity and focused workflow; watchouts remain procurement and security proof.
[source:pricing-1]
- Copilot wins on distribution and IDE breadth; watchouts remain direct packaging comparison.
[source:feature-1]

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
"""
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py::test_writer_line_repair_preserves_protectable_report_without_llm -q
```

Expected: FAIL because `_real_writer_step()` still ignores writer `redo_request` messages and performs a normal LLM call.

- [ ] **Step 3: Extend MarkdownReport payload schema for repair metadata**

Modify `backend/packages/schema/messages.py`:

```python
class MarkdownReportMessagePayload(_MessagePayload):
    report_md: str
    writer_mode: str = ""
    error: str | None = None
    writer_repair_mode: Literal["none", "line", "section", "full"] = "none"
    writer_repair_sections: list[str] = Field(default_factory=list)
    writer_repair_decision: str = ""
    anti_regression_reason: str | None = None
    previous_report_protected: bool = False
```

- [ ] **Step 4: Wire line repair into `_real_writer_step()`**

Modify `backend/packages/agents/writer/logic.py` imports:

```python
from packages.agents.writer.repair import (
    apply_line_repair,
    build_writer_repair_plan,
    report_regression_problem,
    replace_markdown_section,
)
```

Inside `_real_writer_step()`, consume redo requests and compute the plan before the LLM call:

```python
        redo_messages = self._consume_queued_agent_messages(
            record,
            to_agent="writer",
            consumer_agent="writer",
            message_types={"redo_request"},
        )
        redo_issues = [
            issue
            for message in redo_messages
            for issue in message.payload.get("issues", [])
            if isinstance(issue, QCIssue)
        ]
        pending = record.pending_graph_redo
        upstream_data_changed = bool(
            pending is not None and pending.stage in {"collector", "analyst", "comparator", "full"}
        )
        repair_plan = build_writer_repair_plan(
            detail,
            redo_issues,
            upstream_data_changed=upstream_data_changed,
        )
```

Because Pydantic validation may store issues as dictionaries, normalize the list with:

```python
        redo_issues = []
        for message in redo_messages:
            for item in message.payload.get("issues", []):
                redo_issues.append(item if isinstance(item, QCIssue) else QCIssue.model_validate(item))
```

Before the full writer call, short-circuit line repair:

```python
        repair_metadata = {
            "writer_repair_mode": "none",
            "writer_repair_sections": [],
            "writer_repair_decision": "",
            "anti_regression_reason": None,
            "previous_report_protected": False,
        }
        if previous_report.strip() and redo_issues and repair_plan.mode == "line":
            repaired = apply_line_repair(previous_report, redo_issues)
            detail.report_md = self._harden_report_markdown(detail, repaired)
            writer_mode = "writer repair: line"
            repair_metadata = {
                "writer_repair_mode": "line",
                "writer_repair_sections": [],
                "writer_repair_decision": repair_plan.reason,
                "anti_regression_reason": None,
                "previous_report_protected": repair_plan.previous_report_protectable,
            }
            writer_error = None
        else:
            # existing full writer try/except block remains here in Task 2
```

Wrap the existing full writer `try/except` block in the `else:` branch. Add `**repair_metadata` to the writer `MarkdownReport` payload and the `report_updated` event payload.

- [ ] **Step 5: Run focused tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py::test_writer_line_repair_preserves_protectable_report_without_llm backend\tests\unit\test_run_service.py::test_writer_timeout_preserves_previous_report_and_metrics -q
```

Expected: PASS. The timeout test verifies the existing fallback path still works.

- [ ] **Step 6: Commit Task 2**

Run:

```powershell
git add -- backend/packages/agents/writer/logic.py backend/packages/schema/messages.py backend/tests/unit/test_run_service.py
git commit -m "feat: apply writer line repair mode"
```

---

### Task 3: Writer Section Repair Integration

**Files:**
- Modify: `backend/packages/agents/writer/logic.py`
- Modify: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Write failing service test for section repair preserving unrelated sections**

Add this test near `test_writer_line_repair_preserves_protectable_report_without_llm`:

```python
@pytest.mark.asyncio
async def test_writer_section_repair_replaces_only_target_section() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            writer_timeout_seconds=5,
        ),
    )
    captured_user = ""

    async def fake_complete_text(*, system: str, user: str) -> str:  # noqa: ARG001
        nonlocal captured_user
        captured_user = user
        return (
            "## User Review Themes\n"
            "- Praise: Cursor is easier to explain in initial evaluation because pricing is direct. "
            "[source:pricing-1]\n"
            "- Blocker: Copilot can defend with existing Microsoft workflow familiarity. "
            "[source:feature-1]\n"
        )

    service._llm.complete_text = fake_complete_text  # type: ignore[method-assign]
    detail = await service.create_run(
        RunCreateRequest(
            topic="Writer section repair",
            competitors=["Cursor", "Copilot"],
            dimensions=["pricing", "feature", "persona"],
            execution_mode="real",
            output_language="en-US",
        )
    )
    record = service._runs[detail.id]
    record.detail.raw_sources = _writer_repair_sources()
    record.detail.report_md = _writer_repair_protectable_report().replace(
        (
            "User review themes show Cursor is easier to explain during procurement, while Copilot "
            "benefits from\nexisting Microsoft workflow familiarity. [source:pricing-1]\n"
            "- Customer theme: pricing clarity supports fast evaluation. [source:pricing-1]\n"
            "- Adoption blocker: security review and procurement packaging still need deeper evidence.\n"
            "[source:feature-1]"
        ),
        "Existing evidence does not provide verified user reviews.",
    )
    issue = QCIssue(
        id="issue-review-thin",
        severity="blocker",
        detected_by="schema",
        target_agent="writer",
        target_subagent="review_theme_summary",
        field_path="report_md.section[review_theme_summary]",
        problem="User Review Themes section is too thin.",
        redo_scope=RedoScope(kind="writer_only", target_subagent="review_theme_summary", rationale="repair review section"),
    )
    service._append_agent_message(
        record,
        from_agent="qa",
        to_agent="writer",
        message_type="redo_request",
        payload_schema="RedoRequestPayload",
        payload={
            "redo_scope": issue.redo_scope.model_dump(mode="json"),
            "issues": [issue.model_dump(mode="json")],
            "issue_ids": [issue.id],
        },
    )

    await service._real_writer_step(record)

    assert "Repair only these sections: review_theme_summary" in captured_user
    assert "## Executive Summary" in record.detail.report_md
    assert "## SWOT Analysis" in record.detail.report_md
    assert "- Praise: Cursor is easier to explain" in record.detail.report_md
    assert "Existing evidence does not provide verified user reviews." not in record.detail.report_md
    assert record.detail.agent_messages[-1].payload["writer_mode"] == "writer repair: section"
    assert record.detail.agent_messages[-1].payload["writer_repair_mode"] == "section"
    assert record.detail.agent_messages[-1].payload["writer_repair_sections"] == ["review_theme_summary"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py::test_writer_section_repair_replaces_only_target_section -q
```

Expected: FAIL because `repair_plan.mode == "section"` is not wired and the full writer path replaces the whole report.

- [ ] **Step 3: Implement section repair helper methods in `WriterAgentMixin`**

Add these methods to `backend/packages/agents/writer/logic.py` near `_real_writer_step()`:

```python
    async def _writer_section_repair_markdown(
        self,
        record: RunRecord,
        *,
        sections: list[str],
        previous_report: str,
    ) -> str:
        detail = record.detail
        sections_text = ", ".join(sections)
        repaired_section = await self._trace_llm_text(
            record,
            agent="writer",
            subagent=None,
            name="report_section_repair",
            system=(
                "You are repairing selected sections of an existing markdown competitive "
                "intelligence report. Return only the requested section markdown. Preserve "
                "source citation syntax using existing [source:ID] tokens. Do not rewrite "
                "unrequested sections."
            ),
            user=(
                f"Topic: {detail.topic}\n"
                f"Competitors: {', '.join(detail.plan.competitors)}\n"
                f"Dimensions: {', '.join(detail.plan.dimensions)}\n"
                f"Repair only these sections: {sections_text}\n"
                f"Writer Context JSON: {json.dumps(self._writer_context_package(detail), ensure_ascii=False)}\n\n"
                f"Previous Report:\n{previous_report}\n"
            ),
        )
        updated = previous_report
        for section in sections:
            updated = replace_markdown_section(
                updated,
                target_section=section,
                output_language=detail.output_language,
                replacement_markdown=repaired_section,
            )
        return self._harden_report_markdown(detail, updated)
```

- [ ] **Step 4: Wire section mode in `_real_writer_step()`**

Add an `elif` after line repair and before full writer call:

```python
        elif previous_report.strip() and redo_issues and repair_plan.mode == "section":
            detail.report_md = await asyncio.wait_for(
                self._writer_section_repair_markdown(
                    record,
                    sections=repair_plan.sections,
                    previous_report=previous_report,
                ),
                timeout=timeout_seconds,
            )
            writer_mode = "writer repair: section"
            writer_error = None
            repair_metadata = {
                "writer_repair_mode": "section",
                "writer_repair_sections": list(repair_plan.sections),
                "writer_repair_decision": repair_plan.reason,
                "anti_regression_reason": None,
                "previous_report_protected": repair_plan.previous_report_protectable,
            }
```

Ensure `timeout_seconds` is defined before line and section branches:

```python
        timeout_seconds = max(0.05, float(self._settings.writer_timeout_seconds))
```

Keep the existing writer timeout fallback for section repair exceptions by letting the current `except TimeoutError` and `except Exception` blocks preserve `previous_report`.

- [ ] **Step 5: Run focused tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py::test_writer_section_repair_replaces_only_target_section backend\tests\unit\test_run_service.py::test_writer_line_repair_preserves_protectable_report_without_llm backend\tests\unit\test_writer_repair.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 3**

Run:

```powershell
git add -- backend/packages/agents/writer/logic.py backend/tests/unit/test_run_service.py
git commit -m "feat: apply writer section repair mode"
```

---

### Task 4: Full Rewrite Anti-Regression Guard

**Files:**
- Modify: `backend/packages/agents/writer/logic.py`
- Modify: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Write failing test for rejecting collapsed full rewrite**

Add this test near the writer repair tests:

```python
@pytest.mark.asyncio
async def test_writer_full_rewrite_rejects_collapsed_review_section_when_previous_is_protectable() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            writer_timeout_seconds=5,
        ),
    )

    async def fake_complete_text(*, system: str, user: str) -> str:  # noqa: ARG001
        return _writer_repair_protectable_report().replace(
            (
                "User review themes show Cursor is easier to explain during procurement, while Copilot "
                "benefits from\nexisting Microsoft workflow familiarity. [source:pricing-1]\n"
                "- Customer theme: pricing clarity supports fast evaluation. [source:pricing-1]\n"
                "- Adoption blocker: security review and procurement packaging still need deeper evidence.\n"
                "[source:feature-1]"
            ),
            "Existing evidence does not provide verified user reviews.",
        )

    service._llm.complete_text = fake_complete_text  # type: ignore[method-assign]
    detail = await service.create_run(
        RunCreateRequest(
            topic="Writer full rewrite guard",
            competitors=["Cursor", "Copilot"],
            dimensions=["pricing", "feature", "persona"],
            execution_mode="real",
            output_language="en-US",
        )
    )
    record = service._runs[detail.id]
    record.detail.raw_sources = _writer_repair_sources()
    record.detail.report_md = _writer_repair_protectable_report()
    issue = QCIssue(
        id="issue-broad-writer",
        severity="blocker",
        detected_by="schema",
        target_agent="writer",
        field_path="report_md",
        problem="Broad writer refresh requested.",
        redo_scope=RedoScope(kind="writer_only", rationale="refresh writer output"),
    )
    service._append_agent_message(
        record,
        from_agent="qa",
        to_agent="writer",
        message_type="redo_request",
        payload_schema="RedoRequestPayload",
        payload={
            "redo_scope": issue.redo_scope.model_dump(mode="json"),
            "issues": [issue.model_dump(mode="json")],
            "issue_ids": [issue.id],
        },
    )

    await service._real_writer_step(record)

    assert "Existing evidence does not provide verified user reviews." not in record.detail.report_md
    assert "- Customer theme: pricing clarity supports fast evaluation." in record.detail.report_md
    assert record.detail.agent_messages[-1].payload["writer_mode"] == "preserved previous report after writer anti-regression"
    assert record.detail.agent_messages[-1].payload["writer_repair_mode"] == "full"
    assert record.detail.agent_messages[-1].payload["anti_regression_reason"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py::test_writer_full_rewrite_rejects_collapsed_review_section_when_previous_is_protectable -q
```

Expected: FAIL because the successful but weaker full rewrite is accepted.

- [ ] **Step 3: Add anti-regression check after full writer output**

In `backend/packages/agents/writer/logic.py`, after hardening the full writer candidate, compare it to the previous report when `repair_plan.anti_regression_required` is true:

```python
            hardened_report = self._harden_report_markdown(detail, report_md)
            if previous_report.strip() and repair_plan.anti_regression_required:
                previous_detail = detail.model_copy(update={"report_md": previous_report})
                candidate_detail = detail.model_copy(update={"report_md": hardened_report})
                regression = report_regression_problem(
                    previous_detail,
                    candidate_detail,
                    protected_sections=repair_plan.sections
                    or ["review_theme_summary", "swot_analysis", "competitor_deep_dives", self._layer_section_label_key(detail)],
                )
                if regression:
                    detail.report_md = previous_report
                    writer_mode = "preserved previous report after writer anti-regression"
                    repair_metadata = {
                        "writer_repair_mode": "full",
                        "writer_repair_sections": list(repair_plan.sections),
                        "writer_repair_decision": repair_plan.reason,
                        "anti_regression_reason": regression,
                        "previous_report_protected": repair_plan.previous_report_protectable,
                    }
                else:
                    detail.report_md = hardened_report
                    repair_metadata = {
                        "writer_repair_mode": "full" if redo_issues else "none",
                        "writer_repair_sections": list(repair_plan.sections),
                        "writer_repair_decision": repair_plan.reason if redo_issues else "",
                        "anti_regression_reason": None,
                        "previous_report_protected": repair_plan.previous_report_protectable,
                    }
            else:
                detail.report_md = hardened_report
```

Do not run anti-regression for an empty or unprotectable previous report. Those cases must keep the normal full rewrite behavior.

- [ ] **Step 4: Run focused tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py::test_writer_full_rewrite_rejects_collapsed_review_section_when_previous_is_protectable backend\tests\unit\test_run_service.py::test_writer_budget_timeout_generates_deterministic_report backend\tests\unit\test_writer_repair.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 4**

Run:

```powershell
git add -- backend/packages/agents/writer/logic.py backend/tests/unit/test_run_service.py
git commit -m "feat: guard writer rewrites from report thinning"
```

---

### Task 5: Poor Drafts And Upstream-Changed Behavior

**Files:**
- Modify: `backend/tests/unit/test_run_service.py`
- Modify: `backend/packages/agents/writer/logic.py` only if tests reveal missing upstream detection
- Modify: `backend/packages/agents/writer/repair.py` only if classifier thresholds need a small adjustment

- [ ] **Step 1: Write failing test that poor previous drafts still use full rewrite**

Add:

```python
@pytest.mark.asyncio
async def test_writer_poor_previous_report_allows_full_rewrite() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            writer_timeout_seconds=5,
        ),
    )

    async def fake_complete_text(*, system: str, user: str) -> str:  # noqa: ARG001
        return _writer_repair_protectable_report()

    service._llm.complete_text = fake_complete_text  # type: ignore[method-assign]
    detail = await service.create_run(
        RunCreateRequest(
            topic="Writer poor draft rewrite",
            competitors=["Cursor", "Copilot"],
            dimensions=["pricing", "feature", "persona"],
            execution_mode="real",
            output_language="en-US",
        )
    )
    record = service._runs[detail.id]
    record.detail.raw_sources = _writer_repair_sources()
    record.detail.report_md = "# Report\n\nbad line \ufffd"
    issue = QCIssue(
        id="issue-poor-line",
        severity="blocker",
        detected_by="text_quality",
        target_agent="writer",
        field_path="report_md.line[3]",
        problem="Report line 3 contains non-publishable text noise.",
        redo_scope=RedoScope(kind="writer_only", rationale="repair poor report"),
    )
    service._append_agent_message(
        record,
        from_agent="qa",
        to_agent="writer",
        message_type="redo_request",
        payload_schema="RedoRequestPayload",
        payload={
            "redo_scope": issue.redo_scope.model_dump(mode="json"),
            "issues": [issue.model_dump(mode="json")],
            "issue_ids": [issue.id],
        },
    )

    await service._real_writer_step(record)

    assert "bad line" not in record.detail.report_md
    assert "## Decision Summary" in record.detail.report_md
    assert record.detail.agent_messages[-1].payload["writer_repair_mode"] == "full"
    assert record.detail.agent_messages[-1].payload["previous_report_protected"] is False
```

- [ ] **Step 2: Write test that upstream data changes allow full rewrite with metadata**

Add:

```python
@pytest.mark.asyncio
async def test_writer_upstream_changed_allows_full_rewrite_with_guard_metadata() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(
            demo_mode=False,
            ark_api_key="key",
            ark_model="model",
            ark_base_url="https://ark.cn-beijing.volces.com/api/v3",
            llm_timeout_seconds=10,
            llm_temperature=0.2,
            writer_timeout_seconds=5,
        ),
    )

    async def fake_complete_text(*, system: str, user: str) -> str:  # noqa: ARG001
        return _writer_repair_protectable_report().replace(
            "Cursor has stronger pricing transparency",
            "Cursor has updated pricing transparency",
        )

    service._llm.complete_text = fake_complete_text  # type: ignore[method-assign]
    detail = await service.create_run(
        RunCreateRequest(
            topic="Writer upstream rewrite",
            competitors=["Cursor", "Copilot"],
            dimensions=["pricing", "feature", "persona"],
            execution_mode="real",
            output_language="en-US",
        )
    )
    record = service._runs[detail.id]
    record.detail.raw_sources = _writer_repair_sources()
    record.detail.report_md = _writer_repair_protectable_report()
    scope = RedoScope(kind="collector", target_subagent="pricing", target_competitor="Cursor", rationale="new pricing evidence")
    record.pending_graph_redo = PendingGraphRedo(
        iteration=1,
        stage="collector",
        redo_scope=scope,
        redo_scopes=[scope],
        before_md=record.detail.report_md,
        issue_ids=["collector-issue"],
        qa_issue_ids_before=["collector-issue"],
        issue_count_before=1,
    )

    await service._real_writer_step(record)

    assert "Cursor has updated pricing transparency" in record.detail.report_md
    assert record.detail.agent_messages[-1].payload["writer_repair_mode"] == "full"
    assert record.detail.agent_messages[-1].payload["previous_report_protected"] is True
```

Ensure `PendingGraphRedo` is imported from `packages.orchestrator.service` in the test file if it is not already imported.

- [ ] **Step 3: Run tests to verify failures**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py::test_writer_poor_previous_report_allows_full_rewrite backend\tests\unit\test_run_service.py::test_writer_upstream_changed_allows_full_rewrite_with_guard_metadata -q
```

Expected: FAIL if full metadata is not set consistently or if upstream-changed detection is missing.

- [ ] **Step 4: Complete upstream detection and metadata consistency**

If Task 4 did not already centralize metadata, add a small helper in `_real_writer_step()`:

```python
        def repair_metadata_for(
            *,
            mode: str,
            decision: str,
            sections: list[str] | None = None,
            anti_regression_reason: str | None = None,
        ) -> dict[str, object]:
            return {
                "writer_repair_mode": mode,
                "writer_repair_sections": list(sections or []),
                "writer_repair_decision": decision,
                "anti_regression_reason": anti_regression_reason,
                "previous_report_protected": repair_plan.previous_report_protectable,
            }
```

Use this helper in line, section, normal full, anti-regression-preserved, timeout, and deterministic fallback branches. For non-redo normal writer calls, keep:

```python
repair_metadata = {
    "writer_repair_mode": "none",
    "writer_repair_sections": [],
    "writer_repair_decision": "",
    "anti_regression_reason": None,
    "previous_report_protected": False,
}
```

- [ ] **Step 5: Run focused tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py::test_writer_poor_previous_report_allows_full_rewrite backend\tests\unit\test_run_service.py::test_writer_upstream_changed_allows_full_rewrite_with_guard_metadata backend\tests\unit\test_writer_repair.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 5**

Run:

```powershell
git add -- backend/packages/agents/writer/logic.py backend/packages/agents/writer/repair.py backend/tests/unit/test_run_service.py
git commit -m "test: cover writer rewrite routing edge cases"
```

---

### Task 6: Regression And Contract Verification

**Files:**
- Modify only if tests reveal necessary small fixes:
  - `backend/packages/agents/writer/logic.py`
  - `backend/packages/agents/writer/repair.py`
  - `backend/packages/schema/messages.py`
  - `backend/tests/unit/test_run_service.py`
  - `backend/tests/unit/test_writer_repair.py`

- [ ] **Step 1: Run writer and quality regression tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_writer_repair.py backend\tests\unit\test_run_service.py backend\tests\unit\test_report_quality.py -q
```

Expected: PASS. If a failure occurs, fix only the smallest behavior related to writer repair or metadata.

- [ ] **Step 2: Run redo route seed tests to preserve five-level RedoScope contract**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_redo_seed_cases.py backend\tests\unit\test_graph_send.py -q
```

Expected: PASS. This confirms no graph-level redo kind was added.

- [ ] **Step 3: Run linter**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m ruff check backend\packages\agents\writer\logic.py backend\packages\agents\writer\repair.py backend\packages\schema\messages.py backend\tests\unit\test_writer_repair.py backend\tests\unit\test_run_service.py
```

Expected: `All checks passed!`

- [ ] **Step 4: Run diff whitespace check**

Run:

```powershell
git diff --check
```

Expected: no output and exit code 0.

- [ ] **Step 5: Inspect final staged scope**

Run:

```powershell
git status --short
git diff --stat
```

Expected: only writer repair, message schema, and unit test files are modified. Existing untracked artifacts under `data/artifacts/`, `outputs/`, and local document exports remain untracked and are not staged.

- [ ] **Step 6: Commit final verification fixes if any**

If Task 6 required small fixes, run:

```powershell
git add -- backend/packages/agents/writer/logic.py backend/packages/agents/writer/repair.py backend/packages/schema/messages.py backend/tests/unit/test_writer_repair.py backend/tests/unit/test_run_service.py
git commit -m "fix: stabilize writer redo repair verification"
```

If Task 6 required no fixes, do not create an empty commit.

---

## Self-Review Checklist

- Spec coverage: line repair, section repair, full rewrite, upstream-changed behavior, anti-regression guard, audit metadata, error handling, and tests are covered by Tasks 1-6.
- Scope: no collector, analyst, comparator, survey/interview, frontend, or graph-level `RedoScope.kind` redesign is included.
- TDD: each behavior task starts with a failing test and focused verification command.
- Type consistency: `WriterRepairPlan.mode` uses `line`, `section`, or `full`; `MarkdownReportMessagePayload.writer_repair_mode` uses `none`, `line`, `section`, or `full`.
- Execution environment: all commands use `D:\Anaconda\envs\bd-competiscope-v2\python.exe`.
