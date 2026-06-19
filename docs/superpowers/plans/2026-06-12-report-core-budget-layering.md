# Report Core Budget Layering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make generated reports spend most of their length on core competitive analysis while keeping evidence, QA, risk, and appendix material concise and secondary.

**Architecture:** Keep a single Markdown report, but make the writer prompt and quality checks treat it as two semantic layers: core analysis and support/audit. Strengthen deterministic quality metrics so thin core sections fail even when support sections are present, then route isolated thin core sections through existing writer section repair.

**Tech Stack:** Python backend, pytest, ruff, existing writer mixin, report quality scoring, writer repair planner. Use `D:\Anaconda\envs\bd-competiscope-v2\python.exe` for all Python commands.

---

## File Structure

- Modify `backend/packages/agents/writer/logic.py`
  - Update the full writer prompt budget from `around 5,500 characters` to `8,500-10,000 characters`.
  - Make `_writer_required_sections()` explicitly emit a core analysis layer followed by a support/audit layer.
  - Keep existing hardening and fallback behavior intact.

- Modify `backend/packages/business_intel/report_quality.py`
  - Add deterministic `core_section_depth_score`.
  - Add deterministic `core_support_balance_score`.
  - Add both metrics to snapshot values, normalized values, metric specs, report quality gating, regression gating, and recommendations.
  - Reuse existing section parsing helpers and localized aliases.

- Modify `backend/packages/agents/writer/repair.py`
  - Extend `SECTION_REPAIR_HINTS` so thin core sections map to section repair, especially Decision Summary, Competitive Findings, User Review Themes, Competitor Deep Dives, SWOT Analysis, and layer-specific sections.

- Modify `backend/tests/unit/test_run_service.py`
  - Update writer prompt contract tests.
  - Add a writer redo test proving a thin core section routes to section repair.

- Modify `backend/tests/unit/test_report_quality.py`
  - Add quality tests for support-heavy/core-thin reports.
  - Add passing quality coverage for substantive core plus concise support.

- Modify `backend/tests/unit/test_writer_repair.py`
  - Add focused section-mapping tests for thin core findings.

---

## Task 1: Writer Prompt Budget And Layer Contract

**Files:**
- Modify: `backend/packages/agents/writer/logic.py`
- Test: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Update the failing prompt test**

Edit `test_writer_uses_compact_context_package_for_llm_prompt` in `backend/tests/unit/test_run_service.py` so the prompt budget assertions read:

```python
    assert "Writer Context JSON:" in captured_user
    assert "around 5,500 characters" not in captured_user
    assert "8,500-10,000 characters" in captured_user
    assert "65-75%" in captured_user
    assert "Core analysis layer" in captured_user
    assert "Support/audit layer" in captured_user
    assert "Competitor KB JSON:" not in captured_user
    assert "Competitor Knowledge Schema JSON:" not in captured_user
    assert len(captured_user) < 16500
    assert captured_user.count("long-context-token") < 80
    assert record.detail.agent_messages[-1].payload["writer_mode"] == "real LLM call"
```

- [ ] **Step 2: Run the prompt test and verify it fails**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py::test_writer_uses_compact_context_package_for_llm_prompt -q
```

Expected: FAIL because the prompt still contains `around 5,500 characters` and does not contain the new budget/layer wording.

- [ ] **Step 3: Update the writer prompt budget**

In `backend/packages/agents/writer/logic.py`, replace the current user prompt ending:

```python
                            f"Required sections:\n{required_sections}\n"
                            "Keep the first draft around 5,500 characters. Spend most of the body "
                            "on cited analysis and implications; keep evidence and QA support "
                            "concise but complete."
```

with:

```python
                            f"Required sections:\n{required_sections}\n"
                            "Target 8,500-10,000 characters for the first draft. Use about "
                            "65-75% of the report on the Core analysis layer: decision summary, "
                            "competitive findings, user review themes, competitor deep dives, "
                            "SWOT, matrix interpretation, and layer-specific implications. Keep "
                            "the Support/audit layer concise and complete; it is the audit trail, "
                            "not the main readout. Prefer deeper cited analysis and decision "
                            "implications over repeated source IDs or QA boilerplate."
```

- [ ] **Step 4: Update `_writer_required_sections()` to name the two layers**

In `backend/packages/agents/writer/logic.py`, replace the final `return "\n".join(...)` block in `_writer_required_sections()` with:

```python
        core_lines = [
            "Core analysis layer (target 65-75% of the report body):",
            *(
                f"{index}. {section}"
                for index, section in enumerate([*analysis_sections, *layer_sections], start=1)
            ),
        ]
        support_lines = [
            "Support/audit layer (concise audit trail after core analysis):",
            *(
                f"{index}. {section}"
                for index, section in enumerate(support_sections, start=1)
            ),
        ]
        return "\n".join([*core_lines, *support_lines])
```

This keeps the same semantic section list but makes the layer split visible to the LLM and future Phase 3 work.

- [ ] **Step 5: Run the focused prompt test and verify it passes**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py::test_writer_uses_compact_context_package_for_llm_prompt -q
```

Expected: PASS.

- [ ] **Step 6: Run ruff for touched files**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m ruff check backend\packages\agents\writer\logic.py backend\tests\unit\test_run_service.py
```

Expected: `All checks passed!`

- [ ] **Step 7: Commit Task 1**

Run:

```powershell
git add backend/packages/agents/writer/logic.py backend/tests/unit/test_run_service.py
git commit -m "feat: rebalance writer report budget"
```

---

## Task 2: Core Depth And Core/Support Balance Metrics

**Files:**
- Modify: `backend/packages/business_intel/report_quality.py`
- Test: `backend/tests/unit/test_report_quality.py`

- [ ] **Step 1: Add failing quality tests**

Append these tests near the existing report quality core-depth tests in `backend/tests/unit/test_report_quality.py`:

```python
def test_compare_run_quality_rejects_support_heavy_report_with_thin_core_sections() -> None:
    long_support = (
        "## Evidence Appendix\n"
        + "\n".join(
            f"- source-{index}: supporting audit detail that should not outweigh the core analysis. "
            f"[source:source-{index % 4}]"
            for index in range(40)
        )
    )
    report_md = _structured_report_md()
    report_md = _replace_report_section(
        report_md,
        report_label("en-US", "decision_summary"),
        "## Decision Summary\nCursor is stronger. [source:source-0]",
    )
    report_md = _replace_report_section(
        report_md,
        report_label("en-US", "competitive_findings"),
        "## Competitive Findings\nCursor has a cited edge. [source:source-0]",
    )
    report_md = _replace_report_section(
        report_md,
        report_label("en-US", "competitor_deep_dives"),
        "## Competitor Deep Dives\nCursor is ahead. [source:source-0]",
    )
    report_md = _replace_report_section(
        report_md,
        report_label("en-US", "evidence_appendix"),
        long_support,
    )
    detail = _run_detail(
        run_id="support-heavy-thin-core",
        execution_mode="real",
        source_count=4,
        report_md=report_md,
        metrics=RunMetrics(
            llm_calls=3,
            source_coverage_rate=1.0,
            verified_source_rate=1.0,
            claim_citation_rate=1.0,
        ),
        trace_spans=[
            TraceSpan(
                id="span-llm-1",
                kind="llm",
                agent="writer",
                name="real writer",
                status="ok",
                model="deepseek/deepseek-v4-pro",
                provider="openrouter",
                duration_ms=120,
            )
        ],
    )

    comparison = compare_run_quality(detail)
    metrics = {metric.name: metric for metric in comparison.metrics}
    blockers = {
        name
        for check in comparison.signal_checks
        if check.signal == "report_quality"
        for name in check.blocking_metric_names
    }

    assert metrics["core_section_depth_score"].target_value < 1.0
    assert metrics["core_support_balance_score"].target_value < 1.0
    assert comparison.report_quality_signal is False
    assert "core_section_depth_score" in blockers
    assert "core_support_balance_score" in blockers
    assert any("core section depth" in item for item in comparison.recommendations)


def test_compare_run_quality_accepts_substantive_core_with_concise_support() -> None:
    detail = _run_detail(
        run_id="substantive-core-concise-support",
        execution_mode="real",
        source_count=4,
        report_md=_structured_report_md(),
        metrics=RunMetrics(
            llm_calls=3,
            source_coverage_rate=1.0,
            verified_source_rate=1.0,
            claim_citation_rate=1.0,
        ),
        trace_spans=[
            TraceSpan(
                id="span-llm-1",
                kind="llm",
                agent="writer",
                name="real writer",
                status="ok",
                model="deepseek/deepseek-v4-pro",
                provider="openrouter",
                duration_ms=120,
            )
        ],
    )

    comparison = compare_run_quality(detail)
    metrics = {metric.name: metric for metric in comparison.metrics}

    assert metrics["core_section_depth_score"].target_value == 1.0
    assert metrics["core_support_balance_score"].target_value == 1.0
    assert comparison.report_quality_signal is True
```

Keep the passing test as written. The existing `_structured_report_md()` fixture is the accepted substantive baseline, so the metric thresholds must allow it to pass while rejecting the support-heavy/thin-core case above.

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_report_quality.py::test_compare_run_quality_rejects_support_heavy_report_with_thin_core_sections backend\tests\unit\test_report_quality.py::test_compare_run_quality_accepts_substantive_core_with_concise_support -q
```

Expected: FAIL because `core_section_depth_score` and `core_support_balance_score` do not exist yet.

- [ ] **Step 3: Add snapshot metric values**

In `backend/packages/business_intel/report_quality.py`, add these two entries to the `values` dict in `_snapshot()` immediately after `core_analysis_depth_score`:

```python
        "core_section_depth_score": _core_section_depth_score(detail),
        "core_support_balance_score": _core_support_balance_score(detail.report_md),
```

Add the matching entries to `normalized` immediately after `core_analysis_depth_score`:

```python
        "core_section_depth_score": values["core_section_depth_score"],
        "core_support_balance_score": values["core_support_balance_score"],
```

- [ ] **Step 4: Add metric weights**

In `_metric_specs()`, replace:

```python
        ("report_structure_score", 0.05, "higher_is_better"),
...
        ("core_analysis_depth_score", 0.04, "higher_is_better"),
```

with:

```python
        ("report_structure_score", 0.03, "higher_is_better"),
...
        ("core_analysis_depth_score", 0.02, "higher_is_better"),
        ("core_section_depth_score", 0.02, "higher_is_better"),
        ("core_support_balance_score", 0.02, "higher_is_better"),
```

This keeps the total report-quality weight stable while shifting some weight from generic structure to core substance.

- [ ] **Step 5: Add report-quality gating**

In `report_quality_signal`, add these gates immediately after `core_analysis_depth_score`:

```python
        and values["core_section_depth_score"] >= 1.0
        and values["core_support_balance_score"] >= 1.0
```

In `_signal_checks()`, add both metrics to the report blocker thresholds immediately after `core_analysis_depth_score`:

```python
        ("core_section_depth_score", 1.0),
        ("core_support_balance_score", 1.0),
```

- [ ] **Step 6: Implement the core section depth helper**

Add these helpers near `_core_analysis_depth_score()`:

```python
def _core_section_depth_score(detail: RunDetail) -> float:
    specs = [
        (_report_label_aliases("decision_summary"), 180, 2),
        (_report_label_aliases("competitive_findings"), 320, 3),
        (_review_theme_section_aliases(), 220, 3),
        (
            (
                *_report_label_aliases("competitor_deep_dives"),
                "Competitor Deep Dive",
            ),
            320,
            max(3, len(detail.plan.competitors)),
        ),
        (_swot_section_aliases(), 240, 4),
        (_layer_section_aliases(detail), 240, 3),
    ]
    scores: list[float] = []
    for aliases, min_chars, min_rows in specs:
        section = _find_section_before_support(detail.report_md, aliases)
        if section is None:
            scores.append(0.0)
            continue
        chars, rows = _body_content_summary(section.body)
        score = max(
            min(chars / float(min_chars), 1.0),
            min(rows / float(min_rows), 1.0),
        )
        if aliases == _swot_section_aliases() and not _has_structured_swot_quadrants(section.body):
            score = min(score, 0.5)
        scores.append(score)
    return min(scores) if scores else 0.0
```

- [ ] **Step 7: Implement the core/support balance helper**

Add this helper near `_markdown_before_support_sections()`:

```python
def _core_support_balance_score(markdown: str) -> float:
    report_md = repair_mojibake_text(markdown)
    sections = _report_sections(report_md)
    first_support = _first_support_section(sections)
    if first_support is None:
        core_markdown = report_md
        support_markdown = ""
    else:
        core_markdown = report_md[: first_support.start]
        support_markdown = report_md[first_support.start :]
    core_chars, core_rows = _body_content_summary(core_markdown)
    support_chars, support_rows = _body_content_summary(support_markdown)
    core_units = core_chars + core_rows * 60
    support_units = support_chars + support_rows * 60
    if core_units <= 0:
        return 0.0
    if support_units <= 0:
        return 1.0
    core_ratio = core_units / float(core_units + support_units)
    return min(1.0, core_ratio / 0.65)
```

- [ ] **Step 8: Add regression gate coverage**

In `_regression_gate()`, add the new metric names to the `core_regressions` set:

```python
            "core_section_depth_score",
            "core_support_balance_score",
```

- [ ] **Step 9: Add recommendations**

In `_clean_recommendations()`, add these checks after the existing `core_analysis_depth_score` recommendation:

```python
    if target.values.get("core_section_depth_score", 0.0) < 1.0:
        recommendations.append(
            "Expand core section depth so Decision Summary, Competitive Findings, User Review "
            "Themes, Competitor Deep Dives, SWOT, and layer analysis contain decision-useful "
            "substance rather than one-line placeholders."
        )
    if target.values.get("core_support_balance_score", 0.0) < 1.0:
        recommendations.append(
            "Move report weight back to core analysis and keep evidence, QA, risk, and appendix "
            "sections concise support material."
        )
```

- [ ] **Step 10: Run focused quality tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_report_quality.py::test_compare_run_quality_rejects_support_heavy_report_with_thin_core_sections backend\tests\unit\test_report_quality.py::test_compare_run_quality_accepts_substantive_core_with_concise_support backend\tests\unit\test_report_quality.py::test_compare_run_quality_rejects_support_heavy_report_without_core_analysis -q
```

Expected: PASS.

- [ ] **Step 11: Run the full report quality suite**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_report_quality.py -q
```

Expected: PASS. If failures are fixture-depth failures, strengthen the test fixture core sections with cited implications instead of lowering thresholds.

- [ ] **Step 12: Run ruff for touched files**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m ruff check backend\packages\business_intel\report_quality.py backend\tests\unit\test_report_quality.py
```

Expected: `All checks passed!`

- [ ] **Step 13: Commit Task 2**

Run:

```powershell
git add backend/packages/business_intel/report_quality.py backend/tests/unit/test_report_quality.py
git commit -m "feat: enforce core report depth budget"
```

---

## Task 3: Writer Section Repair Mapping For Thin Core Sections

**Files:**
- Modify: `backend/packages/agents/writer/repair.py`
- Test: `backend/tests/unit/test_writer_repair.py`
- Test: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Add failing repair planner tests**

Add these tests to `backend/tests/unit/test_writer_repair.py` after `test_writer_repair_upstream_changed_allows_full_without_anti_regression`:

```python
def test_writer_repair_maps_thin_competitive_findings_to_section_repair() -> None:
    detail = _detail(report_md=_protectable_report())
    issue = QCIssue(
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
    issue = QCIssue(
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
```

- [ ] **Step 2: Run the new planner tests and verify they fail**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_writer_repair.py::test_writer_repair_maps_thin_competitive_findings_to_section_repair backend\tests\unit\test_writer_repair.py::test_writer_repair_maps_thin_decision_summary_to_section_repair -q
```

Expected: FAIL because the planner currently treats these findings as broad or unmapped.

- [ ] **Step 3: Extend `SECTION_REPAIR_HINTS`**

In `backend/packages/agents/writer/repair.py`, replace `SECTION_REPAIR_HINTS` with:

```python
SECTION_REPAIR_HINTS: dict[str, tuple[str, ...]] = {
    "decision_summary": (
        "decision summary",
        "recommended action",
        "decision posture",
        "immediate next move",
    ),
    "competitive_findings": (
        "competitive findings",
        "dimension findings",
        "highest-impact finding",
        "findings section",
    ),
    "review_theme_summary": (
        "review",
        "user review",
        "review_theme",
        "user_research",
        "adoption blocker",
        "switching trigger",
    ),
    "swot_analysis": ("swot", "strength", "weakness", "opportunit", "threat"),
    "competitor_deep_dives": ("competitor deep", "deep_dive", "wins", "watchouts"),
    "battlecard": ("battlecard", "response guidance", "sales response", "objection"),
    "workflow_enterprise_risk": ("workflow", "enterprise risk", "switching cost"),
    "market_landscape": ("market landscape", "category strategy", "competitor clusters"),
    "claim_risk": ("claim risk", "claim_validation", "evidence risk"),
    "rag_gap_fill": ("rag", "gap fill", "retrieval"),
}
```

- [ ] **Step 4: Add an integration test for section repair routing**

Add this test to `backend/tests/unit/test_run_service.py` near the existing writer section repair tests:

```python
@pytest.mark.asyncio
async def test_writer_only_thin_core_finding_uses_section_repair() -> None:
    service = RunService(
        skill_registry=SkillRegistry.from_default_path(),
        settings=Settings(demo_mode=True, writer_timeout_seconds=5),
    )
    detail = await service.create_run(
        RunCreateRequest(
            topic="Writer thin core section repair",
            competitors=["Cursor", "Copilot"],
            dimensions=["pricing", "feature", "persona"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]
    record.detail.report_md = _writer_repair_protectable_report()
    record.detail.qa_findings = [
        QCIssue(
            id="issue-competitive-findings-thin",
            severity="blocker",
            detected_by="report_quality",
            target_agent="writer",
            field_path="report_quality.core_section_depth_score",
            problem="Competitive Findings section is too thin for decision-grade reporting.",
            redo_scope=RedoScope(kind="writer_only", rationale="Expand Competitive Findings."),
        )
    ]
    record.pending_graph_redo = PendingGraphRedo(
        stage="writer",
        redo_scope=RedoScope(kind="writer_only", rationale="Expand Competitive Findings."),
        issue_ids=["issue-competitive-findings-thin"],
        reason="Expand thin core section.",
    )

    async def fake_complete_text(*, system: str, user: str) -> str:  # noqa: ARG001
        assert "Competitive Findings" in user
        return (
            "## Competitive Findings\n"
            "- Cursor has clearer pricing evaluation signals for buyers comparing direct "
            "developer workflow tools. [source:pricing-1]\n"
            "- Copilot retains enterprise familiarity through Microsoft workflow adjacency, "
            "but this creates a different buying motion. [source:feature-1]\n"
            "- The decision implication is to test pricing transparency and onboarding proof "
            "before treating either product as the default winner. [source:pricing-1]"
        )

    service._llm.complete_text = fake_complete_text  # type: ignore[method-assign]

    await service._real_writer_step(record)

    message = record.detail.agent_messages[-1]
    assert message.payload["writer_repair_mode"] == "section"
    assert message.payload["writer_repair_sections"] == ["competitive_findings"]
    assert "The decision implication is to test pricing transparency" in record.detail.report_md
```

- [ ] **Step 5: Run focused planner and integration tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_writer_repair.py::test_writer_repair_maps_thin_competitive_findings_to_section_repair backend\tests\unit\test_writer_repair.py::test_writer_repair_maps_thin_decision_summary_to_section_repair backend\tests\unit\test_run_service.py::test_writer_only_thin_core_finding_uses_section_repair -q
```

Expected: PASS.

- [ ] **Step 6: Run existing writer repair tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_writer_repair.py backend\tests\unit\test_run_service.py::test_writer_section_repair_replaces_only_target_section backend\tests\unit\test_run_service.py::test_writer_full_rewrite_rejects_collapsed_review_section_when_previous_is_protectable -q
```

Expected: PASS.

- [ ] **Step 7: Run ruff for touched files**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m ruff check backend\packages\agents\writer\repair.py backend\tests\unit\test_writer_repair.py backend\tests\unit\test_run_service.py
```

Expected: `All checks passed!`

- [ ] **Step 8: Commit Task 3**

Run:

```powershell
git add backend/packages/agents/writer/repair.py backend/tests/unit/test_writer_repair.py backend/tests/unit/test_run_service.py
git commit -m "feat: route thin core sections to writer repair"
```

---

## Task 4: Regression Verification

**Files:**
- Modify only if a verification failure exposes a bug in Task 1-3 files.

- [ ] **Step 1: Run writer/report quality regression tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_writer_repair.py backend\tests\unit\test_run_service.py backend\tests\unit\test_report_quality.py -q
```

Expected: PASS.

- [ ] **Step 2: Run redo and graph contract tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_redo_seed_cases.py backend\tests\unit\test_graph_send.py -q
```

Expected: PASS.

- [ ] **Step 3: Run ruff**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m ruff check backend\packages\agents\writer\logic.py backend\packages\agents\writer\repair.py backend\packages\business_intel\report_quality.py backend\tests\unit\test_writer_repair.py backend\tests\unit\test_run_service.py backend\tests\unit\test_report_quality.py
```

Expected: `All checks passed!`

- [ ] **Step 4: Run git hygiene checks**

Run:

```powershell
git diff --check
git status --short
git diff --stat
```

Expected:

- `git diff --check` prints no errors.
- `git diff --stat` is empty after all commits.
- `git status --short` shows only known unrelated untracked artifacts or a clean tree.

- [ ] **Step 5: Commit verification fixes only when needed**

If Step 1, 2, 3, or 4 requires a code fix, run:

```powershell
git add backend/packages/agents/writer/logic.py backend/packages/agents/writer/repair.py backend/packages/business_intel/report_quality.py backend/tests/unit/test_writer_repair.py backend/tests/unit/test_run_service.py backend/tests/unit/test_report_quality.py
git commit -m "fix: stabilize report core budget verification"
```

If all verification commands pass with no code changes, do not create a Task 4 commit.

---

## Completion Criteria

- Writer prompt no longer contains `around 5,500 characters`.
- Writer prompt contains `8,500-10,000 characters`, `65-75%`, `Core analysis layer`, and `Support/audit layer`.
- `compare_run_quality()` exposes `core_section_depth_score` and `core_support_balance_score`.
- Report quality blocks support-heavy/core-thin reports.
- Substantive core plus concise support passes quality.
- Thin core findings can route to writer section repair.
- Existing writer redo anti-regression behavior remains intact.
- Focused and regression test commands pass in the conda environment.

## Self-Review Checklist For Implementers

- The implementation keeps a single Markdown report.
- Evidence, QA, claim-risk, RAG gap, and appendix sections remain present.
- Weak evidence still produces explicit evidence-gap analysis rather than invented claims.
- New quality metrics use deterministic parsing, not LLM scoring.
- Localized headings still work through existing report-label aliases.
- No unrelated generated artifacts are staged or committed.
