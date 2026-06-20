# Schema-First Writer Main Path Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make schema-first writer generation the authoritative real-run path, prevent silent Markdown fallback, preserve scoped redo intent, unify final quality accounting, and verify the result with a restarted real run.

**Architecture:** Keep the existing `StructuredReport`, renderer, validator, publication contract, and legacy Markdown writer. Harden the real-run branch so structured failures produce typed section failures, preservation, or fail-closed writer errors instead of silently generating a Markdown fallback report. Add a small final quality-result boundary so deterministic QA and release-gate warnings feed the same revision, metrics, detail, and completion-event counts.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, existing conda environment at `D:\Anaconda\envs\bd-competiscope-v2\python.exe`, current backend modules under `backend/packages/agents/writer`, `backend/packages/orchestrator`, and `backend/packages/quality`.

---

## Scope And Guardrails

This plan implements `docs/superpowers/specs/2026-06-20-schema-first-writer-main-path-hardening-design.md`.

Do not commit generated reports, run DB files, output packages, Word docs, zip files, or local artifacts. The current worktree already has unrelated untracked artifacts; ignore them and stage only the files named in each task.

Use PowerShell commands from repository root:

```powershell
cd D:\codex_workspace\plan_a
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest ...
```

## Current Code Map

- `backend/packages/agents/writer/logic.py`
  - Currently catches any structured writer exception and calls `_writer_markdown_report_from_evidence_pack()` at lines around 805-937.
  - Owns `_writer_structured_report()` and `_writer_structured_section_json()`.
  - Emits `writer_structured_section_started`, `writer_structured_section_completed`, `writer_markdown_fallback_used`, and final report metadata.

- `backend/packages/agents/writer/structured_report.py`
  - Defines the `StructuredReport` object and typed section models.

- `backend/packages/agents/writer/structured_renderer.py`
  - Deterministically renders structured reports into Markdown.

- `backend/packages/agents/writer/structured_validation.py`
  - Validates structured object quality.

- `backend/packages/agents/writer/publication_contract.py`
  - Validates rendered Markdown hygiene.
  - Already checks headings, table headers, internal terms, citations, and core/support order.
  - Does not yet explicitly reject citations on `<!-- report-section:... -->` marker lines.

- `backend/packages/agents/writer/assembler.py`
  - Contains `StructuredReportAssembler`, currently only reporting missing/duplicate competitor coverage telemetry.

- `backend/packages/agents/writer/repair.py`
  - Maps release-gate and publication issues to repair plan modes and structured repair targets.

- `backend/packages/orchestrator/service.py`
  - Owns `RunRecord`, `PendingGraphRedo`, release-gate sync, revision recording, and metrics refresh.
  - `_sync_release_gate_repair_issues()` can update latest revision counts after release-gate warnings are attached.
  - `_record_revision()` emits `revision_recorded` before later release-gate sync can update `detail.revisions`, which caused event/detail disagreement in `run-b604...`.

- `backend/tests/unit/test_run_service.py`
  - Contains existing structured writer integration tests.
  - Existing `test_real_writer_traces_markdown_fallback_when_structured_path_fails` must be replaced because real schema-first runs must fail closed.

## Implementation Rules

- Real schema-first run means `detail.execution_mode == "real"` and `settings.writer_structured_report_enabled is True`.
- In that mode, structured failure must not call `_writer_markdown_report_from_evidence_pack()`.
- Existing Markdown writer remains available when the structured flag is disabled.
- A redo run with a previous report may preserve the previous report on structured failure.
- A scoped upstream redo may merge only affected structured sections into the previous structured snapshot.
- If no previous structured snapshot exists and a scoped redo candidate changes the executive recommendation without a scoped-evidence justification, preserve the previous report rather than accepting drift.
- One final quality result must feed revision records, event payloads, metrics, and run detail issue counts.

---

### Task 1: Publication Contract Marker-Line Citation Gate

**Files:**
- Modify: `backend/packages/agents/writer/publication_contract.py`
- Test: `backend/tests/unit/test_writer_publication_contract.py`

- [ ] **Step 1: Add failing tests for section marker citations**

Append these tests to `backend/tests/unit/test_writer_publication_contract.py`:

```python
def test_publication_contract_rejects_source_citation_on_section_marker_line() -> None:
    report = _report("zh-CN")
    markdown = (
        "<!-- report-section:key=executive_summary layer=core --> "
        "[source:raw-source-a]\n"
        "## 执行摘要\n"
        "- 建议: 选择 Cursor。[source:raw-source-a]\n"
    )

    result = validate_publication_contract(
        markdown,
        structured_report=report,
        allowed_source_ids={"raw-source-a"},
    )

    assert not result.passed
    assert "citation_on_section_marker" in result.issue_codes()
    issue = next(
        item for item in result.issues if item.code == "citation_on_section_marker"
    )
    assert issue.line_number == 1
    assert issue.repair_target == "renderer"


def test_publication_contract_accepts_clean_section_marker_line() -> None:
    report = _report("zh-CN")
    markdown = (
        "<!-- report-section:key=executive_summary layer=core -->\n"
        "## 执行摘要\n"
        "- 建议: 选择 Cursor。[source:raw-source-a]\n"
    )

    result = validate_publication_contract(
        markdown,
        structured_report=report,
        allowed_source_ids={"raw-source-a"},
    )

    assert "citation_on_section_marker" not in result.issue_codes()
```

- [ ] **Step 2: Run the focused failing tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_writer_publication_contract.py::test_publication_contract_rejects_source_citation_on_section_marker_line backend/tests/unit/test_writer_publication_contract.py::test_publication_contract_accepts_clean_section_marker_line -q
```

Expected: first test fails because `citation_on_section_marker` is not detected.

- [ ] **Step 3: Implement marker-line validation**

In `backend/packages/agents/writer/publication_contract.py`, add a marker regex near the existing regex constants:

```python
_SECTION_MARKER_RE = re.compile(r"^<!--\s*report-section:[^>]*-->\s*$")
_SECTION_MARKER_PREFIX_RE = re.compile(r"^<!--\s*report-section:[^>]*-->")
```

Call the new validator inside `validate_publication_contract()` after `lines` and `is_zh` are computed:

```python
    _validate_section_marker_lines(lines, issues=issues)
```

Add this function before `_validate_headings()`:

```python
def _validate_section_marker_lines(
    lines: list[str],
    *,
    issues: list[PublicationContractIssue],
) -> None:
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not _SECTION_MARKER_PREFIX_RE.match(stripped):
            continue
        if not _SECTION_MARKER_RE.fullmatch(stripped):
            issues.append(
                PublicationContractIssue(
                    code="citation_on_section_marker"
                    if has_source_token(stripped)
                    else "invalid_section_marker_line",
                    line_number=line_number,
                    message="Section marker line must contain only the marker comment.",
                    repair_target="renderer",
                )
            )
```

- [ ] **Step 4: Run publication contract tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_writer_publication_contract.py -q
```

Expected: all tests in `test_writer_publication_contract.py` pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/packages/agents/writer/publication_contract.py backend/tests/unit/test_writer_publication_contract.py
git commit -m "fix: reject citations on report section markers"
```

---

### Task 2: Fail-Closed Real Schema-First Writer Path

**Files:**
- Modify: `backend/packages/agents/writer/logic.py`
- Modify: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Replace the old real-run fallback test**

In `backend/tests/unit/test_run_service.py`, replace `test_real_writer_traces_markdown_fallback_when_structured_path_fails` with:

```python
def test_real_schema_first_writer_fails_closed_when_structured_path_fails(
    monkeypatch,
) -> None:
    service = _segmented_writer_service()
    service._settings = replace(
        service._settings,
        writer_structured_report_enabled=True,
        writer_timeout_seconds=10,
    )
    record = _segmented_writer_record(service, competitors=["Cursor", "Windsurf"])
    record.detail.execution_mode = "real"
    record.detail.output_language = "zh-CN"
    record.detail.raw_sources = _structured_writer_raw_sources()

    async def fake_structured_report(self, record, evidence_pack_result, timeout_seconds):
        raise ValueError("structured section failed")

    async def fail_if_markdown_writer_called(self, record, evidence_pack_result, timeout_seconds):
        raise AssertionError("Markdown fallback must not run for real schema-first reports")

    monkeypatch.setattr(
        "packages.agents.writer.logic.WriterAgentMixin._writer_structured_report",
        fake_structured_report,
    )
    monkeypatch.setattr(
        "packages.agents.writer.logic.WriterAgentMixin._writer_markdown_report_from_evidence_pack",
        fail_if_markdown_writer_called,
    )

    asyncio.run(service._real_writer_step(record))

    assert record.detail.status == "failed"
    assert record.detail.report_md == ""
    event_types = [event.type for event in record.events]
    assert "writer_schema_first_failed_closed" in event_types
    assert "writer_markdown_fallback_used" not in event_types
```

Add this compatibility test after it:

```python
def test_markdown_writer_still_runs_when_structured_flag_disabled(monkeypatch) -> None:
    service = _segmented_writer_service()
    service._settings = replace(
        service._settings,
        writer_structured_report_enabled=False,
        writer_timeout_seconds=10,
    )
    record = _segmented_writer_record(service, competitors=["Cursor", "Windsurf"])
    record.detail.execution_mode = "real"
    record.detail.output_language = "zh-CN"
    record.detail.raw_sources = _structured_writer_raw_sources()

    async def fail_if_structured_writer_called(self, record, evidence_pack_result, timeout_seconds):
        raise AssertionError("Structured writer should not run when flag is disabled")

    async def fake_markdown_writer(self, record, evidence_pack_result, timeout_seconds):
        return "## 执行摘要\n\nFallback-disabled-path report. [source:raw-source-a]\n"

    monkeypatch.setattr(
        "packages.agents.writer.logic.WriterAgentMixin._writer_structured_report",
        fail_if_structured_writer_called,
    )
    monkeypatch.setattr(
        "packages.agents.writer.logic.WriterAgentMixin._writer_markdown_report_from_evidence_pack",
        fake_markdown_writer,
    )

    asyncio.run(service._real_writer_step(record))

    assert record.detail.status != "failed"
    assert "Fallback-disabled-path report" in record.detail.report_md
```

- [ ] **Step 2: Run the focused failing tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_run_service.py::test_real_schema_first_writer_fails_closed_when_structured_path_fails backend/tests/unit/test_run_service.py::test_markdown_writer_still_runs_when_structured_flag_disabled -q
```

Expected: first test fails because `writer_markdown_fallback_used` still appears and Markdown fallback runs.

- [ ] **Step 3: Add fallback policy helpers**

In `backend/packages/agents/writer/logic.py`, add these helpers near other writer helper functions:

```python
def _schema_first_real_run(detail: RunDetail, structured_enabled: bool) -> bool:
    return structured_enabled and detail.execution_mode == "real"


def _structured_markdown_fallback_allowed(detail: RunDetail, structured_enabled: bool) -> bool:
    if not structured_enabled:
        return True
    return detail.execution_mode != "real"
```

- [ ] **Step 4: Replace broad structured fallback with fail-closed handling**

In `_real_writer_step()`, replace the `except Exception as exc:` block that emits `writer_markdown_fallback_used` and calls `_writer_markdown_report_from_evidence_pack()` with:

```python
                    except Exception as exc:  # noqa: BLE001 - structured failures are handled by policy.
                        fallback_reason = str(exc)[:500]
                        if not _structured_markdown_fallback_allowed(
                            detail,
                            self._settings.writer_structured_report_enabled,
                        ):
                            await self.emit(
                                detail.id,
                                "writer_schema_first_failed_closed",
                                "writer",
                                None,
                                "Schema-first writer failed closed for a real run.",
                                {
                                    "reason": fallback_reason,
                                    "previous_report_preserved": bool(previous_report.strip()),
                                    "writer_repair_mode": writer_repair_mode,
                                    "writer_repair_sections": list(writer_repair_sections),
                                },
                            )
                            if previous_report.strip():
                                detail.report_md = self._preserve_hardened_previous_report(
                                    detail,
                                    previous_report,
                                )
                                writer_error = fallback_reason
                                writer_mode = "preserved previous report after schema-first writer error"
                            else:
                                await self._fail_writer_without_report(
                                    record,
                                    fallback_reason,
                                    writer_repair_mode=writer_repair_mode,
                                    writer_repair_sections=writer_repair_sections,
                                    writer_repair_decision=writer_repair_decision,
                                    anti_regression_reason=anti_regression_reason,
                                    previous_report_protected=previous_report_protected,
                                )
                            report_md = detail.report_md
                        else:
                            fallback_payload = {"reason": fallback_reason}
                            await self.emit(
                                detail.id,
                                "writer_markdown_fallback_used",
                                "writer",
                                None,
                                "Structured writer failed; using Markdown writer fallback.",
                                fallback_payload,
                            )
                            self._trace_local_tool(
                                record,
                                agent="writer",
                                subagent=None,
                                name="writer_markdown_fallback_used",
                                input_text="structured_writer_exception",
                                output_text=fallback_reason,
                                metadata=fallback_payload,
                            )
                            report_md = await self._writer_markdown_report_from_evidence_pack(
                                record,
                                evidence_pack_result,
                                timeout_seconds,
                            )
                            writer_mode = (
                                "real segmented LLM call"
                                if evidence_pack_result.metrics.segmented_writer_required
                                else "real LLM call"
                            )
```

Keep the existing outer exception handling after this block. Do not remove the feature-flag-disabled Markdown path.

- [ ] **Step 5: Run focused run-service tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_run_service.py::test_real_schema_first_writer_fails_closed_when_structured_path_fails backend/tests/unit/test_run_service.py::test_markdown_writer_still_runs_when_structured_flag_disabled -q
```

Expected: both tests pass.

- [ ] **Step 6: Commit**

```powershell
git add backend/packages/agents/writer/logic.py backend/tests/unit/test_run_service.py
git commit -m "fix: fail closed for real schema-first writer errors"
```

---

### Task 3: Typed Structured Section Failure Telemetry

**Files:**
- Create: `backend/packages/agents/writer/structured_sections.py`
- Modify: `backend/packages/agents/writer/logic.py`
- Modify: `backend/tests/unit/test_writer_structured_generation.py`

- [ ] **Step 1: Write failing section failure tests**

Append these tests to `backend/tests/unit/test_writer_structured_generation.py`:

```python
@pytest.mark.asyncio
async def test_structured_section_json_raises_typed_failure_after_retry() -> None:
    harness = _WriterHarness(["not json", "still not json"])

    with pytest.raises(Exception) as exc_info:
        await harness._writer_structured_section_json(
            record=object(),
            segment={"section_id": "executive_summary", "content": "Evidence"},
            section_schema=ExecutiveSummarySection,
            allowed_source_ids={"raw-source-a"},
            timeout_seconds=5.0,
        )

    assert exc_info.value.__class__.__name__ == "StructuredSectionGenerationError"
    assert "executive_summary" in str(exc_info.value)
    assert len(harness.prompts) == 2


@pytest.mark.asyncio
async def test_structured_report_emits_section_failed_event(monkeypatch) -> None:
    harness = _WriterHarness([])
    record = _record_for_structured_writer()
    record.detail.raw_sources = _raw_sources()

    async def failing_section_json(
        record, *, segment, section_schema, allowed_source_ids, timeout_seconds
    ):
        if str(segment["section_id"]) == "decision_matrix":
            from packages.agents.writer.structured_sections import (
                StructuredSectionGenerationError,
            )

            raise StructuredSectionGenerationError(
                section_key="decision_matrix",
                section_id="decision_matrix",
                schema_name="DecisionMatrixSection",
                message="source_ids are required unless evidence_role is evidence_gap",
            )
        return _section_fixture_for_schema(section_schema, segment)

    monkeypatch.setattr(harness, "_writer_structured_section_json", failing_section_json)

    with pytest.raises(Exception) as exc_info:
        await harness._writer_structured_report(
            record,
            evidence_pack_result=_minimal_evidence_pack_result(),
            timeout_seconds=10,
        )

    assert exc_info.value.__class__.__name__ == "StructuredReportGenerationError"
    failed = [
        event for event in harness.emitted_events if event[1] == "writer_structured_section_failed"
    ]
    assert failed
    assert failed[0][5]["section_key"] == "decision_matrix"
```

If `_record_for_structured_writer`, `_raw_sources`, or `_section_fixture_for_schema` do not exist, add small helpers in the same test file using the existing `_minimal_evidence_pack_result()`, `_report()`, and `_WriterHarness` patterns already present in that file.

- [ ] **Step 2: Run the focused failing tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_writer_structured_generation.py::test_structured_section_json_raises_typed_failure_after_retry backend/tests/unit/test_writer_structured_generation.py::test_structured_report_emits_section_failed_event -q
```

Expected: tests fail because errors are generic `ValueError` and no section failure event is emitted.

- [ ] **Step 3: Add typed failure classes**

Create `backend/packages/agents/writer/structured_sections.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StructuredSectionGenerationError(RuntimeError):
    section_key: str
    section_id: str
    schema_name: str
    message: str

    def __str__(self) -> str:
        return (
            f"{self.section_key} ({self.schema_name}) failed structured generation: "
            f"{self.message}"
        )


@dataclass(frozen=True)
class StructuredReportGenerationError(RuntimeError):
    failed_sections: tuple[StructuredSectionGenerationError, ...]

    def __str__(self) -> str:
        section_names = ", ".join(error.section_key for error in self.failed_sections)
        return f"structured report generation failed for section(s): {section_names}"
```

- [ ] **Step 4: Raise typed errors after section retry**

In `backend/packages/agents/writer/logic.py`, import:

```python
from packages.agents.writer.structured_sections import (
    StructuredReportGenerationError,
    StructuredSectionGenerationError,
)
```

In `_writer_structured_section_json()`, wrap the retry parse failure:

```python
        except ValueError as exc:
            ...
            try:
                return _parse_structured_section_response(
                    retry_response,
                    section_schema,
                    allowed_source_ids,
                )
            except ValueError as retry_exc:
                section_id = str(segment.get("section_id") or "unknown")
                section_key = str(segment.get("section_key") or section_id)
                raise StructuredSectionGenerationError(
                    section_key=section_key,
                    section_id=section_id,
                    schema_name=section_schema.__name__,
                    message=str(retry_exc),
                ) from retry_exc
```

Add `"section_key": key` to each `section_inputs[key]` before passing it to `_writer_structured_section_json()` in `_writer_structured_report()`.

- [ ] **Step 5: Emit section failure events from `_writer_structured_report()`**

In `_writer_structured_report()`, wrap each section call:

```python
            try:
                sections[key] = await self._writer_structured_section_json(
                    record,
                    segment=section_inputs[key],
                    section_schema=_structured_section_schema(item["schema"]),
                    allowed_source_ids=section_allowed_source_ids,
                    timeout_seconds=timeout_seconds,
                )
            except StructuredSectionGenerationError as exc:
                await self.emit(
                    detail.id,
                    "writer_structured_section_failed",
                    "writer",
                    key,
                    f"Structured report section failed {index}/{total_sections}: {key}",
                    {
                        **event_payload,
                        "schema_name": exc.schema_name,
                        "error": exc.message,
                    },
                )
                raise StructuredReportGenerationError((exc,)) from exc
```

- [ ] **Step 6: Run structured generation tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_writer_structured_generation.py -q
```

Expected: all structured generation tests pass.

- [ ] **Step 7: Commit**

```powershell
git add backend/packages/agents/writer/structured_sections.py backend/packages/agents/writer/logic.py backend/tests/unit/test_writer_structured_generation.py
git commit -m "feat: emit typed structured section failures"
```

---

### Task 4: Scoped Redo Structured Snapshot Merge And Recommendation Guard

**Files:**
- Create: `backend/packages/agents/writer/structured_repair.py`
- Modify: `backend/packages/orchestrator/service.py`
- Modify: `backend/packages/agents/writer/logic.py`
- Test: `backend/tests/unit/test_writer_structured_repair.py`
- Test: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Write pure repair tests**

Replace or extend `backend/tests/unit/test_writer_structured_repair.py` with these tests:

```python
from __future__ import annotations

from packages.agents.writer.structured_repair import (
    recommendation_delta_problem,
    scoped_structured_section_keys,
)
from packages.schema.models import RedoScope


def _scope(kind: str, subagent: str, competitor: str) -> RedoScope:
    return RedoScope(
        kind=kind,
        target_subagent=subagent,
        target_competitor=competitor,
        rationale=f"{competitor} {subagent} redo",
    )


def test_scoped_structured_section_keys_for_persona_redo() -> None:
    keys = scoped_structured_section_keys([_scope("collector", "persona", "Claude Code")])

    assert keys == {
        "user_review_themes",
        "competitor_deep_dive::Claude Code",
        "support",
    }


def test_scoped_structured_section_keys_for_pricing_redo() -> None:
    keys = scoped_structured_section_keys([_scope("collector", "pricing", "Windsurf")])

    assert keys == {
        "decision_matrix",
        "competitor_deep_dive::Windsurf",
        "support",
    }


def test_recommendation_delta_problem_detects_unjustified_top_choice_change() -> None:
    problem = recommendation_delta_problem(
        previous_recommendation="GitHub Copilot and Cursor are the risk-adjusted primary choices.",
        candidate_recommendation="Windsurf is the primary recommendation.",
        scoped_competitors={"Claude Code"},
        scoped_dimensions={"persona"},
        candidate_rationale="Windsurf has broad feature coverage.",
    )

    assert problem is not None
    assert "recommendation changed" in problem


def test_recommendation_delta_problem_allows_scoped_justification() -> None:
    problem = recommendation_delta_problem(
        previous_recommendation="GitHub Copilot is the baseline.",
        candidate_recommendation="Claude Code is now the primary recommendation.",
        scoped_competitors={"Claude Code"},
        scoped_dimensions={"persona"},
        candidate_rationale=(
            "New Claude Code persona evidence from the scoped redo shows stronger "
            "adoption fit for terminal-heavy teams."
        ),
    )

    assert problem is None
```

- [ ] **Step 2: Run pure repair tests and observe failure**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_writer_structured_repair.py -q
```

Expected: fails because `structured_repair.py` does not expose these functions yet.

- [ ] **Step 3: Implement scoped repair helpers**

Create `backend/packages/agents/writer/structured_repair.py`:

```python
from __future__ import annotations

import re
from collections.abc import Iterable

from packages.schema.models import RedoScope


def scoped_structured_section_keys(scopes: Iterable[RedoScope]) -> set[str]:
    keys: set[str] = set()
    for scope in scopes:
        dimension = (scope.target_subagent or "").casefold()
        competitor = scope.target_competitor or ""
        if dimension in {"persona", "review", "customer", "user"}:
            keys.add("user_review_themes")
            if competitor:
                keys.add(f"competitor_deep_dive::{competitor}")
        elif dimension == "pricing":
            keys.add("decision_matrix")
            if competitor:
                keys.add(f"competitor_deep_dive::{competitor}")
        elif dimension == "feature":
            if competitor:
                keys.add(f"competitor_deep_dive::{competitor}")
            else:
                keys.add("competitor_deep_dives")
        else:
            keys.add("competitive_findings")
        keys.add("support")
    return keys


def recommendation_delta_problem(
    *,
    previous_recommendation: str,
    candidate_recommendation: str,
    scoped_competitors: set[str],
    scoped_dimensions: set[str],
    candidate_rationale: str,
) -> str | None:
    previous = _normalize(previous_recommendation)
    candidate = _normalize(candidate_recommendation)
    if not previous or not candidate or previous == candidate:
        return None
    changed_to_scoped_competitor = any(
        _contains_name(candidate, competitor) for competitor in scoped_competitors
    )
    rationale = _normalize(candidate_rationale)
    rationale_mentions_scope = any(
        _contains_name(rationale, competitor) for competitor in scoped_competitors
    ) and any(dimension in rationale for dimension in scoped_dimensions)
    if changed_to_scoped_competitor and rationale_mentions_scope:
        return None
    return (
        "recommendation changed outside scoped redo evidence; preserve previous "
        "recommendation or provide scoped new-evidence justification"
    )


def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def _contains_name(text: str, name: str) -> bool:
    normalized_name = _normalize(name)
    if not normalized_name:
        return False
    return bool(re.search(rf"(^|\\W){re.escape(normalized_name)}($|\\W)", text))
```

- [ ] **Step 4: Add structured snapshot fields to `RunRecord`**

In `backend/packages/orchestrator/service.py`, import typing-only type names:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from packages.agents.writer.structured_report import StructuredReport
```

Add these fields to `RunRecord`:

```python
    structured_report_snapshot: "StructuredReport | None" = None
    previous_structured_report_snapshot: "StructuredReport | None" = None
```

Use string annotations so runtime imports do not create a circular dependency.

- [ ] **Step 5: Use scoped snapshot merge and recommendation guard in writer**

In `backend/packages/agents/writer/logic.py`, import:

```python
from packages.agents.writer.structured_repair import (
    recommendation_delta_problem,
    scoped_structured_section_keys,
)
```

After `structured_report = assembly.report` and before validation, add:

```python
                        structured_report = self._merge_scoped_structured_redo(
                            record,
                            candidate=structured_report,
                            previous=getattr(record, "structured_report_snapshot", None),
                            previous_report=previous_report,
                        )
```

Add this method to `WriterAgentMixin` near other structured writer helpers:

```python
    def _merge_scoped_structured_redo(
        self,
        record: RunRecord,
        *,
        candidate: StructuredReport,
        previous: StructuredReport | None,
        previous_report: str,
    ) -> StructuredReport:
        pending = record.pending_graph_redo
        if pending is None or previous is None:
            return candidate
        affected = scoped_structured_section_keys(pending.redo_scopes)
        if not affected:
            return candidate
        merged = previous.model_copy(deep=True)
        if "user_review_themes" in affected:
            merged.core.user_review_themes = candidate.core.user_review_themes
        if "decision_matrix" in affected:
            merged.core.decision_matrix = candidate.core.decision_matrix
        if "support" in affected:
            merged.support = candidate.support
        deep_dives = {item.competitor: item for item in merged.core.competitor_deep_dives}
        for item in candidate.core.competitor_deep_dives:
            if f"competitor_deep_dive::{item.competitor}" in affected:
                deep_dives[item.competitor] = item
        merged.core.competitor_deep_dives = [
            deep_dives.get(competitor, item)
            for competitor, item in zip(
                previous.competitors,
                previous.core.competitor_deep_dives,
                strict=False,
            )
        ]
        return merged
```

After publication contract passes and before assigning `report_md = rendered`, set:

```python
                        record.previous_structured_report_snapshot = getattr(
                            record,
                            "structured_report_snapshot",
                            None,
                        )
                        record.structured_report_snapshot = structured_report
```

Add a recommendation guard before accepting rendered output:

```python
                        pending = record.pending_graph_redo
                        if pending is not None and previous_report.strip():
                            scoped_competitors = {
                                scope.target_competitor
                                for scope in pending.redo_scopes
                                if scope.target_competitor
                            }
                            scoped_dimensions = {
                                scope.target_subagent
                                for scope in pending.redo_scopes
                                if scope.target_subagent
                            }
                            problem = recommendation_delta_problem(
                                previous_recommendation=_extract_markdown_recommendation(previous_report),
                                candidate_recommendation=structured_report.core.executive_summary.recommendation.text,
                                scoped_competitors=scoped_competitors,
                                scoped_dimensions=scoped_dimensions,
                                candidate_rationale=structured_report.core.executive_summary.risk_adjusted_rationale.text,
                            )
                            if problem:
                                anti_regression_reason = problem
                                detail.report_md = self._preserve_hardened_previous_report(
                                    detail,
                                    previous_report,
                                )
                                writer_mode = "preserved previous report after recommendation delta guard"
                                report_md = detail.report_md
                                raise RuntimeError(problem)
```

Add `_extract_markdown_recommendation()` as a module helper:

```python
def _extract_markdown_recommendation(markdown: str) -> str:
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped.startswith("-"):
            continue
        if "推荐" in stripped or "recommend" in stripped.casefold():
            return stripped
    return ""
```

If raising would enter the fail-closed branch and overwrite preservation, implement this guard as an explicit preservation branch instead of raising. The final behavior must be: no Markdown fallback, previous report preserved, event emitted with the recommendation-delta reason.

- [ ] **Step 6: Add run-service recommendation drift test**

In `backend/tests/unit/test_run_service.py`, add:

```python
def test_real_schema_first_scoped_redo_preserves_previous_report_on_unjustified_recommendation_delta(
    monkeypatch,
) -> None:
    service = _segmented_writer_service()
    service._settings = replace(
        service._settings,
        writer_structured_report_enabled=True,
        writer_timeout_seconds=10,
    )
    record = _segmented_writer_record(service, competitors=["Claude Code", "Cursor", "Windsurf"])
    record.detail.execution_mode = "real"
    record.detail.output_language = "zh-CN"
    record.detail.raw_sources = _structured_writer_raw_sources()
    record.detail.report_md = (
        "## 执行摘要\n"
        "- 推荐决策: GitHub Copilot 与 Cursor 是风险调整后的主力选择。[source:raw-source-a]\n"
    )
    _attach_structured_writer_redo(record)

    candidate = _structured_writer_fixture_report(record.detail)
    candidate.core.executive_summary.recommendation.text = (
        "Windsurf is the primary recommendation."
    )
    candidate.core.executive_summary.risk_adjusted_rationale.text = (
        "Windsurf has broad feature coverage."
    )

    async def fake_structured_report(self, record, evidence_pack_result, timeout_seconds):
        return candidate

    monkeypatch.setattr(
        "packages.agents.writer.logic.WriterAgentMixin._writer_structured_report",
        fake_structured_report,
    )

    asyncio.run(service._real_writer_step(record))

    assert "GitHub Copilot 与 Cursor" in record.detail.report_md
    assert "Windsurf is the primary recommendation" not in record.detail.report_md
    assert any(
        event.type == "writer_schema_first_failed_closed"
        or event.type == "writer_structured_repair_failed_preserved_previous"
        for event in record.events
    )
```

- [ ] **Step 7: Run repair and run-service tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_writer_structured_repair.py backend/tests/unit/test_run_service.py::test_real_schema_first_scoped_redo_preserves_previous_report_on_unjustified_recommendation_delta -q
```

Expected: all selected tests pass.

- [ ] **Step 8: Commit**

```powershell
git add backend/packages/agents/writer/structured_repair.py backend/packages/agents/writer/logic.py backend/packages/orchestrator/service.py backend/tests/unit/test_writer_structured_repair.py backend/tests/unit/test_run_service.py
git commit -m "feat: guard scoped schema-first redo recommendations"
```

---

### Task 5: Unified Final Quality Result And Revision Accounting

**Files:**
- Create: `backend/packages/quality/final_result.py`
- Modify: `backend/packages/quality/__init__.py`
- Modify: `backend/packages/orchestrator/service.py`
- Test: `backend/tests/unit/test_quality_findings.py`
- Test: `backend/tests/unit/test_run_service.py`

- [ ] **Step 1: Add pure final quality result tests**

Append to `backend/tests/unit/test_quality_findings.py`:

```python
from packages.quality.final_result import build_final_quality_result


def test_final_quality_result_includes_release_gate_warnings_when_deterministic_qa_is_clean() -> None:
    result = build_final_quality_result(
        deterministic_findings=[],
        release_gate_findings=[_qc_issue("release_gate.claim_self_consistency_required", severity="warn")],
        readiness_score=88,
    )

    assert result.issue_count == 1
    assert result.warn_count == 1
    assert result.blocker_count == 0
    assert result.quality_status == "completed_with_warnings"
    assert result.revision_issue_count_after == 1


def test_final_quality_result_marks_clean_when_no_findings() -> None:
    result = build_final_quality_result(
        deterministic_findings=[],
        release_gate_findings=[],
        readiness_score=100,
    )

    assert result.issue_count == 0
    assert result.warn_count == 0
    assert result.quality_status == "clean_pass"
```

If `_qc_issue` in this file has a different signature, add a local helper:

```python
def _qc_issue(field_path: str, severity: str = "warn") -> QCIssue:
    return QCIssue(
        id=f"qc-{field_path}",
        severity=severity,
        detected_by="coverage",
        target_agent="writer",
        field_path=field_path,
        problem=field_path,
        redo_scope=RedoScope(kind="writer_only", rationale=field_path),
    )
```

- [ ] **Step 2: Run failing pure tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_quality_findings.py::test_final_quality_result_includes_release_gate_warnings_when_deterministic_qa_is_clean backend/tests/unit/test_quality_findings.py::test_final_quality_result_marks_clean_when_no_findings -q
```

Expected: import fails because `packages.quality.final_result` does not exist.

- [ ] **Step 3: Implement final quality result module**

Create `backend/packages/quality/final_result.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence

from packages.schema.models import QCIssue


@dataclass(frozen=True)
class FinalQualityResult:
    findings: list[QCIssue]
    blocker_count: int
    warn_count: int
    issue_count: int
    quality_status: str
    readiness_score: int | None
    revision_issue_count_after: int
    revision_convergence_ratio: float

    def telemetry_payload(self) -> dict[str, object]:
        return {
            "blocker_count": self.blocker_count,
            "warn_count": self.warn_count,
            "issue_count": self.issue_count,
            "quality_status": self.quality_status,
            "readiness_score": self.readiness_score,
            "revision_issue_count_after": self.revision_issue_count_after,
            "revision_convergence_ratio": self.revision_convergence_ratio,
        }


def build_final_quality_result(
    *,
    deterministic_findings: Sequence[QCIssue],
    release_gate_findings: Sequence[QCIssue],
    readiness_score: int | None,
    issue_count_before: int = 0,
) -> FinalQualityResult:
    findings = _dedupe_findings([*deterministic_findings, *release_gate_findings])
    blocker_count = sum(1 for finding in findings if finding.severity == "blocker")
    warn_count = sum(1 for finding in findings if finding.severity == "warn")
    issue_count = len(findings)
    if blocker_count:
        quality_status = "completed_with_blockers"
    elif warn_count:
        quality_status = "completed_with_warnings"
    else:
        quality_status = "clean_pass"
    return FinalQualityResult(
        findings=findings,
        blocker_count=blocker_count,
        warn_count=warn_count,
        issue_count=issue_count,
        quality_status=quality_status,
        readiness_score=readiness_score,
        revision_issue_count_after=issue_count,
        revision_convergence_ratio=round(issue_count / max(1, issue_count_before), 3),
    )


def _dedupe_findings(findings: list[QCIssue]) -> list[QCIssue]:
    seen: set[str] = set()
    deduped: list[QCIssue] = []
    for finding in findings:
        if finding.id in seen:
            continue
        seen.add(finding.id)
        deduped.append(finding)
    return deduped
```

Export it from `backend/packages/quality/__init__.py`:

```python
from packages.quality.final_result import FinalQualityResult, build_final_quality_result
```

Add both names to `__all__`.

- [ ] **Step 4: Add run-service event/detail consistency test**

In `backend/tests/unit/test_run_service.py`, add:

```python
@pytest.mark.asyncio
async def test_release_gate_sync_records_unified_quality_result_event_and_revision_counts() -> None:
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
    detail = await service.create_run(
        RunCreateRequest(
            topic="Unified quality result",
            competitors=["Claude"],
            dimensions=["pricing"],
            execution_mode="real",
        )
    )
    record = service._runs[detail.id]
    record.detail.report_md = "After redo. [source:pricing-1]"
    record.detail.revisions = [
        RevisionRecord(
            id="revision-1",
            iteration=1,
            stage="writer",
            before_md="Before redo.",
            after_md=record.detail.report_md,
            issue_count_before=1,
            issue_count_after=0,
            convergence_ratio=0.0,
        )
    ]

    service._sync_release_gate_repair_issues(record, _blocked_release_gate())

    assert len(record.detail.qa_findings) == 1
    assert record.detail.revisions[-1].issue_count_after == 1
    assert record.detail.revisions[-1].convergence_ratio == 1.0
    assert any(
        event.type == "writer_unified_quality_result_recorded"
        for event in record.events
    )
```

- [ ] **Step 5: Integrate final quality result into release-gate sync**

In `backend/packages/orchestrator/service.py`, import:

```python
from packages.quality import build_final_quality_result
```

At the end of `_sync_release_gate_repair_issues()`, after `detail.qa_findings = [*retained, *release_issues]`, compute:

```python
        readiness_score = gate.readiness.score if gate is not None else None
        final_quality = build_final_quality_result(
            deterministic_findings=retained,
            release_gate_findings=release_issues,
            readiness_score=readiness_score,
            issue_count_before=detail.revisions[-1].issue_count_before
            if detail.revisions
            else len(detail.qa_findings),
        )
        detail.qa_findings = final_quality.findings
```

Then refresh metrics and revision counts from `final_quality`:

```python
        self._refresh_quality_metrics(detail)
        self._sync_latest_revision_issue_count(detail)
```

Add this import near existing observability imports in `backend/packages/orchestrator/service.py`:

```python
from packages.observability.tracing import build_run_event
```

Add this synchronous helper near `_sync_latest_revision_issue_count()`:

```python
    def _record_unified_quality_result_event(
        self,
        record: RunRecord,
        final_quality: FinalQualityResult,
    ) -> None:
        event = build_run_event(
            event_id=len(record.events) + 1,
            run_id=record.detail.id,
            event_type="writer_unified_quality_result_recorded",
            agent="quality",
            subagent=None,
            message="Unified final quality result recorded.",
            payload=final_quality.telemetry_payload(),
        )
        record.events.append(event)
```

Call the helper after `_sync_latest_revision_issue_count(detail)`:

```python
        self._record_unified_quality_result_event(record, final_quality)
```

- [ ] **Step 6: Ensure `revision_recorded` event is emitted after release-gate sync for graph redo**

Move `_record_pending_graph_redo(record)` in the graph path so it runs after final release-gate sync, or re-emit a `revision_recorded` update event after `_sync_latest_revision_issue_count()` updates the latest revision.

The accepted behavior is:

```python
assert record.detail.revisions[-1].issue_count_after == event.payload["revision"]["issue_count_after"]
assert record.detail.revisions[-1].convergence_ratio == event.payload["revision"]["convergence_ratio"]
```

Use the smallest code path that makes this true for real graph redo without changing historical event storage for old runs.

- [ ] **Step 7: Run quality and run-service tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_quality_findings.py backend/tests/unit/test_run_service.py::test_release_gate_sync_records_unified_quality_result_event_and_revision_counts backend/tests/unit/test_run_service.py::test_release_gate_sync_updates_latest_revision_after_issue_count -q
```

Expected: selected tests pass.

- [ ] **Step 8: Commit**

```powershell
git add backend/packages/quality/final_result.py backend/packages/quality/__init__.py backend/packages/orchestrator/service.py backend/tests/unit/test_quality_findings.py backend/tests/unit/test_run_service.py
git commit -m "feat: unify final report quality accounting"
```

---

### Task 6: Structured Writer Regression Suite

**Files:**
- Modify: `backend/tests/unit/test_run_service.py`
- Modify: `backend/tests/unit/test_writer_publication_contract.py`
- Modify: `backend/tests/unit/test_writer_structured_renderer.py`
- Modify: `backend/tests/unit/test_writer_structured_validation.py`

- [ ] **Step 1: Add a regression test that real schema-first runs never emit Markdown fallback**

In `backend/tests/unit/test_run_service.py`, add:

```python
def test_real_schema_first_success_does_not_emit_markdown_fallback(monkeypatch) -> None:
    service = _segmented_writer_service()
    service._settings = replace(
        service._settings,
        writer_structured_report_enabled=True,
        writer_timeout_seconds=10,
    )
    record = _segmented_writer_record(service, competitors=["Cursor", "Windsurf"])
    record.detail.execution_mode = "real"
    record.detail.output_language = "zh-CN"
    record.detail.raw_sources = _structured_writer_raw_sources()
    structured_report = _structured_report_fixture(competitors=["Cursor", "Windsurf"])

    async def fake_structured_report(self, record, evidence_pack_result, timeout_seconds):
        return structured_report

    async def fail_if_markdown_writer_called(self, record, evidence_pack_result, timeout_seconds):
        raise AssertionError("Markdown fallback must not be called")

    monkeypatch.setattr(
        "packages.agents.writer.logic.WriterAgentMixin._writer_structured_report",
        fake_structured_report,
    )
    monkeypatch.setattr(
        "packages.agents.writer.logic.WriterAgentMixin._writer_markdown_report_from_evidence_pack",
        fail_if_markdown_writer_called,
    )

    asyncio.run(service._real_writer_step(record))

    event_types = [event.type for event in record.events]
    assert "writer_markdown_fallback_used" not in event_types
    assert "writer_structured_report_validated" in event_types
    assert "writer_publication_contract_validated" in event_types
```

- [ ] **Step 2: Add renderer assertions for section markers and Chinese headings**

In `backend/tests/unit/test_writer_structured_renderer.py`, add:

```python
def test_renderer_section_marker_lines_do_not_carry_citations() -> None:
    rendered = render_structured_report(_report("zh-CN"))

    marker_lines = [
        line for line in rendered.splitlines() if line.startswith("<!-- report-section:")
    ]

    assert marker_lines
    assert all("[source:" not in line for line in marker_lines)


def test_renderer_zh_structural_headings_are_localized() -> None:
    rendered = render_structured_report(_report("zh-CN"))

    assert "## 执行摘要" in rendered
    assert "Direct User / Community Signals" not in rendered
    assert "Pricing and Packaging" not in rendered
```

- [ ] **Step 3: Add structured validation assertion for template executive summary**

Add this test to `backend/tests/unit/test_writer_structured_validation.py`:

```python
def test_structured_validation_rejects_template_only_executive_summary() -> None:
    report = _report()
    report.core.executive_summary.recommendation.text = "core conclusion"

    result = validate_structured_report(
        report,
        allowed_source_ids={"raw-source-a"},
        strong_source_ids={"raw-source-a"},
    )

    assert not result.passed
    assert "executive_summary_template_only" in result.issue_codes()
```

- [ ] **Step 4: Run regression suite**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_writer_publication_contract.py backend/tests/unit/test_writer_structured_renderer.py backend/tests/unit/test_writer_structured_validation.py backend/tests/unit/test_writer_structured_generation.py backend/tests/unit/test_run_service.py -k "schema_first or structured or publication_contract or unified_quality or release_gate_sync_updates_latest_revision" -q
```

Expected: selected tests pass. If unrelated failures appear in the broad `test_run_service.py` selection, rerun the exact failing tests and separate unrelated pre-existing failures from this feature's failures.

- [ ] **Step 5: Commit**

```powershell
git add backend/tests/unit/test_run_service.py backend/tests/unit/test_writer_publication_contract.py backend/tests/unit/test_writer_structured_renderer.py backend/tests/unit/test_writer_structured_validation.py
git commit -m "test: cover schema-first writer hardening regressions"
```

---

### Task 7: Focused Backend Verification

**Files:**
- No source edits unless tests reveal a feature-owned failure.

- [ ] **Step 1: Run focused writer tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_writer_structured_report.py backend/tests/unit/test_writer_structured_renderer.py backend/tests/unit/test_writer_structured_validation.py backend/tests/unit/test_writer_publication_contract.py backend/tests/unit/test_writer_structured_generation.py backend/tests/unit/test_writer_structured_repair.py backend/tests/unit/test_writer_repair.py -q
```

Expected: all listed writer tests pass.

- [ ] **Step 2: Run focused run-service quality tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_run_service.py -k "schema_first or structured or release_gate_sync or convergence_ratio or scoped_redo" -q
```

Expected: all selected tests pass.

- [ ] **Step 3: Run quality tests**

Run:

```powershell
D:\Anaconda\envs\bd-competiscope-v2\python.exe -m pytest backend/tests/unit/test_quality_findings.py backend/tests/unit/test_report_quality.py -k "release_gate or quality_result or qa_findings or warnings" -q
```

Expected: all selected tests pass.

- [ ] **Step 4: Commit any test-driven fixes**

If Task 7 required code changes, list the exact touched files with `git status --short`, then stage only those feature-owned paths. The commit command must name each file explicitly:

```powershell
git status --short
git add backend/packages/agents/writer/logic.py backend/tests/unit/test_run_service.py
git commit -m "fix: stabilize schema-first writer hardening tests"
```

Use the `git add` command above only when those two paths are the actual touched paths. If different feature-owned paths changed, replace the paths in the command with the exact files shown by `git status --short`. If no changes were needed, do not create an empty commit.

---

### Task 8: Restart Services And Run One Real Report

**Files:**
- Do not edit source files in this task unless the real run reveals a feature-owned issue.
- Do not commit run DBs, logs, or generated reports.

- [ ] **Step 1: Record service commands currently used by the repo**

Inspect `README.md`, `Makefile`, `docker-compose.yml`, and existing runtime logs:

```powershell
rg -n "uvicorn|vite|pnpm|npm|conda|backend|frontend|5173|8000" README.md Makefile docker-compose.yml docs -S
```

Use the existing project commands. Do not invent a new startup path if the repo already has one.

- [ ] **Step 2: Stop existing backend/frontend processes**

Find existing local dev processes:

```powershell
Get-Process | Where-Object { $_.ProcessName -match 'python|node|uvicorn|vite' } | Select-Object Id,ProcessName,Path,CommandLine
```

Stop only processes clearly serving this repository's backend or frontend. Do not kill unrelated Python or Node processes.

- [ ] **Step 3: Start backend with conda Python**

Use the command discovered in Step 1. If the repo's standard command does not start the backend, start from `backend` with conda Python and record the exact command in the final audit.

Example fallback command:

```powershell
Start-Process -WindowStyle Hidden -FilePath "D:\Anaconda\envs\bd-competiscope-v2\python.exe" -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000" -WorkingDirectory "D:\codex_workspace\plan_a\backend"
```

- [ ] **Step 4: Start frontend**

Use the repo's existing frontend command. If the repo uses pnpm:

```powershell
Start-Process -WindowStyle Hidden -FilePath "pnpm" -ArgumentList "dev", "--host", "127.0.0.1" -WorkingDirectory "D:\codex_workspace\plan_a\frontend"
```

Use another port only if the existing frontend port is occupied.

- [ ] **Step 5: Confirm health**

Check backend and frontend:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
Invoke-WebRequest http://127.0.0.1:5173 -UseBasicParsing | Select-Object StatusCode
```

If endpoint paths differ, use the actual paths exposed by the current app.

- [ ] **Step 6: Start one real run**

Use the existing API shape from frontend/network logs or OpenAPI. The run must be real mode, topic `AI Coding Agent`, output language `zh-CN`, competitors `Claude Code`, `Cursor`, `GitHub Copilot`, `Windsurf`, dimensions `pricing`, `feature`, `persona`.

Record the returned run id in `$runId` immediately. Example API shape if no more specific current OpenAPI request is discovered:

```powershell
$created = Invoke-RestMethod -Method Post -ContentType "application/json" -Uri "http://127.0.0.1:8000/api/runs" -Body (@{
  topic = "AI Coding Agent"
  competitors = @("Claude Code", "Cursor", "GitHub Copilot", "Windsurf")
  dimensions = @("pricing", "feature", "persona")
  execution_mode = "real"
  output_language = "zh-CN"
} | ConvertTo-Json -Depth 6)
$runId = $created.id
$runId
```

- [ ] **Step 7: Wait for completion**

Poll the run endpoint until status is terminal:

```powershell
while ($true) {
  $run = Invoke-RestMethod "http://127.0.0.1:8000/api/runs/$runId"
  "{0} {1}" -f (Get-Date), $run.status
  if ($run.status -in @("completed", "completed_with_blockers", "failed")) { break }
  Start-Sleep -Seconds 20
}
```

- [ ] **Step 8: Audit the real run**

Use SQLite/API inspection. Verify:

- No `writer_markdown_fallback_used` event appears for this real schema-first run.
- `writer_structured_section_started` and `writer_structured_section_completed` appear.
- If any structured section fails, `writer_structured_section_failed` and fail-closed/preservation events appear.
- `revision_recorded` event issue counts match final `detail.revisions[-1]`.
- Deterministic QA and release-gate warnings are both reflected in final `qa_findings`.
- Report body has no citations on section marker lines.
- Report body has no citations in headings.
- Report body has no citations in table headers.
- Chinese report has localized structural H2/H3/H4 headings.
- No internal terms such as `source_registry`, `allowed_source_ids`, `Segment Evidence Pack`, `fact:`, or `signal:` appear.
- Executive summary is a real recommendation, not a one-line system description.
- Battlecard is competitor-specific, not a template explaining what a battlecard should contain.

- [ ] **Step 9: Fix only feature-owned real-run failures**

If the run reveals a feature-owned failure, return to the smallest relevant task above, write a failing unit test for the observed shape, fix it, run focused tests, commit, restart services, and run a new real run.

Do not mark the objective complete until a real run passes the audit in Step 8.

---

## Final Completion Checklist

Before claiming completion, verify all items below with current evidence:

- [ ] Spec file exists and is committed: `docs/superpowers/specs/2026-06-20-schema-first-writer-main-path-hardening-design.md`
- [ ] This implementation plan exists and is committed.
- [ ] Real schema-first writer path cannot silently fall back to Markdown.
- [ ] Legacy/flag-disabled Markdown path still works.
- [ ] Structured section failures emit typed events.
- [ ] Scoped redo cannot accept unjustified recommendation drift.
- [ ] Final quality result includes release-gate warnings.
- [ ] Revision detail and revision events agree on post-redo issue counts.
- [ ] Publication contract catches marker-line citations.
- [ ] Focused writer/run-service/quality tests pass in the conda environment.
- [ ] Backend and frontend were restarted from the current branch.
- [ ] One new real run was executed after restart.
- [ ] The real run was audited for trace, redo behavior, final quality result, and report body quality.
- [ ] No generated artifacts, DB packages, logs, zips, Word docs, or report outputs were committed.
