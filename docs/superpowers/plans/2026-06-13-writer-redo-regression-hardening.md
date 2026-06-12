# Writer Redo Regression Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent upstream-triggered writer redo from replacing a protectable report with a thinner full rewrite, while still allowing scoped section repair and safe full rewrites.

**Architecture:** Keep the existing graph-level redo contracts unchanged. Harden `packages.agents.writer.repair` so upstream-data changes produce line/section/full repair plans with anti-regression enabled for protectable reports, and harden `WriterAgentMixin._real_writer_step()` so every preserved previous report passes Markdown/source-token hardening before assignment.

**Tech Stack:** Python, Pydantic DTOs, pytest, ruff, existing `RunService` writer mixin and report-quality helpers.

---

## File Structure

- Modify: `backend/packages/agents/writer/repair.py`
  - Owns repair-mode classification and report regression detection.
  - Add upstream scoped-routing helper, whole-report substantive character counting, and stricter core-section collapse rules.
- Modify: `backend/packages/agents/writer/logic.py`
  - Owns writer execution, section/full rewrite acceptance, fallback behavior, and writer metadata.
  - Harden every preserved `previous_report` assignment.
- Modify: `backend/tests/unit/test_writer_repair.py`
  - Add red tests for upstream scoped routing and stronger regression detection.
  - Update the old upstream test that expected anti-regression to be disabled.
- Modify: `backend/tests/unit/test_run_service.py`
  - Add red tests for upstream persona section repair, rejecting thinner upstream full rewrite, and source-token hardening when preserving previous report.
  - Update existing upstream full rewrite tests to match the new anti-regression behavior.

---

### Task 1: Repair Plan Routes Upstream Changes Safely

**Files:**
- Modify: `backend/tests/unit/test_writer_repair.py`
- Modify: `backend/packages/agents/writer/repair.py`

- [ ] **Step 1: Write failing tests for upstream scoped routing**

Append these tests near the existing `test_writer_repair_upstream_changed_allows_full_without_anti_regression` test, then replace that old test with the new expectations:

```python
def test_writer_repair_upstream_persona_change_routes_to_section_repair() -> None:
    detail = _detail(report_md=_protectable_report())
    issue = QCIssue(
        id="issue-persona-upstream",
        severity="warn",
        detected_by="coverage",
        target_agent="collector",
        target_subagent="persona",
        target_competitor="Copilot",
        field_path="raw_sources[persona]",
        problem="Copilot persona evidence needs stronger review themes and interview signal.",
        redo_scope=RedoScope(
            kind="collector",
            target_subagent="persona",
            target_competitor="Copilot",
            rationale="Collect persona survey and interview evidence for Copilot.",
        ),
    )

    plan = build_writer_repair_plan(detail, [issue], upstream_data_changed=True)

    assert plan.mode == "section"
    assert plan.previous_report_protectable is True
    assert plan.sections == ["review_theme_summary"]
    assert plan.anti_regression_required is True
    assert "upstream data changed" in plan.reason


def test_writer_repair_upstream_broad_change_uses_full_with_anti_regression() -> None:
    detail = _detail(report_md=_protectable_report())
    issue = QCIssue(
        id="issue-broad-upstream",
        severity="warn",
        detected_by="coverage",
        target_agent="collector",
        field_path="raw_sources",
        problem="Broad upstream evidence changed without a section-specific mapping.",
        redo_scope=RedoScope(kind="collector", rationale="Refresh broad evidence."),
    )

    plan = build_writer_repair_plan(detail, [issue], upstream_data_changed=True)

    assert plan.mode == "full"
    assert plan.previous_report_protectable is True
    assert plan.anti_regression_required is True
    assert "anti-regression" in plan.reason


def test_writer_repair_upstream_poor_previous_report_uses_full_without_guard() -> None:
    detail = _detail(report_md="# Report\n\nthin")
    issue = _report_line_issue(line_number=3, problem="stale upstream evidence")

    plan = build_writer_repair_plan(detail, [issue], upstream_data_changed=True)

    assert plan.mode == "full"
    assert plan.previous_report_protectable is False
    assert plan.anti_regression_required is False
    assert "not protectable" in plan.reason
```

- [ ] **Step 2: Run the targeted tests and verify they fail**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_writer_repair.py -q
```

Expected: the new upstream persona test fails because current code returns `mode == "full"` with `anti_regression_required is False`.

- [ ] **Step 3: Implement upstream repair-plan routing**

In `backend/packages/agents/writer/repair.py`, add this constant below `LINE_REPAIR_MAX_ISSUES`:

```python
UPSTREAM_SECTION_REPAIR_MAX_SECTIONS = 4
```

Replace the current `if upstream_data_changed:` block in `build_writer_repair_plan()` with:

```python
    if upstream_data_changed:
        return _upstream_data_changed_repair_plan(detail, issues, protectable)
```

Add this helper below `build_writer_repair_plan()`:

```python
def _upstream_data_changed_repair_plan(
    detail: RunDetail,
    issues: list[QCIssue],
    protectable: bool,
) -> WriterRepairPlan:
    if not protectable:
        return WriterRepairPlan(
            mode="full",
            reason="upstream data changed; previous report is not protectable",
            previous_report_protectable=False,
            anti_regression_required=False,
        )

    line_numbers = _report_line_numbers(issues)
    if (
        line_numbers
        and len(line_numbers) <= LINE_REPAIR_MAX_ISSUES
        and len(line_numbers) == len(issues)
    ):
        return WriterRepairPlan(
            mode="line",
            reason="upstream data changed; small report line repair selected",
            previous_report_protectable=True,
            line_numbers=line_numbers,
            anti_regression_required=True,
        )

    sections = _target_sections(issues)
    if sections and len(sections) <= UPSTREAM_SECTION_REPAIR_MAX_SECTIONS:
        return WriterRepairPlan(
            mode="section",
            reason="upstream data changed; scoped section repair selected",
            previous_report_protectable=True,
            sections=sections,
            anti_regression_required=True,
        )

    return WriterRepairPlan(
        mode="full",
        reason="upstream data changed; broad rewrite required with anti-regression",
        previous_report_protectable=True,
        anti_regression_required=True,
    )
```

- [ ] **Step 4: Expand section hints for current upstream issue text**

In `SECTION_REPAIR_HINTS`, add these exact hint strings without removing the existing ones:

```python
    "review_theme_summary": (
        "user review",
        "review themes",
        "customer review",
        "buyer feedback",
        "review_theme",
        "user_research",
        "adoption blocker",
        "switching trigger",
        "persona",
        "survey",
        "interview",
    ),
    "competitive_findings": (
        "competitive findings",
        "dimension findings",
        "highest-impact finding",
        "findings section",
        "feature",
        "capability",
        "dimension cell",
    ),
    "competitor_deep_dives": (
        "competitor deep",
        "competitor deep dive",
        "deep_dive",
        "deep dive watchouts",
        "per-competitor wins/watchouts",
        "feature",
        "capability",
    ),
```

Keep the current tuple contents and merge these hints into the tuples rather than duplicating dictionary keys.

- [ ] **Step 5: Run tests and verify Task 1 passes**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_writer_repair.py -q
```

Expected: all tests in `test_writer_repair.py` pass.

---

### Task 2: Strengthen Anti-Regression Detection

**Files:**
- Modify: `backend/tests/unit/test_writer_repair.py`
- Modify: `backend/packages/agents/writer/repair.py`

- [ ] **Step 1: Write failing tests for section and whole-report collapse**

Add these tests after the existing `test_report_regression_detects_collapsed_review_section` tests:

```python
def test_report_regression_detects_large_review_section_collapse() -> None:
    rich_review = "\n".join(
        f"- User research theme {index}: buyer feedback explains adoption blocker "
        f"and switching trigger for Cursor and Copilot. [source:pricing-1]"
        for index in range(12)
    )
    previous = _detail(
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
            rich_review,
        )
    )
    candidate = _detail(
        report_md=previous.report_md.replace(
            rich_review,
            "Existing evidence does not provide verified user reviews.",
        )
    )

    problem = report_regression_problem(
        previous,
        candidate,
        protected_sections=["review_theme_summary"],
    )

    assert problem is not None
    assert "review_theme_summary" in problem


def test_report_regression_detects_whole_report_collapse() -> None:
    previous_report = _protectable_report() + "\n\n" + "\n".join(
        f"Detailed cited analysis line {index} explains buyer impact, risk, and next action. "
        f"[source:pricing-1]"
        for index in range(220)
    )
    candidate_report = _protectable_report()
    previous = _detail(report_md=previous_report)
    candidate = _detail(report_md=candidate_report)

    problem = report_regression_problem(
        previous,
        candidate,
        protected_sections=["review_theme_summary", "swot_analysis"],
    )

    assert problem is not None
    assert "report regressed" in problem
```

- [ ] **Step 2: Run the targeted tests and verify at least one fails**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_writer_repair.py -q
```

Expected: the whole-report collapse test fails before implementation because `report_regression_problem()` only checks protected sections and `compare_run_quality()`.

- [ ] **Step 3: Implement substantive character helpers and collapse rules**

In `backend/packages/agents/writer/repair.py`, add these constants below `PROTECTABLE_MINIMUMS`:

```python
SECTION_COLLAPSE_RULES = {
    "review_theme_summary": (700, 600, 0.60),
    "swot_analysis": (900, 700, 0.60),
    "competitor_deep_dives": (900, 700, 0.60),
}
WHOLE_REPORT_COLLAPSE_MIN_CHARS = 12_000
WHOLE_REPORT_COLLAPSE_RATIO = 0.70
```

Add this helper near `_section_content_chars()`:

```python
def _substantive_report_chars(markdown: str) -> int:
    body = re.sub(r"\[source:[^\]]+\]", "", markdown)
    body = re.sub(r"\s+", " ", body).strip()
    return len(body)
```

- [ ] **Step 4: Apply the stronger checks in `report_regression_problem()`**

After the existing protected-section loop and before `comparison = compare_run_quality(...)`, add:

```python
    for section_key, (previous_minimum, candidate_floor, ratio) in SECTION_COLLAPSE_RULES.items():
        previous_chars = _section_content_chars(
            previous.report_md,
            section_key,
            previous.output_language,
        )
        candidate_chars = _section_content_chars(
            candidate.report_md,
            section_key,
            candidate.output_language,
        )
        if previous_chars >= previous_minimum and candidate_chars < max(
            candidate_floor,
            previous_chars * ratio,
        ):
            return (
                f"{section_key} section regressed from {previous_chars} to "
                f"{candidate_chars} substantive characters"
            )

    previous_report_chars = _substantive_report_chars(previous.report_md)
    candidate_report_chars = _substantive_report_chars(candidate.report_md)
    if (
        previous_report_chars >= WHOLE_REPORT_COLLAPSE_MIN_CHARS
        and candidate_report_chars < previous_report_chars * WHOLE_REPORT_COLLAPSE_RATIO
    ):
        return (
            f"report regressed from {previous_report_chars} to "
            f"{candidate_report_chars} substantive characters"
        )
```

- [ ] **Step 5: Run tests and verify Task 2 passes**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_writer_repair.py -q
```

Expected: all tests in `test_writer_repair.py` pass.

---

### Task 3: Harden Preserved Previous Reports In Writer Logic

**Files:**
- Modify: `backend/tests/unit/test_run_service.py`
- Modify: `backend/packages/agents/writer/logic.py`

- [ ] **Step 1: Write failing tests for upstream section routing and preserved hardening**

Add these tests near the existing writer repair tests in `backend/tests/unit/test_run_service.py`:

```python
@pytest.mark.asyncio
async def test_writer_upstream_persona_change_uses_section_repair() -> None:
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
        return (
            "## User Review Themes\n"
            "- Persona refresh: simulated survey and interview signals show buyers compare "
            "pricing clarity with Microsoft workflow familiarity. [source:pricing-1]\n"
            "- Adoption blocker: procurement and rollout proof still need validation. "
            "[source:feature-1]\n"
        )

    service._llm.complete_text = fake_complete_text  # type: ignore[method-assign]
    detail = await service.create_run(
        RunCreateRequest(
            topic="Writer upstream persona section",
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
        id="issue-upstream-persona",
        severity="warn",
        detected_by="coverage",
        target_agent="collector",
        target_subagent="persona",
        target_competitor="Copilot",
        field_path="raw_sources[persona]",
        problem="Copilot persona review themes need stronger survey and interview evidence.",
        redo_scope=RedoScope(
            kind="collector",
            target_subagent="persona",
            target_competitor="Copilot",
            rationale="Collect persona survey and interview evidence for Copilot.",
        ),
    )
    record.detail.qa_findings = [issue]
    record.pending_graph_redo = PendingGraphRedo(
        iteration=1,
        stage="collector",
        redo_scope=issue.redo_scope,
        redo_scopes=[issue.redo_scope],
        before_md=record.detail.report_md,
        issue_ids=[issue.id],
        qa_issue_ids_before=[issue.id],
        issue_count_before=1,
    )

    await service._real_writer_step(record)

    payload = record.detail.agent_messages[-1].payload
    assert payload["writer_mode"] == "writer repair: section"
    assert payload["writer_repair_mode"] == "section"
    assert payload["writer_repair_sections"] == ["review_theme_summary"]
    assert payload["previous_report_protected"] is True
    assert "## SWOT Analysis" in record.detail.report_md
    assert "Persona refresh" in record.detail.report_md


@pytest.mark.asyncio
async def test_writer_preserved_previous_report_is_hardened_after_anti_regression() -> None:
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
        return (
            "# Thin Candidate\n\n"
            "## Executive Summary\n"
            "Existing evidence does not provide verified user reviews. [source:pricing-1]\n"
        )

    service._llm.complete_text = fake_complete_text  # type: ignore[method-assign]
    detail = await service.create_run(
        RunCreateRequest(
            topic="Writer preserved hardening",
            competitors=["Cursor", "Copilot"],
            dimensions=["pricing", "feature", "persona"],
            execution_mode="real",
            output_language="en-US",
        )
    )
    record = service._runs[detail.id]
    record.detail.raw_sources = _writer_repair_sources()
    previous_report = _writer_repair_protectable_report().replace(
        "[source:pricing-1]",
        "[source:pricing]",
        1,
    )
    record.detail.report_md = previous_report
    issue = QCIssue(
        id="issue-broad-writer-collapse",
        severity="blocker",
        detected_by="text_quality",
        target_agent="writer",
        field_path="report_md",
        problem="Report needs broad narrative quality repair.",
        redo_scope=RedoScope(kind="writer_only", rationale="repair broad writer quality"),
    )
    record.detail.qa_findings = [issue]
    record.pending_graph_redo = PendingGraphRedo(
        iteration=1,
        stage="writer_only",
        redo_scope=issue.redo_scope,
        redo_scopes=[issue.redo_scope],
        before_md=record.detail.report_md,
        issue_ids=[issue.id],
        qa_issue_ids_before=[issue.id],
        issue_count_before=1,
    )
    service._append_agent_message(
        record,
        from_agent="qa",
        to_agent="writer_only",
        message_type="redo_request",
        payload_schema="RedoRequestPayload",
        payload={
            "redo_scope": issue.redo_scope.model_dump(mode="json"),
            "issues": [issue.model_dump(mode="json")],
            "issue_ids": [issue.id],
        },
    )
    service._consume_queued_agent_messages(
        record,
        to_agent="writer_only",
        consumer_agent="redo_router",
        message_types={"redo_request"},
    )

    await service._real_writer_step(record)

    payload = record.detail.agent_messages[-1].payload
    assert payload["writer_mode"] == "preserved previous report after writer anti-regression"
    assert payload["anti_regression_reason"]
    assert "[source:pricing]" not in record.detail.report_md
    assert "[source:pricing-1]" in record.detail.report_md
```

- [ ] **Step 2: Update existing upstream full-rewrite tests to new expectations**

In `test_writer_upstream_changed_accepts_thinner_full_rewrite`, change the expected behavior:

```python
    payload = record.detail.agent_messages[-1].payload
    assert "Cursor has updated pricing transparency" not in record.detail.report_md
    assert "Customer theme: pricing clarity supports fast evaluation" in record.detail.report_md
    assert payload["writer_repair_mode"] == "full"
    assert payload["previous_report_protected"] is True
    assert payload["anti_regression_reason"]
    assert (
        payload["writer_mode"]
        == "preserved previous report after writer anti-regression"
    )
```

Keep `test_writer_upstream_changed_allows_full_rewrite_with_guard_metadata`, but update it only if needed so it expects `writer_repair_mode == "full"` and `anti_regression_reason is None` for a non-collapsing candidate.

- [ ] **Step 3: Run the targeted run-service tests and verify failures**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py -q -k "writer_upstream or writer_preserved_previous_report_is_hardened_after_anti_regression"
```

Expected: upstream persona currently uses full rewrite, and preserved previous report currently keeps the stale `[source:pricing]` token.

- [ ] **Step 4: Add a preserved-report hardening helper**

In `backend/packages/agents/writer/logic.py`, add this method inside `WriterAgentMixin`, near `_harden_report_markdown()`:

```python
    def _preserve_hardened_previous_report(
        self,
        detail: RunDetail,
        previous_report: str,
    ) -> str:
        return self._harden_report_markdown(detail, previous_report)
```

- [ ] **Step 5: Use the helper on every previous-report fallback assignment**

In `_real_writer_step()`, replace every assignment of:

```python
detail.report_md = previous_report
```

with:

```python
detail.report_md = self._preserve_hardened_previous_report(detail, previous_report)
```

This must cover:

- section repair `TimeoutError`
- section repair generic `Exception`
- full rewrite anti-regression rejection
- full rewrite `TimeoutError`
- full rewrite generic `Exception`

- [ ] **Step 6: Run tests and verify Task 3 passes**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py -q -k "writer_repair or writer_upstream or writer_preserved_previous_report_is_hardened_after_anti_regression"
```

Expected: selected run-service writer tests pass.

---

### Task 4: Full Verification And Cleanup

**Files:**
- Review: `backend/packages/agents/writer/repair.py`
- Review: `backend/packages/agents/writer/logic.py`
- Review: `backend/tests/unit/test_writer_repair.py`
- Review: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Run writer repair unit tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_writer_repair.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run run-service writer subset**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_run_service.py -q -k "writer_repair or writer_upstream or writer_preserved_previous_report_is_hardened_after_anti_regression"
```

Expected: all selected tests pass.

- [ ] **Step 3: Run report quality regression tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend\tests\unit\test_report_quality.py -q
```

Expected: all tests pass.

- [ ] **Step 4: Run ruff on touched files**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m ruff check backend\packages\agents\writer\repair.py backend\packages\agents\writer\logic.py backend\tests\unit\test_writer_repair.py backend\tests\unit\test_run_service.py
```

Expected: exit code 0.

- [ ] **Step 5: Inspect diff**

Run:

```powershell
git diff -- backend\packages\agents\writer\repair.py backend\packages\agents\writer\logic.py backend\tests\unit\test_writer_repair.py backend\tests\unit\test_run_service.py
git diff --check
```

Expected: diff only contains the scoped repair routing, regression checks, preserved-report hardening, and tests described in this plan. `git diff --check` exits 0.

- [ ] **Step 6: Commit implementation**

Run:

```powershell
git add backend\packages\agents\writer\repair.py backend\packages\agents\writer\logic.py backend\tests\unit\test_writer_repair.py backend\tests\unit\test_run_service.py
git commit -m "Harden writer redo regression handling"
```

Expected: commit succeeds.

---

## Self-Review

- Spec coverage: This plan covers upstream scoped routing, mandatory anti-regression for protectable reports, stronger section and whole-report collapse detection, hardened previous-report preservation, observability via existing writer metadata, and conda-based verification.
- Placeholder scan: No placeholder tasks are left; each implementation task names exact files, code shape, commands, and expected outcomes.
- Type consistency: The plan uses existing `WriterRepairPlan`, `QCIssue`, `RedoScope`, `PendingGraphRedo`, `RunDetail`, `RunService`, and `report_regression_problem()` APIs.
